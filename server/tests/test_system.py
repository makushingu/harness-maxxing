import json
import threading
import time
import types

import pytest

from _org_helpers import client, org  # noqa: F401
from maxxing import config, crons, health, security
from maxxing.api import system as system_api


def _svc(states):
    def show(name):
        if name not in states:
            return {"LoadState": "not-found"}
        active, enabled = states[name]
        return {"LoadState": "loaded", "ActiveState": active, "UnitFileState": enabled,
                "ActiveEnterTimestampMonotonic": "1000000", "Description": f"{name} unit"}
    return show


@pytest.fixture
def services(monkeypatch):
    states = {"claude-maxxing": ("active", "enabled"), "caddy": ("failed", "enabled"),
              "cron": ("active", "enabled"), "custom": ("inactive", "disabled")}
    show = _svc(states)
    monkeypatch.setattr(health, "_systemctl_show_all", lambda names: {n: show(n) for n in names})
    return states


def test_proc_readers():
    m = health.meminfo()
    assert m["total"] > 0 and 0 < m["avail"] <= m["total"]
    assert len(health.loadavg()) == 3 and health.uptime_s() > 0
    c = health.cpu_pct()
    assert c is None or 0 <= c <= 100


def test_cpu_after_a_long_pause_is_measured_again(monkeypatch):
    """After 10 min without a call, every later call repeated the last value forever (seen stuck at 90 %)."""
    ticks = iter([(100, 1000), (100, 1010), (101, 1020)])
    monkeypatch.setattr(health, "_cpu_times", lambda: next(ticks))
    monkeypatch.setattr(health.time, "sleep", lambda s: None)
    monkeypatch.setattr(health, "_cpu_last", 90.2)
    monkeypatch.setattr(health, "_cpu_prev", (time.time() - 700, 0, 0))
    assert health.cpu_pct() == 0.0            # the 0.1 s sample: no busy tick out of 10
    health._cpu_prev = (time.time() - 5, *health._cpu_prev[1:])
    assert health.cpu_pct() == 10.0           # the next call is a real measure, not the old 90.2


def test_health(client, org, services, monkeypatch):
    monkeypatch.setattr(health, "disk", lambda path=None: {"total": 100e9, "free": 5e9, "pct": 95.0})
    monkeypatch.setattr(health, "meminfo", lambda: {"total": 8 << 30, "avail": 100 << 20})
    crons.append_run({"id": "r1", "cron_id": "c_a", "name": "Nightly", "at": time.time() - 60, "ok": False, "code": 2})
    crons.append_run({"id": "r2", "cron_id": "c_b", "name": "Fixed", "at": time.time() - 120, "ok": False, "code": 1})
    crons.append_run({"id": "r3", "cron_id": "c_b", "name": "Fixed", "at": time.time() - 60, "ok": True, "code": 0})
    for _ in range(security.FAIL_MAX):
        security.throttle("1.2.3.4", False)
    config.update_config(backup={"repo": "acme/memory"})
    hist = config.state_dir("backup") / "history.jsonl"
    hist.write_text(json.dumps({"at": time.time() - 72 * 3600, "ok": True}) + "\nnot json\n")

    h = client.get("/api/system/health").json()
    codes = {i["code"]: i for i in h["issues"]}
    assert codes["disk_full"]["level"] == "warn" and "low_memory" in codes
    assert codes["service_down"]["text"].startswith("Service Caddy")
    assert codes["cron_failed"]["text"] == 'Scheduled job "Nightly" failed (code 2)'
    assert sum(1 for i in h["issues"] if i["code"] == "cron_failed") == 1      # c_b recovered
    assert "login_failures" in codes and h["failed_logins_1h"] == security.FAIL_MAX
    assert codes["claude_auth"]["level"] == "error" and h["claude_auth"] is False
    assert "backup_old" in codes and 71 < h["backup_age_h"] < 73
    assert h["ok"] is False and set(h) >= {"cpu_pct", "load", "mem", "disk", "uptime_s"}

    # cached 30 s, force refresh
    config.set_secret("anthropic_api_key", "sk-test")
    assert client.get("/api/system/health").json()["claude_auth"] is False
    assert client.get("/api/system/health?force=1").json()["claude_auth"] is True


