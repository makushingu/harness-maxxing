"""Routes other Harness servers call (Team, see maxxing/teampeer.py). Public: every request but /hello is signed
with the link key of a contact (or of a group). Nothing answers while Team is off."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from .. import config, team, teampeer

router = APIRouter(prefix="/api/team-peer", tags=["team-peer"])


def _on() -> None:
    if not config.load_config().get("team_page"):
        raise HTTPException(404, detail={"error": "not_found", "message": "Not found"})


def _ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else "?")


async def _call(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except teampeer.PeerError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None
    except team.TeamError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


@router.post("/hello")
async def hello(request: Request):
    _on()
    try:
        body = json.loads(await request.body())
    except ValueError:
        raise HTTPException(400, detail={"error": "bad_request", "message": "JSON expected"}) from None
    return await _call(teampeer.hello, body if isinstance(body, dict) else {}, _ip(request))


@router.post("/inbox")
async def inbox(request: Request):
    _on()
    raw = await request.body()
    frm = await _call(teampeer.verify, "POST", "/api/team-peer/inbox", dict(request.headers), raw, _ip(request))
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(400, detail={"error": "bad_request", "message": "JSON expected"}) from None
    if not isinstance(event, dict):
        raise HTTPException(400, detail={"error": "bad_request", "message": "Object expected"})
    return await _call(teampeer.receive, frm, event)


@router.get("/files/{fid}")
async def file(fid: str, request: Request):
    _on()
    path = f"/api/team-peer/files/{fid}"
    frm = await _call(teampeer.verify, "GET", path, dict(request.headers), b"", _ip(request))
    f = await _call(teampeer.file_for, frm, fid)
    return FileResponse(f["path"], media_type="application/octet-stream", filename=f["name"])
