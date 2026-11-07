"""Catch-up of missed runs, retries after a transient failure, one-time jobs and silent runs (maxxing/crons.py)."""
import datetime as dt
import sys
import time
import types
from zoneinfo import ZoneInfo

import pytest

from _org_helpers import client, org  # noqa: F401
from maxxing import cmd_cron, config, crons

UTC = ZoneInfo("UTC")
PARIS = ZoneInfo("Europe/Paris")


def ts(y, mo, d, h=0, mi=0, zone=UTC) -> float:
    return dt.datetime(y, mo, d, h, mi, tzinfo=zone).timestamp()


@pytest.fixture(autouse=True)
def _tick_alive(request, monkeypatch):
    """Retries are planned only while the server's tick runs (tests marked real_tick check it for real)."""
    if "real_tick" not in request.keywords:
        monkeypatch.setattr(crons, "tick_alive", lambda now=None: True)


def job(**kw) -> dict:
    return {**crons.DEFAULTS, "id": "c_aaaaaa", "name": "j", "created": ts(2026, 1, 1), "updated": ts(2026, 1, 1), **kw}


def run(at, duration=5.0, **kw) -> dict:
    return {"id": "r", "cron_id": "c_aaaaaa", "at": at, "ok": True, "duration_s": duration, **kw}


# ---- catch-up decision (pure) ---------------------------------------------------------------
def test_daily_job_missed_this_morning_is_caught_up_once():
    j = job(schedule="0 7 * * *")
    now = ts(2026, 11, 7, 10)
    assert crons.catch_up_slot(j, [], now, UTC) == ts(2026, 11, 7, 7)
    assert crons.catch_up_slot(j, [run(ts(2026, 11, 6, 7))], now, UTC) == ts(2026, 11, 7, 7)   # yesterday's only
    assert crons.catch_up_slot(j, [run(ts(2026, 11, 7, 7, 0) + 2)], now, UTC) is None           # it ran
    assert crons.catch_up_slot(j, [run(ts(2026, 11, 7, 9), trigger="catch-up")], now, UTC) is None   # made up for


def test_the_regular_run_has_time_to_start_and_only_the_last_slot_counts():
    j = job(schedule="0 7 * * *")
    assert crons.catch_up_slot(j, [], ts(2026, 11, 7, 7, 1), UTC) is None          # within the grace delay
    assert crons.catch_up_slot(j, [], ts(2026, 11, 7, 7, 4), UTC) == ts(2026, 11, 7, 7)
    # missed two days in a row: one run, for the most recent slot
    assert crons.catch_up_slot(j, [run(ts(2026, 11, 5, 7))], ts(2026, 11, 7, 8), UTC) == ts(2026, 11, 7, 7)


def test_no_catch_up_older_than_a_day_or_for_frequent_reboot_or_opted_out_jobs():
    now = ts(2026, 11, 7, 10)
    assert crons.catch_up_slot(job(schedule="0 7 * * 1"), [], now, UTC) is None    # Monday 07:00: 5 days ago
    assert crons.catch_up_slot(job(schedule="*/15 * * * *"), [], now, UTC) is None
    assert crons.catch_up_slot(job(schedule="0,30 9 * * *"), [], now, UTC) is None  # 30 min apart
    assert crons.catch_up_slot(job(schedule="0 * * * *"), [], now, UTC) is None    # hourly, 10:00 starts now
    assert crons.catch_up_slot(job(schedule="0 * * * *"), [], now + 600, UTC) == now   # ...and was missed
    assert crons.catch_up_slot(job(schedule="@reboot"), [], now, UTC) is None
    assert crons.catch_up_slot(job(schedule="0 7 * * *", catch_up=False), [], now, UTC) is None
    assert crons.catch_up_slot(job(schedule="0 7 * * *", enabled=False), [], now, UTC) is None
    assert crons.catch_up_slot(job(schedule="not valid"), [], now, UTC) is None


def test_no_catch_up_just_before_the_next_regular_run():
    hourly = job(schedule="0 * * * *")
    assert crons.catch_up_slot(hourly, [], ts(2026, 11, 7, 10, 45), UTC) == ts(2026, 11, 7, 10)
    assert crons.catch_up_slot(hourly, [], ts(2026, 11, 7, 10, 52), UTC) is None   # 11:00 is 8 min away
    daily = job(schedule="0 7 * * *")
    assert crons.catch_up_slot(daily, [], ts(2026, 11, 8, 4), UTC) == ts(2026, 11, 7, 7)
    assert crons.catch_up_slot(daily, [], ts(2026, 11, 8, 5), UTC) is None         # 2 h < 10 % of a day
    every3h = job(schedule="0 */3 * * *")
    assert crons.catch_up_slot(every3h, [], ts(2026, 11, 7, 10, 40), UTC) == ts(2026, 11, 7, 9)
    assert crons.catch_up_slot(every3h, [], ts(2026, 11, 7, 11, 45), UTC) is None   # 15 min < 18 min


