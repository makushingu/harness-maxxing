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


def _own_turn_started_another(mx, sid: str) -> bool:
    raw = _raw(mx, sid)
    return any(e.get("subtype") == "task_started" and e.get("task_id") == "bg_two" for e in raw) \
        and sum(1 for e in raw if e["type"] == "result") == 2


@pytest.mark.parametrize("how", ["send", "steer", "inject"])
def test_a_message_reaches_the_process_whose_last_task_ended_and_which_started_another(client, topic, mx,
                                                                                      monkeypatch, how):
    """The last background task ends: Claude starts a turn by itself a moment later, and that turn may start new
    background work. Its input was closed in between: a message then waited for that work to end, "Add to plan"
    did nothing and a steer killed the whole process (the work with it)."""
    monkeypatch.setenv("FAKE_CLAUDE_BG_S_one", "1")
    monkeypatch.setenv("FAKE_CLAUDE_BG_THEN", "two")
    monkeypatch.setenv("FAKE_CLAUDE_BG_S_two", "6")
    sid = client.post("/api/sessions", json={"path": topic, "message": "BGTASK:one NOTOOL"}).json()["id"]
    wait_for(lambda: _own_turn_started_another(mx, sid), 15)
    assert client.get(f"/api/sessions/{sid}").json()["state"] == "running"           # the second task runs
    client.post(f"/api/sessions/{sid}/messages", json={"text": "status? NOTOOL"})
    if how == "steer":
        assert client.post(f"/api/sessions/{sid}/steer").json()["steered"] is True
    elif how == "inject":
        client.post(f"/api/sessions/{sid}/inject")
    wait_for(lambda: sum(1 for e in _raw(mx, sid) if e["type"] == "mx_user") == 2, 4)
    assert not (mx["fake_dir"] / "bg-two.done").exists()                             # answered while it still runs
    s = wait_idle(client, sid, 30)
    assert (mx["fake_dir"] / "bg-two.done").exists() and s["error"] is None and s["turns"] == 2
    assert [x.get("continued", False) for x in calls(mx)] == [False, True]           # ONE claude process
    evs = all_events(client, sid)
    assert not any(e["type"] == "note" and (e["text"] == "Stopped." or "could not be added" in e["text"])
                   for e in evs)
    assert [e["code"] for e in _raw(mx, sid) if e["type"] == "mx_done"] == [0, 0]


def test_the_process_ends_once_its_last_task_ended_and_claude_said_so(client, topic, mx, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_BG_S", "1")
    t0 = time.time()
    sid = client.post("/api/sessions", json={"path": topic, "message": "BGTASK:one NOTOOL"}).json()["id"]
    s = wait_idle(client, sid, 20)
    assert time.time() - t0 < 8 and s["error"] is None and s["turns"] == 1
    assert any("Background task one finished" in e["text"] for e in all_events(client, sid) if e["type"] == "assistant")


def _proc() -> runner_mod._Proc:
    return runner_mod._Proc(p=None, stdin=None, lines=iter(()), err_chunks=[], t_err=None)   # type: ignore[arg-type]


def test_the_result_of_a_turn_claude_started_itself_is_not_the_answer_to_the_prompt(monkeypatch):
    own = {"type": "result", "origin": {"kind": "task-notification"}, "num_turns": 0}
    init = {"type": "system", "subtype": "init"}
    monkeypatch.setattr(runner_mod, "TASK_SETTLE_S", 0.2)
    pr = _proc()
    pr.sent()
    for ev in (init, own):                               # a task the previous process left, told at the resume
        pr.track(ev)
    assert pr.turn_done is False and pr.settle() is False
    pr.track(init)
    pr.track({"type": "result"})
    assert pr.turn_done is True and pr.owed is False
    time.sleep(0.25)
    assert pr.settle() is True
    # no prompt waiting: Claude's own turn ends like any turn, the input closes once nothing else can start
    pr.track(init)
    pr.track(own)
    assert pr.turn_done is True and pr.settle() is False
    time.sleep(0.25)
    assert pr.settle() is True
    # the prompt was read inside Claude's own turn (no turn of its own follows): over after the wait, never stuck
    pr.sent()
    pr.track(own)
    assert pr.turn_done is False
    time.sleep(0.25)
    assert pr.settle() is True and pr.turn_done is True and pr.owed is False


def test_the_input_stays_open_a_moment_after_a_background_task_ended(monkeypatch):
    monkeypatch.setattr(runner_mod, "TASK_SETTLE_S", 0.2)
    pr = _proc()
    pr.sent()
    pr.track({"type": "system", "subtype": "task_started", "task_id": "t1", "is_backgrounded": True})
    pr.track({"type": "result"})
    time.sleep(0.25)
    assert pr.turn_done and pr.tasks == {"t1"} and pr.settle() is True
    pr.track({"type": "system", "subtype": "background_tasks_changed", "tasks": []})
    assert not pr.tasks and pr.settle() is False        # Claude is about to start a turn by itself
    pr.track({"type": "system", "subtype": "task_notification", "task_id": "other"})   # not one of its tasks
    time.sleep(0.25)
    assert pr.settle() is True
