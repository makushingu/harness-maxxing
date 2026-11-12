"""Agents that burn tokens for nothing: a turn killed before Claude reports its cost (timeout), a cron timeout
above the agent's own, the run note against waiting inside a run, a group session resumed after a long pause
(maxxing/agent_cost.py, agents.py, agent_rooms.py)."""
from __future__ import annotations

import json
import time

from conftest import wait_for, wait_idle
from maxxing import agent_cost, agent_rooms, agents

A = "projects/acme/topics/blog/agents/writer"


def _on(client) -> None:
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200


def _create(client, **extra) -> dict:
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": "writer",
                                         "display_name": "Writer", "sandbox": False, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _asst(mid: str, model: str, cr: int, cw: int = 0, out: int = 0, parent: str | None = None) -> str:
    return json.dumps({"type": "assistant", "parent_tool_use_id": parent,
                       "message": {"id": mid, "model": model, "usage": {
                           "input_tokens": 0, "output_tokens": out, "cache_read_input_tokens": cr,
                           "cache_creation_input_tokens": cw}}})


def test_last_turn_prices_a_turn_without_result():
    old = [json.dumps({"type": "mx_user", "text": "before"}), _asst("m0", "claude-opus-5-5", 10 ** 9),
           json.dumps({"type": "result", "total_cost_usd": 1}), json.dumps({"type": "mx_done", "code": 0, "at": 1})]
    turn = [json.dumps({"type": "mx_user", "text": "Run de TRAVAIL."}),
            _asst("m1", "claude-opus-5-5", 1_000_000, cw=100_000, out=1000),
            _asst("m1", "claude-opus-5-5", 1_000_000, cw=100_000, out=1000),      # same message, another block
            _asst("s1", "claude-sonnet-5-5", 2_000_000, parent="toolu_x"),        # a sub-agent counts too
            json.dumps({"type": "mx_done", "code": 143, "stopped": False, "timed_out": True, "at": 50})]
    done, usage, usd = agent_cost.last_turn(old + turn)
    assert done["timed_out"] and usage["cache_read_input_tokens"] == 3_000_000 and usage["output_tokens"] == 1000
    assert usd == round(0.2 + 0.5 + 0.02 + 0.4, 6)      # opus: read 0.2, write 5, out 20 / sonnet: read 0.2
    # a turn that reported its cost, one stopped by the owner, one still running: nothing to estimate
    assert agent_cost.last_turn(old)[0] is None
    stopped = turn[:-1] + [json.dumps({"type": "mx_done", "code": 143, "stopped": True, "timed_out": False})]
    assert agent_cost.last_turn(old + stopped)[0] is None
    assert agent_cost.last_turn(old + turn[:-1])[0] is None
    assert agent_cost.price("claude-unknown-9") == agent_cost.PRICES[-1][1]


def test_last_turn_keeps_the_tokens_before_a_message_added_to_the_turn():
    """Add now writes an `mx_user` marked injected in the middle of the turn: it does not start a new turn."""
    turn = [json.dumps({"type": "mx_user", "text": "go"}), _asst("m1", "claude-opus-5-5", 0, out=1_000_000),
            json.dumps({"type": "mx_user", "text": "more", "kind": "user", "injected": True}),
            _asst("m2", "claude-opus-5-5", 0, out=1_000_000),
            json.dumps({"type": "mx_done", "code": 143, "stopped": False, "timed_out": True, "at": 50})]
    assert agent_cost.last_turn(turn)[1]["output_tokens"] == 2_000_000
    fake = [json.dumps({"type": "mx_user", "text": '"injected": true'})]          # only the field counts
    assert agent_cost.last_turn(turn[:2] + fake + turn[3:])[1]["output_tokens"] == 1_000_000


def test_last_turn_is_the_one_sent_at_its_time_even_when_the_next_already_started():
    """The runner may start a queued message before on_turn_end reads the log: the lost turn is found by its time."""
    lost = [json.dumps({"type": "mx_user", "text": "work", "at": 10.0}), _asst("m1", "claude-opus-5-5", 0, out=1_000_000),
            json.dumps({"type": "mx_done", "code": 143, "stopped": False, "timed_out": True, "at": 50})]
    nxt = [json.dumps({"type": "mx_user", "text": "queued", "at": 60.0}), _asst("m2", "claude-opus-5-5", 0, out=5)]
    assert agent_cost.last_turn(lost + nxt)[0] is None                       # the last message's turn: still running
    done, usage, usd = agent_cost.last_turn(lost + nxt, 10.0)
    assert done["timed_out"] and usage["output_tokens"] == 1_000_000 and usd == 20.0
    assert agent_cost.last_turn(lost + nxt, 999.0)[0] is None                 # unknown time: as before


def test_the_next_turn_does_not_count_an_estimated_turn_again():
    """Claude keeps a SIGTERM-ed turn in the thread's total: the next --resume reports it again."""
    from maxxing.sessions import store
    assert store.turn_cost(5.0, 2.0, 1.0) == 2.0 and store.turn_cost(5.0, 2.0) == 3.0
    assert store.turn_cost(2.5, 2.0, 1.0) == 0.0                              # Claude had not saved it: never below 0
    m = {"csid": "c1", "thread_cost": {"csid": "c1", "total": 2.0, "estimated": 1.5}}
    assert store.thread_estimated(m, "c1") == 1.5 and store.thread_estimated(m, "c2") == 0.0
    assert store.thread_estimated({"thread_cost": {"csid": "c1", "estimated": "x"}}, "c1") == 0.0


