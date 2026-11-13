"""Approvals: a turn of an agent with `approvals: true`, or of any session whose permission mode is `ask`, waits for
the user's Allow / Deny before a tool call.

The requests are files `<state>/approvals/<id>.json` written by the approval MCP server (approval_mcp.py, a child of
Claude Code, another process); this module lists them for the UI, writes the user's decision into them, and - from
the server's watcher (api/approvals.py, every POLL_S) - notices the new / finished ones: the agent's thread gets a
message, the bus topics "approvals" and "sessions" are invalidated, and a request whose session is no longer running
is marked "expired". Decided requests are kept KEEP_S for the record, then deleted.
"""
from __future__ import annotations

import json
import logging
import os
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
    for k in ("command", "file_path", "notebook_path", "path", "url", "host", "pattern", "query", "prompt", "description"):
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


_EDITS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
_READS = ("Read", "Glob", "Grep", "LS", "NotebookRead")


def always_rule(d: dict) -> str:
    """The Claude Code rule an "Always allow" of this request adds to its topic ("" = not offered: an agent's
    request - agents have their own tool lists -, a cut request, a command of several lines). Narrow on purpose:
    the exact command, the exact file, the site's domain; another tool = the tool (an MCP tool, WebSearch...)."""
    if d.get("agent_path") or d.get("clipped"):
        return ""
    tool = str(d.get("tool") or "")
    inp = d.get("input") if isinstance(d.get("input"), dict) else {}
    from . import logs
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", tool) or any(
            isinstance(v, str) and logs.redact(v) != v for v in inp.values()):   # a secret in it: never in a rule
        return ""
    try:                                             # a lone surrogate: the topic file could not store the rule
        json.dumps(inp, ensure_ascii=False).encode("utf-8")
    except (UnicodeEncodeError, ValueError, RecursionError):
        return ""
    if tool == "Bash":
        cmd = inp.get("command")
        # "*" and a final ":*" are wildcards in Bash rules: the rule would match more than what was allowed
        if not isinstance(cmd, str) or not cmd.strip() or any(c in cmd.strip() for c in "\n\r\0*") or len(cmd) > 400:
            return ""
        return f"Bash({cmd.strip()})"
    if tool in _EDITS:
        p = inp.get("file_path") or inp.get("notebook_path")
        # Edit rules are gitignore patterns: "?", "[...]", "{...}", "!", "\\", "#", a final "/" (a whole folder)
        # or a "." / ".." segment would allow more than this one file; trailing spaces are dropped from a pattern
        # (the rule would cover "a" for "a "); a NUL or a rule over RULE_MAX could not be saved in the topic
        from .workspace import RULE_MAX
        if not isinstance(p, str) or not p.startswith("/") or any(c in p for c in "\n\r\t\0()*?[]{}!\\#") or \
                p.endswith("/") or p != p.rstrip() or len(f"Edit(/{p})") > RULE_MAX or \
                any(seg in (".", "..") for seg in p.split("/")):
            return ""
        return f"Edit(/{p})"                        # "//abs": an absolute path; Edit rules cover Write too
    if tool == "WebFetch":
        from urllib.parse import urlsplit
        try:
            host = urlsplit(str(inp.get("url") or "")).hostname or ""
        except ValueError:                           # "http://[::1": not a URL, no rule
            return ""
        return f"WebFetch(domain:{host})" if re.fullmatch(r"[a-z0-9.-]{1,253}", host) else ""
    if tool in ("Task", "Agent", "Skill"):           # the subagent / skill runs under the same rules: ask each time
        return ""
    if tool in ("ExitPlanMode", "AskUserQuestion"):  # each plan / question is read by the user: never allowed for good
        return ""
    if tool in _READS:                               # the bare tool would allow reading any file: ask each time
        return ""
    return tool


def topic_of_session(sid: str) -> str:
    """The topic path of a session ("" for an agent's session or an unknown one)."""
    from . import agents
    from .sessions import store
    m = store.read(sid) if sid else None
    path = str((m or {}).get("path") or "")
    return "" if not path or agents.is_agent_path(path) else path


