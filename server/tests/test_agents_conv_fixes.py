"""The owner's conversation with an agent: Run now, messages that wait for a run in progress, silent agents on
Telegram, replies to group answers, long texts and the thread's trim, the text of a big turn."""
from __future__ import annotations

import json
import time

from conftest import wait_for, wait_idle
from test_agent_manager import _create, _say
from test_agents import A, _on, _results
from maxxing import agents
from maxxing.sessions import service, store


def _sid(r: dict) -> str:
    s = r["session"]
    return s if isinstance(s, str) else s["id"]


def _runs() -> list[dict]:
    return [m for m in agents.thread(A, 500) if m["kind"] == "run"]


# ---- Run now ------------------------------------------------------------------------------------------------
def test_run_now_starts_a_run_of_the_routine_not_a_message_of_the_conversation(client, topic, mx):
    _on(client)
    _create(client)
    chat = _sid(_say(client, "hi"))
    wait_idle(client, chat)
    r = client.post("/api/agents/acme/blog/writer/run", json={}).json()     # the Run now button: no text
    assert r["started"] and not r.get("continued")
    run = _sid(r)
    assert run != chat
    wait_idle(client, run)
    assert not agents.manager_turn(store.read(run))                       # the routine's rules, not the manager's
    assert agents._read_state(A)["chat"]["session"] == chat               # the conversation stays the same
    m = _runs()[-1]
    assert m["session"] == run and m["source"] == agents.RUN_NOW_SOURCE and not m.get("owner")
    # the next message of the owner goes on in the conversation
    assert _sid(_say(client, "and now?")) == chat


def test_words_on_the_page_still_go_into_the_conversation(client, topic, mx):
    _on(client)
    _create(client)
    chat = _sid(_say(client, "hi"))
    wait_idle(client, chat)
    r = _say(client, "run your routine please")                            # typed: a message, not the button
    assert r.get("continued") and _sid(r) == chat


# ---- the owner's message waits for the run that holds the budget -----------------------------------------------
def test_new_conversation_during_a_running_turn_the_next_message_waits_then_starts_a_new_one(client, topic, mx):
    _on(client)
    _create(client)                                                       # default budget: 2 $ a day
    old = _sid(_say(client, "SLOW long question"))
    wait_for(lambda: store.read(old).get("state") == "running")
    assert client.post("/api/agents/acme/blog/writer/chat/new").json() == {"ok": True}
    r = _say(client, "another subject")
    assert r == {"started": True, "waiting": True}                        # not refused busy
    waiting = _runs()[-1]
    assert waiting["owner"] and waiting["waiting"] and "session" not in waiting
    assert not [m for m in agents.thread(A) if m["kind"] == "skip"]
    client.post(f"/api/sessions/{old}/stop")
    wait_for(lambda: (next((m for m in _runs() if m["id"] == waiting["id"]), {}).get("session")))
    m = next(m for m in _runs() if m["id"] == waiting["id"])
    assert m["session"] != old and m.get("chat") == "new" and "waiting" not in m
    assert agents._read_state(A)["chat"]["session"] == m["session"]       # /new took effect for this message
    wait_idle(client, m["session"])
    assert agents.manager_turn(store.read(m["session"]))
    assert not agents._read_state(A).get("owner_wait")


def test_owner_message_waits_for_a_cron_run_then_goes_on_in_the_conversation(client, topic, mx):
    _on(client)
    _create(client)
    chat = _sid(_say(client, "hi"))
    wait_idle(client, chat)
    run = _sid(agents.fire(A, trigger="cron:c_1", prompt="SLOW routine", source="cron"))
    wait_for(lambda: store.read(run).get("state") == "running")
    assert _say(client, "quick question").get("waiting")
    # an automation keeps the hold rule: refused (or asked to try again), never queued behind the owner
    assert agents.fire(A, trigger="cron:c_2", prompt="other", source="cron") == {"started": False, "reason": "busy"}
    assert agents.fire(A, trigger="feed:t1", text="ev", source="shop", wait=True) == {"started": False,
                                                                                       "reason": "busy"}
    client.post(f"/api/sessions/{run}/stop")
    wait_for(lambda: _runs()[-1].get("session"))
    assert _runs()[-1]["session"] == chat
    wait_idle(client, chat)


