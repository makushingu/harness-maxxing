"""Turn and job units get the systemd protections measured harmless for sessions that administer the server
(audit F02, without changing the user): clock, personality, realtime - nothing that blocks apt, sudo or mounts."""
from types import SimpleNamespace

from maxxing import config, crons
from maxxing.sessions import spawn

KEPT = ["ProtectClock=yes", "LockPersonality=yes", "RestrictRealtime=yes"]
# measured to break legitimate admin work in a session (see docs/dev/INTERNALS.md "Unit hardening")
REJECTED = ("NoNewPrivileges", "ProtectSystem", "ProtectHome", "PrivateTmp", "ProtectKernelTunables",
            "ProtectKernelModules", "ProtectKernelLogs", "ProtectControlGroups", "RestrictSUIDSGID",
            "SystemCallArchitectures", "RestrictNamespaces", "MemoryDenyWriteExecute", "PrivateDevices", "User=")


def _turn_props(monkeypatch, cfg):
    calls = []
    monkeypatch.setattr(config, "load_config", lambda: cfg)
    monkeypatch.setattr(spawn, "_runner_env", lambda: {})
    monkeypatch.setattr(spawn.subprocess, "run",
                        lambda cmd, **k: calls.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    spawn._start_unit("12345678-1234-1234-1234-123456789012")
    cmd = calls[0]
    return [cmd[i + 1] for i, a in enumerate(cmd[:-1]) if a == "--property"]


def test_turn_units_are_hardened(monkeypatch):
    props = _turn_props(monkeypatch, {"unit_memory_max": "75%"})
    assert all(k in props for k in KEPT)
    assert not [p for p in props if p.startswith(REJECTED)]


def test_job_units_are_hardened(monkeypatch):
    monkeypatch.setattr(config, "load_config", lambda: {"unit_memory_max": "75%"})
    props = crons.unit_properties({"timeout_s": 60})
    assert all(k in props for k in KEPT) and "MemoryMax=75%" in props
    assert not [p for p in props if p.startswith(REJECTED)]


def test_hardening_can_be_turned_off(monkeypatch):
    props = _turn_props(monkeypatch, {"unit_hardening": False})
    assert not any(k in props for k in KEPT) and "OOMPolicy=continue" in props
    assert config.DEFAULT_CONFIG["unit_hardening"] is True
