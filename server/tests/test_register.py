"""Optional registration with the authors' cloud (maxxing/register.py, /api/settings/register)."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from maxxing import config, license, register


class FakeCloud:
    """/v1/register (POST create/update, DELETE) and /v1/heartbeat, like the real Worker."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.calls: list[tuple[str, str, dict]] = []
        cloud = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # noqa: D401 - quiet
                pass

            def _answer(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self) -> None:
                b = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                cloud.calls.append((self.command, self.path, b))
                tok = b.get("token")
                if self.path == "/v1/heartbeat":
                    if tok not in cloud.rows:
                        return self._answer(404, {"ok": False, "error": "unknown_install"})
                    cloud.rows[tok]["version"] = b.get("version")
                    return self._answer(200, {"ok": True})
                if self.command == "DELETE":
                    cloud.rows.pop(tok, None)
                    return self._answer(200, {"ok": True})
                if tok:
                    if tok not in cloud.rows:
                        return self._answer(404, {"ok": False, "error": "unknown_install"})
                    cloud.rows[tok].update({k: v for k, v in b.items() if k != "token"})
                    return self._answer(200, {"ok": True, "token": tok})
                new = f"i1.{len(cloud.calls):032x}.sig"
                cloud.rows[new] = {k: v for k, v in b.items()}
                return self._answer(200, {"ok": True, "token": new})

            do_POST = do_DELETE = _handle

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def cloud(mx, monkeypatch):
    c = FakeCloud()
    monkeypatch.setattr(license, "API", c.url)
    monkeypatch.setattr(register, "_offline", lambda: False)
    monkeypatch.setattr(register, "health_codes", lambda: ["service_ok", "claude_signed_in"])
    for k in register.OPT_OUT_ENV:
        monkeypatch.delenv(k, raising=False)
    yield c
    c.httpd.shutdown()


def test_anonymous_counter_sends_the_version_the_system_and_health_codes_only(cloud, mx):
    config.update_config(profile={"name": "Tom", "color": "", "emoji": ""}, language="fr")
    st = register.save(count=True)
    assert st["registered"] and st["count"] and not st["email"]
    (row,) = cloud.rows.values()
    assert set(row) == {"version", "email", "news", "os", "arch", "health"} and row["email"] is None
    assert row["news"] is False and row["health"] == ["service_ok", "claude_signed_in"]
    assert row["arch"] and 0 < len(row["os"]) <= 40
    sent = json.dumps(cloud.calls)
    import socket
    for private in ("Tom", str(mx["state"]), str(mx["ws"]), socket.gethostname(), "127.0.0.1"):
        assert private not in sent                  # no pseudo, path, hostname or IP
    assert config.get_secret(register.TOKEN)
    register._meta(beat_at=0)
    assert register.heartbeat_due()
    register.heartbeat()
    m, path, body = cloud.calls[-1]
    assert path == "/v1/heartbeat" and set(body) == {"token", "version", "os", "arch", "health"}


def test_counter_is_on_by_default(mx):
    assert register.settings()["count"] is True and register.counting()


def test_os_name_and_health_codes_are_short(mx, tmp_path, monkeypatch):
    f = tmp_path / "os-release"
    f.write_text('PRETTY_NAME="Ubuntu 24.04.1 LTS"\nNAME="Ubuntu"\nVERSION_ID="24.04"\n')
    monkeypatch.setattr(register, "OS_RELEASE", f)
    assert register.os_name() == "Ubuntu 24.04"
    f.write_text('PRETTY_NAME="' + "x" * 80 + '"\n')
    assert register.os_name() == "x" * 40
    codes = register.health_codes()             # the real (cached) health check of the test state
    assert 0 < len(codes) <= register.HEALTH_MAX and all(register.HEALTH_RE.match(c) for c in codes)
    config.update_config(telegram={"chat_id": 1}, backup={"repo": "acme/backup"})
    assert {"telegram_on", "backup_on"} <= set(register.health_codes())


@pytest.mark.parametrize("env", ["MAXXING_NO_TELEMETRY", "DO_NOT_TRACK"])
def test_environment_opt_out_wins_over_the_setting(cloud, monkeypatch, env):
    register.save(count=True)
    assert cloud.rows
    monkeypatch.setenv(env, "1")
    st = register.state()
    assert st["count"] and st["count_blocked"] and not register.counting()
    assert register.heartbeat_due()                 # a count-only row left behind: deleted at the next signal
    register.heartbeat()
    assert cloud.rows == {} and not config.get_secret(register.TOKEN) and not register.heartbeat_due()
    register.save(email="a@b.co")                   # an email is still sent (the user typed it), never the counter
    (row,) = cloud.rows.values()
    assert row["email"] == "a@b.co" and row["os"] is None and row["health"] is None
    monkeypatch.setenv(env, "0")
    assert not register.blocked()


