"""Workspace layout: projects and topics (folders Claude works in).

    <workspace>/CLAUDE.md, memory.md
    <workspace>/projects/<p>/CLAUDE.md, memory.md
    <workspace>/projects/<p>/topics/<t>/CLAUDE.md, memory.md

Each CLAUDE.md starts with a heading, the level's description, then `@memory.md` (Claude Code
imports the memory file). A session started in a topic folder therefore loads the workspace,
project and topic context (Claude Code reads every CLAUDE.md of the cwd and its parents).

*Topic path* = path relative to the workspace: "" (root), "projects/<p>", "projects/<p>/topics/<t>".
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import copy
import hashlib
import inspect
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Iterator

from . import bus, config

log = logging.getLogger("maxxing.workspace")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_PATH_RE = re.compile(r"^projects/([a-z0-9][a-z0-9-]{0,47})(?:/topics/([a-z0-9][a-z0-9-]{0,47}))?$")
_callbacks: list[Callable[..., Any]] = []


class WorkspaceError(Exception):
    """Error with an API code and HTTP status (mapped by api/workspace.py)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---- paths ---------------------------------------------------------------------------------
_root_now: contextvars.ContextVar[Path | None] = contextvars.ContextVar("workspace_root", default=None)


def root() -> Path:
    r = _root_now.get()
    return r if r is not None else config.workspace()


@contextlib.contextmanager
def _one_root() -> Iterator[None]:
    """Inside: root() is read once (a tree asks for it for every project and topic)."""
    token = _root_now.set(config.workspace())
    try:
        yield
    finally:
        _root_now.reset(token)


def check_slug(name: str) -> str:
    if not isinstance(name, str) or not SLUG_RE.match(name):
        raise WorkspaceError(400, "invalid_name",
                             "Use 1-48 lowercase letters, digits or dashes (starting with a letter or digit)")
    return name


def normalize_path(path: str | None) -> str:
    """Canonical topic path ("" for the root). ValueError when malformed."""
    p = (path or "").strip().strip("/")
    if p in ("", "."):
        return ""
    if not _PATH_RE.match(p):
        raise ValueError(f"invalid topic path: {path!r}")
    return p


def topic_dir(path: str) -> Path:
    """Folder of a topic path (must exist). ValueError when invalid or missing."""
    p = normalize_path(path)
    d = root() / p if p else root()
    if not d.is_dir():
        raise ValueError(f"topic not found: {path!r}")
    return d


def project_dir(project: str) -> Path:
    return root() / "projects" / project


def topic_path(project: str, topic: str | None = None) -> str:
    return f"projects/{project}" + (f"/topics/{topic}" if topic else "")


# ---- small files read on every tree / topic list --------------------------------------------
# The tree reads each project's and topic's CLAUDE.md and .maxxing.json: a parsed file is kept while its stat
# (inode, mtime, size, ctime) is unchanged. A file changed less than RACY_S ago is read again (a rewrite within
# the same timestamp tick and with the same size would look unchanged); the writes made here drop their entry.
RACY_S = 2.0
_files: dict[str, tuple[tuple, Any]] = {}
_FILES_MAX = 4096


def _cached(path: Path, parse: Callable[[Path], Any]) -> Any:
    key = str(path)
    try:
        st = os.stat(path)
        ident: tuple | None = (st.st_ino, st.st_mtime_ns, st.st_size, st.st_ctime_ns)
        settled = time.time() - max(st.st_mtime, st.st_ctime) > RACY_S
    except OSError:
        ident, settled = None, True
    hit = _files.get(key)
    if hit is not None and hit[0] == ident:
        return hit[1]
    value = parse(path)
    if settled:
        if len(_files) >= _FILES_MAX:
            _files.clear()
        _files[key] = (ident, value)
    else:
        _files.pop(key, None)
    return value


def _forget(path: Path) -> None:
    _files.pop(str(path), None)


# ---- CLAUDE.md -----------------------------------------------------------------------------
def _heading(kind: str, name: str) -> str:
    return "# Workspace" if kind == "workspace" else f"# {kind.capitalize()} {name}"


def _render_claude_md(kind: str, name: str, description: str) -> str:
    desc = description.strip()
    return _heading(kind, name) + "\n\n" + (desc + "\n\n" if desc else "") + "@memory.md\n"


def read_description(folder: Path) -> str:
    """Text between the first heading of CLAUDE.md and the `@memory.md` line (or next ## heading)."""
    return _cached(folder / "CLAUDE.md", _parse_description)


