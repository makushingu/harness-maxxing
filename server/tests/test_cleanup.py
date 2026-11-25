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


def test_journal_counts_only_archived_files(tmp_path, monkeypatch):
    j = tmp_path / "journal"
    _fill(j / "m" / "system.journal", 900)                      # active: --vacuum-size leaves it
    _fill(j / "m" / "system@0001-0002.journal", 300)
    monkeypatch.setattr(cleanup, "JOURNAL_DIRS", (j,))
    monkeypatch.setattr(cleanup, "_journal_bytes", lambda: cleanup.JOURNAL_KEEP + 10_000)
    assert cleanup._measure("journal")[0] == 300


def test_previews_drop_old_copies_and_thumbnails_only(client):
    import os
    import time
    from maxxing.videos import COPY_KEEP_S
    old, playing, encoding = (config.STATE / "videos" / n for n in ("a-720.mp4", "b-720.mp4", "c-720.part.mp4"))
    thumb, thumb_part = (config.STATE / "thumbs" / n for n in ("t.webp", "u.1234abcd.part.webp"))
    for f in (old, playing, encoding, thumb, thumb_part):
        _fill(f, 100)
    then = time.time() - COPY_KEEP_S - 60
    os.utime(old, (then, then))
    parts = {p["id"]: p for p in client.get("/api/system/cleanup?force=true").json()["parts"]}
    assert parts["previews"]["bytes"] == 200 and not parts["previews"]["default"]
    assert client.post("/api/system/cleanup", json={"parts": ["previews"]}).json()["freed"] == 200
    assert not old.exists() and not thumb.exists() and playing.exists() and encoding.exists()
    assert thumb_part.exists()                          # ffmpeg is still writing it


def test_caches_in_use_and_the_upload_folder_stay(monkeypatch):
    home = deps.root_home()
    used, idle = home / ".npm" / "_npx" / "used", home / ".npm" / "_npx" / "idle"
    _fill(used / "x.js", 10)
    _fill(idle / "x.js", 10)
    _fill(config.STATE / "tmp" / "uploads" / ".keep", 1)
    monkeypatch.setattr(deps, "_in_use", lambda roots: {r for r in roots if r.name == "used"})
    gone = {x["path"] for x in deps.clean(caches=True)}
    assert str(idle) in gone and str(used) not in gone and used.exists()
    assert (config.STATE / "tmp" / "uploads").exists()


def test_in_use_sees_a_process_working_in_a_folder(tmp_path):
    import subprocess
    busy, free = tmp_path / "busy", tmp_path / "free"
    busy.mkdir()
    free.mkdir()
    p = subprocess.Popen(["sleep", "30"], cwd=busy)
    try:
        assert deps._in_use([busy, free]) == {busy}
    finally:
        p.kill()
        p.wait()


def test_no_clean_while_an_update_runs(capsys):
    from maxxing import cmd_deps
    import pytest
    with deps.run_lock():
        with pytest.raises(deps.Busy):
            deps.clean()
        r = cleanup.run(["leftovers"])
        assert "update" in r["parts"][0]["error"]
        import argparse
        assert cmd_deps.cmd_deps(argparse.Namespace(action="clean", names=[], dry_run=False, caches=False, quiet=True)) == 0
        assert "skipped" in capsys.readouterr().out
    assert deps.clean(dry=True) is not None                     # measuring never waits


def test_the_trash_part_reuses_the_per_item_size_cache(client, monkeypatch):
    """Scanning the disk space must not walk every trash item again: unchanged items come from trash.py's cache."""
    import os
    from maxxing import trash
    t = trash.trash_dir()
    for i in range(3):
        d = t / f"item{i}"
        d.mkdir(parents=True, exist_ok=True)
        for j in range(4):
            (d / f"f{j}").write_bytes(b"x" * 10)
    (t / "stray.bin").write_bytes(b"y" * 7)
    expected = deps._size(t)
    assert cleanup._measure("trash")[0] == expected
    walks = {"n": 0}
    real = os.walk

    def counting(*a, **k):
        walks["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(os, "walk", counting)
    assert cleanup._measure("trash")[0] == expected
    assert walks["n"] == 0


def test_run_reuses_a_fresh_scan_instead_of_measuring_twice(monkeypatch):
    calls = []
    monkeypatch.setattr(cleanup, "_measure", lambda p: (calls.append(p), (100 if len(calls) == 1 else 40, []))[1])
    monkeypatch.setattr(cleanup, "_free_part", lambda p: None)
    monkeypatch.setattr(cleanup, "PARTS", ("caches",))
    cleanup.scan(force=True)
    assert calls == ["caches"]
    assert cleanup.run(["caches"]) == {"freed": 60, "parts": [{"id": "caches", "freed": 60}]}
    assert calls == ["caches", "caches"]                   # the scan's measure + after, no second walk before
