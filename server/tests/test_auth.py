from __future__ import annotations

from fastapi.testclient import TestClient

from maxxing import security


def _app():
    from maxxing.app import create_app
    return create_app()


def test_setup_login_logout(mx):
    with TestClient(_app()) as c:
        st = c.get("/api/auth/state").json()
        assert st["setup_required"] is True and st["authenticated"] is False
        tok = security.ensure_setup_token()
        h = {"X-Maxxing": "1"}
        assert c.post("/api/auth/setup", json={"token": "bad", "password": "longenough-pass"}, headers=h).status_code == 403
        assert c.post("/api/auth/setup", json={"token": tok, "password": "short"}, headers=h).status_code == 400
        assert c.post("/api/auth/setup", json={"token": tok, "password": "longenough-pass"}, headers=h).json() == {"ok": True}
        assert c.get("/api/auth/state").json()["authenticated"] is True
        assert c.get("/api/workspace/tree").status_code == 200
        assert c.post("/api/auth/setup", json={"token": tok, "password": "another1"}, headers=h).status_code == 409
        c.post("/api/auth/logout", headers=h)
        c.cookies.clear()
        assert c.get("/api/workspace/tree").status_code == 401
        assert c.post("/api/auth/login", json={"password": "longenough-pass"}, headers=h).json() == {"ok": True}
        assert c.get("/api/workspace/tree").status_code == 200


def test_csrf_header_required(client):
    r = client.post("/api/workspace/projects", json={"name": "x"}, headers={"X-Maxxing": "0"})
    assert r.status_code == 403 and r.json()["error"] == "csrf"


def test_wrong_password_delayed(mx):
    import time
    security.set_password("rightpassword")
    security._fails.clear()
    with TestClient(_app()) as c:
        t0 = time.time()
        r = c.post("/api/auth/login", json={"password": "wrong"}, headers={"X-Maxxing": "1"})
        assert r.status_code == 401 and r.json()["error"] == "bad_password"
        assert time.time() - t0 >= 0.9
        assert c.post("/api/auth/login", json={"password": "rightpassword"},
                      headers={"X-Maxxing": "1"}).status_code == 200


def test_password_change_is_throttled_and_needs_12_characters(mx, monkeypatch):
    """A signed-in browser (maybe a stolen cookie) cannot use the password change to guess the current password."""
    security.set_password("rightpassword")
    security._fails.clear()
    monkeypatch.setattr(security, "FAIL_MAX", 3)
    real_end = security.end_attempt
    monkeypatch.setattr(security, "end_attempt", lambda key, ok: real_end(key, ok) and 0.0)   # no 1-8 s waits
    h = {"X-Maxxing": "1"}
    with TestClient(_app()) as c:
        assert c.post("/api/auth/login", json={"password": "rightpassword"}, headers=h).status_code == 200
        r = c.post("/api/auth/password", json={"current": "rightpassword", "new": "elevenchars"}, headers=h)
        assert r.status_code == 400 and r.json()["error"] == "weak_password"
        codes = [c.post("/api/auth/password", json={"current": f"guess{i}", "new": "a-long-new-passphrase"},
                        headers=h).status_code for i in range(4)]
        assert codes == [401, 401, 401, 429]
        assert c.post("/api/auth/password", json={"current": "rightpassword", "new": "a-long-new-passphrase"},
                      headers=h).status_code == 429                      # still blocked for this client
        security._fails.clear()
        assert c.post("/api/auth/password", json={"current": "rightpassword", "new": "a-long-new-passphrase"},
                      headers=h).json() == {"ok": True}
        assert c.get("/api/workspace/tree").status_code == 200           # the new cookie works


def test_logout_revokes_only_that_cookie(mx):
    security.set_password("rightpassword")
    security._fails.clear()
    h = {"X-Maxxing": "1"}
    with TestClient(_app()) as a, TestClient(_app()) as b:
        assert a.post("/api/auth/login", json={"password": "rightpassword"}, headers=h).status_code == 200
        assert b.post("/api/auth/login", json={"password": "rightpassword"}, headers=h).status_code == 200
        stolen = a.cookies.get(security.COOKIE)
        assert stolen != b.cookies.get(security.COOKIE)        # each sign-in gets its own cookie
        a.post("/api/auth/logout", headers=h)
        assert b.get("/api/workspace/tree").status_code == 200  # the other browser stays signed in
        a.cookies.set(security.COOKIE, stolen)                  # replaying the old cookie: refused
        assert a.get("/api/workspace/tree").status_code == 401
        assert a.get("/api/auth/state").json()["authenticated"] is False


