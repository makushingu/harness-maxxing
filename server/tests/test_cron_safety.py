"""Shell jobs never spill their whole output to disk; a damaged crontab block never costs the user's own lines."""
from __future__ import annotations

import os
import tempfile
import time

from maxxing import crons


def _job(command: str, timeout_s: int = 60) -> dict:
    return {**crons.DEFAULTS, "id": "c_out", "name": "chatty", "command": command, "timeout_s": timeout_s}


def test_chatty_shell_job_keeps_only_the_tail_and_spills_nothing_to_disk(mx, tmp_path, monkeypatch):
    """20 MB of output: only the last OUTPUT_TAIL bytes are kept, none of it in a temp file (/tmp is often RAM)."""
    made = []

    def spy(*a, **kw):                                 # any temp file the run opens stays visible here
        kw.pop("dir", None)
        f = tempfile.NamedTemporaryFile(*a, dir=tmp_path, delete=False, **kw)
        made.append(f.name)
        return f
    monkeypatch.setattr(tempfile, "TemporaryFile", spy)
    ok, code, tail = crons._run_shell(_job("head -c 20000000 /dev/zero | tr '\\0' x; echo; echo the-end"))
    assert ok and code == 0
    assert tail.startswith("…") and tail.rstrip().endswith("the-end")
    assert len(tail.encode()) <= crons.OUTPUT_TAIL + len("…".encode())
    assert all(os.path.getsize(m) <= 1024 * 1024 for m in made)


def test_short_output_failure_and_timeout(mx):
    assert crons._run_shell(_job("echo hello; echo oops >&2; exit 3")) == (False, 3, "hello\noops\n")
    ok, code, tail = crons._run_shell(_job("echo started; sleep 30", timeout_s=1))
    assert (ok, code) == (False, 124) and tail.startswith("started") and "[timed out after 1 s]" in tail


def test_background_child_holding_the_output_does_not_hold_the_run(mx):
    """`daemon &` keeps the pipe open after bash exits: the run still ends right away with what was printed."""
    t = time.monotonic()
    ok, code, tail = crons._run_shell(_job("sleep 4 >/dev/null 2>&1 </dev/null & sleep 4 & echo launched"))
    assert ok and "launched" in tail and time.monotonic() - t < 3.5


def test_sync_keeps_user_lines_when_the_end_marker_was_deleted(mx, monkeypatch, tmp_path):
    tab = tmp_path / "crontab"
    monkeypatch.setenv("MAXXING_CRONTAB_FILE", str(tab))
    tab.write_text(f"{crons.BLOCK_BEGIN}\n0 5 * * * /usr/local/bin/maxxing cron run c_aaaaaa >/dev/null 2>&1\n"
                   "30 3 * * * /root/bin/my-own-backup.sh\n")              # the user deleted the END line by hand
    crons.sync_crontab([])
    text = tab.read_text()
    assert "my-own-backup.sh" in text and "c_aaaaaa" not in text
    outside, inside = crons.split_crontab(text)
    assert outside == ["30 3 * * * /root/bin/my-own-backup.sh"] and inside == []


def test_split_crontab_with_an_intact_block_is_unchanged(mx):
    text = f"MAILTO=\"\"\n{crons.BLOCK_BEGIN}\n* * * * * maxxing cron run c_1 --if-due\n{crons.BLOCK_END}\n0 1 * * * mine\n"
    assert crons.split_crontab(text) == (['MAILTO=""', "0 1 * * * mine"], ["* * * * * maxxing cron run c_1 --if-due"])



def test_background_child_keeps_writing_after_the_run(mx, tmp_path):
    """A child left running (`nohup app &`) still holds the output pipe once `maxxing cron run` has exited: it must
    not die of SIGPIPE at its next line."""
    import subprocess
    import sys
    mark = tmp_path / "alive"
    cmd = f"(sleep 3; for i in $(seq 200); do echo late; done; touch {mark}) &"
    code = f"from maxxing import crons; print(crons._run_shell({{**crons.DEFAULTS, 'id': 'c', 'name': 'c', 'command': {cmd!r}}})[0])"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "True", out.stderr[-500:]
    for _ in range(80):
        if mark.exists():
            break
        time.sleep(0.1)
    assert mark.exists()


def test_parallel_run_appends_survive_the_trim(mx):
    """8 processes append while the history gets trimmed (runs.jsonl replaced): no run is lost."""
    import json
    import subprocess
    import sys
    p = crons.runs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps({"id": f"old{i}"}) + "\n" for i in range(crons.MAX_RUNS + 150)))
    code = ("import sys\nfrom maxxing import crons\n"
            "for i in range(40):\n    crons.append_run({'id': f'r_{sys.argv[1]}_{i}', 'cron_id': 'c_x', 'pad': 'x' * 50})\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(k)]) for k in range(8)]
    assert [q.wait(timeout=60) for q in procs] == [0] * 8
    ids = {json.loads(line)["id"] for line in p.read_text().splitlines()}
    assert {f"r_{k}_{i}" for k in range(8) for i in range(40)} <= ids


def test_odd_timeouts_are_refused_or_fall_back_to_the_default(mx):
    """timeout_s inf through create_job: a CronError, not an OverflowError; "30" in a hand-edited jobs.json:
    the run still has a limit (it raised TypeError and left the job running unbounded)."""
    import pytest
    for v in (float("inf"), 1e999):
        with pytest.raises(crons.CronError):
            crons._clean({"name": "n", "command": "x", "timeout_s": v})
    assert crons._timeout({"timeout_s": "30"}) == 30 and crons._timeout({"timeout_s": float("inf")}) == crons.DEFAULT_TIMEOUT
    job = {**crons.DEFAULTS, "id": "c_x", "name": "n", "command": "echo hi", "timeout_s": [1]}
    ok, code, text = crons._run_shell(job)
    assert ok and code == 0 and "hi" in text
    assert any("RuntimeMaxSec=" in x for x in crons.unit_properties(job))
