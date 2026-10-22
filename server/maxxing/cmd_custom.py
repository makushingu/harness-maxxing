"""`maxxing custom` - record changes made to the product code so updates carry them over.

  maxxing custom [status]                       customizations, unsaved changes, pending update
  maxxing custom save "TITLE" --why "REASON"    commit the uncommitted changes as one customization
  maxxing custom check ID "COMMAND"             the command proving it still works (run after each update)
  maxxing custom drop ID                        remove one customization
  maxxing custom export                         rewrite <workspace>/CUSTOMIZATIONS.md + customizations/*.patch
  maxxing custom restore [--from DIR] [--stat]  re-apply saved patches (new server, after a restore); --stat lists them
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from . import cli, config, customs


def _configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="c_cmd")
    s = sub.add_parser("status", help="customizations, unsaved changes, pending update")
    s.add_argument("--json", action="store_true")
    sub.add_parser("list", help="same as status")
    s = sub.add_parser("save", help="commit the uncommitted changes of the code directory as one customization")
    s.add_argument("title", help="what the customization does, in a few words")
    s.add_argument("--why", default="", help="why the user wanted it (kept for future updates)")
    s.add_argument("--files", nargs="*", help="only these files (default: every change)")
    s.add_argument("--check", default="", help="a shell command that exits 0 while the customization works "
                                              "(run by `maxxing update --verify` after every update)")
    s = sub.add_parser("check", help="set (or clear with \"\") the check command of a customization")
    s.add_argument("id")
    s.add_argument("command", help="shell command, run from the workspace; exit 0 = still working")
    s = sub.add_parser("drop", help="remove one customization")
    s.add_argument("id")
    sub.add_parser("export", help="rewrite CUSTOMIZATIONS.md and customizations/*.patch in the workspace")
    s = sub.add_parser("restore", help="re-apply the saved patches (e.g. on a new server)")
    s.add_argument("--from", dest="src", help="folder with the .patch files (default: <workspace>/customizations)")
    s.add_argument("--stat", action="store_true", help="only list the patches that would be applied (changes nothing)")


def _print_status(js: bool) -> int:
    st = customs.summary()
    if js:
        print(json.dumps(st, indent=2, default=str))
        return 0
    if not st["git"]:
        print(f"{config.CODE} is not a git clone - customizations are not available")
        return 1
    items = st["customs"]
    print(f"Code directory : {config.CODE}")
    print(f"Customizations : {len(items) or 'none'}")
    for it in items:
        print(f"  - [{it['id']}] {it['title']}" + (f"  - {it['why']}" if it["why"] and it["why"] != "-" else ""))
        print(f"      files: {', '.join(it['files'])}")
        print(f"      check: {it['check']}" if it.get("check") else "      check: none  (maxxing custom check ID \"COMMAND\")")
    if st["dirty"]:
        print(f"Unsaved changes: {len(st['dirty'])} file(s) - {', '.join(st['dirty'][:8])}")
        print('  -> maxxing custom save "what it does" --why "why"   (an update would auto-save them)')
    if st["rebase"]:
        print("Rebase in progress: customizations are being adapted to a new version")
        print("  -> finish (git add <files> && git rebase --continue) then: maxxing update --resume")
    p = st["pending"]
    if p:
        when = dt.datetime.fromtimestamp(p.get("at", 0)).strftime("%Y-%m-%d %H:%M")
        what = {"conflict": "customizations conflict with the new version",
                "health": "the new version did not start (rolled back)",
                "dependencies": "dependency sync failed (rolled back)"}.get(p.get("reason"), p.get("reason"))
        print(f"Pending update : {p.get('target_version') or (p.get('target') or '')[:8]} - {what} ({when})")
        if p.get("conflicts"):
            print(f"  conflicting files: {', '.join(p['conflicts'])}")
        from .cmd_core import update_topic
        print(f"  -> topic {update_topic()} (skill maxxing-customize)")
    if items:
        print(f"Registry       : {Path(config.load_config()['workspace']) / customs.REGISTRY}")
    return 0


def _handler(a) -> int:
    cmd = a.c_cmd or "status"
    try:
        if cmd in ("status", "list"):
            return _print_status(getattr(a, "json", False))
        if cmd == "save":
            r = customs.save(a.title, a.why, a.files, check=a.check)
            print(f"Saved customization {r['id']}: {a.title}")
            print(f"Recorded in {r['registry']}")
            return 0
        if cmd == "check":
            customs.set_check(a.id, a.command)
            print(f"Check of {a.id}: {a.command}" if a.command.strip() else f"Check of {a.id} removed")
            return 0
        if cmd == "drop":
            r = customs.drop(a.id)
            print(f"Dropped {r['dropped']['id']}: {r['dropped']['title']}")
            print("Restart the service to run without it: systemctl restart claude-maxxing")
            return 0
        if cmd == "export":
            r = customs.export()
            print(f"{len(r['customs'])} customization(s) exported" + (f" -> {r['registry']}" if r["registry"] else ""))
            return 0
        if cmd == "restore" and a.stat:
            todo = customs.preview(Path(a.src) if a.src else None)
            if not todo:
                print("No saved customization to apply.")
            for it in todo:
                print(f"- [{it['id'] or it['file']}] {it['title']}")
                for ln in it["stat"].splitlines():
                    print("    " + ln)
            return 0
        if cmd == "restore":
            r = customs.restore(Path(a.src) if a.src else None)
            print(f"{r['applied']} customization(s) applied, {len(r['customs'])} in total")
            if r["applied"]:
                print("Restart the service to use them: systemctl restart claude-maxxing")
            return 0
    except customs.CustomError as e:
        print(f"error: {e}")
        return 1
    return 2


cli.register("custom", "customizations of the product code (status, save, check, drop, export, restore)", _configure, _handler)
