"""Infra -> E-mail (infra/mailinfo.py), view only: Cloudflare Email Routing, Hostinger Email and the DNS health of the
mail domains, against fake local APIs (Cloudflare, Hostinger, DNS over HTTPS). Never a real provider or resolver."""
import time
from urllib.parse import parse_qs, urlparse

from _conn_helpers import _Server
from _org_helpers import client, org  # noqa: F401
from maxxing import config, mail, vault
from maxxing.infra import mailinfo

J = "application/json"
DENIED = (403, {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}, J)


def ok(result, pages=1):
    return 200, {"success": True, "result": result, "result_info": {"total_pages": pages}}, J


def fake_cloudflare(calls):
    def h(method, path, headers, body):
        assert method == "GET", "Infra -> E-mail only reads"
        assert headers.get("Authorization") == "Bearer cf-tok"
        p = urlparse(path).path
        calls.append(p)
        if p == "/zones":
            return ok([{"id": "z1", "name": "shop.example.com"}, {"id": "z2", "name": "blog.example.org"},
                       {"id": "z3", "name": "quiet.example.net"}, {"id": "z4", "name": "rules.example.com"}])
        if p == "/accounts/acc/email/routing/addresses":
            return ok([{"email": "owner@gmail.com", "verified": "2026-01-01T00:00:00Z"},
                       {"email": "late@example.net", "verified": None}])
        if p == "/zones/z1/email/routing":
            return ok({"enabled": True, "status": "ready"})
        if p == "/zones/z1/email/routing/rules":
            return ok([
                {"name": "contact", "enabled": True, "matchers": [{"type": "literal", "field": "to", "value": "contact@shop.example.com"}],
                 "actions": [{"type": "forward", "value": ["owner@gmail.com"]}]},
                {"name": "sales", "enabled": True, "matchers": [{"type": "literal", "field": "to", "value": "sales@shop.example.com"}],
                 "actions": [{"type": "forward", "value": ["late@example.net"]}]},
                {"name": "bot", "enabled": False, "matchers": [{"type": "literal", "field": "to", "value": "bot@shop.example.com"}],
                 "actions": [{"type": "worker", "value": ["mail-bot"]}]},
            ])
        if p == "/zones/z1/email/routing/rules/catch_all":
            return ok({"enabled": True, "matchers": [{"type": "all"}], "actions": [{"type": "drop"}]})
        if p.startswith("/zones/z2/"):
            return DENIED                                   # the token sees the zone, not its Email Routing
        if p == "/zones/z4/email/routing":
            return DENIED                                   # the settings need their own permission...
        if p == "/zones/z4/email/routing/rules":            # ...the rules are readable all the same
            return ok([{"name": "hi", "enabled": True, "matchers": [{"type": "literal", "field": "to", "value": "hi@rules.example.com"}],
                        "actions": [{"type": "forward", "value": ["owner@gmail.com"]}]}])
        if p == "/zones/z3/email/routing":
            return ok({"enabled": False, "status": "unconfigured"})
        return 404, {"success": False, "errors": [{"code": 7003, "message": "no route"}]}, J
    return h


def fake_hostinger(with_plan, calls):
    def h(method, path, headers, body):
        assert method == "GET"
        p = urlparse(path).path
        calls.append(p)
        page = int(parse_qs(urlparse(path).query).get("page", ["1"])[0])
        empty = {"data": [], "meta": {"current_page": page, "per_page": 100, "total": 0}}
        if p == "/api/mail/v1/orders":
            if not with_plan or page > 1:
                return 200, empty, J
            return 200, {"data": [{"id": "OR1", "status": "active", "seats": 1, "domain": {"id": "DO1", "name": "acme.example"},
                                   "plan": {"name": "hostinger_free", "title": "Free Email"}}], "meta": {"total": 1}}, J
        if p == "/api/mail/v1/orders/OR1/mailboxes":
            return 200, {"data": [{"id": "AC1", "address": "info@acme.example", "status": "active", "is_catchall": False}]}, J
        if p == "/api/mail/v1/orders/OR1/forwarders":
            return 200, {"data": [{"id": "FW1", "mailbox": {"id": "AC1", "address": "info@acme.example"},
                                   "destination": "me@box.example", "is_active": True, "is_confirmed": False}]}, J
        if p in ("/api/mail/v1/orders/OR1/aliases", "/api/mail/v1/orders/OR1/catchalls"):
            return 200, empty, J
        return 404, {"message": "not found"}, J
    return h


