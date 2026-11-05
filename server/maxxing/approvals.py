"""Approvals: a turn of an agent with `approvals: true` waits for the user's Allow / Deny before a tool call.

The requests are files `<state>/approvals/<id>.json` written by the approval MCP server (approval_mcp.py, a child of
Claude Code, another process); this module lists them for the UI, writes the user's decision into them, and - from
the server's watcher (api/approvals.py, every POLL_S) - notices the new / finished ones: the agent's thread gets a
message, the bus topics "approvals" and "sessions" are invalidated, and a request whose session is no longer running
is marked "expired". Decided requests are kept KEEP_S for the record, then deleted.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from . import approval_mcp, config

log = logging.getLogger("maxxing.approvals")

ID_RE = re.compile(r"^[0-9a-f]{16}$")
DECISIONS = ("allow", "deny")
MESSAGE_MAX = 1000
KEEP_S = 86400.0                  # decided requests stay this long
ORPHAN_GRACE_S = 15.0             # a pending request of a session that is not running is expired after this
SHORT_MAX = 160


class ApprovalError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def folder() -> Path:
    return config.STATE / "approvals"


def _file(rid: str) -> Path:
    return folder() / f"{rid}.json"


def _redact(v: Any) -> Any:
    from . import logs
    if isinstance(v, str):
        return logs.redact(v)
    if isinstance(v, dict):
        return {k: _redact(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_redact(x) for x in v]
    return v


# keys that change nothing of what a tool does: a summary without them still shows the whole request
_MINOR = {"Bash": {"description", "timeout", "run_in_background"}, "Read": {"offset", "limit"}}


def summary(tool: str, inp: Any) -> tuple[str, bool]:
    """`short()` and whether it shows the whole request (False: cut, or other keys left out such as the content of
    a Write). Only a complete summary may be allowed from a one-tap button (feed, Telegram)."""
    inp = inp if isinstance(inp, dict) else {}
    for k in ("command", "file_path", "notebook_path", "path", "url", "pattern", "query", "prompt", "description"):
        if isinstance(inp.get(k), str) and inp[k].strip():
            text = " ".join(inp[k].split())
            rest = {o for o, v in inp.items() if o != k and v not in (None, "", [], {})} - _MINOR.get(tool, set())
            break
    else:
        text = json.dumps(inp, ensure_ascii=False) if inp else ""
        rest = set()
    from . import logs
    text = logs.redact(text)
    whole = len(text) <= SHORT_MAX and not rest
    text = text if len(text) <= SHORT_MAX else text[:SHORT_MAX - 1] + "…"
    return (f"{tool}: {text}" if text else tool), whole


def short(tool: str, inp: Any) -> str:
    """One line for a thread / a notification: "Bash: git push", "Write: /path/file"."""
    return summary(tool, inp)[0]


def public(d: dict) -> dict:
    return {"id": d.get("id"), "session": d.get("session") or "", "agent_path": d.get("agent_path") or "",
            "tool": d.get("tool") or "", "input": _redact(d.get("input") if isinstance(d.get("input"), dict) else {}),
            "summary": short(str(d.get("tool") or ""), d.get("input")), "at": d.get("at"),
            "expires": d.get("expires"), "status": d.get("status"), "message": d.get("message") or "",
            "decided_at": d.get("decided_at")}


def _all() -> list[dict]:
    try:
        files = list(folder().glob("*.json"))
    except OSError:
        return []
    out = []
    for f in files:
        d = approval_mcp.read(f)
        if d and ID_RE.match(str(d.get("id") or "")) and f.stem == d["id"]:
            out.append(d)
    out.sort(key=lambda d: d.get("at") or 0)
    return out


def pending(session: str | None = None) -> list[dict]:
    """Requests waiting for an answer (of one session when given), oldest first."""
    return [public(d) for d in _all() if d.get("status") == "pending" and (not session or d.get("session") == session)]


def _count(items: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in items:
        if d.get("status") == "pending" and d.get("session"):
            out[d["session"]] = out.get(d["session"], 0) + 1
    return out


def waiting(sid: str) -> int:
    """Requests of a session waiting for the user, as last seen by the watcher (in memory: cheap for lists)."""
    return _counts.get(sid, 0)


def get(rid: str) -> dict:
    d = approval_mcp.read(_file(rid)) if ID_RE.match(rid or "") else None
    if not d:
        raise ApprovalError(404, "not_found", "No such approval request")
    return d


def decide(rid: str, decision: str, message: str = "", by: str = "web") -> dict:
    """The user's answer. 409 when the request is no longer waiting (answered, timed out, session stopped)."""
    if decision not in DECISIONS:
        raise ApprovalError(400, "bad_decision", "decision: allow or deny")
    d = get(rid)
    if d.get("status") != "pending":
        raise ApprovalError(409, "not_pending", f"This request is already {d.get('status')}")
    d.update(status=decision, message=" ".join(str(message or "").split())[:MESSAGE_MAX], decided_at=time.time(),
             decided_by=by)
    approval_mcp.write_atomic(_file(rid), d)
    _seen[rid] = decision
    if _counts.get(d.get("session") or "", 0) > 0:
        _counts[d["session"]] -= 1
    _note(d)
    _invalidate()
    return public(d)


