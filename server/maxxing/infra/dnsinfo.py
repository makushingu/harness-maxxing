"""Public DNS, no key: where a domain's DNS is served and who hosts each address, for every registrar and host.

Resolved over DNS-over-HTTPS (JSON API, MAXXING_DOH_API, default Cloudflare's resolver), cached in
`<state>/infra/dns.json` for DNS_TTL_S, at most PER_REFRESH names a refresh. The name servers say who serves the DNS
(`dns_provider`), the CNAME chain and A records say who hosts the address (`hosted_by`): Vercel, Netlify, GitHub Pages,
Shopify... or one of our servers (matched by IP in build.py).
"""
from __future__ import annotations

import ipaddress
import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

DNS_TTL_S = 6 * 3600
PER_REFRESH = 80
TYPES = {"A": 1, "AAAA": 28, "CNAME": 5, "NS": 2}

# name server suffix -> DNS provider
NS_PROVIDERS = [
    ("ns.cloudflare.com", "cloudflare"), ("dns-parking.com", "hostinger"), ("hostinger.", "hostinger"),
    ("ovh.net", "ovh"), ("ovh.ca", "ovh"), ("anycast.me", "ovh"), ("gandi.net", "gandi"),
    ("registrar-servers.com", "namecheap"), ("domaincontrol.com", "godaddy"), ("ui-dns.", "ionos"),
    ("awsdns", "aws"), ("googledomains.com", "google"), ("vercel-dns.com", "vercel"), ("nsone.net", "netlify"),
    ("porkbun.com", "porkbun"), ("wixdns.net", "wix"), ("o2switch.net", "o2switch"), ("infomaniak.", "infomaniak"),
    ("digitalocean.com", "digitalocean"), ("hetzner.", "hetzner"), ("name.com", "name.com"), ("dnsimple.com", "dnsimple"),
    ("azure-dns.", "azure"), ("vultr.com", "vultr"), ("linode.com", "linode"), ("squarespacedns.com", "squarespace"),
]
# CNAME suffix -> host
CNAME_HOSTS = [
    ("vercel-dns.com", "vercel"), (".vercel.app", "vercel"), (".netlify.app", "netlify"), (".netlify.com", "netlify"),
    (".github.io", "github"), (".pages.dev", "cloudflare"), ("myshopify.com", "shopify"), ("webflow.com", "webflow"),
    ("squarespace.com", "squarespace"), ("wixdns.net", "wix"), (".supabase.co", "supabase"), (".onrender.com", "render"),
    (".up.railway.app", "railway"), (".fly.dev", "fly"), (".web.app", "firebase"), (".firebaseapp.com", "firebase"),
    ("herokudns.com", "heroku"), (".ghost.io", "ghost"), (".azurewebsites.net", "azure"), ("cloudfront.net", "aws"),
    (".amplifyapp.com", "aws"), ("hostingersite.com", "hostinger"),
]
# address -> host
IP_HOSTS = [(ipaddress.ip_network(n), h) for n, h in (
    ("76.76.21.0/24", "vercel"), ("216.198.79.0/24", "vercel"), ("75.2.60.5/32", "netlify"), ("99.83.231.61/32", "netlify"),
    ("185.199.108.0/22", "github"), ("23.227.38.0/24", "shopify"), ("198.185.159.0/24", "squarespace"),
    ("198.49.23.0/24", "squarespace"), ("185.230.63.0/24", "wix"), ("199.36.158.100/32", "firebase"),
)]


def doh_api() -> str:
    return os.environ.get("MAXXING_DOH_API", "https://cloudflare-dns.com/dns-query").rstrip("/")


def _query(c: httpx.Client, name: str, rtype: str) -> list[dict]:
    r = c.get(doh_api(), params={"name": name, "type": rtype}, headers={"Accept": "application/dns-json"})
    if r.status_code >= 400:
        raise httpx.HTTPError(f"DoH {r.status_code}")
    body = r.json()
    if not isinstance(body, dict) or not isinstance(body.get("Answer") or [], list):
        raise ValueError("bad_answer")
    return [a for a in body.get("Answer") or [] if isinstance(a, dict) and isinstance(a.get("data"), str)]


def resolve(name: str, apex: bool) -> dict:
    """{"ns": [...] (apex only), "cname": [...] chain, "a": [...], "checked": ts} or {"error", "checked"}."""
    out: dict = {"checked": int(time.time())}
    try:
        with httpx.Client(timeout=8) as c:
            if apex:
                out["ns"] = sorted({a["data"].rstrip(".").lower() for a in _query(c, name, "NS") if a.get("type") == TYPES["NS"]})
            ans = _query(c, name, "A") + _query(c, name, "AAAA")
    except (httpx.HTTPError, ValueError) as e:
        return {"error": str(e)[:120] or type(e).__name__, "checked": out["checked"]}
    out["cname"] = list(dict.fromkeys(a["data"].rstrip(".").lower() for a in ans if a.get("type") == TYPES["CNAME"]))
    out["a"] = sorted({a["data"] for a in ans if a.get("type") in (TYPES["A"], TYPES["AAAA"])})
    return out


def dns_provider(ns: list[str]) -> str | None:
    for n in ns or []:
        for suffix, p in NS_PROVIDERS:
            if suffix in n:
                return p
    return "other" if ns else None


def hosted_by(info: dict) -> str | None:
    """The platform behind an address, from its CNAME chain then its IPs (our own servers are matched in build.py)."""
    for cn in info.get("cname") or []:
        for suffix, h in CNAME_HOSTS:
            if cn.endswith(suffix.lstrip(".")) or suffix in cn:
                return h
    from .build import behind_cloudflare
    for ip in info.get("a") or []:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        for net, h in IP_HOSTS:
            if a.version == net.version and a in net:
                return h
    if info.get("a") and all(behind_cloudflare(ip) for ip in info["a"]):
        return "cloudflare"                              # proxied: the origin is hidden
    return None


def refresh_cache(cache: dict, names: list[tuple[str, bool]]) -> dict:
    """Resolve the names (name, is_apex) not checked for DNS_TTL_S, at most PER_REFRESH. Returns the updated cache."""
    now = time.time()
    todo = [(n, ap) for n, ap in names if now - (cache.get(n) or {}).get("checked", 0) > DNS_TTL_S][:PER_REFRESH]
    if todo:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for (n, _), info in zip(todo, ex.map(lambda x: resolve(*x), todo)):
                cache[n] = info
    return cache
