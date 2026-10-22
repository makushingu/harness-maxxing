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
