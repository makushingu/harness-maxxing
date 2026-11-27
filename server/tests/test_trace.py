"""What a turn did, step by step (sessions/trace.py, GET /api/sessions/{sid}/turns[/{n}])."""
from __future__ import annotations

import json

from maxxing.sessions import store, trace


def _usage(i, o=0, r=0, w=0):
    return {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": r, "cache_creation_input_tokens": w}


def _assistant(mid, at, blocks, usage, parent=None, model="claude-opus-5-5"):
    return {"type": "assistant", "mx_at": at, "parent_tool_use_id": parent,
            "message": {"id": mid, "model": model, "content": blocks, "usage": usage}}


def _result(tool_id, at, error=False, parent=None):
    return {"type": "user", "mx_at": at, "parent_tool_use_id": parent,
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "is_error": error, "content": "out"}]}}


LOG = [
    {"type": "system", "subtype": "init", "mx_at": 1},                           # before any turn: ignored
    {"type": "mx_user", "text": "fix the bug " + "x" * 400, "source": "web", "kind": "", "at": 100.0},
    {"type": "system", "subtype": "init", "model": "claude-opus-5-5", "mx_at": 100.5},
    # one model call logged as two lines (thinking, then the tool call): same id, same usage -> one step
    _assistant("m1", 101.0, [{"type": "thinking", "thinking": "..."}], _usage(2, 1, 1000, 50)),
    _assistant("m1", 101.2, [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls -la"}}], _usage(2, 9, 1000, 50)),
    _result("t1", 103.7),
    _assistant("m2", 104.0, [{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/x/a.py"}},
                             {"type": "tool_use", "id": "t3", "name": "Agent", "input": {"description": "look"}}], _usage(3, 5, 1100, 10)),
    _assistant("s1", 104.5, [{"type": "tool_use", "id": "t4", "name": "Grep", "input": {"pattern": "foo"}}], _usage(1, 1, 10, 10), parent="t3"),
    _result("t4", 104.9, parent="t3"),
    _result("t2", 105.0, error=True),
    {"type": "mx_note", "text": "retrying", "level": "warning", "at": 105.5},
    _assistant("m3", 106.0, [{"type": "text", "text": "done!"}], _usage(4, 2, 1200, 0)),
    {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 6000, "ttft_ms": 800, "num_turns": 3,
     "total_cost_usd": 9.0, "mx_turn_cost": 0.42, "usage": _usage(9, 300, 3300, 60), "mx_at": 106.5},
    {"type": "mx_done", "code": 0, "stderr": "", "stopped": False, "timed_out": False, "at": 107.0},
    "garbage that is not json",
    {"type": "mx_user", "text": "again", "source": "telegram", "at": 200.0},
    _assistant("m4", 201.0, [{"type": "tool_use", "id": "t9", "name": "Bash", "input": {"command": "sleep 999"}}], _usage(5, 1, 0, 0)),
    {"type": "mx_done", "code": 143, "stderr": "", "stopped": True, "timed_out": False, "at": 230.0},
    {"type": "mx_user", "text": "third", "at": 300.0},
    _assistant("m5", 301.0, [{"type": "text", "text": "hi"}], _usage(7, 1, 0, 0)),
]


def _make() -> str:
    m = store.new_meta("", "S")
    store.create(m)
    with open(store.log_path(m["id"]), "a") as f:
        for ev in LOG:
            f.write((ev if isinstance(ev, str) else json.dumps(ev)) + "\n")
    return m["id"]


def test_turns_in_numbers(mx):
    sid = _make()
    a, b, c = trace.turns(sid)
    assert "steps" not in a and len(a["prompt"]) == trace.PROMPT_MAX
    assert (a["n"], a["state"], a["duration_s"], a["cost_usd"], a["model"]) == (1, "done", 7.0, 0.42, "claude-opus-5-5")
    assert (a["model_calls"], a["tool_calls"], a["errors"]) == (4, 4, 1)       # the sub-agent's call and tool included
    # the tokens Settings -> Usage counts for the turn: its result line, not the sum of what each call announced
    assert a["tokens"] == {"input": 9, "output": 300, "cache_read": 3300, "cache_write": 60} and a["tokens_source"] == "result"
    assert a["total_tokens"] == 3669 and a["api"] == {"duration_s": 6.0, "first_token_s": 0.8, "model_turns": 3}
    assert (b["state"], b["code"], b["duration_s"], b["cost_usd"], b["source"]) == ("stopped", 143, 30.0, None, "telegram")
    assert b["tokens_source"] == "calls" and b["tokens"]["input"] == 5
    assert (c["state"], c["duration_s"], c["model_calls"]) == ("running", None, 1)   # no mx_done yet


def test_one_turn_step_by_step(mx):
    sid = _make()
    t = trace.turn(sid, 1)
    kinds = [(s["kind"], s.get("name") or s.get("level") or "") for s in t["steps"]]
    assert kinds == [("model", ""), ("tool", "Bash"), ("model", ""), ("tool", "Read"), ("tool", "Agent"),
                     ("model", ""), ("tool", "Grep"), ("note", "warning"), ("model", "")]
    m1, bash, _m2, read, agent, sub_call, grep, note, m3 = t["steps"]
    assert m1 == {"kind": "model", "at": 101.0, "model": "claude-opus-5-5", "sub": False, "text_chars": 0, "thinking": True,
                  "context": 1052, "cache_read": 1000, "cache_write": 50}
    assert bash == {"kind": "tool", "at": 101.2, "name": "Bash", "summary": "Bash: ls -la", "sub": False,
                    "duration_s": 2.5, "error": False, "done": True}
    assert read["error"] and read["duration_s"] == 1.0 and read["summary"] == "Read /x/a.py"
    assert not agent["done"] and agent["duration_s"] is None                    # its result never came
    assert sub_call["sub"] and grep["sub"] and grep["duration_s"] == 0.4
    assert note["text"] == "retrying" and m3["text_chars"] == 5 and t["steps_dropped"] == 0
    # the other turns' lines are not this one's
    two = trace.turn(sid, 2)
    assert [s["name"] for s in two["steps"] if s["kind"] == "tool"] == ["Bash"] and not two["steps"][1]["done"]
    assert trace.turn(sid, 3)["state"] == "running" and trace.turn(sid, 4) is None and trace.turn(sid, 0) is None


def test_a_huge_turn_is_cut_not_refused(mx, monkeypatch):
    monkeypatch.setattr(trace, "STEPS_MAX", 3)
    t = trace.turn(_make(), 1)
    assert len(t["steps"]) == 3 and t["steps_dropped"] == 6 and t["tool_calls"] == 4


def test_api(client, mx):
    sid = _make()
    r = client.get(f"/api/sessions/{sid}/turns").json()
    assert [t["n"] for t in r["turns"]] == [1, 2, 3] and "steps" not in r["turns"][0]
    r = client.get(f"/api/sessions/{sid}/turns/1")
    assert r.status_code == 200 and "content-disposition" not in r.headers
    assert r.json()["session"] == sid and len(r.json()["turn"]["steps"]) == 9
    d = client.get(f"/api/sessions/{sid}/turns/2?download=1")
    assert f'harness-turn-{sid[:8]}-2.json' in d.headers["content-disposition"]
    assert client.get(f"/api/sessions/{sid}/turns/9").json()["error"] == "not_found"
    assert client.get(f"/api/sessions/{sid}/turns/x").status_code == 422
    assert client.get("/api/sessions/00000000-0000-0000-0000-000000000000/turns").status_code == 404
    assert client.get("/api/sessions/00000000-0000-0000-0000-000000000000/turns/1").status_code == 404


def test_no_log_no_turn(mx):
    m = store.new_meta("", "S")
    store.create(m)
    assert trace.turns(m["id"]) == [] and trace.turn(m["id"], 1) is None
