"""Huge session logs: clipping at write time, backward paging, compact-logs, reset on rewrite."""
from __future__ import annotations

import json
import os
import time

from maxxing import cli
from maxxing.sessions import clip, service, store

from conftest import all_events, wait_idle


def _line(ev: dict) -> str:
    return json.dumps(ev) + "\n"


def _turn_lines(i: int, result_size: int = 0) -> str:
    """One synthetic turn as the runner writes it: user, assistant text, tool_use/result, result."""
    tid = f"toolu_{i:08d}"
    content = f"output {i}" + ("y" * result_size)
    return "".join([
        _line({"type": "mx_user", "text": f"message {i}", "attachments": [], "source": "web", "at": float(i)}),
        _line({"type": "assistant", "message": {"content": [{"type": "text", "text": f"answer {i}"}]},
               "mx_at": float(i)}),
        _line({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": "Bash",
                                                              "input": {"command": f"echo {i}"}}]},
               "mx_at": float(i)}),
        _line({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                                         "content": content}]}, "mx_at": float(i)}),
        _line({"type": "result", "subtype": "success", "total_cost_usd": 0, "mx_at": float(i)}),
    ])


def _session_with_log(topic: str, text: str) -> str:
    meta = store.new_meta(topic, "Long history")
    store.create(meta)
    store.log_path(meta["id"]).write_text(text)
    return meta["id"]


def test_runner_clips_tool_outputs(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "HUGE please"}).json()
    s = wait_idle(client, s["id"])
    assert s["state"] == "idle" and s["error"] is None
    size = store.log_size(s["id"])
    assert size < 200_000, size                        # 3 MB + 500 kB + 100 kB never reach the log
    raw = [json.loads(x) for x in store.log_path(s["id"]).read_text().splitlines()]
    assert all("tool_use_result" not in ev for ev in raw)
    big = [b for ev in raw if ev.get("type") == "user"
           for b in (ev.get("message") or {}).get("content") or [] if b.get("mx_clipped")]
    assert {b["mx_clipped"] for b in big if isinstance(b["content"], str)} == {3_000_000}
    evs = all_events(client, s["id"])
    results = [e for e in evs if e["type"] == "tool_result"]
    huge = next(r for r in results if r["text"].startswith("xxx"))
    assert len(huge["text"]) < clip.RESULT_MAX + 200 and "3,000,000 characters" in huge["text"]
    assert any(r["text"] == "[image]" for r in results)
    write = next(e for e in evs if e["type"] == "tool_use" and e["name"] == "Write")
    assert len(write["input"]["content"]) < clip.INPUT_MAX + 200 and "100,000" in write["input"]["content"]
    assert evs[-1]["type"] == "result" and evs[-1]["ok"]


def test_tail_and_before_paging(client, topic):
    sid = _session_with_log(topic, "".join(_turn_lines(i) for i in range(500)))
    size = store.log_size(sid)
    r = client.get(f"/api/sessions/{sid}/events", params={"tail": 20}).json()
    assert r["next"] == size and r["more_before"] is True and r["state"] == "idle"
    assert 20 <= len(r["events"]) < 30
    assert r["events"][-1]["type"] == "result"
    seen = r["events"]
    start = r["start"]
    pages = 0
    while start > 0:
        p = client.get(f"/api/sessions/{sid}/events", params={"before": start, "limit": 300}).json()
        assert p["start"] < start and p["next"] == start
        seen = p["events"] + seen
        start = p["start"]
        pages += 1
        assert p["more_before"] == (start > 0)
    assert pages >= 2
    users = [e["text"] for e in seen if e["type"] == "user"]
    assert users == [f"message {i}" for i in range(500)]      # every event exactly once, in order
    # forward reading from the same log gives the same events
    assert seen == all_events(client, sid)
    # an offset that is not a line boundary -> reset
    assert client.get(f"/api/sessions/{sid}/events", params={"before": start + 5}).json()["reset"] is True
    assert client.get(f"/api/sessions/{sid}/events", params={"from": size + 10}).json()["reset"] is True


def test_tail_of_50mb_log_is_fast(client, topic):
    text = "".join(_turn_lines(i, result_size=50_000) for i in range(1000))    # ~50 MB
    sid = _session_with_log(topic, text)
    assert store.log_size(sid) > 50_000_000
    t0 = time.perf_counter()
    r = client.get(f"/api/sessions/{sid}/events", params={"tail": 200}).json()
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, elapsed
    assert len(r["events"]) >= 200 and r["events"][-1]["type"] == "result" and r["more_before"]
    assert r["next"] == store.log_size(sid)


