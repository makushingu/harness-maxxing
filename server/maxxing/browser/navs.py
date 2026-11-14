"""The navigators of the Harness Browser: what a person opens and what a turn drives, each with its own tabs.

A profile is sign-ins (cookies, saved logins), an exit and a site list: one Chromium. A navigator is a window of tabs
in a profile's Chromium. Several navigators may use the same profile (the same sign-ins); each one sees only its tabs:

    me, me-2 ...          the person's navigators (Browser page; <state>/browser/navigators.json: name, profile)
    agent:<path>          an agent's (all its runs), in the profile its browser settings give
    session:<sid>         a session's (the turns of that session), in the profile of its folder

A tab knows its navigator (tabs.py `nav`). The person may open tabs in an agent's or a session's navigator too (to
sign in for Claude, for example): Claude sees them, they are marked as the person's.
"""
from __future__ import annotations

import json
import re
import time

from .. import browser, config

ME = "me"
MAX_PERSON = 8
NAV_RE = re.compile(r"^(me(-[0-9]{1,3})?|agent:projects/[^\s:]{1,250}|session:[A-Za-z0-9_-]{6,80})\Z")
PERSON_RE = re.compile(r"^me(-[0-9]{1,3})?\Z")


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
    """[{id, name, profile, at}], "me" first (always there, on `main` unless changed)."""
    try:
        d = json.loads(_file().read_text())
        raw = d.get("navigators") if isinstance(d, dict) else None
    except (OSError, ValueError):
        raw = None
    out: list[dict] = []
    seen: set[str] = set()
    for n in raw if isinstance(raw, list) else []:
        if not isinstance(n, dict) or not PERSON_RE.match(str(n.get("id") or "")) or n["id"] in seen:
            continue
        seen.add(n["id"])
        pid = str(n.get("profile") or browser.MAIN)
        out.append({"id": n["id"], "name": browser._name(n.get("name")), "at": float(n.get("at") or 0),
                    "profile": pid if browser.profile(pid) else browser.MAIN})
    if ME not in seen:
        out.insert(0, {"id": ME, "name": "", "profile": browser.MAIN, "at": 0.0})
    out.sort(key=lambda n: (n["id"] != ME, n["at"]))
    return out[:MAX_PERSON]


def _save(rows: list[dict]) -> None:
    browser.home().mkdir(parents=True, exist_ok=True)
    config.write_json(_file(), {"navigators": rows})


def get_person(nav: str) -> dict | None:
    return next((n for n in person() if n["id"] == nav), None)


def create(profile: str = browser.MAIN, name: str = "") -> dict:
    if browser.profile(profile) is None:
        raise browser.BrowserError(404, "no_profile", "No such browser profile")
    rows = person()
    if len(rows) >= MAX_PERSON:
        raise browser.BrowserError(409, "too_many", f"At most {MAX_PERSON} browsers of your own")
    taken = {n["id"] for n in rows}
    i = 2
    while f"me-{i}" in taken:
        i += 1
    row = {"id": f"me-{i}", "name": browser._name(name), "profile": profile, "at": time.time()}
    _save(rows + [row])
    return row


def update(nav: str, profile: str | None = None, name: str | None = None) -> tuple[dict, str]:
    """(the navigator, the profile it had)."""
    rows = person()
    row = next((n for n in rows if n["id"] == nav), None)
    if row is None:
        raise browser.BrowserError(404, "no_navigator", "No such browser")
    old = row["profile"]
    if profile is not None:
        if browser.profile(profile) is None:
            raise browser.BrowserError(404, "no_profile", "No such browser profile")
        row["profile"] = profile
    if name is not None:
        row["name"] = browser._name(name)
    _save(rows)
    return row, old


def delete(nav: str) -> dict:
    if nav == ME:
        raise browser.BrowserError(400, "keep_me", "Your first browser stays (close its tabs instead)")
    rows = person()
    row = next((n for n in rows if n["id"] == nav), None)
    if row is None:
        raise browser.BrowserError(404, "no_navigator", "No such browser")
    _save([n for n in rows if n["id"] != nav])
    return row


def on_profile_deleted(pid: str) -> None:
    """The person's navigators on a deleted profile go back to `main`."""
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
        r = browser.resolve(nav.split(":", 1)[1])
        return None if r.get("gone") else r["profile"]
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


def agents_on() -> list[str]:
    """The agents whose browser is on (their navigator exists even before their first tab)."""
    from .. import agents
    out: list[str] = []
    root = config.workspace() / "projects"
    if not root.is_dir():
        return out
    for a in sorted(root.glob("*/topics/*/agents/*/agent.json")):
        ap = str(a.parent.relative_to(config.workspace()))
        try:
            block = browser.clean(agents.load(ap).get("browser"))
        except Exception:  # noqa: BLE001
            continue
        if block.get("enabled"):
            out.append(f"agent:{ap}")
    return out
