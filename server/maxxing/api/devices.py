"""Devices (maxxing/devices): the person's computers and phones that Claude uses, through Harness Link.

Signed in:
  GET    /api/devices                      feature, what can be downloaded, devices (+ online, paused, who uses it),
                                           codes waiting, requests (ask_human) waiting, the last actions
  POST   /api/devices/invites              {os?} a one-time code (15 min) -> commands, phone link, QR target
  POST   /api/devices/{id}/confirm         {ok} accept / refuse a device that paired
  PUT    /api/devices/{id}                 {name?, mode?: view|control, scope?: ["*"] | ["project:<name>", "agent:<path>"], display?: -1..15}
  DELETE /api/devices/{id}                 remove it: its token is revoked, its app forgets this server and stops
  GET    /api/devices/session/{sid}        the devices this session's Claude is using now + its requests waiting
  GET    /api/devices/asks?session=        requests waiting       POST /api/devices/asks/{rid}  {action: done|skip, note?}
  POST   /api/devices/live-token           {token} (30 s, one use) for WS /api/devices/{id}/live?t=
Public, gated by the pairing code (rate-limited): GET /api/devices/install/{code}.sh|.ps1,
  GET /api/devices/download/{target}?code=, GET /link/{code} (the phone's page), POST /api/devices/pair.
Public, gated by the device's token: WS /api/devices/ws (Authorization: Bearer).
Loopback only (+ the turn's token): POST /api/devices/mcp/{sid}.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from .. import config, devices, downloads
from ..devices import asks, dist, store, tools, turns
from ..devices.hub import DeviceError, Offline, hub
from ..security import COOKIE, client_key, cookie_valid, loopback, require_auth
from .browser import LiveTokens

log = logging.getLogger("maxxing.api.devices")
router = APIRouter(tags=["devices"])
AUTH = [Depends(require_auth)]
P = "/api/devices"
MAX_INPUT = 8192
FAIL_WINDOW = 600.0
FAIL_MAX = 20                         # wrong codes per client in FAIL_WINDOW before 429
INPUT_KEYS = ("a", "x", "y", "x2", "y2", "sw", "sh", "button", "double", "dx", "dy", "text", "keys", "ms")


def _err(e: devices.DevicesError | asks.AskError) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.code, "message": e.message})


def _server_url(request: Request) -> str:
    base = (config.load_config().get("public_url") or "").rstrip("/")
    return base or str(request.base_url).rstrip("/")


# ---- throttle of the public code routes -------------------------------------------------------------------------------
_fails: dict[str, list[float]] = {}
_flock = threading.Lock()


def _throttled(request: Request) -> bool:
    now = time.time()
    with _flock:
        lst = [t for t in _fails.get(client_key(request), []) if now - t < FAIL_WINDOW]
        return len(lst) >= FAIL_MAX


def _failed(request: Request) -> None:
    now = time.time()
    with _flock:
        if len(_fails) > 5000:
            _fails.clear()
        k = client_key(request)
        _fails[k] = [t for t in _fails.get(k, []) if now - t < FAIL_WINDOW] + [now]


def _gate(request: Request) -> None:
    if _throttled(request):
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many wrong codes: wait 10 minutes"})
    if not devices.feature_on():
        raise HTTPException(404, detail={"error": "off", "message": "Devices are off on this server"})


async def _code_ok(request: Request, fn, *a):
    """Run a code-checked call in a thread; a wrong code counts against the client."""
    try:
        return await asyncio.to_thread(fn, *a)
    except devices.DevicesError as e:
        if e.code in ("bad_code", "expired"):
            _failed(request)
        raise _err(e) from None


# ---- signed in ---------------------------------------------------------------------------------------------------------
def _view(dev: dict) -> dict:
    return {**store.public(dev), **hub().public(dev["id"])}


def _status() -> dict:
    return {"feature": devices.feature_on(), "available": dist.available(), "latest": dist.latest_version(),
            "devices": [_view(d) for d in store.devices()], "invites": store.invites_public(),
            "actions": store.actions(30)}


@router.get(P, dependencies=AUTH)
async def status() -> dict:
    st = await asyncio.to_thread(_status)
    st["asks"] = asks.pending()
    return st


class InviteIn(BaseModel):
    os: Literal["", "linux", "darwin", "windows", "android"] = ""


@router.post(P + "/invites", dependencies=AUTH)
async def new_invite(body: InviteIn, request: Request) -> dict:
    if not devices.feature_on():
        raise HTTPException(409, detail={"error": "off", "message": "Turn Devices on first (Settings -> Features)"})
    try:
        inv = await asyncio.to_thread(store.new_invite, body.os)
    except devices.DevicesError as e:
        raise _err(e) from None
    base, code = _server_url(request), inv["code"]
    return {**inv, "server": base, "commands": dist.commands(base, code), "link": f"{base}/link/{code}",
            "deeplink": dist.deeplink(base, code),
            "downloads": {t: f"{base}{P}/download/{t}?code={code}" for t in dist.TARGETS}}


class ConfirmIn(BaseModel):
    ok: bool = True


@router.post(P + "/{device_id}/confirm", dependencies=AUTH)
async def confirm(device_id: str, body: ConfirmIn) -> dict:
    ok = await asyncio.to_thread(store.confirm, device_id, body.ok)
    if ok and not body.ok:
        await hub().unpair(device_id)
    elif ok:
        await hub().access_changed(device_id)
    return {"ok": ok}


class DeviceIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    mode: Optional[Literal["view", "control"]] = None
    scope: Optional[list[str]] = None
    display: Optional[int] = Field(default=None, ge=-1, le=15)


@router.put(P + "/{device_id}", dependencies=AUTH)
async def put_device(device_id: str, body: DeviceIn) -> dict:
    try:
        dev = await asyncio.to_thread(store.update, device_id, body.name, body.mode, body.scope, body.display)
    except devices.DevicesError as e:
        raise _err(e) from None
    await hub().access_changed(device_id)
    return _view(dev)


@router.delete(P + "/{device_id}", dependencies=AUTH)
async def remove(device_id: str) -> dict:
    ok = await asyncio.to_thread(store.remove, device_id)
    if ok:
        asks.decide_device(device_id, "skip", "the device was removed")
        await hub().unpair(device_id)
    return {"ok": ok}


@router.get(P + "/session/{sid}", dependencies=AUTH)
async def session_devices(sid: str) -> dict:
    """What a session's line shows: "Claude is using <device>" (+ Watch), and its requests waiting."""
    using = []
    h = hub()
    for dev in await asyncio.to_thread(store.devices):
        pub = h.public(dev["id"])
        if pub["used_by"] and pub["used_by"].get("session") == sid:
            using.append({"id": dev["id"], "name": dev["name"], "os": dev["os"], "online": pub["online"],
                          "human": pub["human"], "at": pub["used_by"]["at"]})
    return {"using": using, "asks": asks.pending(session=sid)}


