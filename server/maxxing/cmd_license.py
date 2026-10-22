"""`maxxing license activate|status|remove|release` - the Enterprise key of this server (optional)."""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import cli
from .cmd_core import FAIL, INFO, OK, line


def _date(t) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(float(t))) if t else ""


def _show(st: dict) -> None:
    if not st.get("enabled"):
        if st.get("has_key"):
            line(OK, f"Enterprise key {st.get('key_hint', '')} ({st.get('kind') or '?'})"
                 + (f" - {st['email']}" if st.get("email") else "")
                 + (f" · ends {_date(st['expires_at'])}" if st.get("expires_at") else ""))
        else:
            line(INFO, "no Enterprise key (none is needed for yourself or one organisation's own needs)",
                 "for affiliates, clients or a paid offer: https://harness-maxxing.com/#enterprise, then "
                 "maxxing license activate")
        line(INFO, "updates come from the git repository" + (f" (since {_date(st['moved_to_git'])})" if st.get("moved_to_git") else ""))
        return
    # an install from before 2.0.0a87, still on the code of a signed archive
    if st.get("has_key"):
        line(OK, f"Enterprise key {st.get('key_hint', '')} ({st.get('kind') or '?'})"
             + (f" - {st['email']}" if st.get("email") else ""))
    line(INFO, "this server moves to the public git repository by itself"
         + (f" - not yet: {st['move_error']}" if st.get("move_error") else ""), "maxxing update  (moves it now)")


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action")
    a = sub.add_parser("activate", help="record an Enterprise key on this server (checked by the license server)")
    a.add_argument("key", nargs="?", help="HM-XXXX-XXXX-XXXX-XXXX (better: leave it out to be asked, or --key-from-stdin)")
    a.add_argument("--key-from-stdin", action="store_true")
    # no-op, kept: install.sh passes it (the old code of an install from before 2.0.0a87 understands it)
    a.add_argument("--no-fetch", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("status", help="show the license of this server").add_argument("--json", action="store_true")
    sub.add_parser("remove", help="forget the Enterprise key of this server (frees its place)")
    sub.add_parser("release", help="free this server's place on the license (before moving to another server)")


def _handler(a) -> int:
    from . import license
    act = a.action or "status"
    try:
        if act == "activate":
            key = sys.stdin.readline().strip() if a.key_from_stdin else (a.key or "").strip()
            if not key and not a.key_from_stdin and sys.stdin.isatty():
                import getpass                          # asked, hidden: the key stays out of the shell history
                key = getpass.getpass("License key (HM-XXXX-XXXX-XXXX-XXXX): ").strip()
            if not key:
                line(FAIL, "give the license key", "maxxing license activate  (it asks for the key)")
                return 2
            r = license.activate(key)
            line(OK, f"Enterprise key recorded ({r['license'].get('kind')}, {r['license'].get('email')})",
                 "nothing else changes: updates keep coming from the git repository")
            return 0
        if act == "status":
            st = license.status()
            if getattr(a, "json", False):
                print(json.dumps(st, indent=2))
            else:
                _show(st)
            return 0
        if act == "remove":
            r = license.remove_key()
            line(OK, "Enterprise key removed" + (" (its place on the license is free)" if r.get("freed") else ""))
            return 0
        if act == "release":
            license.release()
            line(OK, "this server no longer uses a place on the license",
                 "it keeps working; activate the key on the new server with: maxxing license activate <key>")
            return 0
    except license.LicenseError as e:
        line(FAIL, str(e))
        for s in (e.data.get("servers") or [])[:10]:
            line(INFO, f"active on {s.get('hostname') or '?'} (last seen {_date(s.get('last_seen'))})")
        return 1
    return 2


cli.register("license", "Enterprise key of this server (activate, status, remove, release)", _configure, _handler)
