"""Steer keeps Claude's background work: the steered message goes to the SAME claude process (stream-json input,
an `interrupt` control request), so background commands / sub-agents are never killed; Stop still kills all."""
from __future__ import annotations

import json
import time

import pytest

from maxxing.sessions import runner as runner_mod

from conftest import all_events, wait_for, wait_idle


def calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def _raw(mx, sid: str) -> list[dict]:
    from maxxing.sessions import store
    return [json.loads(x) for x in store.log_path(sid).read_text().splitlines() if x.strip()]


def _bg_started(mx, sid: str) -> bool:
    return any(e.get("subtype") == "task_started" for e in _raw(mx, sid))


def test_steer_keeps_the_background_task_and_continues_in_the_same_process(client, topic, mx, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_BG_S", "4")
    sid = client.post("/api/sessions", json={"path": topic, "message": "SLOW BGTASK:keep long job"}).json()["id"]
    wait_for(lambda: _bg_started(mx, sid), 10)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "also check X NOTOOL"})
    t0 = time.time()
    assert client.post(f"/api/sessions/{sid}/steer").json()["interrupted"] is True
    s = wait_idle(client, sid, 30)
    assert time.time() - t0 < 20                                                      # the SLOW step was cut short
    assert (mx["fake_dir"] / "bg-keep.done").exists()                                 # the background task finished
    assert s["state"] == "idle" and s["error"] is None and s["turns"] == 2
    c = calls(mx)
    assert [x.get("continued", False) for x in c] == [False, True]                   # ONE claude process
    evs = all_events(client, sid)
    assert [e["text"] for e in evs if e["type"] == "user"] == ["SLOW BGTASK:keep long job", "also check X NOTOOL"]
    note = [e["text"] for e in evs if e["type"] == "note" and e["text"].startswith("Interrupted")]
    assert note and "Background tasks keep running" in note[0]
    texts = [e["text"] for e in evs if e["type"] == "assistant"]
    assert any("interrupted your previous turn" in t for t in texts)                 # the steered message ran
    assert any("Background task keep finished" in t for t in texts)                  # and Claude's own follow-up
    # cost: the interrupted step cost nothing more; the steered turn + the follow-up = 2 x 0.0123
    assert s["cost_usd"] == pytest.approx(0.0246)
    raw = _raw(mx, sid)
    order = [e["type"] for e in raw if e["type"] in ("mx_user", "mx_done")]
    assert order == ["mx_user", "mx_done", "mx_user", "mx_done"]


def test_steer_while_only_background_tasks_run_just_adds_the_message(client, topic, mx, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_BG_S", "5")
    sid = client.post("/api/sessions", json={"path": topic, "message": "BGTASK:bg NOTOOL"}).json()["id"]
    wait_for(lambda: any(e["type"] == "result" for e in _raw(mx, sid)), 10)          # the turn answered...
    assert client.get(f"/api/sessions/{sid}").json()["state"] == "running"           # ...the task still runs
    client.post(f"/api/sessions/{sid}/messages", json={"text": "status? NOTOOL"})
    assert client.post(f"/api/sessions/{sid}/steer").json()["steered"] is True
    s = wait_idle(client, sid, 30)
    assert (mx["fake_dir"] / "bg-bg.done").exists() and s["error"] is None and s["turns"] == 2
    assert [x.get("continued", False) for x in calls(mx)] == [False, True]
    evs = all_events(client, sid)
    assert not any(e["type"] == "note" and e["text"] in ("Stopped.",) for e in evs)
    assert any("interrupted your previous turn" in e["text"] for e in evs if e["type"] == "assistant")


def test_steer_falls_back_to_killing_without_stream_input(client, topic, mx, monkeypatch):
    """Old way (stdin closed at once): the steer kills the turn, the background task with it."""
    monkeypatch.setenv("MAXXING_STREAM_INPUT", "0")
    monkeypatch.setenv("FAKE_CLAUDE_BG_S", "3")
    sid = client.post("/api/sessions", json={"path": topic, "message": "SLOW BGTASK:gone job"}).json()["id"]
    wait_for(lambda: _bg_started(mx, sid), 10)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "other NOTOOL"})
    assert client.post(f"/api/sessions/{sid}/steer").json()["interrupted"] is True
    s = wait_idle(client, sid, 20)
    assert s["error"] is None and s["turns"] == 2
    assert [x.get("continued", False) for x in calls(mx)] == [False, False]          # a new process
    time.sleep(3.5)
    assert not (mx["fake_dir"] / "bg-gone.done").exists()