@router.get(P + "/asks", dependencies=AUTH)
async def list_asks(session: Optional[str] = None) -> dict:
    return {"asks": asks.pending(session=session or None)}


class AnswerIn(BaseModel):
    action: Literal["done", "skip"]
    note: Optional[str] = Field(default=None, max_length=500)


@router.post(P + "/asks/{rid}", dependencies=AUTH)
async def answer(rid: str, body: AnswerIn) -> dict:
    try:
        d = asks.decide(rid, body.action, body.note or "")
    except asks.AskError as e:
        raise _err(e) from None
    await hub().release(d["device"])                 # whoever had taken over hands back with the answer
    return d


_live = LiveTokens()


@router.post(P + "/live-token", dependencies=AUTH)
async def live_token() -> dict:
    return _live.new()


# ---- public: pairing code ----------------------------------------------------------------------------------------------
@router.get(P + "/install/{name}")
async def install(name: str, request: Request):
    code, _, kind = name.rpartition(".")
    if kind not in ("sh", "ps1") or not code:
        raise HTTPException(404, detail={"error": "not_found", "message": "<code>.sh or <code>.ps1"})
    _gate(request)
    try:
        text = await asyncio.to_thread(dist.install_script, kind, code, _server_url(request))
    except devices.DevicesError as e:
        if e.code not in ("bad_code", "expired"):
            raise _err(e) from None
        _failed(request)
        # a shell runs this: the reason in plain words (curl -f would only print an HTTP error)
        text = dist.install_error_script(kind, e.code)
    return PlainTextResponse(text, headers={"Cache-Control": "no-store"})


