"""Infra -> E-mail (view only): where every address comes from and whether its domain is set up to receive mail.

- the mailboxes of the E-mail page (`maxxing.mail`: address, servers, last check),
- Cloudflare Email Routing (vault token, see providers.py): per zone the routing state and its rules (forwards,
  worker / drop actions, the catch-all), and the account's destination addresses (verified or not),
- Hostinger Email (`/api/mail/v1`): orders, their mailboxes, aliases, forwarders and catch-alls,
- the DNS health of every domain that receives mail (MX, SPF, DKIM on a few common selectors, DMARC) over public
  DNS-over-HTTPS (`dnsinfo.doh_api()`, MAXXING_DOH_API), no key.

Read-only: nothing is created, changed or deleted at a provider (GET calls only). Provider answers are cached
PROVIDERS_TTL_S in `<state>/infra/mail.json`, DNS facts DNS_TTL_S in `<state>/infra/mail-dns.json`; view(refresh=True)
bypasses both. A provider error stays in the payload, never an exception. See docs/dev/API.md#infra.

Next providers with an API (not done yet): Migadu, Purelymail, Zoho Mail, OVHcloud, cPanel (UAPI).
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from .. import config
from . import dnsinfo, providers
from .providers import ProviderError

PROVIDERS_TTL_S = 300
DNS_TTL_S = 3600
ZONE_WORKERS = 4                    # Cloudflare zone calls at once (rate limit: 1200 calls / 5 min)
DOMAIN_WORKERS = 6
MAX_DOMAINS = 60
SPF_MAX_QUERIES = 12                # DNS queries spent following include: / redirect= of one domain
DKIM_SELECTORS = ("google", "selector1", "selector2", "default", "mail", "k1", "cf2024-1", "dkim")

CF_RULES_FIX = "Add the permission Zone → Email Routing Rules → Read for all zones to the Cloudflare token (Settings → Keys)"
CF_ADDR_FIX = "Add the permission Account → Email Routing Addresses → Read to the Cloudflare token (Settings → Keys)"

_ODD = (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError)
_lock = threading.Lock()


def _cache_path():
    return config.state_dir("infra") / "mail.json"


def _dns_path():
    return config.state_dir("infra") / "mail-dns.json"


def _err(e: Exception) -> dict:
    if isinstance(e, ProviderError):
        return {"error": e.code, "message": e.message}
    if isinstance(e, httpx.HTTPError):
        return {"error": "unreachable", "message": type(e).__name__}
    return {"error": "bad_answer", "message": type(e).__name__}


# ---- E-mail page --------------------------------------------------------------------------------
def mailboxes() -> list[dict]:
    from .. import mail
    out = []
    for acc in mail.list_accounts():
        try:
            p = mail.public(acc)
        except Exception:  # noqa: BLE001 - one odd account never hides the others
            p = acc
        addr = (p.get("address") or "").lower()
        out.append({**{k: p.get(k) for k in ("id", "address", "label", "imap_host", "imap_port", "smtp_host", "smtp_port",
                                             "has_password", "last_check")},
                    "domain": addr.rpartition("@")[2]})
    return out


# ---- Cloudflare Email Routing -------------------------------------------------------------------
def _cf_rule(r: dict) -> dict:
    matchers = [m for m in r.get("matchers") or [] if isinstance(m, dict)]
    actions = [a for a in r.get("actions") or [] if isinstance(a, dict)]
    values = lambda kind: [str(v) for a in actions if a.get("type") == kind for v in (a.get("value") or [])]  # noqa: E731
    return {"name": str(r.get("name") or ""), "enabled": bool(r.get("enabled", True)),
            "catch_all": any(m.get("type") == "all" for m in matchers),
            "from": next((str(m.get("value")).lower() for m in matchers
                          if m.get("type") == "literal" and m.get("field") == "to" and m.get("value")), None),
            "action": next((a.get("type") for a in actions), None),     # forward | worker | drop
            "to": [v.lower() for v in values("forward")], "worker": next(iter(values("worker")), None)}


def cloudflare_mail() -> dict:
    name, token = providers._key(providers.CF_TOKEN_KEYS)
    if not token:
        return {"connected": False, "key": None, "zones": [], "addresses": []}
    out: dict[str, Any] = {"connected": True, "key": name, "zones": [], "addresses": []}
    cf = providers._CF(token)
    try:
        _, acct = providers._key(providers.CF_ACCOUNT_KEYS)
        if not acct:
            accts = cf.get("/accounts").get("result") or []
            acct = accts[0]["id"] if accts else None
        zones = cf.all("/zones", 50)
    except (ProviderError, *_ODD) as e:
        cf.c.close()
        return {**out, **_err(e)}
    if acct:
        try:
            out["addresses"] = sorted(({"email": str(a.get("email") or "").lower(), "verified": bool(a.get("verified")),
                                        "verified_at": a.get("verified")}
                                       for a in cf.all(f"/accounts/{acct}/email/routing/addresses", 50, 1000) if a.get("email")),
                                      key=lambda a: a["email"])
        except (ProviderError, *_ODD) as e:
            out["addresses_error"] = _err(e)["error"]
            if out["addresses_error"] == "missing_permission":
                out["addresses_fix"] = CF_ADDR_FIX

    def zone(z: dict) -> dict:
        item: dict[str, Any] = {"zone": z.get("id"), "name": z.get("name"), "routing": None, "rules": []}
        try:
            try:
                r = cf.get(f"/zones/{z['id']}/email/routing").get("result") or {}
                item["routing"] = {"enabled": bool(r.get("enabled")), "status": r.get("status")}
                if not item["routing"]["enabled"]:
                    return item
            except ProviderError as e:
                # the routing settings need their own permission; the rules (what matters here) may still be readable
                if _err(e).get("error") != "missing_permission":
                    raise
            rules = [_cf_rule(x) for x in cf.all(f"/zones/{z['id']}/email/routing/rules", 50, 500) if isinstance(x, dict)]
            if not any(x["catch_all"] for x in rules):
                try:
                    ca = cf.get(f"/zones/{z['id']}/email/routing/rules/catch_all").get("result") or {}
                    if ca.get("actions"):
                        rules.append({**_cf_rule(ca), "catch_all": True})
                except (ProviderError, *_ODD):
                    pass
            item["rules"] = rules
            if item["routing"] is None:                 # settings unreadable, rules read: routing is on if a rule is
                item["routing"] = {"enabled": any(x.get("enabled") for x in rules), "status": None}
        except (ProviderError, *_ODD) as e:
            item.update(_err(e))
            if item["error"] == "missing_permission":
                item["missing_permission"] = True
        return item

    with ThreadPoolExecutor(max_workers=ZONE_WORKERS) as ex:
        out["zones"] = sorted(ex.map(zone, [z for z in zones if isinstance(z, dict) and z.get("id")]),
                              key=lambda z: str(z.get("name")))
    cf.c.close()
    missing = sum(1 for z in out["zones"] if z.get("missing_permission"))
    if missing:
        out["missing_permission_zones"] = missing
        out["fix"] = CF_RULES_FIX
    return out


# ---- Hostinger Email ----------------------------------------------------------------------------
def _hostinger_paged(path: str, pages: int = 20) -> list[dict]:
    out: list[dict] = []
    for page in range(1, pages + 1):
        got = providers._hostinger_call("GET", f"{path}?page={page}&per_page=100")
        rows = [x for x in got if isinstance(x, dict)] if isinstance(got, list) else []
        out += rows
        if len(rows) < 100:
            break
    return out


def hostinger_mail() -> dict:
    name, token = providers._key(providers.HOSTINGER_KEYS)
    if not token:
        return {"connected": False, "key": None, "orders": []}
    out: dict[str, Any] = {"connected": True, "key": name, "orders": []}
    try:
        orders = _hostinger_paged("/api/mail/v1/orders")
    except (ProviderError, *_ODD) as e:
        return {**out, **_err(e)}

    def one(o: dict) -> dict:
        dom = o.get("domain") if isinstance(o.get("domain"), dict) else {}
        plan = o.get("plan") if isinstance(o.get("plan"), dict) else {}
        item: dict[str, Any] = {"id": str(o.get("id") or ""), "domain": str(dom.get("name") or "").lower() or None,
                                "status": o.get("status"), "plan": plan.get("title") or plan.get("name"),
                                "seats": o.get("seats"), "expires": o.get("expires_at"),
                                "mailboxes": [], "aliases": [], "forwarders": [], "catchalls": []}
        base = f"/api/mail/v1/orders/{item['id']}"
        addr = lambda x: str(((x.get("mailbox") or {}) if isinstance(x.get("mailbox"), dict) else {}).get("address") or "").lower()  # noqa: E731
        try:
            item["mailboxes"] = [{"address": str(m.get("address") or "").lower(), "status": m.get("status"),
                                  "catch_all": bool(m.get("is_catchall"))} for m in _hostinger_paged(base + "/mailboxes")]
            item["aliases"] = [{"address": str(a.get("address") or "").lower(), "to": addr(a),
                                "enabled": bool(a.get("is_active", True))} for a in _hostinger_paged(base + "/aliases")]
            item["forwarders"] = [{"from": addr(f), "to": str(f.get("destination") or "").lower(),
                                   "enabled": bool(f.get("is_active", True)), "confirmed": bool(f.get("is_confirmed")),
                                   "keep_copy": bool(f.get("is_keep_copy_enabled"))} for f in _hostinger_paged(base + "/forwarders")]
            item["catchalls"] = [{"domain": str(c.get("domain") or "").lower(), "to": addr(c),
                                  "enabled": bool(c.get("is_active", True)), "confirmed": bool(c.get("is_confirmed"))}
                                 for c in _hostinger_paged(base + "/catchalls")]
        except (ProviderError, *_ODD) as e:
            item.update(_err(e))
        return item

    with ThreadPoolExecutor(max_workers=4) as ex:
        out["orders"] = list(ex.map(one, orders))
    return out


# ---- routes: address -> where it goes -----------------------------------------------------------
def routes(boxes: list[dict], cf: dict, hs: dict) -> list[dict]:
    """One line per address: {domain, address, via, kind, enabled, account, to: [{address, verified, account}], worker}.
    `account` = id of the E-mail page mailbox with that address (the end of the chain)."""
    acc = {(b.get("address") or "").lower(): b["id"] for b in boxes if b.get("address")}
    verified = {a["email"]: a["verified"] for a in cf.get("addresses") or []}
    out: list[dict] = []

    def add(domain, address, via, kind, enabled=True, to=(), worker=None):
        out.append({"domain": domain, "address": address, "via": via, "kind": kind, "enabled": enabled,
                    "account": acc.get(address), "worker": worker,
                    "to": [{"address": t, "verified": v, "account": acc.get(t)} for t, v in to]})

    for z in cf.get("zones") or []:
        for r in z.get("rules") or []:
            address = f"*@{z['name']}" if r["catch_all"] else r["from"]
            if not address:
                continue
            kind = r["action"] if r["action"] in ("forward", "worker", "drop") else "other"
            add(z["name"], address, "cloudflare", kind, r["enabled"],
                [(t, verified.get(t) if verified else None) for t in r["to"]], r["worker"])
    for o in hs.get("orders") or []:
        for m in o.get("mailboxes") or []:
            add(m["address"].rpartition("@")[2], m["address"], "hostinger", "mailbox", m.get("status") in (None, "active"))
        for a in o.get("aliases") or []:
            add(a["address"].rpartition("@")[2], a["address"], "hostinger", "alias", a["enabled"], [(a["to"], True)])
        for f in o.get("forwarders") or []:
            add(f["from"].rpartition("@")[2], f["from"], "hostinger", "forward", f["enabled"], [(f["to"], f["confirmed"])])
        for c in o.get("catchalls") or []:
            add(c["domain"], f"*@{c['domain']}", "hostinger", "catchall", c["enabled"], [(c["to"], c["confirmed"])])
    out.sort(key=lambda r: (r["domain"], r["address"].startswith("*"), r["address"]))
    return out


# ---- DNS health ---------------------------------------------------------------------------------
def _txt(c: httpx.Client, name: str) -> list[str]:
    out = []
    for a in dnsinfo._query(c, name, "TXT"):
        if a.get("type") != 16:
            continue
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', a["data"])
        out.append("".join(parts) if parts else a["data"])
    return out


def _spf_lookups(c: httpx.Client, record: str, budget: list[int], seen: set[str], depth: int = 0) -> int:
    """DNS lookups an SPF check costs (RFC 7208 limit: 10), following include:/redirect= up to the budget."""
    n = 0
    for term in record.split()[1:]:
        t = term.lstrip("+-~?").lower()
        target = t[8:] if t.startswith("include:") else t[9:] if t.startswith("redirect=") else None
        if target is not None:
            n += 1
            if depth < 4 and target not in seen and budget[0] > 0:
                seen.add(target)
                budget[0] -= 1
                sub = next((x for x in _txt(c, target) if x.lower().startswith("v=spf1")), None)
                if sub:
                    n += _spf_lookups(c, sub, budget, seen, depth + 1)
        elif t in ("a", "mx", "ptr") or t.startswith(("a:", "a/", "mx:", "mx/", "ptr:", "exists:")):
            n += 1
    return n


def dns_facts(domain: str) -> dict:
    """{mx: [{prio, host}], spf: [records], spf_lookups, dmarc: [records], dkim: [selectors found], checked} or
    {error, checked}."""
    out: dict[str, Any] = {"checked": int(time.time())}
    try:
        with httpx.Client(timeout=8) as c:
            mx = []
            for a in dnsinfo._query(c, domain, "MX"):
                if a.get("type") == 15:
                    prio, _, host = a["data"].partition(" ")
                    mx.append({"prio": int(prio) if prio.isdigit() else 0, "host": host.strip().rstrip(".").lower()})
            out["mx"] = sorted(mx, key=lambda m: (m["prio"], m["host"]))
            out["spf"] = [t for t in _txt(c, domain) if t.lower().startswith("v=spf1")]
            out["spf_lookups"] = _spf_lookups(c, out["spf"][0], [SPF_MAX_QUERIES], {domain}) if len(out["spf"]) == 1 else None
            out["dmarc"] = [t for t in _txt(c, f"_dmarc.{domain}") if t.lower().startswith("v=dmarc1")]
            if not out["dmarc"]:        # a subdomain without its own record: receivers apply the parent's (RFC 7489)
                labels = domain.split(".")
                for i in range(1, len(labels) - 1):
                    parent = ".".join(labels[i:])
                    rec = [t for t in _txt(c, f"_dmarc.{parent}") if t.lower().startswith("v=dmarc1")]
                    if rec:
                        out["dmarc_parent"] = {"domain": parent, "records": rec}
                        break
            out["dkim"] = [s for s in DKIM_SELECTORS
                           if any(re.search(r"(^|;)p=[^;]+", t.replace(" ", "")) for t in _txt(c, f"{s}._domainkey.{domain}"))]   # "p=" alone: a revoked key
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        return {"error": str(e)[:120] or type(e).__name__, "checked": out["checked"]}
    return out


def _spf_suggestion(mx_hosts: list[str]) -> str:
    for h in mx_hosts:
        if h.endswith("mx.cloudflare.net"):
            return "v=spf1 include:_spf.mx.cloudflare.net ~all"
        if h.endswith("google.com") or h.endswith("googlemail.com"):
            return "v=spf1 include:_spf.google.com ~all"
        if h.endswith("outlook.com"):
            return "v=spf1 include:spf.protection.outlook.com ~all"
        if "hostinger" in h:
            return "v=spf1 include:_spf.mail.hostinger.com ~all"
    return "v=spf1 mx ~all"


def _p(level: str, code: str, text: str, fix: str = "", **params) -> dict:
    return {"level": level, "code": code, "text": text, "fix": fix, "params": params}


def problems(domain: str, facts: dict, expects: bool, cf_routing: bool, rua: str) -> list[dict]:
    """What is wrong with a domain's mail DNS, in plain words, each with what to do. `expects`: the domain should
    receive mail (routing on, a mailbox, a Hostinger plan); `cf_routing`: Cloudflare Email Routing is on."""
    if facts.get("error"):
        return [_p("warn", "dns_unreachable", f"Public DNS did not answer for {domain} ({facts['error']}).",
                   "Try Refresh in a minute.", domain=domain, error=facts["error"])]
    out: list[dict] = []
    mx = [m["host"] for m in facts.get("mx") or []]
    real = [h for h in mx if h not in ("", ".")]
    if not real:
        if not expects:
            return [_p("info", "no_mail", f"{domain} receives no mail (no MX record).", "", domain=domain)]
        if mx:
            out.append(_p("error", "null_mx", f"{domain} says it takes no mail (null MX record \"0 .\").",
                          "Remove the null MX record and add the MX records of your mail provider.", domain=domain))
        else:
            out.append(_p("error", "no_mx", f"No MX record: mail sent to @{domain} goes nowhere.",
                          "Add the MX records of your mail provider (Cloudflare adds them when Email Routing is turned on for the zone).",
                          domain=domain))
    elif cf_routing and not all(h.endswith("mx.cloudflare.net") for h in real):
        out.append(_p("warn", "mx_not_cloudflare",
                      f"Email Routing is on but the MX records point to {', '.join(real)}: mail may not go through Cloudflare.",
                      "In Cloudflare → Email → Email Routing → Settings, let Cloudflare fix the DNS records (and remove the other MX).",
                      domain=domain, hosts=", ".join(real)))
    spf = facts.get("spf") or []
    suggestion = _spf_suggestion(real)
    if not spf:
        out.append(_p("warn", "no_spf", f"No SPF record: anyone can claim to send mail as @{domain}.",
                      f"Add a TXT record on {domain}: {suggestion}", domain=domain, record=suggestion))
    elif len(spf) > 1:
        out.append(_p("error", "multiple_spf", f"{len(spf)} SPF records on {domain}: receivers treat that as an error.",
                      "Merge them into one TXT record that starts with v=spf1.", domain=domain, count=len(spf)))
    else:
        rec = spf[0].lower()            # SPF terms are case-insensitive (RFC 7208)
        if re.search(r"(^|\s)\+?all(\s|$)", rec):
            out.append(_p("error", "spf_all", f"The SPF record of {domain} ends with +all: anyone may send as @{domain}.",
                          "End it with ~all (or -all).", domain=domain))
        elif re.search(r"(^|\s)\?all(\s|$)", rec) or not re.search(r"(^|\s)[~-]all(\s|$)|(^|\s)redirect=", rec):
            out.append(_p("warn", "spf_neutral", f"The SPF record of {domain} does not end with ~all or -all: it says "
                          f"nothing about other senders, so anyone can claim to send mail as @{domain}.",
                          "End it with ~all (or -all).", domain=domain))
        if (facts.get("spf_lookups") or 0) > 10:
            out.append(_p("error", "spf_lookups", f"The SPF record of {domain} needs about {facts['spf_lookups']} DNS lookups (limit 10).",
                          "Remove the include: of services you no longer send with.", domain=domain, count=facts["spf_lookups"]))
    if not facts.get("dkim"):
        out.append(_p("info", "no_dkim", f"No DKIM key found on the usual selectors of {domain}.",
                      "If you send mail from this domain, publish the DKIM key your sending provider gives (its selector may simply not be one of: "
                      + ", ".join(DKIM_SELECTORS) + ").", domain=domain, selectors=", ".join(DKIM_SELECTORS)))
    dmarc = facts.get("dmarc") or []
    record = f"v=DMARC1; p=none; rua=mailto:{rua}"
    parent = facts.get("dmarc_parent") or {}
    if not dmarc and parent.get("records"):
        # p=none here would WEAKEN the parent's policy for this subdomain: never advised
        pol = _policy(parent["records"], sub=True) or "?"
        out.append(_p("info", "dmarc_inherited", f"No DMARC record on {domain}: the policy of {parent['domain']} "
                      f"applies (p={pol}).",
                      "Nothing to add. Do not add a p=none record here: it would weaken that policy for this domain."
                      if pol != "none" else f"Once SPF and DKIM pass, switch the record of {parent['domain']} to "
                      "p=quarantine, then p=reject.", domain=domain, parent=parent["domain"], policy=pol))
    elif not dmarc:
        out.append(_p("warn", "no_dmarc", f"No DMARC record on {domain}.",
                      f"Add a TXT record _dmarc.{domain}: {record}", domain=domain, record=record))
    elif len(dmarc) > 1:
        out.append(_p("error", "multiple_dmarc", f"{len(dmarc)} DMARC records on _dmarc.{domain}: receivers ignore them all.",
                      "Keep only one TXT record v=DMARC1 on _dmarc." + domain + ".", domain=domain, count=len(dmarc)))
    else:
        m = re.search(r"(?:^|;)\s*p\s*=\s*([a-z]+)", dmarc[0].lower())
        if not m:
            out.append(_p("error", "dmarc_no_policy", f"The DMARC record of {domain} has no policy (p=).",
                          f"Use for example: {record}", domain=domain, record=record))
        elif m.group(1) == "none":
            out.append(_p("info", "dmarc_none", f"DMARC on {domain} only watches (p=none).",
                          "Once SPF and DKIM pass for every service that sends as you, switch to p=quarantine, then p=reject.",
                          domain=domain))
    return out


def _policy(dmarc: list[str], sub: bool = False) -> str | None:
    """p= of the one record; sub: the policy it sets for subdomains (sp=, else p=)."""
    if len(dmarc) != 1:
        return None
    rec = dmarc[0].lower()
    m = re.search(r"(?:^|;)\s*sp\s*=\s*([a-z]+)", rec) if sub else None
    m = m or re.search(r"(?:^|;)\s*p\s*=\s*([a-z]+)", rec)
    return m.group(1) if m else None


def domains_health(wanted: dict[str, dict], refresh: bool = False, rua_of: dict[str, str] | None = None) -> list[dict]:
    """wanted: {domain: {"expects": bool, "cf_routing": bool, "sources": [..]}} -> one health line per domain."""
    cache = config.read_json(_dns_path(), {}) or {}
    if not isinstance(cache, dict):
        cache = {}
    now = time.time()
    names = sorted(wanted)[:MAX_DOMAINS]
    todo = [d for d in names if refresh or now - ((cache.get(d) or {}).get("checked") or 0) > DNS_TTL_S]
    if todo:
        with ThreadPoolExecutor(max_workers=DOMAIN_WORKERS) as ex:
            for d, facts in zip(todo, ex.map(dns_facts, todo)):
                cache[d] = facts
        cache = {d: f for d, f in cache.items() if now - ((f or {}).get("checked") or 0) < 7 * 86400}
        config.write_json(_dns_path(), cache)
    out = []
    for d in names:
        f, w = cache.get(d) or {}, wanted[d]
        spf = f.get("spf") or []
        out.append({"domain": d, "sources": sorted(w.get("sources") or []), "expects": bool(w.get("expects")),
                    "checked": f.get("checked"), "error": f.get("error"),
                    "mx": [m["host"] for m in f.get("mx") or []],
                    "spf": {"record": spf[0] if len(spf) == 1 else None, "count": len(spf), "lookups": f.get("spf_lookups")},
                    "dkim": f.get("dkim") or [],
                    "dmarc": {"record": (f.get("dmarc") or [None])[0], "count": len(f.get("dmarc") or []),
                              "policy": _policy(f.get("dmarc") or []),
                              "parent": (f.get("dmarc_parent") or {}).get("domain")},     # inherited from it
                    "problems": problems(d, f, bool(w.get("expects")), bool(w.get("cf_routing")),
                                         (rua_of or {}).get(d) or f"dmarc@{d}")})
    return out


# ---- the view -----------------------------------------------------------------------------------
def _providers(refresh: bool) -> tuple[dict, bool]:
    with _lock:
        cached = config.read_json(_cache_path(), None)
        if (not refresh and isinstance(cached, dict) and time.time() - (cached.get("at") or 0) < PROVIDERS_TTL_S
                and isinstance(cached.get("cloudflare"), dict) and isinstance(cached.get("hostinger"), dict)):
            return cached, True
        with ThreadPoolExecutor(max_workers=2) as ex:
            fc, fh = ex.submit(cloudflare_mail), ex.submit(hostinger_mail)
            data = {"at": int(time.time())}
            for k, f in (("cloudflare", fc), ("hostinger", fh)):
                try:
                    data[k] = f.result()
                except Exception as e:  # noqa: BLE001 - never a 5xx for a provider
                    data[k] = {"connected": True, "error": "failed", "message": type(e).__name__}
        config.write_json(_cache_path(), data)
        return data, False


def view(refresh: bool = False) -> dict:
    from .. import mail
    boxes = mailboxes()
    prov, cached = _providers(refresh)
    cf, hs = prov["cloudflare"], prov["hostinger"]
    from ..mail import KNOWN
    wanted: dict[str, dict] = {}

    def want(d: str | None, source: str, expects: bool, cf_routing: bool = False) -> None:
        d = (d or "").strip().lower().rstrip(".")
        if not d or d in KNOWN or "." not in d:
            return
        w = wanted.setdefault(d, {"expects": False, "cf_routing": False, "sources": set()})
        w["expects"] |= expects
        w["cf_routing"] |= cf_routing
        w["sources"].add(source)

    for z in cf.get("zones") or []:
        r = z.get("routing") or {}
        if r.get("enabled") or z.get("missing_permission"):
            want(z.get("name"), "cloudflare", bool(r.get("enabled")), bool(r.get("enabled")))
    for o in hs.get("orders") or []:
        want(o.get("domain"), "hostinger", True)
    for b in boxes:
        want(b.get("domain"), "mail_page", True)
    rua_of: dict[str, str] = {}
    for b in boxes:
        if b.get("address"):
            rua_of.setdefault(b["domain"], b["address"])
    for d in wanted:                # reports only reach a mailbox of the same domain (or a parent): else dmarc@<domain>
        if d not in rua_of:
            parent = next((a for bd, a in rua_of.items() if d.endswith("." + bd)), None)
            if parent:
                rua_of[d] = parent
    return {"generated_at": prov.get("at"), "cached": cached, "mail_page": mail.enabled(),
            "mailboxes": boxes, "cloudflare": cf, "hostinger": hs, "routes": routes(boxes, cf, hs),
            "domains": domains_health(wanted, refresh, rua_of)}
