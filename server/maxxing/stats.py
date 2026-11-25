"""Token and cost statistics over the sessions (Settings -> Usage). See docs/dev/API.md#stats.

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
_cache: dict = {"at": 0.0, "data": None, "inflight": None}
CACHE_S = 20.0
FORCE_MIN_S = 3.0          # a forced refresh younger than this returns the cache
COMPUTE_WAIT_S = 120.0     # a call sharing a running computation waits at most this long


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
    except (TypeError, ValueError, OverflowError):      # OverflowError: an integer too big for a float
        return 0.0
    return f if math.isfinite(f) else 0.0


def _text(v) -> str:
    """A string of a meta that JSON can carry: a lone surrogate (hand edit) would break the encoding of the answer."""
    return v.encode("utf-8", "replace").decode() if isinstance(v, str) else ""


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


def _finite(v) -> bool:
    try:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    except OverflowError:                               # an integer too big for a float
        return False


def _when(v):
    """A date of a meta (Unix seconds or ISO text); anything else (NaN, a list...) would break the JSON answer."""
    return _text(v) if isinstance(v, str) else v if _finite(v) else None


def _project_of(path: str) -> str:
    parts = (path or "").split("/")
    return parts[1] if len(parts) >= 2 and parts[0] == "projects" else ""


def _where_label(path: str) -> dict:
    """{label, agent} of a "topics" row: "acme / blog", or "acme / blog / Writer" + agent "Writer" for an agent folder."""
    from . import agents
    p = agents.parse(path)
    if p:
        try:
            name = (agents.load(path)["name"] if agents.exists(path) else "") or p[2]
        except Exception:  # noqa: BLE001 - a broken agent.json never breaks the stats
            name = p[2]
        return {"label": f"{p[0]} / {p[1]} / {name}", "agent": name}
    rel = (path or "").removeprefix("projects/").replace("/topics/", " / ")
    return {"label": rel, "agent": None}


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
        latency = m.get("latency")
        for pair in latency if isinstance(latency, list) else []:
            if isinstance(pair, list) and pair and _finite(pair[0]):
                starts.append(float(pair[0]))
                if len(pair) > 1 and _finite(pair[1]):
                    firsts.append(float(pair[1]))
        path = _text(m.get("path"))
        _add(totals, tk, cost, turns)
        _add(projects.setdefault(_project_of(path), {"name": _project_of(path)}), tk, cost, turns)
        _add(topics.setdefault(path, {"path": path}), tk, cost, turns)
        for day, d in (m.get("days") if isinstance(m.get("days"), dict) else {}).items():
            if isinstance(d, dict):
                day = _text(day)
                cur = days.setdefault(day, {"date": day, "tokens": 0, "cost_usd": 0.0})
                cur["tokens"] += _int(d.get("tokens"))
                cur["cost_usd"] = round(cur["cost_usd"] + _float(d.get("cost")), 6)
        title = _text(m.get("title"))
        sessions.append({"id": sid, "title": title or "Untitled", "path": path,
                         "archived": bool(m.get("archived")), "updated": _when(m.get("updated")) or _when(m.get("created")),
                         **tk, "total": sum(tk.values()), "cost_usd": round(cost, 6), "turns": turns})
    for row in topics.values():
        row.update(_where_label(row["path"]))
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


def invalidate() -> None:
    with _lock:
        _cache["at"], _cache["data"] = 0.0, None


def tokens(force: bool = False) -> dict:
    """The usage payload, cached CACHE_S seconds. `force` (the Refresh button) recomputes unless the cache is
    under FORCE_MIN_S old. The computation runs outside `_lock`: readers of a cached payload never wait for it,
    and calls that arrive while it runs share its result instead of starting another one."""
    with _lock:
        age = time.time() - _cache["at"]
        if _cache["data"] is not None and age < (FORCE_MIN_S if force else CACHE_S):
            return _cache["data"]
        inflight = _cache.get("inflight")
        mine = inflight is None
        if mine:
            inflight = _cache["inflight"] = threading.Event()
        elif _cache["data"] is not None and not force:
            return _cache["data"]                      # stale, a recompute is already on its way
    if not mine:
        inflight.wait(COMPUTE_WAIT_S)
        with _lock:
            if _cache["data"] is not None:
                return _cache["data"]
    try:
        data = compute()
        with _lock:
            _cache["data"], _cache["at"] = data, time.time()
    finally:
        if mine:
            with _lock:
                _cache["inflight"] = None
            inflight.set()
    return data