@router.get(P + "/download/{target}")
async def download(target: str, request: Request, code: str = ""):
    if target not in dist.TARGETS:
        raise HTTPException(404, detail={"error": "not_found", "message": "unknown target"})
    _gate(request)
    name, app, trailer = await _code_ok(request, dist.personalised, target, code, _server_url(request))
    f = await asyncio.to_thread(app.open, "rb")       # opened now: a cache replaced meanwhile does not matter
    size = os.fstat(f.fileno()).st_size

    def body():
        with f:
            while chunk := f.read(1 << 20):
                yield chunk
        if trailer:
            yield trailer

    media = "application/vnd.android.package-archive" if target == "android" else "application/octet-stream"
    return StreamingResponse(body(), media_type=media, headers={
        "Content-Disposition": downloads.content_disposition(name), "Content-Length": str(size + len(trailer)),
        "Cache-Control": "no-store"})


@router.get("/link/{code}")
async def link_page(code: str, request: Request):
    if _throttled(request):
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many wrong codes: wait 10 minutes"})
    lang = "fr" if config.load_config().get("language") == "fr" else "en"
    if not devices.feature_on():
        st, page = 410, dist.link_page("", _server_url(request), lang)[1]
    else:
        st, page = await asyncio.to_thread(dist.link_page, code, _server_url(request), lang)
    if st != 200:
        _failed(request)
    return HTMLResponse(page, status_code=st, headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"})


class PairIn(BaseModel):
    code: str = Field(max_length=64)
    name: str = Field(default="", max_length=200)
    os: str = Field(default="", max_length=32)
    arch: str = Field(default="", max_length=32)
    version: str = Field(default="", max_length=64)
    caps: list[str] = Field(default_factory=list, max_length=20)


@router.post(P + "/pair")
async def pair(body: PairIn, request: Request):
    _gate(request)
    ip = request.client.host if request.client else ""
    return await _code_ok(request, store.pair, body.code, body.model_dump(), ip)


# ---- public: the device's channel ------------------------------------------------------------------------------------------
@router.websocket(P + "/ws")
async def device_ws(ws: WebSocket):
    auth = ws.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    dev = await asyncio.to_thread(store.device_for_token, token) if token else None
    if dev is None:                                  # revoked or unknown: refused before the handshake (HTTP 403)
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        if not dev.get("confirmed"):
            dev = await _wait_confirmation(ws, dev["id"])
            if dev is None:
                return
        await hub().serve(ws, dev)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("device connection")


async def _wait_confirmation(ws: WebSocket, device_id: str) -> dict | None:
    """Hold a device not accepted yet (nothing is asked of it): it goes on once the user says yes; on no, or after
    15 min, it is told to forget this server. Its terminal says it waits for the user's OK."""
    dev = await asyncio.to_thread(store.get, device_id)
    mode = "control" if (dev or {}).get("mode") == "control" else "view"
    await ws.send_text(json.dumps({"t": "access", "ok": False, "mode": mode}))
    while True:
        dev = await asyncio.to_thread(store.get, device_id)
        if dev is not None and dev.get("confirmed"):
            return dev
        if dev is None:
            with contextlib.suppress(Exception):
                await ws.send_text('{"t":"unpair"}')
                await ws.close(code=4001)
            return None
        await asyncio.sleep(1)


# ---- signed in: the live view ------------------------------------------------------------------------------------------
@router.websocket(P + "/{device_id}/live")
async def live(ws: WebSocket, device_id: str):
    """Pictures of the device (binary JPEG, ~3 a second while watched) + its state (text JSON); the person's input
    ({"t":"input", a, x, y, ... in pixels of the picture shown, sw/sh = its size}: the device is theirs while they use
    it), {"t":"take"}, {"t":"release", "done": true|"skip"|false, "note"}. The signed-in cookie AND a live token."""
    if not _live.take(ws.query_params.get("t", "")) or not cookie_valid(ws.cookies.get(COOKIE)):
        await ws.close(code=4403)
        return
    dev = await asyncio.to_thread(store.get, device_id)
    if dev is None or not dev.get("confirmed"):
        await ws.close(code=4404)
        return
    await ws.accept()
    h = hub()
    vid = id(ws)
    send_lock = asyncio.Lock()
    latest: list = [None]
    fresh = asyncio.Event()
    sent = {"state": ""}

    def push(data: bytes) -> None:
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
            await ws.send_text(json.dumps(d, ensure_ascii=False, default=str))

    async def follow() -> None:
        while True:
            cur = await asyncio.to_thread(store.get, device_id)
            if cur is None:
                await send_json({"t": "gone"})
                await ws.close(code=4404)
                return
            st = {"t": "state", "device": _view(cur), "me": (h.human.get(device_id) or (None,))[0] == vid,
                  "asks": asks.pending(device=device_id)}
            text = json.dumps(st, sort_keys=True, default=str)
            if text != sent["state"]:
                sent["state"] = text
                await send_json(st)
            await asyncio.sleep(1.0)

    h.watch(device_id, vid, push)
    tasks = [asyncio.create_task(pump()), asyncio.create_task(follow())]
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > MAX_INPUT:
                continue
            try:
                ev = json.loads(raw)
            except (ValueError, RecursionError):             # RecursionError: "[[[[..." under the size limit
                continue
            if not isinstance(ev, dict):
                continue
            t = ev.get("t")
            if t == "take":
                await h.take(device_id, vid)
            elif t == "release":
                done = ev.get("done")
                if done in (True, "done", "skip"):
                    asks.decide_device(device_id, "skip" if done == "skip" else "done", str(ev.get("note") or "")[:500])
                await h.release(device_id, vid)
            elif t == "input":
                await h.take(device_id, vid)
                msg = {"t": "input", **{k: ev[k] for k in INPUT_KEYS if k in ev}}
                if isinstance(msg.get("text"), str):
                    msg["text"] = msg["text"][:tools.MAX_TEXT]
                try:
                    await h.request(device_id, msg)
                except Offline:
                    await send_json({"t": "error", "code": "offline"})
                except DeviceError as e:
                    await send_json({"t": "error", "code": e.code, "text": e.message})
                except asyncio.TimeoutError:
                    await send_json({"t": "error", "code": "timeout"})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for tk in tasks:
            tk.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await tk
        h.unwatch(device_id, vid)
        await h.release(device_id, vid)              # its requests stay pending: the person may come back


# ---- loopback: a turn's tools --------------------------------------------------------------------------------------------
@router.post(P + "/mcp/{sid}")
async def mcp(sid: str, request: Request):
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    turn = await asyncio.to_thread(turns.check_turn, sid, token) if turns.SID_RE.match(sid) and token else None
    if not loopback(request) or turn is None:
        return JSONResponse({"error": "forbidden", "message": "Not a running turn of this server"}, status_code=403)
    try:
        m = await request.json()
    except (ValueError, RecursionError):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
    if not isinstance(m, dict):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}})
    mid, method, params = m.get("id"), m.get("method"), m.get("params") or {}
    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": {"tools": tools.TOOLS}})
    if method == "tools/call" and isinstance(params, dict):
        args = params.get("arguments")

        async def alive() -> bool:
            return not await request.is_disconnected() and await asyncio.to_thread(turns.turn_alive, sid)
        res = await tools.call(turn, sid, str(params.get("name") or ""), args if isinstance(args, dict) else {}, alive)
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": res})
    return JSONResponse({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}})


async def startup() -> None:
    await asyncio.to_thread(turns.clear_turns)


async def shutdown() -> None:
    await hub().shutdown()
