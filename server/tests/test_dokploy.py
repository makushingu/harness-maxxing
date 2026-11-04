"""maxxing.dokploy against a local fake Dokploy API (shapes of the Dokploy OpenAPI / @dokploy/mcp schemas)."""
import json

import pytest

from _conn_helpers import _Server
from _org_helpers import client, org  # noqa: F401
from maxxing import config, dokploy, vault
from maxxing.infra.providers import ProviderError

KEY = "dk-test-key"

PROJECTS = [{"projectId": "p1", "name": "acme", "environments": [{
    "environmentId": "e1", "name": "production",
    "applications": [{"applicationId": "a1", "name": "web", "appName": "acme-web-x1", "applicationStatus": "done",
                      "buildType": "nixpacks", "owner": "acme", "repository": "web",
                      "domains": [{"host": "web.example.com", "https": True, "port": 3000, "path": "/"}]},
                     {"applicationId": "a2", "name": "api", "appName": "acme-api-x2", "applicationStatus": "error",
                      "customGitUrl": "https://git.example.com/acme/api.git", "domains": []}],
    "compose": [{"composeId": "c1", "name": "stack", "appName": "acme-stack", "composeStatus": "running"}],
    "postgres": [{"postgresId": "pg1", "name": "db", "appName": "acme-db"}]}]},
    {"projectId": "p2", "name": "old", "applications": [{"applicationId": "a3", "name": "web", "appName": "old-web",
                                                         "applicationStatus": "idle"}]}]


def _all(projects, plural):
    for p in projects:
        for e in p.get("environments") or [p]:
            yield from e.get(plural) or []


def _slim(projects):
    """What project.all really gives (Dokploy v0.30): no app name, domains nor git source on apps / compose."""
    keep = {"applications": ("applicationId", "name", "applicationStatus"), "compose": ("composeId", "name", "composeStatus")}

    def env(e):
        return {k: ([{f: x[f] for f in keep[k] if f in x} for x in v] if k in keep else v) for k, v in e.items()}
    return [{**p, **({"environments": [env(e) for e in p["environments"]]} if "environments" in p else env(p))}
            for p in projects]


class FakeDokploy:
    def __init__(self, logs=None):
        self.calls: list[tuple[str, str, dict]] = []
        self.logs = logs
        self.s = _Server(self.handle)
        self.url = self.s.url

    def handle(self, method, path, headers, body):
        if headers.get("x-api-key") != KEY:
            return 401, {"message": "Unauthorized"}, "application/json"
        proc, _, query = path.removeprefix("/api/").partition("?")
        data = json.loads(body) if body else {}
        self.calls.append((method, proc, data or dict(q.split("=") for q in query.split("&") if q)))
        if proc == "project.all":                          # v0.30: apps and stacks carry only id, name and state
            return 200, _slim(PROJECTS), "application/json"
        if proc in ("application.one", "compose.one"):
            key = "applicationId" if proc == "application.one" else "composeId"
            want = self.calls[-1][2].get(key)
            for x in _all(PROJECTS, "applications" if key == "applicationId" else "compose"):
                if x[key] == want:
                    return 200, x, "application/json"
            return 404, {"message": "not found"}, "application/json"
        if proc == "application.create":
            return 200, {"applicationId": "new1", "name": data["name"]}, "application/json"
        if proc == "deployment.all":
            return 200, [{"deploymentId": "d1", "title": "old", "status": "done", "createdAt": "2026-10-01T10:00:00Z",
                          "logPath": str(self.logs / "acme-web-x1" / "d1.log") if self.logs else None},
                         {"deploymentId": "d2", "title": "new", "status": "error", "createdAt": "2026-11-01T10:00:00Z",
                          "logPath": "/elsewhere/d2.log"}], "application/json"
        if proc in ("application.deploy", "application.redeploy", "compose.deploy", "domain.create",
                    "application.saveGitProvider", "application.saveBuildType"):
            return 200, b"", "application/json"
        return 404, {"message": "no such procedure"}, "application/json"

    def close(self):
        self.s.close()


@pytest.fixture
def fake(org, tmp_path, monkeypatch):
    logs = tmp_path / "dokploy-logs"
    monkeypatch.setenv("MAXXING_DOKPLOY_LOGS", str(logs))
    f = FakeDokploy(logs)
    yield f
    f.close()


@pytest.mark.parametrize("u", ["ftp://h", "http://dokploy.example.com", "https://u:p@h.example.com", "", "h:3000",
                               "http://169.254.169.254", "http://127.0.0.1:99999"])
