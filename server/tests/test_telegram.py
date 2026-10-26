"""Telegram gateway tests - everything runs against a local fake Bot API (no network)."""
from __future__ import annotations

import asyncio
import json
import re
import sys
import threading
import time

import httpx
import pytest

from _conn_helpers import (TG_TOKEN, FakeService, FakeTelegram, FakeWorkspace, bare_app,  # noqa: F401
                           mx_state, wait_for)
from maxxing import config
from maxxing.api import telegram as tg_api
from maxxing.sessions import service as real_service, store as real_store  # before the fakes
from maxxing.telegram import format as fmt
from maxxing.telegram import gateway

TOPIC = "projects/acme/topics/blog"


# =============================================================================================
# Formatting
# =============================================================================================
def test_inline_formatting():
    html = fmt.to_html("**bold** *it* _it2_ ~~gone~~ `a<b>` [site](https://example.com) x < y & z")
    assert "<b>bold</b>" in html and "<i>it</i>" in html and "<i>it2</i>" in html
    assert "<s>gone</s>" in html
    assert "<code>a&lt;b&gt;</code>" in html
    assert '<a href="https://example.com">site</a>' in html
    assert "x &lt; y &amp; z" in html


def test_snake_case_and_unsafe_links_untouched():
    html = fmt.to_html("call my_function_name and [x](javascript:alert(1))")
    assert "my_function_name" in html and "<i>" not in html
    assert "href" not in html


def test_blocks():
    md = "# Title\n\nText\n\n```python\nif a < b:\n    print('**no**')\n```\n\n- one\n- two\n1. first\n\n> quoted\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    html = fmt.to_html(md)
    assert html.startswith("<b>Title</b>")
    assert '<pre><code class="language-python">if a &lt; b:\n    print(\'**no**\')</code></pre>' in html
    assert "• one\n• two\n1. first" in html
    assert "<blockquote>quoted</blockquote>" in html
    assert "• <b>1</b>\n   <i>b</i>: 2" in html and "|" not in html          # tables become lists


def _balanced(h: str) -> bool:
    for tag in ("b", "i", "pre", "code", "blockquote", "a", "s"):
        if len(re.findall(rf"<{tag}[ >]", h)) != h.count(f"</{tag}>"):
            return False
    return True


def _nested(h: str) -> bool:
    """Every closing tag closes the last open one (Telegram refuses crossed tags)."""
    stack: list[str] = []
    for close, tag in re.findall(r"<(/?)([a-z]+)[^>]*>", h):
        if not close:
            stack.append(tag)
        elif not stack or stack.pop() != tag:
            return False
    return not stack


def test_crossing_emphasis_gives_balanced_html():
    for md, want in (("**a *b** c*", "<b>a <i>b</i></b><i> c</i>"),
                     ("*a **b* c**", "<i>a <b>b</b></i><b> c</b>"),
                     ("~~a **b~~ c**", "<s>a <b>b</b></s><b> c</b>")):
        html = fmt.to_html(md)
        assert _nested(html), html
        assert html == want


def test_split_long_text_and_code():
    para = "word " * 300                                  # ~1500 chars
    code = "\n".join(f"line {i} <x> & y" for i in range(600))
    md = f"{para}\n\n{para}\n\n{para}\n\n```js\n{code}\n```\n\nend **done**"
    parts = fmt.render(md)
    assert len(parts) >= 4
    assert all(len(p) <= 4096 for p in parts)
    assert all(_balanced(p) for p in parts)
    assert sum(p.count('<code class="language-js">') for p in parts) >= 2   # code re-opened per part
    assert parts[-1].endswith("end <b>done</b>")


def test_split_monster_line_and_plain():
    parts = fmt.render("&" * 20000)
    assert all(len(p) <= 4096 for p in parts) and "".join(parts).count("&amp;") == 20000
    pl = fmt.plain("a<b\n" * 3000)
    assert all(len(p) <= 4096 for p in pl) and "a&lt;b" in pl[0]


# =============================================================================================
# Fixtures
# =============================================================================================
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
async def api(tg, svc, ws, monkeypatch):
    """The Telegram router on a bare app (auth bypassed) + hooks installed; gateway stopped after."""
    monkeypatch.setattr(gateway, "_hooks", False)
    app = bare_app(tg_api.router)
    await tg_api.startup()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await tg_api.shutdown()


async def _link(api, tg) -> None:
    r = await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    assert r.status_code == 200, r.text
    assert r.json()["bot"]["username"] == "maxxing_test_bot"
    r = await api.post("/api/telegram/link")
    link = r.json()
    assert link["deep_link"] == f"https://t.me/maxxing_test_bot?start={link['code']}"
    assert gateway.status()["running"] and gateway.status()["linking"]
    tg.message(f"/start {link['code']}")
    await wait_for(lambda: gateway.link_status()["linked"], what="link")
    await wait_for(lambda: len(gateway.tg_config()["threads"]) == 3, what="threads")      # Crons, Alerts, Notifications


def _thread(key: str) -> int:
    return gateway.tg_config()["threads"][key]


async def _open(api, svc, title: str = "Plan", path: str = TOPIC) -> tuple[str, int]:
    """A web session -> the sync gives it a thread. Returns (session id, thread id)."""
    sid = svc.create_session(path, title=title, source="web")["id"]
    assert (await api.post("/api/telegram/sync")).status_code == 200
    tid = gateway.thread_of(sid)
    assert tid, gateway.tg_config()
    return sid, tid


# =============================================================================================
# Setup flow
# =============================================================================================
async def test_token_rejected(api, tg):
    r = await api.post("/api/telegram/token", json={"token": "not a token"})
    assert r.status_code == 400 and r.json()["error"] == "bad_token"
    r = await api.post("/api/telegram/token", json={"token": "123456789:" + "x" * 35})
    assert r.status_code == 400 and "rejected" in r.json()["message"]
    assert config.get_secret("telegram_token") == ""


async def test_webhook_bot_refused(api, tg):
    tg.webhook = "https://elsewhere.example.com/hook"
    r = await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    assert r.status_code == 400 and "webhook" in r.json()["message"]