def public(d: dict) -> dict:
    return {"id": d.get("id"), "session": d.get("session") or "", "agent_path": d.get("agent_path") or "",
            "always_rule": always_rule(d),
            "tool": d.get("tool") or "", "input": _redact(d.get("input") if isinstance(d.get("input"), dict) else {}),
            "summary": short(str(d.get("tool") or ""), d.get("input")), "at": d.get("at"),
            "expires": d.get("expires"), "status": d.get("status"), "message": d.get("message") or "",
            "decided_at": d.get("decided_at"), "clipped": bool(d.get("clipped")), "kind": d.get("kind") or ""}


_parsed: dict[str, tuple[tuple[int, int, int], dict | None]] = {}   # path -> ((inode, mtime_ns, size), content)


def _all() -> list[dict]:
    """Every request. A file is parsed again only when it changed: the watcher calls this every 2 s while one
    request waits, and decided ones stay for a day."""
    try:
        files = [(e.path, e.name, e.stat()) for e in os.scandir(folder()) if e.name.endswith(".json") and e.is_file()]
    except OSError:
        return []
    out = []
    for path, name, st in files:
        key = (st.st_ino, st.st_mtime_ns, st.st_size)
        hit = _parsed.get(path)
        d = hit[1] if hit and hit[0] == key else approval_mcp.read(Path(path))
        _parsed[path] = (key, d)
        if d and ID_RE.match(str(d.get("id") or "")) and name[:-5] == d["id"]:
            out.append(dict(d))
    for path in set(_parsed) - {p for p, _, _ in files}:
        _parsed.pop(path, None)
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


_lock = config.ProcessLock("approvals")     # read-check-write of a request (decide, the watcher's expiry)


def decide(rid: str, decision: str, message: str = "", by: str = "web", always: bool = False) -> dict:
    """The user's answer. 409 when the request is no longer waiting (answered, timed out, session stopped).
    `always` (with allow): the request's rule (always_rule) is added to its topic first, so the next turns of the
    topic's sessions run it without asking (the running turn still asks for other calls of it)."""
    if decision not in DECISIONS:
        raise ApprovalError(400, "bad_decision", "decision: allow or deny")
    if always:
        if decision != "allow":
            raise ApprovalError(400, "bad_decision", "always: only with allow")
        d = get(rid)
        rule, topic = always_rule(d), topic_of_session(str(d.get("session") or ""))
        if not rule or not topic:
            raise ApprovalError(400, "no_rule", "This request cannot be allowed for good: allow it once")
        if d.get("status") == "pending":
            from . import workspace
            try:
                workspace.add_topic_allowed_tool(topic, rule)
            except workspace.WorkspaceError as e:
                raise ApprovalError(e.status, e.code, e.message) from None
    # an agent's settings change that can no longer be applied as its card shows it (agent gone, a value changed
    # since): the Allow is refused with the reason and the request closed (denied, `stale`), nothing applied
    problem = ""
    if decision == "allow":
        d = get(rid)
        if d.get("kind") == "agent_change" and d.get("status") == "pending":
            from . import agents
            problem = agents.change_problem(d)
    with _lock:                                 # web, Telegram and the feed at once: one answer, the others get 409
        d = get(rid)
        if d.get("status") != "pending":
            raise ApprovalError(409, "not_pending", f"This request is already {d.get('status')}")
        if decision == "allow" and d.get("clipped"):
            raise ApprovalError(409, "clipped", CLIPPED_NOTE)
        if problem:
            d.update(status="deny", stale=True, message=problem[:MESSAGE_MAX], decided_at=time.time(), decided_by=by)
            approval_mcp.write_atomic(_file(rid), d)
            _seen[rid] = "deny"
        else:
            d.update(status=decision, message=" ".join(str(message or "").split())[:MESSAGE_MAX], decided_at=time.time(),
                     decided_by=by)
            approval_mcp.write_atomic(_file(rid), d)
            _seen[rid] = decision
    if _counts.get(d.get("session") or "", 0) > 0:
        _counts[d["session"]] -= 1
    if d.get("kind") == "agent_change":
        from . import agents
        agents.change_decided(d)
    _note(d)
    _invalidate()
    if problem:
        raise ApprovalError(409, "stale_change", problem)
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


