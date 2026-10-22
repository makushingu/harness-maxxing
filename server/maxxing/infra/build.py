"""Turn raw sources (server probes, Cloudflare, Hostinger, hosting platforms, RDAP, public DNS) into the resources of
the Infra page.

A resource: {id, kind, name, location, provider, urls, status, status_detail, details, links, project, note, hidden,
declared, missing}. Kinds: server, site, worker, pages, database, bucket, domain. `location` is "local" (this
server), a registered server name, "cloudflare", "hostinger" or a platform ("vercel", "netlify", "supabase", "github");
domains are located at their registrar when it is connected, else "other". `links` are ids of related resources (a site and
its server, a domain and its sites, a database and its server...).
"""
from __future__ import annotations

import ipaddress
import re
from datetime import datetime, timezone
from pathlib import Path

LOCAL = "local"
SYSTEM_DBS = {"postgres"}
TWO_LEVEL_TLDS = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "com.br", "com.mx",
                  "co.jp", "co.za", "com.tr", "com.cn", "co.in", "co.kr", "com.ar", "com.co", "com.pt", "co.il"}
CF_NETS = [ipaddress.ip_network(n) for n in (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22", "141.101.64.0/18", "108.162.192.0/18",
    "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22", "2400:cb00::/32", "2606:4700::/32", "2803:f800::/32",
    "2405:b500::/32", "2405:8100::/32", "2a06:98c0::/29", "2c0f:f248::/32")]


def registrable(host: str) -> str:
    parts = host.lower().strip(".").split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in TWO_LEVEL_TLDS:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s.strip("[]"))
        return True
    except ValueError:
        return False


def behind_cloudflare(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in n for n in CF_NETS if n.version == a.version)


