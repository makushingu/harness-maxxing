"""`maxxing jarvis …`: Jarvis (Settings -> Features -> Jarvis), its conversation and its work board.

  maxxing jarvis status [--json]            on/off, its conversation, settings, open work
  maxxing jarvis say TEXT...                a message into its conversation (made when there is none)
  maxxing jarvis new                        its next message starts a new conversation
  maxxing jarvis work [--all] [--json]      the work board (open entries; --all: closed ones too)
  maxxing jarvis work close ID              an entry is done (its next turn ends are no longer reported)
  maxxing jarvis digest [--since H] [--mark]
                                            what changed since the last night pass (or H hours); --mark: the night
                                            pass is done (the next digest starts here)
  maxxing jarvis brief | dream              the morning brief / the night pass, now
  maxxing jarvis set KEY VALUE              a setting: model, dream_model, root, ask_first, internals, daily, brief, dream,
                                            reuse, archive_done
"""
from __future__ import annotations

import json
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="jarvis_cmd", required=True)
    st = sub.add_parser("status", help="on/off, its conversation, settings, open work")
    st.add_argument("--json", action="store_true")
    s = sub.add_parser("say", help="a message into its conversation")
    s.add_argument("text", nargs="+")
    sub.add_parser("new", help="its next message starts a new conversation")
    w = sub.add_parser("work", help="the work board")
    w.add_argument("action", nargs="?", choices=["close"], help="close: an entry is done")
    w.add_argument("ref", nargs="?", help="the entry: its number (#12) or its session id")
    w.add_argument("--all", action="store_true", help="closed entries too")
    w.add_argument("--json", action="store_true")
    d = sub.add_parser("digest", help="what changed since the last night pass")
    d.add_argument("--since", type=float, help="the last H hours instead")
    d.add_argument("--mark", action="store_true", help="the night pass is done: the next digest starts now")
    sub.add_parser("brief", help="the morning brief, now")
    sub.add_parser("dream", help="the night pass, now (a separate session)")
    se = sub.add_parser("set", help="a setting")
    se.add_argument("key", choices=["model", "dream_model", "root", "ask_first", "internals", "daily", "brief", "dream", "compact_tokens", "telegram", "report_effort", "reuse", "archive_done"])
    se.add_argument("value")


def _ago(t) -> str:
    import time
    if not isinstance(t, (int, float)):
        return ""
    m = int((time.time() - t) / 60)
    return f"{m} min ago" if m < 90 else f"{m // 60} h ago" if m < 48 * 60 else f"{m // 1440} d ago"


def _row(i: dict) -> str:
    flag = " · asks you" if i.get("question") and i.get("state") == "replied" else ""
    return (f"#{i['id']:<4} {i['state']:<8} {i['session'][:8]}  {i['path']}  {i['title']}"
            f"  ({_ago(i.get('updated'))}{flag})")


def _handler(a) -> int:
    from . import jarvis
    from .sessions import service
    try:
        if a.jarvis_cmd == "status":
            st = jarvis.status()
            if a.json:
                print(json.dumps(st, indent=2, default=str))
                return 0
            s = st["session"] or {}
            print(f"Jarvis     {'on' if st['on'] else 'off (Settings -> Features -> Jarvis)'}")
            print(f"Talk       {s.get('id', '')[:8]} {s.get('title', '')} [{s.get('state', '-')}]" if s else "Talk       none yet")
            print(f"Settings   " + ", ".join(f"{k}={v}" for k, v in st["settings"].items()))
            print(f"Work       {st['open']} open, {st['asks']} asking you")
            return 0
        if a.jarvis_cmd == "say":
            s = jarvis.say(" ".join(a.text))
            print(f"sent to {s.get('id', '')[:8]} {s.get('title', '')}")
            return 0
        if a.jarvis_cmd == "new":
            s = jarvis.new_conversation()
            print(f"new conversation {s.get('id', '')[:8]}")
            return 0
        if a.jarvis_cmd == "work":
            if a.action == "close":
                if not a.ref:
                    print("work close ID", file=sys.stderr)
                    return 2
                i = jarvis.close(a.ref)
                print(f"closed #{i['id']} {i['title']}" + (" - its session is archived" if i.get("archived") else ""))
                return 0
            items = jarvis.work(None if a.all else "open", everyone=a.all)
            print(json.dumps(items, indent=2) if a.json else "\n".join(map(_row, items)) or "no open work")
            return 0
        if a.jarvis_cmd == "digest":
            if a.mark:
                jarvis.mark_dream()
            print("night pass marked: the next digest starts now" if a.mark else jarvis.digest(a.since))
            return 0
        if a.jarvis_cmd == "brief":
            s = jarvis.brief()
            print(f"brief sent to {s.get('id', '')[:8]}")
            return 0
        if a.jarvis_cmd == "dream":
            s = jarvis.dream()
            print(f"night pass started: {s.get('id', '')[:8]}")
            return 0
        if a.jarvis_cmd == "set":
            boolean = isinstance(jarvis.DEFAULTS[a.key], bool)
            v: object = a.value.lower() in ("1", "on", "true", "yes") if boolean else a.value
            jarvis.save_settings({a.key: v})
            print(f"{a.key} = {jarvis.settings()[a.key]}")
            return 0
    except (jarvis.JarvisError, service.SessionError) as e:
        print(e.message, file=sys.stderr)
        return 1
    return 2


cli.register("jarvis", "Jarvis: its conversation (say, new), work board, digest, brief, night pass, settings", _configure, _handler)
