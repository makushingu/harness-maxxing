"""Harness updates itself while nobody uses it (maxxing/auto_update.py): never a real update."""
from __future__ import annotations

import asyncio

import pytest

from maxxing import auto_update as au
from maxxing import bus, config


@pytest.fixture
def fake(mx, monkeypatch):
    config.update_config(auto_update=True)
    st = {"browsers": 0, "busy": None, "spawned": 0, "branch": True, "pending": False,
          "rep": {"ok": True, "verdict": "simple", "target": "abc123", "latest": "2.0.0a99", "notes": [],
                  "unsaved": [], "customs": [{"id": "c1", "status": "ok"}]}}
    monkeypatch.setattr(au, "browsers", lambda: st["browsers"])
    monkeypatch.setattr(au.claude_update, "busy_reason", lambda now=None: st["busy"])
    monkeypatch.setattr(au, "_update_running", lambda: False)
    monkeypatch.setattr(au, "on_branch", lambda: st["branch"])
    monkeypatch.setattr(au, "pending_update", lambda: st["pending"])
    monkeypatch.setattr(au, "preflight", lambda: st["rep"])
    st["spawn"] = lambda: st.__setitem__("spawned", st["spawned"] + 1)
    return st


def test_off_by_default(fake):
    config.update_config(auto_update=False)
    assert au.tick(fake["spawn"]) == "off" and fake["spawned"] == 0


def test_updates_when_nobody_is_here_and_nothing_runs(fake):
    assert au.tick(fake["spawn"], now=1000.0) == "started" and fake["spawned"] == 1
    assert au.tick(fake["spawn"], now=1000.0 + 3600) == "tried_recently" and fake["spawned"] == 1   # same version
    assert au.tick(fake["spawn"], now=1000.0 + 25 * 3600) == "started" and fake["spawned"] == 2     # a day later


def test_never_moves_a_branch_under_test_nor_retries_a_pending_update(fake):
    fake["branch"] = False                              # detached HEAD: a branch under test, on purpose
    assert au.tick(fake["spawn"]) == "not_on_branch" and fake["spawned"] == 0
    fake["branch"], fake["pending"] = True, True        # conflict or rolled-back version waiting for a person
    assert au.tick(fake["spawn"], now=1000.0 + 30 * 3600) == "pending" and fake["spawned"] == 0


def test_branch_and_pending_read_the_real_state(mx, monkeypatch):
    from maxxing import cmd_core, customs
    monkeypatch.setattr(cmd_core, "_current_branch", lambda: "HEAD")
    assert au.on_branch() is False
    monkeypatch.setattr(cmd_core, "_current_branch", lambda: "main")
    assert au.on_branch() is True
    assert au.pending_update() is False
    customs.set_pending(reason="health")
    assert au.pending_update() is True


def test_waits_for_the_browsers_and_for_the_work(fake):
    fake["browsers"] = 1
    assert au.tick(fake["spawn"]) == "busy"
    fake["browsers"], fake["busy"] = 0, "a turn is running"
    assert au.tick(fake["spawn"]) == "busy" and fake["spawned"] == 0


@pytest.mark.parametrize("change", [
    {"verdict": "adapt"},
    {"notes": [{"version": "2.0.0a99"}]},
    {"unsaved": ["server/maxxing/app.py"]},
    {"customs": [{"id": "c1", "status": "conflict"}]},
    {"customs": [{"id": "c1", "status": "review"}]},
])
def test_does_not_update_when_something_needs_a_person(fake, change):
    fake["rep"] = {**fake["rep"], **change}
    assert au.tick(fake["spawn"]) == "needs_review" and fake["spawned"] == 0


def test_up_to_date_and_unavailable(fake):
    fake["rep"] = {"ok": True, "verdict": "up_to_date"}
    assert au.tick(fake["spawn"]) == "up_to_date"
    fake["rep"] = {"ok": False, "verdict": "unavailable", "error": "offline"}
    assert au.tick(fake["spawn"]) == "unavailable" and fake["spawned"] == 0


def test_somebody_arrives_during_the_preflight(fake, monkeypatch):
    def slow():
        fake["browsers"] = 1                      # a tab opens while the new version is simulated
        return fake["rep"]
    monkeypatch.setattr(au, "preflight", slow)
    assert au.tick(fake["spawn"]) == "busy" and fake["spawned"] == 0


def test_browser_count_follows_the_open_streams(mx):
    async def run():
        assert bus.browser_count() == 0
        g = bus.stream(check=True)
        await g.__anext__()
        assert bus.browser_count() == 1
        await g.aclose()
        assert bus.browser_count() == 0
        s = bus.stream(check=False)               # server-side listener: not a person
        await s.__anext__()
        assert bus.browser_count() == 0
        await s.aclose()
    asyncio.run(run())


def test_setting_through_the_api(client):
    assert client.get("/api/system/version").json()["auto_update"]["enabled"] is False
    assert client.put("/api/system/auto-update", json={"enabled": True}).json()["enabled"] is True
    assert client.get("/api/system/version").json()["auto_update"]["enabled"] is True
