"""macOS: install.sh hands over to install-macos.sh (launchd agent of the user, pinned macOS builds), and the server
reads from launchd, sysctl, vm_stat, ps and lsof what it reads from systemd and /proc on Linux. Nothing here runs on
a Mac: the commands of macOS are replaced by their recorded answers."""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from maxxing import cmd_core, deps, health, mac, pkg

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "install-macos.sh"

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               12345.
Pages active:                            400000.
Pages inactive:                          200000.
Pages speculative:                         5000.
Pages purgeable:                           1000.
"""
SYSCTL = {"hw.memsize": "17179869184", "kern.boottime": "{ sec = 1795000000, usec = 0 } Sat Nov 21 10:00:00 2026",
          "vm.swapusage": "total = 2048.00M  used = 100.00M  free = 1948.00M  (encrypted)"}


@pytest.fixture
def on_mac(monkeypatch):
    calls: list[list[str]] = []
    state = {"loaded": True}

    def fake(cmd, timeout=10):
        calls.append(cmd)
        if cmd[0] == "sysctl":
            return 0, SYSCTL[cmd[2]]
        if cmd[0] == "vm_stat":
            return 0, VM_STAT
        if cmd[0] == "ps" and "%cpu=" in cmd:
            return 0, " 12.5\n  3,0\n  0.0\n"
        if cmd[0] == "ps" and "lstart=" in cmd:
            return (0, "Sat Nov 28 03:00:00 2026\n") if cmd[-1] == "4242" else (1, "")
        if cmd[0] == "lsof":
            return 0, "p123\nf5\nn127.0.0.1:8787\nf6\nn*:8787\nf7\nn[::1]:8787\n"
        if cmd[:2] == ["launchctl", "print"]:
            return (0, "gui/501/x = {\n\tstate = running\n\tpid = 4242\n}") if state["loaded"] else (113, "Could not find service")
        if cmd[:2] == ["launchctl", "bootout"]:
            state["loaded"] = False
        if cmd[:2] == ["launchctl", "bootstrap"]:
            state["loaded"] = True
        return 0, ""

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(mac, "_out", fake)
    return calls, state


def test_memory_uptime_cpu_and_ports_without_proc(on_mac):
    assert health.meminfo() == {"total": 17179869184, "avail": (12345 + 200000 + 5000 + 1000) * 16384}
    assert mac.swap_total() == 2048 * 1024 * 1024
    assert health.uptime_s() > 0
    assert mac.cpu_pct() is not None and 0 < mac.cpu_pct() <= 100
    assert mac.proc_start(4242) == "Sat Nov 28 03:00:00 2026" and mac.proc_start(1) is None
    assert cmd_core._listen_addrs(8787) == ["0.0.0.0", "127.0.0.1", "::1"]
    assert cmd_core.check_memory()["title"] == "16.0 GB of RAM"


def test_the_service_is_a_launchd_agent(on_mac, monkeypatch, tmp_path):
    calls, state = on_mac
    plist = tmp_path / "agent.plist"
    plist.write_text("x")
    monkeypatch.setattr(mac, "plist_path", lambda: plist)
    assert cmd_core.systemctl("is-active", cmd_core.SERVICE) == (0, "active")
    assert cmd_core.systemctl("stop", "maxxing-*")[0] == 127           # no transient units on a Mac
    assert health._systemctl_show_all([health.SELF_UNIT, "caddy"])[health.SELF_UNIT]["ActiveState"] == "active"
    assert cmd_core.systemctl("disable", "--now", cmd_core.SERVICE)[0] == 0 and not state["loaded"]
    assert cmd_core.systemctl("is-active", cmd_core.SERVICE) == (3, "inactive")
    cmd_core.systemctl("restart", cmd_core.SERVICE)                    # stopped: loaded again, then started
    assert ["launchctl", "bootstrap", mac.target().rsplit("/", 1)[0], str(plist)] in calls
    assert calls[-1][:3] == ["launchctl", "kickstart", "-k"]


def test_macos_builds_are_pinned_with_their_own_checksums(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(deps.platform, "machine", lambda: "arm64")
    assert deps.machine() == "darwin_aarch64"
    comps = deps.load()
    assert deps.url_of(comps["uv"]).endswith(f"uv-aarch64-apple-darwin.tar.gz")
    assert "/darwin-arm64/claude" in deps.url_of(comps["claude"]) and "darwin-arm64.tar.xz" in deps.url_of(comps["node"])
    for name in ("uv", "node", "claude"):
        assert deps.sha_of(comps[name]) != deps.sha_of(comps[name], "aarch64")       # never the Linux build's sum
        assert deps.sha_of(comps[name], "darwin_x86_64")


def test_homebrew_is_the_package_manager_named_in_the_hints(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(pkg.shutil, "which", lambda b: "/opt/homebrew/bin/brew" if b == "brew" else None)
    assert pkg.manager() == "brew" and pkg.hint("ffmpeg") == "brew install ffmpeg"


def sh(snippet: str, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f'MAXXING_INSTALL_LIB=1 source "{SCRIPT}"; set +e; INSTALL_DIR="{ROOT}"; '
                           'uname() { [ "$1" = -m ] && echo arm64 || echo Darwin; }; ' + snippet],
                          capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin", "HOME": str(home)})


def test_the_installer_reads_the_same_pins_and_writes_a_valid_agent(tmp_path):
    out = sh('echo "$(dep uv version)|$(dep uv arch "$(machine)")|$(dep claude sha256 "$(machine)")|$(dep python version)"; '
             'dep uv nothing || echo missing', tmp_path).stdout.split()
    comps = deps.load()
    assert out[0] == f'{comps["uv"]["version"]}|aarch64|{comps["claude"]["sha256"]["darwin_aarch64"]}|{comps["python"]["version"]}'
    assert out[1] == "missing"
    d = plistlib.loads(sh("plist_text", tmp_path).stdout.encode())
    assert d["Label"] == mac.LABEL and d["ProgramArguments"] == [f"{tmp_path}/.local/bin/maxxing", "serve"]
    assert d["EnvironmentVariables"]["MAXXING_STATE"] == f"{tmp_path}/.harness-maxxing/state"
    assert d["KeepAlive"] is True and d["RunAtLoad"] is True
    assert d["AbandonProcessGroup"] is True          # a restart of the service leaves the running turns alone
    assert d["StandardOutPath"].endswith("/logs/server.log")


def test_install_sh_hands_over_before_anything_linux():
    text = (ROOT / "install.sh").read_text()
    assert text.index("install-macos.sh") < text.index("umask 077") < text.index("declare -A")   # bash 3.2 never gets there
    mac_text = SCRIPT.read_text()
    for gnu in ("declare -A", "readlink -f", "sha256sum", "sed -i ", "mapfile", "${VOICE^^}", "systemctl"):
        assert gnu not in mac_text


def test_asking_systemd_on_a_mac_answers_no_such_unit(tmp_path, monkeypatch):
    from maxxing import config
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    folder = config.no_systemd_shim(tmp_path / "shim")
    assert sorted(p.name for p in folder.iterdir()) == sorted(config.NO_SYSTEMD) and "systemd-run" not in config.NO_SYSTEMD
    r = subprocess.run([str(folder / "systemctl"), "is-active", "caddy"], capture_output=True, text=True)
    assert r.returncode == 1 and r.stdout == ""
    assert os.environ["PATH"].endswith(str(folder))          # at the end: a real command always wins