def test_a_job_created_or_changed_after_the_slot_is_not_caught_up():
    now = ts(2026, 11, 7, 10)
    assert crons.catch_up_slot(job(schedule="0 7 * * *", created=ts(2026, 11, 7, 8), updated=ts(2026, 11, 7, 8)),
                               [], now, UTC) is None
    assert crons.catch_up_slot(job(schedule="0 7 * * *", updated=ts(2026, 11, 7, 9)), [], now, UTC) is None
    no_dates = {k: v for k, v in job(schedule="0 7 * * *").items() if k not in ("created", "updated")}
    assert crons.catch_up_slot(no_dates, [], now, UTC) is None                     # unknown age: never


def test_a_slot_skipped_because_the_previous_run_was_still_running_is_not_a_miss():
    j = job(schedule="0 */2 * * *")
    long_run = run(ts(2026, 11, 7, 6), duration=3 * 3600)                           # 06:00 -> 09:00
    assert crons.catch_up_slot(j, [long_run], ts(2026, 11, 7, 9, 30), UTC) is None   # 08:00 overlapped


def test_a_trimmed_history_is_not_taken_for_a_miss():
    j = job(schedule="0 7 * * *")
    now = ts(2026, 11, 7, 10)
    assert crons.catch_up_slot(j, [], now, UTC, known_since=ts(2026, 11, 7, 8)) is None    # its run may be gone
    assert crons.catch_up_slot(j, [], now, UTC, known_since=ts(2026, 11, 6, 8)) == ts(2026, 11, 7, 7)
    assert crons._known_since([{"at": 5.0}]) is None


def test_catch_up_uses_the_configured_zone():
    j = job(schedule="0 7 * * *")
    now = ts(2026, 11, 7, 10)                                                       # 11:00 in Paris
    assert crons.catch_up_slot(j, [], now, PARIS) == ts(2026, 11, 7, 7, zone=PARIS)


def test_tick_starts_one_catch_up_and_the_run_records_it(org, monkeypatch):
    j = crons.create_job({"name": "Morning", "command": "echo hi", "schedule": "0 7 * * *"})
    raw = crons._load_raw()
    raw[0]["created"] = raw[0]["updated"] = time.time() - 3 * 86400
    crons._save_raw(raw)
    slot = crons.next_runs("0 7 * * *", 1, time.time() - 86400)[0]
    now = slot + 3600 if slot + 3600 < time.time() + 86400 else slot
    started = []
    monkeypatch.setattr(crons, "spawn_run", lambda cid, trigger="manual", attempt=1: started.append((cid, trigger)))
    assert crons.tick(now) == [(j["id"], "catch-up")] and started == [(j["id"], "catch-up")]

    sent = []
    monkeypatch.setattr(crons, "_notify", lambda job, r, answer=None: sent.append(r))
    monkeypatch.setattr(crons.time, "time", lambda: now)
    r = crons.run_job(j["id"], "catch-up")
    assert r["ok"] and r["trigger"] == "catch-up" and r["slot"] == slot
    assert crons._run_note(r).startswith(" · catch-up of ")
    started.clear()
    assert crons.tick(now) == [] and started == []                                  # once, never per slot
    again = crons.run_job(j["id"], "catch-up")                                      # a second start: refused
    assert again == {"skipped": "not missed any more", "cron_id": j["id"]} and len(sent) == 1


def test_a_catch_up_overtaken_by_the_regular_run_is_skipped(org, monkeypatch):
    j = crons.create_job({"name": "Morning", "command": "echo hi", "schedule": "0 7 * * *"})
    raw = crons._load_raw()
    raw[0]["created"] = raw[0]["updated"] = time.time() - 3 * 86400
    crons._save_raw(raw)
    slot = crons.next_runs("0 7 * * *", 1, time.time() - 86400)[0]
    crons.append_run({"id": "r1", "cron_id": j["id"], "at": slot + 1, "ok": True, "duration_s": 1})
    monkeypatch.setattr(crons.time, "time", lambda: slot + 600)
    assert crons.run_job(j["id"], "catch-up")["skipped"]
    assert len(crons.read_runs(j["id"])) == 1


# ---- retries ----------------------------------------------------------------------------------
@pytest.mark.parametrize("text,error,want", [
    ("Claude AI usage limit reached|1900000000", "", "limit"),
    ("You've hit your limit · resets 4pm (Europe/Paris)", "", "limit"),
    ("5-hour limit reached ∙ resets 3pm", "", "limit"),
    ('API Error: 529 {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}', "", "transient"),
    ("API Error: 500 Internal server error", "", "transient"),
    ("", "Connection error.", "transient"),
    ("", "request to https://api.anthropic.com failed, reason: getaddrinfo EAI_AGAIN", "transient"),
    ("API Error: Request timed out.", "", "transient"),
    ("I could not find the file report.csv.", "", None),
    ("", "Claude exited with code 1", None),
    ("x" * 5000 + " the network was fine " + "y" * 3000, "", None),               # a long answer: only its end
    # an answer that only mentions an error of something else is the job's own result, not a passing failure
    ("I checked the site: it returned 503 three times, so I stopped.", "", None),
    ("Processed 500 rows; the export step failed because the file is locked.", "", None),
    ("The Stripe API said: rate limit reached for this key.", "", None),
    ("Done.\nAPI Error: Connection error.", "", "transient"),
])
def test_failures_worth_a_retry(text, error, want):
    assert crons.classify_failure(text, error) == want


