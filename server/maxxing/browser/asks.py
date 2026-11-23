"""`ask_human`: a turn needs the person (a captcha, a sign-in, a code) - the server side.

browser_mcp.py writes <state>/browser/asks/<id>.json and waits; this module announces it (a Notifications event with
"Open the browser" / "Skip", which Telegram shows too; a line in the agent's thread; the waiting count of the session) and
writes the person's answer: "done" (they took over and handed back), "skip". A request whose turn is gone expires.
"""
from __future__ import annotations

import contextlib
import logging
import math
import re
import time
from pathlib import Path

from .. import browser, bus, browser_mcp

log = logging.getLogger("maxxing.browser")

ID_RE = re.compile(r"\A[0-9a-f]{16}\Z")
ORPHAN_GRACE_S = 15.0
KEEP_S = 86400.0
WHAT = {"captcha": "a captcha", "sign_in": "a sign-in", "code": "a code", "payment": "a payment",
        "consent": "an agreement", "other": "a step"}
DONE_TEXT = {"done": "Done by you", "skip": "Skipped", "timeout": "No answer in time", "expired": "The run stopped"}

_seen: dict[str, str] = {}
_counts: dict[str, int] = {}


class AskError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def folder() -> Path:
    d = browser.asks_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _file(rid: str) -> Path:
    return folder() / f"{rid}.json"


def _num(v) -> bool:
    """A usable timestamp (or none): a hand-edited file with at="yesterday" must not break every listing."""
    return v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v))


_parsed: dict[Path, tuple[tuple, dict | None]] = {}      # file -> (inode, mtime, size), its content: a request holds a screenshot


def _read(f: Path) -> dict | None:
    """A request file, parsed again only when the file changed (images of several 100 KB are parsed at every status poll)."""
    try:
        st = f.stat()
    except OSError:
        _parsed.pop(f, None)
        return None
    key = (st.st_ino, st.st_mtime_ns, st.st_size)
    hit = _parsed.get(f)
    if hit is None or hit[0] != key:
        hit = _parsed[f] = (key, browser_mcp.read(f))
    return dict(hit[1]) if hit[1] is not None else None


def _all() -> list[dict]:
    out = []
    files = list(folder().glob("*.json"))
    for gone in [f for f in _parsed if f not in files]:
        del _parsed[gone]
    for f in files:
        d = _read(f)
        if d and ID_RE.match(str(d.get("id") or "")) and _num(d.get("at")) and _num(d.get("decided_at")):
            out.append(d)
    return sorted(out, key=lambda d: d.get("at") or 0)


def public(d: dict) -> dict:
    return {k: d.get(k) for k in ("id", "session", "owner", "profile", "reason", "what", "at", "expires", "status", "note",
                                  "decided_at", "decided_by")}


def pending(owner: str | None = None, session: str | None = None) -> list[dict]:
    return [public(d) for d in _all() if d.get("status") == "pending"
            and (owner is None or d.get("owner") == owner) and (session is None or d.get("session") == session)]


def pending_for_profile(pid: str) -> bool:
    return any((d.get("profile") or browser.MAIN) == pid and d.get("status") == "pending" for d in _all())


def waiting(sid: str) -> int:
    return _counts.get(sid, 0)


def get(rid: str) -> dict | None:
    d = browser_mcp.read(_file(rid)) if ID_RE.match(rid or "") else None
    return public(d) if d else None


# ---- the person answers --------------------------------------------------------------------------------------------
HANDBACK = ("trail", "page", "picture")         # what Claude gets with the answer (pool.hand_back)


def decide(rid: str, action: str, by: str = "web", note: str = "", extra: dict | None = None) -> dict:
    if not ID_RE.match(rid or ""):
        raise AskError(404, "not_found", "No such request")
    if action not in ("done", "skip"):
        raise AskError(400, "bad_action", "done or skip")
    with browser_mcp.state_lock(folder()):
        d = browser_mcp.read(_file(rid))
        if not d:
            raise AskError(404, "not_found", "No such request")
        if d.get("status") != "pending":
            raise AskError(409, "decided", "This request is already answered")
        d.update({k: v for k, v in (extra or {}).items() if k in HANDBACK})
        d.update(status=action, note=(note or "")[:500], decided_by=by, decided_at=time.time())
        _seen[rid] = action                          # before the file: a scan in between must not announce it too
        browser_mcp.write_atomic(_file(rid), d)
    _done(d)
    _recount()
    bus.invalidate("browser", "sessions", "agents")
    return public(d)


