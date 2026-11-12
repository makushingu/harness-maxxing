"""codediff: photos before / after a turn, views, restore, commit, push - never touching the user's index or HEAD."""
import json
import subprocess
from pathlib import Path

import pytest

from maxxing import codediff, config
from maxxing.gitview import GitError

ENV = {"GIT_AUTHOR_NAME": "Ann", "GIT_AUTHOR_EMAIL": "a@example.com", "GIT_COMMITTER_NAME": "Ann",
       "GIT_COMMITTER_EMAIL": "a@example.com", "PATH": "/usr/bin:/bin"}


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**ENV, "HOME": str(repo)}).stdout


@pytest.fixture
def repo(mx):
    r = config.files_root() / "acme" / "app"
    r.mkdir(parents=True)
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "Ann")
    _git(r, "config", "user.email", "a@example.com")
    (r / "a.txt").write_text("one\ntwo\nthree\n")
    (r / "keep.txt").write_text("k\n")
    (r / ".gitignore").write_text("secret.env\n")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "start")
    return r


def _state(r):
    return _git(r, "rev-parse", "HEAD"), _git(r, "status", "--porcelain"), (r / ".git" / "index").read_bytes()


def test_a_photo_never_touches_index_head_or_files(repo):
    (repo / "a.txt").write_text("one\nTWO\nthree\n")
    (repo / "new.txt").write_text("n\n")
    _git(repo, "add", "new.txt")                         # something staged by the user
    before = _state(repo)
    sha = codediff.snapshot(repo, "refs/maxxing/t/1/pre")
    assert _state(repo) == before
    assert _git(repo, "rev-parse", "refs/maxxing/t/1/pre").strip() == sha
    files = {f["path"]: f for f in codediff.numstat(repo, "HEAD", sha)}
    assert set(files) == {"a.txt", "new.txt"}
    assert files["a.txt"]["add"] == 1 and files["a.txt"]["del"] == 1


def test_ignored_files_are_never_photographed(repo):
    (repo / "secret.env").write_text("TOKEN=x\n")
    sha = codediff.snapshot(repo)
    assert "secret.env" not in _git(repo, "ls-tree", "-r", "--name-only", sha)


def test_a_turn_shows_only_its_own_changes(repo):
    (repo / "a.txt").write_text("one\nchanged before\nthree\n")      # not this turn's work
    pre = codediff.turn_start("s1234567", 1, [str(repo)])
    (repo / "keep.txt").write_text("k\nk2\n")
    (repo / "made.txt").write_text("x\n")
    out = codediff.turn_end("s1234567", 1, pre, {str(repo / "keep.txt")}, str(repo))
    [r] = out["repos"]
    assert r["root"] == str(repo) and r["branch"] == "main" and not r["approx"]
    assert {f["path"]: f["status"] for f in r["files"]} == {"keep.txt": "M", "made.txt": "A"}
    assert r["add"] == 2


def test_a_repo_first_touched_during_the_turn_is_compared_with_head(repo, mx):
    other = config.files_root() / "acme" / "blog"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    (other / "p.md").write_text("p\n")
    _git(other, "add", ".")
    _git(other, "-c", "user.name=A", "-c", "user.email=a@x", "commit", "-qm", "p")
    pre = codediff.turn_start("s2", 1, [str(repo)])
    (other / "post.md").write_text("hello\n")
    out = codediff.turn_end("s2", 1, pre, {str(other / "post.md")}, None)
    [r] = out["repos"]                                  # the app repo did not change: not listed
    assert r["name"] == "blog" and r["approx"] and r["files"][0]["path"] == "post.md"


def test_nothing_changed_gives_nothing(repo):
    pre = codediff.turn_start("s3", 1, [str(repo)])
    assert codediff.turn_end("s3", 1, pre, set(), str(repo)) is None


def test_a_diff_gives_hunks_with_line_numbers(repo):
    (repo / "a.txt").write_text("one\nTWO\nthree\nfour\n")
    d = codediff.diff(repo, "HEAD", codediff.snapshot(repo), "a.txt")
    lines = [(l["t"], l["o"], l["n"], l["s"]) for h in d["hunks"] for l in h["lines"]]
    assert ("-", 2, None, "two") in lines and ("+", None, 2, "TWO") in lines and ("+", None, 4, "four") in lines


