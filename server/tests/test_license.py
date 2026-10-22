"""License: activation, signed archives, import as origin/main, and `maxxing update` on a licensed install
(fake license server on localhost, test signing key - never the real api.harness-maxxing.com)."""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from maxxing import config, license
from test_cmd_core import _git, env, repos, run_cli  # noqa: F401  (fixtures)
from test_customs import _upstream_release, code  # noqa: F401  (fixture)


@pytest.fixture
def keys(tmp_path, monkeypatch):
    priv, pub = tmp_path / "sign.pem", tmp_path / "sign.pub"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(priv)], check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(priv), "-pubout", "-out", str(pub)], check=True, capture_output=True)
    monkeypatch.setenv("MAXXING_RELEASE_PUBKEY", str(pub))
    return {"priv": priv, "pub": pub, "dir": tmp_path}


def _sign(keys, version, sha):
    msg = keys["dir"] / "msg"
    msg.write_bytes(license.signed_message(version, sha))
    sig = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", str(keys["priv"]), "-rawin", "-in", str(msg)], check=True, capture_output=True).stdout
    return base64.b64encode(sig).decode()


class FakeServer:
    """Minimal api.harness-maxxing.com: /v1/activate, /v1/update, /v1/ping, /v1/release, /dl/<version>."""

    def __init__(self):
        self.releases: dict[str, dict] = {}       # version -> {data, sha256, signature}
        self.latest: str | None = None
        self.calls: list[tuple[str, dict]] = []
        self.refuse: dict | None = None
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None, raw=None, ctype="application/json"):
                body = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                v = self.path.rsplit("/", 1)[-1]
                r = srv.releases.get(v)
                self._send(200, raw=r["data"], ctype="application/gzip") if r else self._send(404, {"ok": False})

            def do_POST(self):
                b = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
                srv.calls.append((self.path, b))
                if srv.refuse:
                    return self._send(403, srv.refuse)
                lic = {"email": "buyer@example.com", "kind": "paid", "max_servers": 2, "updates_until": None, "channel": "stable"}
                rel = srv.manifest(srv.latest) if srv.latest else None
                if self.path == "/v1/activate":
                    return self._send(200, {"ok": True, "activation_id": "a" * 32, "token": "a1.tok", "license": lic, "release": rel, "latest": srv.latest})
                newer = rel if rel and b.get("version") != srv.latest else None
                if self.path in ("/v1/update", "/v1/ping"):
                    return self._send(200, {"ok": True, "license": lic, "latest": srv.latest, "available": bool(newer), "allowed": bool(newer),
                                            "release": newer if self.path == "/v1/update" else None})
                if self.path == "/v1/release":
                    return self._send(200, {"ok": True})
                self._send(404, {"ok": False})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def manifest(self, v):
        r = self.releases[v]
        return {"version": v, "sha256": r["sha256"], "signature": r["signature"], "size": len(r["data"]), "published_at": 1700000000, "url": f"{self.url}/dl/{v}"}

    def publish(self, keys, work: Path, version: str, tamper: bool = False):
        out = keys["dir"] / f"r-{version}.tar.gz"
        subprocess.run(["git", "-C", str(work), "archive", "--format=tar.gz", "-o", str(out), "HEAD"], check=True)
        data = out.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        self.releases[version] = {"data": data + (b"x" if tamper else b""), "sha256": sha, "signature": _sign(keys, version, sha)}
        self.latest = version


@pytest.fixture
def server(monkeypatch):
    s = FakeServer()
    monkeypatch.setattr(license, "API", s.url)
    yield s
    s.httpd.shutdown()


def _licensed_install(tmp_path, srv, version):
    """What install.sh does for a license: extract the release, git init, origin/main = that commit."""
    d = tmp_path / "opt"
    d.mkdir()
    arch = tmp_path / "first.tar.gz"
    arch.write_bytes(srv.releases[version]["data"])
    with tarfile.open(arch) as t:
        t.extractall(d, filter="data")
    for args in (["init", "-q", "-b", "main"], ["add", "-A", "-f"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", version],
                 ["update-ref", "refs/remotes/origin/main", "HEAD"]):
        subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True)
    return d


