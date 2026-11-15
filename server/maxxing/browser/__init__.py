"""Harness Browser: Chromium on this server for the user, their sessions and their agents, for pages that have no API.

Off unless the feature is on (Settings -> Features: `browser_feature`). Its settings are in `config.json` -> `browser`:
global ones (sleep, asks, downloads) plus

- **profiles**: each one its own Chromium (its own sign-ins) and its exit; it opens any public site.
  `main` (the person's, "General") always exists; it is also the profile of the projects general and system.
  **One profile per project** (`project` = its folder), made by
  itself the first time the browser is used there (and for every project with agents when the Browser page is
  shown), with the exit of `main`. More profiles may be added by hand. A profile only runs while someone
  uses it (`max_active_profiles` at once).
- **exits**: where a profile's traffic leaves (exits.py): `direct` (this server's address, always there), a rented
  `proxy`, a phone / box over `tailscale`, a `wireguard` box. An exit that is down makes its profiles wait, never fall
  back to the server's address (unless the profile says `on_exit_down: vps`).

Who may use it: a `browser` block {enabled?} in the .maxxing.json of a project or a topic and {enabled?, profile?} in
an agent's agent.json; `enabled` is inherited (topic -> project -> on), an agent's is its own (never inherited, off until its
owner turns it on). Which profile: a session's is its project's; an agent's is its project's unless it chose another
(`profile`; a chosen profile that was deleted = its project's again).

Which sites: a profile has no list. A sandboxed agent opens only its `domains` (the same list as its commands and
WebFetch: `agent_sites`); every other turn and the person open any public site. Pages of this server and of local
networks, `file:` and Chromium's own pages are refused for all (rules).

Modules: rules (what may be opened / sent), proxy (the only way out of a browser), exits (the exits and their
runtimes), unit (the systemd unit of a profile's Chromium), cdm (chrome-devtools-mcp, the tools Claude gets: one per
turn), relay (DevTools between those tools / the live view and the browser), view (which tab a turn's command is on),
tabs (the tabs of a profile), pool (the running profiles), asks (`ask_human`: the user takes over), replays (the
journal of each action).
"""
from __future__ import annotations

import re
import secrets as _secrets
import threading
from pathlib import Path

from .. import config
from . import rules

MCP_NAME = "maxxing-browser"                  # Claude Code's MCP server name: tools are mcp__maxxing-browser__*
NAME = "Harness Browser"
MAIN = "main"
DIRECT = "direct"
DEFAULTS = {"ask": True, "wait_min": 30, "downloads": False, "idle_min": 30, "tab_sleep_min": 20, "max_tabs": 12,
            "max_active_profiles": 3, "exit_wait_s": 180, "search": "google"}
NUMBERS = {"wait_min": (1, 1440), "idle_min": (5, 1440), "tab_sleep_min": (2, 720), "max_tabs": (2, 30),
           "max_active_profiles": (1, 8), "exit_wait_s": (0, 900)}
PROFILE_DEFAULTS = {"name": "", "exit": DIRECT, "on_exit_down": "wait", "project": ""}
OWN = "own"                                    # of before the profiles per project: read as "its project's"
OWNER_DEFAULTS = {"enabled": False, "profile": MAIN}
SHARED_PROJECTS = ("projects/general", "projects/system")   # use `main` ("General"), no profile of their own
SESSIONS_DEFAULT = True     # a project / topic that says nothing: its sessions have the browser (an agent: off)
PROJECT_RE = re.compile(r"projects/[^/\s]{1,80}")
EXIT_DOWN = ("wait", "vps")
EXIT_TYPES = ("proxy", "tailscale", "wireguard")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}\Z")
MAX_PROFILES = 40
MAX_EXITS = 10
NAME_MAX = 40
_plock = threading.Lock()                       # a project's profile is made once, whoever asks first
_slock = config.ProcessLock("browser-settings")  # read, change and save the settings in one go (routes, commands)


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
    while out in taken or out in (DIRECT, OWN):
        out, n = f"{base[:18]}-{n}", n + 1
    return out