def test_restore_a_file_then_undo(repo):
    pre = codediff.snapshot(repo)
    (repo / "a.txt").write_text("broken\n")
    (repo / "made.txt").write_text("x\n")
    res = codediff.restore(repo, pre, ["a.txt"])
    assert (repo / "a.txt").read_text() == "one\ntwo\nthree\n" and (repo / "made.txt").exists()
    codediff.restore(repo, res["undo"])
    assert (repo / "a.txt").read_text() == "broken\n"


def test_restore_everything_removes_new_files(repo):
    pre = codediff.snapshot(repo)
    (repo / "made.txt").write_text("x\n")
    (repo / "keep.txt").write_text("other\n")
    res = codediff.restore(repo, pre)
    assert not (repo / "made.txt").exists() and (repo / "keep.txt").read_text() == "k\n"
    assert set(res["removed"]) == {"made.txt"}


def test_paths_outside_the_repo_are_refused(repo):
    with pytest.raises(GitError):
        codediff.restore(repo, "HEAD", ["../../etc/passwd"])


def test_commit_and_push_to_a_new_branch(repo, tmp_path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "switch", "-qc", "feat/x")
    (repo / "a.txt").write_text("new\n")
    out = codediff.commit(repo, "Change a")
    assert _git(repo, "log", "-1", "--format=%s").strip() == "Change a" and out["branch"] == "feat/x"
    head = codediff.push(repo)
    assert head["upstream"] == "origin/feat/x" and head["ahead"] == 0
    assert _git(bare, "rev-parse", "feat/x").strip() == out["sha"]


def test_commit_runs_the_repository_hooks(repo):
    hook = repo / ".git" / "hooks" / "commit-msg"
    hook.write_text("#!/bin/sh\ngrep -q Claude \"$1\" && { echo 'no AI credit' >&2; exit 1; }\nexit 0\n")
    hook.chmod(0o755)
    (repo / "a.txt").write_text("z\n")
    with pytest.raises(GitError) as e:
        codediff.commit(repo, "x\n\nCo-Authored-By: Claude")
    assert "no AI credit" in e.value.message


def test_views_uncommitted_and_branch(repo):
    _git(repo, "switch", "-qc", "feat/y")
    (repo / "b.txt").write_text("b\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "b")
    (repo / "c.txt").write_text("c\n")
    unc = codediff.view(repo, "uncommitted")
    assert [f["path"] for f in unc["files"]] == ["c.txt"]
    br = codediff.view(repo, "branch", base_branch="main")
    assert sorted(f["path"] for f in br["files"]) == ["b.txt", "c.txt"]
    assert [c["subject"] for c in codediff.commits(repo, "main")] == ["b"]


def test_checked_repo_refuses_a_subfolder_or_outside(repo, tmp_path):
    (repo / "sub").mkdir()
    with pytest.raises(GitError):
        codediff.checked_repo(str(repo / "sub"))
    with pytest.raises(GitError):
        codediff.checked_repo("/etc")
    assert codediff.checked_repo(str(repo)) == repo


# ---- a real turn ----------------------------------------------------------------------------------------------

from conftest import all_events, wait_idle  # noqa: E402


def test_a_turn_in_a_repository_reports_its_changes(client, topic, mx):
    config.save_config({**config.load_config(), "files_root": str(mx["tmp"])})   # the workspace is under it
    folder = Path(mx["ws"]) / topic
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "add", ".")
    _git(folder, "-c", "user.name=A", "-c", "user.email=a@x", "commit", "-qm", "start")
    s = client.post("/api/sessions", json={"path": topic, "message": "edit WRITEFILE:src/app.txt NOTOOL"}).json()
    wait_idle(client, s["id"])
    [ch] = [e for e in all_events(client, s["id"]) if e["type"] == "changes"]
    [r] = ch["repos"]
    assert r["root"] == str(folder) and r["branch"] == "main"
    assert [(f["path"], f["status"]) for f in r["files"]] == [("src/app.txt", "A")]
    # a second turn without changes adds no "changes" event
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "nothing NOTOOL"})
    wait_idle(client, s["id"])
    assert len([e for e in all_events(client, s["id"]) if e["type"] == "changes"]) == 1


