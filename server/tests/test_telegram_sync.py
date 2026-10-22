"""Telegram: a session thread whose deletion failed is retried, not forgotten; feed messages never cut an HTML
entity in half."""
from __future__ import annotations

import re

import pytest

from maxxing.telegram import gateway
from maxxing.telegram.client import TelegramError
from test_telegram import svc  # noqa: F401  (fixture)
from _conn_helpers import mx_state  # noqa: F401  (fixture)


def _closed_session_thread():
    gateway.mutate_tg(lambda t: t.update(chat_id=-100, session_threads={"s_gone": {"tid": 77, "name": "old"}}))


def _failing(err: TelegramError | None):
    calls = []

    async def call(method, **kw):
        calls.append(method)
        if method == "deleteForumTopic" and err is not None:
            raise err
        return {}
    return call, calls


@pytest.mark.parametrize("err", [
    TelegramError(429, "Too Many Requests: retry after 45", 45),           # flood limit longer than the client waits
    TelegramError(0, "connection reset"),                                  # network
    TelegramError(502, "Bad Gateway"),                                     # Telegram's own error
], ids=["flood", "network", "server-error"])
async def test_failed_thread_delete_keeps_the_mapping_for_the_next_sync(mx_state, svc, err):
    _closed_session_thread()
    call, calls = _failing(err)
    await gateway._sync_sessions(call, -100)
    assert "deleteForumTopic" in calls
    assert gateway.session_threads()["s_gone"]["tid"] == 77
    call, _ = _failing(None)                                               # next sync: Telegram answers
    res = await gateway._sync_sessions(call, -100)
    assert "s_gone" not in gateway.session_threads() and res["deleted"] == 1


@pytest.mark.parametrize("err", [
    TelegramError(400, "Bad Request: message thread not found"),
    TelegramError(400, "Bad Request: not enough rights to manage topics"),  # never retried at every sync
], ids=["gone", "no-rights"])
async def test_thread_already_gone_or_refused_is_forgotten(mx_state, svc, err):
    _closed_session_thread()
    call, _ = _failing(err)
    res = await gateway._sync_sessions(call, -100)
    assert "s_gone" not in gateway.session_threads() and res["deleted"] == 1


@pytest.mark.parametrize("body", ["a" + "&" * 300, "<" * 699 + "&", "x" * 698 + '"&', "é" * 800],
                         ids=["ampersands", "lt-then-amp", "quote-amp", "accents"])
def test_feed_message_never_cuts_an_html_entity(mx_state, body):
    text, _ = gateway.feed_message({"id": 1, "title": "t", "body": body, "level": "error", "source": "x"})
    assert not re.search(r"&(?!amp;|lt;|gt;|quot;|#\d+;|#x[0-9a-fA-F]+;)", text)
    shown = text.split("\n")[1]
    assert shown.endswith("…") == (len(body) > 700)


def test_short_feed_body_is_shown_whole(mx_state):
    text, _ = gateway.feed_message({"id": 1, "title": "Deploy", "body": "a & b", "level": "info", "source": "ci"})
    assert "\na &amp; b\n" in text and "…" not in text
