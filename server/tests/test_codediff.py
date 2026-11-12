"""codediff: photos before / after a turn, views, restore, commit, push - never touching the user's index or HEAD."""
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
