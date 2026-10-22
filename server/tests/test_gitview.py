import time
import subprocess
from urllib.parse import parse_qs, urlparse

import pytest

from _conn_helpers import _Server
from _org_helpers import client, org  # noqa: F401
from maxxing import config, gitview, vault


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "Ann", "GIT_AUTHOR_EMAIL": "a@example.com", "GIT_COMMITTER_NAME": "Ann",
                        "GIT_COMMITTER_EMAIL": "a@example.com", "HOME": str(repo), "PATH": "/usr/bin:/bin"})


@pytest.fixture
def repo(org):
    """files_root/sites/acme: main (3 commits) + feature branch merged back, a tag, one unpushed change."""
    gitview.clear_cache()
    root = config.files_root()
    r = root / "sites" / "acme"
    r.mkdir(parents=True)
    _git(r, "init", "-q", "-b", "main")
    _git(r, "remote", "add", "origin", "https://user:secret@github.com/acme/site.git")
    for i in range(2):
        (r / f"f{i}.txt").write_text(str(i))
        _git(r, "add", ".")
        _git(r, "commit", "-qm", f"commit {i}")
    _git(r, "tag", "v1")
    _git(r, "checkout", "-qb", "feat/login")
    (r / "login.txt").write_text("x")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "add login")
    _git(r, "checkout", "-q", "main")
    _git(r, "merge", "-q", "--no-ff", "feat/login", "-m", "merge login")
    (r / "f0.txt").write_text("changed")
    (r / "new.txt").write_text("u")
    (root / "node_modules" / "dep").mkdir(parents=True)          # pruned
    _git(root / "node_modules" / "dep", "init", "-q")
    return r


def test_local_overview_graph_commit(client, org, repo):
    ov = client.get("/api/git/repos").json()
    assert ov["github"]["connected"] is False
    assert [r["path"] for r in ov["local"]] == [str(repo)]
    s = ov["local"][0]
    assert s["branch"] == "main" and s["changed"] == 1 and s["untracked"] == 1
    assert s["github"] == "acme/site" and "secret" not in s["remote"]

    g = client.get("/api/git/graph", params={"repo": str(repo)}).json()
    subj = [c["subject"] for c in g["commits"]]
    assert subj[0] == "merge login" and len(g["commits"]) == 4 and not g["truncated"]
    top = g["commits"][0]
    assert {"name": "main", "kind": "branch", "current": True} in top["refs"] and len(top["parents"]) == 2
    assert any(r == {"name": "v1", "kind": "tag"} for c in g["commits"] for r in c["refs"])
    assert any(r["name"] == "feat/login" for c in g["commits"] for r in c["refs"])
    assert g["repo"]["kind"] == "local"

    g2 = client.get("/api/git/graph", params={"repo": str(repo / "sites"), "limit": 2}).json()   # missing subfolder
    assert g2.get("error") == "not_found" or g2.get("truncated") is True
    g3 = client.get("/api/git/graph", params={"repo": str(repo), "branches": "feat/login"}).json()
    assert [c["subject"] for c in g3["commits"]][0] == "add login"
    assert client.get("/api/git/graph", params={"repo": str(repo), "branches": "nope"}).json()["error"] == "no_branch"

    c = client.get("/api/git/commit", params={"repo": str(repo), "sha": g3["commits"][0]["sha"]}).json()
    assert c["message"] == "add login" and c["files"] == [{"path": "login.txt", "additions": 1, "deletions": 0}]
    merge = client.get("/api/git/commit", params={"repo": str(repo), "sha": top["sha"]}).json()
    assert [f["path"] for f in merge["files"]] == ["login.txt"]          # merge: diff against the first parent
    assert client.get("/api/git/commit", params={"repo": str(repo), "sha": "--all"}).json()["error"] == "bad_sha"


def test_paths_are_confined(client, org, repo, tmp_path_factory):
    (repo / "src").mkdir()
    assert client.get("/api/git/graph", params={"repo": str(repo / "src")}).json()["repo"]["path"] == str(repo)
    other = tmp_path_factory.mktemp("elsewhere")
    _git(other, "init", "-q")
    r = client.get("/api/git/graph", params={"repo": str(other)})
    assert r.status_code == 403 and r.json()["error"] == "outside_root"
    r = client.get("/api/git/graph", params={"repo": str(config.files_root())})
    assert r.status_code == 404 and r.json()["error"] == "not_a_repo"


