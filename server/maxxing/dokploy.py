"""Dokploy (self-hosted PaaS: Docker Swarm + Traefik) through its API. See docs/dev/INTERNALS.md (maxxing.dokploy).

The key is in the vault (`DOKPLOY_API_KEY`, not in the environment of sessions: they go through `maxxing dokploy`),
and the URL it was checked against sits next to it in secrets.json (`dokploy_url`): the key is only ever sent there,
whatever the environment or config.json say. Procedures are tRPC style: GET|POST <url>/api/<router>.<proc>, header
`x-api-key`. MAXXING_DOKPLOY_LOGS replaces the deployment log folder (tests).
"""
from __future__ import annotations

import ipaddress
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import config
from .infra.providers import TIMEOUT, ProviderError

KEY = "DOKPLOY_API_KEY"
DEFAULT_URL = "http://127.0.0.1:3000"
LOGS = Path("/etc/dokploy/logs")
DB_KINDS = ("postgres", "mysql", "mariadb", "mongo", "redis")
KINDS = ("application", "compose") + DB_KINDS
BUILD_TYPES = ("dockerfile", "nixpacks", "railpack", "heroku_buildpacks", "paketo_buildpacks", "static")
LOG_MAX_LINES = 2000
TAILNET = ipaddress.ip_network("100.64.0.0/10")      # Tailscale addresses: already encrypted end to end
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]$")
BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]{1,200}$")
NAME_RE = re.compile(r"^(?!-)[A-Za-z0-9 ._-]{1,63}$")
GIT_URL_RE = re.compile(r"^(https://|ssh://)[^\s'\"\\]+$|^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:[^\s'\"\\-][^\s'\"\\]*$")


def logs_dir() -> Path:
    return Path(os.environ.get("MAXXING_DOKPLOY_LOGS") or LOGS)


def check_url(url: str) -> str:
    """The URL without trailing slash; plain http only to this machine or a private network (the key goes in clear)."""
    u = (url or "").strip().rstrip("/")
    p = urlsplit(u)
    try:
        p.port                                         # a port out of range raises here, not later in httpx
    except ValueError:
        raise ProviderError("invalid_url", "the Dokploy URL has an invalid port") from None
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ProviderError("invalid_url", "the Dokploy URL must be http(s)://host[:port]")
    if p.scheme == "http" and not _private(p.hostname):
        raise ProviderError("invalid_url", "use https for a Dokploy on another network: the key would travel in clear")
    return u


def _private(host: str) -> bool:
    h = host.lower()
    if h == "localhost" or h.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    if ip.is_link_local:                               # 169.254.x (cloud metadata) is never a Dokploy
        return False
    return ip.is_loopback or ip.is_private or ip in TAILNET


URL_SECRET = "dokploy_url"


def url() -> str:
    return (config.get_secret(URL_SECRET) or DEFAULT_URL).rstrip("/")


def _saved_key() -> str | None:
    from . import vault
    return (vault.get(KEY) or "").strip() or None


class Client:
    def __init__(self, base: str, key: str):
        self.base = base.rstrip("/") + "/api/"
        self.c = httpx.Client(timeout=TIMEOUT, headers={"x-api-key": key, "Accept": "application/json",
                                                        "User-Agent": "harness-maxxing"})

    def _do(self, method: str, proc: str, **kw: Any) -> Any:
        try:
            r = self.c.request(method, self.base + proc, **kw)
        except httpx.HTTPError as e:
            raise ProviderError("unreachable", f"Dokploy does not answer ({type(e).__name__})") from None
        if r.status_code in (401, 403):
            raise ProviderError("missing_permission", "the Dokploy key is refused")
        if r.status_code == 404:
            raise ProviderError("not_found", f"Dokploy: {proc} not found")
        if r.status_code >= 400:
            raise ProviderError("api_error", f"Dokploy answered {r.status_code} to {proc}: {_message(r)}")
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            raise ProviderError("bad_response", "Dokploy answered something that is not JSON") from None

    def get(self, proc: str, params: dict | None = None) -> Any:
        return self._do("GET", proc, params=params)

    def post(self, proc: str, body: dict) -> Any:
        return self._do("POST", proc, json=body)

    def close(self) -> None:
        self.c.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *a: Any) -> None:
        self.close()


def _message(r: httpx.Response) -> str:
    try:
        j = r.json()
    except ValueError:
        return r.text[:200]
    return str((j.get("message") if isinstance(j, dict) else None) or j)[:200]


def client() -> Client:
    k = _saved_key()
    if not k:
        raise ProviderError("not_connected", "Dokploy is not connected: maxxing dokploy connect")
    return Client(url(), k)


def status() -> dict:
    """{connected, url}; no network call."""
    return {"connected": bool(_saved_key()), "url": url()}


