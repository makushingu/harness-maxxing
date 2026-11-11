"""An agent's turn start / end reaches its page through `agents:<path>` from the session watcher: the page no longer
refetches its thread on every turn of every session (BUS_TURN_KEYS of the web app)."""
from __future__ import annotations

import time

from maxxing import bus
from maxxing.sessions import service, store
from conftest import wait_for

AGENT = "projects/acme/topics/blog/agents/writer"


def _session(path: str) -> str:
    meta = store.new_meta(path, "t")
    meta.update(state="idle", turns=0)
    store.create(meta)
    return meta["id"]


def _pass() -> set[str]:
    service._scan(True)
    out = set(service._agent_turns)
    service._agent_turns.clear()
    return out


def test_an_agent_turn_start_and_end_name_the_agent(mx):
    service._known.clear()
    service._agent_turns.clear()
    sid = _session(AGENT)
    other = _session("projects/acme/topics/blog")
    service._scan(False)                                              # baseline
    service._agent_turns.clear()
    store.update(sid, state="running")
    assert _pass() == {AGENT}                                         # started
    store.update(sid, state="idle", turns=1, finished_at=time.time())
    assert _pass() == {AGENT}                                         # ended
    store.update(other, state="running")
    assert _pass() == set()                                           # a normal session's turn: no agent page
    store.update(sid, title="renamed")
    assert _pass() == set()                                           # metadata only (no state / unread change)
    service._known.clear()


def test_a_new_running_agent_session_names_the_agent(mx):
    service._known.clear()
    service._agent_turns.clear()
    service._scan(False)
    meta = store.new_meta(AGENT, "t")
    meta.update(state="running")
    store.create(meta)
    assert _pass() == {AGENT}
    service._known.clear()


def test_the_watcher_publishes_the_agent_topic(client, monkeypatch):
    """Sibling path: the running watcher puts `agents:<path>` in the same bus message as sessions + workspace."""
    sent: list[tuple[str, ...]] = []
    real = bus.invalidate
    monkeypatch.setattr(bus, "invalidate", lambda *t: (sent.append(t), real(*t)))
    sid = _session(AGENT)
    wait_for(lambda: any("sessions" in t for t in sent), 10)
    store.update(sid, state="running")
    wait_for(lambda: any(f"agents:{AGENT}" in t for t in sent), 10)
    msg = next(t for t in sent if f"agents:{AGENT}" in t)
    assert "sessions" in msg and "workspace" in msg
    assert not service._agent_turns                                   # drained once sent
