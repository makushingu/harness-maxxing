"""Harness Browser: one Chromium on this server for the user, their sessions and their agents (one profile: one set
of sign-ins), for pages that have no API.

Off unless the feature is on (Settings -> Features: `browser_feature`). Its settings are global (`config.json` ->
`browser`); a topic or an agent only has a switch (`browser.enabled` in its .maxxing.json / agent.json): may its turns
use the browser.

Every tab has a scope (tabs.py): `me` (the user only), `topic:projects/<p>/topics/<t>`, `project:projects/<p>` or
`agent:projects/<p>/topics/<t>/agents/<a>` (that agent only). A turn sees and drives only the tabs whose scope covers its
folder; a tab it opens gets its topic's scope (an agent's: its own). The user sees every tab.

Modules: rules (what may be opened / sent), proxy (the only way out of the browser), unit (the systemd unit that runs
Chromium as the `maxxing-browser` user with no network of its own), cdm (chrome-devtools-mcp, the tools Claude
gets: one per turn), relay (DevTools between those tools / the live view and the browser), view (what a turn's tools
see of the tabs), tabs (the tabs and their scopes), pool (the browser), asks (`ask_human`: the user takes over),
replays (the journal of each action), setup (what this server needs).
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import config
from . import rules

MCP_NAME = "maxxing-browser"                  # Claude Code's MCP server name: tools are mcp__maxxing-browser__*
NAME = "Harness Browser"
SLUG = "harness"                              # its profile / run folder and unit name
DEFAULTS = {"web": "list", "sites": [], "profile": "keep", "ask": True, "wait_min": 30, "downloads": False,
            "idle_min": 30, "tab_sleep_min": 20, "max_tabs": 12}
NUMBERS = {"wait_min": (1, 1440), "idle_min": (5, 1440), "tab_sleep_min": (2, 720), "max_tabs": (2, 30)}
OWNER_DEFAULTS = {"enabled": False}
WEB_MODES = ("list", "public")
PROFILE_MODES = ("keep", "fresh")
ME = "me"


class BrowserError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---- global settings ---------------------------------------------------------------------------------------------
def feature_on() -> bool:
    return bool(config.load_config().get("browser_feature", False))


def clean_settings(raw: object, strict: bool = False) -> dict:
    """The browser's settings, complete and valid. strict: a bad value raises instead of being replaced."""
    src = raw if isinstance(raw, dict) else {}
    out = {**DEFAULTS, "sites": []}

    def bad(key: str, why: str) -> None:
        if strict:
            raise BrowserError(400, "bad_browser", f"browser.{key}: {why}")

    for key in ("ask", "downloads"):
        if key in src:
            if isinstance(src[key], bool):
                out[key] = src[key]
            else:
                bad(key, "true or false")
    if "web" in src:
        if src["web"] in WEB_MODES:
            out["web"] = src["web"]
        else:
            bad("web", "list or public")
    if "profile" in src:
        if src["profile"] in PROFILE_MODES:
            out["profile"] = src["profile"]
        else:
            bad("profile", "keep or fresh")
    for key, (lo, hi) in NUMBERS.items():
        if key in src and src[key] is not None:
            try:
                n = int(src[key])
                if not lo <= n <= hi:
                    raise ValueError
                out[key] = n
            except (TypeError, ValueError):
                bad(key, f"a whole number between {lo} and {hi}")
    if "sites" in src:
        items = src["sites"] if isinstance(src["sites"], list) else []
        sites = rules.clean_sites(items)
        if strict:
            wrong = [str(s) for s in items if rules.clean_site(s) is None]
            if not isinstance(src["sites"], list) or wrong:
                bad("sites", "public site names like example.com" + (f" (not: {', '.join(wrong[:3])})" if wrong else ""))
            if len(items) > rules.MAX_SITES:
                bad("sites", f"at most {rules.MAX_SITES}")
        out["sites"] = sites
    return out


def settings() -> dict:
    return clean_settings(config.load_config().get("browser"))


def set_settings(values: dict) -> dict:
    """Merge `values` into the settings (strict) and save them."""
    known = {k: v for k, v in (values or {}).items() if k in DEFAULTS}
    out = clean_settings({**settings(), **known}, strict=True)
    config.update_config(browser=out)
    return out


def allowed_sites(s: dict | None = None) -> list[str] | None:
    """None = the public web."""
    s = settings() if s is None else s
    return None if s.get("web") == "public" else list(s.get("sites") or [])