BOB = "github_pat_" + "B" * 30                      # a fine-grained token of a second account


def _fake_github():
    commits = {
        "main": [{"sha": "c3" * 20, "parents": [{"sha": "c2" * 20}, {"sha": "b1" * 20}],
                  "commit": {"message": "Merge feat", "author": {"name": "Ann", "date": "2026-10-03T10:00:00Z"},
                             "committer": {"date": "2026-10-03T10:00:00Z"}}},
                 {"sha": "b1" * 20, "parents": [{"sha": "c1" * 20}],
                  "commit": {"message": "feat work", "author": {"name": "Bob", "date": "2026-10-02T10:00:00Z"},
                             "committer": {"date": "2026-10-02T10:00:00Z"}}},
                 {"sha": "c2" * 20, "parents": [{"sha": "c1" * 20}],
                  "commit": {"message": "fix", "author": {"name": "Ann", "date": "2026-10-02T12:00:00Z"},
                             "committer": {"date": "2026-10-02T12:00:00Z"}}},
                 {"sha": "c1" * 20, "parents": [],
                  "commit": {"message": "init", "author": {"name": "Ann", "date": "2026-10-01T10:00:00Z"},
                             "committer": {"date": "2026-10-01T10:00:00Z"}}}],
        "dev": [{"sha": "d1" * 20, "parents": [{"sha": "c3" * 20}],
                 "commit": {"message": "wip", "author": {"name": "Ann", "date": "2026-10-04T10:00:00Z"},
                            "committer": {"date": "2026-10-04T10:00:00Z"}}}],
    }
    site = {"full_name": "acme/site", "name": "site", "owner": {"login": "acme"}, "private": True,
            "default_branch": "main", "pushed_at": "2026-10-04T10:00:00Z"}
    users = {
        "Bearer ghp_test": ("ann", [{**site, "permissions": {"push": True, "pull": True}},
                                    {"full_name": "other/lib", "name": "lib", "owner": {"login": "other"},
                                     "private": False, "permissions": {"pull": True}}]),
        f"Bearer {BOB}": ("bob", [{**site, "permissions": {"admin": True}},
                                  {"full_name": "bob/tool", "name": "tool", "owner": {"login": "bob"}, "private": True,
                                   "permissions": {"admin": True}, "default_branch": "main"}]),
    }
    seen = []

    def handler(method, path, headers, body):
        u = urlparse(path)
        q = parse_qs(u.query)
        auth = headers.get("Authorization")
        seen.append((u.path, auth))
        if auth not in users:
            return 401, {"message": "Bad credentials"}, "application/json"
        login, repos = users[auth]
        visible = {r["full_name"] for r in repos}
        if u.path == "/user":
            return 200, {"login": login, "name": login.title()}, "application/json"
        if u.path == "/user/repos":
            return 200, repos, "application/json"
        full = "/".join(u.path.split("/")[2:4]) if u.path.startswith("/repos/") else ""
        if full and full not in visible:
            return 404, {"message": "Not Found"}, "application/json"
        if u.path == "/repos/bob/tool":
            return 200, {"name": "tool", "default_branch": "main", "private": True,
                         "permissions": {"admin": True}}, "application/json"
        if u.path == "/repos/bob/tool/branches":
            return 200, [{"name": "main", "commit": {"sha": "e1" * 20}}], "application/json"
        if u.path == "/repos/bob/tool/commits":
            return 200, [{"sha": "e1" * 20, "parents": [], "commit": {"message": "tool init", "author": {
                "name": "Bob", "date": "2026-10-01T10:00:00Z"}, "committer": {"date": "2026-10-01T10:00:00Z"}}}], \
                "application/json"
        if u.path == "/repos/acme/site":
            return 200, {"name": "site", "default_branch": "main", "private": True,
                         "permissions": {"push": True}}, "application/json"
        if u.path == "/repos/acme/site/branches":
            return 200, [{"name": "main", "commit": {"sha": "c3" * 20}},
                         {"name": "dev", "commit": {"sha": "d1" * 20}}], "application/json"
        if u.path == "/repos/acme/site/commits":
            return 200, commits[q["sha"][0]], "application/json"
        if u.path == f"/repos/acme/site/commits/{'b1' * 20}":
            return 200, {**commits["main"][1], "files": [{"filename": "a.py", "additions": 3, "deletions": 1}]}, \
                "application/json"
        if u.path == "/repos/acme/site/pulls":
            return 200, [{"number": 7, "title": "Dev", "user": {"login": "ann"}, "head": {"ref": "dev"},
                          "base": {"ref": "main"}, "draft": False}], "application/json"
        return 404, {"message": "Not Found"}, "application/json"
    return _Server(handler), seen


