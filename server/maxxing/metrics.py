"""Metrics in the Prometheus text format: `GET /metrics` (off by default, `maxxing metrics on`, Settings -> System).

What Settings -> Usage, the health line and the Crons page already show, for a monitoring system the user already
runs (Prometheus, Grafana Agent, VictoriaMetrics, an OpenTelemetry collector's Prometheus receiver...). Read from the
caches those pages use (stats.tokens 20 s, health.collect): a scrape every 15 s costs no more than an open tab.

Off until config `metrics` is true, then only with `Authorization: Bearer <token>` (secret `metrics_token`, made when
it is switched on, shown once). No session title, no path of a session, no message: the labels are project names,
agent folders and job names (at most SERIES_MAX each, the biggest first).

The usage numbers are GAUGES, not counters: they are what the sessions kept on this server add up to, so deleting
or trashing a session lowers them. `harness_usage_today_*` restart from 0 every day (Harness time zone).
"""
from __future__ import annotations

import hmac
import math
import secrets as _secrets
import time

from . import __version__, config

SERIES_MAX = 200
TOKEN_SECRET = "metrics_token"
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def enabled() -> bool:
    return config.load_config().get("metrics") is True


def has_token() -> bool:
    return bool(config.get_secret(TOKEN_SECRET))


def new_token() -> str:
    """Make (or replace) the token and return it: the only time it is readable."""
    tok = "hmx_" + _secrets.token_urlsafe(32)
    config.set_secret(TOKEN_SECRET, tok)
    return tok


def set_enabled(on: bool) -> str | None:
    """Switch the endpoint; -> the new token when switching on created one (none existed)."""
    tok = new_token() if on and not has_token() else None
    config.update_config(metrics=bool(on))
    return tok


def authorized(header: str | None) -> bool:
    want = config.get_secret(TOKEN_SECRET)
    scheme, _, got = (header or "").partition(" ")
    return bool(want) and scheme.lower() == "bearer" and hmac.compare_digest(got.strip().encode(), want.encode())


def status() -> dict:
    base = (config.load_config().get("public_url") or "").rstrip("/")
    return {"enabled": enabled(), "has_token": has_token(), "url": (base or "") + "/metrics"}


# ---------------------------------------------------------------- the text format
def _label(v) -> str:
    return str(v).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _num(v) -> str | None:
    if isinstance(v, bool):
        return "1" if v else "0"
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(f):
        return None
    return str(int(f)) if f == int(f) and abs(f) < 1e15 else repr(round(f, 6))


class _Out:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.seen: set[str] = set()

    def add(self, name: str, help_: str, value, labels: dict | None = None) -> None:
        v = _num(value)
        if v is None:
            return
        if name not in self.seen:
            self.seen.add(name)
            self.lines += [f"# HELP {name} {help_}", f"# TYPE {name} gauge"]
        lab = "{" + ",".join(f'{k}="{_label(x)}"' for k, x in labels.items()) + "}" if labels else ""
        self.lines.append(f"{name}{lab} {v}")


def _usage(o: _Out) -> None:
    from . import budget, stats
    from .sessions import store
    d = stats.tokens()
    t = d["totals"]
    for kind in ("input", "output", "cache_read", "cache_write"):
        o.add("harness_usage_tokens", "Tokens of the sessions kept on this server, by kind.", t.get(kind), {"kind": kind})
    o.add("harness_usage_cost_usd", "Cost of the sessions kept on this server, in dollars at API prices.", t.get("cost_usd"))
    o.add("harness_usage_turns", "Turns of the sessions kept on this server.", t.get("turns"))
    o.add("harness_sessions", "Sessions kept on this server (archived included).", t.get("sessions"))
    running = 0
    for sid in store.list_ids():
        m = store.read_cached(sid)
        running += bool(m and m.get("state") == "running")
    o.add("harness_sessions_running", "Sessions with a turn running now.", running)
    today = store.day_of(time.time())
    day = next((x for x in reversed(d["days"]) if x.get("date") == today), None) or {}
    o.add("harness_usage_today_tokens", "Tokens of today (Harness time zone).", day.get("tokens", 0))
    for p in d["projects"][:SERIES_MAX]:
        lab = {"project": p.get("name") or ""}
        o.add("harness_project_tokens", "Tokens of a project's sessions.", p.get("total"), lab)
        o.add("harness_project_cost_usd", "Cost of a project's sessions, in dollars at API prices.", p.get("cost_usd"), lab)
        o.add("harness_project_turns", "Turns of a project's sessions.", p.get("turns"), lab)
    for a in d.get("agents", [])[:SERIES_MAX]:
        lab = {"agent": a.get("name") or "", "path": a.get("path") or ""}
        o.add("harness_agent_tokens", "Tokens of an agent's sessions.", a.get("total"), lab)
        o.add("harness_agent_cost_usd", "Cost of an agent's sessions, in dollars at API prices.", a.get("cost_usd"), lab)
        o.add("harness_agent_turns", "Turns of an agent's sessions.", a.get("turns"), lab)
    lat = d.get("latency") or {}
    o.add("harness_turn_start_seconds", "Median seconds until Claude Code's first event, recent turns.", lat.get("start_s"))
    o.add("harness_turn_first_answer_seconds", "Median seconds until the first answer, recent turns.", lat.get("first_answer_s"))
    b = budget.status()
    o.add("harness_usage_today_cost_usd", "Cost of today (Harness time zone), every session, job and agent.", b["spent_today"])
    o.add("harness_budget_usd_per_day", "The server's daily budget in dollars (0 = none).", b["usd_per_day"])
    o.add("harness_budget_reached", "1 while the daily budget is reached (scheduled work waits for tomorrow).", b["reached"])


