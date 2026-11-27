"""Authenticator app (TOTP) as a second sign-in step, recovery codes."""
from __future__ import annotations

import base64
import time

import pytest
from fastapi.testclient import TestClient

from maxxing import config, security, twofactor

PW = "correct horse battery"
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    twofactor.reset()
    security._fails.clear()
    security._good.clear()
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    yield
    twofactor.reset()
    security._fails.clear()


_real_sleep = __import__("asyncio").sleep


async def _no_sleep(s, *a, **k):
    await _real_sleep(0)


def _code(secret: str, shift: int = 0) -> str:
    return twofactor.totp_at(secret, int(time.time() // 30) + shift)


def _enrol(client: TestClient) -> tuple[str, list[str]]:
    r = client.post("/api/auth/totp", json={"password": PW})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    r = client.post("/api/auth/totp/confirm", json={"code": _code(secret)})
    assert r.status_code == 200, r.text
    return secret, r.json()["recovery_codes"]


def _stranger(client: TestClient) -> TestClient:
    c = TestClient(client.app)
    c.headers["X-Maxxing"] = "1"
    return c


def _login(c: TestClient) -> dict:
    r = c.post("/api/auth/login", json={"password": PW})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("t,code", [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
                                    (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130")])
def test_rfc6238_sha1_vectors(t, code):
    assert twofactor.totp_at(RFC_SECRET, t // 30) == code          # the RFC lists 8 digits: these are their last 6


def test_window_and_replay(mx):
    config.set_secret("totp", {"secret": RFC_SECRET})
    now = 1_700_000_015.0
    step = int(now // 30)
    assert not twofactor.totp_verify(twofactor.totp_at(RFC_SECRET, step - 2), now)
    assert not twofactor.totp_verify(twofactor.totp_at(RFC_SECRET, step + 2), now)
    assert not twofactor.totp_verify("12345", now) and not twofactor.totp_verify("abcdef", now)
    assert twofactor.totp_verify(twofactor.totp_at(RFC_SECRET, step - 1), now)
    assert not twofactor.totp_verify(twofactor.totp_at(RFC_SECRET, step - 1), now)      # replay
    assert twofactor.totp_verify(twofactor.totp_at(RFC_SECRET, step), now)
    assert not twofactor.totp_verify(twofactor.totp_at(RFC_SECRET, step - 1), now)      # older than the last used
    assert twofactor.totp_verify(twofactor.totp_at(RFC_SECRET, step + 1), now)
    assert not twofactor.totp_verify(twofactor.totp_at(RFC_SECRET, step + 1), now)


def test_enrolment_needs_password_and_confirm(client):
    assert client.post("/api/auth/totp", json={"password": "wrong wrong wrong"}).status_code == 401
    r = client.post("/api/auth/totp", json={"password": PW})
    body = r.json()
    secret = body["secret"]
    assert len(base64.b32decode(secret)) == 20
    assert body["uri"].startswith("otpauth://totp/Harness%20Maxxing%3A")
    for part in (f"secret={secret}", "issuer=Harness%20Maxxing", "algorithm=SHA1", "digits=6", "period=30"):
        assert part in body["uri"]
    # not active before a code was typed: the password alone still signs in, the state says off
    assert client.get("/api/auth/second-factor").json() == {"telegram": False, "totp": False, "recovery_left": 0}
    assert not twofactor.required()
    assert _login(_stranger(client)) == {"ok": True}
    assert client.post("/api/auth/totp/confirm", json={"code": "000000"}).status_code == 400
    assert not twofactor.totp_on()
    r = client.post("/api/auth/totp/confirm", json={"code": _code(secret)})
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert client.get("/api/auth/second-factor").json() == {"telegram": False, "totp": True, "recovery_left": 10}
    # stored: the secret in secrets.json only, the recovery codes hashed; nothing gives the secret back
    assert secret not in (config.STATE / "config.json").read_text()
    stored = config.load_secrets()
    assert stored["totp"]["secret"] == secret and "pending" not in stored["totp"]
    assert all(c not in str(stored["recovery_codes"]) for c in codes)
    assert secret not in client.get("/api/auth/second-factor").text + client.get("/api/auth/state").text
    # the code that confirmed cannot sign in (same step)
    assert not twofactor.totp_verify(_code(secret))


def test_sign_in_with_app_code(client):
    secret, _ = _enrol(client)
    c = _stranger(client)
    two = _login(c)["two_factor"]
    assert two["methods"] == ["totp"]
    assert security.COOKIE not in c.cookies
    assert c.get("/api/sessions").status_code == 401
    assert c.post("/api/auth/two-factor", json={"challenge": two["challenge"]}).json()["status"] == "pending"
    r = c.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": "000000"})
    assert r.status_code == 400 and r.json()["error"] == "bad_code"
    code = _code(secret, 1)
    r = c.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": code})
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    assert c.get("/api/sessions").status_code == 200
    # trusted browser: no second step next time; a new browser cannot replay the code
    assert _login(c) == {"ok": True}
    d = _stranger(client)
    two = _login(d)["two_factor"]
    assert d.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": code}).status_code == 400


def test_wrong_codes_hit_the_attempt_limiter(client):
    _enrol(client)
    c = _stranger(client)
    seen = []
    for _ in range(4):                                   # 5 wrong codes end a challenge; 8 block the client
        try:
            two = _login(c)["two_factor"]
        except AssertionError:
            break
        for _ in range(5):
            r = c.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": "000000"})
            seen.append((r.status_code, r.json().get("error")))
            if r.status_code != 400:
                break
        if seen[-1][0] == 429:
            break
    assert (429, "throttled") in seen
    assert sum(1 for s in seen if s == (400, "bad_code")) <= security.FAIL_MAX
    assert security.failures_last_hour() >= security.FAIL_MAX


def test_recovery_codes_once_only(client):
    secret, codes = _enrol(client)
    c = _stranger(client)
    two = _login(c)["two_factor"]
    r = c.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": codes[0].upper(), "trust": False})
    assert r.status_code == 200, r.text
    assert twofactor.recovery_left() == 9
    d = _stranger(client)
    two = _login(d)["two_factor"]
    assert d.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": codes[0]}).status_code == 400
    assert d.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": codes[1]}).status_code == 200
    # new ones need the password and end the old ones
    assert client.post("/api/auth/recovery-codes", json={"password": "nope nope nope"}).status_code == 401
    fresh = client.post("/api/auth/recovery-codes", json={"password": PW}).json()["recovery_codes"]
    assert len(fresh) == 10 and not set(fresh) & set(codes)
    assert not twofactor.use_recovery(codes[2]) and twofactor.use_recovery(fresh[0])
    assert not twofactor.use_recovery(fresh[0])


def test_turning_off_needs_password_and_code(client):
    secret, codes = _enrol(client)
    assert client.post("/api/auth/totp/off", json={"password": "nope nope nope", "code": codes[0]}).status_code == 401
    assert client.post("/api/auth/totp/off", json={"password": PW, "code": "000000"}).status_code == 400
    assert twofactor.totp_on() and twofactor.recovery_left() == 10
    assert client.post("/api/auth/totp/off", json={"password": PW, "code": codes[0]}).status_code == 200
    s = config.load_secrets()
    assert "totp" not in s and "recovery_codes" not in s
    assert _login(_stranger(client)) == {"ok": True}
    assert client.post("/api/auth/recovery-codes", json={"password": PW}).status_code == 409


def test_telegram_and_app_together(client, monkeypatch):
    """Both on: the Telegram message is sent as before, and its code, an app code or a recovery code all work."""
    secret, codes = _enrol(client)
    config.update_config(telegram={"chat_id": 1, "user_ids": [2], "two_factor": True})
    config.set_secret("telegram_token", "1:x")
    sent = []
    monkeypatch.setattr(twofactor, "_send", lambda c: sent.append(c) or True)
    c = _stranger(client)
    two = _login(c)["two_factor"]
    assert two["methods"] == ["telegram", "totp"] and len(sent) == 1
    r = c.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": _code(secret, 1)})
    assert r.status_code == 200, r.text
    d = _stranger(client)
    two = _login(d)["two_factor"]
    assert d.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": sent[-1].code}).status_code == 200
    # Telegram refuses the message: the app still gets the owner in
    monkeypatch.setattr(twofactor, "_send", lambda c: False)
    e = _stranger(client)
    two = _login(e)["two_factor"]
    assert two["methods"] == ["totp"]
    assert e.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": codes[3]}).status_code == 200
    # the app off: Telegram stays, with the recovery codes
    twofactor.totp_off()
    assert twofactor.required() and twofactor.recovery_left() == 9
    twofactor.set_on(False)
    assert twofactor.recovery_left() == 0


def test_recovery_code_with_telegram_only(client, monkeypatch):
    config.update_config(telegram={"chat_id": 1, "user_ids": [2], "two_factor": True})
    config.set_secret("telegram_token", "1:x")
    monkeypatch.setattr(twofactor, "_send", lambda c: True)
    codes = client.post("/api/auth/recovery-codes", json={"password": PW}).json()["recovery_codes"]
    c = _stranger(client)
    two = _login(c)["two_factor"]
    assert two["methods"] == ["telegram"]
    assert c.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": codes[4]}).status_code == 200
    # an "enable" challenge never takes a recovery code
    twofactor.set_on(False)
    config.set_secret("recovery_codes", [twofactor._hash(twofactor._clean(codes[5]))])
    two = client.put("/api/auth/two-factor", json={"enabled": True}).json()["two_factor"]
    r = client.post("/api/auth/two-factor", json={"challenge": two["challenge"], "code": codes[5]})
    assert r.status_code == 400 and not twofactor.is_on()


def test_cli_way_out(client, capsys):
    from maxxing import cmd_twofactor
    _enrol(client)

    class A:
        action = "status"
        json = True
    assert cmd_twofactor._handler(A) == 0
    assert '"totp": true' in capsys.readouterr().out
    A.action = "off"
    assert cmd_twofactor._handler(A) == 0
    assert not twofactor.totp_on() and twofactor.recovery_left() == 0
    assert _login(_stranger(client)) == {"ok": True}