async def test_link_flow_and_threads(api, tg):
    st = (await api.get("/api/telegram")).json()
    assert st["configured"] is False and st["running"] is False
    await _link(api, tg)
    tg_cfg = gateway.tg_config()
    assert tg_cfg["chat_id"] == 555 and tg_cfg["user_ids"] == [555] and tg_cfg["chat_title"] == "Ada"
    names = [p["name"] for m, p in tg.calls if m == "createForumTopic"]
    assert names == ["Crons", "Alerts", "Notifications"]      # no session yet: no session thread
    st = (await api.get("/api/telegram")).json()
    assert st["chat"]["id"] == 555 and st["topics_enabled"] is True and st["running"] is True
    assert [t["path"] for t in st["threads"]] == ["#alerts", "#crons", "#feed"]
    assert st["settings"]["thread_days"] == 30
    assert any(m == "setMyCommands" for m, _ in tg.calls)
    assert (await api.get("/api/telegram/link")).json()["linked"] is True
    # offset persisted
    assert config.read_json(config.state_dir("telegram") / "offset.json")["offset"] >= 2
    # sync again creates nothing
    assert (await api.post("/api/telegram/sync")).json()["created"] == 0



async def test_non_ascii_link_code_from_stranger_is_refused_not_crashing(api, tg, svc, caplog):
    # while a link code is pending, `/start é` from a stranger gets the normal refusal (no TypeError from
    # hmac.compare_digest on a non-ASCII str)
    await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    await api.post("/api/telegram/link")
    tg.message("/start é", chat_id=777, user_id=777)
    await wait_for(lambda: [p for p in tg.sent() if p["chat_id"] == 777], what="refusal")
    assert not [r for r in caplog.records if r.getMessage() == "telegram update failed"]
    assert not gateway.link_status()["linked"]

async def test_wrong_code_and_strangers_refused_once(api, tg, svc):
    await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    await api.post("/api/telegram/link")
    tg.message("/start WRONGCODE", chat_id=777, user_id=777)
    tg.message("hello", chat_id=777, user_id=777)
    await wait_for(lambda: tg.sent(), what="refusal")
    await asyncio.sleep(0.3)
    refusals = [p for p in tg.sent() if p["chat_id"] == 777]
    assert len(refusals) == 1 and "private" in refusals[0]["text"]
    assert not gateway.link_status()["linked"] and not svc.sent


async def test_open_sessions_mirror_the_web_ui(api, tg, svc, ws):
    """One thread per open human session: created, renamed, deleted on archive, recreated on un-archive."""
    await _link(api, tg)
    config.update_config(public_url="https://ui.example.com")
    sid, tid = await _open(api, svc, "Refactor")
    assert tg.topics[tid] == "acme/blog · Refactor"
    intro = next(p for p in tg.sent() if p.get("message_thread_id") == tid)
    assert "Refactor" in intro["text"] and intro["disable_notification"]
    assert f"https://ui.example.com/sessions/{sid}" in intro["text"]
    cron = svc.create_session(TOPIC, title="Nightly", source="cron", cron=True)["id"]
    old = svc.create_session(TOPIC, title="Old")["id"]
    svc.sessions[old]["updated"] -= 40 * 86400
    gone = svc.create_session(TOPIC, title="Done")["id"]
    svc.sessions[gone]["archived"] = True
    await api.post("/api/telegram/sync")
    assert set(gateway.session_threads()) == {sid}            # no cron, no idle > 30 days, no archived
    # renamed in the UI -> renamed thread
    svc.sessions[sid]["title"] = "Refactor the API"
    await api.post("/api/telegram/sync")
    assert tg.topics[tid] == "acme/blog · Refactor the API"
    # a longer window brings the old one back
    assert (await api.put("/api/telegram/settings", json={"thread_days": 60})).status_code == 200
    await api.post("/api/telegram/sync")
    assert set(gateway.session_threads()) == {sid, old}
    # archived in the UI -> its thread is deleted, the data stays
    svc.sessions[sid]["archived"] = True
    r = (await api.post("/api/telegram/sync")).json()
    assert r["deleted"] == 1 and tid not in tg.topics and sid not in gateway.session_threads()
    assert sid in svc.sessions
    svc.sessions[sid]["archived"] = False                     # un-archived -> a new thread
    await api.post("/api/telegram/sync")
    assert gateway.thread_of(sid) and gateway.thread_of(sid) != tid
    assert cron not in gateway.session_threads()
    st = (await api.get("/api/telegram")).json()
    assert {t.get("session_id") for t in st["threads"]} >= {sid, old}


async def test_renamed_thread_is_announced_once(api, tg, svc, monkeypatch):
    """A rename changes a session's thread link: the UI hears "workspace"; a sync with nothing new stays quiet."""
    await _link(api, tg)
    sid, tid = await _open(api, svc, "Refactor")
    seen: list[tuple] = []
    monkeypatch.setattr(gateway.bus, "invalidate", lambda *t: seen.append(t))
    await api.post("/api/telegram/sync")
    assert not any("workspace" in t for t in seen)
    svc.sessions[sid]["title"] = "Refactor the API"
    await api.post("/api/telegram/sync")
    assert tg.topics[tid] == "acme/blog · Refactor the API" and any("workspace" in t for t in seen)


async def test_deleted_thread_comes_back_when_the_session_is_used(api, tg, svc):
    """Telegram does not tell bots about a deleted thread: the session stays open and gets a new thread
    the next time the bot writes for it (no probing: it would post service messages)."""
    await _link(api, tg)
    await api.put("/api/telegram/settings", json={"mirror_web": True})
    sid, tid = await _open(api, svc)
    tg.topics.pop(tid)                                        # the user deletes the thread in Telegram
    n_edits = len(tg.sent("editForumTopic"))
    assert (await api.post("/api/telegram/sync")).json()["created"] == 0
    assert len(tg.sent("editForumTopic")) == n_edits
    # the user writes in the web UI -> the mirrored turn reopens a thread
    svc.send_message(sid, "still there?", source="web")
    svc.finish(sid, "yes")
    await wait_for(lambda: gateway.thread_of(sid) not in (None, tid), what="reopened")
    new = gateway.thread_of(sid)
    await wait_for(lambda: any(p.get("message_thread_id") == new and p["text"] == "yes" for p in tg.sent()), what="answer")
    assert svc.sessions[sid]["archived"] is False
    # a rename that finds the thread deleted also reopens it
    tg.topics.pop(new)
    svc.sessions[sid]["title"] = "Renamed"
    await api.post("/api/telegram/sync")
    assert gateway.thread_of(sid) not in (None, new) and tg.topics[gateway.thread_of(sid)] == "acme/blog · Renamed"


