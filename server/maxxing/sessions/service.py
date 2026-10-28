"""Sessions service - the only entry point the rest of the server uses (docs/dev/INTERNALS.md).

Blocking functions (file I/O, waiting for a runner) are plain functions: call them through
`asyncio.to_thread` from async code. The turn-end watcher (`start_watcher`) runs on the event loop.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import shutil
import signal
import time
from pathlib import Path
from typing import Any, Callable

from .. import bus, config, voice, workspace
from . import clip, normalize, spawn, store, titles, voicejobs
from .runner import SUMMARY_PROMPT  # noqa: F401  (also used by the runner's automatic compaction)

log = logging.getLogger("maxxing.sessions")

READ_CHUNK = 4 * 1024 * 1024          # max bytes normalised per read_events call
BACK_CHUNK = 256 * 1024               # backward reading step
BACK_SCAN_MAX = 64 * 1024 * 1024      # max bytes scanned by one read_back call (then more_before)
TASK_START_SCAN_MAX = 32 * 1024 * 1024  # how far back read_back looks for the task_started of a task in its page
STOP_WAIT_S = 10.0
KNOWN_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5-20251001", "claude-fable-5-1"]
_MODEL_RE = re.compile(rb'"model"\s*:\s*"(claude-[a-z0-9.-]+)"')
# a model id given by a client: passed to `claude --model`, so no option, no NUL, no control character
_MODEL_ID = re.compile(r"[A-Za-z0-9._:@/\[\]][A-Za-z0-9._:@/\[\]-]{0,99}")


def _check_model(model: str | None) -> str:
    model = (model or "").strip()
    if model and not _MODEL_ID.fullmatch(model):
        raise SessionError(400, "bad_model", "Invalid model id")
    return model
_WINDOW_RE = re.compile(rb'"(claude-[a-z0-9.-]+)"\s*:\s*\{[^{}]*?"contextWindow"\s*:\s*(\d+)')


class SessionError(Exception):
    """Error carrying an HTTP status and an API code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---- public representation -----------------------------------------------------------------
def _effective(meta: dict) -> dict:
    """Repairs a session whose runner died while 'running' (crash, reboot, killed unit)."""
    sid = meta["id"]
    if meta.get("state") != "running" or store.runner_alive(sid, meta):
        return meta
    try:
        with store.edit(sid) as m:
            if m.get("state") == "running" and not store.runner_alive(sid, m):
                if spawn.unit_end_reason(m.get("unit")) == "oom":
                    error = "The turn was stopped: the server ran out of memory."
                    text = ("The turn was stopped: the server ran out of memory (a command used too much RAM; "
                            "`journalctl -k | grep -i oom` shows which). Ask for a lighter way: a lower resolution, "
                            "a render in parts, fewer inputs at once.")
                else:
                    error = "The turn process ended unexpectedly."
                    text = "The turn process ended unexpectedly (server reboot or crash)."
                m.update(state="error", pid=None, spawned_at=None, updated=time.time(), error=error)
                store.append_log(sid, {"type": "mx_note", "level": "error", "at": time.time(), "text": text})
            return dict(m)
    except KeyError:
        return meta


def _waiting_items(m: dict) -> list:
    """Messages really waiting behind a turn. While a turn is starting (state running, the runner has not
    popped its item yet: no pid), the head of the queue is the message being sent, not a queued one. Same for a
    message held at the head during an idle compaction: it was sent (shown in the thread), the summary runs first."""
    q = m.get("queue") or []
    if not isinstance(q, list):
        return []
    if q and m.get("state") == "running" and not m.get("pid"):
        q = q[1:]                                  # the head is being sent (held or not): drop it once, not twice
    return [x for x in q if not (isinstance(x, dict) and x.get("held"))]


def _waiting(m: dict) -> int:
    return len(_waiting_items(m))


QUEUE_PREVIEW_CHARS = 280
QUEUE_PREVIEW_ITEMS = 20       # sent with every session of the list and every live update: the stack shows the last


def _queue_preview(m: dict) -> list[dict]:
    """What the queue stack shows for each waiting message, whoever queued it (another tab or device, Telegram,
    a cron, the server itself): the start of the text, how many files, where it comes from."""
    out = []
    for q in _waiting_items(m)[-QUEUE_PREVIEW_ITEMS:]:
        if not isinstance(q, dict):
            continue
        att = q.get("attachments")
        out.append({"text": str(q.get("text") or "")[:QUEUE_PREVIEW_CHARS],
                    "attachments": len(att) if isinstance(att, list) else 0,
                    "source": str(q.get("source") or "web"), "kind": str(q.get("kind") or "user"),
                    **({"voice": True} if q.get("voice") else {})})
    return out


def _num(v: object) -> float:
    """A number from a session file that may have been edited by hand (string, null, junk -> 0)."""
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def public(meta: dict) -> dict:
    """Internal meta -> API.md Session."""
    m = _effective(meta)
    finished, seen = _num(m.get("finished_at")), _num(m.get("seen_at"))
    return {"id": m["id"], "title": m.get("title") or "Untitled", "path": m.get("path") or "",
            "state": m.get("state") or "idle", "queue": _waiting(m), "queue_items": _queue_preview(m),
            "created": m.get("created"), "updated": m.get("updated") or m.get("created"),
            "turns": int(_num(m.get("turns"))), "cost_usd": round(_num(m.get("cost_usd")), 4),
            "model": m.get("model") or "", "real_model": m.get("real_model") or None,
            "context_tokens": m.get("context_tokens"), "context_window": _context_window(m),
            "archived": bool(m.get("archived")), "favorite": bool(m.get("favorite")),
            "notify": bool(m.get("notify")), "source": m.get("source") or "web", "cron": bool(m.get("cron")),
            "unread": bool(finished) and finished > seen and m.get("state") != "running",
            "last_text": m.get("last_text") or "", "error": m.get("error") or None,
            "plan_mode": bool(m.get("plan_mode")), "plan_ready": bool(m.get("plan_ready")),
            "permission_mode": m.get("permission_mode") or ""}


_no_window: set[str] = set()      # sessions whose log has no contextWindow (do not rescan on every list)


