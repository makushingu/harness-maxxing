"""One-time repair of session costs counted before 2.0.0a32.

Claude's `result.total_cost_usd` is the running total of the whole Claude thread (every `--resume` reports it), but
the runner used to add it to the session on every turn, so `cost_usd` (and the daily costs) grew quadratically. This
recomputes them from the raw log - each turn's cost is the increase of its thread's total (store.turn_cost) - adds
that per-turn cost to the logged `result` lines (`mx_turn_cost`, shown per turn by normalize.py), and records the
thread's last total for the runner. Done once per session (`cost_v` in the meta); a running session is retried
every 2 minutes until it is idle. The log is rewritten like `compact-logs` (atomic, under the run lock): open streams get `reset`.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

from . import store

COST_V = 2
log = logging.getLogger("maxxing.costfix")


def _day(ev: dict) -> str | None:
    at = ev.get("mx_at") or ev.get("at")
    return time.strftime("%Y-%m-%d", time.localtime(float(at))) if isinstance(at, (int, float)) else None


def fix_session(sid: str) -> str:
    """-> "fixed" | "done" (already) | "running" | "missing"."""
    meta = store.read(sid)
    path = store.log_path(sid)
    if meta is None:
        return "missing"
    if int(meta.get("cost_v") or 0) >= COST_V:
        return "done"
    if not path.is_file():
        with store.edit(sid) as m:
            m["cost_v"] = COST_V
        return "fixed"
    if store.runner_alive(sid, meta):
        return "running"
    fd = store.hold_run_lock(sid, wait_s=0)
    if fd is None:
        return "running"
    tmp = path.with_name(f"{path.name}.cost.tmp")
    try:
        last: dict[str, float] = {}                   # Claude thread -> its last running total
        total, days, changed = 0.0, {}, False
        last_thread: tuple[str, float] | None = None
        with open(path, "rb") as src, open(tmp, "wb") as out:
            for raw in src:
                if b'"total_cost_usd"' in raw and b'"result"' in raw:
                    try:
                        ev = json.loads(raw)
                    except ValueError:
                        ev = None
                    if isinstance(ev, dict) and ev.get("type") == "result" and ev.get("total_cost_usd") is not None:
                        thread = str(ev.get("session_id") or "")
                        t = float(ev.get("total_cost_usd") or 0)
                        cost = store.turn_cost(t, last.get(thread, 0.0))
                        last[thread] = t
                        last_thread = (thread, t)
                        total += cost
                        day = _day(ev)
                        if day:
                            days[day] = days.get(day, 0.0) + cost
                        if ev.get("mx_turn_cost") != cost:
                            ev["mx_turn_cost"] = cost
                            raw = (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
                            changed = True
                out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        if changed:
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        with store.edit(sid) as m:
            m["cost_usd"] = round(total, 6)
            for day, d in (m.get("days") or {}).items():
                if isinstance(d, dict):
                    d["cost"] = round(days.get(day, 0.0), 6)
            if last_thread and last_thread[0] == (m.get("csid") or sid):
                m["thread_cost"] = {"csid": last_thread[0], "total": last_thread[1]}
            m["cost_v"] = COST_V
        return "fixed"
    finally:
        tmp.unlink(missing_ok=True)
        os.close(fd)


def fix_all() -> dict[str, int]:
    out: dict[str, int] = {}
    for sid in store.list_ids():
        try:
            st = fix_session(sid)
        except Exception:                             # a broken session never blocks the others
            log.exception("cost repair failed for %s", sid)
            st = "error"
        out[st] = out.get(st, 0) + 1
    return out


RETRY_S = 120.0
RETRY_FOR_S = 7 * 86400.0


def start_background() -> None:
    """At server start: repair what is left, in the background (big logs take a moment); sessions that were running
    are retried every RETRY_S until they are idle (for a week at most)."""
    def run() -> None:
        until = time.time() + RETRY_FOR_S
        while True:
            res = fix_all()
            if res.get("fixed"):
                log.info("session costs repaired: %s", res)
            if not res.get("running") or time.time() > until:
                return
            time.sleep(RETRY_S)
    threading.Thread(target=run, name="costfix", daemon=True).start()
