"""Customizations (local commits on the product code) and the careful update."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from maxxing import cmd_core, config, customs
from test_cmd_core import _git, env, repos, run_cli  # noqa: F401  (fixtures)


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


@pytest.fixture
def code(env, repos, monkeypatch):
    """The install directory = a clone of origin with a tracked server file; a workspace."""
    work, clone = repos["work"], repos["clone"]
    (work / "server" / "maxxing").mkdir(parents=True)
    (work / "server" / "maxxing" / "__init__.py").write_text('__version__ = "1.0.0"\n')
    (work / "server" / "maxxing" / "rules.py").write_text("LIMIT = 10\nNAME = 'product'\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "rules", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    _git("pull", "-q", "origin", "main", cwd=clone)
    env["ws"].mkdir()
    config.update_config(workspace=str(env["ws"]))
    monkeypatch.setattr(config, "CODE", clone)
    monkeypatch.setattr(cmd_core, "uv_bin", lambda: "/fake/uv")
    real = cmd_core.run
    monkeypatch.setattr(cmd_core, "run", lambda cmd, **kw: real(cmd, **kw) if cmd[0] == "git" else (0, ""))
    monkeypatch.setattr(cmd_core, "_healthy", lambda version, wait=45: True)
    return {**repos, "ws": env["ws"]}


def _upstream_release(work, version, rules=None, extra=None):
    (work / "server" / "maxxing" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    if rules is not None:
        (work / "server" / "maxxing" / "rules.py").write_text(rules)
    if extra:
        (work / extra).write_text("new upstream file\n")
    cl = (work / "CHANGELOG.md").read_text().replace("# Changelog\n\n", f"# Changelog\n\n## {version}\n- release {version}\n\n", 1)
    (work / "CHANGELOG.md").write_text(cl)
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", version, cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)


def test_save_records_commit_registry_and_patch(code, capsys):
    clone, ws = code["clone"], code["ws"]
    assert run_cli("custom", "save", "nothing") == 1                       # no change yet
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    assert run_cli("custom", "save", "Raise the limit to 50", "--why", "the user runs many sessions") == 0
    items = customs.list_customs()
    assert len(items) == 1 and items[0]["title"] == "Raise the limit to 50"
    assert items[0]["why"] == "the user runs many sessions" and items[0]["files"] == ["server/maxxing/rules.py"]
    reg = (ws / "CUSTOMIZATIONS.md").read_text()
    assert "## Raise the limit to 50" in reg and items[0]["id"] in reg and "server/maxxing/rules.py" in reg
    patches = list((ws / "customizations").glob("*.patch"))
    assert len(patches) == 1 and "LIMIT = 50" in patches[0].read_text()
    assert customs.dirty_files() == []
    # the web UI is pre-built: never a customization
    (clone / "web").mkdir()
    (clone / "web" / "x.ts").write_text("x")
    assert run_cli("custom", "save", "UI tweak") == 1
    assert "extension" in capsys.readouterr().out


def test_quoted_web_paths_are_still_refused(code, capsys):
    clone = code["clone"]
    (clone / "web").mkdir()
    (clone / "web" / "café x.ts").write_text("x")
    assert customs.dirty_files() == ["web/café x.ts"]
    with pytest.raises(customs.CustomError, match="web/"):
        customs.save("UI tweak")
    (clone / "web" / "café x.ts").unlink()
    (clone / "server" / "maxxing" / "rules.py").rename(clone / "server" / "maxxing" / "règles.py")
    customs.git("add", "-A", check=True)
    assert set(customs.dirty_files()) == {"server/maxxing/règles.py", "server/maxxing/rules.py"}

def test_update_carries_customizations_over(code, capsys):
    clone, work, ws = code["clone"], code["work"], code["ws"]
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit", "many sessions")
    _upstream_release(work, "1.1.0", extra="feature.txt")                  # no overlap
    assert run_cli("update", "--check") == 0
    assert "will be carried over: Raise the limit" in capsys.readouterr().out
    assert run_cli("update") == 0
    out = capsys.readouterr().out
    assert "1 customization(s) carried over" in out and "release 1.1.0" in out
    assert (clone / "feature.txt").exists() and "LIMIT = 50" in (clone / "server/maxxing/rules.py").read_text()
    assert [c["title"] for c in customs.list_customs()] == ["Raise the limit"]
    assert customs.pending() is None and (ws / "CUSTOMIZATIONS.md").exists()


def test_conflict_changes_nothing_then_resume_after_claude_adapts(code, capsys):
    clone, work = code["clone"], code["work"]
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit", "many sessions")
    before = _head(clone)
    _upstream_release(work, "1.2.0", rules="LIMIT = 20\nNAME = 'product'\nMODE = 'fast'\n")
    assert run_cli("update") == 3
    out = capsys.readouterr().out
    assert "conflict with the new version 1.2.0" in out and "nothing changed" in out
    assert _head(clone) == before and not customs.rebase_in_progress()   # untouched
    p = customs.pending()
    assert p["reason"] == "conflict" and p["conflicts"] == ["server/maxxing/rules.py"] and p["target_version"] == "1.2.0"
    assert run_cli("doctor") in (0, 1)
    assert "update pending: customizations conflict" in capsys.readouterr().out
    # what Claude does (skill maxxing-customize): rebase, adapt, continue, resume
    customs.ensure_identity()                                           # done by save() / update anyway
    subprocess.run(["git", "-C", str(clone), "rebase", "origin/main"], capture_output=True)
    assert customs.rebase_in_progress() and customs.conflicts() == ["server/maxxing/rules.py"]
    assert run_cli("update", "--resume") == 1                            # not finished yet
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\nMODE = 'fast'\n")
    # exactly what Claude runs - plain git, no terminal, no editor configured
    subprocess.run(["git", "-C", str(clone), "add", "server/maxxing/rules.py"], check=True)
    r = subprocess.run(["git", "-C", str(clone), "rebase", "--continue"], capture_output=True, text=True,
                       env={k: v for k, v in __import__("os").environ.items() if k not in ("EDITOR", "VISUAL", "GIT_EDITOR")}
                       | {"TERM": "dumb"})
    assert r.returncode == 0, r.stderr
    assert run_cli("update", "--resume") == 0
    assert customs.pending() is None
    assert "MODE = 'fast'" in (clone / "server/maxxing/rules.py").read_text()
    assert [c["title"] for c in customs.list_customs()] == ["Raise the limit"]


def test_unsaved_changes_are_auto_saved_by_the_update(code, capsys):
    clone, work = code["clone"], code["work"]
    (clone / "server" / "maxxing" / "hotfix.py").write_text("FIX = True\n")
    _upstream_release(work, "1.1.0", extra="feature.txt")
    assert run_cli("update") == 0
    assert "uncommitted change(s) saved as customization" in capsys.readouterr().out
    items = customs.list_customs()
    assert len(items) == 1 and items[0]["files"] == ["server/maxxing/hotfix.py"]
    assert (clone / "server/maxxing/hotfix.py").exists() and (clone / "feature.txt").exists()


def test_a_release_that_does_not_start_is_rolled_back(code, monkeypatch, capsys):
    clone, work = code["clone"], code["work"]
    before = _head(clone)
    _upstream_release(work, "1.3.0", extra="feature.txt")
    cmd_core.UNIT_PATH.write_text("[Unit]\n")
    monkeypatch.setattr(cmd_core, "systemctl", lambda *a, timeout=60: (0, "ok"))
    monkeypatch.setattr(cmd_core, "_healthy", lambda version, wait=45: False)
    assert run_cli("update") == 4
    assert "rolled back" in capsys.readouterr().out
    assert _head(clone) == before and not (clone / "feature.txt").exists()
    assert customs.pending()["reason"] == "health"
    monkeypatch.setattr(cmd_core, "_healthy", lambda version, wait=45: True)
    assert run_cli("update") == 0 and customs.pending() is None             # next try works


def test_rollback_and_drop(code, capsys):
    clone, work = code["clone"], code["work"]
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    first = customs.save("Raise the limit")["id"]
    (clone / "server" / "maxxing" / "extra.py").write_text("X = 1\n")
    customs.save("Add extra")
    before = _head(clone)
    _upstream_release(work, "1.1.0", extra="feature.txt")
    assert run_cli("update") == 0 and (clone / "feature.txt").exists()
    assert run_cli("update", "--rollback", "--no-restart") == 0
    assert _head(clone) == before and not (clone / "feature.txt").exists()
    assert run_cli("custom", "drop", first) == 0
    assert [c["title"] for c in customs.list_customs()] == ["Add extra"]
    assert "LIMIT = 10" in (clone / "server/maxxing/rules.py").read_text()
    assert run_cli("custom", "drop", "nope") == 1


def test_drop_needs_a_real_id_not_an_empty_or_tiny_prefix(code):
    """`custom drop ""` matched every commit (startswith("")) and silently removed the oldest customization."""
    clone = code["clone"]
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit")
    (clone / "server" / "maxxing" / "extra.py").write_text("X = 1\n")
    customs.save("Add extra")
    first = customs.list_customs()[0]
    for cid in ("", first["commit"][:1], first["commit"][:3]):
        with pytest.raises(customs.CustomError):
            customs.drop(cid)
    assert [c["title"] for c in customs.list_customs()] == ["Raise the limit", "Add extra"]
    assert customs.drop(first["commit"][:7])["dropped"]["title"] == "Raise the limit"


def test_check_set_by_a_sha_prefix_is_kept_under_the_customization_id(code):
    """`custom check <sha prefix>` was stored under the prefix: list_customs never showed it, the update never ran it."""
    (code["clone"] / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit")
    it = customs.list_customs()[0]
    customs.set_check(it["commit"][:8], "true")
    assert customs.check_overrides() == {it["id"]: "true"} and customs.list_customs()[0]["check"] == "true"
    customs.set_check(it["commit"][:8], "")
    assert customs.check_overrides() == {}


def test_restore_on_a_fresh_install(code, tmp_path, monkeypatch, capsys):
    clone, ws = code["clone"], code["ws"]
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit", "many sessions")
    fresh = tmp_path / "fresh"
    _git("clone", "-q", "-b", "main", str(code["origin"]), str(fresh), cwd=tmp_path)
    monkeypatch.setattr(config, "CODE", fresh)                            # new server, workspace restored
    assert run_cli("custom", "restore") == 0
    assert "1 customization(s) applied" in capsys.readouterr().out
    assert "LIMIT = 50" in (fresh / "server/maxxing/rules.py").read_text()
    assert [c["title"] for c in customs.list_customs()] == ["Raise the limit"]
    assert run_cli("custom", "restore") == 0                               # idempotent
    assert "0 customization(s) applied" in capsys.readouterr().out


def test_status_json(code, capsys):
    (code["clone"] / "server" / "maxxing" / "rules.py").write_text("LIMIT = 1\n")
    assert run_cli("custom", "status", "--json") == 0
    st = json.loads(capsys.readouterr().out)
    assert st["git"] and st["dirty"] == ["server/maxxing/rules.py"] and st["customs"] == []


def test_version_card_cached_until_the_clone_changes(code, monkeypatch):
    import time as _time

    from maxxing.api import system as system_api
    system_api._ver.update(at=_time.time(), busy=False)            # no remote check here
    calls = []
    real = customs.list_customs
    monkeypatch.setattr(customs, "list_customs", lambda branch=None: calls.append(1) or real(branch))
    v = system_api.version_info()
    assert v["custom"]["count"] == 0 and v["commit"] and len(calls) == 1
    assert system_api.version_info()["commit"] == v["commit"] and len(calls) == 1     # cached
    rules = code["clone"] / "server" / "maxxing" / "rules.py"
    rules.write_text("LIMIT = 50\nNAME = 'product'\n")
    assert run_cli("custom", "save", "Raise the limit", "--why", "more sessions") == 0  # commits: HEAD ref moves
    v2 = system_api.version_info()
    assert v2["custom"]["count"] == 1 and v2["custom"]["titles"] == ["Raise the limit"] and v2["commit"] != v["commit"]
    rules.write_text("LIMIT = 60\n")                                                   # uncommitted edit
    monkeypatch.setattr(system_api, "LOCAL_TTL", 0)
    assert system_api.version_info()["custom"]["dirty"] == 1


def _rewrite_upstream(work):
    """The maintainers rewrite the whole history (new authors, same code), with no common ancestor left."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "Maintainer", "GIT_AUTHOR_EMAIL": "maintainer@example.com",
           "GIT_COMMITTER_NAME": "Maintainer", "GIT_COMMITTER_EMAIL": "maintainer@example.com"}

    def git(*a):
        return subprocess.run(["git", "-C", str(work), *a], check=True, env=env, capture_output=True, text=True).stdout.strip()
    parent = None
    for sha in git("rev-list", "--reverse", "main").split():
        msg = git("log", "-1", "--format=%B", sha) or "commit"
        parent = git("commit-tree", f"{sha}^{{tree}}", *(["-p", parent] if parent else []), "-m", msg)
    git("reset", "-q", "--hard", parent)
    _git("push", "-q", "-f", "origin", "main", cwd=work)


