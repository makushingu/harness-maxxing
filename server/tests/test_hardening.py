"""Hardening taken from the external audit: damaged settings files, bus merge, file modes, uploads."""
from __future__ import annotations

import asyncio
import json
import os
import stat

from maxxing import bus, config


def test_damaged_secrets_are_kept_not_overwritten(mx):
    config.set_secret("A_KEY", "one")
    config.secrets_path().write_text("{ not json")                 # damaged on disk
    assert config.load_secrets() == {}                              # the server keeps running
    config.set_secret("B_KEY", "two")                               # ... and a save never loses it
    copy = config.damaged_copy_of(config.secrets_path())
    assert copy and copy.read_text() == "{ not json" and stat.S_IMODE(copy.stat().st_mode) == 0o600
    assert config.load_secrets() == {"B_KEY": "two"}
    assert stat.S_IMODE(config.secrets_path().stat().st_mode) == 0o600
    from maxxing import cmd_core
    assert cmd_core.check_state_files()["level"] == cmd_core.WARN


def test_damaged_config_falls_back_to_defaults(mx):
    config.config_path().write_text("[1, 2]")
    assert config.load_config()["port"] == config.DEFAULT_CONFIG["port"]
    config.update_config(language="fr")
    assert config.damaged_copy_of(config.config_path()) is not None and config.load_config()["language"] == "fr"


def test_load_config_cache_sees_every_write_and_returns_copies(mx, monkeypatch):
    config.update_config(language="fr")
    a = config.load_config()
    a["language"] = "xx"                                             # callers may change their copy
    a["dashboard"] = {"order": ["x"]}
    assert config.load_config()["language"] == "fr" and "x" not in str(config.load_config().get("dashboard"))
    parsed = []
    real = config._document
    monkeypatch.setattr(config, "_document", lambda p: parsed.append(p) or real(p))
    config.load_config()
    assert parsed == []                                              # unchanged file: not parsed again
    raw = json.loads(config.config_path().read_text())
    raw["language"] = "en"
    config.config_path().write_text(json.dumps(raw))                 # in place, as another process could
    assert config.load_config()["language"] == "en" and len(parsed) == 1
    monkeypatch.setitem(config.DEFAULT_CONFIG, "brand_new_default", 1)
    assert config.load_config()["brand_new_default"] == 1            # the defaults are part of the key


def test_write_json_keeps_readable_modes(mx, tmp_path):
    p = tmp_path / "data.json"
    config.write_json(p, {"a": 1})
    assert stat.S_IMODE(p.stat().st_mode) == 0o666 & ~config._UMASK    # not private by accident
    os.chmod(p, 0o640)
    config.write_json(p, {"a": 2})
    assert stat.S_IMODE(p.stat().st_mode) == 0o640                       # existing mode kept
    assert not list(tmp_path.glob(".data.json.*"))                       # no temp file left


def test_bus_merges_topics_for_a_stalled_client():
    loop = asyncio.new_event_loop()
    try:
        bus.bind_loop(loop)
        q = asyncio.Queue(maxsize=1)
        bus._subscribers.add(q)

        async def go():
            bus.invalidate("sessions")
            bus.invalidate("tasks")                  # queue full: merged, not dropped
            bus.invalidate("crons")
            await asyncio.sleep(0)
            return q.get_nowait()
        assert set(loop.run_until_complete(go())) == {"sessions", "tasks", "crons"}
    finally:
        bus._subscribers.discard(q)
        loop.close()