def _parse_description(f: Path) -> str:
    try:
        lines = f.read_text(errors="replace").splitlines()
    except OSError:
        return ""
    out, started = [], False
    for ln in lines:
        if not started:
            started = ln.startswith("# ")
            continue
        if ln.strip() == "@memory.md" or ln.startswith("## "):
            break
        out.append(ln)
    return "\n".join(out).strip()


def _write_claude_md(folder: Path, kind: str, name: str, description: str | None) -> None:
    """Rewrite heading (+ description when given) keeping whatever the user added after it."""
    f = folder / "CLAUDE.md"
    try:
        lines = f.read_text(errors="replace").splitlines()
    except OSError:
        lines = []
    desc = read_description(folder) if description is None else description
    _forget(f)
    if not lines or not any(ln.startswith("# ") for ln in lines):
        f.write_text(_render_claude_md(kind, name, desc))
        return
    start = next(i for i, ln in enumerate(lines) if ln.startswith("# "))
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() == "@memory.md" or lines[i].startswith("## ")), len(lines))
    head = [_heading(kind, name), ""] + ([desc.strip(), ""] if desc.strip() else [])
    rest = lines[end:] or ["@memory.md"]
    f.write_text("\n".join(lines[:start] + head + rest) + "\n")


def _init_level(folder: Path, kind: str, name: str, description: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / "CLAUDE.md").exists():
        (folder / "CLAUDE.md").write_text(_render_claude_md(kind, name, description))
    if not (folder / "memory.md").exists():
        title = "Workspace" if kind == "workspace" else f"{kind.capitalize()} {name}"
        (folder / "memory.md").write_text(f"# {title} - memory\n\n")


def ensure_root() -> Path:
    """Create the workspace root files when missing (idempotent)."""
    r = root()
    _init_level(r, "workspace", "", "Shared context for every session. Each project and topic below "
                "has its own CLAUDE.md and memory.md.")
    (r / "projects").mkdir(exist_ok=True)
    return r


# ---- tree ----------------------------------------------------------------------------------
def _session_stats() -> dict[str, dict[str, int]]:
    """path -> {sessions, archived, running, unread} (archived sessions excluded from sessions/unread)."""
    try:
        from .sessions import service
        sessions = service.list_sessions(archived=None)
    except Exception:
        log.exception("session stats failed")
        return {}
    stats: dict[str, dict[str, int]] = {}
    for s in sessions:
        st = stats.setdefault(s["path"], {"sessions": 0, "archived": 0, "running": 0, "unread": 0})
        st["archived" if s["archived"] else "sessions"] += 1
        st["running"] += s["state"] == "running"
        st["unread"] += bool(s["unread"]) and not s["archived"]
    return stats


def _topic_obj(project: str, name: str, stats: dict, threads: dict) -> dict:
    path = topic_path(project, name)
    st = stats.get(path, {})
    thread = threads.get(path)
    folder = project_dir(project) / "topics" / name
    mode = _folder_meta(folder).get("permission_mode")
    return {"name": name, "project": project, "path": path,
            "description": read_description(folder),
            "permission_mode": mode if mode in PERMISSION_MODES else "",
            "session_count": st.get("sessions", 0), "archived_count": st.get("archived", 0), "running": st.get("running", 0),
            "unread": st.get("unread", 0), "telegram_thread": thread if isinstance(thread, int) else None}


def _dirs(folder: Path) -> list[str]:
    try:
        return sorted(p.name for p in folder.iterdir() if p.is_dir() and SLUG_RE.match(p.name))
    except OSError:
        return []


# ---- order chosen by drag and drop in the Sessions tree ------------------------------------------
# Projects: projects/.order.json {"projects": [...]}; topics: "topics" in projects/<p>/.maxxing.json (moves with
# the project). Names not listed (new ones) come after, alphabetically; stale names are ignored.
ORDER_FILE = ".order.json"


def _ordered(names: list[str], order: object) -> list[str]:
    order = [n for n in order if isinstance(n, str)] if isinstance(order, list) else []
    rank = {n: i for i, n in enumerate(dict.fromkeys(order))}
    return sorted(names, key=lambda n: (0, rank[n]) if n in rank else (1, n))


def _parse_order(f: Path) -> object:
    try:
        return json.loads(f.read_text()).get("projects")
    except (OSError, ValueError, AttributeError):
        return None