def test_health_issue_marked_seen(client, org, services, monkeypatch):
    crons.append_run({"id": "r1", "cron_id": "c_a", "name": "Nightly", "at": time.time() - 60, "ok": False, "code": 2})
    issues = client.get("/api/system/health?force=1").json()["issues"]
    job = next(i for i in issues if i["code"] == "cron_failed")
    assert job["seen"] is False and len(job["id"]) == 12
    assert client.post("/api/system/health/seen", json={"id": "nope"}).status_code == 404
    h = client.post("/api/system/health/seen", json={"id": job["id"]}).json()
    assert next(i for i in h["issues"] if i["id"] == job["id"])["seen"] is True
    assert all(not i["seen"] for i in h["issues"] if i["id"] != job["id"])
    # the same job failing with another exit code keeps its mark (numbers left out); another job is a new issue
    assert health.issue_id({"code": "cron_failed", "text": 'Scheduled job "Nightly" failed (code 7)'}) == job["id"]
    assert health.issue_id({"code": "cron_failed", "text": 'Scheduled job "Weekly" failed (code 2)'}) != job["id"]
    assert health.issue_id({"code": "cron_failed", "text": 'Scheduled job "Backup 1" failed (code 1)'}) \
        != health.issue_id({"code": "cron_failed", "text": 'Scheduled job "Backup 2" failed (code 1)'})
    # the mark ends after 24 h
    marks = json.loads(health._seen_path().read_text())
    health._seen_path().write_text(json.dumps({job["id"]: marks[job["id"]] - health.SEEN_TTL_S - 1}))
    h = client.get("/api/system/health?force=1").json()
    assert next(i for i in h["issues"] if i["id"] == job["id"])["seen"] is False
    assert json.loads(health._seen_path().read_text()) == {}
    # seen -> not seen again
    client.post("/api/system/health/seen", json={"id": job["id"]})
    h = client.post("/api/system/health/seen", json={"id": job["id"], "seen": False}).json()
    assert next(i for i in h["issues"] if i["id"] == job["id"])["seen"] is False


def test_two_marks_at_once_are_both_kept(mx, monkeypatch):
    iss = [health._issue("warn", "cron_failed", 'Scheduled job "Alpha" failed (code 1)'),
           health._issue("warn", "claude_auth", "Claude is not connected")]
    for i in iss:
        i["id"] = health.issue_id(i)
    monkeypatch.setattr(health, "collect", lambda force=False: {"issues": iss})
    read = health._read_seen

    def slow_read():
        d = read()
        time.sleep(0.2)                                     # both marks read the file before either writes
        return d
    monkeypatch.setattr(health, "_read_seen", slow_read)
    ts = [threading.Thread(target=health.mark_seen, args=(i["id"],)) for i in iss]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert set(json.loads(health._seen_path().read_text())) == {i["id"] for i in iss}


def test_health_backup_never_and_ok(org, services):
    assert health.collect(force=True)["backup_age_h"] is None
    config.update_config(backup={"repo": "acme/memory"})
    assert "backup_never" in {i["code"] for i in health.collect(force=True)["issues"]}


def test_services_and_actions(client, services, monkeypatch):
    config.update_config(services_extra=["custom", "ghost"])
    lst = client.get("/api/system/services").json()
    assert [s["name"] for s in lst] == ["claude-maxxing", "caddy", "cron", "custom"]
    assert lst[0]["active"] is True and lst[0]["since"] and lst[1]["active"] is False and lst[3]["enabled"] is False

    calls = []
    monkeypatch.setattr(system_api.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or types.SimpleNamespace(returncode=0, stdout="", stderr=""))
    assert client.post("/api/system/services/claude-maxxing/stop").json()["error"] == "refused"
    assert client.post("/api/system/services/claude-maxxing/restart").json() == {"ok": True}
    assert calls[-1][0] == "systemd-run" and "--on-active=2" in calls[-1] and calls[-1][-2:] == ["restart", "claude-maxxing"]
    assert client.post("/api/system/services/caddy/restart").json() == {"ok": True}
    assert calls[-1] == ["systemctl", "restart", "caddy"]
    assert client.post("/api/system/services/sshd/stop").status_code == 404
    assert client.post("/api/system/services/caddy/explode").status_code == 422
    monkeypatch.setattr(system_api.subprocess, "run",
                        lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr="Access denied"))
    r = client.post("/api/system/services/caddy/start")
    assert r.status_code == 502 and "Access denied" in r.json()["message"]


