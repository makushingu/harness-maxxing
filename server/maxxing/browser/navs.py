"""The navigators of the Harness Browser: what a person opens and what a turn drives, each with its own tabs.

A profile is sign-ins (cookies, saved logins) and an exit: one Chromium. A navigator is a window of tabs
in a profile's Chromium. Several navigators may use the same profile (the same sign-ins); each one sees only its tabs:

    me                    the person's one navigator (Browser page; <state>/browser/navigators.json: its profile)
    agent:<path>          an agent's (all its runs): lasting, in its project's profile or the one it chose
    session:<sid>         a session's (the turns of that session), in its project's profile: temporary, its tabs
                          are closed once the session has had no turn for a while (pool.tidy); a line stays in the
                          profile's journal

A tab knows its navigator (tabs.py `nav`). The person may open tabs in an agent's or a session's navigator too (to
sign in for Claude, for example): Claude sees them, they are marked as the person's.
"""
from __future__ import annotations

import json
import re
import threading

from .. import browser, config

ME = "me"
SEG = r"(?!\.\.?/)[^\s:/]{1,80}"            # a folder name (never "." or "..")
NAV_RE = re.compile(rf"^(me|agent:projects/{SEG}/topics/{SEG}/agents/(?!\.\.?\Z)[^\s:/]{{1,80}}"
                    r"|session:[A-Za-z0-9_-]{6,80})\Z")
_lock = threading.Lock()                # navigators.json: read, change, write (routes run in threads)


def valid(nav: object) -> bool:
    return isinstance(nav, str) and bool(NAV_RE.match(nav))


def kind(nav: str) -> str:
    """person | agent | session"""
    return "agent" if nav.startswith("agent:") else "session" if nav.startswith("session:") else "person"


def of_by(by: dict | None) -> str:
    """The navigator of a tab opened by `by` ({kind: you|session|agent, sid?, path?}) when it does not say."""
    by = by or {}
    if by.get("kind") == "agent" and by.get("path"):
        return f"agent:{str(by['path']).strip('/')}"
    if by.get("kind") == "session" and by.get("sid"):
        return f"session:{by['sid']}"
    return ME


def of_turn(sid: str, owner: str) -> str:
    """An agent's runs share its navigator; the turns of a session share the session's."""
    return f"agent:{browser.owner_path(owner)}" if owner.startswith("agent:") else f"session:{sid}"


# ---- the person's navigators ---------------------------------------------------------------------------------------
def _file():
    return browser.home() / "navigators.json"


def person() -> list[dict]:
    """[{id: "me", name, profile, at}]: the person's navigator, on `main` unless changed (older `me-N` are ignored)."""
    try:
        d = json.loads(_file().read_text())
        raw = d.get("navigators") if isinstance(d, dict) else None
    except (OSError, ValueError, RecursionError):       # RecursionError: JSON nested too deep
        raw = None
    me = next((n for n in (raw if isinstance(raw, list) else []) if isinstance(n, dict) and n.get("id") == ME), {})
    pid = str(me.get("profile") or browser.MAIN)
    return [{"id": ME, "name": "", "at": 0.0, "profile": pid if browser.profile(pid) else browser.MAIN}]


def _save(rows: list[dict]) -> None:
    browser.home().mkdir(parents=True, exist_ok=True)
    config.write_json(_file(), {"navigators": rows})


def get_person(nav: str) -> dict | None:
    return next((n for n in person() if n["id"] == nav), None)


def update(nav: str, profile: str) -> tuple[dict, str]:
    """Put the person's navigator on another profile: (the navigator, the profile it had)."""
    with _lock:
        rows = person()
        row = next((n for n in rows if n["id"] == nav), None)
        if row is None:
            raise browser.BrowserError(404, "no_navigator", "No such browser")
        old = row["profile"]
        if browser.profile(profile) is None:
            raise browser.BrowserError(404, "no_profile", "No such browser profile")
        row["profile"] = profile
        _save(rows)
        return row, old


def on_profile_deleted(pid: str) -> None:
    """The person's navigators on a deleted profile go back to `main`."""
    with _lock:
        rows = person()
        if any(n["profile"] == pid for n in rows):
            _save([{**n, "profile": browser.MAIN if n["profile"] == pid else n["profile"]} for n in rows])


# ---- where a navigator lives ---------------------------------------------------------------------------------------
def profile_of(nav: str) -> str | None:
    """The profile a navigator uses now (None: an agent without a browser, or a navigator that does not exist)."""
    k = kind(nav)
    if k == "person":
        n = get_person(nav)
        return n["profile"] if n else None
    if k == "agent":
        return browser.resolve(nav.split(":", 1)[1])["profile"] or None
    from .turns import read_turn
    t = read_turn(nav.split(":", 1)[1])
    if t and t.get("profile"):
        return str(t["profile"])
    from .pool import pool
    return pool().profile_with(nav)


def label(nav: str) -> dict:
    """{kind, name, path?, session?} for the UI (an agent's name, a session's title)."""
    k = kind(nav)
    if k == "person":
        n = get_person(nav) or {"name": ""}
        return {"kind": k, "name": n["name"]}
    if k == "agent":
        path = nav.split(":", 1)[1]
        return {"kind": k, "name": path.rstrip("/").rsplit("/", 1)[-1], "path": path}
    sid = nav.split(":", 1)[1]
    title, path = "", ""
    try:
        from ..sessions import store
        m = store.read(sid) if store.is_valid_id(sid) else None
        if m:
            title, path = str(m.get("title") or "")[:80], str(m.get("path") or "")
    except Exception:  # noqa: BLE001
        pass
    return {"kind": k, "name": title, "session": sid, "path": path}


def agents_on(s: dict | None = None) -> list[tuple[str, str | None]]:
    """The agents whose browser is on (their navigator exists even before their first tab), with the profile each
    uses (None: its profile is gone). One read of each agent, the settings read once (the Browser page lists them all)."""
    from .. import agents
    out: list[tuple[str, str | None]] = []
    root = config.workspace() / "projects"
    if not root.is_dir():
        return out
    s = s or browser.settings()
    for a in sorted(root.glob("*/topics/*/agents/*/agent.json")):
        ap = str(a.parent.relative_to(config.workspace()))
        try:
            block = browser.clean(agents.load(ap).get("browser"))
        except Exception:  # noqa: BLE001
            continue
        if block.get("enabled"):
            out.append((f"agent:{ap}", browser.agent_profile(ap, block, s)))
    return out