def test_github(client, org, repo, monkeypatch):
    srv, seen = _fake_github()
    monkeypatch.setenv("MAXXING_GITHUB_API", srv.url)
    try:
        vault.put("GITHUB_TOKEN", "ghp_test")
        vault.put("MY_OTHER_PAT", BOB)                   # any name: recognised by its value
        vault.put("BLOG_PAT_COPY", BOB)                  # same value twice: used once
        vault.put("STRIPE_KEY", "sk_live_notgithub")     # not a GitHub token: ignored
        vault.put("OLD_GH_PAT", "ghp_" + "Z" * 36)       # refused by GitHub: reported, the rest still shows
        gitview.clear_cache()
        assert [k for k, _ in gitview.tokens()] == ["GITHUB_TOKEN", "BLOG_PAT_COPY", "OLD_GH_PAT"]
        gh = client.get("/api/git/repos").json()["github"]
        assert gh["connected"] and gh["error"] is None
        assert {a["login"]: a["keys"] for a in gh["accounts"]} == {"ann": ["GITHUB_TOKEN"], "bob": ["BLOG_PAT_COPY"]}
        assert gh["errors"] == [{"key": "OLD_GH_PAT", "error": "GitHub refused the token (expired or revoked?)"}]
        by = {r["full_name"]: r for r in gh["repos"]}
        assert set(by) == {"acme/site", "other/lib", "bob/tool"}
        site = by["acme/site"]
        assert site["permission"] == "admin" and set(site["keys"]) == {"GITHUB_TOKEN", "BLOG_PAT_COPY"}
        assert site["local_paths"] == [str(repo)] and by["other/lib"]["permission"] == "pull"
        assert "ghp_test" not in str(gh) and BOB not in str(gh)          # values never sent to the UI

        g = client.get("/api/git/graph", params={"repo": "github:acme/site"}).json()
        order = [c["subject"] for c in g["commits"]]
        assert order[0] == "wip" and order[-1] == "init" and set(order) == {"wip", "Merge feat", "fix", "feat work", "init"}
        assert order.index("Merge feat") < order.index("feat work")      # children before parents
        assert {"name": "dev", "kind": "branch"} in g["commits"][0]["refs"]
        assert g["repo"]["kind"] == "github" and g["repo"]["branches"] == 2

        tool = client.get("/api/git/graph", params={"repo": "github:bob/tool"}).json()   # only bob's token sees it
        assert [c["subject"] for c in tool["commits"]] == ["tool init"]
        assert all(a == f"Bearer {BOB}" for p, a in seen if p.startswith("/repos/bob/tool"))

        c = client.get("/api/git/commit", params={"repo": "github:acme/site", "sha": "b1" * 20}).json()
        assert c["files"] == [{"path": "a.py", "additions": 3, "deletions": 1}] and c["message"] == "feat work"
        assert client.get("/api/git/pulls", params={"repo": "github:acme/site"}).json()[0]["number"] == 7
        assert client.get("/api/git/graph", params={"repo": "github:../x"}).json()["error"] == "bad_repo"
        assert client.get("/api/git/graph", params={"repo": "github:nobody/none"}).json()["error"] == "not_found"
    finally:
        srv.close()


def test_git_page_setting(client, org):
    assert client.get("/api/settings").json()["git_page"] is False         # off by default, like Infra
    assert client.put("/api/settings", json={"git_page": True}).json()["git_page"] is True
    assert config.load_config()["git_page"] is True


