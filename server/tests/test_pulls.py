"""Pull requests in Harness: the PR view (read, comment, review, merge, close) and a session on a PR's branch."""
import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from _conn_helpers import _Server
from conftest import wait_idle
from maxxing import config, gitview, vault

ENV = {"GIT_AUTHOR_NAME": "Ann", "GIT_AUTHOR_EMAIL": "a@example.com", "GIT_COMMITTER_NAME": "Ann",
       "GIT_COMMITTER_EMAIL": "a@example.com", "PATH": "/usr/bin:/bin"}
PATCH = "@@ -1,2 +1,2 @@\n one\n-two\n+TWO\n"


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**ENV, "HOME": str(repo)}).stdout


class GH:
    def __init__(self, association="MEMBER", fork=False, merged_head=None):
        self.sent: list[tuple[str, str, dict]] = []
        self.association, self.fork, self.merged_head = association, fork, merged_head
        self.srv = _Server(self.handler)

    def handler(self, method, path, headers, body):
        u = urlparse(path)
        q = parse_qs(u.query)
        j = "application/json"
        if method != "GET":
            self.sent.append((method, u.path, json.loads(body or b"{}")))
        if u.path == "/user":
            return 200, {"login": "ann"}, j
        if u.path == "/user/repos":
            return 200, [{"full_name": "acme/app", "name": "app", "owner": {"login": "acme"}, "private": True,
                          "permissions": {"push": True}, "default_branch": "main"}], j
        if u.path == "/repos/acme/app":
            return 200, {"full_name": "acme/app", "permissions": {"push": True}, "allow_merge_commit": False,
                         "allow_squash_merge": True, "allow_rebase_merge": True}, j
        head_repo = "bob/app" if self.fork else "acme/app"
        pr = {"number": 7, "title": "Fix two", "body": "Makes two loud", "user": {"login": "bob"},
              "author_association": self.association, "state": "open", "merged": False, "draft": False,
              "mergeable": True, "mergeable_state": "clean", "html_url": "https://github.com/acme/app/pull/7",
              "head": {"ref": "fix/two", "sha": "a" * 40, "repo": {"full_name": head_repo}},
              "base": {"ref": "main"}, "commits": 1, "additions": 1, "deletions": 1,
              "requested_reviewers": [{"login": "ann"}], "updated_at": "2026-11-13T10:00:00Z"}
        if u.path == "/repos/acme/app/pulls" and method == "GET" and self.merged_head:   # merged on GitHub
            closed = {**pr, "state": "closed", "merged_at": "2026-11-13T12:00:00Z",
                      "head": {**pr["head"], "sha": self.merged_head}}
            return 200, [closed] if q.get("state") == ["closed"] else [], j
        if u.path == "/repos/acme/app/pulls" and method == "GET":
            return 200, [pr], j
        if u.path == "/repos/acme/app/pulls/7" and method == "GET":
            return 200, pr, j
        if u.path == "/repos/acme/app/pulls/7" and method == "PATCH":
            return 200, {**pr, "state": "closed"}, j
        if u.path == "/repos/acme/app/pulls/7/files":
            return 200, [{"filename": "a.txt", "status": "modified", "additions": 1, "deletions": 1,
                          "patch": PATCH}], j
        if u.path == "/repos/acme/app/issues/7/comments" and method == "GET":
            return 200, [{"id": 1, "user": {"login": "bob"}, "body": "ready", "created_at": "2026-11-13T10:00:00Z"}], j
        if u.path == "/repos/acme/app/issues/7/comments":
            return 201, {"id": 2, "html_url": "c"}, j
        if u.path == "/repos/acme/app/pulls/7/reviews" and method == "GET":
            return 200, [{"id": 3, "user": {"login": "carl"}, "state": "APPROVED", "body": "",
                          "submitted_at": "2026-11-13T11:00:00Z"},
                         {"id": 4, "user": {"login": "carl"}, "state": "COMMENTED", "body": "",
                          "submitted_at": "2026-11-13T11:00:00Z"}], j
        if u.path == "/repos/acme/app/pulls/7/reviews":
            return 200, {"id": 5, "state": "APPROVED"}, j
        if u.path == "/repos/acme/app/pulls/7/comments":
            return 200, [{"id": 6, "path": "a.txt", "line": 2, "side": "RIGHT", "user": {"login": "carl"},
                          "body": "nice", "created_at": "2026-11-13T11:00:00Z"}], j
        if u.path == "/repos/acme/app/pulls/7/merge":
            return 200, {"merged": True, "sha": "b" * 40, "message": "Pull Request successfully merged"}, j
        if u.path.endswith("/check-runs"):
            return 200, {"check_runs": [{"name": "tests", "status": "completed", "conclusion": "failure"}]}, j
        if u.path.endswith("/status"):
            return 200, {"statuses": []}, j
        return 404, {"message": "Not Found"}, j


