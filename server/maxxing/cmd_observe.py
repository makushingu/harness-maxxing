"""`maxxing usage`, `maxxing logs`, `maxxing metrics`: what the server spends and says, from a terminal.

  maxxing usage export [--group days|projects|topics|agents|sessions] [--format csv|json] [-o FILE]
                                the tokens and cost of Settings -> Usage as a file (every session), stdout by default
  maxxing logs [--since 15m|1h|6h|24h|7d|30d] [--level info|warning|error] [--grep TEXT]
               [--unit NAME | --session ID-OR-TITLE] [-n LINES] [--json]
                                search the journal: the server by default, another unit, or one session (its turn
                                unit + what the server says about it)
  maxxing metrics [status]      is GET /metrics on, and where
  maxxing metrics on | off      switch it (on: prints the bearer token the first time, the only time it is shown)
  maxxing metrics token         replace the token and print the new one
"""
from __future__ import annotations

import json
import sys

from . import cli


def _usage_configure(p) -> None:
    sub = p.add_subparsers(dest="usage_cmd", required=True)
    e = sub.add_parser("export", help="tokens and cost as CSV or JSON (every session)")
    e.add_argument("--group", default="days", choices=["days", "projects", "topics", "agents", "sessions"])
    e.add_argument("--format", default="csv", choices=["csv", "json"])
    e.add_argument("-o", "--output", help="write to this file instead of the terminal")


def _usage(a) -> int:
    from . import stats
    if a.format == "csv":
        text = stats.export_csv(a.group)
    else:
        cols, rows = stats.export_rows(a.group)
        text = json.dumps({"group": a.group, "columns": cols, "rows": rows}, ensure_ascii=False, indent=1) + "\n"
    if a.output:
        with open(a.output, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"{a.output}: {max(0, text.count(chr(10)) - 1) if a.format == 'csv' else len(rows)} row(s)")
    else:
        sys.stdout.write(text)
    return 0


def _logs_configure(p) -> None:
    from . import logsearch
    p.add_argument("--since", default="", choices=["", *logsearch.SINCE], help="how far back (default: the last lines)")
    p.add_argument("--level", default="", choices=["", "info", "warning", "error"], help="this level and above")
    p.add_argument("--grep", default="", metavar="TEXT", help="only the lines containing this text (any case)")
    p.add_argument("--unit", default="", help="another unit: caddy, cron, maxxing-cron-<id>... (default: the server)")
    p.add_argument("--session", default="", metavar="ID-OR-TITLE", help="the journal of one session")
    p.add_argument("-n", "--lines", type=int, default=200, help="lines shown, the newest (default 200)")
    p.add_argument("--json", action="store_true", help="one JSON object: {lines, rows, matched, scanned, truncated}")


def _logs(a) -> int:
    import re

    from . import health, logsearch
    units, mention = [a.unit or health.SELF_UNIT], None
    if a.unit and a.unit not in health.service_names() and not re.match(r"^maxxing-[a-z0-9-]{1,64}\Z", a.unit):
        print(f"logs of {a.unit} are not available here (a service of Settings -> System, or a maxxing-* unit)", file=sys.stderr)
        return 2
    if a.session:
        from .sessions import service, spawn
        try:
            sid = service.find_session(a.session)["id"]
        except service.SessionError as e:
            print(e.message, file=sys.stderr)
            return 2
        units, mention = [health.SELF_UNIT, spawn.unit_name(sid)], {health.SELF_UNIT: sid[:8]}
    r = logsearch.search(units, lines=max(1, min(a.lines, 5000)), since=a.since, level=a.level, q=a.grep, mention=mention)
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
        return 0
    for line in r["lines"]:
        print(line)
    if r["matched"] > len(r["lines"]) or r["truncated"]:
        print(f"-- {len(r['lines'])} of {r['matched']} matching line(s)"
              + (f", only the newest {r['scanned']} journal lines were read: narrow --since" if r["truncated"] else ""), file=sys.stderr)
    return 0


def _metrics_configure(p) -> None:
    p.add_argument("action", nargs="?", default="status", choices=["status", "on", "off", "token"])


def _metrics(a) -> int:
    from . import metrics
    token = None
    if a.action in ("on", "off"):
        token = metrics.set_enabled(a.action == "on")
    elif a.action == "token":
        token = metrics.new_token()
    st = metrics.status()
    print(f"metrics: {'on' if st['enabled'] else 'off'}   {st['url'] if st['url'] != '/metrics' else '<address of this Harness>/metrics'}")
    if token:
        print(f"token (shown once, keep it in your monitoring's configuration):\n  {token}")
        print("Prometheus:  authorization: { credentials: <token> }      curl:  -H 'Authorization: Bearer <token>'")
    elif st["enabled"] and a.action == "on":
        print("the token did not change (`maxxing metrics token` makes a new one)")
    return 0


cli.register("usage", "tokens and cost: export (CSV / JSON by day, project, topic, agent, session)", _usage_configure, _usage)
cli.register("logs", "search the journal: --since, --level, --grep, --session", _logs_configure, _logs)
cli.register("metrics", "GET /metrics in the Prometheus format: status, on, off, token", _metrics_configure, _metrics)
