"""Telegram bridge reliability: replies matched to their own turn, typing that stops, closed threads, restarts,
flood limits, system alerts (fake Bot API, fake sessions service)."""
from __future__ import annotations

import asyncio
import fcntl
import json
import os

from _conn_helpers import mx_state, wait_for  # noqa: F401  (fixture)
from maxxing import config
from maxxing.api import telegram as tg_api
from maxxing.telegram import gateway
from test_telegram import TOPIC, _link, _open, _thread, api, svc, tg, ws  # noqa: F401  (fixtures)


def _texts(tg, tid=None) -> list[str]:
    return [p["text"] for p in tg.sent() if tid is None or p.get("message_thread_id") == tid]


# ---- 1. replies go to the turn they belong to ----------------------------------------------------
async def test_web_turn_is_not_sent_as_the_phone_answer(api, tg, svc):
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    svc.send_message(sid, "web question", source="web")              # a web turn is running
    tg.message("phone question", thread=tid)                          # queued behind it
    await wait_for(lambda: len(svc.sent) == 2, what="queued")
    await wait_for(lambda: any("Queued" in t for t in _texts(tg, tid)), what="queued notice")
    svc.finish(sid, "WEB ANSWER")
    await asyncio.sleep(0.4)
    assert not any("WEB ANSWER" in t for t in _texts(tg))             # mirror off: not sent at all
    assert gateway.gateway()._pending[sid]["refs"] == [svc.sent[1]["ref"]]
    svc.finish(sid, "PHONE ANSWER")
    await wait_for(lambda: any("PHONE ANSWER" in t for t in _texts(tg, tid)), what="phone answer")
    await wait_for(lambda: gateway.gateway()._pending == {}, what="nothing pending")


async def test_compaction_summary_is_never_the_answer(api, tg, svc):
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    tg.message("hello again", thread=tid)
    await wait_for(lambda: svc.sent, what="sent")
    svc.finish(sid, "SUMMARY OF THE SESSION", kind="compact")         # idle compaction runs first
    await asyncio.sleep(0.4)
    assert not any("SUMMARY" in t for t in _texts(tg))
    assert sid in gateway.gateway()._pending
    svc.finish(sid, "the real answer")
    await wait_for(lambda: any("the real answer" in t for t in _texts(tg, tid)), what="answer")
    await wait_for(lambda: gateway.gateway()._pending == {}, what="nothing pending")


# ---- 2. typing stops after a stop / steer --------------------------------------------------------
async def test_typing_stops_after_a_web_stop(api, tg, svc, monkeypatch):
    monkeypatch.setattr(gateway, "RECHECK_EVERY", 0.1)
    monkeypatch.setattr(gateway, "REF_GRACE", 0.2)
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    tg.message("one", thread=tid)
    tg.message("two", thread=tid)
    await wait_for(lambda: len(svc.sent) == 2, what="sent")
    svc.stop(sid)                                                     # from the web UI: queue cleared, no turn end
    await wait_for(lambda: gateway.gateway()._pending == {}, timeout=5, what="typing stopped")


async def test_steer_merges_and_typing_ends(api, tg, svc):
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    for t in ("first", "second", "third"):
        tg.message(t, thread=tid)
    await wait_for(lambda: len(svc.sent) == 3, what="sent")
    svc.steer(sid)                                                    # second + third -> one message
    svc.finish(sid, "interrupted answer")
    await wait_for(lambda: any("interrupted answer" in t for t in _texts(tg, tid)), what="first answer")
    assert len(gateway.gateway()._pending[sid]["refs"]) == 2
    svc.finish(sid, "merged answer")
    await wait_for(lambda: any("merged answer" in t for t in _texts(tg, tid)), what="merged answer")
    await wait_for(lambda: gateway.gateway()._pending == {}, what="nothing pending")


async def test_stop_from_telegram_clears_typing(api, tg, svc):
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    tg.message("long job", thread=tid)
    await wait_for(lambda: svc.sent, what="sent")
    tg.message("/stop", thread=tid)
    await wait_for(lambda: svc.stopped == [sid], what="stopped")
    await wait_for(lambda: gateway.gateway()._pending == {}, what="typing stopped")


