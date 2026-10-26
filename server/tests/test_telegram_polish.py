"""Telegram bridge, incoming side: audio files, replies / forwards / hidden links, edits, long pastes, albums,
captions that look like commands, /model validation, translated bot texts, thread naming."""
from __future__ import annotations

import asyncio
import sys

import httpx
import pytest

from _conn_helpers import (TG_TOKEN, FakeService, FakeTelegram, FakeWorkspace, bare_app,  # noqa: F401
                           mx_state, wait_for)
from maxxing import config
from maxxing.api import telegram as tg_api
from maxxing.sessions import service as real_service, store as real_store, titles  # noqa: F401 - before the fakes
from maxxing.telegram import gateway

TOPIC = "projects/acme/topics/blog"


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


async def _open(api, svc, title: str = "Plan") -> tuple[str, int]:
    sid = svc.create_session(TOPIC, title=title, source="web")["id"]
    assert (await api.post("/api/telegram/sync")).status_code == 200
    tid = gateway.thread_of(sid)
    assert tid
    return sid, tid


# =============================================================================================
# Pure helpers
# =============================================================================================
def test_hidden_links_are_expanded_with_utf16_offsets():
    text = "😀 see docs and Ada"                      # the emoji is 2 UTF-16 code units
    ents = [{"type": "text_link", "offset": 7, "length": 4, "url": "https://example.com/d"},
            {"type": "text_mention", "offset": 16, "length": 3, "user": {"id": 42, "first_name": "Ada"}},
            {"type": "bold", "offset": 0, "length": 2}]
    out = gateway._with_context({"text": text, "entities": ents}, text)
    assert out == "😀 see docs (https://example.com/d) and Ada (tg://user?id=42)"
    # a visible URL is not repeated
    t2 = "https://x.io"
    assert gateway._with_context({"text": t2, "entities": [{"type": "text_link", "offset": 0, "length": 12,
                                                             "url": "https://x.io"}]}, t2) == t2


def test_reply_quote_and_forward_context():
    bot_reply = {"message_id": 7, "from": {"id": 1, "is_bot": True}, "text": "Plan:\n1. a\n2. b"}
    msg = {"message_id": 9, "text": "do 2", "reply_to_message": bot_reply}
    assert gateway._with_context(msg, "do 2") == "(Replying to your earlier message:)\n> Plan:\n> 1. a\n> 2. b\n\ndo 2"
    msg["quote"] = {"text": "2. b"}                        # the user quoted a part only
    assert gateway._with_context(msg, "do 2") == "(Replying to your earlier message:)\n> 2. b\n\ndo 2"
    long = {"message_id": 3, "from": {"id": 5}, "text": "x" * 2000}
    out = gateway._with_context({"text": "ok", "reply_to_message": long}, "ok")
    assert out.startswith("(Replying to this message:)\n> " + "x" * 500 + "…") and len(out) < 600
    # in a forum thread every message points to the thread's first message: not a reply
    root = {"message_id": 40, "forum_topic_created": {"name": "t"}}
    assert gateway._with_context({"text": "hi", "message_thread_id": 40, "reply_to_message": root}, "hi") == "hi"
    assert gateway._with_context({"text": "hi", "message_thread_id": 40,
                                  "reply_to_message": {"message_id": 40, "text": "x"}}, "hi") == "hi"
    fwd = {"text": "news", "forward_origin": {"type": "channel", "chat": {"title": "Tech Daily"}}}
    assert gateway._with_context(fwd, "news") == "Forwarded from Tech Daily:\n\nnews"
    fwd = {"caption": "pic", "forward_origin": {"type": "user", "sender_user": {"first_name": "Bob"}}}
    assert gateway._with_context(fwd, "pic") == "Forwarded from Bob:\n\npic"
    assert gateway._with_context({"text": "a", "forward_sender_name": "Eve"}, "a") == "Forwarded from Eve:\n\na"


def test_resolve_model():
    models = gateway.FALLBACK_MODELS
    assert gateway.resolve_model("opus", models) == "claude-opus-5-5"
    assert gateway.resolve_model("Sonnet 5.5", models) == "claude-sonnet-5-5"
    assert gateway.resolve_model("claude-haiku-4-5-20251001", models) == "claude-haiku-4-5-20251001"
    assert gateway.resolve_model("default", models) == ""
    assert gateway.resolve_model("gpt-5", models) is None
    assert gateway.resolve_model("5", models) is None