def requester(d: dict) -> tuple[str, str]:
    """(who asks, where to answer): the agent and its page, else the session (its title) in the Sessions page."""
    path = d.get("agent_path") or ""
    if path:
        return _agent_name(path), _agent_url(path)
    sid = str(d.get("session") or "")
    try:
        from .sessions import store
        m = store.read(sid) if sid else None
    except Exception:  # noqa: BLE001
        m = None
    title = " ".join(str((m or {}).get("title") or "").split())[:80] or "Claude"
    from urllib.parse import quote
    url = f"/sessions?path={quote(str(m.get('path') or ''), safe='')}&session={sid}" if m else "/sessions"
    return title, url


def _agent_name(path: str) -> str:
    try:
        from . import agents
        return agents.public(path)["display_name"]
    except Exception:  # noqa: BLE001
        return path.rsplit("/", 1)[-1] or "An agent"


CUT_NOTE = "Only part of the request is shown: open it to see all of it before allowing."
# the request is too long to be kept whole (approval_mcp.clip): Allow would run what nobody can see
CLIPPED_NOTE = "This request is too long to be shown whole: it can only be denied. Ask the agent for smaller steps."


def _feed_new(d: dict) -> bool | None:
    """A waiting request = a Notifications event with Allow / Deny (source `agents`), once per request. When its
    summary is not the whole request (cut, or the content of a Write left out), no one-tap Allow: Deny and Open (the
    request card shows everything). True: posted now, False: it already was, None: the feed failed."""
    try:
        from . import feed
        path = d.get("agent_path") or ""
        text, whole = summary(str(d.get("tool") or ""), d.get("input"))
        whole = whole and not d.get("clipped")
        acts = ([{"id": "allow", "label": "Allow", "style": "primary"}] if whole else
                [{"id": "open", "label": "Open", "style": "link"}])
        note = CLIPPED_NOTE if d.get("clipped") else CUT_NOTE
        name, url = requester(d)
        return feed.post(f"{name} is waiting for your OK", text if whole else f"{text}\n{note}",
                  "warning", "agents" if path else "sessions", url, dedupe=f"approval:{d['id']}", ref=f"approval:{d['id']}",
                  agent=path or None, actions=acts + [{"id": "deny", "label": "Deny", "style": "danger"}]) is not None
    except Exception:  # noqa: BLE001 - the feed is a nicety here
        log.exception("feed event for an approval failed")
        return None


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
        change = d.get("kind") == "agent_change"         # outlives its turn, until it expires (agents.request_change)
        if st == "pending" and (now > float(d.get("expires") or now) if change else
                                now - float(d.get("at") or now) > ORPHAN_GRACE_S and not _running(d.get("session") or "")):
            with _lock:                         # its turn is gone: nobody waits for it (unless answered meanwhile)
                cur = approval_mcp.read(_file(rid)) or d
                if cur.get("status") == "pending":
                    cur = {**cur, "status": "expired", "decided_at": now}
                    approval_mcp.write_atomic(_file(rid), cur)
            d, st = cur, cur.get("status")
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
    """At startup: what is already there is not new (no repeated thread messages after a restart), except a request
    written while the server was down (its turn survives restarts): announced once, when it has no feed event yet."""
    now = time.time()
    for d in _all():
        if d.get("status") != "pending":
            _feed_done(d)                       # answered or expired while the server was down: its event says so
        elif (_running(d.get("session") or "") or d.get("kind") == "agent_change") and _feed_new(d) is not False:
            _post(d, "approval", short(str(d.get("tool") or ""), d.get("input")), status="pending")
            _telegram("notify_approval", d)
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