async def test_web_turns_are_mirrored(api, tg, svc):
    await _link(api, tg)
    assert (await api.get("/api/telegram")).json()["settings"]["mirror_web"] is False      # opt-in
    config.update_config(telegram={"mirror_web": True})                                     # a5 default, not a choice
    assert gateway.status()["settings"]["mirror_web"] is False
    await api.put("/api/telegram/settings", json={"mirror_web": True})
    sid, tid = await _open(api, svc)
    svc.send_message(sid, "Plan the <launch>", source="web")
    svc.finish(sid, "Here is **the plan**")
    await wait_for(lambda: any(p["text"] == "<b>Here is the plan</b>" or "the plan</b>" in p["text"] for p in tg.sent()),
                   what="mirrored answer")
    mine = [p for p in tg.sent() if p.get("message_thread_id") == tid]
    assert mine[-2]["text"] == "🖥 <i>Plan the &lt;launch&gt;</i>" and mine[-2]["disable_notification"]
    assert "<b>the plan</b>" in mine[-1]["text"] and mine[-1]["disable_notification"]    # silent: Notify off
    # mirror off -> nothing (Notify off)
    await api.put("/api/telegram/settings", json={"mirror_web": False})
    n = len(tg.sent())
    svc.send_message(sid, "again", source="web")
    svc.finish(sid, "quiet")
    await asyncio.sleep(0.3)
    assert len(tg.sent()) == n


async def test_migration_from_topic_threads(api, tg, svc):
    """2.0.0a4 layout (one thread per topic + General): the topic's Telegram session keeps its thread."""
    await _link(api, tg)
    sid = svc.create_session(TOPIC, title="Telegram", source="telegram")["id"]
    # The new session wakes the background sync (its own loop): let it finish (same lock as /sync) so it
    # cannot write a thread for the session after the legacy layout below is in place.
    await api.post("/api/telegram/sync")
    stray = gateway.thread_of(sid)
    if stray:
        tg.topics.pop(stray, None)
    tg.topics.update({50: "General", 51: "acme / blog"})

    def legacy(t: dict) -> None:
        t["threads"].update({"": 50, TOPIC: 51})
        t["sessions"] = {TOPIC: sid}
        t["session_threads"] = {}            # the a4 layout had no session threads
    gateway.mutate_tg(legacy)
    await api.post("/api/telegram/sync")
    assert gateway.thread_of(sid) == 51 and tg.topics[51] == "acme/blog · Telegram"
    assert 50 not in tg.topics                                # General is gone: the main chat replaces it
    assert set(gateway.tg_config()["threads"]) == {"#crons", "#alerts", "#feed"}


async def test_new_session_from_the_main_chat(api, tg, svc, monkeypatch):
    await _link(api, tg)
    tg.message("Write a plan for the launch")
    await wait_for(lambda: any(p.get("reply_markup") for p in tg.sent()), what="where?")
    q = next(p for p in tg.sent() if p.get("reply_markup"))
    assert q["text"] == "Where should this session live?" and q.get("message_thread_id") is None
    buttons = [r[0] for r in q["reply_markup"]["inline_keyboard"]]
    assert buttons[0]["text"] == "General" and any(b["text"] == "acme / blog" for b in buttons)
    assert not svc.sent                                       # kept until the topic is chosen
    tg.callback(f"w:0:{gateway._path_hash(TOPIC)}")
    await wait_for(lambda: svc.sent, what="session created")
    sid = svc.sent[0]["sid"]
    s = svc.sessions[sid]
    assert s["path"] == TOPIC and s["source"] == "telegram" and s["title"] == "Write a plan for the launch"
    assert svc.auto_titles == [sid]                           # made from the message: shortened by the server
    tid = gateway.thread_of(sid)
    assert tid and tg.topics[tid] == "acme/blog · Write a plan for the launch"
    assert any(p.get("message_thread_id") == tid and "Write a plan" in p["text"] for p in tg.sent())   # quoted
    edits = [p["text"] for p in tg.sent("editMessageText")]
    assert any("continue in the thread" in e for e in edits)
    n = len(tg.sent())
    svc.finish(sid, "Here is the plan")
    await wait_for(lambda: len(tg.sent()) > n, what="reply")
    assert tg.sent()[-1]["message_thread_id"] == tid and tg.sent()[-1]["text"] == "Here is the plan"
    svc.sessions[sid]["title"] = "Launch plan"               # the short title arrives: the thread follows
    from maxxing import bus
    monkeypatch.setattr(bus, "_loop", asyncio.get_running_loop())   # bound by the full app at startup
    monkeypatch.setattr(gateway, "SYNC_DEBOUNCE", 0.2)
    bus.invalidate("sessions")
    await wait_for(lambda: tg.topics[tid] == "acme/blog · Launch plan", timeout=gateway.SYNC_DEBOUNCE + 10,
                   what="thread renamed")


async def test_new_session_from_a_thread_the_user_created(api, tg, svc):
    await _link(api, tg)
    tid = tg.user_thread("Coffee ideas")
    await wait_for(lambda: any(p.get("reply_markup") and p.get("message_thread_id") == tid for p in tg.sent()),
                   what="where? in the new thread")
    tg.message("first idea", thread=tid)
    await asyncio.sleep(0.2)
    assert not svc.sent
    tg.callback(f"w:{tid}:{gateway._path_hash(TOPIC)}", thread=tid)
    await wait_for(lambda: svc.sent, what="session")
    sid = svc.sent[0]["sid"]
    assert svc.sent[0]["text"] == "first idea" and svc.sessions[sid]["title"] == "Coffee ideas"
    assert svc.auto_titles == []                              # the thread's name is the user's title
    assert gateway.thread_of(sid) == tid and tg.topics[tid] == "acme/blog · Coffee ideas"
    tg.message("second idea", thread=tid)                     # now a normal session thread
    await wait_for(lambda: len(svc.sent) == 2, what="second")
    assert svc.sent[1]["sid"] == sid


async def test_new_session_defaults_when_unanswered(api, tg, svc, monkeypatch):
    monkeypatch.setattr(gateway, "NEW_WAIT", 0.2)
    await _link(api, tg)
    tg.message("quick note")
    await wait_for(lambda: svc.sent, what="default topic")
    sid = svc.sent[0]["sid"]
    assert svc.sessions[sid]["path"] == "" and gateway.thread_of(sid)
    assert any("no answer" in p["text"] for p in tg.sent("editMessageText"))


