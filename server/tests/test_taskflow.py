"""A task and the session that does it (taskflow.py): its branch, its pull request, done when it is merged."""
from pathlib import Path

from conftest import wait_idle
from maxxing import gitview, taskflow
from maxxing.sessions import store
from test_worktrees import _git, _new, code  # noqa: F401  (fixture)


def _task(client, tid):
    return next(t for t in client.get("/api/tasks").json()["tasks"] if t["id"] == tid)


def _started(client, code):
    topic, clone = code
    t = client.post("/api/tasks", json={"title": "Fix the login page", "topic_path": topic}).json()
    assert t["session"] is None and t["work"] is None
    s = _new(client, topic, clone)
    wait_idle(client, s["id"])
    r = client.post(f"/api/tasks/{t['id']}/session", json={"session": s["id"]})
    assert r.status_code == 200 and r.json()["status"] == "doing" and r.json()["session"] == s["id"]
    return t["id"], s, clone


def _github(monkeypatch, status):
    monkeypatch.setattr(gitview, "github_name", lambda remote: "acme/app")
    monkeypatch.setattr(gitview, "branch_status", lambda full, branch, sha: status(branch, sha))
    monkeypatch.setattr("maxxing.codediff.repo_head", _head(__import__("maxxing.codediff").codediff.repo_head))


def _head(real):
    def head(folder):
        return {**real(folder), "remote": "git@github.com:acme/app.git"}
    return head


def test_a_started_task_shows_the_pull_request_of_its_session(client, code, monkeypatch):
    tid, s, _ = _started(client, code)
    checks = {"total": 2, "ok": 1, "failed": 1, "pending": 0}
    _github(monkeypatch, lambda branch, sha: {"pr": {"number": 7, "url": "https://github.com/acme/app/pull/7",
                                                        "title": "x", "draft": False, "base": "main"},
                                              "merged_pr": None, "checks": checks})
    taskflow.scan()
    t = _task(client, tid)
    assert t["work"]["branch"] == s["worktree"]["branch"] and t["work"]["github"] == "acme/app"
    assert t["work"]["pr"] == {"number": 7, "url": "https://github.com/acme/app/pull/7", "draft": False}
    assert t["work"]["checks"] == checks and t["status"] == "doing"


def test_the_task_is_done_and_the_copy_removed_when_the_pull_request_is_merged(client, code, monkeypatch):
    tid, s, clone = _started(client, code)
    folder = Path(s["worktree"]["path"])
    _git(folder, "add", "-A")
    _git(folder, "commit", "-qm", "login fixed")
    sha = _git(folder, "rev-parse", "HEAD").strip()
    _github(monkeypatch, lambda branch, _sha: {"pr": None, "checks": None, "merged_pr": {
        "number": 7, "url": "https://github.com/acme/app/pull/7", "head_sha": sha}})
    taskflow.scan()
    t = _task(client, tid)
    assert t["status"] == "done" and t["done_at"] and t["work"]["merged"]["number"] == 7
    assert not folder.exists() and store.read(s["id"])["worktree"]["removed"]
    assert s["worktree"]["branch"] not in _git(clone, "branch")           # its commits are in the merged head
    taskflow.scan()                                                         # nothing left to read
    assert _task(client, tid)["status"] == "done"


def test_an_older_pull_request_of_the_same_branch_name_delivers_nothing(client, code, monkeypatch):
    tid, s, _ = _started(client, code)
    _github(monkeypatch, lambda branch, sha: {"pr": None, "checks": None, "merged_pr": {
        "number": 3, "url": "u", "head_sha": "a" * 40}})
    taskflow.scan()
    t = _task(client, tid)
    assert t["status"] == "doing" and t["work"]["merged"] is None and Path(s["worktree"]["path"]).is_dir()


def test_a_copy_with_work_not_saved_is_kept(client, code, monkeypatch):
    tid, s, _ = _started(client, code)
    folder = Path(s["worktree"]["path"])
    sha = _git(folder, "rev-parse", "HEAD").strip()
    (folder / "note.txt").write_text("not committed\n")
    _github(monkeypatch, lambda branch, _sha: {"pr": None, "checks": None, "merged_pr": {
        "number": 7, "url": "u", "head_sha": sha}})
    taskflow.scan()
    assert _task(client, tid)["status"] == "done" and (folder / "note.txt").exists()


def test_merging_the_copy_here_delivers_the_task(client, code):
    tid, s, _ = _started(client, code)
    r = client.post(f"/api/sessions/{s['id']}/copy/merge", json={"message": "login fixed"})
    assert r.status_code == 200, r.text
    t = _task(client, tid)
    assert t["status"] == "done" and t["work"]["merged"] == {"local": True}


def test_only_a_real_session_is_linked(client, code):
    topic, _ = code
    t = client.post("/api/tasks", json={"title": "x"}).json()
    assert client.post(f"/api/tasks/{t['id']}/session", json={"session": "nope"}).status_code == 404
    assert client.post("/api/tasks/t_none/session", json={"session": "nope"}).status_code == 404
    assert client.post(f"/api/tasks/{t['id']}/session", json={"session": "../x"}).status_code == 422


def test_a_task_linked_again_while_github_is_read_keeps_its_new_session(mx, monkeypatch):
    from maxxing.api import tasks as board
    data = board.load()
    data["tasks"].append(board._norm_task({"id": "t1", "title": "x", "status": "doing", "session": "old",
                                           "created": 1, "updated": 1}))
    board.save(data)

    def follow(t):                                   # the owner starts the task again during the round
        taskflow.link("t1", "new")
        return {"branch": "b", "github": "acme/app", "pr": None, "checks": None,
                "merged": {"number": 1, "url": "u", "sha": "s"}}, True
    monkeypatch.setattr(store, "read", lambda sid: {"id": sid})
    monkeypatch.setattr(taskflow, "_follow", follow)
    taskflow.scan()
    t = next(x for x in board.load()["tasks"] if x["id"] == "t1")
    assert t["session"] == "new" and t["status"] != "done" and not t.get("work"), t
