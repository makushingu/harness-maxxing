from __future__ import annotations

from maxxing import config


def test_status_with_fake_claude(client, mx, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))            # no ~/.claude/.credentials.json
    r = client.get("/api/claude/status").json()
    assert r["installed"] is True and r["version"] == "2.1.0"
    assert r["auth"] == {"ok": False, "method": None, "detail": "Not connected", "checked_at": None,
                         "error": None}
    assert r["permission_mode"] == "bypass" and r["default_model"] == ""
    ids = [m["id"] for m in r["models"]]
    assert "claude-opus-5-5" in ids and "claude-haiku-4-5-20251001" in ids
    assert {"id": "claude-opus-5-5", "label": "Opus 5.5"}.items() <= next(m for m in r["models"] if m["id"] == "claude-opus-5-5").items()


def test_credentials_file_detected(client, monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / ".credentials.json").write_text('{"claudeAiOauth": {"subscriptionType": "max"}}')
    monkeypatch.setenv("HOME", str(home))
    auth = client.get("/api/claude/status").json()["auth"]
    assert auth["ok"] and auth["method"] == "credentials" and "(Max plan)" in auth["detail"]


def test_auth_store_test_delete(client, mx, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    r = client.post("/api/claude/auth", json={"kind": "oauth_token", "value": "sk-test-oauth-0123456789"})
    assert r.json() == {"ok": True}
    assert config.get_secret("claude_oauth_token") == "sk-test-oauth-0123456789"
    st = client.get("/api/claude/status").json()["auth"]
    assert st["ok"] and st["method"] == "oauth_token"
    r = client.post("/api/claude/auth", json={"kind": "api_key", "value": "sk-ant-api-0123456789"}).json()
    assert r["ok"] and config.get_secret("claude_oauth_token") == ""      # one credential at a time
    t = client.post("/api/claude/test").json()
    assert t["ok"] and t["model"] == "claude-haiku-4-5-20251001" and t["ms"] >= 0
    assert client.post("/api/claude/auth", json={"kind": "api_key", "value": "short"}).status_code == 400
    assert client.post("/api/claude/auth", json={"kind": "nope", "value": "x" * 20}).status_code == 422
    assert client.delete("/api/claude/auth").json() == {"ok": True}
    assert client.get("/api/claude/status").json()["auth"]["method"] is None


def test_failing_test_reported(client, mx, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    import maxxing.api.claude as cl
    monkeypatch.setattr(cl, "TEST_PROMPT", "FAIL now")
    r = client.post("/api/claude/auth", json={"kind": "api_key", "value": "sk-ant-api-0123456789"}).json()
    assert r["ok"] is False and r["error"]
    auth = client.get("/api/claude/status").json()["auth"]
    assert auth["ok"] is False and auth["detail"].startswith("Last test failed")


def test_settings(client):
    assert client.put("/api/claude/settings", json={"default_model": "claude-opus-5-5",
                                                    "permission_mode": "acceptEdits"}).json() == {"ok": True}
    st = client.get("/api/claude/status").json()
    assert st["default_model"] == "claude-opus-5-5" and st["permission_mode"] == "acceptEdits"
    assert client.put("/api/claude/settings", json={"permission_mode": "yolo"}).status_code == 400


def test_onboarding(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    r = client.get("/api/onboarding").json()
    assert r == {"completed": False, "steps": {"password": True, "claude": False, "workspace": False,
                                               "telegram": False, "backup": False, "profile": False}}
    client.post("/api/workspace/projects", json={"name": "acme"})
    client.post("/api/workspace/projects/acme/topics", json={"name": "blog"})
    config.update_config(telegram={"chat_id": 123}, backup={"repo": "acme/memory"}, register={"asked": True})
    config.set_secret("anthropic_api_key", "sk-ant-api-0123456789")
    steps = client.get("/api/onboarding").json()["steps"]
    assert all(steps.values())
    assert client.post("/api/onboarding/complete").json() == {"ok": True, "jobs_enabled": []}
    assert client.get("/api/onboarding").json()["completed"] is True
