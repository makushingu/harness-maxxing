"""Harness Maxxing updates itself while nobody uses it. See docs/dev/INTERNALS.md#maxxingauto_update.

Off by default (config `auto_update`, Settings -> Updates). Every POLL_S, when it is on, the update is started only if
ALL of these hold:
- nobody is on the interface (no browser holds the /api/stream connection) and nothing runs (no turn, no queued
  message, no cron job, no side question, the last turn ended more than 10 minutes ago: `claude_update.busy_reason`);
- the simulated update (`smartupdate.preflight`) is "simple": no conflict with a customization, none to review, no
  unsaved change in the code folder and no extension the new version drops (those need a Harness session: the
  person is told instead, once per version). An upgrade note does not hold the update back: the notes only change
  the workspace, they are announced in the notifications once the new version runs (`smartupdate.after_update`);
- the code folder is on a branch (a detached HEAD = a branch under test, never moved unattended) and no update is
  pending (a conflict or a rolled-back version waits for a person, it is not retried every day);
- the same target was not tried in the last 24 hours (`maxxing update` rolls itself back when the new version does
  not start; one attempt per version a day, never a loop).
The update is the usual `maxxing update --auto` (not `--smart`: no Harness session is opened unattended). Only the
installed server does it (`claude_update.runs_here`). While the server is busy the next pass comes after BUSY_POLL_S
instead of POLL_S, so a short quiet moment between two jobs is not missed.

State: <state>/auto-update.json = {tried: {target, version, at}, last_check: {at, verdict}, last: {at, result, why?}}
(`last` = what the last pass decided, shown under the switch). Tests replace `preflight`, `busy_reason`, `browsers`
and the `spawn` argument of `tick`.
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
BUSY_POLL_S = 5 * 60
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
    return {"enabled": enabled(), "tried": d.get("tried"), "last_check": d.get("last_check"), "last": d.get("last")}


def browsers() -> int:
    return bus.browser_count()


def _update_running() -> bool:
    from . import cmd_core
    lock = cmd_core.update_lock()                      # a `maxxing update` from a terminal holds it too
    if lock is None:
        return True
    lock.close()
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


# what holds the update back, as the short word kept in `last.why` (the interface has a sentence for each)
WHY = {"someone is on the interface": "browser", "a turn is running": "turn", "a message is waiting": "queue",
       "a side question is running": "aside", "a cron job is running": "cron",
       "a turn ended less than 10 min ago": "recent", "an update is already running": "update"}


def busy_reason(now: float | None = None) -> str | None:
    """Why the update must wait (None = nobody is here and nothing runs)."""
    if browsers():
        return "someone is on the interface"
    return claude_update.busy_reason(now) or ("an update is already running" if _update_running() else None)


def preflight() -> dict:
    from . import smartupdate
    return smartupdate.preflight(None, True)


def _simple(rep: dict) -> bool:
    """No conflict, nothing to review, nothing unsaved, no extension dropped. Upgrade notes do not count: they ask
    for changes in the workspace, made after the update whoever started it."""
    return (rep.get("verdict") == "simple" and not rep.get("unsaved")
            and all(c.get("status") in ("ok", "included") for c in rep.get("customs") or []))


def _decide(spawn, now: float, d: dict) -> tuple[str, str | None]:
    """(result, what holds the update back). Fills `d` (the state) with what the pass learned."""
    if not on_branch():
        return "not_on_branch", None
    if pending_update():
        return "pending", None
    why = busy_reason(now)
    if why:
        return "busy", why
    rep = preflight()                                   # fetches: only once the server is known to be idle
    d["last_check"] = {"at": now, "verdict": rep.get("verdict")}
    if not rep.get("ok"):
        return "unavailable", None
    if rep.get("verdict") == "up_to_date":
        return "up_to_date", None
    target, version = rep.get("target"), rep.get("latest")
    if not _simple(rep):
        feed.system(f"Harness {version} is available but needs you",
                    "The automatic update waits: a customization or an unsaved change of the code needs a look. "
                    "Update with Harness from Settings -> Updates.", "info", "system", "/settings/updates",
                    dedupe=f"auto-update-review:{version}")
        return "needs_review", None
    tried = d.get("tried") or {}
    if tried.get("target") == target and now - float(tried.get("at") or 0) < RETRY_TARGET_S:
        return "tried_recently", None
    why = busy_reason(now)                              # the preflight takes a while: somebody may have come
    if why:
        return "busy", why
    d["tried"] = {"target": target, "version": version, "at": now}
    config.write_json(state_file(), d, mode=0o600)      # before the update: it restarts this server
    try:
        spawn()
    except Exception as e:  # noqa: BLE001 - not started: said under the switch, tried again tomorrow (never a loop)
        log.warning("automatic update to %s could not start: %s", version, getattr(e, "detail", None) or e)
        return "failed", None
    feed.system(f"Harness is updating to {version}", "Automatic update: nobody was on the interface and nothing "
                "was running. The service restarts for a few seconds.", "info", "system", "/settings/updates")
    return "started", None


def tick(spawn, now: float | None = None) -> str:
    """One pass -> off | not_on_branch | pending | busy | unavailable | up_to_date | needs_review | tried_recently
    | failed | started. What it decided is kept in the state (`last`) and logged when it changes."""
    now = time.time() if now is None else now
    if not enabled():
        return "off"
    d = load()
    before = d.get("last") if isinstance(d.get("last"), dict) else {}
    result, why = _decide(spawn, now, d)
    d["last"] = {"at": now, "result": result, **({"why": WHY.get(why, "work")} if why else {})}
    config.write_json(state_file(), d, mode=0o600)
    if (before.get("result"), before.get("why")) != (result, d["last"].get("why")):
        log.info("automatic update: %s%s", result, f" ({why})" if why else "")
    return result


async def _loop(spawn) -> None:
    await asyncio.sleep(float(os.environ.get("MAXXING_AUTO_UPDATE_DELAY", FIRST_DELAY_S)))
    while True:
        result = ""
        try:
            result = await asyncio.to_thread(tick, spawn)
        except Exception:  # noqa: BLE001
            log.exception("automatic update pass failed")
        await asyncio.sleep(BUSY_POLL_S if result == "busy" else POLL_S)


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
