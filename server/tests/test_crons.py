import datetime as dt
import json
import sys
import time
import types
from zoneinfo import ZoneInfo

import pytest

from _org_helpers import client, org  # noqa: F401
from maxxing import config, crons

UTC = ZoneInfo("UTC")
PARIS = ZoneInfo("Europe/Paris")


def ts(y, mo, d, h=0, mi=0, zone=UTC) -> float:
    return dt.datetime(y, mo, d, h, mi, tzinfo=zone).timestamp()


# ---- expressions ----------------------------------------------------------------------------
def test_parse_fields():
    c = crons.parse("*/15 9-17/4 1,15 jan-mar MON-fri")
    assert c.minutes == {0, 15, 30, 45} and c.hours == {9, 13, 17}
    assert c.doms == {1, 15} and c.months == {1, 2, 3} and c.dows == {1, 2, 3, 4, 5}
    assert crons.parse("0 0 * * 7").dows == {0}
    assert crons.parse("5/20 * * * *").minutes == {5, 25, 45}
    assert crons.parse("@daily").source == "@daily" and crons.parse("@reboot").reboot
    assert crons.validate("  0   5 * * * ") == "0 5 * * *"


@pytest.mark.parametrize("bad", ["", "* * * *", "61 * * * *", "* * * * * *", "*/0 * * * *", "5-1 * * * *",
                                 "@sometimes", "a * * * *", "* * 0 * *", "1,,2 * * * *",
                                 "² * * * *", "٣ * * * *", "*/² * * * *"])           # Unicode digits: refused
def test_parse_errors(bad):
    with pytest.raises(crons.CronError):
        crons.parse(bad)


def test_next_runs_timezone():
    after = ts(2026, 7, 1, 4, 30)                                   # 06:30 in Paris (UTC+2)
    assert crons.next_runs("0 5 * * *", 2, after, PARIS) == [ts(2026, 7, 2, 3), ts(2026, 7, 3, 3)]
    assert crons.next_runs("0 5 * * *", 1, after, UTC) == [ts(2026, 7, 1, 5)]
    assert crons.next_runs("*/20 * * * *", 3, ts(2026, 1, 1, 0, 0), UTC) == \
        [ts(2026, 1, 1, 0, 20), ts(2026, 1, 1, 0, 40), ts(2026, 1, 1, 1, 0)]
    assert crons.next_runs("@reboot", 3) == []
    # Feb 29th: next leap year
    assert crons.next_runs("0 0 29 2 *", 1, ts(2026, 3, 1), UTC) == [ts(2028, 2, 29)]


def test_dom_dow_or_semantics():
    # 1st of the month OR any Monday (Vixie cron)
    runs = crons.next_runs("0 0 1 * 1", 3, ts(2026, 6, 1, 1), UTC)
    days = [dt.datetime.fromtimestamp(r, UTC).date() for r in runs]
    assert days == [dt.date(2026, 6, 8), dt.date(2026, 6, 15), dt.date(2026, 6, 22)]
    # day-of-week restricted only: AND with "*"
    runs = crons.next_runs("0 0 * * 1", 1, ts(2026, 6, 1, 1), UTC)
    assert dt.datetime.fromtimestamp(runs[0], UTC).date() == dt.date(2026, 6, 8)


def test_dst_is_monotonic():
    runs = crons.next_runs("30 2 * * *", 5, ts(2026, 3, 27), PARIS)   # 29 March: 02:30 does not exist
    assert runs == sorted(set(runs)) and len(runs) == 5
    runs = crons.next_runs("*/30 * * * *", 10, ts(2026, 10, 25, 0, 0), PARIS)   # fall back
    assert runs == sorted(set(runs))