def test_signature_and_tampering(keys, mx):
    sha = "ab" * 32
    sig = _sign(keys, "1.0.0", sha)
    assert license.verify_signature("1.0.0", sha, sig)
    assert not license.verify_signature("1.0.1", sha, sig)          # signed for another version
    assert not license.verify_signature("1.0.0", "cd" * 32, sig)


def test_machine_id_is_a_stable_hash(mx):
    a, b = license.machine_id(), license.machine_id()
    assert a == b and len(a) == 64 and int(a, 16) >= 0


def test_activate_stores_the_token_and_the_license(server, keys, mx, capsys):
    assert run_cli("license", "activate", "hm-abcd-efgh-jkmn-pqrs", "--no-fetch") == 0
    # a88: the key is a right of use, the server stays on git (no archive token, only the seat to free later)
    assert not config.get_secret(license.TOKEN) and config.get_secret(license.SEAT) == "a1.tok"
    assert config.get_secret(license.KEY) == "HM-ABCD-EFGH-JKMN-PQRS"
    st = license.status()
    assert not st["enabled"] and st["has_key"] and st["email"] == "buyer@example.com" and st["kind"] == "paid"
    assert st["key_hint"].startswith("HM-ABCD")
    assert "Enterprise key recorded" in capsys.readouterr().out
    path, body = server.calls[0]
    assert path == "/v1/activate" and len(body["machine_id"]) == 64 and body["hostname"]


def test_refused_activation_shows_the_message(server, keys, mx, capsys):
    server.refuse = {"ok": False, "error": "limit", "message": "already on 2 servers", "servers": [{"hostname": "old-vps", "last_seen": 1}]}
    assert run_cli("license", "activate", "HM-ABCD-EFGH-JKMN-PQRS", "--no-fetch") == 1
    out = capsys.readouterr().out
    assert "already on 2 servers" in out and "old-vps" in out
    assert not license.enabled()


