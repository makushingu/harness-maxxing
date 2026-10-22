"""`maxxing infra` - where every site, database, bucket, domain and server is, and the standard recipes to create
them on this server (skill `maxxing-infra`, page Infra).

    maxxing infra status                         sources and problems of the last snapshot
    maxxing infra list [--kind K] [--json]       resources (site, worker, pages, database, bucket, domain, server)
    maxxing infra refresh                        gather everything now (takes 10-60 s)
    maxxing infra site add NAME (--dir DIR | --port PORT) [--host HOST] [--dns] [--project P] [--keep-prefix]
    maxxing infra site remove NAME | site list | reserved
    maxxing infra db install | db create NAME [--project P] | db sqlite PATH [--project P] | db backup
    maxxing infra bucket install | bucket create NAME [--public] [--project P]
    maxxing infra server connect HOST|HOSTINGER_ID [--user U] [--port N] [--label L]   (keys found or added for you)
    maxxing infra server add NAME HOST [--user U] [--port N] [--key PATH] [--label L] [--force]
    maxxing infra server rename NAME LABEL | server remove NAME | server list
    maxxing infra domain add|remove NAME | domain list   domains added by hand (any registrar: public DNS + RDAP)
    maxxing infra annotate ID [--project P] [--note TEXT] [--hide | --show]

Without --host a site is https://<Harness address>/<NAME>/ (sandboxed: no access to Harness); with --host it gets
its own address (--dns creates the DNS record on Cloudflare when the token may).
"""
from __future__ import annotations

import json
import sys

from . import cli