def connect(base: str, key: str) -> dict:
    """Checks the key with project.all, then saves the URL and the (unexposed) key."""
    from . import vault
    base, key = check_url(base), (key or "").strip()
    if not key:
        raise ProviderError("missing_permission", "a Dokploy API key is needed (Dokploy -> Profile -> API keys)")
    with Client(base, key) as c:
        projects = c.get("project.all")
    if not isinstance(projects, list):
        raise ProviderError("bad_response", "project.all did not answer a list")
    vault.put(KEY, key, note="Dokploy API (read by maxxing dokploy)", expose=False)
    config.set_secret(URL_SECRET, base)
    return {"connected": True, "url": base, "projects": len(projects)}


def disconnect() -> bool:
    from . import vault
    had = bool(config.get_secret(URL_SECRET))
    config.set_secret(URL_SECRET, None)
    return vault.delete(KEY) or had


# ---- services ------------------------------------------------------------------------------
_ID = {"application": "applicationId", "compose": "composeId", "postgres": "postgresId", "mysql": "mysqlId",
       "mariadb": "mariadbId", "mongo": "mongoId", "redis": "redisId"}
_STATUS = {"application": "applicationStatus", "compose": "composeStatus"}
_PLURAL = {"application": "applications", "compose": "compose"}


def _repo(a: dict) -> str | None:
    if a.get("owner") and a.get("repository"):
        return f"{a['owner']}/{a['repository']}"
    return a.get("customGitUrl") or a.get("gitlabPathNamespace") or None


def services(projects: Any) -> list[dict]:
    """project.all flattened: one entry per application, compose and database (environments of newer Dokploy, or the
    services directly on the project)."""
    out: list[dict] = []
    for p in projects if isinstance(projects, list) else []:
        if not isinstance(p, dict):
            continue
        envs = p.get("environments") if isinstance(p.get("environments"), list) else [p]
        for e in envs:
            if not isinstance(e, dict):
                continue
            for kind in KINDS:
                for s in e.get(_PLURAL.get(kind, kind)) or []:
                    if isinstance(s, dict) and s.get(_ID[kind]):
                        out.append(_service(kind, s, p, e))
    return out


def _service(kind: str, s: dict, p: dict, e: dict) -> dict:
    return {"kind": kind, "id": s[_ID[kind]], "name": s.get("name") or s.get("appName") or s[_ID[kind]],
            "app_name": s.get("appName"), "project": p.get("name"), "project_id": p.get("projectId"),
            "environment": e.get("name") if e is not p else None, "environment_id": e.get("environmentId"),
            "status": s.get(_STATUS.get(kind, "applicationStatus")) or None,
            "domains": [{"host": d.get("host"), "https": bool(d.get("https")), "port": d.get("port"),
                         "path": d.get("path") or "/"} for d in s.get("domains") or [] if isinstance(d, dict) and d.get("host")],
            "repo": _repo(s) if kind in _PLURAL else None,
            "build": s.get("buildType") if kind == "application" else None}


def environments(projects: Any) -> list[dict]:
    """Where an app can be created: {id, name, project, project_id} (an older Dokploy without environments: none)."""
    out = []
    for p in projects if isinstance(projects, list) else []:
        for e in (p.get("environments") or []) if isinstance(p, dict) else []:
            if isinstance(e, dict) and e.get("environmentId"):
                out.append({"id": e["environmentId"], "name": e.get("name"), "project": p.get("name"),
                            "project_id": p.get("projectId")})
    return out


def inventory(c: Client) -> list[dict]:
    """project.all, then <kind>.one of each app / compose stack: project.all (v0.30) gives only their id, name and
    state, not their app name, domains or repository."""
    projects = c.get("project.all")
    svcs = services(projects)
    todo = [s for s in svcs if s["kind"] in _PLURAL]

    def one(s: dict) -> dict:
        try:
            full = c.get(f"{s['kind']}.one", {_ID[s['kind']]: s["id"]})
        except ProviderError:
            return s                                   # shown with what project.all gave
        if not isinstance(full, dict):
            return s
        more = _service(s["kind"], {**full, _ID[s["kind"]]: s["id"]}, {"name": s["project"], "projectId": s["project_id"]},
                        {"name": s["environment"], "environmentId": s["environment_id"]})
        return {**s, **{k: v for k, v in more.items() if v not in (None, [], "") or k == "domains"},
                "environment": s["environment"]}
    if todo:
        with ThreadPoolExecutor(max_workers=min(8, len(todo))) as ex:
            done = {s["id"]: x for s, x in zip(todo, ex.map(one, todo))}
        svcs = [done.get(s["id"], s) if s["kind"] in _PLURAL else s for s in svcs]
    return svcs


def find(svcs: list[dict], ref: str) -> dict:
    """By id, then name or app name (case-insensitive); `ambiguous` lists the candidates."""
    r = (ref or "").strip()
    hit = [s for s in svcs if s["id"] == r]
    if not hit:
        low = r.lower()
        hit = [s for s in svcs if low in ((s["name"] or "").lower(), (s["app_name"] or "").lower())]
    if not hit:
        raise ProviderError("not_found", f"no Dokploy service named {r!r} (maxxing dokploy list)")
    if len(hit) > 1:
        names = ", ".join(f"{s['project']}/{s['name']} ({s['kind']}, {s['id']})" for s in hit)
        raise ProviderError("ambiguous", f"{r!r} matches several services: {names} - use the id")
    return hit[0]