def test_owner_messages_from_telegram_wait_too_and_start_in_order(client, topic, mx):
    _on(client)
    _create(client)
    run = _sid(agents.fire(A, trigger="cron:c_1", prompt="SLOW routine", source="cron"))
    wait_for(lambda: store.read(run).get("state") == "running")
    a = agents.fire(A, trigger="telegram", prompt="NOTOOL first", source="telegram")
    b = _say(client, "second")
    assert a.get("waiting") and b.get("waiting")
    ids = [m["id"] for m in _runs()[-2:]]
    client.post(f"/api/sessions/{run}/stop")
    wait_for(lambda: all(next(m for m in _runs() if m["id"] == i).get("session") for i in ids))
    first, second = (next(m for m in _runs() if m["id"] == i) for i in ids)
    assert first["session"] == second["session"]                          # one conversation, in that order
    assert first["source"] == "telegram" and first.get("chat") == "new" and not second.get("chat")
    wait_idle(client, first["session"])


def test_a_waiting_message_is_never_a_way_around_the_daily_budget(client, topic, mx, monkeypatch):
    _on(client)
    _create(client)
    monkeypatch.setattr(agents, "day_cost", lambda *a, **k: 99.0)
    r = _say(client, "hi")
    assert r == {"started": False, "reason": "budget"}
    assert not agents._read_state(A).get("owner_wait")


def test_waiting_messages_left_by_a_restart_start_from_the_loop(client, topic, mx, monkeypatch):
    _on(client)
    _create(client)
    st = agents._read_state(A)
    msg = agents.post(A, "run", "NOTOOL left", owner=True, waiting=True, trigger="manual", source="manual")
    st["owner_wait"] = [{"id": msg["id"], "trigger": "manual", "source": "manual", "prompt": "NOTOOL left",
                         "attachments": [], "reply_to": "", "model": "", "at": msg["at"]}]
    agents._write_state(A, st)
    agents._waiting.clear()
    monkeypatch.setattr(agents, "_waiting_seeded", False)                 # a restart: seeded from the state
    assert agents.flush_waiting() == 1
    m = next(m for m in _runs() if m["id"] == msg["id"])
    assert m.get("session") and "waiting" not in m
    wait_idle(client, m["session"])


# ---- silent agents still answer the owner on Telegram ------------------------------------------------------------
def test_a_silent_agent_answers_what_the_owner_asked_it_on_telegram(client, topic, mx, monkeypatch):
    from maxxing.telegram import gateway
    sent = []
    monkeypatch.setattr(gateway, "notify_agent", lambda path, text, **k: sent.append((text, k.get("silent"))))
    _on(client)
    _create(client, telegram=True, silent=True)
    sid = _sid(agents.fire(A, trigger="telegram", prompt="NOTOOL what time is it?", source="telegram"))
    wait_idle(client, sid)
    wait_for(lambda: sent, 10)
    assert sent[0][0].startswith("Echo: NOTOOL what time") and sent[0][1] is True     # without a sound
    # the same conversation from the page: answered on the page only
    sid2 = _sid(_say(client, "and from the page"))
    wait_idle(client, sid2)
    wait_for(lambda: len(_results(client)) >= 2, 10)
    time.sleep(0.5)
    assert len(sent) == 1
    # an automatic run of a silent agent: never on Telegram
    run = _sid(agents.fire(A, trigger="cron:c_1", prompt="NOTOOL routine", source="cron"))
    wait_idle(client, run)
    wait_for(lambda: len(_results(client)) >= 3, 10)
    time.sleep(0.5)
    assert len(sent) == 1


def test_a_loud_agent_still_sends_every_result(client, topic, mx, monkeypatch):
    from maxxing.telegram import gateway
    sent = []
    monkeypatch.setattr(gateway, "notify_agent", lambda path, text, **k: sent.append(k.get("silent")))
    _on(client)
    _create(client, telegram=True)
    run = _sid(agents.fire(A, trigger="cron:c_1", prompt="NOTOOL routine", source="cron"))
    wait_idle(client, run)
    wait_for(lambda: sent, 10)
    assert sent == [False]