def test_check_url_refuses_unsafe_urls(u):
    with pytest.raises(ProviderError) as e:
        dokploy.check_url(u)
    assert e.value.code == "invalid_url"


@pytest.mark.parametrize("u", ["http://127.0.0.1:3000/", "http://10.0.0.5:3000", "http://dokploy.localhost",
                               "https://dokploy.example.com", "http://100.101.102.103:3000"])
def test_check_url_accepts_local_http_and_any_https(u):
    assert dokploy.check_url(u) == u.rstrip("/")


def test_connect_checks_the_key_then_saves_it_unexposed(fake):
    with pytest.raises(ProviderError) as e:
        dokploy.connect(fake.url, "wrong")
    assert e.value.code == "missing_permission" and vault.get(dokploy.KEY) is None
    assert dokploy.connect(fake.url, KEY) == {"connected": True, "url": fake.url, "projects": 2}
    assert config.get_secret(dokploy.URL_SECRET) == fake.url and "dokploy" not in config.load_config()
    assert dokploy.KEY not in vault.exposed_env()                  # sessions never see it
    assert dokploy.status() == {"connected": True, "url": fake.url}
    assert dokploy.disconnect() and vault.get(dokploy.KEY) is None and not config.get_secret(dokploy.URL_SECRET)
    with pytest.raises(ProviderError) as e:
        dokploy.client()
    assert e.value.code == "not_connected"


def test_the_key_only_goes_to_the_url_it_was_checked_against(fake, monkeypatch):
    """A session setting an env variable or editing config.json cannot send the key to another host."""
    dokploy.connect(fake.url, KEY)
    monkeypatch.setenv("MAXXING_DOKPLOY_API", "https://attacker.example")
    config.update_config(dokploy={"url": "https://attacker.example"})
    assert dokploy.url() == fake.url and dokploy.client().base == fake.url + "/api/"


def test_services_flatten_environments_and_old_projects(fake):
    dokploy.connect(fake.url, KEY)
    with dokploy.client() as c:
        svcs = dokploy.inventory(c)
    by = {s["id"]: s for s in svcs}
    assert set(by) == {"a1", "a2", "c1", "pg1", "a3"}
    assert by["a1"]["repo"] == "acme/web" and by["a1"]["domains"][0]["host"] == "web.example.com"
    assert by["a2"]["repo"] == "https://git.example.com/acme/api.git" and by["a2"]["status"] == "error"
    assert by["c1"]["status"] == "running" and by["pg1"]["kind"] == "postgres"
    assert by["a3"]["environment"] is None and by["a1"]["environment"] == "production"
    assert dokploy.find(svcs, "acme-api-x2")["id"] == "a2"
    assert dokploy.environments(PROJECTS) == [{"id": "e1", "name": "production", "project": "acme", "project_id": "p1"}]
    with pytest.raises(ProviderError) as e:
        dokploy.find(svcs, "web")                                  # two projects have one
    assert e.value.code == "ambiguous" and "a1" in e.value.message and "a3" in e.value.message
    with pytest.raises(ProviderError) as e:
        dokploy.find(svcs, "nope")
    assert e.value.code == "not_found"


def test_writes_send_the_documented_bodies(fake):
    dokploy.connect(fake.url, KEY)
    with dokploy.client() as c:
        svcs = dokploy.inventory(c)
        dokploy.deploy(c, dokploy.find(svcs, "a1"), title="from harness")
        dokploy.deploy(c, dokploy.find(svcs, "c1"))
        dokploy.domain_add(c, dokploy.find(svcs, "a2"), "API.example.com", port=8080)
        with pytest.raises(ProviderError) as e:
            dokploy.deploy(c, dokploy.find(svcs, "pg1"))
        assert e.value.code == "not_deployable"
        assert dokploy.app_create(c, "e1", "blog", "https://github.com/acme/blog.git", build="dockerfile") == "new1"
        with pytest.raises(ProviderError):
            dokploy.app_create(c, "e1", "x", "https://github.com/acme/x.git", build="magic")
    posts = {proc: body for m, proc, body in fake.calls if m == "POST"}
    assert posts["application.deploy"] == {"applicationId": "a1", "title": "from harness"}
    assert posts["compose.deploy"] == {"composeId": "c1"}
    assert posts["domain.create"] == {"host": "api.example.com", "https": True, "certificateType": "letsencrypt",
                                      "domainType": "application", "applicationId": "a2", "port": 8080}
    assert posts["application.create"] == {"name": "blog", "environmentId": "e1"}
    assert posts["application.saveGitProvider"]["customGitUrl"] == "https://github.com/acme/blog.git"
    assert posts["application.saveBuildType"]["buildType"] == "dockerfile"


