"""Harness Browser: Chromium on this server for the user, their sessions and their agents, for pages that have no API.

Off unless the feature is on (Settings -> Features: `browser_feature`). Its settings are in `config.json` -> `browser`:
global ones (sleep, asks, downloads) plus

- **profiles**: each one its own Chromium (its own sign-ins), its sites (a list or the public web) and its exit.
  `main` always exists. A profile only runs while someone uses it (`max_active_profiles` at once).
- **exits**: where a profile's traffic leaves (exits.py): `direct` (this server's address, always there), a rented
  `proxy`, a phone / box over `tailscale`, a `wireguard` box. An exit that is down makes its profiles wait, never fall
  back to the server's address (unless the profile says `on_exit_down: vps`).

Who uses which profile: a `browser` block {enabled?, profile?} in the .maxxing.json of a project or a topic and in an
agent's agent.json; a missing key is inherited (agent -> topic -> project -> off / `main`). An agent's `enabled` is
its own (never inherited: its owner turns it on).

Modules: rules (what may be opened / sent), proxy (the only way out of a browser), exits (the exits and their
runtimes), unit (the systemd unit of a profile's Chromium), cdm (chrome-devtools-mcp, the tools Claude gets: one per
turn), relay (DevTools between those tools / the live view and the browser), view (which tab a turn's command is on),
tabs (the tabs of a profile), pool (the running profiles), asks (`ask_human`: the user takes over), replays (the
journal of each action).
"""
from __future__ import annotations

import re
import secrets as _secrets
from pathlib import Path

from .. import config
from . import rules

MCP_NAME = "maxxing-browser"                  # Claude Code's MCP server name: tools are mcp__maxxing-browser__*
NAME = "Harness Browser"
MAIN = "main"
DIRECT = "direct"
DEFAULTS = {"ask": True, "wait_min": 30, "downloads": False, "idle_min": 30, "tab_sleep_min": 20, "max_tabs": 12,
            "max_active_profiles": 3, "exit_wait_s": 180}
NUMBERS = {"wait_min": (1, 1440), "idle_min": (5, 1440), "tab_sleep_min": (2, 720), "max_tabs": (2, 30),
           "max_active_profiles": (1, 8), "exit_wait_s": (0, 900)}
PROFILE_DEFAULTS = {"name": "", "exit": DIRECT, "web": "list", "sites": [], "on_exit_down": "wait"}
OWNER_DEFAULTS = {"enabled": False, "profile": MAIN}
WEB_MODES = ("list", "public")
EXIT_DOWN = ("wait", "vps")
EXIT_TYPES = ("proxy", "tailscale", "wireguard")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}\Z")
MAX_PROFILES = 20
MAX_EXITS = 10
NAME_MAX = 40


class BrowserError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def feature_on() -> bool:
    return bool(config.load_config().get("browser_feature", False))


# ---- settings ------------------------------------------------------------------------------------------------------
def _bad(strict: bool, key: str, why: str) -> None:
    if strict:
        raise BrowserError(400, "bad_browser", f"browser.{key}: {why}")


def _name(raw: object) -> str:
    return re.sub(r"\s+", " ", str(raw or "")).strip()[:NAME_MAX]


def new_id(name: str, taken: set[str]) -> str:
    """A short id from a name ("Boutique Paris" -> "boutique-paris"), unique among `taken`."""
    base = re.sub(r"[^a-z0-9]+", "-", _name(name).lower().encode("ascii", "ignore").decode()).strip("-")[:20]
    base = base or _secrets.token_hex(3)
    out, n = base, 2
    while out in taken or out in (DIRECT,):
        out, n = f"{base[:18]}-{n}", n + 1
    return out