@pytest.mark.parametrize("expr,text", [
    ("* * * * *", "every minute"),
    ("*/5 * * * *", "every 5 minutes"),
    ("0 * * * *", "every hour"),
    ("15 * * * *", "every hour at minute 15"),
    ("0 */6 * * *", "every 6 hours at :00"),
    ("0 5 * * *", "every day at 05:00"),
    ("30 7 * * 1-5", "at 07:30 on weekdays"),
    ("0 9 * * 1,3,5", "at 09:00 on Monday, Wednesday and Friday"),
    ("0 0 1 * *", "at 00:00 on the 1st of the month"),
    ("0 8 * 1 *", "at 08:00 in January"),
    ("@reboot", "at boot"),
    ("@weekly", "every Sunday at 00:00"),
    ("0 6,18 * * *", "every day at 06:00 and 18:00"),
    ("not valid", "not valid"),
])
def test_humanize(expr, text):
    assert crons.humanize(expr) == text


# ---- crontab bridge -------------------------------------------------------------------------
EXTERNAL = "MAILTO=\"\"\n# my own jobs\n0 3 * * * /usr/bin/backup.sh --all\n@reboot /opt/start.sh\n"


def test_crontab_block_preserves_external_lines(org, monkeypatch):
    monkeypatch.setattr(crons, "maxxing_bin", lambda: "/usr/local/bin/maxxing")
    org.crontab.write_text(EXTERNAL)
    j = crons.create_job({"name": "Hello", "schedule": "*/5 * * * *", "command": "echo hi"})
    text = org.crontab.read_text()
    assert text.startswith(EXTERNAL)
    assert crons.BLOCK_BEGIN in text and crons.BLOCK_END in text
    line = [ln for ln in text.splitlines() if j["id"] in ln][0]
    assert line.startswith("*/5 * * * * ") and line.endswith(f"/usr/local/bin/maxxing cron run {j['id']} >/dev/null 2>&1")
    assert "MAXXING_CRON_DETACH=1 /usr/local/bin/maxxing" in line and "--detach" not in line   # a rolled-back version runs it
    assert "MAXXING_STATE=" in line                                  # non-default state dir is passed on

    crons.update_job(j["id"], {"enabled": False})
    assert org.crontab.read_text() == EXTERNAL                      # block removed when nothing is enabled
    crons.update_job(j["id"], {"enabled": True})
    crons.sync_crontab()
    crons.sync_crontab()
    assert org.crontab.read_text().count(crons.BLOCK_BEGIN) == 1
    crons.delete_job(j["id"])
    assert org.crontab.read_text() == EXTERNAL

    ext = crons.external_jobs()
    assert ext == [{"schedule": "0 3 * * *", "command": "/usr/bin/backup.sh --all", "human": "every day at 03:00"},
                   {"schedule": "@reboot", "command": "/opt/start.sh", "human": "at boot"}]


def test_kept_server_clock_guards_lines(org, monkeypatch):
    """system_clock = keep: the system zone is never touched, lines fire hourly and check the schedule."""
    monkeypatch.setattr(crons, "maxxing_bin", lambda: "/usr/local/bin/maxxing")
    monkeypatch.setenv("MAXXING_SYSTEM_ZONE", "UTC")
    config.update_config(timezone="Europe/Paris", system_clock="follow")
    j = crons.create_job({"name": "Daily", "schedule": "30 9 * * 1-5", "command": "echo hi"})
    r = crons.create_job({"name": "Boot", "schedule": "@reboot", "command": "echo hi"})
    assert any(ln.startswith("30 9 * * 1-5 ") for ln in org.crontab.read_text().splitlines())

    config.update_config(system_clock="keep")
    crons.sync_crontab()
    lines = org.crontab.read_text().splitlines()
    daily = [ln for ln in lines if j["id"] in ln][0]
    assert daily.startswith("30 * * * * ") and f"cron run {j['id']} --if-due " in daily
    assert [ln for ln in lines if r["id"] in ln][0].startswith("@reboot ")
    # Monday 6 July 2026 09:30 in Paris = 07:30 UTC; not at 08:30 UTC nor on Saturday
    assert crons.is_due("30 9 * * 1-5", ts(2026, 7, 6, 7, 30))
    assert not crons.is_due("30 9 * * 1-5", ts(2026, 7, 6, 8, 30))
    assert not crons.is_due("30 9 * * 1-5", ts(2026, 7, 4, 7, 30))
    assert crons.is_due("30 9 * * 1-5", ts(2026, 1, 5, 8, 30))      # winter: UTC+1

    monkeypatch.setenv("MAXXING_SYSTEM_ZONE", "Asia/Kolkata")         # +5:30: minutes shift too
    crons.sync_crontab()
    assert [ln for ln in org.crontab.read_text().splitlines() if j["id"] in ln][0].startswith("* * * * * ")
    monkeypatch.setenv("MAXXING_SYSTEM_ZONE", "Europe/Paris")         # same zone: plain lines again
    crons.sync_crontab()
    assert [ln for ln in org.crontab.read_text().splitlines() if j["id"] in ln][0].startswith("30 9 * * 1-5 ")