def clean_profile(raw: object, strict: bool = False) -> dict | None:
    """A profile, complete and valid; None when it has no valid id."""
    src = raw if isinstance(raw, dict) else {}
    pid = str(src.get("id") or "")
    if not ID_RE.match(pid) or pid == DIRECT:
        _bad(strict, "profiles", f"bad id {pid!r}")
        return None
    out = {**PROFILE_DEFAULTS, "id": pid, "name": _name(src.get("name"))}   # `web` / `sites` of before: dropped
    if src.get("on_exit_down") in EXIT_DOWN:
        out["on_exit_down"] = src["on_exit_down"]
    elif "on_exit_down" in src:
        _bad(strict, "on_exit_down", "wait or vps")
    # a connection that is gone stays as it is (the profile then waits, never goes direct), and never stops a save
    # of other settings: a new value is checked by set_profile
    out["exit"] = str(src.get("exit") or DIRECT)[:40]
    project = str(src.get("project") or "")
    if project and PROJECT_RE.fullmatch(project) and project not in SHARED_PROJECTS:
        out["project"] = project                   # the project this profile is for
    return out


def clean_settings(raw: object, strict: bool = False) -> dict:
    """The browser's settings, complete and valid. strict: a bad value raises instead of being replaced.
    Settings of before the profiles become `main`."""
    from . import exits as exits_mod
    src = raw if isinstance(raw, dict) else {}
    out: dict = {**DEFAULTS}
    for key in ("ask", "downloads"):
        if key in src:
            if isinstance(src[key], bool):
                out[key] = src[key]
            else:
                _bad(strict, key, "true or false")
    if "search" in src:
        if src["search"] in rules.SEARCH_ENGINES:
            out["search"] = src["search"]
        else:
            _bad(strict, "search", " or ".join(rules.SEARCH_ENGINES))
    for key, (lo, hi) in NUMBERS.items():
        if key in src and src[key] is not None:
            try:
                n = int(src[key])
                if not lo <= n <= hi:
                    raise ValueError
                out[key] = n
            except (TypeError, ValueError, OverflowError):     # OverflowError: int(1e999)
                _bad(strict, key, f"a whole number between {lo} and {hi}")
    ex_list: list[dict] = []
    for e in (src.get("exits") if isinstance(src.get("exits"), list) else [])[:MAX_EXITS]:
        c = exits_mod.clean_exit(e, strict)
        if c and c["id"] not in {x["id"] for x in ex_list}:
            ex_list.append(c)
    out["exits"] = ex_list
    profiles: list[dict] = []
    raw_profiles = src.get("profiles") if isinstance(src.get("profiles"), list) else None
    if raw_profiles is None:                         # settings of before the profiles
        raw_profiles = [{"id": MAIN}]
    for p in raw_profiles[:MAX_PROFILES]:
        c = clean_profile(p, strict)
        if c and c["id"] not in {x["id"] for x in profiles}:
            if c["project"] and any(x["project"] == c["project"] for x in profiles):
                c["project"] = ""                    # one profile per project: a second one is just a profile
            profiles.append(c)
    if not any(p["id"] == MAIN for p in profiles):
        profiles.insert(0, {**PROFILE_DEFAULTS, "id": MAIN})
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
    with _slock:
        known = {k: v for k, v in (values or {}).items() if k in DEFAULTS}
        return _save({**settings(), **known})


def profiles() -> list[dict]:
    return settings()["profiles"]


def profile(pid: str, s: dict | None = None) -> dict | None:
    return next((p for p in (s or settings())["profiles"] if p["id"] == pid), None)


def set_profile(values: dict, pid: str | None = None, *, new_exit: bool = True) -> dict:
    """Create (pid None) or change a profile; returns it. new_exit: `exit` is a choice of now (it must exist), not one
    copied from another profile (kept as it is, even gone: that profile waits too)."""
    with _slock:
        s = settings()
        values = {k: v for k, v in (values or {}).items() if k in PROFILE_DEFAULTS}
        ex = values.get("exit")
        if new_exit and ex is not None and str(ex) != DIRECT and str(ex) not in {e["id"] for e in s["exits"]}:
            raise BrowserError(400, "bad_browser", f"browser.exit: no exit {str(ex)[:40]!r}")
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


def project_profile(project: str, s: dict | None = None) -> dict | None:
    """The profile of a project (`projects/<name>`), None while it was never made. general and system: `main`."""
    if project in SHARED_PROJECTS:
        return profile(MAIN, s)
    return next((p for p in (s or settings())["profiles"] if p.get("project") == project), None)


