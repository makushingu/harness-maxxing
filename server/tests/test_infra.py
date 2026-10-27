"""Infra page: probe parsing, resource building and links, providers (fake APIs), checks, recipes (fake caddy,
psql and garage), API and CLI. Never touches the real web server, databases or provider accounts."""
import json
import os
import stat
import time

import pytest

from _conn_helpers import _Server
from _org_helpers import client, org  # noqa: F401
from maxxing import config, crons, infra, vault
from maxxing.infra import actions, build, caddy, probe, providers, registry

CADDY_JSON = {"apps": {"http": {"servers": {"srv0": {"listen": [":443"], "routes": [
    {"match": [{"host": ["ui.example.com"]}], "terminal": True, "handle": [{"handler": "subroute", "routes": [
        {"match": [{"path": ["/demo/*"]}], "handle": [{"handler": "subroute", "routes": [
            {"handle": [{"handler": "rewrite", "strip_path_prefix": "/demo"}]},
            {"handle": [{"handler": "headers", "response": {"set": {"Content-Security-Policy": [caddy.SANDBOX]}}},
                        {"handler": "vars", "root": "/srv/demo"}, {"handler": "file_server"}]}]}]},
        {"match": [{"path": ["/blog*"]}], "handle": [{"handler": "subroute", "routes": [
            {"handle": [{"handler": "vars", "root": "/var/www"}]},
            {"handle": [{"handler": "file_server"}]}]}]},
        {"handle": [{"handler": "reverse_proxy", "upstreams": [{"dial": "127.0.0.1:8787"}]}]}]}]},
    {"match": [{"host": ["shop.example.com"]}], "handle": [{"handler": "subroute", "routes": [
        {"handle": [{"handler": "reverse_proxy", "upstreams": [{"dial": "localhost:3000"}]}]}]}]},
    {"match": [{"host": ["www.example.com"]}], "handle": [{"handler": "static_response",
                                                         "headers": {"Location": ["https://example.com{http.request.uri}"]},
                                                         "status_code": 301}]},
]}}}}}

NGINX = """
# comment { not a block }
server {
    listen 443 ssl;
    server_name api.example.org www.api.example.org;
    location / { proxy_pass http://127.0.0.1:5000; }
    location /static { alias /srv/static; }
}
server { listen 80; server_name old.example.org; return 301 https://example.org$request_uri; }
"""


def test_parse_caddy():
    sites = {(s["host"], s["path"]): s for s in probe.parse_caddy(CADDY_JSON)}
    assert sites[("ui.example.com", "/demo")]["root"] == "/srv/demo"          # handle_path: the root itself
    assert sites[("ui.example.com", "/demo")]["sandbox"] is True
    assert sites[("ui.example.com", "/blog")]["root"] == "/var/www/blog"      # no strip: root + path
    assert sites[("ui.example.com", "")]["upstreams"] == ["127.0.0.1:8787"]
    assert sites[("shop.example.com", "")]["kind"] == "proxy"
    assert sites[("www.example.com", "")]["redirect"].startswith("https://example.com")


def test_parse_nginx():
    sites = {(s["host"], s["path"]): s for s in probe.parse_nginx(NGINX)}
    assert sites[("api.example.org", "")]["upstreams"] == ["127.0.0.1:5000"]
    assert sites[("www.api.example.org", "/static")]["root"] == "/srv/static"
    assert sites[("old.example.org", "")]["kind"] == "redirect"


def test_probe_runs_here():
    out = probe.collect({"sqlite_roots": []})
    assert out["version"] == 1 and out["server"]["cpus"] and isinstance(out["listeners"], list)


def _probes(ws):
    local = {"server": {"hostname": "box", "ips": [{"ip": "203.0.113.5", "iface": "eth0"}], "disk_total": 100, "disk_free": 50},
             "web_servers": ["caddy"], "sites": probe.parse_caddy(CADDY_JSON),
             "listeners": [{"port": 3000, "addrs": ["127.0.0.1"], "process": "node", "pid": 1, "unit": "shop.service",
                            "cwd": f"{ws}/projects/acme/topics/shop/app",
                            "repo": {"path": f"{ws}/projects/acme/topics/shop/app", "remote": "git@github.com:acme/shop.git", "branch": "main"}}],
             "containers": [], "databases": [
                 {"engine": "postgres", "where": "native", "port": 5432, "databases": [
                     {"name": "postgres", "size": 7, "owner": "postgres"}, {"name": "shop", "size": 9000, "owner": "shop"}]},
                 {"engine": "sqlite", "where": "file", "path": f"{ws}/projects/acme/data.db", "size": 4096}],
             "buckets": []}
    remote = {"server": {"hostname": "far", "ips": [{"ip": "198.51.100.9", "iface": "eth0"}]}, "sites": [
        {"host": "blog.example.com", "path": "", "kind": "static", "upstreams": [], "root": "/var/www/blog"}],
        "listeners": [], "containers": [{"id": "abc", "name": "pg-1", "image": "postgres:16", "engine": "postgres", "ports": []}],
        "databases": [{"engine": "redis", "where": "docker", "container": "redis-1", "databases": None}], "buckets": []}
    return {"local": local, "far": remote}


CF = {"connected": True, "account_id": "acc", "worker_subdomain": "acme",
      "workers": [{"name": "api", "routes": []}], "worker_domains": [{"hostname": "api.example.com", "service": "api"}],
      "pages": [], "r2": [{"name": "media", "public": ["https://cdn.example.com"]}], "d1": [{"name": "blogdb", "size": 10}],
      "registrar": {"error": "missing_permission"},
      "zones": [{"id": "z1", "name": "example.com", "name_servers": ["a.ns"], "dns": [
          {"type": "A", "name": "shop.example.com", "content": "198.51.100.9"},
          {"type": "A", "name": "blog.example.com", "content": "198.51.100.9"}]}]}
HST = {"connected": True, "domains": [{"name": "example.org", "status": "active", "expires": "2020-01-01T00:00:00Z"}],
       "vps": [{"id": 7, "hostname": "far.example.net", "state": "running", "ips": ["198.51.100.9"]}]}


def test_build_links_and_status(tmp_path):
    ws = str(tmp_path / "ws")
    servers = [{"name": "far", "host": "198.51.100.9", "user": "root"}]
    reg = {"site:local:gone.example.com": {"declared": True, "kind": "site", "name": "gone.example.com"},
           "db:local:postgres:native:shop": {"project": "billing", "note": "main db"}}
    res = {r["id"]: r for r in build.build(_probes(ws), servers, CF, HST, {}, reg, ws, "ui.example.com")}
    shop = res["site:local:shop.example.com"]
    assert shop["details"]["services"][0]["unit"] == "shop.service"
    assert shop["details"]["services"][0]["repo"]["git"].endswith("/app")           # local clone -> Git page path
    assert shop["project"] == "acme"                                                   # from the app's folder
    assert shop["details"]["dns_elsewhere"] == ["server:far"]                         # DNS points to the other server
    assert "domain:example.com" in shop["links"] and "server:local" in shop["links"]
    assert res["site:local:ui.example.com"]["details"]["harness"] is True
    assert res["site:far:blog.example.com"]["details"].get("dns_elsewhere") is None   # right server
    assert res["server:far"]["details"]["hostinger"]["hostname"] == "far.example.net"  # matched by IP
    assert "server:hostinger:7" not in res
    assert res["db:local:postgres:native:postgres"]["details"]["system"] is True
    assert res["db:local:postgres:native:shop"]["project"] == "billing"
    assert res["db:local:postgres:native:shop"]["note"] == "main db"
    assert res["db:local:sqlite:" + ws + "/projects/acme/data.db"]["project"] == "acme"
    assert res["db:far:redis:redis-1"]["name"] == "redis (redis-1)"
    assert res["worker:cloudflare:api"]["urls"] == ["https://api.example.com/", "https://api.acme.workers.dev/"]
    assert res["bucket:cloudflare:r2:media"]["urls"] == ["https://cdn.example.com/"]
    assert "domain:example.com" in res["bucket:cloudflare:r2:media"]["links"]
    assert res["db:cloudflare:d1:blogdb"]["kind"] == "database"
    assert res["domain:example.org"]["status"] == "down"                              # expired
    gone = res["site:local:gone.example.com"]
    assert gone["missing"] and gone["status"] == "down" and gone["declared"]


