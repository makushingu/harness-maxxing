"""`maxxing update` never loses what ran before: the branch, uncommitted edits, the web/ edits set aside."""
from __future__ import annotations

import os
import subprocess

from maxxing import cmd_core, customs
from test_cmd_core import _git, env, repos, run_cli  # noqa: F401  (fixtures)
from test_customs import _head, _upstream_release, code  # noqa: F401  (fixtures)


def _rev(repo, ref):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", ref], capture_output=True, text=True).stdout.strip()


def _with_web_file(code):
    clone, work = code["clone"], code["work"]
    (work / "web").mkdir()
    (work / "web" / "app.js").write_text("v1\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "web", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    _git("pull", "-q", "origin", "main", cwd=clone)


def _broken_release(monkeypatch):
    cmd_core.UNIT_PATH.write_text("[Unit]\n")
    monkeypatch.setattr(cmd_core, "systemctl", lambda *a, timeout=60: (0, "ok"))
    monkeypatch.setattr(cmd_core, "_healthy", lambda version, wait=45: False)


def test_branch_switch_that_does_not_start_rolls_back_to_the_running_branch(code, monkeypatch, capsys):
    """`--branch dev` with a dev release that does not start: back on main at the commit that ran."""
    clone, work = code["clone"], code["work"]
    before = _head(clone)
    _git("checkout", "-q", "-b", "dev", cwd=work)
    (work / "server" / "maxxing" / "__init__.py").write_text('__version__ = "1.9.0"\n')
    (work / "broken.txt").write_text("does not start\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "dev 1.9.0", cwd=work)
    _git("push", "-q", "origin", "dev", cwd=work)
    _broken_release(monkeypatch)
    assert run_cli("update", "--branch", "dev") == 4
    assert "rolled back" in capsys.readouterr().out
    assert _head(clone) == before and not (clone / "broken.txt").exists()
    branch = subprocess.run(["git", "-C", str(clone), "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True).stdout.strip()
    assert branch == "main"
    assert _rev(clone, "dev") == _rev(clone, "origin/dev")        # the local dev branch is not rewritten


def test_rollback_refuses_to_destroy_uncommitted_changes(code, capsys):
    clone, work = code["clone"], code["work"]
    _upstream_release(work, "1.1.0", extra="feature.txt")
    assert run_cli("update") == 0
    after = _head(clone)
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 99\nNAME = 'wip'\n")   # work in progress
    assert run_cli("update", "--rollback", "--no-restart") == 1
    out = capsys.readouterr().out
    assert "nothing changed" in out
    assert "stash push" in out and "custom save" not in out    # a customization saved now would be rolled back
    assert "LIMIT = 99" in (clone / "server/maxxing/rules.py").read_text()
    assert _head(clone) == after
    _git("stash", "push", "-u", "-q", "-m", "before rollback", cwd=clone)   # the advice, followed
    assert run_cli("update", "--rollback", "--no-restart") == 0
    assert not (clone / "feature.txt").exists()
    _git("stash", "pop", "-q", cwd=clone)
    assert "LIMIT = 99" in (clone / "server/maxxing/rules.py").read_text()


def test_conflict_puts_the_web_edits_back(code, capsys):
    """'nothing changed' on a conflict also means the edits of web/ are back in place, not left in a stash."""
    clone, work = code["clone"], code["work"]
    _with_web_file(code)
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit")
    _upstream_release(work, "1.2.0", rules="LIMIT = 20\nNAME = 'product'\n")      # conflicts
    (clone / "web" / "app.js").write_text("my hot fix\n")
    assert run_cli("update") == 3
    assert "nothing changed" in capsys.readouterr().out
    assert (clone / "web" / "app.js").read_text() == "my hot fix\n"
    assert subprocess.run(["git", "-C", str(clone), "stash", "list"], capture_output=True, text=True).stdout == ""


def test_failed_auto_save_puts_the_web_edits_back(code, monkeypatch, capsys):
    """The update stops because the uncommitted changes cannot be saved: the web/ edits it set aside are back."""
    clone, work = code["clone"], code["work"]
    _with_web_file(code)
    _upstream_release(work, "1.2.0")
    (clone / "web" / "app.js").write_text("my hot fix\n")
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")

    def boom(*a, **k):
        raise customs.CustomError("nope")
    monkeypatch.setattr(customs, "save", boom)
    assert run_cli("update") == 1
    assert "cannot be kept" in capsys.readouterr().out
    assert (clone / "web" / "app.js").read_text() == "my hot fix\n"
    assert subprocess.run(["git", "-C", str(clone), "stash", "list"], capture_output=True, text=True).stdout == ""


def test_health_rollback_puts_the_web_edits_back(code, monkeypatch, capsys):
    clone, work = code["clone"], code["work"]
    _with_web_file(code)
    before = _head(clone)
    _upstream_release(work, "1.3.0", extra="feature.txt")
    (clone / "web" / "app.js").write_text("my hot fix\n")
    _broken_release(monkeypatch)
    assert run_cli("update") == 4
    assert "rolled back" in capsys.readouterr().out
    assert _head(clone) == before and (clone / "web" / "app.js").read_text() == "my hot fix\n"


def _branch(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def _push_dev(work, version, rules=None):
    if _branch(work) != "dev":
        _git("checkout", "-q", "-B", "dev", cwd=work)
    (work / "server" / "maxxing" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    if rules is not None:
        (work / "server" / "maxxing" / "rules.py").write_text(rules)
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", f"dev {version}", cwd=work)
    _git("push", "-q", "origin", "dev", cwd=work)


def test_detached_start_rollback_does_not_move_main(code, monkeypatch, capsys):
    """A branch under test checked out detached, then `--branch main` that does not start: back on the detached
    commit, and main is not rewritten to it (its test commits would then pass for customizations)."""
    clone, work = code["clone"], code["work"]
    (clone / "test.txt").write_text("branch under test\n")
    _git("add", "-A", cwd=clone)
    _git("commit", "-q", "-m", "test branch", cwd=clone)
    tested = _head(clone)
    _git("checkout", "-q", "--detach", tested, cwd=clone)
    _git("branch", "-q", "-f", "main", "origin/main", cwd=clone)
    _upstream_release(work, "1.4.0", extra="feature.txt")
    _broken_release(monkeypatch)
    assert run_cli("update", "--branch", "main") == 4
    assert _head(clone) == tested and _branch(clone) == "HEAD"
    assert _rev(clone, "main") != tested


def test_rollback_after_a_branch_switch_goes_back_to_the_branch_that_ran(code, capsys):
    clone, work = code["clone"], code["work"]
    before = _head(clone)
    _push_dev(work, "1.9.0")
    assert run_cli("update", "--branch", "dev", "--no-restart") == 0
    assert _branch(clone) == "dev"
    assert run_cli("update", "--rollback", "--no-restart") == 0
    assert _branch(clone) == "main" and _head(clone) == before
    assert _rev(clone, "dev") == _rev(clone, "origin/dev")        # dev is not rewritten to main's commit


def test_conflict_after_a_branch_switch_resumes_on_that_branch(code, monkeypatch, capsys):
    clone, work = code["clone"], code["work"]
    before = _head(clone)
    _push_dev(work, "1.9.0")
    _git("fetch", "-q", "origin", "dev", cwd=clone)
    _git("checkout", "-q", "-b", "dev", "--track", "origin/dev", cwd=clone)
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit")
    _git("checkout", "-q", "main", cwd=clone)
    _push_dev(work, "1.9.1", rules="LIMIT = 20\nNAME = 'product'\n")         # conflicts with the customization
    assert run_cli("update", "--branch", "dev") == 3
    out = capsys.readouterr().out
    assert "git checkout dev && git rebase origin/dev" in out
    assert _branch(clone) == "main" and _head(clone) == before
    # Claude follows the instructions, then the resumed version does not start
    _git("checkout", "-q", "dev", cwd=clone)
    subprocess.run(["git", "-C", str(clone), "rebase", "-q", "origin/dev"], capture_output=True)
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    _git("add", "-A", cwd=clone)
    subprocess.run(["git", "-C", str(clone), "rebase", "--continue"], capture_output=True,
                   env={**os.environ, "GIT_EDITOR": "true"})
    rebased = _head(clone)
    _broken_release(monkeypatch)
    assert run_cli("update", "--resume") == 4
    assert _branch(clone) == "main" and _head(clone) == before
    assert _rev(clone, "dev") == rebased                          # the adapted customization is kept on dev


def test_conflict_with_web_edits_prints_instructions_that_work(code, capsys):
    """The web/ edits are back in place after a conflict: the printed instructions set them aside again first,
    else git refuses the rebase (unstaged changes)."""
    clone, work = code["clone"], code["work"]
    _with_web_file(code)
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit")
    _upstream_release(work, "1.2.0", rules="LIMIT = 20\nNAME = 'product'\n")
    (clone / "web" / "app.js").write_text("my hot fix\n")
    assert run_cli("update") == 3
    out = capsys.readouterr().out
    cmd = next(ln.strip() for ln in out.splitlines() if ln.strip().startswith(f"cd {clone} && "))
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert "unstaged changes" not in r.stderr + r.stdout
    assert customs.rebase_in_progress() and customs.conflicts() == ["server/maxxing/rules.py"]


def test_branch_switch_rollback_keeps_the_auto_saved_changes_running(code, monkeypatch, capsys):
    """Uncommitted changes auto-saved on the new branch come back with the rollback (same customization)."""
    clone, work = code["clone"], code["work"]
    before = _head(clone)
    _push_dev(work, "1.9.0")
    (clone / "server" / "maxxing" / "rules.py").write_text("LIMIT = 99\nNAME = 'product'\n")   # not saved yet
    _broken_release(monkeypatch)
    assert run_cli("update", "--branch", "dev") == 4
    assert _branch(clone) == "main" and _rev(clone, "HEAD~1") == before
    assert "LIMIT = 99" in (clone / "server/maxxing/rules.py").read_text()
    assert [c["title"] for c in customs.list_customs("main")] == ["Unsaved changes found by the update"]
    assert _rev(clone, customs.PRE_UPDATE_REF) == _head(clone)