def test_thread_name_ignores_the_project_emoji():
    assert gateway._name_text("🛒 acme/blog · Plan") == gateway._name_text("acme/blog · Plan")
    assert gateway._name_text("🛒 acme/blog · Plan") != gateway._name_text("acme/blog · Plan B")


def test_words_have_the_same_keys_in_every_language():
    for lang, words in gateway.WORDS.items():
        assert set(words) == set(gateway.WORDS["en"]), lang
    for c, _ in gateway.COMMANDS:
        assert all(f"cmd_{c}" in w for w in gateway.WORDS.values())


# =============================================================================================
# Through the fake Bot API
# =============================================================================================
async def test_audio_file_is_an_attachment_not_a_voice_note(api, tg, svc, monkeypatch):
    from maxxing import voice
    monkeypatch.setattr(voice, "readiness", lambda *a, **k: pytest.fail("audio files are not transcribed"))
    await _link(api, tg)
    _, thread = await _open(api, svc)
    tg.add_file("MP3", b"ID3....", "music/file_3.mp3")
    tg.message("", thread=thread, audio={"file_id": "MP3", "file_name": "song.mp3", "duration": 200})
    await wait_for(lambda: svc.sent, what="audio turn")
    att = svc.sent[0]["attachments"]
    assert len(att) == 1 and "/attachments/telegram/" in att[0]
    assert att[0].endswith("song.mp3") and svc.sent[0]["text"] == "(sent from Telegram: song.mp3)"


async def test_reply_and_hidden_link_reach_claude(api, tg, svc):
    await _link(api, tg)
    _, thread = await _open(api, svc)
    tg.message("check this", thread=thread,
               entities=[{"type": "text_link", "offset": 6, "length": 4, "url": "https://example.com"}],
               reply_to_message={"message_id": 3, "from": {"id": 123456789, "is_bot": True}, "text": "Step 2 failed"})
    await wait_for(lambda: svc.sent, what="turn")
    assert svc.sent[0]["text"] == "(Replying to your earlier message:)\n> Step 2 failed\n\ncheck this (https://example.com)"


async def test_edited_message_is_answered_once(api, tg, svc):
    await _link(api, tg)
    _, thread = await _open(api, svc)
    edited = {"message_id": 77, "date": 1, "edit_date": 2, "text": "fixed typo", "message_thread_id": thread,
              "is_topic_message": True, "chat": {"id": 555, "type": "private"}, "from": {"id": 555, "is_bot": False}}
    tg.push({"edited_message": edited})
    tg.push({"edited_message": {**edited, "text": "fixed typo again"}})
    tg.push({"edited_message": {**edited, "chat": {"id": 777, "type": "private"}, "from": {"id": 777}}})  # stranger
    await wait_for(lambda: any("Edits are not sent" in p["text"] for p in tg.sent()), what="edit notice")
    await asyncio.sleep(0.5)
    notes = [p for p in tg.sent() if "Edits are not sent" in p["text"]]
    assert len(notes) == 1 and notes[0]["message_thread_id"] == thread and notes[0]["disable_notification"]
    assert not svc.sent


async def test_long_paste_split_by_telegram_is_one_turn(api, tg, svc):
    await _link(api, tg)
    _, thread = await _open(api, svc)
    part1, part2, part3 = "a" * 4096, "b" * 4096, "c" * 300
    tg.message(part1, thread=thread)
    tg.message(part2, thread=thread)
    tg.message(part3, thread=thread)
    await wait_for(lambda: svc.sent, what="merged turn")
    await asyncio.sleep(2.0)
    assert [m["text"] for m in svc.sent] == [f"{part1}\n{part2}\n{part3}"]
    assert not [p for p in tg.sent() if "Queued" in p["text"]]
    # short messages are never held back or merged
    tg.message("one", thread=thread)
    tg.message("two", thread=thread)
    await wait_for(lambda: len(svc.sent) == 3, what="two short turns")
    assert [m["text"] for m in svc.sent[1:]] == ["one", "two"]
    assert gateway._inflight_path().read_text().strip() in ("{}", "")


async def test_album_then_text_keeps_the_order_and_waits_for_slow_items(api, tg, svc):
    await _link(api, tg)
    _, thread = await _open(api, svc)
    for i in range(3):
        tg.add_file(f"P{i}", b"\xff\xd8jpeg", f"photos/file_{i}.jpg")
    for i in range(3):                                          # the album takes 2 s to arrive
        tg.message("", thread=thread, media_group_id="G1", caption="three photos" if i == 0 else None,
                   photo=[{"file_id": f"P{i}", "file_size": 5, "width": 10}])
        if i < 2:
            await asyncio.sleep(1.0)
    tg.message("and what do you think?", thread=thread)
    await wait_for(lambda: len(svc.sent) == 2, timeout=15, what="album then text")
    assert svc.sent[0]["text"] == "three photos" and len(svc.sent[0]["attachments"]) == 3
    assert svc.sent[1]["text"] == "and what do you think?"


