"""Installation without root (install.sh run by a normal user): everything in that user's home, a unit of their own
systemd, this machine only, nothing of the system touched; the server then talks to `systemctl --user` and runs
turns as plain processes. install.sh is sourced with MAXXING_INSTALL_LIB=1: nothing on this machine is changed."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from maxxing import cmd_core, config, deps

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "install.sh"


def sh(snippet: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f'MAXXING_INSTALL_LIB=1 source "{INSTALL}"; set +e; {snippet}'],
                          capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin", "HOME": "/root", **env})


def test_user_unit_is_the_users_own():
    out = sh('BIN=/home/u/.local/bin/maxxing WORKSPACE=/home/u/maxxing STATE_DIR=/home/u/.harness-maxxing/state; user_unit_text').stdout
    assert "ExecStart=/home/u/.local/bin/maxxing serve" in out
    assert "Environment=MAXXING_STATE=/home/u/.harness-maxxing/state" in out
    assert "KillMode=process" in out            # a running turn (a plain process there) survives a restart
    assert "WantedBy=default.target" in out
    assert "User=" not in out and "MemoryMax" not in out


def test_a_domain_needs_root():
    r = sh('USERMODE=1 ACCESS=domain DOMAIN=ui.example.com; cfg_get() { :; }; choose_access')
    assert r.returncode != 0 and "ACCESS=domain needs root" in r.stdout + r.stderr
    r = sh('USERMODE=1 ACCESS=; cfg_get() { :; }; choose_access >/dev/null; echo "$ACCESS $BIND"')
    assert r.stdout.split() == ["local", "127.0.0.1"]


def test_missing_packages_are_named_not_installed():
    """Without root nothing is installed: a missing base package stops with the command to type."""
    r = sh('USERMODE=1; pkg_installed() { [ "$1" != git ]; }; apt_get() { echo APT-CALLED; }; user_packages')
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "sudo apt-get install -y git" in out and "APT-CALLED" not in out
    r = sh('USERMODE=1; pkg_installed() { [ "$1" != ffmpeg ]; }; systemctl() { :; }; user_packages')
    assert r.returncode == 0 and "sudo apt-get install -y ffmpeg" in r.stdout


def test_the_security_step_is_roots():
    r = sh('USERMODE=1; main --secure')
    assert r.returncode != 0 and "run it as root" in r.stdout + r.stderr


def test_server_talks_to_the_users_systemd(monkeypatch, tmp_path):
    assert config.sd() == ["systemctl"]                       # the tests run as root
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    assert config.user_mode()
    assert config.sd("journalctl") == ["journalctl", "--user"]
    seen = []
    monkeypatch.setattr(cmd_core, "run", lambda cmd, **k: seen.append(cmd) or (0, "active"))
    monkeypatch.setattr(cmd_core, "SYSTEMD_DIR", tmp_path)
    cmd_core.systemctl("is-active", cmd_core.SERVICE)
    assert seen == [["systemctl", "--user", "is-active", "claude-maxxing"]]


def test_doctor_leaves_the_system_alone(monkeypatch):
    monkeypatch.setattr(cmd_core, "USER_MODE", True)
    monkeypatch.setattr(cmd_core, "_run_ok", lambda *a, **k: (_ for _ in ()).throw(AssertionError("system probed")))
    assert cmd_core.check_security()["level"] == cmd_core.INFO
    assert cmd_core.check_caddy({"public_url": "https://x.example.com"}) is None
    assert cmd_core.check_hardening() is None


def test_components_belong_to_the_user(monkeypatch, tmp_path):
    f = tmp_path / "bin"
    f.write_text("x")
    f.chmod(0o755)
    os.chown(tmp_path, 1000, 1000)
    os.chown(f, 1000, 1000)
    assert deps.foreign_owned(tmp_path) == [str(tmp_path), str(f)] or len(deps.foreign_owned(tmp_path)) == 2
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert deps.foreign_owned(tmp_path) == []
    f.chmod(0o775)                                            # writable by the group: still refused
    assert deps.foreign_owned(tmp_path) == [str(f)]
