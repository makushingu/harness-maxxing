"""Usage alerts (Settings -> Usage -> Alerts): maxxing/usage_alerts.py."""
from __future__ import annotations

import time

import pytest

from maxxing import config, feed, usage_alerts
from maxxing.sessions import service, store

A = "projects/acme/topics/blog/agents/writer"
DAY = 86400


@pytest.fixture(autouse=True)
def _fresh():
    usage_alerts._base = None
    yield
    usage_alerts._base = None


def _spend(path: str, usd: float, days_ago: int = 0) -> dict:
    m = store.new_meta(path, "spent")
    store.add_usage(m, {}, usd, time.time() - days_ago * DAY)
    store.create(m)
    usage_alerts._base = None
    return m


def _events(word: str) -> list[dict]:
    return [e for e in feed.list_events(source="system")["events"] if word in e["title"].lower()]


def test_defaults_and_setting(client, topic):
    s = client.get("/api/settings").json()
    assert (s["alert_spend_factor"], s["alert_turn_usd"], s["alert_tool_errors"]) == (3.0, 0.0, True)
    for body, err in (({"alert_spend_factor": 1.0}, "invalid_alert_spend_factor"), ({"alert_spend_factor": 101.0}, "invalid_alert_spend_factor"),
                      ({"alert_turn_usd": -1.0}, "invalid_alert_turn_usd")):
        r = client.put("/api/settings", json=body)
        assert r.status_code == 400 and r.json()["error"] == err, body
    assert client.put("/api/settings", json={"alert_spend_factor": True}).status_code == 422      # true is not 1
    s = client.put("/api/settings", json={"alert_spend_factor": 0, "alert_turn_usd": 2.5, "alert_tool_errors": False}).json()
    assert (s["alert_spend_factor"], s["alert_turn_usd"], s["alert_tool_errors"]) == (0.0, 2.5, False)
    assert usage_alerts.settings() == {"spend_factor": 0.0, "turn_usd": 2.5, "tool_errors": False}
    config.update_config(alert_spend_factor="lots", alert_turn_usd=float("nan"))                 # edited by hand
    assert usage_alerts.settings()["spend_factor"] == 3.0 and usage_alerts.settings()["turn_usd"] == 0.0


def test_an_unusual_day_is_said_once(client, topic):
    for ago in (1, 2, 3, 5):
        _spend(topic, 4.0, ago)
    m = _spend(topic, 11.0)                                    # 2.75 usual days: nothing yet
    usage_alerts.check(m, None)
    assert _events("more than usual") == []
    m = _spend(topic, 2.0)                                     # 13 $ for a usual day of 4 $
    usage_alerts.check(m, None)
    usage_alerts.check(m, None)
    evs = _events("more than usual")
    assert len(evs) == 1 and "13.00 $" in evs[0]["body"] and "4.00 $" in evs[0]["body"] and evs[0]["url"] == "/settings/usage"


def test_no_usual_day_no_alert(client, topic):
    _spend(topic, 1.0, 1)
    _spend(topic, 1.0, 2)                                      # two days of history: too few
    usage_alerts.check(_spend(topic, 500.0), None)
    assert _events("more than usual") == []


def test_small_amounts_are_never_unusual(client, topic):
    for ago in (1, 2, 3):
        _spend(topic, 0.1, ago)
    usage_alerts.check(_spend(topic, 4.0), None)               # 40 times, but under 5 $
    assert _events("more than usual") == []


def test_switched_off(client, topic):
    client.put("/api/settings", json={"alert_spend_factor": 0})
    for ago in (1, 2, 3):
        _spend(topic, 2.0, ago)
    usage_alerts.check(_spend(topic, 90.0), None)
    assert _events("more than usual") == []


def test_an_agent_that_runs_away(client, topic):
    for ago in (1, 2, 3):
        _spend(A, 1.0, ago)
        _spend(topic, 40.0, ago)                               # the server itself stays in its usual range
    m = _spend(A, 3.5)
    usage_alerts.check(m, None)
    evs = _events("more than usual")
    assert len(evs) == 1 and evs[0]["agent"] == A and "3.50 $" in evs[0]["body"]


def test_an_expensive_turn(client, topic):
    client.put("/api/settings", json={"alert_turn_usd": 2.0, "alert_tool_errors": False})
    m = _spend(topic, 1.0)
    m["turns"] = 4
    usage_alerts.check(m, {"type": "result", "cost_usd": 1.99})
    assert _events("expensive") == []
    usage_alerts.check(m, {"type": "result", "cost_usd": 2.4})
    usage_alerts.check(m, {"type": "result", "cost_usd": 2.4})          # the same turn seen twice
    evs = _events("expensive")
    assert len(evs) == 1 and "2.40 $" in evs[0]["body"] and m["id"] in evs[0]["url"]


def test_a_turn_that_keeps_failing(client, topic, monkeypatch):
    m = _spend(topic, 0.2)
    tools = [{"name": "Bash", "summary": "npm test", "error": True}] * 7 + [{"name": "Read", "summary": "a"}] * 3
    monkeypatch.setattr(service, "ended_turn_steps", lambda sid: {"tools": tools, "tools_total": 10})
    usage_alerts.check(m, None)
    assert _events("kept failing") == []                       # 7 failed: under the 8 it takes
    tools = [{"name": "Bash", "summary": "npm test", "error": True}] * 9 + [{"name": "Read", "summary": "a"}] * 11
    usage_alerts.check(m, None)
    assert _events("kept failing") == []                       # 9 of 20: fewer than half
    tools = [{"name": "Bash", "summary": "npm test", "error": True}] * 9 + [{"name": "Read", "summary": "a"}] * 3
    usage_alerts.check(m, None)
    usage_alerts.check(m, None)
    evs = _events("kept failing")
    assert len(evs) == 1 and "9 of its last 12" in evs[0]["body"]
    client.put("/api/settings", json={"alert_tool_errors": False})
    m2 = _spend(topic, 0.2)
    usage_alerts.check(m2, None)
    assert len(_events("kept failing")) == 1


def test_the_usual_day_is_the_median_of_the_last_14_days_only(client, topic):
    for ago in (1, 2, usage_alerts.BASE_DAYS + 1):             # the third day is 15 days ago: not counted
        _spend(topic, 4.0, ago)
    usage_alerts.check(_spend(topic, 20.0), None)
    assert _events("more than usual") == []                    # two days of history: too few


def test_an_unusual_day_deleted_from_the_feed_does_not_come_back_the_same_day(client, topic):
    for ago in (1, 2, 3):
        _spend(topic, 4.0, ago)
    usage_alerts.check(_spend(topic, 20.0), None)
    evs = _events("more than usual")
    assert len(evs) == 1
    feed.delete(evs[0]["id"])
    usage_alerts.check(_spend(topic, 0.5), None)
    assert _events("more than usual") == []
