"""Telegram modes: the simple mode (one chat, replies continue a session), the bell, health problems and alerts,
choosing a mode (fake Bot API, fake sessions service)."""
from __future__ import annotations

import asyncio

from _conn_helpers import TG_TOKEN, mx_state, wait_for  # noqa: F401  (fixture)
from maxxing import config
from maxxing.telegram import gateway
from test_telegram import TOPIC, _link, api, svc, tg, ws  # noqa: F401  (fixtures)


def _simple() -> None:
    config.update_config(telegram={"mode": "simple"})


async def _link_simple(api, tg) -> None:
    _simple()
    r = await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    assert r.status_code == 200, r.text
    code = (await api.post("/api/telegram/link")).json()["code"]
    tg.message(f"/start {code}")
    await wait_for(lambda: gateway.link_status()["linked"], what="link")


def _bot(text_part: str, tg) -> dict:
    return next(p for p in tg.sent() if text_part in (p.get("text") or ""))


def _reply_to(p: dict, mid: int) -> dict:
    return {"reply_to_message": {"message_id": mid, "from": {"id": 1, "is_bot": True}, "text": p.get("text", "")}}


async def _start(tg, svc, text: str = "Plan the launch") -> tuple[str, int]:
    """A message, "where?", the topic tapped -> (session id, message id of the user's message)."""
    tg.message(text)
    mid = tg.next_msg
    await wait_for(lambda: any("Where should" in (p.get("text") or "") for p in tg.sent()), what="where?")
    tg.callback(f"w:0:{gateway._path_hash(TOPIC)}")
    await wait_for(lambda: any(m["text"] == text for m in svc.sent), what="sent")
    return next(m["sid"] for m in svc.sent if m["text"] == text), mid


async def test_simple_mode_no_threads_and_replies_continue(api, tg, svc):
    await _link_simple(api, tg)
    assert gateway.mode() == "simple" and gateway.status()["mode"] == "simple"
    await asyncio.sleep(0.3)
    assert not tg.sent("createForumTopic")                       # no Crons / Alerts / Notifications either
    assert "reply to a message" in _bot("Linked to Harness", tg)["text"]
    sid, mid = await _start(tg, svc)
    assert svc.sessions[sid]["path"] == TOPIC and svc.sessions[sid]["source"] == "telegram"
    assert not tg.sent("createForumTopic")
    svc.finish(sid, "Here is the plan")
    await wait_for(lambda: any(p.get("text") == "Here is the plan" for p in tg.sent()), what="answer")
    ans = _bot("Here is the plan", tg)
    assert ans["reply_parameters"]["message_id"] == mid and ans.get("message_thread_id") is None
    # the answer's message id (bound to the session)
    bound = gateway._msgs_all()
    answer_mid = max(int(k.split(":")[1]) for k, v in bound.items() if v.get("sid") == sid)
    tg.message("and the budget?", **_reply_to(ans, answer_mid))
    await wait_for(lambda: len(svc.sent) == 2, what="continued")
    assert svc.sent[1]["sid"] == sid
    assert "Replying to" not in svc.sent[1]["text"]               # the bot's own answer is not quoted back
    # replying to my own first message continues it too
    svc.finish(sid, "Budget: 1k")
    await wait_for(lambda: any(p.get("text") == "Budget: 1k" for p in tg.sent()), what="second answer")
    tg.message("one more", reply_to_message={"message_id": mid, "from": {"id": 555, "is_bot": False}, "text": "x"})
    await wait_for(lambda: len(svc.sent) == 3, what="reply to own message")
    assert svc.sent[2]["sid"] == sid


async def test_simple_mode_continue_button_and_commands(api, tg, svc):
    await _link_simple(api, tg)
    sid, _ = await _start(tg, svc)
    svc.finish(sid, "done")
    await wait_for(lambda: any(p.get("text") == "done" for p in tg.sent()), what="answer")
    # a new message (not a reply): "↩ Continue" the last session is offered first
    n = len(tg.sent())
    tg.message("also this")
    await wait_for(lambda: any("Where should" in (p.get("text") or "") for p in tg.sent()[n:]), what="where? 2")
    where = next(p for p in tg.sent()[n:] if "Where should" in (p.get("text") or ""))
    first = where["reply_markup"]["inline_keyboard"][0][0]
    assert first["callback_data"] == "w:0:s" and "Continue" in first["text"]
    tg.callback("w:0:s")
    await wait_for(lambda: len(svc.sent) == 2, what="continued")
    assert svc.sent[1]["sid"] == sid and svc.sent[1]["text"] == "also this"
    # /stop without a reply: the last session
    tg.message("/stop")
    await wait_for(lambda: sid in svc.stopped, what="/stop")
    # /status replying to nothing still knows the session; /sessions lists it and a tap posts a card to reply to
    tg.message("/sessions")
    await wait_for(lambda: any(p.get("reply_markup") and "Recent sessions" in (p.get("text") or "")
                               for p in tg.sent()), what="/sessions")
    tg.callback(f"o:{sid}")
    await wait_for(lambda: any("Reply to this message" in (p.get("text") or "") for p in tg.sent()), what="card")
    # /help is the simple one
    tg.message("/help")
    await wait_for(lambda: any("continue a recent session" in (p.get("text") or "") for p in tg.sent()), what="/help")


