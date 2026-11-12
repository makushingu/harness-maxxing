"""Terminals of the web app: off by default, password to turn on, websocket auth, limits, idle close."""
import json
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from maxxing import terminal

ORIGIN = {"origin": "http://testserver"}


@pytest.fixture
def term_env(mx, monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("HOME", str(mx["tmp"]))
    yield mx
    terminal.close_all()


@pytest.fixture
def on(client, term_env):
    assert client.post("/api/term/enable", json={"password": "correct horse battery"}).json() == {"enabled": True}
    return client


def _read_until(ws, needle: bytes, limit: int = 200) -> bytes:
    got = b""
    for _ in range(limit):
        got += ws.receive_bytes()
        if needle in got:
            return got
    raise AssertionError(got[-500:])


def test_off_by_default_and_the_password_turns_it_on(client, term_env):
    assert client.get("/api/term").json()["enabled"] is False
    assert client.get("/api/settings").json()["terminal_feature"] is False
    r = client.post("/api/term", json={"cwd": str(term_env["files"])})
    assert r.status_code == 403 and r.json()["error"] == "term_off"
    assert client.post("/api/term/enable", json={"password": "wrong"}).status_code == 401
    assert client.get("/api/term").json()["enabled"] is False
    assert client.post("/api/term/enable", json={"password": "correct horse battery"}).status_code == 200
    assert client.get("/api/settings").json()["terminal_feature"] is True


def test_a_terminal_runs_commands_in_its_folder(on, term_env):
    t = on.post("/api/term", json={"cwd": str(term_env["files"]), "cols": 80, "rows": 24}).json()
    with on.websocket_connect(f"/api/term/{t['id']}/ws?token={t['token']}", headers=ORIGIN) as ws:
        ws.send_text(json.dumps({"r": [120, 40]}))
        ws.send_text(json.dumps({"i": "echo hi-$((1+2)); pwd\n"}))
        out = _read_until(ws, str(term_env["files"]).encode())
        assert b"hi-3" in out
    # a page reload: a new token, the output since the start comes first
    tok = on.post(f"/api/term/{t['id']}/token").json()["token"]
    with on.websocket_connect(f"/api/term/{t['id']}/ws?token={tok}", headers=ORIGIN) as ws:
        assert b"hi-3" in ws.receive_bytes()
    assert [x["id"] for x in on.get("/api/term").json()["terms"]] == [t["id"]]
    assert on.delete(f"/api/term/{t['id']}").json() == {"ok": True}
    assert terminal.wait_gone(t["id"], 5)


def test_the_websocket_needs_a_fresh_token_the_cookie_and_the_same_origin(on, term_env):
    t = on.post("/api/term", json={"cwd": str(term_env["files"])}).json()
    for url, headers in ((f"/api/term/{t['id']}/ws?token=nope", ORIGIN),
                         (f"/api/term/{t['id']}/ws?token={t['token']}", {"origin": "https://evil.example.com"})):
        with pytest.raises(WebSocketDisconnect):
            with on.websocket_connect(url, headers=headers) as ws:
                ws.receive_bytes()
    tok = on.post(f"/api/term/{t['id']}/token").json()["token"]
    with on.websocket_connect(f"/api/term/{t['id']}/ws?token={tok}", headers=ORIGIN):
        pass
    with pytest.raises(WebSocketDisconnect):                     # used once
        with on.websocket_connect(f"/api/term/{t['id']}/ws?token={tok}", headers=ORIGIN) as ws:
            ws.receive_bytes()
    on.cookies.clear()
    tok = terminal.token(t["id"])
    with pytest.raises(WebSocketDisconnect):
        with on.websocket_connect(f"/api/term/{t['id']}/ws?token={tok}", headers=ORIGIN) as ws:
            ws.receive_bytes()


def test_folder_limit_idle_and_turning_off(on, term_env, tmp_path):
    r = on.post("/api/term", json={"cwd": str(tmp_path.parent)})
    assert r.status_code == 400 and r.json()["error"] == "bad_cwd"
    ids = [on.post("/api/term", json={"cwd": str(term_env["files"])}).json()["id"] for _ in range(terminal.MAX_TERMS)]
    r = on.post("/api/term", json={"cwd": str(term_env["files"])})
    assert r.status_code == 409 and r.json()["error"] == "too_many"
    terminal.get(ids[0]).last = time.time() - terminal.IDLE_S - 1
    assert terminal.reap_idle() == [ids[0]]
    assert terminal.wait_gone(ids[0], 5)
    assert on.post("/api/term/disable").json()["closed"] == terminal.MAX_TERMS - 1
    for i in ids[1:]:
        assert terminal.wait_gone(i, 5)
    assert on.post("/api/term", json={"cwd": str(term_env["files"])}).status_code == 403


def test_doctor_lists_programs_started_by_hand_and_forgotten():
    from maxxing.cmd_core import stale_units
    now = 1_800_000_000
    show = "\n\n".join([
        f"Id=pm-preview.service\nTransient=yes\nActiveEnterTimestamp=@{now - 20 * 86400}",
        f"Id=mx-dev.service\nTransient=yes\nActiveEnterTimestamp=@{now - 2 * 86400}",
        f"Id=maxxing-0c86cf6b.service\nTransient=yes\nActiveEnterTimestamp=@{now - 30 * 86400}",
        f"Id=caddy.service\nTransient=no\nActiveEnterTimestamp=@{now - 90 * 86400}",
        f"Id=old-dovecot.service\nTransient=yes\nActiveEnterTimestamp=@{now - 8 * 86400}",
    ])
    assert stale_units(show, now) == [("pm-preview.service", 20), ("old-dovecot.service", 8)]