def test_cron_run_if_due_skips(org, monkeypatch, capsys):
    from maxxing import cmd_cron
    monkeypatch.setenv("MAXXING_SYSTEM_ZONE", "UTC")
    config.update_config(timezone="Europe/Paris", system_clock="keep")
    j = crons.create_job({"name": "Never now", "schedule": "0 0 29 2 *", "command": "echo hi"})
    monkeypatch.setattr(crons, "run_job", lambda cid: pytest.fail("must not run"))
    assert cmd_cron._handler(types.SimpleNamespace(cron_cmd="run", id=j["id"], if_due=True)) == 0


def test_crontab_without_file_uses_crontab_command(org, monkeypatch):
    monkeypatch.delenv("MAXXING_CRONTAB_FILE")
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw.get("input")))
        if cmd == ["crontab", "-l"]:
            return types.SimpleNamespace(returncode=1, stdout="", stderr="no crontab for root")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(crons.subprocess, "run", fake_run)
    crons.create_job({"name": "x", "schedule": "@hourly", "command": "true"})
    written = [i for c, i in calls if c == ["crontab", "-"]]
    assert written and written[0].startswith(crons.BLOCK_BEGIN)


# ---- runs -----------------------------------------------------------------------------------
def test_run_shell_success_failure_timeout(org, monkeypatch):
    sent = []
    gw = types.ModuleType("maxxing.telegram.gateway")
    gw.notify_cron = sent.append
    monkeypatch.setitem(sys.modules, "maxxing.telegram.gateway", gw)
    import maxxing.telegram as tpkg
    monkeypatch.setattr(tpkg, "gateway", gw, raising=False)
    from maxxing import vault
    vault.put("MY_TOKEN", "s3cret-value", expose=True)

    ok = crons.create_job({"name": "ok", "command": "echo $MY_TOKEN; echo $MAXXING_CRON_NAME; pwd",
                           "notify": "always"})
    r = crons.run_job(ok["id"])
    assert r["ok"] and r["code"] == 0 and r["session_id"] is None
    assert r["output_tail"].splitlines() == ["s3cret-value", "ok", str(org.ws)]
    assert sent and sent[-1].startswith("OK - ok")
    assert str(org.ws) in sent[-1]                                  # notify always -> output included

    bad = crons.create_job({"name": "bad", "command": "echo boom; exit 3"})
    r = crons.run_job(bad["id"])
    assert not r["ok"] and r["code"] == 3 and "boom" in r["output_tail"]
    assert sent[-1].startswith("FAILED (code 3) - bad") and "boom" in sent[-1]

    slow = crons.create_job({"name": "slow", "command": "sleep 30", "timeout_s": 10, "notify": "never"})
    raw = crons._load_raw()
    for j in raw:
        if j["id"] == slow["id"]:
            j["timeout_s"] = 1                                       # below the API minimum, for speed
    crons._save_raw(raw)
    n = len(sent)
    t0 = time.time()
    r = crons.run_job(slow["id"])
    assert time.time() - t0 < 10 and r["code"] == 124 and "timed out" in r["output_tail"]
    assert len(sent) == n                                           # notify: never

    big = crons.create_job({"name": "big", "command": "head -c 10000 /dev/zero | tr '\\0' x"})
    r = crons.run_job(big["id"])
    assert len(r["output_tail"]) <= crons.OUTPUT_TAIL + 1 and r["output_tail"].startswith("…")

    jobs = {j["id"]: j for j in crons.list_jobs()}
    assert jobs[bad["id"]]["last_run"]["ok"] is False and jobs[ok["id"]]["last_run"]["code"] == 0
    assert [x["name"] for x in crons.read_runs(limit=2)] == ["big", "slow"]
    assert crons.read_runs(ok["id"])[0]["cron_id"] == ok["id"]
    assert crons.run_job("c_nope") is None