def test_a_turn_killed_before_its_result_counts_in_the_budget(client, topic, mx):
    _on(client)
    _create(client)
    r = agents.fire(A, trigger="manual", prompt="HALFTURN work", source="command line")
    sid = r["session"]["id"]
    wait_idle(client, sid)
    res = wait_for(lambda: [m for m in agents.thread(A) if m["kind"] == "result" and m.get("session") == sid])
    from maxxing.sessions import store
    m = store.read(sid)
    assert m["estimated_usd"] > 0 and m["cost_usd"] == m["estimated_usd"]
    assert sum(d["cost"] for d in m["days"].values()) == m["estimated_usd"]
    assert agents.day_cost(A) == round(m["estimated_usd"], 4) and res[0]["cost"] == round(m["estimated_usd"], 4)
    assert agent_cost.charge_unbilled(sid) == 0.0          # once per turn
    assert store.read(sid)["cost_usd"] == m["cost_usd"]
    tc = m["thread_cost"]                                  # taken off the next reported total of the same thread
    assert tc["csid"] == (m.get("csid") or sid) and tc["estimated"] == m["estimated_usd"]
    # a normal turn reports its cost itself: nothing estimated
    r = agents.fire(A, trigger="manual", prompt="NOTOOL ok", source="command line")
    wait_idle(client, r["session"]["id"])
    assert "estimated_usd" not in store.read(r["session"]["id"])


def test_the_turn_after_a_killed_one_does_not_count_it_twice(client, topic, mx):
    _on(client)
    _create(client)
    r = agents.fire(A, trigger="manual", prompt="HALFTURN HALFCOST=0.25 work", source="command line")
    sid = r["session"]["id"]
    wait_idle(client, sid)
    from maxxing.sessions import store
    wait_for(lambda: store.read(sid).get("estimated_usd"))
    est = store.read(sid)["estimated_usd"]
    assert client.post(f"/api/sessions/{sid}/messages", json={"text": "NOTOOL go on"}).status_code == 200
    wait_idle(client, sid)
    m = wait_for(lambda: (x := store.read(sid)) and int(x.get("turns") or 0) >= 2 and x)
    # Claude reported 0.25 (the killed turn) + 0.0123 (this one): the estimate is not counted a second time
    assert m["cost_usd"] == round(est + 0.25 + 0.0123 - est, 6) and "estimated" not in m["thread_cost"]


def test_a_cron_timeout_never_goes_past_the_agents_own(client, topic, mx):
    _on(client)
    _create(client, limits={"timeout_s": 600})
    a = agents.load(A)
    assert agents.run_timeout(a, 3600) == 600 and agents.run_timeout(a, 120) == 120
    assert agents.run_timeout(a, None) == 600 and agents.run_timeout(a, "x") == 600
    r = agents.fire(A, trigger="cron:c_x", prompt="NOTOOL hourly", source="cron", timeout_s=3600)
    from maxxing.sessions import store
    assert store.read(r["session"]["id"])["timeout_s"] == 600
    wait_idle(client, r["session"]["id"])


def test_runs_are_told_not_to_wait_inside_a_run(client, topic, mx):
    _on(client)
    _create(client)
    note = agents.run_settings(A)["system_note"]
    assert agents.RUN_NOTE in note and "Never wait inside a run" in note


def test_a_group_session_is_renewed_after_a_long_pause(client, topic, mx):
    from test_agent_groups import G, W, _idle, _setup
    from maxxing.sessions import store
    _setup(client)
    path = "projects/acme/groups/team"
    assert client.post(f"{G}/messages", json={"text": "@writer\nREPLY_AS writer: Draft ready"}).status_code == 200
    _idle(client, 1)
    first = agent_rooms._read_state(path)["sessions"][W]
    # a message soon after: the same session goes on
    assert client.post(f"{G}/messages", json={"text": "@writer again\nREPLY_AS writer: Second"}).status_code == 200
    _idle(client, 2)
    assert agent_rooms._read_state(path)["sessions"][W] == first
    # silent for longer than chat_idle_h: a new session, with the recent talk (its own answers too)
    with store.edit(first) as m:
        m["finished_at"] = time.time() - (agents.load(W)["limits"]["chat_idle_h"] + 1) * 3600
    store.read_cached(first)
    assert client.post(f"{G}/messages", json={"text": "@writer later\nREPLY_AS writer: Third"}).status_code == 200
    _idle(client, 3)
    new = agent_rooms._read_state(path)["sessions"][W]
    assert new != first
    from test_agent_groups import _calls
    prompt = [c for c in _calls() if c["cwd"].endswith("/writer")][-1]["prompt"]
    assert 'You are @writer in the agent group "Team"' in prompt and "Draft ready" in prompt and "Second" in prompt
