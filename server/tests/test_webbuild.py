"""Customized web UI: its sources are customizations, this server builds them into <state>/web-dist (webbuild.py).
A fake Node stands in for npm / tsc / vite: `vite build` copies web/src/main.txt to <outDir>/index.html."""
from __future__ import annotations

import subprocess

import pytest

from maxxing import cmd_core, config, customs, deps, smartupdate, webbuild
from test_cmd_core import _git, env, repos, run_cli  # noqa: F401  (fixtures)
from test_customs import _upstream_release, code  # noqa: F401  (fixtures)

FAKE_NODE = """#!/bin/sh
case "$1" in
  *tsc) if [ -f "$PWD/src/TYPE_ERROR" ]; then echo "src/main.tsx(1,1): error TS2322: wrong type"; exit 2; fi; exit 0 ;;
  *vite.js) out=""; while [ $# -gt 0 ]; do [ "$1" = "--outDir" ] && out="$2"; shift; done
            mkdir -p "$out" && cp src/main.txt "$out/index.html" && exit 0 ;;
esac
exit 1
"""
FAKE_NPM = """#!/bin/sh
mkdir -p node_modules
echo "npm $*" >> node_modules/npm.log
"""


@pytest.fixture
def ui(code, tmp_path, monkeypatch):
    """The code directory ships web sources + their build; a fake Node.js."""
    work, clone = code["work"], code["clone"]
    (work / "web" / "src").mkdir(parents=True)
    (work / "web" / "dist").mkdir()
    (work / "web" / "package.json").write_text('{"name": "web"}\n')
    (work / "web" / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    (work / "web" / "src" / "main.txt").write_text("<p>standard</p>\n")
    (work / "web" / "dist" / "index.html").write_text("<p>shipped</p>\n")
    (work / ".gitignore").write_text("node_modules\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "web", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    _git("pull", "-q", "origin", "main", cwd=clone)
    bin_dir = tmp_path / "nodebin"
    bin_dir.mkdir()
    for name, text in (("node", FAKE_NODE), ("npm", FAKE_NPM)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    monkeypatch.setattr(deps, "node_bin", lambda: bin_dir / "node")
    monkeypatch.setattr(config, "WEB_DIST", clone / "web" / "dist")
    monkeypatch.delenv("MAXXING_WEB_DIST", raising=False)
    webbuild.forget()
    yield {**code}
    webbuild.forget()


def _served(clone=None) -> str:
    webbuild.forget()
    return (webbuild.active_dist() / "index.html").read_text()


def _edit(clone, text="<p>mine</p>\n"):
    (clone / "web" / "src" / "main.txt").write_text(text)


def test_the_shipped_build_is_served_until_a_customization_is_built(ui):
    clone = ui["clone"]
    assert webbuild.customized_files() == [] and _served() == "<p>shipped</p>\n"
    assert run_cli("custom", "build") == 0                       # nothing customized: nothing to do
    assert not webbuild.build_dir().exists()
    _edit(clone)
    assert webbuild.customized_files() == ["web/src/main.txt"]
    assert _served() == "<p>shipped</p>\n"                       # not built yet
    assert cmd_core.check_web()["level"] == cmd_core.WARN
    assert run_cli("custom", "build") == 0
    assert _served() == "<p>mine</p>\n"                          # served at once, no restart
    assert cmd_core.check_web()["level"] == cmd_core.OK
    assert (clone / "web" / "dist" / "index.html").read_text() == "<p>shipped</p>\n"   # never touched
    assert customs.dirty_files() == ["web/src/main.txt"]         # node_modules ignored, dist clean
    assert run_cli("custom", "save", "My header", "--why", "the user wanted it") == 0
    assert _served() == "<p>mine</p>\n"                          # the same sources, now saved


def test_the_customized_ui_stays_until_a_new_build_replaces_it(ui, capsys):
    clone = ui["clone"]
    _edit(clone)
    assert webbuild.build()["ok"]
    _edit(clone, "<p>mine, edited again</p>\n")
    (clone / "web" / "src" / "scratch.orig").write_text("x")     # a stray file under web/ changes nothing either
    assert _served() == "<p>mine</p>\n"                          # being adapted: the customized UI stays
    st = webbuild.status()
    assert st["built"] and not st["current"]
    assert cmd_core.check_web()["level"] == cmd_core.WARN
    run_cli("custom")
    assert "your previous build" in capsys.readouterr().out
    (clone / "web" / "src" / "scratch.orig").unlink()
    assert webbuild.build()["ok"]
    assert _served() == "<p>mine, edited again</p>\n"
    _edit(clone)                                                  # back to the first sources (a rollback)
    assert _served() == "<p>mine</p>\n"                          # the previous build is kept for that
    _git("checkout", "--", "web", cwd=clone)                     # the unsaved customization thrown away
    assert _served() == "<p>shipped</p>\n"


def test_a_dropped_customization_shows_the_shipped_ui(ui):
    clone = ui["clone"]
    _edit(clone)
    assert run_cli("custom", "save", "My header", "--why", "the user wanted it") == 0
    assert webbuild.build()["ok"]
    (clone / "web" / "src" / "other.txt").write_text("more\n")
    assert run_cli("custom", "save", "Another", "--why", "more") == 0   # saving more keeps the build served
    assert _served() == "<p>mine</p>\n"
    first = customs.list_customs()[0]["id"]
    assert run_cli("custom", "drop", first) == 0
    assert _served() == "<p>shipped</p>\n"                       # the build holds what was dropped


def test_a_failed_build_keeps_what_was_served(ui, capsys):
    clone = ui["clone"]
    _edit(clone)
    assert webbuild.build()["ok"]
    _edit(clone, "<p>broken</p>\n")
    (clone / "web" / "src" / "TYPE_ERROR").write_text("x")
    assert run_cli("custom", "build") == 1
    out = capsys.readouterr().out
    assert "does not build" in out and "TS2322" in out and "previous build stays" in out
    assert _served() == "<p>mine</p>\n"                          # the last good build, never a half one
    assert (webbuild.build_dir() / "index.html").read_text() == "<p>mine</p>\n"


def test_node_modules_are_installed_once_per_lockfile(ui):
    clone = ui["clone"]
    _edit(clone)
    assert webbuild.build()["ok"] and webbuild.build()["ok"]
    log = (clone / "web" / "node_modules" / "npm.log").read_text().splitlines()
    assert len(log) == 1 and log[0].startswith("npm ci")
    (clone / "web" / "package-lock.json").write_text('{"lockfileVersion": 3, "x": 1}\n')
    assert webbuild.build()["ok"]
    assert len((clone / "web" / "node_modules" / "npm.log").read_text().splitlines()) == 2


def test_the_update_rebuilds_the_customized_ui(ui, capsys):
    clone, work = ui["clone"], ui["work"]
    _edit(clone)
    assert run_cli("custom", "save", "My header", "--why", "the user wanted it") == 0
    assert webbuild.build()["ok"]
    _upstream_release(work, "1.1.0", extra="feature.txt")
    rep = smartupdate.preflight()
    assert rep["ui_build"]["status"] == "ok" and rep["verdict"] == "simple"
    assert run_cli("update", "--no-restart") == 0
    assert "customized web UI rebuilt" in capsys.readouterr().out
    assert (clone / "feature.txt").exists() and _served() == "<p>mine</p>\n"
    assert webbuild._stamp(webbuild.build_dir())["commit"] == subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def test_a_ui_customization_that_no_longer_builds_never_blocks_the_update(ui, capsys):
    clone, work = ui["clone"], ui["work"]
    _edit(clone)
    assert run_cli("custom", "save", "My header", "--why", "the user wanted it") == 0
    assert webbuild.build()["ok"]
    (work / "web" / "src" / "TYPE_ERROR").write_text("the new version changed a type\n")
    _upstream_release(work, "1.1.0")
    rep = smartupdate.preflight()
    assert rep["ui_build"]["status"] == "failed" and rep["verdict"] == "adapt"
    assert "does NOT BUILD" in smartupdate.assist_prompt(rep)
    assert run_cli("update", "--no-restart") == 0
    assert "do not build on the new version" in capsys.readouterr().out
    assert _served() == "<p>shipped</p>\n"                       # the standard interface meanwhile


def test_uncommitted_ui_sources_are_saved_by_the_update_and_the_build_set_aside(ui, capsys):
    clone, work = ui["clone"], ui["work"]
    _edit(clone)
    (clone / "web" / "dist" / "index.html").write_text("<p>built by hand in place</p>\n")
    _upstream_release(work, "1.1.0")
    rep = smartupdate.preflight()
    assert rep["unsaved"] == ["web/src/main.txt"] and rep["web_changes"] == ["web/dist/index.html"]
    assert run_cli("update", "--no-restart") == 0
    assert [c["files"] for c in customs.list_customs()] == [["web/src/main.txt"]]
    assert (clone / "web" / "dist" / "index.html").read_text() == "<p>shipped</p>\n"
    assert _served() == "<p>mine</p>\n"                          # rebuilt from the saved sources
    assert [x["kind"] for x in customs.web_leftovers()] == ["stash"]
    run_cli("custom")
    assert "Old UI edits" in capsys.readouterr().out


def test_leftovers_also_list_commits_that_changed_the_shipped_build(ui):
    clone = ui["clone"]
    (clone / "web" / "dist" / "index.html").write_text("<p>hand made</p>\n")
    _git("commit", "-qam", "my ui", cwd=clone)
    assert [(x["kind"], x["title"]) for x in customs.web_leftovers()] == [("commit", "my ui")]


def test_the_env_override_always_wins(ui, tmp_path, monkeypatch):
    _edit(ui["clone"])
    assert webbuild.build()["ok"]
    monkeypatch.setenv("MAXXING_WEB_DIST", str(tmp_path / "dev"))
    monkeypatch.setattr(config, "WEB_DIST", tmp_path / "dev")
    webbuild.forget()
    assert webbuild.active_dist() == tmp_path / "dev"


def test_no_pathspec_slips_the_shipped_build_into_a_customization(ui):
    clone = ui["clone"]
    (clone / "web" / "dist" / "index.html").write_text("<p>edited build</p>\n")
    _edit(clone)
    for files in (["."], ["web"], None):
        with pytest.raises(customs.CustomError, match="web/dist"):
            customs.save("UI tweak", files=files)
    assert customs.list_customs() == []
    _git("add", "web/dist", cwd=clone)                            # staged earlier, other files saved
    with pytest.raises(customs.CustomError, match="web/dist"):
        customs.save("UI tweak", files=["web/src/main.txt"])
    assert customs.save("UI tweak", files=["web/src/main.txt"])["id"]   # the refusal unstaged it


def test_the_preflight_never_installs_build_tools(ui):
    clone, work = ui["clone"], ui["work"]
    _edit(clone)
    assert run_cli("custom", "save", "My header", "--why", "x") == 0
    assert webbuild.build()["ok"]
    (work / "web" / "package-lock.json").write_text('{"lockfileVersion": 3, "new": 1}\n')
    _upstream_release(work, "1.1.0")
    rep = smartupdate.preflight()
    assert rep["ui_build"]["status"] == "unchecked" and rep["verdict"] == "simple"
    assert rep["ui_build"]["reason"] == "tools_changed"
    assert len((clone / "web" / "node_modules" / "npm.log").read_text().splitlines()) == 1   # no npm ci for it


def test_a_source_edited_during_the_build_is_not_taken_for_built(ui, monkeypatch):
    clone = ui["clone"]
    _edit(clone)
    real = webbuild._run

    def run(cmd, cwd, env, timeout):
        if cmd[1].endswith("vite.js"):
            _edit(clone, "<p>edited while building</p>\n")
        return real(cmd, cwd, env, timeout)
    monkeypatch.setattr(webbuild, "_run", run)
    assert webbuild.build()["ok"]
    assert not webbuild.status()["current"]                      # the build has the older text: not up to date


def test_leftovers_of_a_killed_build_are_swept(ui):
    import os
    old = config.STATE / "web-dist.new-abc"
    old.mkdir(parents=True)
    os.utime(old, (1, 1))
    _edit(ui["clone"])
    assert webbuild.build()["ok"] and not old.exists()


def test_the_build_stamp_is_never_served(ui):
    from fastapi.testclient import TestClient
    from maxxing.app import create_app
    _edit(ui["clone"])
    assert run_cli("custom", "build") == 0
    webbuild.forget()
    assert (webbuild.active_dist() / webbuild.STAMP).is_file()
    r = TestClient(create_app()).get("/" + webbuild.STAMP)
    assert "commit" not in r.text and "built_at" not in r.text


def test_a_web_file_name_that_is_not_utf8_never_takes_the_pages_down(ui):
    import os
    clone = ui["clone"]
    _edit(clone)
    assert webbuild.build()["ok"] and _served() == "<p>mine</p>\n"
    (clone / "web" / "src" / os.fsdecode(b"caf\xe9.ts")).write_text("x\n")
    assert webbuild.source_key() is not None                    # no UnicodeDecodeError
    assert _served() == "<p>mine</p>\n"                         # sources changed: the last build, not a 500
    assert webbuild.build()["ok"] and _served() == "<p>mine</p>\n"


def test_a_build_never_raises(ui, monkeypatch, capsys):
    import errno
    import tempfile
    clone = ui["clone"]
    _edit(clone)
    real = webbuild._run

    def latin1(cmd, cwd, env, timeout):                     # a tool that prints a Latin-1 file name and fails
        if cmd[1].endswith("tsc"):
            cmd = ["sh", "-c", "printf 'error caf\\351.ts\\n'; exit 2"]
        return real(cmd, cwd, env, timeout)
    with monkeypatch.context() as m:
        m.setattr(webbuild, "_run", latin1)
        r = webbuild.build()
        assert not r["ok"] and "caf" in r["error"]

    def full(*a, **k):
        raise OSError(errno.ENOSPC, "No space left on device")
    with monkeypatch.context() as m:
        m.setattr(tempfile, "mkdtemp", full)
        r = webbuild.build()
        assert not r["ok"] and "No space left" in r["error"]
        cmd_core._rebuild_web_ui()                           # the end of `maxxing update`: a warning, no trace
        assert "do not build" in capsys.readouterr().out
    assert webbuild.build()["ok"] and _served() == "<p>mine</p>\n"
    assert not list(config.STATE.glob("web-dist.new-*"))


def test_a_failed_swap_keeps_the_served_build(ui, monkeypatch):
    from pathlib import Path
    clone = ui["clone"]
    _edit(clone)
    assert webbuild.build()["ok"]
    _edit(clone, "<p>second</p>\n")
    assert webbuild.build()["ok"]
    _edit(clone, "<p>third</p>\n")
    real = Path.rename

    def rename(self, target):
        if self.name.startswith("web-dist.new-"):
            raise OSError("rename failed")
        return real(self, target)
    with monkeypatch.context() as m:
        m.setattr(Path, "rename", rename)
        assert not webbuild.build()["ok"]
    _edit(clone, "<p>second</p>\n")
    assert _served() == "<p>second</p>\n"                    # still in place
    _edit(clone)
    assert _served() == "<p>mine</p>\n"                      # and the previous one still kept
    assert not list(config.STATE.glob("web-dist.new-*"))


def test_a_swap_cut_between_its_renames_puts_the_build_back(ui):
    _edit(ui["clone"])
    assert webbuild.build()["ok"]
    old = webbuild.build_dir().with_name("web-dist.old")
    webbuild.build_dir().rename(old)                         # stopped after the first rename
    assert _served() == "<p>mine</p>\n"
    assert webbuild.build_dir().is_dir() and not old.exists()


def test_a_timed_out_build_step_leaves_no_process_behind(tmp_path):
    import os
    import time
    pidfile = tmp_path / "pid"
    ok, msg = webbuild._run(["sh", "-c", f"sleep 300 & echo $! > {pidfile}; sleep 300"], tmp_path, dict(os.environ), 2)
    assert not ok and "timed out" in msg
    pid = int(pidfile.read_text())
    for _ in range(50):                                      # the grandchild (npm's scripts, esbuild) is gone too
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("grandchild still alive")


def test_a_link_to_a_fifo_under_web_never_blocks_the_pages(ui):
    import os
    clone = ui["clone"]
    _edit(clone)
    assert webbuild.build()["ok"] and _served() == "<p>mine</p>\n"
    os.mkfifo(clone / "fifo")
    (clone / "web" / "src" / "link.ts").symlink_to(clone / "fifo")
    assert webbuild.source_key() is not None                    # returns: the link is keyed by its target, not read
    assert _served() == "<p>mine</p>\n"                         # sources changed (a new file): the last build stays
    assert not webbuild.status()["current"]
    (clone / "web" / "src" / "link.ts").unlink()
    assert _served() == "<p>mine</p>\n"


def test_rebuilding_the_same_sources_keeps_the_previous_build(ui):
    clone = ui["clone"]
    _edit(clone)
    assert webbuild.build()["ok"]
    first = webbuild._stamp(webbuild.build_dir())["key"]
    _edit(clone, "<p>mine, edited again</p>\n")
    assert webbuild.build()["ok"]
    assert webbuild._stamp(webbuild._prev_dir())["key"] == first
    assert webbuild.build()["ok"]                                 # nothing changed: a second build of the same sources
    assert webbuild._stamp(webbuild._prev_dir())["key"] == first  # the rollback still finds the first one
    _edit(clone)
    assert _served() == "<p>mine</p>\n"


def test_the_settings_page_never_builds_the_ui_inside_its_request(ui, monkeypatch):
    import asyncio
    import threading
    from maxxing.api import system
    clone, work = ui["clone"], ui["work"]
    _edit(clone)
    assert run_cli("custom", "save", "My header", "--why", "x") == 0
    assert webbuild.build()["ok"]
    _upstream_release(work, "1.1.0")
    real, later = webbuild.build, smartupdate.check_ui_later
    started = []
    monkeypatch.setattr(smartupdate, "check_ui_later", lambda: started.append(1) or True)
    monkeypatch.setattr(webbuild, "build", lambda *a, **k: pytest.fail("built in the request"))
    rep = asyncio.run(system.update_preflight(refresh=True))
    assert rep["ui_build"]["status"] == "pending" and started == [1]
    assert asyncio.run(system.update_preflight())["ui_build"]["status"] == "pending" and started == [1, 1]
    monkeypatch.setattr(webbuild, "build", real)
    assert later()                                                 # the real background check
    for t in threading.enumerate():
        if t.name == "preflight-ui":
            t.join(60)
    assert smartupdate.cached_preflight()["ui_build"]["status"] == "ok"


def test_a_ui_never_built_here_is_not_blamed_on_new_build_tools(ui, capsys):
    clone, work = ui["clone"], ui["work"]
    _edit(clone)
    assert run_cli("custom", "save", "My header", "--why", "x") == 0      # saved, never built
    _upstream_release(work, "1.1.0")
    rep = smartupdate.preflight()
    assert rep["ui_build"]["status"] == "unchecked" and rep["ui_build"]["reason"] == "never_built"
    assert run_cli("update", "--preflight") == 0
    out = capsys.readouterr().out
    assert "never built on this server" in out and "changes its build tools" not in out
