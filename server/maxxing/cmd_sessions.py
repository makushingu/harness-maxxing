"""`maxxing sessions …` sub-commands.

  maxxing sessions compact-logs [--dry-run]   clip the tool outputs of existing session logs and slim
                                              their system lines (what the runner does at write time)
  maxxing sessions token-report [--days N] [--json]
                                              where the tokens go (Claude Code transcripts) + compaction simulation
  maxxing sessions send TO TEXT... [--file P] [--report-to S] [--json]
                                              write to another session as if typed in it (TO = its id or title);
                                              from a turn, the message says which session sent it
  maxxing sessions list [--json]              the sessions that are not archived (id, state, topic, title)
  maxxing sessions list --topic P/T [--days N] [--json]
                                              a topic's recent sessions for Jarvis: about (title, last answer), who
                                              started it, reusable / why_not (running, owner_active, context_full)
  maxxing sessions new TOPIC [TEXT...] [--title T] [--model M] [--effort E] [--file P] [--report-to S] [--fresh REASON] [--json]
                                              start a session in a topic (TOPIC = <project>/<topic> or its path) with
                                              a first message; from a turn, the message says which session sent it
  --report-to me|<session>                    its answers come back to that session when its turns end (the
                                              work board of jarvis.py); a turn of Jarvis's conversation always does
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
    s.add_argument("--report-to", default="", help="the session its next answers are reported to (`me` = the session "
                                                   "of this turn); from Jarvis's conversation: always Jarvis")
    s.add_argument("--json", action="store_true")
    n = sub.add_parser("new", help="start a session in a topic, with a first message (from a turn: says who sent it)")
    n.add_argument("topic", help="<project>/<topic>, or its path projects/<project>/topics/<topic>")
    n.add_argument("text", nargs="*", help="the first message (none: an empty session)")
    n.add_argument("--title", default="", help="its title (default: made from the first message)")
    n.add_argument("--model", default="", help="its model (default: the server's)")
    n.add_argument("--effort", default="", help="low, medium, high, xhigh, max (default: Claude Code's)")
    n.add_argument("--file", action="append", default=[], help="attach a file (absolute path), repeatable")
    n.add_argument("--report-to", default="", help="the session its answers are reported to (`me` = the session of "
                                                   "this turn); from Jarvis's conversation: always Jarvis")
    n.add_argument("--fresh", default="", metavar="REASON",
                   help="from Jarvis's conversation: start a new session even though the topic has reusable ones, "
                        "with why (another subject): shown on its work board")
    n.add_argument("--json", action="store_true")
    ls = sub.add_parser("list", help="the sessions that are not archived")
    ls.add_argument("--topic", default="", help="<project>/<topic>: its recent sessions, with what they are about and "
                                                "whether new work may continue one (reusable, why_not)")
    ls.add_argument("--days", type=int, default=0, help="with --topic: active in the last N days (default 30)")
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
    try:
        files = [str(Path(f).expanduser().resolve()) for f in a.file]
    except (OSError, ValueError, RuntimeError) as e:    # a NUL byte, an unknown ~user
        print(f"--file: {e}", file=sys.stderr)
        return 2
    try:
        report = _reporting(meta, a.report_to)
        r = service.relay_message(a.to, " ".join(a.text).strip(), files, sender=sender, hops=turn["depth"] + 1,
                                  short=report[0])
        _register(meta, report, r["session"] or {}, " ".join(a.text).strip(), turn["depth"] + 1)
    except service.SessionError as e:
        print(e.message, file=sys.stderr)
        return 1
    s = r["session"] or {}
    if a.json:
        print(json.dumps({"session": s.get("id"), "title": s.get("title"), "queued": r["queued"]}))
    else:
        print(f"sent to {s.get('id', '')[:8]} {s.get('title', '')}" + (" (queued: it is busy)" if r["queued"] else ""))
    return 0


def _reporting(meta: dict | None, report_to: str) -> tuple[bool, str]:
    """-> (put the work on the board, the session its answers go to: "" = Jarvis's current conversation).
    A turn of Jarvis's conversation always reports to Jarvis; `--report-to me|<session>` from any turn or shell."""
    from . import jarvis
    from .sessions import service
    jarvis_turn = bool(meta) and meta.get("path") == jarvis.PATH and jarvis.feature_on()
    want = (report_to or "").strip()
    if jarvis_turn and want in ("", "me", "jarvis"):
        return True, ""
    if not want:
        return False, ""
    if want == "jarvis":
        return True, ""
    if want == "me":
        if not meta:
            raise service.SessionError(400, "no_session", "--report-to me: only from a session's turn")
        return True, str(meta.get("id") or "")
    return True, service.find_session(want)["id"]


def _register(meta: dict | None, report: tuple[bool, str], s: dict, text: str, hops: int, fresh: str = "") -> None:
    if not report[0] or not s.get("id"):
        return
    from . import jarvis
    jarvis.register(s["id"], s.get("path") or "", s.get("title") or "", text, hops=hops, to=report[1], fresh=fresh)


def _topic(raw: str) -> str:
    """<project>/<topic> -> projects/<project>/topics/<topic>; a full path is kept as it is."""
    p = (raw or "").strip().strip("/")
    parts = p.split("/")
    return f"projects/{parts[0]}/topics/{parts[1]}" if len(parts) == 2 and parts[0] != "projects" else p


def _new(a) -> int:
    import json
    import sys
    from pathlib import Path
    from . import agent_guard, agents
    from .sessions import service, titles
    path = _topic(a.topic)
    if agents.is_agent_path(path):
        print("This is an agent: use `maxxing agents run <agent> \"...\"`.", file=sys.stderr)
        return 2
    meta = agent_guard.turn_meta()
    turn = agent_guard.agent_turn()
    text = " ".join(a.text).strip()
    try:
        files = [str(Path(f).expanduser().resolve()) for f in a.file]
    except (OSError, ValueError, RuntimeError) as e:    # a NUL byte, an unknown ~user
        print(f"--file: {e}", file=sys.stderr)
        return 2
    reuse = _reusable_first(meta, path, a.fresh, f"{a.title} {text}")
    if reuse:
        print(reuse, file=sys.stderr)
        return 3
    try:
        # created empty, then the first message goes in like a send: from a turn it says who sent it, and the
        # sends in a row stay capped (MAX_HOPS) - a session that starts sessions never loops forever
        hops = turn["depth"] + 1
        service.check_hops(hops)                         # refused before anything is created
        service._check_attachments(files)               # a missing --file too
        report = _reporting(meta, a.report_to)
        from . import jarvis
        root = bool(meta) and meta.get("path") == jarvis.PATH and jarvis.feature_on() and jarvis.settings()["root"]
        s = service.create_session(path, title=a.title or (titles.provisional(text) if text else None),
                                   model=a.model or None, effort=a.effort or None,
                                   source="session" if meta else "cli", auto_title=not a.title and bool(text),
                                   permission_mode="bypass" if root else "",
                                   push=not meta or meta.get("push") is not False)   # a muted session's start stays muted
        _register(meta, report, s, text, hops, a.fresh.strip())
        if report[0] and not report[1]:                # started for Jarvis's work board: archivable once done
            from .sessions import store
            store.update(s["id"], jarvis_made=True)
        if text or files:
            sender = {"id": meta.get("id") or "", "title": meta.get("title") or "",
                      "path": meta.get("path") or ""} if meta else None
            s = service.relay_message(s["id"], text, files, sender=sender, hops=hops, short=report[0])["session"] or s
    except service.SessionError as e:
        print(e.message, file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps({"session": s.get("id"), "title": s.get("title"), "path": s.get("path")}))
    else:
        print(f"started {s.get('id', '')[:8]} {s.get('title', '')} in {s.get('path', '')}")
    return 0


def _words(text: str) -> set[str]:
    """The words that tell a subject apart: accents off, lower case, 3 letters or more, plus the short acronyms
    written in capitals ("YA", "GW": the titles the owner gives)."""
    import re
    import unicodedata
    flat = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return {w.lower() for w in re.findall(r"[A-Za-z0-9]+", flat) if len(w) >= 3 or (len(w) == 2 and w.isupper())}


def _closest(rows: list[dict], subject: str) -> list[dict]:
    """The sessions most likely on the subject first (words shared with its title, then its last answer), the most
    recent among equals: Jarvis reads 5 of them, short titles ("YA", "GW") included."""
    want = _words(subject)
    def score(r: dict) -> tuple[int, int, float]:
        return (len(want & _words(r["title"])), len(want & _words(r["last_answer"])), r.get("updated") or 0)
    return sorted(rows, key=score, reverse=True) if want else rows


def _reusable_first(meta: dict | None, path: str, fresh: str, subject: str = "") -> str:
    """From Jarvis's conversation (setting `reuse` on), a new session is refused while the topic has reusable ones:
    the refusal lists them, closest to the subject first, so the work goes to one on the same subject (`sessions
    send`) or, on purpose and saying why, to a new one (`--fresh "<reason>"`, shown on its work board). Its rules
    said so, but it never looked: each piece of work started from zero."""
    if fresh.strip() or not meta:
        return ""
    from . import jarvis
    if meta.get("path") != jarvis.PATH or not jarvis.feature_on() or not jarvis.settings()["reuse"]:
        return ""
    rows = _closest([r for r in jarvis.topic_sessions(path) if r["reusable"]], subject)
    if not rows:
        return ""
    lines = [f"  {r['id'][:8]}  {r['title']}" + (f" - {r['last_answer'][:120]}" if r["last_answer"] else "")
             for r in rows[:5]]
    return ("Not started: this topic has recent sessions that can take the work (its context is already there), "
            "closest to the subject first:\n" + "\n".join(lines) + "\nSame subject or a follow-up: `maxxing "
            "sessions send <id> \"<brief>\"`. Another subject: the same command again with `--fresh \"<why none of "
            "them fits>\"` (shown to the owner on your work board).")


def _list(a) -> int:
    import json
    from .sessions import service
    if a.topic:
        from . import jarvis
        rows = jarvis.topic_sessions(_topic(a.topic), a.days or jarvis.REUSE_DAYS)
        if a.json:
            print(json.dumps(rows, indent=2))
        else:
            for s in rows:
                mark = "reusable" if s["reusable"] else s["why_not"]
                print(f"{s['id'][:8]}  {mark:<12} {s['title']}" + ("  (archived)" if s["archived"] else ""))
        return 0
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
    if a.sess_cmd == "new":
        return _new(a)
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


cli.register("sessions", "start a session (new), write to one (send), list them, logs maintenance (compact-logs), token report", _configure, _handler)
