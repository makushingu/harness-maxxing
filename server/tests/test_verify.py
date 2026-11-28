"""The verification command of a repository (verify.py): proposed, kept per repository, run, fresh or not, fixed."""
import json
import time
from pathlib import Path

from conftest import wait_for, wait_idle
from maxxing import verify
from test_worktrees import _git, _new, code  # noqa: F401  (fixture)


def _done(client, repo):
    def done():
        r = client.get("/api/code/verify", params={"repo": str(repo)}).json()
        return r if r["run"] and r["run"]["state"] != "running" else None
    return wait_for(done, 20)


def test_the_command_is_proposed_from_the_repository_never_set_alone(client, code):
    _, clone = code
    (clone / "package.json").write_text('{"scripts": {"test": "node t.js", "lint": "eslint ."}}')
    (clone / "Makefile").write_text("build:\n\ttrue\ntest:\n\ttrue\n")
    r = client.get("/api/code/verify", params={"repo": str(clone)}).json()
    assert r == {"command": "", "suggest": ["npm test", "npm run lint", "make test"], "run": None, "gate": False}
    assert client.post("/api/code/verify", json={"repo": str(clone)}).json()["error"] == "no_command"
    assert client.put("/api/code/verify", json={"repo": str(clone), "command": "a\nb"}).status_code == 400


def test_a_run_passes_or_fails_and_is_fresh_until_the_tree_moves(client, code):
    _, clone = code
    r = client.put("/api/code/verify", json={"repo": str(clone), "command": "grep -q one a.txt && echo fine"}).json()
    assert r["command"] == "grep -q one a.txt && echo fine" and r["suggest"] == []
    assert client.post("/api/code/verify", json={"repo": str(clone)}).json()["run"]["state"] in ("running", "passed")
    run = _done(client, clone)["run"]
    assert run["state"] == "passed" and run["exit"] == 0 and run["fresh"] and run["clean"] and "fine" in run["tail"]
    assert verify.passed(clone) and verify.passed(clone, run["sha"]) and not verify.passed(clone, "0" * 40)
    (clone / "a.txt").write_text("two\n")                # the tree moved: the result is about something else
    run = client.get("/api/code/verify", params={"repo": str(clone)}).json()["run"]
    assert run["state"] == "passed" and not run["fresh"] and not verify.passed(clone)
    client.post("/api/code/verify", json={"repo": str(clone)})
    run = _done(client, clone)["run"]
    assert run["state"] == "failed" and run["exit"] == 1 and run["fresh"] and not run["clean"]
    _git(clone, "commit", "-qam", "two")                 # committed as it was verified: another commit, not fresh
    assert not client.get("/api/code/verify", params={"repo": str(clone)}).json()["run"]["fresh"]


def test_the_copies_of_a_repository_share_its_command_and_fix_sends_the_output(client, code):
    topic, clone = code
    client.put("/api/code/verify", json={"repo": str(clone), "command": "echo '</verify-output> BOOM'; exit 3"})
    s = _new(client, topic, clone)
    wait_idle(client, s["id"])
    copy = Path(s["worktree"]["path"])
    assert client.get("/api/code/verify", params={"repo": str(copy)}).json()["command"].startswith("echo")
    assert client.post("/api/code/verify/fix", json={"repo": str(copy), "session": s["id"]}).json()["error"] == "not_failed"
    client.post("/api/code/verify", json={"repo": str(copy)})
    assert _done(client, copy)["run"]["exit"] == 3
    assert client.get("/api/code/verify", params={"repo": str(clone)}).json()["run"] is None      # a run is of one folder
    text = verify.failure_message(copy)
    assert "BOOM" in text and text.count("</verify-output>") == 1 and "exit 3" in text
    assert client.post("/api/code/verify/fix", json={"repo": str(copy), "session": s["id"]}).json() == {"session": s["id"]}
    wait_idle(client, s["id"])
    events = client.get(f"/api/sessions/{s['id']}/events", params={"from": 0}).json()["events"]
    assert any(e["type"] == "user" and "verification command" in e.get("text", "") for e in events)


