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
    # a normal turn reports its cost itself: nothing estimated
    r = agents.fire(A, trigger="manual", prompt="NOTOOL ok", source="command line")
    wait_idle(client, r["session"]["id"])
    assert "estimated_usd" not in store.read(r["session"]["id"])


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
