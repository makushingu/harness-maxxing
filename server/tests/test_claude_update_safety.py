"""Claude Code updates never run under a turn: the update lock (exclusive for `claude update`, shared for each
Claude a turn starts), and only the installed server updates the machine's CLI. Never a real `claude update`."""
from __future__ import annotations

import json
import os
import time

from maxxing import claude_update as cu
from maxxing import config
from maxxing.sessions import runner, service, store
from conftest import wait_for


def _calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(ln) for ln in f.read_text().splitlines()] if f.exists() else []


def _notes(sid: str) -> list[str]:
    path = store.log_path(sid)
    if not path.exists():
        return []
    out = []
    for ln in path.read_text().splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if ev.get("type") == "mx_note":
            out.append(ev["text"])
    return out


def test_turn_started_during_an_update_waits_for_it(mx, client, topic):
    """While `claude update` replaces the binary (exclusive lock held), a new turn does not start Claude: it says
    so in the session and starts right after the update."""
    fd = cu._exclusive()
    assert fd is not None
    try:
        s = service.create_session(topic, message="hello", title="during the update", source="web")
        assert wait_for(lambda: any("being updated" in n for n in _notes(s["id"])), timeout=15)
        time.sleep(0.5)
        assert _calls(mx) == []                                                # Claude not started under the update
    finally:
        os.close(fd)
    done = service.wait_turn(s["id"], 30)
    assert done["state"] == "idle" and len(_calls(mx)) == 1


def test_turn_never_waits_longer_than_the_update_limit(mx, monkeypatch):
    monkeypatch.setattr(runner, "UPDATE_WAIT_S", 1)
    fd = cu._exclusive()
    notes = []
    try:
        t = time.monotonic()
        mine = runner._claude_in_use(lambda text, level="info": notes.append((level, text)))
        assert mine is not None and 0.9 <= time.monotonic() - t < 5
        os.close(mine)
    finally:
        os.close(fd)
    assert [lv for lv, _ in notes] == ["info", "warn"] and "starts anyway" in notes[1][1]


def test_free_lock_costs_a_turn_nothing(mx):
    notes = []
    t = time.monotonic()
    fd = runner._claude_in_use(lambda *a, **k: notes.append(a))
    assert fd is not None and time.monotonic() - t < 0.5 and notes == []
    assert cu._exclusive() is None                                             # a running Claude holds the update
    os.close(fd)
    again = cu._exclusive()
    assert again is not None
    os.close(again)


def test_only_the_installed_server_updates_the_machine(monkeypatch, tmp_path):
    """A dev server or a test copy of the state (another MAXXING_STATE) never runs `claude update` on its own."""
    monkeypatch.delenv("MAXXING_CLAUDE_UPDATE", raising=False)
    monkeypatch.setattr(config, "STATE", tmp_path)
    assert not cu.runs_here()
    monkeypatch.setattr(config, "STATE", cu.DEFAULT_STATE)
    assert cu.runs_here()
    monkeypatch.setenv("MAXXING_CLAUDE_UPDATE", "0")
    assert not cu.runs_here()
    monkeypatch.setenv("MAXXING_CLAUDE_UPDATE", "1")
    monkeypatch.setattr(config, "STATE", tmp_path)
    assert cu.runs_here()