def test_licensed_update_carries_customizations_over(code, server, keys, tmp_path, monkeypatch, capsys):
    work = code["work"]
    server.publish(keys, work, "1.0.0")
    opt = _licensed_install(tmp_path, server, "1.0.0")
    monkeypatch.setattr(config, "CODE", opt)
    config.set_secret(license.TOKEN, "a1.tok")
    # the buyer customizes the code
    (opt / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    assert run_cli("custom", "save", "Raise the limit to 50", "--why", "many sessions") == 0
    # a new version is published (another file changes upstream)
    _upstream_release(work, "1.1.0", extra="NEW.md")
    server.publish(keys, work, "1.1.0")
    capsys.readouterr()
    assert run_cli("update") == 0, capsys.readouterr().out
    assert (opt / "server" / "maxxing" / "__init__.py").read_text().strip() == '__version__ = "1.1.0"'
    assert (opt / "NEW.md").exists()
    assert "LIMIT = 50" in (opt / "server" / "maxxing" / "rules.py").read_text()      # customization kept
    log = subprocess.run(["git", "-C", str(opt), "log", "--format=%s", "-3"], capture_output=True, text=True).stdout
    assert "Raise the limit to 50" in log and "Harness Maxxing 1.1.0" in log
    # nothing new: a second check does not download again
    n = len(server.calls)
    assert license.fetch_latest()["version"] is None
    assert len(server.calls) == n + 1


def test_a_tampered_archive_is_refused(code, server, keys, tmp_path, monkeypatch, capsys):
    work = code["work"]
    server.publish(keys, work, "1.0.0")
    opt = _licensed_install(tmp_path, server, "1.0.0")
    monkeypatch.setattr(config, "CODE", opt)
    config.set_secret(license.TOKEN, "a1.tok")
    _upstream_release(work, "1.1.0")
    server.publish(keys, work, "1.1.0", tamper=True)
    before = subprocess.run(["git", "-C", str(opt), "rev-parse", "refs/remotes/origin/main"], capture_output=True, text=True).stdout
    with pytest.raises(license.LicenseError) as e:
        license.fetch_latest()
    assert e.value.code == "bad_archive"
    after = subprocess.run(["git", "-C", str(opt), "rev-parse", "refs/remotes/origin/main"], capture_output=True, text=True).stdout
    assert before == after


def test_release_frees_the_server(server, keys, mx):
    config.set_secret(license.TOKEN, "a1.tok")
    license.release()
    assert not license.enabled() and server.calls[-1][0] == "/v1/release"


def test_ping_sends_health_codes_only(server, keys, mx):
    config.set_secret(license.TOKEN, "a1.tok")
    h = license.health_summary()
    assert set(h) <= {"ok", "issues", "disk_pct", "mem_avail_mb", "uptime_d", "claude_auth", "backup_age_h", "os", "error"}
    license.ping(h)
    path, body = server.calls[-1]
    assert path == "/v1/ping" and body["token"] == "a1.tok" and body["version"]
    assert not license.ping_due()


# ---- installer security overhaul: downgrades, key ids, machine binding, token rotation ----------------------
def test_an_older_release_is_refused_unless_allowed(code, server, keys, tmp_path, monkeypatch):
    """A license server (or whoever answers in its place) offering an older signed release: refused - an old
    version with known holes would be installed (maxxing update --allow-downgrade accepts it)."""
    work = code["work"]
    server.publish(keys, work, "1.0.0")
    _upstream_release(work, "1.1.0")
    server.publish(keys, work, "1.1.0")
    opt = _licensed_install(tmp_path, server, "1.1.0")
    monkeypatch.setattr(config, "CODE", opt)
    config.set_secret(license.TOKEN, "a1.tok")
    server.latest = "1.0.0"
    before = subprocess.run(["git", "-C", str(opt), "rev-parse", "refs/remotes/origin/main"], capture_output=True, text=True).stdout
    with pytest.raises(license.LicenseError) as e:
        license.fetch_latest()
    assert e.value.code == "downgrade" and "--allow-downgrade" in str(e.value)
    assert subprocess.run(["git", "-C", str(opt), "rev-parse", "refs/remotes/origin/main"], capture_output=True, text=True).stdout == before
    assert license.fetch_latest(allow_downgrade=True)["version"] == "1.0.0"


def test_update_cli_has_allow_downgrade(code, server, keys, tmp_path, monkeypatch, capsys):
    work = code["work"]
    server.publish(keys, work, "1.0.0")
    _upstream_release(work, "1.1.0")
    server.publish(keys, work, "1.1.0")
    opt = _licensed_install(tmp_path, server, "1.1.0")
    monkeypatch.setattr(config, "CODE", opt)
    config.set_secret(license.TOKEN, "a1.tok")
    server.latest = "1.0.0"
    assert run_cli("update", "--check") == 1
    assert "refused" in capsys.readouterr().out


def test_is_downgrade():
    assert license.is_downgrade("2.0.0a9", "2.0.0a10")
    assert license.is_downgrade("2.0.0a10", "2.0.0a10")
    assert not license.is_downgrade("2.0.0a11", "2.0.0a10", "2.0.0a9")
    assert license.is_downgrade("not-a-version", "2.0.0")


def test_release_key_ids(code, server, keys, tmp_path, monkeypatch):
    """A release names its signing key (`kid`): none or k1 = the current key; an unknown id is refused before the
    download (the key can be rotated by shipping the new public key first)."""
    sha = "ab" * 32
    sig = _sign(keys, "1.0.0", sha)
    assert license.verify_signature("1.0.0", sha, sig, None) and license.verify_signature("1.0.0", sha, sig, "k1")
    assert not license.verify_signature("1.0.0", sha, sig, "k9")
    assert set(license.PUBKEYS) >= {"k1"} and license.DEFAULT_KID == "k1"
    work = code["work"]
    server.publish(keys, work, "1.0.0")
    opt = _licensed_install(tmp_path, server, "1.0.0")
    monkeypatch.setattr(config, "CODE", opt)
    config.set_secret(license.TOKEN, "a1.tok")
    _upstream_release(work, "1.1.0")
    server.publish(keys, work, "1.1.0")
    orig = server.manifest
    monkeypatch.setattr(server, "manifest", lambda v: {**orig(v), "kid": "k9"})
    with pytest.raises(license.LicenseError) as e:
        license.fetch_latest()
    assert e.value.code == "unknown_key"
    monkeypatch.setattr(server, "manifest", lambda v: {**orig(v), "kid": "k1"})
    assert license.fetch_latest()["version"] == "1.1.0"


def test_releases_only_over_https(mx, tmp_path):
    with pytest.raises(license.LicenseError) as e:
        license.download({"url": "http://releases.example.com/r.tar.gz", "version": "1.0.0", "sha256": "0" * 64,
                          "signature": ""}, tmp_path / "r.tar.gz")
    assert e.value.code == "insecure_url"
    assert license._url_ok("https://releases.example.com/r") and license._url_ok("http://127.0.0.1:9/r")


def test_calls_are_bound_to_the_machine_and_rotate_the_token(server, keys, mx, monkeypatch):
    config.set_secret(license.TOKEN, "a1.tok")
    license.check("1.0.0")
    license.ping({})
    for path, body in server.calls:
        assert body["machine_id"] == license.machine_id(), path
    real = license._post
    monkeypatch.setattr(license, "_post", lambda path, body, timeout=25: {**real(path, body, timeout), "token": "a2.rotated"})
    license.check("1.0.0")
    assert config.get_secret(license.TOKEN) == "a2.rotated"
    monkeypatch.setattr(license, "_post", lambda path, body, timeout=25: {**real(path, body, timeout), "token": "a3.rotated"})
    license.ping({})
    assert config.get_secret(license.TOKEN) == "a3.rotated"
    monkeypatch.setattr(license, "_post", real)
    license.release()
    assert server.calls[-1][0] == "/v1/release" and server.calls[-1][1]["machine_id"] == license.machine_id()


def test_a_fetched_but_never_installed_version_does_not_block_the_offered_one(code, server, keys, tmp_path,
                                                                                monkeypatch):
    """Adapted at integration: 1.2.0 fetched, its install rolled back, then withdrawn: 1.1.0 (newer than the
    installed 1.0.0) is not a downgrade."""
    work = code["work"]
    server.publish(keys, work, "1.0.0")
    opt = _licensed_install(tmp_path, server, "1.0.0")
    monkeypatch.setattr(config, "CODE", opt)
    config.set_secret(license.TOKEN, "a1.tok")
    _upstream_release(work, "1.1.0")
    server.publish(keys, work, "1.1.0")
    _upstream_release(work, "1.2.0")
    server.publish(keys, work, "1.2.0")
    server.latest = "1.2.0"
    assert license.fetch_latest()["version"] == "1.2.0"           # fetched into origin/main, not installed
    server.latest = "1.1.0"
    assert license.fetch_latest()["version"] == "1.1.0"


# ---- fair source: a licensed install moves to the git repository (2.0.0a87) --------------------
def _licensed_with_custom(code, server, keys, tmp_path, monkeypatch):
    work = code["work"]
    server.publish(keys, work, "1.0.0")
    opt = _licensed_install(tmp_path, server, "1.0.0")
    monkeypatch.setattr(config, "CODE", opt)
    monkeypatch.setattr(license, "GIT_URL", str(code["origin"]))
    config.set_secret(license.TOKEN, "a1.tok")
    config.set_secret(license.KEY, "HM-ABCD-EFGH-JKMN-PQRS")
    (opt / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    assert run_cli("custom", "save", "Raise the limit to 50", "--why", "many sessions") == 0
    return opt


def _g(opt, *args):
    return subprocess.run(["git", "-C", str(opt), *args], capture_output=True, text=True).stdout.strip()


def test_a_licensed_install_moves_to_git_and_keeps_its_customizations(code, server, keys, tmp_path, monkeypatch, capsys):
    from maxxing import customs
    opt = _licensed_with_custom(code, server, keys, tmp_path, monkeypatch)
    work = code["work"]
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)            # 1.0.0 is on GitHub `stable`
    head_before = _g(opt, "rev-parse", "HEAD")
    r = license.move_to_git()
    assert r["ok"] and r["moved"] and r["version"] == "1.0.0", r
    assert r["commit"] == _g(work, "rev-parse", "HEAD")             # same files -> that very commit
    assert _g(opt, "rev-parse", "--abbrev-ref", "HEAD") == "stable"
    assert _g(opt, "rev-parse", "--abbrev-ref", "stable@{upstream}") == "origin/stable"
    assert _g(opt, "remote", "get-url", "origin") == str(code["origin"])
    assert _g(opt, "rev-parse", license.PRE_GIT_REF) == head_before
    assert not _g(opt, "branch", "--list", "main") and not _g(opt, "rev-parse", "-q", "--verify", "refs/remotes/origin/main")
    assert "LIMIT = 50" in (opt / "server" / "maxxing" / "rules.py").read_text()
    assert [c["title"] for c in customs.list_customs()] == ["Raise the limit to 50"]
    assert not license.enabled() and config.get_secret(license.KEY) == "HM-ABCD-EFGH-JKMN-PQRS"
    from maxxing import cmd_core
    assert cmd_core.update_source() == "git"
    # from now on the updates come from git, customizations still carried over
    _upstream_release(work, "1.1.0", extra="NEW.md")
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)
    n = len(server.calls)
    capsys.readouterr()
    assert run_cli("update") == 0, capsys.readouterr().out
    assert (opt / "server" / "maxxing" / "__init__.py").read_text().strip() == '__version__ = "1.1.0"'
    assert (opt / "NEW.md").exists() and "LIMIT = 50" in (opt / "server" / "maxxing" / "rules.py").read_text()
    assert len(server.calls) == n                                    # the license server is not asked any more