def test_deployment_logs_are_read_only_from_the_dokploy_log_folder(fake):
    (fake.logs / "acme-web-x1").mkdir(parents=True)
    (fake.logs / "acme-web-x1" / "d1.log").write_text("".join(f"line {i}\n" for i in range(500)))
    dokploy.connect(fake.url, KEY)
    with dokploy.client() as c:
        deps = dokploy.deployments(c, dokploy.find(dokploy.inventory(c), "a1"))
    assert [d["id"] for d in deps] == ["d2", "d1"]                 # newest first
    assert dokploy.log(deps[1], lines=3) == "line 497\nline 498\nline 499"
    with pytest.raises(ProviderError) as e:
        dokploy.log(deps[0])
    assert e.value.code == "remote_log"


def run(monkeypatch, *argv, stdin=""):
    import io
    from maxxing import cli
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return cli.main(["dokploy", *argv])


def test_cli_connects_lists_and_asks_yes_before_writing(fake, monkeypatch, capsys):
    assert run(monkeypatch, "status") == 1
    assert run(monkeypatch, "list") == 2                           # not connected
    assert "not_connected" in capsys.readouterr().err
    assert run(monkeypatch, "connect", "--url", fake.url, stdin=KEY + "\n") == 0
    assert vault.get(dokploy.KEY) == KEY
    capsys.readouterr()
    assert run(monkeypatch, "list") == 0
    out = capsys.readouterr().out
    assert "web.example.com" in out and "acme/production" in out and KEY not in out
    assert run(monkeypatch, "deploy", "a1") == 3                   # no --yes: nothing sent
    assert not [c for c in fake.calls if c[1] == "application.deploy"]
    assert run(monkeypatch, "deploy", "acme-web-x1", "--yes") == 0
    assert [c[2] for c in fake.calls if c[1] == "application.deploy"] == [{"applicationId": "a1"}]
    assert run(monkeypatch, "deploy", "web", "--yes") == 2         # ambiguous name: nothing sent
    assert "ambiguous" in capsys.readouterr().err
    assert run(monkeypatch, "domain", "add", "a1", "www.example.com", "--yes") == 0
    assert run(monkeypatch, "disconnect") == 0 and vault.get(dokploy.KEY) is None


def test_infra_reads_dokploy_as_a_platform(fake):
    from maxxing.infra import build, platforms
    assert platforms.dokploy() == {"connected": False, "key": None}
    dokploy.connect(fake.url, KEY)
    d = platforms.dokploy()
    sites = {x["id"]: x for x in d["sites"]}
    assert sites["a1"]["urls"] == ["https://web.example.com/"] and sites["a1"]["repo"] == "acme/web"
    assert sites["a1"]["state"] == "ok" and sites["a2"]["state"] == "failed" and sites["a2"]["repo"] is None
    assert sites["c1"]["state"] == "building" and sites["a3"]["state"] == "paused"
    assert d["databases"] == [{"id": "postgres:pg1", "name": "db", "engine": "postgres", "state": "unknown",
                               "dashboard": None, "group": "p1"}]                # a loopback address opens nowhere
    state = platforms.source_state({"dokploy": d})["dokploy"]
    assert state["beta"] and state["url"] == fake.url and state["sections"] == {"sites": "ok", "databases": "ok"}
    res = {r["id"]: r for r in build.build({build.LOCAL: {}}, [], {}, {}, {}, {}, "/w", None, platforms={"dokploy": d})}
    assert res["pages:dokploy:a2"]["status"] == "down" and res["pages:dokploy:a1"]["details"]["repo"]["git"] == "github:acme/web"
    assert "db:dokploy:postgres:pg1" in res
    vault.put(dokploy.KEY, "revoked", expose=False)
    assert platforms.dokploy()["sites"]["error"] == "missing_permission"


def test_infra_api_connects_dokploy(fake, client):
    config.update_config(infra_page=True)
    r = client.post("/api/infra/dokploy/connect", json={"url": "http://dokploy.example.com", "key": KEY})
    assert r.status_code == 422 and r.json()["error"] == "invalid_url"
    r = client.post("/api/infra/dokploy/connect", json={"url": fake.url, "key": KEY})
    assert r.status_code == 200 and r.json()["projects"] == 2
    assert client.post("/api/infra/dokploy/disconnect").json() == {"removed": True}


