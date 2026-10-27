"""Security hardening: login throttle, file-site token scope, file headers, webhook body cap,
extension paths, response headers, reserved vault names, imported Claude settings."""
from __future__ import annotations

import time
from pathlib import Path, PurePosixPath

import pytest
from fastapi.testclient import TestClient

from maxxing import feedhooks, importer, security, vault
from maxxing.api import files, filesite, hooks

from test_files import tree  # noqa: F401  (fixture)

H = {"X-Maxxing": "1"}


@pytest.fixture
def anon(mx, monkeypatch):
    """Signed-out client + a counter of password checks (scrypt)."""
    from maxxing.app import create_app
    security.set_password("rightpassword")
    security._fails.clear()
    monkeypatch.setattr(security, "_last_global", 0.0)
    calls: list[str] = []
    real = security.verify_password
    monkeypatch.setattr(security, "verify_password", lambda pw, stored: calls.append(pw) or real(pw, stored))
    with TestClient(create_app()) as c:
        yield c, calls
    security._fails.clear()


# ---- login throttle --------------------------------------------------------------------------
def test_blocked_client_refused_even_with_right_password(anon):
    c, calls = anon
    security._fails["testclient"] = [time.time()] * security.FAIL_MAX
    r = c.post("/api/auth/login", json={"password": "rightpassword"}, headers=H)
    assert r.status_code == 429 and r.json()["error"] == "throttled"
    assert calls == []                                        # refused before scrypt
    security._fails["testclient"] = [time.time() - security.FAIL_WINDOW - 1] * security.FAIL_MAX
    assert c.post("/api/auth/login", json={"password": "rightpassword"}, headers=H).status_code == 200
    assert "testclient" not in security._fails                # a success clears the client


def test_global_cap_slows_everyone_without_locking_out(anon):
    c, calls = anon
    now = time.time()
    for i in range(security.GLOBAL_FAIL_MAX):                 # distributed: one failure per address
        security._fails[f"10.0.{i // 250}.{i % 250}"] = [now]
    assert c.post("/api/auth/login", json={"password": "rightpassword"}, headers=H).status_code == 200
    r = c.post("/api/auth/login", json={"password": "rightpassword"}, headers=H)
    assert r.status_code == 429 and len(calls) == 1            # second check within GLOBAL_GAP_S: refused
    security._last_global = time.time() - security.GLOBAL_GAP_S - 1
    assert c.post("/api/auth/login", json={"password": "rightpassword"}, headers=H).status_code == 200


def test_parallel_attempts_count_up_front_and_old_entries_are_pruned(mx):
    security._fails.clear()
    security._fails["old"] = [time.time() - security.KEEP_S - 1]
    for _ in range(security.FAIL_MAX):                         # none finished yet: all counted
        assert security.begin_attempt("1.2.3.4")[0] is None
    assert security.begin_attempt("1.2.3.4")[0] == "client"
    assert "old" not in security._fails
    security._fails.clear()


# ---- file-site token -------------------------------------------------------------------------
def _site_url(client, path: Path) -> str:
    return client.get("/api/files/site-url", params={"path": str(path)}).json()["url"]



def test_single_file_site_token_never_serves_a_file_under_a_dot_folder(client, tree):  # noqa: F811
    d = tree / ".ssh"
    d.mkdir()
    (d / "id_ed25519").write_text("-----BEGIN " + "OPENSSH PRIVATE KEY-----\nAAAA\n")       # split: no key-shaped literal
    (d / "page.html").write_text("<p>hidden page")
    r = client.get("/api/files/site-url", params={"path": str(d / "id_ed25519")})
    assert r.status_code == 415                                 # only an HTML page gets a site link
    url = _site_url(client, d / "page.html")                    # a page under a dot folder: single-file token
    client.cookies.clear()
    r = client.get(url)
    assert r.status_code == 403 and "hidden page" not in r.text

def test_site_token_never_serves_dotfiles(client, tree):  # noqa: F811
    site = tree / "report"
    (site / ".ssh").mkdir(parents=True)
    (site / ".ssh" / "id_rsa").write_text("KEY")
    (site / ".env").write_text("A=1")
    (site / "page.html").write_text("<p>hi")
    (site / "sub").mkdir()
    (site / "sub" / "index.html").symlink_to(tree / "b.txt")   # index.html leading out of the folder
    url = _site_url(client, site / "page.html")
    base = url.rsplit("/", 1)[0]
    client.cookies.clear()
    assert client.get(url).status_code == 200
    assert client.get(base + "/.ssh/id_rsa").status_code == 403
    assert client.get(base + "/%2Essh/id_rsa").status_code == 403
    assert client.get(base + "/.env").status_code == 403
    assert client.get(base + "/sub/").status_code == 403


