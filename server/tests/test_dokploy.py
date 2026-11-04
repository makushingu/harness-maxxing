"""maxxing.dokploy against a local fake Dokploy API (shapes of the Dokploy OpenAPI / @dokploy/mcp schemas)."""
import json

import pytest

from _conn_helpers import _Server
from _org_helpers import org  # noqa: F401
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
        if proc == "project.all":
            return 200, PROJECTS, "application/json"
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


@pytest.mark.parametrize("u", ["ftp://h", "http://dokploy.example.com", "https://u:p@h.example.com", "", "h:3000"])
def test_check_url_refuses_unsafe_urls(u):
    with pytest.raises(ProviderError) as e:
        dokploy.check_url(u)
    assert e.value.code == "invalid_url"


@pytest.mark.parametrize("u", ["http://127.0.0.1:3000/", "http://10.0.0.5:3000", "http://dokploy.localhost",
                               "https://dokploy.example.com"])
def test_check_url_accepts_local_http_and_any_https(u):
    assert dokploy.check_url(u) == u.rstrip("/")


def test_connect_checks_the_key_then_saves_it_unexposed(fake):
    with pytest.raises(ProviderError) as e:
        dokploy.connect(fake.url, "wrong")
    assert e.value.code == "missing_permission" and vault.get(dokploy.KEY) is None
    assert dokploy.connect(fake.url, KEY) == {"connected": True, "url": fake.url, "projects": 2}
    assert config.load_config()["dokploy"] == {"url": fake.url}
    assert dokploy.KEY not in vault.exposed_env()                  # sessions never see it
    assert dokploy.status() == {"connected": True, "url": fake.url}
    assert dokploy.disconnect() and vault.get(dokploy.KEY) is None and "dokploy" not in config.load_config()
    with pytest.raises(ProviderError) as e:
        dokploy.client()
    assert e.value.code == "not_connected"


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