def test_host_sites_are_refused_when_traefik_owns_80_443(org, tmp_path, monkeypatch):
    from maxxing.infra import caddy
    route = tmp_path / "harness-maxxing.yml"
    route.write_text("# Harness Maxxing\n")
    monkeypatch.setenv("MAXXING_TRAEFIK_ROUTE", str(route))
    monkeypatch.setenv("MAXXING_CADDY_DIR", str(tmp_path / "caddy"))
    with pytest.raises(caddy.CaddyError) as e:
        caddy.add_site("shop", port=3100, host="shop.example.com")
    assert e.value.code == "behind_traefik"


def test_deps_pin_dokploy_and_never_remove_it():
    from maxxing import deps
    c = deps.get("dokploy")
    assert c["update"] == "manual" and c["url"].startswith("https://raw.githubusercontent.com/Dokploy/website/")
    assert "{" not in c["url"] and len(deps.sha_of(c, "x86_64")) == 64
    with pytest.raises(deps.DepError):
        deps.remove("dokploy", force=True)
    assert deps.owned_paths("dokploy") == []                       # its 777 /etc/dokploy is not ours to judge


def test_doctor_checks_dokploy(fake, monkeypatch, tmp_path):
    from maxxing import cmd_core
    monkeypatch.setenv("MAXXING_TRAEFIK_ROUTE", str(tmp_path / "none.yml"))
    monkeypatch.setenv("MAXXING_DOKPLOY_ETC", str(tmp_path / "no-dokploy"))
    monkeypatch.setattr(cmd_core, "_public_tcp_ports", lambda: set())
    assert cmd_core.check_dokploy() is None                        # no Dokploy here, none connected
    dokploy.connect(fake.url, KEY)
    c = cmd_core.check_dokploy()
    assert c["level"] == "ok" and "2 projects" in c["title"]
    monkeypatch.setattr(cmd_core, "_public_tcp_ports", lambda: {22, 80, 443, 3000})
    assert cmd_core.check_dokploy()["level"] == "ok"               # Dokploy elsewhere: 3000 here is another program
    (tmp_path / "no-dokploy" / "traefik").mkdir(parents=True)      # Dokploy on this server
    c = cmd_core.check_dokploy()
    assert c["level"] == "warn" and "port 3000" in c["title"] and "2 projects" in c["detail"]
    vault.put(dokploy.KEY, "revoked", expose=False)
    c = cmd_core.check_dokploy()
    assert c["level"] == "warn" and "missing_permission" in c["title"]   # not hidden by the open port


def test_public_ports_ignore_loopback(monkeypatch):
    from maxxing import cmd_core
    out = ("LISTEN 0 4096 0.0.0.0:3000 0.0.0.0:*\nLISTEN 0 4096 127.0.0.1:8787 0.0.0.0:*\n"
           "LISTEN 0 4096 [::1]:2019 [::]:*\nLISTEN 0 4096 [::]:443 [::]:*\n")
    monkeypatch.setattr(cmd_core, "_run_ok", lambda cmd: (True, out))
    assert cmd_core._public_tcp_ports() == {3000, 443}


def test_deps_status_trusts_the_dokploy_version_it_runs(monkeypatch):
    from maxxing import deps
    real = deps.installed
    monkeypatch.setattr(deps, "installed", lambda n: {"version": "v0.31.0", "where": "docker service dokploy",
                                                      "managed": False, "detail": ""} if n == "dokploy" else real(n))
    row = next(r for r in deps.status() if r["name"] == "dokploy")
    assert row["state"] == "ok"                                    # updated from Dokploy's UI: not "outdated"


@pytest.mark.parametrize("kw", [
    {"repo": "--upload-pack=touch /tmp/x"}, {"repo": "ext::sh -c id"}, {"repo": "file:///etc"},
    {"repo": "https://github.com/acme/x.git; rm -rf /"}, {"branch": "-x"}, {"branch": "main dev"},
    {"name": "-rf"}, {"build_path": "/../../etc"},
])
def test_app_create_refuses_values_git_or_dokploy_could_misread(fake, kw):
    dokploy.connect(fake.url, KEY)
    args = {"repo": "https://github.com/acme/x.git", "branch": "main", "name": "x", "build_path": "/", **kw}
    with dokploy.client() as c, pytest.raises(ProviderError) as e:
        dokploy.app_create(c, "e1", args["name"], args["repo"], args["branch"], "nixpacks", args["build_path"])
    assert e.value.code == "invalid_value"
    assert not [x for x in fake.calls if x[1] == "application.create"]  # nothing sent


