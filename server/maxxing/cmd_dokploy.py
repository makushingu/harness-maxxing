"""`maxxing dokploy` - deploy through the Dokploy of this server (or another) without ever seeing its key.

    printf %s "$KEY" | maxxing dokploy connect [--url URL]   check the key, then keep it in the vault (not exposed)
    maxxing dokploy status | disconnect
    maxxing dokploy list [--json]                              projects, apps, compose stacks, databases, domains
    maxxing dokploy environments [--json]                      where `app create` can put an app (their ids)
    maxxing dokploy deploy|redeploy APP --yes [--title T]      APP = id, name or app name
    maxxing dokploy deployments APP [--json]
    maxxing dokploy logs APP [--deployment ID] [--lines N]
    maxxing dokploy domain add APP HOST [--port N] [--path P] [--service S] [--no-https] --yes
    maxxing dokploy domain list APP
    maxxing dokploy app create --environment ID --name N --repo URL [--branch B] [--build T] --yes

Writes need --yes: the skill asks the user first.
"""
from __future__ import annotations

import json
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action", required=True)
    c = sub.add_parser("connect", help="check an API key (read from stdin) and keep it in the vault, not exposed")
    c.add_argument("--url", help="Dokploy address (default http://127.0.0.1:3000)")
    sub.add_parser("status", help="connected or not, and the address")
    sub.add_parser("disconnect", help="forget the address and delete the key")
    ls = sub.add_parser("list", help="projects, apps, compose stacks, databases and their domains")
    ls.add_argument("--json", action="store_true")
    en = sub.add_parser("environments", help="projects and environments, with the ids app create needs")
    en.add_argument("--json", action="store_true")
    for name in ("deploy", "redeploy"):
        d = sub.add_parser(name, help=f"{name} an application or compose stack")
        d.add_argument("app")
        d.add_argument("--title")
        d.add_argument("--yes", action="store_true")
    d = sub.add_parser("deployments", help="deployments of an app, newest first")
    d.add_argument("app")
    d.add_argument("--json", action="store_true")
    lg = sub.add_parser("logs", help="log of the last (or a given) deployment")
    lg.add_argument("app")
    lg.add_argument("--deployment")
    lg.add_argument("--lines", type=int, default=200)

    dom = sub.add_parser("domain", help="domains served by Dokploy's Traefik").add_subparsers(dest="sub", required=True)
    a = dom.add_parser("add")
    a.add_argument("app")
    a.add_argument("host")
    a.add_argument("--port", type=int, help="port the app listens on inside its container")
    a.add_argument("--path")
    a.add_argument("--service", help="compose stack: the service (container) of the stack to serve")
    a.add_argument("--no-https", action="store_true")
    a.add_argument("--yes", action="store_true")
    dl = dom.add_parser("list")
    dl.add_argument("app")

    app = sub.add_parser("app", help="create an application from a git repository").add_subparsers(dest="sub", required=True)
    ac = app.add_parser("create")
    ac.add_argument("--environment", required=True, help="environment id (maxxing dokploy environments)")
    ac.add_argument("--name", required=True)
    ac.add_argument("--repo", required=True, help="git URL (https or ssh)")
    ac.add_argument("--branch", default="main")
    ac.add_argument("--build", default="nixpacks")
    ac.add_argument("--build-path", default="/")
    ac.add_argument("--yes", action="store_true")


def _confirm(a, what: str) -> bool:
    if getattr(a, "yes", False):
        return True
    print(f"{what}: add --yes once the user agreed", file=sys.stderr)
    return False


def _list(svcs: list[dict]) -> None:
    for s in svcs:
        urls = " ".join(("https://" if d["https"] else "http://") + d["host"] + (d["path"] if d["path"] != "/" else "")
                        for d in s["domains"])
        where = s["project"] + (f"/{s['environment']}" if s["environment"] else "")
        print(f"{(s['status'] or '-'):<8} {s['kind']:<11} {where[:28]:<28} {s['name'][:28]:<28} {s['id']:<24} {urls}")
    if not svcs:
        print("Nothing in Dokploy yet.")


