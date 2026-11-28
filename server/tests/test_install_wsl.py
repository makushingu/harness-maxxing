"""Windows through WSL 2: install.ps1 prepares the distribution, install.sh then runs in it like on a server, with
the access and the last screen of a PC. install.sh is sourced with MAXXING_INSTALL_LIB=1: nothing here is changed."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "install.sh"
PS1 = (ROOT / "install.ps1").read_text()


def sh(snippet: str, tmp_path, kernel: str) -> subprocess.CompletedProcess:
    (tmp_path / "osrelease").write_text(kernel + "\n")
    return subprocess.run(["bash", "-c", f'MAXXING_INSTALL_LIB=1 source "{INSTALL}"; set +e; {snippet}'],
                          capture_output=True, text=True, timeout=60,
                          env={"PATH": "/usr/bin:/bin", "HOME": "/root", "PROC_VERSION": str(tmp_path / "osrelease")})


def test_wsl_is_told_by_its_kernel(tmp_path):
    assert sh("is_wsl && echo yes", tmp_path, "6.6.87.2-microsoft-standard-WSL2").stdout.strip() == "yes"
    assert sh("is_wsl || echo no", tmp_path, "7.0.0-30-generic").stdout.strip() == "no"


def test_wsl_gets_local_access_without_a_question(tmp_path):
    snippet = 'cfg_get() { :; }; section() { :; }; ok() { :; }; has_tty() { return 1; }; dns_check() { :; }; ' \
              'ACCESS=""; choose_access >/dev/null 2>&1; echo "access=$ACCESS"'
    assert "access=local" in sh(snippet, tmp_path, "6.6.87.2-microsoft-standard-WSL2").stdout


def test_the_windows_script_runs_the_same_installer_as_root_with_systemd_on():
    assert "raw.githubusercontent.com/makushingu/harness-maxxing/$Branch/install.sh" in PS1
    assert "systemd=true" in PS1 and "/etc/wsl.conf" in PS1
    assert "--exec bash -c" in PS1 and " -- bash" not in PS1.split("# Settings")[1]   # one parsing only: no shell in between
    conf = next(line for line in PS1.splitlines() if line.strip().startswith("$conf ="))
    assert conf.count('"') == 2                       # Windows PowerShell 5 drops double quotes passed to a program
    assert "Register-ScheduledTask" in PS1 and "sleep infinity" in PS1