def test_services_one_systemctl_call_and_cache(client, monkeypatch):
    out = ("Id=claude-maxxing.service\nLoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
           "ActiveEnterTimestampMonotonic=5000000\nDescription=HM\n\n"
           "Id=caddy.service\nLoadState=loaded\nActiveState=failed\nUnitFileState=enabled\n"
           "ActiveEnterTimestampMonotonic=0\nDescription=Caddy\n\n"
           "Id=tailscaled.service\nLoadState=not-found\nActiveState=inactive\nUnitFileState=\n"
           "ActiveEnterTimestampMonotonic=0\nDescription=tailscaled.service\n\n"
           "Id=cron.service\nLoadState=loaded\nActiveState=active\nUnitFileState=enabled\n"
           "ActiveEnterTimestampMonotonic=7000000\nDescription=cron\n")
    calls = []
    monkeypatch.setattr(health.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or types.SimpleNamespace(returncode=0, stdout=out, stderr=""))
    lst = client.get("/api/system/services").json()
    assert [(s["name"], s["active"]) for s in lst] == [("claude-maxxing", True), ("caddy", False), ("cron", True)]
    assert len(calls) == 1 and calls[0][:6] == ["systemctl", "show", "claude-maxxing", "caddy", "tailscaled", "cron"]
    client.get("/api/system/services")
    assert len(calls) == 1                                      # cached
    assert client.post("/api/system/services/caddy/restart").json() == {"ok": True}
    assert calls[-1] == ["systemctl", "restart", "caddy"]
    client.get("/api/system/services")
    assert len(calls) == 3 and calls[-1][1] == "show"                                     # an action drops the cache


def test_logs_whitelist(client, monkeypatch):
    calls = []
    monkeypatch.setattr(system_api.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or
                        types.SimpleNamespace(returncode=0, stdout="line 1\n\nline 2\n", stderr=""))
    assert client.get("/api/system/logs?unit=caddy&lines=50").json() == {"lines": ["line 1", "line 2"]}
    assert calls[-1][:5] == ["journalctl", "-u", "caddy", "-n", "50"]
    assert client.get("/api/system/logs?unit=maxxing-cron-c-abc123").status_code == 200
    assert client.get("/api/system/logs?unit=ssh").status_code == 400
    assert client.get("/api/system/logs?unit=caddy;reboot").status_code == 400
    assert client.get("/api/system/logs?lines=0").status_code == 422


def test_version(client, monkeypatch):
    answers = {("rev-parse", "--short", "HEAD"): "abc1234", ("fetch", "--quiet", "origin"): "",
               ("rev-parse", "--short", "FETCH_HEAD"): "def5678", ("rev-list", "--count", "HEAD..FETCH_HEAD"): "3"}
    monkeypatch.setattr(system_api, "_git", lambda *a, timeout=10, auth=False: answers.get(a))
    system_api._ver.update(at=0.0, latest=None, behind=None, busy=False)
    v = client.get("/api/system/version").json()
    assert v["version"] and v["commit"] == "abc1234"
    for _ in range(50):
        if not system_api._ver["busy"]:
            break
        time.sleep(0.02)
    v = client.get("/api/system/version").json()
    assert v["latest_commit"] == "def5678" and v["behind"] == 3

    answers.pop(("fetch", "--quiet", "origin"))                     # offline: tolerated
    answers[("ls-remote", "origin", "HEAD")] = None
    system_api._ver.update(at=0.0, busy=False)
    system_api._refresh_remote()
    assert system_api._ver["latest"] is None and system_api._ver["behind"] is None

    # "Check now": refresh=1 checks synchronously
    answers[("fetch", "--quiet", "origin")] = ""
    answers[("rev-list", "--count", "HEAD..FETCH_HEAD")] = "5"
    system_api._ver.update(at=time.time(), busy=False)              # fresh cache: only refresh=1 re-checks
    v = client.get("/api/system/version?refresh=1").json()
    assert v["behind"] == 5 and v["checking"] is False and v["checked_at"]


