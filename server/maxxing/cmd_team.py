"""`maxxing team` - write to a Team contact or group from a session or a script (see docs/user/29-team.md).

  maxxing team send NAME MESSAGE... [--file PATH]   the message goes out as yours, as if typed on the Team page
  maxxing team list [--json]                        the contacts and groups you can write to

Nothing here reads the chats: what people write never reaches Claude by itself (see team.py).
"""
from __future__ import annotations

import json
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="team_cmd", required=True)
    s = sub.add_parser("send", help="send a message to a contact or a group (by its name)")
    s.add_argument("to", help="name of the contact or group (case and accents ignored, a unique beginning is enough), "
                              "or a contact's address")
    s.add_argument("text", nargs="*", help="the message (several words are joined; '-' reads it from stdin)")
    s.add_argument("--file", action="append", default=[], metavar="PATH", help="attach a file (repeat for several)")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("list", help="contacts and groups you can write to")
    s.add_argument("--json", action="store_true")


def _run(a) -> int:
    from . import team
    try:
        if a.team_cmd == "list":
            rows = team.recipients()
            if a.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
                return 0
            for r in rows:
                detail = r["address"] + f"  ({r['status']})" if r["kind"] == "dm" else "group: " + ", ".join(r["members"])
                print(f"{r['name']:<24} {detail}")
            if not rows:
                print("No contact yet: Team -> Connections")
            return 0
        text = " ".join(a.text)
        if text == "-":
            text = sys.stdin.read()
        r = team.send_to(a.to, text, a.file)
        if a.json:
            print(json.dumps(r, ensure_ascii=False))
        else:
            files = len(r["message"].get("files") or [])
            print(f"sent to {r['to']}" + (" (group)" if r["kind"] == "group" else "")
                  + (f" with {files} file(s)" if files else ""))
        return 0
    except team.TeamError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return 2


cli.register("team", "Team: send a message to a contact or a group, list them", _configure, _run)