def _context_window(m: dict) -> int | None:
    """Window of the session's model. Sessions older than this field are filled once from the last
    result of their log (Claude Code reports `modelUsage[..].contextWindow`, e.g. 1000000)."""
    cw = m.get("context_window")
    if cw or not m.get("turns") or m["id"] in _no_window or m.get("state") == "running":
        return cw or None
    found = None
    try:
        size = store.log_size(m["id"])
        lines, _ = read_raw(m["id"], max(0, size - 256 * 1024), 256 * 1024 + 1)
        for line in reversed(lines):
            if '"result"' in line and '"modelUsage"' in line:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("type") == "result":
                    store.record_windows(ev)
                    found = store.context_window_of(ev, m.get("real_model"))
                    break
    except OSError:
        pass
    if not found:
        _no_window.add(m["id"])
        return None
    try:
        with store.edit(m["id"]) as cur:
            cur.setdefault("context_window", found)
    except (KeyError, OSError):
        pass
    return found


def _require(sid: str) -> dict:
    m = store.read(sid) if store.is_valid_id(sid) else None
    if m is None:
        raise SessionError(404, "not_found", "Session not found")
    return m


# ---- queries -------------------------------------------------------------------------------
def list_sessions(path: str | None = None, archived: bool | None = None) -> list[dict]:
    out = []
    ids = store.list_ids()
    store.forget_cached(set(ids))
    for sid in ids:
        m = store.read_cached(sid)
        if m is None or (path is not None and (m.get("path") or "") != path):
            continue
        if archived is not None and bool(m.get("archived")) != archived:
            continue
        out.append(public(m))
    return sorted(out, key=lambda s: s.get("updated") or 0, reverse=True)


def session_exists(sid: str) -> bool:
    """The session's file is there (get_session may still return None: unreadable just now)."""
    return store.is_valid_id(sid) and store.meta_path(sid).exists()


def get_session(sid: str) -> dict | None:
    m = store.read_cached(sid) if store.is_valid_id(sid) else None
    return public(m) if m else None


# ---- turns ---------------------------------------------------------------------------------
def _item(text: str, attachments: list[str] | None, source: str, kind: str = "user", **extra: Any) -> dict:
    return {"text": text, "attachments": list(attachments or []), "source": source, "kind": kind,
            "at": time.time(), **extra}


def _check_attachments(paths: list[str] | None) -> list[str]:
    out = []
    for p in paths or []:
        pp = Path(str(p))
        if not pp.is_absolute() or not pp.is_file():
            raise SessionError(400, "bad_attachment", f"Attachment not found: {p}")
        out.append(str(pp))
    return out


HANDOFF_HOLD_S = 600.0               # a hand-off summary that takes longer no longer holds the new session's queue


def _handoff_held(m: dict) -> bool:
    """A continuation waiting for its hand-off summary (meta `handoff_pending` = when it was created): messages
    sent to it are queued behind the summary seed, for HANDOFF_HOLD_S at most (a summary that never comes - its
    runner died - can never keep them stuck)."""
    pending = _num(m.get("handoff_pending"))
    return bool(pending) and time.time() - pending < HANDOFF_HOLD_S


def _enqueue(sid: str, item: dict, *, reset_cron: bool = False) -> bool:
    """Append to the queue and start a runner if none is alive. Returns True when queued behind
    a running turn (or behind a hand-off summary that is coming)."""
    with store.edit(sid) as m:
        m.setdefault("queue", []).append(item)
        m["updated"] = time.time()
        if reset_cron:                    # a cron session you talk to becomes a normal one
            m["cron"], m["archived"] = False, False
        busy = m.get("state") == "running" and store.runner_alive(sid, m)
        held = not busy and _handoff_held(m)     # runner._handoff puts the seed first and starts it
        if not busy and not held:                # pid=None: a dead runner's pid is never signalled (it may be reused)
            m.update(state="running", spawned_at=time.time(), error=None, pid=None)
        busy = busy or held
    if not busy:
        _spawn(sid)
    bus.invalidate("sessions", "workspace")
    return busy


def _spawn(sid: str) -> None:
    try:
        unit = spawn.start(sid)
        store.update(sid, unit=unit)
    except Exception as e:
        log.exception("spawn failed for %s", sid)
        store.update(sid, state="error", spawned_at=None, error=f"Could not start the turn: {e}"[:300])
        store.append_log(sid, {"type": "mx_note", "level": "error", "at": time.time(),
                               "text": f"Could not start the turn: {e}"[:500]})


def _default_title(path: str, message: str | None) -> str:
    first = titles.provisional(message or "")
    if first:
        return first
    return f"Session {len(list_sessions(path)) + 1}"


def create_session(path: str, message: str | None = None, title: str | None = None,
                   model: str | None = None, attachments: list[str] | None = None,
                   source: str = "web", notify: bool = False, cron: bool = False,
                   env: dict | None = None, timeout_s: int | None = None, plan_mode: bool = False,
                   permission_mode: str = "", auto_title: bool = False, voice_path: str | None = None) -> dict:
    """`auto_title`: `title` was made from the first message by the caller (Telegram) - still worth a short title."""
    try:
        p = workspace.normalize_path(path)
        workspace.topic_dir(p)
    except ValueError as e:
        raise SessionError(400, "bad_path", str(e)) from None
    files = _check_attachments(attachments)
    audio = _check_voice(voice_path)
    given = (title or "").strip()[:120]
    model = _check_model(model)
    meta = store.new_meta(p, given or _default_title(p, message), model=model or "",
                          source=source, notify=notify, cron=cron, env=env, timeout_s=timeout_s, plan_mode=plan_mode,
                          permission_mode=permission_mode)
    automatic, has_text = auto_title or not given, bool((message or "").strip())
    if automatic and not has_text:
        meta["title_auto"] = meta["title"]       # short title on the first message (titles.first_message)
    store.create(meta)
    if audio:
        _enqueue_voice(meta["id"], _item((message or "").strip(), files, source), audio)
    elif (message or "").strip() or files:
        _enqueue(meta["id"], _item((message or "").strip(), files, source))
    if automatic and has_text:
        titles.schedule(meta["id"], meta["title"], message or "")   # short title in the background
    bus.invalidate("sessions", "workspace")
    return get_session(meta["id"]) or public(meta)