def test_providers_with_fake_apis(org, monkeypatch):
    def cf(method, path, headers, body):
        assert headers.get("Authorization") == "Bearer cf-tok"
        if path.startswith("/accounts/acc/workers/scripts"):
            return 200, {"success": True, "result": [{"id": "api", "routes": []}]}, "application/json"
        if path.startswith("/accounts/acc/r2/buckets/media/domains/custom"):
            return 200, {"success": True, "result": {"domains": [{"domain": "cdn.example.com", "enabled": True}]}}, "application/json"
        if path.startswith("/accounts/acc/r2/buckets/media/domains/managed"):
            return 200, {"success": True, "result": {"enabled": False}}, "application/json"
        if path.startswith("/accounts/acc/r2/buckets"):
            return 200, {"success": True, "result": {"buckets": [{"name": "media"}]}}, "application/json"
        if path.startswith("/zones?") or path == "/zones":
            return 200, {"success": True, "result": [{"id": "z1", "name": "example.com"}], "result_info": {"total_pages": 1}}, "application/json"
        if path.startswith("/zones/z1/dns_records"):
            return 403, {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}, "application/json"
        if path.startswith("/zones/z1/workers/routes"):
            return 200, {"success": True, "result": []}, "application/json"
        if path.startswith("/accounts/acc/workers/subdomain"):
            return 200, {"success": True, "result": {"subdomain": "acme"}}, "application/json"
        return 403, {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}, "application/json"

    def hs(method, path, headers, body):
        if path == "/api/domains/v1/portfolio":
            return 200, [{"domain": "example.org", "status": "active", "expires_at": "2030-01-01T00:00:00Z"}], "application/json"
        if path == "/api/vps/v1/virtual-machines":
            return 200, [{"id": 7, "hostname": "far", "state": "running", "ipv4": [{"address": "198.51.100.9"}]}], "application/json"
        if path == "/api/dns/v1/zones/example.org":
            return 200, [{"name": "@", "type": "A", "records": [{"content": "198.51.100.9", "is_disabled": False}]}], "application/json"
        return 404, {}, "application/json"
    a, b = _Server(cf), _Server(hs)
    monkeypatch.setenv("MAXXING_CLOUDFLARE_API", a.url)
    monkeypatch.setenv("MAXXING_HOSTINGER_API", b.url)
    try:
        assert providers.cloudflare() == {"connected": False, "key": None}
        vault.put("CLOUDFLARE_API_TOKEN", "cf-tok")
        vault.put("CLOUDFLARE_ACCOUNT_ID", "acc")
        vault.put("HOSTINGER_API_TOKEN", "h-tok")
        c = providers.cloudflare()
        assert c["workers"][0]["name"] == "api" and c["r2"][0]["public"] == ["https://cdn.example.com"]
        assert c["pages"] == {"error": "missing_permission", "message": "the Cloudflare token has no read access to this"}
        assert c["zones"][0]["dns_error"] == "missing_permission"                     # one section, not the whole provider
        h = providers.hostinger()
        assert h["vps"][0]["ips"] == ["198.51.100.9"]
        assert h["domains"][0]["dns"] == [{"type": "A", "name": "example.org", "content": "198.51.100.9"}]
        state = infra._source_state(c, h)
        assert state["cloudflare"]["sections"]["dns"] == "missing_permission"
        assert state["cloudflare"]["sections"]["workers"] == "ok"
    finally:
        a.close()
        b.close()


def test_url_checks():
    def h(method, path, headers, body):
        code = int(path.strip("/") or 200)
        return code, b"x", "text/plain"
    s = _Server(h)
    try:
        assert infra.check_url(s.url + "/200")["status"] == "ok"
        assert infra.check_url(s.url + "/403")["status"] == "ok"
        assert infra.check_url(s.url + "/404")["status"] == "warn"
        assert infra.check_url(s.url + "/502")["status"] == "down"
        site = {"kind": "site", "urls": [s.url + "/404"], "missing": False, "status": "unknown", "status_detail": "",
                "details": {"kind": "proxy"}}
        static = {**site, "details": {"kind": "static"}, "status": "unknown"}
        infra.run_checks([site, static])
        assert site["status"] == "ok"                       # an app answering 404 on / is alive
        assert static["status"] == "warn" and static["status_detail"] == "http_404"
    finally:
        s.close()
    assert infra.check_url("http://127.0.0.1:9/")["status"] == "down"


@pytest.fixture
def fake_caddy(org, monkeypatch, tmp_path):
    d = tmp_path / "caddy"
    d.mkdir()
    (d / "Caddyfile").write_text("import " + str(d / "claude-maxxing.caddy") + "\n")
    (d / "claude-maxxing.caddy").write_text("ui.example.com {\n\tencode zstd gzip\n\treverse_proxy 127.0.0.1:8787 {\n\t\tflush_interval -1\n\t}\n}\n")
    binary = tmp_path / "fake-caddy"
    binary.write_text("#!/bin/sh\n[ -f \"$FAKE_CADDY_FAIL\" ] && { echo 'Error: bad directive' >&2; exit 1; }\nexit 0\n")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("MAXXING_CADDY_DIR", str(d))
    monkeypatch.setenv("MAXXING_CADDY_BIN", str(binary))
    monkeypatch.setenv("MAXXING_CADDY_RELOAD", "true")
    monkeypatch.setenv("MAXXING_CADDY_API", "http://127.0.0.1:9")
    monkeypatch.setenv("MAXXING_CADDYFILE", str(d / "nothing"))
    monkeypatch.setenv("FAKE_CADDY_FAIL", str(tmp_path / "fail"))
    config.update_config(public_url="https://ui.example.com")
    return d


def test_path_site(fake_caddy, tmp_path):
    www = tmp_path / "www"
    www.mkdir()
    res = caddy.add_site("demo", root=str(www), project="acme")
    assert res["url"] == "https://ui.example.com/demo/" and res["mode"] == "path"
    text = (fake_caddy / "maxxing-paths" / "demo.caddy").read_text()
    assert "handle_path /demo/*" in text and caddy.SANDBOX in text and f"root * {www}" in text
    harness = (fake_caddy / "claude-maxxing.caddy").read_text().splitlines()
    imp = next(i for i, ln in enumerate(harness) if "import" in ln and "maxxing-paths" in ln)
    assert imp < next(i for i, ln in enumerate(harness) if "reverse_proxy" in ln)      # before Harness's proxy
    reg = registry.resources()["site:local:ui.example.com/demo"]
    assert reg["declared"] and reg["project"] == "acme"
    with pytest.raises(caddy.CaddyError) as e:
        caddy.add_site("demo", root=str(www))
    assert e.value.code == "exists"
    for bad in ("api", "assets", "git"):
        with pytest.raises(caddy.CaddyError) as e:
            caddy.add_site(bad, root=str(www))
        assert e.value.code == "reserved_name"
    caddy.add_site("app", port=3100, keep_prefix=True)
    assert "handle /app/*" in (fake_caddy / "maxxing-paths" / "app.caddy").read_text()
    assert sum("maxxing-paths" in ln for ln in (fake_caddy / "claude-maxxing.caddy").read_text().splitlines()) == 1
    assert [s["name"] for s in caddy.list_sites()] == ["app", "demo"]
    caddy.remove_site("demo")
    assert not (fake_caddy / "maxxing-paths" / "demo.caddy").exists()
    assert "site:local:ui.example.com/demo" not in registry.resources()