def test_run_claude_job(org, monkeypatch):
    (org.ws / "projects" / "acme" / "topics" / "blog").mkdir(parents=True)
    calls = []
    svc = types.ModuleType("maxxing.sessions.service")

    def create_session(path, **kw):
        calls.append(("create", path, kw))
        return {"id": "s-1"}
    svc.create_session = create_session
    svc.get_session = lambda sid: {"id": sid} if sid == "s-1" else None
    svc.send_message = lambda sid, text, **kw: calls.append(("send", sid, text, kw)) or {"queued": False}
    svc.wait_turn = lambda sid, timeout: {"id": sid, "state": "idle", "error": None}
    svc.last_assistant_text = lambda sid: "All done."
    monkeypatch.setitem(sys.modules, "maxxing.sessions.service", svc)
    import maxxing.sessions as pkg
    monkeypatch.setattr(pkg, "service", svc, raising=False)

    modes = []
    monkeypatch.setattr(crons, "store_mode", lambda sid, mode: modes.append((sid, mode)))
    j = crons.create_job({"name": "Digest", "kind": "claude", "topic_path": "projects/acme/topics/blog",
                          "prompt": "Summarise", "reuse_session": True, "model": "claude-sonnet-5-5",
                          "permission_mode": "acceptEdits"})
    r = crons.run_job(j["id"])
    assert r["ok"] and r["session_id"] == "s-1" and r["output_tail"] == "All done."
    kind, path, kw = calls[0]
    assert kind == "create" and path == "projects/acme/topics/blog"
    assert kw["source"] == "cron" and kw["cron"] is True and kw["title"].startswith("Digest - ")
    assert kw["model"] == "claude-sonnet-5-5" and kw["message"] == "Summarise"
    assert kw["permission_mode"] == "acceptEdits"
    r = crons.run_job(j["id"])                                      # reuse -> send_message
    assert calls[-1][:3] == ("send", "s-1", "Summarise") and calls[-1][3]["source"] == "cron"
    assert modes == [("s-1", "acceptEdits")]                        # the reused session follows the job

    svc.wait_turn = lambda sid, timeout: {"id": sid, "state": "error", "error": "boom"}
    svc.last_assistant_text = lambda sid: ""
    r = crons.run_job(j["id"])
    assert not r["ok"] and r["output_tail"] == "boom"


def test_claude_job_validation(org):
    with pytest.raises(crons.CronError) as e:
        crons.create_job({"name": "x", "kind": "claude", "topic_path": "nope", "prompt": "hi"})
    assert e.value.code == "invalid_topic"
    with pytest.raises(crons.CronError):
        crons.create_job({"name": "x", "kind": "claude", "topic_path": "", "prompt": ""})
    with pytest.raises(crons.CronError):
        crons.create_job({"name": "x", "command": "true", "schedule": "bad"})
    with pytest.raises(crons.CronError):
        crons.create_job({"name": "", "command": "true"})
    with pytest.raises(crons.CronError) as e:
        crons.create_job({"name": "x", "command": "true", "permission_mode": "yolo"})
    assert e.value.code == "invalid_permission_mode"