def test_repo_config_never_runs_programs(repo, tmp_path):
    """A repository's own config names programs (fsmonitor, signature check, clean filter, diff driver): listing,
    graph and commit details run none of them."""
    flag = tmp_path / "ran"
    hook = tmp_path / "hook.sh"
    hook.write_text(f"#!/bin/sh\necho \"$0 $*\" >> {flag}\ncat\n")
    hook.chmod(0o755)
    _git(repo, "config", "core.fsmonitor", str(hook))
    _git(repo, "config", "log.showSignature", "true")
    _git(repo, "config", "gpg.program", str(hook))
    _git(repo, "config", "filter.evil.clean", str(hook))
    _git(repo, "config", "filter.evil.process", str(hook))
    _git(repo, "config", "diff.external", str(hook))
    _git(repo, "config", "diff.evil.textconv", str(hook))
    (repo / ".gitattributes").write_text("*.txt filter=evil diff=evil\n")
    # a commit carrying a (fake) signature: `git log` would hand it to gpg.program
    raw = subprocess.run(["git", "-C", str(repo), "cat-file", "commit", "HEAD"], capture_output=True, text=True).stdout
    head, body = raw.split("\n\n", 1)
    signed = head + "\ngpgsig -----BEGIN PGP SIGNATURE-----\n \n -----END PGP SIGNATURE-----\n\n" + body
    sha = subprocess.run(["git", "-C", str(repo), "hash-object", "-t", "commit", "-w", "--stdin"], input=signed,
                         capture_output=True, text=True).stdout.strip()
    _git(repo, "update-ref", "refs/heads/main", sha)
    (repo / "f1.txt").write_text("9")                         # same size: status must look at the content
    gitview.clear_cache()
    s = gitview.summary(repo)
    assert s["branch"] == "main" and not s.get("error")
    g = gitview.graph(str(repo))
    assert g["commits"][0]["sha"] == sha
    assert gitview.commit(str(repo), sha)["sha"] == sha
    assert not flag.exists(), flag.read_text()


def test_remote_credentials_masked_even_with_at_sign(repo):
    _git(repo, "remote", "set-url", "origin", "https://user:p@ss@github.com/acme/site.git")
    gitview.clear_cache()
    assert gitview.summary(repo)["remote"] == "https://github.com/acme/site.git"


def test_github_odd_answers(org, monkeypatch):
    """A rate limit is not "not found", a broken answer costs one key, not the whole page."""
    import httpx
    answers = {}

    class Fake:
        def get(self, url, headers=None, params=None):
            tok = headers["Authorization"].split()[-1]
            return answers[tok](httpx.Request("GET", url))
    monkeypatch.setattr(gitview, "_client", lambda: Fake())
    answers["ghp_limited"] = lambda req: httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={"message": "API rate limit exceeded"}, request=req)
    answers["ghp_garbage"] = lambda req: httpx.Response(200, content=b"<html>oops", request=req)
    answers["ghp_noowner"] = lambda req: httpx.Response(200, json=[{"full_name": "x/y"}] if "repos" in str(req.url) else {"login": "z"}, request=req)
    with pytest.raises(gitview.GitError) as e:
        gitview._gh("/user", tok="ghp_limited")
    assert e.value.code == "rate_limited"
    with pytest.raises(gitview.GitError) as e:
        gitview._gh("/user", tok="ghp_garbage")
    assert e.value.status == 502
    answers["ghp_revoked"] = lambda req: httpx.Response(401, json={"message": "Bad credentials"}, request=req)
    with pytest.raises(gitview.GitError) as e:
        gitview._gh("/user", tok="ghp_revoked")
    assert e.value.code == "bad_token" and e.value.status == 502    # never 401: that one signs the UI out
    vault.put("GITHUB_TOKEN", "ghp_garbage")
    vault.put("OTHER_PAT", "ghp_noowner" + "x" * 30)
    answers["ghp_noowner" + "x" * 30] = answers["ghp_noowner"]
    gitview.clear_cache()
    gh = gitview.github_repos(refresh=True)                  # no exception: each key reports its own problem
    assert gh["connected"] and len(gh["errors"]) >= 1


def test_github_dates_are_utc():
    assert gitview._ts("2026-01-01T00:00:00Z") == 1767225600


def test_worktree_config_filters_never_run(repo, tmp_path):
    """A filter defined in `.git/config.worktree` (extensions.worktreeConfig) is not seen by `config --local`."""
    flag = tmp_path / "ran"
    hook = tmp_path / "hook.sh"
    hook.write_text(f"#!/bin/sh\necho ran >> {flag}\ncat\n")
    hook.chmod(0o755)
    _git(repo, "config", "extensions.worktreeConfig", "true")
    _git(repo, "config", "--worktree", "filter.wt.clean", str(hook))
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.txt filter=wt\n")
    (repo / ".gitattributes").write_text("*.txt filter=wt\n")
    (repo / "f1.txt").write_text("8")
    gitview.clear_cache()
    assert gitview.summary(repo)["branch"] == "main"
    assert not flag.exists()


