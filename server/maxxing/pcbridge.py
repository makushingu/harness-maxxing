"""Browser of my PC: Claude sessions drive an isolated Chromium browser (Brave, Chrome, Edge…) on the user's computer.

    Claude session --MCP (http, loopback)--> /api/pc/mcp --> chrome-devtools-mcp (node, started on demand)
        --CDP websocket (loopback)--> /api/pc/cdp --> control websocket /api/pc/ws <-- Harness PC agent (on the PC)
        --> the browser's DevTools socket on the PC (127.0.0.1 there).

The PC agent (pc-agent/, Go) connects OUT to this server; nothing listens on the PC. Nothing runs all the time either:
the browser and chrome-devtools-mcp start with the first browser tool call and stop after `idle_min` minutes without
one (or with "Stop now"). Protocol: pc-agent/PROTOCOL.md.

State (`<state>/pc/`): `devices.json` {device (one PC), pairing, settings, mcp_secret, cdp_secret} (0600; tokens are
stored hashed), `actions.jsonl` (tool calls, last 500), `tools.json` (cached tool list), `bin/` (agent downloads).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import struct
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import anyio

from . import config

log = logging.getLogger("maxxing.pc")

PAIR_TTL = 15 * 60
IDLE_MIN_DEFAULT = 10
LAUNCH_TIMEOUT = 40.0
START_TIMEOUT = 60.0                                  # chrome-devtools-mcp: initialize / tools/list
NPM_TIMEOUT = 300.0
CALL_TIMEOUT = 120.0
MCP_NAME = "harness-pc"
CDM_VERSION = "1.11.0"                                # chrome-devtools-mcp, installed on first use
BROWSERS = ("brave", "chrome", "edge", "vivaldi", "opera", "chromium")
TARGETS = {                                           # download target -> agent file name
    "windows-amd64": "HarnessPC-windows-amd64.exe", "windows-arm64": "HarnessPC-windows-arm64.exe",
    "darwin-arm64": "harness-pc-darwin-arm64", "darwin-amd64": "harness-pc-darwin-amd64",
    "linux-amd64": "harness-pc-linux-amd64", "linux-arm64": "harness-pc-linux-arm64",
}
TRAILER_MAGIC = b"HMPCCFG1"
MAX_ACTIONS = 500
MAX_FRAME = 16 * 1024 * 1024
# chrome-devtools-mcp, trimmed: every session carries the tool list (~5k tokens instead of ~8k). Performance traces,
# emulation, memory and network tools are off; upload_file would hand the browser a path of THIS server.
CDM_ARGS = ("--usageStatistics=false", "--performanceCrux=false", "--screenshotMaxWidth=1600",
            "--categoryPerformance=false", "--categoryEmulation=false", "--categoryMemory=false",
            "--categoryNetwork=false")
BLOCKED_TOOLS = frozenset({"upload_file", "screencast_start", "screencast_stop", "lighthouse_audit"})
CHANNEL_MAX_BYTES = 64 << 20                           # DevTools frames waiting for the local socket
SERVER_FILE_ARGS = ("filePath", "sourcePath")          # read / write files of this server: never offered, dropped
PAGE_SCHEMES = ("http", "https", "about", "data")      # what a page may be (the agent refuses the rest as well)
# names that only mean something on the PC's own network (its router, a NAS, a local service)
LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".home", ".internal", ".intranet", ".home.arpa", ".corp")
# public names that resolve to the IP written in them, or to 127.0.0.1 (DNS rebinding helpers)
LOOPBACK_DNS = ("nip.io", "sslip.io", "xip.io", "localtest.me", "lvh.me", "vcap.me", "traefik.me", "local.gd",
                "localhost.direct", "lacolhost.com")


class PcError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---- state -----------------------------------------------------------------------------------------------------
def _dir() -> Path:
    d = config.state_dir() / "pc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path() -> Path:
    return _dir() / "devices.json"


# every read-modify-write of devices.json: a hello of the agent (_touch_device) racing an unpair brought the PC back
_state_lock = threading.RLock()


def load() -> dict:
    d = config.read_json(_path(), {}) or {}
    if not isinstance(d, dict):
        d = {}
    changed = False
    for k in ("mcp_secret", "cdp_secret"):
        if not isinstance(d.get(k), str) or len(d[k]) < 32:
            d[k] = secrets.token_urlsafe(32)
            changed = True
    d.setdefault("settings", {})
    if changed:
        save(d)
    return d


def save(d: dict) -> None:
    config.write_json(_path(), d, mode=0o600)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def settings() -> dict:
    s = load().get("settings") or {}
    idle = s.get("idle_min")
    return {"idle_min": idle if isinstance(idle, int) and 1 <= idle <= 240 else IDLE_MIN_DEFAULT}


def set_settings(idle_min: int | None = None) -> dict:
    with _state_lock:
        d = load()
        if idle_min is not None:
            if not isinstance(idle_min, int) or not 1 <= idle_min <= 240:
                raise PcError(422, "invalid", "idle_min: 1-240 minutes")
            d["settings"]["idle_min"] = idle_min
        save(d)
        return settings()


# ---- pairing ---------------------------------------------------------------------------------------------------
def available() -> bool:
    """An agent can be downloaded: a local build (MAXXING_PC_BIN_DIR) or a release listed in pc_agent.json."""
    return bool(os.environ.get("MAXXING_PC_BIN_DIR")) or bool(_manifest().get("files"))


def start_pairing(browser: str, os_name: str, autostart: bool = True) -> dict:
    if not available():
        raise PcError(409, "no_agent", "Harness PC is not available for download yet")
    if browser not in BROWSERS:
        raise PcError(422, "invalid", f"browser: one of {', '.join(BROWSERS)}")
    if os_name not in ("windows", "darwin", "linux"):
        raise PcError(422, "invalid", "os: windows, darwin or linux")
    with _state_lock:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        code = "".join(secrets.choice(alphabet) for _ in range(10))
        d = load()
        d["pairing"] = {"code_hash": _hash(code), "expires": time.time() + PAIR_TTL, "browser": browser,
                        "os": os_name, "autostart": bool(autostart)}
        save(d)
        return {"code": code, "expires_at": d["pairing"]["expires"], "expires_in": PAIR_TTL}


def _pairing_for(code: str) -> dict:
    p = load().get("pairing") or {}
    if not p or not isinstance(code, str) or not code:
        raise PcError(403, "bad_code", "No pairing in progress: create a new download in Harness Maxxing")
    if time.time() > float(p.get("expires") or 0):
        raise PcError(403, "expired", "This download expired: create a new one in Harness Maxxing")
    if not hmac.compare_digest(_hash(code.strip().upper()), str(p.get("code_hash") or "")):
        raise PcError(403, "bad_code", "Unknown pairing code")
    return p


CANDIDATE_TTL = 15 * 60


def pair(code: str, info: dict, ip: str = "") -> dict:
    """POST /api/pc/pair from the agent: the PC waits as `candidate` until the user confirms it in Harness (a
    pairing code seen by someone else - a screenshot of the command - cannot plug their computer in silently).
    One PC per server: confirming replaces the previous one."""
    p = _pairing_for(code)
    token = secrets.token_urlsafe(32)
    dev = {"id": "pc_" + secrets.token_hex(4), "token_hash": _hash(token), "created": time.time(),
           "name": str(info.get("name") or "PC")[:64], "os": str(info.get("os") or p["os"])[:16],
           "arch": str(info.get("arch") or "")[:16], "version": str(info.get("version") or "")[:32],
           "browsers": [b for b in (info.get("browsers") or []) if b in BROWSERS][:10],
           "browser": p["browser"], "last_seen": time.time(), "ip": str(ip or "")[:64]}
    with _state_lock:
        d = load()
        d["candidate"], d["pairing"] = dev, None
        save(d)
        return {"device_id": dev["id"], "token": token}


def candidate() -> dict | None:
    c = load().get("candidate") or None
    return c if c and time.time() - float(c.get("created") or 0) < CANDIDATE_TTL else None


async def confirm(device_id: str, ok: bool) -> bool:
    """The user's answer about the PC waiting (`candidate`): it becomes the PC, or is refused (its agent is told
    to unpair itself). The files in a thread, the hub (the agent's websocket) on the event loop that owns it."""
    res, old = await asyncio.to_thread(_confirm_state, device_id, ok)
    if res:
        if old:
            _hub.drop(old)
        await register_mcp()
    return res


def _confirm_state(device_id: str, ok: bool) -> tuple[bool, str | None]:
    with _state_lock:
        d = load()
        c = d.get("candidate") or {}
        if not c or c.get("id") != device_id:
            return False, None
        d["candidate"] = None
        old = (d.get("device") or {}).get("id")
        if ok and candidate() is not None:
            d["device"] = c
        save(d)
        if ok and d.get("device") is c:
            return True, (old if old and old != c["id"] else None)
        return False, None


def device_for_token(token: str) -> dict | None:
    """The PC of this token: the paired one, or the one waiting for confirmation (`candidate: True`)."""
    if not token:
        return None
    d = load()
    h = _hash(token)
    dev = d.get("device") or {}
    if dev and hmac.compare_digest(h, str(dev.get("token_hash") or "")):
        return dev
    c = candidate() or {}
    if c and hmac.compare_digest(h, str(c.get("token_hash") or "")):
        return {**c, "candidate": True}
    return None


def _touch_device(**kw: Any) -> None:
    with _state_lock:
        d = load()
        if d.get("device"):
            d["device"].update(kw, last_seen=time.time())
            save(d)


async def unpair() -> None:
    dev = await asyncio.to_thread(_unpair_state)
    if dev:
        _hub.unpair(dev.get("id"))
    await unregister_mcp()


def _unpair_state() -> dict:
    with _state_lock:
        d = load()
        dev = d.get("device") or {}
        d["device"], d["pairing"], d["candidate"] = None, None, None
        save(d)
        return dev


# ---- downloads -------------------------------------------------------------------------------------------------
def _manifest() -> dict:
    p = Path(__file__).with_name("pc_agent.json")
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def agent_file(target: str) -> Path:
    """The generic agent for `target`: MAXXING_PC_BIN_DIR (tests / a local build), else the cache, else the GitHub
    release named in pc_agent.json - always checked against its SHA-256 there."""
    name = TARGETS.get(target)
    if not name:
        raise PcError(404, "not_found", "unknown target")
    local = os.environ.get("MAXXING_PC_BIN_DIR")
    if local:
        f = Path(local) / name
        if f.is_file():
            return f
        raise PcError(404, "not_found", f"{name} is not built")
    man = _manifest()
    want = (man.get("files") or {}).get(name)
    if not want:
        raise PcError(404, "not_found", "this server has no agent for this computer yet")
    cache = _dir() / "bin" / f"{man.get('version')}-{name}"
    if cache.is_file():
        with cache.open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() == want:
                return cache
    import httpx
    url = str(man.get("url") or "").format(version=man.get("version"), name=name)
    r = httpx.get(url, follow_redirects=True, timeout=60)
    r.raise_for_status()
    if hashlib.sha256(r.content).hexdigest() != want:
        raise PcError(502, "checksum", "the downloaded agent does not match its checksum")
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_bytes(r.content)
    os.replace(tmp, cache)
    return cache


def personalised(target: str, code: str, server_url: str) -> tuple[str, Path, bytes]:
    """The agent with its trailer (server, pairing code, browser): downloading it is pairing it.
    (file name, the generic agent, the trailer to send after it): the agent is streamed, never held in memory."""
    p = _pairing_for(code)
    body = json.dumps({"server": server_url, "code": code.strip().upper(), "browser": p["browser"],
                       "autostart": bool(p.get("autostart", True))}).encode()
    agent = agent_file(target)
    name = TARGETS[target]
    return (name.replace("-windows-amd64", "").replace("-windows-arm64", "") if name.endswith(".exe") else
            "harness-pc"), agent, body + struct.pack(">I", len(body)) + TRAILER_MAGIC


def install_script(kind: str, code: str, server_url: str, target: str) -> str:
    _pairing_for(code)
    url = f"{server_url}/api/pc/download/{target}?code={code}"
    if kind == "ps1":
        return ("$ErrorActionPreference = 'Stop'\n"
                "$dir = Join-Path $env:LOCALAPPDATA 'HarnessPC'; New-Item -ItemType Directory -Force -Path $dir | Out-Null\n"
                "$exe = Join-Path $dir 'HarnessPC.exe'\n"
                f"Invoke-WebRequest -UseBasicParsing -Uri '{url}' -OutFile $exe\n"
                "Start-Process -FilePath $exe\n"
                "Write-Host 'Harness PC started: check Harness Maxxing -> Settings -> MCP.'\n")
    return ("#!/bin/sh\nset -e\n"
            'dir="$HOME/.local/bin"; mkdir -p "$dir"; f="$dir/harness-pc"\n'
            f"curl -fsSL '{url}' -o \"$f\"\nchmod 700 \"$f\"\n"
            '[ "$(uname)" = Darwin ] && xattr -d com.apple.quarantine "$f" 2>/dev/null || true\n'
            'nohup "$f" >/dev/null 2>&1 &\n'
            "echo 'Harness PC started: check Harness Maxxing -> Settings -> MCP.'\n")


# ---- MCP registration ------------------------------------------------------------------------------------------
def local_port() -> int:
    """The port this server listens on (`maxxing serve --port` wins over the config)."""
    return int(os.environ.get("MAXXING_LISTEN_PORT") or config.load_config().get("port") or 8787)


def local_host() -> str:
    """The address this server answers on from this machine: 127.0.0.1, or the `bind` address (Tailscale mode)."""
    bind = str(config.load_config().get("bind") or "").strip()
    if not bind or bind in ("0.0.0.0", "::", "localhost"):
        return "127.0.0.1"
    return f"[{bind}]" if ":" in bind else bind


def mcp_url() -> str:
    return f"http://{local_host()}:{local_port()}/api/pc/mcp"


def _mcp_spec() -> dict:
    return {"type": "http", "url": mcp_url(), "headers": {"Authorization": f"Bearer {load()['mcp_secret']}"}}


async def register_mcp() -> None:
    from . import mcp
    spec = _mcp_spec()
    try:
        await asyncio.to_thread(_replace_mcp, mcp, spec)
    except Exception:  # noqa: BLE001 - shown in the status (mcp_registered false)
        log.exception("registering the %s MCP server failed", MCP_NAME)


def _replace_mcp(mcp: Any, spec: dict) -> None:
    for s in mcp.servers():
        if s["name"] == MCP_NAME and s["scope"] == "user":
            mcp.remove(s["id"])
    mcp.add(MCP_NAME, spec, None)


def _remove_mcp(mcp: Any) -> None:
    for s in mcp.servers():
        if s["name"] == MCP_NAME and s["scope"] == "user":
            mcp.remove(s["id"])


async def unregister_mcp() -> None:
    from . import mcp
    try:
        await asyncio.to_thread(_remove_mcp, mcp)
    except Exception:  # noqa: BLE001
        log.exception("removing the %s MCP server failed", MCP_NAME)


def mcp_config_args() -> list[str]:
    """`--mcp-config <file>` for a turn: the PC's browser tools come from a file of ours (0600, the secret stays out of
    the process list) instead of ~/.claude.json, which every running Claude process rewrites from its own copy and
    so can drop the entry. [] when no PC is paired. Never raises."""
    try:
        dev = load()
        if not dev.get("device"):
            return []
        f = _dir() / "mcp-config.json"
        text = json.dumps({"mcpServers": {MCP_NAME: _mcp_spec()}})
        if not f.is_file() or f.read_text() != text:
            config.write_json(f, json.loads(text), mode=0o600)
            text = f.read_text()
        return ["--mcp-config", str(f)]
    except Exception:  # noqa: BLE001 - a turn must never fail because of this
        log.exception("preparing the %s MCP config failed", MCP_NAME)
        return []


_ensure_at = {"t": -1e9}
_ensure_lock = threading.Lock()
ENSURE_EVERY = 30.0


def ensure_mcp() -> bool:
    """Put `harness-pc` back in Claude's config when a PC is paired but the entry is gone (~/.claude.json rewritten
    by another Claude process, a restore...). Called before a session turn starts, so the browser tools are there for
    that very turn: no new session, no manual step. Checked at most every 30 s. True when it repaired something."""
    if not _ensure_lock.acquire(blocking=False):      # a repair is already under way
        return False
    try:
        now = time.monotonic()
        if now - _ensure_at["t"] < ENSURE_EVERY:
            return False
        _ensure_at["t"] = now
        if not load().get("device") or mcp_registered():
            return False
        from . import mcp
        _replace_mcp(mcp, _mcp_spec())
        if not load().get("device"):                   # unpaired while `claude mcp add-json` ran: no dead entry left
            _remove_mcp(mcp)
            return False
        log.warning("the %s MCP server was missing from Claude's config: registered again", MCP_NAME)
        return True
    except Exception:  # noqa: BLE001 - a turn must never fail because of this
        log.exception("repairing the %s MCP server failed", MCP_NAME)
        return False
    finally:
        _ensure_lock.release()


def ensure_mcp_soon() -> None:
    """`ensure_mcp` without holding up the turn (the CLI call can take seconds): the turn itself already gets the
    PC's tools from `mcp_config_args`."""
    threading.Thread(target=ensure_mcp, name="pc-mcp-ensure", daemon=True).start()


def mcp_registered() -> bool:
    try:
        from . import mcp
        return mcp.has_user_server(MCP_NAME)     # polled every few seconds: never walk every project's .mcp.json
    except Exception:  # noqa: BLE001
        return False


# ---- actions log -----------------------------------------------------------------------------------------------
def _page(url: str) -> str:
    """A URL without what may carry a secret (query, fragment, user:password): sign-in codes, magic links."""
    try:
        u = urlsplit(url.strip())
        host = u.hostname or ""
        port = f":{u.port}" if u.port else ""
    except ValueError:
        return "?"
    return (f"{u.scheme}://{host}{port}{u.path}" if u.scheme in ("http", "https") else u.scheme + ":")[:200]


def _text(v) -> str:
    """str(v) that UTF-8 can write: a lone surrogate (from a JSON "\\ud800") becomes "?"."""
    return str(v).encode("utf-8", "replace").decode()


def _log_action(tool: str, args: dict, ok: bool, ms: int) -> None:
    keep = {k: (_text(v)[:200] if k not in ("value", "text", "url") else
                _page(_text(v)) if k == "url" else f"<{len(str(v))} chars>")
            for k, v in (args or {}).items() if k in ("url", "uid", "value", "text", "type", "key", "pageId", "fullPage")}
    line = json.dumps({"at": time.time(), "tool": tool, "args": keep, "ok": ok, "ms": ms}, ensure_ascii=False)
    p = _dir() / "actions.jsonl"
    try:
        lines = p.read_text().splitlines()[-(MAX_ACTIONS - 1):] if p.exists() else []
        p.write_text("\n".join(lines + [line]) + "\n")
    except (OSError, ValueError):
        pass


def actions(limit: int = 30) -> list[dict]:
    p = _dir() / "actions.jsonl"
    out = []
    try:
        for ln in p.read_text().splitlines()[-limit:]:
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        pass
    return list(reversed(out))


# ---- the hub: the PC's control websocket, its DevTools channels, chrome-devtools-mcp ----------------------------
def _schedule(coro: Any) -> None:
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:                               # no loop (CLI / a worker thread): run it here
        try:
            asyncio.run(coro)
        except Exception:  # noqa: BLE001
            log.exception("pc task failed")


class Offline(Exception):
    pass


class Hub:
    def __init__(self) -> None:
        self.ws: Any = None                            # the agent's websocket (starlette WebSocket)
        self.device_id: str | None = None
        self.hello: dict = {}
        self.running = False                           # the browser is up on the PC
        self._ids = 0
        self._wait: dict[int, asyncio.Future] = {}
        self._chans: dict[int, asyncio.Queue] = {}     # channel -> frames from the PC (None = ended)
        self._send_lock: asyncio.Lock | None = None
        self._launch_lock: asyncio.Lock | None = None
        self._child_lock: asyncio.Lock | None = None
        self.child: Child | None = None
        self.last_use = 0.0
        self._idle_task: asyncio.Task | None = None

    def _locks(self) -> None:
        if self._send_lock is None:
            self._send_lock, self._launch_lock, self._child_lock = asyncio.Lock(), asyncio.Lock(), asyncio.Lock()

    @property
    def online(self) -> bool:
        return self.ws is not None

    async def send(self, msg: dict) -> None:
        self._locks()
        if self.ws is None:
            raise Offline()
        async with self._send_lock:
            await self.ws.send_text(json.dumps(msg))

    async def request(self, msg: dict, timeout: float) -> dict:
        self._ids += 1
        rid = self._ids
        fut = asyncio.get_running_loop().create_future()
        self._wait[rid] = fut
        try:
            await self.send({**msg, "id": rid})
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._wait.pop(rid, None)

    # -- the agent's connection --
    async def serve(self, ws: Any, dev: dict) -> None:
        self._locks()
        if self.ws is not None:                        # a reconnect: the old socket is dead or a duplicate
            try:
                await self.ws.close(code=4000)
            except Exception:  # noqa: BLE001
                pass
            self._disconnected()
        self.ws, self.device_id, self.running = ws, dev["id"], False
        self._ensure_idle_watch()
        try:
            while True:
                raw = await ws.receive_text()
                if len(raw) > MAX_FRAME:
                    continue
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    try:
                        await self._on(msg)
                    except (TypeError, ValueError, AttributeError, KeyError) as e:    # a malformed frame only
                        log.warning("pc agent: frame %r ignored: %s", msg.get("t"), e)
        finally:
            if self.ws is ws:
                self._disconnected()

    async def _on(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "hello":
            self.hello = {k: msg.get(k) for k in ("v", "os", "arch", "name", "browsers")}
            self.running = bool(msg.get("running"))
            await asyncio.to_thread(_touch_device, version=str(msg.get("v") or "")[:32],
                                    browsers=[b for b in (msg.get("browsers") or []) if b in BROWSERS][:10])
        elif t in ("launched", "closed", "wiped", "opened") and isinstance(msg.get("id" if t != "opened" else "ch"), int):
            key = msg["id"] if t != "opened" else -msg["ch"]
            fut = self._wait.get(key)
            if fut and not fut.done():
                fut.set_result(msg)
            if t == "launched" and msg.get("ok"):
                self.running = True
            if t in ("closed", "wiped"):
                self.running = False
        elif t == "data" and isinstance(msg.get("ch"), int):
            q = self._chans.get(msg["ch"])
            if q is not None:
                d = msg.get("d") or ""
                q.bytes = getattr(q, "bytes", 0) + len(d)
                if q.bytes > CHANNEL_MAX_BYTES:            # the local side does not read: end it, never pile up
                    log.warning("pc devtools channel %s: %d bytes waiting, closed", msg["ch"], q.bytes)
                    self._chans.pop(msg["ch"], None)
                    q.put_nowait(None)
                else:
                    q.put_nowait(d)
        elif t == "end" and isinstance(msg.get("ch"), int):
            q = self._chans.get(msg["ch"])
            if q is not None:
                q.put_nowait(None)
        elif t == "exited":                            # closed on the PC: the MCP must reconnect next time
            self.running = False
            for q in self._chans.values():
                q.put_nowait(None)
            await self.stop_child()

    def _disconnected(self) -> None:
        self.ws, self.running = None, False
        for f in self._wait.values():
            if not f.done():
                f.set_exception(Offline())
        for q in self._chans.values():
            q.put_nowait(None)
        c, self.child = self.child, None               # nothing to drive until the PC is back
        if c is not None:
            _schedule(c.stop())

    def drop(self, device_id: str | None) -> None:
        if self.ws is not None and self.device_id == device_id:
            _schedule(self._close_ws())

    def unpair(self, device_id: str | None) -> None:
        async def run() -> None:
            try:
                await self.send({"t": "unpair"})
            except Exception:  # noqa: BLE001
                pass
            await self.stop_child()
            await self._close_ws()
        if self.device_id == device_id:
            _schedule(run())

    async def _close_ws(self) -> None:
        ws = self.ws
        self._disconnected()
        if ws is not None:
            try:
                await ws.close(code=4001)
            except Exception:  # noqa: BLE001
                pass

    # -- browser --
    async def ensure_browser(self) -> None:
        self._locks()
        if self.ws is None:
            raise Offline()
        async with self._launch_lock:
            if self.running:
                return
            dev = load().get("device") or {}
            r = await self.request({"t": "launch", "browser": dev.get("browser") or "chrome",
                                    "headless": os.environ.get("MAXXING_PC_HEADLESS") == "1"}, LAUNCH_TIMEOUT)
            if not r.get("ok"):
                raise RuntimeError(str(r.get("error") or "the browser did not start"))
            self.running = True

    async def close_browser(self) -> None:
        await self.stop_child()
        if self.ws is not None and self.running:
            try:
                await self.request({"t": "close"}, 20)
            except Exception:  # noqa: BLE001
                pass
        self.running = False

    async def wipe(self) -> None:
        await self.stop_child()
        if self.ws is None:
            raise Offline()
        r = await self.request({"t": "wipe"}, 60)
        self.running = False
        if not r.get("ok"):
            raise RuntimeError(str(r.get("error") or "the profile could not be erased"))

    # -- DevTools channels (chrome-devtools-mcp's websocket <-> the PC) --
    async def channel(self, peer: Any) -> None:
        """Relay one local DevTools websocket (`peer`, starlette) to the browser on the PC."""
        await self.ensure_browser()
        self._ids += 1
        ch = self._ids
        q: asyncio.Queue = asyncio.Queue()
        self._chans[ch] = q
        fut = asyncio.get_running_loop().create_future()
        self._wait[-ch] = fut
        try:
            await self.send({"t": "open", "ch": ch})
            r = await asyncio.wait_for(fut, 20)
            if not r.get("ok"):
                raise RuntimeError(str(r.get("error") or "no DevTools socket"))

            async def down() -> None:
                while True:
                    d = await q.get()
                    if d is None:
                        return
                    q.bytes = getattr(q, "bytes", 0) - len(d)
                    await peer.send_text(d)

            async def up() -> None:
                while True:
                    m = await peer.receive()
                    if m.get("type") == "websocket.disconnect":
                        return
                    d = m.get("text")
                    if d is None and m.get("bytes") is not None:
                        d = m["bytes"].decode("utf-8", "replace")
                    if d is not None:
                        await self.send({"t": "data", "ch": ch, "d": d})

            tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
        finally:
            self._wait.pop(-ch, None)
            self._chans.pop(ch, None)
            try:
                # shielded: a cancelled relay (local socket gone, shutdown) still tells the PC to close its end
                with anyio.move_on_after(5, shield=True):
                    await self.send({"t": "end", "ch": ch})
            except Exception:  # noqa: BLE001
                pass

    # -- chrome-devtools-mcp --
    async def get_child(self) -> "Child":
        self._locks()
        async with self._child_lock:                   # two sessions calling at once share one child
            if self.child is None or not self.child.alive:
                self.child = await Child.start()
            return self.child

    async def stop_child(self) -> None:
        c, self.child = self.child, None
        if c is not None:
            await c.stop()

    def _ensure_idle_watch(self) -> None:
        if self._idle_task is None or self._idle_task.done():
            self._idle_task = asyncio.get_running_loop().create_task(self._idle_watch())

    async def _idle_watch(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                idle = settings()["idle_min"] * 60
                if (self.child is not None or self.running) and time.time() - self.last_use > idle:
                    log.info("browser of the PC idle for %d min: closing it", idle // 60)
                    await self.close_browser()
            except Exception:  # noqa: BLE001
                log.exception("pc idle watch")

    async def shutdown(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
        await self.stop_child()


_hub = Hub()


def hub() -> Hub:
    return _hub


# ---- chrome-devtools-mcp (stdio JSON-RPC) ----------------------------------------------------------------------
def cdm_dir() -> Path:
    return config.state_dir() / "tools" / f"chrome-devtools-mcp-{CDM_VERSION}"


def cdm_entry() -> Path:
    return cdm_dir() / "node_modules" / "chrome-devtools-mcp" / "build" / "src" / "bin" / "chrome-devtools-mcp.js"


async def ensure_cdm() -> Path:
    """Install the pinned chrome-devtools-mcp on first use (npm checks the tarball against the registry's integrity
    hash; the package ships bundled, without dependencies; no install scripts run)."""
    if cdm_entry().is_file():
        return cdm_entry()
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is not installed on this server")
    d = cdm_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "package.json").write_text('{"private": true}\n')
    proc = await asyncio.create_subprocess_exec(
        npm, "install", "--silent", "--no-audit", "--no-fund", "--ignore-scripts", f"chrome-devtools-mcp@{CDM_VERSION}",
        cwd=str(d), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, env=_child_env())
    try:
        _, err = await asyncio.wait_for(proc.communicate(), NPM_TIMEOUT)
    except BaseException:
        _kill(proc)
        raise
    if proc.returncode != 0 or not cdm_entry().is_file():
        raise RuntimeError("installing chrome-devtools-mcp failed: " + (err or b"").decode()[-300:])
    return cdm_entry()


def _child_env() -> dict:
    """What node / npm need, and nothing else of this server's environment (keys, tokens)."""
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TZ", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE",
            "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy", "npm_config_cache")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS"] = "1"
    return env


def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


class Child:
    """chrome-devtools-mcp connected to /api/pc/cdp (loopback + secret header)."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc
        self._ids = 0
        self._wait: dict[int, asyncio.Future] = {}
        self._reader = asyncio.get_running_loop().create_task(self._read())
        self.tools: list[dict] = []

    @property
    def alive(self) -> bool:
        return self.proc.returncode is None and not self._reader.done()

    @classmethod
    async def start(cls) -> "Child":
        node = shutil.which("node")
        if not node:
            raise RuntimeError("node is not installed on this server")
        entry = await ensure_cdm()
        headers = json.dumps({"X-PC-Secret": load()["cdp_secret"]})
        proc = await asyncio.create_subprocess_exec(
            node, str(entry), "--wsEndpoint", f"ws://{local_host()}:{local_port()}/api/pc/cdp", "--wsHeaders", headers,
            *CDM_ARGS, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=MAX_FRAME, env=_child_env())
        c = cls(proc)
        try:
            await c.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "harness-maxxing", "version": "1"}}, START_TIMEOUT)
            await c.notify("notifications/initialized")
            c.tools = [t for t in (await c.call("tools/list", {}, START_TIMEOUT)).get("tools") or []
                       if t.get("name") not in BLOCKED_TOOLS]
        except BaseException:                          # never leave a node process behind a failed start
            await c.stop()
            raise
        try:
            (_dir() / "tools.json").write_text(json.dumps({"version": CDM_VERSION, "tools": c.tools}))
        except OSError:
            pass
        return c

    async def _read(self) -> None:
        assert self.proc.stdout is not None
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            fut = self._wait.get(msg.get("id")) if isinstance(msg, dict) else None
            if fut and not fut.done():
                fut.set_result(msg)
        for f in self._wait.values():
            if not f.done():
                f.set_exception(RuntimeError("chrome-devtools-mcp stopped"))

    async def _write(self, msg: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def notify(self, method: str, params: dict | None = None) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    async def call(self, method: str, params: dict, timeout: float = CALL_TIMEOUT) -> dict:
        self._ids += 1
        rid = self._ids
        fut = asyncio.get_running_loop().create_future()
        self._wait[rid] = fut
        try:
            await self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            msg = await asyncio.wait_for(fut, timeout)
        finally:
            self._wait.pop(rid, None)
        if "error" in msg:
            raise RuntimeError(str((msg["error"] or {}).get("message") or msg["error"]))
        return msg.get("result") or {}

    async def stop(self) -> None:
        if self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), 5)
            except (ProcessLookupError, asyncio.TimeoutError):
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass
        self._reader.cancel()


def cached_tools() -> list[dict]:
    """The tool list without starting anything: the one seen last, else the one shipped (pc_tools.json)."""
    for f in (_dir() / "tools.json", Path(__file__).with_name("pc_tools.json")):
        try:
            d = json.loads(f.read_text())
            if d.get("version") == CDM_VERSION and isinstance(d.get("tools"), list) and d["tools"]:
                return d["tools"]
        except (OSError, ValueError):
            pass
    return []


OFFLINE_TEXT = ("The browser of the user's PC is not reachable: the Harness PC program is not running or the PC is "
                "off / asleep. Tell the user, who can start Harness PC on the computer (Settings -> MCP -> Browser "
                "of my PC in Harness Maxxing).")


def _offered(tools: list[dict]) -> list[dict]:
    """The tools Claude sees: no blocked tool, no argument reading or writing files of this server."""
    out = []
    for t in tools:
        if t.get("name") in BLOCKED_TOOLS:
            continue
        schema = dict(t.get("inputSchema") or {})
        props = {k: v for k, v in (schema.get("properties") or {}).items() if k not in SERVER_FILE_ARGS}
        if "properties" in schema:
            schema["properties"] = props
        if "required" in schema:
            schema["required"] = [k for k in schema["required"] if k not in SERVER_FILE_ARGS]
        out.append({**t, "inputSchema": schema})
    return out


def _local_host(host: str) -> bool:
    """A host of the PC itself or of its local network (as the browser there would read it: 127.1, 2130706433…)."""
    h = unicodedata.normalize("NFKC", host).replace("\u3002", ".")   # full-width digits and dots, as the browser maps them
    h = h.strip().strip("[]").rstrip(".").lower()
    if not h:
        return False
    if not h.isascii() and ":" not in h:
        try:
            h = h.encode("idna").decode("ascii")       # an international name: its punycode form
        except UnicodeError:
            return True
    if "%" in h or not h.isascii():
        return True                                    # an escaped host the filter cannot read safely
    if h == "localhost" or h.endswith(LOCAL_SUFFIXES) or "." not in h and not h.isdigit() and ":" not in h:
        return True                                    # a bare name ("router", "nas") resolves on the PC's network
    if any(h == d or h.endswith("." + d) for d in LOOPBACK_DNS):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        try:
            ip = ipaddress.ip_address(socket.inet_aton(h))   # the short / decimal / hex IPv4 forms
        except OSError:
            return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def _bad_url(args: dict) -> str | None:
    url = args.get("url")
    if url is None:
        return None
    raw = re.sub(r"[\t\n\r]", "", str(url)).strip().replace("\\", "/")   # what the browser drops / reads as "/"
    try:
        u = urlsplit(raw)
    except ValueError:                                   # "http://[::1": not an address the browser can open
        return "Only http(s) pages can be opened in the browser of the PC (no file:, chrome:... addresses)."
    scheme = u.scheme.lower()
    if scheme not in PAGE_SCHEMES or (scheme == "about" and raw.lower() not in ("about:blank",)):
        return "Only http(s) pages can be opened in the browser of the PC (no file:, chrome:... addresses)."
    try:
        host = u.hostname or ""
    except ValueError:
        host = ""
    # `http:host/`, `http:/host/`, `http:///host/`: the browser finds a host where urlsplit sees none
    if scheme in ("http", "https") and (not re.match(r"^[a-z]+://[^/]", raw, re.I) or not host or _local_host(host)):
        return ("Addresses of the PC itself or of its local network (localhost, 192.168.x.x, router, NAS...) cannot be "
                "opened by Claude in the browser of the PC: only sites on the internet.")
    return None


async def tools_list() -> list[dict]:
    tools = cached_tools()
    if not tools:
        # never seen: start chrome-devtools-mcp once to learn its tools (it connects to the browser only on a call)
        c = await _hub.get_child()
        _hub.last_use = time.time()
        tools = c.tools
    return _offered(tools)


async def tools_call(name: str, args: dict) -> dict:
    t0 = time.time()
    _hub.last_use = t0
    if name in BLOCKED_TOOLS or not any(t.get("name") == name for t in cached_tools() or []):
        return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool {name}"}]}
    args = {k: v for k, v in (args or {}).items() if k not in SERVER_FILE_ARGS}
    if (why := _bad_url(args)) is not None:
        await asyncio.to_thread(_log_action, name, args, False, 0)
        return {"isError": True, "content": [{"type": "text", "text": why}]}
    ok = False
    try:
        if not _hub.online:
            raise Offline()
        await _hub.ensure_browser()
        c = await _hub.get_child()
        try:
            res = await c.call("tools/call", {"name": name, "arguments": args or {}})
        except RuntimeError:
            if c.alive:                                # the tool's own error (a bad argument): no restart
                raise
            await _hub.stop_child()                    # chrome-devtools-mcp stopped (browser closed): one fresh try
            await _hub.ensure_browser()
            c = await _hub.get_child()
            res = await c.call("tools/call", {"name": name, "arguments": args or {}})
        ok = not res.get("isError")
        return res
    except Offline:
        return {"isError": True, "content": [{"type": "text", "text": OFFLINE_TEXT}]}
    except (asyncio.TimeoutError, RuntimeError) as e:
        return {"isError": True, "content": [{"type": "text", "text": f"Browser of the PC: {e or 'timed out'}"}]}
    finally:
        _hub.last_use = time.time()
        await asyncio.to_thread(_log_action, name, args or {}, ok, int((time.time() - t0) * 1000))


# ---- status ----------------------------------------------------------------------------------------------------
def status() -> dict:
    d = load()
    dev = d.get("device") or None
    p = d.get("pairing") or None
    pending = bool(p) and time.time() < float(p.get("expires") or 0)
    cand = candidate()
    return {
        "device": ({k: dev.get(k) for k in ("id", "name", "os", "arch", "version", "browsers", "browser",
                                            "created", "last_seen")} if dev else None),
        "online": _hub.online,
        "browser_running": _hub.running,
        "mcp_running": _hub.child is not None and _hub.child.alive,
        "last_use": _hub.last_use or None,
        "pairing": ({"expires_at": p["expires"], "browser": p["browser"], "os": p["os"]} if pending else None),
        "candidate": ({k: cand.get(k) for k in ("id", "name", "os", "arch", "version", "created", "ip")}
                      if cand else None),
        "available": available(),
        "mcp_registered": mcp_registered() if dev else False,
        "settings": settings(),
        "browsers": list(BROWSERS),
        "targets": list(TARGETS),
    }
