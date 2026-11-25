"""CPU priorities (maxxing/cpu.py): the three slices, `maxxing heavy`, the turn units, CPU pressure and who uses the
processor. Never the real systemd: paths under tmp_path, systemctl / exec monkeypatched."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from maxxing import cli, cmd_core, cmd_heavy, cmd_video, config, cpu, health
from maxxing.sessions import spawn


@pytest.fixture
def systemd(mx, tmp_path, monkeypatch):
    """A fake systemd: /etc/systemd/system and the unit under tmp_path, systemctl recorded."""
    etc, run = tmp_path / "etc-systemd", tmp_path / "run-systemd"
    etc.mkdir()
    run.mkdir()
    calls: list[tuple] = []
    monkeypatch.setattr(cpu, "SLICE_DIR", etc)
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path / "cgroup")
    monkeypatch.setattr(cmd_core, "SYSTEMD_DIR", run)
    monkeypatch.setattr(cmd_core, "JOBS_SLICE_PATH", etc / "maxxing-jobs.slice")
    monkeypatch.setattr(cmd_core, "UNIT_PATH", etc / "claude-maxxing.service")
    monkeypatch.setattr(cmd_core, "systemctl", lambda *a, **kw: calls.append(a) or (0, ""))
    monkeypatch.delenv("MAXXING_SPAWN")
    return SimpleNamespace(etc=etc, calls=calls, cgroup=tmp_path / "cgroup")


def test_slice_texts_follow_the_setting():
    on, off = {"cpu_priorities": True}, {"cpu_priorities": False}
    assert "[Slice]\nCPUWeight=1000\nIOWeight=1000\n" in cpu.slice_text(cpu.LIVE, on)
    assert "CPUWeight=100\nIOWeight=100\n" in cpu.slice_text(cpu.NORMAL, on)
    assert "CPUWeight=100\n" in cpu.slice_text(cpu.LIVE, off)          # off: equal weights, the files stay
    jobs = cmd_core.jobs_slice_text({"jobs_memory_max": "60%", "cpu_priorities": True})
    assert "Description=Harness Maxxing scheduled jobs\n\n[Slice]\nMemoryMax=60%\nCPUWeight=30\nIOWeight=30\n" in jobs
    assert "CPUWeight=100" in cmd_core.jobs_slice_text({"jobs_memory_max": "", "cpu_priorities": False})
    assert config.DEFAULT_CONFIG["cpu_priorities"] is True


def test_init_writes_the_slices_and_the_server_drop_in(systemd):
    assert cmd_core.ensure_cpu_slices() == "written (on)"
    live = (systemd.etc / "maxxing-live.slice").read_text()
    assert "CPUWeight=1000" in live and "CPUWeight=100\n" in (systemd.etc / "maxxing-turns.slice").read_text()
    assert "CPUWeight=30" in (systemd.etc / "maxxing-jobs.slice").read_text()
    drop = systemd.etc / "claude-maxxing.service.d" / "30-cpu-priority.conf"
    assert "[Service]\nSlice=maxxing-live.slice\n" in drop.read_text()
    assert systemd.calls.count(("daemon-reload",)) == 2                 # jobs slice + the others; never a restart
    assert not any("restart" in c for c in systemd.calls)
    assert cmd_core.ensure_cpu_slices() == "unchanged" and systemd.calls.count(("daemon-reload",)) == 2
    assert cmd_core.check_cpu_priorities()["level"] == cmd_core.OK

    (systemd.cgroup / "maxxing.slice" / "maxxing-live.slice").mkdir(parents=True)     # running: weight set now
    config.update_config(cpu_priorities=False)
    assert cmd_core.ensure_cpu_slices() == "written (off: equal weights)"
    assert "CPUWeight=100\n" in (systemd.etc / "maxxing-live.slice").read_text() and drop.is_file()
    assert ("set-property", "--runtime", "maxxing-live.slice", "CPUWeight=100", "IOWeight=100") in systemd.calls
    assert not any("maxxing-turns.slice" in c for c in systemd.calls if c[0] == "set-property")   # not running


def test_doctor_tells_slices_out_of_date(systemd):
    c = cmd_core.check_cpu_priorities()
    assert c["level"] == cmd_core.WARN and c["fix"] == "maxxing init" and "maxxing-live.slice" in c["detail"]
    cmd_core.ensure_cpu_slices()
    config.update_config(cpu_priorities=False)                           # setting changed by hand
    assert cmd_core.check_cpu_priorities()["level"] == cmd_core.WARN


def test_skipped_in_tests_and_without_systemd(mx, tmp_path, monkeypatch):
    monkeypatch.setattr(cpu, "SLICE_DIR", tmp_path / "etc")
    assert cmd_core.ensure_cpu_slices() == "skipped (no systemd)"       # MAXXING_SPAWN=direct
    assert not (tmp_path / "etc").exists() and cmd_core.check_cpu_priorities() is None
    assert cpu.set_level("maxxing-br-x.service", "live") is False


def test_turn_units_go_to_the_turns_slice(mx, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cpu, "SLICE_DIR", tmp_path)
    monkeypatch.setattr(spawn, "_runner_env", lambda: {})
    monkeypatch.setattr(spawn.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    spawn._start_unit("12345678-1234-1234-1234-123456789012")
    assert "--slice" not in calls[-1]                                   # no slice file yet (before `maxxing init`)
    (tmp_path / "maxxing-turns.slice").write_text("x")
    spawn._start_unit("12345678-1234-1234-1234-123456789012")
    cmd = calls[-1]
    assert cmd[cmd.index("--slice") + 1] == "maxxing-turns.slice" and cmd.index("--slice") < cmd.index("--")
    config.update_config(cpu_priorities=False)
    spawn._start_unit("12345678-1234-1234-1234-123456789012")
    assert "--slice" not in calls[-1]


def test_set_level(mx, monkeypatch):
    calls = []
    monkeypatch.setattr(cpu, "systemd_ok", lambda: True)
    monkeypatch.setattr(cpu.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=0))
    assert cpu.set_level("maxxing-br-1.service", "live") is True
    assert calls[-1] == ["systemctl", "set-property", "--runtime", "maxxing-br-1.service", "CPUWeight=1000", "IOWeight=1000"]
    assert cpu.set_level("maxxing-br-1.service", "fast") is False
    config.update_config(cpu_priorities=False)
    assert cpu.set_level("maxxing-br-1.service", "normal") is False and len(calls) == 1


def test_heavy_command_line(monkeypatch):
    env = {"MAXXING_SESSION": "abcdef12-3456-7890-abcd-ef1234567890"}
    argv = cpu.heavy_argv(["ffmpeg", "-i", "a.mov", "b.mp4"], env=env, systemd=True)
    assert argv[:5] == ["systemd-run", "--scope", "--quiet", "--collect", "--slice=maxxing-jobs.slice"]
    unit = next(a for a in argv if a.startswith("--unit="))[7:]
    assert unit.startswith("maxxing-heavy-session-abcdef12-") and unit.endswith(".scope")
    assert argv[argv.index("--") + 1:] == ["ffmpeg", "-i", "a.mov", "b.mp4"]
    assert cpu.heavy_unit({"MAXXING_CRON_ID": "c_f659ec"}, pid=7) == "maxxing-heavy-cron-c-f659ec-7.scope"
    assert cpu.heavy_unit({}, pid=7) == "maxxing-heavy-7.scope"
    monkeypatch.setattr(cpu.shutil, "which", lambda n: "/usr/bin/" + n)
    assert cpu.heavy_argv(["make"], env={}, systemd=False) == ["nice", "-n", "10", "ionice", "-c3", "make"]


def test_maxxing_heavy_execs_the_command(mx, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(cmd_heavy, "_exec", lambda f, argv: seen.append(argv))
    monkeypatch.setattr(cpu, "systemd_ok", lambda: False)
    assert cli.main(["heavy", "python3", "-c", "print(1)"]) == 0
    assert seen[-1][-3:] == ["python3", "-c", "print(1)"] and seen[-1][0] in ("nice", "ionice", "python3")
    assert cli.main(["heavy", "no-such-command-xyz"]) == 127 and len(seen) == 1
    assert cmd_heavy.run([]) == 2

    proj = tmp_path / "video"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "index.jsx").write_text("")
    monkeypatch.setattr(cmd_video, "render_cmd", lambda e, c, o: ["python3", "-V", e, c, o])
    monkeypatch.chdir(tmp_path)
    assert cmd_video.render(proj, "Intro", "out/v.mp4") == 0
    assert seen[-1][-5:] == ["python3", "-V", "src/index.jsx", "Intro", "out/v.mp4"]
    with pytest.raises(SystemExit):
        cmd_video.render(tmp_path / "nothing")


def test_pressure_parsing_and_the_alert(mx, monkeypatch, tmp_path):
    text = "some avg10=27.50 avg60=41.00 avg300=12.10 total=1\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
    assert cpu.parse_pressure(text) == {"avg10": 27.5, "avg60": 41.0, "avg300": 12.1}
    assert cpu.parse_pressure("") is None and cpu.parse_pressure("some avg10=x") is None
    monkeypatch.setitem(cpu._watch, "since", None)
    monkeypatch.setitem(cpu._watch, "seen", 0.0)
    p = cpu.parse_pressure(text)
    assert cpu.note_pressure(p, now=1000) == 0
    assert cpu.note_pressure(p, now=1240) == 240
    assert cpu.note_pressure(p, now=1700) == 0                            # no reading for 7 min: starts again
    assert cpu.note_pressure(p, now=1960) == 260
    assert cpu.note_pressure({"avg10": 0, "avg60": 5, "avg300": 0}, now=1990) == 0

    pf = tmp_path / "pressure"
    pf.write_text(text)
    monkeypatch.setattr(cpu, "PRESSURE_PATH", pf)
    monkeypatch.setattr(cpu, "snapshot", lambda force=False: {"top": [{"label": "Heavy · launch video"}]})
    monkeypatch.setattr(cpu, "note_pressure", lambda p, now=None: 720.0)
    h = health.collect(force=True)
    assert h["cpu_pressure"]["avg10"] == 27.5 and h["cpu_waiting"] is True
    issue = next(i for i in h["issues"] if i["code"] == "cpu_pressure")
    assert "12 min" in issue["text"] and "Heavy · launch video" in issue["text"]
    monkeypatch.setattr(cpu, "note_pressure", lambda p, now=None: 0.0)
    assert not [i for i in health.collect(force=True)["issues"] if i["code"] == "cpu_pressure"]   # clears itself


def test_unit_names(mx):
    from maxxing.sessions import store
    s = store.create(store.new_meta("projects/acme/topics/blog", "Launch post"))
    a = store.create(store.new_meta("projects/acme/topics/blog/agents/writer", "Writer"))
    assert cpu.describe("claude-maxxing.service") == ("harness", "Harness")
    assert cpu.describe(f"maxxing-{s['id'][:8]}.service") == ("session", "Launch post")
    assert cpu.describe(f"maxxing-{a['id'][:8]}-12345.service") == ("agent", "writer")
    assert cpu.describe(f"maxxing-heavy-session-{s['id'][:8]}-42.scope") == ("heavy", "Launch post")
    assert cpu.describe("maxxing-heavy-42.scope") == ("heavy", "")
    assert cpu.describe("maxxing-br-acme.service")[0] == "browser"
    assert cpu.describe("docker-1d59a7.scope") == ("docker", "")
    assert cpu.describe("cron-runner.service") == ("other", "cron-runner")
    assert cpu.label("session", "Launch post") == "Session · Launch post" and cpu.label("harness", "Harness") == "Harness"
    assert cpu.level_of("maxxing-turns.slice") == "normal" and cpu.level_of("system.slice") == "other"


def test_a_session_name_reads_only_the_metas_of_its_prefix(mx, monkeypatch):
    from maxxing.sessions import store
    ids = [store.create(store.new_meta("projects/acme/topics/blog", f"S{i}"))["id"] for i in range(20)]
    read, real = [], store.read_cached
    monkeypatch.setattr(store, "read_cached", lambda sid: (read.append(sid), real(sid))[1])
    names = cpu._Names()
    assert names.session(ids[7][:8])["title"] == "S7" and names.session(ids[7][:8])["title"] == "S7"
    assert names.session("ffffffff") is None
    assert read == [ids[7]]


def test_top_reads_the_cgroups(mx, tmp_path, monkeypatch):
    root = tmp_path / "cg"
    units = {"maxxing.slice/maxxing-live.slice/claude-maxxing.service": [0, 50_000],
             "maxxing.slice/maxxing-jobs.slice/maxxing-heavy-9.scope": [0, 900_000],
             "system.slice/docker-ab.scope": [0, 10_000], "system.slice/docker-cd.scope": [0, 20_000],
             "system.slice/idle.service": [0, 0]}
    for rel in units:
        (root / rel).mkdir(parents=True)
    monkeypatch.setattr(cpu, "CGROUP_ROOT", root)
    monkeypatch.setattr(cpu.os, "cpu_count", lambda: 1)
    clock = iter([100.0, 101.0])
    monkeypatch.setattr(cpu, "_clock", lambda: next(clock))
    monkeypatch.setattr(cpu, "_sleep", lambda s: [(root / r / "cpu.stat").write_text(f"usage_usec {v[1]}\n") for r, v in units.items()])
    for r, v in units.items():
        (root / r / "cpu.stat").write_text(f"usage_usec {v[0]}\n")
    monkeypatch.setitem(cpu._prev, "usage", {})
    rows = cpu.top()
    assert [(r["kind"], r["level"], r["pct"]) for r in rows] == [("heavy", "background", 90.0), ("harness", "live", 5.0),
                                                                    ("docker", "other", 3.0)]   # containers in one row


def test_top_never_waits_without_a_readable_cgroup(mx, tmp_path, monkeypatch):
    # an empty sample left `prev` empty: every call slept 0.5 s (holding the lock) to return nothing
    monkeypatch.setattr(cpu, "CGROUP_ROOT", tmp_path / "none")
    sleeps = []
    monkeypatch.setattr(cpu, "_sleep", sleeps.append)
    monkeypatch.setitem(cpu._prev, "usage", {})
    assert [cpu.top() for _ in range(3)] == [[], [], []]
    assert sleeps == []


def test_parallel_forced_snapshots_share_one_sample(mx, monkeypatch):
    calls = []
    monkeypatch.setattr(cpu, "top", lambda n=cpu.TOP_N: calls.append(1) or [])
    monkeypatch.setattr(cpu, "_cache", {"at": 0.0, "data": None})
    for _ in range(4):
        cpu.snapshot(force=True)
    assert len(calls) == 1
    cpu._cache["at"] -= cpu.FORCE_S
    cpu.snapshot(force=True)
    assert len(calls) == 2


def test_cpu_endpoint_and_setting(client, monkeypatch):
    monkeypatch.setattr(cpu, "top", lambda n=cpu.TOP_N: [])
    r = client.get("/api/system/cpu", params={"force": 1}).json()
    assert r["enabled"] is True and r["top"] == [] and "pressure" in r and "waiting" in r
    assert client.get("/api/settings").json()["cpu_priorities"] is True
    s = client.put("/api/settings", json={"cpu_priorities": False}).json()
    assert s["cpu_priorities"] is False and config.load_config()["cpu_priorities"] is False