async def test_bell_follows_the_turn_not_the_session(api, tg, svc):
    await _link_simple(api, tg)
    config.update_config(public_url="https://ui.example.com")
    sid, _ = await _start(tg, svc)
    svc.update_session(sid, notify=True)
    svc.finish(sid, "phone answer")                              # a Telegram turn: answered, no bell
    await wait_for(lambda: any(p.get("text") == "phone answer" for p in tg.sent()), what="answer")
    await asyncio.sleep(0.3)
    assert not any("✅ <b>" in (p.get("text") or "") for p in tg.sent())
    # the same session continued in the web UI: the bell rings in the main chat (it used to stay silent)
    svc.send_message(sid, "from the browser", source="web")
    svc.finish(sid, "web answer")
    await wait_for(lambda: any("✅ <b>" in (p.get("text") or "") for p in tg.sent()), what="bell")
    bell = next(p for p in tg.sent() if "✅ <b>" in (p.get("text") or ""))
    assert bell.get("message_thread_id") is None and not bell.get("disable_notification")
    bound = gateway._msgs_all()
    assert sum(1 for v in bound.values() if v.get("sid") == sid) >= 3    # message, answer, bell…
    # a job's turn never rings
    job = svc.create_session(TOPIC, title="Nightly", source="cron", cron=True, notify=True)["id"]
    svc.send_message(job, "run", source="cron")
    n = len(tg.sent())
    svc.finish(job, "ok")
    await asyncio.sleep(0.3)
    assert len(tg.sent()) == n


def test_mode_of_older_installs(mx_state):
    def set_tg(**kw) -> None:
        def fn(t: dict) -> None:
            t.pop("mode", None)
            t.update(kw)
        gateway.mutate_tg(fn)
    set_tg(session_threads={}, threads={})
    assert gateway.mode() == "simple"                              # nothing yet: a new install
    set_tg(threads={"#crons": 5, "#alerts": 6})
    assert gateway.mode() == "threads"                             # it had threads: kept
    set_tg(mirror_web=True, mirror_web_chosen=True)
    assert gateway.mode() == "mirror"
    gateway.mutate_tg(lambda t: t.__setitem__("chat_id", 555))
    gateway._settle_mode()
    assert config.read_json(config.config_path(), {})["telegram"]["mode"] == "mirror"
    gateway.update_settings(mirror_web=False)                      # older clients
    assert gateway.mode() == "threads"


async def test_threads_to_simple_deletes_the_threads(api, tg, svc):
    await _link(api, tg)                                           # threads mode (test default)
    web = svc.create_session(TOPIC, title="Plan", source="web")["id"]
    await api.post("/api/telegram/sync")
    tid = gateway.thread_of(web)
    agent_tid = tg.next_thread + 100
    tg.topics[agent_tid] = "🤖 Writer · acme/blog"
    gateway.mutate_tg(lambda t: t.__setitem__("agent_threads", {"projects/acme/topics/blog/agents/writer":
                                                                  {"tid": agent_tid, "name": "x"}}))
    r = await api.put("/api/telegram/settings", json={"mode": "simple"})
    assert r.json()["mode"] == "simple" and r.json()["deleting"] == 4  # the session + Crons, Alerts, Notifications
    await wait_for(lambda: gateway.tg_config()["session_threads"] == {} and gateway.tg_config()["threads"] == {},
                   what="purged")
    assert tid not in tg.topics and agent_tid in tg.topics         # agents keep their thread
    # back to threads: the sync makes them again
    await api.put("/api/telegram/settings", json={"mode": "threads"})
    await api.post("/api/telegram/sync")
    assert gateway.thread_of(web) and set(gateway.tg_config()["threads"]) == {"#crons", "#alerts", "#feed"}