def txt(*records):
    return [{"type": 16, "data": " ".join(f'"{x}"' for x in r)} for r in records]


DNS = {
    ("shop.example.com", "MX"): [{"type": 15, "data": "10 route1.mx.cloudflare.net."}, {"type": 15, "data": "20 route2.mx.cloudflare.net."}],
    ("shop.example.com", "TXT"): txt(["v=spf1 include:_spf.mx.cloudflare.net ~all"], ["google-site-verification=x"]),
    ("_spf.mx.cloudflare.net", "TXT"): txt(["v=spf1 ip4:192.0.2.0/24 ~all"]),
    ("_dmarc.shop.example.com", "TXT"): txt(["v=DMARC1; p=none; rua=mailto:d@shop.example.com"]),
    ("cf2024-1._domainkey.shop.example.com", "TXT"): txt(["v=DKIM1; h=sha256; k=rsa; ", "p=MIIBIjAN"]),
    # blog.example.org (rules unreadable): has MX elsewhere, two SPF records, no DMARC
    ("blog.example.org", "MX"): [{"type": 15, "data": "5 mx1.mail.example.net."}],
    ("blog.example.org", "TXT"): txt(["v=spf1 mx ~all"], ["v=spf1 include:other.example ~all"]),
    # acme.example (Hostinger plan + E-mail page): nothing at all
}


def fake_doh(queries):
    def h(method, path, headers, body):
        q = parse_qs(urlparse(path).query)
        name, rtype = q["name"][0], q["type"][0]
        queries.append((name, rtype))
        ans = DNS.get((name, rtype))
        return 200, ({"Status": 0, "Answer": ans} if ans else {"Status": 3}), J
    return h


def setup(monkeypatch, with_plan=True):
    cf_calls, hs_calls, dns_q = [], [], []
    servers = [_Server(fake_cloudflare(cf_calls)), _Server(fake_hostinger(with_plan, hs_calls)), _Server(fake_doh(dns_q))]
    monkeypatch.setenv("MAXXING_CLOUDFLARE_API", servers[0].url)
    monkeypatch.setenv("MAXXING_HOSTINGER_API", servers[1].url)
    monkeypatch.setenv("MAXXING_DOH_API", servers[2].url + "/dns-query")
    vault.put("CLOUDFLARE_API_TOKEN", "cf-tok")
    vault.put("CLOUDFLARE_ACCOUNT_ID", "acc")
    vault.put("HOSTINGER_API_TOKEN", "h-tok")
    return servers, cf_calls, hs_calls, dns_q


def add_box(address, host="imap.example.net"):
    acc, _ = mail.add_account({"address": address, "imap_host": host, "imap_port": 993, "imap_tls": "ssl",
                               "smtp_host": host, "smtp_port": 465, "smtp_tls": "ssl"}, "pw", skip_test=True)
    return acc