def _handler(a) -> int:
    from . import dokploy
    from .infra.providers import ProviderError
    try:
        if a.action == "connect":
            key = sys.stdin.read().strip()
            res = dokploy.connect(a.url or dokploy.url(), key)
            print(f"connected to {res['url']} ({res['projects']} projects)")
            _stale()
            return 0
        if a.action == "status":
            s = dokploy.status()
            print(f"{'connected' if s['connected'] else 'not connected'}  {s['url']}")
            return 0 if s["connected"] else 1
        if a.action == "disconnect":
            print("disconnected" if dokploy.disconnect() else "was not connected")
            _stale()
            return 0
        with dokploy.client() as c:
            if a.action == "environments":
                envs = dokploy.environments(c.get("project.all"))
                if a.json:
                    print(json.dumps(envs, indent=2))
                for e in [] if a.json else envs:
                    print(f"{(e['project'] or '')[:28]:<28} {(e['name'] or '')[:20]:<20} {e['id']}")
                if not envs and not a.json:
                    print("No environment: create a project in Dokploy first.")
                return 0
            if a.action == "app":
                if not _confirm(a, f"create {a.name} from {a.repo}"):
                    return 3
                app_id = dokploy.app_create(c, a.environment, a.name, a.repo, a.branch, a.build, a.build_path)
                print(f"created {a.name} ({app_id}); deploy it with: maxxing dokploy deploy {app_id} --yes")
                _stale()
                return 0
            svcs = dokploy.inventory(c)
            if a.action == "list":
                if a.json:
                    print(json.dumps(svcs, indent=2))
                else:
                    _list(svcs)
                return 0
            svc = dokploy.find(svcs, a.app)
            if a.action in ("deploy", "redeploy"):
                if not _confirm(a, f"{a.action} {svc['project']}/{svc['name']}"):
                    return 3
                getattr(dokploy, a.action)(c, svc, a.title)
                print(f"{a.action} of {svc['name']} started; follow it with: maxxing dokploy logs {svc['id']}")
                _stale()
                return 0
            if a.action == "deployments":
                deps = dokploy.deployments(c, svc)
                if a.json:
                    print(json.dumps(deps, indent=2))
                for d in [] if a.json else deps:
                    print(f"{(d['status'] or '-'):<8} {d['created'] or '':<26} {d['id']:<24} {d['title'] or ''}")
                return 0
            if a.action == "logs":
                deps = dokploy.deployments(c, svc)
                dep = next((d for d in deps if d["id"] == a.deployment), None) if a.deployment else (deps[0] if deps else None)
                if not dep:
                    print("no such deployment", file=sys.stderr)
                    return 1
                print(f"# {dep['status']} {dep['created']} {dep['title'] or ''}")
                print(dokploy.log(dep, a.lines))
                return 0
            if a.action == "domain":
                if a.sub == "list":
                    for d in svc["domains"]:
                        print(f"{'https' if d['https'] else 'http ':<5} {d['host']}{d['path'] if d['path'] != '/' else ''}"
                              f"  -> port {d['port'] or '-'}")
                    return 0
                if not _confirm(a, f"add {a.host} to {svc['name']}"):
                    return 3
                dokploy.domain_add(c, svc, a.host, a.port, not a.no_https, a.path, a.service)
                print(f"{a.host} -> {svc['name']} added; point its DNS to this server, then redeploy")
                _stale()
                return 0
    except ProviderError as e:
        print(f"error ({e.code}): {e.message}", file=sys.stderr)
        return 2
    return 2


def _stale() -> None:
    try:
        from . import infra
        infra.mark_stale()
    except Exception:  # noqa: BLE001 - the Infra page refreshes on its own anyway
        pass


cli.register("dokploy", "deploy through Dokploy: list, deploy, logs, domains (the key stays in the vault)",
             _configure, _handler)
