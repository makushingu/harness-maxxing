"""`maxxing community …`: read what a package from outside does before installing it (community.py).

  maxxing community check PATH [--kind extension|skill|theme] [--json]
        what the folder or zip would do (code on the server, network, keys, processes, paths): nothing is installed
  maxxing community install PATH [--sha256 HASH] [--yes] [--read] [--force] [--source TEXT]
        show the same report, ask, then install exactly that content; `--yes` needs the `--sha256` of the report
        the owner read, and `--read` when it has findings marked "danger"
  maxxing community list [--json]
        what was installed this way: content hash, source, date, and whether its files changed since

The report is a reading aid, not a verdict.
"""
from __future__ import annotations

import json
import sys
import time

from . import cli

NEEDS_CONFIRMATION = 3
MARK = {"danger": "!!", "warn": " !", "info": "  "}


def _configure(p) -> None:
    sub = p.add_subparsers(dest="cm_cmd", required=True)
    r = sub.add_parser("check", help="what a package (folder or zip) would do; nothing is installed")
    r.add_argument("path"); r.add_argument("--kind", choices=("extension", "skill", "theme"))
    r.add_argument("--json", action="store_true")
    r = sub.add_parser("install", help="show the report, ask, then install exactly the content that was read")
    r.add_argument("path"); r.add_argument("--kind", choices=("extension", "skill", "theme"))
    r.add_argument("--sha256", help="the hash of the report that was read: refused when the content differs")
    r.add_argument("--yes", action="store_true", help="do not ask (needs --sha256)")
    r.add_argument("--read", action="store_true", help="the owner read the findings marked danger")
    r.add_argument("--force", action="store_true", help="replace an installed package (an update)")
    r.add_argument("--source", default="", help="where it comes from (repository URL and commit), kept with it")
    r = sub.add_parser("list", help="packages installed this way")
    r.add_argument("--json", action="store_true")


def _day(ts) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if isinstance(ts, (int, float)) else "?"


def print_report(r: dict, out=None) -> None:
    out = out or sys.stdout
    print(r["summary"], file=out)
    print(f"  sha256 {r['sha256']}", file=out)
    prev = r.get("installed")
    if prev:
        note = ("CHANGED since the version you installed" if r.get("changed")
                else "same content as the version you installed")
        print(f"  {note} ({_day(prev.get('installed_at'))}, sha256 {str(prev.get('sha256'))[:12]}"
              + (f", from {prev['source']}" if prev.get("source") else "") + ")", file=out)
    for f in r["findings"]:
        where = f["file"] + (f":{f['line']}" if f["line"] else "")
        print(f"{MARK[f['level']]} {f['level']:<6} {where}  {f['what']}", file=out)
        if f["excerpt"]:
            print(f"            {f['excerpt']}", file=out)


def _ask(question: str, expect: tuple[str, ...]) -> bool:
    try:
        return input(question).strip().lower() in expect
    except (EOFError, KeyboardInterrupt):
        return False


def confirm(r: dict, yes: bool, read: bool, sha256: str | None, again: str) -> tuple[int, bool]:
    """(0, read_it) when the owner agreed, else (exit code, False) after saying why."""
    danger = r["counts"]["danger"]
    if yes:
        if not sha256:
            print("error: --yes needs --sha256 (the hash of the report the owner read)", file=sys.stderr)
            return 1, False
        if danger and not read:
            print(f"error: {danger} finding(s) marked danger: --read says the owner read what it does",
                  file=sys.stderr)
            return NEEDS_CONFIRMATION, False
        return 0, read
    if not sys.stdin.isatty():
        print(f"\nNothing installed: this needs the owner's agreement. Once they read the report:\n  {again} "
              f"--sha256 {r['sha256']} --yes" + (" --read" if danger else ""), file=sys.stderr)
        return NEEDS_CONFIRMATION, False
    if danger and not _ask(f"\n{danger} finding(s) marked danger. Type \"read\" once you read what it does: ",
                           ("read",)):
        print("Nothing installed.", file=sys.stderr)
        return NEEDS_CONFIRMATION, False
    if not _ask("Install this? [y/N] ", ("y", "yes")):
        print("Nothing installed.", file=sys.stderr)
        return NEEDS_CONFIRMATION, False
    return 0, bool(danger)


def _handler(a) -> int:
    from . import community
    try:
        if a.cm_cmd == "check":
            r = community.report(a.path, a.kind)
            if a.json:
                print(json.dumps(r, indent=2, ensure_ascii=False))
            else:
                print_report(r)
            return 0
        if a.cm_cmd == "install":
            r = community.report(a.path, a.kind)
            print_report(r)
            if a.sha256 and a.sha256.strip().lower() != r["sha256"]:
                print("error: the content is not the one that was checked (--sha256 differs): nothing installed. "
                      "Read this report.", file=sys.stderr)
                return 1
            code, read_it = confirm(r, a.yes, a.read, a.sha256, f"maxxing community install {a.path}")
            if code:
                return code
            done = community.install(a.path, r["sha256"], read_it=read_it, force=a.force, source=a.source, kind=a.kind)
            where = {"extension": "Settings -> Widgets / Pages -> Rescan", "skill": "Settings -> Skills",
                     "theme": "Settings -> Appearance -> Theme"}[done["kind"]]
            print(f"Installed {done['kind']} {done['id']} (sha256 {done['sha256'][:12]}): {where}.")
            return 0
        if a.cm_cmd == "list":
            rows = community.installed()
            if a.json:
                print(json.dumps({"packages": rows}, indent=2, ensure_ascii=False))
                return 0
            for p in rows:
                state = {"ok": "", "modified": "  (files CHANGED since the install)",
                         "removed": "  (no longer there)"}[p["state"]]
                print(f"{p['kind']:<10} {p['id']:<24} {str(p.get('version') or '-'):<10} {_day(p.get('installed_at'))}  "
                      f"sha256 {str(p.get('sha256'))[:12]}  {p.get('source') or '-'}{state}")
            if not rows:
                print("Nothing installed with `maxxing community install`.")
            return 0
    except community.PackageError as e:
        print(f"error: {e}", file=sys.stderr)
        return NEEDS_CONFIRMATION if isinstance(e, community.NeedsConfirmation) else 1
    return 2


cli.register("community", "packages from outside: read what one does (check), install exactly that (install), list",
             _configure, _handler)
