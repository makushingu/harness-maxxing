"""Free up disk space (Settings -> System -> Disk space, `maxxing cleanup`).

Only what comes back by itself or that the user asked to drop: never a file of the workspace. Each part is
measured first (`scan`), then the user picks which ones go (`run`):

- leftovers: old versions of the components, browsers no longer used, temporary files of earlier runs,
  oversized logs (`deps.clean`, also the weekly "Clean caches and old versions" job);
- caches: root's uv / npm / pip / npx caches and Claude Code installer downloads, re-downloaded when needed;
- journal: the systemd journal, cut down to JOURNAL_KEEP (`journalctl --vacuum-size`);
- apt: downloaded packages (`apt-get clean`);
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

from . import deps, trash

JOURNAL_KEEP = 200 * 1024 * 1024
APT_CACHE = Path("/var/cache/apt/archives")
SCAN_TTL = 60
PARTS = ("leftovers", "caches", "journal", "apt", "trash")
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
        return max(0, used - JOURNAL_KEEP), []
    if part == "apt":
        return _apt_bytes(), []
    if part == "trash":
        d = trash.trash_dir()
        return (deps._size(d) if d.is_dir() else 0), []
    raise ValueError(part)


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
        for p in dict.fromkeys(parts):
            before, _ = _measure(p)
            row: dict[str, Any] = {"id": p}
            try:
                _free_part(p)
            except (OSError, subprocess.SubprocessError) as e:
                row["error"] = str(e)[:300]
            after, _ = _measure(p)
            row["freed"] = max(0, before - after)
            out.append(row)
        _last.update(at=0.0, parts=None)
    return {"freed": sum(r["freed"] for r in out), "parts": out}
