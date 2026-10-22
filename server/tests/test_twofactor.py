"""Two-step sign-in with Telegram: challenge on sign-in, Allow / Deny / code, trusted browser, `maxxing 2fa off`."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from _conn_helpers import TG_TOKEN, FakeTelegram
from maxxing import cli, config, security, twofactor

H = {"X-Maxxing": "1"}
PW = "correct horse battery"


@pytest.fixture
def tg(mx, monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setenv("MAXXING_TELEGRAM_API", fake.url)
    config.set_secret("telegram_token", TG_TOKEN)
    cfg = config.load_config()
    cfg["telegram"].update(chat_id=555, user_ids=[555], threads={"#alerts": 11})
    config.save_config(cfg)
    security.set_password(PW)
    security._fails.clear()
    twofactor.reset()
    yield fake
    fake.close()


def _app():
    from maxxing.app import create_app
    return create_app()


def _sent(fake) -> list[dict]:
    return [p for m, p in fake.calls if m == "sendMessage" and "a:" in json.dumps(p.get("reply_markup") or {})]


def _on():
    twofactor.set_on(True)


def _login(c) -> dict:
    r = c.post("/api/auth/login", json={"password": PW}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def test_off_by_default_password_alone_signs_in(tg):
    with TestClient(_app()) as c:
        assert _login(c) == {"ok": True}
        assert not _sent(tg)


def test_sign_in_waits_for_telegram_then_allow(tg):
    _on()
    with TestClient(_app()) as c:
        r = _login(c)
        assert r["ok"] is False and r["two_factor"]["expires_in"] == twofactor.TTL
        cid = r["two_factor"]["challenge"]
        assert c.get("/api/workspace/tree").status_code == 401           # no cookie yet
        msg = _sent(tg)[-1]
        assert msg["chat_id"] == 555 and msg["message_thread_id"] == 11
        assert "testclient" in msg["text"] and "Code" in msg["text"]
        assert twofactor.short_ua("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
                                  "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1") == "Safari · iPhone"
        assert c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H).json()["status"] == "pending"
        assert twofactor.decide(cid, True).startswith("✅")
        r = c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H)
        assert r.json() == {"ok": True, "status": "approved"}
        assert c.get("/api/workspace/tree").status_code == 200
        # collected once only
        assert c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H).status_code == 410
        # trusted browser: next sign-in skips the second step
        c.post("/api/auth/logout", headers=H)
        assert _login(c) == {"ok": True}


def test_deny_and_code(tg):
    _on()
    with TestClient(_app()) as c:
        cid = _login(c)["two_factor"]["challenge"]
        twofactor.decide(cid, False)
        r = c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H)
        assert r.status_code == 403 and r.json()["error"] == "denied"
        assert twofactor.decide(cid, True) == twofactor._w("gone")          # too late
        # the code typed by hand works too; trust=false keeps the browser untrusted
        cid = _login(c)["two_factor"]["challenge"]
        code = twofactor._ch[cid].code
        bad = "000000" if code != "000000" else "111111"
        r = c.post("/api/auth/two-factor", json={"challenge": cid, "code": bad}, headers=H)
        assert r.status_code == 400 and r.json()["tries_left"] == twofactor.CODE_TRIES - 1
        r = c.post("/api/auth/two-factor", json={"challenge": cid, "code": code, "trust": False}, headers=H)
        assert r.json()["status"] == "approved"
        assert twofactor.DEVICE_COOKIE not in c.cookies
        c.post("/api/auth/logout", headers=H)
        assert _login(c)["ok"] is False


def test_wrong_codes_kill_the_challenge_and_expiry(tg, monkeypatch):
    _on()
    with TestClient(_app()) as c:
        cid = _login(c)["two_factor"]["challenge"]
        code = twofactor._ch[cid].code
        bad = "000000" if code != "000000" else "111111"
        for _ in range(twofactor.CODE_TRIES - 1):
            assert c.post("/api/auth/two-factor", json={"challenge": cid, "code": bad}, headers=H).status_code == 400
        assert c.post("/api/auth/two-factor", json={"challenge": cid, "code": bad}, headers=H).status_code == 410
        assert c.post("/api/auth/two-factor", json={"challenge": cid, "code": code}, headers=H).status_code == 410
        cid = _login(c)["two_factor"]["challenge"]
        twofactor._ch[cid].expires = time.time() - 1
        assert c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H).status_code == 410


def test_requests_are_throttled_and_telegram_failure_is_explained(tg, monkeypatch):
    _on()
    with TestClient(_app()) as c:
        for _ in range(twofactor.NEW_MAX):
            assert _login(c)["ok"] is False
        r = c.post("/api/auth/login", json={"password": PW}, headers=H)
        assert r.status_code == 429
        twofactor.reset()
        tg.fail["sendMessage"] = (403, "Forbidden: bot was blocked by the user")
        r = c.post("/api/auth/login", json={"password": PW}, headers=H)
        assert r.status_code == 503 and "maxxing 2fa off" in r.json()["message"]
        assert c.get("/api/workspace/tree").status_code == 401


def test_turn_on_needs_an_approval_and_off_over_ssh(tg, capsys):
    with TestClient(_app()) as c:
        assert _login(c) == {"ok": True}
        r = c.put("/api/auth/two-factor", json={"enabled": True}, headers=H).json()
        cid = r["two_factor"]["challenge"]
        assert not twofactor.is_on()                               # not before Telegram answered
        twofactor.decide(cid, True)
        assert c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H).json()["status"] == "approved"
        assert twofactor.enabled() and "two_factor" not in c.get("/api/auth/state").json()      # public route
        assert c.get("/api/telegram").json()["settings"]["two_factor"] is True
        c.post("/api/auth/logout", headers=H)
        assert _login(c) == {"ok": True}                           # this browser was trusted when turning on
        c.cookies.clear()
        assert _login(c)["ok"] is False
    assert cli.main(["2fa", "status"]) == 0 and "on" in capsys.readouterr().out
    assert cli.main(["2fa", "off"]) == 0
    assert "off" in capsys.readouterr().out and not twofactor.is_on()
    with TestClient(_app()) as c:
        assert _login(c) == {"ok": True}


def test_password_change_and_unlink_forget_browsers(tg):
    _on()
    with TestClient(_app()) as c:
        cid = _login(c)["two_factor"]["challenge"]
        twofactor.decide(cid, True)
        c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H)
        old = c.cookies.get(twofactor.DEVICE_COOKIE)
        assert twofactor.device_trusted(old)
        r = c.post("/api/auth/password", json={"current": PW, "new": PW}, headers=H)
        assert r.status_code == 200
        assert not twofactor.device_trusted(old)                   # other browsers ask again
        assert twofactor.device_trusted(c.cookies.get(twofactor.DEVICE_COOKIE))   # not this one
        assert c.delete("/api/telegram", headers=H).status_code == 200
        assert not twofactor.is_on()


@pytest.mark.parametrize("cmd", [
    "import getpass; getpass.getpass=lambda p='': 'brand new password 42'\n"
    "from maxxing import cli; raise SystemExit(cli.main(['password']))",
    "from maxxing import cli; raise SystemExit(cli.main(['2fa', 'forget-browsers']))",
    "from maxxing import cli; raise SystemExit(cli.main(['2fa', 'off']))",
])
def test_cli_password_or_forget_kills_approved_challenge(tg, cmd):
    """`maxxing password` / `2fa forget-browsers` / `2fa off` run in another process than the server: a request
    already approved there must not be collectable afterwards."""
    _on()
    with TestClient(_app()) as c:
        cid = _login(c)["two_factor"]["challenge"]
        twofactor.decide(cid, True)                    # Allow pressed by mistake
        env = {**os.environ}
        env.pop("PYTHONPATH", None)
        r = subprocess.run([sys.executable, "-c", cmd], env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-500:]
        r = c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H)
        assert r.status_code == 410, (r.status_code, r.text)
        if "forget-browsers" in cmd:                   # a request made after the command still works
            _on()
            cid = _login(c)["two_factor"]["challenge"]
            twofactor.decide(cid, True)
            assert c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H).json()["status"] == "approved"
