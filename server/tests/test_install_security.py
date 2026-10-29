"""Installer and first-run security (2.0.0a70): the setup link expires and stays out of the journal, a memory restore
at install time keeps what would run code off until an explicit yes, release keys by id, installer pins and checks.

The install.sh functions are tested by sourcing the script with MAXXING_INSTALL_LIB=1 (definitions only, main is
not run) inside a bash subprocess: nothing on this machine is changed."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from _conn_helpers import mx_state  # noqa: F401
from maxxing import backup, cli, config, security

INSTALL = Path(__file__).resolve().parents[2] / "install.sh"


def sh(snippet: str, **env: str) -> subprocess.CompletedProcess:
    """Run bash with install.sh's functions loaded (nothing of main runs)."""
    return subprocess.run(["bash", "-c", f'MAXXING_INSTALL_LIB=1 source "{INSTALL}"; set +e; {snippet}'],
                          capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin", **env})


# ---- setup link -----------------------------------------------------------------------------------------------
def test_setup_link_expires_after_one_hour(mx_state, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(security.time, "time", lambda: now[0])
    tok = security.ensure_setup_token()
    assert security.check_setup_token(tok)
    now[0] += security.SETUP_TOKEN_TTL - 5
    assert security.check_setup_token(tok) and security.ensure_setup_token() == tok
    now[0] += 10                                      # past one hour: the old link no longer works
    assert not security.check_setup_token(tok)
    fresh = security.ensure_setup_token()             # `maxxing setup-link` gives a new one
    assert fresh != tok and security.check_setup_token(fresh)
    security.clear_setup_token()
    assert not security.check_setup_token(fresh) and not config.get_secret("setup_token_at")


def test_serve_never_prints_the_setup_link(mx_state, monkeypatch, capsys):
    """The service's output goes to the journal, readable by every member of systemd-journal / adm."""
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(cli, "create_app", lambda: None, raising=False)
    import maxxing.app as app_mod
    monkeypatch.setattr(app_mod, "create_app", lambda: None)
    config.set_secret("password_hash", None)
    cli.main(["serve"])
    out = capsys.readouterr().out
    assert "token=" not in out and "setup-link" in out


# ---- restore held at install ----------------------------------------------------------------------------------
def test_install_restore_holds_then_releases(mx_state, monkeypatch):
    """`maxxing backup restore --hold` (what install.sh runs) keeps new jobs, extension code, hooks and local MCP
    servers off even on a brand-new server; `maxxing backup release` turns them on after the user's yes."""
    crons = pytest.importorskip("maxxing.crons")
    from maxxing import mcp
    added = []
    monkeypatch.setattr(mcp, "restore", lambda items: added.extend(items) or len(items))
    ws = config.workspace()
    ws.mkdir(parents=True, exist_ok=True)
    jobs = {"jobs": [{"id": "j1", "name": "Nightly", "schedule": "0 1 * * *", "kind": "shell",
                      "command": "bash run.sh", "enabled": True}]}
    hooks = {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}
    files = {f"{backup.META_DIR}/crons/jobs.json": json.dumps(jobs).encode(),
             "extensions/probe/api.py": b"def card(ctx):\n    return {}\n",
             "projects/acme/topics/blog/.claude/settings.json": json.dumps({"hooks": hooks}).encode(),
             f"{backup.META_DIR}/mcp.json": json.dumps([{"name": "local", "where": None,
                                                          "config": {"command": "node"}}]).encode()}
    r = backup._apply(files, hold=True)               # a new server: without hold=True all of it would run
    assert r["held"]["crons"] == ["Nightly"] and r["held"]["extensions"] == ["probe"]
    assert r["held"]["mcp"] == ["local"] and not added
    assert not crons.list_jobs()[0]["enabled"]
    assert "probe" in config.load_config()["extensions"]["disabled"]
    settings = ws / "projects/acme/topics/blog/.claude/settings.json"
    assert not settings.exists() and r["held"]["outside"] == ["projects/acme/topics/blog/.claude/settings.json"]
    assert any("Nightly" in ln for ln in backup.held_lines(r["held"]))

    out = backup.release_held()
    assert out["crons"] == ["j1"] and out["extensions"] == ["probe"] and out["mcp"] == 1
    assert crons.list_jobs()[0]["enabled"] and [i["name"] for i in added] == ["local"]
    assert "probe" not in config.load_config()["extensions"]["disabled"]
    assert json.loads(settings.read_text())["hooks"] == hooks and out["files"] == [str(settings.relative_to(ws))]
    assert backup.release_held().get("nothing")      # only once


def test_backup_cli_held_and_release(mx_state, capsys):
    assert cli.main(["backup", "held"]) == 0 and "Nothing held" in capsys.readouterr().out
    assert cli.main(["backup", "release"]) == 0 and "Nothing held" in capsys.readouterr().out


def test_custom_restore_stat_changes_nothing(tmp_path, capsys):
    assert cli.main(["custom", "restore", "--stat", "--from", str(tmp_path)]) == 0
    assert "No saved customization" in capsys.readouterr().out


# ---- installer checks -----------------------------------------------------------------------------------------
def test_installer_never_pipes_a_download_into_a_shell_nor_uses_fixed_tmp_paths():
    text = INSTALL.read_text()
    code = "\n".join(ln for ln in text.splitlines()       # comments and our own usage text aside
                     if not ln.lstrip().startswith("#") and "get.harness-maxxing.com" not in ln)
    assert not re.search(r"curl[^\n|]*\|\s*(sudo\s+)?(ba)?sh\b", code.replace("tailscale.com/install.sh | sh", ""))
    assert not re.search(r"/tmp/(maxxing|claude|node|harness)[-\w.]*", code.replace("/tmp/harness-install.XXXXXXXX", ""))
    assert "umask 077" in text and "export -n LICENSE GH_TOKEN" in text


def test_installer_library_mode_runs_nothing():
    r = sh("type safe_path >/dev/null && echo loaded")
    assert r.returncode == 0 and r.stdout.strip().endswith("loaded"), r.stderr


@pytest.mark.parametrize("value, ok", [("/opt/claude-maxxing", True), ("/srv/a_b-c.d", True), ("relative/x", False),
                                       ("/opt/it's", False), ("/opt/a b", False), ("/opt/%h", False),
                                       ("/opt/$(id)", False), ("/opt/../etc", False), ("/opt/a\\b", False)])
def test_paths_are_validated(value, ok):
    r = sh('safe_path INSTALL_DIR "$V" && echo fine', V=value)
    assert ("fine" in r.stdout) is ok, r.stdout + r.stderr


@pytest.mark.parametrize("value, ok", [("ui.example.com", True), ("a.b", False), ("ui.example.com;rm", False),
                                       ("-x.example.com", False), ("UI.example.com", False)])
def test_domains_are_validated(value, ok):
    assert (sh('valid_domain "$V" && echo fine', V=value).stdout.strip() == "fine") is ok


@pytest.mark.parametrize("value, ok", [("/opt/claude-maxxing", True), ("/var/lib/claude-maxxing", True),
                                       ("/root/.claude", True), ("/workspace", True), ("/", False), ("//", False),
                                       ("/var/lib", False), ("/var/lib/", False), ("/etc", False), ("/etc/maxxing", False),
                                       ("/usr/local", False), ("/root", False), ("/home/bob", False), ("/opt", False),
                                       ("//etc", False), ("/./usr/lib", False), ("/var//lib", False),
                                       ("/home/./bob", False), ("/.", False), ("/etc/.", False), ("/./", False),
                                       ("/srv/./maxxing", True), ("//opt/claude-maxxing", True)])
def test_system_directories_are_refused(value, ok):
    """STATE_DIR=/var/lib by mistake: chmod 700 on it broke every service reading it, and --purge deleted it."""
    r = sh('(not_system_dir STATE_DIR "$V") && echo fine', V=value)
    assert ("fine" in r.stdout) is ok, r.stdout + r.stderr


@pytest.mark.parametrize("fn, value", [("valid_domain", "ui.example.com\n:80 { file_server browse }"),
                                       ("valid_domain", "ui.example.com\r"),
                                       ("valid_tz_name", "Europe/Paris\nx")])
def test_a_second_line_never_passes_a_check(fn, value):
    """grep -E checks each line alone: a DOMAIN with a newline put a whole Caddy site in the root-owned Caddyfile."""
    assert "fine" not in sh(f'{fn} "$(printf "$V")" && echo fine', V=value).stdout
    r = sh('REPO="$(printf "a/b\nc")"; check_inputs', INSTALL_DIR="/opt/claude-maxxing", WORKSPACE="/root/maxxing",
           STATE_DIR="/var/lib/claude-maxxing")
    assert r.returncode != 0 and "one line" in (r.stdout + r.stderr)


def test_a_public_udp_service_keeps_the_firewall_off(tmp_path):
    """A server whose only public service is UDP (WireGuard...) looked fresh: the automatic firewall cut it off."""
    fake = ('ss() { case "$1" in -lunpH) printf "%s\\n" \'UNCONN 0 0 0.0.0.0:51820 0.0.0.0:* users:(("wg",pid=1,fd=3))\' '
            '"UNCONN 0 0 127.0.0.53%lo:53 0.0.0.0:*" "UNCONN 0 0 0.0.0.0:68 0.0.0.0:*" ;; *) : ;; esac; }; '
            'ssh_ports() { echo 22; }; our_unit_active() { return 1; }; ')
    r = sh(fake + 'PUBLIC_OTHER=""; detect_server >/dev/null 2>&1; echo "[$PUBLIC_OTHER]"', HOME=str(tmp_path))
    assert "[51820/udp/wg]" in r.stdout, r.stdout + r.stderr


def test_fail2ban_jail_names_the_real_ssh_ports():
    """F11: the jail used to name no port (fail2ban's default "ssh" = 22): a server on 2222 was not protected."""
    r = sh('ssh_ports() { printf "22\\n2222\\n"; }; f2b_jail')
    assert "port = 22,2222" in r.stdout and "backend = systemd" in r.stdout


def test_ufw_add_mode_sees_existing_ssh_rules():
    for rules, port, has in (("22/tcp 80", "22", True), ("OpenSSH", "22", True), ("2200:2300/tcp", "2222", True),
                             ("80,443/tcp", "443", True), ("80/tcp", "2222", False)):
        r = sh(f'ufw_has_port "{rules}" {port} && echo yes')
        assert ("yes" in r.stdout) is has, (rules, port)


def test_tunnel_instructions_use_the_session_user_address_and_port():
    """F13: `ssh -L ... root@<first address>` was wrong on cloud images (ubuntu@, another port, another address)."""
    r = sh('PORT=8787; tunnel_cmd', SSH_CONNECTION="198.51.100.7 51234 203.0.113.9 2222", SUDO_USER="ubuntu")
    assert r.stdout == "ssh -N -L 8787:127.0.0.1:8787 -p 2222 ubuntu@203.0.113.9"
    r = sh('PORT=8787; tunnel_cmd', SSH_CONNECTION="198.51.100.7 51234 203.0.113.9 22", SUDO_USER="ubuntu")
    assert r.stdout == "ssh -N -L 8787:127.0.0.1:8787 ubuntu@203.0.113.9"


def test_a_failed_protection_stops_the_install(tmp_path):
    """F06: security updates, fail2ban and the firewall that the installer turns on are checked for real; one that
    does not work stops the installation unless ALLOW_UNPROTECTED=1."""
    stubs = ('apt_get() { return 0; }; systemctl() { return 0; }; apt-config() { echo; }; '
             'fail2ban-client() { return 1; }; ssh_key_only() { :; }; ssh_ports() { echo 22; }; '
             'systemd-detect-virt() { return 1; }; ufw() { echo "Status: inactive"; }; manifest() { :; }; sleep() { :; }; ')
    base = (f'WORK={tmp_path}; EXISTING=0; PRIOR=0; FIREWALL=1; ACCESS=local; PUBLIC_OTHER=""; HAS_DOCKER=0; ')
    r = sh(stubs + base + 'ALLOW_UNPROTECTED=0; secure_server; echo "rc=$?"')
    assert "NOT protected: fail2ban" in r.stdout and "NOT protected: firewall" in r.stdout
    assert "NOT protected: automatic security updates" in r.stdout
    assert "rc=" not in r.stdout and "ALLOW_UNPROTECTED=1" in r.stderr          # stopped (die)
    for used in ("EXISTING=1; ", "PRIOR=1; "):     # adapted at integration: a server in use / a re-run only warns
        r = sh(stubs + base + used + 'ALLOW_UNPROTECTED=0; secure_server; echo "rc=$?"')
        assert "rc=0" in r.stdout and "NOT protected: fail2ban" in r.stdout and "already in use" in r.stdout
    r = sh(stubs + base + 'ALLOW_UNPROTECTED=1; secure_server; echo "rc=$?"')
    assert "rc=0" in r.stdout and "continuing without it" in r.stdout
