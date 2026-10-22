"""Infra providers read through their APIs with keys of the vault (read-only calls only):

- Cloudflare (CLOUDFLARE_API_TOKEN or CF_API_TOKEN, account CLOUDFLARE_ACCOUNT_ID or the token's first account):
  zones, DNS records, Workers (+ custom domains, routes, workers.dev subdomain), Pages, R2 (+ public domains), D1,
  Registrar domains.
- Hostinger (HOSTINGER_API_TOKEN): domains portfolio, VPS, DNS zones. One write, only on a click (Connect):
  hostinger_add_ssh_key() puts the Harness public key in a VPS' root authorized_keys.
- RDAP (no key): expiry date of a domain whose registrar is not connected.

Every section is fetched on its own: a token without one permission gives {"error": "missing_permission"} for that
section only. API bases can be redirected for tests: MAXXING_CLOUDFLARE_API, MAXXING_HOSTINGER_API, MAXXING_RDAP_API.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import httpx

CF_TOKEN_KEYS = ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN", "CLOUDFLARE_TOKEN")
CF_ACCOUNT_KEYS = ("CLOUDFLARE_ACCOUNT_ID", "CF_ACCOUNT_ID")
HOSTINGER_KEYS = ("HOSTINGER_API_TOKEN", "HOSTINGER_TOKEN")
TIMEOUT = 15


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message

    def as_dict(self) -> dict:
        return {"error": self.code, "message": self.message}


def _key(names: tuple[str, ...]) -> tuple[str | None, str | None]:
    from .. import vault
    for n in names:
        v = (vault.get(n) or "").strip()
        if v:
            return n, v
    return None, None


# what a network call or an undocumented answer can raise besides ProviderError
_ODD = (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError)


def _section(fn, *args) -> Any:
    try:
        return fn(*args)
    except ProviderError as e:
        return e.as_dict()
    except httpx.HTTPError as e:
        return {"error": "unreachable", "message": type(e).__name__}
    except (ValueError, KeyError, TypeError, AttributeError) as e:   # an answer that is not what the API documents
        return {"error": "bad_answer", "message": type(e).__name__}


# ---- Cloudflare -------------------------------------------------------------------------------------
def cf_api() -> str:
    return os.environ.get("MAXXING_CLOUDFLARE_API", "https://api.cloudflare.com/client/v4").rstrip("/")


class _CF:
    def __init__(self, token: str):
        self.c = httpx.Client(timeout=TIMEOUT, headers={"Authorization": f"Bearer {token}", "User-Agent": "harness-maxxing"})

    def get(self, path: str, params: dict | None = None) -> Any:
        r = self.c.get(cf_api() + path, params=params)
        try:
            body = r.json()
        except ValueError:
            raise ProviderError("bad_response", f"Cloudflare answered {r.status_code}") from None
        if r.status_code in (401, 403) or (not body.get("success") and any(e.get("code") in (10000, 9109, 10001)
                                                                            for e in body.get("errors") or [])):
            raise ProviderError("missing_permission", "the Cloudflare token has no read access to this")
        if not body.get("success"):
            msg = "; ".join(str(e.get("message")) for e in body.get("errors") or []) or f"HTTP {r.status_code}"
            raise ProviderError("api_error", msg[:200])
        return body

    def all(self, path: str, per_page: int = 100, limit: int = 2000) -> list:
        out, page = [], 1
        while len(out) < limit:
            body = self.get(path, {"page": page, "per_page": per_page})
            res = body.get("result") or []
            out += res
            info = body.get("result_info") or {}
            if not res or page >= (info.get("total_pages") or 1):
                return out
            page += 1
        return out


def cloudflare() -> dict:
    name, token = _key(CF_TOKEN_KEYS)
    if not token:
        return {"connected": False, "key": None}
    cf = _CF(token)
    out: dict[str, Any] = {"connected": True, "key": name}
    _, acct = _key(CF_ACCOUNT_KEYS)
    if not acct:
        try:
            accts = cf.get("/accounts").get("result") or []
            acct = accts[0]["id"] if accts else None
        except ProviderError as e:
            out["error"] = e.message
            return out
        except _ODD as e:
            out["error"] = f"Cloudflare unreachable or odd answer ({type(e).__name__})"
            return out
    if not acct:
        out["error"] = "no Cloudflare account visible with this token"
        return out
    out["account_id"] = acct
    a = f"/accounts/{acct}"

    def zones():
        zs = cf.all("/zones", 50)
        return [{"id": z["id"], "name": z["name"], "status": z.get("status"), "plan": (z.get("plan") or {}).get("name"),
                 "name_servers": z.get("name_servers") or [], "original_registrar": z.get("original_registrar")} for z in zs]

    def workers():
        scripts = cf.get(a + "/workers/scripts").get("result") or []
        return [{"name": s["id"], "modified": s.get("modified_on"), "created": s.get("created_on"),
                 "routes": [r.get("pattern") for r in s.get("routes") or [] if r.get("pattern")]} for s in scripts]

    def worker_domains():
        return [{"hostname": d["hostname"], "service": d.get("service"), "zone": d.get("zone_name")}
                for d in cf.get(a + "/workers/domains").get("result") or []]

    def worker_subdomain():
        return (cf.get(a + "/workers/subdomain").get("result") or {}).get("subdomain")

    def pages():
        ps = cf.all(a + "/pages/projects", 10, 500)
        return [{"name": p["name"], "subdomain": p.get("subdomain"), "domains": p.get("domains") or [],
                 "branch": p.get("production_branch"),
                 "repo": ((p.get("source") or {}).get("config") or {}).get("repo_name"),
                 "owner": ((p.get("source") or {}).get("config") or {}).get("owner"),
                 "deployed": ((p.get("latest_deployment") or {}).get("created_on")),
                 "status": (((p.get("latest_deployment") or {}).get("latest_stage") or {}).get("status"))} for p in ps]

    def r2():
        bs = (cf.get(a + "/r2/buckets").get("result") or {}).get("buckets") or []

        def one(b):
            item = {"name": b["name"], "created": b.get("creation_date"), "location": b.get("location"), "public": []}
            try:
                for d in (cf.get(f"{a}/r2/buckets/{b['name']}/domains/custom").get("result") or {}).get("domains") or []:
                    if d.get("enabled", True):
                        item["public"].append("https://" + d["domain"])
                m = cf.get(f"{a}/r2/buckets/{b['name']}/domains/managed").get("result") or {}
                if m.get("enabled") and m.get("domain"):
                    item["public"].append("https://" + m["domain"])
            except (ProviderError, *_ODD):
                pass
            return item
        with ThreadPoolExecutor(max_workers=6) as ex:
            return list(ex.map(one, bs))

    def d1():
        return [{"name": d["name"], "uuid": d.get("uuid"), "size": d.get("file_size"), "tables": d.get("num_tables"),
                 "created": d.get("created_at")} for d in cf.all(a + "/d1/database", 100)]

    def registrar():
        return [{"name": d.get("name") or d.get("id"), "expires": d.get("expires_at"), "auto_renew": d.get("auto_renew"),
                 "locked": d.get("locked")} for d in cf.get(a + "/registrar/domains").get("result") or []]

    jobs = {"zones": zones, "workers": workers, "worker_domains": worker_domains, "worker_subdomain": worker_subdomain,
            "pages": pages, "r2": r2, "d1": d1, "registrar": registrar}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {k: ex.submit(_section, fn) for k, fn in jobs.items()}
        for k, f in futs.items():
            out[k] = f.result()
    zl = out.get("zones")
    if isinstance(zl, list):
        def dns(z):
            try:
                recs = cf.all(f"/zones/{z['id']}/dns_records", 500, 5000)
                z["dns"] = [{"type": r["type"], "name": r["name"], "content": r.get("content"), "proxied": r.get("proxied")}
                            for r in recs if r.get("type") in ("A", "AAAA", "CNAME")]
            except ProviderError as e:
                z["dns_error"] = e.code
            except _ODD:
                z["dns_error"] = "unreachable"
            try:
                z["worker_routes"] = [{"pattern": r.get("pattern"), "script": r.get("script")}
                                      for r in cf.get(f"/zones/{z['id']}/workers/routes").get("result") or []]
            except (ProviderError, *_ODD):
                z["worker_routes"] = []
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(dns, zl))
    cf.c.close()
    return out


# ---- Hostinger --------------------------------------------------------------------------------------
def hostinger_api() -> str:
    return os.environ.get("MAXXING_HOSTINGER_API", "https://developers.hostinger.com").rstrip("/")


def hostinger() -> dict:
    name, token = _key(HOSTINGER_KEYS)
    if not token:
        return {"connected": False, "key": None}
    c = httpx.Client(timeout=TIMEOUT, headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                                                "User-Agent": "harness-maxxing"})

    def get(path: str) -> Any:
        r = c.get(hostinger_api() + path)
        if r.status_code in (401, 403):
            raise ProviderError("missing_permission", "the Hostinger token is refused for this")
        if r.status_code >= 400:
            raise ProviderError("api_error", f"Hostinger answered {r.status_code}")
        return r.json()

    def domains():
        return [{"name": d.get("domain"), "status": d.get("status"), "expires": d.get("expires_at"), "type": d.get("type")}
                for d in get("/api/domains/v1/portfolio") if d.get("domain")]

    def vps():
        return [{"id": v.get("id"), "hostname": v.get("hostname"), "state": v.get("state"), "plan": v.get("plan"),
                 "cpus": v.get("cpus"), "memory_mb": v.get("memory"), "disk_mb": v.get("disk"),
                 "ips": [i.get("address") for i in (v.get("ipv4") or []) + (v.get("ipv6") or []) if i.get("address")],
                 "os": (v.get("template") or {}).get("name")} for v in get("/api/vps/v1/virtual-machines")]

    out: dict[str, Any] = {"connected": True, "key": name}
    out["domains"] = _section(domains)
    out["vps"] = _section(vps)
    if isinstance(out["domains"], list):
        def zone(d):
            if d.get("status") not in (None, "active"):
                return
            try:
                recs = get(f"/api/dns/v1/zones/{d['name']}")
                d["dns"] = [{"type": r.get("type"), "name": _fqdn(r.get("name"), d["name"]), "content": x.get("content")}
                            for r in recs if r.get("type") in ("A", "AAAA", "CNAME")
                            for x in r.get("records") or [] if not x.get("is_disabled")]
            except (ProviderError, *_ODD):
                d["dns_error"] = "unavailable"
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(zone, out["domains"]))
    c.close()
    return out


def _hostinger_call(method: str, path: str, json_body: Any = None) -> Any:
    _, token = _key(HOSTINGER_KEYS)
    if not token:
        raise ProviderError("no_key", "no Hostinger key in the vault (HOSTINGER_API_TOKEN)")
    r = httpx.request(method, hostinger_api() + path, json=json_body, timeout=TIMEOUT,
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "harness-maxxing"})
    if r.status_code in (401, 403):
        raise ProviderError("missing_permission", "the Hostinger token is refused for this")
    if r.status_code >= 400:
        raise ProviderError("api_error", f"Hostinger answered {r.status_code}")
    d = r.json()
    return d.get("data", d) if isinstance(d, dict) else d


def hostinger_ssh_keys(vm_id: int | str) -> list[str]:
    """The public keys of the VPS' root user (`<type> <data>`, without the comment)."""
    return [f"{k.get('type')} {k.get('data')}" for k in _hostinger_call("GET", f"/api/vps/v1/virtual-machines/{vm_id}/ssh-keys")
            if isinstance(k, dict) and k.get("data")]