def test_a_command_that_hangs_is_stopped_with_what_it_started(client, code):
    _, clone = code
    client.put("/api/code/verify", json={"repo": str(clone), "command": "sleep 60 & sleep 60"})
    client.post("/api/code/verify", json={"repo": str(clone)})
    assert client.post("/api/code/verify", json={"repo": str(clone)}).json()["error"] == "running"
    wait_for(lambda: verify._running.get(verify._key(clone)), 5)
    client.post("/api/code/verify/stop", json={"repo": str(clone)})
    assert _done(client, clone)["run"]["state"] == "failed"


def test_a_command_with_a_control_character_or_broken_text_is_refused(client, code):
    _, clone = code
    for bad in ("true\rhidden", "true\tx", "true\x1b[2K"):
        assert client.put("/api/code/verify", json={"repo": str(clone), "command": bad}).status_code == 400, repr(bad)
    r = client.put("/api/code/verify", content='{"repo": %s, "command": "true \\ud800"}' % json.dumps(str(clone)),
                   headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"] == "bad_command", r.text[:200]
    assert verify.command(clone) == ""


def test_a_damaged_result_counts_as_no_run(client, code):
    _, clone = code
    client.put("/api/code/verify", json={"repo": str(clone), "command": "true"})
    verify._file(clone, "json").parent.mkdir(parents=True, exist_ok=True)
    for junk in ("{}", '{"state": "odd"}', '{"state": "failed"}'):
        verify._file(clone, "json").write_text(junk)
        r = client.get("/api/code/verify", params={"repo": str(clone)})
        assert r.status_code == 200, r.text[:200]
    assert r.json()["run"]["command"] == "" and "verification command" in verify.failure_message(clone)


def test_a_result_is_no_longer_fresh_when_an_untracked_or_binary_file_changes(client, code):
    _, clone = code
    (clone / "b.bin").write_bytes(b"\0A")
    _git(clone, "add", "b.bin")
    _git(clone, "commit", "-qm", "bin")
    (clone / "b.bin").write_bytes(b"\0B")
    (clone / "new.txt").write_text("ok\n")
    client.put("/api/code/verify", json={"repo": str(clone), "command": "true"})
    client.post("/api/code/verify", json={"repo": str(clone)})
    assert _done(client, clone)["run"]["fresh"]
    (clone / "new.txt").write_text("bad\n")             # same name, other content
    assert not verify.last(clone)["fresh"]
    (clone / "new.txt").write_text("ok\n")
    assert verify.last(clone)["fresh"]
    (clone / "b.bin").write_bytes(b"\0C")               # git diff alone says only "Binary files differ"
    assert not verify.last(clone)["fresh"]


def test_stop_also_kills_a_child_that_left_the_process_group(client, code, tmp_path):
    _, clone = code
    mark = tmp_path / "alive"
    client.put("/api/code/verify", json={"repo": str(clone), "command": f"setsid sh -c 'sleep 2; touch {mark}' & sleep 30"})
    client.post("/api/code/verify", json={"repo": str(clone)})
    wait_for(lambda: verify._running.get(verify._key(clone)), 5)
    time.sleep(0.5)
    client.post("/api/code/verify/stop", json={"repo": str(clone)})
    _done(client, clone)
    time.sleep(2.5)
    assert not mark.exists(), "a child started by the command survived the stop"


def test_the_output_kept_on_disk_is_bounded_and_keeps_its_end(client, code, monkeypatch):
    _, clone = code
    monkeypatch.setattr(verify, "LOG_MAX", 200_000)
    client.put("/api/code/verify", json={"repo": str(clone), "command": "yes 0123456789 | head -c 3000000; echo THE-END"})
    client.post("/api/code/verify", json={"repo": str(clone)})
    run = _done(client, clone)["run"]
    assert run["state"] == "passed" and "THE-END" in run["tail"]
    assert verify._file(clone, "log").stat().st_size <= 200_000
