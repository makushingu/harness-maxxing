"""The trash: list, restore and purge what was deleted (files, folders, topics, projects, sessions).

Layout of state_dir('trash') (written by workspace.move_to_trash / trash_session):
    <stamp>-<label>             the deleted file or folder (a project / topic folder, a file...)
    <stamp>-<label>.json        sidecar {original, at, kind?, title?, path?}
    <stamp>-<label>.sessions/   sessions of a deleted project / topic (<sid>.json + <sid>.log)
    <stamp>-session-<slug>/     one deleted session (<sid>.json + <sid>.log), sidecar kind "session"
    backup-restore-<stamp>/     previous versions saved by a backup restore (no sidecar: listed, not
                                restorable from here - they mirror the workspace tree)
Items older than KEEP_DAYS are hidden from the list and purged when the trash is listed (at most once
per PURGE_EVERY_S).
Item sizes are cached per item, keyed by the (inode, mtime) of the item and of its .sessions folder.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from . import bus, config

KEEP_DAYS = 30
SKIP = {"skills"}                          # internal subfolders (cmd_core keeps old skills there)
PURGE_EVERY_S = 3600

_lock = threading.Lock()
_sizes: dict[str, tuple[tuple, int]] = {}  # item name -> (signature, bytes)
_purged = {"at": 0.0, "dir": ""}
_listing: dict[str, Any] = {"key": None, "items": []}   # the last listing, while no trash entry changed


class TrashError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def trash_dir() -> Path:
    return config.state_dir("trash")


def _size(p: Path) -> int:
    try:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    except OSError:
        return 0


def _sig(p: Path) -> tuple:
    try:
        st = p.stat()
    except OSError:
        return ()
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _item_size(p: Path) -> int:
    """Size of an item + its .sessions folder, walked again only when one of them changed."""
    sess = p.with_name(p.name + ".sessions")
    sig = (_sig(p), _sig(sess))
    with _lock:
        hit = _sizes.get(p.name)
    if hit and hit[0] == sig:
        return hit[1]
    n = _size(p) + _size(sess)
    with _lock:
        _sizes[p.name] = (sig, n)
    return n


def invalidate_sizes() -> None:
    """Forget cached sizes (after something wrote deep inside an existing item, e.g. a backup restore)
    and run the purge on the next listing."""
    with _lock:
        _sizes.clear()
        _listing["key"] = None
        _purged["at"] = 0.0


def _kind(item: Path, side: dict) -> str:
    if side.get("kind"):
        return str(side["kind"])
    name = re.sub(r"^\d{8}-\d{6}-", "", item.name)
    if name.startswith(("project-", "topic-")) and item.is_dir():
        return name.split("-", 1)[0]
    return "folder" if item.is_dir() else "file"


def _rel(original: str, root: Path | None = None) -> str:
    """Workspace-relative display of an original path (root: the resolved workspace, when known)."""
    try:
        return str(Path(original).relative_to(root or config.workspace().resolve()))
    except (ValueError, OSError):
        return original


def _sessions_of(item: Path) -> list[Path]:
    """Session metas kept with a deleted project / topic."""
    d = item.with_name(item.name + ".sessions")
    return sorted(d.glob("*.json")) if d.is_dir() else []


def _side(item: Path) -> dict:
    try:
        d = json.loads(item.with_name(item.name + ".json").read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _is_extra(p: Path) -> bool:
    """A sidecar or a .sessions folder - not a deleted "export.json", which has a sidecar of its own."""
    return p.name.endswith((".json", ".sessions")) and not p.with_name(p.name + ".json").exists()


def _entries() -> list[Path]:
    t = trash_dir()
    out = []
    for p in t.iterdir():
        if p.name in SKIP or _is_extra(p):
            continue
        out.append(p)
    return out


def list_items(purge: bool = True) -> list[dict[str, Any]]:
    """Most recent first -> [{id, kind, name, original, at, size, sessions, restorable}]."""
    t = trash_dir()
    if purge:
        with _lock:
            due = time.time() - _purged["at"] >= PURGE_EVERY_S or _purged["dir"] != str(t)
            if due:
                _purged.update(at=time.time(), dir=str(t))
        if due:
            purge_old()
    root = config.workspace().resolve()
    cutoff = time.time() - KEEP_DAYS * 86400
    key = (str(t), str(root), _dir_sig(t))
    with _lock:
        cached = _listing["items"] if _listing["key"] == key else None
    if cached is None:
        cached = _build(t, root)
        with _lock:
            _listing.update(key=key, items=cached)
    # expired items are hidden until the hourly purge removes them
    return [dict(i) for i in cached if not purge or i["at"] >= cutoff]


def _dir_sig(t: Path) -> tuple:
    """(name, inode, mtime, size) of every trash entry: a new, removed or rewritten item or sidecar,
    or a change at the top of an item folder or of its .sessions folder, changes it."""
    out = []
    try:
        with os.scandir(t) as it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                out.append((e.name, st.st_ino, st.st_mtime_ns, st.st_size))
    except OSError:
        return ()
    return tuple(sorted(out))


def _build(t: Path, root: Path) -> list[dict[str, Any]]:
    items = []
    entries = _entries()
    with _lock:                                    # drop sizes of items that are gone
        for name in set(_sizes) - {p.name for p in entries}:
            del _sizes[name]
    for p in entries:
        side = _side(p)
        try:
            at = float(side.get("at") or p.stat().st_mtime)
        except OSError:                            # removed meanwhile
            continue
        kind = "previous_versions" if not side and p.name.startswith("backup-restore-") else _kind(p, side)
        name = side.get("title") or (Path(side["original"]).name if side.get("original") and kind != "session"
                                      else re.sub(r"^\d{8}-\d{6}-", "", p.name))
        items.append({"id": p.name, "kind": kind, "name": name,
                      "original": side.get("path", "") if kind == "session" else _rel(side.get("original", ""), root),
                      "at": at, "size": _item_size(p),
                      "sessions": 1 if kind == "session" else len(_sessions_of(p)),
                      "restorable": bool(side.get("original"))})
    items.sort(key=lambda i: i["at"], reverse=True)
    return items


def _item(item_id: str) -> Path:
    if not item_id or "/" in item_id or item_id.startswith(".") or item_id in SKIP:
        raise TrashError(400, "bad_id", "Invalid trash item")
    p = trash_dir() / item_id
    if not p.exists() or _is_extra(p):
        raise TrashError(404, "not_found", "Not in the trash (already restored or deleted?)")
    return p


def _free(dest: Path) -> Path:
    """dest, or "<name> (restored)", "<name> (restored 2)"... when something has the name now."""
    if not dest.exists():
        return dest
    stem, suffix = (dest.stem, dest.suffix) if dest.is_file() or dest.suffix else (dest.name, "")
    n = 1
    while True:
        tag = " (restored)" if n == 1 else f" (restored {n})"
        cand = dest.with_name(f"{stem}{tag}{suffix}")
        if not cand.exists():
            return cand
        n += 1


def _free_dir_name(dest: Path) -> Path:
    """Topics and projects need slug names (at most 48 characters): "<name>-restored", "<name>-restored-2"...,
    the name cut to make room for the tag."""
    if not dest.exists():
        return dest
    n = 1
    while True:
        tag = "-restored" + ("" if n == 1 else f"-{n}")
        cand = dest.with_name(dest.name[:48 - len(tag)].rstrip("-") + tag)   # still a slug (workspace.SLUG_RE)
        if not cand.exists():
            return cand
        n += 1


def _put_sessions(folder: Path, old_prefix: str | None = None, new_prefix: str | None = None) -> int:
    """Move <sid>.json/.log from a trash folder back into the session store (paths remapped)."""
    from .sessions import store
    done = 0
    for meta_p in sorted(folder.glob("*.json")):
        sid = meta_p.stem
        if not store.is_valid_id(sid) or store.meta_path(sid).exists():
            continue
        try:
            meta = json.loads(meta_p.read_text())
        except (OSError, ValueError):
            continue
        path = meta.get("path") or ""
        if old_prefix is not None and new_prefix is not None and (path == old_prefix or path.startswith(old_prefix + "/")):
            meta["path"] = new_prefix + path[len(old_prefix):]
        meta["state"] = "idle" if meta.get("state") == "running" else meta.get("state", "idle")
        meta.update(pid=None, queue=[])
        config.write_json(store.meta_path(sid), meta)
        log_p = meta_p.with_suffix(".log")
        if log_p.exists():
            shutil.move(str(log_p), str(store.log_path(sid)))
        meta_p.unlink()
        done += 1
    shutil.rmtree(folder, ignore_errors=True)
    return done


def restore(item_id: str) -> dict[str, Any]:
    """Put an item back where it was (a free name next to it if the place is taken now)."""
    p = _item(item_id)
    side = _side(p)
    if not side.get("original"):
        raise TrashError(409, "not_restorable", "This item cannot be restored from here")
    kind = _kind(p, side)
    from . import workspace
    if kind == "session":
        path = side.get("path") or ""
        if not (workspace.root() / path).is_dir():          # its topic was deleted since: workspace root
            path = ""
        for mp in p.glob("*.json"):
            try:
                meta = json.loads(mp.read_text())
                meta["path"] = path
                config.write_json(mp, meta)
            except (OSError, ValueError):
                pass
        n = _put_sessions(p)
        p.with_name(p.name + ".json").unlink(missing_ok=True)
        bus.invalidate("sessions", "workspace", "trash")
        return {"ok": True, "kind": kind, "restored_to": path, "sessions": n}
    original = Path(side["original"])
    dest = _free_dir_name(original) if kind in ("project", "topic") else _free(original)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(dest))
    p.with_name(p.name + ".json").unlink(missing_ok=True)
    n = 0
    sess = p.with_name(p.name + ".sessions")
    if sess.is_dir():
        root = config.workspace().resolve()
        try:
            old = str(original.relative_to(root))
            new = str(dest.relative_to(root))
        except ValueError:
            old = new = None
        n = _put_sessions(sess, old, new)
    if kind in ("project", "topic"):
        try:
            workspace._changed("restored", kind, str(dest.relative_to(config.workspace().resolve())))  # noqa: SLF001
        except (ValueError, AttributeError):
            pass
    bus.invalidate("files", "workspace", "sessions", "trash")
    return {"ok": True, "kind": kind, "restored_to": _rel(str(dest)), "sessions": n}


def delete(item_id: str) -> None:
    p = _item(item_id)
    _remove(p)
    bus.invalidate("trash")


def _remove(p: Path) -> None:
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    else:
        p.unlink(missing_ok=True)
    p.with_name(p.name + ".json").unlink(missing_ok=True)
    shutil.rmtree(p.with_name(p.name + ".sessions"), ignore_errors=True)


def empty() -> int:
    items = _entries()
    for p in items:
        _remove(p)
    bus.invalidate("trash")
    return len(items)


def purge_old(days: int = KEEP_DAYS) -> int:
    cutoff = time.time() - days * 86400
    n = 0
    for p in _entries():
        at = float(_side(p).get("at") or p.stat().st_mtime)
        if at < cutoff:
            _remove(p)
            n += 1
    return n


def trash_session(sid: str) -> Path:
    """Move one session (meta + log) into the trash, restorable from Settings -> Trash."""
    from .sessions import store
    meta = store.read(sid) or {}
    slug = re.sub(r"[^a-z0-9]+", "-", (meta.get("title") or "session").lower()).strip("-")[:40] or "session"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest, n = trash_dir() / f"{stamp}-session-{slug}", 1
    while dest.exists():
        n += 1
        dest = trash_dir() / f"{stamp}-session-{slug}-{n}"
    dest.mkdir(parents=True)
    for ext in (".json", ".log"):
        src = store._path(sid, ext)                     # noqa: SLF001 - same package family
        if src.exists():
            shutil.move(str(src), str(dest / f"{sid}{ext}"))
    store.remove(sid)                                   # locks and run markers
    config.write_json(dest.with_name(dest.name + ".json"),
                      {"original": sid, "at": time.time(), "kind": "session",
                       "title": meta.get("title") or "Session", "path": meta.get("path") or ""})
    bus.invalidate("trash")
    return dest
