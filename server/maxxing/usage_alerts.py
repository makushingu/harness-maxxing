"""Usage alerts (Settings -> Usage -> Alerts): the Notifications feed says when the spend leaves its usual range,
without a budget to set first.

Looked at when a turn ends (api/stats._turn_end), three causes, each with its own setting:
- **an unusual day** (`alert_spend_factor`, 3 by default, 0 = off): what today cost so far is at least that many
  times a usual day - the median of the last BASE_DAYS days that had usage, at least BASE_MIN of them - for the
  whole server, and for each agent (an agent without a budget that starts to run in a loop);
- **an expensive turn** (`alert_turn_usd`, 0 = off): one turn cost at least this amount;
- **a turn whose tools failed** (`alert_tool_errors`, on by default): at least ERRORS_MIN tool calls of the turn
  failed, and at least half of them - Claude kept trying something that does not work.
One event per cause and per day (per session and turn for the last two): never a second one for the same thing.
Nothing is stopped: that is the budgets' job (budget.py, agents.py). Costs are the ones of the Usage page (the price
Claude Code reports: real money with an API key, the price of the same tokens on a subscription).
"""
from __future__ import annotations

import logging
import math
import statistics
import time

from . import config
from .sessions import store

log = logging.getLogger("maxxing.usage_alerts")

FACTOR_DEFAULT = 3.0
FACTOR_MIN, FACTOR_MAX = 1.5, 100.0
TURN_USD_MAX = 100000.0
BASE_DAYS = 14                          # days looked at for "a usual day"
BASE_MIN = 3                            # ...of which at least this many had usage (a new server has no usual day)
FLOOR_USD = 5.0                         # a day under this amount is never "unusual" (3 x a few cents)
AGENT_FLOOR_USD = 2.0
ERRORS_MIN = 8
ERRORS_SHARE = 0.5
BASE_CACHE_S = 1800.0
URL = "/settings/usage"
OPEN = [{"id": "open", "label": "Open", "style": "link"}]


def settings() -> dict:
    """{spend_factor, turn_usd, tool_errors}: what is on, with the values in use (a damaged value = its default)."""
    cfg = config.load_config()
    return {"spend_factor": _number(cfg.get("alert_spend_factor"), FACTOR_DEFAULT, FACTOR_MIN, FACTOR_MAX),
            "turn_usd": _number(cfg.get("alert_turn_usd"), 0.0, 0.01, TURN_USD_MAX),
            "tool_errors": cfg.get("alert_tool_errors", True) is not False}


