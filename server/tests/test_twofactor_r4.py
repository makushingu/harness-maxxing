"""Two-step sign-in hardening (round 4): code guessing, lock-out, stale approvals, odd input."""
import time

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from maxxing import security, twofactor
from test_twofactor import H, PW, _app, _login, _on, tg  # noqa: F401


def _bad(c):
    return "000000" if c.code != "000000" else "111111"


def test_wrong_codes_are_bounded_server_wide(tg):  # noqa: F811
    """Many addresses x 5 requests x 5 codes used to give ~1000 guesses an hour; now BAD_MAX, then only Allow."""
    _on()
    tried = 0
    for n in range(40):
        for _ in range(twofactor.NEW_MAX):
            try:
                c = twofactor.start("login", f"198.51.100.{n}", "x")
            except twofactor.Refused:
                break
            for _ in range(twofactor.CODE_TRIES):
                if twofactor.check(c.id, _bad(c))[0] in ("bad_code", "expired"):
                    tried += 1
    assert tried <= twofactor.BAD_MAX
    c = twofactor.start("login", "203.0.113.9", "owner")
    assert twofactor.check(c.id, c.code)[0] == "codes_paused"        # even the right code: no oracle
    twofactor.decide(c.id, True)
    assert twofactor.check(c.id)[0] == "approved"                     # the button still signs in


def test_a_few_clients_cannot_lock_the_owner_out(tg):  # noqa: F811
    _on()
    for n in range(4):
        for _ in range(twofactor.NEW_MAX):
            twofactor.start("login", f"198.51.100.{n}", "attacker")
    c = twofactor.start("login", "203.0.113.9", "owner phone")         # the oldest request gives way
    assert twofactor.check(c.id)[0] == "pending"
    assert sum(x.status == "pending" for x in twofactor._ch.values()) <= twofactor.PENDING_MAX


def test_ipv6_clients_are_counted_per_64():
    def key(host):
        return security.client_key(Request({"type": "http", "client": (host, 1), "headers": []}))
    assert key("2001:db8:1:2::1") == key("2001:db8:1:2:ffff::9") == "2001:db8:1:2::/64"
    assert key("203.0.113.7") == "203.0.113.7" and key("::ffff:203.0.113.7") == "203.0.113.7"
    assert key("testclient") == "testclient"


def test_an_approval_dies_with_time_and_with_the_password(tg, monkeypatch):  # noqa: F811
    _on()
    with TestClient(_app()) as c:
        cid = _login(c)["two_factor"]["challenge"]
        twofactor.decide(cid, True)
        security.set_password("another long password")                # the owner reacts to an Allow by mistake
        assert c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H).status_code == 410
        r = c.post("/api/auth/login", json={"password": "another long password"}, headers=H)
        cid = r.json()["two_factor"]["challenge"]
        twofactor.decide(cid, True)
        later = time.time() + twofactor.TTL + twofactor.GRACE + 1
        monkeypatch.setattr(twofactor.time, "time", lambda: later)
        assert c.post("/api/auth/two-factor", json={"challenge": cid}, headers=H).status_code == 410


@pytest.mark.parametrize("where", ["code", "cookie"])
def test_non_ascii_input_is_not_a_500(tg, where):  # noqa: F811
    _on()
    with TestClient(_app(), raise_server_exceptions=False) as c:
        if where == "code":
            cid = _login(c)["two_factor"]["challenge"]
            r = c.post("/api/auth/two-factor", json={"challenge": cid, "code": "１２３４５６"}, headers=H)
            assert r.status_code == 400, r.status_code
        else:
            r = c.post("/api/auth/login", json={"password": PW}, headers={**H, "cookie": "mx_device=1.2.é".encode()})
            assert r.status_code == 200, r.status_code