def _deployable(svc: dict) -> None:
    if svc["kind"] not in _PLURAL:
        raise ProviderError("not_deployable", f"{svc['name']} is a {svc['kind']} database: nothing to deploy")


# ---- writes (the CLI asks --yes) --------------------------------------------------------------
def deploy(c: Client, svc: dict, title: str | None = None) -> None:
    _deployable(svc)
    body = {_ID[svc["kind"]]: svc["id"], **({"title": title} if title else {})}
    c.post(f"{svc['kind']}.deploy", body)


def redeploy(c: Client, svc: dict, title: str | None = None) -> None:
    _deployable(svc)
    body = {_ID[svc["kind"]]: svc["id"], **({"title": title} if title else {})}
    c.post(f"{svc['kind']}.redeploy", body)


def _check(value: str, rx: re.Pattern, what: str) -> str:
    """Values a (possibly prompt-injected) session passes on to Dokploy: git clone, Traefik rules, container names."""
    v = (value or "").strip()
    if not rx.match(v):
        raise ProviderError("invalid_value", f"invalid {what}: {v[:80]!r}")
    return v


def domain_add(c: Client, svc: dict, host: str, port: int | None = None, https: bool = True,
               path: str | None = None, service: str | None = None) -> Any:
    _deployable(svc)
    host = _check(host.lower(), HOST_RE, "host name")
    if port is not None and not 1 <= int(port) <= 65535:
        raise ProviderError("invalid_value", "the port must be 1-65535")
    if path is not None and not re.match(r"^/[A-Za-z0-9._~/-]*$", path):
        raise ProviderError("invalid_value", "the path must start with / and use letters, digits, . _ ~ - /")
    if svc["kind"] == "compose" and not service:
        raise ProviderError("service_needed", "a compose stack needs --service: the container of the stack to serve")
    body: dict[str, Any] = {"host": host, "https": https,
                            "certificateType": "letsencrypt" if https else "none", "domainType": svc["kind"],
                            _ID[svc["kind"]]: svc["id"]}
    if port:
        body["port"] = int(port)
    if path:
        body["path"] = path
    if service:
        body["serviceName"] = _check(service, NAME_RE, "service name")
    return c.post("domain.create", body)


def app_create(c: Client, environment_id: str, name: str, repo: str, branch: str = "main",
               build: str = "nixpacks", build_path: str = "/") -> str:
    """application.create, then its git source and build type; returns the new application id."""
    if build not in BUILD_TYPES:
        raise ProviderError("invalid_build", f"build must be one of {', '.join(BUILD_TYPES)}")
    name, repo = _check(name, NAME_RE, "app name"), _check(repo, GIT_URL_RE, "git URL (https://, ssh:// or git@host:path)")
    branch = _check(branch, BRANCH_RE, "branch")
    if not re.match(r"^/[A-Za-z0-9._/-]*$", build_path or "") or ".." in build_path:
        raise ProviderError("invalid_value", "the build path must start with / and stay inside the repository")
    app = c.post("application.create", {"name": name, "environmentId": environment_id})
    app_id = app.get("applicationId") if isinstance(app, dict) else None
    if not app_id:
        raise ProviderError("bad_response", "application.create did not give the new application id")
    c.post("application.saveGitProvider", {"applicationId": app_id, "customGitUrl": repo, "customGitBranch": branch,
                                           "customGitBuildPath": build_path, "watchPaths": None})
    c.post("application.saveBuildType", {"applicationId": app_id, "buildType": build, "dockerfile": None,
                                         "dockerContextPath": None, "dockerBuildStage": None, "herokuVersion": None,
                                         "railpackVersion": None})
    return app_id


# ---- reads -------------------------------------------------------------------------------------
def deployments(c: Client, svc: dict) -> list[dict]:
    """Newest first: {id, title, status, created, log_path}."""
    _deployable(svc)
    proc, key = ("deployment.all", "applicationId") if svc["kind"] == "application" \
        else ("deployment.allByCompose", "composeId")
    rows = c.get(proc, {key: svc["id"]}) or []
    out = [{"id": d.get("deploymentId"), "title": (d.get("title") or "").strip().split("\n")[0][:120] or None,
            "status": d.get("status"), "created": d.get("createdAt"), "log_path": d.get("logPath")}
           for d in rows if isinstance(d, dict)]  # Dokploy titles a git deployment with the whole commit message
    return sorted(out, key=lambda d: d["created"] or "", reverse=True)


def log(dep: dict, lines: int = 200) -> str:
    """Tail of a deployment log; only a local file under the Dokploy log folder is read."""
    raw = dep.get("log_path")
    if not raw:
        raise ProviderError("no_log", "this deployment has no log file")
    root = logs_dir().resolve()
    p = Path(raw).resolve()
    if root not in p.parents or not p.is_file():
        raise ProviderError("remote_log", "the log is not on this server: open it in Dokploy")
    n = max(1, min(int(lines), LOG_MAX_LINES))
    with p.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 256 * 1024))
        tail = f.read().decode("utf-8", "replace").splitlines()
    return "\n".join(tail[-n:])
