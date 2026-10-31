"""Session files: meta JSON, raw NDJSON log, cross-process locks.  STDLIB ONLY (used by the runner).

Meta (`<id>.json`, internal - service.public() turns it into the API.md Session):
  id, title, path (topic path), state ("idle"|"running"|"error"), queue [QueueItem],
  created, updated, turns, cost_usd, tokens {input, output, cache_read, cache_write} (absent on
  sessions created before 2.0.0a6 until stats.py backfills it from the log), days {YYYY-MM-DD:
  {tokens, cost}} (last 90 days), model, real_model, context_tokens, base_tokens (context of the
  first call of the current thread: the fixed part), context_window (from the last result), archived, notify,
  source, cron, last_text, error, csid (Claude session id), fresh (next turn uses --session-id),
  pid (runner), unit, spawned_at, finished_at, seen_at, cache_at (last side question: it warmed the
  thread's prompt cache too), env {..}, timeout_s, handoff_pending (continuation waiting for its hand-off
  summary: when it was created; queued messages wait behind the seed, service.HANDOFF_HOLD_S at most)
QueueItem = {text, attachments:[path], source, at, kind:"user"|"compact"|"handoff"|"seed", target?, auto?, idle?}

Every read-modify-write goes through `edit(sid)` which holds an flock on `<id>.lock`, so the
server and the runner (separate processes) never lose each other's updates. Writes are atomic
(tmp + rename), so lock-free readers always see a complete file.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .. import config

ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SPAWN_GRACE_S = 30.0          # a runner just spawned may not hold its run lock yet


_dir: tuple[Path, Path, str] | None = None    # (config.STATE it was made for, sessions dir, same as str)


LOCK_RETRY_S = 0.05            # the previous runner of the session is exiting: retry the run lock this often

def _private(path: str, flags: int) -> int:
    """open() opener: a new session log is created 0600 (only root reads conversations)."""
    return os.open(path, flags, 0o600)


def sessions_dir() -> Path:
    global _dir
    # Called for every session path (a list of 300 sessions): create + chmod the folder once per state dir, then
    # only check that it still exists (one stat instead of mkdir + chmod + path building each time).
    if _dir is not None and _dir[0] is config.STATE and os.path.isdir(_dir[2]):
        return _dir[1]
    d = config.state_dir("sessions")
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    _dir = (config.STATE, d, str(d))
    return d


def is_valid_id(sid: str) -> bool:
    return bool(ID_RE.match(sid or ""))


def _path(sid: str, ext: str) -> Path:
    if not is_valid_id(sid):
        raise KeyError(sid)
    return sessions_dir() / f"{sid}{ext}"


def meta_path(sid: str) -> Path:
    return _path(sid, ".json")


def log_path(sid: str) -> Path:
    return _path(sid, ".log")


def new_id() -> str:
    return str(uuid.uuid4())


# ---- meta ----------------------------------------------------------------------------------
def read(sid: str) -> dict | None:
    """Meta of a session, None when missing or corrupt."""
    try:
        with open(meta_path(sid)) as f:
            d = json.load(f)
    except (KeyError, OSError, ValueError):
        return None
    return d if isinstance(d, dict) and d.get("id") == sid else None


_cache: dict[str, tuple[tuple[int, int, int], dict]] = {}   # meta path -> ((inode, mtime_ns, size), meta)


def read_cached(sid: str) -> dict | None:
    """Like read(), but an unchanged file (same inode, mtime and size) is not parsed again: session lists
    stop re-reading every meta. The dict is shared between callers: never mutate it."""
    try:
        p = meta_path(sid)
        st = p.stat()
    except (KeyError, OSError):
        return None
    key, hit = (st.st_ino, st.st_mtime_ns, st.st_size), _cache.get(str(p))
    if hit and hit[0] == key:
        return hit[1]
    d = read(sid)                     # replaced since the stat: cached under the old key, re-read next time
    if d is None:
        _cache.pop(str(p), None)
    else:
        _cache[str(p)] = (key, d)
    return d


def forget_cached(keep: set[str]) -> None:
    """Drops cached metas of sessions that are gone (ids not in `keep`)."""
    for k in [k for k in list(_cache) if Path(k).stem not in keep]:
        _cache.pop(k, None)


def _write(sid: str, data: dict) -> None:
    p = meta_path(sid)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)                    # a failed write (disk full) leaves no stray file


def _same_file(fd: int, path: Path) -> bool:
    """The locked fd is still the file at `path`: `prune_locks` may have removed it (under the lock) between our
    open() and our flock(), and a lock on a removed file excludes nobody."""
    try:
        a, b = os.fstat(fd), os.stat(path)
    except OSError:
        return False
    return (a.st_ino, a.st_dev) == (b.st_ino, b.st_dev)


@contextmanager
def _flock(sid: str) -> Iterator[None]:
    path = _path(sid, ".lock")
    while True:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except BaseException:
            os.close(fd)
            raise
        if _same_file(fd, path):
            break
        os.close(fd)                                    # removed under us: lock the new file
    try:
        yield
    finally:
        os.close(fd)


@contextmanager
def edit(sid: str) -> Iterator[dict]:
    """Locked read-modify-write of a meta: mutate the yielded dict in place. KeyError if missing."""
    with _flock(sid):
        d = read(sid)
        if d is None:
            raise KeyError(sid)
        yield d
        _write(sid, d)


def update(sid: str, **changes: Any) -> dict:
    with edit(sid) as d:
        d.update(changes)
        return dict(d)


def create(meta: dict) -> dict:
    sid = meta["id"]
    with _flock(sid):
        _write(sid, meta)
    log_path(sid).touch(mode=0o600, exist_ok=True)
    _ids["ids"] = _ids["ids"] | {sid}
    return meta


TOKEN_KEYS = (("input", "input_tokens"), ("output", "output_tokens"),
              ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens"))
DAYS_KEPT = 90


def empty_tokens() -> dict:
    return {k: 0 for k, _ in TOKEN_KEYS}


def turn_cost(total: float, prev: float) -> float:
    """Cost of one turn from Claude's `total_cost_usd`, which adds up over the whole Claude thread (every
    `--resume` reports the thread's running total): the increase since the previous turn of the same thread, or the
    total itself when it went down (a new thread, a thread Claude no longer knew)."""
    total, prev = float(total or 0), float(prev or 0)
    return round(total - prev, 6) if total >= prev else round(total, 6)


def thread_prev_cost(m: dict, csid: str | None) -> float:
    """Running total last reported for Claude thread `csid` (0 for a thread not seen yet)."""
    tc = m.get("thread_cost") if isinstance(m.get("thread_cost"), dict) else {}
    return float(tc.get("total") or 0) if csid and tc.get("csid") == csid else 0.0


def add_usage(m: dict, usage: dict | None, cost: float, when: float) -> None:
    """Add one Claude `result` (raw usage + cost) to the meta counters. `tokens` is only kept up to date
    once it exists (new sessions; older ones are backfilled from their log first, see stats.py)."""
    u = usage if isinstance(usage, dict) else {}
    total = sum(int(u.get(src) or 0) for _, src in TOKEN_KEYS)
    if isinstance(m.get("tokens"), dict):
        tk = m["tokens"]
        for k, src in TOKEN_KEYS:
            tk[k] = int(tk.get(k) or 0) + int(u.get(src) or 0)
    days = m.get("days") if isinstance(m.get("days"), dict) else {}
    day = time.strftime("%Y-%m-%d", time.localtime(when))
    d = days.get(day) if isinstance(days.get(day), dict) else {"tokens": 0, "cost": 0.0}
    days[day] = {"tokens": int(d.get("tokens") or 0) + total, "cost": round(float(d.get("cost") or 0) + float(cost or 0), 6)}
    m["days"] = {k: days[k] for k in sorted(days)[-DAYS_KEPT:]}


def context_window_of(result: dict, real_model: str | None = None) -> int | None:
    """Context window (tokens) of the main model of a raw Claude `result` (modelUsage[..].contextWindow)."""
    mu = result.get("modelUsage") if isinstance(result.get("modelUsage"), dict) else {}
    entries = {k: v for k, v in mu.items() if isinstance(v, dict)}
    if not entries:
        return None
    entry = entries.get(real_model or "") or max(entries.values(), key=lambda v: float(v.get("costUSD") or 0))
    try:
        cw = int(entry.get("contextWindow") or 0)
    except (TypeError, ValueError):
        return None
    return cw if cw > 0 else None


def windows_path() -> Path:
    return config.STATE / "context_windows.json"


def known_windows() -> dict[str, int]:
    """Context window of every model Claude Code has reported on this server ({model id: tokens})."""
    d = config.read_json(windows_path(), {}) or {}
    return {str(k): int(v) for k, v in d.items() if isinstance(v, (int, float)) and v > 0} if isinstance(d, dict) else {}


def record_windows(result: dict) -> None:
    """Remember modelUsage[..].contextWindow of a raw result (each model, including sub-agents)."""
    mu = result.get("modelUsage") if isinstance(result.get("modelUsage"), dict) else {}
    seen = {k: int(v.get("contextWindow") or 0) for k, v in mu.items() if isinstance(v, dict)}
    seen = {k: v for k, v in seen.items() if v > 0}
    if not seen:
        return
    cur = known_windows()
    if all(cur.get(k) == v for k, v in seen.items()):
        return
    try:
        config.write_json(windows_path(), {**cur, **seen})
    except OSError:
        pass


def new_meta(path: str, title: str, *, model: str = "", source: str = "web", notify: bool = False,
             cron: bool = False, env: dict | None = None, timeout_s: int | None = None,
             plan_mode: bool = False, permission_mode: str = "") -> dict:
    now = time.time()
    sid = new_id()
    return {"id": sid, "title": title, "path": path, "state": "idle", "queue": [],
            "created": now, "updated": now, "turns": 0, "cost_usd": 0.0, "cost_v": 2, "tokens": empty_tokens(), "days": {},
            "model": model or "",
            "real_model": None, "context_tokens": None, "archived": False, "notify": bool(notify),
            "source": source, "cron": bool(cron), "last_text": "", "error": None,
            "csid": sid, "fresh": True, "pid": None, "unit": None, "spawned_at": None,
            "finished_at": None, "seen_at": None, "env": dict(env or {}), "timeout_s": timeout_s,
            "plan_mode": bool(plan_mode), "plan_ready": False,
            "permission_mode": permission_mode or ""}


# Session ids, kept in memory: the folder is listed again only when its mtime changed (a file added, removed or
# renamed - every meta save is a rename) or changed less than IDS_RACY_S ago (a file created in the same timestamp
# tick as the last listing would not change it).
IDS_RACY_S = 1.0
_ids: dict[str, Any] = {"key": None, "ids": set()}


def list_ids() -> list[str]:
    d = sessions_dir()
    try:
        st = os.stat(d)
        key: tuple | None = (str(d), st.st_ino, st.st_mtime_ns)
        settled = time.time() - st.st_mtime > IDS_RACY_S
    except OSError:
        key, settled = None, False
    if key is not None and settled and _ids["key"] == key:
        return list(_ids["ids"])
    ids: set[str] = set()
    try:
        with os.scandir(d) as it:
            for e in it:
                n = e.name
                if n.endswith(".json") and is_valid_id(n[:-5]):
                    ids.add(n[:-5])
    except OSError:
        pass
    _ids.update(key=key, ids=ids)
    return list(ids)


def remove(sid: str) -> None:
    for ext in (".json", ".log", ".lock", ".run"):
        try:
            _path(sid, ext).unlink()
        except (FileNotFoundError, KeyError):
            pass
    if is_valid_id(sid):                       # its MCP config of the turns (mcp_auto.py), holds server secrets
        try:
            (config.STATE / "mcp-auto" / "sessions" / f"{sid}.json").unlink()
        except OSError:
            pass
    _ids["ids"] = _ids["ids"] - {sid}


PRUNE_IDLE_S = 3600.0          # a lock file is removed only once its session has been idle this long


def prune_locks(idle_s: float = PRUNE_IDLE_S) -> int:
    """Remove the `.lock` / `.run` files nothing needs: of sessions that are gone, and of sessions idle for
    `idle_s` (not running, empty queue, no runner spawned, finished and updated that long ago). Each file is
    removed while we hold its lock (never one a runner or an edit holds); `_flock` / `hold_run_lock` check after
    locking that the file is still there, so a waiter on a removed file starts again on a new one.
    -> number of files removed."""
    d = sessions_dir()
    now, n = time.time(), 0
    try:
        names = [e.name for e in os.scandir(d)]
    except OSError:
        return 0
    for name in names:
        sid, dot, ext = name.partition(".")
        if ext not in ("lock", "run") or not is_valid_id(sid):
            continue
        path = d / name
        try:
            if now - os.stat(path).st_mtime < idle_s:
                continue
        except OSError:
            continue
        m = read(sid)
        if m is not None and not _idle_since(m, now, idle_s):
            continue
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)                                # held: in use
            continue
        try:
            m = read(sid)                               # again, now that nobody else holds it
            if (m is None or _idle_since(m, now, idle_s)) and _same_file(fd, path):
                path.unlink()
                n += 1
        except OSError:
            pass
        finally:
            os.close(fd)
    return n


def _idle_since(m: dict, now: float, idle_s: float) -> bool:
    def num(v: Any) -> float:
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0
    if m.get("state") == "running" or m.get("queue") or m.get("pid"):
        return False
    if now - num(m.get("spawned_at")) < idle_s or now - num(m.get("updated")) < idle_s:
        return False
    return now - num(m.get("finished_at")) >= idle_s


# ---- raw log -------------------------------------------------------------------------------
def append_log(sid: str, obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with open(log_path(sid), "a", opener=_private) as f:
        f.write(line)


def log_size(sid: str) -> int:
    try:
        return log_path(sid).stat().st_size
    except (OSError, KeyError):
        return 0


# ---- runner liveness -----------------------------------------------------------------------
def hold_run_lock(sid: str, wait_s: float = 0.0) -> int | None:
    """Runner side: take the exclusive run lock (kept for the runner's life), retrying for
    `wait_s` seconds. None if still taken."""
    path = _path(sid, ".run")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.time() + wait_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if time.time() >= deadline:
                os.close(fd)
                return None
            time.sleep(LOCK_RETRY_S)
            continue
        if _same_file(fd, path):
            return fd
        os.close(fd)                                    # removed by prune_locks meanwhile: lock the new file
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)


def runner_alive(sid: str, meta: dict | None = None) -> bool:
    """True when a runner holds the run lock, or was spawned less than SPAWN_GRACE_S ago."""
    meta = meta if meta is not None else read(sid)
    if meta and meta.get("spawned_at") and time.time() - float(meta["spawned_at"]) < SPAWN_GRACE_S:
        return True
    try:
        fd = os.open(_path(sid, ".run"), os.O_RDWR)    # no file: nobody holds it (not created just to look)
    except (OSError, KeyError):
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)