async def test_command_caption_keeps_the_photo(api, tg, svc):
    await _link(api, tg)
    sid, thread = await _open(api, svc)
    tg.add_file("PH", b"\xff\xd8jpeg", "photos/file_9.jpg")
    tg.message("", thread=thread, caption="/new", photo=[{"file_id": "PH", "file_size": 5, "width": 10}])
    await wait_for(lambda: svc.sent, what="photo turn")
    assert svc.sent[0]["sid"] == sid and svc.sent[0]["text"] == "/new" and len(svc.sent[0]["attachments"]) == 1
    assert len(svc.sessions) == 1


async def test_model_command_validates(api, tg, svc):
    await _link(api, tg)
    sid, thread = await _open(api, svc)
    tg.message("/model gpt-9", thread=thread)
    await wait_for(lambda: any("Unknown model" in p["text"] for p in tg.sent()), what="unknown model")
    err = next(p for p in tg.sent() if "Unknown model" in p["text"])
    assert "claude-opus-5-5" in err["text"] and err.get("reply_markup")
    assert svc.sessions[sid]["model"] == ""
    tg.message("/model opus", thread=thread)
    await wait_for(lambda: svc.sessions[sid]["model"] == "claude-opus-5-5", what="alias")


async def test_bot_texts_follow_the_language(api, tg, svc):
    config.update_config(language="fr")
    await _link(api, tg)
    _, thread = await _open(api, svc)
    tg.message("/stop", thread=thread)
    await wait_for(lambda: any(p["text"] == "Rien n'est en cours." for p in tg.sent()), what="fr text")
    tg.message("/help", thread=thread)
    await wait_for(lambda: any("Chaque session ouverte" in p["text"] for p in tg.sent()), what="fr help")
    menus = {p.get("language_code"): p["commands"] for p in tg.sent("setMyCommands")}
    assert {None, "en", "fr"} <= set(menus)
    assert menus["en"][0]["description"].startswith("Start a new session")
    assert menus["fr"][0]["description"].startswith("Démarrer") and menus[None] == menus["fr"]


async def test_thread_waits_for_the_short_title_and_renames_sparingly(api, tg, svc, monkeypatch):
    await _link(api, tg)
    waiting: set[str] = set()
    monkeypatch.setattr(titles, "pending", lambda sid: sid in waiting)
    sid = svc.create_session(TOPIC, title="can you please look at the failing deploy", source="web")["id"]
    waiting.add(sid)
    await api.post("/api/telegram/sync")
    assert gateway.thread_of(sid) is None                     # not named yet: no thread
    svc.sessions[sid]["title"] = "Failing deploy"
    waiting.discard(sid)
    await api.post("/api/telegram/sync")
    tid = gateway.thread_of(sid)
    assert tid and tg.topics[tid] == "acme/blog · Failing deploy" and not tg.sent("editForumTopic")
    # a still-pending title is not waited for once the session is older than TITLE_WAIT
    old = svc.create_session(TOPIC, title="x", source="web")["id"]
    svc.sessions[old]["created"] -= gateway.TITLE_WAIT + 1
    waiting.add(old)
    await api.post("/api/telegram/sync")
    assert gateway.thread_of(old)
    # in the first minutes: one rename, the next one waits
    svc.sessions[sid]["title"] = "Deploy fixed"
    await api.post("/api/telegram/sync")
    assert tg.topics[tid] == "acme/blog · Deploy fixed"
    svc.sessions[sid]["title"] = "Deploy fixed again"
    await api.post("/api/telegram/sync")
    assert tg.topics[tid] == "acme/blog · Deploy fixed" and len(tg.sent("editForumTopic")) == 1
    # later on, renames go through again
    svc.sessions[sid]["created"] -= gateway.RENAME_QUIET
    await api.post("/api/telegram/sync")
    assert tg.topics[tid] == "acme/blog · Deploy fixed again"
    # only the project emoji changed: no rename
    monkeypatch.setattr(gateway, "_emoji", lambda project: "🛒")
    await api.post("/api/telegram/sync")
    assert len(tg.sent("editForumTopic")) == 2