# ---- Reply under a group answer in the member's own flow -------------------------------------------------------
def test_reply_to_a_group_answer_goes_into_the_private_conversation(client, topic, mx):
    from test_agent_groups import G, W, _idle, _setup
    from maxxing import agent_rooms
    _setup(client)
    client.post(f"{G}/messages", json={"text": "@writer go\nREPLY_AS writer: Draft ready"})
    _idle(client, 1)
    gsid = agent_rooms._read_state("projects/acme/groups/team")["sessions"][W]
    res = [m for m in agents.thread(W) if m["kind"] == "result" and m.get("session") == gsid]
    r = client.post("/api/agents/acme/blog/writer/run",
                    json={"text": "NOTOOL PRIVATE: my salary is 1234", "reply_to": res[-1]["id"]}).json()
    assert r["started"] and _sid(r) != gsid                              # never the group's session
    sid = _sid(r)
    wait_idle(client, sid)
    meta = store.read(sid)
    assert agents.manager_turn(meta) and not (meta.get("env") or {}).get("MAXXING_AGENT_GROUP")
    assert agents._read_state(W)["chat"]["session"] == sid
    first = service.last_user_message(sid) or {}
    assert "PRIVATE" in first.get("text", "") and "Draft ready" in first.get("text", "")   # the answer, as data
    run = [m for m in agents.thread(W) if m["kind"] == "run"][-1]
    assert run["session"] == sid and "reply_to" not in run


def test_reply_to_an_automation_result_still_goes_on_in_that_run(client, topic, mx):
    _on(client)
    _create(client)
    run = _sid(agents.fire(A, trigger="cron:c_1", prompt="NOTOOL routine", source="cron"))
    wait_idle(client, run)
    res = wait_for(lambda: [m for m in _results(client) if m["session"] == run])
    r = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL why?", "reply_to": res[-1]["id"]})
    assert r.json().get("continued") and _sid(r.json()) == run
    wait_idle(client, run)


# ---- long texts: marked, the conversation's kept whole ---------------------------------------------------------
def test_long_owner_message_and_answer_are_kept_and_an_automation_result_is_marked(client, topic, mx, monkeypatch):
    from maxxing.telegram import gateway
    sent = []
    monkeypatch.setattr(gateway, "notify_agent", lambda path, text, **k: sent.append(text))
    _on(client)
    _create(client, telegram=True)
    long_q = "NOTOOL " + "q" * 1500
    sid = _sid(client.post("/api/agents/acme/blog/writer/run", json={"text": long_q}).json())
    wait_idle(client, sid)
    own = _runs()[-1]
    assert own["text"] == long_q and "cut" not in own
    answer = "a" * 6000
    sid = _sid(_say(client, f"x\nREPLY_AS writer: {answer}"))
    wait_idle(client, sid)
    res = wait_for(lambda: [m for m in _results(client) if (m["text"] or "").startswith("aaa")])
    assert res[-1]["text"] == answer and "cut" not in res[-1]                # page = Telegram
    wait_for(lambda: answer in sent)
    run = _sid(agents.fire(A, trigger="cron:c_1", prompt=f"x\nREPLY_AS writer: {answer}", source="cron"))
    wait_idle(client, run)
    res = wait_for(lambda: [m for m in _results(client) if m["session"] == run])
    assert len(res[-1]["text"]) == agents.TEXT_MAX and res[-1]["cut"] == 6000   # marked, the run has it all


def test_post_marks_only_a_text_it_cut(mx):
    m = agents.post(A, "note", "short")
    assert "cut" not in m
    m = agents.post(A, "result", "b" * (agents.TEXT_MAX + 5))
    assert m["cut"] == agents.TEXT_MAX + 5 and len(m["text"]) == agents.TEXT_MAX
    m = agents.post(A, "result", "b" * (agents.CHAT_TEXT_MAX + 1), cap=agents.CHAT_TEXT_MAX)
    assert m["cut"] == agents.CHAT_TEXT_MAX + 1


