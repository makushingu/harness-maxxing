"""The user's profile photo (Settings -> Profile), kept on this server, and the cached photos of Team contacts.

Own photo: `<state>/profile/photo` (JPEG, PNG or WebP, checked by its first bytes, at most PHOTO_MAX; the browser
already crops it square and shrinks it to 256 px). `config.profile.photo` = the first 16 hex characters of its
SHA-256: the version the UI and the contacts see (`?v=`), empty = no photo.
A contact's photo is asked to its server only when its version changes (signed GET /api/team-peer/photo, see
teampeer.fetch_photo) and kept in `<state>/team/photos/<person id>-<version>`. Never SVG (no script in an <img>
we serve).
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from . import config

PHOTO_MAX = 512 * 1024
VERSION = re.compile(r"[0-9a-f]{16}")
_busy: set[str] = set()                     # fetches in flight: a second request for the same photo waits for none
_busy_lock = threading.Lock()
_failed: dict[str, float] = {}              # "<pid>-<version>" -> when a fetch failed (asked again after RETRY_S)
RETRY_S = 600


def sniff(data: bytes) -> str | None:
    """The image type of these bytes (only the 3 we serve), else None."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def own_path() -> Path:
    return config.STATE / "profile" / "photo"


def save(data: bytes) -> str:
    """Store a new own photo -> its version. ValueError if it is not a small JPEG / PNG / WebP."""
    if not data or len(data) > PHOTO_MAX:
        raise ValueError("too_large" if data else "empty")
    if not sniff(data):
        raise ValueError("not_an_image")
    p = own_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("photo.part")
    tmp.write_bytes(data)
    tmp.chmod(0o644)
    tmp.replace(p)
    return hashlib.sha256(data).hexdigest()[:16]


def remove() -> None:
    own_path().unlink(missing_ok=True)


def own() -> tuple[Path, str] | None:
    """(path, mime) of the own photo, or None."""
    p = own_path()
    try:
        with open(p, "rb") as f:
            mime = sniff(f.read(16))
    except OSError:
        return None
    return (p, mime) if mime else None


def _cache_dir() -> Path:
    return config.STATE / "team" / "photos"


def cached(pid: str, version: str) -> tuple[Path, str] | None:
    """(path, mime) of a contact's photo at this version, fetched from its server the first time (None if it has
    none, cannot be reached, or sent something that is not an image)."""
    if not VERSION.fullmatch(version or "") or not re.fullmatch(r"p_[0-9a-f]{6,32}", pid or ""):
        return None
    d = _cache_dir()
    p = d / f"{pid}-{version}"
    if not p.is_file():
        key = f"{pid}-{version}"
        if time.time() - _failed.get(key, 0) < RETRY_S:
            return None
        with _busy_lock:
            if key in _busy:                    # another request is fetching it: no second download
                return None
            _busy.add(key)
        try:
            from . import teampeer
            data = teampeer.fetch_photo(pid, version)
            if not data or not sniff(data) or hashlib.sha256(data).hexdigest()[:16] != version:
                _failed[key] = time.time()
                return None
            d.mkdir(parents=True, exist_ok=True)
            for old in d.glob(f"{pid}-*"):      # one version per person
                if old.name != p.name:
                    old.unlink(missing_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, prefix=f".{pid}-", suffix=".part")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                os.replace(tmp, p)
            except OSError:
                Path(tmp).unlink(missing_ok=True)
                return None
        finally:
            with _busy_lock:
                _busy.discard(key)
    try:
        with open(p, "rb") as f:
            mime = sniff(f.read(16))
    except OSError:                             # replaced by a newer version meanwhile
        return None
    return (p, mime) if mime else None
