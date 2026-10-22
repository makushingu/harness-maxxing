"""`maxxing keys` - the Keys vault (Settings -> Keys) from scripts and sessions.

    maxxing keys list                     names, notes, exposed or not (never the values)
    maxxing keys get NAME                 print the value (exit 1 if missing)
    printf %s "$V" | maxxing keys set NAME [--note TEXT] [--no-expose]
    maxxing keys delete NAME

`set` reads the value from stdin (never from the command line, which `ps` shows). A new key is exposed
by default: every later Claude turn and shell job gets it as an environment variable.
"""
from __future__ import annotations

import json
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action", required=True)
    ls = sub.add_parser("list", help="names and notes, never the values")
    ls.add_argument("--json", action="store_true")
    g = sub.add_parser("get", help="print a value")
    g.add_argument("name")
    s = sub.add_parser("set", help="create or update a key; the value is read from stdin")
    s.add_argument("name")
    s.add_argument("--note")
    s.add_argument("--no-expose", action="store_true", help="keep it out of the environment of sessions and jobs")
    d = sub.add_parser("delete", help="remove a key")
    d.add_argument("name")


def _handler(a) -> int:
    from . import vault
    if a.action == "list":
        rows = vault.list_secrets()
        if a.json:
            print(json.dumps([{k: r[k] for k in ("name", "note", "expose", "updated")} for r in rows], indent=2))
        for r in [] if a.json else rows:
            print(f"{r['name']:<40} {'env' if r['expose'] else '   '}  {r['note']}")
        return 0
    if a.action == "get":
        v = vault.get(a.name)
        if v is None:
            print(f"{a.name}: no such key (Settings -> Keys)", file=sys.stderr)
            return 1
        print(v)
        return 0
    if a.action == "set":
        value = sys.stdin.read().strip()
        if not value:
            print("the value is read from stdin: printf %s \"$VALUE\" | maxxing keys set NAME", file=sys.stderr)
            return 2
        existed = vault.get(a.name) is not None
        try:
            vault.put(a.name, value, note=a.note, expose=False if a.no_expose else (None if existed else True))
        except vault.VaultError as e:
            print(f"{a.name}: {e}", file=sys.stderr)
            return 2
        print(f"{a.name} {'updated' if existed else 'created'}")
        return 0
    if not vault.delete(a.name):
        print(f"{a.name}: no such key", file=sys.stderr)
        return 1
    print(f"{a.name} deleted")
    return 0


cli.register("keys", "the Keys vault: list, get, set (value from stdin), delete", _configure, _handler)