async def test_topics_disabled_fallback(api, tg, svc):
    tg.topics_enabled = False
    await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    code = (await api.post("/api/telegram/link")).json()["code"]
    tg.message(f"/start {code}")
    await wait_for(lambda: gateway.load_state().get("topics_enabled") is False, what="fallback")
    st = gateway.status()
    assert st["topics_enabled"] is False and "BotFather" in st["last_error"] and st["threads"] == []
    # the main chat talks to the workspace root
    tg.message("hi from the main chat")
    await wait_for(lambda: svc.sent, what="message")
    sid = svc.sent[0]["sid"]
    assert svc.sessions[sid]["path"] == "" and svc.sessions[sid]["source"] == "telegram"
    # /topic switches the main chat to a topic
    tg.callback(f"t:{gateway._path_hash(TOPIC)}")
    await wait_for(lambda: gateway.load_state().get("fallback_path") == TOPIC, what="topic switch")
    tg.message("now in blog")
    await wait_for(lambda: len(svc.sent) == 2, what="second message")
    blog = svc.sent[1]["sid"]
    assert svc.sessions[blog]["path"] == TOPIC
    # /new + /sessions + switching back
    tg.message("/new Research")
    await wait_for(lambda: gateway.tg_config()["sessions"][TOPIC] != blog, what="/new")
    tg.message("/sessions")
    await wait_for(lambda: any(p.get("reply_markup") for p in tg.sent()), what="/sessions")
    tg.callback(f"s:{blog}")
    await wait_for(lambda: gateway.tg_config()["sessions"][TOPIC] == blog, what="switch")
    # notifications go to the main chat (no thread)
    gateway.notify_cron("cron ok")
    await wait_for(lambda: any(p["text"] == "cron ok" for p in tg.sent()), what="cron notify")
    assert next(p for p in tg.sent() if p["text"] == "cron ok").get("message_thread_id") is None


# =============================================================================================
# Conversation
# =============================================================================================
async def test_message_to_session_and_reply(api, tg, svc):
    await _link(api, tg)
    web_sid, thread = await _open(api, svc)
    tg.message("Write **a** plan", thread=thread)
    await wait_for(lambda: svc.sent, what="send_message")
    sent = svc.sent[0]
    assert sent["text"] == "Write **a** plan" and sent["source"] == "telegram"
    sid = sent["sid"]
    assert sid == web_sid                                     # the thread IS the web session
    await wait_for(lambda: any(p.get("message_thread_id") == thread for p in tg.sent("sendChatAction")),
                   what="typing")
    n = len(tg.sent())
    svc.finish(sid, "Here is **the plan**:\n\n```py\nx = 1 < 2\n```")
    await wait_for(lambda: len(tg.sent()) > n, what="reply")
    reply = tg.sent()[-1]
    assert reply["message_thread_id"] == thread and reply["parse_mode"] == "HTML"
    assert "<b>the plan</b>" in reply["text"] and "x = 1 &lt; 2" in reply["text"]
    assert gateway.gateway()._pending == {}
    # a second message reuses the same session
    tg.message("again", thread=thread)
    await wait_for(lambda: len(svc.sent) == 2, what="second")
    assert svc.sent[1]["sid"] == sid
    n = len(tg.sent())
    svc.finish(sid, "", error="Claude crashed")
    await wait_for(lambda: any("⚠️ Claude crashed" in p["text"] for p in tg.sent()[n:]), what="error reply")


async def test_handled_updates_not_replayed_after_restart(api, tg, svc, monkeypatch):
    """Two updates in one batch, the server stops while the 2nd is handled: after the restart the 1st
    (already sent to Claude) is not handled again, the 2nd is."""
    await _link(api, tg)
    sid, thread = await _open(api, svc)
    gw = gateway.gateway()
    real, hang = gw.handle_update, asyncio.Event()

    async def slow(u):
        if (u.get("message") or {}).get("text") == "second":
            await hang.wait()                                            # e.g. a long download
        return await real(u)
    monkeypatch.setattr(gw, "handle_update", slow)
    tg.message("first", thread=thread)
    tg.message("second", thread=thread)
    await wait_for(lambda: any(m["text"] == "first" for m in svc.sent), what="first handled")
    await asyncio.sleep(0.3)
    await gateway.stop()                                                 # restart (or crash) here
    svc.sessions[sid]["state"] = "idle"
    await gateway.start()
    await wait_for(lambda: any(m["text"] == "second" for m in svc.sent), what="second handled")
    await asyncio.sleep(0.5)
    assert [m["text"] for m in svc.sent] == ["first", "second"]


async def test_long_reply_is_split(api, tg, svc):
    await _link(api, tg)
    _, thread = await _open(api, svc)
    tg.message("long please", thread=thread)
    await wait_for(lambda: svc.sent, what="send")
    n = len(tg.sent())
    svc.finish(svc.sent[0]["sid"], ("paragraph " * 200 + "\n\n") * 6)
    await wait_for(lambda: len(tg.sent()) >= n + 3, what="split reply")
    assert all(len(p["text"]) <= 4096 for p in tg.sent()[n:])


async def test_photo_and_document_saved_as_attachments(api, tg, svc, mx_state):
    await _link(api, tg)
    tg.add_file("PHOTO1", b"\xff\xd8jpegdata", "photos/file_7.jpg")
    tg.add_file("DOC1", b"%PDF-1.4", "documents/file_8.pdf")
    _, thread = await _open(api, svc)
    tg.message("", thread=thread, caption="look at this",
               photo=[{"file_id": "small", "file_size": 10, "width": 90},
                      {"file_id": "PHOTO1", "file_size": 999, "width": 1280}])
    await wait_for(lambda: svc.sent, what="photo turn")
    att = svc.sent[0]["attachments"]
    assert svc.sent[0]["text"] == "look at this" and len(att) == 1
    assert "/projects/acme/topics/blog/attachments/telegram/" in att[0]
    with open(att[0], "rb") as f:
        assert f.read() == b"\xff\xd8jpegdata"
    tg.message("", thread=thread, document={"file_id": "DOC1", "file_name": "../../evil report.pdf"})
    await wait_for(lambda: len(svc.sent) == 2, what="document turn")
    att = svc.sent[1]["attachments"][0]
    assert att.endswith("/evil report.pdf") and "/attachments/telegram/" in att
    assert svc.sent[1]["text"].startswith("(sent from Telegram")


async def test_voice_transcription_does_not_block_other_messages(api, tg, svc, monkeypatch):
    """A slow transcription runs in the background: /stop in another thread is handled at once, and a
    text sent after the voice note in the same thread still reaches Claude after it."""
    from maxxing import voice
    monkeypatch.setattr(voice, "readiness", lambda *a, **k: (True, None))
    monkeypatch.setattr(voice, "transcribe_file", lambda *a, **k: (time.sleep(2.5), {"text": "hello"})[1])
    await _link(api, tg)
    a, ta = await _open(api, svc, "A")
    b, tb = await _open(api, svc, "B")
    svc.sessions[b]["state"] = "running"
    tg.add_file("VOICE1", b"OggS....", "voice/file_1.oga")
    tg.message("", thread=ta, voice={"file_id": "VOICE1", "duration": 60})
    await asyncio.sleep(0.5)                                     # the transcription is running
    tg.message("after", thread=ta)
    t0 = time.monotonic()
    tg.message("/stop", thread=tb)
    await wait_for(lambda: b in svc.stopped, timeout=15, what="stop")
    assert time.monotonic() - t0 < 1.5, "/stop waited behind a voice transcription"
    await wait_for(lambda: len(svc.sent) == 2, timeout=15, what="voice then text")
    assert [m["text"] for m in svc.sent] == ["hello", "after"]


