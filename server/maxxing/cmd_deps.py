"""`maxxing deps list|verify|update|remove|clean|check` - the external components of deps.toml (see deps.py)."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import cli, deps


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def _root_only() -> bool:
    if os.geteuid() != 0 and not os.environ.get("MAXXING_DEPS_BIN"):
        print("Run as root (the components belong to root).", file=sys.stderr)
        return False
    return True


def cmd_deps(a) -> int:
    what = a.action
    if what == "list":
        rows = deps.status()
        if a.json:
            print(json.dumps(rows, indent=1))
            return 0
        w = max(len(r["name"]) for r in rows)
        for r in rows:
            mark = {"ok": "✔", "outdated": "!", "missing": "✘"}.get(r["state"], "–")
            have = r["installed"] or "-"
            want = r["expected"] or "-"
            extra = "" if r["state"] in ("ok", "not installed") else f"  (expected {want})"
            print(f"  {mark} {r['name']:<{w}}  {have}{extra}  [{r['update']}]  {r['detail']}".rstrip())
        return 1 if any(r["state"] in ("missing", "outdated") for r in rows) else 0
    if what == "verify":
        res = deps.verify(a.names or None, fresh=True)
        if a.json:
            print(json.dumps(res, indent=1))
        else:
            for r in res:
                print(f"  {'✔' if r['level'] == 'ok' else ('!' if r['level'] == 'warn' else '✘')} {r['name']}: {r['text']}")
        return 1 if any(r["level"] == "fail" for r in res) else 0
    if what == "update":
        if not _root_only():
            return 1
        rep = deps.update(a.names or None, log=(lambda s: None) if a.quiet else (lambda s: print("  " + s, flush=True)),
                          explicit=False if a.auto else None)
        failed = [r for r in rep if r["result"] == "failed"]
        if failed and a.notify:
            from . import feed
            body = "\n".join(f"{r['name']}: {r['text']}" for r in failed)[:2000]
            feed.system("Dependency update failed", body, "warning", "system", "/settings")
            from .telegram import gateway
            gateway.system_alert("Dependency update failed (Harness Maxxing):\n" + body)
        if a.quiet and failed:
            for r in failed:
                print(f"{r['name']}: {r['text']}", file=sys.stderr)
        return 1 if failed else 0
    if what == "remove":
        if not _root_only():
            return 1
        if not a.names:
            print("Name the component(s) to remove (see: maxxing deps list).", file=sys.stderr)
            return 2
        rc = 0
        for n in a.names:
            try:
                gone = deps.remove(n, force=a.force)
                print(f"  ✔ {n}: removed {len(gone)} path(s)" + ("" if not gone else " - " + ", ".join(gone[:4])))
            except deps.DepError as e:
                print(f"  ✘ {n}: {e}", file=sys.stderr)
                rc = 1
        return rc
    if what == "clean":
        if not _root_only():
            return 1
        out = deps.clean(dry=a.dry_run, caches=a.caches)
        total = sum(x["bytes"] for x in out)
        if not a.quiet or a.dry_run:
            for x in out:
                print(f"  {_human(x['bytes']):>9}  {x['path']}  ({x['why']})")
            print(f"  {'would free' if a.dry_run else 'freed'} {_human(total)}")
        return 0
    if what == "check":
        try:
            r = deps.check()
        except Exception as e:  # noqa: BLE001 - offline / OSV down: not a vulnerability
            print(f"  – vulnerability check skipped (osv.dev not reachable: {str(e)[:120]})")
            return 0
        if a.json:
            print(json.dumps(r, indent=1))
        elif not r["vulnerable"]:
            print(f"  ✔ no known vulnerability in {r['checked']} packages and components (osv.dev)")
        else:
            for v in r["vulnerable"]:
                print(f"  ! {v['where']}: {v['name']} {v['version']} ({', '.join(x for x in v['ids'] if x)})")
        if a.notify:
            deps.notify_vulnerable(r)
        return 1 if r["vulnerable"] else 0
    return 2


def _cfg(p: argparse.ArgumentParser) -> None:
    p.add_argument("action", choices=("list", "verify", "update", "remove", "clean", "check"),
                   help="list: installed vs pinned | verify: checksums and owners | update: move to the pinned versions"
                        " | remove NAME | clean: caches, old versions, orphans | check: known vulnerabilities (OSV)")
    p.add_argument("names", nargs="*", help="components (default: all) - see deps.toml")
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true", help="print only problems")
    p.add_argument("--notify", action="store_true", help="check/update: report problems in the feed (+ Telegram)")
    p.add_argument("--dry-run", action="store_true", help="clean: say what would go, remove nothing")
    p.add_argument("--force", action="store_true", help="remove: also uv, Python or Claude Code")
    p.add_argument("--caches", action="store_true",
                   help="clean: also root's uv/npm/pip/npx caches (shared with the other tools of the server)")
    p.add_argument("--auto", action="store_true",
                   help="update: as after `maxxing update` - keep a uv that is not ours and a venv that works")


cli.register("deps", "external components: list, verify, update, remove, clean, check", _cfg, cmd_deps)