def test_runs_trimmed(org, monkeypatch):
    monkeypatch.setattr(crons, "MAX_RUNS", 10)
    for i in range(215):
        crons.append_run({"id": f"r{i}", "cron_id": "c_x", "at": i, "ok": True})
    lines = crons.runs_path().read_text().splitlines()
    assert len(lines) <= 10 + 200 and json.loads(lines[-1])["id"] == "r214"
    crons.runs_path().write_text(crons.runs_path().read_text() + "garbage\n")
    assert crons.read_runs(limit=1)[0]["id"] == "r214"


def test_runs_cache_follows_the_file(org):
    crons.append_run({"id": "r1", "cron_id": "c_a", "at": 1, "ok": True})
    first = crons.read_runs()
    assert [r["id"] for r in first] == ["r1"]
    first[0]["name"] = "annotated by a caller"                     # copies: the cache stays clean
    assert "name" not in crons.read_runs()[0]
    crons.append_run({"id": "r2", "cron_id": "c_b", "at": 2, "ok": False})
    assert [r["id"] for r in crons.read_runs()] == ["r2", "r1"]      # a new version of the file is re-read
    assert crons.last_runs()["c_a"]["id"] == "r1" and crons.read_runs("c_b")[0]["ok"] is False
    crons.runs_path().unlink()
    assert crons.read_runs() == []


