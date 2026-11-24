"""Who sent a message the owner did not type (runner._sender): one card for every sender in the thread."""
from __future__ import annotations

import time

from conftest import all_events, wait_idle
from maxxing import agents
from maxxing.sessions import normalize, runner, service, store


def test_the_owner_s_own_words_have_no_sender():
    assert runner._sender({"text": "hi", "source": "web"}) == {}
    assert runner._sender({"text": "hi", "source": "telegram"}) == {}
    assert runner._sender({"text": "hi", "source": "agent"}) == {}          # the owner on an agent's page


def test_every_other_sender_is_named():
    s = runner._sender({"relay": {"from": "a" * 36, "title": "Blog", "path": "projects/acme/topics/blog"}})
    assert s == {"from": {"kind": "session", "session": "a" * 36, "title": "Blog", "path": "projects/acme/topics/blog"}}
    a = runner._sender({"relay": {"from": "b" * 36, "title": "Writer - 2026", "path": "projects/acme/topics/blog/agents/writer"}})
    assert a["from"]["kind"] == "agent"
    assert runner._sender({"relay": {"hops": 0}, "source": "cli"})["from"] == {"kind": "cli"}
    assert runner._sender({"source": "cron"})["from"] == {"kind": "cron"}
    assert runner._sender({"source": "github"})["from"] == {"kind": "github"}
    got = runner._sender({"source": "agent", "sender": {"kind": "feed"}, "shown": "the event"})
    assert got == {"from": {"kind": "feed"}, "shown": "the event"}


def test_reports_keep_their_numbers_and_what_the_owner_reads():
    rep = runner._sender({"relay": {"from": "b" * 36, "title": "Post", "path": "p", "report": 4, "outcome": "asks"},
                          "shown": "done?"})
    assert rep["from"]["reports"] == [{"id": 4, "outcome": "asks"}] and rep["shown"] == "done?"
    merged = runner._merge_reports({"text": "r1", "shown": "a", "relay": {"from": "b" * 36, "report": 4, "outcome": "done"}},
                                   [{"text": "r2", "shown": "b", "relay": {"from": "c" * 36, "report": 5, "outcome": "failed"}}])
    out = runner._sender(merged)
    assert out["from"]["reports"] == [{"id": 4, "outcome": "done"}, {"id": 5, "outcome": "failed"}]
    assert out["shown"] == "a\n\n---\n\nb"


def test_log_lines_older_than_kind_are_sessions():
    old = normalize.normalize({"type": "mx_user", "text": "x", "source": "session",
                               "from": {"session": "a" * 36, "title": "Jarvis", "jarvis": True,
                                        "reports": [{"id": 2, "outcome": "done"}, {"id": "bad"}]}})[0]
    assert old["from"] == {"kind": "session", "session": "a" * 36, "title": "Jarvis",
                           "reports": [{"id": 2, "outcome": "done"}]}
    mine = normalize.normalize({"type": "mx_user", "text": "x", "source": "web"})[0]
    assert "from" not in mine and "shown" not in mine


def test_a_run_says_what_started_it():
    assert agents.run_sender("cron:c_1", "cron") == {"kind": "cron"}
    assert agents.run_sender("feed:t1", "feed") == {"kind": "feed"}
    assert agents.run_sender("mail:acc", "mail") == {"kind": "mail"}
    assert agents.run_sender("agent:projects/acme/topics/blog/agents/writer", "agent") == {
        "kind": "agent", "title": "writer", "path": "projects/acme/topics/blog/agents/writer"}
    assert agents.run_sender("manual", "command line") == {"kind": "cli"}
    assert agents.run_sender("manual", agents.RUN_NOW_SOURCE) == {"kind": "manual"}
    assert agents.run_sender("manual", "Jarvis") == {"kind": "manual", "title": "Jarvis"}


def test_a_sent_message_carries_its_sender_to_the_thread(client, topic):
    s = client.post("/api/sessions", json={"path": topic}).json()
    service.send_message(s["id"], "Run the report.", source="cron", sender={"kind": "cron", "title": "Daily report"})
    wait_idle(client, s["id"])
    assert not store.read(s["id"]).get("owner_at")
    service.send_message(s["id"], "hi", source="web", sender={"kind": "nope"})   # unknown kind: ignored
    wait_idle(client, s["id"])
    users = [e for e in all_events(client, s["id"]) if e.get("type") == "user"]
    assert users[0]["from"] == {"kind": "cron", "title": "Daily report"}
    assert "from" not in users[1]
    assert time.time() - store.read(s["id"])["owner_at"] < 10