def feed_action(rid: str, action: str, by: str, ev: dict) -> None:
    """A button of the request's Notifications event (web or Telegram): skip. "open" only opens the page."""
    if action != "skip":
        return
    try:
        decide(rid, "skip", by=by)
    except AskError as e:
        if e.status != 409:
            from .. import feed
            feed.update(ev["id"], resolve=True, resolution="The run stopped")


# ---- announcing ----------------------------------------------------------------------------------------------------
def _where(d: dict) -> tuple[str, str]:
    """(name shown, url of the live view)."""
    owner = str(d.get("owner") or "")
    path = browser.owner_path(owner)
    if owner.startswith("agent:"):
        from .. import agents
        name = path.rsplit("/", 1)[-1]
        with contextlib.suppress(Exception):
            name = agents.load(path).get("name") or name
        return name, (f"/settings/browser?session={d.get('session')}" if d.get("session") else "/settings/browser")
    name = "A session"
    try:
        from ..sessions import store
        m = store.read(str(d.get("session") or "")) if d.get("session") else None
        name = (m or {}).get("title") or name
    except Exception:  # noqa: BLE001
        pass
    return name, f"/settings/browser?session={d.get('session')}" if d.get("session") else "/settings/browser"


def _new(d: dict) -> None:
    name, url = _where(d)
    try:
        from .. import feed
        feed.post(f"{name} needs you in its browser", f"{d.get('reason') or ''}", "warning",
                  "agents" if str(d.get("owner", "")).startswith("agent:") else "system", url,
                  dedupe=f"human:{d['id']}", ref=f"human:{d['id']}",
                  agent=browser.owner_path(d["owner"]) if str(d.get("owner", "")).startswith("agent:") else None,
                  actions=[{"id": "open", "label": "Open the browser", "style": "primary"},
                           {"id": "skip", "label": "Skip", "style": "default"}])
    except Exception:  # noqa: BLE001 - the feed is a nicety
        log.exception("feed event for a browser request failed")
    _thread(d, f"Waiting for you in the browser: {d.get('reason') or WHAT.get(str(d.get('what')), 'a step')}")


def _done(d: dict) -> None:
    st = str(d.get("status") or "")
    try:
        from .. import feed
        feed.resolve(f"human:{d.get('id')}", DONE_TEXT.get(st, st), read=True if st in ("done", "skip") else None,
                     level="info" if st == "done" else "warning")
    except Exception:  # noqa: BLE001
        log.exception("feed event update for a browser request failed")
    _thread(d, f"Browser: {DONE_TEXT.get(st, st).lower()}" + (f" ({d['note']})" if d.get("note") else ""))


def _thread(d: dict, text: str) -> None:
    owner = str(d.get("owner") or "")
    if not owner.startswith("agent:"):
        return
    try:
        from .. import agents
        path = browser.owner_path(owner)
        if agents.exists(path):
            agents.post(path, "note", text, session=d.get("session") or "", ask=d.get("id"))
    except Exception:  # noqa: BLE001
        log.exception("agent thread message for a browser request failed")


def _running(sid: str) -> bool:
    from ..sessions import store
    m = store.read(sid) if sid else None
    return bool(m) and m.get("state") == "running" and store.runner_alive(sid, m)


def _recount() -> None:
    counts: dict[str, int] = {}
    for d in _all():
        if d.get("status") == "pending" and d.get("session"):
            counts[d["session"]] = counts.get(d["session"], 0) + 1
    _counts.clear()
    _counts.update(counts)


def scan() -> bool:
    """One watcher pass (blocking; in a thread). True when something changed."""
    now = time.time()
    changed = False
    items = _all()
    for d in items:
        rid, st = d["id"], d.get("status")
        if st == "pending" and now - float(d.get("at") or now) > ORPHAN_GRACE_S and not _running(d.get("session") or ""):
            with browser_mcp.state_lock(folder()):
                cur = browser_mcp.read(_file(rid)) or d
                if cur.get("status") == "pending":
                    cur = {**cur, "status": "expired", "decided_at": now}
                    browser_mcp.write_atomic(_file(rid), cur)
            d, st = cur, cur.get("status")
        prev = _seen.get(rid)
        if prev == st:
            if st != "pending" and now - float(d.get("decided_at") or d.get("at") or now) > KEEP_S:
                _file(rid).unlink(missing_ok=True)
                _seen.pop(rid, None)
            continue
        _seen[rid] = str(st)
        changed = True
        if st == "pending":
            _new(d)
        elif prev is not None or now - float(d.get("decided_at") or now) < 60:
            _done(d)
    if changed:
        _recount()
        bus.invalidate("browser", "sessions", "agents")
    return changed


def prime() -> None:
    """At startup: requests already announced are not announced again."""
    for d in _all():
        _seen[d["id"]] = str(d.get("status"))
    _recount()