def project_names() -> list[str]:
    return _ordered(_dirs(root() / "projects"), _cached(root() / "projects" / ORDER_FILE, _parse_order))


def topic_names(project: str) -> list[str]:
    return _ordered(_dirs(project_dir(project) / "topics"), _meta(project).get("topics"))


def set_project_order(names: list[str]) -> list[str]:
    known = set(_dirs(root() / "projects"))
    order = [n for n in dict.fromkeys(names) if isinstance(n, str) and n in known]
    config.write_json(root() / "projects" / ORDER_FILE, {"projects": order})
    _forget(root() / "projects" / ORDER_FILE)
    bus.invalidate("workspace")                       # order only: no rename/delete for the Telegram hooks
    return project_names()


def set_topic_order(project: str, names: list[str]) -> list[str]:
    if not project_dir(check_slug(project)).is_dir():
        raise WorkspaceError(404, "not_found", f"Project {project!r} not found")
    known = set(_dirs(project_dir(project) / "topics"))
    meta = _meta(project)
    meta["topics"] = [n for n in dict.fromkeys(names) if isinstance(n, str) and n in known]
    _forget(project_dir(project) / META_FILE)
    config.write_json(project_dir(project) / META_FILE, meta)
    bus.invalidate("workspace")
    return topic_names(project)


def _rename_in_order(names: list, old: str, new: str) -> list:
    return [new if n == old else n for n in names] if isinstance(names, list) else names


# ---- folder settings: project emoji, topic permission mode (<folder>/.maxxing.json: moves with the folder) ----
META_FILE = ".maxxing.json"
PERMISSION_MODES = ("bypass", "acceptEdits", "default")


def _parse_meta(f: Path) -> dict:
    try:
        data = json.loads(f.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _folder_meta(folder: Path) -> dict:
    """<folder>/.maxxing.json - a copy the caller may change."""
    return copy.deepcopy(_cached(folder / META_FILE, _parse_meta))


def _set_folder_meta(folder: Path, key: str, value: str) -> None:
    meta = _folder_meta(folder)
    if value:
        meta[key] = value
    else:
        meta.pop(key, None)
    _forget(folder / META_FILE)
    if meta:
        config.write_json(folder / META_FILE, meta)
    else:
        (folder / META_FILE).unlink(missing_ok=True)


def _meta(project: str) -> dict:
    return _folder_meta(project_dir(project))


def topic_permission_mode(path: str) -> str:
    """The topic's own permission mode for Claude turns ("" = the global setting). `path` = projects/<p>/topics/<t>."""
    try:
        mode = _folder_meta(topic_dir(path)).get("permission_mode")
    except (ValueError, OSError):
        return ""
    return mode if mode in PERMISSION_MODES else ""


def check_permission_mode(value: str) -> str:
    v = (value or "").strip()
    if v and v not in PERMISSION_MODES:
        raise WorkspaceError(400, "bad_permission_mode", "permission_mode: bypass, acceptEdits, default or empty")
    return v


def project_emoji(project: str) -> str:
    """The emoji the user chose for a project ("" when none)."""
    e = _meta(project).get("emoji")
    return e if isinstance(e, str) else ""


def check_emoji(value: str) -> str:
    """One emoji (a few code points: flags, skin tones, ZWJ sequences) - not words."""
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) > 8 or any(c.isspace() or c.isascii() and c.isalnum() for c in v) or all(c.isascii() for c in v):
        raise WorkspaceError(400, "bad_emoji", "Use a single emoji")
    return v


def set_project_emoji(project: str, emoji: str) -> None:
    _set_folder_meta(project_dir(project), "emoji", emoji)


def _project_obj(name: str, stats: dict, threads: dict) -> dict:
    topics = [_topic_obj(name, t, stats, threads) for t in topic_names(name)]
    own = stats.get(topic_path(name), {}).get("sessions", 0)
    return {"name": name, "path": topic_path(name), "description": read_description(project_dir(name)),
            "emoji": project_emoji(name), "topics": topics, "session_count": own + sum(t["session_count"] for t in topics)}


def tree() -> dict:
    stats = _session_stats()
    threads = config.load_config().get("telegram", {}).get("threads") or {}
    with _one_root():
        projects = [_project_obj(p, stats, threads) for p in project_names()]
        return {"root": str(root()), "projects": projects}


