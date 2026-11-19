"""The devices of a turn: its token file and its MCP config (written by the runner, so: no heavy imports here).

    <state>/devices/turns/<session>.json        {owner, path, token, at}     (0600; removed when the turn ends)
    <state>/devices/turns/<session>.mcp.json    the --mcp-config of the turn (0600)

The server trusts the folder of that file, never one sent by the turn (POST /api/devices/mcp/<session>, Bearer token);
which devices it may use is checked again on every call (devices.visible), so a device removed or an access narrowed
applies at once.
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
import sys
import time
from pathlib import Path

from .. import config
from . import MCP_NAME, turns_dir

SID_RE = re.compile(r"^[A-Za-z0-9_-]{6,80}\Z")


def turn_file(sid: str) -> Path:
    if not SID_RE.match(sid or ""):
        raise ValueError("bad session id")
    return turns_dir() / f"{sid}.json"


def owner_of(path: str) -> str:
    from .. import agents
    p = (path or "").strip("/")
    return f"agent:{p}" if agents.is_agent_path(p) else f"session:{p}"


def write_turn(sid: str, path: str) -> str:
    token = secrets.token_urlsafe(32)
    turns_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    config.write_json(turn_file(sid), {"owner": owner_of(path), "path": (path or "").strip("/"), "token": token,
                                       "at": time.time()}, mode=0o600)
    return token


def end_turn(sid: str) -> None:
    try:
        f = turn_file(sid)
    except ValueError:
        return
    f.unlink(missing_ok=True)
    f.with_suffix(".mcp.json").unlink(missing_ok=True)


def read_turn(sid: str) -> dict | None:
    try:
        d = json.loads(turn_file(sid).read_text())
        return d if isinstance(d, dict) and d.get("token") and "path" in d else None
    except (OSError, ValueError, RecursionError):
        return None


def check_turn(sid: str, token: str) -> dict | None:
    d = read_turn(sid)
    if d and token and hmac.compare_digest(str(d["token"]).encode(), token.encode()):
        return d
    return None


def turn_alive(sid: str) -> bool:
    """Its file is there and its session is running (a crashed runner may leave the file)."""
    if read_turn(sid) is None:
        return False
    from ..sessions import store
    m = store.read(sid)
    return bool(m) and m.get("state") == "running"


def clear_turns() -> None:
    """At server start: turns of a previous run are over (their runner removes them; a crash may not)."""
    d = turns_dir()
    if not d.is_dir():
        return
    from ..sessions import store
    for f in d.glob("*.json"):
        sid = f.name.split(".", 1)[0]
        m = store.read(sid) if store.is_valid_id(sid) else None
        if not m or m.get("state") != "running":
            f.unlink(missing_ok=True)


def mcp_args(sid: str, path: str) -> list[str]:
    """`--mcp-config <file>` giving the turn the device tools (devices_mcp.py, stdio)."""
    from .. import devices_mcp
    token = write_turn(sid, path)
    env = {"MAXXING_DEVICES_URL": f"http://{config.local_host()}:{config.local_port()}/api/devices/mcp/{sid}",
           "MAXXING_DEVICES_TOKEN": token, "MAXXING_SESSION": sid}
    spec = {"type": "stdio", "command": sys.executable,
            "args": ["-I", str(Path(devices_mcp.__file__).resolve())], "env": env}
    f = turn_file(sid).with_suffix(".mcp.json")
    config.write_json(f, {"mcpServers": {MCP_NAME: spec}}, mode=0o600)
    return ["--mcp-config", str(f)]
