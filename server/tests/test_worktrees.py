"""Separate copies (worktrees.py): a session on its own folder and branch, its end (merge, discard), Code mode only."""
import subprocess
import time
from pathlib import Path

import pytest

from conftest import wait_for, wait_idle
from maxxing import config, worktrees
from maxxing.sessions import store

ENV = {"GIT_AUTHOR_NAME": "Ann", "GIT_AUTHOR_EMAIL": "a@example.com", "GIT_COMMITTER_NAME": "Ann",
       "GIT_COMMITTER_EMAIL": "a@example.com", "PATH": "/usr/bin:/bin"}


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**ENV, "HOME": str(repo)}).stdout


def _init(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "config", "user.name", "Ann")
    _git(folder, "config", "user.email", "a@example.com")
    (folder / "a.txt").write_text("one\n")
    (folder / ".gitignore").write_text(".env\nnode_modules/\n")
    _git(folder, "add", ".")
    _git(folder, "commit", "-qm", "start")
    return folder


@pytest.fixture
def code(client, topic, mx):
    """Code mode on, the workspace inside the files root, a clone `app` in the topic."""
    config.save_config({**config.load_config(), "files_root": str(mx["tmp"]), "code_mode": True})
    clone = _init(Path(mx["ws"]) / topic / "app")
    return topic, clone


def _new(client, topic, clone, message="fix the login page WRITEFILE:x.txt NOTOOL", **extra):
    r = client.post("/api/sessions", json={"path": topic, "message": message,
                                           "worktree": {"repo": str(clone), **extra}})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_topic_lists_its_repositories(client, code):
    topic, clone = code
    r = client.get("/api/code/copy-repos", params={"path": topic}).json()
    assert r["enabled"] and [x["root"] for x in r["repos"]] == [str(clone)]
    assert r["repos"][0]["default_base"] == "main" and r["repos"][0]["prefs"]["prefix"] == "session"


def test_without_code_mode_there_is_no_copy(client, code):
    topic, clone = code
    config.save_config({**config.load_config(), "code_mode": False})
    assert client.get("/api/code/copy-repos", params={"path": topic}).json() == {"enabled": False, "repos": []}
    r = client.post("/api/sessions", json={"path": topic, "message": "hi", "worktree": {"repo": str(clone)}})
    assert r.status_code == 403


def test_a_session_works_in_its_own_copy_and_branch(client, code, mx):
    topic, clone = code
    s = _new(client, topic, clone)
    wt = s["worktree"]
    folder = Path(wt["path"])
    assert folder.parent == Path(mx["ws"]) / topic / "worktrees"         # visible, beside the clone
    assert wt["branch"].startswith("session/") and wt["base"] == "main"
    wait_idle(client, s["id"])
    assert (folder / "x.txt").is_file() and not (clone / "x.txt").exists()   # the turn ran in the copy
    assert _git(clone, "status", "--porcelain") == ""                     # the clone never sees it
    st = client.get(f"/api/sessions/{s['id']}/copy").json()
    assert st["exists"] and st["dirty"] == 1 and st["ahead"] == 0


def test_the_branch_follows_the_title_until_it_is_pushed(client, code):
    topic, clone = code
    s = _new(client, topic, clone)
    wait_idle(client, s["id"])
    r = client.patch(f"/api/sessions/{s['id']}", json={"title": "Login fix"})
    assert r.json()["worktree"]["branch"] == "session/login-fix"
    assert "session/login-fix" in _git(clone, "branch", "--list")


def test_a_copy_inside_the_repository_is_hidden_and_excluded(client, topic, mx):
    config.save_config({**config.load_config(), "files_root": str(mx["tmp"]), "code_mode": True})
    folder = _init(Path(mx["ws"]) / topic)                                 # the topic IS the repository
    s = _new(client, topic, folder)
    assert Path(s["worktree"]["path"]).parent == folder / ".worktrees"
    wait_idle(client, s["id"])
    assert _git(folder, "status", "--porcelain") == ""
    assert "/.worktrees/" in (folder / ".git" / "info" / "exclude").read_text()


