"""Scheduled jobs run in their transient systemd unit (memory cap, jobs slice) like "Run now", and a timed-out
job never leaves a process behind (audit F07 / F08)."""
from __future__ import annotations

import argparse
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

from _org_helpers import org  # noqa: F401
from maxxing import cmd_cron, cmd_core, config, crons

FAKE_SYSTEMD_RUN = textwrap.dedent("""\
    #!{python}
    # Fake systemd-run: records its arguments, then runs the command after `--` (synchronously) with the --setenv's.
    import json, os, subprocess, sys
    args = sys.argv[1:]
    with open(os.environ["FAKE_SYSTEMD_LOG"], "a") as f:
        f.write(json.dumps(args) + "\\n")
    cmd = args[args.index("--") + 1:]
    env = dict(os.environ)
    for a in args[:args.index("--")]:
        if a.startswith("--setenv="):
            k, _, v = a[len("--setenv="):].partition("=")
            env[k] = v
    sys.exit(subprocess.run(cmd, env=env).returncode)
    """)


def _alive(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(") ", 1)[1][0] != "Z"
    except OSError:
        return False


def _ns(cid: str, detach: bool = True) -> argparse.Namespace:
    return argparse.Namespace(cron_cmd="run", id=cid, if_due=False, detach=detach)


@pytest.fixture
def units(org, tmp_path, monkeypatch):  # noqa: F811
    """systemd 'available': a fake systemd-run first on PATH and a fake /run/systemd/system."""
    bindir, sysdir = tmp_path / "bin", tmp_path / "run-systemd"
    bindir.mkdir()
    sysdir.mkdir()
    fake = bindir / "systemd-run"
    fake.write_text(FAKE_SYSTEMD_RUN.format(python=sys.executable))
    fake.chmod(0o755)
    log = tmp_path / "systemd-run.log"
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SYSTEMD_LOG", str(log))
    monkeypatch.delenv("MAXXING_SPAWN")
    monkeypatch.setattr(crons, "SYSTEMD_DIR", sysdir)
    return log


def test_timeout_kills_a_child_that_ignores_sigterm(org, tmp_path, monkeypatch):  # noqa: F811
    """Audit F08 reproduction: bash dies on SIGTERM, its child ignores it - it used to outlive the failed run."""
    monkeypatch.setattr(crons, "KILL_GRACE_S", 0.5, raising=False)
    pidfile = tmp_path / "child.pid"
    job = {**crons.DEFAULTS, "id": "c_stub", "name": "stubborn", "timeout_s": 1,
           "command": f"bash -c 'trap \"\" TERM; exec sleep 60' & echo $! > {pidfile}; wait"}
    t = time.monotonic()
    ok, code, tail = crons._run_shell(job)
    assert (ok, code) == (False, 124) and "[timed out after 1 s]" in tail
    pid = int(pidfile.read_text())
    end = time.monotonic() + 3
    while _alive(pid) and time.monotonic() < end:
        time.sleep(0.05)
    alive = _alive(pid)
    if alive:
        os.kill(pid, 9)
    assert not alive, "the child ignoring SIGTERM survived the timeout"
    assert time.monotonic() - t < 6


def test_crontab_lines_start_the_job_in_its_unit(org):  # noqa: F811
    j = crons.create_job({"name": "nightly", "command": "true", "schedule": "0 3 * * *"})
    assert any(f"MAXXING_CRON_DETACH=1 " in line and line.endswith(f"cron run {j['id']} >/dev/null 2>&1")
               for line in crons.read_crontab().splitlines())


def test_scheduled_run_goes_through_a_job_unit_with_memory_caps(org, units):  # noqa: F811
    """Audit F07: the crontab path (`cron run <id> --detach`) uses the same unit as "Run now"."""
    j = crons.create_job({"name": "nightly", "command": "echo from-the-unit", "timeout_s": 300})
    assert cmd_cron._handler(_ns(j["id"])) == 0
    import json
    args = json.loads(units.read_text().splitlines()[0])
    assert "--unit" in args and args[args.index("--unit") + 1] == crons.unit_name(j["id"])
    assert "--slice=maxxing-jobs.slice" in args                       # the budget of all jobs together
    assert "MemoryMax=75%" in args and "OOMPolicy=continue" in args   # the cap of this job
    assert f"RuntimeMaxSec={300 + int(crons.KILL_GRACE_S) + crons.UNIT_RUNTIME_MARGIN_S}" in args
    assert args[args.index("--") + 1:][-3:] == ["cron", "run", j["id"]]   # the unit runs it inline
    run = crons.read_runs(j["id"])[0]
    assert run["ok"] and "from-the-unit" in run["output_tail"]


def test_run_now_uses_the_same_unit(org, units):  # noqa: F811
    j = crons.create_job({"name": "x", "command": "true"})
    crons.spawn_run(j["id"])
    import json
    args = json.loads(units.read_text().splitlines()[0])
    assert "--slice=maxxing-jobs.slice" in args and "MemoryMax=75%" in args


def test_detach_without_systemd_runs_here_with_the_timeout(org, tmp_path, monkeypatch):  # noqa: F811
    """Containers without systemd: the crontab line still runs the job (in the cron process), timeout included."""
    monkeypatch.delenv("MAXXING_SPAWN")
    monkeypatch.setattr(crons, "SYSTEMD_DIR", tmp_path / "absent")
    assert not crons.units_available()
    ok = crons.create_job({"name": "ok", "command": "echo here"})
    assert cmd_cron._handler(_ns(ok["id"])) == 0
    assert crons.read_runs(ok["id"])[0]["output_tail"].strip() == "here"
    slow = crons.create_job({"name": "slow", "command": "sleep 30", "notify": "never"})
    raw = crons._load_raw()
    for x in raw:
        if x["id"] == slow["id"]:
            x["timeout_s"] = 1
    crons._save_raw(raw)
    monkeypatch.setattr(crons, "KILL_GRACE_S", 0.3)
    t = time.monotonic()
    assert cmd_cron._handler(_ns(slow["id"])) == 1
    assert time.monotonic() - t < 5 and crons.read_runs(slow["id"])[0]["code"] == 124


def test_init_writes_the_jobs_slice(tmp_path, monkeypatch):
    path, sysdir = tmp_path / "maxxing-jobs.slice", tmp_path / "run-systemd"
    sysdir.mkdir()
    calls = []
    monkeypatch.setattr(cmd_core, "JOBS_SLICE_PATH", path)
    monkeypatch.setattr(cmd_core, "SYSTEMD_DIR", sysdir)
    monkeypatch.setattr(cmd_core, "systemctl", lambda *a, **kw: calls.append(a) or (0, ""))
    monkeypatch.setattr(config, "load_config", lambda: {"jobs_memory_max": "60%"})
    assert cmd_core.ensure_jobs_slice() == "skipped (no systemd)"      # tests run with MAXXING_SPAWN=direct
    monkeypatch.delenv("MAXXING_SPAWN")
    assert cmd_core.ensure_jobs_slice() == "written"
    assert "[Slice]\nMemoryMax=60%\n" in path.read_text() and calls == [("daemon-reload",)]
    assert cmd_core.ensure_jobs_slice() == "unchanged" and len(calls) == 1
    monkeypatch.setattr(config, "load_config", lambda: {"jobs_memory_max": ""})
    assert cmd_core.ensure_jobs_slice() == "written" and "MemoryMax" not in path.read_text()


def test_a_unit_that_cannot_start_still_runs_the_job(org, units, tmp_path):  # noqa: F811
    """Adapted at integration: systemd-run failing (D-Bus error, systemd busy) used to skip the scheduled run
    without a trace (the crontab line sends everything to /dev/null): the job now runs in the cron process."""
    broken = tmp_path / "bin" / "systemd-run"
    broken.write_text("#!/bin/sh\necho 'Failed to connect to bus' >&2\nexit 1\n")
    j = crons.create_job({"name": "nightly", "command": "echo ran-anyway"})
    assert cmd_cron._handler(_ns(j["id"])) == 0
    assert "ran-anyway" in crons.read_runs(j["id"])[0]["output_tail"]


def test_the_crontab_variable_detaches_like_the_flag(org, units, monkeypatch):  # noqa: F811
    """Adapted at integration: the crontab lines carry MAXXING_CRON_DETACH=1 instead of `--detach`, which a version
    restored by a rollback would refuse (every job silent)."""
    j = crons.create_job({"name": "nightly", "command": "echo via-env"})
    monkeypatch.setenv("MAXXING_CRON_DETACH", "1")
    assert cmd_cron._handler(_ns(j["id"], detach=False)) == 0
    assert units.exists() and "maxxing-cron-" in units.read_text()


def test_installs_from_before_a70_keep_scheduled_runs_in_the_cron_process(org, units):  # noqa: F811
    """Adapted at integration: `cron_keep_background` -> no unit for scheduled runs (their background programs keep
    living, and no leftover process keeps the fixed unit name taken so the next run is not skipped)."""
    raw = config.load_config()
    raw["cron_keep_background"] = True
    config.write_json(config.config_path(), raw)
    j = crons.create_job({"name": "nightly", "command": "echo inline"})
    assert cmd_cron._handler(_ns(j["id"])) == 0
    assert not units.exists()                                         # systemd-run never called
    assert "inline" in crons.read_runs(j["id"])[0]["output_tail"]