@pytest.fixture
def gh(monkeypatch, mx):
    made = []

    def make(**kw):
        g = GH(**kw)
        made.append(g)
        monkeypatch.setenv("MAXXING_GITHUB_API", g.srv.url)
        vault.put("GITHUB_TOKEN", "ghp_" + "A" * 36)
        gitview.clear_cache()
        return g
    yield make
    for g in made:
        g.srv.close()


def test_the_pr_view_reads_everything(client, gh):
    gh()
    lst = client.get("/api/git/pulls", params={"repo": "github:acme/app"}).json()
    assert lst[0]["number"] == 7 and lst[0]["review_me"] and not lst[0]["outside"]
    p = client.get("/api/git/pull", params={"repo": "github:acme/app", "number": 7}).json()
    assert p["title"] == "Fix two" and p["methods"] == ["squash", "rebase"] and p["can_write"]
    [f] = p["files"]
    assert f["path"] == "a.txt" and [ln["t"] for ln in f["hunks"][0]["lines"]] == [" ", "-", "+"]
    assert [c["kind"] for c in p["conversation"]] == ["comment", "review"]       # empty envelope left out
    assert p["line_comments"][0]["line"] == 2
    assert p["checks"] == [{"name": "tests", "status": "completed", "conclusion": "failure", "url": None}]


def test_comment_review_merge_close(client, gh):
    g = gh()
    base = {"repo": "github:acme/app", "number": 7}
    assert client.post("/api/git/pull/comment", json={**base, "body": "thanks"}).status_code == 200
    r = client.post("/api/git/pull/review", json={**base, "event": "APPROVE", "body": "",
                                                    "comments": [{"path": "a.txt", "line": 2, "body": "ok"}]})
    assert r.status_code == 200
    assert client.post("/api/git/pull/review", json={**base, "event": "COMMENT"}).status_code == 400
    assert client.post("/api/git/pull/merge", json={**base, "method": "squash"}).json()["merged"]
    assert client.post("/api/git/pull/close", json=base).json()["state"] == "closed"
    sent = [(m, p) for m, p, _ in g.sent]
    assert sent == [("POST", "/repos/acme/app/issues/7/comments"), ("POST", "/repos/acme/app/pulls/7/reviews"),
                    ("PUT", "/repos/acme/app/pulls/7/merge"), ("PATCH", "/repos/acme/app/pulls/7")]
    assert g.sent[1][2]["comments"] == [{"path": "a.txt", "line": 2, "side": "RIGHT", "body": "ok"}]
    assert g.sent[2][2] == {"merge_method": "squash"}