def test_merge_into_the_base_then_the_copy_goes(client, code):
    topic, clone = code
    s = _new(client, topic, clone)
    wait_idle(client, s["id"])
    r = client.post(f"/api/sessions/{s['id']}/copy/merge", json={})
    assert r.status_code == 409 and r.json()["error"] == "uncommitted"
    r = client.post(f"/api/sessions/{s['id']}/copy/merge", json={"message": "Add x"})
    assert r.status_code == 200, r.text
    assert r.json()["merged"] and not Path(s["worktree"]["path"]).exists()
    assert (clone / "x.txt").is_file()                                    # main moved forward, checked out
    assert _git(clone, "log", "-1", "--format=%s").strip() == "Add x"
    assert "session/" not in _git(clone, "branch", "--list")              # merged: the branch went too
    sess = client.get(f"/api/sessions/{s['id']}").json()
    assert sess["worktree"]["removed"]
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "again WRITEFILE:y.txt NOTOOL"})
    wait_idle(client, s["id"])
    assert not (clone / "y.txt").exists()                                  # back in the topic folder


def test_merge_from_origin_main_drops_the_branch_too(client, code, tmp_path):
    topic, clone = code
    bare = tmp_path / "o.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    _git(clone, "remote", "add", "origin", str(bare))
    _git(clone, "push", "-q", "-u", "origin", "main")
    _git(clone, "remote", "set-head", "origin", "main")
    s = _new(client, topic, clone)
    assert s["worktree"]["base"] == "main"
    wait_idle(client, s["id"])
    r = client.post(f"/api/sessions/{s['id']}/copy/merge", json={"message": "Add x"})
    assert r.status_code == 200 and r.json()["kept_branch"] is None, r.text


def test_a_conflict_with_the_base_leaves_the_copy_as_it_was(client, code):
    topic, clone = code
    s = _new(client, topic, clone, message="hi NOTOOL")
    wait_idle(client, s["id"])
    folder = Path(s["worktree"]["path"])
    (folder / "a.txt").write_text("copy\n")
    _git(folder, "commit", "-qam", "copy")
    (clone / "a.txt").write_text("main\n")
    _git(clone, "commit", "-qam", "main")
    r = client.post(f"/api/sessions/{s['id']}/copy/merge", json={})
    assert r.status_code == 409 and r.json()["error"] == "conflict"
    assert (folder / "a.txt").read_text() == "copy\n" and _git(folder, "status", "--porcelain") == ""


def test_discard_removes_folder_and_branch(client, code):
    topic, clone = code
    s = _new(client, topic, clone)
    wait_idle(client, s["id"])
    assert client.post(f"/api/sessions/{s['id']}/copy/remove", json={}).status_code == 409   # not committed
    r = client.post(f"/api/sessions/{s['id']}/copy/remove", json={"force": True})
    assert r.status_code == 200 and r.json()["kept_branch"] is None
    assert not Path(s["worktree"]["path"]).exists() and "session/" not in _git(clone, "branch", "--list")


def test_a_session_on_a_copy_cannot_move_topic(client, code):
    topic, clone = code
    client.post("/api/workspace/projects/acme/topics", json={"name": "other"})
    s = _new(client, topic, clone, message="hi NOTOOL")
    wait_idle(client, s["id"])
    r = client.patch(f"/api/sessions/{s['id']}", json={"path": "projects/acme/topics/other"})
    assert r.status_code == 409


def test_preparation_and_env_files(client, code):
    topic, clone = code
    (clone / ".env").write_text("A=1\n")
    s = _new(client, topic, clone, message="hi NOTOOL", prepare="echo ready > prepared.txt", copy_env=True,
             remember=True)
    folder = Path(s["worktree"]["path"])
    assert (folder / ".env").read_text() == "A=1\n"
    wait_for(lambda: (store.read(s["id"])["worktree"].get("prepare") or {}).get("state") == "done")
    assert (folder / "prepared.txt").read_text().strip() == "ready"
    assert worktrees.prefs(clone)["prepare"] == "echo ready > prepared.txt"
    log = client.get(f"/api/sessions/{s['id']}/copy/prepare-log").json()["log"]
    assert "$ echo ready" in log and "[exit 0]" in log