def test_retry_plan_backoff_limits_and_never_on_timeout(org, monkeypatch):
    now = 1_900_000_000.0
    claude = {"kind": "claude"}
    over = "API Error: 529 overloaded"
    assert [crons.retry_plan(claude, ok=False, attempt=a, timed_out=False, text=over, now=now)["at"] - now
            for a in (1, 2, 3)] == [300, 900, 1800]
    assert crons.retry_plan(claude, ok=False, attempt=4, timed_out=False, text=over, now=now) is None   # 3 retries
    assert crons.retry_plan(claude, ok=False, attempt=1, timed_out=True, text=over, now=now) is None
    assert crons.retry_plan(claude, ok=True, attempt=1, timed_out=False, text=over, now=now) is None
    assert crons.retry_plan(claude, ok=False, attempt=1, timed_out=False, text="no such file", now=now) is None
    p = crons.retry_plan(claude, ok=False, attempt=1, timed_out=False, text="usage limit reached|1900000900", now=now)
    assert p["reason"] == "limit" and p["at"] == 1900000900 + 120 and p["attempt"] == 2
    monkeypatch.setattr(crons, "limit_reset", lambda text, now: None)
    p = crons.retry_plan(claude, ok=False, attempt=1, timed_out=False, text="You've hit your limit", now=now)
    assert p["at"] - now == crons.LIMIT_RETRY_S
    monkeypatch.setattr(crons, "limit_reset", lambda text, now: now + 5 * 86400)   # weekly limit: give up
    assert crons.retry_plan(claude, ok=False, attempt=1, timed_out=False, text="Weekly limit reached", now=now) is None
    # shell: only with `retries`
    assert crons.retry_plan({"kind": "shell"}, ok=False, attempt=1, timed_out=False, text="boom", now=now) is None
    sh = {"kind": "shell", "retries": 2}
    assert crons.retry_plan(sh, ok=False, attempt=2, timed_out=False, text="boom", now=now)["at"] - now == 900
    assert crons.retry_plan(sh, ok=False, attempt=3, timed_out=False, text="boom", now=now) is None


def test_limit_reset_reads_the_limits_claude_code_reported(org):
    from maxxing import claude_auth
    now = time.time()
    claude_auth.record_limits({"unifiedWindows": {"five_hour": {"utilization": 1.0, "resetsAt": now + 3600},
                                                  "seven_day": {"utilization": 0.4, "resetsAt": now + 86400}}})
    assert crons.limit_reset("You've hit your limit", now) == pytest.approx(now + 3600)


def test_failed_shell_job_with_retries_is_retried_by_the_tick(org, monkeypatch):
    sent, telegram = [], []
    gw = types.ModuleType("maxxing.telegram.gateway")
    gw.notify_cron = telegram.append
    monkeypatch.setitem(sys.modules, "maxxing.telegram.gateway", gw)
    import maxxing.telegram as tpkg
    monkeypatch.setattr(tpkg, "gateway", gw, raising=False)
    from maxxing import feed
    monkeypatch.setattr(feed, "system", lambda title, body="", level="info", *a, **kw: sent.append((title, level)))
    flag = org.ws / "ok-now"
    j = crons.create_job({"name": "Flaky", "command": f"test -e {flag}", "retries": 2, "notify": "failure"})
    r = crons.run_job(j["id"], "schedule")
    assert not r["ok"] and r["retry_at"] > time.time() and r["trigger"] == "schedule"
    assert telegram == [] and sent[-1] == ("Cron will retry: Flaky", "warning")      # not the final outcome
    assert crons.get_job(j["id"])["retry_at"] == r["retry_at"]

    started = []
    monkeypatch.setattr(crons, "spawn_run", lambda cid, trigger="manual", attempt=1: started.append((cid, trigger, attempt)))
    assert crons.tick() == [] and started == []                                       # not due yet
    assert crons.tick(r["retry_at"] + 1) == [(j["id"], "retry")] and started == [(j["id"], "retry", 2)]

    assert crons.run_job(j["id"], "retry", 3)["skipped"]                             # not the waiting attempt
    monkeypatch.setattr(crons.time, "time", lambda: r["retry_at"] + 2)
    flag.touch()
    r2 = crons.run_job(j["id"], "retry", 2)
    assert r2["ok"] and r2["attempt"] == 2 and r2["trigger"] == "retry" and "retry_at" not in r2
    assert telegram == [] and crons._read_retries() == {}                            # notify failure: ok is silent
    assert crons.run_job(j["id"], "retry", 2)["skipped"] == "retry cancelled"        # claimed once


