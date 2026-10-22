"""Claude sign-in state from real calls (turns, tests, background check), health and doctor."""
from __future__ import annotations

import asyncio
import os
import time

from maxxing import claude_auth, config, health

from conftest import wait_idle

EXPIRED = "OAuth session expired and could not be refreshed"


def _creds(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    f = home / ".claude" / ".credentials.json"
    f.write_text('{"claudeAiOauth": {"accessToken": "x", "subscriptionType": "max"}}')
    os.utime(f, (time.time() - 60, time.time() - 60))
    monkeypatch.setenv("HOME", str(home))
    return f


def test_turn_with_expired_sign_in_flips_status(client, topic, tmp_path, monkeypatch):
    _creds(tmp_path, monkeypatch)
    st = client.get("/api/claude/status").json()["auth"]
    assert st["ok"] and st["method"] == "credentials" and st["checked_at"] is None   # not verified yet
    s = client.post("/api/sessions", json={"path": topic, "message": "hello AUTH_EXPIRED"}).json()
    s = wait_idle(client, s["id"])
    assert s["state"] == "error" and EXPIRED in s["error"]
    st = client.get("/api/claude/status").json()["auth"]
    assert st["ok"] is False and EXPIRED in st["error"] and st["checked_at"] > time.time() - 30
    assert st["detail"].startswith("Claude sign-in failed")
    h = client.get("/api/system/health?force=1").json()
    issue = next(i for i in h["issues"] if i["code"] == "claude_auth")
    assert issue["text"].startswith("Claude sign-in expired") and h["claude_auth"] is False
    assert EXPIRED in h["claude_auth_error"]
    assert client.get("/api/onboarding").json()["steps"]["claude"] is False
    # a successful turn afterwards = signed in again
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "fine NOTOOL"})
    wait_idle(client, s["id"])
    st = client.get("/api/claude/status").json()["auth"]
    assert st["ok"] is True and st["error"] is None and st["checked_at"]


def test_normal_answer_mentioning_auth_is_not_an_error(client, topic, tmp_path, monkeypatch):
    _creds(tmp_path, monkeypatch)
    s = client.post("/api/sessions", json={"path": topic, "message": "explain invalid api key NOTOOL"}).json()
    wait_idle(client, s["id"])
    assert client.get("/api/claude/status").json()["auth"]["ok"] is True


def test_new_login_clears_old_failure(client, tmp_path, monkeypatch):
    f = _creds(tmp_path, monkeypatch)
    claude_auth.record(False, EXPIRED, "turn")
    assert claude_auth.status()["ok"] is False
    os.utime(f, (time.time() + 1, time.time() + 1))    # `claude /login` rewrote the credentials
    st = claude_auth.status()
    assert st["ok"] is True and st["checked_at"] is None


def test_background_check(client, tmp_path, monkeypatch):
    import maxxing.api.claude as cl
    _creds(tmp_path, monkeypatch)
    monkeypatch.setattr(cl, "_last_attempt", 0.0)
    monkeypatch.setenv("FAKE_CLAUDE_AUTH_EXPIRED", "1")
    assert claude_auth.needs_check()
    r = cl.check_now()
    assert r is not None and r["ok"] is False
    st = claude_auth.status()
    assert st["ok"] is False and EXPIRED in st["error"]
    assert cl.check_now() is None                       # at most once every 6 h
    # a recent real result: no check needed
    monkeypatch.setattr(cl, "_last_attempt", 0.0)
    claude_auth.record(True, None, "turn")
    assert not claude_auth.needs_check() and cl.check_now() is None
    # stale (> 6 h): checked again, now fine
    rec = claude_auth.last()
    rec["at"] = time.time() - 7 * 3600
    config.write_json(claude_auth.state_file(), rec)
    monkeypatch.delenv("FAKE_CLAUDE_AUTH_EXPIRED")
    r = cl.check_now()
    assert r is not None and r["ok"] and claude_auth.status()["ok"]


def test_background_check_timeout_is_not_signed_out(client, tmp_path, monkeypatch):
    import maxxing.api.claude as cl
    _creds(tmp_path, monkeypatch)
    claude_auth.record(True, None, "turn")
    monkeypatch.setattr(cl, "TEST_PROMPT", "FAIL now")              # non-auth failure
    rec = claude_auth.last()
    rec["at"] = time.time() - 7 * 3600
    config.write_json(claude_auth.state_file(), rec)
    monkeypatch.setattr(cl, "_last_attempt", 0.0)
    assert cl.check_now()["ok"] is False
    assert claude_auth.status()["ok"] is True


def test_checker_runs_at_startup(mx, tmp_path, monkeypatch):
    import maxxing.api.claude as cl
    _creds(tmp_path, monkeypatch)
    monkeypatch.setattr(cl, "_last_attempt", 0.0)
    monkeypatch.setenv("MAXXING_AUTH_CHECK", "1")
    monkeypatch.setenv("MAXXING_AUTH_CHECK_DELAY", "0")
    monkeypatch.setenv("FAKE_CLAUDE_AUTH_EXPIRED", "1")

    async def go():
        await cl.startup()
        for _ in range(100):
            if claude_auth.last():
                break
            await asyncio.sleep(0.1)
        await cl.shutdown()
    asyncio.run(go())
    assert claude_auth.status()["ok"] is False


def test_doctor_reports_expired_sign_in(mx, tmp_path, monkeypatch):
    from maxxing import cmd_core
    _creds(tmp_path, monkeypatch)
    monkeypatch.setattr(cmd_core, "home", lambda: tmp_path / "home")
    claude_auth.record(False, EXPIRED, "turn")
    c = cmd_core.check_claude_auth(False)
    assert c["level"] == "fail" and c["title"] == "Claude sign-in expired" and EXPIRED in c["detail"]
    assert health.claude_auth() is False
