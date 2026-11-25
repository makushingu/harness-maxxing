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


def test_a_fifo_a_link_or_a_huge_file_never_holds_the_turn(tmp_path):
    import threading
    root = tmp_path / "sessions"
    root.mkdir()
    os.mkfifo(root / "999999991.json")                          # open() for reading would wait for a writer forever
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"sessionId": "abc"}))
    (root / "999999992.json").symlink_to(target)
    (root / "999999993.json").write_text(json.dumps({"sessionId": "abc", "pad": "x" * runner.CLAIM_MAX}))
    out = []
    t = threading.Thread(target=lambda: out.append(runner._free_stale_claim("abc", {"CLAUDE_CONFIG_DIR": str(tmp_path)})),
                         daemon=True)
    t.start()
    t.join(5)
    assert out == [0]
    assert (root / "999999992.json").is_symlink() and (root / "999999993.json").exists()
