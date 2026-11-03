"""Agents on Telegram (option `telegram`): one permanent thread per agent, through the fake Bot API."""
from __future__ import annotations

import asyncio
import sys

import httpx
import pytest

from _conn_helpers import (TG_TOKEN, FakeService, FakeTelegram, FakeWorkspace, bare_app,  # noqa: F401
                           mx_state, wait_for)
from maxxing import agents, config, workspace as real_workspace
from maxxing.api import telegram as tg_api
from maxxing.sessions import service as real_service, store as real_store, titles  # noqa: F401 - before the fakes
from maxxing.telegram import gateway

TOPIC = "projects/acme/topics/blog"
A = TOPIC + "/agents/writer"


@pytest.fixture
def tg(mx_state, monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setenv("MAXXING_TELEGRAM_API", fake.url)
    yield fake
    fake.close()


@pytest.fixture
def svc(monkeypatch):
    s = FakeService()
    monkeypatch.setitem(sys.modules, "maxxing.sessions.service", s)
    return s


@pytest.fixture
def ws(mx_state, monkeypatch):
    w = FakeWorkspace(mx_state / "ws", [("acme", "blog")])
    monkeypatch.setitem(sys.modules, "maxxing.workspace", w)
    return w


@pytest.fixture
def fired(monkeypatch):
    """The agent `writer` (display name "Writer"); agents.fire recorded, its answer set by the test."""
    class Calls(list):
        answer: dict
    calls = Calls()
    answer = {"started": True, "session": {"id": "s1"}}
    monkeypatch.setattr(agents, "load", lambda path: {"name": "Writer"})
    monkeypatch.setattr(agents, "exists", lambda path: path == A)
    monkeypatch.setattr(agents, "fire", lambda path, **k: calls.append({"path": path, **k}) or dict(answer))
    calls.answer = answer
    return calls


@pytest.fixture
async def api(tg, svc, ws, fired, monkeypatch):
    monkeypatch.setattr(gateway, "_hooks", False)
    app = bare_app(tg_api.router)
    await tg_api.startup()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await tg_api.shutdown()


async def _link(api, tg) -> None:
    assert (await api.post("/api/telegram/token", json={"token": TG_TOKEN})).status_code == 200
    link = (await api.post("/api/telegram/link")).json()
    tg.message(f"/start {link['code']}")
    await wait_for(lambda: gateway.link_status()["linked"], what="link")
    await wait_for(lambda: len(gateway.tg_config()["threads"]) == 3, what="threads")


async def test_result_goes_to_the_agent_thread_created_once(api, tg):
    await _link(api, tg)
    await asyncio.to_thread(gateway.notify_agent, A, "**Post written.**")
    tid = gateway.agent_threads()[A]["tid"]
    assert tg.topics[tid] == "🤖 Writer · acme/blog"
    msgs = [p for p in tg.sent() if p.get("message_thread_id") == tid]
    assert "posts its results here" in msgs[0]["text"] and msgs[-1]["text"] == "<b>Post written.</b>"
    # from the event loop itself: never blocks, same thread reused
    gateway.notify_agent(A, "Second", ok=False)
    await wait_for(lambda: tg.sent()[-1]["text"] == "⚠️ Second", what="loop-safe agent notify")
    assert tg.sent()[-1]["message_thread_id"] == tid and len(tg.sent("createForumTopic")) == 4   # 3 specials + 1
    # the session sync never deletes it
    assert (await api.post("/api/telegram/sync")).status_code == 200
    assert gateway.agent_threads()[A]["tid"] == tid and not tg.sent("deleteForumTopic")


async def test_a_message_in_the_agent_thread_starts_it(api, tg, fired):
    await _link(api, tg)
    await asyncio.to_thread(gateway.notify_agent, A, "hello")
    tid = gateway.agent_threads()[A]["tid"]
    tg.message("Write about the launch", thread=tid)
    await wait_for(lambda: fired, what="fire")
    f = fired[0]
    assert f["path"] == A and f["trigger"] == "telegram" and f["source"] == "telegram"
    assert f["prompt"] == "Write about the launch" and not f.get("text")   # the user's words: a task, not data
    await wait_for(lambda: tg.sent()[-1]["text"] == "⏳ Writer is on it.", what="started reply")
    # a guard says no: the reason is the answer
    fired.answer.clear()
    fired.answer.update({"started": False, "reason": "budget"})
    tg.message("again", thread=tid)
    await wait_for(lambda: "did not start" in tg.sent()[-1]["text"], what="skip reply")
    assert "daily budget" in tg.sent()[-1]["text"]
    # commands are not for agents
    tg.message("/stop", thread=tid)
    await wait_for(lambda: "Commands work in session threads" in tg.sent()[-1]["text"], what="command reply")
    assert len(fired) == 2


async def test_threads_off_main_chat_with_the_agent_name(api, tg):
    await _link(api, tg)
    gateway.update_state(topics_enabled=False)
    await asyncio.to_thread(gateway.notify_agent, A, "Done")
    p = tg.sent()[-1]
    assert p.get("message_thread_id") is None and p["text"] == "🤖 <b>Writer</b>\nDone"
    assert A not in gateway.agent_threads()


async def test_deleted_by_hand_then_dropped_with_the_agent(api, tg):
    await _link(api, tg)
    await asyncio.to_thread(gateway.notify_agent, A, "one")
    tid = gateway.agent_threads()[A]["tid"]
    tg.topics.pop(tid)                                           # the user deleted the thread
    await asyncio.to_thread(gateway.notify_agent, A, "two")
    assert tg.sent()[-1]["text"] == "two" and tg.sent()[-1].get("message_thread_id") is None
    assert A not in gateway.agent_threads()                      # forgotten: the next message makes a new one
    await asyncio.to_thread(gateway.notify_agent, A, "three")
    new = gateway.agent_threads()[A]["tid"]
    assert new != tid and tg.sent()[-1]["message_thread_id"] == new
    await asyncio.to_thread(gateway.drop_agent_thread, A, True)
    assert A not in gateway.agent_threads() and tg.sent("deleteForumTopic")[-1]["message_thread_id"] == new


def test_topic_rename_remaps_the_agent_thread(mx_state):
    gateway.mutate_tg(lambda t: t.__setitem__("agent_threads", {A: {"tid": 42, "name": "x"}}))
    real_workspace._remap_telegram(TOPIC, "projects/acme/topics/news")
    assert gateway.agent_threads() == {"projects/acme/topics/news/agents/writer": {"tid": 42, "name": "x"}}
    assert config.load_config()["telegram"]["agent_threads"]