async def test_health_problems_become_alerts(api, tg, svc, monkeypatch):
    await _link_simple(api, tg)
    from maxxing import health
    monkeypatch.setattr(gateway, "_feed_alerts", lambda: False)   # an older feed: the bridge posts them itself
    issues = [{"id": "aaa", "level": "error", "code": "disk_full", "text": "Disk 97 % full", "seen": False},
              {"id": "bbb", "level": "warn", "code": "cron_failed", "text": "Job failed", "seen": False}]
    seen: list = []
    monkeypatch.setattr(health, "collect", lambda force=False: {"issues": [dict(i) for i in issues]})
    monkeypatch.setattr(health, "mark_seen", lambda iid, s=True: seen.append(iid) or True)
    gw = gateway.gateway()
    await gw._health_pass()
    sent = [p for p in tg.sent() if "Disk" in (p.get("text") or "")]
    assert len(sent) == 1 and sent[0]["text"].startswith("🚨") and not sent[0].get("disable_notification")
    assert sent[0]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "h:aaa"
    assert not any("Job failed" in (p.get("text") or "") for p in tg.sent())   # failed jobs: their own report
    await gw._health_pass()
    assert len([p for p in tg.sent() if "Disk" in (p.get("text") or "")]) == 1   # once
    mid = gateway.load_state()["health"]["aaa"]["mid"]
    tg.callback("h:aaa", message_id=mid)
    await wait_for(lambda: seen == ["aaa"], what="seen")
    await wait_for(lambda: any("✓ Seen" in (p.get("text") or "") for p in tg.sent("editMessageText")), what="edited")
    issues.clear()                                                 # fixed
    await gw._health_pass()
    assert any("Resolved" in (p.get("text") or "") for p in tg.sent("editMessageText"))
    assert gateway.load_state()["health"] == {}
    # notify_system off: nothing
    gateway.update_settings(notify_system=False)
    issues.append({"id": "ccc", "level": "warn", "code": "backup_old", "text": "Backup old", "seen": False})
    await gw._health_pass()
    assert not any("Backup old" in (p.get("text") or "") for p in tg.sent())


async def test_feed_alerts_buttons_call_feed_act(api, tg, svc, monkeypatch):
    await _link_simple(api, tg)
    from maxxing import feed, health
    acted: list = []
    ev = {"id": 7, "source": "agents", "level": "warning", "title": "Writer asks", "body": "rm -rf build",
          "url": "/agents/acme/blog/writer", "count": 1, "read": False, "ref": "approval:r1", "agent": None,
          "actions": [{"id": "allow", "label": "Allow", "style": "primary"},
                      {"id": "deny", "label": "Deny", "style": "danger"},
                      {"id": "open", "label": "Open", "style": "link"}],
          "resolved": None, "resolution": None, "telegram": "off"}

    def act(eid, action, by="web"):
        acted.append((eid, action, by))
        return {**ev, "actions": [], "resolved": 1.0, "resolution": "Allowed on Telegram"}
    monkeypatch.setattr(feed, "act", act, raising=False)
    gateway.post_alert(ev)                                         # an approval goes even with "off"
    await wait_for(lambda: any("Writer asks" in (p.get("text") or "") for p in tg.sent()), what="alert")
    p = _bot("Writer asks", tg)
    assert [b["callback_data"] for b in p["reply_markup"]["inline_keyboard"][0]] == ["al:7:allow", "al:7:deny"]
    assert not p.get("disable_notification") and p.get("message_thread_id") is None
    mid = gateway._notes()["al:7"][1]
    # an older message with the same event id (feed.db recreated) decides nothing, and loses its buttons
    tg.callback("al:7:allow", message_id=mid + 100)
    await wait_for(lambda: any(q.get("message_id") == mid + 100 for q in tg.sent("editMessageReplyMarkup")),
                   what="stale buttons cleared")
    assert acted == []
    tg.callback("al:7:allow", message_id=mid)
    await wait_for(lambda: acted == [(7, "allow", "telegram")], what="act")
    await wait_for(lambda: any("Allowed on Telegram" in (q.get("text") or "") for q in tg.sent("editMessageText")),
                   what="edited")
    await wait_for(lambda: "al:7" not in gateway._notes(), what="forgotten")   # resolved: forgotten
    # "off" sends nothing else; "silent" is silent
    gateway.post_alert({**ev, "id": 8, "ref": "agent:x#failed", "title": "Quiet one", "actions": []})
    gateway.post_alert({**ev, "id": 9, "ref": "agent:x#failed", "title": "Soft one", "actions": [],
                        "telegram": "silent", "level": "error", "count": 3})
    await wait_for(lambda: any("Soft one" in (q.get("text") or "") for q in tg.sent()), what="silent")
    assert _bot("Soft one", tg).get("disable_notification") and "×3" in _bot("Soft one", tg)["text"]
    assert not any("Quiet one" in (q.get("text") or "") for q in tg.sent())
    # the feed carries the alerts: the bridge no longer posts health problems itself
    gw = gateway.gateway()
    monkeypatch.setattr(health, "collect", lambda force=False: {"issues": [
        {"id": "zzz", "level": "error", "code": "disk_full", "text": "Disk full", "seen": False}]})
    await gw._health_pass()
    assert not any("Disk full" in (q.get("text") or "") for q in tg.sent())