def test_last_attempt_reports_the_failure_on_telegram(org, monkeypatch):
    telegram = []
    gw = types.ModuleType("maxxing.telegram.gateway")
    gw.notify_cron = telegram.append
    monkeypatch.setitem(sys.modules, "maxxing.telegram.gateway", gw)
    import maxxing.telegram as tpkg
    monkeypatch.setattr(tpkg, "gateway", gw, raising=False)
    j = crons.create_job({"name": "Flaky", "command": "exit 2", "retries": 1})
    first = crons.run_job(j["id"])
    assert first["retry_at"] and telegram == []
    monkeypatch.setattr(crons.time, "time", lambda: first["retry_at"] + 1)
    last = crons.run_job(j["id"], "retry", 2)
    assert not last["ok"] and "retry_at" not in last
    assert telegram and telegram[-1].startswith("FAILED (code 2) - Flaky") and "attempt 2" in telegram[-1]


def test_a_retry_is_cancelled_when_the_job_is_switched_off_or_ran_again(org, monkeypatch):
    j = crons.create_job({"name": "Flaky", "command": "exit 1", "retries": 3, "notify": "never"})
    r = crons.run_job(j["id"])
    assert crons._read_retries()
    crons.update_job(j["id"], {"enabled": False})
    assert crons._read_retries() == {} and crons.get_job(j["id"])["retry_at"] is None
    crons.update_job(j["id"], {"enabled": True})
    crons._save_retry(j["id"], {"at": r["at"], "attempt": 2, "after": r["at"] - 10, "reason": "failed"})
    assert crons.run_job(j["id"], "retry", 2)["skipped"] == "retry cancelled"        # a newer run exists


def test_a_timed_out_shell_job_is_not_retried(org):
    j = crons.create_job({"name": "slow", "command": "sleep 30", "retries": 3, "notify": "never"})
    raw = crons._load_raw()
    raw[0]["timeout_s"] = 1
    crons._save_raw(raw)
    r = crons.run_job(j["id"])
    assert r["code"] == 124 and "retry_at" not in r and crons._read_retries() == {}


def test_claude_job_retried_after_an_overloaded_api(org, monkeypatch):
    (org.ws / "projects" / "a" / "topics" / "b").mkdir(parents=True)
    svc = types.ModuleType("maxxing.sessions.service")
    svc.create_session = lambda path, **kw: {"id": "s-1"}
    svc.get_session = lambda sid: None
    svc.wait_turn = lambda sid, timeout: {"id": sid, "state": "error", "error": "API Error: 529 Overloaded"}
    svc.last_assistant_text = lambda sid: ""
    monkeypatch.setitem(sys.modules, "maxxing.sessions.service", svc)
    import maxxing.sessions as pkg
    monkeypatch.setattr(pkg, "service", svc, raising=False)
    j = crons.create_job({"name": "Digest", "kind": "claude", "topic_path": "projects/a/topics/b", "prompt": "Go"})
    r = crons.run_job(j["id"])
    assert not r["ok"] and r["retry_at"] - r["at"] == pytest.approx(300, abs=5)
    svc.wait_turn = lambda sid, timeout: {"id": sid, "state": "error", "error": "Turn stopped (timeout)"}
    crons._drop_retry(j["id"])
    assert "retry_at" not in crons.run_job(j["id"])                                  # a timeout: never


# ---- one-time jobs ----------------------------------------------------------------------------
def test_once_at_is_normalised_in_the_configured_zone(org):
    config.update_config(timezone="Europe/Paris")
    assert crons.parse_once("2026-11-08 09:00") == "2026-11-08T09:00"
    assert crons.parse_once("2026-11-08T08:00:00Z") == "2026-11-08T09:00"
    assert crons.once_ts("2026-11-08T09:00") == ts(2026, 11, 8, 9, zone=PARIS)
    with pytest.raises(crons.CronError) as e:
        crons.parse_once("tomorrow")
    assert e.value.code == "invalid_once"


