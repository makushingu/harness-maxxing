"""Scheduled jobs: cron expressions, job store, run history, crontab bridge and the job runner.

Storage (state_dir("crons")):
  jobs.json     {"version": 1, "jobs": [job]}         - edited by the API (and sometimes by hand)
  jobs.seen.json the job list as last written or synced - to notice a job that vanished
  deleted.jsonl {at, reason, job} per removed job       - last MAX_DELETED kept; `maxxing cron restore <id>`
  runs.jsonl    one Run per line (last MAX_RUNS kept)  - appended by `maxxing cron run` (other process)
  sessions.json {cron_id: session_id}                  - session reused by `reuse_session` Claude jobs
  locks/<id>.lock                                      - flock held while a job runs (no overlap)

The scheduler is the system cron daemon: every enabled job becomes one line of a *managed block*
in root's crontab that calls `MAXXING_CRON_DETACH=1 maxxing cron run <id>` (an environment variable, not a flag: an
older version restored by a rollback ignores it instead of refusing the line): the run starts in a transient systemd unit
(the same one as "Run now": MemoryMax, the `maxxing-jobs.slice` budget, cleanup of every process it left),
or in the cron process itself when systemd is not available. Lines outside the block are never touched.
`last_run` is derived from runs.jsonl at read time, so the runner never rewrites jobs.json.

Cron expressions are parsed, humanised and evaluated here in pure Python (5 fields, ranges,
steps, lists, month/day names, @daily/@hourly/@weekly/@monthly/@yearly/@reboot), in the
configured time zone.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import logging
import os
import re
import secrets as _secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from . import config

BLOCK_BEGIN = "# >>> claude-maxxing (managed) >>>"
BLOCK_END = "# <<< claude-maxxing <<<"
MAX_RUNS = 2000
MAX_DELETED = 200
OUTPUT_TAIL = 2048
DEFAULT_TIMEOUT = 3600
NOTIFY_POLICIES = ("never", "failure", "always")
KINDS = ("shell", "claude")
KILL_GRACE_S = 5.0                       # timed-out shell job: SIGTERM, this long, then SIGKILL of its whole group
JOBS_SLICE = "maxxing-jobs.slice"        # every job unit runs in it: its MemoryMax = budget of all jobs together
UNIT_RUNTIME_MARGIN_S = 120              # RuntimeMaxSec of a job unit = timeout + this (the run's own kill comes first)
SYSTEMD_DIR = Path("/run/systemd/system")   # present when systemd is PID 1 (absent in most containers)

_lock = config.ProcessLock("crons")      # jobs.json + crontab: also written by `maxxing cron` and the runs
log = logging.getLogger("maxxing.crons")


class CronError(ValueError):
    """Invalid cron expression or job definition (message is user-facing)."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


# =============================================================================================
# Cron expressions
# =============================================================================================
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December"]
DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

SPECIALS = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@hourly": "0 * * * *",
}
# field name, min, max, names
_FIELDS = [("minute", 0, 59, None), ("hour", 0, 23, None), ("day of month", 1, 31, None),
           ("month", 1, 12, MONTHS), ("day of week", 0, 7, DAYS)]


@dataclass(frozen=True)
class CronExpr:
    """A parsed 5-field expression. `reboot` = @reboot (no next run)."""
    source: str
    minutes: frozenset[int] = frozenset()
    hours: frozenset[int] = frozenset()
    doms: frozenset[int] = frozenset()
    months: frozenset[int] = frozenset()
    dows: frozenset[int] = frozenset()
    dom_star: bool = True
    dow_star: bool = True
    reboot: bool = False

    def day_matches(self, d: dt.date) -> bool:
        if d.month not in self.months:
            return False
        dom_ok = d.day in self.doms
        dow_ok = (d.isoweekday() % 7) in self.dows
        # Vixie cron: when both fields are restricted, a day matching EITHER runs the job.
        if not self.dom_star and not self.dow_star:
            return dom_ok or dow_ok
        return dom_ok and dow_ok


def _value(tok: str, lo: int, hi: int, names: list[str] | None, what: str) -> int:
    t = tok.lower()
    if names and t[:3] in names and t.isalpha():
        v = names.index(t[:3]) + (1 if names is MONTHS else 0)
    elif t.isascii() and t.isdigit():                  # "²" or "٣" are digits for str.isdigit()
        v = int(t)
    else:
        raise CronError(f"{what}: '{tok}' is not a number")
    if not lo <= v <= hi:
        raise CronError(f"{what}: {v} is outside {lo}-{hi}")
    return v


def _parse_field(text: str, lo: int, hi: int, names: list[str] | None, what: str) -> set[int]:
    out: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"{what}: empty list item")
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            if not (s.isascii() and s.isdigit()) or int(s) == 0:
                raise CronError(f"{what}: bad step '/{s}'")
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            x, y = part.split("-", 1)
            a, b = _value(x, lo, hi, names, what), _value(y, lo, hi, names, what)
            if a > b:
                raise CronError(f"{what}: range {x}-{y} is reversed")
        else:
            a = _value(part, lo, hi, names, what)
            b = hi if step > 1 else a           # "5/15" = from 5 every 15
        out.update(range(a, b + 1, step))
    return out