def hostinger_add_ssh_key(vm_id: int | str, public_key: str) -> None:
    _hostinger_call("POST", f"/api/vps/v1/virtual-machines/{vm_id}/ssh-keys", {"keys": [public_key.strip()]})


def _fqdn(name: str | None, domain: str) -> str:
    n = (name or "@").strip(".")
    return domain if n in ("@", "") else (n if n.endswith(domain) else f"{n}.{domain}")


# ---- RDAP -------------------------------------------------------------------------------------------
def rdap_api() -> str:
    return os.environ.get("MAXXING_RDAP_API", "https://rdap.org").rstrip("/")


RDAP_MAX_BYTES = 1 << 20        # a real answer is a few KiB
RDAP_TOTAL_S = 15.0             # the whole lookup, redirects included (httpx timeouts are per read)
RDAP_MAX_REDIRECTS = 3          # rdap.org sends to the registry's server: https only, and only a few hops


def _rdap_get(url: str) -> tuple[int, bytes]:
    """GET with a total deadline, a capped body and a few https-only redirects. Raises httpx.HTTPError or ValueError."""
    deadline = time.monotonic() + RDAP_TOTAL_S
    with httpx.Client(timeout=httpx.Timeout(5, connect=3), follow_redirects=False,
                      headers={"Accept": "application/rdap+json", "User-Agent": "harness-maxxing"}) as c:
        for _ in range(RDAP_MAX_REDIRECTS + 1):
            left = deadline - time.monotonic()               # the deadline also covers the redirects' requests
            if left <= 0:
                raise ValueError("RDAP answer too slow")
            with c.stream("GET", url, timeout=httpx.Timeout(min(5, left), connect=min(3, left))) as r:
                if r.is_redirect:
                    nxt = r.url.join(r.headers.get("location", ""))
                    if nxt.scheme != "https":
                        raise ValueError("RDAP redirect to a non-https address")
                    url = str(nxt)
                    continue
                if r.status_code != 200:
                    return r.status_code, b""
                if int(r.headers.get("content-length") or 0) > RDAP_MAX_BYTES:
                    raise ValueError("RDAP answer too large")
                body = bytearray()
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > RDAP_MAX_BYTES:
                        raise ValueError("RDAP answer too large")
                    if time.monotonic() > deadline:
                        raise ValueError("RDAP answer too slow")
                return 200, bytes(body)
    raise ValueError("too many RDAP redirects")


