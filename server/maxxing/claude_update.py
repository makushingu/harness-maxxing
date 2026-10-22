"""Claude Code updates itself while the server is idle. See docs/dev/INTERNALS.md#maxxingclaude_update.

Turns start Claude Code with its own update check off (quiet start), so without this the CLI only moves when
someone runs `claude update`. Off by default (config `claude_auto_update`). Every CHECK_EVERY_S the `stable`
release (npm dist-tag: a release already out for some days, not the newest one) is read from the npm registry;
when it is newer than the installed one and nothing runs (no session turn running or waiting, no cron job, no side
question, the last turn ended more than IDLE_AFTER_S ago), that exact version is installed the way Claude Code was
installed (`claude install <v>` for the native installer, `npm install -g` in the same prefix for npm; another
install is left alone). The update holds <state>/.claude-update.lock exclusively: a turn holds it shared while its
Claude runs (sessions/runner.py), so an update never starts under a running Claude and a turn starting meanwhile
waits for it. A version that does not start after the update is rolled back to the previous one.

State: <state>/claude-update.json = {checked_at, latest, installed, last: {from, to, at, ok, error} | null,
failed_version, failed_at}. Tests replace `latest_version`, `installed_version` and `run_update`.
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from . import config, depcheck, feed

log = logging.getLogger("maxxing.claude_update")

CHECK_EVERY_S = 6 * 3600          # registry check period
POLL_S = 300                      # an update waiting for idleness is retried this often
IDLE_AFTER_S = 600                # the last turn must have ended this long ago
UPDATE_TIMEOUT_S = 300
FIRST_DELAY_S = 600               # first pass after the server starts
_VERSION = re.compile(r"\d+\.\d+\.\d+")
_lock = threading.Lock()
_task: asyncio.Task | None = None


def state_file() -> Path:
    return config.STATE / "claude-update.json"


def load() -> dict:
    d = config.read_json(state_file(), {})
    return d if isinstance(d, dict) else {}


def _save(d: dict) -> None:
    config.write_json(state_file(), d, mode=0o600)


def enabled(cfg: dict | None = None) -> bool:
    return bool((cfg or config.load_config()).get("claude_auto_update", False))


def public() -> dict:
    """GET /api/claude/status `auto_update`."""
    d = load()
    return {"enabled": enabled(), "checked_at": d.get("checked_at"), "latest": d.get("latest"),
            "last": d.get("last") or None}


# ---- probes (replaced in tests) --------------------------------------------------------------
def _bin() -> str | None:
    from .api import claude as claude_api
    return claude_api._resolved_bin()


def installed_version() -> str | None:
    """`claude --version`, read fresh (no cache: called right after an update)."""
    from .sessions import spawn
    b = _bin()
    if not b:
        return None
    try:
        r = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=20, env=spawn.base_env())
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = _VERSION.search(r.stdout or "") if r.returncode == 0 else None
    return m.group(0) if m else None


def latest_version() -> str | None:
    """The `stable` release of Claude Code (not `latest`: a release out for some days already)."""
    return depcheck.claude_stable()


def install_method() -> tuple[str, list[str]] | None:
    """("native" | "npm", command prefix to install a given version) from where the claude binary really is; None
    for another kind of install (left alone: updated by hand)."""
    b = _bin()
    if not b:
        return None
    real = os.path.realpath(b)
    if "/.local/share/claude/versions/" in real:
        return "native", [b, "install"]
    marker = "/lib/node_modules/@anthropic-ai/claude-code/"
    if marker in real:
        prefix = real.split(marker)[0]
        npm = os.path.join(prefix, "bin", "npm")
        if not os.access(npm, os.X_OK):
            from .sessions import spawn
            import shutil
            npm = shutil.which("npm", path=spawn.base_env().get("PATH")) or ""
        if npm:
            return "npm", [npm, "install", "-g", "--prefix", prefix, "--no-fund", "--no-audit"]
    return None


def run_update(version: str) -> tuple[bool, str]:
    """Install exactly `version` the way Claude Code is installed -> (exit code 0, output tail)."""
    from .sessions import spawn
    how = install_method()
    if how is None:
        return False, "Claude Code is not installed by the official installer or npm: update it by hand"
    kind, cmd = how
    arg = version if kind == "native" else f"@anthropic-ai/claude-code@{version}"
    try:
        r = subprocess.run([*cmd, arg], capture_output=True, text=True, timeout=UPDATE_TIMEOUT_S,
                           env=spawn.base_env(), stdin=subprocess.DEVNULL, cwd=str(config.STATE))
    except subprocess.TimeoutExpired:
        return False, f"No end within {UPDATE_TIMEOUT_S // 60} min"
    except OSError as e:
        return False, str(e)
    return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()[-400:]


def _exclusive() -> int | None:
    """The update lock, exclusive, without waiting: None while a turn's Claude holds it (shared)."""
    from .sessions import runner
    try:
        fd = os.open(config.STATE / runner.UPDATE_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        os.close(fd)
        return None


# ---- idleness --------------------------------------------------------------------------------
def busy_reason(now: float | None = None) -> str | None:
    """Why an update must wait (None = the server is idle)."""
    from . import crons
    from .sessions import aside, service, store
    now = time.time() if now is None else now
    last_end = 0.0
    for sid in store.list_ids():
        m = store.read_cached(sid)
        if m is None:
            continue
        s = service.public(m)
        if s["state"] == "running":
            return "a turn is running"
        if s["queue"] and s["state"] != "error":
            return "a message is waiting"
        last_end = max(last_end, float(m.get("finished_at") or 0))
    if aside._busy:
        return "a side question is running"
    try:
        if any(crons.is_running(j["id"]) for j in crons.list_jobs()):
            return "a cron job is running"
    except Exception:  # noqa: BLE001 - unreadable cron files: do not block, do not crash
        log.exception("cron state unreadable")
    if now - last_end < IDLE_AFTER_S:
        return "a turn ended less than 10 min ago"
    return None


def _newer(latest: str | None, installed: str | None) -> bool:
    if not latest or not installed:
        return False
    a, b = depcheck._vtuple(installed), depcheck._vtuple(latest)
    return len(a) == 3 and len(b) == 3 and b > a


# ---- one pass --------------------------------------------------------------------------------
def tick(now: float | None = None, force_check: bool = False) -> str:
    """One pass -> what happened: off | not_installed | unknown | up_to_date | unsupported | busy |
    failed_recently | updated | failed. The registry is read at most every CHECK_EVERY_S (or when `force_check`)."""
    if not _lock.acquire(blocking=False):
        return "busy"
    try:
        return _tick(time.time() if now is None else now, force_check)
    finally:
        _lock.release()


def _tick(now: float, force_check: bool) -> str:
    if not enabled():
        return "off"
    d = load()
    due = force_check or not d.get("latest") or now - float(d.get("checked_at") or 0) >= CHECK_EVERY_S
    if not due and not _newer(d.get("latest"), d.get("installed")):
        return "up_to_date"                 # between two checks, nothing pending: not even `claude --version`
    installed = installed_version()
    if not installed:
        return "not_installed"
    d["installed"] = installed
    if due:
        d["checked_at"] = now
        d["latest"] = latest_version() or d.get("latest")
    _save(d)
    latest = d.get("latest")
    if not latest:
        return "unknown"
    if not _newer(latest, installed):
        return "up_to_date"
    if d.get("failed_version") == latest and now - float(d.get("failed_at") or 0) < CHECK_EVERY_S:
        return "failed_recently"
    if install_method() is None:
        return "unsupported"
    if busy_reason(now):
        return "busy"
    fd = _exclusive()                       # no Claude of a turn running, and none starts until it is released
    if fd is None:
        return "busy"
    try:
        if busy_reason(now):                # checked again under the lock
            return "busy"
        ok, out = run_update(latest)
        from .api import claude as claude_api
        claude_api._version_cache.clear()
        after = installed_version()
        if not after and installed:          # the new version does not start: back to the one that worked
            log.warning("Claude Code %s does not start: back to %s", latest, installed)
            run_update(installed)
            claude_api._version_cache.clear()
            after = installed_version()
            out = (out + f"\nClaude Code {latest} did not start: back to {after or installed}").strip()
    finally:
        os.close(fd)
    at = time.time()
    if ok and after and not _newer(latest, after):
        d.update(installed=after, last={"from": installed, "to": after, "at": at, "ok": True, "error": None},
                 failed_version=None, failed_at=None)
        _save(d)
        feed.system(f"Claude Code updated to {after}", f"From {installed}, while nothing was running.", "success",
                    "system", "/settings/claude")
        return "updated"
    if not ok:
        err = out or "The update failed"
    elif after:
        err = f"The update ended but Claude Code is still {after}" + (f": {out}" if out else "")
    else:
        err = "Claude Code does not start after the update (and could not be put back)"
    d.update(installed=after or installed, failed_version=latest, failed_at=at,
             last={"from": installed, "to": latest, "at": at, "ok": False, "error": err[-400:]})
    _save(d)
    feed.system(f"Claude Code could not update to {latest}", f"{err[-600:]}\nBy hand: claude update", "error",
                "system", "/settings/claude", dedupe=f"claude-update-failed:{latest}")
    return "failed"


# ---- background loop -------------------------------------------------------------------------
async def _loop() -> None:
    await asyncio.sleep(float(os.environ.get("MAXXING_CLAUDE_UPDATE_DELAY", FIRST_DELAY_S)))
    while True:
        try:
            await asyncio.to_thread(tick)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Claude Code update pass failed")
        await asyncio.sleep(POLL_S)


DEFAULT_STATE = "/var/lib/claude-maxxing"


def runs_here() -> bool:
    """`claude update` changes the CLI of the whole machine: only the installed server does it. A second server on
    the same machine (a dev server, a test copy of the state: another MAXXING_STATE) never does, unless
    MAXXING_CLAUDE_UPDATE=1; MAXXING_CLAUDE_UPDATE=0 turns it off everywhere."""
    flag = os.environ.get("MAXXING_CLAUDE_UPDATE", "")
    if flag in ("0", "1"):
        return flag == "1"
    if os.path.realpath(config.STATE) == os.path.realpath(DEFAULT_STATE):
        return True
    try:                                               # installed with another STATE_DIR: the service itself
        return Path("/proc/self/cgroup").read_text().rstrip().endswith("/claude-maxxing.service")
    except OSError:
        return False


def start() -> None:
    global _task
    if not runs_here():
        return
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop())


def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        _task = None
