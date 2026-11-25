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
    assert au.tick(fake["spawn"], now=50.0) == "busy"
    assert au.public()["last"] == {"at": 50.0, "result": "busy", "why": "browser"}     # said under the switch
    fake["browsers"], fake["busy"] = 0, "a turn is running"
    assert au.tick(fake["spawn"]) == "busy" and fake["spawned"] == 0
    assert au.public()["last"]["why"] == "turn"
    fake["busy"] = "something new"
    assert au.tick(fake["spawn"]) == "busy" and au.public()["last"]["why"] == "work"
    for why in ("a message is waiting", "a side question is running", "a cron job is running",
                "a turn ended less than 10 min ago"):                # every reason claude_update gives has its word
        assert why in au.WHY


def test_every_reason_of_the_idle_check_has_a_word():
    import inspect
    import re
    given = set(re.findall(r'return "([^"]+)"', inspect.getsource(au.claude_update.busy_reason)))
    given |= set(re.findall(r'return "([^"]+)"', inspect.getsource(au.busy_reason)))
    assert given and given <= set(au.WHY)


def test_an_upgrade_note_does_not_hold_the_update_back(fake, mx):
    """Half the versions come with a note for the workspace: the update goes on, the note is announced after it."""
    from maxxing import feed
    fake["rep"] = {**fake["rep"], "notes": [{"version": "2.0.0a98"}, {"version": "2.0.0a99"}]}
    assert au.tick(fake["spawn"], now=1000.0) == "started" and fake["spawned"] == 1
    assert au.public()["last"] == {"at": 1000.0, "result": "started"}
    assert au.public()["tried"] == {"target": "abc123", "version": "2.0.0a99", "at": 1000.0}
    assert [e["title"] for e in feed.list_events()["events"]] == ["Harness is updating to 2.0.0a99"]


def test_an_update_that_cannot_start_is_said_and_not_announced(fake, mx):
    from maxxing import feed

    def broken():
        raise RuntimeError("systemd-run: not found")
    assert au.tick(broken, now=1000.0) == "failed"
    assert au.public()["last"]["result"] == "failed" and feed.list_events()["events"] == []
    assert au.tick(fake["spawn"], now=1000.0 + 600) == "tried_recently" and fake["spawned"] == 0   # never a loop
    assert au.tick(fake["spawn"], now=1000.0 + 25 * 3600) == "started"


def test_one_notification_per_version_when_a_person_is_needed(fake, mx):
    from maxxing import feed
    fake["rep"] = {**fake["rep"], "customs": [{"id": "c1", "status": "conflict"}]}
    assert au.tick(fake["spawn"]) == "needs_review"
    fake["rep"] = {**fake["rep"], "target": "def456"}               # a new commit of the same version
    assert au.tick(fake["spawn"]) == "needs_review"
    assert [e["title"] for e in feed.list_events()["events"]] == ["Harness 2.0.0a99 is available but needs you"]


def test_a_busy_server_is_looked_at_again_sooner(fake, monkeypatch):
    slept, results = [], iter(["busy", "up_to_date"])

    async def sleep(s):
        slept.append(s)
        if len(slept) == 3:
            raise asyncio.CancelledError
    monkeypatch.setattr(au.asyncio, "sleep", sleep)
    monkeypatch.setattr(au, "tick", lambda spawn: next(results))
    monkeypatch.setenv("MAXXING_AUTO_UPDATE_DELAY", "7")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(au._loop(fake["spawn"]))
    assert slept == [7.0, au.BUSY_POLL_S, au.POLL_S]


@pytest.mark.parametrize("change", [
    {"verdict": "adapt"},
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


@pytest.mark.parametrize("tried", ["x", ["abc123"], {"target": "abc123", "at": "soon"}, {"target": "abc123", "at": float("nan")}])
def test_a_damaged_state_file_does_not_block_the_update(fake, tried):
    config.write_json(au.state_file(), {"tried": tried, "last": {"at": "yesterday", "result": "busy"}, "last_check": 7})
    pub = au.public()                                   # the Version card formats these dates: never a bad one
    assert pub["tried"] is None and pub["last"] is None and pub["last_check"] is None
    assert au.tick(fake["spawn"], now=1000.0) == "started" and fake["spawned"] == 1
    assert au.public()["last"]["result"] == "started"
