"""Daily budget of the whole server (Settings -> Usage): maxxing/budget.py."""
from __future__ import annotations

import time

from maxxing import agents, budget, crons, feed
from maxxing.sessions import store

from conftest import wait_idle

A = "projects/acme/topics/blog/agents/writer"


def _spend(path: str, usd: float, when: float | None = None) -> dict:
    m = store.new_meta(path, "spent")
    store.add_usage(m, {}, usd, when or time.time())
    store.create(m)
    return m


def _budget(client, usd: float) -> dict:
    r = client.put("/api/settings", json={"daily_budget_usd": usd})
    assert r.status_code == 200, r.text
    return r.json()


def _events() -> list[dict]:
    return [e for e in feed.list_events(source="system")["events"] if "budget" in e["title"].lower()]


def test_no_budget_by_default(client, topic):
    _spend(topic, 50.0)
    assert client.get("/api/settings").json()["daily_budget_usd"] == 0
    assert client.get("/api/stats/budget").json() == {"usd_per_day": 0.0, "spent_today": 50.0, "reached": False}
    assert not budget.reached() and _events() == []


def test_the_setting_is_checked(client, topic):
    assert _budget(client, 12.345)["daily_budget_usd"] == 12.35
    for bad in (-1, 100001):
        r = client.put("/api/settings", json={"daily_budget_usd": bad})
        assert r.status_code == 400 and r.json()["error"] == "invalid_daily_budget"
    assert budget.limit() == 12.35
    assert _budget(client, 0)["daily_budget_usd"] == 0


def test_only_today_counts(client, topic):
    _budget(client, 10)
    _spend(topic, 9.0, time.time() - 2 * 86400)                # two days ago
    _spend(topic, 3.0)
    assert budget.spent_today() == 3.0 and not budget.reached()
    _spend(topic, 7.5)
    assert client.get("/api/stats/budget").json() == {"usd_per_day": 10.0, "spent_today": 10.5, "reached": True}


def test_alerts_at_80_then_reached_once_each(client, topic):
    _budget(client, 10)
    _spend(topic, 5.0)
    budget.check()
    assert _events() == []
    _spend(topic, 3.5)
    budget.check()
    budget.check()
    (warn,) = _events()
    assert warn["title"] == "85 % of today's budget used" and warn["url"] == "/settings/usage"
    _spend(topic, 2.0)
    budget.check()
    budget.check()
    evs = _events()
    assert len(evs) == 2
    alert = feed.find(budget.REF)
    assert alert and alert["title"] == "Daily budget reached" and "10.50 $" in alert["body"]


def test_a_higher_budget_closes_the_alert(client, topic):
    _budget(client, 10)
    _spend(topic, 11.0)
    budget.check()
    assert feed.find(budget.REF)
    _budget(client, 50)                                        # the settings change checks at once
    assert feed.find(budget.REF) is None and not budget.reached()
    _budget(client, 10)                                        # the same amount again the same day: no second alert
    assert feed.find(budget.REF) is None and budget.reached()


def test_a_turn_end_posts_the_alert(client, topic):
    _budget(client, 1)
    _spend(topic, 2.0)
    r = client.post("/api/sessions", json={"path": topic, "message": "hello"})
    assert r.status_code == 200, r.text                        # the user's own message still runs
    wait_idle(client, r.json()["id"])
    deadline = time.time() + 10
    while time.time() < deadline and not feed.find(budget.REF):
        time.sleep(0.1)
    assert feed.find(budget.REF)


def test_scheduled_prompt_waits_but_run_now_and_commands_run(client, topic):
    _budget(client, 1)
    _spend(topic, 2.0)
    j = crons.create_job({"name": "Digest", "kind": "claude", "topic_path": topic, "prompt": "Summarise"})
    r = crons.run_job(j["id"], trigger="schedule")
    assert r["ok"] and r["session_id"] is None and r["output_tail"] == f"skipped: {budget.SKIP_TEXT}"
    sh = crons.create_job({"name": "Echo", "kind": "shell", "command": "echo hi"})
    assert crons.run_job(sh["id"], trigger="schedule")["output_tail"].strip() == "hi"
    r = crons.run_job(j["id"])                                 # "Run now"
    assert r["ok"] and r["session_id"]
    _budget(client, 0)
    r = crons.run_job(j["id"], trigger="schedule")
    assert r["ok"] and r["session_id"]


def test_agent_triggers_wait_but_the_owner_is_answered(client, topic):
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    r = client.post("/api/agents", json={"topic_path": topic, "name": "writer", "display_name": "Writer",
                                         "description": "You write the blog posts."})
    assert r.status_code == 200, r.text
    _budget(client, 1)
    _spend(topic, 2.0)
    assert agents.gate(A) == "limit" and agents.gate(A, owner=True) is None
    r = agents.fire(A, trigger="manual", prompt="write", source="command line")
    assert r == {"started": False, "reason": "limit"}
    skip = agents.thread(A, 10)[-1]
    assert skip["kind"] == "skip" and skip["reason"] == "limit" and "Settings -> Usage" in skip["text"]
    _budget(client, 0)
    assert agents.gate(A) is None


def test_a_group_still_answers_its_owner(client, topic):
    from test_agent_groups import G, W, _idle, _setup
    _setup(client)
    _budget(client, 1)
    _spend(topic, 2.0)
    assert agents.gate(W) == "limit"
    client.post(f"{G}/messages", json={"text": "@writer\nREPLY_AS writer: Here"})
    assert [(m["kind"], m["author"]) for m in _idle(client, 1)] == [("message", W)]



def test_a_damaged_cost_in_a_session_is_ignored(client, topic):
    _budget(client, 10)
    _spend(topic, 3.0)
    for bad in ("nan", "inf", 1e999, 10 ** 400):
        m = store.new_meta(topic, "damaged")
        store.add_usage(m, {}, 1.0, time.time())
        m["days"][store.day_of(time.time())]["cost"] = bad
        store.create(m)
    r = client.get("/api/stats/budget")
    assert r.status_code == 200 and r.json()["spent_today"] == 3.0
    assert budget.reached() is False
