"""What an agent's turn cost when Claude never reported it.

Claude Code reports a turn's cost in its final `result` line. A turn stopped before it (its timeout, a stop, a
crash) has none: the runner records 0, so the agent's daily budget (`day_cost`, `--max-budget-usd`) never saw
those tokens. Measured on this product's own agents: an hourly agent that waited for its background jobs
(`sleep 598`, polling loops) until its 55 min timeout spent ~125 $ of tokens in 34 such turns, all counted 0 $,
and its 100 $ budget never stopped it.

`charge_unbilled(sid)` reads the assistant messages of the ended turn in the raw log (sub-agents included, each
message once), prices their usage (`PRICES`, list prices per million tokens) and adds it to the session meta like a
`result` would (cost_usd, tokens, days): the budget, the agent page and Stats then count it. `estimated_usd` in
the meta keeps what was estimated. Done once per turn (the `mx_done` line is remembered). Claude Code still saves
the cost of a turn stopped by SIGTERM in its thread: the next `--resume` reports it in its total, so the estimate
is kept in `thread_cost.estimated` and taken off that next turn (store.turn_cost). STDLIB ONLY.
"""
from __future__ import annotations

import json
import logging
import time

log = logging.getLogger("maxxing.agent_cost")

# $ per million tokens: (input, output, cache read, cache write 5 min). First match on the model id wins; an
# unknown model gets the last row (Opus list price: rather too much than a budget that never stops).
PRICES: tuple[tuple[str, tuple[float, float, float, float]], ...] = (
    ("opus-5-5", (4.0, 20.0, 0.2, 5.0)),
    ("sonnet-5", (2.0, 10.0, 0.2, 2.5)),
    ("haiku-5", (0.1, 0.5, 0.01, 0.125)),
    ("fable", (10.0, 50.0, 1.0, 12.5)),
    ("mythos", (10.0, 50.0, 1.0, 12.5)),
    ("haiku", (1.0, 5.0, 0.1, 1.25)),
    ("sonnet", (3.0, 15.0, 0.3, 3.75)),
    ("", (5.0, 25.0, 0.5, 6.25)),
)
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def price(model: str) -> tuple[float, float, float, float]:
    m = (model or "").lower()
    return next(p for k, p in PRICES if k in m)


def cost_of(usage: dict, model: str) -> float:
    p = price(model)
    return sum(int(usage.get(k) or 0) * p[i] for i, k in enumerate(USAGE_KEYS)) / 1e6


def _injected(raw: str) -> bool:
    try:
        return json.loads(raw).get("injected") is True
    except (ValueError, RecursionError, AttributeError):
        return False


def _at(raw: str) -> float:
    try:
        v = json.loads(raw).get("at")
        return float(v) if isinstance(v, (int, float)) else 0.0
    except (ValueError, RecursionError, AttributeError):
        return 0.0


def last_turn(lines, at: float | None = None) -> tuple[dict | None, dict, float]:
    """The ended turn of a raw log (its lines after the last `mx_user`, or after the one sent at `at` - meta
    last_turn.at - when a message queued meanwhile already started) -> (its `mx_done` line, None unless the turn
    ended without a `result` - its timeout, a crash - and was not stopped by the owner; its usage summed over every
    assistant message; its estimated cost)."""
    msgs: dict[str, tuple[dict, str]] = {}
    done, result, n, mine = None, False, 0, False
    for raw in lines:
        if '"mx_user"' in raw[:40]:
            if '"injected"' in raw and _injected(raw):
                continue                                # added to the running turn (Add now): the same turn goes on
            if mine:
                break                                   # the next message's turn: the one at `at` is over
            msgs, done, result = {}, None, False
            mine = bool(at) and abs(_at(raw) - float(at)) < 1e-3
            continue
        if '"type": "result"' not in raw and '"type": "assistant"' not in raw and '"mx_done"' not in raw[:40]:
            continue
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "result":
            result = True
        elif t == "mx_done":
            done = ev
        elif t == "assistant":
            msg = ev.get("message") or {}
            u = msg.get("usage")
            if isinstance(u, dict):
                n += 1
                msgs[str(msg.get("id") or f"_{n}")] = (u, str(msg.get("model") or ""))   # one message, many lines
    if done is None or result or done.get("stopped"):
        return None, {}, 0.0                            # a stop or a steer by the owner: not a lost turn
    usage = {k: 0 for k in USAGE_KEYS}
    usd = 0.0
    for u, model in msgs.values():
        for k in USAGE_KEYS:
            usage[k] += int(u.get(k) or 0)
        usd += cost_of(u, model)
    return done, usage, round(usd, 6)


SAVED_CODES = (143,)    # Claude Code's own exit after a SIGTERM: it saved the turn's cost in its thread first


def saved_by_claude(done: dict) -> bool:
    """The lost turn's cost is in the thread's next reported total: Claude ended by itself on the runner's SIGTERM.
    Not after a SIGKILL (no answer within 5 s, out of memory) or a crash: nothing saved, nothing to take off."""
    return done.get("code") in SAVED_CODES


def charge_unbilled(sid: str, at: float | None = None) -> float:
    """Adds the estimated cost of the session's ended turn (the one sent at `at` when given) when Claude never
    reported it -> the $ added (0: nothing to add, already added, or the turn reported its cost)."""
    from .sessions import store
    try:
        with open(store.log_path(sid), errors="replace") as f:
            done, usage, usd = last_turn(f, at)
    except OSError:
        return 0.0
    if done is None or not any(usage.values()):
        return 0.0
    at = float(done.get("at") or 0)
    with store.edit(sid) as m:
        if float(m.get("estimated_at") or 0) == at:
            return 0.0                                  # this turn was already charged
        m["estimated_at"] = at
        m["estimated_usd"] = round(float(m.get("estimated_usd") or 0) + usd, 6)
        m["cost_usd"] = round(float(m.get("cost_usd") or 0) + usd, 6)
        store.add_usage(m, usage, usd, at or time.time())
        if saved_by_claude(done):                       # Claude keeps this turn in the thread's total: the next
            csid = str(m.get("csid") or sid)            # turn takes this estimate off (turn_cost)
            tc = {"csid": csid, "total": store.thread_prev_cost(m, csid)}
            tc["estimated"] = round(store.thread_estimated(m, csid) + usd, 6)
            m["thread_cost"] = tc
    log.info("session %s: turn ended without a reported cost, %.2f $ estimated from its log", sid, usd)
    return usd