def test_expired_cache_answers_at_once_and_rebuilds_behind(monkeypatch):
    import threading as _th
    gitview.clear_cache()
    calls, gate = [], _th.Event()

    def build():
        calls.append(1)
        if len(calls) > 1:
            gate.wait(5)
        return len(calls)
    assert gitview._cached("t", build) == 1
    monkeypatch.setattr(gitview, "CACHE_S", 0)
    assert gitview._cached("t", build) == 1                    # stale value now, rebuild started behind
    assert gitview._cached("t", build) == 1                    # one rebuild at a time
    gate.set()
    for _ in range(50):
        if gitview._cache["t"][1] == 2:
            break
        time.sleep(0.02)
    assert gitview._cache["t"][1] == 2 and len(calls) == 2
    assert gitview._cached("t", build, refresh=True) == 3      # refresh: built now


def test_worktrees_are_not_listed_as_repositories(repo):
    """`git worktree add` makes one folder per branch: the page lists the clone once, with the count."""
    root = config.files_root()
    _git(repo, "worktree", "add", "-q", str(root / "sites" / "acme-login"), "-b", "wt-branch")
    other = root / "lone"
    other.mkdir()
    _git(other, "init", "-q")
    gitview.clear_cache()
    repos = {r["name"]: r for r in gitview.local_repos(refresh=True)}
    assert "acme-login" not in repos and repos["acme"]["worktrees"] == 1 and repos["lone"]["worktrees"] == 0
    assert gitview.summary(root / "sites" / "acme-login")["branch"] == "wt-branch"   # still opens by its path


def test_graph_of_an_empty_repository_or_an_unborn_head(org):
    gitview.clear_cache()
    root = config.files_root()
    empty = root / "empty"
    empty.mkdir(parents=True)
    _git(empty, "init", "-q", "-b", "main")
    assert gitview.graph(str(empty))["commits"] == []
    orphan = root / "orphan"
    orphan.mkdir()
    _git(orphan, "init", "-q", "-b", "main")
    _git(orphan, "commit", "-q", "--allow-empty", "-m", "one")
    _git(orphan, "checkout", "-q", "--orphan", "x")
    assert [c["subject"] for c in gitview.graph(str(orphan))["commits"]] == ["one"]


def test_commit_detail_refuses_what_is_not_a_commit(repo):
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}", "HEAD:f1.txt"],
                         capture_output=True, text=True, check=True).stdout.split()
    for sha in out:
        with pytest.raises(gitview.GitError) as e:
            gitview.commit(str(repo), sha)
        assert e.value.status == 404
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    with pytest.raises(gitview.GitError):
        gitview.commit(str(repo), head + "\n")
    assert gitview.commit(str(repo), head[:8])["sha"] == head
    _git(repo, "tag", "-a", "t1", "-m", "annotated")  # an annotated tag shows the commit it points to
    tag = subprocess.run(["git", "-C", str(repo), "rev-parse", "t1"], capture_output=True, text=True).stdout.strip()
    assert tag != head and gitview.commit(str(repo), tag)["sha"] == head


def test_github_name_needs_github_com_itself():
    for remote, name in (("https://user:secret@github.com/acme/site.git", "acme/site"),
                         ("git@github.com:acme/site.git", "acme/site"), ("ssh://git@github.com/acme/site", "acme/site"),
                         ("https://www.GitHub.com/acme/site/", "acme/site"),
                         ("https://notgithub.com/own/repo.git", None), ("https://gitlab.com/x/github.com/own/repo", None),
                         ("git@gitlab.com:github.com/own/repo.git", None), ("git@evilgithub.com:own/repo", None),
                         ("https://github.com.evil.io/own/repo", None), ("/srv/github.com/own/repo", None)):
        assert gitview.github_name(remote) == name, remote


def test_graph_of_a_branch_named_like_a_file(repo):
    (repo / "main").write_text("a file named like the branch")
    _git(repo, "add", "main")
    _git(repo, "commit", "-qm", "add main file")
    gitview.clear_cache()
    assert gitview.graph(str(repo), branches=["main"])["commits"][0]["subject"] == "add main file"
