"""Browser of my PC (pcbridge): pairing, agent downloads, the agent's websocket, the local MCP and DevTools relays.

Signed-in routes manage it; three are public with their own permission:
- `POST /api/pc/pair`, `GET /api/pc/download/…`, `GET /api/pc/install.(ps1|sh)`: the pairing code (15 min);
- `WS /api/pc/ws`: the PC's device token (Bearer);
- `POST /api/pc/mcp`, `WS /api/pc/cdp`: loopback only (no proxy header) + a secret of this server - Claude Code and
  chrome-devtools-mcp run on this machine.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.websockets import WebSocketDisconnect

from .. import config, downloads, pcbridge
from ..security import require_auth

log = logging.getLogger("maxxing.pc")
router = APIRouter(prefix="/api/pc", tags=["pc"])
AUTH = [Depends(require_auth)]


def _err(e: pcbridge.PcError) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.code, "message": e.message})


def _server_url(request: Request) -> str:
    base = (config.load_config().get("public_url") or "").rstrip("/")
    return base or str(request.base_url).rstrip("/")


def _loopback(conn: Request | WebSocket) -> bool:
    """A client of this machine reached directly (Caddy adds X-Forwarded-For: anything through it is not local)."""
    host = conn.client.host if conn.client else ""
    local = ("127.0.0.1", "::1", pcbridge.local_host().strip("[]"))   # + the bind address (Tailscale mode)
    return host in local and "x-forwarded-for" not in conn.headers and "forwarded" not in conn.headers


# ---- signed in ---------------------------------------------------------------------------------------------------
@router.get("", dependencies=AUTH)
async def get_status():
    st = await asyncio.to_thread(pcbridge.status)
    st["actions"] = await asyncio.to_thread(pcbridge.actions, 20)
    return st


class PairingIn(BaseModel):
    browser: str
    os: str
    autostart: bool = True


@router.post("/pairing", dependencies=AUTH)
async def new_pairing(body: PairingIn, request: Request):
    try:
        p = await asyncio.to_thread(pcbridge.start_pairing, body.browser, body.os, body.autostart)
    except pcbridge.PcError as e:
        raise _err(e) from None
    base, code = _server_url(request), p["code"]
    p["server"] = base
    p["downloads"] = {t: f"{base}/api/pc/download/{t}?code={code}" for t in pcbridge.TARGETS}
    p["commands"] = {
        "windows": f"irm '{base}/api/pc/install.ps1?code={code}&target=windows-amd64' | iex",
        # the binary itself, never a script piped into a shell
        "darwin": _unix_command(f"{base}/api/pc/download/darwin-arm64?code={code}", mac=True),
        "linux": _unix_command(f"{base}/api/pc/download/linux-amd64?code={code}"),
    }
    return p


def _unix_command(url: str, mac: bool = False) -> str:
    f = "~/.local/bin/harness-pc"
    unquarantine = f"xattr -d com.apple.quarantine {f} 2>/dev/null; " if mac else ""
    return (f"mkdir -p ~/.local/bin && curl -fsSL -o {f} '{url}' && chmod 700 {f} && "
            f"{unquarantine}(nohup {f} >/dev/null 2>&1 &)")


class SettingsIn(BaseModel):
    idle_min: int | None = None


@router.put("/settings", dependencies=AUTH)
async def put_settings(body: SettingsIn):
    try:
        return await asyncio.to_thread(pcbridge.set_settings, body.idle_min)
    except pcbridge.PcError as e:
        raise _err(e) from None


@router.post("/stop", dependencies=AUTH)
async def stop_now():
    await pcbridge.hub().close_browser()
    return {"ok": True}


@router.post("/wipe", dependencies=AUTH)
async def wipe_profile():
    try:
        await pcbridge.hub().wipe()
    except pcbridge.Offline:
        raise HTTPException(409, detail={"error": "offline", "message": "The PC is not connected"}) from None
    except (RuntimeError, asyncio.TimeoutError) as e:
        raise HTTPException(502, detail={"error": "pc_error", "message": str(e) or "timed out"}) from None
    return {"ok": True}


@router.post("/test", dependencies=AUTH)
async def test_browser():
    """Open the browser on the PC and read its version through the same path Claude uses."""
    res = await pcbridge.tools_call("list_pages", {})
    text = " ".join(c.get("text", "") for c in res.get("content") or [] if isinstance(c, dict))[:500]
    return {"ok": not res.get("isError"), "text": text}


@router.post("/mcp/register", dependencies=AUTH)
async def reregister():
    if not (await asyncio.to_thread(pcbridge.load)).get("device"):
        raise HTTPException(409, detail={"error": "not_paired", "message": "No PC is paired"})
    await pcbridge.register_mcp()
    return {"ok": pcbridge.mcp_registered()}


class ConfirmIn(BaseModel):
    id: str
    ok: bool = True


@router.post("/confirm", dependencies=AUTH)
async def confirm_pc(body: ConfirmIn):
    """Yes / no to the PC that paired with a download code and waits (`candidate` in the status)."""
    return {"ok": await pcbridge.confirm(body.id, body.ok)}


@router.delete("", dependencies=AUTH)
async def unpair():
    await pcbridge.unpair()
    return {"ok": True}


# ---- public: pairing code ----------------------------------------------------------------------------------------
class PairIn(BaseModel):
    code: str
    name: str = ""
    os: str = ""
    arch: str = ""
    version: str = ""
    browsers: list[str] = []


@router.post("/pair")
async def pair(body: PairIn, request: Request):
    ip = request.client.host if request.client else ""          # the real client: uvicorn trusts only the local proxy
    try:
        return await asyncio.to_thread(pcbridge.pair, body.code, body.model_dump(), ip)
    except pcbridge.PcError as e:
        raise _err(e) from None


@router.get("/download/{target}")
async def download(target: str, code: str, request: Request):
    try:
        name, agent, trailer = await asyncio.to_thread(pcbridge.personalised, target, code, _server_url(request))
        f = await asyncio.to_thread(agent.open, "rb")      # opened now: a cache replaced meanwhile does not matter
    except pcbridge.PcError as e:
        raise _err(e) from None
    size = os.fstat(f.fileno()).st_size

    def body():
        with f:
            while chunk := f.read(1 << 20):
                yield chunk
        yield trailer

    return StreamingResponse(body(), media_type="application/octet-stream", headers={
        "Content-Disposition": downloads.content_disposition(name), "Content-Length": str(size + len(trailer)),
        "Cache-Control": "no-store"})


@router.get("/install.{kind}")
async def install(kind: str, code: str, request: Request, target: str = ""):
    if kind not in ("ps1", "sh"):
        raise HTTPException(404, detail={"error": "not_found", "message": "install.ps1 or install.sh"})
    target = target or ("windows-amd64" if kind == "ps1" else "linux-amd64")
    if target not in pcbridge.TARGETS:
        raise HTTPException(404, detail={"error": "not_found", "message": "unknown target"})
    try:
        text = await asyncio.to_thread(pcbridge.install_script, kind, code, _server_url(request), target)
    except pcbridge.PcError as e:
        raise _err(e) from None
    return PlainTextResponse(text, headers={"Cache-Control": "no-store"})


# ---- public: the PC agent ----------------------------------------------------------------------------------------
@router.websocket("/ws")
async def agent_ws(ws: WebSocket):
    auth = ws.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    dev = await asyncio.to_thread(pcbridge.device_for_token, token) if token else None
    if dev is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        if dev.get("candidate"):
            dev = await _wait_confirmation(ws, dev["id"])
            if dev is None:
                return
        await pcbridge.hub().serve(ws, dev)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("pc agent connection")


async def _wait_confirmation(ws: WebSocket, device_id: str) -> dict | None:
    """Hold a PC that is not confirmed yet (nothing is relayed): it goes on once the user says yes; on no, or after
    15 min, it is told to unpair itself (it removes its config and startup entry)."""
    while True:
        d = await asyncio.to_thread(pcbridge.load)
        if (d.get("device") or {}).get("id") == device_id:
            return d["device"]
        c = await asyncio.to_thread(pcbridge.candidate)
        if not c or c.get("id") != device_id:
            try:
                await ws.send_text('{"t":"unpair"}')
                await ws.close(code=4001)
            except Exception:  # noqa: BLE001
                pass
            return None
        await asyncio.sleep(1)


# ---- loopback: chrome-devtools-mcp's DevTools socket, Claude Code's MCP --------------------------------------------
@router.websocket("/cdp")
async def cdp_ws(ws: WebSocket):
    secret = ws.headers.get("x-pc-secret", "")
    if not _loopback(ws) or not hmac.compare_digest(secret.encode(), pcbridge.load()["cdp_secret"].encode()):
        await ws.close(code=4403)
        return
    await ws.accept()
    try:
        await pcbridge.hub().channel(ws)
    except (pcbridge.Offline, RuntimeError, asyncio.TimeoutError) as e:
        log.info("pc devtools channel: %s", e or "timeout")
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


SERVER_INFO = {"name": "harness-pc", "version": "1"}
INSTRUCTIONS = ("Tools to drive the browser of the user's own computer (a separate profile of their browser, which "
                "starts on the first call and closes when unused). Use it when the user asks you to do something in "
                "their browser or on a site they are signed in to.")


@router.post("/mcp")
async def mcp(request: Request):
    """Minimal MCP (streamable HTTP, JSON responses): initialize, tools/list, tools/call, ping."""
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not _loopback(request) or not token or \
            not hmac.compare_digest(token.encode(), pcbridge.load()["mcp_secret"].encode()):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    try:
        msg = await request.json()
    except (ValueError, RecursionError):                # RecursionError: "[[[[…" nested too deep
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
    if isinstance(msg, list):
        out = [r for r in [await _rpc(m) for m in msg] if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    r = await _rpc(msg)
    return JSONResponse(r) if r is not None else Response(status_code=202)


async def _rpc(m: dict) -> dict | None:
    if not isinstance(m, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    mid, method, params = m.get("id"), m.get("method"), m.get("params") or {}
    if mid is None:                                        # a notification
        return None

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def invalid(what: str) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"invalid params: {what}"}}
    if not isinstance(params, dict):
        return invalid("params must be an object")
    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or "2025-06-18",
                   "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                   "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        try:
            return ok({"tools": await pcbridge.tools_list()})
        except Exception as e:  # noqa: BLE001
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"browser tools: {e}"}}
    if method == "tools/call":
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return invalid("arguments must be an object")
        return ok(await pcbridge.tools_call(str(params.get("name") or ""), args))
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}


async def shutdown() -> None:
    await pcbridge.hub().shutdown()