def clean_profile(raw: object, strict: bool = False, exits: set[str] | None = None) -> dict | None:
    """A profile, complete and valid; None when it has no valid id."""
    src = raw if isinstance(raw, dict) else {}
    pid = str(src.get("id") or "")
    if not ID_RE.match(pid) or pid == DIRECT:
        _bad(strict, "profiles", f"bad id {pid!r}")
        return None
    out = {**PROFILE_DEFAULTS, "id": pid, "name": _name(src.get("name")), "sites": []}
    if src.get("web") in WEB_MODES:
        out["web"] = src["web"]
    elif "web" in src:
        _bad(strict, "web", "list or public")
    if src.get("on_exit_down") in EXIT_DOWN:
        out["on_exit_down"] = src["on_exit_down"]
    elif "on_exit_down" in src:
        _bad(strict, "on_exit_down", "wait or vps")
    ex = str(src.get("exit") or DIRECT)
    if exits is not None and ex != DIRECT and ex not in exits:
        _bad(strict, "exit", f"no exit {ex!r}")     # read back as it is: the profile then waits, never goes direct
    out["exit"] = ex[:40]
    if "sites" in src:
        items = src["sites"] if isinstance(src["sites"], list) else []
        if strict:
            wrong = [str(s) for s in items if rules.clean_site(s) is None]
            if not isinstance(src["sites"], list) or wrong:
                _bad(strict, "sites", "public site names like example.com" + (f" (not: {', '.join(wrong[:3])})" if wrong else ""))
            if len(items) > rules.MAX_SITES:
                _bad(strict, "sites", f"at most {rules.MAX_SITES}")
        out["sites"] = rules.clean_sites(items)
    return out


def clean_settings(raw: object, strict: bool = False) -> dict:
    """The browser's settings, complete and valid. strict: a bad value raises instead of being replaced.
    Settings of before the profiles (`web`, `sites` at the top) become those of `main`."""
    from . import exits as exits_mod
    src = raw if isinstance(raw, dict) else {}
    out: dict = {**DEFAULTS}
    for key in ("ask", "downloads"):
        if key in src:
            if isinstance(src[key], bool):
                out[key] = src[key]
            else:
                _bad(strict, key, "true or false")
    for key, (lo, hi) in NUMBERS.items():
        if key in src and src[key] is not None:
            try:
                n = int(src[key])
                if not lo <= n <= hi:
                    raise ValueError
                out[key] = n
            except (TypeError, ValueError):
                _bad(strict, key, f"a whole number between {lo} and {hi}")
    ex_list: list[dict] = []
    for e in (src.get("exits") if isinstance(src.get("exits"), list) else [])[:MAX_EXITS]:
        c = exits_mod.clean_exit(e, strict)
        if c and c["id"] not in {x["id"] for x in ex_list}:
            ex_list.append(c)
    out["exits"] = ex_list
    ids = {x["id"] for x in ex_list}
    profiles: list[dict] = []
    raw_profiles = src.get("profiles") if isinstance(src.get("profiles"), list) else None
    if raw_profiles is None:                         # settings of before the profiles
        raw_profiles = [{"id": MAIN, "web": src.get("web", "list"), "sites": src.get("sites") or []}]
    for p in raw_profiles[:MAX_PROFILES]:
        c = clean_profile(p, strict, ids)
        if c and c["id"] not in {x["id"] for x in profiles}:
            profiles.append(c)
    if not any(p["id"] == MAIN for p in profiles):
        profiles.insert(0, {**PROFILE_DEFAULTS, "id": MAIN, "sites": []})
    else:                                            # main first
        profiles.sort(key=lambda p: p["id"] != MAIN)
    out["profiles"] = profiles
    return out


def settings() -> dict:
    return clean_settings(config.load_config().get("browser"))


def _save(out: dict) -> dict:
    out = clean_settings(out, strict=True)
    config.update_config(browser=out)
    return out


def set_settings(values: dict) -> dict:
    """Merge the global values (not profiles / exits: see set_profile, exits.set_exit) and save them."""
    known = {k: v for k, v in (values or {}).items() if k in DEFAULTS}
    return _save({**settings(), **known})


