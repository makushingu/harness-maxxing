"""Tests for maxxing.cmd_core (init, doctor, update, status, uninstall).

Everything runs in temp dirs: state, HOME, workspace, crontab file, fake /etc paths. System calls
(systemctl, caddy, crontab, uv) are monkeypatched; git runs for real on temp repositories.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

from maxxing import cli, cmd_core, config, security


@pytest.fixture
def env(tmp_path, monkeypatch):
    state, home, ws, etc = tmp_path / "state", tmp_path / "home", tmp_path / "ws", tmp_path / "etc"
    home.mkdir()
    etc.mkdir()
    monkeypatch.setattr(config, "STATE", state)
    monkeypatch.setenv("MAXXING_STATE", str(state))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MAXXING_CRONTAB_FILE", str(tmp_path / "crontab"))
    for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(cmd_core, "UNIT_PATH", etc / "claude-maxxing.service")
    monkeypatch.setattr(cmd_core, "CADDYFILE", etc / "Caddyfile")
    monkeypatch.setattr(cmd_core, "CADDY_SITE", etc / "claude-maxxing.caddy")
    monkeypatch.setattr(cmd_core, "BIN_LINK", etc / "maxxing")
    monkeypatch.setattr(cmd_core, "JOBS_SLICE_PATH", etc / "maxxing-jobs.slice")
    calls: list[tuple] = []

    def fake_systemctl(*args, timeout=60):
        calls.append(("systemctl", *args))
        return 3, "inactive"

    real_run = cmd_core.run

    def fake_run(cmd, timeout=60, cwd=None, input=None, env=None):
        calls.append(tuple(cmd))
        if cmd[0] == "git":
            return real_run(cmd, timeout=timeout, cwd=cwd, input=input, env=env)
        if cmd[0] == "timedatectl":
            return 0, "Europe/Paris\n"
        return 127, f"{cmd[0]}: not found"

    monkeypatch.setattr(cmd_core, "systemctl", fake_systemctl)
    monkeypatch.setattr(cmd_core, "run", fake_run)
    monkeypatch.setattr(cmd_core, "http_get", lambda url, timeout=6: (0, "connection refused"))
    return {"state": state, "home": home, "ws": ws, "etc": etc, "calls": calls, "tmp": tmp_path}


def run_cli(*argv: str) -> int:
    return cli.main(list(argv))


# ---- init ----------------------------------------------------------------------------------
def test_init_creates_state_config_workspace_skills(env, capsys):
    assert run_cli("init", "--workspace", str(env["ws"]), "--port", "8801") == 0
    st, ws, home = env["state"], env["ws"], env["home"]
    assert (st.stat().st_mode & 0o777) == 0o700
    cfg = json.loads((st / "config.json").read_text())
    assert cfg["workspace"] == str(ws.resolve())
    assert cfg["port"] == 8801 and cfg["bind"] == "127.0.0.1"
    assert cfg["timezone"] == "Europe/Paris"            # detected (fake timedatectl)
    assert cfg["files_root"] == str(ws.resolve())        # workspace outside HOME -> itself
    for rel in ("CLAUDE.md", "memory.md", "tasks.json", "extensions/README.md",
                "projects/general/CLAUDE.md", "projects/general/memory.md",
                "projects/general/topics/inbox/CLAUDE.md", "projects/general/topics/inbox/memory.md"):
        assert (ws / rel).is_file(), rel
    assert json.loads((ws / "tasks.json").read_text()) == {"version": 1, "projects": [], "tasks": []}
    names = cmd_core.product_skill_names()
    assert "memory" in names and "memory-compaction" in names and "maxxing-setup" in names
    for n in names:
        assert (home / ".claude" / "skills" / n / "SKILL.md").is_file()
    assert json.loads((home / ".claude" / "settings.json").read_text())["cleanupPeriodDays"] == 3650
    out = capsys.readouterr().out
    assert "/setup?token=" in out                         # password not set -> setup link
    assert security.ensure_setup_token() in out


def test_init_claude_dir_keeps_home_claude_untouched(env, tmp_path):
    own = tmp_path / "claude-harness"
    assert run_cli("init", "--workspace", str(env["ws"]), "--claude-dir", str(own), "--quiet") == 0
    assert json.loads((env["state"] / "config.json").read_text())["claude_dir"] == str(own.resolve())
    assert config.claude_dir() == own.resolve()
    for n in cmd_core.product_skill_names():
        assert (own / "skills" / n / "SKILL.md").is_file()
    assert json.loads((own / "settings.json").read_text())["cleanupPeriodDays"] == 3650
    assert not (env["home"] / ".claude").exists()       # the Claude Code already used here is left alone
    from maxxing.sessions import spawn
    assert spawn.base_env()["CLAUDE_CONFIG_DIR"] == str(own.resolve())
    assert run_cli("init", "--quiet") == 0               # a later init (update) keeps it
    assert config.claude_dir() == own.resolve()


def test_default_claude_dir_is_home_claude(env):
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0
    assert config.claude_dir() == env["home"] / ".claude"
    from maxxing.sessions import spawn
    assert "CLAUDE_CONFIG_DIR" not in spawn.base_env()


def test_init_is_idempotent_and_never_clobbers(env):
    ws = env["ws"]
    assert run_cli("init", "--workspace", str(ws), "--timezone", "UTC", "--quiet") == 0
    (ws / "memory.md").write_text("# mine\n")
    config.update_config(language="fr")
    settings = env["home"] / ".claude" / "settings.json"
    settings.write_text(json.dumps({"cleanupPeriodDays": 30, "model": "x"}))
    assert run_cli("init", "--quiet") == 0
    assert (ws / "memory.md").read_text() == "# mine\n"
    cfg = config.load_config()
    assert cfg["language"] == "fr" and cfg["timezone"] == "UTC"
    assert json.loads(settings.read_text()) == {"cleanupPeriodDays": 30, "model": "x"}
    # an explicit flag wins
    assert run_cli("init", "--timezone", "Asia/Tokyo", "--public-url", "https://ui.example.com/", "--quiet") == 0
    cfg = config.load_config()
    assert cfg["timezone"] == "Asia/Tokyo" and cfg["public_url"] == "https://ui.example.com"
    assert run_cli("init", "--public-url", "", "--quiet") == 0
    assert config.load_config()["public_url"] == ""


@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "8.8.8.8"])
def test_init_refuses_public_bind(env, bind):
    with pytest.raises(SystemExit):
        run_cli("init", "--workspace", str(env["ws"]), "--bind", bind)


def test_init_accepts_tailscale_bind(env):
    assert run_cli("init", "--workspace", str(env["ws"]), "--bind", "100.101.102.103", "--quiet") == 0
    assert config.load_config()["bind"] == "100.101.102.103"


def test_secret_from_stdin(env, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("tok-123\n"))
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet",
                   "--secret-from-stdin", "github_update_token") == 0
    assert config.get_secret("github_update_token") == "tok-123"
    assert (config.secrets_path().stat().st_mode & 0o777) == 0o600
    monkeypatch.setattr(sys, "stdin", io.StringIO("x"))
    with pytest.raises(SystemExit):
        run_cli("init", "--quiet", "--secret-from-stdin", "password_hash")


def test_skills_manifest_replaces_and_removes(env, tmp_path, monkeypatch):
    target = env["home"] / ".claude" / "skills"
    (target / "memory").mkdir(parents=True)
    (target / "memory" / "SKILL.md").write_text("user's own skill")
    (target / "my-skill").mkdir()
    (target / "my-skill" / "SKILL.md").write_text("keep me")
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0
    assert (target / "memory" / "SKILL.md").read_text() != "user's own skill"
    backups = list((env["state"] / "trash" / "skills").iterdir())
    assert len(backups) == 1 and (backups[0] / "SKILL.md").read_text() == "user's own skill"
    # a product skill disappears from the code -> removed at the next init; user skills stay
    fake_src = tmp_path / "skills-src"
    for n in ("memory", "maxxing-doctor"):
        (fake_src / n).mkdir(parents=True)
        (fake_src / n / "SKILL.md").write_text(f"---\nname: {n}\n---\n")
    monkeypatch.setattr(config, "SKILLS_DIR", fake_src)
    assert run_cli("init", "--quiet") == 0
    assert sorted(p.name for p in target.iterdir()) == ["maxxing-doctor", "memory", "my-skill"]
    assert (target / "my-skill" / "SKILL.md").read_text() == "keep me"
    assert all(s["state"] == "ok" for s in cmd_core.skills_status())



def test_skills_are_rendered_with_the_paths_of_this_install(env):
    """Shipped skills name the real code / workspace / state folders, not the defaults (install audit 4.2)."""
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0
    target = env["home"] / ".claude" / "skills"
    texts = {p.parent.name: p.read_text() for p in target.glob("*/SKILL.md")}
    assert texts
    for name, text in texts.items():
        text = text.replace(str(config.CODE), "<code>")      # a dev checkout may itself live under /root/maxxing
        for default in ("/opt/claude-maxxing", "/root/maxxing", "/var/lib/claude-maxxing", "{{"):
            assert default not in text, (name, default)
    assert f'p = "{env["ws"]}/tasks.json"' in texts["maxxing-tasks"]
    assert f"{env['state']}/crons/jobs.json" in texts["maxxing-cron"]
    assert f"bash {config.CODE}/install.sh" in texts["maxxing-setup"]
    assert all(s["state"] == "ok" for s in cmd_core.skills_status())
    # a stale copy (old defaults) is reported as outdated, and the next init renders it again
    (target / "memory" / "SKILL.md").write_text((config.SKILLS_DIR / "memory" / "SKILL.md").read_text())
    assert {s["name"]: s["state"] for s in cmd_core.skills_status()}["memory"] == "outdated"
    assert run_cli("init", "--quiet") == 0
    assert all(s["state"] == "ok" for s in cmd_core.skills_status())


def test_shipped_skills_use_placeholders_not_default_paths():
    for f in sorted(config.SKILLS_DIR.glob("*/SKILL.md")):
        text = f.read_text()
        for default in ("/opt/claude-maxxing", "/root/maxxing", "/var/lib/claude-maxxing"):
            assert default not in text, (f.parent.name, default)

def test_init_creates_default_compaction_job_once(env):
    crons = pytest.importorskip("maxxing.crons")
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0
    jobs = crons.list_jobs()
    assert [j["name"] for j in jobs] == ["Memory compaction", "Check for updates", "Morning tasks",
                                         "Clean caches and old versions", "Check dependencies for vulnerabilities"]
    j = jobs[0]
    assert j["kind"] == "claude" and not j["enabled"] and j["schedule"] == "0 5 * * *"   # off until Claude signs in
    assert "memory-compaction" in j["prompt"]
    assert f"cron run {j['id']}" not in (env["tmp"] / "crontab").read_text()
    assert cmd_core.enable_pending_jobs() == [j["id"]]          # end of the onboarding, Claude signed in
    assert crons.get_job(j["id"])["enabled"] and f"cron run {j['id']}" in (env["tmp"] / "crontab").read_text()
    crons.update_job(j["id"], {"enabled": False})               # the user turns it off: never turned back on
    assert run_cli("init", "--quiet") == 0
    assert cmd_core.enable_pending_jobs() == [] and not crons.get_job(j["id"])["enabled"]
    crons.delete_job(j["id"])                       # the user deletes it -> never recreated
    assert run_cli("init", "--quiet") == 0
    assert "Memory compaction" not in [x["name"] for x in crons.list_jobs()]


# ---- doctor --------------------------------------------------------------------------------
def test_doctor_json(env, capsys):
    run_cli("init", "--workspace", str(env["ws"]), "--quiet")
    capsys.readouterr()
    code = run_cli("doctor", "--json", "--offline")
    data = json.loads(capsys.readouterr().out)
    ids = {c["id"]: c for c in data["checks"]}
    assert code == 1 and data["ok"] is False                 # server not answering, no claude auth
    assert ids["http"]["level"] == "fail"
    assert ids["claude_auth"]["level"] == "fail" and "setup-token" in ids["claude_auth"]["fix"]
    assert ids["workspace"]["level"] == "ok"
    assert ids["skills"]["level"] == "ok"
    assert ids["setup"]["level"] == "warn"
    assert ids["python"]["level"] == "ok"
    for c in data["checks"]:
        assert set(c) == {"id", "level", "title", "detail", "fix"}
        assert c["level"] in ("ok", "warn", "fail", "info")


def test_doctor_human_output_and_auth(env, capsys, monkeypatch):
    run_cli("init", "--workspace", str(env["ws"]), "--quiet")
    config.set_secret("claude_oauth_token", "x")
    monkeypatch.setattr(cmd_core, "http_get",
                        lambda url, timeout=6: (200, json.dumps({"version": "2.0.0a1"})))
    capsys.readouterr()
    run_cli("doctor", "--offline")
    out = capsys.readouterr().out
    assert "Claude auth: oauth_token" in out
    assert "server answers" in out


def test_public_bind_detection():
    assert cmd_core._is_public_bind("0.0.0.0")
    assert cmd_core._is_public_bind("::")
    assert cmd_core._is_public_bind("8.8.8.8") is True
    assert not cmd_core._is_public_bind("127.0.0.1")
    assert not cmd_core._is_public_bind("100.64.1.2")       # Tailscale range
    assert not cmd_core._is_public_bind("10.0.0.5")


def test_check_bind_fails_on_wildcard(env):
    c = cmd_core.check_bind({"bind": "0.0.0.0", "port": 8787})
    assert c["level"] == "fail"


def test_crontab_check(env):
    crons = pytest.importorskip("maxxing.crons")
    run_cli("init", "--workspace", str(env["ws"]), "--quiet")
    assert cmd_core.check_crontab()["level"] == "ok"
    (env["tmp"] / "crontab").write_text("")
    c = cmd_core.check_crontab()
    assert c["level"] == "warn" and c["fix"] == "maxxing cron sync"
    assert crons  # noqa


# ---- status --------------------------------------------------------------------------------
def test_status_json(env, capsys):
    run_cli("init", "--workspace", str(env["ws"]), "--quiet")
    capsys.readouterr()
    assert run_cli("status", "--json") == 0
    s = json.loads(capsys.readouterr().out)
    assert s["service"] == "inactive" and s["password_set"] is False
    assert s["workspace"] == str(env["ws"].resolve())
    assert s["backup"]["repo"] == ""


# ---- uninstall -----------------------------------------------------------------------------
def test_uninstall_removes_integrations_keeps_workspace(env, capsys):
    run_cli("init", "--workspace", str(env["ws"]), "--quiet")
    etc = env["etc"]
    cmd_core.UNIT_PATH.write_text("[Unit]\n")
    cmd_core.CADDY_SITE.write_text("ui.example.com {\n}\n")
    cmd_core.CADDYFILE.write_text(f"other.example.com {{\n}}\n\nimport {cmd_core.CADDY_SITE}\n")
    cmd_core.BIN_LINK.symlink_to("/nonexistent/.venv/bin/maxxing")
    (env["tmp"] / "crontab").write_text(
        "MAILTO=\"\"\n0 1 * * * /usr/bin/true\n\n# >>> claude-maxxing (managed) >>>\n"
        "0 5 * * * /usr/local/bin/maxxing cron run c_abc123 >/dev/null 2>&1\n# <<< claude-maxxing <<<\n")
    assert run_cli("uninstall", "--yes") == 0
    assert not cmd_core.UNIT_PATH.exists() and not cmd_core.CADDY_SITE.exists()
    assert cmd_core.CADDYFILE.read_text() == "other.example.com {\n}\n"
    assert not cmd_core.BIN_LINK.is_symlink()
    assert (env["tmp"] / "crontab").read_text() == 'MAILTO=""\n0 1 * * * /usr/bin/true\n'
    assert not (env["home"] / ".claude" / "skills" / "memory").exists()
    assert (env["ws"] / "CLAUDE.md").exists() and env["state"].exists()
    assert ("systemctl", "disable", "--now", "claude-maxxing") in env["calls"]
    assert etc.exists()


def test_uninstall_purge(env, tmp_path, monkeypatch):
    run_cli("init", "--workspace", str(env["ws"]), "--quiet")
    code = tmp_path / "opt" / "claude-maxxing"
    (code / "server" / "maxxing").mkdir(parents=True)
    (code / "install.sh").write_text("#!/bin/bash\n")
    monkeypatch.setattr(config, "CODE", code)
    assert run_cli("uninstall", "--yes", "--purge") == 0
    assert not code.exists() and not env["state"].exists()
    assert env["ws"].exists()


def test_uninstall_purge_refuses_non_install_dir(env, tmp_path, monkeypatch):
    run_cli("init", "--workspace", str(env["ws"]), "--quiet")
    code = tmp_path / "random"
    code.mkdir()
    monkeypatch.setattr(config, "CODE", code)
    assert run_cli("uninstall", "--yes", "--purge", "--purge-workspace") == 0
    assert code.exists() and not env["ws"].exists()


def test_uninstall_aborts_without_confirmation(env, monkeypatch):
    monkeypatch.setattr(cmd_core, "_confirm", lambda q, y: y)
    cmd_core.UNIT_PATH.write_text("[Unit]\n")
    assert run_cli("uninstall") == 1
    assert cmd_core.UNIT_PATH.exists()


# ---- update --------------------------------------------------------------------------------
def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})


@pytest.fixture
def repos(tmp_path):
    origin, work, clone = tmp_path / "origin.git", tmp_path / "work", tmp_path / "clone"
    _git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    _git("clone", "-q", str(origin), str(work), cwd=tmp_path)
    _git("checkout", "-q", "-b", "main", cwd=work)
    (work / "CHANGELOG.md").write_text("# Changelog\n\n## 1.0.0\n- first\n")
    (work / "server").mkdir()
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "v1", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    _git("clone", "-q", "-b", "main", str(origin), str(clone), cwd=tmp_path)
    return {"origin": origin, "work": work, "clone": clone}


def test_update_fast_forwards_syncs_and_prints_changelog(env, repos, monkeypatch, capsys):
    work, clone = repos["work"], repos["clone"]
    (work / "CHANGELOG.md").write_text("# Changelog\n\n## 1.1.0\n- shiny feature\n\n## 1.0.0\n- first\n")
    _git("commit", "-q", "-am", "v1.1", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    monkeypatch.setattr(config, "CODE", clone)
    monkeypatch.setattr(cmd_core, "uv_bin", lambda: "/fake/uv")
    seen = []
    real = cmd_core.run

    def fake(cmd, **kw):
        seen.append(cmd)
        if cmd[0] == "git":
            return real(cmd, **kw)
        return 0, ""
    monkeypatch.setattr(cmd_core, "run", fake)
    cmd_core.UNIT_PATH.write_text("[Unit]\n")
    restarted = []
    monkeypatch.setattr(cmd_core, "systemctl", lambda *a, timeout=60: (restarted.append(a), (0, "ok"))[1])
    monkeypatch.setattr(cmd_core, "_healthy", lambda version, wait=45: True)
    assert run_cli("update") == 0
    out = capsys.readouterr().out
    assert "shiny feature" in out and "## 1.1.0" in out
    assert (clone / "CHANGELOG.md").read_text().startswith("# Changelog\n\n## 1.1.0")
    assert ["/fake/uv", "sync", "--frozen", "--no-dev", "--quiet"] in seen
    assert any(c[:4] == [sys.executable, "-m", "maxxing", "init"] for c in seen)
    assert ("restart", "claude-maxxing") in restarted


def test_update_carries_a_local_commit_over(env, repos, monkeypatch, capsys):
    """A local commit in the code directory is a customization: rebased, never blocking the update."""
    work, clone = repos["work"], repos["clone"]
    (work / "a.txt").write_text("remote")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "remote", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    (clone / "b.txt").write_text("local")
    _git("add", "-A", cwd=clone)
    _git("commit", "-q", "-m", "local", cwd=clone)
    monkeypatch.setattr(config, "CODE", clone)
    monkeypatch.setattr(cmd_core, "uv_bin", lambda: "/fake/uv")
    real = cmd_core.run
    monkeypatch.setattr(cmd_core, "run", lambda cmd, **kw: real(cmd, **kw) if cmd[0] == "git" else (0, ""))
    assert run_cli("update") == 0
    assert "1 customization(s) carried over" in capsys.readouterr().out
    assert (clone / "a.txt").exists() and (clone / "b.txt").exists()


def test_update_uses_token_header_without_storing_it(env, repos, monkeypatch):
    monkeypatch.setattr(config, "CODE", repos["clone"])
    config.set_secret("github_update_token", "secret-tok")
    seen = []
    real = cmd_core.run

    def fake(cmd, **kw):
        seen.append((cmd, kw.get("env") or {}))
        return real(cmd, **kw) if cmd[0] == "git" else (0, "")
    monkeypatch.setattr(cmd_core, "run", fake)
    assert run_cli("update", "--check") == 0
    fetch, env = next(c for c in seen if "fetch" in c[0])
    assert env.get("GIT_CONFIG_VALUE_0") == cmd_core.auth_header("secret-tok")
    assert not any("secret-tok" in a or "Authorization" in a for a in fetch)   # never in the command line
    assert "secret-tok" not in (repos["clone"] / ".git" / "config").read_text()


def test_doctor_git_reports_behind(env, repos, monkeypatch):
    monkeypatch.setattr(config, "CODE", repos["clone"])
    work = repos["work"]
    (work / "c.txt").write_text("x")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "new", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    c = cmd_core.check_git(fetch=True)
    assert c["level"] == "warn" and "1 update" in c["title"]


def test_timezone_check(env):
    run_cli("init", "--workspace", str(env["ws"]), "--quiet")    # default = system zone (fake: Europe/Paris)
    assert cmd_core.check_timezone(config.load_config())["level"] == "ok"
    run_cli("init", "--timezone", "Asia/Tokyo", "--quiet")
    c = cmd_core.check_timezone(config.load_config())
    assert c["level"] == "warn" and "timedatectl set-timezone Asia/Tokyo" in c["fix"]


# ---- default projects (templates) -----------------------------------------------------------
SYSTEM_TOPICS = ("tutorial", "help", "harness")


def test_init_creates_default_projects_rendered(env):
    from maxxing import workspace
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0
    ws = env["ws"]
    for t in SYSTEM_TOPICS:
        for f in ("CLAUDE.md", "memory.md"):
            assert (ws / "projects/system/topics" / t / f).is_file(), (t, f)
    assert sorted(p.name for p in (ws / "projects/system/topics").iterdir()) == sorted(SYSTEM_TOPICS)
    assert not (ws / "projects/tutorial").exists()
    assert sorted(p.name for p in (ws / "projects").iterdir()) == ["general", "system"]
    assert (ws / "projects/general/topics/inbox/CLAUDE.md").is_file()
    # placeholders rendered everywhere
    for f in ws.rglob("*.md"):
        assert "{{" not in f.read_text(), f
    help_md = (ws / "projects/system/topics/help/CLAUDE.md").read_text()
    assert f"{config.CODE}/docs/user/" in help_md
    assert f"Last applied upgrade notes\n{cmd_core.__version__}" in \
        (ws / "projects/system/topics/harness/memory.md").read_text()
    assert str(ws.resolve()) in (ws / "projects/general/topics/inbox/CLAUDE.md").read_text()   # tasks.json path
    # the UI sees them as projects/topics with a description
    topics = {t["path"]: t for t in workspace.list_topics()}
    assert "projects/system/topics/help" in topics and "projects/system/topics/tutorial" in topics
    assert topics["projects/system/topics/help"]["description"].startswith("Ask anything")
    assert cmd_core.update_topic() == "system/harness"
    # the docs referenced by the help topic exist
    for name in ("08-crons.md", "17-cli-reference.md", "19-system-project.md"):
        assert (config.DOCS_DIR / name).is_file()


def test_init_never_overwrites_nor_recreates_deleted_defaults(env):
    import shutil
    ws = env["ws"]
    assert run_cli("init", "--workspace", str(ws), "--quiet") == 0
    mine = ws / "projects/system/topics/help/CLAUDE.md"
    mine.write_text("# Topic help\n\nmine\n")
    shutil.rmtree(ws / "projects/system/topics/tutorial")       # done with the tutorial
    (ws / "projects/system/topics/harness/memory.md").unlink()  # a single missing file: restored
    assert run_cli("init", "--quiet") == 0
    assert mine.read_text() == "# Topic help\n\nmine\n"
    assert not (ws / "projects/system/topics/tutorial").exists()
    assert (ws / "projects/system/topics/harness/memory.md").is_file()


def test_workspace_from_before_2_0_0a33_keeps_its_layout(env):
    """An older workspace (system/update, server, tasks... and the tutorial project) gets no system/tutorial nor
    system/harness next to its topics; the update topic stays system/update."""
    ws = env["ws"]
    for t in ("update", "server", "tasks", "accounts", "extensions", "help"):
        (ws / "projects/system/topics" / t).mkdir(parents=True)
        (ws / "projects/system/topics" / t / "CLAUDE.md").write_text(f"# Topic {t}\n\nold\n")
    (ws / "projects/tutorial/topics/1-first-steps").mkdir(parents=True)
    config.write_json(config.STATE / "install.json", {"version": "2.0.0a32", "initialized": 1.0})
    assert run_cli("init", "--workspace", str(ws), "--quiet") == 0
    assert not (ws / "projects/system/topics/tutorial").exists()
    assert not (ws / "projects/system/topics/harness").exists()
    assert (ws / "projects/system/topics/help/CLAUDE.md").read_text() == "# Topic help\n\nold\n"
    assert cmd_core.update_topic() == "system/update"
    assert run_cli("init", "--quiet") == 0                         # still nothing new on a second run
    assert not (ws / "projects/system/topics/harness").exists()


def test_init_upgrade_from_previous_version_adds_new_projects(env):
    """An install made before the default projects existed: general deleted by the user stays gone,
    the new projects and jobs appear."""
    crons = pytest.importorskip("maxxing.crons")
    ws = env["ws"]
    ws.mkdir()
    (ws / "CLAUDE.md").write_text("# Workspace\n")
    config.write_json(config.STATE / "install.json",
                      {"version": "2.0.0a1", "initialized": 1.0, "default_crons": ["memory-compaction"]})
    assert run_cli("init", "--workspace", str(ws), "--quiet") == 0
    assert (ws / "CLAUDE.md").read_text() == "# Workspace\n"
    assert not (ws / "projects/general").exists()
    assert (ws / "projects/system/topics/harness/CLAUDE.md").is_file()
    assert (ws / "projects/system/topics/tutorial/CLAUDE.md").is_file()
    names = [j["name"] for j in crons.list_jobs()]
    assert names == ["Check for updates", "Clean caches and old versions",   # Morning tasks lives in general/inbox,
                     "Check dependencies for vulnerabilities"]              # deleted here


def test_default_jobs_definitions(env, monkeypatch):
    crons = pytest.importorskip("maxxing.crons")
    monkeypatch.setattr(cmd_core, "update_source", lambda: "git")   # a sandbox may hide the checkout's .git
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0
    jobs = {j["name"]: j for j in crons.list_jobs()}
    up = jobs["Check for updates"]
    assert up["kind"] == "shell" and up["enabled"] and up["schedule"] == "0 9 * * 1"
    assert up["command"].endswith("update --check --notify")
    mt = jobs["Morning tasks"]
    assert mt["kind"] == "claude" and not mt["enabled"] and mt["schedule"] == "0 8 * * *"
    assert mt["topic_path"] == "projects/general/topics/inbox" and mt["notify"] == "always"
    assert "Renewal reminder" not in jobs
    tab = (env["tmp"] / "crontab").read_text()
    assert f"cron run {up['id']}" in tab and f"cron run {mt['id']}" not in tab   # disabled -> no line
    assert run_cli("init", "--quiet") == 0                                         # idempotent
    assert len(crons.list_jobs()) == 5
    crons.delete_job(up["id"])
    assert run_cli("init", "--quiet") == 0
    assert "Check for updates" not in [j["name"] for j in crons.list_jobs()]


def test_init_no_crons_flag(env):
    crons = pytest.importorskip("maxxing.crons")
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet", "--no-crons") == 0
    assert crons.list_jobs() == []


# ---- update --check / --notify -------------------------------------------------------------
def _release(work, version, note):
    (work / "server" / "maxxing").mkdir(parents=True, exist_ok=True)
    (work / "server" / "maxxing" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    cl = (work / "CHANGELOG.md").read_text().replace("# Changelog\n\n", f"# Changelog\n\n## {version}\n- {note}\n\n", 1)
    (work / "CHANGELOG.md").write_text(cl)
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", version, cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)


@pytest.fixture
def released(repos, monkeypatch):
    work, clone = repos["work"], repos["clone"]
    _release(work, "1.0.1", "patch")
    _git("pull", "-q", "origin", "main", cwd=clone)
    monkeypatch.setattr(config, "CODE", clone)
    return repos


def test_update_check_reports_versions_and_changelog_without_changing(env, released, capsys):
    clone = released["clone"]
    assert run_cli("update", "--check") == 0
    assert "up to date" in capsys.readouterr().out
    _release(released["work"], "1.2.0", "shiny feature")
    _release(released["work"], "1.3.0a1", "even shinier")
    head = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    assert run_cli("update", "--check") == 0
    out = capsys.readouterr().out
    assert "1.0.1" in out and "1.3.0a1" in out and "2 new commit" in out
    assert "shiny feature" in out and "even shinier" in out and "- patch" not in out
    assert subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout == head                     # nothing changed
    assert run_cli("update", "--check", "--json") == 0
    info = json.loads(capsys.readouterr().out)
    assert info["ok"] and info["available"] and info["current"] == "1.0.1" and info["latest"] == "1.3.0a1"
    assert info["behind"] == 2 and any("shiny feature" in ln for ln in info["changelog"])


def test_compaction_job_waits_for_claude_and_upgrades_keep_theirs(env, monkeypatch):
    """Audit 2 2.9: no daily failure before Claude is signed in; an existing install keeps its enabled job."""
    crons = pytest.importorskip("maxxing.crons")
    from maxxing.api import onboarding
    config.STATE.mkdir(parents=True, exist_ok=True)
    config.write_json(config.STATE / "install.json", {"version": "2.0.0a60", "initialized": 1.0,
                                                      "default_crons": ["memory-compaction"]})
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0
    old = crons.create_job({**cmd_core.COMPACTION_JOB, "enabled": True})          # made by an older version
    assert run_cli("init", "--quiet") == 0                                          # the update
    assert crons.get_job(old["id"])["enabled"] and cmd_core.enable_pending_jobs() == []
    crons.delete_job(old["id"])
    config.write_json(config.STATE / "install.json", {})                           # a fresh install
    assert run_cli("init", "--quiet") == 0
    new = [j for j in crons.list_jobs() if j["name"] == "Memory compaction"][0]
    assert not new["enabled"]
    import asyncio
    monkeypatch.setattr(onboarding, "auth_status", lambda: {"ok": False})
    assert asyncio.run(onboarding.complete())["jobs_enabled"] == []                 # Claude not signed in: stays off
    assert not crons.get_job(new["id"])["enabled"]
    monkeypatch.setattr(onboarding, "auth_status", lambda: {"ok": True})
    assert asyncio.run(onboarding.complete())["jobs_enabled"] == [new["id"]]
    assert crons.get_job(new["id"])["enabled"]


def test_no_license_no_remote_means_no_failing_update_job(env, tmp_path, monkeypatch, capsys):
    """Audit 2 1.2: a clone without `origin` and without a license: the weekly check is created off and
    `maxxing update --check` says updates are unavailable (exit 0) instead of failing every week."""
    crons = pytest.importorskip("maxxing.crons")
    code = tmp_path / "code"
    code.mkdir()
    _git("init", "-q", cwd=code)
    monkeypatch.setattr(config, "CODE", code)
    assert cmd_core.update_source() is None
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0
    up = [j for j in crons.list_jobs() if j["name"] == "Check for updates"][0]
    assert not up["enabled"]
    capsys.readouterr()
    assert run_cli("update", "--check") == 0
    assert "updates unavailable (no git remote)" in capsys.readouterr().out
    _git("remote", "add", "origin", str(tmp_path / "somewhere.git"), cwd=code)
    assert cmd_core.update_source() == "git"


def test_update_check_fails_only_on_error(env, released, capsys):
    _git("remote", "set-url", "origin", str(env["tmp"] / "nowhere.git"), cwd=released["clone"])
    assert run_cli("update", "--check") == 1
    assert "cannot check" in capsys.readouterr().out


def test_update_check_notify(env, released, monkeypatch, capsys):
    import types
    sent = []
    gw = types.ModuleType("maxxing.telegram.gateway")
    gw.notify_cron = sent.append
    monkeypatch.setitem(sys.modules, "maxxing.telegram.gateway", gw)
    import maxxing.telegram as tpkg
    monkeypatch.setattr(tpkg, "gateway", gw, raising=False)
    config.update_config(public_url="https://ui.example.com")
    assert run_cli("update", "--check", "--notify") == 0
    assert sent == []                                                     # up to date: silent
    _release(released["work"], "1.1.0", "new things")
    assert run_cli("update", "--check", "--notify") == 0
    assert len(sent) == 1
    assert "1.1.0" in sent[0] and "1.0.1" in sent[0] and "system/harness" in sent[0]
    assert "https://ui.example.com" in sent[0]
    assert "Telegram notified" in capsys.readouterr().out
    # a broken notifier never fails the check
    gw.notify_cron = lambda text: (_ for _ in ()).throw(RuntimeError("down"))
    assert run_cli("update", "--check", "--notify") == 0


def test_update_check_not_a_git_clone(env, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "CODE", tmp_path / "plain")
    (tmp_path / "plain").mkdir()
    assert run_cli("update", "--check", "--notify") == 0
    assert "not a git clone" in capsys.readouterr().out


def test_update_lists_upgrade_notes(env, released, monkeypatch, capsys):
    work, clone = released["work"], released["clone"]
    monkeypatch.setattr(cmd_core, "__version__", "1.0.1")
    (work / "docs" / "upgrade").mkdir(parents=True)
    for v in ("1.0.1", "1.1.0", "1.2.0a1", "9.0.0"):
        (work / "docs" / "upgrade" / f"{v}.md").write_text(f"# Upgrade notes {v}\n")
    (work / "docs" / "upgrade" / "README.md").write_text("format\n")
    _release(work, "1.2.0", "x")
    monkeypatch.setattr(cmd_core, "uv_bin", lambda: "/fake/uv")
    real = cmd_core.run
    monkeypatch.setattr(cmd_core, "run", lambda cmd, **kw: real(cmd, **kw) if cmd[0] == "git" else (0, ""))
    assert run_cli("update", "--no-restart") == 0
    out = capsys.readouterr().out
    i, j = out.index("1.1.0.md"), out.index("1.2.0a1.md")
    assert i < j and "1.0.1.md" not in out and "9.0.0.md" not in out and "README" not in out


def test_version_key_and_upgrade_notes(tmp_path):
    k = cmd_core.version_key
    assert k("2.0.0a1") < k("2.0.0a2") < k("2.0.0-beta.1") < k("2.0.0rc1") < k("2.0.0") < k("2.0.1")
    assert k("2.0.0-alpha.2") == k("2.0.0a2") and k("README") is None
    d = tmp_path / "docs" / "upgrade"
    d.mkdir(parents=True)
    for v in ("2.0.0a2", "2.0.0", "2.1.0"):
        (d / f"{v}.md").write_text("x")
    assert [p.stem for p in cmd_core.upgrade_notes("2.0.0a1", "2.0.0", tmp_path)] == ["2.0.0a2", "2.0.0"]
    assert cmd_core.upgrade_notes("2.1.0", "2.1.0", tmp_path) == []


def test_shipped_upgrade_notes_are_well_named():
    d = config.CODE / "docs" / "upgrade"
    assert (d / "README.md").is_file()
    notes = [p for p in d.glob("*.md") if p.name != "README.md"]
    assert notes and all(cmd_core.version_key(p.stem) for p in notes)
    assert any(p.stem == cmd_core.__version__ for p in notes)


def test_public_url_behind_cloudflare_is_a_warning(monkeypatch):
    from maxxing import cmd_core
    monkeypatch.setattr(cmd_core, "http_get", lambda url, timeout=6: (200, '{"version":"x"}'))
    monkeypatch.setattr(cmd_core, "http_headers", lambda url, timeout=6: {"server": "cloudflare", "cf-ray": "1"})
    c = cmd_core.check_public_url({"public_url": "https://ui.example.com"})
    assert c["level"] == cmd_core.WARN and "Cloudflare" in c["title"]
    monkeypatch.setattr(cmd_core, "http_headers", lambda url, timeout=6: {"server": "Caddy"})
    assert cmd_core.check_public_url({"public_url": "https://ui.example.com"})["level"] == cmd_core.OK


# ---- harden (systemd sandboxing drop-in) ---------------------------------------------------
def test_harden_writes_dropin_and_undo(env, monkeypatch, capsys):
    cmd_core.UNIT_PATH.write_text("[Service]\nExecStart=/bin/true\n")
    monkeypatch.setattr(cmd_core, "systemctl", lambda *a, timeout=60: (env["calls"].append(("systemctl", *a)), (0, ""))[1])
    monkeypatch.setattr(cmd_core, "_healthy", lambda version, wait=45: True)
    drop = cmd_core.hardening_path()
    assert drop == env["etc"] / "claude-maxxing.service.d" / "10-hardening.conf"
    assert cmd_core.check_hardening()["level"] == cmd_core.INFO
    assert run_cli("harden") == 0
    assert drop.read_text() == cmd_core.HARDENING
    assert ("systemctl", "daemon-reload") in env["calls"] and ("systemctl", "restart", "claude-maxxing") in env["calls"]
    assert cmd_core.check_hardening()["level"] == cmd_core.OK
    env["calls"].clear()
    assert run_cli("harden") == 0 and env["calls"] == []          # already applied: no restart
    assert run_cli("harden", "--undo", "--no-restart") == 0
    assert not drop.exists() and ("systemctl", "restart", "claude-maxxing") not in env["calls"]


def test_harden_rolls_back_when_service_does_not_answer(env, monkeypatch):
    cmd_core.UNIT_PATH.write_text("[Service]\nExecStart=/bin/true\n")
    monkeypatch.setattr(cmd_core, "systemctl", lambda *a, timeout=60: (0, ""))
    monkeypatch.setattr(cmd_core, "_healthy", lambda version, wait=45: False)
    assert run_cli("harden") == 1
    assert not cmd_core.hardening_path().exists()


def test_harden_without_service(env):
    assert run_cli("harden") == 1
    assert cmd_core.check_hardening() is None


def test_hardening_is_safe_and_matches_installer():
    import re
    from pathlib import Path
    text = cmd_core.HARDENING
    for banned in ("ProtectSystem", "ProtectHome", "PrivateTmp", "RestrictNamespaces", "MemoryDenyWriteExecute",
                   "UMask", "User=", "DynamicUser"):
        assert banned not in text, banned
    install = (Path(__file__).resolve().parents[2] / "install.sh").read_text()
    m = re.search(r"10-hardening.conf\"\)? <<'EOF'\n(.*?)EOF\n", install, re.S)
    assert m and m.group(1) == text


def test_doctor_telegram_linked_without_owner(env):
    config.set_secret("telegram_token", "123:abc")
    cfg = config.load_config()
    cfg["telegram"] = {**cfg["telegram"], "chat_id": 42, "user_ids": []}
    c = cmd_core.check_telegram(cfg)
    assert c["level"] == cmd_core.WARN and "owner" in c["title"]
    cfg["telegram"]["user_ids"] = [42]
    assert "owner" not in cmd_core.check_telegram(cfg)["title"]


# ---- update_verify_signature -----------------------------------------------------------------
def _signed_update_env(env, repos, monkeypatch, verify_commit: int, tag_ok: bool = False):
    work, clone = repos["work"], repos["clone"]
    (work / "CHANGELOG.md").write_text("# Changelog\n\n## 1.1.0\n- signed?\n\n## 1.0.0\n- first\n")
    _git("commit", "-q", "-am", "v1.1", cwd=work)
    if tag_ok:
        _git("tag", "v1.1", cwd=work)
        _git("push", "-q", "origin", "v1.1", cwd=work)
    _git("push", "-q", "origin", "main", cwd=work)
    monkeypatch.setattr(config, "CODE", clone)
    monkeypatch.setattr(cmd_core, "uv_bin", lambda: "/fake/uv")
    seen = []
    real = cmd_core.run

    def fake(cmd, **kw):
        seen.append(cmd)
        if cmd[0] == "git" and "verify-commit" in cmd:
            return verify_commit, "" if verify_commit == 0 else "error: no signature found\n"
        if cmd[0] == "git" and "verify-tag" in cmd:
            return (0, "Good signature") if tag_ok else (1, "error: no signature found\n")
        if cmd[0] == "git":
            if "fetch" in cmd and tag_ok:
                kw2 = dict(kw)
                code, out = real(cmd, **kw2)
                real(["git", "-C", str(clone), "fetch", "-q", "--tags", "origin"], **kw2)
                return code, out
            return real(cmd, **kw)
        return 0, ""
    monkeypatch.setattr(cmd_core, "run", fake)
    monkeypatch.setattr(cmd_core, "systemctl", lambda *a, timeout=60: (0, "ok"))
    monkeypatch.setattr(cmd_core, "_healthy", lambda version, wait=45: True)
    cmd_core.UNIT_PATH.write_text("[Unit]\n")
    return clone, seen


def test_update_signature_off_by_default(env, repos, monkeypatch):
    clone, seen = _signed_update_env(env, repos, monkeypatch, verify_commit=1)
    assert run_cli("update") == 0
    assert not any("verify-commit" in c for c in seen)
    assert "signed?" in (clone / "CHANGELOG.md").read_text()


def test_update_signature_required_stops_unsigned(env, repos, monkeypatch, capsys):
    config.update_config(update_verify_signature=True)
    clone, seen = _signed_update_env(env, repos, monkeypatch, verify_commit=1)
    before = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    assert run_cli("update") == 1
    out = capsys.readouterr().out
    assert "no valid signature" in out and "nothing changed" in out
    assert subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True).stdout == before
    assert "signed?" not in (clone / "CHANGELOG.md").read_text()
    assert not any(c[:2] == ["/fake/uv", "sync"] for c in seen)


def test_update_signature_good_commit_or_tag(env, repos, monkeypatch, capsys):
    config.update_config(update_verify_signature=True)
    clone, _ = _signed_update_env(env, repos, monkeypatch, verify_commit=0)
    assert run_cli("update") == 0
    assert "signature verified" in capsys.readouterr().out
    assert "signed?" in (clone / "CHANGELOG.md").read_text()


def test_update_signature_signed_tag_is_enough(env, repos, monkeypatch, capsys):
    config.update_config(update_verify_signature=True)
    clone, _ = _signed_update_env(env, repos, monkeypatch, verify_commit=1, tag_ok=True)
    assert run_cli("update") == 0
    assert "tag v1.1 signature verified" in capsys.readouterr().out


def test_doctor_update_signature(env, repos, monkeypatch):
    monkeypatch.setattr(config, "CODE", repos["clone"])
    assert cmd_core.check_update_signature() is None
    config.update_config(update_verify_signature=True)
    real = cmd_core.run
    monkeypatch.setattr(cmd_core, "run", lambda cmd, **kw: (1, "no signature") if "verify-commit" in cmd else real(cmd, **kw))
    assert cmd_core.check_update_signature()["level"] == cmd_core.WARN
    monkeypatch.setattr(cmd_core, "run", lambda cmd, **kw: (0, "") if "verify-commit" in cmd else real(cmd, **kw))
    assert cmd_core.check_update_signature()["level"] == cmd_core.OK


def test_light_commands_do_not_load_the_web_stack(tmp_path):
    """`maxxing`, `--help`, `cron list`, `status`... start fast: no FastAPI import, and only the command
    being run builds its options."""
    import subprocess
    import sys as _sys
    from pathlib import Path as _Path
    code = ("import sys\nfrom maxxing import cli\n"
            "try:\n    cli.main(sys.argv[1:])\nexcept SystemExit:\n    pass\n"
            "print('LOADED', 'fastapi' in sys.modules, 'maxxing.feed' in sys.modules)")
    env = {"PATH": "/usr/bin:/bin", "MAXXING_STATE": str(tmp_path / "state"), "HOME": str(tmp_path),
           "PYTHONPATH": str(_Path(__file__).resolve().parent.parent), "MAXXING_CRONTAB_FILE": str(tmp_path / "ct")}
    for argv in (["--help"], ["cron", "list"]):
        r = subprocess.run([_sys.executable, "-c", code, *argv], capture_output=True, text=True, env=env, timeout=60)
        assert "LOADED False False" in r.stdout, (argv, r.stdout[-300:], r.stderr[-300:])
    r = subprocess.run([_sys.executable, "-c", code, "feed", "--help"], capture_output=True, text=True, env=env, timeout=60)
    assert "post" in r.stdout and "read-all" in r.stdout


def test_python_floor_is_3_11(monkeypatch):
    """Audit F14: tomllib (depcheck, claude_update) exists from Python 3.11, so 3.10 is refused by the package metadata
    and failed by doctor instead of losing routes at import."""
    import tomllib
    from pathlib import Path
    from types import SimpleNamespace
    root = Path(__file__).resolve().parents[1]
    assert tomllib.loads((root / "pyproject.toml").read_text())["project"]["requires-python"] == ">=3.11"
    assert tomllib.loads((root / "uv.lock").read_text())["requires-python"] == ">=3.11"
    V = type("V", (tuple,), {"major": property(lambda s: s[0]), "minor": property(lambda s: s[1]),
                             "micro": property(lambda s: s[2])})
    for version, level in (((3, 10, 14), cmd_core.FAIL), ((3, 11, 0), cmd_core.OK)):
        monkeypatch.setattr(cmd_core, "sys", SimpleNamespace(version_info=V(version), executable=sys.executable))
        assert cmd_core.check_python()["level"] == level


def test_old_service_units_get_a_memory_cap(env, monkeypatch):
    """F01: the web service written by an older installer has no MemoryMax: init (= every update) adds a drop-in."""
    monkeypatch.delenv("MAXXING_SPAWN", raising=False)
    monkeypatch.setattr(cmd_core, "SYSTEMD_DIR", env["etc"])
    cmd_core.UNIT_PATH.write_text("[Service]\nExecStart=/usr/local/bin/maxxing serve\n")
    assert cmd_core.ensure_service_memory() == "written"
    assert "MemoryMax=60%" in cmd_core.service_memory_path().read_text()
    assert cmd_core.ensure_service_memory() == "unchanged"
    cmd_core.UNIT_PATH.write_text("[Service]\nMemoryMax=4800M\n")
    assert cmd_core.ensure_service_memory() == "in the unit"


# ---- adapted at integration (2.0.0a70): no silent change on installs that existed before ------------------------
def test_new_weekly_jobs_arrive_off_on_an_existing_install(env):
    crons = pytest.importorskip("maxxing.crons")
    cmd_core._save_install_state(default_crons=["check-updates", "memory-compaction", "morning-tasks"])
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0
    jobs = {j["name"]: j for j in crons.list_jobs()}
    assert not jobs["Clean caches and old versions"]["enabled"]
    assert not jobs["Check dependencies for vulnerabilities"]["enabled"]
    assert config.load_config()["cron_keep_background"] is True       # their background programs keep living
    assert config.load_config()["unit_hardening"] is False            # protections new there: off


def test_a_new_install_ends_jobs_background_programs(env):
    crons = pytest.importorskip("maxxing.crons")
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0
    assert run_cli("init", "--workspace", str(env["ws"]), "--quiet") == 0    # a re-run does not flip it
    assert config.load_config()["cron_keep_background"] is False
    assert config.load_config()["unit_hardening"] is True
    jobs = {j["name"]: j for j in crons.list_jobs()}
    assert jobs["Clean caches and old versions"]["enabled"]


def test_no_license_is_never_a_warning(env, tmp_path, monkeypatch, capsys):
    """Fair source: a server without a license key is normal - doctor and `maxxing license status` say where the
    updates come from (git or a local copy), never a warning asking for a key."""
    code = tmp_path / "code"
    code.mkdir()
    _git("init", "-q", cwd=code)
    monkeypatch.setattr(config, "CODE", code)
    c = cmd_core.check_license()                               # a local copy (no remote)
    assert c["level"] == cmd_core.INFO and "local copy" in c["title"]
    _git("remote", "add", "origin", str(tmp_path / "somewhere.git"), cwd=code)
    c = cmd_core.check_license()                               # a git install, public repository: no token
    assert c["level"] == cmd_core.INFO and "git repository" in c["title"]
    capsys.readouterr()
    assert run_cli("license", "status") == 0
    out = capsys.readouterr().out
    assert "– no license (none is needed" in out and "  ! " not in out


@pytest.mark.parametrize("branch", ["--upload-pack=touch {mark};git-upload-pack", "-x", "a..b", "a b", "a;b", "/a",
                                    "a/"])
def test_update_branch_is_never_a_git_option(tmp_path, monkeypatch, branch):
    """`maxxing update --branch`: the names install.sh accepts, and `--` before it (else `--upload-pack=…` runs)."""
    g = lambda *a, cwd: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)  # noqa: E731
    origin, code, state = tmp_path / "origin", tmp_path / "code", tmp_path / "state"
    origin.mkdir()
    state.mkdir()
    (state / "config.json").write_text(json.dumps({"workspace": str(tmp_path / "ws")}))
    g("init", "-q", "-b", "main", cwd=origin)
    (origin / "f").write_text("x")
    g("add", "-A", cwd=origin)
    g("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x", cwd=origin)
    g("clone", "-q", str(origin), str(code), cwd=tmp_path)
    monkeypatch.setattr(config, "STATE", state)
    monkeypatch.setattr(config, "CODE", code)
    mark = tmp_path / "pwned"
    ok, err = cmd_core._fetch(branch.format(mark=mark))
    assert not ok and "invalid branch" in err and not mark.exists()
    assert cmd_core.check_update(branch.format(mark=mark))["ok"] is False and not mark.exists()
    assert cmd_core._fetch("main") == (True, "")