def test_the_move_waits_until_the_version_is_on_stable(code, server, keys, tmp_path, monkeypatch):
    opt = _licensed_with_custom(code, server, keys, tmp_path, monkeypatch)
    work = code["work"]
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)
    _upstream_release(work, "1.1.0")                                 # only 1.1.0 published as an archive...
    server.publish(keys, work, "1.1.0")
    _git("checkout", "-q", "HEAD~1", cwd=work)
    _git("push", "-q", "-f", "origin", "HEAD:stable", cwd=work)      # ...stable still at 1.0.0
    assert license.fetch_latest()["version"] == "1.1.0"
    _git("-c", "user.name=t", "-c", "user.email=t@t", "rebase", "-q", "origin/main", cwd=opt)
    before = _g(opt, "rev-parse", "HEAD")
    r = license.try_move_to_git()
    assert not r["ok"] and "1.1.0 is not on stable" in r["error"]
    assert _g(opt, "rev-parse", "--abbrev-ref", "HEAD") == "main" and _g(opt, "rev-parse", "HEAD") == before
    assert license.enabled() and (config.load_config()["license"]["move_error"])
    assert not license.move_due()                                    # tried again in a few hours


def test_the_move_matches_the_version_when_the_files_differ(code, server, keys, tmp_path, monkeypatch):
    opt = _licensed_with_custom(code, server, keys, tmp_path, monkeypatch)
    work = code["work"]
    (work / "ONLY-IN-GIT.md").write_text("x\n")                      # same version, not the same files
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "--amend", "-m", "rules + docs", cwd=work)  # no commit of stable has the archive's files
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)
    r = license.move_to_git()
    assert r["moved"] and r["commit"] == _g(work, "rev-parse", "HEAD")
    assert (opt / "ONLY-IN-GIT.md").exists() and "LIMIT = 50" in (opt / "server" / "maxxing" / "rules.py").read_text()