def test_the_git_page_lists_the_copies(client, code):
    topic, clone = code
    s = _new(client, topic, clone, message="hi NOTOOL")
    wait_idle(client, s["id"])
    [c] = client.get("/api/code/copies").json()
    assert c["sid"] == s["id"] and c["exists"] and c["repo"] == str(clone)


def test_slugs():
    assert worktrees.slug("Fix the login page!") == "fix-the-login-page"
    assert worktrees.slug("Éditer l'accueil") == "editer-l-accueil"
    assert len(worktrees.slug("word " * 30)) <= worktrees.SLUG_MAX
    assert worktrees.slug("…") == ""


def test_claude_is_told_to_work_in_the_copy(client, code, mx):
    import json, os
    topic, clone = code
    s = _new(client, topic, clone, message="hi NOTOOL")
    wait_idle(client, s["id"])
    calls = [json.loads(x) for x in open(os.path.join(os.environ["FAKE_CLAUDE_DIR"], "calls.jsonl"))]
    call = [c for c in calls if c["cwd"] == s["worktree"]["path"]][-1]
    note = call["argv"][call["argv"].index("--append-system-prompt") + 1]
    assert "separate copy" in note and s["worktree"]["branch"] in note and str(clone) in note


def test_a_deleted_session_takes_its_copy_only_when_nothing_is_lost(client, code):
    topic, clone = code
    clean = _new(client, topic, clone, message="hi NOTOOL")
    worked = _new(client, topic, clone, message="other WRITEFILE:y.txt NOTOOL")
    wait_idle(client, clean["id"])
    wait_idle(client, worked["id"])
    assert client.delete(f"/api/sessions/{clean['id']}").status_code in (200, 204)
    assert client.delete(f"/api/sessions/{worked['id']}").status_code in (200, 204)
    assert not Path(clean["worktree"]["path"]).exists()
    assert Path(worked["worktree"]["path"], "y.txt").is_file()                # a file left: the copy stays


def test_worktreeinclude_files_and_a_block_of_ports(client, code):
    import json, os
    topic, clone = code
    (clone / ".gitignore").write_text(".env\nnode_modules/\n*.local\n")
    (clone / ".worktreeinclude").write_text("*.local\na.txt\n")
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "include")
    (clone / "conf").mkdir()
    (clone / "conf" / "db.local").write_text("secret=1\n")
    (clone / "node_modules").mkdir()
    (clone / "node_modules" / "x.local").write_text("big\n")      # named, ignored: copied as well
    (clone / "notes.txt").write_text("untracked, not ignored\n")
    one = _new(client, topic, clone, message="hi NOTOOL")
    two = _new(client, topic, clone, message="hi NOTOOL")
    folder = Path(one["worktree"]["path"])
    assert (folder / "conf" / "db.local").read_text() == "secret=1\n"
    assert not (folder / "notes.txt").exists()                        # not ignored by git: never copied
    assert (folder / "a.txt").read_text() == "one\n"                  # tracked: the copy has it already
    st = client.get(f"/api/sessions/{one['id']}/copy").json()
    assert st["included"] == 2
    p1, p2 = st["port"], client.get(f"/api/sessions/{two['id']}/copy").json()["port"]
    assert p1 >= worktrees.PORT_START and abs(p1 - p2) >= worktrees.PORT_BLOCK
    wait_idle(client, one["id"])
    calls = [json.loads(x) for x in open(os.path.join(os.environ["FAKE_CLAUDE_DIR"], "calls.jsonl"))]
    call = [c for c in calls if c["cwd"] == str(folder)][-1]
    assert call["env"]["MAXXING_PORT"] == str(p1)
    note = call["argv"][call["argv"].index("--append-system-prompt") + 1]
    assert f"ports {p1} to {p1 + 9}" in note


def test_the_preparation_knows_its_ports(client, code):
    topic, clone = code
    s = _new(client, topic, clone, message="hi NOTOOL", prepare='echo "$MAXXING_PORT $MAXXING_COPY_PATH" > p.txt')
    folder = Path(s["worktree"]["path"])
    wait_for(lambda: (store.read(s["id"])["worktree"].get("prepare") or {}).get("state") == "done")
    port = store.read(s["id"])["worktree"]["port"]
    assert (folder / "p.txt").read_text().split() == [str(port), str(folder)]


