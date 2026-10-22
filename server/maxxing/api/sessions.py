"""Sessions + uploads. See docs/dev/API.md#sessions."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import media, security, streamcap
from .. import uploads as upload_limits
from ..security import require_auth
from ..sessions import costfix, service
from ..sessions.service import SessionError

router = APIRouter(prefix="/api", tags=["sessions"], dependencies=[Depends(require_auth)])

HEARTBEAT_S = 15.0
POLL_RUNNING_S = 0.1           # a running session's log is checked this often (a stat): new events show ~0.05 s after
POLL_IDLE_S = 1.0
POLL_QUIET_S = 0.25            # a running session silent for QUIET_AFTER_S (thinking, a long tool) is checked less often
QUIET_AFTER_S = 3.0


class CreateIn(BaseModel):
    path: str = ""
    message: str | None = None
    title: str | None = None
    model: str | None = None
    attachments: list[str] = Field(default_factory=list)
    plan_mode: bool = False
    voice: str | None = None          # absolute path of a voice message sent directly (transcribed afterwards)


class PatchIn(BaseModel):
    title: str | None = None
    model: str | None = None
    archived: bool | None = None
    notify: bool | None = None
    favorite: bool | None = None
    path: str | None = None           # move to another topic (idle sessions only)
    plan_mode: bool | None = None


class AskIn(BaseModel):
    question: str = ""


class ApproveIn(BaseModel):
    text: str = ""      # what the conversation shows (the client's language), e.g. "Plan validated - go ahead."


class HideIn(BaseModel):
    at: float
    hidden: bool = True


class MessageIn(BaseModel):
    text: str = ""
    attachments: list[str] = Field(default_factory=list)
    hud: bool = False  # sent from the HUD: Claude is told to answer short and may annotate the screen capture
    voice: str | None = None  # absolute path of a voice message sent directly: transcribed on the server, then sent


async def _call(fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    """Run a blocking service call in a thread, mapping SessionError to HTTP errors."""
    try:
        return await asyncio.to_thread(fn, *args, **kw)
    except SessionError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


def _found(s: dict | None) -> dict:
    if s is None:
        raise HTTPException(404, detail={"error": "not_found", "message": "Session not found"})
    return s


async def startup() -> None:
    service.start_watcher()
    costfix.start_background()   # one-time repair of costs counted before 2.0.0a32


async def shutdown() -> None:
    await service.stop_watcher()


# ---- collection ----------------------------------------------------------------------------
@router.get("/sessions")
async def list_sessions(path: str | None = None, archived: int | None = Query(None, ge=0, le=1)):
    arch = None if archived is None else bool(archived)
    # Plain JSON data: a JSONResponse skips FastAPI's jsonable_encoder walk (~11 ms for 300 sessions), same body.
    return JSONResponse(await _call(service.list_sessions, path.strip("/") if path is not None else None, arch))


@router.post("/sessions")
async def create_session(body: CreateIn):
    return await _call(service.create_session, body.path, message=body.message, title=body.title,
                       model=body.model, attachments=body.attachments, source="web",
                       plan_mode=body.plan_mode, voice_path=body.voice)


@router.get("/sessions/search")
async def search(q: str = ""):
    return await _call(service.search, q)


# ---- one session ---------------------------------------------------------------------------
@router.get("/sessions/{sid}")
async def get_session(sid: str):
    return _found(await _call(service.get_session, sid))


@router.patch("/sessions/{sid}")
async def patch_session(sid: str, body: PatchIn):
    return await _call(service.update_session, sid, title=body.title, model=body.model,
                       archived=body.archived, notify=body.notify, plan_mode=body.plan_mode,
                       favorite=body.favorite, path=body.path)


@router.post("/sessions/{sid}/ask")
async def ask_aside(sid: str, body: AskIn):
    """Side question: Claude answers about the session without interrupting it (nothing is saved)."""
    from ..sessions import aside
    return await _call(aside.ask, sid, body.question)


@router.post("/sessions/{sid}/plan/approve")
async def approve_plan(sid: str, body: ApproveIn):
    return await _call(service.approve_plan, sid, body.text)


@router.delete("/sessions/{sid}")
async def delete_session(sid: str):
    await _call(service.delete_session, sid)
    return {"ok": True}


@router.post("/sessions/{sid}/messages")
async def send_message(sid: str, body: MessageIn):
    return await _call(service.send_message, sid, body.text, body.attachments, "web", hud=body.hud,
                       voice_path=body.voice)


@router.post("/sessions/{sid}/queue/take")
async def take_queue(sid: str):
    return await _call(service.take_queue, sid)


@router.post("/sessions/{sid}/hide")
async def hide_message(sid: str, body: HideIn):
    await _call(service.hide_message, sid, body.at, body.hidden)
    return {"ok": True}


@router.post("/sessions/{sid}/steer")
async def steer(sid: str):
    return await _call(service.steer, sid)


@router.delete("/sessions/{sid}/queue")
async def clear_queue(sid: str):
    await _call(service.clear_queue, sid)
    return {"ok": True}


@router.post("/sessions/{sid}/stop")
async def stop(sid: str):
    await _call(service.stop, sid)
    return {"ok": True}


@router.post("/sessions/{sid}/compact")
async def compact(sid: str):
    await _call(service.compact, sid)
    return {"ok": True}


@router.post("/sessions/{sid}/handoff")
async def handoff(sid: str):
    return await _call(service.handoff, sid)


@router.post("/sessions/{sid}/seen")
async def seen(sid: str):
    await _call(service.mark_seen, sid)
    return {"ok": True}


@router.get("/sessions/{sid}/events")
async def events(sid: str, from_: int | None = Query(None, alias="from", ge=0),
                 tail: int | None = Query(None, ge=1, le=5000), before: int | None = Query(None, ge=0),
                 limit: int = Query(200, ge=1, le=5000)):
    """Forward (`from`), last events (`tail`) or backward paging (`before` + `limit`)."""
    if tail is not None or before is not None:
        page = await _call(service.read_back, sid, before, tail if tail is not None else limit)
        s = _found(await _call(service.get_session, sid))
        if page.get("reset"):
            return {"events": [], "reset": True, "state": s["state"]}
        media.warm_events(page.get("events") or [])
        return JSONResponse({**page, "state": s["state"]})
    from_ = from_ or 0
    if not await asyncio.to_thread(service.offset_valid, sid, from_):
        s = _found(await _call(service.get_session, sid))
        return {"events": [], "next": from_, "state": s["state"], "more": False, "reset": True}
    evs, nxt = await _call(service.read_events, sid, from_)
    s = _found(await _call(service.get_session, sid))
    more = await asyncio.to_thread(service.has_more, sid, nxt)
    return JSONResponse({"events": evs, "next": nxt, "state": s["state"], "more": more})


@router.get("/sessions/{sid}/stream")
async def stream(sid: str, request: Request, from_: int = Query(0, alias="from", ge=0)):
    _found(await _call(service.get_session, sid))
    return streamcap.stream_response(request.cookies.get(security.COOKIE), lambda: _sse(sid, from_, request),
                                     media_type="text/event-stream",
                                     headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _frame(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _probe(sid: str) -> tuple[tuple[int, int] | None, tuple[int, int, int] | None]:
    return service.log_ident(sid), service.meta_ident(sid)


def _read_tick(sid: str, offset: int | None, session: bool) -> tuple[list[dict], int | None, bool, dict | None]:
    """New events from `offset` (None = the log did not grow), whether more are waiting, and the Session (when
    asked). Raises SessionError when the session is gone."""
    evs, nxt, more = [], offset, False
    if offset is not None:
        evs, nxt = service.read_events(sid, offset)
        more = bool(evs) and service.has_more(sid, nxt)
    return evs, nxt, more, (service.get_session(sid) if session else None)


async def _sse(sid: str, offset: int, request: Request) -> AsyncIterator[str]:
    """Tail the raw log: `events` frames as lines arrive, `state` frames when the Session changes,
    `reset` (then end of stream) when the log was rewritten under us: the client reloads the tail.
    A quiet tick is one stat of the log and of the meta file; events and the Session are only read when
    they changed (a running Session is re-read at least every POLL_IDLE_S: a dead runner is repaired there)."""
    auth = security.StreamAuth(request.cookies.get(security.COOKIE))
    yield "retry: 3000\n\n"
    last_state = ""
    last_out = time.monotonic()
    if not await asyncio.to_thread(service.offset_valid, sid, offset):
        yield _frame("reset", {})                      # the client's offset belongs to an older log
        return
    ident = await asyncio.to_thread(service.log_ident, sid)
    s: dict | None = None
    seen_meta: tuple[int, int, int] | None = None      # meta file stat when `s` was read
    read_at = 0.0
    changed_at = time.monotonic()                      # last new event or state frame
    while True:
        if await request.is_disconnected():
            return
        if not auth.ok():                              # signed out / password changed / expired: close
            return
        cur, meta = _probe(sid)                         # two stat() calls: cheaper inline than a thread hop per tick
        if ident and cur and (cur[0] != ident[0] or cur[1] < offset):
            yield _frame("reset", {})                  # log rewritten (compact-logs) or shrunk
            return
        ident = cur or ident
        if meta is None:
            yield _frame("state", None)                # deleted
            return
        grew = cur is not None and cur[1] > offset
        stale = s is None or meta != seen_meta or (
            s["state"] == "running" and time.monotonic() - read_at >= POLL_IDLE_S)
        evs: list[dict] = []
        more = False
        if grew or stale:
            try:
                evs, nxt, more, fresh = await asyncio.to_thread(_read_tick, sid, offset if grew else None, stale)
            except SessionError:
                yield _frame("state", None)
                return
            media.warm_events(evs)
            if nxt is not None and nxt != offset:
                offset = nxt
                if evs:
                    yield _frame("events", {"events": evs, "next": nxt})
                    last_out = changed_at = time.monotonic()
            if stale:
                if fresh is None:
                    yield _frame("state", None)
                    return
                s, seen_meta, read_at = fresh, meta, time.monotonic()
                sig = json.dumps(s, sort_keys=True)
                if sig != last_state:
                    last_state = sig
                    yield _frame("state", s)
                    last_out = changed_at = time.monotonic()
        if more:
            continue                                   # a long backlog: keep reading
        if time.monotonic() - last_out >= HEARTBEAT_S:
            yield ": ping\n\n"
            last_out = time.monotonic()
        if s and s["state"] == "running":
            await asyncio.sleep(POLL_RUNNING_S if time.monotonic() - changed_at < QUIET_AFTER_S else POLL_QUIET_S)
        else:
            await asyncio.sleep(POLL_IDLE_S)


# ---- uploads -------------------------------------------------------------------------------
_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_name(name: str) -> str:
    base = _SAFE.sub("_", Path(name or "file").name).strip(" .") or "file"
    return base[:120]


def unique_path(folder: Path, name: str) -> Path:
    p = folder / name
    stem, suf, n = p.stem, p.suffix, 1
    while p.exists():
        p = folder / f"{stem}-{n}{suf}"
        n += 1
    return p


def reserve_path(folder: Path, name: str) -> tuple[Path, int]:
    """Like unique_path, but creates the file exclusively (O_EXCL): two uploads with the same name at
    the same moment can never write into the same file. Returns (path, open fd)."""
    p = folder / name
    stem, suf, n = p.stem, p.suffix, 1
    while True:
        try:
            return p, os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            p = folder / f"{stem}-{n}{suf}"
            n += 1


def save_upload(up: UploadFile, folder: Path) -> dict:
    """Copy one spooled upload into `folder`: 413 over `upload_max_mb`, 507 when the copy would leave less
    than `upload_min_free_mb` free there (maxxing/uploads.py)."""
    size = up.size
    if size is None:
        try:
            size = os.fstat(up.file.fileno()).st_size
        except (OSError, AttributeError, ValueError):
            size = 0
    upload_limits.check_room(folder, size)
    max_b, _ = upload_limits.limits()
    dest, fd = reserve_path(folder, safe_name(up.filename or "file"))
    try:
        with os.fdopen(fd, "wb") as out:
            done = 0
            while chunk := up.file.read(1024 * 1024):
                done += len(chunk)
                if max_b and done > max_b:
                    raise upload_limits.too_large(max_b)
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)                    # no half-written file left behind
        raise
    return {"path": str(dest), "name": dest.name, "size": dest.stat().st_size,
            "mime": up.content_type or mimetypes.guess_type(dest.name)[0] or "application/octet-stream"}


@router.post("/uploads")
async def uploads(path: str = "", file: list[UploadFile] = File(...)):
    folder = await _call(service.uploads_dir, path.strip("/"))
    saved = [await asyncio.to_thread(save_upload, f, folder) for f in file]
    return {"files": saved}
