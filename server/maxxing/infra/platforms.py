"""Hosting platforms read through their APIs with a key of the vault (read-only calls only): Vercel, Netlify, Supabase,
GitHub Pages. Written from each platform's published API reference (OpenAPI); `VERIFIED` lists the ones checked
against a real account, the others show as beta on the page.

Each platform returns the same shape, so build.py handles them all the same way:

    {"connected", "key", "error"?,
     "sites":     [{"id", "name", "urls", "state": ok|failed|building|paused, "deployed", "repo", "framework", "dashboard"}],
     "databases": [{"id", "name", "engine", "region", "version", "state", "dashboard", "group"}],
     "buckets":   [{"id", "name", "public", "dashboard", "group"}],
     "functions": [{"id", "name", "state", "dashboard", "group"}],
     "domains":   [{"name", "registrar": bool (bought there), "expires", "auto_renew", "dns": bool (DNS there), "records"}]}

A section that fails is {"error": code, "message"} on its own (the others still show). `group` ties the resources of
one Supabase project together. API bases can be redirected for tests: MAXXING_VERCEL_API, MAXXING_NETLIFY_API,
MAXXING_SUPABASE_API (GitHub uses MAXXING_GITHUB_API).
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import httpx

from .providers import TIMEOUT, ProviderError, _key, _section

PLATFORMS = {
    "vercel": {"label": "Vercel", "keys": ("VERCEL_TOKEN", "VERCEL_API_TOKEN"),
               "token_url": "https://vercel.com/account/settings/tokens"},
    "netlify": {"label": "Netlify", "keys": ("NETLIFY_AUTH_TOKEN", "NETLIFY_TOKEN", "NETLIFY_API_TOKEN"),
                "token_url": "https://app.netlify.com/user/applications#personal-access-tokens"},
    "supabase": {"label": "Supabase", "keys": ("SUPABASE_ACCESS_TOKEN", "SUPABASE_TOKEN"),
                 "token_url": "https://supabase.com/dashboard/account/tokens"},
    "github": {"label": "GitHub Pages", "keys": (), "token_url": "https://github.com/settings/personal-access-tokens"},
}
VERIFIED: set[str] = set()                # none seen on a real account with data yet: all beta
SECTIONS = ("sites", "databases", "buckets", "functions", "domains")
MAX_ITEMS = 500


def _api(env: str, default: str) -> str:
    return os.environ.get(env, default).rstrip("/")


class _Client:
    def __init__(self, base: str, token: str, label: str):
        self.base, self.label = base, label
        self.c = httpx.Client(timeout=TIMEOUT, headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                                                        "User-Agent": "harness-maxxing"})

    def get(self, path: str, params: dict | None = None) -> Any:
        r = self.c.get(self.base + path, params=params)
        if r.status_code in (401, 403):
            raise ProviderError("missing_permission", f"the {self.label} token is refused for this")
        if r.status_code == 404:
            raise ProviderError("not_found", f"{self.label}: not found")
        if r.status_code >= 400:
            raise ProviderError("api_error", f"{self.label} answered {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise ProviderError("bad_response", f"{self.label} answered something that is not JSON") from None

    def close(self) -> None:
        self.c.close()


def _run(out: dict, jobs: dict[str, Callable[[], Any]]) -> dict:
    with ThreadPoolExecutor(max_workers=len(jobs) or 1) as ex:
        futs = {k: ex.submit(_section, fn) for k, fn in jobs.items()}
        for k, f in futs.items():
            out[k] = f.result()
    return out


def _host(url: str | None) -> str | None:
    if not url:
        return None
    return url.split("://")[-1].split("/")[0].lower() or None


# ---- Vercel ---------------------------------------------------------------------------------------
VERCEL_STATE = {"READY": "ok", "ERROR": "failed", "CANCELED": "failed", "BUILDING": "building", "QUEUED": "building",
                "INITIALIZING": "building", "BLOCKED": "failed"}


def vercel() -> dict:
    name, token = _key(PLATFORMS["vercel"]["keys"])
    if not token:
        return {"connected": False, "key": None}
    c = _Client(_api("MAXXING_VERCEL_API", "https://api.vercel.com"), token, "Vercel")
    out: dict[str, Any] = {"connected": True, "key": name}
    try:                                      # personal scope + every team the token sees
        teams = [None] + [t for t in (c.get("/v2/teams", {"limit": 20}).get("teams") or []) if t.get("id")]
    except (ProviderError, httpx.HTTPError):  # an odd token (a newline in it) is an httpx error naming its header
        teams = [None]

    def pages(path: str, field: str, team: dict | None) -> list:
        items, params = [], {"limit": 100}
        if team:
            params["teamId"] = team["id"]
        while len(items) < MAX_ITEMS:
            body = c.get(path, params)
            batch = body.get(field) or []
            items += batch
            nxt = (body.get("pagination") or {}).get("next")
            if not nxt or not batch or nxt == params.get("until"):   # an empty page or the same cursor: done
                break
            params["until"] = nxt
        return items

    def sites():
        res = []
        for team in teams:
            slug = (team or {}).get("slug")
            for p in pages("/v10/projects", "projects", team):
                prod = (p.get("targets") or {}).get("production") or {}
                latest = prod or next(iter(p.get("latestDeployments") or []), {})
                hosts = [a.get("domain") for a in p.get("alias") or [] if a.get("domain") and a.get("target") in (None, "PRODUCTION")
                         and not a.get("redirect")]
                hosts += [h for h in prod.get("alias") or [] if isinstance(h, str)]
                custom = [h for h in dict.fromkeys(hosts) if not h.endswith(".vercel.app")]
                default = [h for h in dict.fromkeys(hosts) if h.endswith(".vercel.app")][:1]
                link = p.get("link") or {}
                repo = f"{link.get('org')}/{link.get('repo')}" if link.get("type", "").startswith("github") and link.get("org") else None
                res.append({"id": p["id"], "name": p.get("name") or p["id"], "urls": [f"https://{h}/" for h in custom + default],
                            "state": VERCEL_STATE.get(latest.get("readyState") or "", "ok" if latest else "unknown"),
                            "deployed": int(latest["createdAt"] / 1000) if latest.get("createdAt") else None,
                            "repo": repo, "framework": p.get("framework"), "team": slug,
                            "dashboard": f"https://vercel.com/{slug or 'dashboard'}/{p.get('name')}" if slug else "https://vercel.com/dashboard"})
        return res

    def domains():
        res = []
        for team in teams:
            for d in pages("/v5/domains", "domains", team):
                res.append({"name": d["name"], "registrar": bool(d.get("boughtAt")),
                            "expires": int(d["expiresAt"] / 1000) if d.get("expiresAt") else None, "auto_renew": d.get("renew"),
                            "dns": d.get("serviceType") == "zeit.world", "name_servers": d.get("nameservers") or []})
        return res
    try:
        return _run(out, {"sites": sites, "domains": domains})
    finally:
        c.close()


# ---- Netlify --------------------------------------------------------------------------------------
NETLIFY_STATE = {"ready": "ok", "error": "failed", "building": "building", "enqueued": "building", "processing": "building",
                 "uploading": "building", "preparing": "building", "new": "building"}


def netlify() -> dict:
    name, token = _key(PLATFORMS["netlify"]["keys"])
    if not token:
        return {"connected": False, "key": None}
    c = _Client(_api("MAXXING_NETLIFY_API", "https://api.netlify.com/api/v1"), token, "Netlify")
    out: dict[str, Any] = {"connected": True, "key": name}

    def sites():
        res, page = [], 1
        while len(res) < MAX_ITEMS:
            batch = c.get("/sites", {"page": page, "per_page": 100, "filter": "all"})
            if not isinstance(batch, list) or not batch:
                break
            for s in batch:
                hosts = [s.get("custom_domain"), *(s.get("domain_aliases") or [])]
                urls = [f"https://{h}/" for h in hosts if h] + ([s["ssl_url"].rstrip("/") + "/"] if s.get("ssl_url") else [])
                dep = s.get("published_deploy") or {}
                bs = s.get("build_settings") or {}
                repo = None
                if "github.com" in (bs.get("repo_url") or ""):
                    repo = bs["repo_url"].split("github.com/")[-1].removesuffix(".git").strip("/")
                elif bs.get("provider") == "github" and bs.get("repo_path"):
                    repo = bs["repo_path"]
                res.append({"id": s["id"], "name": s.get("name") or s["id"], "urls": list(dict.fromkeys(urls)),
                            "state": NETLIFY_STATE.get(dep.get("state") or "", "ok" if dep else "unknown"),
                            "deployed": dep.get("published_at") or dep.get("created_at"), "repo": repo,
                            "dashboard": s.get("admin_url")})
            if len(batch) < 100:
                break
            page += 1
        return res

    def domains():
        res = []
        for z in c.get("/dns_zones") or []:
            recs = [{"type": r.get("type"), "name": r.get("hostname"), "content": r.get("value")}
                    for r in z.get("records") or [] if r.get("type") in ("A", "AAAA", "CNAME", "NETLIFY")]
            res.append({"name": z.get("name") or z.get("domain"), "registrar": False, "dns": True,
                        "name_servers": z.get("dns_servers") or [], "records": recs})
        return [d for d in res if d["name"]]
    try:
        return _run(out, {"sites": sites, "domains": domains})
    finally:
        c.close()


# ---- Supabase -------------------------------------------------------------------------------------
SUPABASE_STATE = {"ACTIVE_HEALTHY": "ok", "ACTIVE_UNHEALTHY": "failed", "INACTIVE": "paused", "COMING_UP": "building",
                  "RESTORING": "building", "UPGRADING": "building", "GOING_DOWN": "building", "INIT_FAILED": "failed",
                  "REMOVED": "failed", "UNKNOWN": "unknown"}


def supabase() -> dict:
    name, token = _key(PLATFORMS["supabase"]["keys"])
    if not token:
        return {"connected": False, "key": None}
    c = _Client(_api("MAXXING_SUPABASE_API", "https://api.supabase.com"), token, "Supabase")
    out: dict[str, Any] = {"connected": True, "key": name, "databases": [], "buckets": [], "functions": []}
    try:
        try:
            projects = c.get("/v1/projects")
        except (ProviderError, httpx.HTTPError) as e:
            err = e.as_dict() if isinstance(e, ProviderError) else {"error": "unreachable", "message": type(e).__name__}
            return {**out, "databases": err, "buckets": err, "functions": err}
        projects = [p for p in projects or [] if p.get("status") != "REMOVED"][:100]

        def one(p):
            ref = p.get("ref") or p.get("id")
            dash = f"https://supabase.com/dashboard/project/{ref}"
            db = {"id": ref, "name": p.get("name") or ref, "engine": "supabase", "region": p.get("region"),
                  "version": (p.get("database") or {}).get("version"), "state": SUPABASE_STATE.get(p.get("status") or "", "unknown"),
                  "api_url": f"https://{ref}.supabase.co", "dashboard": dash, "group": ref}
            buckets = functions = []
            if db["state"] == "ok":                            # a paused project answers nothing
                try:
                    buckets = [{"id": f"{ref}:{b.get('id') or b.get('name')}", "name": b.get("name"), "public": bool(b.get("public")),
                                "dashboard": f"{dash}/storage/buckets/{b.get('name')}", "group": ref}
                               for b in c.get(f"/v1/projects/{ref}/storage/buckets") or []]
                except (ProviderError, httpx.HTTPError):
                    buckets = []
                try:
                    functions = [{"id": f"{ref}:{f.get('slug')}", "name": f.get("name") or f.get("slug"),
                                  "state": "ok" if f.get("status") == "ACTIVE" else "failed",
                                  "url": f"https://{ref}.supabase.co/functions/v1/{f.get('slug')}",
                                  "dashboard": f"{dash}/functions/{f.get('slug')}", "group": ref}
                                 for f in c.get(f"/v1/projects/{ref}/functions") or [] if f.get("status") != "REMOVED"]
                except (ProviderError, httpx.HTTPError):
                    functions = []
            return db, buckets, functions
        with ThreadPoolExecutor(max_workers=6) as ex:
            for db, bs, fs in ex.map(one, projects):
                out["databases"].append(db)
                out["buckets"] += bs
                out["functions"] += fs
        return out
    finally:
        c.close()


# ---- GitHub Pages ---------------------------------------------------------------------------------
GH_PAGES_STATE = {"built": "ok", "errored": "failed", "building": "building"}


def github_pages() -> dict:
    from .. import gitview
    toks = gitview.tokens()
    if not toks:
        return {"connected": False, "key": None}
    out: dict[str, Any] = {"connected": True, "key": toks[0][0]}
    base = gitview.github_api()

    def sites():
        found: dict[str, tuple[dict, str]] = {}
        errors = 0
        for _label, tok in toks:
            c = _Client(base, tok, "GitHub")
            c.c.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
            try:
                page = 1
                while page <= 5:
                    batch = c.get("/user/repos", {"per_page": 100, "page": page, "sort": "pushed"})
                    for r in batch or []:
                        if r.get("has_pages") and r["full_name"].lower() not in found:
                            found[r["full_name"].lower()] = (r, tok)
                    if len(batch or []) < 100:
                        break
                    page += 1
            except (ProviderError, httpx.HTTPError):
                errors += 1
            finally:
                c.close()
        if errors and errors == len(toks):
            raise ProviderError("missing_permission", "no GitHub token could list its repositories")

        def one(item):
            r, tok = item
            c = _Client(base, tok, "GitHub")
            c.c.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
            try:
                p = c.get(f"/repos/{r['full_name']}/pages")
            except (ProviderError, httpx.HTTPError):
                p = {}
            finally:
                c.close()
            url = p.get("html_url") or f"https://{r['owner']['login'].lower()}.github.io/{r['name']}/"
            urls = [url if url.endswith("/") else url + "/"]
            if p.get("cname") and p["cname"] not in urls[0]:
                urls.insert(0, f"https://{p['cname']}/")
            return {"id": r["full_name"], "name": r["full_name"], "urls": urls,
                    "state": GH_PAGES_STATE.get(p.get("status") or "", "ok" if p else "unknown"),
                    "deployed": r.get("pushed_at"), "repo": r["full_name"],
                    "dashboard": f"https://github.com/{r['full_name']}/settings/pages"}
        with ThreadPoolExecutor(max_workers=6) as ex:
            return list(ex.map(one, list(found.values())[:100]))
    return _run(out, {"sites": sites})


READERS: dict[str, Callable[[], dict]] = {"vercel": vercel, "netlify": netlify, "supabase": supabase, "github": github_pages}


def read_all() -> dict[str, dict]:
    def safe(fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - one platform never breaks the refresh
            # only our own messages are kept: any other error text may quote a request (its URL or token header)
            msg = f"{type(e).__name__}: {e}" if isinstance(e, ProviderError) else type(e).__name__
            return {"connected": True, "key": None, "error": msg[:200]}
    with ThreadPoolExecutor(max_workers=len(READERS)) as ex:
        futs = {k: ex.submit(safe, fn) for k, fn in READERS.items()}
        return {k: f.result() for k, f in futs.items()}


def source_state(data: dict[str, dict]) -> dict[str, dict]:
    out = {}
    for pid, d in data.items():
        meta = PLATFORMS[pid]
        s = {"connected": bool(d.get("connected")), "key": d.get("key"), "error": d.get("error"), "label": meta["label"],
             "beta": pid not in VERIFIED, "token_url": meta["token_url"], "keys": list(meta["keys"])}
        if d.get("connected") and not d.get("error"):
            s["sections"] = {k: (d[k].get("error") if isinstance(d[k], dict) else "ok") for k in SECTIONS if k in d}
        out[pid] = s
    return out