# ---- 3. a closed thread is reopened, not duplicated ------------------------------------------------
async def test_closed_thread_is_reopened(api, tg, svc):
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    alerts = _thread("#alerts")
    before = dict(gateway.tg_config()["threads"])
    tg.fail_once["sendMessage"] = (400, "Bad Request: TOPIC_CLOSED")
    gateway.alert("New sign-in", loud=True)
    await wait_for(lambda: tg.sent("reopenForumTopic"), what="reopened")
    assert tg.sent("reopenForumTopic")[0]["message_thread_id"] == alerts
    await wait_for(lambda: any("New sign-in" in t for t in _texts(tg, alerts)), what="sent in the same thread")
    assert gateway.tg_config()["threads"] == before
    # the session thread: the answer lands in it, no new thread
    tg.message("hi", thread=tid)
    await wait_for(lambda: svc.sent, what="sent")
    n = len(tg.sent("createForumTopic"))
    tg.fail_once["sendMessage"] = (400, "Bad Request: TOPIC_CLOSED")
    svc.finish(sid, "answer in the closed thread")
    await wait_for(lambda: any("answer in the closed thread" in t for t in _texts(tg, tid)), what="answer")
    assert gateway.thread_of(sid) == tid and len(tg.sent("createForumTopic")) == n
    # without the gateway (another process): same
    await tg_api.shutdown()
    tg.fail_once["sendMessage"] = (400, "Bad Request: TOPIC_CLOSED")
    assert await asyncio.to_thread(gateway._send_sync, gateway.ALERTS, ["direct"], False)
    assert any(t == "direct" for t in _texts(tg, alerts)) and gateway.tg_config()["threads"] == before


def test_closed_is_not_gone():
    from maxxing.telegram.client import TelegramError
    closed = TelegramError(400, "Bad Request: TOPIC_CLOSED")
    assert gateway._thread_closed(closed) and not gateway._thread_gone(closed)
    assert gateway._thread_gone(TelegramError(400, "Bad Request: message thread not found"))
    assert not gateway._thread_closed(TelegramError(400, "Bad Request: message thread not found"))


# ---- 4. reopen_thread does not race the sync ------------------------------------------------------
async def test_reopen_thread_waits_for_the_sync(api, tg, svc):
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    gw = gateway.gateway()
    gateway._drop_session_thread(sid)
    n = len(tg.sent("createForumTopic"))
    await gw._sync_lock.acquire()                                    # a sync is running...
    task = asyncio.ensure_future(gw.reopen_thread(sid))
    await asyncio.sleep(0.2)
    gateway._set_session_thread(sid, 777, "made by the sync")         # ... and makes the thread
    gw._sync_lock.release()
    assert await task == 777
    assert len(tg.sent("createForumTopic")) == n


# ---- 5 / 6. system alerts go to "Alerts" -----------------------------------------------------------
async def test_system_alerts_go_to_the_alerts_thread(api, tg, svc):
    await _link(api, tg)
    alerts = _thread("#alerts")
    assert gateway.system_alert("Claude Code could not update to 9.9.9")
    await wait_for(lambda: any("could not update" in t for t in _texts(tg, alerts)), what="alert")
    config.update_config(telegram={"login_alerts": False, "notify_crons": False})
    assert gateway.system_alert("Harness Maxxing 2.0 did not start and was rolled back")   # not tied to those
    await wait_for(lambda: any("rolled back" in t for t in _texts(tg, alerts)), what="rollback alert")
    r = await api.put("/api/telegram/settings", json={"notify_system": False})
    assert r.status_code == 200 and gateway.status()["settings"]["notify_system"] is False
    assert not gateway.system_alert("muted")


def test_update_notices_use_system_alert(mx_state, monkeypatch):
    from maxxing import cmd_core, deps
    sent = []
    monkeypatch.setattr(gateway, "system_alert", lambda text, loud=True: sent.append((text, loud)) or True)
    monkeypatch.setattr(gateway, "notify_cron", lambda text: sent.append(("CRONS", text)))
    cmd_core._notify("Harness Maxxing 9 did not start and was rolled back")
    assert sent[-1] == ("Harness Maxxing 9 did not start and was rolled back", True)
    assert cmd_core.notify_update({"latest": "9", "current": "8", "behind": 3}) is True
    assert sent[-1][1] is False and "9 is available" in sent[-1][0]
    assert deps.notify_vulnerable({"vulnerable": [{"where": "pip", "name": "x", "version": "1", "ids": ["CVE-1"]}]})
    assert "Known vulnerability" in sent[-1][0]
    assert not any(s[0] == "CRONS" for s in sent)


