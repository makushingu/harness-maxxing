"""The browser of a turn: its token file and its MCP config (written by the runner, so: no heavy imports here).

    <state>/browser/turns/<session>.json    {owner, profile, token, at, sites}   (0600; removed when the turn ends)
    <state>/browser/turns/<session>.mcp.json                     (the --mcp-config of the turn, 0600)

The server trusts the owner and the profile of that file, never ones sent by the turn (POST /api/browser/mcp/<session>, Bearer token).
`sites`: what the turn may open, fixed when it starts (browser.agent_sites: a sandboxed agent's run -> its domains;
null = any public site), so the checks of each page never read the agent again.
"""
from __future__ import annotations

import hmac
import json
import re
import secrets
import sys
import time
from pathlib import Path

from .. import browser, config

SID_RE = re.compile(r"^[A-Za-z0-9_-]{6,80}\Z")


def turn_file(sid: str) -> Path:
    if not SID_RE.match(sid or ""):
        raise ValueError("bad session id")
    return browser.turns_dir() / f"{sid}.json"


def write_turn(sid: str, owner: str, profile: str = browser.MAIN, sites: list[str] | None = None) -> str:
    token = secrets.token_urlsafe(32)
    browser.turns_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    config.write_json(turn_file(sid), {"owner": owner, "profile": profile, "token": token, "at": time.time(),
                                       "sites": sites}, mode=0o600)
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
        return d if isinstance(d, dict) and d.get("owner") and d.get("token") else None
    except (OSError, ValueError, RecursionError):       # RecursionError: JSON nested too deep
        return None


def sites_of(turn: dict) -> list[str] | None:
    """The sites of a turn's file (a file written before `sites` existed: read from its agent)."""
    if "sites" in turn:
        v = turn["sites"]
        return [str(x) for x in v] if isinstance(v, list) else None
    return browser.agent_sites(str(turn.get("owner") or ""))


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
    if m and m.get("state") == "running":
        return True
    if not m or time.time() - float(m.get("updated") or m.get("at") or 0) > 60:
        end_turn(sid)
    return False


def clear_turns() -> None:
    """At server start: turns of a previous run are over (their runner removes them; a crash may not)."""
    d = browser.turns_dir()
    if not d.is_dir():
        return
    from ..sessions import store
    for f in d.glob("*.json"):
        sid = f.name.split(".", 1)[0]
        m = store.read(sid) if store.is_valid_id(sid) else None
        if not m or m.get("state") != "running":
            f.unlink(missing_ok=True)


def mcp_args(sid: str, owner: str, profile: str, settings: dict, sites: list[str] | None = None) -> list[str]:
    """`--mcp-config <file>` giving the turn the browser tools + ask_human (browser_mcp.py, stdio)."""
    from .. import browser_mcp
    token = write_turn(sid, owner, profile, sites)
    wait = int(settings.get("wait_min") or 30) * 60 if settings.get("ask", True) else 0
    env = {"MAXXING_BROWSER_URL": f"http://{config.local_host()}:{config.local_port()}/api/browser/mcp/{sid}",
           "MAXXING_BROWSER_TOKEN": token, "MAXXING_SESSION": sid, "MAXXING_BROWSER_OWNER": owner,
           "MAXXING_BROWSER_PROFILE": profile,
           "MAXXING_BROWSER_ASKS": str(browser.asks_dir()) if settings.get("ask", True) else "",
           "MAXXING_BROWSER_WAIT": str(wait)}
    spec = {"type": "stdio", "command": sys.executable,
            "args": ["-I", str(Path(browser_mcp.__file__).resolve())], "env": env}
    f = turn_file(sid).with_suffix(".mcp.json")
    config.write_json(f, {"mcpServers": {browser.MCP_NAME: spec}}, mode=0o600)
    return ["--mcp-config", str(f)]