def _voice_paths(item: dict) -> list[str]:
    return [str(v["path"]) for v in item.get("voice") or [] if isinstance(v, dict) and v.get("path")]


def _drop_voice_jobs(sid: str, *items: dict) -> None:
    """Voice messages removed from the queue (Stop, Clear, Edit): their transcription is no longer needed."""
    ids = {v.get("id") for x in items for v in x.get("voice") or [] if isinstance(v, dict)}
    if not ids:
        return
    with store.edit(sid) as m:
        jobs = m.get("voice_jobs")
        if isinstance(jobs, dict):
            for j in ids:
                jobs.pop(j, None)


def _check_voice(path: str | None) -> str | None:
    """The audio of a voice message sent directly: an existing file under an attachments/ folder of the workspace
    (the transcription remuxes it in place), and a transcription engine that is ready."""
    if not path:
        return None
    pp = Path(str(path))
    if not pp.is_absolute() or not pp.is_file():
        raise SessionError(400, "bad_attachment", f"Voice message not found: {path}")
    pp = pp.resolve()
    try:
        rel = pp.relative_to(config.workspace().resolve())
    except ValueError:
        rel = None
    if rel is None or "attachments" not in rel.parts[:-1]:
        raise SessionError(400, "bad_attachment", f"Voice message outside the workspace attachments: {path}")
    ready, reason = voice.readiness()
    if not ready:
        raise SessionError(409, "voice_off", f"Voice transcription is not ready ({reason}): Settings -> Voice")
    return str(pp)


def _enqueue_voice(sid: str, item: dict, audio: str, *, reset_cron: bool = False) -> bool:
    """Queue a voice message and start its transcription (the runner waits for it before the turn)."""
    with store.edit(sid) as m:
        job = voicejobs.new_job(m, audio)
    item["voice"] = [job]
    queued = _enqueue(sid, item, reset_cron=reset_cron)
    voicejobs.submit(sid, job["id"], audio)
    return queued


def send_message(sid: str, text: str, attachments: list[str] | None = None, source: str = "web",
                 hud: bool = False, voice_path: str | None = None, ref: str | None = None) -> dict:
    """`ref`: an id the caller (Telegram) finds again in the meta of the turn that ran this message
    (`turn_refs` while it runs, `last_turn.refs` once it ended; see live_refs)."""
    _require(sid)
    files = _check_attachments(attachments)
    audio = _check_voice(voice_path)
    if not (text or "").strip() and not files and not audio:
        raise SessionError(400, "empty", "Empty message")
    extra: dict[str, Any] = {"hud": True} if hud else {}
    if ref:
        extra["refs"] = [str(ref)]
    if text.strip():
        titles.first_message(sid, text.strip())
    item = _item(text.strip(), files, source, **extra)
    if audio:
        queued = _enqueue_voice(sid, item, audio, reset_cron=source != "cron")
    else:
        queued = _enqueue(sid, item, reset_cron=source != "cron")
    return {"queued": queued, "session": get_session(sid)}


def clear_queue(sid: str) -> dict:
    _require(sid)
    with store.edit(sid) as m:
        dropped = [x for x in m.get("queue") or [] if isinstance(x, dict)]
        m["queue"], m["updated"] = [], time.time()
    _drop_voice_jobs(sid, *dropped)
    bus.invalidate("sessions")
    return get_session(sid) or {}


def hide_message(sid: str, at: float, hidden: bool = True) -> None:
    """Hide (or show again) the user message logged at `at`: an `mx_hide` line is appended to the log, the UI
    drops that message's rows. Nothing is erased and Claude's own thread is not touched. 404 when no user message
    has that time; nothing is written when the message is already in that state."""
    _require(sid)
    found, state = False, False
    try:
        with open(store.log_path(sid), "rb") as f:
            for raw in f:
                if b'"mx_user"' not in raw and b'"mx_hide"' not in raw:
                    continue
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if ev.get("type") == "mx_user" and ev.get("at") == at:
                    found = True
                elif ev.get("type") == "mx_hide" and ev.get("ref") == at:
                    state = ev.get("hidden") is not False
    except OSError:
        pass
    if not found:
        raise SessionError(404, "not_found", "Message not found")
    if state == bool(hidden):
        return
    store.append_log(sid, {"type": "mx_hide", "ref": at, "hidden": bool(hidden), "at": time.time()})


def stop(sid: str) -> None:
    """Clear the queue and abort the running turn (blocks up to ~10 s for the runner to settle). A message held
    behind an idle-compaction summary (`held`) stays queued: only the summary is cancelled."""
    _require(sid)
    with store.edit(sid) as m:
        dropped = [x for x in m.get("queue") or [] if not x.get("held")]
        m["queue"] = [x for x in m.get("queue") or [] if x.get("held")]
        turns0, running = int(m.get("turns") or 0), m.get("state") == "running"
    _drop_voice_jobs(sid, *dropped)
    if not running:
        bus.invalidate("sessions")
        return
    signalled: set[int] = set()
    deadline = time.time() + STOP_WAIT_S
    m = store.read(sid) or {}
    while time.time() < deadline:
        m = store.read(sid) or {}
        if m.get("state") != "running" or int(m.get("turns") or 0) > turns0:
            break
        pid = int(m.get("pid") or 0)
        # Only a runner that holds the run lock: the pid of a dead one (OOM, kill -9) may belong to another process.
        if pid and pid not in signalled and store.runner_alive(sid, {}):
            _signal(pid, signal.SIGTERM)
            signalled.add(pid)
        if not store.runner_alive(sid, m):
            break
        time.sleep(0.2)
    else:
        spawn.stop_unit(m.get("unit"))
        if store.runner_alive(sid, {}):           # still holding the lock: the signalled runner is alive
            for pid in signalled:
                _signal(pid, signal.SIGKILL)
    with store.edit(sid) as m:
        if m.get("state") == "running" and not store.runner_alive(sid, {}):
            m.update(state="idle", pid=None, spawned_at=None, updated=time.time())
            store.append_log(sid, {"type": "mx_note", "text": "Stopped.", "level": "warn", "at": time.time()})
    bus.invalidate("sessions", "workspace")


