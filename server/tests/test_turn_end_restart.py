"""A turn that ends while the server is stopped or restarting is still reported (Telegram reply, notification)."""
from __future__ import annotations

import time

from maxxing import config
from maxxing.sessions import service, store
from conftest import wait_for


def test_a_turn_ended_during_a_restart_is_reported(client, topic):
    """The watcher stops (update, restart), the turn ends meanwhile, the watcher starts again: it reports it."""
    ended: list[str] = []
    service.on_turn_end(lambda sess, res: ended.append(sess["id"]))
    try:
        s = client.post("/api/sessions", json={"path": topic, "message": "PAUSE NOTOOL"}).json()
        wait_for(lambda: (store.read(s["id"]) or {}).get("pid"), 10)
        wait_for(lambda: (config.STATE / "session-watcher.json").exists(), 10)
        client.portal.call(service.stop_watcher)                     # the server stops
        wait_for(lambda: (store.read(s["id"]) or {}).get("state") == "idle", 20)   # the turn ends meanwhile
        assert s["id"] not in ended
        client.portal.call(lambda: service.start_watcher())          # the server is back
        wait_for(lambda: s["id"] in ended, 10)
        time.sleep(1.5)
        assert ended.count(s["id"]) == 1
    finally:
        service._turn_cbs.pop()


def _ended(finished_at: float) -> str:
    meta = store.new_meta("", "done")
    meta.update(state="idle", turns=1, finished_at=finished_at)
    store.create(meta)
    return meta["id"]


def test_first_pass_reports_only_what_ended_after_the_last_pass(mx):
    """No stamp (first start ever): nothing is reported. Otherwise only turns that ended after the last pass."""
    sid = _ended(time.time() - 30)

    def first_pass() -> list[str]:
        service._known.clear()
        ends, _, _ = service._scan(False)
        return [s["id"] for s, _ in ends]
    assert first_pass() == []                                         # first start: a baseline only
    service._stamp(time.time() - 60)
    assert first_pass() == [sid]                                      # ended 30 s ago, the server stopped 60 s ago
    service._stamp(time.time() - 10)
    assert first_pass() == []                                         # already reported before the stop
    service._known.clear()
