"""Feedback button: messages sent to the authors' cloud (maxxing/feedback.py, /api/settings/feedback)."""
from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from maxxing import config, license, register


class FakeCloud:
    """/v1/feedback like the real Worker: email + message required, 429 after `limit` messages."""

    def __init__(self, limit: int = 10) -> None:
        self.got: list[dict] = []
        cloud = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self) -> None:
                b = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                if self.path != "/v1/feedback":
                    code, out = 404, {"ok": False, "error": "not_found"}
                elif "@" not in (b.get("email") or ""):
                    code, out = 400, {"ok": False, "error": "bad_email", "message": "Enter a valid email address"}
                elif len(cloud.got) >= limit:
                    code, out = 429, {"ok": False, "error": "rate", "message": "Too many messages today, try again tomorrow."}
                else:
                    cloud.got.append({**b, "_ua": self.headers.get("user-agent")})
                    code, out = 200, {"ok": True, "id": len(cloud.got)}
                data = json.dumps(out).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


@pytest.fixture
def cloud(mx, monkeypatch):
    c = FakeCloud(limit=2)
    monkeypatch.setattr(license, "API", c.url)
    monkeypatch.setattr(register, "_offline", lambda: False)
    yield c
    c.httpd.shutdown()


def test_feedback_is_sent_with_the_version_and_the_email_is_remembered(client, cloud):
    config.update_config(language="fr", profile={"name": "Romi"})
    assert client.get("/api/settings/feedback").json()["email"] == ""
    r = client.post("/api/settings/feedback", json={"email": " me@x.io ", "type": "bug", "message": "The sidebar flickers"})
    assert r.status_code == 200, r.text
    sent = cloud.got[0]
    assert sent["email"] == "me@x.io" and sent["type"] == "bug" and sent["message"] == "The sidebar flickers"
    assert sent["lang"] == "fr" and sent["name"] == "Romi" and sent["version"] == license.disk_version()
    assert sent["_ua"].startswith("harness-maxxing/")
    assert set(sent) == {"email", "type", "message", "version", "lang", "name", "_ua"}   # nothing else leaves the server
    assert client.get("/api/settings/feedback").json()["email"] == "me@x.io"


def test_the_email_of_the_profile_is_the_first_default(client, cloud):
    config.update_config(register={"email": "team@x.io"})
    assert client.get("/api/settings/feedback").json()["email"] == "team@x.io"


def test_email_and_message_are_required(client, cloud):
    assert client.post("/api/settings/feedback", json={"email": "nope", "message": "hello"}).json()["error"] == "invalid_email"
    assert client.post("/api/settings/feedback", json={"email": "a@b.io", "message": "  "}).json()["error"] == "message_required"
    assert client.post("/api/settings/feedback", json={"email": "a@b.io", "message": "x" * 4001}).json()["error"] == "too_long"
    assert client.post("/api/settings/feedback", json={"email": "a@b.io", "type": "spam", "message": "hi there"}).status_code == 422
    assert cloud.got == []


def test_the_cloud_rate_limit_is_passed_on(client, cloud):
    for _ in range(2):
        assert client.post("/api/settings/feedback", json={"email": "a@b.io", "message": "hello"}).status_code == 200
    r = client.post("/api/settings/feedback", json={"email": "a@b.io", "message": "hello"})
    assert r.status_code == 429 and r.json()["error"] == "rate"


def test_feedback_email_is_capped(client, cloud):
    big = "a" * 1_000_000 + "@example.com"
    r = client.post("/api/settings/feedback", json={"email": big, "message": "hello there"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_email"
    assert cloud.got == [] and not config.load_config().get("feedback_email")


def test_a_cut_answer_is_unreachable_not_a_500(client, mx, monkeypatch):
    def cut(*a, **k):
        raise http.client.IncompleteRead(b"x")
    monkeypatch.setattr(register, "_offline", lambda: False)
    monkeypatch.setattr("urllib.request.urlopen", cut)
    r = client.post("/api/settings/feedback", json={"email": "a@b.io", "message": "hello"})
    assert r.status_code == 502 and r.json()["error"] == "unreachable"
    with pytest.raises(license.LicenseError) as e:
        license.activate("HM-ABCD-EFGH-JKMN-PQRS")
    assert e.value.code == "network" and not config.get_secret(license.KEY)


def test_unreachable_or_offline_cloud(client, mx, monkeypatch):
    monkeypatch.setattr(license, "API", "http://127.0.0.1:9")            # nothing listens there
    monkeypatch.setattr(register, "_offline", lambda: False)
    r = client.post("/api/settings/feedback", json={"email": "a@b.io", "message": "hello"})
    assert r.status_code == 502 and r.json()["error"] == "unreachable"
    monkeypatch.setattr(register, "_offline", lambda: True)
    assert client.post("/api/settings/feedback", json={"email": "a@b.io", "message": "hello"}).json()["error"] == "offline"