@pytest.fixture
def clone(client, topic, mx, tmp_path):
    """A clone of acme/app in the topic whose origin (a bare repository) has the PR's branch and refs/pull/7/head."""
    config.save_config({**config.load_config(), "files_root": str(mx["tmp"]), "code_mode": True})
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-q", "-b", "main")
    (seed / "a.txt").write_text("one\ntwo\n")
    _git(seed, "add", ".")
    _git(seed, "commit", "-qm", "start")
    _git(seed, "push", "-q", str(bare), "main")
    _git(seed, "switch", "-qc", "fix/two")
    (seed / "a.txt").write_text("one\nTWO\n")
    _git(seed, "commit", "-qam", "loud")
    _git(seed, "push", "-q", str(bare), "fix/two", "fix/two:refs/pull/7/head")
    c = Path(mx["ws"]) / topic / "app"
    subprocess.run(["git", "clone", "-q", str(bare), str(c)], check=True, env={**ENV, "HOME": str(tmp_path)})
    _git(c, "remote", "set-url", "origin", "https://github.com/acme/app.git")
    _git(c, "config", "remote.origin.url", str(bare))            # fetches go to the bare repository...
    _git(c, "config", "url." + str(bare) + ".insteadOf", "https://github.com/acme/app.git")
    _git(c, "remote", "set-url", "origin", "https://github.com/acme/app.git")   # ...while it looks like GitHub
    return topic, c


def test_work_on_a_pull_request_of_the_same_repository(client, gh, clone):
    topic, c = clone
    gh()
    r = client.post("/api/code/pr-session", json={"repo": "github:acme/app", "number": 7, "message": "go NOTOOL"})
    assert r.status_code == 200, r.text
    s = r.json()
    wt = s["worktree"]
    assert wt["branch"] == "fix/two" and wt["pr"]["number"] == 7 and not s["plan_mode"]
    assert Path(wt["path"], "a.txt").read_text() == "one\nTWO\n"
    assert s["path"] == topic
    wait_idle(client, s["id"])
    st = client.get(f"/api/sessions/{s['id']}/copy").json()
    assert st["upstream"] == "origin/fix/two" and not st["fork"]


def test_a_strangers_fork_opens_in_plan_mode_on_pr_n(client, gh, clone):
    topic, c = clone
    gh(association="NONE", fork=True)
    s = client.post("/api/code/pr-session", json={"repo": "github:acme/app", "number": 7}).json()
    assert s["plan_mode"] and s["worktree"]["branch"] == "pr/7"
    assert Path(s["worktree"]["path"], "a.txt").read_text() == "one\nTWO\n"
    assert client.get(f"/api/sessions/{s['id']}/copy").json()["fork"]


def test_a_pr_session_needs_a_clone_in_a_topic(client, gh, topic, mx):
    config.save_config({**config.load_config(), "code_mode": True})
    gh()
    r = client.post("/api/code/pr-session", json={"repo": "github:acme/app", "number": 7})
    assert r.status_code == 400 and r.json()["error"] == "no_clone"


def test_a_copy_whose_pr_was_merged_on_github_is_put_away_with_its_branch(client, gh, clone):
    topic, c = clone
    g = gh()
    s = client.post("/api/code/pr-session", json={"repo": "github:acme/app", "number": 7, "message": "go NOTOOL"}).json()
    wait_idle(client, s["id"])
    r = client.post(f"/api/sessions/{s['id']}/copy/remove", json={"merged_pr": True})
    assert r.status_code == 409 and "merged" in r.text                  # still open: nothing happens
    assert Path(s["worktree"]["path"]).is_dir()
    g.merged_head = _git(c, "rev-parse", "fix/two").strip()               # squash-merged on GitHub
    gitview.clear_cache()
    st = client.get("/api/code/status", params={"repo": s["worktree"]["path"]}).json()
    assert st["pr"] is None and st["merged_pr"]["number"] == 7, st
    r = client.post(f"/api/sessions/{s['id']}/copy/remove", json={"merged_pr": True})
    assert r.status_code == 200, r.text
    assert r.json()["kept_branch"] is None and not Path(s["worktree"]["path"]).exists()
    assert "fix/two" not in _git(c, "branch", "--list")


def test_a_pr_gets_the_repository_template(tmp_path):
    from maxxing.api.code import _pr_text
    assert _pr_text(tmp_path, ["one", "two"]) == "- two\n- one"
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "pull_request_template.md").write_text("## Why\n\n## Tests\n")
    assert _pr_text(tmp_path, ["one"]) == "- one\n\n## Why\n\n## Tests"