async def test_voice_cut_by_a_restart_is_asked_again(api, tg, svc, monkeypatch):
    """Telegram has the voice note as read once its lane starts: a restart before the lane ends must not lose it
    in silence - the next start asks for it again (not replayed: that could start a turn twice)."""
    from maxxing import voice
    monkeypatch.setattr(voice, "readiness", lambda *a, **k: (True, None))
    hold = threading.Event()                                     # the transcription lasts until the restart is over
    monkeypatch.setattr(voice, "transcribe_file", lambda *a, **k: (hold.wait(20), {"text": "hello"})[1])
    await _link(api, tg)
    a, ta = await _open(api, svc, "A")
    tg.add_file("VOICE1", b"OggS....", "voice/file_1.oga")
    tg.message("", thread=ta, voice={"file_id": "VOICE1", "duration": 60})
    try:
        await wait_for(lambda: gateway._inflight_path().exists() and json.loads(gateway._inflight_path().read_text()),
                       what="voice in flight")
        await tg_api.shutdown()
        await tg_api.startup()
        await wait_for(lambda: any("send it again" in m.get("text", "") and m.get("message_thread_id") == ta
                                   for m in tg.sent()), timeout=15, what="asked again")
        assert json.loads(gateway._inflight_path().read_text()) == {}
        assert svc.sent == []
    finally:
        hold.set()


async def test_voice_already_handed_to_the_session_is_not_asked_again(api, tg, svc, monkeypatch):
    """A stop that cancels the lane while send_message runs in its worker thread: the message reaches the session,
    so the next start must not ask for it again (it would run twice)."""
    from maxxing import voice
    monkeypatch.setattr(voice, "readiness", lambda *a, **k: (True, None))
    monkeypatch.setattr(voice, "transcribe_file", lambda *a, **k: {"text": "hello"})
    real = svc.send_message
    monkeypatch.setattr(svc, "send_message", lambda *a, **k: (time.sleep(1.5), real(*a, **k))[1])
    await _link(api, tg)
    a, ta = await _open(api, svc, "A")
    tg.add_file("VOICE1", b"OggS....", "voice/file_1.oga")
    tg.message("", thread=ta, voice={"file_id": "VOICE1", "duration": 60})
    await wait_for(lambda: gateway._inflight_path().exists() and json.loads(gateway._inflight_path().read_text()),
                   what="voice in flight")
    await asyncio.sleep(0.5)                                     # send_message is running in its thread
    await tg_api.shutdown()
    await wait_for(lambda: len(svc.sent) == 1, timeout=10, what="handed to the session")
    await wait_for(lambda: json.loads(gateway._inflight_path().read_text()) == {}, timeout=10, what="mark dropped")
    await tg_api.startup()
    await asyncio.sleep(1)
    assert not any("send it again" in m.get("text", "") for m in tg.sent())


async def test_finished_voice_leaves_nothing_in_flight(api, tg, svc, monkeypatch):
    from maxxing import voice
    monkeypatch.setattr(voice, "readiness", lambda *a, **k: (True, None))
    monkeypatch.setattr(voice, "transcribe_file", lambda *a, **k: {"text": "hello"})
    await _link(api, tg)
    a, ta = await _open(api, svc, "A")
    tg.add_file("VOICE1", b"OggS....", "voice/file_1.oga")
    tg.message("", thread=ta, voice={"file_id": "VOICE1", "duration": 60})
    await wait_for(lambda: len(svc.sent) == 1, timeout=15, what="voice handled")
    await wait_for(lambda: json.loads(gateway._inflight_path().read_text()) == {}, what="lane ended")


async def test_live_status_message(api, tg, svc, monkeypatch):
    monkeypatch.setattr(gateway, "TICK", 0.02)
    monkeypatch.setattr(gateway, "PROGRESS_DELAY", 0.0)
    monkeypatch.setattr(gateway, "PROGRESS_EVERY", 0.0)
    await _link(api, tg)
    assert (await api.get("/api/telegram")).json()["settings"]["reply_mode"] == "progress"   # default
    _, thread = await _open(api, svc)
    tg.message("do it", thread=thread)
    await wait_for(lambda: svc.sent, what="send")
    sid = svc.sent[0]["sid"]
    svc.events[sid] = [
        {"type": "tool_use", "id": "t0", "name": "TodoWrite", "summary": "TodoWrite (2 items)",
         "input": {"todos": [{"content": "Read the code", "status": "completed"},
                             {"content": "Fix the bug", "activeForm": "Fixing the bug", "status": "in_progress"}]}},
        {"type": "tool_use", "id": "t1", "name": "Read", "summary": "Read src/app.py"},
    ]
    await wait_for(lambda: any("Read src/app.py" in p["text"] for p in tg.sent()), what="status message")
    status = next(p for p in tg.sent() if "Read src/app.py" in p["text"])
    assert status["disable_notification"] and status["message_thread_id"] == thread
    assert "⋯ Read src/app.py" in status["text"] and "◐ 1/2 Fixing the bug" in status["text"]
    assert "<blockquote>" in status["text"] and "TodoWrite" not in status["text"]
    svc.events[sid] += [{"type": "tool_result", "tool_use_id": "t1", "text": "ok"},
                        {"type": "tool_use", "id": "t2", "name": "Bash", "summary": "Bash: pytest -q"}]
    await wait_for(lambda: any("✓ Read src/app.py" in p["text"] and "⋯ Bash: pytest -q" in p["text"]
                               for p in tg.sent("editMessageText")), what="status edited in place")
    n_status = len([p for p in tg.sent() if "Read src/app.py" in p["text"]])
    svc.finish(sid, "done")
    await wait_for(lambda: tg.sent()[-1]["text"] == "done", what="final answer")
    last_edit = tg.sent("editMessageText")[-1]["text"]
    assert last_edit.startswith("✅") and "2 steps" in last_edit and "<blockquote expandable>" in last_edit
    assert "✓ Bash: pytest -q" in last_edit
    assert len([p for p in tg.sent() if "Read src/app.py" in p["text"]]) == n_status == 1   # one message, edited


