"""`maxxing backup run|status|restore|held|release` - memory backup from a shell, a cron job or the installer."""
from __future__ import annotations

import datetime as dt
import getpass
import json
import os
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="bk_cmd", required=True)
    sub.add_parser("run", help="back up the workspace memory now")
    s = sub.add_parser("status", help="show the backup configuration and the last run")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("restore", help="restore the memory from the backup repository")
    s.add_argument("--from", dest="src", metavar="OWNER/NAME",
                   help="configure this private repository first (new server bootstrap)")
    s.add_argument("--token", help="GitHub token (else $MAXXING_GITHUB_TOKEN, else prompted)")
    s.add_argument("--ref", help="commit to restore (default: latest)")
    s.add_argument("--hold", action="store_true",
                   help="keep what would run code here off (jobs, extensions, hooks, local MCP servers) even on a "
                        "new server, until `maxxing backup release`")
    sub.add_parser("held", help="what the last restore kept off (jobs, extensions, hooks, local MCP servers)")
    sub.add_parser("release", help="turn on what the last restore kept off, once you checked it")


def _when(at) -> str:
    return dt.datetime.fromtimestamp(float(at)).strftime("%Y-%m-%d %H:%M") if at else "-"


def _handler(a) -> int:
    from . import backup
    if a.bk_cmd == "run":
        r = backup.run()
        if r["ok"]:
            what = "changes pushed" if r.get("changed") else "nothing changed"
            print(f"Backup OK - {r['files']} files, {what} ({(r.get('commit') or '-')[:10]}).")
            return 0
        print(f"Backup FAILED: {r.get('error')}", file=sys.stderr)
        return 2 if r.get("code") == "secret_found" else 1
    if a.bk_cmd == "status":
        st = backup.status()
        if a.json:
            print(json.dumps(st, indent=2))
            return 0
        print(f"repository : {st['repo'] or 'not configured'}"
              + ("" if st["private"] is None else (" (private)" if st["private"] else " (PUBLIC!)")))
        print(f"schedule   : {st['schedule']}")
        print(f"include    : {', '.join(dict.fromkeys(st['always'] + st['include']))}")
        last = st["last"]
        if last:
            res = "OK" if last["ok"] else f"FAILED - {last['error']}"
            print(f"last run   : {_when(last['at'])} {res} ({last.get('files') or 0} files)")
        else:
            print("last run   : never")
        return 0
    if a.bk_cmd == "held":
        _, m = backup.held_manifest()
        lines = backup.held_lines(m) if m and not m.get("released") else []
        if not lines:
            print("Nothing held.")
            return 0
        print("Restored but kept off (turn on once checked: maxxing backup release):")
        for ln in lines:
            print("  - " + ln)
        return 0
    if a.bk_cmd == "release":
        r = backup.release_held()
        if r.get("nothing"):
            print("Nothing held.")
            return 0
        print(f"Turned on: {len(r['crons'])} job(s), {len(r['extensions'])} extension(s), "
              f"hooks in {len(r['hooks'])} file(s), {r['mcp']} local MCP server(s).")
        return 0
    # restore
    hold = True if a.hold else None
    if a.src:
        tok = a.token or os.environ.get("MAXXING_GITHUB_TOKEN") or getpass.getpass("GitHub token: ")
        r = backup.restore_from(a.src, tok, a.ref, hold)
    else:
        r = backup.restore(a.ref, hold)
    if not r.get("ok"):
        print(f"Restore FAILED: {r.get('error')}", file=sys.stderr)
        return 1
    print(f"Restored {r['files']} files ({r.get('unchanged', 0)} unchanged)"
          + (", cron jobs restored" if r.get("crons") else "")
          + (f". Previous versions: {r['trash']}" if r.get("trash") else "."))
    lines = backup.held_lines(r.get("held") or {})
    if lines:
        print("Kept off until you check them (maxxing backup held / maxxing backup release):")
        for ln in lines:
            print("  - " + ln)
    return 0


cli.register("backup", "memory backup (run, status, restore, held, release)", _configure, _handler)
