"""Harness Browser (maxxing/browser): status, settings, the switch of a topic / an agent, start / stop, tabs,
`ask_human` answers, the live view, and the two loopback routes of a turn.

Signed in:
  GET  /api/browser                          feature, settings, what this server lacks, the browser (tabs...), asks
  PUT  /api/browser/settings                 the browser's settings (sites, sign-ins kept, asks, sleep...)
  POST /api/browser/setup                    install what is missing (root; runs in the background, see GET)
  GET  /api/browser/owner?path=              a topic / an agent: its switch, the tabs it sees, its requests
  PUT  /api/browser/owner                    {path, enabled}
  POST /api/browser/open                     {session?} start it for the person (its last tab; a session's tab)
  POST /api/browser/stop | forget | sleep    forget = sign-ins, tabs and journal erased; sleep = tabs asleep
  POST /api/browser/tabs                     {url?, scope?} a new tab (the person's: scope "me" by default)
  POST /api/browser/tabs/{key}/show          show it (wakes an asleep tab)
  PUT  /api/browser/tabs/{key}               {scope}   DELETE: close it
  GET  /api/browser/asks?session=&path=      pending `ask_human` requests
  POST /api/browser/asks/{id}                {action: done|skip, note?}
  POST /api/browser/live-token               -> {token} (30 s, one use) for WS /api/browser/live?t=
Loopback only (+ a secret): POST /api/browser/mcp/{sid} (Bearer = the turn's token), WS /api/browser/cdp/{slug}
(X-Browser-Secret = the secret of a turn's tools: chrome-devtools-mcp, seeing only that turn's tabs).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import shutil
import threading
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from .. import agents, browser, bus, config
from ..browser import asks, pool as pool_mod, replays, unit
from ..security import COOKIE, cookie_valid, require_auth
from .pc import _loopback

log = logging.getLogger("maxxing.api.browser")
router = APIRouter(prefix="/api/browser", tags=["browser"])
AUTH = [Depends(require_auth)]
LIVE_TOKEN_S = 30.0
MAX_INPUT = 8192
POLL_S = 2.0


def _err(e: browser.BrowserError | asks.AskError | agents.AgentError) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.code, "message": e.message})


def _owner(path: str) -> str:
    path = (path or "").strip().strip("/")
    owner = browser.owner_of(path)
    if not owner:
        raise HTTPException(400, detail={"error": "bad_path", "message": "A topic or an agent folder"})
    if owner.startswith("agent:") and not agents.exists(path):
        raise HTTPException(404, detail={"error": "not_found", "message": "No such agent"})
    if owner.startswith("topic:") and not (config.workspace() / path).is_dir():
        raise HTTPException(404, detail={"error": "not_found", "message": "No such topic"})
    return owner


# ---- setup (background) ------------------------------------------------------------------------------------------
_setup = {"running": False, "log": [], "error": None, "at": 0.0}


def _run_setup() -> None:
    def line(text: str) -> None:
        _setup["log"] = (_setup["log"] + [str(text)[:300]])[-40:]
    try:
        unit.setup(line)
        _setup["error"] = None
    except Exception as e:  # noqa: BLE001
        _setup["error"] = str(e)[:500]
        log.exception("browser setup")
    finally:
        _setup["running"] = False
        unit.available(fresh=True)
        bus.invalidate("browser")


# ---- signed in ---------------------------------------------------------------------------------------------------
@router.get("", dependencies=AUTH)
async def status() -> dict:
    p = pool_mod.pool()
    return {"feature": browser.feature_on(), "settings": browser.settings(),
            "available": await asyncio.to_thread(unit.available),
            "setup": {k: _setup[k] for k in ("running", "log", "error")},
            "browser": p.public(), "profile": (browser.profiles_dir() / browser.SLUG).is_dir(),
            "actions": await asyncio.to_thread(replays.actions, browser.SLUG, 30),
            "asks": await asyncio.to_thread(asks.pending)}


@router.put("/settings", dependencies=AUTH)
async def put_settings(body: dict) -> dict:
    try:
        out = await asyncio.to_thread(browser.set_settings, body)
    except browser.BrowserError as e:
        raise _err(e) from None
    bus.invalidate("browser", "settings")
    return out


@router.post("/setup", dependencies=AUTH)
async def setup() -> dict:
    if not _setup["running"]:
        _setup.update(running=True, log=[], error=None, at=time.time())
        threading.Thread(target=_run_setup, daemon=True, name="browser-setup").start()
    return {"running": True}


def _owner_view(owner: str) -> dict:
    p = pool_mod.pool()
    path = browser.owner_path(owner)
    return {"owner": owner, "path": path, "settings": browser.owner_settings(owner), "feature": browser.feature_on(),
            "scope": browser.scope_for(path), "running": p.public()["state"] == "running",
            "tabs": p.tabs_of(path), "asks": asks.pending(owner=owner)}


@router.get("/owner", dependencies=AUTH)
async def get_owner(path: str) -> dict:
    return await asyncio.to_thread(_owner_view, _owner(path))


class OwnerIn(BaseModel):
    path: str = Field(max_length=300)
    enabled: Optional[bool] = None
    settings: Optional[dict] = None          # older clients: {"enabled": ...}


@router.put("/owner", dependencies=AUTH)
async def put_owner(body: OwnerIn) -> dict:
    owner = _owner(body.path)
    path = browser.owner_path(owner)
    enabled = body.enabled if body.enabled is not None else (body.settings or {}).get("enabled")

    def save() -> None:
        block = browser.clean({"enabled": enabled} if enabled is not None else browser.owner_settings(owner),
                              strict=True)
        if owner.startswith("agent:"):
            agents.update(path, {"browser": block})
        else:
            from .. import workspace
            workspace.set_topic_browser(path, block)
    try:
        await asyncio.to_thread(save)
    except (browser.BrowserError, agents.AgentError) as e:
        raise _err(e) from None
    bus.invalidate("browser", "agents", "workspace")
    return await asyncio.to_thread(_owner_view, owner)


class OpenIn(BaseModel):
    session: Optional[str] = Field(default=None, max_length=100)


@router.post("/open", dependencies=AUTH)
async def open_browser(body: OpenIn) -> dict:
    p = pool_mod.pool()
    try:
        await p.open_for_person()
        if body.session:
            await p.focus_session(body.session)
    except browser.BrowserError as e:
        raise _err(e) from None
    return p.public()


@router.post("/stop", dependencies=AUTH)
async def stop_browser() -> dict:
    p = pool_mod.pool()
    await p.stop("stopped by the user")
    return p.public()


@router.post("/sleep", dependencies=AUTH)
async def sleep_tabs() -> dict:
    p = pool_mod.pool()
    n = await p.sleep_now()
    return {**p.public(), "slept": n}


@router.post("/forget", dependencies=AUTH)
async def forget() -> dict:
    """Sign-ins (the profile), the tabs and the journal of its actions are erased."""
    p = pool_mod.pool()
    await p.stop("forget")
    await asyncio.to_thread(shutil.rmtree, browser.profiles_dir() / browser.SLUG, True)
    for key in list(p.tabs.items):
        p.tabs.drop(key)
    await asyncio.to_thread(p.tabs.save)
    (browser.home() / "tabs.json").unlink(missing_ok=True)
    await asyncio.to_thread(replays.forget, browser.SLUG)
    bus.invalidate("browser")
    return p.public()


class TabIn(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2000)
    scope: Optional[str] = Field(default=None, max_length=300)


def _scope(raw: Optional[str]) -> str:
    if not raw:
        return browser.ME
    s = browser.clean_scope(raw)
    if not s:
        raise HTTPException(400, detail={"error": "bad_scope", "message": "me, topic:<topic folder> or "
                                                                         "project:<project folder>"})
    return s


@router.post("/tabs", dependencies=AUTH)
async def new_tab(body: TabIn) -> dict:
    p = pool_mod.pool()
    try:
        await p.new_tab((body.url or "").strip(), _scope(body.scope))
    except browser.BrowserError as e:
        raise _err(e) from None
    return p.public()


@router.post("/tabs/{key}/show", dependencies=AUTH)
async def show_tab(key: str) -> dict:
    p = pool_mod.pool()
    try:
        await p.wake(key)
    except browser.BrowserError as e:
        raise _err(e) from None
    return p.public()


@router.put("/tabs/{key}", dependencies=AUTH)
async def put_tab(key: str, body: TabIn) -> dict:
    p = pool_mod.pool()
    try:
        await p.set_scope(key, _scope(body.scope))
    except browser.BrowserError as e:
        raise _err(e) from None
    bus.invalidate("browser")
    return p.public()


@router.delete("/tabs/{key}", dependencies=AUTH)
async def close_tab(key: str) -> dict:
    p = pool_mod.pool()
    await p.close_tab(key)
    return p.public()


@router.get("/asks", dependencies=AUTH)
async def list_asks(session: Optional[str] = None, path: Optional[str] = None) -> dict:
    owner = _owner(path) if path else None
    return {"asks": await asyncio.to_thread(asks.pending, owner, session or None)}


class AnswerIn(BaseModel):
    action: Literal["done", "skip"]
    note: Optional[str] = Field(default=None, max_length=500)


async def _decide(rid: str, action: str, note: str = "") -> dict:
    """Answer a request; "done" gives Claude what the person did (pages, the page now, a picture of it)."""
    cur = await asyncio.to_thread(asks.get, rid)
    extra = await pool_mod.pool().hand_back(cur.get("session")) if cur and action == "done" else None
    return await asyncio.to_thread(asks.decide, rid, action, "web", note, extra)


@router.post("/asks/{rid}", dependencies=AUTH)
async def answer(rid: str, body: AnswerIn) -> dict:
    try:
        d = await _decide(rid, body.action, body.note or "")
    except asks.AskError as e:
        raise _err(e) from None
    await pool_mod.pool().release()                 # whoever had taken over hands back with the answer
    return d


# ---- live view -----------------------------------------------------------------------------------------------------
_live: dict[str, float] = {}


@router.post("/live-token", dependencies=AUTH)
async def live_token() -> dict:
    now = time.time()
    for k, at in list(_live.items()):
        if now - at > LIVE_TOKEN_S:
            _live.pop(k, None)
    t = secrets.token_urlsafe(24)
    _live[t] = now
    return {"token": t}


def _take_token(t: str) -> bool:
    at = _live.pop(t or "", None)
    return bool(at and time.time() - at <= LIVE_TOKEN_S)


@router.websocket("/live")
async def live(ws: WebSocket):
    """Pictures of the tab shown (binary JPEG) + the browser's state (text JSON) while it runs; the person's mouse and
    keyboard on the tab shown ({"t":"mouse"|"wheel"|"key"|"text"|"nav"|"back"|"forward"|"reload"}: the tab is theirs
    while they use it; {"t":"take"} / {"t":"release","done":bool,"note":...}).
    The signed-in cookie AND a live token (POST /live-token, CSRF-protected) are needed."""
    if not _take_token(ws.query_params.get("t", "")) or not cookie_valid(ws.cookies.get(COOKIE)):
        await ws.close(code=4403)
        return
    await ws.accept()
    p = pool_mod.pool()
    vid = id(ws)
    watched: list = [None]                  # the Browser being watched
    sent = {"state": ""}
    send_lock = asyncio.Lock()
    latest: list = [None]                   # the newest picture not sent yet (older ones are dropped)
    fresh = asyncio.Event()

    async def send_bytes(data: bytes) -> None:
        """Never waits for the network: a slow connection gets fewer pictures, never late ones."""
        latest[0] = data
        fresh.set()

    async def pump() -> None:
        while True:
            await fresh.wait()
            fresh.clear()
            data, latest[0] = latest[0], None
            if data:
                async with send_lock:
                    await ws.send_bytes(data)

    async def send_json(d: dict) -> None:
        async with send_lock:
            await ws.send_text(json.dumps(d, ensure_ascii=False))

    async def follow() -> None:
        """Attach to the browser when it (re)starts; push its state when it changes."""
        while True:
            b = p.b
            if b is not watched[0]:
                old = watched[0]
                if old is not None and old.watcher:
                    await old.watcher.unwatch(vid)
                watched[0] = b if b and b.state == "running" and b.watcher else None
                if watched[0] is not None:
                    await watched[0].watcher.watch(vid, send_bytes, ws.query_params.get("q", "high"))
            st = {"t": "state", "browser": p.public(), "me": bool(b and b.control and b.control["vid"] == vid),
                  "asks": await asyncio.to_thread(asks.pending)}
            text = json.dumps(st, sort_keys=True, default=str)
            if text != sent["state"]:
                sent["state"] = text
                await send_json(st)
            await asyncio.sleep(0.5 if b and b.state == "starting" else 1.0)

    task = asyncio.create_task(follow())
    pumping = asyncio.create_task(pump())
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > MAX_INPUT:
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            t = ev.get("t")
            b = p.b
            if t == "quality":
                if b and b.watcher:
                    await b.watcher.set_quality(vid, str(ev.get("q") or "high"))
            elif t == "size":
                if b and b.watcher and b.state == "running":
                    with contextlib.suppress(Exception):
                        await b.watcher.resize(ev.get("w"), ev.get("h"))
            elif t == "take":
                p.input(vid)
            elif t == "release":
                if ev.get("done") in (True, "done", "skip"):
                    action = "skip" if ev.get("done") == "skip" else "done"
                    for d in await asyncio.to_thread(asks.pending):
                        with contextlib.suppress(asks.AskError):
                            await _decide(d["id"], action, str(ev.get("note") or "")[:500])
                await p.release(vid)
            elif b and b.watcher and b.state == "running":
                if t in ("mouse", "wheel", "key", "text", "nav", "back", "forward", "reload") and \
                        not (t == "mouse" and ev.get("type") == "move" and not (b.control and b.control["vid"] == vid)):
                    p.input(vid)
                try:
                    why = await b.watcher.input(ev)
                except Exception as e:  # noqa: BLE001 - a page that went away
                    why = str(e)[:200]
                b.last_use = time.time()
                if why:
                    await send_json({"t": "error", "text": why})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for tk in (task, pumping):
            tk.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await tk
        b = watched[0]
        if b is not None and b.watcher:
            with contextlib.suppress(Exception):
                await b.watcher.unwatch(vid)
        await p.release(vid)          # its requests stay pending: the person may come back


# ---- loopback: a turn's tools, chrome-devtools-mcp's DevTools --------------------------------------------------------
@router.post("/mcp/{sid}")
async def mcp(sid: str, request: Request):
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not _loopback(request) or not replays.SID_RE.match(sid) or \
            not await asyncio.to_thread(pool_mod.check_turn, sid, token):
        return JSONResponse({"error": "forbidden", "message": "Not a running turn of this server"}, status_code=403)
    try:
        m = await request.json()
    except (ValueError, RecursionError):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
    if not isinstance(m, dict):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}})
    mid, method, params = m.get("id"), m.get("method"), m.get("params") or {}
    p = pool_mod.pool()
    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": {"tools": await p.tools()}})
    if method == "tools/call" and isinstance(params, dict):
        args = params.get("arguments")
        try:
            res = await p.call(sid, str(params.get("name") or ""), args if isinstance(args, dict) else {})
        except browser.BrowserError as e:
            res = pool_mod._error(e.message)
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": res})
    return JSONResponse({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}})


@router.websocket("/cdp/{slug}")
async def cdp(ws: WebSocket, slug: str):
    p = pool_mod.pool()
    found = p.by_secret(ws.headers.get("x-browser-secret", "")) if slug == browser.SLUG else None
    if not found or not _loopback(ws):
        await ws.close(code=4403)
        return
    b, turn = found
    await ws.accept()
    from ..browser import relay

    async def recv() -> str | None:
        try:
            return await ws.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            return None
    try:
        await relay.pump(b.run / "cdp.sock", b.ws_path, b.sites, recv, ws.send_text, view=p.view_for(b, turn),
                         wait_tab=lambda target: p.wait_tab(b, target))
    except Exception as e:  # noqa: BLE001
        log.info("browser devtools relay: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await ws.close()


# ---- watcher -------------------------------------------------------------------------------------------------------
_task: asyncio.Task | None = None


async def _watch() -> None:
    await asyncio.to_thread(asks.prime)
    while True:
        await asyncio.sleep(POLL_S)
        try:
            await asyncio.to_thread(asks.scan)
        except Exception:  # noqa: BLE001
            log.exception("browser asks watcher pass failed")


async def startup() -> None:
    global _task
    await asyncio.to_thread(unit.stop_all_units)        # browsers of a previous server run
    await asyncio.to_thread(pool_mod.clear_turns)
    pool_mod.pool().watch()
    _task = asyncio.get_running_loop().create_task(_watch())


async def shutdown() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
    with contextlib.suppress(Exception):
        await asyncio.wait_for(pool_mod.pool().stop_all(), 10)
