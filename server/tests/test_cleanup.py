"""Settings -> System -> Disk space: measure, then free only the chosen parts (maxxing/cleanup.py)."""
from __future__ import annotations

from pathlib import Path

from maxxing import cleanup, config, deps

_REAL_SH = cleanup._sh    # the autouse fixture replaces it in every test


def _fill(p: Path, size: int) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)


def test_scan_measures_without_deleting(client, monkeypatch):
    home = deps.root_home()
    _fill(home / ".cache" / "uv" / "a.whl", 4000)
    _fill(home / ".npm" / "_cacache" / "b", 1000)
    _fill(cleanup.APT_CACHE / "x.deb", 500)
    monkeypatch.setattr(cleanup, "_sh", lambda cmd, timeout=120, **_:
                        "Archived and active journals take up 1.0G in the file system." if "--disk-usage" in cmd else "")
    r = client.get("/api/system/cleanup").json()
    parts = {p["id"]: p for p in r["parts"]}
    assert set(parts) == set(cleanup.PARTS)
    assert parts["caches"]["bytes"] == 5000 and parts["caches"]["default"]
    assert {i["why"] for i in parts["caches"]["items"]} == {"uv cache", "npm cache"}
    assert parts["apt"]["bytes"] == 500
    assert parts["journal"]["bytes"] == 1024 ** 3 - cleanup.JOURNAL_KEEP
    assert not parts["trash"]["default"]
    assert "total" in r["disk"]
    assert (home / ".cache" / "uv" / "a.whl").exists()          # measured only


def test_run_frees_only_the_chosen_parts(client, monkeypatch):
    home = deps.root_home()
    _fill(home / ".cache" / "pip" / "c", 2000)
    _fill(cleanup.APT_CACHE / "x.deb", 500)
    ran: list[list[str]] = []
    monkeypatch.setattr(cleanup, "_sh", lambda cmd, timeout=120, **_: ran.append(cmd) or "")
    ws_file = config.workspace() / "projects" / "keep.bin"
    _fill(ws_file, 100)
    r = client.post("/api/system/cleanup", json={"parts": ["caches"]})
    assert r.status_code == 200, r.text
    assert r.json()["freed"] == 2000
    assert not (home / ".cache" / "pip").exists()
    assert (cleanup.APT_CACHE / "x.deb").exists() and ws_file.exists()
    assert ran == []                                           # no journal / apt command for caches alone
    client.post("/api/system/cleanup", json={"parts": ["journal", "apt"]})
    assert ["apt-get", "clean"] in ran and any(c[0] == "journalctl" and c[1].startswith("--vacuum-size=") for c in ran)


def test_run_refuses_unknown_or_empty(client):
    assert client.post("/api/system/cleanup", json={"parts": ["projects"]}).json()["error"] == "unknown_part"
    assert client.post("/api/system/cleanup", json={"parts": []}).status_code == 400


def test_a_failing_system_command_is_reported(tmp_path, monkeypatch):
    import subprocess

    import pytest
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "apt-get").write_text("#!/bin/sh\necho 'dpkg lock held' >&2\nexit 100\n")
    (fake / "apt-get").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:/usr/bin:/bin")
    with pytest.raises(subprocess.SubprocessError, match="dpkg lock held"):
        _REAL_SH(["apt-get", "clean"], check=True)


def test_an_unknown_part_with_a_surrogate_is_a_400(client):
    r = client.post("/api/system/cleanup", content=b'{"parts":["\\ud800"]}', headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"] == "unknown_part"
