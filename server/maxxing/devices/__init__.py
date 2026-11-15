"""Devices: Claude uses the user's own computers and phones (computer use), the user watches and takes over.

    session (claude -p) --stdio MCP--> devices_mcp.py --loopback HTTP + the turn's token--> POST /api/devices/mcp/<sid>
       server: devices/ (store, hub, tools) --WS /api/devices/ws (out of the device, Bearer)--> Harness Link
    UI: Settings -> Devices, WS /api/devices/<id>/live (pictures + the person's input)

Off unless the feature is on (Settings -> Features: `devices_feature`). A device runs Harness Link (`link/`: Linux,
macOS, Windows; `android/`), pairs with a one-time code (15 min) and waits until the user accepts it. Protocol between
the server and the app: `link/PROTOCOL.md` (v2).

Modules: store (devices.json: devices, hashed tokens, invitations, the actions log), dist (the app's downloads and
install scripts), hub (the devices' websockets: requests with ids, state, the live pictures), tools (Claude's tools),
asks (`ask_human`: the person takes over), turns (a turn's token file and MCP config).

Who sees a device: its `scope` (["*"] = every project and agent; "project:<name>", "agent:<path>"), and for an agent
turn its agent.json `devices` (ids the owner turned on; a sandboxed agent: only those). Its `mode`: "view" (Claude
looks and guides) or "control" (Claude clicks and types).
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import config

MCP_NAME = "harness-devices"                   # Claude Code's MCP server name: tools are mcp__harness-devices__*
PROTOCOL = 2
ID_RE = re.compile(r"^dev_[0-9a-f]{8}\Z")
OSES = ("linux", "darwin", "windows", "android")
OS_NAMES = {"linux": "Linux", "darwin": "macOS", "windows": "Windows", "android": "Android"}
MODES = ("view", "control")
PROJECT_SCOPE_RE = re.compile(r"^project:[^/\s:]{1,80}\Z")
AGENT_SCOPE_RE = re.compile(r"^agent:projects/[^/\s]{1,80}/topics/[^/\s]{1,80}/agents/[^/\s]{1,80}\Z")


class DevicesError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def feature_on() -> bool:
    return bool(config.load_config().get("devices_feature", False))


def home() -> Path:
    d = config.state_dir() / "devices"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def turns_dir() -> Path:
    return home() / "turns"


def kind_of(os_name: str) -> str:
    return "android" if os_name == "android" else "desktop"


def clean_scope(raw: object, strict: bool = False) -> list[str]:
    """["*"], or a list of "project:<name>" / "agent:<path>" (an empty list = no project, no agent)."""
    items = raw if isinstance(raw, list) else ["*"] if raw is None else []
    out: list[str] = []
    for x in items[:50]:
        s = str(x).strip()
        if s == "*":
            return ["*"]
        if PROJECT_SCOPE_RE.match(s) or AGENT_SCOPE_RE.match(s):
            if s not in out:
                out.append(s)
        elif strict:
            raise DevicesError(400, "bad_scope", f"scope: \"*\", \"project:<name>\" or \"agent:<path>\", not {s[:80]!r}")
    return out


def project_name(path: str) -> str:
    m = re.match(r"projects/([^/]+)(/|$)", (path or "").strip("/"))
    return m.group(1) if m else ""


def in_scope(dev: dict, path: str) -> bool:
    """The device's own access list lets a turn of this folder (a session's topic, an agent's folder) see it."""
    scope = dev.get("scope") or []
    if "*" in scope:
        return True
    p = (path or "").strip("/")
    name = project_name(p)
    if name and f"project:{name}" in scope:
        return True
    from .. import agents
    return agents.is_agent_path(p) and f"agent:{p}" in scope


def agent_allows(dev: dict, path: str) -> bool:
    """An agent's folder: the device is one its owner turned on (agent.json `devices`), or - a free agent (not
    sandboxed) - one whose access names this very agent. Other folders: True."""
    from .. import agents
    p = (path or "").strip("/")
    if not agents.is_agent_path(p):
        return True
    try:
        a = agents.load(p)
    except Exception:  # noqa: BLE001 - an agent that cannot be read gets nothing
        return False
    if dev.get("id") in (a.get("devices") or []):
        return True
    return not a.get("sandbox") and f"agent:{p}" in (dev.get("scope") or [])


def visible(path: str, devices: list[dict] | None = None) -> list[dict]:
    """The confirmed devices a turn of this folder may use (empty when the feature is off)."""
    if not feature_on():
        return []
    from . import store
    out = []
    for d in devices if devices is not None else store.devices():
        if d.get("confirmed") and in_scope(d, path) and agent_allows(d, path):
            out.append(d)
    return out