def test_version_check_uses_the_update_token(mx, monkeypatch):
    from maxxing import config
    calls = []
    monkeypatch.setattr(system_api.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw["env"])) or
                        types.SimpleNamespace(returncode=0, stdout="", stderr=""))
    system_api._git("fetch", "--quiet", "origin", auth=True)
    assert "GIT_CONFIG_VALUE_0" not in calls[-1][1]                 # no token stored: plain fetch
    config.set_secret("github_update_token", "tok123")
    system_api._git("fetch", "--quiet", "origin", auth=True)
    cmd, env = calls[-1]
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader" and env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    assert not any("tok123" in c or "Authorization" in c for c in cmd)   # never in the command line (ps)
    system_api._git("rev-parse", "HEAD")
    assert "GIT_CONFIG_VALUE_0" not in calls[-1][1]                 # local commands never get it


def test_update_spawn(client, monkeypatch):
    spawned = []
    monkeypatch.setattr(system_api.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    assert client.post("/api/system/update").json() == {"ok": True}
    assert spawned[0][-2:] == ["update", "--smart"]                 # the Update button: smart update


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def test_usage(client, org, monkeypatch):
    assert client.get("/api/usage").json()["available"] is False                   # disabled by default
    config.update_config(usage_widget=True)
    assert client.get("/api/usage").json()["reason"] == "no_oauth_credentials"

    creds = org.tmp / "home" / ".claude" / ".credentials.json"
    creds.parent.mkdir(parents=True)
    creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok"}}))
    seen = {}
    import httpx

    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers)
        return _Resp(200, {"five_hour": {"utilization": 42.0, "resets_at": "2026-10-10T12:00:00Z"},
                           "seven_day": {"utilization": 7, "resets_at": None}})
    monkeypatch.setattr(httpx, "get", fake_get)
    u = client.get("/api/usage?force=1").json()
    assert seen["url"] == health.USAGE_URL and seen["headers"]["anthropic-beta"] == "oauth-2025-04-20"
    assert seen["headers"]["Authorization"] == "Bearer tok"
    assert u == {"available": True, "five_hour": {"pct": 42.0, "resets_at": 1791633600.0},
                 "seven_day": {"pct": 7.0, "resets_at": None}, "plan": None}

    def boom(*a, **k):
        raise httpx.ConnectError("offline")
    monkeypatch.setattr(httpx, "get", boom)
    u = client.get("/api/usage?force=1").json()
    assert u["available"] is True and u["stale"] == "ConnectError"          # last good values kept


def test_map_usage_limits_shape():
    u = health.map_usage({"limits": [{"kind": "session", "percent": 12, "resets_at": "x"},
                                      {"kind": "weekly_all", "percent": 55.55}]})
    assert u["five_hour"] == {"pct": 12.0, "resets_at": None} and u["seven_day"]["pct"] == 55.5
    assert health.map_usage({})["available"] is False


def test_usage_with_the_stored_long_lived_token_and_rate_limits(client, org, monkeypatch):
    """A server signed in with `claude setup-token` (no credentials file) still gets its usage; a 429 is waited
    out (no call before Retry-After, even forced) and the last good values stay, flagged stale."""
    import httpx
    config.update_config(usage_widget=True)
    health._usage.update(at=0.0, data=None, blocked_until=0.0)
    config.set_secret("anthropic_api_key", "sk-ant-api-x")
    assert client.get("/api/usage?force=1").json()["reason"] == "api_key"
    config.set_secret("claude_oauth_token", "sk-ant-oat01-stored")
    calls = []

    def ok(url, headers=None, timeout=None):
        calls.append(headers["Authorization"])
        return _Resp(200, {"five_hour": {"utilization": 10}})
    monkeypatch.setattr(httpx, "get", ok)
    assert client.get("/api/usage?force=1").json()["available"] is True
    assert calls == ["Bearer sk-ant-oat01-stored"]

    class _Limited(_Resp):
        headers = {"retry-after": "600"}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: (calls.append("x"), _Limited(429, {}))[1])
    u = client.get("/api/usage?force=1").json()
    assert u["available"] is True and u["stale"] == "rate_limited" and u["retry_at"] > time.time() + 500
    n = len(calls)
    client.get("/api/usage?force=1")
    assert len(calls) == n                                                      # blocked: no new call
    health._usage.update(at=0.0, data=None, blocked_until=0.0)                 # no rate limit left for other tests