def rdap_expiry(domain: str) -> dict:
    """{"expires": iso | None, "registrar": str | None} from the public RDAP service (no key)."""
    try:
        code, raw = _rdap_get(f"{rdap_api()}/domain/{domain}")
        if code == 429 or code >= 500:
            return {"expires": None, "registrar": None, "checked": int(time.time()), "error": "unreachable"}
        if code != 200:
            return {"expires": None, "registrar": None, "checked": int(time.time())}
        body = json.loads(raw)
    except (httpx.HTTPError, ValueError):
        return {"expires": None, "registrar": None, "checked": int(time.time()), "error": "unreachable"}
    if not isinstance(body, dict):                       # answered, but not an RDAP object
        return {"expires": None, "registrar": None, "checked": int(time.time()), "error": "bad_answer"}
    try:                                                 # an odd answer (list, short vCard...) never stops a refresh
        exp = next((e.get("eventDate") for e in body.get("events") or [] if e.get("eventAction") == "expiration"), None)
        reg = None
        for ent in body.get("entities") or []:
            if "registrar" in (ent.get("roles") or []):
                for item in ((ent.get("vcardArray") or [None, []])[1] or []):
                    if isinstance(item, list) and len(item) > 3 and item[0] == "fn":
                        reg = item[3]
    except (AttributeError, IndexError, KeyError, TypeError):
        return {"expires": None, "registrar": None, "checked": int(time.time()), "error": "bad_answer"}
    if exp is not None and not _iso_date(exp):           # NaN, 1e999, a word: kept, it broke every Infra build
        return {"expires": None, "registrar": None, "checked": int(time.time()), "error": "bad_answer"}
    if not (isinstance(reg, str) and len(reg) <= 200):
        reg = None
    return {"expires": exp, "registrar": reg, "checked": int(time.time())}


