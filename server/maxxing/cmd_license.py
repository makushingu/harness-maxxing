"""`maxxing license activate|status|remove|check|release|ping` - the Enterprise key of this server (optional)."""
from __future__ import annotations

import json
import sys
import time

from . import cli
from .cmd_core import FAIL, INFO, OK, WARN, line


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
    line(OK, f"license {st.get('key_hint', '')} ({st.get('kind') or '?'}) - {st.get('email') or ''}")
    up = st.get("updates_until")
    line(INFO, f"updates: {'until ' + _date(up) if up else 'included'}"
         + (f" · key ends {_date(st['expires_at'])}" if st.get("expires_at") else "")
         + (f" · channel {st['channel']}" if st.get("channel") and st["channel"] != "stable" else ""))
    if st.get("latest"):
        line(INFO, f"latest version: {st['latest']}" + (f" ({st['message']})" if st.get("message") else ""))


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action")
    a = sub.add_parser("activate", help="record an Enterprise key on this server (checked by the license server)")
    a.add_argument("key", nargs="?", help="HM-XXXX-XXXX-XXXX-XXXX (better: leave it out to be asked, or --key-from-stdin)")
    a.add_argument("--key-from-stdin", action="store_true")
    a.add_argument("--no-fetch", action="store_true", help="do not download the latest version now")
    sub.add_parser("status", help="show the license of this server").add_argument("--json", action="store_true")
    sub.add_parser("check", help="ask the license server for a new version").add_argument("--json", action="store_true")
    sub.add_parser("remove", help="forget the Enterprise key of this server (frees its place)")
    sub.add_parser("release", help="free this server's place on the license (before moving to another server)")
    sub.add_parser("ping", help="send the daily status now")


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
            was_archives = license.enabled()
            r = license.activate(key)
            line(OK, f"Enterprise key recorded ({r['license'].get('kind')}, {r['license'].get('email')})",
                 "nothing else changes: updates keep coming from the git repository")
            if was_archives and not a.no_fetch and config_is_git():
                f = license.fetch_latest()
                if f.get("version"):
                    line(OK, f"version {f['version']} downloaded and verified", "install it with: maxxing update")
            return 0
        if act == "status":
            st = license.status()
            if getattr(a, "json", False):
                print(json.dumps(st, indent=2))
            else:
                _show(st)
            return 0
        if act == "check":
            r = license.check()
            if getattr(a, "json", False):
                print(json.dumps(r, indent=2))
            elif r.get("allowed"):
                line(OK, f"version {r['release']['version']} available", "maxxing update")
            elif r.get("available"):
                line(WARN, f"version {r['latest']} exists", r.get("message") or "")
            else:
                line(OK, f"up to date ({license.disk_version()})")
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
        if act == "ping":
            r = license.ping(license.health_summary())
            line(OK if r.get("ok") else WARN, "status sent" if r.get("ok") else f"not sent: {r.get('error')}")
            return 0
    except license.LicenseError as e:
        line(FAIL, str(e))
        for s in (e.data.get("servers") or [])[:10]:
            line(INFO, f"active on {s.get('hostname') or '?'} (last seen {_date(s.get('last_seen'))})")
        return 1
    return 2


def config_is_git() -> bool:
    from . import config
    return (config.CODE / ".git").exists()


cli.register("license", "license of this server (activate, status, check, release, ping)", _configure, _handler)
