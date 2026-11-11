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


