"""Server health (GET /api/system/health), services and the experimental Claude usage probe.

No psutil: everything is read from /proc and systemctl. `collect()` is cached 30 s and is
blocking (call it through asyncio.to_thread from async code).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import config

CACHE_S = 30
DISK_WARN, DISK_ERROR = 90.0, 97.0
MEM_MIN = 500 * 1024 * 1024
BACKUP_MAX_AGE_H = 48
CORE_SERVICES = ["claude-maxxing", "caddy", "tailscaled", "cron"]
SELF_UNIT = "claude-maxxing"
LABELS = {"claude-maxxing": "Harness Maxxing", "caddy": "Caddy (HTTPS)", "tailscaled": "Tailscale",
          "cron": "Cron scheduler"}
WATCHED = ("claude-maxxing", "caddy", "cron")       # inactive while enabled -> issue

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "data": None}
_cpu_prev: tuple[float, int, int] | None = None     # (time, busy, total)
_cpu_last: float | None = None


# ---- /proc readers --------------------------------------------------------------------------
def _cpu_times() -> tuple[int, int]:
    with open("/proc/stat") as f:
        vals = [int(x) for x in f.readline().split()[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)        # idle + iowait
    total = sum(vals[:8])                                     # guest time is already in user
    return total - idle, total


def cpu_pct() -> float | None:
    """CPU usage since the previous call (since the server started for the first one). Does not sleep (it waited
    0.25 s on every first call), except after more than 10 min without a call: a 0.1 s sample.
    Calls closer than 1 s apart repeat the last value."""
    global _cpu_prev, _cpu_last
    try:
        now = time.time()
        busy, total = _cpu_times()
        prev = _cpu_prev
        if prev is None:
            _cpu_prev = (now, busy, total)
            return None
        if now - prev[0] > 600:                       # a long pause: its average says nothing of the load now
            time.sleep(0.1)
            prev = (now, busy, total)
            busy, total = _cpu_times()
            now = time.time()
        elif now - prev[0] < 1 and _cpu_last is not None:   # after a pause the 0.1 s sample is always < 1 s old
            return _cpu_last
        _cpu_prev = (now, busy, total)
        dt = total - prev[2]
        _cpu_last = round(100.0 * (busy - prev[1]) / dt, 1) if dt > 0 else 0.0
        return _cpu_last
    except (OSError, ValueError, IndexError):
        return None


def meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, rest = line.partition(":")
                parts = rest.split()
                if parts:
                    out[k] = int(parts[0]) * 1024
    except (OSError, ValueError):
        pass
    total = out.get("MemTotal", 0)
    avail = out.get("MemAvailable", out.get("MemFree", 0) + out.get("Cached", 0))
    return {"total": total, "avail": avail}


def loadavg() -> list[float]:
    try:
        with open("/proc/loadavg") as f:
            return [float(x) for x in f.read().split()[:3]]
    except (OSError, ValueError):
        return [0.0, 0.0, 0.0]


def uptime_s() -> float:
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def disk(path: Path | None = None) -> dict[str, float]:
    p = Path(path or config.workspace())
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        u = shutil.disk_usage(p)
    except OSError:
        return {"total": 0, "free": 0, "pct": 0.0}
    return {"total": u.total, "free": u.free, "pct": round(100.0 * (u.total - u.free) / u.total, 1) if u.total else 0.0}


# ---- services -------------------------------------------------------------------------------
def service_names() -> list[str]:
    extra = config.load_config().get("services_extra") or []
    names = list(CORE_SERVICES)
    for n in extra:
        if isinstance(n, str) and n and n not in names:
            names.append(n)
    return names


_PROPS = ("Id", "LoadState", "ActiveState", "UnitFileState", "ActiveEnterTimestampMonotonic", "Description")
SERVICES_CACHE_S = 10
_svc_cache: dict[str, Any] = {"at": 0.0, "key": None, "data": None}


def _systemctl_show_all(names: list[str]) -> dict[str, dict[str, str]]:
    """One `systemctl show a b c ...` for every unit -> {name: properties} ({} when it failed).
    systemctl prints one block per unit, separated by a blank line, in the order asked."""
    if not names:
        return {}
    cmd = ["systemctl", "show", *names, "--no-pager"]
    for p in _PROPS:
        cmd += ["-p", p]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    blocks = [dict(line.split("=", 1) for line in b.splitlines() if "=" in line)
              for b in r.stdout.strip().split("\n\n")] if r.stdout.strip() else []
    out: dict[str, dict[str, str]] = {}
    for i, info in enumerate(blocks):
        uid = info.get("Id", "")
        name = next((n for n in names if uid in (n, n + ".service")), names[i] if i < len(names) else None)
        if name and name not in out:
            out[name] = info
    return out


def _systemctl_show(name: str) -> dict[str, str]:
    return _systemctl_show_all([name]).get(name, {})


def _state(name: str, info: dict[str, str]) -> dict[str, Any] | None:
    if not info or info.get("LoadState") in ("not-found", "", None):
        return None
    active = info.get("ActiveState") == "active"
    since = None
    mono = info.get("ActiveEnterTimestampMonotonic", "0")
    if active and mono.isdigit() and int(mono) > 0:
        since = round(time.time() - (time.monotonic() - int(mono) / 1e6), 0)
    return {"name": name, "label": LABELS.get(name) or info.get("Description") or name, "active": active,
            "enabled": info.get("UnitFileState") in ("enabled", "enabled-runtime", "static", "alias"),
            "since": since, "state": info.get("ActiveState", "")}


def service_state(name: str) -> dict[str, Any] | None:
    """{name, label, active, enabled, since, state} or None when the unit is not installed."""
    return _state(name, _systemctl_show(name))


def services(force: bool = False) -> list[dict]:
    """Managed services, one systemctl call for all of them, cached SERVICES_CACHE_S seconds
    (invalidate_services() after a start / stop / restart)."""
    names = service_names()
    with _lock:
        c = _svc_cache
        if not force and c["data"] is not None and c["key"] == names and time.time() - c["at"] < SERVICES_CACHE_S:
            return [dict(s) for s in c["data"]]
    infos = _systemctl_show_all(names)
    data = [s for s in (_state(n, infos.get(n, {})) for n in names) if s]
    with _lock:
        _svc_cache.update(at=time.time(), key=names, data=data)
    return [dict(s) for s in data]


def invalidate_services() -> None:
    with _lock:
        _svc_cache["data"] = None


# ---- other probes ---------------------------------------------------------------------------
def claude_auth_state() -> dict:
    """claude_auth.status() (real-call based); credentials passed through the environment count
    as configured."""
    from . import claude_auth as ca
    st = ca.status()
    if st["method"] is None and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")):
        st = {**st, "ok": True, "method": "env", "detail": "Credentials in the environment"}
    return st


def claude_auth() -> bool:
    """True when Claude Code has credentials and the last real call did not fail to sign in."""
    return bool(claude_auth_state()["ok"])


def last_backup() -> dict | None:
    """Last entry of the backup history (owned by the backup module; read defensively)."""
    p = config.STATE / "backup" / "history.jsonl"
    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 8192))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("at"), (int, float)):
            return e
    return None


def backup_configured() -> bool:
    return bool((config.load_config().get("backup") or {}).get("repo"))


def failed_crons(hours: float = 24) -> list[dict]:
    """Jobs whose most recent run failed within `hours`."""
    try:
        from . import crons
        cutoff = time.time() - hours * 3600
        return [r for r in crons.last_runs().values() if not r.get("ok") and (r.get("at") or 0) >= cutoff]
    except Exception:
        return []


# ---- collect --------------------------------------------------------------------------------
def collect(force: bool = False) -> dict:
    """GET /api/system/health payload (cached CACHE_S seconds)."""
    with _lock:
        if not force and _cache["data"] is not None and time.time() - _cache["at"] < CACHE_S:
            return dict(_cache["data"])
    data = _collect()
    with _lock:
        _cache.update(at=time.time(), data=data)
    return dict(data)


def invalidate_cache() -> None:
    with _lock:
        _cache["at"] = 0.0


def _issue(level: str, code: str, text: str) -> dict:
    return {"level": level, "code": code, "text": text}


# ---- issues marked as seen ------------------------------------------------------------------
SEEN_TTL_S = 24 * 3600              # a seen issue still there comes back after this
_seen_lock = config.ProcessLock("health-seen")   # read-modify-write of health-seen.json: two marks at once lost one


def _seen_path() -> Path:
    return config.STATE / "health-seen.json"


def issue_id(issue: dict) -> str:
    """Stable id of an issue: its code and text without the numbers ("Last backup is 31 h old" keeps the id of
    "30 h old"; another job failing is another issue). Quoted names keep their digits ("Backup 1" / "Backup 2")."""
    text = "".join(part if i % 2 else "".join(c for c in part if not c.isdigit())
                   for i, part in enumerate(re.split(r'("[^"]*")', issue["text"])))
    key = issue["code"] + ":" + text
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _read_seen() -> dict[str, float]:
    d = config.read_json(_seen_path(), {})
    return {k: float(v) for k, v in d.items() if isinstance(v, (int, float))} if isinstance(d, dict) else {}


def _apply_seen(issues: list[dict]) -> None:
    """Adds `id` and `seen` to each issue; forgets the marks of issues gone or older than SEEN_TTL_S."""
    with _seen_lock:
        seen = _read_seen()
        now = time.time()
        keep: dict[str, float] = {}
        for i in issues:
            i["id"] = issue_id(i)
            at = seen.get(i["id"])
            i["seen"] = at is not None and now - at < SEEN_TTL_S
            if i["seen"]:
                keep[i["id"]] = at
        if keep != seen:
            try:
                config.write_json(_seen_path(), keep)
            except OSError:
                pass


def mark_seen(iid: str, seen: bool = True) -> bool:
    """Marks a current issue as seen (or not): False when no current issue has that id."""
    if iid not in {i["id"] for i in collect(force=True)["issues"]}:
        return False
    with _seen_lock:
        marks = _read_seen()
        if seen:
            marks[iid] = time.time()
        else:
            marks.pop(iid, None)
        config.write_json(_seen_path(), marks)
    invalidate_cache()
    return True


def _collect() -> dict:
    issues: list[dict] = []
    mem = meminfo()
    dsk = disk()
    if dsk["pct"] >= DISK_WARN:
        issues.append(_issue("error" if dsk["pct"] >= DISK_ERROR else "warn", "disk_full",
                             f"Disk {dsk['pct']:.0f} % full ({dsk['free'] / 1e9:.1f} GB free)"))
    if mem["total"] and mem["avail"] < MEM_MIN:
        issues.append(_issue("warn", "low_memory", f"Only {mem['avail'] // (1024 * 1024)} MB of RAM available"))
    infos = _systemctl_show_all(list(WATCHED))
    for name in WATCHED:
        st = _state(name, infos.get(name, {}))
        if st and st["enabled"] and not st["active"]:
            issues.append(_issue("error", "service_down", f"Service {st['label']} is {st['state'] or 'inactive'}"))
    for r in failed_crons():
        issues.append(_issue("warn", "cron_failed", f"Scheduled job \"{r.get('name', r.get('cron_id'))}\" failed "
                                                     f"(code {r.get('code')})"))
    from . import security                        # imports FastAPI: not at module level (CLI `maxxing status`)
    fails = security.failures_last_hour()
    if fails >= security.FAIL_MAX:
        issues.append(_issue("warn", "login_failures", f"{fails} failed sign-ins in the last hour"))
    ast = claude_auth_state()
    auth = bool(ast["ok"])
    if ast["method"] is None:
        issues.append(_issue("error", "claude_auth", "Claude is not connected (Settings > Claude)"))
    elif not auth:
        issues.append(_issue("error", "claude_auth", "Claude sign-in expired - sign in again in Settings > Claude"
                             + (f" ({ast['error'][:160]})" if ast.get("error") else "")))
    age_h = None
    if backup_configured():
        last = last_backup()
        if last is None:
            issues.append(_issue("warn", "backup_never", "The memory backup has never run"))
        else:
            age_h = round((time.time() - float(last["at"])) / 3600, 1)
            if age_h > BACKUP_MAX_AGE_H:
                issues.append(_issue("warn", "backup_old", f"Last memory backup is {age_h:.0f} h old"))
            elif last.get("ok") is False:
                issues.append(_issue("warn", "backup_failed", "The last memory backup failed"))
    _apply_seen(issues)
    return {"ok": not issues, "issues": issues, "cpu_pct": cpu_pct(), "load": loadavg(), "mem": mem,
            "disk": dsk, "uptime_s": uptime_s(), "claude_auth": auth, "claude_auth_error": ast.get("error"),
            "claude_checked_at": ast.get("checked_at"), "backup_age_h": age_h,
            "failed_logins_1h": fails, "at": time.time()}


# ---- Claude plan usage (experimental, undocumented endpoint) --------------------------------
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
_usage: dict[str, Any] = {"at": 0.0, "data": None, "blocked_until": 0.0}
RATE_LIMIT_DEFAULT_S = 900           # Anthropic's usage endpoint answered 429 without Retry-After
RATE_LIMIT_MAX_S = 2 * 3600
TURN_FRESH_S = 600                   # limits seen in a turn younger than this: no call to the endpoint
USAGE_WAIT_S = 30                    # a request waits this long for the call already in flight
_usage_lock = threading.Lock()


def _window(d: Any) -> dict | None:
    if not isinstance(d, dict):
        return None
    pct = d.get("utilization", d.get("percent"))
    try:
        pct = round(float(pct), 1) if pct is not None else None
    except (TypeError, ValueError, OverflowError):
        pct = None
    if pct is not None and not math.isfinite(pct):   # NaN / Infinity: not valid JSON
        pct = None
    return {"pct": pct, "resets_at": _epoch(d.get("resets_at"))}


def _epoch(v: Any) -> float | None:
    """A reset time in Unix seconds (the endpoint gives ISO 8601)."""
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, str) and v:
        import datetime as _dt
        try:
            return _dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def map_usage(u: dict) -> dict:
    """Accept both known shapes: top-level {five_hour, seven_day} or a `limits` list
    with kinds `session` / `weekly_all`."""
    five = _window(u.get("five_hour"))
    seven = _window(u.get("seven_day"))
    for lim in u.get("limits") or []:
        if not isinstance(lim, dict):
            continue
        if five is None and lim.get("kind") in ("session", "five_hour"):
            five = _window(lim)
        if seven is None and lim.get("kind") in ("weekly_all", "seven_day", "weekly"):
            seven = _window(lim)
    return {"available": five is not None or seven is not None, "five_hour": five, "seven_day": seven}


def usage(force: bool = False) -> dict:
    """Plan usage. Never raises. First source: the limits Claude Code printed in the last turn (no call, always on,
    `source: "turn"`, `seen_at`); with config usage_widget, the experimental endpoint when those are older than
    TURN_FRESH_S or missing.
    The usage endpoint is rate limited hard (Retry-After up to an hour): while it asks to wait, no call is made,
    even with `force`, and the last good values are returned flagged `stale` (or `reason: rate_limited`), with
    `retry_at`. Whatever the endpoint says, a reading without values never hides the limits seen in a turn."""
    from . import claude_auth
    seen = claude_auth.limits()                       # free: the last limits printed by a turn
    if not config.load_config().get("usage_widget"):
        return seen or {"available": False, "reason": "disabled", "five_hour": None, "seven_day": None}
    now = time.time()
    if seen and now - float(seen.get("seen_at") or 0) < TURN_FRESH_S:
        return seen
    data = _endpoint_usage(force, now)
    if not data.get("available") and seen:
        return seen
    return data


def _block_file() -> Path:
    return config.STATE / "claude-usage-block.json"


def _restore_block() -> None:
    """Once per process (and state dir): the Retry-After of the last 429 survives a restart. Lock held."""
    p = _block_file()
    if _usage.get("block_from") == str(p):
        return
    _usage["block_from"] = str(p)
    try:
        until = json.loads(p.read_text()).get("blocked_until")
    except (OSError, ValueError, AttributeError):
        return
    if isinstance(until, (int, float)) and math.isfinite(until):
        _usage["blocked_until"] = max(_usage["blocked_until"], min(float(until), time.time() + RATE_LIMIT_MAX_S))


def _endpoint_usage(force: bool, now: float) -> dict:
    """The usage endpoint, cached 60 s and silent while it asks to wait (see usage())."""
    with _usage_lock:
        _restore_block()
        blocked = _usage["blocked_until"] > now
        if (blocked or not force) and _usage["data"] is not None and (blocked or now - _usage["at"] < 60):
            return dict(_usage["data"])
        if blocked:
            return {"available": False, "reason": "rate_limited", "retry_at": _usage["blocked_until"],
                    "five_hour": None, "seven_day": None}
        inflight = _usage.get("inflight")
        mine = inflight is None
        if mine:
            inflight = _usage["inflight"] = threading.Event()
    if not mine:                                      # a call is already out: share its answer, never a 2nd call
        inflight.wait(USAGE_WAIT_S)
        with _usage_lock:
            data = dict(_usage["data"]) if _usage["data"] is not None else {
                "available": False, "reason": "error", "five_hour": None, "seven_day": None}
        return data
    try:
        data = _fetch_usage()
        with _usage_lock:
            retry = data.pop("_retry_after", None)
            if retry is not None:
                _usage["blocked_until"] = time.time() + retry
                data["retry_at"] = _usage["blocked_until"]
                try:
                    config.write_json(_block_file(), {"blocked_until": _usage["blocked_until"]})
                except OSError:
                    pass
            prev = _usage["data"]
            if data.get("available") or prev is None or not prev.get("available"):
                _usage.update(at=time.time(), data=data)
            else:                                     # keep the last good values, flag them stale
                data = dict(prev, stale=data.get("reason", "error"),
                            **({"retry_at": data["retry_at"]} if "retry_at" in data else {}))
                _usage.update(at=time.time(), data=data)
    finally:
        with _usage_lock:
            _usage["inflight"] = None
        inflight.set()                                # after the cache update: waiters read the fresh values
    return dict(data)


def _oauth_token() -> tuple[str | None, str | None]:
    """(token, reason when none): the long-lived token stored in Harness Maxxing (`claude setup-token`, what the
    sessions use) first, else the `claude login` credentials file. An API key has no plan usage."""
    tok = config.get_secret("claude_oauth_token")
    if tok:
        return tok, None
    from . import claude_auth
    creds = config.read_json(claude_auth.credentials_file(), {}) or {}
    tok = ((creds.get("claudeAiOauth") or {}) if isinstance(creds, dict) else {}).get("accessToken")
    if tok:
        return tok, None
    return None, "api_key" if config.get_secret("anthropic_api_key") else "no_oauth_credentials"


def _retry_after(value: str | None) -> float:
    try:
        return max(30.0, min(float(value), RATE_LIMIT_MAX_S)) if value else RATE_LIMIT_DEFAULT_S
    except ValueError:
        return RATE_LIMIT_DEFAULT_S


def _fetch_usage() -> dict:
    empty = {"available": False, "five_hour": None, "seven_day": None}
    try:
        token, why = _oauth_token()
        if not token:
            return {**empty, "reason": why}
        import httpx
        r = httpx.get(USAGE_URL, timeout=10, headers={"Authorization": f"Bearer {token}",
                                                       "anthropic-beta": "oauth-2025-04-20",
                                                       "Accept": "application/json"})
        if r.status_code == 429:
            return {**empty, "reason": "rate_limited", "_retry_after": _retry_after(r.headers.get("retry-after"))}
        if r.status_code != 200:
            return {**empty, "reason": f"http_{r.status_code}"}
        return map_usage(r.json())
    except Exception as e:                            # network, JSON, anything: never raise
        return {**empty, "reason": type(e).__name__}


try:                                                          # baseline at import: the first call has a real value
    cpu_pct()
except Exception:  # noqa: BLE001
    pass
