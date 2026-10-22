"""Claude Code updated by the server while idle (maxxing/claude_update.py): never a real `claude update`."""
from __future__ import annotations

import time

import pytest

from maxxing import claude_update as cu
from maxxing import config, feed
from maxxing.sessions import store


@pytest.fixture
def fake(mx, monkeypatch):
    """Switched on; installed 2.1.0, stable 2.1.5; run_update(v) moves the installed version to `to` (or fails);
    `installed` None = a version that does not start."""
    config.update_config(claude_auto_update=True)
    st = {"installed": "2.1.0", "latest": "2.1.5", "calls": 0, "ok": True, "to": "2.1.5", "out": "", "asked": []}

    def run(version):
        st["calls"] += 1
        st["asked"].append(version)
        if st["ok"]:
            st["installed"] = st["to"] if version == st["latest"] else version
        return st["ok"], st["out"]

    monkeypatch.setattr(cu, "installed_version", lambda: st["installed"])
    monkeypatch.setattr(cu, "latest_version", lambda: st["latest"])
    monkeypatch.setattr(cu, "run_update", run)
    monkeypatch.setattr(cu, "install_method", lambda: ("npm", ["npm", "install", "-g"]))
    return st


def _session(state: str = "idle", finished_ago: float | None = None) -> str:
    m = store.new_meta("p/t", "x")
    m["state"] = state
    if state == "running":
        m["spawned_at"] = time.time()
    if finished_ago is not None:
        m["finished_at"] = time.time() - finished_ago
    return store.create(m)["id"]


def _events(title_part: str) -> list[dict]:
    return [e for e in feed.list_events()["events"] if title_part in e["title"]]


def test_off_by_default(mx, client):
    assert config.load_config()["claude_auto_update"] is False
    assert cu.tick() == "off" and client.get("/api/claude/status").json()["auto_update"]["enabled"] is False


def test_installs_the_exact_stable_version(fake):
    _session(finished_ago=3600)
    assert cu.tick() == "updated" and fake["asked"] == ["2.1.5"]


def test_version_that_does_not_start_is_rolled_back(fake):
    _session(finished_ago=3600)
    fake["to"] = None                                                      # 2.1.5 installed but broken
    assert cu.tick() == "failed" and fake["asked"] == ["2.1.5", "2.1.0"]
    assert fake["installed"] == "2.1.0" and "back to 2.1.0" in cu.load()["last"]["error"]


def test_running_claude_holds_the_update(fake):
    """A turn's runner holds the lock shared while its claude runs: no update under it."""
    import os
    from maxxing.sessions import runner
    _session(finished_ago=3600)
    fd = runner._claude_in_use()
    try:
        assert cu.tick() == "busy" and fake["calls"] == 0
    finally:
        os.close(fd)
    assert cu.tick() == "updated"


def test_other_install_is_left_alone(fake, monkeypatch):
    monkeypatch.setattr(cu, "install_method", lambda: None)
    assert cu.tick() == "unsupported" and fake["calls"] == 0


def test_install_method_from_the_binary(monkeypatch, tmp_path):
    native = tmp_path / ".local/share/claude/versions/2.1.0"
    native.parent.mkdir(parents=True)
    native.write_text("")
    monkeypatch.setattr(cu, "_bin", lambda: str(native))
    assert cu.install_method() == ("native", [str(native), "install"])
    npm_bin = tmp_path / "usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
    npm_bin.parent.mkdir(parents=True)
    npm_bin.write_text("")
    (tmp_path / "usr/bin").mkdir()
    (tmp_path / "usr/bin/npm").write_text("#!/bin/sh\n")
    (tmp_path / "usr/bin/npm").chmod(0o755)
    monkeypatch.setattr(cu, "_bin", lambda: str(npm_bin))
    kind, cmd = cu.install_method()
    assert kind == "npm" and cmd[0] == str(tmp_path / "usr/bin/npm") and cmd[cmd.index("--prefix") + 1] == str(tmp_path / "usr")
    monkeypatch.setattr(cu, "_bin", lambda: str(tmp_path / "elsewhere/claude"))
    assert cu.install_method() is None