def test_app_create_accepts_ssh_and_scp_like_urls(fake):
    dokploy.connect(fake.url, KEY)
    with dokploy.client() as c:
        for repo in ("ssh://git@git.example.com/acme/x.git", "git@github.com:acme/x.git"):
            assert dokploy.app_create(c, "e1", "x", repo, "release/1.2") == "new1"


@pytest.mark.parametrize("host, port, path", [("bad host", None, None), ("x.example.com", 70000, None),
                                              ("x.example.com", None, "no-slash"), ("-x.example.com", None, None)])
def test_domain_add_refuses_bad_values(fake, host, port, path):
    dokploy.connect(fake.url, KEY)
    with dokploy.client() as c, pytest.raises(ProviderError):
        dokploy.domain_add(c, dokploy.find(dokploy.inventory(c), "a1"), host, port, True, path)


def test_a_compose_domain_needs_its_service(fake):
    dokploy.connect(fake.url, KEY)
    with dokploy.client() as c:
        stack = dokploy.find(dokploy.inventory(c), "c1")
        with pytest.raises(ProviderError) as e:
            dokploy.domain_add(c, stack, "stack.example.com", 80)
        assert e.value.code == "service_needed"
        dokploy.domain_add(c, stack, "stack.example.com", 80, service="web")
    body = [x[2] for x in fake.calls if x[1] == "domain.create"][-1]
    assert body["serviceName"] == "web" and body["composeId"] == "c1" and body["domainType"] == "compose"


def test_logs_refuse_paths_that_leave_the_dokploy_folder(fake, tmp_path):
    fake.logs.mkdir(parents=True, exist_ok=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("root only\n")
    (fake.logs / "link.log").symlink_to(secret)
    for p in (fake.logs / ".." / "secret.txt", fake.logs / "link.log"):
        with pytest.raises(ProviderError) as e:
            dokploy.log({"log_path": str(p)})
        assert e.value.code == "remote_log"


def test_cli_environments_and_domain_list(fake, monkeypatch, capsys):
    assert run(monkeypatch, "connect", "--url", fake.url, stdin=KEY) == 0
    capsys.readouterr()
    assert run(monkeypatch, "environments", "--json") == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "e1"
    assert run(monkeypatch, "domain", "list", "a1") == 0
    assert "web.example.com" in capsys.readouterr().out
    assert run(monkeypatch, "deployments", "a1", "--json") == 0
    assert [d["id"] for d in json.loads(capsys.readouterr().out)] == ["d2", "d1"]


def test_uninstall_removes_only_our_traefik_route_and_drop_in(org, tmp_path, monkeypatch):
    from maxxing import cmd_core
    route, dropin = tmp_path / "route.yml", tmp_path / "20-harness-docker.conf"
    monkeypatch.setenv("MAXXING_TRAEFIK_ROUTE", str(route))
    monkeypatch.setenv("MAXXING_CADDY_DOCKER_DROPIN", str(dropin))
    monkeypatch.setattr(cmd_core, "systemctl", lambda *a, **k: (0, ""))
    monkeypatch.setattr(cmd_core, "CADDY_SITE", tmp_path / "none.caddy")
    monkeypatch.setattr(cmd_core, "CADDYFILE", tmp_path / "Caddyfile")
    route.write_text("# someone else's route\n")
    dropin.write_text("# Harness Maxxing (install.sh)\n")
    cmd_core.remove_caddy_site()
    assert route.exists() and not dropin.exists()                  # never another program's file
    route.write_text('# Harness Maxxing\n          - url: "http://172.17.0.1:8790"\n')
    cmd_core.remove_caddy_site()
    assert not route.exists()


def test_check_security_explains_a_firewall_left_off_for_docker(monkeypatch):
    from maxxing import cmd_core
    monkeypatch.setattr(cmd_core, "_run_ok", lambda cmd: (cmd[0] == "systemctl", ""))
    monkeypatch.setattr(cmd_core.shutil, "which", lambda n: "/usr/bin/docker" if n == "docker" else None)
    assert cmd_core.check_security()["level"] == "info"
    monkeypatch.setattr(cmd_core.shutil, "which", lambda n: None)
    assert cmd_core.check_security()["level"] == "warn"
