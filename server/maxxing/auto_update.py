"""Harness Maxxing updates itself while nobody uses it. See docs/dev/INTERNALS.md#maxxingauto_update.

Off by default (config `auto_update`, Settings -> Updates). Every POLL_S, when it is on, the update is started only if
ALL of these hold:
- nobody is on the interface (no browser holds the /api/stream connection) and nothing runs (no turn, no queued
  message, no cron job, no side question, the last turn ended more than 10 minutes ago: `claude_update.busy_reason`);
- the simulated update (`smartupdate.preflight`) is "simple": no conflict with a customization, none to review, no
  unsaved change in the code folder, no extension the new version drops, and no upgrade note asking for an action
  (those need a Harness session: the person is told instead, once per version);
- the code folder is on a branch (a detached HEAD = a branch under test, never moved unattended) and no update is
  pending (a conflict or a rolled-back version waits for a person, it is not retried every day);
- the same target was not tried in the last 24 hours (`maxxing update` rolls itself back when the new version does
  not start; one attempt per version a day, never a loop).
The update is the usual `maxxing update` (without `--smart`: no Harness session is opened unattended). Only the
installed server does it (`claude_update.runs_here`).

State: <state>/auto-update.json = {tried: {target, at}, last_check: {at, verdict}}. Tests replace `preflight`,
`busy_reason`, `browsers` and the `spawn` argument of `tick`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time

from . import bus, claude_update, config, feed

log = logging.getLogger("maxxing.auto_update")

POLL_S = 30 * 60
FIRST_DELAY_S = 15 * 60
RETRY_TARGET_S = 24 * 3600
_task: asyncio.Task | None = None


def enabled(cfg: dict | None = None) -> bool:
    return bool((cfg or config.load_config()).get("auto_update", False))


def state_file():
    return config.STATE / "auto-update.json"


def load() -> dict:
    d = config.read_json(state_file(), {})
    return d if isinstance(d, dict) else {}


def public() -> dict:
    d = load()
    return {"enabled": enabled(), "tried": d.get("tried"), "last_check": d.get("last_check")}


def browsers() -> int:
    return bus.browser_count()


def _update_running() -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", "maxxing-update"], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() in ("active", "activating")
    except (OSError, subprocess.SubprocessError):
        return False


def on_branch() -> bool:
    """False on a detached HEAD: somebody put a branch under test there on purpose."""
    from . import cmd_core
    return bool(cmd_core._start_branch())


def pending_update() -> bool:
    from . import customs
    return bool(customs.pending())


def busy_reason(now: float | None = None) -> str | None:
    """Why the update must wait (None = nobody is here and nothing runs)."""
    if browsers():
        return "someone is on the interface"
    why = claude_update.busy_reason(now)
    if why:
        return why
    if _update_running():
        return "an update is already running"
    return None


def preflight() -> dict:
    from . import smartupdate
    return smartupdate.preflight(None, True)


def _simple(rep: dict) -> bool:
    """No conflict, nothing to review, nothing unsaved, no extension dropped, no upgrade note asking for an action."""
    return (rep.get("verdict") == "simple" and not rep.get("notes") and not rep.get("unsaved")
            and all(c.get("status") in ("ok", "included") for c in rep.get("customs") or []))


def tick(spawn, now: float | None = None) -> str:
    """One pass -> off | not_on_branch | pending | busy | unavailable | up_to_date | needs_review | tried_recently
    | started."""
    now = time.time() if now is None else now
    if not enabled():
        return "off"
    if not on_branch():
        return "not_on_branch"
    if pending_update():
        return "pending"
    if busy_reason(now):
        return "busy"
    rep = preflight()                                   # fetches: only once the server is known to be idle
    d = load()
    d["last_check"] = {"at": now, "verdict": rep.get("verdict")}
    if not rep.get("ok"):
        config.write_json(state_file(), d, mode=0o600)
        return "unavailable"
    if rep.get("verdict") == "up_to_date":
        config.write_json(state_file(), d, mode=0o600)
        return "up_to_date"
    target, version = rep.get("target"), rep.get("latest")
    if not _simple(rep):
        config.write_json(state_file(), d, mode=0o600)
        feed.system(f"Harness {version} is available but needs you",
                    "The automatic update waits: a customization, an unsaved change or an upgrade note needs a "
                    "look. Update with Harness from Settings -> Updates.", "info", "system", "/settings/system",
                    dedupe=f"auto-update-review:{target}")
        return "needs_review"
    tried = d.get("tried") or {}
    if tried.get("target") == target and now - float(tried.get("at") or 0) < RETRY_TARGET_S:
        return "tried_recently"
    if busy_reason(now):                                # the preflight takes a while: somebody may have come
        return "busy"
    d["tried"] = {"target": target, "version": version, "at": now}
    config.write_json(state_file(), d, mode=0o600)
    feed.system(f"Harness is updating to {version}", "Automatic update: nobody was on the interface and nothing "
                "was running. The service restarts for a few seconds.", "info", "system", "/settings/system")
    spawn()
    return "started"


async def _loop(spawn) -> None:
    await asyncio.sleep(float(os.environ.get("MAXXING_AUTO_UPDATE_DELAY", FIRST_DELAY_S)))
    while True:
        try:
            await asyncio.to_thread(tick, spawn)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("automatic update pass failed")
        await asyncio.sleep(POLL_S)


def start(spawn) -> None:
    global _task
    if not claude_update.runs_here():
        return
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop(spawn))


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
