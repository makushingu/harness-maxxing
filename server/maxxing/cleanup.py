"""Free up disk space (Settings -> System -> Disk space; `maxxing deps clean [--caches]` does the first two parts).

Only what comes back by itself or that the user asked to drop: never a file of the workspace. Each part is
measured first (`scan`), then the user picks which ones go (`run`):

- leftovers: old versions of the components, browsers no longer used, temporary files of earlier runs,
  oversized logs (`deps.clean`, also the weekly "Clean caches and old versions" job);
- caches: root's uv / npm / pip / npx caches and Claude Code installer downloads, re-downloaded when needed (what a
  running process uses - an npx MCP server, a `uv run --with` environment - stays);
- journal: the systemd journal, cut down to JOURNAL_KEEP (`journalctl --vacuum-size`);
- apt: downloaded packages (`apt-get clean`);
- previews: the lighter video copies of the player and the file thumbnails, made again when shown (off by default:
  remaking them costs CPU; a copy played in the last COPY_KEEP_S stays, it may be playing);
- trash: the Harness trash (off by default: what is in it can still be restored).

Anything else (projects, attachments, renders, models, other tools' caches) is for Claude to look into with the
user: the "Clean up with Claude" button of the same card opens a session for that.
"""
from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import config, deps, trash

JOURNAL_KEEP = 200 * 1024 * 1024
APT_CACHE = Path("/var/cache/apt/archives")
JOURNAL_DIRS = (Path("/var/log/journal"), Path("/run/log/journal"))      # tests point them elsewhere
SCAN_TTL = 60
PARTS = ("leftovers", "caches", "journal", "apt", "previews", "trash")
DEFAULT_ON = {"leftovers", "caches", "journal", "apt"}

_lock = threading.Lock()
_last: dict[str, Any] = {"at": 0.0, "parts": None}
_UNITS = {"B": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}


def _sh(cmd: list[str], timeout: float = 120, check: bool = False) -> str:
    """Run a system command (journalctl, apt-get) -> its output, "" when it is missing or fails. Tests replace it.
    With check=True a non-zero exit raises SubprocessError carrying the end of stderr."""
    if not shutil.which(cmd[0]):
        return ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    if check and r.returncode:
        raise subprocess.SubprocessError(f"{cmd[0]} exited {r.returncode}: {(r.stderr or '').strip()[-200:]}")
    return r.stdout


def _journal_bytes() -> int:
    m = re.search(r"take up ([\d.]+)\s*([BKMGT])", _sh(["journalctl", "--disk-usage"], 20))
    return int(float(m.group(1)) * _UNITS[m.group(2)]) if m else 0


def _journal_archived() -> int:
    """Bytes of the archived journal files (name with an @): the only ones --vacuum-size removes."""
    total = 0
    for d in JOURNAL_DIRS:
        for f in d.glob("*/*@*.journal*"):
            with contextlib.suppress(OSError):
                total += f.stat().st_size
    return total


def _previews(dry: bool = True) -> int:
    """Video copies not played in the last COPY_KEEP_S and every thumbnail -> their bytes (deleted unless dry)."""
    from .videos import COPY_KEEP_S
    recent = time.time() - COPY_KEEP_S
    total = 0
    for pattern, keep_recent in (("videos/*.mp4", True), ("thumbs/*.webp", False)):
        for f in config.STATE.glob(pattern):
            if ".part." in f.name:                     # being encoded (video copy or thumbnail)
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            if keep_recent and st.st_atime > recent:
                continue
            if not dry:
                try:
                    f.unlink()
                except OSError:
                    continue
            total += st.st_size
    return total


def _apt_bytes() -> int:
    if not APT_CACHE.is_dir():
        return 0
    total = 0
    for f in APT_CACHE.rglob("*.deb"):
        with contextlib.suppress(OSError):
            total += f.lstat().st_size
    return total


def _measure(part: str) -> tuple[int, list[dict]]:
    """Bytes the part would free and its items ({path, why, bytes})."""
    if part in ("leftovers", "caches"):
        items = deps.clean(dry=True, caches=part == "caches", leftovers=part == "leftovers")
        return sum(i["bytes"] for i in items), items
    if part == "journal":
        used = _journal_bytes()
        known = any(d.is_dir() for d in JOURNAL_DIRS)
        return max(0, min(used - JOURNAL_KEEP, _journal_archived()) if known else used - JOURNAL_KEEP), []
    if part == "apt":
        return _apt_bytes(), []
    if part == "previews":
        return _previews(), []
    if part == "trash":
        return _trash_bytes(), []
    raise ValueError(part)


def _trash_bytes() -> int:
    """The trash's size from the per-item size cache of trash.py (an unchanged item is not walked again);
    only what is not an item (sidecars, strays) is measured here."""
    d = trash.trash_dir()
    if not d.is_dir():
        return 0
    items = trash.list_items(purge=False)
    ids = {i["id"] for i in items}
    total = sum(int(i.get("size") or 0) for i in items)
    try:
        names = [e.name for e in d.iterdir()]
    except OSError:
        return total
    for name in names:
        if name in ids or (name.endswith(".sessions") and name[: -len(".sessions")] in ids):
            continue
        total += deps._size(d / name)
    return total


def scan(force: bool = False) -> list[dict]:
    """Every part with what it would free: [{id, bytes, items, default}] (items only for the first two)."""
    with _lock:
        if not force and _last["parts"] is not None and time.time() - _last["at"] < SCAN_TTL:
            return _last["parts"]
        parts = []
        for p in PARTS:
            size, items = _measure(p)
            parts.append({"id": p, "bytes": size, "default": p in DEFAULT_ON and size > 0,
                          "items": [{"path": i["path"], "why": i["why"], "bytes": i["bytes"]} for i in items[:50]]})
        _last.update(at=time.time(), parts=parts)
        return parts


def _free_part(part: str) -> None:
    if part in ("leftovers", "caches"):
        deps.clean(caches=part == "caches", leftovers=part == "leftovers")
    elif part == "journal":
        _sh(["journalctl", f"--vacuum-size={JOURNAL_KEEP // (1024 * 1024)}M"], check=True)
    elif part == "apt":
        _sh(["apt-get", "clean"], check=True)
    elif part == "previews":
        _previews(dry=False)
    elif part == "trash":
        trash.empty()
        trash.invalidate_sizes()


def run(parts: list[str]) -> dict:
    """Free the chosen parts -> {freed, parts: [{id, freed, error?}]} (freed = measured before minus after)."""
    unknown = [p for p in parts if p not in PARTS]
    if unknown:
        raise ValueError(f"unknown part: {', '.join(u.encode('utf-8', 'replace').decode() for u in unknown)}")
    out = []
    with _lock:
        # the page's scan (under a minute old) already measured each part: one walk of a big cache, not two
        fresh = time.time() - _last["at"] < SCAN_TTL and {r["id"]: r["bytes"] for r in _last["parts"] or []} or {}
        for p in dict.fromkeys(parts):
            before = fresh[p] if p in fresh else _measure(p)[0]
            row: dict[str, Any] = {"id": p}
            try:
                _free_part(p)
            except (OSError, subprocess.SubprocessError, deps.DepError) as e:
                row["error"] = str(e)[:300]
            after, _ = _measure(p)
            row["freed"] = max(0, before - after)
            out.append(row)
        _last.update(at=0.0, parts=None)
    return {"freed": sum(r["freed"] for r in out), "parts": out}