def _user_items(m: dict) -> tuple[list[int], list[dict]]:
    """Indexes of the queued user messages (not the head while a turn is starting), and the queue."""
    q = m.get("queue") or []
    head = 1 if q and m.get("state") == "running" and not m.get("pid") else 0
    return [i for i, x in enumerate(q) if i >= head and (x.get("kind") or "user") == "user"], q


def take_queue(sid: str) -> dict:
    """Edit: removes the user messages waiting in the queue and returns them, so the composer can show
    them for editing (resent as a normal message afterwards). -> {messages:[{text, attachments}], session}
    A voice message comes back as its transcript when it is ready, otherwise as its audio file attached."""
    _require(sid)
    with store.edit(sid) as m:
        idx, q = _user_items(m)
        mine = [q[i] for i in idx]
        m["queue"] = [x for i, x in enumerate(q) if i not in set(idx)]
        m["updated"] = time.time()
        jobs = m.get("voice_jobs") if isinstance(m.get("voice_jobs"), dict) else {}
        out = []
        for x in mine:
            texts, files = [x.get("text") or ""], list(x.get("attachments") or [])
            for v in x.get("voice") or []:
                job = jobs.get(v.get("id")) if isinstance(v, dict) else None
                if isinstance(job, dict) and job.get("state") == "done" and job.get("text"):
                    texts.append(str(job["text"]))
                elif isinstance(v, dict) and v.get("path"):
                    files.append(str(v["path"]))
            out.append({"text": "\n\n".join(t for t in texts if t.strip()), "attachments": files})
    _drop_voice_jobs(sid, *mine)
    bus.invalidate("sessions")
    return {"messages": out, "session": get_session(sid)}


def steer(sid: str) -> dict:
    """Steer: the messages waiting in the queue become ONE message that runs right now. The running turn
    is cut short (SIGUSR1: the runner ends it and continues with the head of the queue in the same Claude
    thread, so nothing is lost); the prompt tells Claude it was interrupted and should go on with it.
    The turn targeted is recorded (steer_turn = turn_id) so a late signal never hits another turn; a
    compact / handoff turn is not interrupted (the message just runs right after it).
    -> {steered: bool, interrupted: bool, session}"""
    _require(sid)
    with store.edit(sid) as m:
        idx, q = _user_items(m)
        # Only while a turn is really in progress (the runner popped its item and set its pid).
        if m.get("state") != "running" or not m.get("pid") or not idx:
            return {"steered": False, "interrupted": False, "session": get_session(sid)}
        mine = [q[i] for i in idx]
        merged = _item("\n\n".join(x["text"] for x in mine if x.get("text")),
                       [a for x in mine for a in x.get("attachments") or []],
                       mine[-1].get("source") or "web", steer=True,
                       **({"voice": [v for x in mine for v in x.get("voice") or []]}
                          if any(x.get("voice") for x in mine) else {}),
                       **({"hud": True} if all(x.get("hud") for x in mine) else {}),
                       **({"plan_approved": True} if any(x.get("plan_approved") for x in mine) else {}),
                       **({"refs": refs} if (refs := [r for x in mine for r in x.get("refs") or []]) else {}))
        m["queue"] = [merged] + [x for i, x in enumerate(q) if i not in set(idx)]
        m["updated"] = time.time()
        pid, caps, turn = int(m.get("pid") or 0), m.get("runner_caps") or [], m.get("turn_id")
        interrupt = m.get("turn_kind") not in ("compact", "handoff")
        if interrupt and turn:
            m["steer_turn"] = turn
    if interrupt and pid and store.runner_alive(sid, store.read(sid) or {}):
        # A runner from before this feature does not handle SIGUSR1 (its default action would kill it):
        # SIGTERM also ends only the current turn and the queue goes on.
        _signal(pid, signal.SIGUSR1 if "steer" in caps and turn else signal.SIGTERM)
    bus.invalidate("sessions")
    return {"steered": True, "interrupted": interrupt, "session": get_session(sid)}


def live_refs(sid: str) -> set[str]:
    """Refs (send_message `ref`) of the messages still to answer: queued, or in the turn running now."""
    m = store.read(sid) if store.is_valid_id(sid) else None
    if not m:
        return set()
    out = {str(r) for x in m.get("queue") or [] if isinstance(x, dict) for r in x.get("refs") or []}
    if m.get("state") == "running":
        out |= {str(r) for r in m.get("turn_refs") or []}
    return out


