"""Smart update: preflight on a throw-away copy, verification after, the Harness sessions."""
from __future__ import annotations

import json
import subprocess

from maxxing import config, customs, extensions, smartupdate
from test_cmd_core import _git, env, repos, run_cli  # noqa: F401  (fixtures)
from test_customs import _head, _upstream_release, code  # noqa: F401  (fixture)


def _worktrees(clone) -> int:
    out = subprocess.run(["git", "-C", str(clone), "worktree", "list"], capture_output=True, text=True).stdout
    return len([ln for ln in out.splitlines() if ln.strip()])


def _status(rep):
    return {c["title"]: c["status"] for c in rep["customs"]}


def test_preflight_simple_changes_nothing(code, capsys):
    clone, work = code["clone"], code["work"]
    (clone / "server/maxxing/rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit", "many sessions")
    before = _head(clone)
    (work / "docs/upgrade").mkdir(parents=True)
    (work / "docs/upgrade/1.1.0.md").write_text("# Upgrade notes - 1.1.0\n\nAdd a line to memory.md.\n")
    _upstream_release(work, "1.1.0", extra="feature.txt")
    rep = smartupdate.preflight()
    assert rep["ok"] and rep["verdict"] == "simple" and rep["latest"] == "1.1.0" and rep["behind"] == 1
    assert _status(rep) == {"Raise the limit": "ok"} and rep["notes"] == [{"version": "1.1.0"}]
    assert _head(clone) == before and not (clone / "feature.txt").exists() and _worktrees(clone) == 1
    assert smartupdate.cached_preflight()["target"] == rep["target"]          # cached while nothing changes
    assert run_cli("update", "--preflight") == 0
    assert "verdict: simple" in capsys.readouterr().out