KINDS = ("site", "worker", "pages", "database", "bucket", "domain", "server")


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("status", help="sources and problems of the last snapshot")
    ls = sub.add_parser("list", help="resources of the last snapshot")
    ls.add_argument("--kind", choices=KINDS)
    ls.add_argument("--all", action="store_true", help="include hidden and system resources")
    ls.add_argument("--json", action="store_true")
    sub.add_parser("refresh", help="gather everything now")
    sub.add_parser("reserved", help="names a path site cannot take")

    site = sub.add_parser("site", help="sites served by Caddy on this server").add_subparsers(dest="sub", required=True)
    a = site.add_parser("add")
    a.add_argument("name")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--dir", help="folder of a static site")
    g.add_argument("--port", type=int, help="local port of an app (127.0.0.1)")
    a.add_argument("--host", help="own address (example: shop.example.com) instead of <Harness address>/<name>/")
    a.add_argument("--dns", action="store_true", help="with --host: create the DNS record on Cloudflare")
    a.add_argument("--project")
    a.add_argument("--keep-prefix", action="store_true", help="app under /<name>/ that handles the prefix itself (basePath)")
    r = site.add_parser("remove")
    r.add_argument("name")
    site.add_parser("list")

    db = sub.add_parser("db", help="databases on this server").add_subparsers(dest="sub", required=True)
    db.add_parser("install", help="install PostgreSQL (localhost only) + nightly backups")
    c = db.add_parser("create", help="PostgreSQL database + role; URL in the vault as DB_<NAME>_URL")
    c.add_argument("name")
    c.add_argument("--project")
    s = db.add_parser("sqlite", help="declare a SQLite file (shown and backed up)")
    s.add_argument("path")
    s.add_argument("--project")
    db.add_parser("backup", help="dump every database now")

    b = sub.add_parser("bucket", help="S3 buckets (Garage) on this server").add_subparsers(dest="sub", required=True)
    b.add_parser("install", help="install Garage (single node, 127.0.0.1)")
    c = b.add_parser("create")
    c.add_argument("name")
    c.add_argument("--public", action="store_true", help="serve its files at <Harness address>/<name>/")
    c.add_argument("--project")

    sv = sub.add_parser("server", help="other servers read over SSH").add_subparsers(dest="sub", required=True)
    a = sv.add_parser("add")
    a.add_argument("name")
    a.add_argument("host")
    a.add_argument("--user", default="root")
    a.add_argument("--port", type=int, default=22)
    a.add_argument("--key", default="", help="private key file (default: the SSH defaults of root)")
    a.add_argument("--note", default="")
    a.add_argument("--label", default="", help="name shown on the page")
    a.add_argument("--force", action="store_true", help="add it even if it cannot be read now")
    c = sv.add_parser("connect", help="connect a server: a Hostinger VPS id (see `list --kind server`) or an address")
    c.add_argument("target")
    c.add_argument("--user", default="root")
    c.add_argument("--port", type=int, default=22)
    c.add_argument("--label", default="")
    rn = sv.add_parser("rename", help="change the name shown on the page")
    rn.add_argument("name")
    rn.add_argument("label")
    dm = sub.add_parser("domain", help="domains added by hand (any registrar)").add_subparsers(dest="sub", required=True)
    for verb in ("add", "remove"):
        dm.add_parser(verb).add_argument("name")
    dm.add_parser("list")
    r = sv.add_parser("remove")
    r.add_argument("name")
    sv.add_parser("list")

    an = sub.add_parser("annotate", help="project, note or hide a resource")
    an.add_argument("id")
    an.add_argument("--project")
    an.add_argument("--note")
    h = an.add_mutually_exclusive_group()
    h.add_argument("--hide", action="store_true")
    h.add_argument("--show", action="store_true")


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _status(snap: dict | None) -> int:
    from . import infra
    if not snap:
        print("No snapshot yet: `maxxing infra refresh` (or turn the Infra page on in Settings -> Features).")
        return 1
    import time
    print(f"Snapshot {int((time.time() - snap['generated_at']) / 60)} min old, took {snap.get('took_ms', 0) / 1000:.1f} s"
          + ("" if infra.enabled() else "  (Infra page off: no background refresh)"))
    src = snap.get("sources") or {}
    for n, s in (src.get("servers") or {}).items():
        print(f"  server {n:<20} {'ok' if s.get('ok') else 'ERROR ' + str(s.get('error'))}")
    for prov in ("cloudflare", "hostinger", "vercel", "netlify", "supabase", "github"):
        s = src.get(prov) or {}
        if not s.get("connected"):
            print(f"  {prov:<27} not connected (no key in Settings -> Keys)")
            continue
        bad = {k: v for k, v in (s.get("sections") or {}).items() if v not in ("ok", None)}
        print(f"  {prov:<27} key {s.get('key')}" + (f" - {s['error']}" if s.get("error") else "")
              + ("" if not bad else " - " + ", ".join(f"{k}: {v}" for k, v in bad.items())))
    res = [r for r in snap.get("resources") or [] if not r.get("hidden")]
    counts: dict[str, int] = {}
    for r in res:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    print("  " + ", ".join(f"{v} {k}{'s' if v > 1 else ''}" for k, v in sorted(counts.items())))
    probs = [r for r in res if r["status"] in ("warn", "down")]
    for r in probs:
        print(f"  {r['status'].upper():<5} {r['kind']:<9} {r['name']:<45} {r['location']:<12} {r.get('status_detail') or ''}")
    return 0