def test_the_move_never_touches_uncommitted_changes(code, server, keys, tmp_path, monkeypatch):
    opt = _licensed_with_custom(code, server, keys, tmp_path, monkeypatch)
    _git("push", "-q", "origin", "HEAD:stable", cwd=code["work"])
    (opt / "server" / "maxxing" / "rules.py").write_text("LIMIT = 70\n")
    r = license.move_to_git()
    assert not r["ok"] and "uncommitted" in r["error"] and license.enabled()
    assert (opt / "server" / "maxxing" / "rules.py").read_text() == "LIMIT = 70\n"


def test_update_moves_a_licensed_install_first(code, server, keys, tmp_path, monkeypatch, capsys):
    opt = _licensed_with_custom(code, server, keys, tmp_path, monkeypatch)
    _git("push", "-q", "origin", "HEAD:stable", cwd=code["work"])
    capsys.readouterr()
    assert run_cli("update") == 0
    out = capsys.readouterr().out
    assert "now updates from" in out and _g(opt, "rev-parse", "--abbrev-ref", "HEAD") == "stable"


def test_the_move_starts_from_the_installed_version_not_a_fetched_one(code, server, keys, tmp_path, monkeypatch):
    opt = _licensed_with_custom(code, server, keys, tmp_path, monkeypatch)
    work = code["work"]
    v100 = _g(work, "rev-parse", "HEAD")
    _upstream_release(work, "1.1.0")
    server.publish(keys, work, "1.1.0")
    assert license.fetch_latest()["version"] == "1.1.0"           # fetched by the daily check, never installed
    _git("push", "-q", "origin", "HEAD:stable", cwd=work)
    r = license.move_to_git()
    assert r["moved"] and r["version"] == "1.0.0" and r["commit"] == v100
    assert (opt / "server" / "maxxing" / "__init__.py").read_text().strip() == '__version__ = "1.0.0"'
    assert "LIMIT = 50" in (opt / "server" / "maxxing" / "rules.py").read_text()