def profiles() -> list[dict]:
    return settings()["profiles"]


def profile(pid: str, s: dict | None = None) -> dict | None:
    return next((p for p in (s or settings())["profiles"] if p["id"] == pid), None)


def set_profile(values: dict, pid: str | None = None) -> dict:
    """Create (pid None) or change a profile; returns it."""
    s = settings()
    values = {k: v for k, v in (values or {}).items() if k in PROFILE_DEFAULTS}
    if pid is None:
        if len(s["profiles"]) >= MAX_PROFILES:
            raise BrowserError(409, "too_many", f"At most {MAX_PROFILES} profiles")
        name = _name(values.get("name"))
        if not name:
            raise BrowserError(400, "bad_browser", "A profile needs a name")
        pid = new_id(name, {p["id"] for p in s["profiles"]})
        s["profiles"].append({**PROFILE_DEFAULTS, **values, "id": pid, "name": name})
    else:
        cur = profile(pid, s)
        if cur is None:
            raise BrowserError(404, "no_profile", "No such profile")
        cur.update(values)
    out = _save(s)
    return profile(pid, out)  # type: ignore[return-value]


def delete_profile(pid: str) -> None:
    if pid == MAIN:
        raise BrowserError(409, "main", "The main profile cannot be deleted")
    s = settings()
    if profile(pid, s) is None:
        raise BrowserError(404, "no_profile", "No such profile")
    s["profiles"] = [p for p in s["profiles"] if p["id"] != pid]
    _save(s)


def sites_of(p: dict) -> list[str] | None:
    """What a profile may open: a list of sites, None = the public web."""
    return None if p.get("web") == "public" else list(p.get("sites") or [])


# ---- who uses it: a project, a topic, an agent ---------------------------------------------------------------------
def clean(raw: object, strict: bool = False) -> dict:
    """A project's / topic's / agent's `browser` block: {enabled?, profile?} (only the keys it sets)."""
    src = raw if isinstance(raw, dict) else {}
    out: dict = {}
    if "enabled" in src and src["enabled"] is not None:
        if isinstance(src["enabled"], bool):
            out["enabled"] = src["enabled"]
        elif strict:
            raise BrowserError(400, "bad_browser", "browser.enabled: true or false")
    if src.get("profile"):
        pid = str(src["profile"])
        if ID_RE.match(pid) and pid != DIRECT:
            out["profile"] = pid
        elif strict:
            raise BrowserError(400, "bad_browser", f"browser.profile: no profile {pid!r}")
    return out


def topic_of(path: str) -> str | None:
    m = re.match(r"(projects/[^/]+/topics/[^/]+)(/|$)", (path or "").strip("/"))
    return m.group(1) if m else None


def project_of(path: str) -> str | None:
    m = re.match(r"(projects/[^/]+)(/|$)", (path or "").strip("/"))
    return m.group(1) if m else None


def owner_of(path: str) -> str | None:
    """Who a folder is for the browser: `agent:<path>`, `topic:<path>` or `project:<path>`; None elsewhere."""
    from .. import agents
    p = (path or "").strip("/")
    if agents.is_agent_path(p):
        return f"agent:{p}"
    if re.fullmatch(r"projects/[^/]+/topics/[^/]+", p):
        return f"topic:{p}"
    if re.fullmatch(r"projects/[^/]+", p):
        return f"project:{p}"
    return None


def owner_path(owner: str) -> str:
    return owner.split(":", 1)[1] if ":" in owner else ""


def own_block(owner: str) -> dict:
    """What this owner itself sets ({} when nothing, or when it is gone)."""
    kind, _, path = owner.partition(":")
    try:
        if kind == "agent":
            from .. import agents
            return clean(agents.load(path).get("browser")) if agents.exists(path) else {}
        if kind in ("topic", "project"):
            from .. import workspace
            return clean(workspace.folder_browser(path))
    except Exception:  # noqa: BLE001 - a broken file: nothing set
        pass
    return {}