def test_usage_rate_limit_survives_a_restart(client, org, monkeypatch):
    """A 429 with Retry-After, then the service restarts (fresh in-memory cache): no call before the wait is over."""
    import httpx
    config.update_config(usage_widget=True)
    config.set_secret("claude_oauth_token", "sk-ant-oat01-stored")
    monkeypatch.setattr(health, "_usage", {"at": 0.0, "data": None, "blocked_until": 0.0})
    calls = []

    class _Limited(_Resp):
        headers = {"retry-after": "3600"}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: (calls.append(1), _Limited(429, {}))[1])
    assert client.get("/api/usage?force=1").json()["reason"] == "rate_limited"
    monkeypatch.setattr(health, "_usage", {"at": 0.0, "data": None, "blocked_until": 0.0})      # restart
    u = client.get("/api/usage?force=1").json()
    assert calls == [1] and u["reason"] == "rate_limited" and u["retry_at"] > time.time() + 3500


def test_usage_from_the_turns(client, org, monkeypatch):
    """The limits printed by Claude Code in a turn (rate_limit_event) are served without any call, even with the
    experimental endpoint off; a window whose reset time has passed is back to 0."""
    import httpx
    from maxxing import claude_auth
    health._usage.update(at=0.0, data=None, blocked_until=0.0)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    now = time.time()
    claude_auth.record_limits({"status": "allowed", "unifiedWindows": {
        "five_hour": {"utilization": 0.19, "resetsAt": now + 3600}, "seven_day": {"utilization": 0.1, "resetsAt": now - 1}}})
    claude_auth.record_limits({"status": "allowed"})                               # nothing to keep: ignored
    u = client.get("/api/usage").json()
    assert u["available"] is True and u["source"] == "turn" and u["seen_at"] >= now
    assert u["five_hour"] == {"pct": 19.0, "resets_at": now + 3600} and u["seven_day"] == {"pct": 0.0, "resets_at": None}
    config.update_config(usage_widget=True)
    assert client.get("/api/usage?force=1").json()["source"] == "turn"            # fresh: still no call


def test_plan_names_and_an_ultra_plan_without_a_five_hour_window(client, org, monkeypatch):
    """Anthropic renamed its plans on 2026-10-31 (Max 5x -> Max, Max 20x -> Ultra) and dropped the 5-hour window of
    verified Ultra accounts: /api/usage says which plan, the dashboard widget says why the 5-hour bar is gone."""
    import json as _json
    import httpx
    from maxxing import claude_auth, widgets
    health._usage.update(at=0.0, data=None, blocked_until=0.0)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    for sub, tier, name in (("max", "default_claude_max_20x", "Ultra"), ("max", "default_claude_max_5x", "Max"),
                            ("ultra", None, "Ultra"), ("pro", None, "Pro"), (None, None, None)):
        assert claude_auth.plan_name({"claudeAiOauth": {"subscriptionType": sub, "rateLimitTier": tier}}) == name
    assert claude_auth.plan_name([]) is None
    f = claude_auth.credentials_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_json.dumps({"claudeAiOauth": {"subscriptionType": "max", "rateLimitTier": "default_claude_max_20x"}}))
    claude_auth.record_limits({"status": "allowed", "unifiedWindows": {
        "seven_day": {"utilization": 0.4, "resetsAt": time.time() + 86400}}})
    u = client.get("/api/usage").json()
    assert u["plan"] == "Ultra" and u["five_hour"] is None and u["seven_day"]["pct"] == 40.0
    w = widgets.usage()
    assert w["blocks"][0]["type"] == "markdown" and "Ultra" in w["blocks"][0]["text"]
    assert [b["value"] for b in w["blocks"] if b["type"] == "progress"] == [40.0]
    assert claude_auth.auth_method()[1].endswith("(Ultra plan)")
    f.unlink()
    assert client.get("/api/usage").json()["plan"] is None


