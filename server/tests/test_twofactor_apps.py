"""Two-step sign-in with an authenticator app (TOTP), passkeys (WebAuthn, a software authenticator here) and recovery
codes: setup in Settings -> Security, the second step at sign-in, replay and guessing limits, `maxxing 2fa off`."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time

import cbor2
import pyotp
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from maxxing import cli, config, security, twofactor, twofactor_apps

H = {"X-Maxxing": "1"}
PW = "correct horse battery"
ORIGIN, RP = "http://testserver", "testserver"


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SoftKey:
    """A passkey in software: makes and signs WebAuthn answers like a real authenticator ("none" attestation)."""

    def __init__(self, origin: str = ORIGIN, rp_id: str = RP):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = os.urandom(16)
        self.count = 0
        self.origin, self.rp_id = origin, rp_id

    def _client_data(self, kind: str, challenge: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin, "crossOrigin": False}).encode()

    def create(self, options: dict) -> dict:
        nums = self.key.public_key().public_numbers()
        cose = cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})
        auth = (hashlib.sha256(options["rp"]["id"].encode()).digest() + bytes([0x45]) + (0).to_bytes(4, "big")
                + bytes(16) + len(self.id).to_bytes(2, "big") + self.id + cose)
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": b64(self.id), "rawId": b64(self.id), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64(self._client_data("webauthn.create", options["challenge"])),
                             "attestationObject": b64(att), "transports": ["internal"]}}

    def get(self, options: dict) -> dict:
        self.count += 1
        auth = hashlib.sha256(options["rpId"].encode()).digest() + bytes([0x05]) + self.count.to_bytes(4, "big")
        cd = self._client_data("webauthn.get", options["challenge"])
        sig = self.key.sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.id), "rawId": b64(self.id), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64(cd), "authenticatorData": b64(auth), "signature": b64(sig),
                             "userHandle": None}}


@pytest.fixture
def app(mx):
    security.set_password(PW)
    security._fails.clear()
    twofactor.reset()
    twofactor_apps.reset()
    from maxxing.app import create_app
    return create_app()


def _signed_in(app) -> TestClient:
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"password": PW}, headers=H).json()["ok"] is True
    return c


def _add_totp(c) -> tuple[str, list[str]]:
    s = c.post("/api/auth/two-factor/totp/setup", json={"password": PW}, headers=H).json()
    assert s["uri"].startswith("otpauth://totp/")
    r = c.post("/api/auth/two-factor/totp", json={"setup": s["setup"], "code": pyotp.TOTP(s["secret"]).now()}, headers=H)
    assert r.status_code == 200, r.text
    return s["secret"], r.json()["recovery_codes"]


def _add_passkey(c, key: SoftKey) -> dict:
    o = c.post("/api/auth/two-factor/passkeys/options", json={"password": PW}, headers=H).json()
    r = c.post("/api/auth/two-factor/passkeys", json={"setup": o["setup"], "credential": key.create(o["options"]),
                                                       "name": "Laptop"}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def _second_step(app) -> tuple[TestClient, dict]:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"password": PW}, headers=H).json()
    assert r["ok"] is False and "ticket" in r["two_factor"]
    assert c.get("/api/auth/state").json()["authenticated"] is False
    return c, r["two_factor"]


def _later(monkeypatch, seconds: float) -> None:
    now = time.time() + seconds
    monkeypatch.setattr(twofactor_apps.time, "time", lambda: now)


def test_an_authenticator_app_is_asked_after_the_password(app, monkeypatch):
    secret, codes = _add_totp(_signed_in(app))
    assert len(codes) == 10 and len(set(codes)) == 10
    c, tf = _second_step(app)
    assert tf["methods"] == ["totp", "recovery"]
    code = pyotp.TOTP(secret).at(time.time() + 31)            # the setup code's step is spent: the next one signs in
    _later(monkeypatch, 31)
    r = c.post("/api/auth/two-factor/code", json={"ticket": tf["ticket"], "code": code, "trust": False}, headers=H)
    assert r.status_code == 200 and c.get("/api/auth/state").json()["authenticated"] is True
    assert "mx_device" not in r.cookies
    # the same code, again: refused (read over a shoulder), and the ticket was spent
    c2, tf2 = _second_step(app)
    r = c2.post("/api/auth/two-factor/code", json={"ticket": tf2["ticket"], "code": code}, headers=H)
    assert r.status_code == 400 and r.json()["error"] == "bad_code"
    assert c.post("/api/auth/two-factor/code", json={"ticket": tf["ticket"], "code": code}, headers=H).status_code == 410


def test_a_setup_needs_the_password_and_a_right_code(app):
    c = _signed_in(app)
    assert c.post("/api/auth/two-factor/totp/setup", json={"password": "nope"}, headers=H).status_code == 401
    s = c.post("/api/auth/two-factor/totp/setup", json={"password": PW}, headers=H).json()
    assert c.post("/api/auth/two-factor/totp", json={"setup": s["setup"], "code": "000000"}, headers=H).status_code == 400
    assert not twofactor_apps.totp_on()                        # a wrong first code turns nothing on
    assert TestClient(app).post("/api/auth/two-factor/totp/setup", json={"password": PW}, headers=H).status_code == 401


def test_five_wrong_codes_kill_the_ticket(app):
    _add_totp(_signed_in(app))
    c, tf = _second_step(app)
    for left in (4, 3, 2, 1):
        r = c.post("/api/auth/two-factor/code", json={"ticket": tf["ticket"], "code": "000000"}, headers=H)
        assert r.json()["tries_left"] == left
    assert c.post("/api/auth/two-factor/code", json={"ticket": tf["ticket"], "code": "000000"}, headers=H).status_code == 410


def test_a_ticket_is_bound_to_its_client(app):
    secret, _ = _add_totp(_signed_in(app))
    _, tf = _second_step(app)
    other = TestClient(app, client=("203.0.113.9", 5000))
    r = other.post("/api/auth/two-factor/code", json={"ticket": tf["ticket"], "code": pyotp.TOTP(secret).now()}, headers=H)
    assert r.status_code == 410


def test_a_recovery_code_works_once(app):
    _, codes = _add_totp(_signed_in(app))
    c, tf = _second_step(app)
    r = c.post("/api/auth/two-factor/code", json={"ticket": tf["ticket"], "code": codes[0].upper()}, headers=H)
    assert r.status_code == 200 and twofactor_apps.recovery_left() == 9
    c2, tf2 = _second_step(app)
    assert c2.post("/api/auth/two-factor/code", json={"ticket": tf2["ticket"], "code": codes[0]}, headers=H).status_code == 400
    new = c.post("/api/auth/two-factor/recovery-codes", json={"password": PW}, headers=H).json()["recovery_codes"]
    assert twofactor_apps.recovery_left() == 10 and codes[1] not in new
    c3, tf3 = _second_step(app)                                # the old ones are gone
    assert c3.post("/api/auth/two-factor/code", json={"ticket": tf3["ticket"], "code": codes[1]}, headers=H).status_code == 400


def test_a_passkey_signs_in(app):
    key = SoftKey()
    added = _add_passkey(_signed_in(app), key)
    assert added["passkey"]["rp_id"] == RP and len(added["recovery_codes"]) == 10
    c, tf = _second_step(app)
    assert tf["methods"] == ["passkey", "recovery"]
    opts = c.post("/api/auth/two-factor/passkey/options", json={"ticket": tf["ticket"]}, headers=H).json()["options"]
    assert [a["id"] for a in opts["allowCredentials"]] == [b64(key.id)]
    r = c.post("/api/auth/two-factor/passkey", json={"ticket": tf["ticket"], "credential": key.get(opts)}, headers=H)
    assert r.status_code == 200, r.text
    assert c.get("/api/auth/state").json()["authenticated"] is True and "mx_device" in r.cookies
    assert config.load_secrets()["passkeys"][0]["sign_count"] == 1


def test_a_passkey_answer_is_checked(app):
    key = SoftKey()
    _add_passkey(_signed_in(app), key)
    c, tf = _second_step(app)
    opts = c.post("/api/auth/two-factor/passkey/options", json={"ticket": tf["ticket"]}, headers=H).json()["options"]
    stranger = SoftKey()
    stranger.id = key.id                                       # same id, another key: the signature fails
    r = c.post("/api/auth/two-factor/passkey", json={"ticket": tf["ticket"], "credential": stranger.get(opts)}, headers=H)
    assert r.status_code == 400 and r.json()["error"] == "bad_passkey"
    # the challenge was spent by that answer: even the right key needs new options
    r = c.post("/api/auth/two-factor/passkey", json={"ticket": tf["ticket"], "credential": key.get(opts)}, headers=H)
    assert r.status_code == 400
    phish = SoftKey(origin="https://evil.example.com")         # signed for another page
    phish.key, phish.id = key.key, key.id
    opts = c.post("/api/auth/two-factor/passkey/options", json={"ticket": tf["ticket"]}, headers=H).json()["options"]
    r = c.post("/api/auth/two-factor/passkey", json={"ticket": tf["ticket"], "credential": phish.get(opts)}, headers=H)
    assert r.status_code == 400
    assert c.get("/api/auth/state").json()["authenticated"] is False


def test_a_passkey_of_another_address_is_not_offered(app):
    key = SoftKey()
    _add_passkey(_signed_in(app), key)
    secrets_ = config.load_secrets()
    secrets_["passkeys"][0]["rp_id"] = "ui.example.com"
    config.set_secret("passkeys", secrets_["passkeys"])
    c, tf = _second_step(app)
    assert tf["methods"] == ["recovery"]
    r = c.post("/api/auth/two-factor/passkey/options", json={"ticket": tf["ticket"]}, headers=H)
    assert r.status_code == 409 and r.json()["error"] == "no_passkey"


def test_removing_the_last_method_removes_the_recovery_codes(app):
    c = _signed_in(app)
    key = SoftKey()
    pid = _add_passkey(c, key)["passkey"]["id"]
    _, codes = _add_totp(c)
    assert codes is None                                       # codes are made with the first method only
    assert c.post("/api/auth/two-factor/totp/off", json={"password": PW}, headers=H).status_code == 200
    assert twofactor_apps.recovery_left() == 10
    assert c.post("/api/auth/two-factor/passkeys/remove", json={"id": pid, "password": "nope"}, headers=H).status_code == 401
    assert c.post("/api/auth/two-factor/passkeys/remove", json={"id": pid, "password": PW}, headers=H).status_code == 200
    assert twofactor_apps.recovery_left() == 0 and not twofactor_apps.any_on()
    assert TestClient(app).post("/api/auth/login", json={"password": PW}, headers=H).json()["ok"] is True


def test_a_password_change_kills_the_waiting_tickets(app):
    secret, _ = _add_totp(_signed_in(app))
    c, tf = _second_step(app)
    security.set_password(PW + "!")
    r = c.post("/api/auth/two-factor/code", json={"ticket": tf["ticket"], "code": pyotp.TOTP(secret).now()}, headers=H)
    assert r.status_code == 410


def test_maxxing_2fa_off_turns_every_method_off(app, capsys):
    c = _signed_in(app)
    _add_totp(c)
    _add_passkey(c, SoftKey())
    assert cli.main(["2fa", "status"]) == 0
    assert "authenticator app, 1 passkey(s), 10 recovery code(s) left" in capsys.readouterr().out
    assert cli.main(["2fa", "off"]) == 0
    assert not twofactor_apps.any_on() and twofactor_apps.recovery_left() == 0
    assert TestClient(app).post("/api/auth/login", json={"password": PW}, headers=H).json()["ok"] is True


def test_the_methods_list(app):
    c = _signed_in(app)
    assert c.get("/api/auth/two-factor/methods").json() == {"telegram": False, "totp": False, "recovery_left": 0,
                                                            "rp_id": RP, "passkeys": []}
    _add_passkey(c, SoftKey())
    m = c.get("/api/auth/two-factor/methods").json()
    assert m["passkeys"][0]["name"] == "Laptop" and "public_key" not in m["passkeys"][0]
    assert TestClient(app).get("/api/auth/two-factor/methods").status_code == 401


def test_removing_a_method_forgets_the_other_trusted_browsers(app):
    c = _signed_in(app)
    _add_totp(c)
    other = TestClient(app, client=("203.0.113.7", 5000))
    other.cookies.set("mx_device", twofactor.make_device_cookie())     # a browser trusted earlier (or a copied cookie)
    assert other.post("/api/auth/login", json={"password": PW}, headers=H).json()["ok"] is True
    _add_passkey(c, SoftKey())
    r = c.post("/api/auth/two-factor/totp/off", json={"password": PW}, headers=H)   # the phone was stolen
    assert r.status_code == 200 and "mx_device" in r.cookies                         # this browser stays trusted
    assert other.post("/api/auth/login", json={"password": PW}, headers=H).json()["ok"] is False
    assert cli.main(["2fa", "off"]) == 0
    assert not twofactor.device_trusted(r.cookies["mx_device"])


def test_one_client_cannot_flood_the_tickets(app):
    _add_totp(_signed_in(app))
    c = TestClient(app, client=("203.0.113.8", 5000))
    for _ in range(twofactor_apps.TICKETS_PER_CLIENT):
        assert "ticket" in c.post("/api/auth/login", json={"password": PW}, headers=H).json()["two_factor"]
    r = c.post("/api/auth/login", json={"password": PW}, headers=H)
    assert r.status_code == 429 and r.json()["error"] == "throttled"
    assert "ticket" in TestClient(app).post("/api/auth/login", json={"password": PW}, headers=H).json()["two_factor"]


def test_a_refused_passkey_says_no_more_than_that(app):
    key = SoftKey()
    _add_passkey(_signed_in(app), key)
    c, tf = _second_step(app)
    opts = c.post("/api/auth/two-factor/passkey/options", json={"ticket": tf["ticket"]}, headers=H).json()["options"]
    bad = key.get(opts)
    bad["response"]["signature"] = b64(b"\x30\x06\x02\x01\x01\x02\x01\x01")
    r = c.post("/api/auth/two-factor/passkey", json={"ticket": tf["ticket"], "credential": bad}, headers=H)
    assert r.status_code == 400 and r.json()["message"] == "The passkey answer was refused"


def test_the_public_url_is_an_accepted_origin(app):
    cfg = config.load_config()
    cfg["public_url"] = "https://testserver"
    config.save_config(cfg)
    key = SoftKey(origin="https://testserver")                 # a proxy that drops X-Forwarded-Proto
    _add_passkey(_signed_in(app), key)
    c, tf = _second_step(app)
    opts = c.post("/api/auth/two-factor/passkey/options", json={"ticket": tf["ticket"]}, headers=H).json()["options"]
    assert opts["allowCredentials"][0].get("transports") == ["internal"]
    r = c.post("/api/auth/two-factor/passkey", json={"ticket": tf["ticket"], "credential": key.get(opts)}, headers=H)
    assert r.status_code == 200, r.text