# ---- 7. "where?" survives a restart ---------------------------------------------------------------
async def test_where_question_survives_a_restart(api, tg, svc):
    await _link(api, tg)
    tg.message("remember the milk")
    await wait_for(lambda: any("Where should" in t for t in _texts(tg)), what="where?")
    await wait_for(lambda: json.loads(gateway._new_path().read_text()).get("0", {}).get("asked"), what="saved")
    await tg_api.shutdown()
    await tg_api.startup()
    await wait_for(lambda: gateway.gateway() and 0 in gateway.gateway()._new, what="restored")
    tg.callback(f"w:0:{gateway._path_hash(TOPIC)}")
    await wait_for(lambda: svc.sent, what="replayed")
    assert svc.sent[0]["text"] == "remember the milk"
    await wait_for(lambda: json.loads(gateway._new_path().read_text()) == {}, what="forgotten")


async def test_session_being_made_at_a_restart_is_announced(api, tg, svc):
    config.write_json(gateway._new_path(), {"0": {"msgs": [{"text": "lost one"}], "name": "", "title": "",
                                                  "chat": 555, "thread": None, "asked": 9, "starting": True}})
    await _link(api, tg)
    await wait_for(lambda: any("1 message(s) not handled" in t for t in _texts(tg)), what="told")


async def test_album_cut_by_a_restart_is_asked_again(api, tg, svc, monkeypatch):
    monkeypatch.setattr(gateway, "MEDIA_GROUP_WAIT", 30)
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    tg.add_file("P1", b"\xff\xd8jpeg", "photos/1.jpg")
    for _ in range(2):
        tg.message("", thread=tid, media_group_id="g1", photo=[{"file_id": "P1", "width": 1}])
    await wait_for(lambda: gateway._inflight_path().exists() and len(json.loads(gateway._inflight_path().read_text())) == 2,
                   what="in flight")
    await tg_api.shutdown()
    await tg_api.startup()
    await wait_for(lambda: [t for t in _texts(tg, tid) if "send it again" in t], what="asked again")
    assert len([t for t in _texts(tg, tid) if "send it again" in t]) == 1


# ---- 8. a failed start keeps the messages --------------------------------------------------------
async def test_failed_start_keeps_the_messages(api, tg, svc, monkeypatch):
    await _link(api, tg)
    real = svc.create_session
    boom = {"n": 1}

    def flaky(*a, **k):
        if boom["n"]:
            boom["n"] -= 1
            raise RuntimeError("disk full")
        return real(*a, **k)
    monkeypatch.setattr(svc, "create_session", flaky)
    tg.message("keep me")
    await wait_for(lambda: 0 in gateway.gateway()._new and gateway.gateway()._new[0]["asked"], what="where?")
    tg.callback(f"w:0:{gateway._path_hash(TOPIC)}")
    await wait_for(lambda: any("Could not start the session: disk full" in t for t in _texts(tg)), what="told")
    assert gateway.gateway()._new[0]["msgs"][0]["text"] == "keep me"
    tg.callback(f"w:0:{gateway._path_hash(TOPIC)}")                   # tapped again: it works
    await wait_for(lambda: svc.sent, what="replayed")
    assert svc.sent[0]["text"] == "keep me" and gateway.gateway()._new == {}


# ---- 9. main-chat commands ------------------------------------------------------------------------
async def test_main_chat_commands_in_topics_mode(api, tg, svc):
    await _link(api, tg)
    await _open(api, svc, "Main")
    tg.message("/sessions")
    await wait_for(lambda: any("Open sessions" in t for t in _texts(tg)), what="/sessions")
    for cmd in ("stop", "model", "close"):
        tg.message(f"/{cmd}")
        await wait_for(lambda c=cmd: any(t.startswith(f"/{c} is about one session") for t in _texts(tg)), what=cmd)
    assert gateway.gateway()._new == {} and not svc.stopped
    tg.message("a real message")                                      # then /status: the buttons are there
    await wait_for(lambda: any("Where should" in t for t in _texts(tg)), what="where?")
    tg.message("/status")
    await wait_for(lambda: any("Choose where" in t for t in _texts(tg)), what="pick first")