def test_usage_from_an_old_turn_survives_a_rate_limited_endpoint(client, org, monkeypatch):
    """Limits seen in a turn an hour ago, endpoint answering 429: every reading (the first, the cached ones while
    blocked) gives the turn's values, never `available: false` - the sidebar bars no longer vanish."""
    import httpx
    from maxxing import claude_auth
    config.update_config(usage_widget=True)
    health._usage.update(at=0.0, data=None, blocked_until=0.0)
    config.set_secret("claude_oauth_token", "sk-ant-oat01-stored")
    now = time.time()
    claude_auth.record_limits({"unifiedWindows": {"five_hour": {"utilization": 0.07, "resetsAt": now + 9000}}})
    monkeypatch.setattr(claude_auth, "limits", lambda now=None, _f=claude_auth.limits: dict(_f(now), seen_at=time.time() - 3600))

    class _Limited(_Resp):
        headers = {"retry-after": "600"}

    calls = []
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (calls.append(1), _Limited(429, {}))[1])
    for force in (False, False, True, False):
        u = client.get("/api/usage" + ("?force=1" if force else "")).json()
        assert u["available"] is True and u["source"] == "turn" and u["five_hour"]["pct"] == 7.0
    assert calls == [1]                                                          # blocked: one call only
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp(500, {}))
    health._usage.update(at=0.0, data=None, blocked_until=0.0)
    assert client.get("/api/usage").json()["source"] == "turn"                   # an error, then its 60 s cache
    assert client.get("/api/usage").json()["source"] == "turn"
    health._usage.update(at=0.0, data=None, blocked_until=0.0)


def test_map_usage_drops_non_finite_numbers():
    from fastapi.responses import JSONResponse
    u = health.map_usage({"five_hour": {"utilization": float("nan"), "resets_at": float("inf")},
                          "seven_day": {"utilization": float("inf"), "resets_at": 1791633600}})
    assert u["five_hour"] == {"pct": None, "resets_at": None}
    assert u["seven_day"] == {"pct": None, "resets_at": 1791633600.0}
    JSONResponse(u)                                    # NaN / Infinity would make the response raise


def test_non_finite_limits_from_a_turn_do_not_break_usage(client, org, monkeypatch):
    """claude-limits.json with NaN / 1e999 (valid JSON for Python): /api/usage answers 200 without that bar, and a
    turn reporting a non-finite utilization is not recorded."""
    import httpx
    from maxxing import claude_auth
    health._usage.update(at=0.0, data=None, blocked_until=0.0)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    now = time.time()
    claude_auth.limits_file().write_text(
        '{"at": %f, "five_hour": {"utilization": NaN, "resets_at": %f},'
        ' "seven_day": {"utilization": 0.5, "resets_at": 1e999}}' % (now, now + 3600))
    r = client.get("/api/usage")
    assert r.status_code == 200
    u = r.json()
    assert u["five_hour"] is None and u["seven_day"] == {"pct": 50.0, "resets_at": None}
    claude_auth.limits_file().unlink()
    claude_auth.record_limits({"unifiedWindows": {"five_hour": {"utilization": float("inf"), "resetsAt": now}}})
    assert not claude_auth.limits_file().exists()
    health._usage.update(at=0.0, data=None, blocked_until=0.0)


def test_a_bad_seen_at_in_the_limits_does_not_break_usage(client, org, monkeypatch):
    """A hand-edited "at" ("x", NaN, 1e999, a list) in claude-limits.json: /api/usage answers 200, seen_at null."""
    import httpx
    from maxxing import claude_auth
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    for at in ('"x"', "NaN", "1e999", "[1]", "true"):
        health._usage.update(at=0.0, data=None, blocked_until=0.0)
        claude_auth.limits_file().write_text(
            '{"at": %s, "five_hour": {"utilization": 0.5, "resets_at": %f}}' % (at, time.time() + 3600))
        r = client.get("/api/usage")
        assert r.status_code == 200, (at, r.text[:200])
        assert claude_auth.limits()["seen_at"] is None
    claude_auth.limits_file().unlink()
    health._usage.update(at=0.0, data=None, blocked_until=0.0)


def test_parallel_forced_usage_makes_one_upstream_call(org, monkeypatch):
    import threading
    import time as _time
    config.update_config(usage_widget=True)
    monkeypatch.setattr(health, "_usage", {"at": 0.0, "data": None, "blocked_until": 0.0})
    calls = []

    def fetch():
        calls.append(1)
        _time.sleep(0.3)
        return {"available": True, "five_hour": {"pct": 10.0, "resets_at": None}, "seven_day": None}
    monkeypatch.setattr(health, "_fetch_usage", fetch)
    out = []
    threads = [threading.Thread(target=lambda: out.append(health.usage(True))) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert len(out) == 5 and all(u["available"] and u["five_hour"]["pct"] == 10.0 for u in out)