@pytest.mark.parametrize("where", ["root", "home"])
def test_site_token_single_file_for_broad_folders(client, tree, monkeypatch, where):  # noqa: F811
    folder = tree if where == "root" else tree / "home"
    folder.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(tree / "home"))
    (folder / "page.html").write_text("<p>hi")
    (folder / "notes.txt").write_text("private")
    url = _site_url(client, folder / "page.html")
    base = url.rsplit("/", 1)[0]
    client.cookies.clear()
    assert client.get(url).status_code == 200
    assert client.get(base + "/notes.txt").status_code == 403


def test_site_token_serves_assets_only(client, tree):  # noqa: F811
    """A folder link serves the page's assets, never notes / code / settings next to it (S1)."""
    site = tree / "report"
    site.mkdir()
    (site / "index.html").write_text("<p>hi")
    for name in ("style.css", "app.js", "pic.png", "font.woff2", "memory.md", "CLAUDE.md", "tool.py", "conf.yaml",
                 "data.json", "accounts.md", "NOTES.md", "export.csv", "notes.txt", "invoice.pdf", "feed.xml"):
        (site / name).write_text("x")
    (site / "img").mkdir()
    (site / "img" / "logo.svg").write_text("<svg/>")
    base = _site_url(client, site / "index.html").rsplit("/", 1)[0]
    client.cookies.clear()
    for name in ("style.css", "app.js", "pic.png", "font.woff2", "img/logo.svg"):
        assert client.get(f"{base}/{name}").status_code == 200, name
    for name in ("memory.md", "CLAUDE.md", "tool.py", "conf.yaml", "data.json", "accounts.md", "NOTES.md",
                 "export.csv", "notes.txt", "invoice.pdf", "feed.xml"):
        assert client.get(f"{base}/{name}").status_code == 403, name


def test_site_token_never_serves_a_topics_notes(client, mx):
    """Audit F03: a page in a topic folder (folder token) cannot read the notes next to it."""
    from maxxing import config
    config.update_config(files_root=str(mx["tmp"]))
    topic = mx["ws"] / "projects" / "acme" / "topics" / "blog"
    topic.mkdir(parents=True)
    (topic / "page.html").write_text("<script>fetch('accounts.md')</script>")
    (topic / "accounts.md").write_text("bank: 1234")
    (topic / "NOTES.md").write_text("private")
    base = _site_url(client, topic / "page.html").rsplit("/", 1)[0]
    client.cookies.clear()
    assert client.get(base + "/page.html").status_code == 200
    assert client.get(base + "/accounts.md").status_code == 403
    assert client.get(base + "/NOTES.md").status_code == 403


def test_site_token_single_file_in_workspace_roots(client, mx):
    """A page at the workspace root, in projects/, a project or its topics/ folder gets its file alone (S1)."""
    from maxxing import config
    config.update_config(files_root=str(mx["tmp"]))
    ws = mx["ws"]
    for folder in (ws, ws / "projects", ws / "projects" / "acme", ws / "projects" / "acme" / "topics"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "page.html").write_text("<p>hi")
        (folder / "data.json").write_text("{}")
        url = _site_url(client, folder / "page.html")
        assert client.get(url).status_code == 200
        assert client.get(url.rsplit("/", 1)[0] + "/data.json").status_code == 403, folder
    topic = ws / "projects" / "acme" / "topics" / "blog"
    topic.mkdir()
    (topic / "page.html").write_text("<p>hi")
    (topic / "style.css").write_text("p{}")
    url = _site_url(client, topic / "page.html")
    assert client.get(url.rsplit("/", 1)[0] + "/style.css").status_code == 200
    (topic / "attachments" / "2026-10").mkdir(parents=True)
    (topic / "attachments" / "2026-10" / "scan.pdf").write_bytes(b"%PDF")
    assert client.get(url.rsplit("/", 1)[0] + "/attachments/2026-10/scan.pdf").status_code == 403
    (topic / "attachments" / "2026-10" / "photo.jpg").write_bytes(b"\xff\xd8")      # pictures sent in a chat: shown
    assert client.get(url.rsplit("/", 1)[0] + "/attachments/2026-10/photo.jpg").status_code == 200
    for name in ("memory.md", "CLAUDE.md", "notes.py", ".env"):                     # notes, code, settings: never
        (topic / name).write_text("x")
        assert client.get(url.rsplit("/", 1)[0] + "/" + name).status_code in (403, 404), name
    (topic / "guide.md").write_text("# notes are never served to a page")
    assert client.get(url.rsplit("/", 1)[0] + "/guide.md").status_code == 403
    att = topic / "attachments" / "2026-10"
    (att / "page.html").write_text("<p>hi")
    url = _site_url(client, att / "page.html")                     # a page among the uploads: alone
    assert client.get(url).status_code == 200
    assert client.get(url.rsplit("/", 1)[0] + "/scan.pdf").status_code == 403


def test_site_token_ends_with_its_session(client, tree):  # noqa: F811
    """Signing out revokes the preview links handed to that session (S1)."""
    (tree / "report").mkdir()
    (tree / "report" / "index.html").write_text("<p>hi")
    url = _site_url(client, tree / "report" / "index.html")
    assert client.get(url).status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get(url).status_code == 403