# ---- watcher (server) ----------------------------------------------------------------------------------
_seen: dict[str, str] = {}        # id -> last status seen by the watcher / set by decide()
_counts: dict[str, int] = {}      # session id -> pending requests (watcher)
_sig: dict[str, Any] = {"v": None}

NOTES = {"allow": "Allowed", "deny": "Denied", "timeout": "No answer in time, denied", "expired": "Expired (turn stopped)"}


def _invalidate() -> None:
    from . import bus
    bus.invalidate("approvals", "sessions")


def _post(d: dict, kind: str, text: str, **extra: Any) -> None:
    path = d.get("agent_path") or ""
    try:
        from . import agents
        if agents.exists(path):
            agents.post(path, kind, text, approval=d.get("id"), session=d.get("session") or "", **extra)
    except Exception:  # noqa: BLE001 - the thread is a nicety
        log.exception("agent thread message for an approval failed")


def _telegram(fn: str, *args: Any) -> None:
    """The older Telegram way (its own Allow / Deny message): only while the bridge has no `post_alert`, which then
    gets the request through its feed event instead (one message, not two). `approval_done` always: it only edits an
    older Allow / Deny message of that request (posted before the feed alerts), if there is one."""
    try:
        from .telegram import gateway
        if fn == "approval_done" or getattr(gateway, "post_alert", None) is None:
            getattr(gateway, fn)(*args)
    except Exception:  # noqa: BLE001 - Telegram is a nicety
        log.exception("telegram %s failed", fn)


def _agent_url(path: str) -> str:
    from . import agents
    p = agents.parse(path)
    return f"/agents/{p[0]}/{p[1]}/{p[2]}" if p else "/agents"


def _agent_name(path: str) -> str:
    try:
        from . import agents
        return agents.public(path)["display_name"]
    except Exception:  # noqa: BLE001
        return path.rsplit("/", 1)[-1] or "An agent"


CUT_NOTE = "Only part of the request is shown: open it to see all of it before allowing."


def _feed_new(d: dict) -> None:
    """A waiting request = a Notifications event with Allow / Deny (source `agents`), once per request. When its
    summary is not the whole request (cut, or the content of a Write left out), no one-tap Allow: Deny and Open (the
    request card shows everything)."""
    try:
        from . import feed
        path = d.get("agent_path") or ""
        text, whole = summary(str(d.get("tool") or ""), d.get("input"))
        acts = ([{"id": "allow", "label": "Allow", "style": "primary"}] if whole else
                [{"id": "open", "label": "Open", "style": "link"}])
        feed.post(f"{_agent_name(path)} is waiting for your OK", text if whole else f"{text}\n{CUT_NOTE}",
                  "warning", "agents", _agent_url(path), dedupe=f"approval:{d['id']}", ref=f"approval:{d['id']}",
                  agent=path or None, actions=acts + [{"id": "deny", "label": "Deny", "style": "danger"}])
    except Exception:  # noqa: BLE001 - the feed is a nicety here
        log.exception("feed event for an approval failed")


FEED_DONE = {"allow": "Allowed", "deny": "Denied", "timeout": "No answer in time, denied",
             "expired": "Expired (the run stopped)"}