def test_host_site_and_rollback(fake_caddy, tmp_path):
    www = tmp_path / "www"
    www.mkdir()
    before = (fake_caddy / "Caddyfile").read_text()
    (tmp_path / "fail").touch()                                          # caddy validate refuses
    with pytest.raises(caddy.CaddyError) as e:
        caddy.add_site("shop", root=str(www), host="shop.example.com")
    assert e.value.code == "invalid_config" and "bad directive" in str(e.value)
    assert (fake_caddy / "Caddyfile").read_text() == before                # put back
    assert not (fake_caddy / "sites" / "shop.caddy").exists()
    (tmp_path / "fail").unlink()
    res = caddy.add_site("shop", port=3000, host="Shop.Example.com")
    assert res["url"] == "https://shop.example.com/"
    assert f"import {fake_caddy}/sites/*.caddy" in (fake_caddy / "Caddyfile").read_text()
    assert "reverse_proxy 127.0.0.1:3000" in (fake_caddy / "sites" / "shop.caddy").read_text()
    for host, code in (("ui.example.com", "taken"), ("not a host", "invalid_host")):
        with pytest.raises(caddy.CaddyError) as e:
            caddy.add_site("x" + code[:3], port=1, host=host)
        assert e.value.code == code


def test_path_site_needs_harness_on_caddy(org, monkeypatch, tmp_path):
    monkeypatch.setenv("MAXXING_CADDY_DIR", str(tmp_path / "none"))
    (tmp_path / "w").mkdir()
    with pytest.raises(caddy.CaddyError) as e:
        caddy.add_site("demo", root=str(tmp_path / "w"))
    assert e.value.code == "no_harness_site"


def test_pg_create(org, monkeypatch):
    calls = []

    def fake_run(args, input=None, timeout=60):
        calls.append((args, input))
        if args[:2] == ["systemctl", "is-active"]:
            return 0, "active\n", ""
        if "select datname" in (input or ""):
            return 0, "postgres\nother\n", ""
        if "pg_roles" in (input or ""):
            return 0, "", ""
        return 0, "", ""
    monkeypatch.setattr(actions, "_run", fake_run)
    monkeypatch.setattr(actions.shutil, "which", lambda b: "/usr/bin/" + b)
    res = actions.pg_create("shop", project="acme")
    assert res["vault_key"] == "DB_SHOP_URL"
    url = vault.get("DB_SHOP_URL")
    assert url.startswith("postgresql://shop:") and url.endswith("@127.0.0.1:5432/shop")
    pw = url.split(":")[2].split("@")[0]
    assert all(pw not in " ".join(a) for a, _ in calls)                  # never on a command line
    assert registry.resources()["db:local:postgres:native:shop"]["vault_keys"] == ["DB_SHOP_URL"]
    assert [j["name"] for j in crons.list_jobs()] == [actions.BACKUP_JOB]
    actions.ensure_backup_job()
    assert len(crons.list_jobs()) == 1
    with pytest.raises(actions.ActionError) as e:
        actions.pg_create("other")
    assert e.value.code == "exists"
    with pytest.raises(actions.ActionError) as e:
        actions.pg_create("Bad-Name")
    assert e.value.code == "invalid_name"


