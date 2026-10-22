from __future__ import annotations

from maxxing.sessions import service, store


def test_queue_count_ignores_the_message_being_started(mx):
    m = store.new_meta("", "Q")
    m.update(state="running", pid=None, queue=[{"text": "first", "kind": "user"}])
    assert service._waiting(m) == 0                            # runner not started: being sent, not queued
    m.update(pid=12345, queue=[{"text": "second", "kind": "user"}])
    assert service._waiting(m) == 1                            # a turn runs: really waiting
    m.update(state="idle", pid=None)
    assert service._waiting(m) == 1