def test_runner_slims_init_and_drops_thinking_tokens(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "hello NOTOOL"}).json()
    s = wait_idle(client, s["id"])
    raw = [json.loads(x) for x in store.log_path(s["id"]).read_text().splitlines()]
    assert not any(ev.get("subtype") == "thinking_tokens" for ev in raw)
    init = next(ev for ev in raw if ev.get("subtype") == "init")
    assert "tools" not in init and init["model"] and init["cwd"] and init["session_id"] and init["permissionMode"]
    assert any(e["type"] == "init" and e["model"] for e in all_events(client, s["id"]))


def test_compact_logs_slims_existing_system_lines(client, topic):
    init = {"type": "system", "subtype": "init", "cwd": "/w", "session_id": "c1", "model": "claude-x",
            "tools": ["Bash"] * 50, "skills": ["s" * 40] * 200, "slash_commands": ["/x"] * 300, "mx_at": 1.0}
    think = {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 40, "session_id": "c1"}
    sid = _session_with_log(topic, _line(init) + _line(think) * 30 + _turn_lines(0))
    before = store.log_size(sid)
    events_before = all_events(client, sid)
    r = service.compact_log(sid)
    assert r["status"] == "compacted" and r["after"] < before / 4
    raw = [json.loads(x) for x in store.log_path(sid).read_text().splitlines()]
    assert raw[0] == {"type": "system", "subtype": "init", "cwd": "/w", "session_id": "c1", "model": "claude-x",
                      "mx_at": 1.0}
    assert not any(ev.get("subtype") == "thinking_tokens" for ev in raw)
    assert all_events(client, sid) == events_before                # nothing the UI shows changed
    assert service.compact_log(sid)["status"] == "unchanged"


def test_tail_ignores_partial_last_line(client, topic):
    sid = _session_with_log(topic, _turn_lines(0) + '{"type": "assistant", "mess')
    r = client.get(f"/api/sessions/{sid}/events", params={"tail": 50}).json()
    assert r["next"] == len(_turn_lines(0).encode()) and r["start"] == 0 and r["more_before"] is False


def test_compact_logs_command(client, topic, capsys):
    sid = _session_with_log(topic, "".join(_turn_lines(i, result_size=100_000) for i in range(20)))
    before = store.log_size(sid)
    evs_before = [e["text"] for e in all_events(client, sid) if e["type"] == "user"]
    assert cli.main(["sessions", "compact-logs", "--dry-run"]) == 0
    assert "would save" in capsys.readouterr().out and store.log_size(sid) == before
    ino = os.stat(store.log_path(sid)).st_ino
    assert cli.main(["sessions", "compact-logs"]) == 0
    out = capsys.readouterr().out
    after = store.log_size(sid)
    assert after < before / 20 and sid in out and "saved" in out
    assert os.stat(store.log_path(sid)).st_ino != ino               # atomic replace
    assert oct(os.stat(store.log_path(sid)).st_mode & 0o777) == "0o600"
    assert [e["text"] for e in all_events(client, sid) if e["type"] == "user"] == evs_before
    # second run: nothing to do
    assert service.compact_log(sid)["status"] == "unchanged"


def test_compact_logs_skips_running_session(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "SLOW please"}).json()
    assert service.compact_log(s["id"])["status"] == "running"
    client.post(f"/api/sessions/{s['id']}/stop")
    wait_idle(client, s["id"], 15)


def test_stream_resets_when_log_shrinks(client, topic):
    sid = _session_with_log(topic, "".join(_turn_lines(i, result_size=10_000) for i in range(10)))
    size = store.log_size(sid)
    # stale offset (the log was rewritten since the client read it)
    with client.stream("GET", f"/api/sessions/{sid}/stream", params={"from": size + 100}) as r:
        body = "".join(r.iter_text())
    assert "event: reset" in body
    # rewritten while streaming
    import threading

    def rewrite():
        time.sleep(1.5)
        service.compact_log(sid)
    threading.Thread(target=rewrite, daemon=True).start()
    with client.stream("GET", f"/api/sessions/{sid}/stream", params={"from": size}) as r:
        body = ""
        for chunk in r.iter_text():
            body += chunk
            if "event: reset" in body:
                break
    assert "event: reset" in body