def test_doctor_flags_an_old_caddy_site(tmp_path, monkeypatch):
    from maxxing import cmd_core
    site = tmp_path / "claude-maxxing.caddy"
    monkeypatch.setattr(cmd_core, "CADDY_SITE", site)
    assert cmd_core.check_caddy_site({"upload_max_mb": 2048}) is None                 # no Caddy site: nothing to say
    site.write_text('x.example {\n\theader {\n\t\tX-Frame-Options "DENY"\n\t}\n\trequest_body {\n\t\tmax_size 500MB\n\t}\n}\n')
    c = cmd_core.check_caddy_site({"upload_max_mb": 2048})
    assert c["level"] == "warn" and "PDF" in c["detail"] and "500 MB" in c["detail"]
    assert "SAMEORIGIN" in c["fix"] and "max_size 2100MB" in c["fix"] and c["fix"].endswith("systemctl reload caddy")
    site.write_text('x.example {\n\theader {\n\t\tX-Frame-Options "SAMEORIGIN"\n\t}\n\trequest_body {\n\t\tmax_size 2100MB\n\t}\n}\n')
    assert cmd_core.check_caddy_site({"upload_max_mb": 2048})["level"] == "ok"
    assert cmd_core._caddy_max_mb("max_size 2GB") == 2000 and cmd_core._caddy_max_mb("nothing") is None
    # no cap in the app (upload_max_mb 0): Caddy's 500 MB is the only limit left -> still flagged
    site.write_text('x.example {\n\trequest_body {\n\t\tmax_size 524288000\n\t}\n}\n')
    c = cmd_core.check_caddy_site({"upload_max_mb": 0})
    assert c["level"] == "warn" and "no limit" in c["detail"]
    # the fix keeps a copy and validates before reloading; its sed rewrites a bare byte count too
    assert c["fix"].startswith(f"cp -p {site} {site}.bak && ") and "caddy validate" in c["fix"]
    import re, subprocess
    sed = re.search(r"sed -i -E '([^']+)'", c["fix"]).group(1)
    out = subprocess.run(["sed", "-E", sed], input=site.read_text(), capture_output=True, text=True).stdout
    assert "max_size 2100MB" in out and "524288000" not in out


def test_installer_caddy_limits_match_the_app():
    from maxxing import cmd_core, config
    text = (config.CODE / "install.sh").read_text()
    assert f"max_size {cmd_core.CADDY_BODY_MB}MB" in text and 'X-Frame-Options "SAMEORIGIN"' in text
    assert cmd_core.CADDY_BODY_MB > config.DEFAULT_CONFIG["upload_max_mb"]


def test_damaged_state_files_never_give_a_500(client, mx):
    """Hand-edited files: a config section set to null keeps its defaults, a cron history line without its keys and
    a tasks list that is not a list are reported, not a 500 (C8)."""
    from maxxing import crons
    raw = json.loads(config.config_path().read_text())
    config.config_path().write_text(json.dumps({**raw, "telegram": None, "backup": "x", "workspace": None}))
    cfg = config.load_config()
    assert isinstance(cfg["telegram"], dict) and isinstance(cfg["backup"], dict)
    assert str(config.workspace()) == config.DEFAULT_CONFIG["workspace"]
    config.config_path().write_text(json.dumps({**raw, "telegram": None}))    # back to the test workspace
    job = crons.create_job({"name": "t", "schedule": "0 5 * * *", "kind": "shell", "command": "true"})
    with open(crons.runs_path(), "a") as f:
        f.write(json.dumps({"cron_id": job["id"]}) + "\n")
    assert client.get("/api/crons").status_code == 200
    (mx["ws"] / "tasks.json").write_text(json.dumps({"version": 1, "tasks": 5}))
    assert client.get("/api/tasks").status_code != 500


def test_config_lock_is_shared_between_processes(mx):
    """config._lock is an flock on <state>/.config.lock: another process waits for it (C7)."""
    import subprocess
    import sys
    import time
    code = ("import fcntl, os, sys, time; fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT); t = time.time(); "
            "fcntl.flock(fd, fcntl.LOCK_EX); print(round(time.time() - t, 2))")
    with config._lock:
        with config._lock:                             # re-entrant in the same thread
            p = subprocess.Popen([sys.executable, "-c", code, str(config.STATE / ".config.lock")],
                                 stdout=subprocess.PIPE, text=True)
            time.sleep(0.6)
    waited = float(p.communicate(timeout=10)[0])
    assert waited >= 0.4
