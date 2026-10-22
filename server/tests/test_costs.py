from __future__ import annotations

import json

from conftest import all_events, wait_idle
from maxxing.sessions import costfix, normalize, store


def test_turn_cost_is_the_increase_of_the_thread_total():
    assert store.turn_cost(1.40, 1.36) == 0.04
    assert store.turn_cost(0.5, 3.0) == 0.5          # a new thread starts again from zero
    assert store.thread_prev_cost({"thread_cost": {"csid": "a", "total": 2.0}}, "a") == 2.0
    assert store.thread_prev_cost({"thread_cost": {"csid": "a", "total": 2.0}}, "b") == 0.0


def test_runner_counts_each_turn_once(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "one NOTOOL"}).json()
    s1 = wait_idle(client, s["id"])
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "two NOTOOL"})
    s2 = wait_idle(client, s["id"])
    one = s1["cost_usd"]
    # the fake Claude reports the same running total pattern as the real one: per-turn costs must not pile up
    results = [e for e in all_events(client, s["id"]) if e["type"] == "result"]
    assert round(sum(r["cost_usd"] for r in results), 4) == round(s2["cost_usd"], 4)
    assert s2["cost_usd"] >= one
    m = store.read(s["id"])
    assert m["cost_v"] == 2 and m["thread_cost"]["csid"]


def test_costfix_repairs_an_old_session(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "x NOTOOL"}).json()
    wait_idle(client, s["id"])
    sid = s["id"]
    path = store.log_path(sid)
    # an old-style log: three turns of one thread reporting its running total, counted as 1 + 3 + 6 = 10
    lines = [json.dumps({"type": "result", "session_id": "t1", "total_cost_usd": t, "usage": {}, "mx_at": 1.7e9})
             for t in (1.0, 3.0, 6.0)]
    path.write_text("\n".join(lines) + "\n")
    with store.edit(sid) as m:
        m["cost_usd"], m["cost_v"], m["csid"] = 10.0, 1, "t1"
        m.pop("thread_cost", None)
    assert costfix.fix_session(sid) == "fixed"
    m = store.read(sid)
    assert m["cost_usd"] == 6.0 and m["thread_cost"] == {"csid": "t1", "total": 6.0}
    evs = normalize.normalize_lines(path.read_text().splitlines())
    assert [e["cost_usd"] for e in evs] == [1.0, 2.0, 3.0]
    assert costfix.fix_session(sid) == "done"