def test_cloudflare_hostinger_routes_and_dns(org, monkeypatch):
    servers, cf_calls, hs_calls, dns_q = setup(monkeypatch)
    try:
        gm = add_box("owner@gmail.com", "imap.gmail.com")
        add_box("me@acme.example")
        v = mailinfo.view()
    finally:
        for s in servers:
            s.close()
    cf = v["cloudflare"]
    zones = {z["name"]: z for z in cf["zones"]}
    assert zones["shop.example.com"]["routing"] == {"enabled": True, "status": "ready"}
    assert zones["blog.example.org"]["missing_permission"] is True and zones["blog.example.org"]["routing"] is None
    assert zones["quiet.example.net"]["routing"]["enabled"] is False and zones["quiet.example.net"]["rules"] == []
    assert not any(c.startswith("/zones/z3/email/routing/rules") for c in cf_calls)        # routing off: no rule call
    assert cf["missing_permission_zones"] == 1
    assert zones["rules.example.com"]["routing"] == {"enabled": True, "status": None} and not zones["rules.example.com"].get("missing_permission")
    assert zones["rules.example.com"]["rules"][0]["to"] == ["owner@gmail.com"]
    assert cf["fix"] == "Add the permission Zone → Email Routing Rules → Read for all zones to the Cloudflare token (Settings → Keys)"
    assert {a["email"]: a["verified"] for a in cf["addresses"]} == {"late@example.net": False, "owner@gmail.com": True}

    routes = {r["address"]: r for r in v["routes"]}
    contact = routes["contact@shop.example.com"]
    assert contact["via"] == "cloudflare" and contact["kind"] == "forward"
    assert contact["to"] == [{"address": "owner@gmail.com", "verified": True, "account": gm["id"]}]   # ends in the E-mail page
    assert routes["sales@shop.example.com"]["to"] == [{"address": "late@example.net", "verified": False, "account": None}]
    assert routes["bot@shop.example.com"]["kind"] == "worker" and routes["bot@shop.example.com"]["worker"] == "mail-bot"
    assert routes["bot@shop.example.com"]["enabled"] is False
    assert routes["*@shop.example.com"]["kind"] == "drop"                                       # the catch-all rule
    assert routes["info@acme.example"]["via"] == "hostinger"
    fwd = [r for r in v["routes"] if r["via"] == "hostinger" and r["kind"] == "forward"][0]
    assert fwd["to"] == [{"address": "me@box.example", "verified": False, "account": None}]
    order = v["hostinger"]["orders"][0]
    assert order["domain"] == "acme.example" and order["plan"] == "Free Email" and order["mailboxes"][0]["address"] == "info@acme.example"

    boxes = {b["address"]: b for b in v["mailboxes"]}
    assert boxes["me@acme.example"]["domain"] == "acme.example" and "last_check" in boxes["me@acme.example"]

    doms = {d["domain"]: d for d in v["domains"]}
    assert set(doms) == {"shop.example.com", "blog.example.org", "rules.example.com", "acme.example"}   # not gmail.com
    shop = doms["shop.example.com"]
    assert shop["mx"] == ["route1.mx.cloudflare.net", "route2.mx.cloudflare.net"]
    assert shop["spf"]["count"] == 1 and shop["spf"]["lookups"] == 1
    assert shop["dkim"] == ["cf2024-1"] and shop["dmarc"]["policy"] == "none"
    assert [p["code"] for p in shop["problems"]] == ["dmarc_none"]
    blog = {p["code"]: p for p in doms["blog.example.org"]["problems"]}
    assert blog["multiple_spf"]["level"] == "error" and "no_dmarc" in blog and "no_dkim" in blog
    assert blog["no_dmarc"]["fix"].endswith("rua=mailto:dmarc@blog.example.org")          # never a mailbox of another domain
    acme = {p["code"]: p for p in doms["acme.example"]["problems"]}
    assert acme["no_mx"]["level"] == "error"
    assert acme["no_dmarc"]["fix"] == "Add a TXT record _dmarc.acme.example: v=DMARC1; p=none; rua=mailto:me@acme.example"
    assert acme["no_spf"]["params"]["record"] == "v=spf1 mx ~all"
    assert ("quiet.example.net", "MX") not in dns_q                                         # routing off: not a mail domain


def test_cache_and_refresh(org, monkeypatch):
    servers, cf_calls, hs_calls, dns_q = setup(monkeypatch, with_plan=False)
    try:
        v = mailinfo.view()
        assert v["hostinger"] == {"connected": True, "key": "HOSTINGER_API_TOKEN", "orders": []}   # "No Hostinger e-mail plan"
        n_cf, n_dns = len(cf_calls), len(dns_q)
        again = mailinfo.view()
        assert again["cached"] is True and len(cf_calls) == n_cf and len(dns_q) == n_dns
        fresh = mailinfo.view(refresh=True)
        assert fresh["cached"] is False and len(cf_calls) > n_cf and len(dns_q) > n_dns
        # an old cache is read again from the providers
        data = config.read_json(mailinfo._cache_path())
        data["at"] = time.time() - mailinfo.PROVIDERS_TTL_S - 5
        config.write_json(mailinfo._cache_path(), data)
        n_cf = len(cf_calls)
        assert mailinfo.view()["cached"] is False and len(cf_calls) > n_cf
    finally:
        for s in servers:
            s.close()


def test_providers_down_or_missing_never_raise(org, monkeypatch):
    monkeypatch.setenv("MAXXING_CLOUDFLARE_API", "http://127.0.0.1:9")                     # nothing listens there
    monkeypatch.setenv("MAXXING_HOSTINGER_API", "http://127.0.0.1:9")
    monkeypatch.setenv("MAXXING_DOH_API", "http://127.0.0.1:9/dns-query")
    v = mailinfo.view()
    assert v["cloudflare"]["connected"] is False and v["hostinger"]["connected"] is False and v["domains"] == []
    vault.put("CLOUDFLARE_API_TOKEN", "cf-tok")
    vault.put("HOSTINGER_API_TOKEN", "h-tok")
    add_box("me@acme.example")
    v = mailinfo.view(refresh=True)
    assert v["cloudflare"]["error"] == "unreachable" and v["hostinger"]["error"] == "unreachable"
    assert v["domains"][0]["problems"][0]["code"] == "dns_unreachable"