def test_update_follows_a_rewritten_history(code, capsys):
    clone, work = code["clone"], code["work"]
    _upstream_release(work, "1.1.0")
    assert run_cli("update") == 0
    old = _head(clone)
    _rewrite_upstream(work)
    _upstream_release(work, "1.2.0", extra="feature.txt")
    capsys.readouterr()
    assert run_cli("update") == 0
    out = capsys.readouterr().out
    assert "rewritten upstream" in out and "release 1.2.0" in out
    assert _head(clone) == _head(work) != old and (clone / "feature.txt").exists()
    assert customs.list_customs() == []


def test_customizations_survive_a_rewritten_history(code, capsys):
    clone, work, ws = code["clone"], code["work"], code["ws"]
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit", "many sessions")
    _rewrite_upstream(work)
    _git("fetch", "-q", "origin", cwd=clone)
    # the old upstream commits are not taken for customizations, before the update either
    assert [c["title"] for c in customs.list_customs()] == ["Raise the limit"]
    _upstream_release(work, "1.2.0", extra="feature.txt")
    assert run_cli("update") == 0
    assert "1 customization(s) carried over" in capsys.readouterr().out
    assert (clone / "feature.txt").exists() and "LIMIT = 50" in (clone / "server/maxxing/rules.py").read_text()
    assert [c["title"] for c in customs.list_customs()] == ["Raise the limit"]
    patches = list((ws / "customizations").glob("*.patch"))
    assert len(patches) == 1 and "LIMIT = 50" in patches[0].read_text()
    log = subprocess.run(["git", "-C", str(clone), "log", "--format=%an"], capture_output=True, text=True).stdout.split("\n")
    assert "Maintainer" in log                                  # sits on the new history


def test_a_local_commit_is_never_dropped_for_a_rewritten_history(code, capsys):
    """Code that is no upstream version (a hand commit merged with upstream) is never reset away."""
    clone, work = code["clone"], code["work"]
    _rewrite_upstream(work)
    _git("fetch", "-q", "origin", cwd=clone)
    assert customs.same_code_upstream()
    (clone / "local.txt").write_text("mine\n")
    _git("add", "-A", cwd=clone)
    _git("commit", "-q", "-m", "local", cwd=clone)
    assert not customs.same_code_upstream()