def _iso_date(v: object) -> bool:
    if not isinstance(v, str) or len(v) > 40:
        return False
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def cf_point(host: str, ip: str) -> dict:
    """Make `host` point to `ip` (A or AAAA record, DNS only - Caddy gets its own certificate) when its zone is on
    Cloudflare and the token may edit DNS. {"done": bool, "message": str}."""
    _, token = _key(CF_TOKEN_KEYS)
    if not token:
        return {"done": False, "message": "no Cloudflare key in the vault"}
    cf = _CF(token)
    try:
        zones = cf.all("/zones", 50)
        zone = next((z for z in sorted(zones, key=lambda z: -len(z["name"])) if host == z["name"] or host.endswith("." + z["name"])), None)
        if not zone:
            return {"done": False, "message": f"{host} is not in a Cloudflare zone of this account"}
        rtype = "AAAA" if ":" in ip else "A"
        recs = cf.get(f"/zones/{zone['id']}/dns_records", {"name": host}).get("result") or []
        if any(r["type"] == rtype and r.get("content") == ip for r in recs):
            return {"done": True, "message": f"{host} already points to {ip}"}
        if any(r["type"] in ("A", "AAAA", "CNAME") for r in recs):
            return {"done": False, "message": f"{host} already has a DNS record pointing elsewhere: change it on purpose"}
        r = cf.c.post(f"{cf_api()}/zones/{zone['id']}/dns_records",
                      json={"type": rtype, "name": host, "content": ip, "proxied": False, "ttl": 1,
                            "comment": "maxxing infra site add"})
        body = r.json()
        if not body.get("success"):
            if r.status_code in (401, 403) or any(e.get("code") in (10000, 9109) for e in body.get("errors") or []):
                return {"done": False, "message": "the Cloudflare token may not edit DNS (permission Zone -> DNS -> Edit)"}
            return {"done": False, "message": "; ".join(str(e.get("message")) for e in body.get("errors") or [])[:200]}
        return {"done": True, "message": f"{rtype} record {host} -> {ip} created on Cloudflare"}
    except ProviderError as e:
        return {"done": False, "message": e.message}
    except (httpx.HTTPError, ValueError) as e:
        return {"done": False, "message": f"Cloudflare unreachable: {type(e).__name__}"}
    finally:
        cf.c.close()