# ---- 10. a message typed while the session is being made -------------------------------------------
async def test_message_while_the_session_is_being_made(api, tg, svc, monkeypatch):
    await _link(api, tg)
    gw = gateway.gateway()
    real = gw.new_session

    async def slow(*a, **k):
        await asyncio.sleep(0.5)                                      # createForumTopic is slow
        return await real(*a, **k)
    monkeypatch.setattr(gw, "new_session", slow)
    tg.message("first")
    await wait_for(lambda: 0 in gw._new and gw._new[0]["asked"], what="where?")
    tg.callback(f"w:0:{gateway._path_hash(TOPIC)}")
    await wait_for(lambda: gw._new.get(0, {}).get("starting"), what="starting")
    tg.message("second")
    await wait_for(lambda: len(svc.sent) == 2, what="both sent")
    assert svc.sent[0]["sid"] == svc.sent[1]["sid"] and [m["text"] for m in svc.sent] == ["first", "second"]
    assert len(svc.sessions) == 1
    assert sum("Where should" in t for t in _texts(tg)) == 1


# ---- 11. service messages are ignored -------------------------------------------------------------
async def test_service_messages_are_ignored(api, tg, svc):
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    n = len(tg.sent())
    tg.message("", thread=tid, pinned_message={"message_id": 3})
    tg.message("", thread=tid, forum_topic_edited={"name": "x"})
    tg.message("", thread=tid, forum_topic_closed={})
    tg.message("", pinned_message={"message_id": 4})                  # main chat: no "where?" either
    tg.message("ping", thread=tid)
    await wait_for(lambda: svc.sent, what="the real message")
    await asyncio.sleep(0.2)
    assert not any("not supported" in t or "Where should" in t for t in _texts(tg)[n:])
    assert gateway.gateway()._new == {}


# ---- 12. flood limits ------------------------------------------------------------------------------
async def test_flood_limit_at_setup_does_not_turn_topics_off(api, tg, svc):
    tg.fail["createForumTopic"] = (429, "Too Many Requests: retry after 1")
    r = await api.post("/api/telegram/token", json={"token": tg.token})
    assert r.status_code == 200
    link = (await api.post("/api/telegram/link")).json()
    tg.message(f"/start {link['code']}")
    await wait_for(lambda: gateway.link_status()["linked"], what="link")
    await wait_for(lambda: gateway.load_state().get("sync_error"), timeout=20, what="sync error")
    assert gateway.load_state().get("topics_enabled") is not False and gateway.threaded()
    tg.fail.clear()
    r = await api.post("/api/telegram/sync")
    assert r.json()["topics_enabled"] is True and len(gateway.tg_config()["threads"]) == 3


async def test_flood_limit_stops_the_session_sync(api, tg, svc):
    await _link(api, tg)
    for i in range(3):
        svc.create_session(TOPIC, title=f"S{i}", source="web")
    tg.fail["createForumTopic"] = (429, "Too Many Requests: retry after 1")
    n = len(tg.sent("createForumTopic"))
    r = (await api.post("/api/telegram/sync")).json()
    assert "slow down" in r["error"] or "Too Many" in r["error"]
    tried = {p["name"] for p in tg.sent("createForumTopic")[n:]}
    assert tried == {"acme/blog · S0"}                                # the pass stopped at the first one


# ---- 13. notifications under flood limits -----------------------------------------------------------
def test_direct_report_parts_are_each_retried(mx_state, tg, monkeypatch):
    config.set_secret("telegram_token", tg.token)
    config.update_config(telegram={"chat_id": 555, "threads": {gateway.CRONS: 11}})
    monkeypatch.setattr(gateway.time, "sleep", lambda s: None)
    tg.fail_once["sendMessage"] = (502, "Bad Gateway")
    assert gateway._send_sync(gateway.CRONS, ["part 1", "part 2", "part 3"], False)
    assert [p["text"] for p in tg.sent()][-3:] == ["part 1", "part 2", "part 3"]
    tg.fail["sendMessage"] = (403, "Forbidden: bot was blocked by the user")
    assert not gateway._send_sync(gateway.CRONS, ["a", "b"], False)
    assert len([p for p in tg.sent() if p["text"] in ("a", "b")]) == 2   # the 2nd part is still tried