def test_legacy_cookie_still_valid_and_revocable(mx):
    import hashlib
    import hmac
    import time
    security.set_password("rightpassword")
    ts = str(int(time.time()))
    legacy = f"{ts}.{hmac.new(security._cookie_key(), ts.encode(), hashlib.sha256).hexdigest()}"
    assert security.cookie_valid(legacy)
    assert security.revoke_cookie(legacy)
    assert not security.cookie_valid(legacy)
    assert not security.revoke_cookie("123.forged")          # forged cookies never fill the list


def test_revocation_list_is_bounded(mx, monkeypatch):
    from maxxing import config
    security.set_password("rightpassword")
    monkeypatch.setattr(security, "REVOKED_MAX", 3)
    import time
    keep = security.make_cookie()
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 5)    # the overflow comes a few seconds later
    for _ in range(4):
        security.revoke_cookie(security.make_cookie())
    assert not security.cookie_valid(keep)                    # overflow -> every older cookie refused
    assert len(config.load_secrets().get("revoked_sessions") or {}) <= 3
    assert config.get_secret("sessions_not_before")


def test_expired_revocations_pruned_and_password_change_clears(mx, monkeypatch):
    import time
    from maxxing import config
    security.set_password("rightpassword")
    old = security.make_cookie()
    security.revoke_cookie(old)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + security.COOKIE_MAX_AGE + 10)
    security.revoke_cookie(security.make_cookie())
    assert len(config.load_secrets()["revoked_sessions"]) == 1
    monkeypatch.setattr(time, "time", real)
    security.set_password("anotherpassword")
    assert "revoked_sessions" not in config.load_secrets()


def test_cookie_lifetime_is_30_days():
    assert security.COOKIE_MAX_AGE == 30 * 24 * 3600


def test_look_shared_with_the_sign_in_page(client):
    assert client.get("/api/auth/state").json()["look"] is None
    assert client.put("/api/settings/look", json={"theme": "light", "accent": "teal"}).status_code == 422
    r = client.put("/api/settings/look", json={"theme": "light", "accent": "rose", "tint": "tinted"})
    assert r.json() == {"ok": True, "look": {"theme": "light", "accent": "rose", "tint": "tinted"}}
    client.cookies.clear()                                  # signed out: still readable, no longer writable
    assert client.get("/api/auth/state").json()["look"] == {"theme": "light", "accent": "rose", "tint": "tinted"}
    assert client.put("/api/settings/look", json={"theme": "dark", "accent": "blue"}).status_code == 401


def test_set_password_failure_midway_leaves_old_cookies_alive(mx, monkeypatch):
    """Disk full while changing the password: either nothing changed, or every old cookie died too."""
    import errno

    from maxxing import config
    security.set_password("rightpassword")
    old = security.make_cookie()
    real = config._atomic_write
    calls = {"n": 0}

    def flaky(path, data, mode=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(path, data, mode)

    monkeypatch.setattr(config, "_atomic_write", flaky)
    try:
        security.set_password("a whole new password")    # a 2nd write to secrets.json fails
    except OSError:
        pass
    monkeypatch.setattr(config, "_atomic_write", real)
    changed = security.verify_password("a whole new password", config.get_secret("password_hash"))
    assert not (changed and security.cookie_valid(old)), "password changed but old cookies still sign in"


def test_non_ascii_session_cookie_is_refused_not_500(mx):
    security.set_password("rightpassword")
    with TestClient(_app(), raise_server_exceptions=False) as c:
        r = c.get("/api/auth/state", headers={"cookie": b"mx_session=1.\xc3\xa9"})
        assert r.status_code == 200 and r.json()["authenticated"] is False, (r.status_code, r.text)
        assert c.get("/api/workspace/tree", headers={"cookie": b"mx_session=1.\xc3\xa9"}).status_code == 401


def test_non_ascii_setup_token_is_refused_not_500(mx):
    security.ensure_setup_token()
    with TestClient(_app(), raise_server_exceptions=False) as c:
        r = c.post("/api/auth/setup", json={"token": "é", "password": "longenough-pass"}, headers={"X-Maxxing": "1"})
        assert r.status_code == 403, (r.status_code, r.text)


def test_setup_token_with_a_lone_surrogate_is_refused_not_500(mx):
    security.ensure_setup_token()
    assert security.check_setup_token("\ud800") is False
    with TestClient(_app(), raise_server_exceptions=False) as c:
        body = b'{"token": "\\ud800", "password": "longenough-pass"}'
        r = c.post("/api/auth/setup", content=body, headers={"X-Maxxing": "1", "Content-Type": "application/json"})
        assert r.status_code == 403, (r.status_code, r.text)


def test_logout_with_corrupted_cookie_key_is_not_a_500(mx):
    from maxxing import config, twofactor
    security.set_password("rightpassword")
    cookie = security.make_cookie()
    s = config.load_secrets()
    s.update(cookie_key=12345, device_key=678)              # secrets.json restored or edited by hand
    config.write_json(config.secrets_path(), s)
    assert twofactor.make_device_cookie()
    with TestClient(_app(), raise_server_exceptions=False) as c:
        c.cookies.set(security.COOKIE, cookie)
        r = c.post("/api/auth/logout", headers={"X-Maxxing": "1"})
        assert r.status_code == 200, (r.status_code, r.text)


async def test_logout_does_not_freeze_the_event_loop(mx, monkeypatch):
    """Another process holds the config lock: logout (revoke_cookie: flock, fsync) waits in a thread, the rest of the
    server keeps answering."""
    import asyncio
    import subprocess
    import sys
    import time

    import httpx
    from maxxing import config
    monkeypatch.setattr(config, "FLOCK_WAIT_S", 1.5)
    security.set_password("correct horse battery")
    holder = subprocess.Popen([sys.executable, "-c",
                               "import fcntl,os,sys,time;fd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT);"
                               "fcntl.flock(fd,fcntl.LOCK_EX);print('held',flush=True);time.sleep(4)",
                               str(config.STATE / ".config.lock")], stdout=subprocess.PIPE, text=True)
    try:
        holder.stdout.readline()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://t",
                                     headers={"X-Maxxing": "1"}) as ac:
            async def ticker():
                worst, last = 0.0, time.perf_counter()
                for _ in range(30):
                    await asyncio.sleep(0.05)
                    now = time.perf_counter()
                    worst, last = max(worst, now - last - 0.05), now
                return worst
            tk = asyncio.create_task(ticker())
            await asyncio.sleep(0.1)
            r = await ac.post("/api/auth/logout", cookies={security.COOKIE: security.make_cookie()})
            assert r.status_code == 200
            assert await tk < 0.2
    finally:
        holder.kill()