def _with_pull(clone: Path, tmp: Path, n: int = 7) -> None:
    """An origin for `clone` with the head of pull request `n` (refs/pull/<n>/head, branch `theirs`), like GitHub's."""
    origin = tmp / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(clone), str(origin)], check=True, env={**ENV, "HOME": str(tmp)})
    _git(clone, "remote", "add", "origin", str(origin))
    _git(clone, "checkout", "-qb", "theirs")
    (clone / "package.json").write_text('{"scripts": {"postinstall": "touch pwned"}}\n')
    _git(clone, "add", ".")
    _git(clone, "commit", "-qm", "theirs")
    _git(clone, "push", "-q", "origin", f"theirs:refs/pull/{n}/head", "theirs:refs/heads/theirs")
    _git(clone, "checkout", "-q", "main")
    _git(clone, "branch", "-qD", "theirs")


@pytest.mark.parametrize("who", [{"fork": True}, {"outside": True, "ref": "theirs"}])
def test_a_strangers_pull_request_runs_nothing_before_it_is_read(client, code, mx, who):
    # the repository's prepare command (`npm ci` runs the PR's scripts) and the clone's .env stay out of it
    from maxxing.sessions import service
    topic, clone = code
    _with_pull(clone, Path(mx["tmp"]))
    (clone / ".env").write_text("SECRET=1\n")
    s = service.create_session(topic, title="PR #7", worktree={
        "repo": str(clone), "pr": {"number": 7, "base": "main", **who},
        "prepare": "echo ran > ran.txt", "copy_env": True})
    wt = store.read(s["id"])["worktree"]
    folder = Path(wt["path"])
    assert (folder / "package.json").exists()                  # the PR's code is there, to be read
    assert not (folder / ".env").exists() and "env_copied" not in wt
    assert "prepare" not in wt
    time.sleep(0.3)
    assert not (folder / "ran.txt").exists()
    assert store.read(s["id"])["plan_mode"] if who.get("outside") else True


def test_a_copy_that_fails_halfway_leaves_no_folder_nor_branch(client, code, monkeypatch):
    from maxxing.sessions import service
    topic, clone = code
    (clone / ".env").write_text("A=1\n")

    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(worktrees, "_copy_env", broken)
    with pytest.raises(OSError):
        service.create_session(topic, title="half", worktree={"repo": str(clone), "copy_env": True})
    assert "session/" not in _git(clone, "branch", "--list")
    assert len(_git(clone, "worktree", "list").splitlines()) == 1
    assert not any((Path(clone).parent / "worktrees").glob("half*"))


def test_discarding_a_copy_never_deletes_the_branch_it_was_switched_to(client, code):
    topic, clone = code
    s = _new(client, topic, clone)
    wait_idle(client, s["id"])
    folder, branch = Path(s["worktree"]["path"]), s["worktree"]["branch"]
    _git(clone, "branch", "precious")
    _git(folder, "switch", "-q", "--discard-changes", "precious")
    (folder / "p.txt").write_text("mine\n")
    _git(folder, "add", "p.txt")
    _git(folder, "commit", "-qm", "precious work")
    r = client.post(f"/api/sessions/{s['id']}/copy/remove", json={"force": True})
    assert r.status_code == 200, r.text
    branches = _git(clone, "branch", "--list")
    assert "precious" in branches and branch not in branches
    assert r.json()["kept_branch"] == "precious"


@pytest.mark.parametrize("prefix", ["a.lock", "x/.hid", "x/y.", "main", "main/x"])
def test_a_prefix_git_would_refuse_is_refused(client, code, prefix):
    topic, clone = code
    r = client.put("/api/code/copy-prefs", json={"repo": str(clone), "prefix": prefix})
    assert r.status_code == 400 and r.json()["error"] == "bad_prefix", r.text
    assert client.put("/api/code/copy-prefs", json={"repo": str(clone), "prefix": "feat/x"}).status_code == 200