def test_problem_rules():
    facts = {"mx": [{"prio": 10, "host": "aspmx.l.google.com"}], "spf": ["v=spf1 include:a include:b all"], "spf_lookups": 12,
             "dmarc": ["v=DMARC1; rua=mailto:x@example.com"], "dkim": ["google"]}
    codes = {p["code"]: p["level"] for p in mailinfo.problems("example.com", facts, True, True, "x@example.com")}
    assert codes == {"mx_not_cloudflare": "warn", "spf_all": "error", "spf_lookups": "error", "dmarc_no_policy": "error"}
    none = mailinfo.problems("example.com", {"mx": [], "spf": [], "dmarc": [], "dkim": []}, False, False, "x@example.com")
    assert [p["code"] for p in none] == ["no_mail"]                                        # not a mail domain: no noise
    null = mailinfo.problems("example.com", {"mx": [{"prio": 0, "host": ""}], "spf": [], "dmarc": [], "dkim": []}, True, False, "x")
    assert null[0]["code"] == "null_mx"
    google = mailinfo.problems("example.com", {"mx": [{"prio": 1, "host": "smtp.google.com"}], "spf": [], "dmarc": [], "dkim": []}, True, False, "x")
    assert next(p for p in google if p["code"] == "no_spf")["params"]["record"] == "v=spf1 include:_spf.google.com ~all"


def test_spf_without_a_real_all_is_flagged():
    base = {"mx": [{"prio": 10, "host": "mx.example.net"}], "dkim": ["google"], "dmarc": ["v=DMARC1; p=reject"], "spf_lookups": 1}
    codes = {r: [p["code"] for p in mailinfo.problems("ex.com", {**base, "spf": [r]}, True, False, "x@ex.com")]
             for r in ("v=spf1 +ALL", "v=spf1 ALL", "v=spf1 ?all", "v=spf1 a mx", "v=spf1 -ALL", "v=spf1 mx ~all",
                       "v=spf1 redirect=_spf.ex.net")}
    assert codes == {"v=spf1 +ALL": ["spf_all"], "v=spf1 ALL": ["spf_all"], "v=spf1 ?all": ["spf_neutral"],
                     "v=spf1 a mx": ["spf_neutral"], "v=spf1 -ALL": [], "v=spf1 mx ~all": [], "v=spf1 redirect=_spf.ex.net": []}


def test_a_subdomain_inherits_the_parent_dmarc_and_is_never_told_p_none(monkeypatch):
    DNS[("_dmarc.example.org", "TXT")] = txt(["v=DMARC1; p=reject; sp=quarantine"])
    monkeypatch.setattr(mailinfo.dnsinfo, "_query", lambda c, name, rtype: DNS.get((name, rtype)) or [])
    try:
        facts = mailinfo.dns_facts("blog.example.org")
    finally:
        del DNS[("_dmarc.example.org", "TXT")]
    assert facts["dmarc"] == [] and facts["dmarc_parent"] == {"domain": "example.org", "records": ["v=DMARC1; p=reject; sp=quarantine"]}
    probs = mailinfo.problems("blog.example.org", facts, True, False, "x@example.org")
    [d] = [p for p in probs if "dmarc" in p["code"]]
    assert d["code"] == "dmarc_inherited" and d["params"]["policy"] == "quarantine" and "Do not add a p=none" in d["fix"]
    assert "no_dmarc" in [p["code"] for p in mailinfo.problems("blog.example.org", {**facts, "dmarc_parent": None}, True, False, "x")]


def test_api_and_cli(client, org, monkeypatch, capsys):  # noqa: F811
    from maxxing import cli
    servers, *_ = setup(monkeypatch)
    try:
        assert client.get("/api/infra/mail").status_code == 409                            # Infra page off
        config.update_config(infra_page=True)
        r = client.get("/api/infra/mail?refresh=1")
        assert r.status_code == 200 and r.json()["cloudflare"]["missing_permission_zones"] == 1
        assert cli.main(["infra", "mail"]) == 0
        out = capsys.readouterr().out
        assert "contact@shop.example.com" in out and "Email Routing Rules → Read" in out
        assert "2 SPF records on blog.example.org" in out
        assert cli.main(["infra", "mail", "--json"]) == 0
        assert '"routes"' in capsys.readouterr().out
    finally:
        for s in servers:
            s.close()