def test_overlap_lock(org):
    j = crons.create_job({"name": "x", "command": "true"})
    import fcntl
    with open(crons._lock_path(j["id"]), "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        assert crons.is_running(j["id"])
        assert crons.run_job(j["id"]) is None
        with pytest.raises(crons.CronError):
            crons.spawn_run(j["id"])
    assert not crons.is_running(j["id"])


# ---- API ------------------------------------------------------------------------------------
def test_api_crud(client, org, monkeypatch):
    org.crontab.write_text(EXTERNAL)
    r = client.post("/api/crons", json={"name": "Ping", "schedule": "0 5 * * *", "command": "echo pong"})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["id"].startswith("c_") and job["human"] == "every day at 05:00" and job["next_run"] > time.time()
    assert job["last_run"] is None and job["notify"] == "failure" and job["running"] is False
    assert client.post("/api/crons", json={"name": "x", "schedule": "* *", "command": "x"}).json()["error"] == "invalid"
    assert client.post("/api/crons", json={"name": "x", "kind": "sql", "command": "x"}).status_code == 422

    data = client.get("/api/crons").json()
    assert [j["id"] for j in data["jobs"]] == [job["id"]] and len(data["external"]) == 2

    p = client.patch(f"/api/crons/{job['id']}", json={"enabled": False, "schedule": "@hourly"}).json()
    assert p["enabled"] is False and p["next_run"] is None and p["schedule"] == "@hourly"
    assert client.get(f"/api/crons/{job['id']}").json()["name"] == "Ping"
    assert client.patch("/api/crons/c_nope", json={"name": "x"}).status_code == 404

    spawned = []
    monkeypatch.setattr(crons.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    assert client.post(f"/api/crons/{job['id']}/run").json() == {"ok": True}
    assert spawned[0][-3:] == ["cron", "run", job["id"]]
    assert client.post("/api/crons/c_nope/run").status_code == 404

    crons.append_run({"id": "r1", "cron_id": job["id"], "name": "Ping", "at": time.time(), "ok": True,
                      "code": 0, "duration_s": 0.1, "output_tail": "pong", "session_id": None})
    runs = client.get(f"/api/crons/runs?cron_id={job['id']}&limit=5").json()
    assert runs[0]["output_tail"] == "pong"
    assert client.get("/api/crons").json()["jobs"][0]["last_run"]["ok"] is True

    assert client.delete(f"/api/crons/{job['id']}").json() == {"ok": True}
    assert client.delete(f"/api/crons/{job['id']}").status_code == 404


def test_spawn_systemd(org, monkeypatch):
    monkeypatch.delenv("MAXXING_SPAWN")
    monkeypatch.setattr(crons, "units_available", lambda: True)
    j = crons.create_job({"name": "x", "command": "true"})
    seen = []
    monkeypatch.setattr(crons.subprocess, "run",
                        lambda cmd, **kw: seen.append(cmd) or types.SimpleNamespace(returncode=0, stderr=""))
    crons.spawn_run(j["id"])
    cmd = seen[0]
    assert cmd[:2] == ["systemd-run", "--collect"] and f"maxxing-cron-{j['id'].replace('_', '-')}" in cmd
    assert any(a.startswith("--setenv=MAXXING_STATE=") for a in cmd)
    assert "OOMPolicy=continue" in cmd and "MemoryMax=75%" in cmd     # a runaway job is killed alone
    monkeypatch.setattr(crons.subprocess, "run",
                        lambda cmd, **kw: types.SimpleNamespace(returncode=1, stderr="Unit already exists"))
    with pytest.raises(crons.CronError) as e:
        crons.spawn_run(j["id"])
    assert e.value.code == "already_running"


def test_api_preview(client):
    r = client.get("/api/crons/preview", params={"schedule": "*/10 * * * *"}).json()
    assert r["valid"] and r["human"] == "every 10 minutes" and len(r["next"]) == 5
    assert r["next"] == sorted(r["next"]) and r["next"][1] - r["next"][0] == 600
    r = client.get("/api/crons/preview", params={"schedule": "nope"}).json()
    assert r["valid"] is False and r["next"] == [] and r["error"]


def test_preview_uses_config_timezone(org):
    config.update_config(timezone="Asia/Tokyo")
    nxt = crons.next_runs("0 9 * * *", 1)[0]
    assert dt.datetime.fromtimestamp(nxt, ZoneInfo("Asia/Tokyo")).hour == 9


def test_cli(org, capsys):
    from maxxing import cli
    j = crons.create_job({"name": "Cli job", "command": "echo hi"})
    assert cli.main(["cron", "run", j["id"]]) == 0
    assert cli.main(["cron", "run", "c_nope"]) == 2
    assert cli.main(["cron", "sync"]) == 0
    assert cli.main(["cron", "list"]) == 0
    out = capsys.readouterr().out
    assert "Cli job" in out and "every day at 05:00" in out and "ok " in out
    bad = crons.create_job({"name": "bad", "command": "false"})
    assert cli.main(["cron", "run", bad["id"]]) == 1


def test_claude_job_end_to_end(mx, monkeypatch, tmp_path):
    """Real sessions service + fake claude binary (conftest `mx` fixture)."""
    monkeypatch.setenv("MAXXING_CRONTAB_FILE", str(tmp_path / "crontab"))
    from maxxing import bus, workspace
    monkeypatch.setattr(bus, "_loop", None)                         # like the CLI: no server loop
    workspace.create_project("acme")
    workspace.create_topic("acme", "blog")
    j = crons.create_job({"name": "Digest", "kind": "claude", "topic_path": "projects/acme/topics/blog",
                          "prompt": "NOTOOL say hi", "timeout_s": 60, "reuse_session": True})
    r = crons.run_job(j["id"])
    assert r["ok"], r
    assert r["session_id"] and r["output_tail"]
    from maxxing.sessions import service
    s = service.get_session(r["session_id"])
    assert s["source"] == "cron" and s["title"].startswith("Digest - ")
    r2 = crons.run_job(j["id"])
    assert r2["session_id"] == r["session_id"]                       # reuse_session

    bad = crons.create_job({"name": "Broken", "kind": "claude", "topic_path": "projects/acme/topics/blog",
                            "prompt": "FAIL please", "timeout_s": 60})
    r3 = crons.run_job(bad["id"])
    assert not r3["ok"] and r3["session_id"] != r["session_id"]


def _zombie_cats() -> list[str]:
    import os
    from pathlib import Path
    out = []
    for st in Path("/proc").glob("[0-9]*/stat"):
        try:
            f = st.read_text().rsplit(")", 1)[-1].split()
        except OSError:
            continue
        if f[0] == "Z" and int(f[1]) == os.getpid() and st.read_text().split()[1] == "(cat)":
            out.append(st.parent.name)
    return out


def test_shell_job_drain_cat_is_reaped(org):
    """A job that leaves a background child holding its output: the `cat` draining it is reaped once it ends."""
    j = crons.create_job({"name": "bg", "command": "sleep 3 & echo started"})
    r = crons.run_job(j["id"])
    assert r["ok"] and "started" in r["output_tail"]
    time.sleep(2.5)                                   # the background sleep ends, cat sees EOF and exits
    assert not _zombie_cats(), "the drain cat was left as a zombie of the server"


def test_shell_job_gets_the_claude_turn_environment(org, tmp_path):
    """A script started by a shell job can call `claude -p`: same Claude folder and credentials as a turn."""
    from maxxing import config
    config.set_secret("claude_oauth_token", "sk-test-oauth")
    config.update_config(claude_dir=str(tmp_path / "own-claude"))
    j = crons.create_job({"name": "env", "command": "echo $CLAUDE_CODE_OAUTH_TOKEN; echo $CLAUDE_CONFIG_DIR"})
    r = crons.run_job(j["id"])
    assert r["ok"] and r["output_tail"].splitlines() == ["sk-test-oauth", str(tmp_path / "own-claude")]


def test_removed_jobs_are_kept_and_restored(org, monkeypatch, capsys):
    """A job deleted, or dropped by a hand edit of jobs.json, stays findable and comes back with its id."""
    from maxxing import cmd_cron
    keep = crons.create_job({"name": "Keep", "schedule": "0 5 * * *", "command": "echo keep"})
    a = crons.create_job({"name": "Radar - PR", "schedule": "0 3 1 1 *", "command": "echo a", "enabled": False})
    b = crons.create_job({"name": "Gone by hand", "schedule": "0 4 * * *", "command": "echo b"})
    assert crons.deleted_jobs() == []

    crons.delete_job(a["id"])
    data = json.loads(crons.jobs_path().read_text())            # a session rewrites jobs.json without b
    data["jobs"] = [j for j in data["jobs"] if j["id"] != b["id"]]
    crons.jobs_path().write_text(json.dumps(data))
    crons.sync_crontab()                                        # what `maxxing cron sync` does after a hand edit

    rows = crons.deleted_jobs()
    assert [(d["job"]["id"], d["reason"]) for d in rows] == [
        (b["id"], "vanished (jobs.json edited outside Harness Maxxing)"), (a["id"], "deleted")]
    assert cmd_cron._handler(types.SimpleNamespace(cron_cmd="deleted")) == 0
    assert a["id"] in capsys.readouterr().out

    assert cmd_cron._handler(types.SimpleNamespace(cron_cmd="restore", id=a["id"])) == 0
    r = crons.get_job(a["id"])
    assert r["name"] == "Radar - PR" and r["enabled"] is False and r["created"] == a["created"]
    assert cmd_cron._handler(types.SimpleNamespace(cron_cmd="restore", id=a["id"])) == 2      # already there
    assert cmd_cron._handler(types.SimpleNamespace(cron_cmd="restore", id="c_000000")) == 2   # never existed
    assert {j["id"] for j in crons.list_jobs()} == {keep["id"], a["id"]}


def test_restore_refuses_an_id_or_a_job_that_is_not_safe(org, monkeypatch):
    """deleted.jsonl is only a file: what comes back from it is checked before it reaches the crontab."""
    monkeypatch.setattr(crons, "maxxing_bin", lambda: "/usr/local/bin/maxxing")
    bad = "x >/dev/null; touch /tmp/PWN #"
    job = {"name": "Old", "schedule": "0 5 * * *", "kind": "shell", "command": "echo old", "enabled": True}
    crons.deleted_path().write_text(
        json.dumps({"at": 1, "reason": "deleted", "job": {**job, "id": bad}}) + "\n"
        + json.dumps({"at": 2, "reason": "deleted", "job": {"id": "c_bad000", "schedule": "nope"}}) + "\n")
    with pytest.raises(crons.CronError) as e:
        crons.restore_job(bad)
    assert e.value.code == "invalid_id"
    with pytest.raises(crons.CronError):
        crons.restore_job("c_bad000")
    assert crons.list_jobs() == []
    assert "touch /tmp/PWN" not in "\n".join(crons.managed_lines([{**job, "id": bad}]))


def test_a_hand_edit_noticed_at_the_next_save(org):
    """No `maxxing cron sync` after the hand edit: the next save through the API still archives the lost job."""
    a = crons.create_job({"name": "A", "schedule": "0 5 * * *", "command": "echo a"})
    data = json.loads(crons.jobs_path().read_text())
    data["jobs"] = []
    crons.jobs_path().write_text(json.dumps(data))
    crons.create_job({"name": "B", "schedule": "0 6 * * *", "command": "echo b"})
    assert [d["job"]["id"] for d in crons.deleted_jobs()] == [a["id"]]


def test_an_unreadable_jobs_json_is_not_an_empty_list(org):
    """A damaged or truncated jobs.json archives nothing as vanished and keeps jobs.seen.json: once the file
    is repaired, nothing was lost from the archive and no job comes back twice."""
    a = crons.create_job({"name": "A", "schedule": "0 5 * * *", "command": "echo a"})
    b = crons.create_job({"name": "B", "schedule": "0 6 * * *", "command": "echo b"})
    good = crons.jobs_path().read_text()
    seen = (crons._dir() / "jobs.seen.json").read_text()
    for bad in ("{trunc", '["not", "a", "dict"]', '{"version": 1, "jobs": 3}'):
        crons.jobs_path().write_text(bad)
        crons.sync_crontab()
        assert crons.deleted_jobs() == []
        assert (crons._dir() / "jobs.seen.json").read_text() == seen
    crons.jobs_path().write_text(good)
    crons.sync_crontab()
    assert crons.deleted_jobs() == []
    assert {j["id"] for j in crons.list_jobs()} == {a["id"], b["id"]}


def test_deleted_lists_even_with_a_bad_date(org, capsys):
    """deleted.jsonl is only a file: a date that is not a number (or out of range) does not break the list."""
    from maxxing import cmd_cron
    job = {"name": "Old", "schedule": "0 5 * * *", "kind": "shell", "command": "echo old", "enabled": True}
    crons.deleted_path().write_text("".join(
        json.dumps({"at": at, "reason": "deleted", "job": {**job, "id": f"c_old00{i}"}}) + "\n"
        for i, at in enumerate(["yesterday", 1e300, None, [1], True, 1700000000])))
    assert all(d["at"] in (0, 1e300, 1700000000) for d in crons.deleted_jobs())
    assert cmd_cron._handler(types.SimpleNamespace(cron_cmd="deleted")) == 0
    out = capsys.readouterr().out
    assert all(f"c_old00{i}" in out for i in range(6))


def test_job_with_a_non_text_id_is_ignored(org):
    good = crons.create_job({"name": "good", "command": "true"})
    p = crons.jobs_path()
    data = json.loads(p.read_text())
    data["jobs"].append({"id": ["a"], "name": "odd", "command": "true"})
    p.write_text(json.dumps(data))
    assert [j["id"] for j in crons.list_jobs()] == [good["id"]]
