"""Routes other Harness servers call (Team, see maxxing/teampeer.py). Public: every request but /hello is signed
with the link key of a contact (or of a group). Nothing answers while Team is off."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .. import config, downloads, security, team, teampeer

log = logging.getLogger("maxxing.teampeer")

router = APIRouter(prefix="/api/team-peer", tags=["team-peer"])


def _on() -> None:
    if not config.load_config().get("team_page"):
        raise HTTPException(404, detail={"error": "not_found", "message": "Not found"})


async def _call(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except (teampeer.PeerError, team.TeamError) as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


async def _verify(request: Request, path: str, body: bytes = b"") -> tuple[str, str]:
    """Team on, and the request signed by a contact or a group member -> (sender, scope). The sender for the rate
    limits is the connection's address (uvicorn already takes it from the local proxy only), never an
    X-Forwarded-For header anyone can write."""
    _on()
    return await _call(teampeer.verify, request.method, path, dict(request.headers), body,
                       security.client_key(request))


def _json(raw: bytes) -> object:
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise HTTPException(400, detail={"error": "bad_request", "message": "JSON expected"}) from None


@router.post("/hello")
async def hello(request: Request):
    _on()
    body = _json(await request.body())
    return await _call(teampeer.hello, body if isinstance(body, dict) else {}, security.client_key(request))


@router.post("/inbox")
async def inbox(request: Request):
    raw = await request.body()
    frm, scope = await _verify(request, "/api/team-peer/inbox", raw)
    if not isinstance(event := _json(raw), dict):
        raise HTTPException(400, detail={"error": "bad_request", "message": "Object expected"})
    try:
        return await _call(teampeer.receive, frm, event, scope)
    except (TypeError, ValueError, AttributeError, OverflowError, KeyError) as e:   # a malformed event: refused for good
        log.info("team: malformed event from %s (%s)", frm, type(e).__name__)
        raise HTTPException(400, detail={"error": "bad_event", "message": "Malformed event"}) from None


@router.get("/files/{fid}")
async def file(fid: str, request: Request):
    frm, scope = await _verify(request, f"/api/team-peer/files/{fid}")
    f = await _call(teampeer.file_for, frm, fid, scope)
    return FileResponse(f["path"], media_type="application/octet-stream",
                        headers={"Content-Disposition": downloads.content_disposition(str(f["name"])),
                                 "X-Content-Type-Options": "nosniff"})


@router.get("/photo")
async def photo(request: Request):
    """Our profile photo, for a contact or a member of a shared group (see teampeer.photo_for)."""
    frm, scope = await _verify(request, "/api/team-peer/photo")
    path, mime = await _call(teampeer.photo_for, frm, scope)
    return FileResponse(path, media_type=mime, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
