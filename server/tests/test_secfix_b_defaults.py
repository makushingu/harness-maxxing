"""Lot B: safe defaults. A new install works in the sandbox, its `system` project in full access; an install that
exists keeps its mode and doctor says which one it has."""
import argparse
import json

from maxxing import agent_guard, cmd_core, config, workspace


def _init(monkeypatch, mx):
    for name, value in (("install_skills", lambda: []), ("claude_settings_defaults", lambda: False),
                        ("ensure_jobs_slice", lambda: ""), ("ensure_service_memory", lambda: ""),
                        ("ensure_cpu_slices", lambda *_: "")):
        monkeypatch.setattr(cmd_core, name, value)
    a = argparse.Namespace(workspace=None, files_root=None, port=None, bind=None, public_url=None, timezone=None,
                           language=None, system_clock=None, claude_dir=None, secret_from_stdin=None, no_crons=True)
    return mx["ws"], cmd_core.do_init(a)


def test_a_new_install_works_in_the_sandbox_and_system_keeps_full_access(monkeypatch, mx):
    monkeypatch.setattr(cmd_core, "_sandbox_ready", lambda: True)
    ws, report = _init(monkeypatch, mx)
    cfg = json.loads(config.config_path().read_text())
    assert cfg["permission_mode"] == "sandbox" and "sandbox_default" not in cfg
    assert workspace.topic_permission_mode("projects/system/topics/harness") == "bypass"
    assert workspace.topic_permission_mode("projects/general/topics/inbox") == ""
    assert "sandbox" in report["permission_mode"]


def test_a_server_where_the_sandbox_cannot_start_keeps_full_access(monkeypatch, mx):
    monkeypatch.setattr(cmd_core, "_sandbox_ready", lambda: False)
    _init(monkeypatch, mx)
    assert "permission_mode" not in json.loads(config.config_path().read_text())


def test_an_install_that_exists_keeps_its_mode(monkeypatch, mx):
    monkeypatch.setattr(cmd_core, "_sandbox_ready", lambda: True)
    cmd_core._save_install_state(version="2.0.0a100", initialized=1.0)
    _init(monkeypatch, mx)
    assert "permission_mode" not in json.loads(config.config_path().read_text())
    assert workspace.topic_permission_mode("projects/system/topics/harness") == ""


def test_doctor_says_full_access_and_fails_on_a_sandbox_that_cannot_start(monkeypatch, mx):
    monkeypatch.setattr(cmd_core, "_sandbox_ready", lambda: False)
    _init(monkeypatch, mx)
    assert cmd_core.check_permissions()["level"] == cmd_core.INFO
    raw = json.loads(config.config_path().read_text())
    config.write_json(config.config_path(), {**raw, "permission_mode": "sandbox"})
    monkeypatch.setattr(agent_guard, "available", lambda fresh=False: {"ok": False, "missing": ["bwrap"]})
    assert cmd_core.check_permissions()["level"] == cmd_core.FAIL
    monkeypatch.setattr(agent_guard, "available", lambda fresh=False: {"ok": True, "missing": []})
    assert cmd_core.check_permissions()["level"] == cmd_core.OK


def test_the_memory_compaction_job_keeps_full_access():
    assert cmd_core.COMPACTION_JOB["permission_mode"] == "bypass"


def test_the_answer_given_at_the_installation_is_kept(monkeypatch, mx):
    from maxxing import register
    monkeypatch.setattr(cmd_core, "_sandbox_ready", lambda: False)
    for name, value in (("install_skills", lambda: []), ("claude_settings_defaults", lambda: False),
                        ("ensure_jobs_slice", lambda: ""), ("ensure_service_memory", lambda: ""),
                        ("ensure_cpu_slices", lambda *_: "")):
        monkeypatch.setattr(cmd_core, name, value)
    a = argparse.Namespace(workspace=None, files_root=None, port=None, bind=None, public_url=None, timezone=None,
                           language=None, system_clock=None, claude_dir=None, secret_from_stdin=None, no_crons=True,
                           count="no")
    cmd_core.do_init(a)
    assert register.settings()["count"] is False and register.settings()["asked"] is True
    a.count = None
    cmd_core.do_init(a)                             # an update: the migration never turns it back on
    assert register.settings()["count"] is False


def test_the_installer_asks_before_the_anonymous_count():
    from pathlib import Path
    sh = (Path(__file__).resolve().parents[2] / "install.sh").read_text()
    assert 'ANON_COUNT="${ANON_COUNT:-ask}"' in sh and "Send this anonymous daily count?" in sh
    assert "ANON_COUNT=keep" in sh                  # an installation that exists is not asked again


def test_the_security_page_lists_what_protects_the_server(client, monkeypatch):
    monkeypatch.setattr(cmd_core, "check_security", lambda: cmd_core._c("security", cmd_core.OK, "hardening on"))
    checks = client.get("/api/system/security").json()["checks"]
    by = {c["id"]: c for c in checks}
    assert {"sign_in", "permissions", "secrets_store", "security", "listen"} <= set(by)
    assert by["sign_in"]["level"] == "warn" and "Two-step" in by["sign_in"]["fix"]
    monkeypatch.setattr(cmd_core, "check_permissions", lambda: 1 / 0)       # a check that breaks is skipped
    assert "permissions" not in {c["id"] for c in client.get("/api/system/security").json()["checks"]}
