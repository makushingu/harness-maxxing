"""`maxxing cron …` sub-commands.

  maxxing cron run <id>   run a job now, in this process (what the job unit of "Run now" runs)
  maxxing cron run <id> --detach   start it in its transient systemd unit (what the crontab lines call)
  maxxing cron sync       rewrite the managed crontab block from jobs.json
  maxxing cron list       print the jobs, their schedule and last result
"""
from __future__ import annotations

import datetime as dt
import os
import sys

from . import cli, config


def _configure(p) -> None:
    sub = p.add_subparsers(dest="cron_cmd", required=True)
    r = sub.add_parser("run", help="run a job now and record the result")
    r.add_argument("id")
    r.add_argument("--if-due", action="store_true",
                   help="run only if the schedule matches now in the configured zone (server clock kept)")
    r.add_argument("--detach", action="store_true",
                   help="start the run in its transient systemd unit (memory cap, jobs budget) and return; "
                        "runs here when systemd is not available")
    sub.add_parser("sync", help="rewrite the managed crontab block")
    sub.add_parser("list", help="list jobs")


def _handler(a) -> int:
    from . import crons
    if a.cron_cmd == "run":
        if crons._raw_job(a.id) is None:
            print(f"unknown job {a.id}", file=sys.stderr)
            return 2
        if a.if_due and not crons.is_due(crons._raw_job(a.id).get("schedule", "")):
            return 0
        detach = getattr(a, "detach", False) or os.environ.pop(crons.DETACH_ENV, "") == "1"   # read once: never inherited
        # installed before 2.0.0a70 (cron_keep_background): scheduled runs stay in the cron process, as they were -
        # the background programs a job leaves keep living, and no unit name stays taken by them
        if detach and config.load_config().get("cron_keep_background"):
            detach = False
        if detach and crons.units_available():
            try:
                crons.spawn_run(a.id)
            except crons.CronError as e:
                print(f"job {a.id}: {e}", file=sys.stderr)
                if e.code == "already_running":
                    return 3
                # no unit (systemd busy, D-Bus error...): run it here rather than skip it without a trace
            else:
                return 0
        run = crons.run_job(a.id)
        if run is None:
            print(f"job {a.id} is already running", file=sys.stderr)
            return 3
        return 0 if run["ok"] else 1
    if a.cron_cmd == "sync":
        text = crons.sync_crontab()
        print(f"crontab synced ({len(crons.managed_lines(crons._load_raw()))} managed lines, "
              f"{len(text.splitlines())} lines total)")
        return 0
    zone = crons.tz()
    jobs = crons.list_jobs()
    if not jobs:
        print("no jobs")
    for j in jobs:
        last = j["last_run"]
        last_txt = "never run" if not last else (
            ("ok" if last["ok"] else f"failed ({last['code']})") + " "
            + dt.datetime.fromtimestamp(last["at"], zone).strftime("%Y-%m-%d %H:%M"))
        state = "on " if j["enabled"] else "off"
        print(f"{j['id']}  {state}  {j['schedule']:<15} {j['name']}  [{j['kind']}]  {j['human']}  - {last_txt}")
    ext = crons.external_jobs()
    if ext:
        print(f"\n{len(ext)} other crontab line(s) not managed by Harness Maxxing")
    return 0


cli.register("cron", "scheduled jobs (run, sync, list)", _configure, _handler)