def test_idle_server_updates_and_posts_once(fake):
    _session(finished_ago=3600)
    assert cu.tick() == "updated" and fake["calls"] == 1
    last = cu.load()["last"]
    assert last["from"] == "2.1.0" and last["to"] == "2.1.5" and last["ok"] and last["error"] is None
    assert len(_events("Claude Code updated to 2.1.5")) == 1
    assert cu.tick() == "up_to_date" and fake["calls"] == 1
    pub = cu.public()
    assert pub["enabled"] and pub["latest"] == "2.1.5" and pub["last"]["to"] == "2.1.5"


def test_busy_server_waits(fake):
    sid = _session("running")
    assert cu.tick() == "busy" and fake["calls"] == 0
    store.update(sid, state="idle", spawned_at=None, finished_at=time.time() - 60)
    assert cu.busy_reason() and cu.tick() == "busy"            # a turn ended 1 min ago
    store.update(sid, finished_at=time.time() - 3600)
    assert cu.busy_reason() is None
    assert cu.tick() == "updated" and fake["calls"] == 1


def test_queued_message_or_cron_keeps_it_waiting(fake, monkeypatch):
    sid = _session(finished_ago=3600)
    store.update(sid, queue=[{"text": "next"}])
    assert cu.tick() == "busy"
    store.update(sid, queue=[])
    from maxxing import crons
    monkeypatch.setattr(crons, "list_jobs", lambda: [{"id": "c1"}])
    monkeypatch.setattr(crons, "is_running", lambda cid: True)
    assert cu.busy_reason() == "a cron job is running" and fake["calls"] == 0


def test_disabled_does_nothing(fake, client):
    assert client.put("/api/claude/settings", json={"claude_auto_update": False}).json() == {"ok": True}
    assert config.load_config()["claude_auto_update"] is False
    assert cu.tick() == "off" and fake["calls"] == 0 and not cu.load()
    st = client.get("/api/claude/status").json()["auto_update"]
    assert st == {"enabled": False, "checked_at": None, "latest": None, "last": None}


def test_failure_posts_one_item_per_version(fake):
    fake.update(ok=False, out="EACCES: permission denied")
    assert cu.tick() == "failed" and fake["calls"] == 1
    last = cu.load()["last"]
    assert not last["ok"] and "EACCES" in last["error"] and last["to"] == "2.1.5"
    assert cu.tick() == "failed_recently" and fake["calls"] == 1          # no retry loop
    assert cu.tick(now=time.time() + cu.CHECK_EVERY_S + 1) == "failed" and fake["calls"] == 2
    assert len(_events("could not update to 2.1.5")) == 1                 # one feed item for this version
    fake["latest"] = "2.1.6"
    cu.tick(now=time.time() + 3 * cu.CHECK_EVERY_S)
    assert len(_events("could not update to 2.1.6")) == 1


def test_update_that_does_not_change_the_version_is_a_failure(fake):
    fake["to"] = "2.1.0"
    assert cu.tick() == "failed"
    assert "still 2.1.0" in cu.load()["last"]["error"]


def test_same_version_does_nothing(fake):
    fake["latest"] = "2.1.0"
    assert cu.tick() == "up_to_date" and fake["calls"] == 0
    fake["latest"] = "2.0.9"                                               # older on the registry: nothing either
    assert cu.tick(force_check=True) == "up_to_date" and fake["calls"] == 0
    assert not _events("Claude Code")


def test_registry_read_at_most_every_period(fake, monkeypatch):
    n = {"latest": 0}

    def latest():
        n["latest"] += 1
        return "2.1.0"
    monkeypatch.setattr(cu, "latest_version", latest)
    cu.tick()
    cu.tick()
    assert n["latest"] == 1
    cu.tick(now=time.time() + cu.CHECK_EVERY_S + 1)
    assert n["latest"] == 2