def test_steer_step_kills_when_stdin_is_closed(monkeypatch):
    r = runner_mod.Runner("x" * 12)
    killed = []
    monkeypatch.setattr(r, "_kill_child", lambda: killed.append(1))

    class P:
        def poll(self):
            return None
    st = runner_mod._Stdin.__new__(runner_mod._Stdin)
    st.closed = True
    pr = runner_mod._Proc(p=P(), stdin=st, lines=iter(()), err_chunks=[], t_err=None)  # type: ignore[arg-type]
    r.steer_pending = True
    assert r._steer_step(pr) is False and killed and r.stop_flag.is_set() and not r.steer_pending


def test_stop_still_kills_the_background_task(client, topic, mx, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_BG_S", "3")
    sid = client.post("/api/sessions", json={"path": topic, "message": "SLOW BGTASK:stop job"}).json()["id"]
    wait_for(lambda: _bg_started(mx, sid), 10)
    client.post(f"/api/sessions/{sid}/stop")
    wait_idle(client, sid, 15)
    time.sleep(3.5)
    assert not (mx["fake_dir"] / "bg-stop.done").exists()


def test_a_turn_with_a_background_task_ends_when_the_task_does(client, topic, mx, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_BG_S", "2")
    sid = client.post("/api/sessions", json={"path": topic, "message": "BGTASK:wait NOTOOL"}).json()["id"]
    s = wait_idle(client, sid, 20)
    assert (mx["fake_dir"] / "bg-wait.done").exists() and s["turns"] == 1 and s["error"] is None
    assert any("Background task wait finished" in e["text"] for e in all_events(client, sid) if e["type"] == "assistant")
    s2 = client.post("/api/sessions", json={"path": topic, "message": "plain NOTOOL"}).json()["id"]
    t0 = time.time()
    assert wait_idle(client, s2, 10)["error"] is None and time.time() - t0 < 8        # no background: exits at once


def test_no_hang_when_claude_exits_without_a_result(client, topic):
    sid = client.post("/api/sessions", json={"path": topic, "message": "NORESULT"}).json()["id"]
    s = wait_idle(client, sid, 15)
    assert s["state"] == "error" or s["error"] is not None or s["turns"] == 1


def test_a_message_sent_while_only_background_tasks_run_is_answered_at_once(client, topic, mx, monkeypatch):
    """A background command that never ends (a dev server) no longer holds the next message in the queue."""
    monkeypatch.setenv("FAKE_CLAUDE_BG_S", "60")
    sid = client.post("/api/sessions", json={"path": topic, "message": "BGTASK:dev NOTOOL"}).json()["id"]
    wait_for(lambda: any(e["type"] == "result" for e in _raw(mx, sid)), 10)          # answered, the task runs on
    t0 = time.time()
    client.post(f"/api/sessions/{sid}/messages", json={"text": "next one NOTOOL"})
    wait_for(lambda: [e["type"] for e in _raw(mx, sid) if e["type"] in ("mx_user", "mx_done", "result")]
             == ["mx_user", "result", "mx_done", "mx_user", "result"], 10)
    assert time.time() - t0 < 10
    assert [x.get("continued", False) for x in calls(mx)] == [False, True]           # the same process
    assert not (mx["fake_dir"] / "bg-dev.done").exists()                              # the task still runs
    evs = all_events(client, sid)
    assert not any(e["type"] == "note" for e in evs)
    assert not any("interrupted your previous turn" in e["text"] for e in evs if e["type"] == "assistant")
    assert [bool(e.get("same")) for e in evs if e["type"] == "init"] == [False, True]   # the page keeps the task
    client.post(f"/api/sessions/{sid}/stop")
    assert wait_idle(client, sid, 20)["turns"] == 2


def test_a_message_after_a_settings_change_starts_a_new_process(client, topic, mx, monkeypatch):
    """A message sent while only a background task runs joins that process, unless Plan mode, the model or the
    permissions changed in between: the old process would run it with the old settings."""
    from maxxing.sessions import store
    monkeypatch.setenv("FAKE_CLAUDE_BG_S", "6")
    sid = client.post("/api/sessions", json={"path": topic, "message": "BGTASK:bg NOTOOL"}).json()["id"]
    wait_for(lambda: any(e["type"] == "result" for e in _raw(mx, sid)), 10)
    store.update(sid, plan_mode=True, model="other-model")
    client.post(f"/api/sessions/{sid}/messages", json={"text": "edit files NOTOOL"})
    wait_idle(client, sid, 30)
    c = calls(mx)
    assert [x.get("continued", False) for x in c] == [False, False]
    assert "other-model" in c[1]["argv"]
    assert not any(e.get("same") for e in all_events(client, sid) if e["type"] == "init")   # the task was cut
