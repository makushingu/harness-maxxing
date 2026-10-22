"""Optional registration with the authors' cloud (maxxing/register.py, /api/settings/register)."""
from __future__ import annotations

import json
import threading
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
    yield c
    c.httpd.shutdown()


def test_anonymous_counter_sends_the_version_only(cloud):
    st = register.save(count=True)
    assert st["registered"] and st["count"] and not st["email"]
    (row,) = cloud.rows.values()
    assert set(row) == {"version", "email", "news"} and row["email"] is None and row["news"] is False
    assert config.get_secret(register.TOKEN)


def test_email_adds_pseudo_and_language_and_news_needs_an_email(cloud):
    config.update_config(profile={"name": "Tom", "color": "", "emoji": ""}, language="fr")
    register.save(email="Tom@Example.com", news=True)
    (row,) = cloud.rows.values()
    assert row["email"] == "tom@example.com" and row["pseudo"] == "Tom" and row["lang"] == "fr" and row["news"] is True
    st = register.save(email="")                   # email removed: news goes with it, the anonymous counter is off
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


def test_nothing_is_sent_without_consent_or_offline(mx, monkeypatch):
    monkeypatch.setattr(license, "API", "http://127.0.0.1:9")   # would fail if called
    assert register.settings()["count"] is False                 # an update never turns the counter on
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