def test_sqlite_declare_and_backup(org, monkeypatch, tmp_path):
    import sqlite3
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as c:
        c.execute("create table t(x)")
        c.execute("insert into t values (1)")
    monkeypatch.setenv("MAXXING_INFRA_BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setattr(actions, "pg_installed", lambda: False)
    actions.declare_sqlite(str(db), project="acme")
    res = actions.backup_all()
    assert len(res) == 1 and res[0]["ok"]
    with sqlite3.connect(res[0]["file"]) as c:
        assert c.execute("select x from t").fetchone() == (1,)
    state = json.loads((org.state / "infra" / "backups.json").read_text())
    assert state[f"db:local:sqlite:{db}"]["ok"] is True
    with pytest.raises(actions.ActionError):
        actions.declare_sqlite(str(tmp_path / "missing.db"))


def test_bucket_create(fake_caddy, monkeypatch):
    def fake_garage(*args, timeout=60):
        if args[:2] == ("key", "create"):
            return 0, "==== ACCESS KEY INFORMATION ====\nKey ID:              GK123\nSecret key:          s3cr3t\n", ""
        return 0, "", ""
    monkeypatch.setattr(actions, "garage_installed", lambda: True)
    monkeypatch.setattr(actions, "_garage", fake_garage)
    res = actions.bucket_create("media", public=True, project="acme")
    assert vault.get("S3_MEDIA_ACCESS_KEY_ID") == "GK123" and vault.get("S3_MEDIA_SECRET_ACCESS_KEY") == "s3cr3t"
    assert res["public_url"] == "https://ui.example.com/media/"
    assert "header_up Host media.web.garage.localhost" in (fake_caddy / "maxxing-paths" / "media.caddy").read_text()
    assert "s3cr3t" not in (org_ws := config.workspace() / "infra.json").read_text() and org_ws.exists()


def test_api_and_cli(client, org, monkeypatch, capsys):
    from maxxing import cli
    monkeypatch.setenv("MAXXING_INFRA_CHECKS", "0")
    monkeypatch.setattr(infra, "probe_local", lambda opts: _probes(str(org.ws))["local"])
    monkeypatch.setattr(providers, "cloudflare", lambda: CF)
    monkeypatch.setattr(providers, "hostinger", lambda: {"connected": False, "key": None})
    v = client.get("/api/infra").json()
    assert v["enabled"] is False and v["resources"] == []
    assert client.post("/api/infra/refresh").status_code == 409
    assert client.get("/api/settings").json()["infra_page"] is False
    client.put("/api/settings", json={"infra_page": True})
    assert client.post("/api/infra/refresh").json()["started"] is True
    for _ in range(100):
        v = client.get("/api/infra").json()
        if v["resources"] and not v["refreshing"]:
            break
        time.sleep(0.05)
    ids = {r["id"] for r in v["resources"]}
    assert "site:local:shop.example.com" in ids and "worker:cloudflare:api" in ids
    assert v["sources"]["cloudflare"]["sections"]["registrar"] == "missing_permission"
    r = client.post("/api/infra/annotate", json={"id": "site:local:shop.example.com", "project": "acme", "note": "prod", "hidden": True})
    assert r.json()["project"] == "acme"
    shop = next(x for x in client.get("/api/infra").json()["resources"] if x["id"] == "site:local:shop.example.com")
    assert shop["hidden"] and shop["note"] == "prod"
    assert "api" in client.get("/api/infra/reserved").json()["names"]
    assert cli.main(["infra", "list", "--kind", "worker"]) == 0
    assert "api.example.com" in capsys.readouterr().out
    assert cli.main(["infra", "status"]) == 0
    out = capsys.readouterr().out
    assert "registrar: missing_permission" in out
    assert cli.main(["infra", "annotate", "site:local:shop.example.com", "--show"]) == 0
    assert not registry.resources()["site:local:shop.example.com"].get("hidden")


def test_alerts(org, monkeypatch):
    from maxxing import feed
    posted = []
    monkeypatch.setattr(feed, "post", lambda *a, **k: posted.append((a, k)))
    r = {"id": "site:local:a", "kind": "site", "name": "a", "status": "down", "hidden": False,
         "details": {"checks": [{"url": "https://a/", "status": "down", "detail": "http_502"}]}}
    infra._alerts([r], {"resources": [{"id": "site:local:a", "status": "ok"}]})
    assert posted[0][0][0] == "Down: a" and "http_502" in posted[0][0][1]
    posted.clear()
    infra._alerts([r], {"resources": [{"id": "site:local:a", "status": "down"}]})
    assert posted == []                                        # still down: no repeat
    d = {"id": "domain:x.org", "kind": "domain", "name": "x.org", "status": "warn", "hidden": False,
         "details": {"days_left": 5, "expires": 1, "auto_renew": False}}
    infra._alerts([d], None)
    assert posted and posted[0][1]["dedupe"].endswith(":7")


def test_ssh_command():
    cmd = infra.ssh_command({"host": "198.51.100.9", "user": "deploy", "port": 2222, "key": "/k"}, "python3", "-")
    assert cmd[:3] == ["ssh", "-o", "BatchMode=yes"] and "-p" in cmd and "2222" in cmd
    assert cmd[-3:] == ["deploy@198.51.100.9", "python3", "-"] and "/k" in cmd
    with pytest.raises(registry.RegistryError):
        registry.check_server("local", "1.2.3.4")
    with pytest.raises(registry.RegistryError):
        registry.check_server("ok", "bad host;rm")


def test_doctor_reports_a_site_hiding_a_ui_route(fake_caddy, tmp_path, monkeypatch):
    from maxxing import cmd_core
    assert cmd_core.check_infra_paths() is None                          # no path site: no line
    www = tmp_path / "www"
    www.mkdir()
    caddy.add_site("reports", root=str(www))
    assert cmd_core.check_infra_paths()["level"] == cmd_core.OK
    monkeypatch.setattr(caddy, "UI_ROUTES", caddy.UI_ROUTES | {"reports"})   # a later version adds /reports
    c = cmd_core.check_infra_paths()
    assert c["level"] == cmd_core.WARN and "/reports/" in c["detail"]


# ---- connecting other servers (infra/connect.py) ---------------------------------------------------
def _fake_hostinger(vm_keys: list[str], added: list):
    def hs(method, path, headers, body):
        assert headers.get("Authorization") == "Bearer h-tok"
        if path == "/api/vps/v1/virtual-machines/7/ssh-keys":
            if method == "POST":
                added.extend(json.loads(body)["keys"])
                vm_keys.extend(" ".join(k.split()[:2]) for k in json.loads(body)["keys"])
            return 200, [{"type": k.split()[0], "data": k.split()[1], "name": "k"} for k in vm_keys], "application/json"
        return 404, {}, "application/json"
    return _Server(hs)


def _home_key(tmp_path, monkeypatch) -> str:
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519").write_text("PRIVATE")
    (home / ".ssh" / "id_ed25519.pub").write_text("ssh-ed25519 AAAAmine me@here\n")
    (home / ".ssh" / "orphan.pub").write_text("ssh-ed25519 AAAAorphan x\n")          # no private key: ignored
    monkeypatch.setenv("HOME", str(home))
    return str(home / ".ssh" / "id_ed25519")


VPS = {"id": 7, "hostname": "srv100200.hstgr.cloud", "state": "running", "ips": ["198.51.100.9"]}


def test_server_names_and_labels(org):
    assert registry.free_name("srv100200.hstgr.cloud") == "srv100200"
    registry.add_server("srv100200", "198.51.100.9", label="  VPS   Hostinger ")
    assert registry.free_name("srv100200.hstgr.cloud") == "srv100200-2"
    assert registry.free_name("local") == "server-local" and registry.free_name("") == "server"
    assert registry.get_server("srv100200")["label"] == "VPS Hostinger"
    registry.rename_server("srv100200", "Shop")
    probes = {build.LOCAL: {}, "srv100200": {"server": {"hostname": "srv100200"}, "sites": [], "databases": []}}
    res = {r["id"]: r for r in build.build(probes, registry.servers(), {}, {"connected": True, "vps": [VPS]}, {}, {}, "/w", None)}
    assert res["server:srv100200"]["name"] == "Shop"
    assert res["server:srv100200"]["details"]["hostinger"]["id"] == 7               # the API VPS merged by IP
    assert "server:hostinger:7" not in res
    with pytest.raises(registry.RegistryError):
        registry.rename_server("nope", "x")


def test_auto_connect_uses_the_key_the_vps_accepts(org, tmp_path, monkeypatch):
    from maxxing.infra import connect
    mine = _home_key(tmp_path, monkeypatch)
    tried = []
    monkeypatch.setattr(connect, "can_login", lambda host, user="root", port=22, key="": tried.append((host, key)))
    s = _fake_hostinger(["ssh-ed25519 AAAAother"], [])
    monkeypatch.setenv("MAXXING_HOSTINGER_API", s.url)
    try:
        vault.put("HOSTINGER_API_TOKEN", "h-tok")
        assert connect.auto_connect([VPS]) == []                  # none of our keys there: nothing tried, nothing added
        assert tried == []
        assert connect.auto_connect([VPS]) == []                  # and not asked again before 6 hours
        (config.STATE / "infra" / "autoconnect.json").unlink()
        s.close()
        s = _fake_hostinger(["ssh-ed25519 AAAAmine"], [])
        monkeypatch.setenv("MAXXING_HOSTINGER_API", s.url)
        added = connect.auto_connect([VPS, {**VPS, "id": 8, "state": "stopped", "ips": ["198.51.100.10"]}])
        assert [(a["name"], a["label"], a["host"], a["key"]) for a in added] == [("srv100200", "VPS Hostinger", "198.51.100.9", mine)]
        assert tried == [("198.51.100.9", mine)]
        (config.STATE / "infra" / "autoconnect.json").unlink()
        assert connect.auto_connect([VPS]) == []                  # already connected (same IP)
        config.write_json(infra.snapshot_path(), {"resources": [{"id": "server:old", "kind": "server", "location": "old",
                                                                 "details": {"ips": ["198.51.100.9"]}}]})
        registry.remove_server("srv100200")                       # a server removed but still in the last snapshot
        (config.STATE / "infra" / "autoconnect.json").unlink()
        assert [a["name"] for a in connect.auto_connect([VPS])] == ["srv100200"]
    finally:
        s.close()


def test_connect_hostinger_adds_the_harness_key(org, tmp_path, monkeypatch):
    from maxxing.infra import connect
    _home_key(tmp_path, monkeypatch)
    monkeypatch.setattr(connect, "ADD_WAIT_S", 2)
    accepted = set()
    monkeypatch.setattr(connect, "can_login", lambda host, user="root", port=22, key="": None if key in accepted else "Permission denied")
    added: list = []
    s = _fake_hostinger([], added)
    monkeypatch.setenv("MAXXING_HOSTINGER_API", s.url)
    snap = {"resources": [{"id": "server:hostinger:7", "kind": "server", "location": "hostinger", "details": {"hostinger": VPS}}]}
    config.write_json(infra.snapshot_path(), snap)
    try:
        vault.put("HOSTINGER_API_TOKEN", "h-tok")
        accepted.add(str(connect.key_path()))                       # the VPS takes the key once it is added
        out = connect.connect_hostinger("server:hostinger:7")
        assert out["via"] == "added_key" and out["name"] == "srv100200" and out["label"] == "VPS Hostinger"
        assert added == [connect.key_path().with_suffix(".pub").read_text().strip()]
        assert stat.S_IMODE(connect.key_path().parent.stat().st_mode) == 0o700
        assert added[0].startswith("ssh-ed25519 ") and "harness-maxxing@" in added[0]
        with pytest.raises(connect.ConnectError) as e:
            connect.connect_hostinger("server:hostinger:7")
        assert e.value.code == "exists"
        with pytest.raises(connect.ConnectError) as e:
            connect.connect_hostinger("server:hostinger:99")
        assert e.value.code == "not_found"
    finally:
        s.close()


def test_connect_host_gives_the_line_to_paste(org, tmp_path, monkeypatch, client):  # noqa: F811
    from maxxing.infra import connect
    _home_key(tmp_path, monkeypatch)
    ok = {"v": False}
    monkeypatch.setattr(connect, "can_login", lambda host, user="root", port=22, key="": None if ok["v"] and key else "denied")
    monkeypatch.setattr(infra, "refresh_in_background", lambda: True)          # no real SSH from a test
    config.update_config(infra_page=True)
    r = client.post("/api/infra/servers/connect", json={"host": "203.0.113.5", "user": "deploy", "port": 2222})
    assert r.status_code == 200 and r.json()["connected"] is False
    pub = connect.key_path().with_suffix(".pub").read_text().strip()
    assert r.json()["public_key"] == pub and pub in r.json()["command"]
    ok["v"] = True
    r = client.post("/api/infra/servers/connect", json={"host": "203.0.113.5", "user": "deploy", "port": 2222, "label": "Shop"})
    assert r.json() == {"connected": True, "name": "shop", "label": "Shop", "host": "203.0.113.5", "user": "deploy", "port": 2222,
                        "via": "harness_key"}
    assert client.post("/api/infra/servers/connect", json={"host": "203.0.113.5"}).status_code == 409
    assert client.post("/api/infra/servers/connect", json={"id": "server:shop"}).status_code == 400
    assert client.post("/api/infra/servers/rename", json={"name": "shop", "label": "Boutique"}).json()["label"] == "Boutique"
    assert [s["label"] for s in client.get("/api/infra").json()["servers"]] == ["Boutique"]
    assert client.post("/api/infra/servers/remove", json={"name": "shop"}).status_code == 200
    assert client.post("/api/infra/servers/remove", json={"name": "shop"}).status_code == 404
    config.update_config(infra_page=False)
    assert client.post("/api/infra/servers/connect", json={"host": "203.0.113.6"}).status_code == 409


# ---- hosting platforms (platforms.py), public DNS (dnsinfo.py), domains added by hand -------------------
def _json(code, body):
    return code, body, "application/json"


def test_platforms_with_fake_apis(org, monkeypatch):
    from maxxing.infra import platforms

    def vercel(method, path, headers, body):                 # shapes of the Vercel OpenAPI (v10 projects, v5 domains)
        assert headers.get("Authorization") == "Bearer v-tok"
        if path.startswith("/v2/teams"):
            return _json(200, {"teams": [{"id": "team_1", "slug": "acme"}], "pagination": {"next": None}})
        if path.startswith("/v10/projects"):
            team = "teamId=team_1" in path
            proj = {"id": "prj_t" if team else "prj_1", "name": "shop" if team else "blog", "framework": "nextjs",
                    "link": {"type": "github", "org": "acme", "repo": "shop" if team else "blog"},
                    "alias": [{"domain": "shop.example.com" if team else "blog.example.com", "target": "PRODUCTION"},
                              {"domain": "blog-acme.vercel.app", "target": "PRODUCTION"}],
                    "targets": {"production": {"readyState": "ERROR" if team else "READY", "createdAt": 1760000000000}}}
            return _json(200, {"projects": [proj], "pagination": {"next": None}})
        if path.startswith("/v5/domains"):
            if "teamId" in path:
                return _json(200, {"domains": [], "pagination": {"next": None}})
            return _json(200, {"domains": [{"name": "example.com", "boughtAt": 1700000000000, "expiresAt": 4102444800000,
                                            "renew": True, "serviceType": "zeit.world", "nameservers": ["ns1.vercel-dns.com"]}],
                               "pagination": {"next": None}})
        return _json(404, {})

    def netlify(method, path, headers, body):                # shapes of the Netlify OpenAPI (/api/v1)
        if headers.get("Authorization") != "Bearer n-tok":
            return _json(401, {"message": "Access Denied"})
        if path.startswith("/api/v1/sites"):
            if "page=1" not in path:
                return _json(200, [])
            return _json(200, [{"id": "s1", "name": "docs", "custom_domain": "docs.example.org", "domain_aliases": [],
                                "ssl_url": "https://docs-acme.netlify.app", "admin_url": "https://app.netlify.com/sites/docs",
                                "published_deploy": {"state": "ready", "published_at": "2026-10-01T10:00:00Z"},
                                "build_settings": {"provider": "github", "repo_url": "https://github.com/acme/docs"}}])
        if path.startswith("/api/v1/dns_zones"):
            return _json(200, [{"name": "example.org", "dns_servers": ["dns1.p01.nsone.net"],
                                "records": [{"hostname": "docs.example.org", "type": "NETLIFY", "value": "docs-acme.netlify.app"}]}])
        return _json(401, {})

    def supa(method, path, headers, body):                   # shapes of the Supabase Management API
        if path == "/v1/projects":
            return _json(200, [{"ref": "abcd", "name": "shop-db", "region": "eu-west-3", "status": "ACTIVE_HEALTHY",
                                "database": {"host": "db.abcd.supabase.co", "version": "15.6"}},
                               {"ref": "zzzz", "name": "old", "status": "INACTIVE"}])
        if path == "/v1/projects/abcd/storage/buckets":
            return _json(200, [{"id": "avatars", "name": "avatars", "public": True}])
        if path == "/v1/projects/abcd/functions":
            return _json(200, [{"slug": "hello", "name": "hello", "status": "ACTIVE"}])
        return _json(404, {})
    sv, sn, ss = _Server(vercel), _Server(netlify), _Server(supa)
    monkeypatch.setenv("MAXXING_VERCEL_API", sv.url)
    monkeypatch.setenv("MAXXING_NETLIFY_API", sn.url + "/api/v1")
    monkeypatch.setenv("MAXXING_SUPABASE_API", ss.url)
    try:
        assert platforms.vercel() == {"connected": False, "key": None}
        vault.put("VERCEL_TOKEN", "v-tok")
        vault.put("NETLIFY_AUTH_TOKEN", "n-tok")
        vault.put("SUPABASE_ACCESS_TOKEN", "sbp-tok")
        v, n, s = platforms.vercel(), platforms.netlify(), platforms.supabase()
        assert {x["name"]: (x["urls"], x["state"], x["repo"]) for x in v["sites"]} == {
            "blog": (["https://blog.example.com/", "https://blog-acme.vercel.app/"], "ok", "acme/blog"),
            "shop": (["https://shop.example.com/", "https://blog-acme.vercel.app/"], "failed", "acme/shop")}
        assert v["domains"][0]["registrar"] and v["domains"][0]["dns"] and v["domains"][0]["expires"] == 4102444800
        assert n["sites"][0]["urls"] == ["https://docs.example.org/", "https://docs-acme.netlify.app/"] and n["sites"][0]["repo"] == "acme/docs"
        assert n["domains"][0]["records"][0]["type"] == "NETLIFY"
        assert [d["state"] for d in s["databases"]] == ["ok", "paused"]
        assert s["buckets"][0]["public"] and s["functions"][0]["url"].endswith("/functions/v1/hello")
        state = platforms.source_state({"vercel": v, "netlify": n, "supabase": s})
        assert state["vercel"]["beta"] and state["vercel"]["sections"] == {"sites": "ok", "domains": "ok"}
        vault.put("NETLIFY_AUTH_TOKEN", "bad")                 # a refused token: its sections say so, nothing breaks
        bad = platforms.netlify()
        assert bad["sites"]["error"] == "missing_permission"

        res = {r["id"]: r for r in build.build({build.LOCAL: {}}, [], {}, {}, {}, {}, "/w", None,
                                               platforms={"vercel": v, "netlify": n, "supabase": s})}
        assert res["pages:vercel:prj_t"]["status"] == "down" and res["pages:vercel:prj_t"]["status_detail"] == "deploy_failed"
        assert res["pages:vercel:prj_1"]["details"]["repo"]["git"] == "github:acme/blog"
        assert res["domain:example.com"]["location"] == "vercel" and res["domain:example.com"]["details"]["dns"] == "vercel"
        assert "pages:vercel:prj_1" in res["domain:example.com"]["links"]          # blog.example.com -> example.com
        assert res["domain:example.org"]["details"]["dns"] == "netlify" and res["domain:example.org"]["location"] == "other"
        db = res["db:supabase:abcd"]
        assert db["status"] == "ok" and "bucket:supabase:abcd:avatars" in db["links"] and "worker:supabase:abcd:hello" in db["links"]
        assert res["db:supabase:zzzz"]["status"] == "warn" and res["db:supabase:zzzz"]["status_detail"] == "paused"
    finally:
        sv.close(), sn.close(), ss.close()


def test_public_dns_and_domains_added_by_hand(org, monkeypatch, client):  # noqa: F811
    from maxxing.infra import dnsinfo
    answers = {("example.net", "NS"): [{"type": 2, "data": "ns1.registrar-servers.com."}],
               ("example.net", "A"): [{"type": 1, "data": "198.51.100.9"}],
               ("www.example.net", "A"): [{"type": 5, "data": "acme.github.io."}, {"type": 1, "data": "185.199.108.153"}],
               ("shop.example.net", "A"): [{"type": 5, "data": "shops.myshopify.com."}, {"type": 1, "data": "23.227.38.65"}]}

    def doh(method, path, headers, body):
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(path).query)
        return _json(200, {"Status": 0, "Answer": answers.get((q["name"][0], q["type"][0]), [])})
    s = _Server(doh)
    monkeypatch.setenv("MAXXING_DOH_API", s.url + "/dns-query")
    try:
        cache = dnsinfo.refresh_cache({}, [("example.net", True), ("www.example.net", False), ("shop.example.net", False)])
        assert dnsinfo.dns_provider(cache["example.net"]["ns"]) == "namecheap"
        assert dnsinfo.hosted_by(cache["www.example.net"]) == "github"
        assert dnsinfo.hosted_by(cache["shop.example.net"]) == "shopify"
        assert dnsinfo.hosted_by({"a": ["104.16.1.1"]}) == "cloudflare"
        assert dnsinfo.refresh_cache(cache, [("example.net", True)]) is cache          # cached: nothing asked again
    finally:
        s.close()
    assert registry.add_domain("HTTPS://Example.NET/path") == "example.net"
    with pytest.raises(registry.RegistryError):
        registry.add_domain("not a domain")
    probes = {build.LOCAL: {"server": {"ips": [{"ip": "198.51.100.9"}]}}}
    res = {r["id"]: r for r in build.build(probes, [], {}, {}, {}, {}, "/w", None, dns=cache, watched=registry.load()["domains"])}
    d = res["domain:example.net"]
    assert d["details"]["added"] and d["details"]["dns"] == "namecheap" and d["details"]["www_hosted_by"] == "github"
    assert "server:local" in d["links"] and d["details"]["hosted_by"] == "server"          # its A record is this server
    hst = {"connected": True, "domains": [{"name": "example.net", "status": "active",
                                           "dns": [{"type": "A", "name": "example.net", "content": "203.0.113.50"}]}]}
    d2 = {r["id"]: r for r in build.build(probes, [], {}, hst, {}, {}, "/w", None, dns=cache)}["domain:example.net"]
    assert d2["details"]["dns"] == "namecheap" and d2["details"]["unused_zone"] == "hostinger"   # name servers win
    assert "server:local" in d2["links"]                                                      # public A, not the unused zone
    names = dict(build.hosts_to_resolve(list(res.values())))
    assert names["example.net"] is True and names["www.example.net"] is False

    monkeypatch.setattr(infra, "refresh_in_background", lambda: True)
    config.update_config(infra_page=True)
    assert client.post("/api/infra/domains", json={"name": "acme.example"}).json() == {"name": "acme.example"}
    assert client.post("/api/infra/domains", json={"name": "x"}).status_code == 400
    assert client.post("/api/infra/domains/remove", json={"name": "acme.example"}).status_code == 200
    assert client.post("/api/infra/domains/remove", json={"name": "acme.example"}).status_code == 404