def list_topics() -> list[dict]:
    out = []
    with _one_root():
        for p in project_names():
            for t in topic_names(p):
                out.append({"path": topic_path(p, t), "project": p, "name": t,
                            "description": read_description(project_dir(p) / "topics" / t)})
    return out


def get_project(name: str) -> dict:
    if not project_dir(check_slug(name)).is_dir():
        raise WorkspaceError(404, "not_found", f"Project {name!r} not found")
    return _project_obj(name, _session_stats(), config.load_config().get("telegram", {}).get("threads") or {})


def get_topic(project: str, name: str) -> dict:
    if not (project_dir(check_slug(project)) / "topics" / check_slug(name)).is_dir():
        raise WorkspaceError(404, "not_found", f"Topic {project}/{name} not found")
    return _topic_obj(project, name, _session_stats(), config.load_config().get("telegram", {}).get("threads") or {})


# ---- mutations -----------------------------------------------------------------------------
def create_project(name: str, description: str = "") -> dict:
    check_slug(name)
    ensure_root()
    d = project_dir(name)
    if d.exists():
        raise WorkspaceError(409, "exists", f"Project {name!r} already exists")
    _init_level(d, "project", name, description or "")
    (d / "topics").mkdir(exist_ok=True)
    _changed("created", "project", topic_path(name))
    return get_project(name)


def create_topic(project: str, name: str, description: str = "") -> dict:
    check_slug(name)
    if not project_dir(check_slug(project)).is_dir():
        raise WorkspaceError(404, "not_found", f"Project {project!r} not found")
    d = project_dir(project) / "topics" / name
    if d.exists():
        raise WorkspaceError(409, "exists", f"Topic {project}/{name} already exists")
    _init_level(d, "topic", name, description or "")
    _changed("created", "topic", topic_path(project, name))
    return get_topic(project, name)


def update_project(project: str, name: str | None = None, description: str | None = None,
                   emoji: str | None = None) -> dict:
    d = project_dir(check_slug(project))
    if not d.is_dir():
        raise WorkspaceError(404, "not_found", f"Project {project!r} not found")
    if emoji is not None:
        set_project_emoji(project, check_emoji(emoji))
    new = project
    if name and name != project:
        new = check_slug(name)
        _rename(topic_path(project), topic_path(new))
        try:
            f = root() / "projects" / ORDER_FILE
            data = json.loads(f.read_text())
            data["projects"] = _rename_in_order(data.get("projects"), project, new)
            _forget(f)
            config.write_json(f, data)
        except (OSError, ValueError, AttributeError):
            pass
    _write_claude_md(project_dir(new), "project", new, description)
    if new != project:
        _changed("renamed", "project", topic_path(new), topic_path(project))
    else:
        _changed("updated", "project", topic_path(new))
    return get_project(new)


def update_topic(project: str, topic: str, name: str | None = None, description: str | None = None,
                 permission_mode: str | None = None) -> dict:
    d = project_dir(check_slug(project)) / "topics" / check_slug(topic)
    if not d.is_dir():
        raise WorkspaceError(404, "not_found", f"Topic {project}/{topic} not found")
    if permission_mode is not None:
        _set_folder_meta(d, "permission_mode", check_permission_mode(permission_mode))
    new = topic
    if name and name != topic:
        new = check_slug(name)
        _rename(topic_path(project, topic), topic_path(project, new))
        meta = _meta(project)
        if isinstance(meta.get("topics"), list):
            meta["topics"] = _rename_in_order(meta["topics"], topic, new)
            _forget(project_dir(project) / META_FILE)
            config.write_json(project_dir(project) / META_FILE, meta)
    _write_claude_md(project_dir(project) / "topics" / new, "topic", new, description)
    if new != topic:
        _changed("renamed", "topic", topic_path(project, new), topic_path(project, topic))
    else:
        _changed("updated", "topic", topic_path(project, new))
    return get_topic(project, new)


def delete_project(project: str) -> None:
    d = project_dir(check_slug(project))
    if not d.is_dir():
        raise WorkspaceError(404, "not_found", f"Project {project!r} not found")
    _delete(topic_path(project), "project")


def delete_topic(project: str, topic: str) -> None:
    d = project_dir(check_slug(project)) / "topics" / check_slug(topic)
    if not d.is_dir():
        raise WorkspaceError(404, "not_found", f"Topic {project}/{topic} not found")
    _delete(topic_path(project, topic), "topic")


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _sessions_under(prefix: str) -> list[dict]:
    from .sessions import service
    return [s for s in service.list_sessions(archived=None) if _under(s["path"], prefix)]