def _feed_done(d: dict) -> None:
    try:
        from . import feed
        st = str(d.get("status") or "")
        how = FEED_DONE.get(st, st)
        if st in ("allow", "deny") and d.get("decided_by") == "telegram":
            how += " on Telegram"
        # answered = handled (read); no answer in time stays unread: the user may want to know what was missed
        feed.resolve(f"approval:{d.get('id')}", how, read=True if st in DECISIONS else None,
                     level="info" if st == "allow" else "warning")
    except Exception:  # noqa: BLE001
        log.exception("feed event update for an approval failed")


def feed_action(rid: str, action: str, by: str, ev: dict) -> None:
    """A button of the request's feed event (web or Telegram). Already answered: nothing to do, the event says how."""
    if action not in DECISIONS:
        return
    try:
        decide(rid, action, by=by)
    except ApprovalError as e:
        if e.status != 409:
            raise
        d = approval_mcp.read(_file(rid)) if ID_RE.match(rid or "") else None
        if d:
            _feed_done(d)                       # make sure the event shows the answer it already got
        else:
            from . import feed
            feed.update(ev["id"], resolve=True, resolution="Expired (the run stopped)")


def _note(d: dict) -> None:
    st = str(d.get("status") or "")
    text = f"{NOTES.get(st, st)}: {short(str(d.get('tool') or ''), d.get('input'))}"
    if st == "deny" and d.get("message"):
        text += f" ({d['message']})"
    _post(d, "note", text, status=st)
    _feed_done(d)
    _telegram("approval_done", str(d.get("id") or ""), st)


def _signature() -> Any:
    try:
        st = folder().stat()
        return (st.st_mtime_ns, sum(1 for _ in folder().glob("*.json")))
    except OSError:
        return None


def _running(sid: str) -> bool:
    from .sessions import store
    m = store.read(sid) if sid else None
    return bool(m) and m.get("state") == "running" and store.runner_alive(sid, m)


def scan(force: bool = False) -> bool:
    """One watcher pass (blocking; run it in a thread). Returns True when something changed."""
    now = time.time()
    sig = _signature()
    changed = sig != _sig["v"]
    _sig["v"] = sig
    items = _all() if (changed or force or any(s == "pending" for s in _seen.values())) else []
    if not items and not changed and not force:
        return False
    final: list[dict] = []
    for d in items:
        rid, st = d["id"], d.get("status")
        if st == "pending" and now - float(d.get("at") or now) > ORPHAN_GRACE_S and not _running(d.get("session") or ""):
            d = {**d, "status": "expired", "decided_at": now}          # its turn is gone: nobody waits for it
            approval_mcp.write_atomic(_file(rid), d)
            st = "expired"
        final.append(d)
        prev = _seen.get(rid)
        if prev == st:
            if st != "pending" and now - float(d.get("decided_at") or d.get("at") or now) > KEEP_S:
                _file(rid).unlink(missing_ok=True)
            continue
        _seen[rid] = str(st)
        changed = True
        if st == "pending":
            _post(d, "approval", short(str(d.get("tool") or ""), d.get("input")), status="pending")
            _feed_new(d)
            _telegram("notify_approval", d)
        elif prev is not None:                  # decided elsewhere (timeout, expired): our own decide() noted it
            _note(d)
    live = {d["id"] for d in final}
    for rid in [r for r in _seen if r not in live]:
        _seen.pop(rid, None)
    _counts.clear()
    _counts.update(_count(final))
    if changed:
        _invalidate()
    return changed


def prime() -> None:
    """At startup: what is already there is not new (no repeated thread messages after a restart)."""
    now = time.time()
    for d in _all():
        if d.get("status") != "pending":
            _feed_done(d)                       # answered or expired while the server was down: its event says so
        if d.get("status") != "pending" and now - float(d.get("decided_at") or d.get("at") or now) > KEEP_S:
            _file(d["id"]).unlink(missing_ok=True)
        else:
            _seen[d["id"]] = str(d.get("status"))
    _counts.clear()
    _counts.update(_count(_all()))
    try:                                        # the runner's MCP config files of old sessions
        for f in (folder() / "config").glob("*.json"):
            if now - f.stat().st_mtime > KEEP_S * 7:
                f.unlink(missing_ok=True)
    except OSError:
        pass
    _sig["v"] = _signature()