def _handler(a) -> int:
    from . import infra
    from .infra import actions, caddy, registry
    try:
        if a.action == "status":
            return _status(infra.load_snapshot())
        if a.action == "refresh":
            print("Refreshing (servers, Cloudflare, Hostinger, URL checks)...", flush=True)
            snap = infra.refresh()
            if snap is None:
                print("a refresh is already running in this process")
                return 1
            return _status(snap)
        if a.action == "list":
            snap = infra.load_snapshot() or {}
            res = [r for r in snap.get("resources") or [] if (not a.kind or r["kind"] == a.kind)
                   and (a.all or (not r.get("hidden") and not r["details"].get("system")))]
            if a.json:
                _print(res)
                return 0
            for r in res:
                url = r["urls"][0] if r["urls"] else ""
                print(f"{r['status']:<7} {r['kind']:<9} {r['name'][:50]:<50} {r['location']:<12} {url}")
            if not snap:
                print("No snapshot yet: `maxxing infra refresh`.")
            return 0
        if a.action == "reserved":
            print(" ".join(caddy.reserved()))
            return 0
        if a.action == "site":
            if a.sub == "list":
                for s in caddy.list_sites():
                    print(f"{s['name']:<30} {s['mode']:<5} {s.get('project', ''):<20} {s['file']}")
                return 0
            if a.sub == "remove":
                _print(caddy.remove_site(a.name))
                infra.mark_stale()
                return 0
            res = caddy.add_site(a.name, root=a.dir, port=a.port, host=a.host, project=a.project, keep_prefix=a.keep_prefix)
            if a.host and a.dns:
                ip = _public_ipv4()
                from .infra import providers
                res["dns"] = providers.cf_point(a.host, ip) if ip else {"done": False, "message": "no public IPv4 found"}
            infra.mark_stale()
            _print(res)
            return 0
        if a.action == "db":
            if a.sub == "install":
                print("Installing PostgreSQL (1-2 min)...", flush=True)
                _print(actions.pg_install())
            elif a.sub == "create":
                _print(actions.pg_create(a.name, a.project))
            elif a.sub == "sqlite":
                _print(actions.declare_sqlite(a.path, a.project))
            else:
                results = actions.backup_all()
                for x in results:
                    print(f"{'ok   ' if x['ok'] else 'FAIL '} {x['name']:<30} {x['file'] or x['error']}")
                if not results:
                    print("nothing to back up (no PostgreSQL database, no declared SQLite file)")
                infra.mark_stale()
                return 0 if all(x["ok"] for x in results) else 1
            infra.mark_stale()
            return 0
        if a.action == "bucket":
            if a.sub == "install":
                print("Installing Garage...", flush=True)
                _print(actions.garage_install())
            else:
                _print(actions.bucket_create(a.name, a.public, a.project))
            infra.mark_stale()
            return 0
        if a.action == "server":
            if a.sub == "list":
                for s in registry.servers():
                    print(f"{s['name']:<20} {s.get('user')}@{s['host']}:{s.get('port', 22)}  {s.get('key') or ''}  {s.get('note') or ''}")
                return 0
            if a.sub == "remove":
                if not registry.remove_server(a.name):
                    print(f"{a.name}: no such server", file=sys.stderr)
                    return 1
                print(f"{a.name} removed")
                infra.mark_stale()
                return 0
            if a.sub == "rename":
                _print(registry.rename_server(a.name, a.label))
                infra.mark_stale()
                return 0
            if a.sub == "connect":
                from .infra import connect
                try:
                    if a.target.isdigit():
                        _print(connect.connect_hostinger(f"server:hostinger:{a.target}", a.label))
                    else:
                        _print(connect.connect_host(a.target, a.user, a.port, a.label))
                except connect.ConnectError as e:
                    print(f"error: {e}", file=sys.stderr)
                    if e.extra.get("command"):
                        print(f"Run this on {a.target} (as {a.user}), then connect again:\n  {e.extra['command']}", file=sys.stderr)
                    return 2
                infra.mark_stale()
                return 0
            _print(actions.server_add(a.name, a.host, a.user, a.port, a.key, a.note, a.force, a.label))
            infra.mark_stale()
            return 0
        if a.action == "domain":
            if a.sub == "list":
                for n in registry.load()["domains"]:
                    print(n)
                return 0
            if a.sub == "add":
                print(f"{registry.add_domain(a.name)} added (shown after the next refresh)")
            elif not registry.remove_domain(a.name):
                print(f"{a.name}: not added by hand", file=sys.stderr)
                return 1
            else:
                print(f"{a.name} removed")
            infra.mark_stale()
            return 0
        if a.action == "annotate":
            hidden = True if a.hide else (False if a.show else None)
            _print(registry.annotate(a.id, a.project, a.note, hidden))
            infra.mark_stale()
            return 0
    except (caddy.CaddyError, actions.ActionError, registry.RegistryError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 2


def _public_ipv4() -> str | None:
    import ipaddress
    from .infra import probe
    for i in probe.server().get("ips") or []:
        try:
            a = ipaddress.ip_address(i["ip"])
        except ValueError:
            continue
        if a.version == 4 and a.is_global:
            return i["ip"]
    return None


cli.register("infra", "sites, databases, buckets, domains and servers: list them, create them the standard way",
             _configure, _handler)