def test_a_password_with_a_lone_surrogate_is_a_400(mx):
    with TestClient(_app(), raise_server_exceptions=False) as c:
        tok = security.ensure_setup_token()
        h = {"X-Maxxing": "1", "Content-Type": "application/json"}
        body = '{"token": "%s", "password": "longenough-\\ud800-pass"}' % tok
        r = c.post("/api/auth/setup", content=body.encode(), headers=h)
        assert r.status_code == 400 and r.json()["error"] == "bad_password"
        assert security.password_is_set() is False


def test_setup_links_made_at_once_share_one_token(mx, monkeypatch):
    import threading
    import time as _time
    real = security.secrets.token_urlsafe
    monkeypatch.setattr(security.secrets, "token_urlsafe", lambda n: _time.sleep(0.05) or real(n))
    gate, got = threading.Barrier(8), []

    def one():
        gate.wait()
        got.append(security.ensure_setup_token())
    threads = [threading.Thread(target=one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(got)) == 1 and security.check_setup_token(got[0])


def test_cookies_made_at_once_while_the_keys_are_missing_all_stay_valid(mx, monkeypatch):
    import secrets
    import threading
    import time as _time

    from maxxing import config, twofactor
    security.set_password("rightpassword")
    config.set_secrets({"cookie_key": None, "device_key": None})       # password changed / browsers forgotten
    real = secrets.token_hex
    monkeypatch.setattr(secrets, "token_hex", lambda n=None: _time.sleep(0.05) or real(n))
    for make, valid in ((security.make_cookie, security.cookie_valid),
                        (twofactor.make_device_cookie, twofactor.device_trusted)):
        gate, got = threading.Barrier(8), []

        def one():
            gate.wait()
            got.append(make())
        threads = [threading.Thread(target=one) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(got) == 8 and all(valid(v) for v in got), make.__name__


def test_a_cookie_issued_in_the_second_of_the_overflow_still_works(mx, monkeypatch):
    import time
    from maxxing import config
    security.set_password("rightpassword")
    monkeypatch.setattr(security, "REVOKED_MAX", 3)
    old = [security.make_cookie() for _ in range(3)]
    for v in old:
        security.revoke_cookie(v)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 5)
    last = security.make_cookie()
    security.revoke_cookie(last)                              # overflow
    assert config.get_secret("sessions_not_before")
    fresh = security.make_cookie()                            # signed in again within the same second
    assert security.cookie_valid(fresh)
    assert not any(security.cookie_valid(v) for v in [*old, last])   # this second's revocation is kept
