"""`maxxing sessions …` sub-commands.

  maxxing sessions compact-logs [--dry-run]   clip the tool outputs of existing session logs and slim
                                              their system lines (what the runner does at write time)
  maxxing sessions token-report [--days N] [--json]
                                              where the tokens go (Claude Code transcripts) + compaction simulation
"""
from __future__ import annotations

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="sess_cmd", required=True)
    c = sub.add_parser("compact-logs", help="rewrite session logs with clipped tool outputs and slim system lines")
    c.add_argument("--dry-run", action="store_true", help="only report what would be saved")
    t = sub.add_parser("token-report", help="where the tokens go: context per call, cache rewrites, tool outputs, "
                                            "compaction simulated at other thresholds")
    t.add_argument("--days", type=float, help="only the last N days")
    t.add_argument("--json", action="store_true")


def _mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


def _token_report(a) -> int:
    import json
    from pathlib import Path
    from .sessions import tokenreport
    r = tokenreport.report(Path.home() / ".claude" / "projects", a.days)
    print(json.dumps(r, indent=2) if a.json else tokenreport.render(r))
    return 0


def _handler(a) -> int:
    if a.sess_cmd == "token-report":
        return _token_report(a)
    from .sessions import service, store
    total_before = total_after = 0
    skipped = 0
    for sid in sorted(store.list_ids()):
        r = service.compact_log(sid, dry_run=a.dry_run)
        if r["status"] == "running":
            skipped += 1
            print(f"{sid}  skipped (running)")
            continue
        total_before += r["before"]
        total_after += r["after"]
        if r["status"] == "compacted":
            print(f"{sid}  {_mb(r['before'])} -> {_mb(r['after'])}")
    verb = "would save" if a.dry_run else "saved"
    print(f"{verb} {_mb(total_before - total_after)} ({_mb(total_before)} -> {_mb(total_after)})"
          + (f", {skipped} running session(s) skipped - run again later" if skipped else ""))
    return 0


cli.register("sessions", "session logs maintenance (compact-logs) and token report", _configure, _handler)