def _ts(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            return int(v)                                # NaN / inf (an old rdap.json): ValueError / OverflowError
        return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
    except (ValueError, OverflowError):
        return None


def _project_of(path: str | None, workspace: str) -> str | None:
    """`<workspace>/projects/<p>/...` -> p."""
    if not path:
        return None
    m = re.match(re.escape(workspace.rstrip("/")) + r"/projects/([^/]+)", path)
    return m.group(1) if m else None


def _github(remote: str | None) -> str | None:
    m = re.search(r"github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", (remote or "").strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _repo(repo: dict | None, local: bool) -> dict | None:
    if not repo:
        return None
    gh = _github(repo.get("remote"))
    target = repo["path"] if local else (f"github:{gh}" if gh else None)
    return {"path": repo["path"], "github": gh, "branch": repo.get("branch"), "git": target}


def _res(rid: str, kind: str, name: str, location: str, provider: str, **kw) -> dict:
    return {"id": rid, "kind": kind, "name": name, "location": location, "provider": provider, "urls": kw.pop("urls", []),
            "status": "unknown", "status_detail": "", "details": kw.pop("details", {}), "links": kw.pop("links", []),
            "project": kw.pop("project", None), "note": "", "hidden": False, "declared": False, "missing": False}


def build(probes: dict[str, dict], servers: list[dict], cf: dict | None, hst: dict | None, rdap: dict[str, dict],
          registry: dict[str, dict], workspace: str, harness_host: str | None, platforms: dict[str, dict] | None = None,
          dns: dict[str, dict] | None = None, watched: list[str] | None = None) -> list[dict]:
    """probes: {"local" | server name: probe output or {"error": msg}}. platforms: platforms.read_all(); dns: public
    DNS cache (dnsinfo); watched: domains added by hand."""
    from . import dnsinfo
    platforms = platforms or {}
    dns = dns or {}
    out: dict[str, dict] = {}
    ip_owner: dict[str, str] = {}                          # IP -> server resource id

    def add(r: dict) -> dict:
        out[r["id"]] = r
        return r

    # servers ---------------------------------------------------------------------------------
    hvps = (hst or {}).get("vps") if isinstance((hst or {}).get("vps"), list) else []
    srv_defs = [{"name": LOCAL, "host": None}] + servers
    for s in srv_defs:
        name = s["name"]
        p = probes.get(name) or {}
        sv = p.get("server") or {}
        rid = f"server:{name}"
        ips = [i["ip"] for i in sv.get("ips") or []]
        if s.get("host") and is_ip(s["host"]) and s["host"] not in ips:
            ips.append(s["host"])
        det = {"server": name, "host": s.get("host"), "user": s.get("user"), "ips": ips, "os": sv.get("os"), "cpus": sv.get("cpus"),
               "mem_total": sv.get("mem_total"), "mem_available": sv.get("mem_available"), "disk_total": sv.get("disk_total"),
               "disk_free": sv.get("disk_free"), "load": sv.get("load"), "uptime_s": sv.get("uptime_s"),
               "hostname": sv.get("hostname"), "web_servers": p.get("web_servers") or [], "probe_ms": p.get("took_ms"),
               "probe_errors": p.get("errors") or {}, "collected_at": p.get("collected_at")}
        r = add(_res(rid, "server", "this server" if name == LOCAL else (s.get("label") or name), name, "server", details=det))
        if name == LOCAL:
            r["details"]["this"] = True
        if p.get("error"):
            r["status"], r["status_detail"] = "down", p["error"]
        elif sv:
            r["status"] = "ok"
            free = sv.get("disk_free") or 0
            total = sv.get("disk_total") or 0
            if total and free / total < 0.1:
                r["status"], r["status_detail"] = "warn", "disk_low"
        for ip in ips:
            ip_owner[ip] = rid
        for v in hvps:
            if set(v.get("ips") or []) & set(ips):
                r["details"]["hostinger"] = v
                v["_matched"] = rid
    for v in hvps:
        if v.get("_matched"):
            continue
        rid = f"server:hostinger:{v.get('id')}"
        r = add(_res(rid, "server", v.get("hostname") or str(v.get("id")), "hostinger", "hostinger",
                     details={"hostinger": v, "ips": v.get("ips") or [], "not_connected": True}))
        r["status"] = "ok" if v.get("state") == "running" else ("down" if v.get("state") in ("stopped", "error") else "unknown")
        for ip in v.get("ips") or []:
            ip_owner.setdefault(ip, rid)

    # sites, databases, buckets of each server ------------------------------------------------------
    for s in srv_defs:
        name = s["name"]
        p = probes.get(name) or {}
        local = name == LOCAL
        srv_id = f"server:{name}"
        by_port = {l["port"]: l for l in p.get("listeners") or []}
        conts = {c["id"]: c for c in p.get("containers") or []}
        for c in p.get("containers") or []:
            for pt in c.get("ports") or []:
                by_port.setdefault(pt["host"], {"port": pt["host"], "container": c["id"]})
                if by_port[pt["host"]].get("process") == "docker-proxy":
                    by_port[pt["host"]] = {**by_port[pt["host"]], "container": c["id"]}
        for site in p.get("sites") or []:
            host, path = site["host"], site.get("path") or ""
            rid = f"site:{name}:{host}{path}"
            urls = []
            if host != "*" and "*" not in host:
                scheme = "http" if is_ip(host) or host == "localhost" else "https"
                urls.append(f"{scheme}://{host}{path}" + ("/" if path else ""))
            det = {k: site.get(k) for k in ("host", "path", "kind", "upstreams", "root", "redirect", "sandbox", "server")}
            services = []
            for up in site.get("upstreams") or []:
                m = re.match(r"^(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)?:?(\d+)$", up.split("://")[-1])
                port = int(m.group(1)) if m else None
                ln = by_port.get(port) if port else None
                if not ln:
                    continue
                c = conts.get(ln.get("container") or "")
                svc = {"port": port, "unit": ln.get("unit"), "process": ln.get("process"), "cwd": ln.get("cwd"),
                       "container": c["name"] if c else None, "repo": _repo(ln.get("repo") or (c or {}).get("repo"), local)}
                services.append(svc)
            det["services"] = services
            project = None
            if local:
                project = _project_of(site.get("root"), workspace) or next(
                    (_project_of(x.get("cwd"), workspace) for x in services if x.get("cwd")), None)
            r = add(_res(rid, "site", f"{host}{path}", name, "server", urls=urls, details=det, links=[srv_id], project=project))
            if harness_host and local and host == harness_host and not path:
                r["details"]["harness"] = True
        for db in p.get("databases") or []:
            eng, where = db["engine"], db.get("where")
            if eng == "sqlite":
                rid = f"db:{name}:sqlite:{db['path']}"
                det = {"engine": "sqlite", "path": db["path"], "size": db.get("size"), "modified": db.get("modified"),
                       "repo": _repo(db.get("repo"), local), "scan_incomplete": db.get("scan_incomplete")}
                r = add(_res(rid, "database", Path(db["path"]).name, name, "server", details=det, links=[srv_id],
                             project=_project_of(db["path"], workspace) if local else None))
                r["status"] = "warn" if db.get("missing") else "ok"
                if db.get("missing"):
                    r["status_detail"] = "file_missing"
                continue
            holder = db.get("container") or "native"
            base = {"engine": eng, "where": where, "container": db.get("container"), "image": db.get("image"),
                    "port": db.get("port"), "version": db.get("version"), "compose_project": db.get("compose_project")}
            if db.get("databases") is None:
                rid = f"db:{name}:{eng}:{holder}"
                r = add(_res(rid, "database", f"{eng} ({holder})", name, "server", details={**base, "error": db.get("error")},
                             links=[srv_id]))
                r["status"] = "warn" if db.get("error") else "ok"
                r["status_detail"] = "list_failed" if db.get("error") else ""
                continue
            for x in db["databases"]:
                rid = f"db:{name}:{eng}:{holder}:{x['name']}"
                r = add(_res(rid, "database", x["name"], name, "server",
                             details={**base, "size": x.get("size"), "owner": x.get("owner"), "system": x["name"] in SYSTEM_DBS},
                             links=[srv_id]))
                r["status"] = "ok"
        for g in p.get("buckets") or []:
            for b in g.get("buckets") or []:
                rid = f"bucket:{name}:garage:{b['name']}"
                add(_res(rid, "bucket", b["name"], name, "server", links=[srv_id],
                         details={"engine": "garage", "bytes": b.get("bytes"), "objects": b.get("objects"),
                                  "website": b.get("website"), "s3_endpoint": g.get("s3_endpoint")}))["status"] = "ok"

    # Cloudflare ------------------------------------------------------------------------------------
    cf = cf or {}
    sub = cf.get("worker_subdomain") if isinstance(cf.get("worker_subdomain"), str) else None
    wdom = cf.get("worker_domains") if isinstance(cf.get("worker_domains"), list) else []
    if isinstance(cf.get("workers"), list):
        for w in cf["workers"]:
            urls = [f"https://{d['hostname']}/" for d in wdom if d.get("service") == w["name"]]
            routes = list(w.get("routes") or [])
            for z in cf.get("zones") or [] if isinstance(cf.get("zones"), list) else []:
                routes += [r["pattern"] for r in z.get("worker_routes") or [] if r.get("script") == w["name"]]
            if sub:
                urls.append(f"https://{w['name']}.{sub}.workers.dev/")
            add(_res(f"worker:cloudflare:{w['name']}", "worker", w["name"], "cloudflare", "cloudflare", urls=urls,
                     details={"modified": _ts(w.get("modified")), "routes": sorted(set(routes)),
                              "dashboard": f"https://dash.cloudflare.com/{cf.get('account_id')}/workers/services/view/{w['name']}/production"}))
    if isinstance(cf.get("pages"), list):
        for pg in cf["pages"]:
            urls = [f"https://{d}/" for d in pg.get("domains") or []]
            r = add(_res(f"pages:cloudflare:{pg['name']}", "pages", pg["name"], "cloudflare", "cloudflare", urls=urls,
                         details={**pg, "deployed": _ts(pg.get("deployed")), "repo": {"github": f"{pg['owner']}/{pg['repo']}", "git": f"github:{pg['owner']}/{pg['repo']}"} if pg.get("repo") and pg.get("owner") else None,
                                  "dashboard": f"https://dash.cloudflare.com/{cf.get('account_id')}/pages/view/{pg['name']}"}))
            if pg.get("status") == "failure":
                r["status"], r["status_detail"] = "down", "deploy_failed"
    if isinstance(cf.get("r2"), list):
        for b in cf["r2"]:
            r = add(_res(f"bucket:cloudflare:r2:{b['name']}", "bucket", b["name"], "cloudflare", "cloudflare",
                         urls=[u + "/" for u in b.get("public") or []],
                         details={"engine": "r2", "created": _ts(b.get("created")), "location": b.get("location"),
                                  "dashboard": f"https://dash.cloudflare.com/{cf.get('account_id')}/r2/default/buckets/{b['name']}"}))
            r["status"] = "ok"
    if isinstance(cf.get("d1"), list):
        for d in cf["d1"]:
            r = add(_res(f"db:cloudflare:d1:{d['name']}", "database", d["name"], "cloudflare", "cloudflare",
                         details={"engine": "d1", "size": d.get("size"), "tables": d.get("tables"), "created": _ts(d.get("created")),
                                  "dashboard": f"https://dash.cloudflare.com/{cf.get('account_id')}/workers/d1/databases/{d.get('uuid')}"}))
            r["status"] = "ok"

    # hosting platforms (platforms.py) ---------------------------------------------------------------
    plat_state = {"ok": ("ok", ""), "failed": ("down", "deploy_failed"), "building": ("unknown", "deploying"),
                  "paused": ("warn", "paused"), "unknown": ("unknown", "")}
    for pid, pdata in platforms.items():
        def items(section: str) -> list:
            v = pdata.get(section)
            return v if isinstance(v, list) else []
        for x in items("sites"):
            r = add(_res(f"pages:{pid}:{x['id']}", "pages", x["name"], pid, pid, urls=x.get("urls") or [],
                         details={"platform": pid, "deployed": _ts(x.get("deployed")), "framework": x.get("framework"),
                                  "team": x.get("team"), "dashboard": x.get("dashboard"), "deploy_state": x.get("state"),
                                  "repo": {"github": x["repo"], "git": f"github:{x['repo']}"} if x.get("repo") else None}))
            st, why = plat_state.get(x.get("state") or "unknown", ("unknown", ""))
            if st != "unknown":
                r["status"], r["status_detail"] = st, why
            elif why:
                r["status_detail"] = why
        groups: dict[str, list[str]] = {}
        for kind, section, prefix in (("database", "databases", "db"), ("bucket", "buckets", "bucket"), ("worker", "functions", "worker")):
            for x in items(section):
                det = {k: v for k, v in x.items() if k not in ("id", "name", "state", "url")}
                det["platform"] = pid
                if kind == "worker" and x.get("url"):
                    det["routes"] = [x["url"]]
                r = add(_res(f"{prefix}:{pid}:{x['id']}", kind, x["name"], pid, pid, details=det))
                st, why = plat_state.get(x.get("state") or "ok", ("ok", ""))
                r["status"], r["status_detail"] = st, why
                if x.get("group"):
                    groups.setdefault(x["group"], []).append(r["id"])
        for ids in groups.values():                      # one Supabase project: its database, buckets and functions
            for other in ids[1:]:
                _link(out, ids[0], other)

    # domains -------------------------------------------------------------------------------------
    domains: dict[str, dict] = {}

    def dom(name: str) -> dict:
        name = name.lower().strip(".")
        if name not in domains:
            domains[name] = {"name": name, "registrar": None, "expires": None, "auto_renew": None, "dns": None,
                             "name_servers": [], "records": [], "sources": [], "dns_error": None}
        return domains[name]
    for z in cf.get("zones") or [] if isinstance(cf.get("zones"), list) else []:
        d = dom(z["name"])
        d["dns"] = "cloudflare"
        d["name_servers"] = z.get("name_servers") or []
        d["sources"].append("cloudflare")
        d["zone_status"] = z.get("status")
        d["records"] += z.get("dns") or []
        d["dns_error"] = z.get("dns_error")
        d["dashboard"] = f"https://dash.cloudflare.com/{cf.get('account_id')}/{z['name']}"
    for x in cf.get("registrar") or [] if isinstance(cf.get("registrar"), list) else []:
        d = dom(x["name"])
        d.update(registrar="cloudflare", expires=_ts(x.get("expires")), auto_renew=x.get("auto_renew"))
        d["sources"].append("cloudflare-registrar")
    for x in (hst or {}).get("domains") or [] if isinstance((hst or {}).get("domains"), list) else []:
        d = dom(x["name"])
        d.update(registrar="hostinger", expires=_ts(x.get("expires")))
        d["registrar_status"] = x.get("status")
        d["sources"].append("hostinger")
        d["hostinger_dashboard"] = f"https://hpanel.hostinger.com/domain/{x['name']}/dns"
        if x.get("dns") and not d["records"]:
            d["records"] = x["dns"]
            d["dns"] = d["dns"] or "hostinger"
    for pid, pdata in platforms.items():
        for x in pdata.get("domains") if isinstance(pdata.get("domains"), list) else []:
            d = dom(x["name"])
            d["sources"].append(pid)
            if x.get("registrar"):
                d.update(registrar=pid, expires=_ts(x.get("expires")) or d["expires"], auto_renew=x.get("auto_renew"))
            if x.get("dns"):
                d["dns"] = d["dns"] or pid
                d["name_servers"] = d["name_servers"] or x.get("name_servers") or []
                if x.get("records") and not d["records"]:
                    d["records"] = [{"type": "A" if rec["type"] == "NETLIFY" else rec["type"], "name": _fqdn(rec["name"], x["name"]),
                                     "content": rec["content"]} for rec in x["records"] if rec.get("content")]
    for name in watched or []:
        dom(name)["sources"].append("added")
    site_hosts = {r["details"]["host"] for r in out.values() if r["kind"] == "site" and r["details"].get("host") not in (None, "*")}
    extra = {h for h in site_hosts if not is_ip(h) and h != "localhost" and "." in h}
    extra |= {d["hostname"] for d in wdom}
    for pg in cf.get("pages") or [] if isinstance(cf.get("pages"), list) else []:
        extra |= {h for h in pg.get("domains") or [] if not h.endswith(".pages.dev")}
    for r in out.values():                              # custom domains of the platforms' sites
        if r["kind"] == "pages" and r["location"] in platforms:
            extra |= {h for h in (_hostname(u) for u in r["urls"]) if h and not _platform_host(h)}
    for h in extra:
        if not any(h == n or h.endswith("." + n) for n in domains):
            dom(registrable(h))["sources"].append("used")
    for name, d in domains.items():
        info = rdap.get(name) or {}
        if not d["expires"] and info.get("expires"):
            d["expires"] = _ts(info["expires"])
            d["registrar"] = d["registrar"] or info.get("registrar")
            d["expiry_source"] = "rdap"
        pub = dns.get(name) or {}
        real = dnsinfo.dns_provider(pub["ns"]) if pub.get("ns") else None
        if real and real != "other" and d["dns"] and d["dns"] != real:
            # a zone exists at a provider (Hostinger keeps one for every domain) but the name servers are elsewhere:
            # the public name servers are the truth, the records of that zone are not used
            d["unused_zone"], d["dns"], d["records"], d["name_servers"] = d["dns"], real, [], pub["ns"]
        elif real and not d["dns"]:
            d["dns"] = real
            d["name_servers"] = d["name_servers"] or pub["ns"]
        if not d["records"]:                            # no zone read through an API: what the public DNS answers
            for h in (name, f"www.{name}"):
                d["records"] += [{"type": "A" if "." in ip else "AAAA", "name": h, "content": ip, "public": True}
                                 for ip in (dns.get(h) or {}).get("a") or []]
        rid = f"domain:{name}"
        known = ("cloudflare", "hostinger", *platforms)
        loc = d["registrar"] if d["registrar"] in known else "other"
        r = add(_res(rid, "domain", name, loc, loc, urls=[f"https://{name}/"], details={k: v for k, v in d.items() if k != "records"}))
        r["details"]["records"] = d["records"][:400]
        if pub and not pub.get("error"):
            r["details"]["hosted_by"] = dnsinfo.hosted_by(pub)
            www = dns.get(f"www.{name}") or {}
            if www and not www.get("error"):
                r["details"]["www_hosted_by"] = dnsinfo.hosted_by(www)
        if "added" in d["sources"]:
            r["details"]["added"] = True
        if d["expires"]:
            days = (d["expires"] - datetime.now(timezone.utc).timestamp()) / 86400
            r["details"]["days_left"] = int(days)
            if days < 0:
                r["status"], r["status_detail"] = "down", "domain_expired"
            elif days < 30 and not d.get("auto_renew"):
                r["status"], r["status_detail"] = "warn", "domain_expiring"
            else:
                r["status"] = "ok"

    # links: host -> domain, DNS record -> server ---------------------------------------------------
    records: dict[str, list[dict]] = {}
    for d in domains.values():
        for rec in d["records"]:
            records.setdefault(rec["name"].lower(), []).append(rec)
    for h, info in dns.items():                         # hosts only the public DNS knows
        if h not in records and info.get("a"):
            records[h] = [{"type": "A" if "." in ip else "AAAA", "name": h, "content": ip, "public": True} for ip in info["a"]]
    for name in domains:                                # a domain pointing at one of our servers
        targets = {ip_owner.get(rec["content"]) for rec in records.get(name, []) if rec["type"] in ("A", "AAAA")}
        for t in targets - {None}:
            _link(out, f"domain:{name}", t)
            out[f"domain:{name}"]["details"]["hosted_by"] = out[f"domain:{name}"]["details"].get("hosted_by") or "server"
    for r in list(out.values()):
        hosts = []
        if r["kind"] == "site" and r["details"].get("host") not in (None, "*"):
            hosts = [r["details"]["host"]]
        elif r["kind"] in ("worker", "pages", "bucket"):
            hosts = [re.sub(r"^https?://([^/]+).*", r"\1", u) for u in r["urls"]]
        for h in hosts:
            if is_ip(h) or "." not in h:
                continue
            dn = next((n for n in sorted(domains, key=len, reverse=True) if h == n or h.endswith("." + n)), None)
            if dn:
                _link(out, r["id"], f"domain:{dn}")
            if r["kind"] != "site":
                continue
            recs = records.get(h.lower(), [])
            r["details"]["dns"] = recs
            targets = {ip_owner.get(rec["content"]) for rec in recs if rec["type"] in ("A", "AAAA")}
            targets.discard(None)
            srv_id = f"server:{r['location']}"
            if recs and any(rec["type"] in ("A", "AAAA") for rec in recs) and targets and srv_id not in targets:
                r["details"]["dns_elsewhere"] = sorted(targets)
    for r in out.values():
        for l in list(r["links"]):
            if l in out and r["id"] not in out[l]["links"]:
                out[l]["links"].append(r["id"])

    # registry: annotations, declared resources ------------------------------------------------------
    for rid, ann in registry.items():
        r = out.get(rid)
        if r is None:
            if not ann.get("declared"):
                continue
            r = add(_res(rid, ann.get("kind") or rid.split(":")[0], ann.get("name") or rid, ann.get("server") or LOCAL,
                         "server", urls=ann.get("urls") or [], details=dict(ann.get("details") or {})))
            r["missing"] = True
            r["status"], r["status_detail"] = "down", "missing"
        r["declared"] = bool(ann.get("declared"))
        if ann.get("project"):
            r["project"] = ann["project"]
        r["note"] = ann.get("note") or ""
        r["hidden"] = bool(ann.get("hidden"))
        for k in ("vault_keys", "recipe"):
            if ann.get(k):
                r["details"][k] = ann[k]
    return sorted(out.values(), key=lambda r: (r["kind"], r["location"] != LOCAL, r["location"], r["name"]))


def _hostname(url: str) -> str | None:
    m = re.match(r"^https?://([^/:]+)", url or "")
    return m.group(1).lower() if m else None


PLATFORM_SUFFIXES = (".vercel.app", ".netlify.app", ".github.io", ".pages.dev", ".supabase.co", ".workers.dev")


def _platform_host(h: str) -> bool:
    return h.endswith(PLATFORM_SUFFIXES)


def hosts_to_resolve(resources: list[dict]) -> list[tuple[str, bool]]:
    """The names the public DNS is asked about: every domain (+ www), every custom address of a site."""
    names: dict[str, bool] = {}
    for r in resources:
        if r["kind"] == "domain":
            names[r["name"]] = True
            names.setdefault(f"www.{r['name']}", False)
        elif r["kind"] in ("site", "pages", "worker"):
            for u in r["urls"][:2]:
                h = _hostname(u)
                if h and not is_ip(h) and "." in h and h != "localhost" and not _platform_host(h):
                    names.setdefault(h, False)
    return list(names.items())


def _fqdn(name: str | None, domain: str) -> str:
    n = (name or "@").strip(".").lower()
    return domain if n in ("@", "") else (n if n.endswith(domain) else f"{n}.{domain}")


def _link(out: dict, a: str, b: str) -> None:
    if b in out and b not in out[a]["links"]:
        out[a]["links"].append(b)
    if b in out and a not in out[b]["links"]:
        out[b]["links"].append(a)


def harness_host(public_url: str | None) -> str | None:
    m = re.match(r"^https?://([^/:]+)", public_url or "")
    return m.group(1).lower() if m else None