def _number(raw, default: float, low: float, high: float) -> float:
    if raw is None:
        return default
    if isinstance(raw, bool):                       # a hand-edited true is not 1
        return default
    try:
        v = float(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(v):
        return default
    if v == 0:
        return 0.0                                  # off
    return v if low <= v <= high else default


# ---- what a usual day costs ------------------------------------------------------------------------------------
_base: tuple | None = None              # (day, monotonic time, {"": {day: cost}, <agent path>: {day: cost}})


def _costs(now: float) -> dict[str, dict[str, float]]:
    """Cost per day of the last BASE_DAYS + today: "" = every session, an agent's path = its sessions."""
    global _base
    day = store.day_of(now)
    hit = _base
    if hit and hit[0] == day and time.monotonic() - hit[1] < BASE_CACHE_S:
        return hit[2]
    from . import agents
    keep = {store.day_of(now - i * 86400) for i in range(BASE_DAYS + 2)}       # + 2: a day of 23 or 25 hours
    out: dict[str, dict[str, float]] = {"": {}}
    for sid in store.list_ids():
        m = store.read_cached(sid)
        days = (m or {}).get("days")
        if not isinstance(days, dict):
            continue
        path = m.get("path") if agents.is_agent_path(m.get("path")) else None
        for d, v in days.items():
            if d not in keep or not isinstance(v, dict):
                continue
            try:
                c = float(v.get("cost") or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(c) or c <= 0:
                continue
            out[""][d] = out[""].get(d, 0.0) + c
            if path:
                per = out.setdefault(path, {})
                per[d] = per.get(d, 0.0) + c
    _base = (day, time.monotonic(), out)
    return out


def usual(costs: dict[str, float], today: str) -> float | None:
    """The median cost of the days before `today` that had usage; None when there are too few to say."""
    past = [c for d, c in costs.items() if d != today and c > 0]
    return statistics.median(past) if len(past) >= BASE_MIN else None


def _today(path: str, now: float) -> float:
    """What the sessions of `path` ("" = all) cost today, read now (the base is kept half an hour)."""
    if not path:
        from . import budget
        return budget.spent_today()
    day = store.day_of(now)
    total = 0.0
    for sid in store.list_ids():
        m = store.read_cached(sid)
        if not m or m.get("path") != path:
            continue
        d = (m.get("days") or {}).get(day) if isinstance(m.get("days"), dict) else None
        try:
            c = float((d or {}).get("cost") or 0) if isinstance(d, dict) else 0.0
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(c):
            total += c
    return total


def _spike(path: str, factor: float, now: float) -> None:
    from . import feed
    day = store.day_of(now)
    base = usual(_costs(now).get(path, {}), day)
    floor = AGENT_FLOOR_USD if path else FLOOR_USD
    if base is None:
        return
    spent = _today(path, now)
    if spent < floor or spent < base * factor:
        return
    times = spent / base if base else 0
    if path:
        from . import agents
        name = agents._display(path)
        if agents.silent(path):
            return
        feed.post(f"{name} costs more than usual today",
                  f"{spent:.2f} $ so far today, {times:.1f} times its usual day ({base:.2f} $, median of the last "
                  f"{BASE_DAYS} days). Nothing is stopped: give it a daily budget in its settings if that is not "
                  "expected.", "warning", "system", agents._page(path), dedupe=f"usage:spike:{day}:{path}",
                  agent=path, actions=OPEN)
    else:
        feed.post("Today costs more than usual",
                  f"{spent:.2f} $ so far today, {times:.1f} times a usual day ({base:.2f} $, median of the last "
                  f"{BASE_DAYS} days). Nothing is stopped: Settings -> Usage shows where it goes and sets a daily "
                  "budget.", "warning", "system", URL, dedupe=f"usage:spike:{day}", actions=OPEN)


# ---- one turn ------------------------------------------------------------------------------------------------
def _session_url(session: dict) -> str:
    from urllib.parse import quote
    return f"/sessions?path={quote(session.get('path') or '', safe='')}&session={session.get('id') or ''}"


def _title(session: dict) -> str:
    return (session.get("title") or "A session")[:80]


def _turn(session: dict, result: dict | None, s: dict) -> None:
    from . import feed
    sid, turn = session.get("id") or "", int(session.get("turns") or 0)
    cost = float((result or {}).get("cost_usd") or 0)
    if s["turn_usd"] and math.isfinite(cost) and cost >= s["turn_usd"]:
        feed.post("An expensive turn",
                  f"“{_title(session)}”: its last turn cost {cost:.2f} $ (alert from {s['turn_usd']:.2f} $, Settings "
                  "-> Usage). The ⚙ under the answer -> Turn details shows what it did.", "warning", "system",
                  _session_url(session), dedupe=f"usage:turn:{sid}:{turn}", actions=OPEN)
    if s["tool_errors"]:
        from .sessions import service
        steps = service.ended_turn_steps(sid)
        total = int(steps.get("tools_total") or 0)
        failed = sum(1 for t in steps.get("tools") or [] if t.get("error"))
        shown = len(steps.get("tools") or [])
        if failed >= ERRORS_MIN and shown and failed >= shown * ERRORS_SHARE:
            feed.post("A turn kept failing",
                      f"“{_title(session)}”: {failed} of its last {shown} tool calls failed ({total} in the turn). "
                      "The ⚙ under the answer -> Turn details lists them.", "warning", "system",
                      _session_url(session), dedupe=f"usage:errors:{sid}:{turn}", actions=OPEN)


def enabled() -> bool:
    s = settings()
    return bool(s["spend_factor"] or s["turn_usd"] or s["tool_errors"])


def check(session: dict, result: dict | None, now: float | None = None) -> None:
    s = settings()
    now = time.time() if now is None else now
    if s["turn_usd"] or s["tool_errors"]:
        try:
            _turn(session, result, s)
        except Exception:  # noqa: BLE001 - one cause never hides the others
            log.exception("usage alerts: turn of %s", session.get("id"))
    if s["spend_factor"]:
        from . import agents
        _spike("", s["spend_factor"], now)
        path = session.get("path")
        if agents.is_agent_path(path):
            _spike(path, s["spend_factor"], now)


def check_quietly(session: dict, result: dict | None) -> None:
    try:
        check(session, result)
    except Exception:  # noqa: BLE001 - an alert never breaks a turn end
        log.exception("usage alerts failed")