def _signal(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except OSError:
        pass


def update_session(sid: str, title: str | None = None, model: str | None = None,
                   archived: bool | None = None, notify: bool | None = None,
                   plan_mode: bool | None = None, favorite: bool | None = None,
                   path: str | None = None) -> dict:
    cur = _require(sid)
    if model is not None:
        model = _check_model(model)
    if path is not None:
        move_session(sid, path, cur)
    with store.edit(sid) as m:
        if title is not None and title.strip():
            m["title"] = title.strip()[:120]
        if model is not None:
            m["model"] = model
        if archived is not None:
            m["archived"] = bool(archived)
        if notify is not None:
            m["notify"] = bool(notify)
        if favorite is not None:
            m["favorite"] = bool(favorite)
        if plan_mode is not None:
            m["plan_mode"] = bool(plan_mode)
            if not plan_mode:
                m["plan_ready"] = False
    bus.invalidate("sessions", "workspace")
    return get_session(sid) or {}


def approve_plan(sid: str, text: str = "") -> dict:
    """The user validates the plan Claude proposed: plan mode goes off and Claude is told to implement it
    (a message shown as the user's `text`). -> {queued, session}"""
    _require(sid)
    with store.edit(sid) as m:
        m["plan_mode"], m["plan_ready"] = False, False
    queued = _enqueue(sid, _item((text or "").strip() or "Plan approved.", [], "web", plan_approved=True))
    return {"queued": queued, "session": get_session(sid)}


def delete_session(sid: str) -> None:
    """Moves the session to the trash (Settings -> Trash restores it)."""
    m = _require(sid)
    if m.get("state") == "running":
        stop(sid)
    from .. import trash
    trash.trash_session(sid)
    _models_seen.pop(sid, None)
    bus.invalidate("sessions", "workspace")


def mark_seen(sid: str) -> None:
    _require(sid)
    with store.edit(sid) as m:
        m["seen_at"] = time.time()
    bus.invalidate("sessions", "workspace")


def _idle_with_history(sid: str) -> dict:
    m = public(_require(sid))
    if m["state"] == "running":
        raise SessionError(409, "busy", "A turn is running - wait for it to finish")
    if not m["turns"]:
        raise SessionError(400, "empty_session", "Nothing to summarise yet")
    return m


def compact(sid: str) -> None:
    """Summary turn, then the runner switches to a fresh Claude thread seeded with it."""
    _idle_with_history(sid)
    _enqueue(sid, _item(SUMMARY_PROMPT, [], "system", "compact"))


def handoff(sid: str) -> dict:
    """New session seeded with a summary of this one (which gets archived once it is handed over)."""
    old = _idle_with_history(sid)
    meta = store.read(sid) or {}
    base = re.sub(r"\s*\(cont\.(?: \d+)?\)$", "", old["title"])
    n = sum(1 for s in list_sessions(old["path"]) if s["title"].startswith(base + " (cont."))
    new = store.new_meta(old["path"], f"{base} (cont.{' %d' % (n + 1) if n else ''})",
                         model=old["model"], source=old["source"], notify=old["notify"],
                         env=meta.get("env"), timeout_s=meta.get("timeout_s"))
    if meta.get("favorite"):                 # the continuation stays in the user's favorites
        new["favorite"] = True
    new["handoff_pending"] = time.time()     # messages sent to it wait for the summary seed (runner._handoff)
    store.create(new)
    store.append_log(new["id"], {"type": "mx_note", "level": "info", "at": time.time(),
                                 "text": f"Continuation of '{old['title']}' - waiting for the summary…"})
    _enqueue(sid, _item(SUMMARY_PROMPT, [], "system", "handoff", target=new["id"]))
    return get_session(new["id"]) or public(new)


# ---- events --------------------------------------------------------------------------------
def read_raw(sid: str, offset: int = 0, max_bytes: int = READ_CHUNK) -> tuple[list[str], int]:
    """Complete lines from `offset` (bytes) -> (lines, next_offset). Never splits a line."""
    path = store.log_path(sid)
    try:
        size = path.stat().st_size
    except OSError:
        return [], offset
    if offset >= size or offset < 0:
        return [], min(max(offset, 0), size)
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(max_bytes)
        cut = chunk.rfind(b"\n")
        if cut < 0:
            if len(chunk) < max_bytes:
                return [], offset             # line still being written
            rest = f.readline()               # one huge line: take it whole
            if not rest.endswith(b"\n"):
                return [], offset
            chunk += rest
            cut = len(chunk) - 1
    chunk = chunk[: cut + 1]
    return chunk.decode("utf-8", "replace").splitlines(), offset + len(chunk)


def read_events(sid: str, offset: int = 0) -> tuple[list[dict], int]:
    _require(sid)
    lines, nxt = read_raw(sid, offset)
    return normalize.normalize_lines(lines), nxt


def end_offset(sid: str) -> int:
    """Offset just after the last complete line of the log: where the events of the next turn start."""
    try:
        with open(store.log_path(sid), "rb") as f:
            pos = os.fstat(f.fileno()).st_size
            while pos > 0:
                step = min(BACK_CHUNK, pos)
                pos -= step
                f.seek(pos)
                cut = f.read(step).rfind(b"\n")
                if cut >= 0:
                    return pos + cut + 1
    except (OSError, KeyError):
        pass
    return 0


def offset_valid(sid: str, offset: int) -> bool:
    """True when `offset` is a line boundary of the current log (False after a rewrite/shrink)."""
    if offset == 0:
        return True
    try:
        with open(store.log_path(sid), "rb") as f:
            if offset < 0 or offset > os.fstat(f.fileno()).st_size:
                return False
            f.seek(offset - 1)
            return f.read(1) == b"\n"
    except (OSError, KeyError):
        return False


def log_ident(sid: str) -> tuple[int, int] | None:
    """(inode, size) of the raw log: a different inode or a smaller size = the log was rewritten."""
    try:
        st = store.log_path(sid).stat()
    except (OSError, KeyError):
        return None
    return st.st_ino, st.st_size


def meta_ident(sid: str) -> tuple[int, int, int] | None:
    """(inode, mtime_ns, size) of the meta file (atomic writes = a new inode): unchanged = same Session."""
    try:
        st = store.meta_path(sid).stat()
    except (OSError, KeyError):
        return None
    return st.st_ino, st.st_mtime_ns, st.st_size


def _line_end(f: Any, size: int) -> int:
    """Offset just after the last complete line (a line still being written is left out)."""
    pos = size
    while pos > 0:
        n = min(BACK_CHUNK, pos)
        f.seek(pos - n)
        i = f.read(n).rfind(b"\n")
        if i >= 0:
            return pos - n + i + 1
        pos -= n
    return 0


def read_back(sid: str, end: int | None = None, limit: int = 200) -> dict:
    """Read the log BACKWARDS from byte `end` (None = end of the log): whole lines, until at least
    `limit` normalised events (or BACK_SCAN_MAX bytes scanned). Never loads the whole file.
    -> {events, start, next, more_before} (`start` = offset of the first line read, `next` = end),
    or {reset: True} when `end` is not a line boundary of the current log (rewritten / shrunk)."""
    _require(sid)
    limit = max(1, int(limit))
    try:
        f = open(store.log_path(sid), "rb")
    except OSError:
        return {"events": [], "start": 0, "next": 0, "more_before": False}
    with f:
        size = os.fstat(f.fileno()).st_size
        if end is None:
            end = _line_end(f, size)
        elif end > size:
            return {"reset": True}
        elif end > 0:
            f.seek(end - 1)
            if f.read(1) != b"\n":
                return {"reset": True}
        groups: list[list[dict]] = []
        count, pos, start, carry = 0, end, end, b""
        while start > 0 and count < limit and end - pos < BACK_SCAN_MAX:
            n = min(BACK_CHUNK, pos)
            pos -= n
            f.seek(pos)
            buf = f.read(n) + carry                    # covers [pos, start)
            if pos > 0:
                i = buf.find(b"\n")
                if i < 0:                              # inside one long line: keep reading
                    carry = buf
                    continue
                carry, body, base = buf[: i + 1], buf[i + 1:], pos + i + 1
            else:
                carry, body, base = b"", buf, 0
            lines = body.split(b"\n")[:-1]            # body ends with a newline
            offs, o = [], base
            for ln in lines:
                offs.append(o)
                o += len(ln) + 1
            for ln, o in zip(reversed(lines), reversed(offs)):
                start = o
                evs = normalize.normalize_lines([ln.decode("utf-8", "replace")])
                if evs:
                    groups.append(evs)
                    count += sum(e["type"] != "task" for e in evs)   # frequent progress lines: not thread rows
                    if count >= limit:
                        break
        events = [e for g in reversed(groups) for e in g]
        _add_task_starts(f, start, events)
    return {"events": events, "start": start, "next": end, "more_before": start > 0}


_START_FIELDS = ("kind", "background", "description", "agent_type")


def _add_task_starts(f, before: int, events: list[dict]) -> None:
    """A task whose task_started line is before the page (a long agent: its progress lines only) would show
    without its kind (the UI hides tasks of unknown kind): copy kind / background / description / agent_type
    of that line onto the task's first event of the page. Only lines holding `task_started` are parsed."""
    first: dict[str, dict] = {}
    for e in events:
        if e["type"] == "task":
            first.setdefault(e["id"], e)
            if "kind" in e:
                first[e["id"]] = {}                   # its start is in the page
    want = {tid: e for tid, e in first.items() if e}
    pos, carry = before, b""
    while want and pos > 0 and before - pos < TASK_START_SCAN_MAX:
        n = min(BACK_CHUNK, pos)
        pos -= n
        f.seek(pos)
        buf = f.read(n) + carry
        i = buf.find(b"\n") if pos > 0 else -1
        carry, body = buf[: i + 1], buf[i + 1:]
        if pos > 0 and i < 0:
            carry, body = buf, b""
        for ln in reversed(body.split(b"\n")):
            if b"task_started" not in ln:
                continue
            for ev in normalize.normalize_lines([ln.decode("utf-8", "replace")]):
                tgt = want.pop(ev["id"], None) if ev["type"] == "task" and "kind" in ev else None
                if tgt is not None:
                    for k in _START_FIELDS:
                        if k in ev and k not in tgt:
                            tgt[k] = ev[k]


def compact_log(sid: str, dry_run: bool = False) -> dict:
    """Rewrite a raw log with clipped tool outputs and slimmed system lines (clip.py), atomically,
    streaming line by line.
    -> {id, status:"compacted"|"unchanged"|"running"|"missing", before, after} (bytes).
    Skips a session whose runner is alive; holds the run lock meanwhile so none starts."""
    meta = store.read(sid)
    path = store.log_path(sid)
    if meta is None or not path.is_file():
        return {"id": sid, "status": "missing", "before": 0, "after": 0}
    before = path.stat().st_size
    if store.runner_alive(sid, meta):
        return {"id": sid, "status": "running", "before": before, "after": before}
    fd = store.hold_run_lock(sid, wait_s=0)
    if fd is None:
        return {"id": sid, "status": "running", "before": before, "after": before}
    tmp = path.with_name(f"{path.name}.compact.tmp")
    try:
        after = 0
        out = None if dry_run else open(tmp, "wb")
        try:
            with open(path, "rb") as src:
                for raw in src:
                    end = b"\n" if raw.endswith(b"\n") else b""
                    line = raw[:-1] if end else raw
                    if clip.drop_line(line):
                        continue
                    if len(line) > clip.RESULT_MAX:
                        new = clip.clip_line(line.decode("utf-8", "replace"))
                        if len(new) < len(line):
                            line = new.encode("utf-8")
                    after += len(line) + len(end)
                    if out is not None:
                        out.write(line + end)
            if out is not None:
                out.flush()
                os.fsync(out.fileno())
        finally:
            if out is not None:
                out.close()
        if after >= before:
            tmp.unlink(missing_ok=True)
            return {"id": sid, "status": "unchanged", "before": before, "after": before}
        if not dry_run:
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        return {"id": sid, "status": "compacted", "before": before, "after": after}
    finally:
        tmp.unlink(missing_ok=True)
        os.close(fd)


def has_more(sid: str, offset: int) -> bool:
    return store.log_size(sid) > offset


def _tail_events(sid: str, nbytes: int = 512 * 1024) -> list[dict]:
    size = store.log_size(sid)
    start = max(0, size - nbytes)
    lines, _ = read_raw(sid, start, nbytes + 1)
    if start:
        lines = lines[1:]                     # first line is probably partial
    return normalize.normalize_lines(lines)


def last_assistant_text(sid: str) -> str:
    for ev in reversed(_tail_events(sid)):
        if ev["type"] == "assistant":
            return ev["text"]
    return ""


def last_user_message(sid: str) -> dict | None:
    """The last user message of the log -> {text, attachments, source, at} (None if there is none). A voice
    message sent directly gets its transcript as text."""
    heard = None
    for ev in reversed(_tail_events(sid)):
        if ev["type"] == "voice_text":
            heard = ev.get("text") or ""
        if ev["type"] == "user":
            if ev.get("voice") and heard:
                return {**ev, "text": "\n\n".join(t for t in (ev.get("text") or "", heard) if t.strip())}
            return ev
    return None


def last_result(sid: str) -> dict | None:
    for ev in reversed(_tail_events(sid)):
        if ev["type"] == "result":
            return ev
        if ev["type"] == "user":
            return None
    return None


# ---- search --------------------------------------------------------------------------------
def search(q: str, limit: int = 50) -> list[dict]:
    """Sessions whose title or messages match (all words, prefixes, accent-insensitive), best first.
    Served by the full-text index (maxxing/search.py)."""
    from .. import search as engine
    res = engine.search(q, ["session"], limit)["results"]
    return [{"id": r["id"], "title": r["title"], "path": r["path"],
             "snippet": r["snippet"].replace("\x02", "").replace("\x03", ""), "at": r["at"]} for r in res]


# ---- models --------------------------------------------------------------------------------
_models_cache: tuple[float, list[dict]] = (0.0, [])


def _label(mid: str) -> str:
    parts = mid.split("-")[1:]
    if not parts:
        return mid
    fam = parts[0].capitalize()
    nums = [p for p in parts[1:] if p.isdigit() and len(p) < 4]
    return f"{fam} {'.'.join(nums)}".strip()


_models_seen: dict[str, tuple[int, int, set[str]]] = {}    # session -> (log inode, bytes scanned, models seen)


def models() -> list[dict]:
    """Known model ids + ids seen in session logs (cached 60 s; each pass reads only what was appended)."""
    global _models_cache
    if time.time() - _models_cache[0] < 60:
        return _models_cache[1]
    seen = set(KNOWN_MODELS)
    windows: dict = {}
    for sid in store.list_ids():
        try:
            p = store.log_path(sid)
            st = p.stat()
            ino, done, ids = _models_seen.get(sid, (0, 0, set()))
            if ino != st.st_ino or done > st.st_size:     # rewritten (message hidden, compacted): start over
                done, ids = 0, set()
            if done < st.st_size:
                with open(p, "rb") as f:
                    f.seek(max(done, st.st_size - 300_000))
                    tail = f.read()
                ids = ids | {m.decode() for m in _MODEL_RE.findall(tail)}
                windows.update({k.decode(): {"contextWindow": int(v)} for k, v in _WINDOW_RE.findall(tail)})
                _models_seen[sid] = (st.st_ino, st.st_size, ids)
            seen |= ids
        except OSError:
            pass
    if windows:
        store.record_windows({"modelUsage": windows})     # windows of models seen before this field existed
    fam = {"opus": 0, "sonnet": 1, "haiku": 2}

    def key(mid: str) -> tuple:
        parts = mid.split("-")
        v = [int(x) for x in parts[2:] if x.isdigit() and len(x) < 4][:3] + [0, 0, 0]
        return (fam.get(parts[1] if len(parts) > 1 else "", 9), [-x for x in v[:3]], mid)
    windows = store.known_windows()
    out = [{"id": m, "label": _label(m), "context_window": windows.get(m)} for m in sorted(seen, key=key)]
    _models_cache = (time.time(), out)
    return out


# ---- workspace hooks -----------------------------------------------------------------------
def _claude_slug(cwd: Path) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-", str(cwd))


def _move_transcript(csid: str, old_cwd: Path, new_cwd: Path) -> None:
    """Claude Code keeps a session under ~/.claude/projects/<slug of its cwd>/: follow the new cwd so
    `--resume` keeps working (best effort; the runner falls back to a new thread)."""
    projects = config.claude_dir() / "projects"
    src = projects / _claude_slug(old_cwd) / f"{csid}.jsonl"
    if not src.is_file():
        return
    dst = projects / _claude_slug(new_cwd) / f"{csid}.jsonl"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    except OSError:
        log.warning("could not move transcript %s", src)


def move_session(sid: str, path: str, meta: dict | None = None) -> None:
    """Move one session to another topic (its cwd from the next turn). Refused while a turn runs or
    messages wait: the turn's process lives in the old folder."""
    m = meta or _require(sid)
    try:
        new = workspace.normalize_path(path)
        workspace.topic_dir(new)
    except ValueError as e:
        raise SessionError(400, "bad_path", str(e)) from None
    old = m.get("path") or ""
    if new == old:
        return
    if m.get("state") == "running" or _waiting(m):
        raise SessionError(409, "busy", "Wait for the current turn to finish before moving the session")
    root = workspace.root()
    with store.edit(sid) as mm:
        if mm.get("state") == "running" or _waiting(mm):      # again under the lock: a turn may have just started
            raise SessionError(409, "busy", "Wait for the current turn to finish before moving the session")
        old = mm.get("path") or ""
        mm["path"] = new
        csid = mm.get("csid") or sid
    _move_transcript(csid, root / old if old else root, root / new if new else root)
    bus.invalidate("sessions", "workspace")


def remap_paths(old: str, new: str, sessions: list[dict]) -> None:
    """After a folder rename: rewrite session paths and move Claude transcripts so `--resume`
    keeps working from the new cwd (best effort; the runner falls back to a new thread)."""
    root = workspace.root()
    for s in sessions:
        sp = s["path"]
        np = new + sp[len(old):]
        try:
            with store.edit(s["id"]) as m:
                m["path"] = np
                csid = m.get("csid") or s["id"]
        except KeyError:
            continue
        _move_transcript(csid, root / sp, root / np)
    bus.invalidate("sessions")


def trash_sessions(ids: list[str], dest: Path) -> None:
    """Move session files (meta + log) of a deleted topic into the trash."""
    if not ids:
        return
    dest.mkdir(parents=True, exist_ok=True)
    for sid in ids:
        for ext in (".json", ".log"):
            try:
                shutil.move(str(store._path(sid, ext)), str(dest / f"{sid}{ext}"))
            except (OSError, KeyError):
                pass
        store.remove(sid)
    bus.invalidate("sessions")


# ---- turn-end watcher ----------------------------------------------------------------------
_turn_cbs: list[Callable[..., Any]] = []
_watch_task: asyncio.Task | None = None
_known: dict[str, tuple[int, int, str, bool]] = {}      # sid -> (mtime_ns, turns, state, unread)


def on_turn_end(cb: Callable[[dict, dict | None], Any]) -> None:
    """Register `cb(session, result)` (sync or async), called on the event loop when a turn of
    any session ends (the turn counter grows, or running -> error)."""
    _turn_cbs.append(cb)


# While a session runs, the watcher passes every WATCH_RUNNING_S (its turn end - Telegram reply, notification, cron
# result - is seen within 0.25 s instead of 1 s); an unchanged running session is still re-read (dead runner check)
# only every RUNNING_RECHECK_S.
WATCH_RUNNING_S = 0.25
RUNNING_RECHECK_S = 1.0
_checked: dict[str, float] = {}


_damaged: dict[str, int] = {}          # session -> mtime of a meta file public() could not read


_held: dict[str, float] = {}           # continuation with queued messages -> when its hand-off hold expires


def release_handoff(sid: str) -> None:
    """End the hand-off hold of a continuation (the summary never came): its queued messages run."""
    try:
        with store.edit(sid) as m:
            m.pop("handoff_pending", None)
            go = bool(m.get("queue")) and not (m.get("state") == "running" and store.runner_alive(sid, m))
            if go:
                m.update(state="running", spawned_at=time.time(), error=None)
    except KeyError:
        return
    if go:
        _spawn(sid)


def _ended(s: dict, m: dict) -> dict:
    """The Session given to on_turn_end callbacks, plus `last_turn`: which item the ended turn ran (id, kind,
    source, refs) - not part of the API Session."""
    return {**s, "last_turn": m.get("last_turn") if isinstance(m.get("last_turn"), dict) else {}}


def _scan(primed: bool) -> tuple[list[tuple[dict, dict | None]], bool, bool]:
    """One pass over the meta files -> (turn ends, sessions changed, workspace changed)."""
    ends: list[tuple[dict, dict | None]] = []
    since = 0.0 if primed else _last_pass()
    now = time.monotonic()
    changed = ws_changed = False
    d = store.sessions_dir()
    alive = set()
    for sid in store.list_ids():
        alive.add(sid)
        try:
            mt = (d / f"{sid}.json").stat().st_mtime_ns
        except OSError:
            continue
        prev = _known.get(sid)
        if prev and prev[0] == mt and (prev[2] != "running" or now - _checked.get(sid, 0) < RUNNING_RECHECK_S):
            continue
        if _damaged.get(sid) == mt:
            continue
        _checked[sid] = now
        m = store.read(sid)
        if m is None:
            continue
        if m.get("handoff_pending") and m.get("queue"):
            _held[sid] = _num(m.get("handoff_pending")) + HANDOFF_HOLD_S
        else:
            _held.pop(sid, None)
        try:
            s = public(m)
        except Exception:                     # one damaged session file never stops the others' turn ends
            log.warning("session %s: unreadable meta", sid, exc_info=True)
            _damaged[sid] = mt                         # logged once: read again only when the file changes
            continue
        try:
            mt = (d / f"{sid}.json").stat().st_mtime_ns
        except OSError:
            pass
        cur = (mt, s["turns"], s["state"], s["unread"])
        if prev is None:
            if not primed:                    # first pass: baseline - except turns that ended while the server was down
                _known[sid] = cur
                if s["state"] != "running" and _num(m.get("finished_at")) > since:
                    ends.append((_ended(s, m), last_result(sid)))
                continue
            prev = (0, 0, "idle", False)      # new session: its turns all happened since
            ws_changed = True
        elif prev[0] == mt:
            continue
        _known[sid] = cur
        changed = True
        if (prev[2], prev[3]) != (cur[2], cur[3]):
            ws_changed = True
        # a turn ended, or failed to start (error without a new turn - also when it failed before this watcher
        # ever saw it running: systemd-run refusing within one pass)
        if cur[1] > prev[1] or (prev[2] != "error" and cur[2] == "error" and cur[1] == prev[1]):
            ends.append((_ended(s, m), last_result(sid)))
    for sid in [k for k, until in _held.items() if k not in alive or until <= time.time()]:
        _held.pop(sid, None)
        if sid in alive:
            release_handoff(sid)
            changed = True
    for sid in set(_known) - alive:
        _known.pop(sid, None)
        _checked.pop(sid, None)
        changed = ws_changed = True
    return ends, changed, ws_changed


_firing: set[asyncio.Task] = set()


async def _fire(session: dict, result: dict | None) -> None:
    for cb in list(_turn_cbs):
        try:
            res = cb(session, result)
            if inspect.isawaitable(res):
                await res
        except Exception:
            log.exception("on_turn_end callback failed")


PASS_STAMP_S = 5.0                     # how often the watcher records its last pass (STATE/session-watcher.json)


def _stamp_path() -> Path:
    return config.STATE / "session-watcher.json"


def _last_pass() -> float:
    """When the watcher last scanned (persisted): turns that ended after it, while the server was stopped or
    restarting, are reported by the first pass of the next start. Never stamped (first start): nothing."""
    d = config.read_json(_stamp_path(), {})
    at = _num(d.get("at")) if isinstance(d, dict) else 0.0
    return at or time.time()


def _stamp(at: float) -> None:
    try:
        config.write_json(_stamp_path(), {"at": at})
    except OSError:
        log.warning("session watcher: cannot write %s", _stamp_path(), exc_info=True)


async def _watch(interval: float) -> None:
    primed, stamped = False, 0.0
    while True:
        try:
            t0 = time.time()
            ends, changed, ws = await asyncio.to_thread(_scan, primed)
            primed = True
            if ends or t0 - stamped >= PASS_STAMP_S:     # at once after a report: a restart does not repeat it
                await asyncio.to_thread(_stamp, t0)
                stamped = t0
            if changed:
                bus.invalidate(*(("sessions", "workspace") if ws else ("sessions",)))
            for s, r in ends:
                t = asyncio.get_running_loop().create_task(_fire(s, r))
                _firing.add(t)                 # keep a reference: an unreferenced task can be collected mid-run
                t.add_done_callback(_firing.discard)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("session watcher pass failed")
        running = any(v[2] == "running" for v in _known.values())
        await asyncio.sleep(min(interval, WATCH_RUNNING_S) if running else interval)


def start_watcher(interval: float = 1.0) -> None:
    global _watch_task
    if _watch_task is None or _watch_task.done():
        _known.clear()
        _watch_task = asyncio.get_running_loop().create_task(_watch(interval))


async def stop_watcher() -> None:
    global _watch_task
    if _watch_task is not None:
        _watch_task.cancel()
        try:
            await _watch_task
        except (asyncio.CancelledError, Exception):
            pass
        _watch_task = None


def wait_turn(sid: str, timeout_s: float) -> dict:
    """Block until the session is no longer running (queue drained) or timeout; returns the Session."""
    deadline = time.time() + max(0.0, float(timeout_s))
    while True:
        s = get_session(sid)
        if s is None:
            raise SessionError(404, "not_found", "Session not found")
        if s["state"] != "running" and s["queue"] == 0:
            return s
        if time.time() >= deadline:
            return s
        time.sleep(0.5)


def uploads_dir(path: str) -> Path:
    """<topic>/attachments/YYYY-MM/ (created)."""
    try:
        d = workspace.topic_dir(path) / "attachments" / time.strftime("%Y-%m")
    except ValueError as e:
        raise SessionError(400, "bad_path", str(e)) from None
    d.mkdir(parents=True, exist_ok=True)
    return d