async def test_gateway_send_waits_out_a_server_error(api, tg, svc):
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    tg.fail_once["sendMessage"] = (500, "Internal Server Error")
    await gateway.gateway().send_parts(555, tid, ["one", "two"])
    assert [t for t in _texts(tg, tid) if t in ("one", "two")] == ["one", "one", "two"]    # retried, in order


# ---- 14. the cron report is sent after the job's lock is released ------------------------------------
def test_cron_report_after_the_lock(mx_state, monkeypatch):
    from maxxing import crons
    job = crons.create_job({"name": "quick", "schedule": "@hourly", "command": "true", "notify": "always"})
    free = []

    def notify(j, run, answer=None):
        with open(crons._lock_path(job["id"]), "w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                free.append(True)
                fcntl.flock(f, fcntl.LOCK_UN)
            except BlockingIOError:
                free.append(False)
    monkeypatch.setattr(crons, "_notify", notify)
    assert crons.run_job(job["id"])["ok"]
    assert free == [True]


# ---- 15. a session that cannot be read just now keeps its thread ------------------------------------
async def test_unreadable_session_keeps_its_thread(api, tg, svc):
    await _link(api, tg)
    sid, tid = await _open(api, svc)
    svc.unreadable.add(sid)
    await api.post("/api/telegram/sync")
    assert gateway.thread_of(sid) == tid and tid in tg.topics
    svc.unreadable.clear()
    svc.sessions.pop(sid)                                             # really gone now
    await api.post("/api/telegram/sync")
    assert gateway.thread_of(sid) is None and tid not in tg.topics


# ---- 16. turning the feed's Telegram option on creates its thread -----------------------------------
async def test_feed_option_creates_its_thread(api, tg, svc, monkeypatch):
    from maxxing import bus, feed
    monkeypatch.setattr(bus, "_loop", asyncio.get_running_loop())     # bare app: no bus bound
    feed.save_settings(telegram=False)
    r = await api.post("/api/telegram/token", json={"token": tg.token})
    assert r.status_code == 200
    link = (await api.post("/api/telegram/link")).json()
    tg.message(f"/start {link['code']}")
    await wait_for(lambda: len(gateway.tg_config()["threads"]) == 2, what="crons + alerts")
    await asyncio.sleep(0.3)
    feed.save_settings(telegram=True)
    await wait_for(lambda: gateway.FEED in gateway.tg_config()["threads"], timeout=10, what="notifications thread")



# ---- the sessions service ties each message to its turn ---------------------------------------------
def test_service_records_the_refs_of_each_turn(mx, monkeypatch):
    from maxxing.sessions import runner, service, store
    monkeypatch.setattr(service, "_spawn", lambda sid: None)
    monkeypatch.setattr(service, "_signal", lambda pid, sig: None)
    m = store.new_meta("", "Refs")
    store.create(m)
    sid = m["id"]
    service.send_message(sid, "one", source="telegram", ref="r1")
    service.send_message(sid, "two", source="telegram", ref="r2")
    service.send_message(sid, "web", source="web")
    assert service.live_refs(sid) == {"r1", "r2"}
    r = runner.Runner(sid)
    item = r._pop(None)
    assert item["refs"] == ["r1"] and store.read(sid)["turn_refs"] == ["r1"]
    service.send_message(sid, "three", source="telegram", ref="r3")
    store.update(sid, pid=os.getpid(), state="running")                 # no runner holds the lock in this test
    assert service.steer(sid)["steered"]                                 # two + web + three -> one message
    assert store.read(sid)["queue"][0]["refs"] == ["r2", "r3"]
    r._record(runner.Attempt(rc=0), item)
    assert store.read(sid)["last_turn"]["refs"] == ["r1"]
    ended = service._ended(service.public(store.read(sid)), store.read(sid))
    assert ended["last_turn"]["source"] == "telegram" and "last_turn" not in service.public(store.read(sid))
    store.update(sid, pid=None)
    service.stop(sid)                                                   # the queue goes: nothing left to answer
    assert service.live_refs(sid) == set()
