"""Terminals of the web app (engine: maxxing/terminal.py). Off by default; turning it on asks for the password again.

- `GET /api/term` -> `{enabled, terms:[…]}`; `POST /api/term/enable {password}`, `POST /api/term/disable`
- `POST /api/term {cwd, cols, rows}` -> `{…term, token}`; `POST /api/term/{id}/token`; `DELETE /api/term/{id}`
- `WS /api/term/{id}/ws?token=`: the session cookie, the same origin and a one-time token (30 s). Server -> browser:
  binary frames of output (what came since the start first). Browser -> server: text frames, JSON
  `{"i": "<input>"}` or `{"r": [cols, rows]}`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from .. import config, security, terminal
from ..terminal import TermError
from . import auth as auth_api

router = APIRouter(prefix="/api/term", tags=["terminal"])
log = logging.getLogger("maxxing.term")
AUTH = [Depends(security.require_auth)]
REAP_EVERY_S = 60
_reaper: asyncio.Task | None = None


def _raise(e: TermError):
    raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


@router.get("", dependencies=AUTH)
async def state():
    return {"enabled": terminal.enabled(), "terms": terminal.listing(), "max": terminal.MAX_TERMS}


class EnableIn(BaseModel):
    password: str


@router.post("/enable", dependencies=AUTH)
async def enable(body: EnableIn, request: Request):
    await auth_api._check_current(request, body.password)
    await asyncio.to_thread(lambda: config.update_config(code_mode=True))
    log.info("terminal turned on")
    return {"enabled": True}


@router.post("/disable", dependencies=AUTH)
async def disable():
    await asyncio.to_thread(lambda: config.update_config(code_mode=False))
    closed = terminal.close_all()
    return {"enabled": False, "closed": closed}


class OpenIn(BaseModel):
    cwd: str
    cols: int = 100
    rows: int = 30


@router.post("", dependencies=AUTH)
async def open_term(body: OpenIn):
    try:
        t = await asyncio.to_thread(terminal.open_term, body.cwd, body.cols, body.rows)
        return {**t.info(), "token": terminal.token(t.id)}
    except TermError as e:
        _raise(e)


@router.post("/{tid}/token", dependencies=AUTH)
async def new_token(tid: str):
    try:
        return {"token": terminal.token(tid)}
    except TermError as e:
        _raise(e)


@router.delete("/{tid}", dependencies=AUTH)
async def close(tid: str):
    return {"ok": terminal.close(tid)}


def _same_origin(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    if not origin:
        return False
    host = ws.headers.get("x-forwarded-host") or ws.headers.get("host") or ""
    return urlsplit(origin).netloc.lower() == host.split(",")[0].strip().lower()


@router.websocket("/{tid}/ws")
async def stream(ws: WebSocket, tid: str, token: str = ""):
    if not security.cookie_valid(ws.cookies.get(security.COOKIE)) or not _same_origin(ws):
        await ws.close(code=4401)
        return
    try:
        t = terminal.take_token(tid, token)
    except TermError:
        await ws.close(code=4403)
        return
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    if t.buf:
        await ws.send_bytes(bytes(t.buf))
    t.listeners.add(q)

    async def pump():
        while True:
            data = await q.get()
            if data is None:
                await ws.close(code=4000)
                return
            await ws.send_bytes(data)

    sender = asyncio.create_task(pump())
    try:
        while True:
            msg = await ws.receive_text()
            try:
                m = json.loads(msg)
            except ValueError:
                continue
            if not isinstance(m, dict):              # [1], "x", 3: not a frame of ours
                continue
            if isinstance(m.get("i"), str):
                await asyncio.to_thread(terminal.write, t, m["i"].encode("utf-8", "replace"))
            elif isinstance(m.get("r"), list) and len(m["r"]) == 2:
                terminal.resize(t, *m["r"])
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        t.listeners.discard(q)
        sender.cancel()


async def _reap_loop():
    while True:
        await asyncio.sleep(REAP_EVERY_S)
        try:
            terminal.reap_idle()
        except Exception:
            log.exception("terminal reaper failed")


async def startup():
    global _reaper
    terminal.bind_loop(asyncio.get_running_loop())
    _reaper = asyncio.create_task(_reap_loop())


async def shutdown():
    if _reaper:
        _reaper.cancel()
    terminal.bind_loop(None)
    terminal.close_all()
