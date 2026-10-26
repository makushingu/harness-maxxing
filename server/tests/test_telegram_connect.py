"""Telegram setup / linking: link codes (stale, wrong, expired), webhook and other pollers at token save,
poll_error vs sync_error, heartbeat, test report, doctor. Against the local fake Bot API (no network)."""
from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx
import pytest

from _conn_helpers import (TG_TOKEN, FakeService, FakeTelegram, FakeWorkspace, bare_app,  # noqa: F401
                           mx_state, wait_for)
from maxxing import cmd_core, config
from maxxing.api import telegram as tg_api
from maxxing.telegram import gateway

CONFLICT = (409, "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running")


@pytest.fixture
def tg(mx_state, monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setenv("MAXXING_TELEGRAM_API", fake.url)
    yield fake
    fake.close()


@pytest.fixture
def api_(tg, mx_state, monkeypatch):
    monkeypatch.setitem(sys.modules, "maxxing.sessions.service", FakeService())
    monkeypatch.setitem(sys.modules, "maxxing.workspace", FakeWorkspace(mx_state / "ws", [("acme", "blog")]))
    monkeypatch.setattr(gateway, "_hooks", False)


@pytest.fixture
async def api(api_):
    app = bare_app(tg_api.router)
    await tg_api.startup()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    await tg_api.shutdown()


async def _linked(api, tg) -> None:
    assert (await api.post("/api/telegram/token", json={"token": TG_TOKEN})).status_code == 200
    code = (await api.post("/api/telegram/link")).json()["code"]
    tg.message(f"/start {code}")
    await wait_for(lambda: gateway.link_status()["linked"], what="link")


def _to(tg, chat: int) -> list[dict]:
    return [p for p in tg.sent() if p["chat_id"] == chat]


# ---- link codes -------------------------------------------------------------------------------
async def test_start_pressed_before_the_link_is_ignored_then_the_link_works(api, tg):
    assert (await api.post("/api/telegram/token", json={"token": TG_TOKEN})).status_code == 200
    tg.message("/start", date=int(time.time()) - 60)                 # Start pressed in Telegram first
    link = (await api.post("/api/telegram/link")).json()
    assert link["expires_in"] == gateway.LINK_TTL and link["expires_at"] > time.time()
    await asyncio.sleep(0.5)
    assert _to(tg, 555) == [] and 555 not in (gateway.load_state().get("refused") or [])
    tg.message(f"/start {link['code']}")
    await wait_for(lambda: gateway.link_status()["linked"], what="link")


async def test_start_without_code_or_wrong_code_is_explained_not_refused(api, tg):
    await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    await api.post("/api/telegram/link")
    tg.message("/start", chat_id=777, user_id=777, **{"from": {"id": 777, "is_bot": False, "language_code": "fr"}})
    tg.message("/start NOPE", chat_id=777, user_id=777)
    await wait_for(lambda: len(_to(tg, 777)) == 2, what="two explanations")
    a, b = _to(tg, 777)
    assert "expiré" in a["text"] and "Réglages" in a["text"] and "expired" in b["text"]
    assert 777 not in (gateway.load_state().get("refused") or [])


async def test_expired_code_is_explained_and_a_new_link_clears_refused(api, tg):
    await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    code = (await api.post("/api/telegram/link")).json()["code"]
    link = dict(gateway.load_state()["link"])
    gateway.update_state(link={**link, "created": time.time() - 3600, "expires": time.time() - 60}, refused=[777])
    pending = (await api.get("/api/telegram/link")).json()["pending"]
    assert pending["code"] == code and pending["expired"] is True and pending["expires_in"] == 0
    assert gateway.status()["link"]["expired"] is True
    tg.message(f"/start {code}")
    await wait_for(lambda: _to(tg, 555), what="explanation")
    assert "expired" in _to(tg, 555)[0]["text"] and not gateway.link_status()["linked"]
    # older than the grace period: back to the plain refusal
    gateway.update_state(link={**link, "created": time.time() - 3 * 86400, "expires": time.time() - 2 * 86400})
    tg.message("/start again", chat_id=888, user_id=888)
    await wait_for(lambda: _to(tg, 888), what="refusal")
    assert "private" in _to(tg, 888)[0]["text"]
    # a new link forgets who was refused
    await api.post("/api/telegram/link")
    assert gateway.load_state()["refused"] == []
    assert gateway.status()["link"]["expired"] is False


async def test_pending_link_survives_a_page_reload(api, tg):
    await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    link = (await api.post("/api/telegram/link")).json()
    st = (await api.get("/api/telegram")).json()
    assert st["linking"] and st["link"]["code"] == link["code"] and st["link"]["deep_link"] == link["deep_link"]
    tg.message(f"/start {link['code']}")
    await wait_for(lambda: gateway.link_status()["linked"], what="link")
    assert (await api.get("/api/telegram")).json()["link"] is None


# ---- token save: webhook, another program ------------------------------------------------------
async def test_webhook_can_be_removed_then_the_token_saved(api, tg):
    tg.webhook = "https://n8n.example.com/hook"
    r = await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    assert r.status_code == 400 and r.json()["error"] == "webhook_set"
    assert config.get_secret("telegram_token") == ""
    r = await api.post("/api/telegram/webhook/remove", json={"token": TG_TOKEN})
    assert r.status_code == 200 and r.json()["ok"]
    assert ("deleteWebhook", {"drop_pending_updates": False}) in tg.calls and tg.webhook == ""
    assert (await api.post("/api/telegram/token", json={"token": TG_TOKEN})).status_code == 200
    r = await api.post("/api/telegram/webhook/remove", json={"token": "nope"})
    assert r.status_code == 400 and r.json()["error"] == "bad_token"


async def test_webhook_check_failure_is_not_ignored(api, tg):
    tg.fail_once["getWebhookInfo"] = (500, "Internal Server Error")
    r = await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    assert r.status_code == 400 and r.json()["error"] == "webhook_check_failed"
    assert config.get_secret("telegram_token") == ""


async def test_another_poller_is_detected_at_save(api, tg):
    tg.fail_once["getUpdates"] = CONFLICT
    r = await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    assert r.status_code == 400 and r.json()["error"] == "conflict" and "n8n" in r.json()["message"]
    assert config.get_secret("telegram_token") == ""


async def test_saving_the_same_token_again_does_not_conflict_with_itself(api, tg):
    await _linked(api, tg)
    assert (await api.post("/api/telegram/token", json={"token": TG_TOKEN})).status_code == 200
    assert gateway.status()["running"] and gateway.link_status()["linked"]


async def test_a_conflict_after_the_token_was_saved_restarts_our_poller(api, tg):
    await _linked(api, tg)
    tg.fail["getUpdates"] = CONFLICT
    r = await api.post("/api/telegram/token", json={"token": TG_TOKEN})
    assert r.status_code == 400 and r.json()["error"] == "conflict"
    del tg.fail["getUpdates"]
    assert gateway.status()["running"] and gateway.link_status()["linked"]
    await wait_for(lambda: gateway.status()["poll_error"] is None, what="our poller back")


# ---- poll_error vs sync_error, heartbeat ---------------------------------------------------------
async def test_poll_error_is_kept_by_the_sync_and_cleared_by_the_poller(api, tg):
    await _linked(api, tg)
    await wait_for(lambda: gateway.status()["last_poll_ok"], what="heartbeat")
    assert gateway.load_state()["poller_pid"] == os.getpid()
    tg.fail["getUpdates"] = CONFLICT
    await wait_for(lambda: gateway.status()["poll_error_code"] == "conflict", what="409")
    st = gateway.status()
    assert "Another program" in st["poll_error"] and st["last_error"] == st["poll_error"]
    assert (await api.post("/api/telegram/sync")).status_code == 200
    assert gateway.status()["poll_error_code"] == "conflict"            # the sync no longer erases it
    tg.fail_once["createForumTopic"] = (400, "Bad Request: something odd")
    gateway.mutate_tg(lambda t: t["threads"].pop("#feed", None))
    await api.post("/api/telegram/sync")
    st = gateway.status()
    assert "something odd" in st["sync_error"] and st["poll_error_code"] == "conflict"
    del tg.fail["getUpdates"]
    await wait_for(lambda: gateway.status()["poll_error"] is None, what="poller recovered")
    assert "something odd" in gateway.status()["sync_error"]


async def test_revoked_token_is_reported_with_its_code(api, tg):
    await _linked(api, tg)
    tg.token = "999:other"
    await wait_for(lambda: gateway.status()["poll_error_code"] == "token_rejected", what="401")
    assert not gateway.status()["running"] and gateway.load_state().get("poller_pid") is None
    c = cmd_core.check_telegram(config.load_config())
    assert c["level"] == "warn" and "token" in c["title"]


def test_poller_running_seen_from_another_process(mx_state, monkeypatch):
    monkeypatch.setattr(gateway, "_gw", None)
    gateway.update_state(poller_pid=os.getppid(), last_poll_ok=time.time() - 10)
    assert gateway.poller_running()
    gateway.update_state(poller_pid=os.getpid())                        # this very process has no gateway
    assert not gateway.poller_running()
    gateway.update_state(poller_pid=2 ** 22 + 12345)                    # no such process
    assert not gateway.poller_running()


# ---- topics off = notice, not an error ------------------------------------------------------------
async def test_topics_off_is_a_notice_and_setup_is_done(api, tg):
    tg.topics_enabled = False
    await _linked(api, tg)
    await wait_for(lambda: gateway.status()["topics_notice"], what="notice")
    st = gateway.status()
    assert st["chat"] and st["sync_error"] is None and st["last_error"] is None and "Retry" in st["topics_notice"]
    c = cmd_core.check_telegram(config.load_config())
    assert c["level"] == "ok" and "Threaded Mode" in c["title"]
    from maxxing.api import onboarding
    assert onboarding.steps()["telegram"] is True
    tg.topics_enabled = True                                           # turned on in @BotFather, then Retry
    res = (await api.post("/api/telegram/sync")).json()
    assert res["topics_enabled"] and res["created"] == 3 and gateway.status()["topics_notice"] is None


def test_legacy_last_error_is_read(mx_state):
    gateway.update_state(last_error="boom")
    assert gateway.status()["sync_error"] == "boom"


# ---- test report, doctor ------------------------------------------------------------------------------
async def test_send_test_reports_poller_and_webhook(api, tg):
    await _linked(api, tg)
    await wait_for(lambda: gateway.status()["last_poll_ok"], what="heartbeat")
    r = (await api.post("/api/telegram/test")).json()
    assert r["ok"] and r["sent"] and r["poller"]["running"] and r["webhook"]["url"] == "" and r["problems"] == []
    tg.webhook = "https://other.example.com/hook"
    r = (await api.post("/api/telegram/test")).json()
    assert r["sent"] and not r["ok"] and any("webhook" in p for p in r["problems"])


async def test_doctor_reads_the_poller_state(api, tg, monkeypatch):
    await _linked(api, tg)
    await wait_for(lambda: gateway.status()["last_poll_ok"], what="heartbeat")
    assert cmd_core.check_telegram(config.load_config())["level"] == "ok"
    gateway.update_state(last_poll_ok=time.time() - 900)
    c = cmd_core.check_telegram(config.load_config())
    assert c["level"] == "warn" and "15 min" in c["title"]
    gateway.update_state(last_poll_ok=time.time(), sync_error="Could not create the thread")
    c = cmd_core.check_telegram(config.load_config())
    assert c["level"] == "warn" and "sync" in c["title"]
    await gateway.stop()
    c = cmd_core.check_telegram(config.load_config())
    assert c["level"] == "warn" and "not reading" in c["title"]


def test_doctor_pending_link_is_info(mx_state):
    config.set_secret("telegram_token", TG_TOKEN)
    gateway.update_state(bot={"id": 1, "username": "b", "name": "B"},
                         link={"code": "x", "created": time.time(), "expires": time.time() + 600})
    assert cmd_core.check_telegram(config.load_config())["level"] == "info"


def test_cli_status_shows_poller_and_errors(mx_state, capsys):
    from maxxing import cli
    config.set_secret("telegram_token", TG_TOKEN)
    gateway.update_state(bot={"id": 1, "username": "b", "name": "B"}, poll_error="Another program…",
                         poll_error_code="conflict", sync_error="sync broke")
    assert cli.main(["telegram", "status"]) == 0
    out = capsys.readouterr().out
    assert "poller     : stopped" in out and "poll error : Another program" in out and "sync error : sync broke" in out