def test_meta_cache_follows_file_changes(client, topic):
    s = client.post("/api/sessions", json={"path": topic}).json()
    a = store.read_cached(s["id"])
    assert store.read_cached(s["id"]) is a                         # unchanged file: not parsed again
    store.update(s["id"], title="Changed")
    assert store.read_cached(s["id"])["title"] == "Changed"
    assert service.get_session(s["id"])["title"] == "Changed"
    store.remove(s["id"])
    assert store.read_cached(s["id"]) is None and service.get_session(s["id"]) is None
    service.list_sessions()
    assert not [k for k in store._cache if s["id"] in k]


def test_log_lines_with_fields_of_the_wrong_type_are_skipped():
    """A JSON object whose fields have odd types (a hand-edited or truncated log) is skipped, never a crash that
    would hide the whole session."""
    from maxxing.sessions.normalize import normalize_lines
    odd = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": 5}]}},
        {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": ["x"]}]}},
        {"type": "result", "usage": {"input_tokens": "x"}},
        {"type": "result", "modelUsage": {"m": 5}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": [{"type": "text", "text": 3}]}]}},
        {"type": "mx_user", "text": "x", "attachments": 5},
        {"type": "mx_done", "code": 1, "stderr": 5},
    ]
    good = {"type": "mx_user", "text": "still here"}
    out = normalize_lines([json.dumps(e) for e in odd] + [json.dumps(good)])
    assert out[-1]["type"] == "user" and out[-1]["text"] == "still here"


def test_log_lines_with_huge_numbers_or_deep_nesting_are_skipped():
    """1e999 is valid JSON (it reads as inf) and a deeply nested array cannot be read without a RecursionError:
    such a line is skipped like any other odd line, the session stays readable."""
    from maxxing.sessions.normalize import normalize_lines
    odd = ['{"type":"result","duration_ms":1e999}',
           '{"type":"result","usage":{"input_tokens":1e999}}',
           '{"type":"system","subtype":"task_progress","task_id":"t","usage":{"total_tokens":1e999}}',
           "[" * 100_000 + "]" * 100_000,
           '{"type":"mx_user","text":"x","attachments":' + "[" * 100_000 + "]" * 100_000 + '}']
    out = normalize_lines(odd + [json.dumps({"type": "mx_user", "text": "still here"})])
    assert [e["text"] for e in out] == ["still here"]


def _task_lines() -> str:
    """A background sub-agent as Claude Code logs it: Agent call, "launched" result, progress, notification."""
    t = "toolu_agent0001"
    return "".join([
        _line({"type": "mx_user", "text": "review it", "attachments": [], "source": "web", "at": 1.0}),
        _line({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": t, "name": "Agent", "input": {
            "description": "Review the diff", "prompt": "Review", "run_in_background": True}}]}, "mx_at": 2.0}),
        _line({"type": "system", "subtype": "task_started", "task_id": "a1", "tool_use_id": t, "task_type": "local_agent",
               "description": "Review the diff", "subagent_type": "general-purpose", "is_backgrounded": True,
               "prompt": "Review", "mx_at": 2.0}),
        _line({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": t,
                                                         "content": "Async agent launched successfully."}]}, "mx_at": 2.1}),
        *[_line({"type": "system", "subtype": "task_progress", "task_id": "a1", "tool_use_id": t,
                 "description": f"Running step {i}", "last_tool_name": "Bash", "subagent_type": "general-purpose",
                 "usage": {"total_tokens": 1000 * i, "tool_uses": i, "duration_ms": 100 * i}, "mx_at": 3.0 + i})
          for i in range(1, 51)],
        # a command run by the sub-agent itself: part of its work, not shown on its own
        _line({"type": "system", "subtype": "task_started", "task_id": "b9", "tool_use_id": "toolu_inner",
               "task_type": "local_bash", "description": "ls", "is_backgrounded": False, "owned_by_subagent": True,
               "mx_at": 4.0}),
        _line({"type": "system", "subtype": "task_updated", "task_id": "a1", "patch": {"status": "completed",
                                                                                     "end_time": 1}, "mx_at": 60.0}),
        _line({"type": "system", "subtype": "task_notification", "task_id": "a1", "tool_use_id": t,
               "status": "completed", "summary": "All good.", "usage": {"total_tokens": 51000, "tool_uses": 51,
                                                                       "duration_ms": 58000}, "mx_at": 60.0}),
        _line({"type": "result", "subtype": "success", "total_cost_usd": 0, "mx_at": 61.0}),
    ])