# ---- the trim keeps the conversation apart from the automations ---------------------------------------------------
def test_a_busy_schedule_never_pushes_the_conversation_out_of_the_thread(mx, monkeypatch):
    monkeypatch.setattr(agents, "THREAD_KEEP", 10)
    monkeypatch.setattr(agents, "CHAT_KEEP", 10)
    agents._trimmed.clear()
    agents.post(A, "run", "hello agent", owner=True, session="s_chat", source="manual", trigger="manual")
    agents.post(A, "result", "hello owner", session="s_chat")
    for i in range(200):
        agents.post(A, "run", "", session=f"s_{i}", source="cron", trigger="cron:c_1")
        agents.post(A, "result", "r" * 800, session=f"s_{i}")
    msgs = agents.thread(A, 500)
    assert [m["text"] for m in msgs[:2]] == ["hello agent", "hello owner"]
    autos = [m for m in msgs if m.get("session") != "s_chat"]
    assert 10 <= len(autos) < 400                                          # the automations are trimmed
    assert autos[-1]["session"] == "s_199"


def test_the_conversation_has_its_own_cap(mx, monkeypatch):
    monkeypatch.setattr(agents, "THREAD_KEEP", 10)
    monkeypatch.setattr(agents, "CHAT_KEEP", 10)
    agents._trimmed.clear()
    for i in range(100):
        agents.post(A, "run", f"q{i} " + "w" * 400, owner=True, session="s_chat", source="manual", trigger="manual")
    msgs = agents.thread(A, 500)
    assert len(msgs) < 100 and msgs[-1]["text"].startswith("q99 ")


# ---- the text of a turn that wrote more than the tail read ------------------------------------------------------
def _big_turn(sid: str, at: float, answer: str, size: int) -> None:
    store.append_log(sid, {"type": "mx_user", "text": "read the reports", "at": at})
    big = "x" * 100_000
    for i in range(size // 100_000):
        store.append_log(sid, {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": big}]}})
    store.append_log(sid, {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": answer}]}})
    store.append_log(sid, {"type": "result", "subtype": "success", "result": answer})


def test_a_turn_bigger_than_the_tail_read_keeps_its_answer(client, topic, mx):
    _on(client)
    _create(client)
    sid = _sid(_say(client, "hi"))
    wait_idle(client, sid)
    at = store.read(sid)["last_turn"]["at"] + 5
    _big_turn(sid, at, "FINAL ANSWER after reading", 600_000)                # read again, further back
    assert service.ended_turn_text(sid, at) == "FINAL ANSWER after reading"
    _big_turn(sid, at + 5, "FINAL after a huge read", 4_500_000)              # past the bounded read: the tail
    assert service.ended_turn_text(sid, at + 5) == "FINAL after a huge read"


def test_a_big_turn_never_takes_the_answer_of_the_message_queued_after_it(client, topic, mx):
    _on(client)
    _create(client)
    sid = _sid(_say(client, "hi"))
    wait_idle(client, sid)
    at = store.read(sid)["last_turn"]["at"] + 5
    store.append_log(sid, {"type": "mx_user", "text": "big one", "at": at})
    store.append_log(sid, {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "ANSWER OF THE BIG ONE"}]}})
    big = "x" * 100_000
    for i in range(46):                                                     # 4.6 MB after its answer
        store.append_log(sid, {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": big}]}})
    store.append_log(sid, {"type": "mx_user", "text": "next", "at": at + 1})
    store.append_log(sid, {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "ANSWER OF THE NEXT ONE"}]}})
    # its own answer is out of every read: nothing, never the next message's answer
    assert service.ended_turn_text(sid, at) == ""
    assert service.ended_turn_text(sid, at + 1) == "ANSWER OF THE NEXT ONE"


def test_the_thread_rewrite_keeps_other_lines(mx):
    a = agents.post(A, "run", "one", owner=True, waiting=True)
    b = agents.post(A, "run", "two")
    agents._set_msg(A, a["id"], waiting=None, session="s_x")
    lines = [json.loads(ln) for ln in agents._state_file(A, "jsonl").read_text().splitlines()]
    assert [m["id"] for m in lines] == [a["id"], b["id"]]
    assert lines[0]["session"] == "s_x" and "waiting" not in lines[0] and lines[1] == b