def test_infra_json_cannot_run_commands_through_ssh(org, tmp_path):
    """infra.json is a plain workspace file: an entry the CLI would refuse never reaches ssh, and even then the
    destination is never read as an ssh option."""
    flag = tmp_path / "pwned"
    evil = [{"name": "x", "host": "1.2.3.4", "user": f"-oProxyCommand=touch {flag}"},
            {"name": "y", "host": f"-oProxyCommand=touch {flag}"},
            {"name": "z", "host": "1.2.3.4", "key": f"-oProxyCommand=touch {flag}"},
            {"name": "ok", "host": "192.0.2.1", "user": "deploy", "port": 22}]
    registry.path().write_text(json.dumps({"servers": evil}))
    assert [s["name"] for s in registry.servers()] == ["ok"]
    cmd = infra.ssh_command(evil[0], "true")
    assert cmd[cmd.index("--") + 1].startswith("-oProxyCommand")
    infra.probe_remote(evil[0], {})                               # ssh refuses the odd host name, runs nothing
    assert not flag.exists()
    from maxxing.sessions import spawn
    assert f"Edit(/{config.workspace()}/infra.json)" in spawn.deny_rules({})


def test_path_sites_never_see_the_session(fake_caddy, tmp_path):
    caddy.add_site("app2", port=3101)
    text = (fake_caddy / "maxxing-paths" / "app2.caddy").read_text()
    assert 'header_up Cookie "mx_[A-Za-z0-9_]+=[^;]*;?\\s*" ""' in text and 'header_down Set-Cookie "^mx_' in text
    assert "-Authorization" not in text                  # the app's own logins keep working
    www = tmp_path / "www2"
    www.mkdir()
    caddy.add_site("files2", root=str(www))
    assert "hide .*" in (fake_caddy / "maxxing-paths" / "files2.caddy").read_text()
    ssh = tmp_path / ".ssh"
    ssh.mkdir()
    for bad in (config.workspace(), config.STATE, ssh, config.CODE):
        with pytest.raises(caddy.CaddyError):
            caddy.add_site("bad", root=str(bad))
    spaced = tmp_path / "with space"
    spaced.mkdir()
    with pytest.raises(caddy.CaddyError):
        caddy.add_site("bad", root=str(spaced))
    with pytest.raises(caddy.CaddyError):
        caddy.add_site("bad", port=3102, project="x\n}\nimport /etc/*")