def test_once_at_out_of_range_is_a_clean_error(org, client):
    for v in ("9999-12-31T23:30-10:00", "0001-01-01T00:10+05:00"):          # past year 9999 / before year 1
        with pytest.raises(crons.CronError) as e:
            crons.parse_once(v)
        assert e.value.code == "invalid_once"
        assert crons.once_ts(v) is None
        assert client.get("/api/crons/preview", params={"once_at": v}).json()["valid"] is False
    far = dt.datetime.fromtimestamp(time.time() + 6 * 366 * 86400, crons.tz()).strftime("%Y-%m-%dT%H:%M")
    with pytest.raises(crons.CronError) as e:
        crons.create_job({"name": "Far", "command": "true", "once_at": far})
    assert e.value.code == "invalid_once"
    r = client.post("/api/crons", json={"name": "Far", "command": "true", "once_at": "9999-12-31T23:30-10:00"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_once"
    soon = dt.datetime.fromtimestamp(time.time() + 4 * 365 * 86400, crons.tz()).strftime("%Y-%m-%dT%H:%M")
    assert crons.create_job({"name": "Ok", "command": "true", "once_at": soon})["once_at"] == soon


def test_one_time_job_fires_once_then_is_disabled(org, monkeypatch):
    when = dt.datetime.fromtimestamp(time.time() + 1800, crons.tz()).strftime("%Y-%m-%dT%H:%M")
    j = crons.create_job({"name": "Remind me", "command": "echo hey", "once_at": when, "notify": "never"})
    assert j["schedule"] == "" and j["once_at"] == when and j["human"].startswith("once on ")
    at = crons.once_ts(when)
    assert j["next_run"] == at and j["once_ts"] == at
    d = dt.datetime.fromtimestamp(at, crons.tz())
    line = next(x for x in crons.read_crontab().splitlines() if j["id"] in x)
    assert line.startswith(f"{d.minute} {d.hour} {d.day} {d.month} * ")
    # the line fires every year on that date: before the time (or a year later) nothing runs
    assert cmd_cron._handler(cmd_cron_ns(j["id"])) == 0 and crons.read_runs(j["id"]) == []
    monkeypatch.setattr(crons.time, "time", lambda: at + 2)
    assert cmd_cron._handler(cmd_cron_ns(j["id"])) == 0
    runs = crons.read_runs(j["id"])
    assert len(runs) == 1 and runs[0]["trigger"] == "schedule"
    done = crons.get_job(j["id"])
    assert not done["enabled"] and done["done_at"] and done["next_run"] is None
    assert j["id"] not in crons.read_crontab()
    assert cmd_cron._handler(cmd_cron_ns(j["id"])) == 0 and len(crons.read_runs(j["id"])) == 1
    monkeypatch.setattr(crons.time, "time", lambda: at + 3600)
    with pytest.raises(crons.CronError) as e:                       # switched back on with a past date
        crons.update_job(j["id"], {"enabled": True})
    assert e.value.code == "invalid_once"
    later = dt.datetime.fromtimestamp(at + 7200, crons.tz()).strftime("%Y-%m-%dT%H:%M")
    again = crons.update_job(j["id"], {"once_at": later, "enabled": True})
    assert again["enabled"] and "done_at" not in again


def cmd_cron_ns(cid):
    import argparse
    return argparse.Namespace(cron_cmd="run", id=cid, if_due=False, detach=True, trigger=None, attempt=1)


def test_a_run_that_plans_no_retry_drops_a_waiting_one(org, monkeypatch):
    j = crons.create_job({"name": "Flaky", "command": "exit 1", "retries": 3, "notify": "never"})
    crons.run_job(j["id"])
    assert j["id"] in crons._read_retries()
    crons.update_job(j["id"], {"command": "true"})                    # fixed, then Run now
    assert crons.run_job(j["id"])["ok"]
    assert crons._read_retries() == {} and crons.get_job(j["id"])["retry_at"] is None
    crons.update_job(j["id"], {"command": "exit 1", "retries": 0})
    crons._save_retry(j["id"], {"at": time.time() + 300, "attempt": 2, "after": time.time() - 5, "reason": "x"})
    assert not crons.run_job(j["id"])["ok"]                           # failed, no retry wanted: none left either
    assert crons._read_retries() == {}


def test_one_time_job_with_delete_after_is_archived(org, monkeypatch):
    when = dt.datetime.fromtimestamp(time.time() + 600, crons.tz()).strftime("%Y-%m-%dT%H:%M")
    j = crons.create_job({"name": "Once", "command": "true", "once_at": when, "delete_after": True, "notify": "never"})
    monkeypatch.setattr(crons.time, "time", lambda: crons.once_ts(when) + 1)
    assert crons.run_job(j["id"], "schedule")["ok"]
    assert crons.get_job(j["id"]) is None
    gone = crons.deleted_jobs()[0]
    assert gone["job"]["id"] == j["id"] and "one-time" in gone["reason"]


def test_a_one_time_job_removed_after_its_run_forgets_its_session(org, monkeypatch):
    when = dt.datetime.fromtimestamp(time.time() + 600, crons.tz()).strftime("%Y-%m-%dT%H:%M")
    j = crons.create_job({"name": "Once", "command": "true", "once_at": when, "delete_after": True, "notify": "never"})
    other = crons.create_job({"name": "Other", "command": "true", "notify": "never"})
    config.write_json(crons._dir() / "sessions.json", {j["id"]: "s_1", other["id"]: "s_2"})
    crons._save_retry(j["id"], {"at": time.time() + 3600, "attempt": 2, "after": time.time(), "reason": "x"})
    monkeypatch.setattr(crons.time, "time", lambda: crons.once_ts(when) + 1)
    crons._finish_once(j["id"])
    assert crons.get_job(j["id"]) is None
    assert config.read_json(crons._dir() / "sessions.json", {}) == {other["id"]: "s_2"}
    assert crons._read_retries() == {}


def test_missed_one_time_job_is_caught_up_or_given_up(org, monkeypatch):
    when = dt.datetime.fromtimestamp(time.time() + 600, crons.tz()).strftime("%Y-%m-%dT%H:%M")
    j = crons.create_job({"name": "Once", "command": "true", "once_at": when, "notify": "never"})
    at = crons.once_ts(when)
    started = []
    monkeypatch.setattr(crons, "spawn_run", lambda cid, trigger="manual", attempt=1: started.append(trigger))
    assert crons.tick(at + 60) == []                                                # the line has time to fire
    assert crons.tick(at + 3600) == [(j["id"], "catch-up")]
    assert crons.tick(at + 2 * 86400) == [] and crons.get_job(j["id"])["missed"]    # too late: given up
    assert not crons.get_job(j["id"])["enabled"]


def test_one_time_job_validation(org):
    with pytest.raises(crons.CronError) as e:
        crons.create_job({"name": "x", "command": "true", "once_at": "2020-01-01T09:00"})
    assert e.value.code == "invalid_once"
    with pytest.raises(crons.CronError) as e:
        crons.create_job({"name": "x", "command": "true", "retries": 9})
    assert e.value.code == "invalid_retries"


def test_kept_server_clock_guards_one_time_lines(org, monkeypatch):
    config.update_config(timezone="Europe/Paris", system_clock="keep")
    monkeypatch.setenv("MAXXING_SYSTEM_ZONE", "UTC")
    when = dt.datetime.fromtimestamp(time.time() + 3600, crons.tz()).strftime("%Y-%m-%dT%H:%M")
    j = crons.create_job({"name": "Once", "command": "true", "once_at": when})
    line = next(x for x in crons.read_crontab().splitlines() if j["id"] in x)
    assert line.split(" ", 5)[1:5] == ["*", "*", "*", "*"] and "--if-due" in line
    at = crons.once_ts(when)
    assert crons.job_is_due(crons._raw_job(j["id"]), at + 30) and not crons.job_is_due(crons._raw_job(j["id"]), at + 60)


def test_api_once_preview_and_fields(client, org):
    when = dt.datetime.fromtimestamp(time.time() + 3600, crons.tz()).strftime("%Y-%m-%dT%H:%M")
    p = client.get("/api/crons/preview", params={"once_at": when}).json()
    assert p["valid"] and p["next"] == [crons.once_ts(when)] and p["human"].startswith("once on")
    assert client.get("/api/crons/preview", params={"once_at": "nope"}).json()["valid"] is False
    r = client.post("/api/crons", json={"name": "Once", "command": "true", "once_at": when, "delete_after": True})
    assert r.status_code == 200 and r.json()["delete_after"] is True and r.json()["schedule"] == ""
    r = client.post("/api/crons", json={"name": "Past", "command": "true", "once_at": "2020-01-01T09:00"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_once"


def test_cli_lists_one_time_jobs(org, capsys):
    from maxxing import cli
    when = dt.datetime.fromtimestamp(time.time() + 3600, crons.tz()).strftime("%Y-%m-%dT%H:%M")
    crons.create_job({"name": "Remind", "command": "true", "once_at": when})
    assert cli.main(["cron", "list"]) == 0
    out = capsys.readouterr().out
    assert "once" in out and "Remind" in out and when.replace("T", " at ") in out


# ---- silent runs ------------------------------------------------------------------------------
@pytest.mark.parametrize("answer,want", [
    ("[SILENT]", True), ("  [silent]\n", True), ("[SILENT] nothing new today", True), ("`[SILENT]`", True),
    ("Here is the report. [SILENT]", False), ("", False), (None, False),
])
def test_silent_answers(answer, want):
    assert crons.is_silent(answer) is want


def test_silent_claude_run_sends_nothing_on_telegram(org, monkeypatch):
    (org.ws / "projects" / "a" / "topics" / "b").mkdir(parents=True)
    svc = types.ModuleType("maxxing.sessions.service")
    svc.create_session = lambda path, **kw: {"id": "s-1"}
    svc.get_session = lambda sid: None
    svc.wait_turn = lambda sid, timeout: {"id": sid, "state": "idle", "error": None}
    answer = ["[SILENT]"]
    svc.last_assistant_text = lambda sid: answer[0]
    monkeypatch.setitem(sys.modules, "maxxing.sessions.service", svc)
    import maxxing.sessions as pkg
    monkeypatch.setattr(pkg, "service", svc, raising=False)
    reports, feed_rows = [], []
    gw = types.ModuleType("maxxing.telegram.gateway")
    gw.notify_cron_report = lambda header, body="", **kw: reports.append(header)
    monkeypatch.setitem(sys.modules, "maxxing.telegram.gateway", gw)
    import maxxing.telegram as tpkg
    monkeypatch.setattr(tpkg, "gateway", gw, raising=False)
    from maxxing import feed
    monkeypatch.setattr(feed, "system", lambda title, body="", level="info", source="", url="", group=None, **kw:
                        feed_rows.append((title, body, level, group)))
    j = crons.create_job({"name": "Watch", "kind": "claude", "topic_path": "projects/a/topics/b", "prompt": "Go",
                          "notify": "always"})
    r = crons.run_job(j["id"])
    assert r["ok"] and r["silent"] and reports == []
    title, body, level, group = feed_rows[-1]
    assert (title, level, group) == ("Cron jobs succeeded", "success", "ok") and "nothing to report" in body
    answer[0] = "Two new orders."
    r = crons.run_job(j["id"])
    assert "silent" not in r and reports and reports[-1].startswith("OK - Watch")


def test_cron_turns_are_told_they_may_answer_silent():
    from maxxing.sessions import spawn
    assert "[SILENT]" in spawn.CRON_SILENT and len(spawn.CRON_SILENT) < 300


def test_only_cron_turns_that_report_every_run_get_the_silent_hint(mx, monkeypatch, tmp_path):
    """Real sessions service + fake claude binary: the hint goes into the turn's system prompt, not its message, and
    only for notify "always" (with "failure" / "never" the answer must stay the full report)."""
    import json
    from maxxing import bus, workspace
    from maxxing.sessions import service, spawn
    monkeypatch.setattr(bus, "_loop", None)                         # like the CLI: no server loop
    workspace.create_project("acme")
    workspace.create_topic("acme", "blog")
    always = crons.create_job({"name": "Digest", "kind": "claude", "topic_path": "projects/acme/topics/blog",
                               "prompt": "NOTOOL say hi", "timeout_s": 60, "notify": "always"})
    failure = crons.create_job({"name": "Quiet", "kind": "claude", "topic_path": "projects/acme/topics/blog",
                                "prompt": "NOTOOL say hi", "timeout_s": 60})
    reused = crons.create_job({"name": "Reused", "kind": "claude", "topic_path": "projects/acme/topics/blog",
                               "prompt": "NOTOOL say hi", "timeout_s": 60, "notify": "always", "reuse_session": True})
    for j in (always, failure, reused, reused):
        assert crons.run_job(j["id"])["ok"]
    s = service.create_session("projects/acme/topics/blog", message="NOTOOL hello")
    service.wait_turn(s["id"], 30)
    calls = [json.loads(x) for x in (mx["fake_dir"] / "calls.jsonl").read_text().splitlines()]
    hints = [c["argv"][c["argv"].index("--append-system-prompt") + 1] for c in calls]
    assert [spawn.CRON_SILENT in h for h in hints] == [True, False, True, True, False]
    assert "[SILENT]" not in calls[0]["prompt"]


# ---- review fixes -------------------------------------------------------------------------------
def _aged(name, **fields):
    j = crons.create_job({"name": name, **fields})
    raw = crons._load_raw()
    for x in raw:
        if x["id"] == j["id"]:
            x["created"] = x["updated"] = time.time() - 3 * 86400
    crons._save_raw(raw)
    return j


def test_a_killed_run_is_never_run_again_by_the_catch_up(org, monkeypatch, tmp_path):
    """A run killed by a reboot / out of memory leaves only its mark in the lock file: it counts for its slot."""
    import json
    sent = tmp_path / "sent"
    j = _aged("Invoices", command=f"echo SENT >> {sent}", schedule="0 7 * * *")
    slot = crons.next_runs("0 7 * * *", 1, time.time() - 86400)[0]
    crons._lock_path(j["id"]).write_text(json.dumps({"at": slot + 1, "pgid": 999999, "pgid_start": "x"}))
    started = []
    monkeypatch.setattr(crons, "spawn_run", lambda cid, trigger="manual", attempt=1: started.append(trigger))
    reports = []
    monkeypatch.setattr(crons, "_notify", lambda job, r, answer=None: reports.append(r))
    now = max(time.time(), slot + 600)
    assert crons.tick(now) == [] and started == []
    r = crons.run_job(j["id"], "catch-up")                            # started anyway (an older server's tick)
    assert r["skipped"] and not sent.exists()
    runs = crons.read_runs(j["id"])
    assert len(runs) == 1 and "interrupted" in runs[0]["output_tail"]   # recorded and reported, once
    assert len(reports) == 1 and not reports[0]["ok"]
    assert crons._lock_path(j["id"]).read_text() == ""
    assert crons.tick(now) == []


def test_no_stale_retry_when_a_job_is_switched_back_on(org, monkeypatch):
    j = crons.create_job({"name": "Sync", "command": "exit 1", "retries": 2, "enabled": False, "notify": "never"})
    assert "retry_at" not in crons.run_job(j["id"]) and crons._read_retries() == {}   # Run now on a disabled job
    on = crons.create_job({"name": "On", "command": "exit 1", "retries": 2, "notify": "never"})
    r = crons.run_job(on["id"])
    crons.update_job(on["id"], {"enabled": False})
    crons._save_retry(on["id"], {"at": r["retry_at"], "attempt": 2, "after": r["at"], "reason": "failed"})
    crons.update_job(on["id"], {"enabled": True})                    # switched back on: the old retry is gone
    assert crons._read_retries() == {}
    started = []
    monkeypatch.setattr(crons, "spawn_run", lambda cid, trigger="manual", attempt=1: started.append(trigger))
    crons._save_retry(on["id"], {"at": r["retry_at"], "attempt": 2, "after": r["at"], "reason": "failed"})
    assert crons.tick(r["at"] + 9 * 86400) == [] or "retry" not in started    # days later: dropped, never run
    assert "retry" not in started and crons._read_retries() == {}
    crons._save_retry(on["id"], {"at": r["retry_at"], "attempt": 2, "after": r["at"] - 2 * 86400, "reason": "failed"})
    monkeypatch.setattr(crons.time, "time", lambda: r["retry_at"] + 1)
    assert crons.run_job(on["id"], "retry", 2)["skipped"] == "retry cancelled"


def _local(at: float) -> str:
    return dt.datetime.fromtimestamp(at, crons.tz()).strftime("%Y-%m-%dT%H:%M")


def test_a_one_time_job_rescheduled_while_it_runs_keeps_its_new_date(org, monkeypatch):
    at = crons.once_ts(_local(time.time() + 600))
    j = crons.create_job({"name": "Once", "command": "true", "once_at": _local(at), "notify": "never"})
    tomorrow = _local(at + 86400)
    real = crons._run_shell

    def moved_meanwhile(job):
        crons.update_job(j["id"], {"once_at": tomorrow})
        return real(job)
    monkeypatch.setattr(crons, "_run_shell", moved_meanwhile)
    monkeypatch.setattr(crons.time, "time", lambda: at + 5)
    assert crons.run_job(j["id"], "schedule")["ok"]
    after = crons._raw_job(j["id"])
    assert after["once_at"] == tomorrow and after["enabled"] and not after.get("done_at")
    # same for delete_after switched on meanwhile: not removed by the end of the old run
    crons.update_job(j["id"], {"once_at": _local(at), "delete_after": True})
    crons._finish_once(j["id"], ran={"once_at": _local(at), "delete_after": False})
    assert crons._raw_job(j["id"]) is not None


def test_a_one_time_job_waiting_for_its_retry_is_not_marked_missed(org, monkeypatch):
    now = time.time()
    j = crons.create_job({"name": "Once", "command": "x", "once_at": _local(now + 600), "notify": "never"})
    raw = crons._load_raw()
    raw[0]["once_at"] = _local(now - 23 * 3600)
    crons._save_raw(raw)
    crons.append_run({"id": "r1", "cron_id": j["id"], "at": now, "ok": False, "duration_s": 3,
                      "retry_at": now + 5 * 3600})
    crons._save_retry(j["id"], {"at": now + 5 * 3600, "attempt": 2, "after": now, "reason": "limit"})
    started = []
    monkeypatch.setattr(crons, "spawn_run", lambda cid, trigger="manual", attempt=1: started.append(trigger))
    assert crons.tick(now + 2 * 3600) == []
    assert crons._raw_job(j["id"])["enabled"] and not crons._raw_job(j["id"]).get("missed")
    assert crons.tick(now + 5 * 3600 + 10) == [(j["id"], "retry")]
    crons._drop_retry(j["id"])                                       # the retry ran out: it did run, not missed
    crons.tick(now + 6 * 3600)
    after = crons._raw_job(j["id"])
    assert after["done_at"] and not after.get("missed") and not after["enabled"]


@pytest.mark.real_tick
def test_retries_need_the_tick(org, monkeypatch):
    """With the server down or its tick off, no retry is promised; a retry the tick could not start in time is
    reported as the final failure."""
    assert not crons.tick_alive()
    telegram = []
    gw = types.ModuleType("maxxing.telegram.gateway")
    gw.notify_cron = telegram.append
    monkeypatch.setitem(sys.modules, "maxxing.telegram.gateway", gw)
    import maxxing.telegram as tpkg
    monkeypatch.setattr(tpkg, "gateway", gw, raising=False)
    j = crons.create_job({"name": "Flaky", "command": "echo oops; exit 2", "retries": 2})
    r = crons.run_job(j["id"])
    assert "retry_at" not in r and telegram and telegram[-1].startswith("FAILED")   # final at once
    monkeypatch.setattr(crons, "spawn_run", lambda *a, **k: None)
    crons.tick()
    assert crons.tick_alive()
    telegram.clear()
    r = crons.run_job(j["id"])
    assert r["retry_at"] and telegram == []
    assert crons.tick(r["retry_at"] + crons.RETRY_OVERDUE_S + 60) == []           # far too late: given up
    assert crons._read_retries() == {} and telegram and "not retried" in telegram[-1]


def test_an_agent_cron_skipped_by_its_budget_is_a_clean_skipped_turn(monkeypatch):
    from maxxing import agents
    monkeypatch.setattr(agents, "is_agent_path", lambda p: True)
    monkeypatch.setattr(agents, "fire", lambda *a, **k: {"started": False, "reason": "budget"})
    t = crons._claude_turn(job(kind="claude", prompt="hi", topic_path="p/a/topics/t"))
    assert t["ok"] is True and t["session_id"] is None and t["text"].startswith("skipped:")
    assert crons.classify_failure(t["text"], t["error"]) is None