def ensure_project_profile(project: str) -> str:
    """The id of a project's profile, made the first time with the exit of `main`, named after it."""
    if project in SHARED_PROJECTS:
        return MAIN
    with _plock:
        mine = project_profile(project)
        if mine:
            return mine["id"]
        main = profile(MAIN) or {}
        keep = {k: main[k] for k in ("exit", "on_exit_down") if k in main}
        return set_profile({**keep, "name": project.split("/", 1)[1], "project": project}, new_exit=False)["id"]


def ensure_projects_with_agents() -> None:
    """Every project with an agent has its profile (shown on the Browser page before its first use)."""
    root = config.workspace() / "projects"
    if not root.is_dir():
        return
    have = {p.get("project") for p in profiles()}
    for pdir in sorted(root.iterdir()):
        rel = f"projects/{pdir.name}"
        if rel not in have and rel not in SHARED_PROJECTS and PROJECT_RE.fullmatch(rel) and pdir.is_dir() and any(pdir.glob("topics/*/agents/*/agent.json")):
            try:
                ensure_project_profile(rel)
            except BrowserError:                      # too many profiles: the others wait for their first use
                return


def project_gone(p: dict) -> bool:
    return bool(p.get("project")) and not (config.workspace() / p["project"]).is_dir()


def delete_profile(pid: str) -> None:
    with _slock:
        if pid == MAIN:
            raise BrowserError(409, "main", "The main profile cannot be deleted")
        s = settings()
        p = profile(pid, s)
        if p is None:
            raise BrowserError(404, "no_profile", "No such profile")
        if p.get("project") and not project_gone(p):
            raise BrowserError(409, "project", "A project's profile stays as long as its project: forget its sign-ins instead")
        s["profiles"] = [p for p in s["profiles"] if p["id"] != pid]
        _save(s)


def agent_sites(owner: str) -> list[str] | None:
    """The sites a turn may open: a sandboxed agent's `domains` (also those of its commands and WebFetch), None = any
    public site (every other turn). An agent that cannot be read opens nothing."""
    kind, _, path = (owner or "").partition(":")
    if kind != "agent":
        return None
    from .. import agents
    try:
        a = agents.load(path)
    except Exception:  # noqa: BLE001
        return []
    if not a.get("sandbox"):
        return None
    out: list[str] = []
    for d in a.get("domains") or []:
        site = rules.clean_site(d)
        if site and site not in out:
            out.append(site)
    return out


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


def chosen_profile(block: dict, s: dict) -> str:
    """The profile an agent's block chose, when it still exists ("" = its project's)."""
    chosen = block.get("profile")
    return chosen if chosen and chosen != OWN and profile(chosen, s) is not None else ""


def agent_profile(path: str, block: dict, s: dict) -> str | None:
    """The profile an agent's browser uses, from its block already read (resolve without reading it again)."""
    mine = chosen_profile(block, s)
    if mine:
        return mine
    project = project_of(path)
    p = project_profile(project, s) if project else None
    return p["id"] if p else None


def resolve(path: str, s: dict | None = None, create: bool = False) -> dict:
    """{enabled, profile, project, from: {enabled, profile}} for a folder. `enabled`: its own block, else its topic's,
    else its project's, else on (an agent's is never inherited: off unless it says on). `profile`: the one an agent
    chose, else its project's ("" while the project's was never made; `create` makes it). `from`: the owner that set it ("" = the default)."""
    s = s or settings()
    owners = chain(path)
    project = project_of(path) or ""
    out = {**OWNER_DEFAULTS, "profile": "", "project": project, "from": {"enabled": "", "profile": ""}}
    if not (owners and owners[0].startswith("agent:")):
        out["enabled"] = SESSIONS_DEFAULT
    for o in owners:
        if owners[0].startswith("agent:") and o != owners[0]:
            break
        v = own_block(o).get("enabled")
        if v is not None:
            out["enabled"], out["from"]["enabled"] = v, o
            break
    if owners and owners[0].startswith("agent:"):
        chosen = chosen_profile(own_block(owners[0]), s)
        if chosen:
            out["profile"], out["from"]["profile"] = chosen, owners[0]
            return out
    if project:
        mine = project_profile(project, s)
        if mine is None and create:
            ensure_project_profile(project)
            mine = project_profile(project)
        if mine:
            out["profile"], out["from"]["profile"] = mine["id"], f"project:{project}"
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
    if not r["profile"]:
        r = resolve(path, create=True)
        s = settings()
    p = profile(r["profile"], s)
    return (owners[0], p, s) if p else None


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
