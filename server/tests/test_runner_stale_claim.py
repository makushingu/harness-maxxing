import json
import os
import subprocess
import sys

from maxxing.sessions import runner


def test_a_claim_left_by_a_dead_process_is_removed(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (root / f"{dead.pid}.json").write_text(json.dumps({"pid": dead.pid, "sessionId": "abc", "procStart": "1"}))
    with open(f"/proc/{os.getpid()}/stat") as fh:
        me = fh.read().rsplit(")", 1)[1].split()[19]
    (root / f"{os.getpid()}.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": "abc", "procStart": me}))
    (root / "999999999.json").write_text(json.dumps({"sessionId": "other"}))
    assert runner._free_stale_claim("abc", {"CLAUDE_CONFIG_DIR": str(tmp_path)}) == 1
    assert not (root / f"{dead.pid}.json").exists()           # dead process: freed
    assert (root / f"{os.getpid()}.json").exists()            # running: kept
    assert (root / "999999999.json").exists()                 # another thread: untouched


def test_a_reused_pid_does_not_keep_the_claim(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    (root / f"{os.getpid()}.json").write_text(json.dumps({"sessionId": "abc", "procStart": "1"}))
    assert runner._free_stale_claim("abc", {"CLAUDE_CONFIG_DIR": str(tmp_path)}) == 1
