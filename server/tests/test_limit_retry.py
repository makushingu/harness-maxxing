"""A cron job or an agent run stopped by Claude's usage limit starts again after the reset (crons.text_reset,
crons.limit_retry_at, agents._plan_limit_retry / retry_limits)."""
import datetime as dt
import time
from zoneinfo import ZoneInfo

import pytest

from _org_helpers import org  # noqa: F401
from conftest import wait_for
from maxxing import agents, config, crons

UTC = ZoneInfo("UTC")
A = "projects/acme/topics/blog/agents/writer"
LIMIT = "You've hit your session limit · resets 4pm (UTC)"


def ts(d, h, mi=0, zone=UTC) -> float:
    return dt.datetime(2026, 11, d, h, mi, tzinfo=zone).timestamp()


@pytest.mark.parametrize("text, now, want", [
    (LIMIT, ts(17, 15), ts(17, 16)),                                       # later today
    ("You've hit your limit · resets 4:30pm", ts(17, 15), ts(17, 16, 30)),  # no zone: UTC
    ("You've hit your limit · resets 4am", ts(17, 15), ts(18, 4)),         # passed today: tomorrow
    ("You've hit your limit · resets 12am (UTC)", ts(17, 15), ts(18, 0)),
    ("You've hit your limit · resets 12pm (UTC)", ts(17, 11), ts(17, 12)),
    (LIMIT, ts(17, 16, 5), ts(17, 16)),          # read just after the reset: that reset, not tomorrow's
    (LIMIT, ts(17, 17), ts(18, 16)),             # long past: the next one
    ("You've hit your limit · resets 4pm (Europe/Paris)", ts(17, 13), ts(17, 15)),
    ("You've hit your limit · resets 4pm (PST)", ts(17, 15), ts(17, 16)),  # unknown zone: UTC
])
def test_text_reset_reads_the_hour_of_claude_code_message(text, now, want):
    assert crons.text_reset(text, now) == want


@pytest.mark.parametrize("text", ["You've hit your limit", "resets 13pm", "resets 4:75pm", "", "the cache resets daily"])
def test_text_reset_without_a_valid_hour_is_unknown(text):
    assert crons.text_reset(text, ts(17, 15)) is None


def test_limit_reset_keeps_its_order_epoch_then_reported_limits_then_text(org):
    from maxxing import claude_auth
    now = time.time()
    assert crons.limit_reset(f"usage limit reached|{int(now) + 600}", now) == int(now) + 600
    text_at = crons.text_reset(LIMIT, now)
    assert crons.limit_reset(LIMIT, now) == text_at
    claude_auth.record_limits({"unifiedWindows": {"five_hour": {"utilization": 1.0, "resetsAt": now + 3600}}})
    assert crons.limit_reset(LIMIT, now) == pytest.approx(now + 3600)


def test_cron_limit_retry_is_one_minute_after_the_reset_of_the_message(org):
    claude, now = {"kind": "claude"}, ts(17, 15)
    p = crons.retry_plan(claude, ok=False, attempt=1, timed_out=False, text=LIMIT, now=now)
    assert p == {"at": ts(17, 16) + 60, "attempt": 2, "reason": "limit"}
    config.update_config(limit_retry_delay_s=300)
    assert crons.retry_plan(claude, ok=False, attempt=1, timed_out=False, text=LIMIT, now=now)["at"] == ts(17, 16) + 300
    config.update_config(limit_retry_delay_s=0)          # the reset is now: at least a minute from now
    assert crons.retry_plan(claude, ok=False, attempt=1, timed_out=False, text=LIMIT,
                            now=ts(17, 16, 5))["at"] == ts(17, 16, 5) + 60
    # more than a day away (a weekly limit): no retry, the next scheduled run will do
    far = f"usage limit reached|{int(now + 3 * 86400)}"
    assert crons.retry_plan(claude, ok=False, attempt=1, timed_out=False, text=far, now=now) is None
    # switched off: a limit is never retried; other passing failures still are
    config.update_config(limit_retry=False)
    assert crons.retry_plan(claude, ok=False, attempt=1, timed_out=False, text=LIMIT, now=now) is None
    assert crons.retry_plan(claude, ok=False, attempt=1, timed_out=False, text="API Error: 529 overloaded",
                            now=now)["reason"] == "transient"