def test_removing_the_key_frees_its_seat(server, keys, mx, capsys):
    license.activate("HM-ABCD-EFGH-JKMN-PQRS")
    assert run_cli("license", "remove") == 0
    assert "Enterprise key removed" in capsys.readouterr().out
    assert server.calls[-1][0] == "/v1/release"
    assert not config.get_secret(license.KEY) and not config.get_secret(license.SEAT)
    assert not license.status()["has_key"]


def test_the_key_from_the_api(server, keys, client):
    c = client
    assert c.get("/api/settings/license").json()["has_key"] is False
    assert c.put("/api/settings/license", json={"key": "nope"}).status_code == 400
    r = c.put("/api/settings/license", json={"key": "HM-ABCD-EFGH-JKMN-PQRS"}).json()
    assert r["has_key"] and r["kind"] == "paid" and r["enabled"] is False and "HM-ABCD-EFGH-JKMN-PQRS" not in str(r)
    server.refuse = {"ok": False, "error": "limit", "message": "already on 2 servers"}
    r = c.put("/api/settings/license", json={"key": "HM-ABCD-EFGH-JKMN-PQRS"})
    assert r.status_code == 400 and "already on 2 servers" in r.text
    assert c.delete("/api/settings/license").json()["has_key"] is False


def test_a_moved_install_keeps_the_seat_of_its_key(code, server, keys, tmp_path, monkeypatch):
    opt = _licensed_with_custom(code, server, keys, tmp_path, monkeypatch)
    _git("push", "-q", "origin", "HEAD:stable", cwd=code["work"])
    assert license.move_to_git()["moved"]
    assert config.get_secret(license.SEAT) == "a1.tok" and not license.enabled() and license.status()["has_key"]