def test_a_turn_outside_any_repository_reports_nothing(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "edit WRITEFILE:x.txt NOTOOL"}).json()
    wait_idle(client, s["id"])
    assert not [e for e in all_events(client, s["id"]) if e["type"] == "changes"]


# ---- API ------------------------------------------------------------------------------------------------------

from urllib.parse import parse_qs, urlparse  # noqa: E402

from _conn_helpers import _Server  # noqa: E402
from maxxing import gitview, vault  # noqa: E402


@pytest.fixture
def worked(client, topic, mx):
    """A session that changed the topic repository in two turns."""
    config.save_config({**config.load_config(), "files_root": str(mx["tmp"])})
    folder = Path(mx["ws"]) / topic
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "config", "user.name", "Ann")
    _git(folder, "config", "user.email", "a@example.com")
    _git(folder, "add", ".")
    _git(folder, "commit", "-qm", "start")
    s = client.post("/api/sessions", json={"path": topic, "message": "one WRITEFILE:a.txt NOTOOL"}).json()
    wait_idle(client, s["id"])
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "two WRITEFILE:b.txt NOTOOL"})
    wait_idle(client, s["id"])
    return s["id"], folder


def test_api_changes_of_a_turn_and_of_the_session(client, worked):
    sid, folder = worked
    last = client.get(f"/api/sessions/{sid}/changes").json()
    assert last["n"] == 2 and [f["path"] for f in last["repos"][0]["files"]] == ["b.txt"]
    first = client.get(f"/api/sessions/{sid}/changes", params={"n": 1}).json()
    assert [f["path"] for f in first["repos"][0]["files"]] == ["a.txt"]
    whole = client.get(f"/api/sessions/{sid}/changes", params={"scope": "session"}).json()
    assert sorted(f["path"] for f in whole["repos"][0]["files"]) == ["a.txt", "b.txt"]
    unc = client.get(f"/api/sessions/{sid}/changes", params={"scope": "uncommitted"}).json()
    assert sorted(f["path"] for f in unc["repos"][0]["files"]) == ["a.txt", "b.txt"]
    r = last["repos"][0]
    d = client.get("/api/code/diff", params={"repo": r["root"], "a": r["pre"], "b": r["post"], "path": "b.txt"}).json()
    assert d["hunks"][0]["lines"] == [{"t": "+", "o": None, "n": 1, "s": "changed by the fake"}]


def test_api_restore_then_undo(client, worked):
    sid, folder = worked
    r = client.get(f"/api/sessions/{sid}/changes").json()["repos"][0]
    res = client.post("/api/code/restore", json={"repo": r["root"], "source": r["pre"], "paths": ["b.txt"]}).json()
    assert not (folder / "b.txt").exists() and (folder / "a.txt").exists()
    client.post("/api/code/undo", json={"repos": [{"root": r["root"], "undo": res["undo"]}]})
    assert (folder / "b.txt").exists()


def test_api_revert_before_a_message(client, worked):
    sid, folder = worked
    out = client.post(f"/api/sessions/{sid}/revert", json={"n": 1}).json()
    assert not (folder / "a.txt").exists() and not (folder / "b.txt").exists()
    [r] = out["repos"]
    client.post("/api/code/undo", json={"repos": [{"root": r["root"], "undo": r["undo"]}]})
    assert (folder / "a.txt").exists() and (folder / "b.txt").exists()
    assert client.post(f"/api/sessions/{sid}/revert", json={"n": 9}).status_code == 404


def test_api_refuses_a_folder_that_is_not_a_repository(client, worked, mx):
    r = client.get("/api/code/diff", params={"repo": "/etc", "a": "HEAD", "b": "now", "path": "passwd"})
    assert r.status_code == 404
    r = client.get("/api/code/diff", params={"repo": str(worked[1]), "a": "--output=/tmp/x", "b": "now",
                                             "path": "a.txt"})
    assert r.status_code == 400