# ---- who may use it (a topic's sessions, an agent) -------------------------------------------------------------------
def clean(raw: object, strict: bool = False) -> dict:
    """A topic's / an agent's `browser` block: only its switch (older keys are ignored)."""
    src = raw if isinstance(raw, dict) else {}
    if "enabled" in src and not isinstance(src["enabled"], bool):
        if strict:
            raise BrowserError(400, "bad_browser", "browser.enabled: true or false")
        return dict(OWNER_DEFAULTS)
    return {"enabled": bool(src.get("enabled", False))}


def owner_of(path: str) -> str | None:
    """Who a session folder belongs to for the browser: `agent:<agent path>` or `topic:<topic path>`; None outside a
    topic."""
    from .. import agents
    p = (path or "").strip("/")
    if agents.is_agent_path(p):
        return f"agent:{p}"
    if re.fullmatch(r"projects/[^/]+/topics/[^/]+", p):
        return f"topic:{p}"
    return None


def owner_path(owner: str) -> str:
    return owner.split(":", 1)[1] if ":" in owner else ""


def owner_settings(owner: str) -> dict:
    """The owner's switch ({"enabled": False} when none, or when the owner is gone)."""
    kind, _, path = owner.partition(":")
    try:
        if kind == "agent":
            from .. import agents
            return clean(agents.load(path).get("browser")) if agents.exists(path) else dict(OWNER_DEFAULTS)
        if kind == "topic":
            from .. import workspace
            return clean(workspace.topic_browser(path))
    except Exception:  # noqa: BLE001 - a broken file: the browser stays off
        pass
    return dict(OWNER_DEFAULTS)


def active_for(path: str) -> tuple[str, dict] | None:
    """(owner, browser settings) when turns in this folder get the browser tools, else None."""
    if not feature_on():
        return None
    owner = owner_of(path)
    if not owner or not owner_settings(owner)["enabled"]:
        return None
    return owner, settings()


# ---- scopes of tabs ------------------------------------------------------------------------------------------------
def topic_of(path: str) -> str | None:
    m = re.match(r"(projects/[^/]+/topics/[^/]+)(/|$)", (path or "").strip("/"))
    return m.group(1) if m else None


def project_of(path: str) -> str | None:
    m = re.match(r"(projects/[^/]+)(/|$)", (path or "").strip("/"))
    return m.group(1) if m else None


def scope_for(path: str) -> str:
    """The scope of a tab a turn in this folder opens: its agent's own (an agent folder), else its topic."""
    from .. import agents
    p = (path or "").strip("/")
    if agents.is_agent_path(p):
        return f"agent:{p}"
    t = topic_of(p)
    return f"topic:{t}" if t else ME


def visible(scope: str | None, path: str) -> bool:
    """May a turn in this folder (a topic or an agent folder) see a tab of this scope? An agent only sees its own tabs
    (the user shares one with it by giving it the agent's scope); the topic's and the project's are its sessions'."""
    if not scope or scope == ME:
        return False
    from .. import agents
    p = (path or "").strip("/")
    kind, _, where = scope.partition(":")
    if kind == "agent":
        return p == where
    if agents.is_agent_path(p):
        return False
    if kind == "topic":
        return topic_of(p) == where
    if kind == "project":
        return project_of(p) == where
    return False


def clean_scope(raw: object) -> str | None:
    """A valid scope of an existing topic / project / agent, or None."""
    s = str(raw or "").strip()
    if s == ME:
        return ME
    kind, _, where = s.partition(":")
    where = where.strip("/")
    if kind == "topic" and re.fullmatch(r"projects/[A-Za-z0-9_.-]+/topics/[A-Za-z0-9_.-]+", where):
        return f"topic:{where}" if (config.workspace() / where).is_dir() else None
    if kind == "project" and re.fullmatch(r"projects/[A-Za-z0-9_.-]+", where):
        return f"project:{where}" if (config.workspace() / where).is_dir() else None
    if kind == "agent":
        from .. import agents
        return f"agent:{where}" if agents.exists(where) else None
    return None


def slug(owner: str = "") -> str:
    """Kept for the journal and the asks: one browser, one slug."""
    return SLUG


# ---- folders -------------------------------------------------------------------------------------------------------
def home() -> Path:
    return config.state_dir() / "browser"


def profiles_dir() -> Path:
    return home() / "profiles"


def run_dir() -> Path:
    return home() / "run"


def asks_dir() -> Path:
    return home() / "asks"


def turns_dir() -> Path:
    return home() / "turns"


def actions_dir() -> Path:
    return home() / "actions"
