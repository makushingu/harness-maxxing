"""Token and cost statistics over the sessions (Settings -> Stats). See docs/dev/API.md#stats.

Every turn adds its usage to the session meta (`tokens`, `days`: sessions/store.add_usage). Sessions
created before those counters existed are backfilled once from their log (the raw Claude `result`
lines), then kept current by the runner. A running session is never backfilled (its last result
would be counted twice): it is counted from its log without saving, until it is idle.
"""
from __future__ import annotations

import json
import math
import threading
import time

from .sessions import store

_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}
CACHE_S = 20.0


def _scan_log(sid: str) -> dict:
    tk = store.empty_tokens()
    try:
        with open(store.log_path(sid), "rb") as f:
            for raw in f:
                if b'"result"' not in raw or b'"usage"' not in raw:
                    continue
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(ev, dict) or ev.get("type") != "result" or not isinstance(ev.get("usage"), dict):
                    continue
                for k, src in store.TOKEN_KEYS:
                    tk[k] += _int(ev["usage"].get(src))
    except OSError:
        pass
    return tk



def _int(v) -> int:
    """A counter from a meta or a log; anything that is not a number (hand edit, other tool) counts as 0."""
    try:
        return int(v or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _float(v) -> float:
    try:
        f = float(v or 0)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def _tokens(sid: str, m: dict) -> dict:
    if isinstance(m.get("tokens"), dict):
        return {k: _int(m["tokens"].get(k)) for k, _ in store.TOKEN_KEYS}
    turns = _int(m.get("turns"))
    tk = _scan_log(sid)
    if m.get("state") != "running":
        try:
            with store.edit(sid) as cur:
                # A turn that ran during the scan may be missing from `tk`: keep it unsaved, rescan next time.
                if (not isinstance(cur.get("tokens"), dict) and cur.get("state") != "running"
                        and _int(cur.get("turns")) == turns):
                    cur["tokens"] = tk
        except (KeyError, OSError):
            pass
    return tk


def _project_of(path: str) -> str:
    parts = (path or "").split("/")
    return parts[1] if len(parts) >= 2 and parts[0] == "projects" else ""


def _add(acc: dict, tk: dict, cost: float, turns: int) -> None:
    for k in tk:
        acc[k] = acc.get(k, 0) + tk[k]
    acc["total"] = acc.get("total", 0) + sum(tk.values())
    acc["cost_usd"] = round(acc.get("cost_usd", 0.0) + cost, 6)
    acc["turns"] = acc.get("turns", 0) + turns
    acc["sessions"] = acc.get("sessions", 0) + 1


def _median(values: list[float]) -> float | None:
    v = sorted(values)
    if not v:
        return None
    mid = len(v) // 2
    return round(v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2, 3)


def compute() -> dict:
    totals: dict = {}
    projects: dict[str, dict] = {}
    topics: dict[str, dict] = {}
    days: dict[str, dict] = {}
    sessions = []
    starts: list[float] = []
    firsts: list[float] = []
    for sid in store.list_ids():
        m = store.read_cached(sid)          # shared, never mutated here: unchanged metas are not parsed again
        if m is None:
            continue
        tk = _tokens(sid, m)
        cost = _float(m.get("cost_usd"))
        turns = _int(m.get("turns"))
        for pair in m.get("latency") or []:
            if isinstance(pair, list) and pair and isinstance(pair[0], (int, float)):
                starts.append(float(pair[0]))
                if len(pair) > 1 and isinstance(pair[1], (int, float)):
                    firsts.append(float(pair[1]))
        path = m.get("path") or ""
        _add(totals, tk, cost, turns)
        _add(projects.setdefault(_project_of(path), {"name": _project_of(path)}), tk, cost, turns)
        _add(topics.setdefault(path, {"path": path}), tk, cost, turns)
        for day, d in (m.get("days") or {}).items():
            if isinstance(d, dict):
                cur = days.setdefault(day, {"date": day, "tokens": 0, "cost_usd": 0.0})
                cur["tokens"] += _int(d.get("tokens"))
                cur["cost_usd"] = round(cur["cost_usd"] + _float(d.get("cost")), 6)
        sessions.append({"id": sid, "title": m.get("title") or "Untitled", "path": path,
                         "archived": bool(m.get("archived")), "updated": m.get("updated") or m.get("created"),
                         **tk, "total": sum(tk.values()), "cost_usd": round(cost, 6), "turns": turns})
    by_total = lambda x: (x.get("total", 0), x.get("cost_usd", 0))  # noqa: E731
    sessions.sort(key=by_total, reverse=True)
    return {
        "totals": totals or {**store.empty_tokens(), "total": 0, "cost_usd": 0.0, "turns": 0, "sessions": 0},
        "projects": sorted(projects.values(), key=by_total, reverse=True),
        "topics": sorted(topics.values(), key=by_total, reverse=True),
        "sessions": sessions[:100],
        "days": [days[k] for k in sorted(days)][-store.DAYS_KEPT:],
        # recent turns of every session: seconds until Claude Code's first event / its first answer
        "latency": {"start_s": _median(starts), "first_answer_s": _median(firsts), "turns": len(starts)},
        "at": time.time(),
    }


def tokens(force: bool = False) -> dict:
    with _lock:
        if force or _cache["data"] is None or time.time() - _cache["at"] > CACHE_S:
            _cache["data"], _cache["at"] = compute(), time.time()
        return _cache["data"]