def test_odd_hosts_and_providers_never_stop_a_refresh(org, monkeypatch):
    for url in ("https://.example.com/", "https://" + "a" * 64 + ".com/", "https://a..b/"):
        assert infra.check_url(url)["status"] in ("unknown", "down")
    conf = "server {\n listen 80;\n server_name .example.com ~^www\\d+\\.x$;\n root /srv/x;\n}\n"
    assert {x["host"] for x in probe.parse_nginx(conf)} == {"example.com"}
    monkeypatch.setenv("MAXXING_INFRA_CHECKS", "0")
    monkeypatch.setattr(infra, "probe_local", lambda opts: _probes(str(org.ws))["local"])

    def boom():
        raise ValueError("maintenance page")
    monkeypatch.setattr(providers, "cloudflare", boom)
    monkeypatch.setattr(providers, "hostinger", lambda: {"connected": False, "key": None})
    snap = infra.refresh()
    assert snap and any(r["id"] == "site:local:shop.example.com" for r in snap["resources"])


def test_connect_guards(org, tmp_path, monkeypatch):
    """One connect per target, a bounded number at once, and odd failures as clean errors (never a 500)."""
    import threading as _th
    from maxxing.infra import connect
    gate, started = _th.Event(), _th.Event()

    def slow(host, user="root", port=22, key=""):
        started.set()
        gate.wait(5)
        return "denied"
    monkeypatch.setattr(connect, "can_login", slow)
    monkeypatch.setattr(connect, "ensure_key", lambda: (tmp_path / "k", "ssh-ed25519 AAAAx harness"))
    t = _th.Thread(target=lambda: pytest.raises(connect.ConnectError, connect.connect_host, "203.0.113.7"))
    t.start()
    assert started.wait(5)
    with pytest.raises(connect.ConnectError) as e:
        connect.connect_host("203.0.113.7")
    assert e.value.code == "in_progress"
    gate.set()
    t.join(5)
    with pytest.raises(connect.ConnectError) as e:              # the line to paste limits the key (tunnels and pty still work)
        connect.connect_host("203.0.113.7")
    assert e.value.code == "need_key" and "no-agent-forwarding,no-X11-forwarding ssh-ed25519" in e.value.extra["command"]
    monkeypatch.undo()
    monkeypatch.setattr(connect.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("ssh-keygen")))
    with pytest.raises(connect.ConnectError) as e:
        connect.ensure_key()
    assert e.value.code == "no_key"