async def test_an_alert_answered_while_it_was_sent_loses_its_buttons(api, tg, svc):
    await _link_simple(api, tg)
    from maxxing import feed
    ev = feed.post("Writer asks", "git push", "warning", "agents", "/agents/acme/blog/writer", notify=False,
                   ref="approval:r2", actions=[{"id": "allow", "label": "Allow", "style": "primary"},
                                               {"id": "deny", "label": "Deny", "style": "danger"}])
    feed.update(ev["id"], resolve=True, resolution="Allowed", notify=False)   # answered on the web meanwhile
    gateway.post_alert({**ev, "telegram": "loud"})                           # the send that was under way
    assert _bot("Writer asks", tg)["reply_markup"]["inline_keyboard"][0]
    edit = next(e for e in tg.sent("editMessageText") if "Writer asks" in e["text"])
    assert "Allowed" in edit["text"] and edit["reply_markup"] == {"inline_keyboard": []}
    assert f"al:{ev['id']}" not in gateway._notes()


async def test_an_alert_cut_on_telegram_says_so_and_cannot_be_sent_from_there(api, tg, svc, monkeypatch):
    await _link_simple(api, tg)
    from maxxing import feed
    acted: list = []
    real = feed.act
    monkeypatch.setattr(feed, "act", lambda eid, action, by="web": acted.append(action) or real(eid, action, by))
    body = "From: me@x\nTo: you@y\nSubject: Contract\n\n" + "word " * 400 + "the end [...]"
    ev = feed.post("Writer wants to send an e-mail", body, "warning", "mail", "/mail", notify=False, ref="mailsend:o_1",
                   actions=[{"id": "allow", "label": "Send", "style": "primary"},
                            {"id": "deny", "label": "Refuse", "style": "danger"},
                            {"id": "open", "label": "Open", "style": "link"}])
    gateway.post_alert({**ev, "telegram": "loud", "attachments": [{"name": "contract.pdf"}, "id-scan.jpg"]})
    p = _bot("Writer wants to send", tg)
    assert "(cut, open it to see all)" in p["text"] and "📎 contract.pdf, id-scan.jpg" in p["text"]
    assert [b["callback_data"] for b in p["reply_markup"]["inline_keyboard"][0]] == [f"al:{ev['id']}:deny"]
    # a Send button of a message posted before: refused, nothing sent
    tg.callback(f"al:{ev['id']}:allow", message_id=gateway._notes()[f"al:{ev['id']}"][1])
    await wait_for(lambda: any(q.get("text") == "…(cut, open it to see all)" for q in tg.sent("answerCallbackQuery")),
                   what="refused")
    assert acted == [] and feed.get(ev["id"])["resolved"] is None
    # short enough: whole, Send stays
    short = feed.post("Writer wants to send an e-mail", "To: you@y\n\nHello", "warning", "mail", notify=False,
                      ref="mailsend:o_2", actions=[{"id": "allow", "label": "Send", "style": "primary"}])
    assert "cut" not in gateway._alert_html(short) and gateway._alert_markup(short)


def test_message_map_keeps_the_newest_and_takes_in_the_old_file(mx_state, monkeypatch):
    import time
    old = gateway._msgs_path().with_name("messages.json")
    old.parent.mkdir(parents=True, exist_ok=True)
    config.write_json(old, {"555:1": {"sid": "s_old", "at": time.time() - 10},
                            "555:2": {"sid": "s_gone", "at": time.time() - 61 * 86400}})
    assert gateway.bound(555, 1) == {"sid": "s_old"} and not old.exists()
    monkeypatch.setattr(gateway, "MSGS_KEEP", 3)
    gateway.bind_messages(555, [10, 11], {"sid": "s_a"})
    gateway.bind_messages(555, [12], {"agent": "projects/acme/topics/blog/agents/writer"})
    gateway.bind_messages(555, [10], {"sid": "s_b"})                       # bound again: newest
    assert list(gateway._msgs_all()) == ["555:11", "555:12", "555:10"]     # the oldest and the 60-day-old went
    assert gateway.bound(555, 10) == {"sid": "s_b"} and gateway.bound(555, 1) is None and gateway.bound(556, 10) is None


async def test_reply_to_an_agent_message_in_the_main_chat(api, tg, svc, monkeypatch):
    await _link_simple(api, tg)
    got: list = []

    async def fake(self, msgs, path, texts):
        got.append((path, *texts))
    monkeypatch.setattr(gateway.Gateway, "_agent_message", fake)
    gateway.bind_messages(555, [4242], {"agent": "projects/acme/topics/blog/agents/writer"})
    tg.message("do it again", reply_to_message={"message_id": 4242, "from": {"id": 1, "is_bot": True}, "text": "r"})
    await wait_for(lambda: got, what="agent")
    assert got[0] == ("projects/acme/topics/blog/agents/writer", "do it again") and not svc.sent