async def test_live_status_ignores_earlier_turns_of_a_big_log(api, tg, svc, monkeypatch, tmp_path):
    """The status of a new turn starts at the end of the log, even past the 4 MB read_events reads at once."""
    monkeypatch.setattr(gateway, "TICK", 0.02)
    monkeypatch.setattr(gateway, "PROGRESS_DELAY", 0.0)
    monkeypatch.setattr(gateway, "PROGRESS_EVERY", 0.0)
    log = tmp_path / "big.log"
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "old", "name": "Bash", "input": {"command": "old-turn-cmd " + "x" * 400}}]}})
    with open(log, "w") as f:
        for _ in range((5 * 1024 * 1024) // (len(line) + 1)):            # ~5 MB of earlier turns
            f.write(line + "\n")
    monkeypatch.setattr(real_store, "log_path", lambda sid: log)
    monkeypatch.setattr(real_service, "_require", lambda sid: {})
    monkeypatch.setattr(svc, "read_events", real_service.read_events, raising=False)
    monkeypatch.setattr(svc, "end_offset", real_service.end_offset, raising=False)
    assert real_service.end_offset("x") == log.stat().st_size
    await _link(api, tg)
    _, thread = await _open(api, svc)
    tg.message("new question", thread=thread)
    await wait_for(lambda: svc.sent, what="send")
    await asyncio.sleep(1.5)                                             # a few status ticks
    texts = [p.get("text", "") for p in tg.sent() + tg.sent("editMessageText")]
    assert not [t for t in texts if "old-turn-cmd" in t], "the live status shows tool calls of earlier turns"


async def test_quick_answer_has_no_status_and_final_mode(api, tg, svc, monkeypatch):
    monkeypatch.setattr(gateway, "TICK", 0.02)
    await _link(api, tg)
    _, thread = await _open(api, svc)
    tg.message("hi", thread=thread)
    await wait_for(lambda: svc.sent, what="send")
    svc.finish(svc.sent[0]["sid"], "hello")
    await wait_for(lambda: tg.sent()[-1]["text"] == "hello", what="answer")
    assert not tg.sent("editMessageText") and not any("⏳" in p["text"] or "✅" in p["text"] for p in tg.sent())
    # reply_mode final: tools are not shown at all
    assert (await api.put("/api/telegram/settings", json={"reply_mode": "final"})).json()["ok"]
    monkeypatch.setattr(gateway, "PROGRESS_DELAY", 0.0)
    tg.message("again", thread=thread)
    await wait_for(lambda: len(svc.sent) == 2, what="send 2")
    sid = svc.sent[1]["sid"]
    svc.events[sid] = [{"type": "tool_use", "id": "x", "name": "Read", "summary": "Read a.py"}]
    svc.finish(sid, "ok2")
    await wait_for(lambda: tg.sent()[-1]["text"] == "ok2", what="answer 2")
    assert not any("Read a.py" in p["text"] for p in tg.sent())


async def test_typing_falls_back_to_the_main_chat(api, tg, svc, monkeypatch):
    monkeypatch.setattr(gateway, "TICK", 0.02)
    monkeypatch.setattr(gateway, "TYPING_EVERY", 0.05)
    await _link(api, tg)
    _, thread = await _open(api, svc)
    tg.fail_once["sendChatAction"] = (400, "Bad Request: some threads refuse actions")
    tg.message("work", thread=thread)
    await wait_for(lambda: len(tg.sent("sendChatAction")) >= 3, what="typing retried")
    calls = tg.sent("sendChatAction")
    assert calls[0].get("message_thread_id") and not calls[1].get("message_thread_id")
    assert not calls[2].get("message_thread_id")                   # remembered for the turn
    svc.finish(svc.sent[0]["sid"], "x")


def test_render_status_is_compact():
    steps = [{"id": str(i), "text": f"Read f{i}.py", "state": "ok"} for i in range(12)]
    steps.append({"id": "x", "text": "Bash: " + "find / -name '*.log' -mtime -2 " * 4, "state": "run"})
    html = gateway.render_status(steps, [], 75, None, "fr")
    assert html.startswith("⏳ <b>Harness travaille…</b> · 1:15\n<blockquote>")
    assert html.count("\n") == 3                                  # header + the last 3 steps
    assert "Read f10.py" in html and "Read f9.py" not in html
    long_line = html.splitlines()[-1]
    assert long_line.startswith("⋯ Bash: find") and long_line.endswith("…</blockquote>") and len(long_line) < 70
    final = gateway.render_status(steps, [], 3700, "error")
    assert final.startswith("⚠️ <b>Stopped with an error</b> · 1:01:40 · 13 steps\n<blockquote expandable>… +1")
    assert gateway.render_status([], [], 2, "ok") == "✅ <b>Done</b> · 0:02"


# =============================================================================================
# Commands
# =============================================================================================
async def test_commands(api, tg, svc):
    await _link(api, tg)
    first, thread = await _open(api, svc, "Main")
    # /new in a session thread: a sibling session in the same topic, with its own thread
    tg.message("/new Research", thread=thread)
    await wait_for(lambda: any("continue in the thread" in p["text"] for p in tg.sent()), what="/new")
    research = next(k for k, v in svc.sessions.items() if v["title"] == "Research")
    assert svc.sessions[research]["path"] == TOPIC and gateway.thread_of(research) not in (None, thread)
    # /sessions lists the open sessions
    tg.message("/sessions", thread=thread)
    await wait_for(lambda: any("Open sessions" in p["text"] for p in tg.sent()), what="/sessions")
    listing = next(p for p in tg.sent() if "Open sessions" in p["text"])["text"]
    assert "acme/blog · Main" in listing and "acme/blog · Research" in listing
    # /model with argument and via keyboard: the thread's session
    tg.message("/model claude-sonnet-5-5", thread=thread)
    await wait_for(lambda: svc.sessions[first]["model"] == "claude-sonnet-5-5", what="/model arg")
    tg.message("/model@maxxing_test_bot", thread=thread)
    await wait_for(lambda: any("Model of this session" in p["text"] for p in tg.sent()), what="/model kb")
    tg.callback("m:claude-opus-5-5", thread=thread)
    await wait_for(lambda: svc.sessions[first]["model"] == "claude-opus-5-5", what="model callback")
    # /status
    tg.message("/status", thread=thread)
    await wait_for(lambda: any("Model: claude-opus-5-5" in p["text"] for p in tg.sent()), what="/status")
    # /stop
    svc.sessions[first]["state"] = "running"
    tg.message("/stop", thread=thread)
    await wait_for(lambda: svc.stopped == [first], what="/stop")
    # /close: the session is archived (kept) and its thread deleted
    rtid = gateway.thread_of(research)
    tg.message("/close", thread=rtid)
    # archived first, then the thread is deleted: wait for both
    await wait_for(lambda: svc.sessions[research]["archived"] and rtid not in tg.topics, what="/close")
    await wait_for(lambda: research not in gateway.session_threads(), what="/close thread map")
    # /help, and messages in notification threads are refused
    tg.message("/help", thread=thread)
    await wait_for(lambda: any("/sessions" in p["text"] and "Main" in p["text"] for p in tg.sent()), what="/help")
    tg.message("hello", thread=_thread("#crons"))
    await wait_for(lambda: any("only receives notifications" in p["text"] for p in tg.sent()), what="crons thread")
    assert not svc.sent
    # a session command in the main chat: where to send it (no "where?" question left behind)
    tg.message("/status")
    await wait_for(lambda: any("send it in that session's thread" in p["text"] for p in tg.sent()), what="in a thread")
    assert gateway.gateway()._new == {}


# =============================================================================================
# Notifications
# =============================================================================================
async def test_alert_from_worker_thread(api, tg):
    await _link(api, tg)
    await asyncio.to_thread(gateway.alert, "Signed in\n1.2.3.4", True)
    await wait_for(lambda: any(p["text"].startswith("Signed in") for p in tg.sent()), what="alert")
    p = next(p for p in tg.sent() if p["text"].startswith("Signed in"))
    assert p["message_thread_id"] == _thread("#alerts") and not p.get("disable_notification")
    await asyncio.to_thread(gateway.alert, "quiet one", False)
    await wait_for(lambda: any(p["text"] == "quiet one" and p.get("disable_notification") for p in tg.sent()),
                   what="silent alert")
    # login_alerts off -> nothing
    await api.put("/api/telegram/settings", json={"login_alerts": False})
    n = len(tg.sent())
    gateway.alert("nope")
    await asyncio.sleep(0.2)
    assert len(tg.sent()) == n


async def test_notifications_without_gateway(api, tg):
    """Another process (`maxxing cron run`) has no gateway: notifications are sent directly."""
    await _link(api, tg)
    crons_thread = _thread("#crons")
    await gateway.stop()
    assert gateway.status()["running"] is False
    await asyncio.to_thread(gateway.notify_cron, "OK - nightly (3 s)")
    p = tg.sent()[-1]
    assert p["text"] == "OK - nightly (3 s)" and p["message_thread_id"] == crons_thread
    await asyncio.to_thread(gateway.notify_topic, TOPIC, "a <b> c")
    assert tg.sent()[-1]["text"] == "a &lt;b&gt; c" and tg.sent()[-1].get("message_thread_id") is None
    # from the event loop itself it must not block: sent from a helper thread
    gateway.notify_topic("projects/none/topics/x", "to the main chat")
    await wait_for(lambda: tg.sent()[-1]["text"] == "to the main chat", what="loop-safe notify")
    assert tg.sent()[-1].get("message_thread_id") is None


async def test_web_session_notify(api, tg, svc):
    await _link(api, tg)
    config.update_config(public_url="https://ui.example.com")
    web = svc.create_session(TOPIC, title="Refactor", source="web", notify=True)["id"]
    await api.post("/api/telegram/sync")
    await api.put("/api/telegram/settings", json={"mirror_web": True})
    # mirror on: the answer goes to the session's thread, loud because Notify is on
    svc.send_message(web, "go", source="web")
    n = len(tg.sent())
    svc.finish(web, "All tests pass.")
    await wait_for(lambda: any(p["text"] == "All tests pass." for p in tg.sent()[n:]), what="mirror")
    p = next(p for p in tg.sent()[n:] if p["text"] == "All tests pass.")
    assert p["message_thread_id"] == gateway.thread_of(web) and not p.get("disable_notification")
    # mirror off: the short "finished" notification as before
    await api.put("/api/telegram/settings", json={"mirror_web": False})
    n = len(tg.sent())
    svc.finish(web, "All tests pass. " * 40)
    await wait_for(lambda: any("Refactor" in p["text"] for p in tg.sent()[n:]), what="notify")
    p = next(p for p in tg.sent()[n:] if "Refactor" in p["text"])
    assert p["message_thread_id"] == gateway.thread_of(web)
    assert p["text"].startswith("✅ <b>Refactor</b>") and f"https://ui.example.com/sessions/{web}" in p["text"]


async def test_deleted_thread_falls_back(api, tg):
    """A thread deleted in Telegram: the message goes to the main chat and the mapping is dropped."""
    await _link(api, tg)
    tg.fail_once["sendMessage"] = (400, "Bad Request: message thread not found")
    await asyncio.to_thread(gateway._send_sync, "#crons", ["x"], False)
    assert tg.sent()[-1]["text"] == "x" and tg.sent()[-1].get("message_thread_id") is None
    assert "#crons" not in gateway.tg_config()["threads"]
    tg.fail_once["sendMessage"] = (400, "Bad Request: can't parse entities: unclosed tag")
    await asyncio.to_thread(gateway._send_sync, "", ["<b>oops & co"], False)
    assert tg.sent()[-1]["text"] == "oops & co" and tg.sent()[-1].get("parse_mode") is None
    assert (await api.post("/api/telegram/sync")).json()["created"] == 1


async def test_forget(api, tg):
    await _link(api, tg)
    r = await api.delete("/api/telegram")
    assert r.json()["ok"]
    st = gateway.status()
    assert not st["configured"] and not st["running"] and st["chat"] is None and st["threads"] == []
    assert config.get_secret("telegram_token") == ""
    assert gateway.tg_config()["sessions"] == {} and gateway.tg_config()["session_threads"] == {}


async def test_token_rejected_stops_gateway(api, tg):
    await _link(api, tg)
    tg.token = "999:other"                                 # every call now returns 401
    await wait_for(lambda: not gateway.status()["running"], what="gateway stop on 401")
    assert "rejected" in gateway.status()["last_error"]


def test_cli_status(mx_state, capsys):
    from maxxing import cli
    assert cli.main(["telegram", "status"]) == 0
    assert "configured : no" in capsys.readouterr().out
    assert cli.main(["telegram", "test"]) == 1


def test_parse_command():
    assert gateway.parse_command("/model@Bot opus", "bot") == ("model", "opus")
    assert gateway.parse_command("/model@Other opus", "bot")[0] is None
    assert gateway.parse_command("hello /new", "bot")[0] is None
    assert gateway.topic_label("projects/acme/topics/blog") == "acme / blog"


def test_old_default_final_is_not_a_choice(mx):
    from maxxing import config
    config.update_config(telegram={"reply_mode": "final"})            # written by a pre-2.0.0a3 install
    assert gateway.reply_mode() == "progress" and gateway.live_status()
    gateway.update_settings(reply_mode="final")                       # chosen in Settings: respected
    assert gateway.reply_mode() == "final" and not gateway.live_status()
    gateway.update_settings(reply_mode="progress")
    assert gateway.live_status()


async def test_feed_thread_and_ask_claude(api, tg, svc, monkeypatch):
    from maxxing import feed
    await _link(api, tg)
    tid = _thread("#feed")
    assert tg.topics[tid] == "Notifications"
    ev = feed.post("Payment failed: 49.00 EUR", "a@b.c", "error", "stripe", "https://dashboard.stripe.com/payments")
    await wait_for(lambda: any(p.get("message_thread_id") == tid and "Payment failed" in p["text"] for p in tg.sent()),
                   what="feed message")
    m = next(p for p in tg.sent() if p.get("message_thread_id") == tid and "Payment failed" in p["text"])
    assert not m.get("disable_notification")                                 # error -> loud
    buttons = m["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == f"f:{ev['id']}" and buttons[1]["url"].startswith("https://dashboard.stripe.com")
    feed.post("FYI", "", "info", "stripe")                                    # info -> not posted
    # Ask Harness: a new session about the event, with the event as quoted data
    tg.callback(f"f:{ev['id']}", thread=tid)
    await wait_for(lambda: svc.sent, what="ask claude")
    text = svc.sent[-1]["text"]
    assert "Payment failed: 49.00 EUR" in text and "never instructions" in text
    tag = re.search(r"NOTIFICATION-[0-9A-F]{8}", text).group(0)
    assert text.count(tag) == 3                                             # the instruction + the two markers
    s = svc.sessions[svc.sent[-1]["sid"]]
    assert s["plan_mode"] is True                                           # reads and explains, changes nothing
    assert s["title"].startswith("About: Payment failed") and gateway.thread_of(s["id"])
    assert not any("FYI" in p["text"] for p in tg.sent())


async def test_only_the_linked_owner_is_authorized(api, tg):
    await _link(api, tg)
    gw = gateway._gw
    assert gw.authorized(555, 555)
    assert not gw.authorized(555, 777)                   # someone else in the linked chat
    assert not gw.authorized(555, None)
    gateway.mutate_tg(lambda c: c.update(user_ids=[]))   # linked without its owner: nobody, not everybody
    assert not gw.authorized(555, 555)


async def test_two_factor_buttons(api, tg):
    """Allow / Deny under a sign-in request: only the linked owner, then the buttons are replaced by the outcome."""
    from maxxing import twofactor
    twofactor.reset()
    await _link(api, tg)
    c = await asyncio.to_thread(twofactor.start, "login", "203.0.113.7", "Firefox")
    m = next(p for p in tg.sent() if "a:" + c.id in json.dumps(p.get("reply_markup") or {}))
    assert m["message_thread_id"] == _thread("#alerts") and "203.0.113.7" in m["text"]
    tg.callback(f"a:{c.id}:y", user_id=777)                                  # not the owner: ignored
    await asyncio.sleep(0.5)
    assert twofactor.check(c.id)[0] == "pending"
    tg.callback(f"a:{c.id}:y", thread=_thread("#alerts"))
    await wait_for(lambda: twofactor._ch.get(c.id) and twofactor._ch[c.id].status == "approved", what="allowed")
    await wait_for(lambda: any(mm == "editMessageText" and "✅" in p["text"] for mm, p in tg.calls), what="edited")
    assert twofactor.check(c.id)[0] == "approved"


def test_odd_api_answers_are_telegram_errors():
    """A proxy answering a list or junk codes gives a TelegramError (retried), never an AttributeError that would
    stop a loop (C4)."""
    import httpx
    from maxxing.telegram.client import TelegramError, _parse
    for body, status in (([1, 2], 502), ({"ok": False, "error_code": "x", "parameters": "y"}, 500), ("str", 200)):
        r = httpx.Response(status, json=body)
        try:
            _parse(r, "tok")
        except TelegramError as e:
            assert e.code == status
        else:
            raise AssertionError("no error")


async def test_sync_does_not_retrigger_itself(api, tg, svc, monkeypatch):
    # with nothing changing, the thread sync must not run again and again: it announced "workspace", which its own
    # session watcher took as a reason to sync again
    from maxxing import bus
    monkeypatch.setattr(gateway, "SYNC_DEBOUNCE", 0.2)
    bus.bind_loop(asyncio.get_running_loop())          # as in the real server (app.py): announcements are delivered
    try:
        await _idle_syncs(api, tg, svc, monkeypatch)
    finally:
        bus.bind_loop(None)


async def _idle_syncs(api, tg, svc, monkeypatch):
    await _link(api, tg)
    svc.create_session(TOPIC, title="Plan", source="web")
    await api.post("/api/telegram/sync")
    await asyncio.sleep(1.0)                           # let the first syncs settle
    calls = {"n": 0}
    real = gateway.Gateway.sync_threads

    async def counting(self):
        calls["n"] += 1
        return await real(self)
    monkeypatch.setattr(gateway.Gateway, "sync_threads", counting)
    t0 = time.monotonic()
    await asyncio.sleep(3.0)
    assert time.monotonic() - t0 >= 3.0 and calls["n"] <= 1, f"{calls['n']} thread syncs in 3 s with nothing changing"


def test_same_name_downloads_at_once_get_two_files(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "_topic_dir", lambda p: tmp_path)

    class SlowClient:
        async def download(self, file_id, dest, max_bytes=0):   # same steps as Client.download
            part = dest.with_name(dest.name + ".part")
            await asyncio.sleep(0.02 if file_id == "A" else 0.04)
            part.write_bytes(file_id.encode() * 3)
            await asyncio.sleep(0.03)
            part.replace(dest)

    gw = gateway.Gateway.__new__(gateway.Gateway)
    gw.client = SlowClient()
    msg = lambda fid, i: {"message_id": i, "document": {"file_id": fid, "file_name": "report.pdf"}}  # noqa: E731

    async def both():
        return await asyncio.gather(gw._download(msg("A", 1), "p"), gw._download(msg("B", 2), "p"))
    (a,), (b,) = asyncio.run(both())
    assert a != b
    assert {open(a, "rb").read(), open(b, "rb").read()} == {b"AAA", b"BBB"}
    assert not list(tmp_path.rglob("*.part"))


def test_render_of_a_huge_line_full_of_markers_stays_fast():
    for line in ("[a](" * 8000, "_a " * 8000, "**a " * 8000, "*" * 32000):
        t0 = time.perf_counter()
        out = "".join(fmt.render(line))
        assert time.perf_counter() - t0 < 0.2, line[:8]
        assert "<b>" not in out and "<i>" not in out
    assert fmt.render("**bold** & <x>" + " word" * 300)[0].startswith("<b>bold</b> &amp; &lt;x&gt;")