def chain(path: str) -> list[str]:
    """The owners a folder inherits from, nearest first: agent, topic, project."""
    p = (path or "").strip("/")
    out: list[str] = []
    a = owner_of(p)
    if a and a.startswith("agent:"):
        out.append(a)
    t = topic_of(p)
    if t:
        out.append(f"topic:{t}")
    pr = project_of(p)
    if pr:
        out.append(f"project:{pr}")
    return out


def resolve(path: str, s: dict | None = None) -> dict:
    """{enabled, profile, from: {enabled, profile}} for a folder: its own block, else its topic's, else its
    project's; `from` = the owner that set it ("" = the default). An agent's `enabled` is never inherited.
    A profile that no longer exists = `main`."""
    s = s or settings()
    owners = chain(path)
    out = {**OWNER_DEFAULTS, "from": {"enabled": "", "profile": ""}}
    for key in ("enabled", "profile"):
        for o in owners:
            if key == "enabled" and owners[0].startswith("agent:") and o != owners[0]:
                break
            v = own_block(o).get(key)
            if v is not None:
                out[key], out["from"][key] = v, o
                break
    if profile(out["profile"], s) is None:
        out["profile"], out["from"]["profile"] = MAIN, ""
    return out


def active_for(path: str) -> tuple[str, dict, dict] | None:
    """(owner, profile, settings) when turns in this folder get the browser tools, else None."""
    if not feature_on():
        return None
    owners = chain(path)
    if not owners:
        return None
    s = settings()
    r = resolve(path, s)
    if not r["enabled"]:
        return None
    return owners[0], profile(r["profile"], s), s  # type: ignore[return-value]


def used_by(pid: str) -> list[dict]:
    """Who chose this profile (projects, topics, agents of the workspace): [{owner, path, kind}]."""
    from .. import agents, workspace
    out: list[dict] = []
    root = config.workspace() / "projects"
    if not root.is_dir():
        return out
    for pdir in sorted(root.iterdir()):
        if not pdir.is_dir():
            continue
        folders = [pdir] + sorted(x for x in (pdir / "topics").glob("*") if x.is_dir())
        for f in folders:
            rel = str(f.relative_to(config.workspace()))
            if workspace.folder_browser(rel).get("profile") == pid:
                out.append({"owner": owner_of(rel), "path": rel, "kind": "project" if f == pdir else "topic"})
            if f != pdir:
                for a in sorted((f / "agents").glob("*/agent.json")):
                    ap = str(a.parent.relative_to(config.workspace()))
                    try:
                        if agents.exists(ap) and clean(agents.load(ap).get("browser")).get("profile") == pid:
                            out.append({"owner": f"agent:{ap}", "path": ap, "kind": "agent"})
                    except Exception:  # noqa: BLE001
                        pass
    return out


# ---- folders -------------------------------------------------------------------------------------------------------
def home() -> Path:
    return config.state_dir() / "browser"


def profiles_dir() -> Path:
    return home() / "profiles"


def profile_dir(pid: str) -> Path:
    return profiles_dir() / pid


def run_dir() -> Path:
    return home() / "run"


def tabs_dir() -> Path:
    return home() / "tabs"


def asks_dir() -> Path:
    return home() / "asks"


def turns_dir() -> Path:
    return home() / "turns"


def actions_dir() -> Path:
    return home() / "actions"


def exits_dir() -> Path:
    return home() / "exits"


def migrate() -> None:
    """Folders of before the profiles: the one browser (`harness`) becomes the `main` profile."""
    old, new = profiles_dir() / "harness", profile_dir(MAIN)
    if old.is_dir() and not new.exists():
        old.rename(new)
    t_old, t_new = home() / "tabs.json", tabs_dir() / f"{MAIN}.json"
    if t_old.is_file() and not t_new.exists():
        tabs_dir().mkdir(parents=True, exist_ok=True)
        t_old.rename(t_new)
