"""`maxxing sessions …` sub-commands.

  maxxing sessions compact-logs [--dry-run]   clip the tool outputs of existing session logs and slim
                                              their system lines (what the runner does at write time)
  maxxing sessions token-report [--days N] [--json]
                                              where the tokens go (Claude Code transcripts) + compaction simulation
  maxxing sessions send TO TEXT... [--file P] [--json]
                                              write to another session as if typed in it (TO = its id or title);
                                              from a turn, the message says which session sent it
  maxxing sessions list [--json]              the sessions that are not archived (id, state, topic, title)
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
    s = sub.add_parser("send", help="write to another session as if typed in it (from a turn: says who sent it)")
    s.add_argument("to", help="the session: its id (or its first 8 characters) or its title")
    s.add_argument("text", nargs="+", help="the message")
    s.add_argument("--file", action="append", default=[], help="attach a file (absolute path), repeatable")
    s.add_argument("--json", action="store_true")
    ls = sub.add_parser("list", help="the sessions that are not archived")
    ls.add_argument("--json", action="store_true")


def _mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


def _token_report(a) -> int:
    import json
    from pathlib import Path
    from .sessions import tokenreport
    r = tokenreport.report(Path.home() / ".claude" / "projects", a.days)
    print(json.dumps(r, indent=2) if a.json else tokenreport.render(r))
    return 0


def _send(a) -> int:
    import json
    import sys
    from pathlib import Path
    from . import agent_guard
    from .sessions import service
    meta = agent_guard.turn_meta()
    turn = agent_guard.agent_turn()
    sender = None
    if meta:
        sender = {"id": meta.get("id") or "", "title": meta.get("title") or "", "path": meta.get("path") or ""}
    files = [str(Path(f).expanduser().resolve()) for f in a.file]
    try:
        r = service.relay_message(a.to, " ".join(a.text).strip(), files, sender=sender, hops=turn["depth"] + 1)
    except service.SessionError as e:
        print(e.message, file=sys.stderr)
        return 1
    s = r["session"] or {}
    if a.json:
        print(json.dumps({"session": s.get("id"), "title": s.get("title"), "queued": r["queued"]}))
    else:
        print(f"sent to {s.get('id', '')[:8]} {s.get('title', '')}" + (" (queued: it is busy)" if r["queued"] else ""))
    return 0


def _list(a) -> int:
    import json
    from .sessions import service
    rows = [{k: s[k] for k in ("id", "title", "path", "state", "updated")} for s in service.list_sessions(archived=False)]
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for s in rows:
            print(f"{s['id'][:8]}  {s['state']:<8} {s['path']}  {s['title']}")
    return 0


def _handler(a) -> int:
    if a.sess_cmd == "token-report":
        return _token_report(a)
    if a.sess_cmd == "send":
        return _send(a)
    if a.sess_cmd == "list":
        return _list(a)
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


cli.register("sessions", "write to a session (send), list them, logs maintenance (compact-logs), token report", _configure, _handler)