def test_site_token_dies_with_sessions_not_before(client, tree, monkeypatch):  # noqa: F811
    """Audit F16: when the revocation list overflows, sessions_not_before refuses every older cookie - and every
    older preview link too (they used to come back to life once their revocation was dropped)."""
    (tree / "report").mkdir()
    (tree / "report" / "index.html").write_text("<p>hi")
    url = _site_url(client, tree / "report" / "index.html")
    assert client.get(url).status_code == 200
    monkeypatch.setattr(security, "REVOKED_MAX", 0)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 5)          # the overflow comes a few seconds later
    assert client.post("/api/auth/logout").status_code == 200      # overflow: list dropped, not_before = now
    from maxxing import config
    assert config.load_secrets().get("revoked_sessions") is None
    assert client.get(url).status_code == 403


# ---- headers of user files -------------------------------------------------------------------
@pytest.mark.parametrize("name", ["feed.rdf", "style.xsl", "news.atom", "x.xul", "a.txt", "x.svg"])
def test_raw_active_types_are_sandboxed(client, tree, name):  # noqa: F811
    (tree / name).write_text("<x/>")
    r = client.get("/api/files/raw", params={"path": str(tree / name)})
    assert r.status_code == 200 and r.headers["content-security-policy"].startswith("sandbox")
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("name", ["doc.pdf", "img.png", "clip.mp4"])
def test_raw_passive_types_keep_working(client, tree, name):  # noqa: F811
    (tree / name).write_bytes(b"\x00" * 10)
    r = client.get("/api/files/raw", params={"path": str(tree / name)})
    assert r.status_code == 200 and "content-security-policy" not in r.headers


def test_thumb_fallback_svg_is_sandboxed(client, tree, monkeypatch):  # noqa: F811
    monkeypatch.setattr(files, "_ffmpeg_thumb", lambda *a, **k: False)
    (tree / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>")
    r = client.get("/api/files/thumb", params={"path": str(tree / "logo.svg")})
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert r.headers["content-security-policy"].startswith("sandbox") and r.headers["x-content-type-options"] == "nosniff"


# ---- webhooks --------------------------------------------------------------------------------
def test_webhook_unknown_token_rejected_before_reading(client, monkeypatch):
    read = []
    monkeypatch.setattr(hooks, "_read_capped", lambda *a: read.append(1))
    client.cookies.clear()
    assert client.post("/api/hooks/not-a-token", content=b"x" * 100).status_code == 404
    assert read == []


def test_webhook_body_capped(client):
    h = feedhooks.create("big", "generic")
    url = "/api/hooks/" + h["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    big = b"x" * (feedhooks.MAX_BODY + 1)
    assert client.post(url, content=big).status_code == 413                       # Content-Length
    assert client.post(url, content=iter([big[:600_000], big[600_000:]])).status_code == 413   # chunked
    assert client.post(url, json={"title": "small"}).status_code == 200


# ---- extensions, headers, vault, importer ----------------------------------------------------
def test_extension_path_cannot_climb(client):
    r = client.get("/api/ext/anything/%2e%2e/secrets")
    assert r.status_code == 400 and r.json()["error"] == "bad_path"


def test_security_headers(client, tree):  # noqa: F811
    r = client.get("/api/workspace/tree")
    assert r.headers["x-frame-options"] == "SAMEORIGIN" and r.headers["referrer-policy"] == "same-origin"
    assert r.headers["x-content-type-options"] == "nosniff" and "content-security-policy" not in r.headers
    spa = client.get("/sessions")
    if spa.status_code == 200:                                 # web/dist present
        assert "frame-ancestors 'self'" in spa.headers["content-security-policy"]
    (tree / "p.html").write_text("<p>hi")
    page = client.get(_site_url(client, tree / "p.html"))
    assert page.headers["content-security-policy"] == filesite.SANDBOX       # the route's own CSP is kept


def test_vault_reserved_names(mx):
    for name in ("NODE_OPTIONS", "BASH_ENV", "GIT_SSH_COMMAND", "ANTHROPIC_BASE_URL", "LD_AUDIT"):
        with pytest.raises(vault.VaultError):
            vault.put(name, "x")


def test_import_skips_claude_settings():
    skip = importer._claude_config
    assert skip(PurePosixPath("projects/acme/.claude/settings.json"))
    assert skip(PurePosixPath("projects/acme/.claude/hooks/run.sh"))
    assert skip(PurePosixPath("projects/acme/.mcp.json"))
    assert not skip(PurePosixPath("projects/acme/.claude/skills/x/run.sh"))
    assert not skip(PurePosixPath(".claude/CLAUDE.md"))
    assert not skip(PurePosixPath("projects/acme/memory.md"))


def test_permissions_policy_header(client):
    pp = client.get("/api/auth/state").headers["permissions-policy"]
    assert "camera=()" in pp and "geolocation=()" in pp and "microphone=(self)" in pp
