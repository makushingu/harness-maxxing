"""Secret FILES of the Keys vault: a keystore, a service-account JSON, a certificate - content a text value cannot
hold. The bytes live in STATE/secret-files/<NAME> (folder mode 700, files mode 600); secrets.json keeps the metadata
under "vault_files": {name: {filename, size, sha256, note, expose, updated}} (the full sha256; the list shows its first
SHA_SHOWN characters, enough to tell two versions apart).

Names follow the text keys (vault.check_name), and a name is either a text key or a file. A file flagged `expose` is
exported as the environment variable NAME holding its PATH, never its content (`exposed_files_env()`, merged where
`vault.exposed_env()` is). The content is never returned by the API; only the CLI reads it (`read`).
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from . import config
from .vault import NAME_RE, RESERVED, VaultError, _is_text, check_name

DIRNAME = "secret-files"
MAX_SIZE = 1024 * 1024
SHA_SHOWN = 12
STALE_TMP_S = 600                                  # a temp file older than this was left by a crash
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def files_dir() -> Path:
    return config.STATE / DIRNAME


def _meta() -> dict[str, dict]:
    v = config.load_secrets().get("vault_files")
    if not isinstance(v, dict):
        return {}
    return {k: e for k, e in v.items() if isinstance(k, str) and isinstance(e, dict)}


def exists(name: str) -> bool:
    return name in _meta()


def clean_filename(filename: str | None, fallback: str) -> str:
    """The original name for display: no folders, no control characters, 100 characters at most."""
    base = _CTRL.sub("", (filename or "").replace("\\", "/").rsplit("/", 1)[-1]).strip()
    return (base if _is_text(base) else "")[:100] or fallback


def list_files() -> list[dict]:
    """Metadata only, never the content."""
    return [{"name": k, "filename": e.get("filename") or k, "size": e.get("size"),
             "sha256": e["sha256"][:SHA_SHOWN] if isinstance(e.get("sha256"), str) else None,
             "note": e.get("note", ""), "expose": bool(e.get("expose")), "updated": e.get("updated")}
            for k, e in sorted(_meta().items())]


def path_of(name: str) -> Path | None:
    """The stored file of `name` (a regular file, not a link), else None."""
    if name not in _meta() or not NAME_RE.match(name):
        return None
    p = files_dir() / name
    return p if p.is_file() and not p.is_symlink() else None


def read(name: str) -> bytes | None:
    p = path_of(name)
    try:
        return p.read_bytes() if p else None
    except OSError:
        return None


def _stage(name: str, data: bytes) -> Path:
    """The new bytes in a temp file of the folder (mode 600 before any byte), fsynced; the caller renames it over
    NAME once the metadata is saved, or removes it."""
    d = files_dir()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=d)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return Path(tmp)


def _sweep(files: dict) -> None:
    """Under config._lock: remove what a crash left in the folder - temp files older than STALE_TMP_S and files with
    no metadata entry. A file that has an entry is never touched; folders are left alone. Never raises."""
    try:
        entries = list(files_dir().iterdir())
    except OSError:
        return
    now = time.time()
    for p in entries:
        try:
            if p.name in files or (p.is_dir() and not p.is_symlink()):
                continue
            if p.name.startswith(".") and p.name.endswith(".tmp") and now - p.lstat().st_mtime < STALE_TMP_S:
                continue
            p.unlink()
        except OSError:
            continue


def put(name: str, data: bytes | None = None, filename: str | None = None, note: str | None = None,
        expose: bool | None = None, create: bool = False) -> None:
    """Create or update. A new file needs `data`; omitted fields keep their value (no `data`: metadata only).
    `create`: only a new name (the "Add file" dialog must not replace a file of the same name)."""
    check_name(name)
    if data is not None and not 1 <= len(data) <= MAX_SIZE:
        raise VaultError(f"a file has 1 byte to {MAX_SIZE // 1024 // 1024} MiB", "invalid_value")
    with config._lock:                                   # read-modify-write of secrets.json
        s = config.load_secrets()
        if isinstance(s.get("vault"), dict) and name in s["vault"]:
            raise VaultError(f"{name} is already a text key", "name_taken")
        files = s.get("vault_files") if isinstance(s.get("vault_files"), dict) else {}
        if create and name in files:
            raise VaultError(f"a file named {name} already exists", "exists")
        cur: dict[str, Any] = dict(files.get(name) or {})
        if data is None and not cur:
            raise VaultError("a new file needs its content", "file_required")
        if note is not None:
            if not _is_text(note):
                raise VaultError("note must be valid text", "invalid_note")
            cur["note"] = note.strip()[:200]
        if expose is not None:
            cur["expose"] = bool(expose)
        if filename is not None or "filename" not in cur:
            cur["filename"] = clean_filename(filename, cur.get("filename") or name)
        cur.setdefault("note", "")
        cur.setdefault("expose", False)
        cur["updated"] = time.time()
        _sweep(files)
        tmp = None
        if data is not None:
            cur["size"] = len(data)
            cur["sha256"] = hashlib.sha256(data).hexdigest()
            tmp = _stage(name, data)
        before = files.get(name)
        files[name] = cur
        try:
            config.set_secret("vault_files", files)
        except BaseException:
            if tmp:                                         # the old bytes and the old entry stay together
                tmp.unlink(missing_ok=True)
            raise
        if tmp:
            try:
                os.replace(tmp, files_dir() / name)         # a reader sees the old or the new file, never half
            except BaseException:
                tmp.unlink(missing_ok=True)
                if before is None:
                    files.pop(name)
                else:
                    files[name] = before
                config.set_secret("vault_files", files or None)
                raise


def delete(name: str) -> bool:
    with config._lock:
        s = config.load_secrets()
        files = s.get("vault_files") if isinstance(s.get("vault_files"), dict) else {}
        _sweep(files)
        if name not in files:
            return False
        if NAME_RE.match(name):
            (files_dir() / name).unlink(missing_ok=True)
        files.pop(name)
        config.set_secret("vault_files", files or None)
    return True


def exposed_files_env() -> dict[str, str]:
    """{NAME: absolute path} of the files flagged `expose` that exist (never raises). The path, never the content."""
    try:
        return {k: str(files_dir() / k) for k, e in _meta().items()
                if e.get("expose") and NAME_RE.match(k) and k not in RESERVED and not k.startswith("MAXXING_")
                and path_of(k)}
    except Exception:
        return {}