def parse(expr: str) -> CronExpr:
    """Parse a cron expression; raises CronError with a readable message."""
    src = " ".join((expr or "").split())
    if not src:
        raise CronError("empty schedule")
    if src.lower() == "@reboot":
        return CronExpr(source=src, reboot=True)
    text = SPECIALS.get(src.lower(), src)
    if text.startswith("@"):
        raise CronError(f"unknown shortcut {src}")
    parts = text.split(" ")
    if len(parts) != 5:
        raise CronError(f"a schedule has 5 fields (minute hour day month weekday), got {len(parts)}")
    sets = [_parse_field(p, lo, hi, n, w) for p, (w, lo, hi, n) in zip(parts, _FIELDS)]
    dows = {d % 7 for d in sets[4]}
    return CronExpr(source=src, minutes=frozenset(sets[0]), hours=frozenset(sets[1]),
                    doms=frozenset(sets[2]), months=frozenset(sets[3]), dows=frozenset(dows),
                    dom_star=parts[2].startswith("*"), dow_star=parts[4].startswith("*"))


def validate(expr: str) -> str:
    """Return the normalised expression or raise CronError."""
    return parse(expr).source


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(config.load_config().get("timezone") or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def iter_runs(expr: str | CronExpr, after: float | None = None, zone: ZoneInfo | None = None) -> Iterator[float]:
    """Yield the next fire times (Unix seconds, strictly after `after`) in time zone `zone`."""
    c = parse(expr) if isinstance(expr, str) else expr
    if c.reboot:
        return
    zone = zone or tz()
    start = dt.datetime.fromtimestamp(after if after is not None else time.time(), zone)
    start = start.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
    hours, minutes = sorted(c.hours), sorted(c.minutes)
    day = start.date()
    last = -1.0
    for _ in range(366 * 5):                      # at most 5 years ahead (e.g. Feb 29 on a Monday)
        if c.day_matches(day):
            for h in hours:
                for m in minutes:
                    local = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=zone)
                    if local < start:
                        continue
                    ts = local.timestamp()
                    if ts > last:                 # DST: never yield the same/earlier instant twice
                        last = ts
                        yield ts
        day += dt.timedelta(days=1)


def next_runs(expr: str, n: int = 5, after: float | None = None, zone: ZoneInfo | None = None) -> list[float]:
    out: list[float] = []
    for ts in iter_runs(expr, after, zone):
        out.append(ts)
        if len(out) >= n:
            break
    return out


def next_run(expr: str, after: float | None = None) -> float | None:
    try:
        r = next_runs(expr, 1, after)
    except CronError:
        return None
    return r[0] if r else None