def _fake_github(pulls_made):
    def handler(method, path, headers, body):
        u = urlparse(path)
        q = parse_qs(u.query)
        if u.path == "/user":
            return 200, {"login": "ann"}, "application/json"
        if u.path == "/user/repos":
            return 200, [{"full_name": "acme/app", "name": "app", "owner": {"login": "acme"}, "private": True,
                          "permissions": {"push": True}, "default_branch": "main"}], "application/json"
        if u.path == "/repos/acme/app/pulls" and method == "POST":
            data = json.loads(body)
            pulls_made.append(data)
            return 201, {"number": 12, "html_url": "https://github.com/acme/app/pull/12", "title": data["title"],
                         "state": "open", "draft": False}, "application/json"
        if u.path == "/repos/acme/app/pulls":
            if pulls_made and q.get("head") == ["acme:feat/x"]:
                return 200, [{"number": 12, "html_url": "u", "title": "t", "draft": False,
                              "base": {"ref": "main"}}], "application/json"
            return 200, [], "application/json"
        if u.path.startswith("/repos/acme/app/commits/") and u.path.endswith("/check-runs"):
            return 200, {"check_runs": [{"conclusion": "success"}, {"conclusion": None}]}, "application/json"
        return 404, {"message": "Not Found"}, "application/json"
    return _Server(handler)


def test_api_commit_push_and_pull_request(client, worked, tmp_path, monkeypatch):
    sid, folder = worked
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    _git(folder, "remote", "add", "origin", "https://github.com/acme/app.git")
    _git(folder, "config", "remote.origin.pushurl", str(bare))
    _git(folder, "push", "-q", "origin", "main")
    _git(folder, "update-ref", "refs/remotes/origin/main", "main")
    assert client.post("/api/code/branch", json={"repo": str(folder), "name": "feat/x"}).json()["branch"] == "feat/x"
    out = client.post("/api/code/commit", json={"repo": str(folder), "message": "Add a and b", "push": True}).json()
    assert out["pushed"] and out["upstream"] == "origin/feat/x"
    made: list = []
    srv = _fake_github(made)
    monkeypatch.setenv("MAXXING_GITHUB_API", srv.url)
    try:
        vault.put("GITHUB_TOKEN", "ghp_" + "A" * 36)
        gitview.clear_cache()
        pr = client.post("/api/code/pr", json={"repo": str(folder)}).json()
        assert pr["number"] == 12 and made[0]["head"] == "feat/x" and made[0]["base"] == "main"
        assert made[0]["title"] == "Add a and b"
        st = client.get("/api/code/status", params={"repo": str(folder)}).json()
        assert st["pr"]["number"] == 12 and st["checks"] == {"total": 2, "ok": 1, "failed": 0, "pending": 1}
    finally:
        srv.close()


def test_api_commit_message_needs_a_change(client, worked):
    _, folder = worked
    _git(folder, "add", ".")
    _git(folder, "commit", "-qm", "all")
    r = client.post("/api/code/message", json={"repo": str(folder)})
    assert r.status_code == 400 and r.json()["error"] == "nothing"


def test_api_commit_message_is_proposed(client, worked):
    r = client.post("/api/code/message", json={"repo": str(worked[1])})
    assert r.status_code == 200 and r.json()["message"]


def test_prune_drops_photos_of_gone_sessions_and_old_ones(repo, monkeypatch):
    from maxxing import gitview
    gitview.clear_cache()
    codediff.snapshot(repo, "refs/maxxing/aaaaaaaa/1/pre")
    codediff.snapshot(repo, "refs/maxxing/bbbbbbbb/1/pre")
    assert codediff.prune(live={"aaaaaaaa"}) == 1
    refs = _git(repo, "for-each-ref", "--format=%(refname)", "refs/maxxing")
    assert "aaaaaaaa" in refs and "bbbbbbbb" not in refs
    monkeypatch.setattr(codediff.time, "time", lambda: 4_000_000_000)
    assert codediff.prune(live={"aaaaaaaa"}) == 1