def test_preflight_conflict_included_and_review(code):
    clone, work = code["clone"], code["work"]
    rules = clone / "server/maxxing/rules.py"
    rules.write_text("LIMIT = 50\nNAME = 'product'\n")
    customs.save("Raise the limit")
    (clone / "server/maxxing/extra.py").write_text("A = 1\nB = 2\nC = 3\nD = 4\nE = 5\nF = 6\n")
    customs.save("Extra settings")
    (clone / "server/maxxing/fix.py").write_text("FIXED = True\n")
    customs.save("Hotfix")
    # upstream: changes LIMIT (conflict), ships the same hotfix (included), edits extra.py elsewhere (review)
    (work / "server/maxxing/fix.py").write_text("FIXED = True\n")
    (work / "server/maxxing/extra.py").write_text("A = 1\nB = 2\nC = 3\nD = 4\nE = 5\nF = 6\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "extra", cwd=work)
    (work / "server/maxxing/extra.py").write_text("A = 1\nB = 2\nC = 3\nD = 4\nE = 5\nF = 60\n")
    _upstream_release(work, "1.2.0", rules="LIMIT = 20\nNAME = 'product'\n")
    rep = smartupdate.preflight()
    st = _status(rep)
    assert st["Raise the limit"] == "conflict" and st["Hotfix"] == "included"
    conflict = next(c for c in rep["customs"] if c["status"] == "conflict")
    assert conflict["conflicts"] == ["server/maxxing/rules.py"] and rep["verdict"] == "adapt"
    assert _worktrees(clone) == 1 and "LIMIT = 50" in rules.read_text()       # the install is untouched
    prompt = smartupdate.assist_prompt(rep)
    assert "CONFLICTS" in prompt and "INCLUDED" in prompt and "maxxing update --resume" in prompt


def test_review_when_a_customization_touches_changed_code(code):
    clone, work = code["clone"], code["work"]
    (work / "server/maxxing/big.py").write_text("\n".join(f"X{i} = {i}" for i in range(20)) + "\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "big", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    _git("pull", "-q", "origin", "main", cwd=clone)
    (clone / "server/maxxing/big.py").write_text("\n".join(f"X{i} = {i if i else 100}" for i in range(20)) + "\n")
    customs.save("First value 100")
    (work / "server/maxxing/big.py").write_text("\n".join(f"X{i} = {i if i != 19 else 190}" for i in range(20)) + "\n")
    _upstream_release(work, "1.1.0")
    rep = smartupdate.preflight()
    assert _status(rep) == {"First value 100": "review"} and rep["verdict"] == "simple"


def test_web_edits_are_reported_then_set_aside(code, capsys):
    clone, work = code["clone"], code["work"]
    (work / "web").mkdir()
    (work / "web/app.js").write_text("ui = 1\n")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "web", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    _git("pull", "-q", "origin", "main", cwd=clone)
    (clone / "web/app.js").write_text("ui = 2  # edited by hand\n")
    _upstream_release(work, "1.1.0", extra="feature.txt")
    rep = smartupdate.preflight()
    assert rep["web_changes"] == ["web/app.js"] and rep["verdict"] == "adapt"
    assert run_cli("update") == 0                                         # no longer blocked
    assert "set aside (git stash)" in capsys.readouterr().out
    assert (clone / "feature.txt").exists() and (clone / "web/app.js").read_text() == "ui = 1\n"
    stash = subprocess.run(["git", "-C", str(clone), "stash", "list"], capture_output=True, text=True).stdout
    assert "edits of the web UI" in stash and customs.list_customs() == []


def test_checks_and_verify(code, capsys):
    clone, ws = code["clone"], code["ws"]
    (clone / "server/maxxing/rules.py").write_text("LIMIT = 50\nNAME = 'product'\n")
    assert run_cli("custom", "save", "Raise the limit", "--why", "w", "--check", "grep -q 'LIMIT = 50' $MAXXING_CODE/server/maxxing/rules.py") == 0
    (clone / "server/maxxing/x.py").write_text("X = 1\n")
    cid = customs.save("Add x")["id"]
    assert run_cli("custom", "check", cid, "test -f $MAXXING_CODE/server/maxxing/nope.py") == 0
    items = {c["title"]: c["check"] for c in customs.list_customs()}
    assert items["Add x"].startswith("test -f") and items["Raise the limit"].startswith("grep")
    assert "- check: `test -f" in (ws / "CUSTOMIZATIONS.md").read_text()
    good = ws / "extensions" / "good"
    good.mkdir(parents=True)
    (good / "manifest.json").write_text(json.dumps({"id": "good", "name": "Good", "type": "widget", "api": 1}))
    (good / "api.py").write_text("def card(ctx):\n    return {'title': 'ok', 'blocks': []}\n")
    bad = ws / "extensions" / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text(json.dumps({"id": "bad", "name": "Bad", "type": "widget"}))
    (bad / "api.py").write_text("import nothing_here\n")
    assert run_cli("update", "--verify") == 1
    out = capsys.readouterr().out
    rep = smartupdate.last_report()
    assert not rep["ok"] and rep["problems"] == 2
    assert {x["id"]: x["ok"] for x in rep["extensions"]} == {"bad": False, "good": True}
    assert {x["title"]: x["ok"] for x in rep["checks"]} == {"Raise the limit": True, "Add x": False}
    assert "2 problem(s)" in out and "nothing_here" in smartupdate.fix_prompt(rep)


def test_extension_api_version(code):
    ws = code["ws"]
    d = ws / "extensions" / "future"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"id": "future", "type": "page", "api": extensions.EXT_API + 1}))
    (d / "page.js").write_text("export function mount(el) {}\n")
    e = next(x for x in extensions.scan() if x.id == "future")
    assert e.error and "update Harness Maxxing" in e.error
    # the preflight lists extensions the new version would not load
    src = f"EXT_API = {extensions.EXT_API + 2}\nEXT_API_MIN = {extensions.EXT_API + 1}\n"
    (d / "manifest.json").write_text(json.dumps({"id": "future", "type": "page"}))
    assert [x["id"] for x in smartupdate._extensions_against(src)] == ["future"]
    assert smartupdate._extensions_against("EXT_API = 1\n") == []


def test_after_update_verifies_and_opens_the_notes_session(code, monkeypatch):
    from maxxing.sessions import service
    clone = code["clone"]
    (clone / "docs/upgrade").mkdir(parents=True)
    (clone / "docs/upgrade/1.1.0.md").write_text("# Upgrade notes - 1.1.0\n\nRename the topic x.\n")
    (clone / "docs/upgrade/1.0.5.md").write_text("# Upgrade notes - 1.0.5\n\nNothing to do: UI only.\n")
    made = []
    monkeypatch.setattr(service, "create_session", lambda path, message=None, title=None, **kw:
                        made.append((path, message, title)) or {"id": "s1"})
    smartupdate.mark_updated("1.0.0", "1.1.0", smart=False)              # updated by Claude: no extra session
    assert smartupdate.after_update()["done"] and made == [] and smartupdate.last_report()["ok"]
    assert smartupdate.after_update() is None                            # once per update
    smartupdate.mark_updated("1.0.0", "1.1.0", smart=True)               # the Update button
    smartupdate.after_update()
    assert len(made) == 1 and made[0][0] == "projects/system/topics/harness"
    assert "1.1.0.md" in made[0][1] and "1.0.5.md" not in made[0][1]
    assert smartupdate.after_info()["notes_session"] == "s1"
    config.update_config(update_auto_notes=False)
    smartupdate.mark_updated("1.0.0", "1.1.0", smart=True)
    smartupdate.after_update()
    assert len(made) == 1
