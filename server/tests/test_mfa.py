"""Two-step sign-in with an authenticator app (TOTP), passkeys (WebAuthn) and recovery codes."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from maxxing import cli, config, mfa, security, totp, twofactor

H = {"X-Maxxing": "1"}
PW = "correct horse battery"
ORIGIN = "https://ui.example.com"


# ---- a software authenticator ------------------------------------------------------------------
def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Authenticator:
    """Makes and uses one ES256 passkey like a browser + authenticator would (attestation "none")."""

    def __init__(self, rp_id: str = "ui.example.com", origin: str = ORIGIN):
        self.rp_id, self.origin = rp_id, origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.count = 0

    def _client_data(self, kind: str, challenge: str, origin: str | None = None) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin or self.origin,
                           "crossOrigin": False}).encode()

    def create(self, options: dict, rp_id: str | None = None, origin: str | None = None) -> dict:
        nums = self.key.public_key().public_numbers()
        cose = {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
        attested = bytes(16) + struct.pack(">H", len(self.cred_id)) + self.cred_id + cbor2.dumps(cose)
        auth = hashlib.sha256((rp_id or self.rp_id).encode()).digest() + bytes([0x45]) + struct.pack(">I", 0) + attested
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        cd = self._client_data("webauthn.create", options["challenge"], origin)
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64(cd), "attestationObject": b64(att), "transports": ["internal"]},
                "clientExtensionResults": {}}

    def get(self, options: dict, origin: str | None = None, count: int | None = None) -> dict:
        self.count = self.count + 1 if count is None else count
        auth = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x05]) + struct.pack(">I", self.count)
        cd = self._client_data("webauthn.get", options["challenge"], origin)
        sig = self.key.sign(auth + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64(self.cred_id), "rawId": b64(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64(cd), "authenticatorData": b64(auth), "signature": b64(sig),
                             "userHandle": None},
                "clientExtensionResults": {}}


# ---- fixtures ---------------------------------------------------------------------------------
@pytest.fixture
def app(mx):
    security.set_password(PW)
    security._fails.clear()
    twofactor.reset()
    mfa.reset()
    from maxxing.app import create_app
    return create_app()


def _signed_in(app, base: str = ORIGIN) -> TestClient:
    c = TestClient(app, base_url=base)
    c.cookies.set(security.COOKIE, security.make_cookie())
    c.headers.update(H)
    return c


def _login(base: str, app) -> tuple[TestClient, dict]:
    c = TestClient(app, base_url=base)
    c.headers.update(H)
    r = c.post("/api/auth/login", json={"password": PW})
    assert r.status_code == 200, r.text
    return c, r.json()


def _enable_totp(c: TestClient) -> tuple[str, list[str]]:
    s = c.post("/api/auth/totp/setup").json()
    assert s["uri"].startswith("otpauth://totp/Harness%20Maxxing%3A") and f"secret={s['secret']}" in s["uri"]
    r = c.post("/api/auth/totp/confirm", json={"code": totp.code_at(s["secret"], totp.now_step())})
    assert r.status_code == 200, r.text
    return s["secret"], r.json().get("recovery_codes", [])


def _add_passkey(c: TestClient, a: Authenticator, name: str = "Laptop") -> dict:
    opts = c.post("/api/auth/passkeys/options").json()
    assert opts["rp"]["id"] == a.rp_id
    r = c.post("/api/auth/passkeys", json={"credential": a.create(opts), "name": name})
    assert r.status_code == 200, r.text
    return r.json()


# ---- TOTP -------------------------------------------------------------------------------------
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize("t,code", [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
                                    (1234567890, "005924"), (2000000000, "279037")])
def test_totp_matches_rfc6238_vectors(t, code):
    assert totp.code_at(RFC_SECRET, t // 30) == code
    assert totp.verify(RFC_SECRET, code, at=t) == t // 30


def test_totp_window_replay_and_format():
    s = totp.new_secret()
    assert len(s) == 32
    step = totp.now_step()
    assert totp.verify(s, totp.code_at(s, step - 1)) == step - 1          # clock drift: one step back
    assert totp.verify(s, totp.code_at(s, step + 2)) is None               # too far
    assert totp.verify(s, totp.code_at(s, step), last_step=step) is None  # used already
    assert totp.verify(s, "12345") is None and totp.verify(s, "abcdef") is None
    assert totp.verify(s, totp.code_at(s, step)[:3] + " " + totp.code_at(s, step)[3:]) == step


def test_totp_setup_needs_a_right_code_then_signs_in(app):
    c = _signed_in(app)
    s = c.post("/api/auth/totp/setup").json()
    assert c.post("/api/auth/totp/confirm", json={"code": "000000" if totp.code_at(s["secret"], totp.now_step()) != "000000" else "111111"}).status_code == 400
    assert not mfa.totp_on()
    assert c.get("/api/auth/methods").json()["totp"] == {"on": False}
    r = c.post("/api/auth/totp/confirm", json={"code": totp.code_at(s["secret"], totp.now_step())})
    assert r.status_code == 200 and len(r.json()["recovery_codes"]) == 10
    assert "mx_device" not in r.cookies                                    # its next sign-in asks the app
    m = c.get("/api/auth/methods").json()
    assert m["required"] and m["totp"] == {"on": True} and m["recovery_left"] == 10
    assert c.post("/api/auth/totp/setup").status_code == 409             # one app at a time
    # a new browser: the password is not enough any more
    n, r = _login(ORIGIN, app)
    tf = r["two_factor"]
    assert r["ok"] is False and tf["methods"] == ["totp", "recovery"] and tf["expires_in"] == twofactor.APP_TTL
    assert n.get("/api/workspace/tree").status_code == 401
    assert n.post("/api/auth/two-factor", json={"challenge": tf["challenge"], "code": "12345x"}).status_code == 400
    # the code used by the setup cannot be used again
    used = totp.code_at(s["secret"], totp.now_step())
    if mfa.config.load_secrets()["totp_last_step"] == totp.now_step():
        assert n.post("/api/auth/two-factor", json={"challenge": tf["challenge"], "code": used}).status_code == 400
    mfa.config.set_secret("totp_last_step", totp.now_step() - 2)
    r = n.post("/api/auth/two-factor", json={"challenge": tf["challenge"], "code": used})
    assert r.json() == {"ok": True, "status": "approved"}
    assert n.get("/api/workspace/tree").status_code == 200


def test_setup_expires_and_needs_a_session(app):
    anon = TestClient(app, base_url=ORIGIN)
    anon.headers.update(H)
    assert anon.post("/api/auth/totp/setup").status_code == 401
    assert anon.post("/api/auth/passkeys/options").status_code == 401
    assert anon.get("/api/auth/methods").status_code == 401
    c = _signed_in(app)
    assert c.post("/api/auth/totp/confirm", json={"code": "123456"}).status_code == 410   # nothing set up


def test_removing_the_app_needs_the_password(app):
    c = _signed_in(app)
    _enable_totp(c)
    assert c.request("DELETE", "/api/auth/totp", json={"password": "wrong password!"}).status_code == 401
    assert mfa.totp_on()
    assert c.request("DELETE", "/api/auth/totp", json={"password": PW}).status_code == 200
    assert not mfa.totp_on() and mfa.recovery_left() == 0                 # last app method: codes go too
    assert _login(ORIGIN, app)[1] == {"ok": True}


# ---- recovery codes ---------------------------------------------------------------------------
def test_recovery_code_signs_in_once(app):
    c = _signed_in(app)
    _, codes = _enable_totp(c)
    assert all(len(x) == 11 and x[5] == "-" for x in codes) and len(set(codes)) == 10
    assert all(codes[0] not in json.dumps(v) for v in config.load_secrets().values())   # stored hashed
    n, r = _login(ORIGIN, app)
    cid = r["two_factor"]["challenge"]
    r = n.post("/api/auth/two-factor", json={"challenge": cid, "code": codes[0].upper().replace("-", " ")})
    assert r.json() == {"ok": True, "status": "approved", "recovery_left": 9}
    n2, r = _login(ORIGIN, app)
    r = n2.post("/api/auth/two-factor", json={"challenge": r["two_factor"]["challenge"], "code": codes[0]})
    assert r.status_code == 400 and r.json()["error"] == "bad_code"


def test_new_recovery_codes_replace_the_old_ones(app):
    c = _signed_in(app)
    assert c.post("/api/auth/recovery-codes", json={"password": PW}).status_code == 409   # no app method yet
    _, old = _enable_totp(c)
    assert c.post("/api/auth/recovery-codes", json={"password": "nope nope nope"}).status_code == 401
    new = c.post("/api/auth/recovery-codes", json={"password": PW}).json()["recovery_codes"]
    assert len(new) == 10 and not set(new) & set(old)
    n, r = _login(ORIGIN, app)
    assert n.post("/api/auth/two-factor", json={"challenge": r["two_factor"]["challenge"], "code": old[1]}).status_code == 400


def test_wrong_codes_kill_the_request(app):
    c = _signed_in(app)
    _enable_totp(c)
    n, r = _login(ORIGIN, app)
    cid = r["two_factor"]["challenge"]
    for left in range(twofactor.CODE_TRIES - 1, 0, -1):
        r = n.post("/api/auth/two-factor", json={"challenge": cid, "code": "aaaaa-bbbbb"})
        assert r.status_code == 400 and r.json()["tries_left"] == left
    assert n.post("/api/auth/two-factor", json={"challenge": cid, "code": "aaaaa-bbbbb"}).status_code == 410


# ---- passkeys ---------------------------------------------------------------------------------
def test_passkey_registration_and_sign_in(app):
    c = _signed_in(app)
    a = Authenticator()
    r = _add_passkey(c, a)
    assert r["passkey"]["name"] == "Laptop" and r["passkey"]["rp_id"] == "ui.example.com"
    assert len(r["recovery_codes"]) == 10                                  # first app method
    stored = config.load_secrets()["passkeys"][0]
    assert stored["id"] == b64(a.cred_id) and stored["transports"] == ["internal"]
    second = _add_passkey(c, Authenticator(), "Phone")
    assert "recovery_codes" not in second                                  # already has codes
    # sign in with it
    n, r = _login(ORIGIN, app)
    tf = r["two_factor"]
    assert tf["methods"] == ["passkey", "recovery"]
    opts = n.post("/api/auth/two-factor/passkey", json={"challenge": tf["challenge"]}).json()
    assert opts["rpId"] == "ui.example.com" and {x["id"] for x in opts["allowCredentials"]} == {b64(a.cred_id), second["passkey"]["id"]}
    r = n.post("/api/auth/two-factor", json={"challenge": tf["challenge"], "passkey": a.get(opts)})
    assert r.json() == {"ok": True, "status": "approved"}, r.text
    assert n.get("/api/workspace/tree").status_code == 200
    row = next(p for p in config.load_secrets()["passkeys"] if p["id"] == b64(a.cred_id))
    assert row["sign_count"] == 1 and row["last_used"]


def test_passkey_answer_is_checked(app):
    c = _signed_in(app)
    a = Authenticator()
    _add_passkey(c, a)
    n, r = _login(ORIGIN, app)
    cid = r["two_factor"]["challenge"]
    opts = n.post("/api/auth/two-factor/passkey", json={"challenge": cid}).json()
    # signed by another key
    other = Authenticator()
    other.cred_id = a.cred_id
    r = n.post("/api/auth/two-factor", json={"challenge": cid, "passkey": other.get(opts)})
    assert r.status_code == 400 and r.json()["error"] == "bad_passkey"
    # a prompt answers once: replaying a good answer to a used prompt fails
    opts = n.post("/api/auth/two-factor/passkey", json={"challenge": cid}).json()
    good = a.get(opts, origin="https://evil.example.net")                  # phishing page
    assert n.post("/api/auth/two-factor", json={"challenge": cid, "passkey": good}).status_code == 400
    assert n.get("/api/workspace/tree").status_code == 401
    # an answer to an old prompt
    old = opts
    n.post("/api/auth/two-factor/passkey", json={"challenge": cid})
    assert n.post("/api/auth/two-factor", json={"challenge": cid, "passkey": a.get(old)}).status_code == 400
    # a cloned authenticator whose counter goes back
    rows = config.load_secrets()["passkeys"]
    rows[0]["sign_count"] = 5
    config.set_secret("passkeys", rows)
    opts = n.post("/api/auth/two-factor/passkey", json={"challenge": cid}).json()
    assert n.post("/api/auth/two-factor", json={"challenge": cid, "passkey": a.get(opts, count=3)}).status_code in (400, 410)
    assert n.get("/api/workspace/tree").status_code == 401


def test_passkeys_need_a_secure_named_origin(app):
    for base, reason in (("http://100.64.1.2:8787", "ip"), ("http://box.example.com", "http")):
        c = _signed_in(app, base)
        r = c.post("/api/auth/passkeys/options")
        assert r.status_code == 409 and r.json()["reason"] == reason
        assert c.get("/api/auth/methods").json()["passkey_here"] == {"ok": False, "reason": reason}
    c = _signed_in(app, "http://localhost:8801")                           # a secure context too
    assert c.get("/api/auth/methods").json()["passkey_here"] == {"ok": True, "rp_id": "localhost"}
    a = Authenticator("localhost", "http://localhost:8801")
    _add_passkey(c, a)
    # proxied: the scheme comes from X-Forwarded-Proto only from a trusted peer (uvicorn), the Host header names it
    c = _signed_in(app, "http://ui.example.com")
    c.headers["X-Forwarded-Proto"] = "https"
    assert c.get("/api/auth/methods").json()["passkey_here"]["ok"]


def test_passkey_only_offered_for_its_host(app):
    c = _signed_in(app)
    _add_passkey(c, Authenticator())
    _enable_totp(c)
    _, r = _login("http://100.64.1.2:8787", app)                           # over Tailscale: no passkey there
    assert r["two_factor"]["methods"] == ["totp", "recovery"]
    n, r = _login(ORIGIN, app)
    assert r["two_factor"]["methods"] == ["passkey", "totp", "recovery"]


def test_adding_a_method_does_not_trust_the_browser(app):
    """The browser that turned a method on must meet it at its next sign-in (it proves the method works)."""
    c = _signed_in(app)
    r = _add_passkey(c, Authenticator(), name="")
    assert "mx_device" not in r and not c.cookies.get("mx_device")
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"password": PW}).json()
    assert r["ok"] is False and r["two_factor"]["methods"] == ["passkey", "recovery"]


def test_passkey_default_name(app):
    c = _signed_in(app)
    c.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"
    assert _add_passkey(c, Authenticator(), name="")["passkey"]["name"] == "Passkey · Firefox · Windows"
    assert mfa._default_name("d548826e-79b4-db40-a3d8-11116f7e8349", "") == "Bitwarden"
    assert mfa._default_name("00000000-0000-0000-0000-000000000000", "") == "Passkey"


def _passkey_only(app, a: Authenticator) -> TestClient:
    """A signed-in client that made passkey `a` (the passkey-only sign-in is then on)."""
    c = _signed_in(app)
    _add_passkey(c, a)
    return c


def _anon(base: str = ORIGIN, app=None) -> TestClient:
    n = TestClient(app, base_url=base)
    n.headers.update(H)
    return n


def test_passkey_login_on_with_the_first_passkey_and_can_be_turned_off(app):
    n = _anon(app=app)
    assert n.get("/api/auth/state").json()["passkey_login"] is False      # no passkey yet
    assert n.post("/api/auth/passkey-login/options").status_code == 409
    c = _signed_in(app)
    _enable_totp(c)
    assert c.get("/api/auth/methods").json()["passkey_login"] is False
    _add_passkey(c, Authenticator())
    assert c.get("/api/auth/methods").json()["passkey_login"] is True
    assert n.get("/api/auth/state").json()["passkey_login"] is True
    # off: at once, then the sign-in page asks the password again
    assert c.put("/api/auth/passkey-login", json={"enabled": False}).json() == {"ok": True, "enabled": False}
    assert n.get("/api/auth/state").json()["passkey_login"] is False
    assert n.post("/api/auth/passkey-login/options").status_code == 409
    # back on: the current password
    assert c.put("/api/auth/passkey-login", json={"enabled": True, "password": "wrong password!"}).status_code == 401
    assert c.put("/api/auth/passkey-login", json={"enabled": True, "password": PW}).json() == {"ok": True, "enabled": True}
    # a new passkey turns it on again
    c.put("/api/auth/passkey-login", json={"enabled": False})
    _add_passkey(c, Authenticator(), "Phone")
    assert mfa.passkey_login_flag()


def test_passkey_login_signs_in_without_password(app):
    a = Authenticator()
    _passkey_only(app, a)
    n = _anon(app=app)
    assert n.get("/api/auth/state").json()["passkey_login"] is True
    assert _anon("http://100.64.1.2:8787", app).get("/api/auth/state").json()["passkey_login"] is False
    opts = n.post("/api/auth/passkey-login/options").json()
    assert opts["userVerification"] == "required" and opts["rpId"] == "ui.example.com"
    r = n.post("/api/auth/passkey-login", json={"credential": a.get(opts)})
    assert r.json()["ok"] is True, r.text
    assert n.get("/api/workspace/tree").status_code == 200
    # a prompt answers once
    assert _anon(app=app).post("/api/auth/passkey-login", json={"credential": a.get(opts)}).status_code == 401


def test_passkey_login_needs_user_verification_and_the_right_key(app):
    a = Authenticator()
    _passkey_only(app, a)
    n = _anon(app=app)
    # user present but not verified (flags UP only)
    opts = n.post("/api/auth/passkey-login/options").json()
    cred = a.get(opts)
    auth = bytearray(unb64(cred["response"]["authenticatorData"]))
    auth[32] = 0x01
    cd = unb64(cred["response"]["clientDataJSON"])
    cred["response"]["authenticatorData"] = b64(bytes(auth))
    cred["response"]["signature"] = b64(a.key.sign(bytes(auth) + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256())))
    assert n.post("/api/auth/passkey-login", json={"credential": cred}).status_code == 401
    # another key, a phishing origin
    other = Authenticator()
    other.cred_id = a.cred_id
    opts = n.post("/api/auth/passkey-login/options").json()
    assert n.post("/api/auth/passkey-login", json={"credential": other.get(opts)}).status_code == 401
    opts = n.post("/api/auth/passkey-login/options").json()
    assert n.post("/api/auth/passkey-login", json={"credential": a.get(opts, origin="https://evil.example.net")}).status_code == 401
    assert n.get("/api/workspace/tree").status_code == 401


def test_passkey_login_failures_are_throttled_like_passwords(app):
    a = Authenticator()
    _passkey_only(app, a)
    n = _anon(app=app)
    for _ in range(security.FAIL_MAX):
        n.post("/api/auth/passkey-login", json={"credential": {"id": "x", "response": {}}})
    r = n.post("/api/auth/passkey-login", json={"credential": {"id": "x", "response": {}}})
    assert r.status_code == 429


def test_passkey_login_goes_with_the_last_passkey(app):
    a = Authenticator()
    c = _passkey_only(app, a)
    pid = mfa.passkeys()[0]["id"]
    assert c.request("DELETE", f"/api/auth/passkeys/{pid}", json={"password": PW}).status_code == 200
    assert not mfa.passkey_login_on("ui.example.com")
    c = _passkey_only(app, Authenticator())
    assert cli.main(["2fa", "off", "passkeys"]) == 0
    assert not mfa.passkey_login_on("ui.example.com")
    assert _anon(app=app).post("/api/auth/passkey-login/options").status_code == 409
    assert c.put("/api/auth/passkey-login", json={"enabled": True, "password": PW}).status_code == 409


def test_passkey_login_unknown_passkey_and_accepted_list(app):
    a = Authenticator()
    _passkey_only(app, a)
    gone = Authenticator()                               # still in the password manager, removed from the server
    n = _anon(app=app)
    opts = n.post("/api/auth/passkey-login/options").json()
    r = n.post("/api/auth/passkey-login", json={"credential": gone.get(opts)})
    assert r.status_code == 401 and r.json()["error"] == "unknown_passkey" and r.json()["rp_id"] == "ui.example.com"
    opts = n.post("/api/auth/passkey-login/options").json()
    r = n.post("/api/auth/passkey-login", json={"credential": a.get(opts)}).json()
    assert r["accepted"] == {"rp_id": "ui.example.com", "user": config.get_secret("passkey_user"), "ids": [b64(a.cred_id)]}


def _sudo(c: TestClient, a: Authenticator, uv: bool = True):
    opts = c.post("/api/auth/reauth/options").json()
    assert opts["userVerification"] == "required"
    cred = a.get(opts)
    if not uv:
        auth = bytearray(unb64(cred["response"]["authenticatorData"]))
        auth[32] = 0x01
        cd = unb64(cred["response"]["clientDataJSON"])
        cred["response"]["authenticatorData"] = b64(bytes(auth))
        cred["response"]["signature"] = b64(a.key.sign(bytes(auth) + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256())))
    return c.post("/api/auth/reauth", json={"credential": cred})


def test_a_passkey_confirms_sensitive_actions(app):
    a = Authenticator()
    c = _signed_in(app)
    _add_passkey(c, a)
    _enable_totp(c)
    # without a confirmation, an empty password is refused
    assert c.request("DELETE", "/api/auth/totp", json={"password": ""}).status_code == 401
    assert _sudo(c, a, uv=False).status_code == 401                        # the passkey must check its user
    assert _sudo(c, a).json() == {"ok": True, "expires_in": mfa.SUDO_TTL}
    assert c.request("DELETE", "/api/auth/totp", json={"password": ""}).status_code == 200
    assert c.post("/api/auth/recovery-codes", json={"password": ""}).status_code == 200
    # another session of the same browser profile is not confirmed
    other = _signed_in(app)
    assert other.post("/api/auth/recovery-codes", json={"password": ""}).status_code == 401
    # never the password change
    r = c.post("/api/auth/password", json={"current": "", "new": "another long password"})
    assert r.status_code == 401
    # the confirmation ends with the password change
    assert c.post("/api/auth/password", json={"current": PW, "new": "another long password"}).status_code == 200
    assert not mfa._sudo


def test_reauth_needs_a_passkey_here(app):
    c = _signed_in(app)
    assert c.post("/api/auth/reauth/options").status_code == 409
    assert _signed_in(app, "http://100.64.1.2:8787").post("/api/auth/reauth/options").status_code == 409
    a = Authenticator()
    _add_passkey(c, a)
    opts = c.post("/api/auth/reauth/options").json()
    # an answer to a prompt of another session does not count
    other = _signed_in(app)
    assert other.post("/api/auth/reauth", json={"credential": a.get(opts)}).status_code == 401


def test_passkey_registration_refused(app):
    c = _signed_in(app)
    a = Authenticator()
    opts = c.post("/api/auth/passkeys/options").json()
    bad = a.create(opts, origin="https://evil.example.net")
    assert c.post("/api/auth/passkeys", json={"credential": bad, "name": "x"}).status_code == 400
    opts = c.post("/api/auth/passkeys/options").json()
    bad = a.create(opts, rp_id="evil.example.net")
    assert c.post("/api/auth/passkeys", json={"credential": bad, "name": "x"}).status_code == 400
    assert c.post("/api/auth/passkeys", json={"credential": {"id": "x"}, "name": "x"}).status_code == 400
    # a prompt made on another host cannot be answered here
    opts = _signed_in(app, "http://localhost:8801").post("/api/auth/passkeys/options").json()
    assert c.post("/api/auth/passkeys", json={"credential": a.create(opts), "name": "x"}).status_code == 400
    assert mfa.passkeys() == []


def test_rename_and_remove_passkey(app):
    c = _signed_in(app)
    pid = _add_passkey(c, Authenticator())["passkey"]["id"]
    assert c.patch(f"/api/auth/passkeys/{pid}", json={"name": "  YubiKey 5  "}).status_code == 200
    assert c.get("/api/auth/methods").json()["passkeys"][0]["name"] == "YubiKey 5"
    assert c.request("DELETE", f"/api/auth/passkeys/{pid}", json={"password": "wrong password!"}).status_code == 401
    assert c.request("DELETE", f"/api/auth/passkeys/{pid}", json={"password": PW}).status_code == 200
    assert c.request("DELETE", f"/api/auth/passkeys/{pid}", json={"password": PW}).status_code == 404
    assert mfa.passkeys() == [] and mfa.recovery_left() == 0 and not mfa.required()


# ---- with Telegram, and the way out -----------------------------------------------------------
def test_app_methods_without_telegram_send_nothing(app, monkeypatch):
    sent = []
    monkeypatch.setattr(twofactor, "_send", lambda c: sent.append(c) or True)
    c = _signed_in(app)
    _enable_totp(c)
    _login(ORIGIN, app)
    assert sent == []


def test_telegram_refusing_does_not_block_the_app(app, monkeypatch):
    monkeypatch.setattr(twofactor, "enabled", lambda: True)
    monkeypatch.setattr(twofactor, "_send", lambda c: False)
    c = _signed_in(app)
    secret, _ = _enable_totp(c)
    n, r = _login(ORIGIN, app)
    assert r["two_factor"]["methods"] == ["totp", "recovery"]              # Telegram dropped, not a 503
    # the Telegram code no longer works for this request, the app does
    ch = twofactor._ch[r["two_factor"]["challenge"]]
    assert n.post("/api/auth/two-factor", json={"challenge": ch.id, "code": ch.code}).status_code == 400
    config.set_secret("totp_last_step", totp.now_step() - 2)
    r = n.post("/api/auth/two-factor", json={"challenge": ch.id, "code": totp.code_at(secret, totp.now_step())})
    assert r.json()["status"] == "approved"


def test_telegram_code_still_works_next_to_the_app(app, monkeypatch):
    monkeypatch.setattr(twofactor, "enabled", lambda: True)
    monkeypatch.setattr(twofactor, "_send", lambda c: setattr(c, "msg", (1, 1)) or True)
    monkeypatch.setattr(twofactor, "_close", lambda c, line: None)
    c = _signed_in(app)
    _enable_totp(c)
    n, r = _login(ORIGIN, app)
    tf = r["two_factor"]
    assert tf["methods"] == ["totp", "telegram", "recovery"] and tf["expires_in"] == twofactor.APP_TTL
    code = twofactor._ch[tf["challenge"]].code
    assert n.post("/api/auth/two-factor", json={"challenge": tf["challenge"], "code": code}).json()["status"] == "approved"


def test_cli_status_and_off(app, capsys):
    c = _signed_in(app)
    _enable_totp(c)
    _add_passkey(c, Authenticator())
    capsys.readouterr()
    assert cli.main(["2fa", "status", "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["active"] and st["authenticator_app"] and st["passkeys"] == [{"name": "Laptop", "host": "ui.example.com"}]
    assert st["recovery_codes_left"] == 10
    assert cli.main(["2fa", "off", "app"]) == 0
    assert "Still asked: 1 passkey(s)" in capsys.readouterr().out
    assert not mfa.totp_on() and mfa.passkeys() and mfa.recovery_left() == 10
    assert cli.main(["2fa", "off"]) == 0
    assert "password alone" in capsys.readouterr().out
    assert not mfa.required() and mfa.recovery_left() == 0
    assert _login(ORIGIN, app)[1] == {"ok": True}


def test_forget_browsers_keeps_this_one_with_app_methods(app):
    c = _signed_in(app)
    _enable_totp(c)
    r = c.post("/api/auth/two-factor/forget-browsers")
    assert r.status_code == 200 and "mx_device" in r.cookies
