"""Scheduled jobs: cron expressions, job store, run history, crontab bridge and the job runner.

Storage (state_dir("crons")):
  jobs.json     {"version": 1, "jobs": [job]}         - edited by the API (and sometimes by hand)
  jobs.seen.json the job list as last written or synced - to notice a job that vanished
  deleted.jsonl {at, reason, job} per removed job       - last MAX_DELETED kept; `maxxing cron restore <id>`
  runs.jsonl    one Run per line (last MAX_RUNS kept)  - appended by `maxxing cron run` (other process)
  sessions.json {cron_id: session_id}                  - session reused by `reuse_session` Claude jobs
  retries.json  {cron_id: {at, attempt, after, reason}} - the retry waiting after a failed run (see `tick`)
  locks/<id>.lock                                      - flock held while a job runs (no overlap)

The scheduler is the system cron daemon: every enabled job becomes one line of a *managed block*
in root's crontab that calls `MAXXING_CRON_DETACH=1 maxxing cron run <id>` (an environment variable, not a flag: an
older version restored by a rollback ignores it instead of refusing the line): the run starts in a transient systemd unit
(the same one as "Run now": MemoryMax, the `maxxing-jobs.slice` budget, cleanup of every process it left),
or in the cron process itself when systemd is not available. Lines outside the block are never touched.
`last_run` is derived from runs.jsonl at read time, so the runner never rewrites jobs.json (except a one-time job,
disabled or removed once it ran).

The server also calls `tick` every few minutes: it starts once the run of a job missed while the server or the cron
daemon was down (catch-up), and the retries due after a transient failure. Both go through `spawn_run` and are
checked again by `run_job` under the job lock, so they never run twice with the regular crontab line.

Cron expressions are parsed, humanised and evaluated here in pure Python (5 fields, ranges,
steps, lists, month/day names, @daily/@hourly/@weekly/@monthly/@yearly/@reboot), in the
configured time zone.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import logging
import math
import os
import re
import secrets as _secrets
import shlex
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
TRIGGERS = ("manual", "schedule", "catch-up", "retry")   # who started a run (Run.trigger)
CATCH_UP_WINDOW_S = 24 * 3600            # a run missed longer ago than this is not made up for
CATCH_UP_GRACE_S = 180                   # a slot counts as missed only this long after it (the regular run starts)
CATCH_UP_MIN_INTERVAL_S = 3600           # jobs that run more often than hourly are never caught up
CATCH_UP_NEXT_S = 600                    # no catch-up when the next regular run is this close (or 10 % of the interval)
SLOT_SLACK_S = 60                        # a run that started this long before its slot still counts for it
RETRY_BACKOFF_S = (300, 900, 1800)       # wait before retry 1, 2, 3 (then the last value)
MAX_RETRIES = 3                          # automatic retries of a Claude job after a transient failure
MAX_SHELL_RETRIES = 5                    # `retries` of a shell job (0 = none, the default)
LIMIT_RETRY_S = 1800                     # usage limit with no known reset time: try again after this
TICK_ALIVE_S = 900                       # retries are planned only while the server's tick ran this recently
RETRY_OVERDUE_S = 3600                   # a retry this late (server down, tick off) is given up: final failure
ONCE_PAST_S = 60                         # a one-time job may be set at most this long in the past
ONCE_MAX_YEARS = 5                       # ...and at most this many years ahead
SILENT = "[SILENT]"                      # a Claude job's answer starting with it: nothing to report

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
    if names and t in names:                            # exact abbreviations only: cron refuses "monday"
        v = names.index(t) + (1 if names is MONTHS else 0)
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
            if names is DAYS and b == 0 and a > 0 and y.lower() == "sun":
                b = 7                                   # "mon-sun" ends on Sunday, like "1-7" ("sun-sun" is Sunday)
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
    at = after if after is not None else time.time()
    first = (at // 60 + 1) * 60                   # the next whole minute: compared as instants, never as wall
    hours, minutes = sorted(c.hours), sorted(c.minutes)   # times (02:45 of a repeated hour is two instants)
    every_hour = len(hours) == 24                 # "*/10 * * * *" also runs in the repeated autumn hour;
    day = dt.datetime.fromtimestamp(at, zone).date()      # a fixed time ("45 2 * * *") runs once
    last = -1.0
    for _ in range(366 * 5):                      # at most 5 years ahead (e.g. Feb 29 on a Monday)
        if c.day_matches(day):
            for h in hours:
                folds: list[float] = []
                for m in minutes:
                    local = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=zone)
                    ts = local.timestamp()        # a time skipped in spring lands just after the gap
                    if every_hour and (ts1 := local.replace(fold=1).timestamp()) > ts:
                        folds.append(ts1)         # the second pass of a repeated hour
                    if ts >= first and ts > last:  # DST: never yield the same/earlier instant twice
                        last = ts
                        yield ts
                for ts in folds:
                    if ts >= first and ts > last:
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


# ---- one-time jobs ---------------------------------------------------------------------------
# A job with `once_at` ("2026-11-08T09:00", wall time in the configured zone) runs once at that minute instead of
# on a schedule: its crontab line names that minute (it would fire again next year, so `once_pending` checks the
# date), the tick makes up for it when missed, and the run disables it (`done_at`) or removes it (`delete_after`).
def parse_once(value: str, zone: ZoneInfo | None = None) -> str:
    """Normalise a one-time date -> "YYYY-MM-DDTHH:MM" in the configured zone (an offset or a Z is converted to it).
    Raises CronError."""
    text = " ".join(str(value or "").split()).replace(" ", "T", 1)
    try:
        d = dt.datetime.fromisoformat(text)
        if d.tzinfo is not None:
            d = d.astimezone(zone or tz()).replace(tzinfo=None)   # year 1 / 9999 with an offset: out of range
        return d.strftime("%Y-%m-%dT%H:%M")
    except (ValueError, OverflowError):
        raise CronError(f"once_at: '{value}' is not a date and time (YYYY-MM-DDTHH:MM)", "invalid_once") from None


def once_ts(value: str, zone: ZoneInfo | None = None) -> float | None:
    """Unix time of a one-time date (None when it cannot be read: a hand edit)."""
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(parse_once(value, zone)).replace(tzinfo=zone or tz()).timestamp()
    except (CronError, ValueError, OverflowError):
        return None


def once_human(value: str) -> str:
    try:
        return f"once on {parse_once(value).replace('T', ' at ')}"
    except CronError:
        return str(value)


def is_once(job: dict) -> bool:
    return bool(job.get("once_at"))


def once_pending(job: dict, now: float | None = None) -> bool:
    """A one-time job still to run now: enabled, not done, its time reached and not older than the catch-up window."""
    at = once_ts(str(job.get("once_at") or ""))
    now = time.time() if now is None else now
    return (at is not None and bool(job.get("enabled", True)) and not job.get("done_at")
            and at - SLOT_SLACK_S <= now <= at + CATCH_UP_WINDOW_S)


def job_runs(job: dict, after: float | None = None, zone: ZoneInfo | None = None) -> Iterator[float]:
    """The next fire times of a job (a schedule, or the single time of a one-time job not done yet)."""
    if is_once(job):
        at = once_ts(str(job["once_at"]), zone)
        if at is not None and not job.get("done_at") and at > (time.time() if after is None else after):
            yield at
        return
    yield from iter_runs(job.get("schedule") or "", after, zone)


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
    elif len(hrs) == 24 and (s := _step(f[0], 0)) and 60 % s == 0:   # */45 = :00 and :45: listed below
        when = f"every {s} minutes"
    elif len(mins) == 60:
        when = f"every minute during hour{'s' if len(hrs) > 1 else ''} {_join([f'{h:02d}' for h in hrs])}"
    elif len(hrs) == 24:
        when = ("every hour at minute " + _join([str(m) for m in mins])) if mins != [0] else "every hour"
    elif (s := _step(f[1], 0)) and 24 % s == 0 and len(mins) == 1:
        when = f"every {s} hours at :{mins[0]:02d}"
    elif len(mins) * len(hrs) <= 6:
        when = "at " + _join([f"{h:02d}:{m:02d}" for h in hrs for m in mins])
    else:
        when = f"at minute {_join([str(m) for m in mins])} of hours {_join([str(h) for h in hrs])}"

    # -- days (dom_star / dow_star are cron's matching rule: "*/2" is still a restriction to describe)
    dom_any, dow_any = c.doms == frozenset(range(1, 32)), c.dows == frozenset(range(7))
    days = ""
    if not dom_any:
        if (s := _step(f[2], 1)):
            dom_txt = f"every {s} days"
        else:
            dom_txt = "on the " + _join([_ordinal(d) for d in sorted(c.doms)])
            dom_txt += " of the month" if c.months == frozenset(range(1, 13)) else ""
        days = dom_txt
    if not dow_any:
        if c.dows == frozenset({1, 2, 3, 4, 5}):
            dow_txt = "on weekdays"
        elif c.dows == frozenset({0, 6}):
            dow_txt = "on weekends"
        else:
            dow_txt = "on " + _names(c.dows, DAY_NAMES)
        if days:                                   # both restricted and neither "*…": either day runs it
            days = f"{days} or {dow_txt}" if not c.dom_star and not c.dow_star else f"{days} and only {dow_txt}"
        else:
            days = dow_txt
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


def _read_raw() -> list[dict] | None:
    """The jobs of jobs.json ([] when there is no file yet); None when the file exists but cannot be read
    (damaged, truncated): that is not an empty list, nothing may be archived as vanished from it."""
    try:
        with open(jobs_path(), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        return None
    jobs = data.get("jobs", []) if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        return None
    return [j for j in jobs if isinstance(j, dict) and j.get("id") and isinstance(j["id"], str)]


def _load_raw() -> list[dict]:
    return _read_raw() or []


def _load_for_write() -> list[dict]:
    """The jobs to change and save back. An unreadable jobs.json is refused (CronError `damaged_jobs`):
    saving over it would lose every job it held, and take their lines out of the crontab."""
    jobs = _read_raw()
    if jobs is None:
        raise CronError(f"{jobs_path()} cannot be read: repair or remove it first", "damaged_jobs")
    return jobs


def _save_raw(jobs: list[dict], reason: str = "removed") -> None:
    old = _read_raw()
    if old is not None:
        _remember(old, "vanished (jobs.json edited outside Harness Maxxing)")
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
            at = d.get("at")
            if not isinstance(at, (int, float)) or isinstance(at, bool) or not math.isfinite(at):
                d["at"] = 0
            out.append(d)
    return out


SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def restore_job(cid: str, topic_path: str | None = None) -> dict:
    """Put back the most recent archived copy of job `cid`, with its id (CronError if absent or still there).
    topic_path: where its folder is now (an agent or topic restored under another name)."""
    with _lock:
        jobs = _load_for_write()
        if any(j["id"] == cid for j in jobs):
            raise CronError(f"job {cid} exists", "exists")
        if not SAFE_ID.fullmatch(str(cid)):              # the id goes into a crontab line: never shell syntax
            raise CronError(f"invalid job id {cid!r}", "invalid_id")
        job = next((d["job"] for d in deleted_jobs() if d["job"]["id"] == cid), None)
        if job is None:
            raise CronError(f"no removed job {cid}", "not_found")
        if topic_path is not None:
            job = {**job, "topic_path": topic_path}
        old = list(jobs)
        jobs.append({**_clean(job), "id": cid, "updated": time.time()})   # checked like a new job
        _commit(old, jobs)
    return get_job(cid)  # type: ignore[return-value]


DEFAULTS: dict[str, Any] = {
    "name": "", "schedule": "0 5 * * *", "kind": "shell", "command": "", "topic_path": "",
    "prompt": "", "model": "", "reuse_session": False, "enabled": True, "notify": "failure",
    "timeout_s": DEFAULT_TIMEOUT, "permission_mode": "",     # "" = the topic's / global permission mode
    "once_at": "", "delete_after": False,     # one-time job: its date (then `schedule` is ""), removed once it ran
    "catch_up": True, "retries": 0,           # make up for a missed run; automatic retries of a shell job
}
PERMISSION_MODES = ("", "bypass", "acceptEdits", "default", "ask")


def _clean(job: dict) -> dict:
    """Validate and normalise a full job definition (raises CronError)."""
    j = {**DEFAULTS, **{k: v for k, v in job.items() if v is not None}}
    j["name"] = str(j["name"]).strip()
    if not j["name"] or len(j["name"]) > 80:
        raise CronError("name is required (max 80 characters)", "invalid_name")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in j["name"]):   # goes into the run's environment
        raise CronError("the name cannot contain control characters", "invalid_name")
    j["once_at"] = str(j["once_at"] or "").strip()
    if j["once_at"]:
        j["once_at"], j["schedule"] = parse_once(j["once_at"]), ""
    else:
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
    for b in ("enabled", "reuse_session", "delete_after", "catch_up"):
        j[b] = bool(j[b])
    try:
        j["retries"] = int(j["retries"])
    except (TypeError, ValueError, OverflowError):
        raise CronError("retries must be a number", "invalid_retries") from None
    if not 0 <= j["retries"] <= MAX_SHELL_RETRIES:
        raise CronError(f"retries must be between 0 and {MAX_SHELL_RETRIES}", "invalid_retries")
    for s in ("command", "topic_path", "prompt", "model", "permission_mode"):
        j[s] = str(j[s] or "")
    for s in ("name", "command", "topic_path", "prompt", "model"):
        try:                                            # a lone surrogate: jobs.json and the crontab cannot hold it
            j[s].encode("utf-8")
        except UnicodeEncodeError:
            raise CronError(f"{s} is not valid text", f"invalid_{s.split('_')[0]}") from None
    if j["permission_mode"] not in PERMISSION_MODES:
        raise CronError("permission_mode must be bypass, acceptEdits, default, ask or empty", "invalid_permission_mode")
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
    waiting = _read_retries()
    out = []
    for j in jobs:
        j = {**DEFAULTS, **j}
        r = last.get(j["id"])
        j["last_run"] = ({"at": r.get("at"), "ok": bool(r.get("ok")), "code": r.get("code"),
                          "duration_s": r.get("duration_s"), "trigger": r.get("trigger") or "",
                          "attempt": r.get("attempt") or 1, "silent": bool(r.get("silent"))} if r else None)
        try:                                           # a job edited by hand with a broken schedule
            j["next_run"] = next(job_runs(j), None) if j["enabled"] else None
            j["human"] = once_human(j["once_at"]) if is_once(j) else humanize(j["schedule"])
        except Exception:
            j["next_run"], j["human"] = None, str(j.get("schedule"))
        j["once_ts"] = once_ts(str(j["once_at"])) if is_once(j) else None
        w = waiting.get(j["id"])
        j["retry_at"] = w.get("at") if isinstance(w, dict) and j["enabled"] else None
        j["running"] = is_running(j["id"])
        out.append(j)
    return out


def get_job(cid: str) -> dict | None:
    return next((j for j in list_jobs() if j["id"] == cid), None)


def _raw_job(cid: str) -> dict | None:
    with _lock:
        return next((dict(j) for j in _load_raw() if j.get("id") == cid), None)


_STORED = tuple(DEFAULTS) + ("id", "created", "updated")


def _check_once_future(j: dict, now: float) -> None:
    """A one-time job set (or switched back on) must name a time to come: a past one would never run."""
    at = once_ts(j["once_at"])
    if j["enabled"] and at is not None and at < now - ONCE_PAST_S:
        raise CronError("this date and time is already past", "invalid_once")
    if at is not None and at > now + ONCE_MAX_YEARS * 366 * 86400:
        raise CronError(f"this date is more than {ONCE_MAX_YEARS} years away", "invalid_once")


def create_job(fields: dict) -> dict:
    j = _clean({k: v for k, v in fields.items() if k in DEFAULTS})
    now = time.time()
    if j["once_at"]:
        _check_once_future(j, now)
    with _lock:
        jobs = _load_for_write()
        j.update(id=new_id(), created=now, updated=now)
        while any(x["id"] == j["id"] for x in jobs):
            j["id"] = new_id()
        _commit(jobs, jobs + [{k: j[k] for k in _STORED}])
    return get_job(j["id"])  # type: ignore[return-value]


def on_workspace_change(change: dict) -> None:
    """A renamed project / topic keeps its Claude jobs: their topic_path follows (else every run fails)."""
    old, new = change.get("old_path") or "", change.get("path") or ""
    if change.get("action") != "renamed" or not old or not new:
        return
    with _lock:
        jobs = _read_raw()
        if jobs is None:
            return
        moved = False
        for j in jobs:
            tp = str(j.get("topic_path") or "")
            if tp == old or tp.startswith(old + "/"):
                j["topic_path"] = new + tp[len(old):]
                moved = True
        if moved:
            _save_raw(jobs)                    # the crontab lines do not change (they name the job id)


def update_job(cid: str, fields: dict) -> dict | None:
    with _lock:
        jobs = _load_for_write()
        for i, cur in enumerate(jobs):
            if cur["id"] == cid:
                merged = {**DEFAULTS, **cur, **{k: v for k, v in fields.items() if k in DEFAULTS}}
                j = _clean(merged)
                j.update(id=cid, created=cur.get("created", time.time()), updated=time.time())
                new = {**cur, **{k: j[k] for k in _STORED}}
                # a one-time job given a new date, or switched back on, is to run again
                again = j["once_at"] and (j["once_at"] != cur.get("once_at") or (j["enabled"] and not cur.get("enabled", True)))
                if again:
                    _check_once_future(j, time.time())
                    new.pop("done_at", None)
                    new.pop("missed", None)
                if not j["once_at"]:
                    new.pop("done_at", None)
                    new.pop("missed", None)
                if j["enabled"] != bool(cur.get("enabled", True)):
                    _drop_retry(cid)                   # switched off or back on: a waiting retry is cancelled
                _commit(jobs, jobs[:i] + [new] + jobs[i + 1:])
                break
        else:
            return None
    return get_job(cid)


def _commit(old: list[dict], new: list[dict], reason: str = "removed") -> None:
    """The crontab, then jobs.json (under _lock): when jobs.json cannot be written (disk full), the crontab goes back
    to the jobs still saved, so both keep agreeing."""
    sync_crontab(new)
    try:
        _save_raw(new, reason)
    except BaseException:
        with contextlib.suppress(Exception):
            sync_crontab(old)
        raise


def delete_job(cid: str) -> bool:
    with _lock:
        jobs = _load_for_write()
        rest = [j for j in jobs if j["id"] != cid]
        if len(rest) == len(jobs):
            return False
        _commit(jobs, rest, "deleted")
        _forget_job(cid)
    return True


def _forget_job(cid: str) -> None:
    """A removed job leaves no waiting retry and no remembered Claude session."""
    _drop_retry(cid)
    m = config.read_json(_dir() / "sessions.json", {}) or {}
    if m.pop(cid, None):
        config.write_json(_dir() / "sessions.json", m)


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
        with open(p, encoding="utf-8", errors="replace") as f:   # a line cut inside a character must not
            lines = f.readlines()                                # hide the whole history
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
            # bytes: a line cut inside a character (killed writer, full disk) must not break the history
            with open(p, "a+b") as f:
                f.seek(0, os.SEEK_END)
                cut = False
                if f.tell():
                    f.seek(-1, os.SEEK_END)
                    cut = f.read(1) != b"\n"            # start on a new line after a cut one
                # a lone surrogate (an answer cut inside an emoji) cannot be written as UTF-8: replace it
                line = json.dumps(run, ensure_ascii=False).encode("utf-8", "replace") + b"\n"
                f.write((b"\n" if cut else b"") + line)
                f.flush()
                f.seek(0)
                lines = f.readlines()
            if len(lines) > MAX_RUNS + 200:            # trim in batches, not on every append
                tmp = p.with_suffix(".tmp")
                tmp.write_bytes(b"".join(lines[-MAX_RUNS:]))
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
    Skipped with an isolated crontab (tests, dev) or MAXXING_SYSTEM_TZ=0. -> False only when the system zone
    could not be switched (no systemd-timedated, polkit...): cron then still fires in the old zone."""
    if _crontab_file() is not None or os.environ.get("MAXXING_SYSTEM_TZ") == "0":
        return True
    try:
        cur = subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        if cur == tz:
            return True
        r = subprocess.run(["timedatectl", "set-timezone", tz], capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            log.warning("timedatectl set-timezone %s failed: %s", tz, r.stderr.strip()[:200])
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


_LINE_STATE = re.compile(r"(?:^|\s)MAXXING_STATE=('(?:[^']|'\\'')*'|\S+)")


def _ours(line: str) -> bool:
    """Is this managed line one of this install's? Another state dir on the same user (a dev copy, a preview
    server, a script run against a copy) writes its own lines, prefixed with its MAXXING_STATE: kept as they are."""
    m = _LINE_STATE.search(line)
    st = ""
    if m:
        try:
            st = shlex.split(m.group(1))[0]
        except (ValueError, IndexError):
            st = m.group(1)
    mine = os.environ.get("MAXXING_STATE") or ""
    norm = lambda x: "" if not x or Path(x) == Path("/var/lib/claude-maxxing") else str(Path(x))  # noqa: E731
    return norm(st) == norm(mine)


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
    minute = (at if at is not None else time.time()) // 60 * 60
    # the same runs as iter_runs (next run, preview): one run in the repeated autumn hour, and a time
    # skipped in spring runs just after the gap instead of never
    return next(iter_runs(c, minute - 1, tz()), None) == minute


def job_is_due(job: dict, at: float | None = None) -> bool:
    """`--if-due` of a job's line: its schedule, or the minute of a one-time job, matches the minute `at`."""
    if is_once(job):
        when = once_ts(str(job.get("once_at") or ""))
        return when is not None and (at if at is not None else time.time()) // 60 == when // 60
    return is_due(job.get("schedule", ""), at)


def _once_fields(job: dict) -> str | None:
    """The 5 fields that fire a one-time job at its minute (in the configured zone = the cron daemon's when the
    server clock follows it). None when the job is done or its date cannot be read."""
    at = once_ts(str(job.get("once_at") or ""))
    if at is None or job.get("done_at"):
        return None
    d = dt.datetime.fromtimestamp(at, tz())
    return f"{d.minute} {d.hour} {d.day} {d.month} *"


DETACH_ENV = "MAXXING_CRON_DETACH"   # set by the crontab lines = `--detach` (a flag would break a rolled-back version)


def managed_lines(jobs: list[dict]) -> list[str]:
    exe, env = _shq(maxxing_bin()), _env_prefix()
    guard = guarded()
    whole = guard and _whole_hours_apart()
    out = []
    for j in jobs:
        if not j.get("enabled", True) or not SAFE_ID.fullmatch(str(j.get("id"))):
            continue
        if is_once(j):
            fields = _once_fields(j)
            if fields is None:
                continue
            if guard:
                minute = fields.split(" ", 1)[0] if whole else "*"
                out.append(f"{minute} * * * * {env}{DETACH_ENV}=1 {exe} cron run {j['id']} --if-due >/dev/null 2>&1")
            else:
                out.append(f"{fields} {env}{DETACH_ENV}=1 {exe} cron run {j['id']} >/dev/null 2>&1")
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
    (except a trailing blank line). Returns the new crontab text. Without `jobs` and with an unreadable
    jobs.json, the crontab is left as it is: a damaged file is not an empty list of jobs."""
    with _lock:
        if jobs is None:
            jobs = _read_raw()
            if jobs is None:
                log.warning("jobs.json cannot be read: crontab left as it is")
                return read_crontab()
            _remember(jobs, "vanished (jobs.json edited outside Harness Maxxing)")
        outside, inside = split_crontab(read_crontab())
        while outside and not outside[-1].strip():
            outside.pop()
        lines = [ln for ln in inside if not _ours(ln)] + managed_lines(jobs)
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


def _flock_within(f, wait: float) -> bool:
    """Take the job lock, retrying for `wait` s: another process's is_running() holds it for an instant."""
    end = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= end:
                return False
            time.sleep(0.02)


def is_running(cid: str, wait: float = 0.0) -> bool:
    """The probe takes the lock for an instant: callers that refuse to start on True pass `wait`."""
    p = _lock_path(cid)
    if not p.exists():
        return False
    try:
        with open(p) as f:
            if not _flock_within(f, wait):
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
            from . import vault, vault_files
            env.update(vault.exposed_env())
            env.update(vault_files.exposed_files_env())
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
    _note_group(job.get("id"), proc.pid)
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
    t = _claude_turn(job)
    return t["ok"], 0 if t["ok"] else 1, t["text"], t["session_id"]


def _claude_turn(job: dict) -> dict:
    """Run the prompt as a Claude session turn -> {ok, text, session_id, error, timed_out}: `error` is the turn's
    own error (the session's), `text` the whole answer (run_job keeps its start)."""
    from .sessions import service                       # lazy: sessions are owned by core
    from . import agents
    when = dt.datetime.now(tz()).strftime("%Y-%m-%d %H:%M")
    title = f"{job['name']} - {when}"
    timeout = _timeout(job)
    env = {"MAXXING_CRON_ID": job["id"], "MAXXING_CRON_NAME": job["name"]}
    smap_path = _dir() / "sessions.json"
    silent = {"silent_ok": True} if job.get("notify") == "always" else {}   # else the answer stays the full report
    if agents.is_agent_path(job["topic_path"]) and not agents.feature_on():   # Agents switched off: no turn costs
        return {"ok": True, "text": "skipped: Agents is switched off (Settings -> Features)", "session_id": None,
                "error": "", "timed_out": False, "skipped": True}
    sid = None
    if job.get("reuse_session"):
        prev = (config.read_json(smap_path, {}) or {}).get(job["id"])
        if prev and service.get_session(prev):
            store_mode(prev, job.get("permission_mode") or "")
            service.send_message(prev, job["prompt"], source="cron", **silent)
            sid = prev
    if sid is None and agents.is_agent_path(job["topic_path"]):
        # an agent's cron trigger: its budget / rate / on-off decide, the run is written in the agent's thread
        r = agents.fire(job["topic_path"], trigger=f"cron:{job['id']}", prompt=job["prompt"], source="cron",
                        cron_env=env, timeout_s=timeout)
        if not r["started"]:
            return {"ok": True, "text": f"skipped: {agents.SKIP_TEXT.get(r['reason'], r['reason'])}",
                    "session_id": None, "error": "", "timed_out": False, "skipped": True}
        sid = r["session"]["id"]
    if sid is None:
        s = service.create_session(job["topic_path"], message=job["prompt"], title=title,
                                   model=job.get("model") or None, source="cron", notify=False,
                                   cron=True, env=env, timeout_s=timeout,
                                   permission_mode=job.get("permission_mode") or "", **silent)
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
    error = str(res.get("error") or "") if isinstance(res, dict) else ""
    timed_out = (isinstance(res, dict) and res.get("state") == "running") or "Turn stopped (timeout)" in error
    if not ok and not text:
        text = error or "the Harness turn failed or timed out"
    return {"ok": ok, "text": text, "session_id": sid, "error": error, "timed_out": timed_out}


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


_live_locks: dict[str, tuple] = {}                   # cron id -> (open lock file, start) while it runs here


def _proc_start(pid: int) -> str | None:
    """Boot id + start time (clock ticks) of a process: who it is, not just its number (numbers are reused)."""
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        stat = Path(f"/proc/{pid}/stat").read_text()
        return f"{boot}:{stat.rsplit(')', 1)[1].split()[19]}"
    except (OSError, IndexError):
        return None


def _mark(lockf, start: float, pgid: int | None = None) -> None:
    """Write the running run into its lock file: a run killed before its end (SIGKILL, out of memory) leaves it."""
    lockf.seek(0)
    lockf.truncate()
    lockf.write(json.dumps({"pid": os.getpid(), "at": start, "pgid": pgid,
                            "pgid_start": _proc_start(pgid) if pgid else None}))
    lockf.flush()


def _note_group(cid, pgid: int) -> None:
    live = _live_locks.get(cid) if isinstance(cid, str) else None
    if live:
        try:
            _mark(live[0], live[1], pgid)
        except OSError:
            pass


def _interrupted(cid: str, job: dict, lockf) -> dict | None:
    """The run left in the lock file by a killed run_job (we hold the lock now, so it is dead): kill its
    orphan job shell and return a failed Run for it. Older lock files hold a bare pid: ignored."""
    try:
        lockf.seek(0)
        mark = json.loads(lockf.read() or "null")
    except (OSError, ValueError):
        return None
    if not isinstance(mark, dict) or not isinstance(mark.get("at"), (int, float)):
        return None
    pgid = mark.get("pgid")
    # Only the same job shell (same boot, same start time): after a reboot or a pid wrap the number may belong to
    # anything else (a session, a database) and the server runs as root.
    same = isinstance(mark.get("pgid_start"), str) and _proc_start(pgid) == mark["pgid_start"] \
        if isinstance(pgid, int) and pgid > 1 else False
    if same and _group_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
    at = float(mark["at"])
    return {"id": "r_" + _secrets.token_hex(4), "cron_id": cid, "name": job["name"], "at": at,
            "ok": False, "code": -9, "duration_s": round(max(0.0, time.time() - at), 2),
            "output_tail": "interrupted: the run was killed before it ended (out of memory, restart or kill)",
            "session_id": None}


# =============================================================================================
# Retries after a transient failure
# =============================================================================================
# A Claude job that failed because the plan's usage limit was reached is tried again after the reset time (read
# from the answer or from the last limits Claude Code reported, else LIMIT_RETRY_S); one that failed on an API or
# network error is tried again after RETRY_BACKOFF_S. A shell job is retried only when it has `retries`. A timeout
# is never retried (the job would most likely time out again). The retry waits in retries.json until the tick
# starts it: it survives a restart and needs no extra unit.
# Claude Code's own usage-limit message, at the start of a line (an answer quoting another service's "rate limit" is
# not one): "Claude AI usage limit reached|<epoch>", "You've hit your limit · resets 4pm", "5-hour limit reached ∙ …"
_LIMIT_RE = re.compile(r"^\W*(?:claude ai usage limit reached|you(?:'|’)ve hit your (?:\w+ )?limit"
                       r"|(?:5-hour|session|weekly|opus|sonnet|usage) limit reached)", re.I | re.M)
# An answer that is Claude Code's API error: "API Error: 529 {…overloaded_error…}", "API Error: Connection error."
_API_ERROR_RE = re.compile(
    r"^\W*API Error:?\s*(?:5\d\d|429|overloaded|connection|request timed out|fetch failed|terminated)"
    r"|overloaded_error|\"type\":\s*\"api_error\"|rate_limit_error", re.I | re.M)
# The turn's own error (the session's, not free text): API or network trouble
_ERROR_TRANSIENT_RE = re.compile(
    r"overloaded|api error|internal server error|bad gateway|service unavailable|gateway time-?out|rate_limit_error"
    r"|too many requests|connection (?:error|refused|reset|closed)|econnreset|econnrefused|etimedout|enotfound"
    r"|eai_again|socket hang up|network (?:error|is unreachable)|fetch failed|request timed out"
    r"|temporarily unavailable|spawn failed", re.I)
_EPOCH_RE = re.compile(r"limit reached\|(\d{10})")


def classify_failure(text: str, error: str = "") -> str | None:
    """Why a Claude turn failed, when it is worth trying again: "limit" (Claude Code's usage-limit message) or
    "transient" (an API error: overloaded, 5xx, 429, network) or None. Read from the turn's own error and from an
    answer shaped like those messages only: a real answer may mention a 503 or a "rate limit" of another service.
    Only the end of a long answer is read (the error comes last)."""
    text = text or ""
    tail = text if len(text) <= 2000 else text[-1000:]
    error = error or ""
    if _LIMIT_RE.search(error) or _LIMIT_RE.search(tail):
        return "limit"
    if _ERROR_TRANSIENT_RE.search(error) or _API_ERROR_RE.search(tail):
        return "transient"
    return None


def limit_reset(text: str, now: float) -> float | None:
    """When the usage limit that stopped a turn resets: the time in an old-style answer ("…limit reached|<epoch>"),
    else the reset of a full window among the limits Claude Code last reported. None = unknown."""
    m = _EPOCH_RE.search(text or "")
    if m and float(m.group(1)) > now:
        return float(m.group(1))
    try:
        from . import claude_auth
        lim = claude_auth.limits(now) or {}
    except Exception:  # noqa: BLE001
        return None
    full = [w["resets_at"] for w in (lim.get("five_hour"), lim.get("seven_day"))
            if isinstance(w, dict) and isinstance(w.get("resets_at"), (int, float)) and w["resets_at"] > now
            and (w.get("pct") or 0) >= 99.5]
    return max(full) if full else None


def retry_plan(job: dict, *, ok: bool, attempt: int, timed_out: bool, text: str, error: str = "",
               now: float | None = None) -> dict | None:
    """The retry to schedule after a run -> {at, attempt (of the retry), reason} or None (final outcome)."""
    if ok or timed_out or not job.get("enabled", True):
        return None                                    # a job switched off (Run now on it) is never retried later
    now = time.time() if now is None else now
    if job.get("kind") == "claude":
        reason = classify_failure(text, error)
        allowed = MAX_RETRIES if reason else 0
    else:
        reason = "failed"
        try:
            allowed = max(0, min(int(job.get("retries") or 0), MAX_SHELL_RETRIES))
        except (TypeError, ValueError, OverflowError):
            allowed = 0
    if attempt > allowed or reason is None:
        return None
    delay = RETRY_BACKOFF_S[min(attempt - 1, len(RETRY_BACKOFF_S) - 1)]
    if reason == "limit":
        reset = limit_reset(text, now)
        delay = max(60.0, reset + 120 - now) if reset else LIMIT_RETRY_S
        if delay > CATCH_UP_WINDOW_S:
            return None                                # a weekly limit: the next scheduled run will do
    return {"at": now + delay, "attempt": attempt + 1, "reason": reason}


def retries_path() -> Path:
    return _dir() / "retries.json"


def tick_path() -> Path:
    return _dir() / "tick.json"


def tick_alive(now: float | None = None) -> bool:
    """Did the server's tick run lately? Only it starts retries: with the server down or its tick off
    (MAXXING_CRON_TICK=0), a failure is final at once instead of promising a retry that never comes."""
    d = config.read_json(tick_path(), {})
    at = d.get("at") if isinstance(d, dict) else None
    now = time.time() if now is None else now
    return isinstance(at, (int, float)) and now - at <= TICK_ALIVE_S


def _read_retries() -> dict:
    d = config.read_json(retries_path(), {})
    return d if isinstance(d, dict) else {}


def _save_retry(cid: str, entry: dict) -> None:
    with _lock:
        d = _read_retries()
        d[cid] = entry
        config.write_json(retries_path(), d)


def _drop_retry(cid: str) -> None:
    with _lock:
        d = _read_retries()
        if d.pop(cid, None) is not None:
            config.write_json(retries_path(), d)


def _take_retry(cid: str, attempt: int, now: float) -> dict | None:
    """Claim the waiting retry `attempt` of a job (removed from the file). None when there is none any more, or when
    it was overtaken: the job was switched off, removed, or ran again meanwhile (a scheduled run, Run now)."""
    with _lock:
        d = _read_retries()
        entry = d.get(cid)
        if not isinstance(entry, dict) or entry.get("attempt") != attempt:
            return None
        if (entry.get("at") or 0) > now + SLOT_SLACK_S:
            return None                                # not due yet (started by hand with --trigger retry)
        d.pop(cid)
        config.write_json(retries_path(), d)
    job = _raw_job(cid)
    if job is None or not job.get("enabled", True) or (is_once(job) and job.get("done_at")):
        return None
    after = entry.get("after") or 0
    if after < now - CATCH_UP_WINDOW_S:
        return None                                    # a failure of days ago: the job ran on since, or will
    if any((r.get("at") or 0) > after + 1 for r in _runs_of(cid)):
        return None
    return entry


def _runs_of(cid: str) -> list[dict]:
    return [r for r in _all_runs() if r.get("cron_id") == cid]


def _lock_mark(cid: str) -> list[dict]:
    """The run left in the lock file by a run killed before its end (reboot, out of memory), as a Run-like entry
    ([] when there is none). It is recorded "interrupted" only by the job's next run: until then it still counts as
    the run of its slot, so a killed run is never started again by the catch-up. Read without the lock: the tick
    only asks for jobs that are not running."""
    try:
        mark = json.loads(_lock_path(cid).read_text() or "null")
    except (OSError, ValueError):
        return []
    at = mark.get("at") if isinstance(mark, dict) else None
    return [{"at": float(at), "duration_s": 0}] if isinstance(at, (int, float)) and math.isfinite(at) else []


def _known_since(runs: list[dict]) -> float | None:
    """The time of the oldest run of a history that was trimmed (MAX_RUNS reached; None when it holds everything)."""
    if len(runs) < MAX_RUNS:
        return None
    at = runs[0].get("at")
    return float(at) if isinstance(at, (int, float)) else None


# =============================================================================================
# Catch-up of missed runs
# =============================================================================================
def _last_slot(c: CronExpr, now: float, zone: ZoneInfo) -> tuple[float | None, float | None]:
    """(the most recent fire time of `c` in the catch-up window (<= now), the next one after now). The first is
    None when there is none, or when the job runs more often than CATCH_UP_MIN_INTERVAL_S (an every-N-minutes job
    simply runs again soon)."""
    slot = prev = None
    for i, ts in enumerate(iter_runs(c, now - CATCH_UP_WINDOW_S - 1, zone)):
        if prev is not None and ts - prev < CATCH_UP_MIN_INTERVAL_S:
            return None, None
        if ts > now:
            return slot, ts
        if i > 400:
            break
        slot = prev = ts
    return slot, None


def catch_up_slot(job: dict, runs: list[dict], now: float, zone: ZoneInfo,
                  known_since: float | None = None) -> float | None:
    """The missed fire time to make up for now, or None. Pure (job, its runs, a clock): a job is caught up once,
    for its most recent slot of the last 24 h, when that slot is past by CATCH_UP_GRACE_S, no run started at or
    after it, none was still running at that time (an overlap is not a miss), and the job already existed with
    this definition before it (`created` / `updated`; a job without them is never caught up). Never for @reboot,
    jobs running more often than hourly, disabled jobs or `catch_up: false`. A one-time job's slot is its date.
    `known_since`: the oldest run left in a trimmed history - before it, a run may have been dropped, not missed."""
    if not job.get("enabled", True) or job.get("catch_up", True) is False:
        return None
    if is_once(job):
        if job.get("done_at"):
            return None
        slot = once_ts(str(job.get("once_at") or ""), zone)
    else:
        born = [x for x in (job.get("created"), job.get("updated")) if isinstance(x, (int, float))]
        if not born:
            return None
        try:
            c = parse(str(job.get("schedule") or ""))
        except CronError:
            return None
        if c.reboot:
            return None
        slot, nxt = _last_slot(c, now, zone)
        if slot is None or max(born) >= slot:
            return None
        if nxt is not None and nxt - now < max(CATCH_UP_NEXT_S, (nxt - slot) / 10):
            return None                                # the regular run comes soon: no double run
    if slot is None or slot > now - CATCH_UP_GRACE_S or slot < now - CATCH_UP_WINDOW_S:
        return None
    if known_since is not None and known_since > slot - SLOT_SLACK_S:
        return None
    for r in runs:
        at = r.get("at")
        if not isinstance(at, (int, float)):
            continue
        if at >= slot - SLOT_SLACK_S:
            return None                                # it ran (or was retried) for this slot
        dur = r.get("duration_s") if isinstance(r.get("duration_s"), (int, float)) else 0
        if at <= slot <= at + dur + SLOT_SLACK_S:
            return None                                # still running at that time: skipped by the overlap rule
    return slot


def tick(now: float | None = None) -> list[tuple[str, str]]:
    """One pass of the server (start + every TICK_S): start the catch-up runs and the retries that are due, mark the
    one-time jobs missed for good. -> [(job id, trigger)] started. Never raises for one job."""
    now = time.time() if now is None else now
    try:
        config.write_json(tick_path(), {"at": now})    # retries may be planned (tick_alive)
    except OSError:
        pass
    jobs = _read_raw()
    if not jobs:
        return []
    zone, started = tz(), []
    runs: dict[str, list[dict]] = {}
    history = _all_runs()
    since = _known_since(history)
    for r in history:
        runs.setdefault(str(r.get("cron_id")), []).append(r)
    waiting = _read_retries()
    for raw in jobs:
        j = {**DEFAULTS, **raw}
        cid = j["id"]
        if not j["enabled"] or not SAFE_ID.fullmatch(cid) or is_running(cid):
            continue
        try:
            w = waiting.get(cid)
            if isinstance(w, dict) and not (isinstance(w.get("after"), (int, float))
                                            and w["after"] >= now - CATCH_UP_WINDOW_S):
                _drop_retry(cid)                       # a failure older than a day: never retried now
                w = None
            if isinstance(w, dict) and isinstance(w.get("at"), (int, float)) and w["at"] < now - RETRY_OVERDUE_S:
                _drop_retry(cid)                       # the server was down or its tick off: it is final now
                _give_up_retry(j, w, runs.get(cid, []))
                w = None
            if isinstance(w, dict) and isinstance(w.get("at"), (int, float)) and w["at"] <= now:
                spawn_run(cid, "retry", int(w.get("attempt") or 2))
                started.append((cid, "retry"))
                continue
            done = runs.get(cid, []) + _lock_mark(cid)
            if is_once(j) and not j.get("done_at") and not isinstance(w, dict):
                at = once_ts(j["once_at"], zone)
                if at is not None and any((r.get("at") or 0) >= at - SLOT_SLACK_S for r in done):
                    _finish_once(cid, ran=j)           # it ran (or was killed) but was not marked done
                    continue
                if (at or now) < now - CATCH_UP_WINDOW_S:
                    _finish_once(cid, missed=True, ran=j)
                    continue
            if catch_up_slot(j, done, now, zone, since) is not None and not isinstance(w, dict):
                spawn_run(cid, "catch-up")
                started.append((cid, "catch-up"))
        except Exception as e:  # noqa: BLE001 - one job must not stop the others
            log.warning("cron %s: tick: %s", cid, e)
    return started


def _give_up_retry(job: dict, entry: dict, runs: list[dict]) -> None:
    """A retry that could not run in time: its failed run is reported as the final outcome (feed + Telegram per
    `notify`), which the failure that planned it did not do."""
    run = next((r for r in reversed(runs) if r.get("id") == entry.get("run_id")), None) or \
        {"id": entry.get("run_id") or "", "cron_id": job["id"], "name": job["name"], "at": entry.get("after") or 0,
         "ok": False, "code": 1, "duration_s": 0, "output_tail": "", "session_id": None}
    final = {k: v for k, v in run.items() if k != "retry_at"}
    final["output_tail"] = ((final.get("output_tail") or "").rstrip()
                            + "\n[not retried: the server could not start the retry in time]").lstrip()
    _notify(job, final)


def _finish_once(cid: str, missed: bool = False, ran: dict | None = None) -> None:
    """A one-time job ran (or was missed for good): disabled and marked done, or removed with `delete_after`
    (archived in deleted.jsonl like any removed job). `ran`: the job as it was when its run started - given a new
    date (or delete_after changed) meanwhile, it is left as the person set it."""
    with _lock:
        jobs = _read_raw()
        if jobs is None:
            return
        job = next((j for j in jobs if j["id"] == cid), None)
        if job is None or not is_once(job):
            return
        if ran is not None and (job.get("once_at") != ran.get("once_at")
                                or bool(job.get("delete_after")) != bool(ran.get("delete_after"))):
            return
        if job.get("delete_after") and not missed:
            rest = [j for j in jobs if j["id"] != cid]
            sync_crontab(rest)
            _save_raw(rest, "removed (one-time job done)")
            _forget_job(cid)
            return
        job["enabled"], job["done_at"] = False, time.time()
        if missed:
            job["missed"] = True
        sync_crontab(jobs)
        _save_raw(jobs)
    if missed:
        try:
            from . import feed
            feed.system(f"One-time job missed: {job.get('name')}",
                        f"It was due at {str(job.get('once_at')).replace('T', ' ')} and the server could not run it "
                        "within 24 h.", "warning", "crons", f"/settings/crons?job={cid}")
        except Exception:  # noqa: BLE001
            pass


def is_silent(answer: str | None) -> bool:
    """A Claude job's answer that says there is nothing to report: `[SILENT]` alone, or at the very start."""
    s = (answer or "").strip().lstrip("`*_ ").upper()
    return s.startswith(SILENT)


def _skip_reason(cid: str, trigger: str, attempt: int, now: float) -> str | None:
    """Checked under the job lock, just before a run: a catch-up or a retry started by the tick may have been
    overtaken meanwhile (the regular run, Run now), and a one-time job's crontab line fires every year."""
    job = _raw_job(cid)
    if job is None:
        return "gone"
    job = {**DEFAULTS, **job}
    if trigger == "catch-up":
        if catch_up_slot(job, _runs_of(cid), now, tz(), _known_since(_all_runs())) is None:
            return "not missed any more"
    elif trigger == "retry":
        if _take_retry(cid, attempt, now) is None:
            return "retry cancelled"
    elif trigger == "schedule" and is_once(job):
        if not once_pending(job, now) or any((r.get("at") or 0) >= (once_ts(job["once_at"]) or 0) - SLOT_SLACK_S
                                             for r in _runs_of(cid)):
            return "one-time job already done"
    return None


def run_job(cid: str, trigger: str = "manual", attempt: int = 1) -> dict | None:
    """Execute one job now (blocking), record the Run and send the Telegram report.
    Returns the Run, None when the job does not exist or is already running, or {"skipped": reason} when a
    catch-up / retry / one-time run is not due any more (checked under the job lock)."""
    job = _raw_job(cid)
    if job is None:
        return None
    job = {**DEFAULTS, **job}
    trigger = trigger if trigger in TRIGGERS else "manual"
    attempt = max(1, int(attempt or 1))
    lockf = open(_lock_path(cid), "a+")                 # not "w": the mark of a killed run is read first
    lost = run = None
    retry = None
    try:
        if not _flock_within(lockf, 1.0):
            return None
        # a run killed before its end is recorded first: it counts as the run of its slot (never caught up again)
        lost = _interrupted(cid, job, lockf)
        if lost:
            try:
                append_run(lost)
            except Exception:
                log.exception("cron %s: cannot record the interrupted run", cid)
            lockf.seek(0)
            lockf.truncate()
            lockf.flush()
        why = _skip_reason(cid, trigger, attempt, time.time())
        if why:
            log.info("cron %s: %s run skipped: %s", cid, trigger, why)
            return {"skipped": why, "cron_id": cid}     # the interrupted run is still reported (finally)
        slot = catch_up_slot(job, _runs_of(cid), time.time(), tz()) if trigger == "catch-up" else None
        start = time.time()
        _mark(lockf, start)
        _live_locks[cid] = (lockf, start)
        session_id = None
        answer = None
        error, timed_out = "", False
        try:
            if job["kind"] == "claude":
                turn = _claude_turn(job)
                ok, answer, session_id = turn["ok"], turn["text"], turn["session_id"]
                code, error, timed_out = 0 if ok else 1, turn["error"], turn["timed_out"]
                tail = _clip_head(answer, OUTPUT_TAIL)  # an answer starts with its title and summary
            else:
                ok, code, tail = _run_shell(job)
                timed_out = code == 124 and tail.rstrip().endswith(f"[timed out after {_timeout(job)} s]")
        except Exception as e:                           # never die without recording the run
            ok, code, tail = False, 1, f"{type(e).__name__}: {e}"
        now = time.time()
        timed_out = timed_out or (not ok and now - start >= _timeout(job) * 0.98)
        run = {"id": "r_" + _secrets.token_hex(4), "cron_id": cid, "name": job["name"], "at": start,
               "ok": ok, "code": code, "duration_s": round(now - start, 2),
               "output_tail": tail, "session_id": session_id, "trigger": trigger}
        if attempt > 1:
            run["attempt"] = attempt
        if slot is not None:
            run["slot"] = slot
        if ok and job["kind"] == "claude" and is_silent(answer):
            run["silent"] = True
        retry = retry_plan(job, ok=ok, attempt=attempt, timed_out=timed_out, text=answer or tail, error=error,
                           now=now) if tick_alive(now) else None
        if retry:
            run["retry_at"] = retry["at"]
            try:
                _save_retry(cid, {**retry, "after": start, "run_id": run["id"]})
            except Exception:
                log.exception("cron %s: cannot keep the retry", cid)
                retry = None
                run.pop("retry_at", None)
        if not retry:
            try:
                _drop_retry(cid)                       # a run that plans none ends any older retry
            except Exception:  # noqa: BLE001
                log.exception("cron %s: cannot drop the retry", cid)
        try:
            append_run(run)
        except Exception:                                # the report still goes out
            log.exception("cron %s: cannot record the run", cid)
        if is_once(job) and not retry and start >= (once_ts(job["once_at"]) or math.inf) - SLOT_SLACK_S:
            try:
                _finish_once(cid, ran=job)               # its run is over: disabled (done) or removed
            except Exception:
                log.exception("cron %s: cannot mark the one-time job done", cid)
    finally:
        _live_locks.pop(cid, None)
        try:
            if run is not None:                          # ended normally: nothing left to report
                lockf.seek(0)
                lockf.truncate()
                lockf.flush()
            fcntl.flock(lockf, fcntl.LOCK_UN)
        finally:
            lockf.close()
        if lost:
            _notify(job, lost)
    _notify(job, run, answer)                            # after the lock: a slow Telegram never holds the job
    return run


def _feed(job: dict, run: dict) -> None:
    """Every run goes to the notifications feed: failures one by one, successes folded into one row."""
    from . import feed
    url = f"/settings/crons?job={run['cron_id']}"
    more = _run_note(run)
    if run["ok"]:
        quiet = " · nothing to report" if run.get("silent") else ""
        feed.system("Cron jobs succeeded", f"{job['name']} ({fmt_duration(run['duration_s'])}{more}){quiet}",
                    "success", "crons", url, group="ok")
    else:
        out = run.get("output_tail") or ""
        body = _clip_head(out, 600) if job.get("kind") == "claude" else _clip_tail(out, 600)
        if run.get("retry_at"):                          # not the end: said once, quietly (no Telegram)
            when = dt.datetime.fromtimestamp(run["retry_at"], tz()).strftime("%H:%M")
            feed.system(f"Cron will retry: {job['name']}",
                        f"Attempt {run.get('attempt') or 1} failed, next attempt at {when}.\n\n{body}".strip(),
                        "warning", "crons", url)
        else:
            feed.system(f"Cron failed: {job['name']}", (f"{more.strip(' ·')}\n\n" if more else "") + body,
                        "error", "crons", url)


def _run_note(run: dict) -> str:
    """" · catch-up of 09:00" / " · attempt 2": what the report says about how the run was started."""
    if run.get("trigger") == "catch-up" and isinstance(run.get("slot"), (int, float)):
        return f" · catch-up of {dt.datetime.fromtimestamp(run['slot'], tz()):%Y-%m-%d %H:%M}"
    if (run.get("attempt") or 1) > 1:
        return f" · attempt {run['attempt']}"
    return ""


def _clip_head(text: str, n: int) -> str:
    from .telegram import format as tgfmt
    return tgfmt.head(text, n)


def _clip_tail(text: str, n: int) -> str:
    from .telegram import format as tgfmt
    return tgfmt.tail(text, n)


def _notify(job: dict, run: dict, answer: str | None = None) -> None:
    """Feed + Telegram report. A Claude job's report is its answer from the start (markdown, rendered
    in Telegram); a command's report is the end of its output (where errors are)."""
    _feed(job, run)
    policy = job.get("notify", "failure")
    if policy == "never" or (policy == "failure" and run["ok"]):
        return
    if run.get("silent") or run.get("retry_at"):
        return                                         # nothing to report / not the final outcome yet
    status = "OK" if run["ok"] else f"FAILED (code {run['code']})"
    header = f"{status} - {job['name']} ({fmt_duration(run['duration_s'])}){_run_note(run)}"
    claude = job.get("kind") == "claude"
    body = ""
    if not run["ok"] or policy == "always":
        if claude:
            body = (answer if answer is not None else run.get("output_tail") or "").strip()
        else:
            body = _clip_tail(run.get("output_tail") or "", 600 if not run["ok"] else 1500)
    try:
        from .telegram import gateway
        gateway.notify_cron_report(header, body, markdown=claude, loud=not run["ok"])
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


def spawn_run(cid: str, trigger: str = "manual", attempt: int = 1) -> None:
    """Start `maxxing cron run <id>` detached: in a transient systemd unit (`maxxing-cron-<id>`), or a plain
    subprocess when units are not available (MAXXING_SPAWN=direct, no systemd). Used by "Run now", by the
    crontab lines (MAXXING_CRON_DETACH / `--detach`) and by the tick (catch-up, retry). Raises
    CronError('already_running') if the job is running."""
    if is_running(cid, wait=1.0):
        raise CronError("this job is already running", "already_running")
    cmd = [sys.executable, "-m", "maxxing", "cron", "run", cid]
    if trigger != "manual":
        cmd += ["--trigger", trigger] + (["--attempt", str(attempt)] if attempt > 1 else [])
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