def _ensure_idle(prefix: str) -> list[dict]:
    sessions = _sessions_under(prefix)
    if any(s["state"] == "running" for s in sessions):
        raise WorkspaceError(409, "has_running_sessions", "Stop the running sessions first")
    return sessions


def _rename(old: str, new: str) -> None:
    """Move the folder, then remap session paths, Claude transcripts and Telegram mappings."""
    sessions = _ensure_idle(old)
    src, dst = root() / old, root() / new
    if dst.exists():
        raise WorkspaceError(409, "exists", f"{new} already exists")
    shutil.move(str(src), str(dst))
    from .sessions import service
    service.remap_paths(old, new, sessions)
    _remap_telegram(old, new)


def _remap_telegram(old: str, new: str) -> None:
    """Keep telegram.threads / telegram.sessions keyed by the new topic paths."""
    with config._lock:
        cfg = config.load_config()
        tg = cfg.get("telegram") or {}
        changed = False
        for key in ("threads", "sessions"):
            m = tg.get(key) or {}
            for k in [k for k in m if _under(k, old)]:
                m[new + k[len(old):]] = m.pop(k)
                changed = True
        if changed:
            config.save_config(cfg)


def _delete(prefix: str, kind: str) -> None:
    sessions = _ensure_idle(prefix)
    dest = move_to_trash(root() / prefix, label=f"{kind}-{prefix.rsplit('/', 1)[-1]}")
    from .sessions import service
    service.trash_sessions([s["id"] for s in sessions], dest.parent / (dest.name + ".sessions"))
    _changed("deleted", kind, prefix)


def move_to_trash(src: Path, label: str | None = None) -> Path:
    """Move a file/folder into state_dir('trash') with a `.json` sidecar keeping its origin."""
    trash = config.state_dir("trash")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    label = label or src.name
    raw = os.fsencode(label)
    if len(raw) > 200:                                   # room for the stamp, "-<n>" and ".sessions" (255 bytes)
        # decode, not fsdecode: a cut inside a multi-byte character would leave lone surrogates in the item id,
        # which the trash listing then fails to encode (500 on the whole Trash page)
        label = raw[:180].decode("utf-8", "ignore") + "-" + hashlib.sha1(raw).hexdigest()[:10]
    base = f"{stamp}-{label}"
    dest, n = trash / base, 1
    while dest.exists() or dest.with_name(dest.name + ".json").exists():
        n += 1
        dest = trash / f"{base}-{n}"
    shutil.move(str(src), str(dest))
    side: dict = {"original": str(src), "at": time.time()}
    if label and label.split("-", 1)[0] in ("project", "topic"):
        side["kind"] = label.split("-", 1)[0]
    config.write_json(dest.with_name(dest.name + ".json"), side)
    bus.invalidate("trash")
    return dest


# ---- change notifications ------------------------------------------------------------------
def on_change(cb: Callable[..., Any]) -> None:
    """Register `cb()` or `cb(change)` (sync or async), called after any project/topic create,
    update, rename or delete. change = {action, kind, path, old_path}."""
    _callbacks.append(cb)


def _changed(action: str, kind: str, path: str, old_path: str | None = None) -> None:
    change = {"action": action, "kind": kind, "path": path, "old_path": old_path}
    for cb in list(_callbacks):
        try:
            res = cb(change) if _wants_arg(cb) else cb()
            if inspect.isawaitable(res):
                _schedule(res)
        except Exception:
            log.exception("workspace on_change callback failed")
    bus.invalidate("workspace", "sessions")


def _wants_arg(cb: Callable[..., Any]) -> bool:
    try:
        params = [p for p in inspect.signature(cb).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)]
    except (TypeError, ValueError):
        return True
    return bool(params)


def _schedule(coro: Any) -> None:
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        loop = bus._loop
        if loop is not None:
            asyncio.run_coroutine_threadsafe(coro, loop)
        else:
            coro.close()


def describe(path: str) -> dict:
    """Small helper for other modules: {path, project, name, description} of a topic path."""
    p = normalize_path(path)
    m = _PATH_RE.match(p) if p else None
    folder = topic_dir(p)
    return {"path": p, "project": m.group(1) if m else None,
            "name": (m.group(2) or m.group(1)) if m else "", "description": read_description(folder)}