def test_refused_hand_written_server_is_kept_but_never_used(org):
    """An entry ssh would read as an option is ignored - and stays in infra.json (to fix), not erased by the next
    write."""
    import json
    registry.add_server("good", "198.51.100.10")
    d = json.loads(registry.path().read_text())
    d["servers"].append({"name": "evil", "host": "-oProxyCommand=touch /tmp/x"})
    registry.path().write_text(json.dumps(d))
    assert [s["name"] for s in registry.servers()] == ["good"]
    registry.add_server("other", "198.51.100.11")
    kept = [s["name"] for s in json.loads(registry.path().read_text())["servers"]]
    assert kept == ["good", "other", "evil"] and [s["name"] for s in registry.servers()] == ["good", "other"]


def test_url_check_reads_headers_only_and_is_bounded(monkeypatch):
    """Audit F17: a monitored site answering a huge body, or dribbling its headers, costs neither memory nor more than
    CHECK_TOTAL_S. Bounded payload: 1 MB of body then a stall (a client that reads bodies waits for the rest)."""
    import socket as so
    import threading as th
    lsock = so.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(8)
    lsock.settimeout(30)
    port = lsock.getsockname()[1]
    stop = th.Event()

    def serve():
        while not stop.is_set():
            try:
                conn, _ = lsock.accept()
            except OSError:
                return
            req = conn.recv(4096)
            try:
                if b"/slow" in req:                       # headers one byte every 0.5 s
                    for ch in b"HTTP/1.1 200 OK\r\nX-Pad: " + b"a" * 40:
                        if stop.is_set():
                            break
                        conn.sendall(bytes([ch]))
                        time.sleep(0.5)
                else:                                     # announces 10 GB, sends 1 MB, then stalls
                    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 10000000000\r\n\r\n")
                    conn.sendall(b"x" * (1024 * 1024))
                    stop.wait(15)
            except OSError:
                pass
            finally:
                conn.close()
    t = th.Thread(target=serve, daemon=True)
    t.start()
    try:
        t0 = time.time()
        r = infra.check_url(f"http://127.0.0.1:{port}/huge")
        assert r["status"] == "ok" and r["code"] == 200 and time.time() - t0 < 3     # headers only, closed at once
        monkeypatch.setattr(infra, "CHECK_TOTAL_S", 2.0)
        t0 = time.time()
        r = infra.check_url(f"http://127.0.0.1:{port}/slow")
        assert r["status"] == "down" and time.time() - t0 < 4
    finally:
        stop.set()
        lsock.close()
        t.join(5)


def test_garage_download_is_verified_by_sha256(monkeypatch, tmp_path):
    """Audit F18: a Garage binary that does not match the pinned sha256 is never installed (nor left executable)."""
    import hashlib
    from pathlib import Path as P
    from maxxing.infra import actions
    payload = b"\x7fELF not really garage"

    class Resp:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def iter_bytes(self): yield payload[:5]; yield payload[5:]

    class Stop(Exception):
        pass

    class SafePath(type(P())):            # the steps after the binary must never touch /var/lib or /etc here
        def mkdir(self, *a, **k):
            raise Stop()
    monkeypatch.setattr(actions, "Path", SafePath)
    monkeypatch.setattr(actions.httpx, "stream", lambda *a, **k: Resp())
    monkeypatch.setattr(actions, "garage_installed", lambda: False)
    monkeypatch.setattr(actions.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(actions, "GARAGE_BIN", str(tmp_path / "garage"))
    (conf := tmp_path / "garage.toml").write_text("")
    monkeypatch.setattr(actions, "GARAGE_CONF", str(conf))
    with pytest.raises(actions.ActionError) as e:
        actions.garage_install()
    assert e.value.code == "checksum_mismatch"
    assert sorted(x.name for x in tmp_path.iterdir()) == ["garage.toml"]           # no binary, no .part
    # the pinned build goes through (and the install carries on to the next step)
    monkeypatch.setattr(actions, "GARAGE_SHA256", {"x86_64": hashlib.sha256(payload).hexdigest()})
    with pytest.raises(Stop):
        actions.garage_install()
    assert (tmp_path / "garage").read_bytes() == payload and (tmp_path / "garage").stat().st_mode & 0o777 == 0o755


def test_odd_rdap_and_doh_answers_never_stop_a_refresh(org, monkeypatch):
    from maxxing.infra import dnsinfo, platforms
    rdap = {"/domain/list.example": [],
            "/domain/vcard.example": {"entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}]]]}]}}
    s = _Server(lambda method, path, headers, body: _json(200, rdap.get(path, {"events": "x"})))
    d = _Server(lambda method, path, headers, body: _json(200, [] if "list" in path else {"Answer": [{"type": 1}]}))
    monkeypatch.setenv("MAXXING_RDAP_API", s.url)
    monkeypatch.setenv("MAXXING_DOH_API", d.url + "/dns-query")
    try:
        assert providers.rdap_expiry("list.example")["error"] == "bad_answer"
        r = providers.rdap_expiry("vcard.example")                  # short vCard entry: skipped, not a crash
        assert r["registrar"] is None and "error" not in r
        assert "error" in dnsinfo.resolve("list.example", True)      # DoH answers a list, or records without data
        r = dnsinfo.resolve("vcard.example", True)
        assert (r["ns"], r["cname"], r["a"]) == ([], [], [])
        for name in ("list.example", "vcard.example"):
            registry.add_domain(name)
        monkeypatch.setattr(infra, "probe_local", lambda opts: _probes(str(org.ws))["local"])
        monkeypatch.setattr(infra, "run_checks", lambda res: None)
        monkeypatch.setattr(providers, "cloudflare", lambda: {"connected": False, "key": None})
        monkeypatch.setattr(providers, "hostinger", lambda: {"connected": False, "key": None})
        monkeypatch.setattr(platforms, "read_all", lambda: {})
        snap = infra.refresh()
        assert snap and {"domain:list.example", "domain:vcard.example"} <= {r["id"] for r in snap["resources"]}
    finally:
        s.close()
        d.close()


def test_rdap_date_that_is_not_a_date_never_breaks_the_build(org, monkeypatch):
    """eventDate NaN / Infinity (Python reads them in JSON) or a word: refused as a bad answer, and a value of that
    kind already saved in rdap.json no longer makes every build fail."""
    def answer(method, path, headers, body):
        date = {"/domain/nan.example": float("nan"), "/domain/inf.example": float("inf")}.get(path, "soon")
        return _json(200, {"events": [{"eventAction": "expiration", "eventDate": date}],
                           "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", 7]]]}]})
    s = _Server(answer)
    monkeypatch.setenv("MAXXING_RDAP_API", s.url)
    try:
        for name in ("nan.example", "inf.example", "word.example"):
            r = providers.rdap_expiry(name)
            assert r["expires"] is None and r["error"] == "bad_answer", name
    finally:
        s.close()
    assert build._ts(float("nan")) is None and build._ts(float("inf")) is None
    assert build._ts("2027-01-02T00:00:00Z") == 1798848000