def test_background_tasks_become_task_events(client, topic):
    sid = _session_with_log(topic, _task_lines())
    evs = all_events(client, sid)
    tasks = [e for e in evs if e["type"] == "task"]
    assert all(e["id"] == "a1" for e in tasks)                       # the sub-agent's own command is dropped
    start = tasks[0]
    assert start["state"] == "running" and start["kind"] == "agent" and start["background"] is True
    assert start["tool_use_id"] == "toolu_agent0001" and start["description"] == "Review the diff"
    assert start["agent_type"] == "general-purpose" and "prompt" not in start
    prog = tasks[50]
    assert prog["activity"] == "Running step 50" and prog["last_tool"] == "Bash"
    assert (prog["tokens"], prog["tools"], prog["duration_ms"]) == (50000, 50, 5000)
    upd, end = tasks[-2], tasks[-1]
    assert upd["state"] == "completed" and "tool_use_id" not in upd
    assert end["state"] == "completed" and end["summary"] == "All good." and end["tokens"] == 51000
    # task events are not thread rows: `tail` still returns that many rows, the task events come on top
    r = client.get(f"/api/sessions/{sid}/events", params={"tail": 4}).json()
    rows = [e for e in r["events"] if e["type"] != "task"]
    assert len(rows) >= 4 and rows[0]["type"] == "user"
    assert len(r["events"]) > 50


def test_a_page_without_the_task_start_still_knows_the_agent(client, topic):
    t = "toolu_agent0002"
    head = _line({"type": "system", "subtype": "task_started", "task_id": "a2", "tool_use_id": t,
                  "task_type": "local_agent", "description": "Audit", "subagent_type": "Explore",
                  "is_backgrounded": True, "mx_at": 1.0})
    body = "".join(_turn_lines(i) for i in range(400))
    tail = _line({"type": "system", "subtype": "task_progress", "task_id": "a2", "tool_use_id": t,
                  "description": "Reading", "mx_at": 500.0})
    sid = _session_with_log(topic, head + body + tail + _turn_lines(400))
    r = client.get(f"/api/sessions/{sid}/events", params={"tail": 20}).json()
    assert r["more_before"] is True
    tasks = [e for e in r["events"] if e["type"] == "task"]
    assert len(tasks) == 1 and tasks[0]["activity"] == "Reading"
    assert (tasks[0]["kind"], tasks[0]["background"], tasks[0]["description"], tasks[0]["agent_type"]) == \
        ("agent", True, "Audit", "Explore")


def test_task_event_states_and_noise():
    n = service.normalize.normalize
    assert n({"type": "system", "subtype": "task_updated", "task_id": "x", "patch": {"status": "killed"}})[0]["state"] == "stopped"
    assert n({"type": "system", "subtype": "task_updated", "task_id": "x", "patch": {"is_backgrounded": True}})[0]["background"] is True
    assert n({"type": "system", "subtype": "task_updated", "task_id": "x", "patch": {"end_time": 3}}) == []
    assert n({"type": "system", "subtype": "task_started", "task_type": "local_bash"}) == []            # no task id
    bash = n({"type": "system", "subtype": "task_started", "task_id": "b", "task_type": "local_bash", "description": "npm ci"})[0]
    assert bash["kind"] == "shell" and bash["background"] is False
    big = n({"type": "system", "subtype": "task_notification", "task_id": "a", "status": "failed", "summary": "z" * 50_000})[0]
    assert big["state"] == "failed" and len(big["summary"]) < 20_100


def test_turn_with_background_agents_streams_their_state(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "AGENTS please"}).json()
    s = wait_idle(client, s["id"])
    assert s["state"] == "idle" and s["error"] is None
    tasks = [e for e in all_events(client, s["id"]) if e["type"] == "task"]
    last: dict[str, dict] = {}
    for e in tasks:
        last.setdefault(e["id"], {}).update(e)
    assert set(last) == {"a1", "a2", "b1"}
    assert {k: (v["kind"], v["state"]) for k, v in last.items()} == {
        "a1": ("agent", "completed"), "a2": ("agent", "completed"), "b1": ("shell", "completed")}
    assert last["a1"]["summary"].startswith("**Review done.**") and last["a1"]["tools"] >= 1
