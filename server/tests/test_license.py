"""License: the optional Enterprise key, and installs from before 2.0.0a87 (code of a signed archive) moving to the
public git repository - including a server whose OLD code installs this version from an archive (fake license
server on localhost - never the real api.harness-maxxing.com)."""
from __future__ import annotations

import asyncio
import json
import subprocess
import tarfile
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from maxxing import config, license
from test_cmd_core import _git, env, repos, run_cli  # noqa: F401  (fixtures)
from test_customs import _upstream_release, code  # noqa: F401  (fixture)


class FakeServer:
    """Minimal license server: /v1/activate, /v1/release."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.refuse: dict | None = None
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                srv.calls.append((self.path, b))
                if srv.refuse:
                    return self._send(403, srv.refuse)
                lic = {"email": "buyer@example.com", "kind": "paid", "max_servers": 1, "expires_at": None}
                if self.path == "/v1/activate":
                    return self._send(200, {"ok": True, "activation_id": "a" * 32, "token": "a1.tok", "license": lic})
                if self.path == "/v1/release":
                    return self._send(200, {"ok": True})
                self._send(404, {"ok": False})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def server(monkeypatch):
    s = FakeServer()
    monkeypatch.setattr(license, "API", s.url)
    yield s
    s.httpd.shutdown()


# ---- what the code of an install from before 2.0.0a87 did (it is no longer in this code) ---------------------
def _archive(work: Path, dest: Path) -> Path:
    subprocess.run(["git", "-C", str(work), "archive", "--format=tar.gz", "-o", str(dest), "HEAD"], check=True)
    return dest


def _licensed_install(tmp_path, work):
    """install.sh with a license key (before a87): the archive extracted, git init, origin/main = that commit."""
    d = tmp_path / "opt"
    d.mkdir()
    with tarfile.open(_archive(work, tmp_path / "first.tar.gz")) as t:
        t.extractall(d, filter="data")
    for args in (["init", "-q", "-b", "main"], ["add", "-A", "-f"],
                 ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "first"],
                 ["update-ref", "refs/remotes/origin/main", "HEAD"]):
        subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True)
    return d


def _old_code_fetches_archive(opt: Path, work: Path) -> str:
    """The old `license.fetch_latest`: the newest signed archive (here: the files of `work`) imported as a commit on
    refs/remotes/origin/main, parent = the previous one."""
    ref = "refs/remotes/origin/main"
    with tempfile.TemporaryDirectory() as d:
        tree_dir, index = Path(d) / "tree", Path(d) / "index"
        tree_dir.mkdir()
        with tarfile.open(_archive(work, Path(d) / "r.tar.gz")) as t:
            t.extractall(tree_dir, filter="data")
        genv = {"GIT_INDEX_FILE": str(index), "GIT_WORK_TREE": str(tree_dir)}
        _g(opt, "--work-tree", str(tree_dir), "add", "-A", "-f", ".", env=genv)
        tree = _g(opt, "write-tree", env=genv)
    parent = _g(opt, "rev-parse", ref)
    ident = {"GIT_AUTHOR_NAME": "Harness Maxxing", "GIT_AUTHOR_EMAIL": "releases@example.com",
             "GIT_COMMITTER_NAME": "Harness Maxxing", "GIT_COMMITTER_EMAIL": "releases@example.com"}
    commit = _g(opt, "commit-tree", tree, "-p", parent, "-m", "Harness Maxxing archive", env=ident)
    _g(opt, "update-ref", ref, commit)
    return commit


def _old_code_installs_archive(opt: Path, work: Path) -> None:
    """The old `maxxing update`: fetch the archive, rebase the customizations onto it."""
    _old_code_fetches_archive(opt, work)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "rebase", "-q", "origin/main", cwd=opt)


def _g(opt, *args, env=None):
    import os
    return subprocess.run(["git", "-C", str(opt), *args], capture_output=True, text=True,
                          env={**os.environ, **(env or {})}).stdout.strip()


def _licensed_with_custom(code, tmp_path, monkeypatch):
    work = code["work"]
    opt = _licensed_install(tmp_path, work)
    monkeypatch.setattr(config, "CODE", opt)
    monkeypatch.setattr(license, "GIT_URL", str(code["origin"]))
    config.set_secret(license.TOKEN, "a1.tok")
    config.set_secret(license.KEY, "HM-ABCD-EFGH-JKMN-PQRS")
    (opt / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    assert run_cli("custom", "save", "Raise the limit to 50", "--why", "many sessions") == 0
    return opt


# ---- the Enterprise key --------------------------------------------------------------------------------------
def test_machine_id_is_a_stable_hash(mx):
    a, b = license.machine_id(), license.machine_id()
    assert a == b and len(a) == 64 and int(a, 16) >= 0


def test_activate_stores_the_seat_and_the_license(server, mx, capsys):
    # --no-fetch: a no-op kept because install.sh passes it (for the old code of a pre-a87 install)
    assert run_cli("license", "activate", "hm-abcd-efgh-jkmn-pqrs", "--no-fetch") == 0
    assert not config.get_secret(license.TOKEN) and config.get_secret(license.SEAT) == "a1.tok"
    assert config.get_secret(license.KEY) == "HM-ABCD-EFGH-JKMN-PQRS"
    st = license.status()
    assert not st["enabled"] and st["has_key"] and st["email"] == "buyer@example.com" and st["kind"] == "paid"
    assert st["key_hint"].startswith("HM-ABCD")
    assert "Enterprise key recorded" in capsys.readouterr().out
    path, body = server.calls[0]
    assert path == "/v1/activate" and len(body["machine_id"]) == 64 and body["hostname"]


def test_refused_activation_shows_the_message(server, mx, capsys):
    server.refuse = {"ok": False, "error": "limit", "message": "already on 1 server",
                     "servers": [{"hostname": "old-vps", "last_seen": 1}]}
    assert run_cli("license", "activate", "HM-ABCD-EFGH-JKMN-PQRS") == 1
    out = capsys.readouterr().out
    assert "already on 1 server" in out and "old-vps" in out
    assert not license.enabled() and not config.get_secret(license.KEY)


def test_the_archive_commands_are_gone(mx, capsys):
    for act in ("check", "ping"):
        with pytest.raises(SystemExit):
            run_cli("license", act)
    with pytest.raises(SystemExit):
        run_cli("update", "--allow-downgrade")
    for name in ("fetch_latest", "check", "ping", "download", "import_release", "verify_signature", "PUBKEYS"):
        assert not hasattr(license, name), name


def test_release_frees_the_seat(server, mx):
    config.set_secret(license.SEAT, "a1.tok")
    license.release()
    assert not config.get_secret(license.SEAT) and server.calls[-1][0] == "/v1/release"


def test_release_on_a_server_still_on_archives_keeps_the_move_to_do(server, mx):
    config.set_secret(license.TOKEN, "a1.tok")
    license.release()
    assert license.enabled() and server.calls[-1][0] == "/v1/release"


def test_removing_the_key_frees_its_seat(server, mx, capsys):
    license.activate("HM-ABCD-EFGH-JKMN-PQRS")
    assert run_cli("license", "remove") == 0
    assert "Enterprise key removed" in capsys.readouterr().out
    assert server.calls[-1][0] == "/v1/release"
    assert not config.get_secret(license.KEY) and not config.get_secret(license.SEAT)
    assert not license.status()["has_key"]


def test_remove_key_forgets_the_license_info(server, mx):
    config.set_secret(license.KEY, "HM-ABCD-EFGH-JKMN-PQRS")
    license._save_info({"email": "boss@example.com", "kind": "enterprise", "status": "active", "max_servers": 3},
                       activation_id="a1", moved_to_git=True)
    license.remove_key()
    lic = config.load_config().get("license") or {}
    assert lic == {"moved_to_git": True}, lic
    assert "email" not in license.status()


def test_activate_without_token_leaves_no_key(mx, monkeypatch):
    monkeypatch.setattr(license, "_post", lambda *a, **k: {"ok": True, "license": {"email": "boss@example.com"}})
    with pytest.raises(license.LicenseError):
        license.activate("HM-ABCD-EFGH-JKMN-PQRS")
    assert not config.get_secret(license.KEY) and not config.get_secret(license.SEAT)
    assert not (config.load_config().get("license") or {}).get("email")


def test_the_key_from_the_api(server, client):
    c = client
    assert c.get("/api/settings/license").json()["has_key"] is False
    assert c.put("/api/settings/license", json={"key": "nope"}).status_code == 400
    r = c.put("/api/settings/license", json={"key": "HM-ABCD-EFGH-JKMN-PQRS"}).json()
    assert r["has_key"] and r["kind"] == "paid" and r["enabled"] is False and "HM-ABCD-EFGH-JKMN-PQRS" not in str(r)
    server.refuse = {"ok": False, "error": "limit", "message": "already on 1 server"}
    r = c.put("/api/settings/license", json={"key": "HM-ABCD-EFGH-JKMN-PQRS"})
    assert r.status_code == 400 and "already on 1 server" in r.text
    assert c.delete("/api/settings/license").json()["has_key"] is False


# ---- installs from before 2.0.0a87 move to the git repository --------------------------------------------------
def test_an_old_server_that_installs_this_version_from_an_archive_ends_on_stable(code, tmp_path, monkeypatch, capsys):
    """The 6 servers still on archives: their OLD code downloads the newest archive (a version with this code) and
    restarts; this code then moves the server to git by itself at start (no command), customizations kept."""
    from maxxing import auto_update, customs, smartupdate
    from maxxing.api import system
    work = code["work"]
    opt = _licensed_with_custom(code, tmp_path, monkeypatch)       # an old version, customized
    _upstream_release(work, "1.1.0", extra="NEW.md")               # the version with this code...
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)          # ...published: on `stable` and as an archive
    _old_code_installs_archive(opt, work)                          # what the old `maxxing update` does
    assert license.enabled() and _g(opt, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    # the new code starts (systemd restart by the old update): the start trigger, without its waits
    monkeypatch.setenv("MAXXING_AFTER_UPDATE_DELAY", "0")
    monkeypatch.setattr(system, "MOVE_QUIET_S", 0.0)
    monkeypatch.setattr(system, "_STARTED", 0.0)
    monkeypatch.setattr(auto_update, "_update_running", lambda: False)
    monkeypatch.setattr(smartupdate, "after_update", lambda: None)
    asyncio.run(system._after_update())
    assert not license.enabled(), config.load_config().get("license")
    assert _g(opt, "rev-parse", "--abbrev-ref", "HEAD") == "stable"
    assert _g(opt, "rev-parse", "--abbrev-ref", "stable@{upstream}") == "origin/stable"
    assert _g(opt, "rev-parse", "HEAD~1") == _g(work, "rev-parse", "HEAD")   # 1.1.0 of GitHub + the customization
    assert (opt / "NEW.md").exists() and "LIMIT = 50" in (opt / "server" / "maxxing" / "rules.py").read_text()
    assert [c["title"] for c in customs.list_customs()] == ["Raise the limit to 50"]
    assert config.get_secret(license.KEY) == "HM-ABCD-EFGH-JKMN-PQRS" and config.get_secret(license.SEAT) == "a1.tok"
    # from now on a plain git update
    _upstream_release(work, "1.2.0")
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)
    capsys.readouterr()
    assert run_cli("update") == 0, capsys.readouterr().out
    assert (opt / "server" / "maxxing" / "__init__.py").read_text().strip() == '__version__ = "1.2.0"'
    assert "LIMIT = 50" in (opt / "server" / "maxxing" / "rules.py").read_text()


def test_a_licensed_install_moves_to_git_and_keeps_its_customizations(code, tmp_path, monkeypatch, capsys):
    from maxxing import cmd_core, customs
    opt = _licensed_with_custom(code, tmp_path, monkeypatch)
    work = code["work"]
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)            # 1.0.0 is on GitHub `stable`
    head_before = _g(opt, "rev-parse", "HEAD")
    r = license.move_to_git()
    assert r["ok"] and r["moved"] and r["version"] == "1.0.0", r
    assert r["commit"] == _g(work, "rev-parse", "HEAD")             # same files -> that very commit
    assert _g(opt, "rev-parse", "--abbrev-ref", "HEAD") == "stable"
    assert _g(opt, "remote", "get-url", "origin") == str(code["origin"])
    assert _g(opt, "rev-parse", license.PRE_GIT_REF) == head_before
    assert not _g(opt, "branch", "--list", "main") and not _g(opt, "rev-parse", "-q", "--verify", "refs/remotes/origin/main")
    assert [c["title"] for c in customs.list_customs()] == ["Raise the limit to 50"]
    assert not license.enabled() and cmd_core.update_source() == "git"


def test_the_move_waits_until_the_version_is_on_stable(code, tmp_path, monkeypatch, capsys):
    opt = _licensed_with_custom(code, tmp_path, monkeypatch)
    work = code["work"]
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)
    _upstream_release(work, "1.1.0")                                 # only 1.1.0 published as an archive...
    _old_code_installs_archive(opt, work)                            # ...stable still at 1.0.0
    before = _g(opt, "rev-parse", "HEAD")
    r = license.try_move_to_git()
    assert not r["ok"] and "1.1.0 is not on stable" in r["error"]
    assert _g(opt, "rev-parse", "--abbrev-ref", "HEAD") == "main" and _g(opt, "rev-parse", "HEAD") == before
    assert license.enabled() and (config.load_config()["license"]["move_error"])
    assert not license.move_due()                                    # tried again in a few hours
    # `maxxing update` says why and changes nothing (no archive download in this code)
    capsys.readouterr()
    assert run_cli("update") == 1
    assert "1.1.0 is not on stable" in capsys.readouterr().out and _g(opt, "rev-parse", "HEAD") == before
    from maxxing import cmd_core
    chk = cmd_core.check_update()
    assert chk["ok"] is False and "not moved to the public git repository yet" in chk["error"]
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)            # published on stable: it moves
    assert run_cli("update") == 0 and _g(opt, "rev-parse", "--abbrev-ref", "HEAD") == "stable"


def test_the_move_matches_the_version_when_the_files_differ(code, tmp_path, monkeypatch):
    opt = _licensed_with_custom(code, tmp_path, monkeypatch)
    work = code["work"]
    (work / "ONLY-IN-GIT.md").write_text("x\n")                      # same version, not the same files
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "--amend", "-m", "rules + docs", cwd=work)  # no commit of stable has the archive's files
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)
    r = license.move_to_git()
    assert r["moved"] and r["commit"] == _g(work, "rev-parse", "HEAD")
    assert (opt / "ONLY-IN-GIT.md").exists() and "LIMIT = 50" in (opt / "server" / "maxxing" / "rules.py").read_text()


def test_the_move_never_touches_uncommitted_changes(code, tmp_path, monkeypatch):
    opt = _licensed_with_custom(code, tmp_path, monkeypatch)
    _git("push", "-q", "origin", "HEAD:stable", cwd=code["work"])
    (opt / "server" / "maxxing" / "rules.py").write_text("LIMIT = 70\n")
    r = license.move_to_git()
    assert not r["ok"] and "uncommitted" in r["error"] and license.enabled()
    assert (opt / "server" / "maxxing" / "rules.py").read_text() == "LIMIT = 70\n"


def test_update_saves_uncommitted_changes_then_moves(code, tmp_path, monkeypatch, capsys):
    opt = _licensed_with_custom(code, tmp_path, monkeypatch)
    _git("push", "-q", "origin", "HEAD:stable", cwd=code["work"])
    (opt / "server" / "maxxing" / "rules.py").write_text("LIMIT = 70\n")
    capsys.readouterr()
    assert run_cli("update") == 0
    out = capsys.readouterr().out
    assert "saved as customization" in out and "now updates from" in out
    assert _g(opt, "rev-parse", "--abbrev-ref", "HEAD") == "stable"
    assert (opt / "server" / "maxxing" / "rules.py").read_text() == "LIMIT = 70\n"


def test_update_moves_a_licensed_install_first(code, tmp_path, monkeypatch, capsys):
    opt = _licensed_with_custom(code, tmp_path, monkeypatch)
    _git("push", "-q", "origin", "HEAD:stable", cwd=code["work"])
    capsys.readouterr()
    assert run_cli("update") == 0
    out = capsys.readouterr().out
    assert "now updates from" in out and _g(opt, "rev-parse", "--abbrev-ref", "HEAD") == "stable"


def test_the_move_starts_from_the_installed_version_not_a_fetched_one(code, tmp_path, monkeypatch):
    opt = _licensed_with_custom(code, tmp_path, monkeypatch)
    work = code["work"]
    v100 = _g(work, "rev-parse", "HEAD")
    _upstream_release(work, "1.1.0")
    _old_code_fetches_archive(opt, work)                           # fetched by the old daily check, never installed
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)
    r = license.move_to_git()
    assert r["moved"] and r["version"] == "1.0.0" and r["commit"] == v100
    assert (opt / "server" / "maxxing" / "__init__.py").read_text().strip() == '__version__ = "1.0.0"'
    assert "LIMIT = 50" in (opt / "server" / "maxxing" / "rules.py").read_text()


def test_a_moved_install_keeps_the_seat_of_its_key(code, tmp_path, monkeypatch):
    _licensed_with_custom(code, tmp_path, monkeypatch)
    _git("push", "-q", "origin", "HEAD:stable", cwd=code["work"])
    assert license.move_to_git()["moved"]
    assert config.get_secret(license.SEAT) == "a1.tok" and not license.enabled() and license.status()["has_key"]