# ---- humaniser ------------------------------------------------------------------------------
def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _ranges(vals: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for v in vals:
        if out and v == out[-1][1] + 1:
            out[-1] = (out[-1][0], v)
        else:
            out.append((v, v))
    return out


def _names(vals: set[int] | frozenset[int], names: list[str], offset: int = 0) -> str:
    parts = []
    for a, b in _ranges(sorted(vals)):
        if b - a >= 2:
            parts.append(f"{names[a - offset]} to {names[b - offset]}")
        else:
            parts.extend(names[v - offset] for v in range(a, b + 1))
    return _join(parts)


def _ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _step(field: str, lo: int) -> int | None:
    m = re.fullmatch(r"(\*|%d)/(\d+)" % lo, field)
    return int(m.group(2)) if m else None


def humanize(expr: str) -> str:
    """English description: '0 5 * * 1-5' -> 'at 05:00 on Monday to Friday'. Never raises."""
    try:
        c = parse(expr)
    except CronError:
        return expr
    if c.reboot:
        return "at boot"
    special = {"@hourly": "every hour", "@daily": "every day at 00:00", "@midnight": "every day at 00:00",
               "@weekly": "every Sunday at 00:00", "@monthly": "on the 1st of every month at 00:00",
               "@yearly": "every year on January 1st at 00:00", "@annually": "every year on January 1st at 00:00"}
    if c.source.lower() in special:
        return special[c.source.lower()]
    f = SPECIALS.get(c.source.lower(), c.source).split(" ")
    mins, hrs = sorted(c.minutes), sorted(c.hours)

    # -- time of day
    if len(mins) == 60 and len(hrs) == 24:
        when = "every minute"
    elif len(hrs) == 24 and (s := _step(f[0], 0)):
        when = f"every {s} minutes"
    elif len(mins) == 60:
        when = f"every minute during hour{'s' if len(hrs) > 1 else ''} {_join([f'{h:02d}' for h in hrs])}"
    elif len(hrs) == 24:
        when = ("every hour at minute " + _join([str(m) for m in mins])) if mins != [0] else "every hour"
    elif (s := _step(f[1], 0)) and len(mins) == 1:
        when = f"every {s} hours at :{mins[0]:02d}"
    elif len(mins) * len(hrs) <= 6:
        when = "at " + _join([f"{h:02d}:{m:02d}" for h in hrs for m in mins])
    else:
        when = f"at minute {_join([str(m) for m in mins])} of hours {_join([str(h) for h in hrs])}"

    # -- days
    days = ""
    if not c.dom_star:
        if (s := _step(f[2], 1)):
            dom_txt = f"every {s} days"
        else:
            dom_txt = "on the " + _join([_ordinal(d) for d in sorted(c.doms)])
            dom_txt += " of the month" if c.months == frozenset(range(1, 13)) else ""
        days = dom_txt
    if not c.dow_star:
        if c.dows == frozenset({1, 2, 3, 4, 5}):
            dow_txt = "on weekdays"
        elif c.dows == frozenset({0, 6}):
            dow_txt = "on weekends"
        else:
            dow_txt = "on " + _names(c.dows, DAY_NAMES)
        days = f"{days} or {dow_txt}" if days else dow_txt
    if not days and when.startswith("at "):
        days = "every day"
    months = ""
    if c.months != frozenset(range(1, 13)):
        months = "in " + _names(c.months, MONTH_NAMES, 1)
    if days == "every day" and months:
        days = ""
    return " ".join(x for x in (days, when, months) if x) if days == "every day" else \
        " ".join(x for x in (when, days, months) if x)


# =============================================================================================
# Job store
# =============================================================================================
def _dir() -> Path:
    return config.state_dir("crons")


def jobs_path() -> Path:
    return _dir() / "jobs.json"


def runs_path() -> Path:
    return _dir() / "runs.jsonl"


def _load_raw() -> list[dict]:
    data = config.read_json(jobs_path(), {"version": 1, "jobs": []})
    jobs = data.get("jobs") if isinstance(data, dict) else None
    return [j for j in (jobs or []) if isinstance(j, dict) and j.get("id")]


def _save_raw(jobs: list[dict], reason: str = "removed") -> None:
    _remember(_load_raw(), "vanished (jobs.json edited outside Harness Maxxing)")
    config.write_json(jobs_path(), {"version": 1, "jobs": jobs})
    _remember(jobs, reason)


def deleted_path() -> Path:
    return _dir() / "deleted.jsonl"


def _remember(jobs: list[dict], reason: str) -> None:
    """Archive in deleted.jsonl every job of the last known list that is not in `jobs` any more, then remember
    `jobs`. A deleted job (or one dropped by a hand edit of jobs.json) can then be found and restored. Never raises."""
    try:
        seen_p = _dir() / "jobs.seen.json"
        seen = config.read_json(seen_p, None)
        ids = {j.get("id") for j in jobs}
        gone = [j for j in seen if isinstance(j, dict) and j.get("id") not in ids] if isinstance(seen, list) else []
        if gone:
            p = deleted_path()
            lines = p.read_text(encoding="utf-8").splitlines(keepends=True) if p.exists() else []
            for j in gone:
                log.warning("cron job %s (%s) %s", j.get("id"), j.get("name"), reason)
                lines.append(json.dumps({"at": time.time(), "reason": reason, "job": j}, ensure_ascii=False) + "\n")
            tmp = p.with_suffix(".tmp")
            tmp.write_text("".join(lines[-MAX_DELETED:]), encoding="utf-8")
            os.replace(tmp, p)
        if gone or seen != jobs:
            config.write_json(seen_p, jobs)
    except Exception as e:  # noqa: BLE001 - the trace must never break a save
        log.warning("could not keep the trace of removed cron jobs: %s", e)


def deleted_jobs() -> list[dict]:
    """The archived jobs, most recent first ({at, reason, job})."""
    try:
        lines = deleted_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and isinstance(d.get("job"), dict) and d["job"].get("id"):
            out.append(d)
    return out


SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def restore_job(cid: str) -> dict:
    """Put back the most recent archived copy of job `cid`, with its id (CronError if absent or still there)."""
    with _lock:
        jobs = _load_raw()
        if any(j["id"] == cid for j in jobs):
            raise CronError(f"job {cid} exists", "exists")
        if not SAFE_ID.fullmatch(str(cid)):              # the id goes into a crontab line: never shell syntax
            raise CronError(f"invalid job id {cid!r}", "invalid_id")
        job = next((d["job"] for d in deleted_jobs() if d["job"]["id"] == cid), None)
        if job is None:
            raise CronError(f"no removed job {cid}", "not_found")
        jobs.append({**_clean(job), "id": cid, "updated": time.time()})   # checked like a new job
        _save_raw(jobs)
        sync_crontab(jobs)
    return get_job(cid)  # type: ignore[return-value]


DEFAULTS: dict[str, Any] = {
    "name": "", "schedule": "0 5 * * *", "kind": "shell", "command": "", "topic_path": "",
    "prompt": "", "model": "", "reuse_session": False, "enabled": True, "notify": "failure",
    "timeout_s": DEFAULT_TIMEOUT, "permission_mode": "",     # "" = the topic's / global permission mode
}
PERMISSION_MODES = ("", "bypass", "acceptEdits", "default")


def _clean(job: dict) -> dict:
    """Validate and normalise a full job definition (raises CronError)."""
    j = {**DEFAULTS, **{k: v for k, v in job.items() if v is not None}}
    j["name"] = str(j["name"]).strip()
    if not j["name"] or len(j["name"]) > 80:
        raise CronError("name is required (max 80 characters)", "invalid_name")
    j["schedule"] = validate(str(j["schedule"]))
    if j["kind"] not in KINDS:
        raise CronError("kind must be shell or claude", "invalid_kind")
    if j["notify"] not in NOTIFY_POLICIES:
        raise CronError("notify must be never, failure or always", "invalid_notify")
    try:
        j["timeout_s"] = int(j["timeout_s"])
    except (TypeError, ValueError, OverflowError):      # OverflowError: inf / 1e999
        raise CronError("timeout_s must be a number of seconds", "invalid_timeout") from None
    if not 10 <= j["timeout_s"] <= 7 * 86400:
        raise CronError("timeout_s must be between 10 s and 7 days", "invalid_timeout")
    for b in ("enabled", "reuse_session"):
        j[b] = bool(j[b])
    for s in ("command", "topic_path", "prompt", "model", "permission_mode"):
        j[s] = str(j[s] or "")
    if j["permission_mode"] not in PERMISSION_MODES:
        raise CronError("permission_mode must be bypass, acceptEdits, default or empty", "invalid_permission_mode")
    if j["kind"] == "shell":
        if not j["command"].strip():
            raise CronError("a shell job needs a command", "invalid_command")
        if "\n" in j["command"].strip():
            pass                                   # multi-line scripts are fine: run via bash -lc
    else:
        if not j["prompt"].strip():
            raise CronError("a Claude job needs a prompt", "invalid_prompt")
        j["topic_path"] = j["topic_path"].strip().strip("/")
        _check_topic(j["topic_path"])
    return j


def _check_topic(path: str) -> None:
    try:
        from . import workspace                         # owned by core, may still be in progress
        workspace.topic_dir(path)
        return
    except ImportError:
        pass
    except ValueError as e:
        raise CronError(f"topic: {e}", "invalid_topic") from None
    root = config.workspace().resolve()
    p = (root / path).resolve()
    if (p != root and root not in p.parents) or not p.is_dir():
        raise CronError(f"topic '{path}' does not exist", "invalid_topic")


def new_id() -> str:
    return "c_" + _secrets.token_hex(3)


def list_jobs() -> list[dict]:
    """Jobs as API.md `Cron` objects (with last_run, next_run, human, running)."""
    with _lock:
        jobs = _load_raw()
    last = last_runs()
    out = []
    for j in jobs:
        j = {**DEFAULTS, **j}
        r = last.get(j["id"])
        j["last_run"] = ({"at": r.get("at"), "ok": bool(r.get("ok")), "code": r.get("code"),
                          "duration_s": r.get("duration_s")} if r else None)
        try:                                           # a job edited by hand with a broken schedule
            j["next_run"] = next_run(j["schedule"]) if j["enabled"] else None
            j["human"] = humanize(j["schedule"])
        except Exception:
            j["next_run"], j["human"] = None, str(j.get("schedule"))
        j["running"] = is_running(j["id"])
        out.append(j)
    return out


def get_job(cid: str) -> dict | None:
    return next((j for j in list_jobs() if j["id"] == cid), None)


def _raw_job(cid: str) -> dict | None:
    with _lock:
        return next((dict(j) for j in _load_raw() if j.get("id") == cid), None)


_STORED = tuple(DEFAULTS) + ("id", "created", "updated")


def create_job(fields: dict) -> dict:
    j = _clean({k: v for k, v in fields.items() if k in DEFAULTS})
    now = time.time()
    with _lock:
        jobs = _load_raw()
        j.update(id=new_id(), created=now, updated=now)
        while any(x["id"] == j["id"] for x in jobs):
            j["id"] = new_id()
        jobs.append({k: j[k] for k in _STORED})
        _save_raw(jobs)
        sync_crontab(jobs)
    return get_job(j["id"])  # type: ignore[return-value]


def update_job(cid: str, fields: dict) -> dict | None:
    with _lock:
        jobs = _load_raw()
        for i, cur in enumerate(jobs):
            if cur["id"] == cid:
                merged = {**DEFAULTS, **cur, **{k: v for k, v in fields.items() if k in DEFAULTS}}
                j = _clean(merged)
                j.update(id=cid, created=cur.get("created", time.time()), updated=time.time())
                jobs[i] = {**cur, **{k: j[k] for k in _STORED}}
                _save_raw(jobs)
                sync_crontab(jobs)
                break
        else:
            return None
    return get_job(cid)


def delete_job(cid: str) -> bool:
    with _lock:
        jobs = _load_raw()
        rest = [j for j in jobs if j["id"] != cid]
        if len(rest) == len(jobs):
            return False
        _save_raw(rest, "deleted")
        sync_crontab(rest)
        m = config.read_json(_dir() / "sessions.json", {}) or {}
        if m.pop(cid, None):
            config.write_json(_dir() / "sessions.json", m)
    return True


# =============================================================================================
# Run history
# =============================================================================================
_runs_cache: tuple[tuple, list[dict]] | None = None
_runs_lock = threading.Lock()


def _all_runs() -> list[dict]:
    """Every Run of the history file, oldest first; parsed once per file version (path, mtime, size): the
    dashboard, the crons page and the health check read it several times per load (up to ~5 MB)."""
    global _runs_cache
    p = runs_path()
    try:
        st = p.stat()
    except OSError:
        return []
    ident = (str(p), st.st_mtime_ns, st.st_size)
    with _runs_lock:
        if _runs_cache and _runs_cache[0] == ident:
            return _runs_cache[1]
    try:
        with open(p) as f:
            lines = f.readlines()
    except OSError:
        return []
    runs: list[dict] = []
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            runs.append(r)
    with _runs_lock:
        _runs_cache = (ident, runs)
    return runs


def read_runs(cron_id: str | None = None, limit: int = 50) -> list[dict]:
    """Most recent first (copies: callers may annotate them)."""
    out: list[dict] = []
    for r in reversed(_all_runs()):
        if cron_id and r.get("cron_id") != cron_id:
            continue
        out.append(dict(r))
        if len(out) >= limit:
            break
    return out


def last_runs() -> dict[str, dict]:
    """cron_id -> most recent Run."""
    out: dict[str, dict] = {}
    for r in read_runs(limit=MAX_RUNS):
        if isinstance(r, dict):
            out.setdefault(r.get("cron_id", ""), r)
    return out


def append_run(run: dict) -> None:
    """Append one Run (process-safe through flock) and trim the history to MAX_RUNS. The lock is a separate,
    stable file: the trim replaces runs.jsonl, and a writer waiting on the old inode would append to a dead file."""
    p = runs_path()
    with open(p.with_name(p.name + ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(p, "a+") as f:
                f.write(json.dumps(run, ensure_ascii=False) + "\n")
                f.flush()
                f.seek(0)
                lines = f.readlines()
            if len(lines) > MAX_RUNS + 200:            # trim in batches, not on every append
                tmp = p.with_suffix(".tmp")
                tmp.write_text("".join(lines[-MAX_RUNS:]))
                os.replace(tmp, p)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


# =============================================================================================
# Crontab bridge
# =============================================================================================
def maxxing_bin() -> str:
    return shutil.which("maxxing") or "/usr/local/bin/maxxing"


def _crontab_file() -> Path | None:
    p = os.environ.get("MAXXING_CRONTAB_FILE")
    return Path(p) if p else None


def read_crontab() -> str:
    f = _crontab_file()
    if f is not None:
        try:
            return f.read_text()
        except OSError:
            return ""
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout if r.returncode == 0 else ""      # "no crontab for root" -> empty


def write_crontab(text: str) -> None:
    f = _crontab_file()
    if f is not None:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f.suffix + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, f)
        return
    r = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise CronError(f"crontab refused the update: {r.stderr.strip()[:300]}", "crontab_error")


def align_system_timezone(tz: str) -> bool:
    """cron fires in the SYSTEM zone: switch it to `tz` (timedatectl) and restart cron.
    Skipped with an isolated crontab (tests, dev) or MAXXING_SYSTEM_TZ=0. -> True if changed."""
    if _crontab_file() is not None or os.environ.get("MAXXING_SYSTEM_TZ") == "0":
        return False
    try:
        cur = subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        if cur == tz:
            return False
        r = subprocess.run(["timedatectl", "set-timezone", tz], capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return False
        subprocess.run(["systemctl", "restart", "cron"], capture_output=True, timeout=30)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def split_crontab(text: str) -> tuple[list[str], list[str]]:
    """-> (lines outside the managed block, lines inside it)."""
    outside, inside, in_block = [], [], False
    for line in text.splitlines():
        s = line.strip()
        if s == BLOCK_BEGIN:
            in_block = True
        elif s == BLOCK_END:
            in_block = False
        elif in_block:
            inside.append(line)
        else:
            outside.append(line)
    if in_block:                                       # END marker deleted by hand: only our own lines are ours
        outside += [ln for ln in inside if " cron run " not in ln]
        inside = [ln for ln in inside if " cron run " in ln]
    return outside, inside


def _env_prefix() -> str:
    st = os.environ.get("MAXXING_STATE")
    if st and Path(st) != Path("/var/lib/claude-maxxing"):
        return f"MAXXING_STATE={_shq(st)} "
    return ""


def _shq(s: str) -> str:
    return s if re.fullmatch(r"[A-Za-z0-9_./=:-]+", s) else "'" + s.replace("'", "'\\''") + "'"


# ---- server clock kept (existing servers) ----------------------------------------------------
# config.system_clock = "follow" (default: the system zone is switched to config.timezone) or "keep"
# (a server with other programs: its clock is never touched). With "keep" and two different zones,
# a job's crontab line fires every hour at its minutes and `cron run <id> --if-due` checks the
# schedule in config.timezone - so jobs still run at the times the UI shows, DST included.
def keep_system_clock() -> bool:
    return config.load_config().get("system_clock") == "keep"


def system_zone_name() -> str:
    """The zone the cron daemon uses (MAXXING_SYSTEM_ZONE overrides it in tests)."""
    z = os.environ.get("MAXXING_SYSTEM_ZONE", "")
    if not z:
        try:
            z = subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            z = ""
    if not z:
        try:
            z = Path("/etc/timezone").read_text().strip()
        except OSError:
            z = ""
    if not z:
        try:
            z = os.readlink("/etc/localtime").split("zoneinfo/", 1)[-1]
        except OSError:
            z = ""
    return z or "UTC"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def guarded() -> bool:
    """True when crontab lines must be guarded (clock kept and zones that differ)."""
    if not keep_system_clock():
        return False
    a, b = _zone(config.load_config().get("timezone") or "UTC"), _zone(system_zone_name())
    now = dt.datetime.now(dt.timezone.utc)
    return any((now + dt.timedelta(days=30 * k)).astimezone(a).utcoffset()
               != (now + dt.timedelta(days=30 * k)).astimezone(b).utcoffset() for k in range(13))


def _whole_hours_apart() -> bool:
    a, b = _zone(config.load_config().get("timezone") or "UTC"), _zone(system_zone_name())
    now = dt.datetime.now(dt.timezone.utc)
    for k in range(13):
        t = now + dt.timedelta(days=30 * k)
        if (t.astimezone(a).utcoffset() - t.astimezone(b).utcoffset()).total_seconds() % 3600:
            return False
    return True


def is_due(expr: str, at: float | None = None) -> bool:
    """Does `expr` fire at the minute `at` (default now) in config.timezone?"""
    c = parse(expr)
    if c.reboot:
        return True
    t = dt.datetime.fromtimestamp(at if at is not None else time.time(), tz())
    return t.minute in c.minutes and t.hour in c.hours and c.day_matches(t.date())


DETACH_ENV = "MAXXING_CRON_DETACH"   # set by the crontab lines = `--detach` (a flag would break a rolled-back version)


def managed_lines(jobs: list[dict]) -> list[str]:
    exe, env = _shq(maxxing_bin()), _env_prefix()
    guard = guarded()
    whole = guard and _whole_hours_apart()
    out = []
    for j in jobs:
        if not j.get("enabled", True) or not SAFE_ID.fullmatch(str(j.get("id"))):
            continue
        try:
            sched = validate(j.get("schedule", ""))
        except CronError:
            continue
        c = parse(sched)
        if guard and not c.reboot:
            minute = ",".join(map(str, sorted(c.minutes))) if whole and len(c.minutes) < 60 else "*"
            out.append(f"{minute} * * * * {env}{DETACH_ENV}=1 {exe} cron run {j['id']} --if-due >/dev/null 2>&1")
        else:
            out.append(f"{sched} {env}{DETACH_ENV}=1 {exe} cron run {j['id']} >/dev/null 2>&1")
    return out


def sync_crontab(jobs: list[dict] | None = None) -> str:
    """Rewrite the managed block from the job list; everything else is preserved byte for byte
    (except a trailing blank line). Returns the new crontab text."""
    with _lock:
        if jobs is None:
            jobs = _load_raw()
            _remember(jobs, "vanished (jobs.json edited outside Harness Maxxing)")
        outside, _ = split_crontab(read_crontab())
        while outside and not outside[-1].strip():
            outside.pop()
        lines = managed_lines(jobs)
        new = list(outside)
        if lines:
            if new:
                new.append("")
            new += [BLOCK_BEGIN, *lines, BLOCK_END]
        text = "\n".join(new) + "\n" if new else ""
        if text != read_crontab():
            write_crontab(text)
        return text


_ENV_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")


def external_jobs() -> list[dict]:
    """Crontab lines outside the managed block -> [{schedule, command, human}] (read-only)."""
    outside, _ = split_crontab(read_crontab())
    out = []
    for line in outside:
        s = line.strip()
        if not s or s.startswith("#") or _ENV_LINE.match(s):
            continue
        parts = s.split()
        if parts[0].startswith("@"):
            sched, cmd = parts[0], " ".join(parts[1:])
        elif len(parts) >= 6:
            sched, cmd = " ".join(parts[:5]), s.split(None, 5)[5]
        else:
            continue
        out.append({"schedule": sched, "command": cmd, "human": humanize(sched)})
    return out


# =============================================================================================
# Running a job (`maxxing cron run <id>`, executed by cron or by "Run now")
# =============================================================================================
def _lock_path(cid: str) -> Path:
    return config.state_dir("crons", "locks") / f"{cid}.lock"


def is_running(cid: str) -> bool:
    p = _lock_path(cid)
    if not p.exists():
        return False
    try:
        with open(p) as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        return False
    return False


def _tail(path: Path, n: int = OUTPUT_TAIL) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - n))
            data = f.read()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace")
    return ("…" + text) if size > n else text


def _job_env(job: dict) -> dict[str, str]:
    """The environment of a Claude turn, so a script can call `claude -p`: PATH with `claude`, HOME, Harness'
    own Claude Code folder (CLAUDE_CONFIG_DIR when set), the Claude credentials stored in Harness and the
    vault keys flagged `expose`."""
    try:
        from .sessions import spawn
        env = spawn.base_env()
        env.update(spawn.auth_env())
    except Exception:
        env = dict(os.environ)
        try:
            from . import vault
            env.update(vault.exposed_env())
        except Exception:
            pass
    env.update(MAXXING_CRON_ID=job["id"], MAXXING_CRON_NAME=job["name"])
    return env


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _kill_group(proc: subprocess.Popen, grace: float | None = None) -> None:
    """A timed-out job: SIGTERM to its process group, then SIGKILL to the WHOLE group once the grace delay is over -
    even when bash itself already exited (a child that ignores SIGTERM used to survive the failed run). The group
    id stays reserved while one member lives, so the SIGKILL cannot hit an unrelated process. In a job unit, what
    escaped the group (setsid) is killed by systemd when the run ends."""
    pgid = proc.pid
    grace = KILL_GRACE_S if grace is None else grace
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    end = time.monotonic() + grace
    while time.monotonic() < end:
        if proc.poll() is not None and not _group_alive(pgid):
            break
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _timeout(job: dict | None) -> int:
    """The job's timeout in seconds; a hand-edited jobs.json ("30", inf, a list...) falls back to the default."""
    try:
        return int((job or {}).get("timeout_s") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_TIMEOUT


def _run_shell(job: dict) -> tuple[bool, int, str]:
    cwd = config.workspace()
    try:
        proc = subprocess.Popen(["bash", "-lc", job["command"]], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=_job_env(job),
                                cwd=str(cwd) if cwd.is_dir() else None, start_new_session=True)
    except OSError as e:
        return False, 127, f"cannot start bash: {e}"
    tail, size = bytearray(), [0]

    def pump() -> None:                                # only the tail is kept: a chatty job never fills /tmp (RAM)
        assert proc.stdout is not None
        for chunk in iter(lambda: proc.stdout.read1(65536), b""):
            size[0] += len(chunk)
            tail.extend(chunk)
            del tail[:-OUTPUT_TAIL]
    reader = threading.Thread(target=pump, name="cron-output", daemon=True)
    reader.start()
    timed_out = False
    try:
        code = proc.wait(timeout=_timeout(job))
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        code = 124
    except BaseException:                              # never leave the job's process group running unbounded
        _kill_group(proc)
        raise
    reader.join(timeout=2)                             # a background child may keep the pipe open: do not wait for it
    if reader.is_alive():                              # ...but keep draining it, or its next write dies of SIGPIPE
        try:
            drain = subprocess.Popen(["cat"], stdin=proc.stdout, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
            # reaped as soon as the last writer is gone: no zombie `cat` left in the long-lived server
            threading.Thread(target=drain.wait, name="cron-drain", daemon=True).start()
        except OSError:
            pass
    text = bytes(tail).decode("utf-8", "replace")
    if size[0] > OUTPUT_TAIL:
        text = "…" + text
    if timed_out:
        text += f"\n[timed out after {_timeout(job)} s]"
    return code == 0, code, text


def store_mode(sid: str, mode: str) -> None:
    """A reused cron session follows the job's current permission mode."""
    from .sessions import store
    store.update(sid, permission_mode=mode)


def _run_claude(job: dict) -> tuple[bool, int, str, str | None]:
    """Run the prompt as a Claude session turn. -> (ok, code, output_tail, session_id)."""
    from .sessions import service                       # lazy: sessions are owned by core
    when = dt.datetime.now(tz()).strftime("%Y-%m-%d %H:%M")
    title = f"{job['name']} - {when}"
    timeout = _timeout(job)
    env = {"MAXXING_CRON_ID": job["id"], "MAXXING_CRON_NAME": job["name"]}
    smap_path = _dir() / "sessions.json"
    sid = None
    if job.get("reuse_session"):
        prev = (config.read_json(smap_path, {}) or {}).get(job["id"])
        if prev and service.get_session(prev):
            store_mode(prev, job.get("permission_mode") or "")
            service.send_message(prev, job["prompt"], source="cron")
            sid = prev
    if sid is None:
        s = service.create_session(job["topic_path"], message=job["prompt"], title=title,
                                   model=job.get("model") or None, source="cron", notify=False,
                                   cron=True, env=env, timeout_s=timeout,
                                   permission_mode=job.get("permission_mode") or "")
        sid = s["id"]
        if job.get("reuse_session"):
            with _lock:
                m = config.read_json(smap_path, {}) or {}
                m[job["id"]] = sid
                config.write_json(smap_path, m)
    res = service.wait_turn(sid, timeout + 60) or {}
    ok = _turn_ok(res)
    last_result = getattr(service, "last_result", None)
    if ok and callable(last_result):
        try:
            r = last_result(sid)
            if isinstance(r, dict) and r.get("ok") is False:
                ok = False
        except Exception:
            pass
    try:
        text = service.last_assistant_text(sid) or ""
    except Exception:
        text = ""
    if not ok and not text:
        text = str(res.get("error") or "the Harness turn failed or timed out")
    if len(text) > OUTPUT_TAIL:
        text = "…" + text[-OUTPUT_TAIL:]
    return ok, 0 if ok else 1, text, sid


def _turn_ok(res: dict) -> bool:
    """wait_turn returns the session (state) and/or the result event (ok) - accept both shapes."""
    if not isinstance(res, dict):
        return False
    if "ok" in res:
        return bool(res["ok"])
    if isinstance(res.get("result"), dict) and "ok" in res["result"]:
        return bool(res["result"]["ok"])
    if res.get("timeout") or res.get("timed_out"):
        return False
    return res.get("state") == "idle" and not res.get("error")


def run_job(cid: str) -> dict | None:
    """Execute one job now (blocking), record the Run and send the Telegram report.
    Returns the Run, or None when the job does not exist or is already running."""
    job = _raw_job(cid)
    if job is None:
        return None
    job = {**DEFAULTS, **job}
    lockf = open(_lock_path(cid), "w")
    try:
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return None
        lockf.write(str(os.getpid()))
        lockf.flush()
        start = time.time()
        session_id = None
        try:
            if job["kind"] == "claude":
                ok, code, tail, session_id = _run_claude(job)
            else:
                ok, code, tail = _run_shell(job)
        except Exception as e:                           # never die without recording the run
            ok, code, tail = False, 1, f"{type(e).__name__}: {e}"
        run = {"id": "r_" + _secrets.token_hex(4), "cron_id": cid, "name": job["name"], "at": start,
               "ok": ok, "code": code, "duration_s": round(time.time() - start, 2),
               "output_tail": tail, "session_id": session_id}
        append_run(run)
        _notify(job, run)
        return run
    finally:
        try:
            fcntl.flock(lockf, fcntl.LOCK_UN)
        finally:
            lockf.close()


def _feed(job: dict, run: dict) -> None:
    """Every run goes to the notifications feed: failures one by one, successes folded into one row."""
    from . import feed
    url = f"/crons?job={run['cron_id']}"
    if run["ok"]:
        feed.system("Cron jobs succeeded", f"{job['name']} ({fmt_duration(run['duration_s'])})", "success",
                    "crons", url, group="ok")
    else:
        feed.system(f"Cron failed: {job['name']}", (run.get("output_tail") or "")[-600:], "error", "crons", url)


def _notify(job: dict, run: dict) -> None:
    _feed(job, run)
    policy = job.get("notify", "failure")
    if policy == "never" or (policy == "failure" and run["ok"]):
        return
    status = "OK" if run["ok"] else f"FAILED (code {run['code']})"
    text = f"{status} - {job['name']} ({fmt_duration(run['duration_s'])})"
    if not run["ok"] and run.get("output_tail"):
        text += "\n" + run["output_tail"][-600:]
    elif run["ok"] and policy == "always" and (run.get("output_tail") or "").strip():
        text += "\n" + run["output_tail"].strip()[-1500:]      # e.g. a Claude job's brief / reminder
    try:
        from .telegram import gateway
        gateway.notify_cron(text)
    except Exception:
        pass


def fmt_duration(s: float | None) -> str:
    if s is None:
        return "-"
    s = float(s)
    if s < 60:
        return f"{s:.0f} s" if s >= 10 else f"{s:.1f} s"
    if s < 3600:
        return f"{int(s // 60)} min {int(s % 60)} s"
    return f"{int(s // 3600)} h {int(s % 3600 // 60)} min"


def units_available() -> bool:
    """Can jobs run in transient systemd units? (not in tests/dev MAXXING_SPAWN=direct, nor without systemd)."""
    return (os.environ.get("MAXXING_SPAWN") != "direct" and shutil.which("systemd-run") is not None
            and SYSTEMD_DIR.is_dir())


def unit_name(cid: str) -> str:
    return f"maxxing-cron-{cid.replace('_', '-')}"


def unit_properties(job: dict | None) -> list[str]:
    """systemd-run options of a job unit: the jobs slice (their common memory budget), the per-unit memory cap,
    the unit hardening of sessions and a RuntimeMaxSec backstop (if the run itself dies, systemd still stops it)."""
    from .sessions.spawn import hardening_properties, memory_properties
    timeout = _timeout(job)
    return [f"--slice={JOBS_SLICE}", *memory_properties(), *hardening_properties(),
            "--property", f"RuntimeMaxSec={timeout + int(KILL_GRACE_S) + UNIT_RUNTIME_MARGIN_S}"]


def spawn_run(cid: str) -> None:
    """Start `maxxing cron run <id>` detached: in a transient systemd unit (`maxxing-cron-<id>`), or a plain
    subprocess when units are not available (MAXXING_SPAWN=direct, no systemd). Used by "Run now" and by the
    crontab lines (MAXXING_CRON_DETACH / `--detach`). Raises CronError('already_running') if the job is running."""
    if is_running(cid):
        raise CronError("this job is already running", "already_running")
    cmd = [sys.executable, "-m", "maxxing", "cron", "run", cid]
    if not units_available():
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        return
    env_args = [f"--setenv={k}={v}" for k, v in os.environ.items()
                if k.startswith("MAXXING_") and k != DETACH_ENV]          # the unit runs it inline, not again detached
    r = subprocess.run(["systemd-run", "--collect", "--quiet", "--unit", unit_name(cid),
                        "--description", f"Harness Maxxing job {cid}", *unit_properties(_raw_job(cid)),
                        *env_args, "--", *cmd],
                       capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        if "already" in r.stderr.lower() or "exists" in r.stderr.lower():
            raise CronError("this job is already running", "already_running")
        raise CronError(f"systemd-run failed: {r.stderr.strip()[:300]}", "spawn_failed")
