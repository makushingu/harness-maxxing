"""Signed-in browsers: list, disconnect, cookies from before the list; open WebSockets follow the sign-in."""
from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

from maxxing import config, security, terminal

PW = "correct horse battery"
CHROME = "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"


@pytest.fixture(autouse=True)
def _fresh():
    security._fails.clear()
    security._seen_at.clear()
    yield
    security._fails.clear()


def _browser(client: TestClient, ua: str) -> TestClient:
    c = TestClient(client.app)
    c.headers.update({"X-Maxxing": "1", "User-Agent": ua})
    assert c.post("/api/auth/login", json={"password": PW}).json() == {"ok": True}
    return c


def _legacy_cookie() -> str:
    body = f"{int(time.time())}.{'ab' * 8}"
    return f"{body}.{hmac.new(security._cookie_key(), body.encode(), hashlib.sha256).hexdigest()}"


def test_list_and_disconnect(client):
    a, b = _browser(client, CHROME), _browser(client, FIREFOX)
    out = a.get("/api/auth/devices").json()
    assert out["legacy"] is False
    labels = {d["label"]: d for d in out["devices"]}
    assert {"Chrome · Windows", "Firefox · Linux"} <= set(labels)
    assert labels["Chrome · Windows"]["current"] and not labels["Firefox · Linux"]["current"]
    assert out["devices"][0]["current"]
    assert labels["Chrome · Windows"]["ip"] == "testclient" and labels["Chrome · Windows"]["seen"] > 0
    assert a.delete("/api/auth/devices/nope").status_code == 404
    assert a.delete(f"/api/auth/devices/{labels['Firefox · Linux']['id']}").status_code == 200
    assert b.get("/api/sessions").status_code == 401
    assert a.get("/api/sessions").status_code == 200 and client.get("/api/sessions").status_code == 200
    assert a.post("/api/auth/devices/disconnect-others").status_code == 200
    assert client.get("/api/sessions").status_code == 401
    assert [d["current"] for d in a.get("/api/auth/devices").json()["devices"]] == [True]


def test_sign_out_removes_the_entry(client):
    a = _browser(client, CHROME)
    n = len(client.get("/api/auth/devices").json()["devices"])
    a.post("/api/auth/logout")
    assert len(client.get("/api/auth/devices").json()["devices"]) == n - 1


def test_last_seen_written_at_most_once_a_minute(client, monkeypatch):
    a = _browser(client, CHROME)
    did = security.device_id(a.cookies[security.COOKIE])
    writes = []
    real = security._write_signins
    monkeypatch.setattr(security, "_write_signins", lambda d: (writes.append(1), real(d))[1])
    for _ in range(5):
        a.get("/api/sessions")
    assert writes == []
    security._seen_at[did] -= security.SEEN_EVERY_S + 1
    for _ in range(5):
        a.get("/api/sessions")
    assert writes == [1]


def test_cookie_from_before_the_list_keeps_working(mx):
    """An installation updated: no signins.json, cookies without an id. Nobody is signed out by the update."""
    from maxxing.app import create_app
    config.set_secrets({"password_hash": security.hash_password(PW), "cookie_key": "k" * 64})
    assert not security.signins_path().exists()
    old = _legacy_cookie()
    assert security.cookie_valid(old)
    with TestClient(create_app()) as c:
        c.headers["X-Maxxing"] = "1"
        c.cookies.set(security.COOKIE, old, domain="testserver.local", path="/")
        out = c.get("/api/auth/devices").json()
        assert out == {"devices": [], "legacy": True, "legacy_current": True}
        new = _browser(c, FIREFOX)
        out = new.get("/api/auth/devices").json()
        assert out["legacy"] is True and out["legacy_current"] is False and len(out["devices"]) == 1
        assert c.get("/api/sessions").status_code == 200                   # still in after another sign-in
        # the old browser disconnects the others: it gets a listed cookie, the new one is out
        other_old = _legacy_cookie()
        assert c.post("/api/auth/devices/disconnect-others").status_code == 200
        assert security.device_id(c.cookies[security.COOKIE])
        assert c.get("/api/sessions").status_code == 200
        assert new.get("/api/sessions").status_code == 401
        assert not security.cookie_valid(old) and not security.cookie_valid(other_old)
        out = c.get("/api/auth/devices").json()
        assert out["legacy"] is False and [d["current"] for d in out["devices"]] == [True]


def test_removed_or_lost_list_never_signs_back_in(client):
    cookie = client.cookies[security.COOKIE]
    assert security.cookie_valid(cookie)
    security.signins_path().unlink()
    security._signins_cache.update(key=None, data=None)
    assert not security.cookie_valid(cookie)


def test_password_change_ends_the_other_browsers(client):
    a = _browser(client, CHROME)
    assert client.post("/api/auth/password", json={"current": PW, "new": "another long password"}).status_code == 200
    assert a.get("/api/sessions").status_code == 401
    out = client.get("/api/auth/devices").json()
    assert out["legacy"] is False and [d["current"] for d in out["devices"]] == [True]


# ---- open WebSockets ---------------------------------------------------------------------------------------------------
@pytest.fixture
def term(client, mx, monkeypatch):
    monkeypatch.setattr(security, "GUARD_S", 0.2)
    config.update_config(code_mode=True)
    yield
    terminal.close_all()


def _open(c: TestClient, mx):
    r = c.post("/api/term", json={"cwd": str(mx["files"])})
    assert r.status_code == 200, r.text
    t = r.json()
    host = "testserver"
    return c.websocket_connect(f"/api/term/{t['id']}/ws?token={t['token']}",
                               headers={"origin": f"http://{host}", "host": host})


def _closed(ws) -> int:
    """Read until the server closes the socket -> its close code."""
    deadline = time.time() + 10
    while time.time() < deadline:
        m = ws.receive()
        if m["type"] == "websocket.close":
            return m["code"]
    raise AssertionError("socket still open")


def test_terminal_closed_on_sign_out(client, mx, term):
    a = _browser(client, CHROME)
    with _open(a, mx) as ws:
        a.post("/api/auth/logout")
        assert _closed(ws) == 4401


def test_terminal_closed_when_its_browser_is_disconnected(client, mx, term):
    a = _browser(client, CHROME)
    did = security.device_id(a.cookies[security.COOKIE])
    with _open(a, mx) as ws, _open(client, mx) as mine:
        assert client.delete(f"/api/auth/devices/{did}").status_code == 200
        assert _closed(ws) == 4401
        time.sleep(0.5)
        mine.send_text('{"r": [80, 24]}')                        # the owner's own terminal is still open


def test_terminal_closed_on_password_change_but_not_the_owners(client, mx, term):
    a = _browser(client, CHROME)
    with _open(a, mx) as ws, _open(client, mx) as mine:
        assert client.post("/api/auth/password", json={"current": PW, "new": "another long password"}).status_code == 200
        assert _closed(ws) == 4401
        time.sleep(0.5)                                          # past GUARD_S: the owner's socket was moved to the new cookie
        mine.send_text('{"i": "echo still-here\\n"}')
        assert not any(g.auth.cookie == a.cookies.get(security.COOKIE) for g in security._guards)
        assert len(security._guards) == 1


def test_terminal_closed_on_password_change_from_the_command_line(client, mx, term):
    with _open(client, mx) as ws:
        security.set_password("set from the terminal")          # `maxxing password`: nothing wakes the socket up
        assert _closed(ws) == 4401