def _plan(o: _Out) -> None:
    from . import claude_auth
    lim = claude_auth.limits() or {}                    # what the last turn printed: never a network call
    for key, window in (("five_hour", "5h"), ("seven_day", "7d")):
        w = lim.get(key)
        if isinstance(w, dict) and w.get("pct") is not None:
            o.add("harness_plan_used_ratio", "Share of the Claude plan's window used (0-1), as seen in the last turn.",
                  float(w["pct"]) / 100, {"window": window})


def _health(o: _Out) -> None:
    from . import health
    h = health.collect()
    o.add("harness_health_ok", "1 when the health check has no issue.", h.get("ok"))
    issues = h.get("issues") or []
    for level in ("warn", "error"):
        o.add("harness_health_issues", "Open health issues, by level.", sum(1 for i in issues if i.get("level") == level), {"level": level})
    o.add("harness_cpu_percent", "Processor use of the server, percent.", h.get("cpu_pct"))
    load = h.get("load") or []
    o.add("harness_load1", "Load average over 1 minute.", load[0] if load else None)
    mem, dsk = h.get("mem") or {}, h.get("disk") or {}
    o.add("harness_memory_total_bytes", "Memory of the server.", mem.get("total"))
    o.add("harness_memory_available_bytes", "Memory available.", mem.get("avail"))
    o.add("harness_disk_total_bytes", "Size of the disk holding the workspace.", dsk.get("total"))
    o.add("harness_disk_free_bytes", "Free space on the disk holding the workspace.", dsk.get("free"))
    o.add("harness_uptime_seconds", "Uptime of the server.", h.get("uptime_s"))
    o.add("harness_claude_signed_in", "1 when Claude Code is signed in.", h.get("claude_auth"))
    o.add("harness_backup_age_hours", "Hours since the last memory backup.", h.get("backup_age_h"))
    o.add("harness_failed_logins_1h", "Refused sign-ins in the last hour.", h.get("failed_logins_1h"))


def _crons(o: _Out) -> None:
    from . import crons
    jobs = crons.list_jobs()
    for state in (True, False):
        o.add("harness_cron_jobs", "Scheduled jobs, by state.", sum(1 for j in jobs if bool(j.get("enabled")) is state),
              {"state": "enabled" if state else "disabled"})
    for j in jobs[:SERIES_MAX]:
        r = j.get("last_run")
        if not r:
            continue
        lab = {"cron": j.get("id") or "", "name": j.get("name") or ""}
        o.add("harness_cron_last_run_success", "1 when the job's last run succeeded.", r.get("ok"), lab)
        o.add("harness_cron_last_run_timestamp_seconds", "When the job last ran (Unix seconds).", r.get("at"), lab)
        o.add("harness_cron_last_run_duration_seconds", "How long the job's last run took.", r.get("duration_s"), lab)


def render() -> str:
    """The whole page. A part that fails is left out (and counted): a broken jobs file never hides the usage."""
    import logging
    o = _Out()
    o.add("harness_build_info", "The Harness Maxxing version (always 1).", 1, {"version": __version__})
    failed = 0
    for part in (_usage, _plan, _health, _crons):
        try:
            part(o)
        except Exception:  # noqa: BLE001
            failed += 1
            logging.getLogger("maxxing.metrics").exception("metrics: %s failed", part.__name__)
    o.add("harness_metrics_parts_failed", "Parts of this page that could not be read (see the server log).", failed)
    return "\n".join(o.lines) + "\n"
