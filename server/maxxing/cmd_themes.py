"""`maxxing themes …`: the installed themes of Settings -> Appearance (themes.py, skill `maxxing-theme`).

  maxxing themes list [--json]              installed themes (and folders that are not usable)
  maxxing themes check <folder> [--json]    read a theme like the interface will: what it sets, what is dropped and why
  maxxing themes install <folder> [--force] check it, then copy it into <workspace>/themes/<id>/
  maxxing themes verify <id>                its advanced css still looks right with this interface: switch it back on
  maxxing themes remove <id>                delete an installed theme (browsers using it go back to its base)
  maxxing themes tokens [--json]            the variables a theme may set, and their kind
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="th_cmd", required=True)
    r = sub.add_parser("list", help="installed themes")
    r.add_argument("--json", action="store_true")
    r = sub.add_parser("check", help="check a theme folder (nothing is installed)")
    r.add_argument("folder"); r.add_argument("--json", action="store_true")
    r = sub.add_parser("install", help="check a theme folder and install it")
    r.add_argument("folder"); r.add_argument("--force", action="store_true", help="replace an installed theme")
    r = sub.add_parser("verify", help="switch a theme's advanced css back on after checking it (after an update)")
    r.add_argument("id")
    r = sub.add_parser("remove", help="delete an installed theme")
    r.add_argument("id")
    r = sub.add_parser("tokens", help="the variables a theme may set")
    r.add_argument("--json", action="store_true")


def _name(t: dict) -> str:
    n = t["name"]
    return n if isinstance(n, str) else n.get("en") or next(iter(n.values()))


def _report(t: dict, warn: list[str]) -> None:
    print(f"{t['id']}  {_name(t)}  (base {t['base']}, modes {', '.join(t['modes'])})")
    for m in ("light", "dark"):
        if t[m]:
            print(f"  {m}: {len(t[m])} variables: {', '.join(t[m])}")
    if t["options"]:
        print("  options: " + ", ".join(f"{k}={v}" for k, v in t["options"].items()))
    for m, u in t["wallpaper"].items():
        if u:
            print(f"  wallpaper ({m}): {u.rsplit('/', 1)[1]}")
    for m, u in t["logo"].items():
        if u:
            print(f"  logo ({m}): {u.rsplit('/', 1)[1]}")
    if t.get("css"):
        state = {"on": "on", "stale": "OFF until `maxxing themes verify " + t["id"] + "` (never checked against "
                 "this interface, or an update changed its CSS)"}.get(t["css_state"], t["css_state"])
        print(f"  advanced css: {len(t['css'])} characters, {state}")
    for w in warn:
        print(f"  ! {w}")
    if not warn:
        print("  no warning")


def _handler(a) -> int:
    from . import themes
    c = a.th_cmd
    try:
        if c == "list":
            data = themes.list_themes()
            if a.json:
                print(json.dumps(data, indent=2, ensure_ascii=False))
                return 0
            for t in data["themes"]:
                print(f"{t['id']:<20} {_name(t):<24} {t['base']:<6} {', '.join(t['modes'])}"
                      + ("  (css OFF: verify)" if t["css_state"] == "stale" else "")
                      + (f"  ({len(t['warnings'])} warnings)" if t["warnings"] else ""))
            for e in data["errors"]:
                print(f"{e['id']:<20} NOT USABLE: {e['error']}")
            if not data["themes"] and not data["errors"]:
                print(f"No theme installed ({themes.root()}). Built-in: solid, glass.")
            return 0
        if c == "check":
            t, warn, err = themes.load(Path(a.folder).expanduser().resolve())
            if a.json:
                print(json.dumps({"ok": not err, "error": err, "theme": t, "warnings": warn}, indent=2,
                                 ensure_ascii=False))
                return 1 if err else 0
            if err or not t:
                print(f"error: {err}", file=sys.stderr)
                return 1
            _report(t, warn)
            return 0
        if c == "install":
            t, warn = themes.install(Path(a.folder), force=a.force)
            _report(t, warn)
            print(f"Installed in {themes.root() / t['id']}: Settings -> Appearance -> Theme.")
            return 0
        if c == "verify":
            t = themes.verify(a.id)
            _report(t, t["warnings"])
            print("Advanced css switched on for this interface." if t["css"] else "This theme has no advanced css.")
            return 0
        if c == "remove":
            if not themes.remove(a.id):
                print(f"No installed theme {a.id}.", file=sys.stderr)
                return 1
            print(f"Removed {a.id}.")
            return 0
        if c == "tokens":
            if a.json:
                print(json.dumps({"schema": themes.SCHEMA, "tokens": themes.TOKENS, "options": themes.OPTIONS},
                                 indent=2))
                return 0
            for k, kind in themes.TOKENS.items():
                print(f"{k:<24} {kind}")
            return 0
    except themes.ThemeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 2


cli.register("themes", "installed themes of Settings -> Appearance (list, check, install, verify, remove, tokens)",
             _configure, _handler)
