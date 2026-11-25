"""Daily budget of the whole server (Settings -> Usage -> Daily budget, config `daily_budget_usd`, 0 = none).

What every session cost today (the cost Claude Code reports for each turn: real money with an API key, the price the
same tokens would have on a subscription) against one amount in dollars:
- at 80 % and when it is reached, one event in the Notifications feed (so Telegram, by the feed's rules);
- once reached, what starts by itself waits for tomorrow: scheduled jobs that run a prompt and the agents' triggers
  are skipped (crons._claude_turn, agents.gate). What the user asks for still runs: their messages in a session or to
  an agent, "Run now". An agent keeps its own daily budget (agents.py) besides this one.
The day is the one of the Harness time zone (store.day_of), as for the agents' budgets and the Usage page.
"""
from __future__ import annotations

import logging
import math
import os
import time

from . import config
from .sessions import store

log = logging.getLogger("maxxing.budget")

MAX_USD = 100000.0
WARN_AT = 0.8
REF = "budget:reached"                  # the open alert while the budget is reached (resolved once work runs again)
URL = "/settings/usage"
SKIP_TEXT = "Daily budget of the server reached (Settings -> Usage)"


def limit() -> float:
    try:
        v = float(config.load_config().get("daily_budget_usd") or 0)
    except (TypeError, ValueError):
        return 0.0
    return v if 0 < v <= MAX_USD else 0.0


def spent_today(now: float | None = None) -> float:
    """What the sessions cost on the day of `now`. Only the sessions written since the day before are read: one
    that cost something today was written today (cheap in a fresh process too: a job's unit)."""
    now = now or time.time()
    day = store.day_of(now)
    total = 0.0
    try:
        with os.scandir(store.sessions_dir()) as it:
            for e in it:
                sid = e.name[:-5]
                if not e.name.endswith(".json") or not store.is_valid_id(sid):
                    continue
                try:
                    if e.stat().st_mtime < now - 90000:
                        continue
                except OSError:                         # deleted during the scan: the others still count
                    continue
                days = (store.read_cached(sid) or {}).get("days")
                d = days.get(day) if isinstance(days, dict) else None
                if isinstance(d, dict):
                    try:
                        c = float(d.get("cost") or 0)
                    except (TypeError, ValueError, OverflowError):    # OverflowError: an integer too big for a float
                        continue
                    if math.isfinite(c):                # a damaged "nan" / "inf" would break the total for the day
                        total += c
    except OSError:
        pass
    return round(total, 4)


def status() -> dict:
    lim = limit()
    spent = spent_today()
    return {"usd_per_day": lim, "spent_today": spent, "reached": bool(lim) and spent >= lim}


def reached() -> bool:
    """True while what starts by itself must wait for tomorrow."""
    lim = limit()
    return bool(lim) and spent_today() >= lim


_open: bool | None = None               # an alert REF is open in the feed (None: not looked at yet in this process)


def check() -> None:
    """Post the 80 % / reached events of the day (once each per amount) and close the alert once work runs again:
    a new day, a higher budget, no budget. Called at the end of every turn and when the setting changes."""
    global _open
    from . import feed
    lim = limit()
    spent = spent_today() if lim else 0.0
    day = store.day_of(time.time())
    if lim and spent >= lim:
        ev = feed.post("Daily budget reached",
                       f"{spent:.2f} $ spent today for a budget of {lim:.2f} $. Scheduled jobs and agents wait for "
                       "tomorrow; your own messages still run. Raise the budget in Settings -> Usage to let them "
                       "run today.", "warning", "system", URL, dedupe=f"budget:{day}:{lim:g}:100", ref=REF,
                       actions=[{"id": "open", "label": "Open", "style": "link"}])
        _open = True if ev else _open
        return
    if _open is not False:
        feed.resolve(REF, "Runs again")
        _open = False
    if lim and spent >= lim * WARN_AT:
        feed.post(f"{round(spent / lim * 100)} % of today's budget used",
                  f"{spent:.2f} $ spent today for a budget of {lim:.2f} $ (Settings -> Usage). Once it is reached, "
                  "scheduled jobs and agents wait for tomorrow.", "info", "system", URL,
                  dedupe=f"budget:{day}:{lim:g}:80")


def check_quietly() -> None:
    try:
        check()
    except Exception:  # noqa: BLE001 - an alert never breaks a turn end or a settings change
        log.exception("daily budget check failed")