def test_settings_expose_the_limit_retry(client):
    s = client.get("/api/settings").json()
    assert s["limit_retry"] is True and s["limit_retry_delay_s"] == 60
    r = client.put("/api/settings", json={"limit_retry_delay_s": 4000})
    assert r.status_code == 400 and r.json()["error"] == "invalid_limit_retry_delay"
    assert client.put("/api/settings", json={"limit_retry": False, "limit_retry_delay_s": 120}).status_code == 200
    s = client.get("/api/settings").json()
    assert s["limit_retry"] is False and s["limit_retry_delay_s"] == 120 and crons.limit_retry_on() is False


# ---- agents ---------------------------------------------------------------------------------------------------
def _agent(client) -> None:
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": "writer"})
    assert r.status_code == 200, r.text


def _results() -> list[dict]:
    return [m for m in agents.thread(A) if m["kind"] == "result"]


def test_agent_run_stopped_by_the_limit_starts_again_in_its_session_after_the_reset(client, topic):
    _agent(client)
    sid = agents.fire(A, trigger="manual", prompt="NOTOOL HITLIMIT", source="command line")["session"]["id"]
    wait_for(lambda: agents._read_state(A).get("limit_retry"))
    e = agents._read_state(A)["limit_retry"]
    assert e["session"] == sid and e["attempt"] == 1 and set(e) == {"at", "session", "attempt"}
    assert e["at"] == crons.text_reset(LIMIT, time.time()) + 60
    note = [m for m in agents.thread(A) if m["kind"] == "note" and m.get("status") == "limit_retry"]
    assert note and note[-1]["session"] == sid
    assert agents.retry_limits() == 0                     # not due yet
    st = agents._read_state(A)
    st["limit_retry"]["at"] = time.time() - 1
    agents._write_state(A, st)
    assert agents.retry_limits() == 1
    run = [m for m in agents.thread(A) if m["kind"] == "run"][-1]
    assert run["trigger"] == agents.LIMIT_RETRY_TRIGGER and run["session"] == sid
    wait_for(lambda: len(_results()) >= 2 and _results()[-1]["ok"], timeout=15)
    wait_for(lambda: "limit_retry" not in agents._read_state(A))   # the retry worked: nothing left
    assert agents.retry_limits() == 0


def test_agent_limit_retry_waits_for_a_held_budget_and_skips_otherwise(client, topic, monkeypatch):
    _agent(client)
    agents._plan_limit_retry(A, "s_x", False, LIMIT, "", {})
    st = agents._read_state(A)
    st["limit_retry"]["at"] = time.time() - 1
    agents._write_state(A, st)
    monkeypatch.setattr("maxxing.sessions.service.session_exists", lambda sid: True)
    monkeypatch.setattr(agents, "gate", lambda path, owner=False: "busy")
    assert agents.retry_limits() == 0 and agents._read_state(A).get("limit_retry")   # waits for the next pass
    monkeypatch.setattr(agents, "gate", lambda path, owner=False: "budget")
    assert agents.retry_limits() == 0 and "limit_retry" not in agents._read_state(A)
    assert agents.thread(A)[-1]["kind"] == "skip" and agents.thread(A)[-1]["reason"] == "budget"


def test_agent_limit_retry_is_left_to_the_cron_and_follows_the_setting(client, topic):
    _agent(client)
    agents._plan_limit_retry(A, "s_x", False, LIMIT, "", {"MAXXING_CRON_ID": "c_aaaaaa"})
    assert "limit_retry" not in agents._read_state(A)     # the cron job's retry_plan starts it again
    agents._plan_limit_retry(A, "s_x", False, "API Error: 529 overloaded", "", {})
    assert "limit_retry" not in agents._read_state(A)     # only the usage limit
    config.update_config(limit_retry=False)
    agents._plan_limit_retry(A, "s_x", False, LIMIT, "", {})
    assert "limit_retry" not in agents._read_state(A)
    config.update_config(limit_retry=True)
    for attempt in range(1, crons.MAX_RETRIES + 1):       # the same session stopped again: at most MAX_RETRIES
        agents._plan_limit_retry(A, "s_x", False, LIMIT, "", {})
        e = agents._read_state(A)["limit_retry"]
        assert e["attempt"] == attempt
        st = agents._read_state(A)
        st["limit_retry"]["fired"] = True
        agents._write_state(A, st)
    agents._plan_limit_retry(A, "s_x", False, LIMIT, "", {})
    assert "limit_retry" not in agents._read_state(A)


def test_agent_limit_retry_drops_a_damaged_entry(client, topic):
    _agent(client)
    st = agents._read_state(A)
    st["limit_retry"] = {"at": "soon", "session": "s_x", "attempt": 1}
    agents._write_state(A, st)
    agents._limit_waiting.add(A)
    assert agents.retry_limits() == 0
    assert "limit_retry" not in agents._read_state(A) and A not in agents._limit_waiting