def test_rdap_deadline_is_checked_before_each_request(org, monkeypatch):
    """The total deadline covers every request (redirects included), not only the reading of a body."""
    hits = []
    s = _Server(lambda method, path, headers, body: (hits.append(path), _json(200, {}))[1])
    monkeypatch.setenv("MAXXING_RDAP_API", s.url)
    monkeypatch.setattr(providers, "RDAP_TOTAL_S", -1)
    try:
        assert providers.rdap_expiry("late.example")["error"] == "unreachable" and hits == []
    finally:
        s.close()


def test_failed_rdap_lookup_is_retried_within_the_day(org, monkeypatch):
    from maxxing.infra import dnsinfo, platforms
    calls = []

    def rdap(name):
        calls.append(name) if name == "flaky.example" else None
        return {"expires": None, "registrar": None, "checked": int(time.time()), "error": "unreachable"}
    registry.add_domain("flaky.example")
    monkeypatch.setattr(providers, "rdap_expiry", rdap)
    monkeypatch.setattr(dnsinfo, "refresh_cache", lambda cache, names: cache)
    monkeypatch.setattr(infra, "probe_local", lambda opts: _probes(str(org.ws))["local"])
    monkeypatch.setattr(infra, "run_checks", lambda res: None)
    monkeypatch.setattr(providers, "cloudflare", lambda: {"connected": False, "key": None})
    monkeypatch.setattr(providers, "hostinger", lambda: {"connected": False, "key": None})
    monkeypatch.setattr(platforms, "read_all", lambda: {})
    infra.refresh()
    infra.refresh()
    assert calls == ["flaky.example"]                                          # just failed: not asked again at once
    cache = config.read_json(infra._dir() / "rdap.json", {})
    cache["flaky.example"]["checked"] -= 2 * 3600
    config.write_json(infra._dir() / "rdap.json", cache)
    infra.refresh()
    assert calls == ["flaky.example"] * 2                                      # 2 h later: asked again, not after 24 h


def _raw_http(*answers: list):
    """Raw HTTP server: the n-th connection gets answers[n], a list of byte chunks (a float = a pause in seconds)."""
    import socket
    import threading
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)

    def run():
        for parts in answers:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            try:
                conn.recv(65536)
                for part in parts:
                    time.sleep(part) if isinstance(part, float) else conn.sendall(part)
            except OSError:
                pass
            finally:
                conn.close()
    threading.Thread(target=run, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.getsockname()[1]}"


def test_rdap_lookup_is_capped_and_redirects_stay_on_https(monkeypatch):
    monkeypatch.setattr(providers, "RDAP_TOTAL_S", 1.0, raising=False)
    body = json.dumps({"events": [{"eventAction": "expiration", "eventDate": "2030-01-01T00:00:00Z"}]}).encode()

    def ok(payload: bytes) -> bytes:
        return b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(payload) + payload

    big = body + b" " * (3 << 20)                       # valid JSON, 3 MB
    slow = [b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body)] + [x for c in body for x in (bytes([c]), 0.03)]
    cases = [
        [[ok(big)]],                                     # an answer far above the cap
        [slow],                                          # an answer dribbled past the total deadline
        [[b"HTTP/1.1 302 Found\r\nLocation: /next\r\nContent-Length: 0\r\n\r\n"], [ok(body)]],  # redirect to http
    ]
    for answers in cases:
        srv, url = _raw_http(*answers)
        monkeypatch.setenv("MAXXING_RDAP_API", url)
        try:
            t0 = time.time()
            out = providers.rdap_expiry("example.com")
            assert out["expires"] is None and out.get("error") == "unreachable", out
            assert time.time() - t0 < 2.5
        finally:
            srv.close()
    srv, url = _raw_http([ok(body)])
    monkeypatch.setenv("MAXXING_RDAP_API", url)
    try:
        assert providers.rdap_expiry("example.com")["expires"] == "2030-01-01T00:00:00Z"
    finally:
        srv.close()


def test_names_with_a_trailing_newline_are_refused():
    for rx in (actions.DB_NAME_RE, actions.BUCKET_RE, registry.NAME_RE, registry.DOMAIN_RE):
        assert not rx.match("abcd\n") and not rx.match("abc.com\n")
    with pytest.raises(actions.ActionError):
        actions.pg_create("app\n")
    with pytest.raises(actions.ActionError):
        actions.bucket_create("media\n")
    with pytest.raises(registry.RegistryError):
        registry.check_server("srv\n", "1.2.3.4", key_must_exist=False)
    with pytest.raises(registry.RegistryError):
        registry.check_server("srv", "1.2.3.4\n", key_must_exist=False)


def test_rotation_keeps_the_backups_of_a_database_sharing_the_prefix(monkeypatch, tmp_path):
    bk = tmp_path / "bk"
    bk.mkdir()
    monkeypatch.setenv("MAXXING_INFRA_BACKUP_DIR", str(bk))
    for i in range(actions.KEEP_BACKUPS + 2):
        for name in ("pg-app", "pg-app-v2", "sqlite-a[1]"):
            f = bk / f"{name}-202610{10 + i:02d}-0330.dump"
            f.write_bytes(b"x")
            os.utime(f, (1_000_000 + i, 1_000_000 + i))
    actions._rotate("pg-app")
    actions._rotate("sqlite-a[1]")
    names = [p.name for p in bk.iterdir()]
    assert sum(n.startswith("pg-app-v2-") for n in names) == actions.KEEP_BACKUPS + 2
    assert sum(n.startswith("pg-app-2") for n in names) == actions.KEEP_BACKUPS
    assert sum(n.startswith("sqlite-a[1]-") for n in names) == actions.KEEP_BACKUPS
