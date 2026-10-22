"""Stop / steer signals reach the right runner: never lost right after a turn starts, never sent to a dead one."""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import time

import pytest

from maxxing.sessions import runner as runner_mod, service, store


def _raw(sid: str) -> list[dict]:
    return [json.loads(x) for x in store.log_path(sid).read_text().splitlines() if x.strip()]


@pytest.mark.parametrize("how", ["stop", "steer"])
def test_a_signal_right_after_the_turn_starts_is_not_lost(mx, monkeypatch, how):
    """A Stop (SIGTERM) or a steer (SIGUSR1) that lands just after the runner popped its item ends that turn."""
    meta = store.new_meta("", "race")
    meta["queue"] = [{"text": "work PAUSE NOTOOL", "attachments": [], "source": "web", "kind": "user",
                      "at": time.time()}]
    meta["state"] = "running"
    store.create(meta)
    sid = meta["id"]
    orig, fired = runner_mod.Runner._pop, []

    def pop(self, failed):
        item = orig(self, failed)
        if item is not None and not fired:          # the server's signal arrives right after the lock is released
            fired.append(1)
            if how == "stop":
                self.on_sigterm()
            else:
                store.update(sid, steer_turn=self.turn_id)
                self.on_steer()
        return item
    monkeypatch.setattr(runner_mod.Runner, "_pop", pop)
    old = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1)}
    try:
        runner_mod.Runner(sid).run()
    finally:
        for s, h in old.items():
            signal.signal(s, h)
    done = [e for e in _raw(sid) if e.get("type") == "mx_done"]
    assert done and done[-1]["stopped"] is True, "the signal was ignored: the turn ran to its end"


def test_stop_never_signals_the_pid_of_a_dead_runner(mx):
    """A runner killed without cleanup (OOM, kill -9) leaves its pid in the meta; the pid may now be another
    process's: Stop must not send it SIGTERM."""
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        meta = store.new_meta("", "stale")
        meta.update(state="running", pid=victim.pid, spawned_at=None)
        store.create(meta)
        service.stop(meta["id"])
        time.sleep(0.3)
        assert victim.poll() is None, "stop() sent SIGTERM to a process that is not the session's runner"
        assert store.read(meta["id"])["state"] == "idle"
    finally:
        victim.kill()
        victim.wait()


def test_a_new_runner_does_not_inherit_the_dead_runners_pid(mx, monkeypatch):
    """Queuing a message to a session whose runner died clears the stale pid while the new runner starts."""
    monkeypatch.setattr(service, "_spawn", lambda sid: None)       # observe the meta before the runner pops
    meta = store.new_meta("", "stale")
    meta.update(state="idle", pid=999999)
    store.create(meta)
    service.send_message(meta["id"], "hello NOTOOL")
    m = store.read(meta["id"])
    assert m["state"] == "running" and m.get("pid") is None


def test_claude_killed_by_the_oom_killer_says_so(mx, monkeypatch, tmp_path):
    """Claude SIGKILLed while the unit's oom_kill counter went up: the turn error speaks of memory, not of code -9."""
    rel = next((x[3:].strip() for x in open("/proc/self/cgroup").read().splitlines() if x.startswith("0::")), None)
    if rel is None:
        pytest.skip("no cgroup v2")
    events = tmp_path / "cg" / rel.lstrip("/") / "memory.events"
    events.parent.mkdir(parents=True)
    events.write_text("low 0\nhigh 0\nmax 4\noom 1\noom_kill 1\n")
    monkeypatch.setattr(runner_mod, "CGROUP_FS", tmp_path / "cg")
    fake = tmp_path / "oom-claude.sh"           # the kernel kills Claude: the counter goes up, then SIGKILL
    fake.write_text(f"#!/bin/sh\nprintf 'oom 2\\noom_kill 2\\n' > '{events}'\nkill -9 $$\n")
    fake.chmod(0o755)
    meta = store.new_meta("", "oom")
    store.create(meta)
    r = runner_mod.Runner(meta["id"])
    a = r.attempt([str(fake)], "hi", str(tmp_path), {"PATH": "/usr/bin:/bin"}, None, False)
    assert a.rc == -9
    err = r._record(a, {"text": "hi"})
    assert "out of memory" in err and store.read(meta["id"])["error"] == err
    # killed without a new OOM kill (a stop, kill -9 by hand): the plain exit code
    a = r.attempt(["sh", "-c", "kill -9 $$"], "hi", str(tmp_path), {"PATH": "/usr/bin:/bin"}, None, False)
    assert r._record(a, {"text": "hi"}) == "Claude exited with code -9"