def test_migration_turns_the_counter_on_only_for_installs_never_asked():
    raw: dict = {}
    assert register.migrate(raw) and raw["register"]["count"] is True and raw[register.MIGRATED]
    raw = {"register": {"count": False, "email": "a@b.co", "asked": False}}
    register.migrate(raw)
    assert raw["register"] == {"count": True, "email": "a@b.co", "asked": False}
    raw = {"register": {"count": False, "email": "", "asked": True}}      # saw the choice and left it off
    register.migrate(raw)
    assert raw["register"]["count"] is False
    raw = {"register": {"count": False, "asked": False}, register.MIGRATED: True}   # once only
    assert not register.migrate(raw) and raw["register"]["count"] is False


def test_init_runs_the_migration_once(mx, monkeypatch):
    import argparse
    from maxxing import cmd_core
    monkeypatch.setattr(cmd_core, "copy_templates", lambda ws: [])
    monkeypatch.setattr(cmd_core, "install_skills", lambda: [])
    monkeypatch.setattr(cmd_core, "claude_settings_defaults", lambda: False)
    monkeypatch.setattr(cmd_core, "ensure_jobs_slice", lambda: "")
    monkeypatch.setattr(cmd_core, "ensure_service_memory", lambda: "")
    a = argparse.Namespace(workspace=None, files_root=None, port=None, bind=None, public_url=None, timezone=None,
                           language=None, system_clock=None, claude_dir=None, secret_from_stdin=None, no_crons=True)
    config.update_config(register={"count": False, "asked": False})
    cmd_core.do_init(a)
    assert register.settings()["count"] is True
    register.save(count=False, asked=True)
    cmd_core.do_init(a)                             # the next update keeps the user's choice
    assert register.settings()["count"] is False


def test_email_adds_pseudo_and_language_and_news_needs_an_email(cloud):
    config.update_config(profile={"name": "Tom", "color": "", "emoji": ""}, language="fr")
    register.save(email="Tom@Example.com", news=True)
    (row,) = cloud.rows.values()
    assert row["email"] == "tom@example.com" and row["pseudo"] == "Tom" and row["lang"] == "fr" and row["news"] is True
    assert "os" in row                              # the counter is on by default
    register.save(count=False)
    (row,) = cloud.rows.values()
    assert row["os"] is None and row["health"] is None   # counter off: what the cloud kept of it is cleared
    st = register.save(email="")                   # email removed: news goes with it, nothing left to send
    assert st["news"] is False and not st["registered"] and cloud.rows == {}


def test_stop_deletes_the_row_and_forgets_the_token(cloud):
    register.save(count=True, email="a@b.co")
    assert cloud.rows
    st = register.save(count=False, email="")
    assert cloud.rows == {} and not st["registered"] and not config.get_secret(register.TOKEN)
    assert cloud.calls[-1][0] == "DELETE"


def test_heartbeat_registers_again_when_the_cloud_forgot_us(cloud):
    register.save(count=True)
    assert not register.heartbeat_due()             # just synced
    tok = config.get_secret(register.TOKEN)
    cloud.rows.clear()                              # deleted from the admin
    register.heartbeat()
    assert config.get_secret(register.TOKEN) != tok and len(cloud.rows) == 1


def test_concurrent_saves_make_one_row(mx, monkeypatch):
    monkeypatch.delenv("MAXXING_LICENSE_PING", raising=False)
    rows = []

    def call(method, path, body):
        time.sleep(0.3)
        if method == "POST" and not body.get("token"):
            rows.append(1)
        return {"ok": True, "token": f"t{len(rows)}"}
    monkeypatch.setattr(register, "_call", call)
    ts = [threading.Thread(target=register.save, kwargs={"email": "a@b.co"}) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert rows == [1] and config.get_secret(register.TOKEN) == "t1"


def test_nothing_is_sent_when_off_or_offline(mx, monkeypatch):
    monkeypatch.setattr(license, "API", "http://127.0.0.1:9")   # would fail if called
    register.save(count=False)                                   # nothing sent: offline (MAXXING_LICENSE_PING=0)
    assert not register.heartbeat_due()
    monkeypatch.setenv("MAXXING_LICENSE_PING", "0")
    st = register.save(count=True)                               # offline install: saved, nothing sent
    assert st["count"] and not st["registered"]


def test_api_validates_and_marks_the_onboarding_step(client, cloud):
    assert client.put("/api/settings/register", json={"email": "nope"}).status_code == 400
    r = client.put("/api/settings/register", json={"count": True, "email": "x@y.io", "news": False, "asked": True})
    assert r.status_code == 200 and r.json()["registered"]
    assert client.get("/api/settings/register").json()["email"] == "x@y.io"
    assert client.get("/api/onboarding").json()["steps"]["profile"] is True


@pytest.mark.parametrize("tok", [{"a": 1}, ["t"], 5, "x" * 257, "t\nX-Evil: 1", "té"])
def test_a_token_the_cloud_sends_is_checked_before_it_is_stored(mx, monkeypatch, tok):
    monkeypatch.delenv("MAXXING_LICENSE_PING", raising=False)
    monkeypatch.setattr(register, "_call", lambda method, path, body: {"ok": True, "token": tok})
    st = register.save(email="a@b.co")
    assert not config.get_secret(register.TOKEN) and st["error"] == "bad_token_answer" and not st["registered"]
