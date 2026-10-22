"""Tasks kanban backed by `<workspace>/tasks.json`. See docs/dev/API.md#tasks.

The file is plain JSON that Claude may edit at any time, so:
- it is re-read on every request (cached by mtime/size only),
- unknown fields (top level, tasks, projects) are preserved on write,
- a corrupt file is never overwritten: requests fail with 409 `corrupt_file` until it is fixed,
- writes are atomic (config.write_json) and serialised by a process lock,
- a write never erases an edit made to the file since the request read it: the change is re-applied on the
  fresh file (`_retry_on_change`), `409 conflict` if the file keeps changing.
A watcher notices external edits (mtime poll every 2 s) and invalidates the "tasks" bus topic.

Every workspace project has a linked task project (`workspace: <project name>`), created on demand (`sync_workspace`, run
by GET and by the workspace change hook), renamed with it and unlinked (kept, as a free project) when it is deleted.
Free task projects (no `workspace`) are still allowed, and so are tasks without a project.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import datetime as dt
import functools
import hashlib
import json
import math
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import bus, config
from ..security import require_auth

router = APIRouter(prefix="/api/tasks", tags=["tasks"], dependencies=[Depends(require_auth)])

STATUSES = ("todo", "doing", "done")
_lock = threading.RLock()
_cache: dict[str, Any] = {"sig": None, "data": None}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CorruptFile(Exception):
    pass


class _Changed(Exception):
    """tasks.json was written by someone else (Claude, an editor) between this request's load() and save()."""


# ---- storage --------------------------------------------------------------------------------
def tasks_path() -> Path:
    return config.workspace() / "tasks.json"


def _sig(p: Path) -> tuple | None:
    try:
        st = os.stat(p)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _text(v: Any) -> str:
    """A hand-written field that should be text: kept as is, else written out (a list of notes, a number)."""
    if isinstance(v, str):
        return v
    if v is None or v == [] or v == {} or v is False:
        return ""
    return json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (list, dict)) else str(v)


def _num(v: Any, default: Any) -> Any:
    """A timestamp: a number, or text a hand-written task may hold ("1767225600", "2026-10-01")."""
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip()):
        try:
            f = float(v)
            return f if math.isfinite(f) else default      # 1e999 / NaN: not JSON, the response would fail
        except OverflowError:                              # an integer with hundreds of digits
            return default
        except ValueError:
            pass
    if isinstance(v, str) and v.strip():
        try:
            d = dt.datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
            return (d if d.tzinfo else d.astimezone()).timestamp()
        except ValueError:
            pass
    return default


def _norm_task(t: dict) -> dict:
    """Fill defaults for a task written by hand (keeps unknown keys)."""
    now = time.time()
    out = dict(t)
    out["id"] = _text(out.get("id"))
    out["title"] = _text(out.get("title"))
    out["notes"] = _text(out.get("notes"))
    if out.get("status") not in STATUSES:
        out["status"] = "todo"
    try:
        out["priority"] = min(3, max(0, int(out.get("priority") or 0)))
    except (TypeError, ValueError, OverflowError):     # OverflowError: 1e999 is read as infinity
        out["priority"] = 0
    if not (isinstance(out.get("due"), str) and _DATE.match(out["due"])):
        out["due"] = None
    for key in ("project_id", "topic_path"):
        out[key] = _text(out.get(key)) or None
    labels = out.get("labels")
    out["labels"] = [str(x) for x in labels] if isinstance(labels, list) else []
    out["created"] = _num(out.get("created"), now)
    out["updated"] = _num(out.get("updated"), out["created"])
    out["done_at"] = _num(out.get("done_at"), None)
    try:
        out["order"] = float(out.get("order") or 0)
        if not math.isfinite(out["order"]):
            out["order"] = 0.0
    except (TypeError, ValueError, OverflowError):
        out["order"] = 0.0
    return out


def load(copy_: bool = True) -> dict:
    """-> {"version", "projects", "tasks", ...unknown keys}; raises CorruptFile.
    copy_=False returns the shared cached object (no deepcopy): read-only callers only, never mutate it."""
    p = tasks_path()
    with _lock:
        sig = _sig(p)
        if sig is not None and sig == _cache["sig"]:
            return copy.deepcopy(_cache["data"]) if copy_ else _cache["data"]
        if sig is None:
            data: dict = {"version": 1, "projects": [], "tasks": []}
        else:
            try:
                data = json.loads(p.read_text() or "{}")
            except ValueError as e:
                raise CorruptFile(f"tasks.json is not valid JSON ({e})") from None
            except OSError as e:
                raise CorruptFile(f"tasks.json cannot be read ({e})") from None
            if isinstance(data, list):                 # tolerate a bare list of tasks
                data = {"version": 1, "projects": [], "tasks": data}
            if not isinstance(data, dict):
                raise CorruptFile("tasks.json must contain an object")
        data.setdefault("version", 1)
        for k in ("projects", "tasks"):
            if not isinstance(data.get(k) or [], list):
                raise CorruptFile(f'tasks.json: "{k}" must be a list')
        data["projects"] = [x for x in (data.get("projects") or []) if isinstance(x, dict) and x.get("id")]
        for proj in data["projects"]:
            if "workspace" in proj and not isinstance(proj["workspace"], str):   # a list is not a dict key: _sync failed
                proj.pop("workspace")
        tasks = []
        for t in data.get("tasks") or []:
            if isinstance(t, dict):
                if not t.get("id"):                    # hand-written task: stable id until saved
                    digest = hashlib.sha1(json.dumps(t, sort_keys=True, default=str).encode()).hexdigest()
                    t = {**t, "id": f"t_{digest[:6]}"}
                tasks.append(_norm_task(t))
        data["tasks"] = tasks
        _cache["sig"], _cache["data"] = sig, (copy.deepcopy(data) if copy_ else data)
        return data


def save(data: dict) -> None:
    """Write `data` (loaded by this request under `_lock`); raises _Changed when the file changed meanwhile."""
    with _lock:
        if _sig(tasks_path()) != _cache["sig"]:
            _cache["sig"] = None
            raise _Changed()
        config.write_json(tasks_path(), data)
        _cache["sig"], _cache["data"] = _sig(tasks_path()), copy.deepcopy(data)
    bus.invalidate("tasks")


# ---- workspace projects <-> task projects ---------------------------------------------------
_TOPIC_PROJECT = re.compile(r"^projects/([^/]+)")
_HIDDEN_BY_DEFAULT = {"system"}       # the product's own project: still listed, hidden from the sidebar until shown


def _ws_project(topic_path: str | None) -> str | None:
    m = _TOPIC_PROJECT.match(topic_path or "")
    return m.group(1) if m else None


def _workspace_names() -> list[str] | None:
    """Workspace project names in the workspace order, None when the workspace cannot be read."""
    from .. import workspace
    try:
        if not (workspace.root() / "projects").is_dir():
            return None
        return workspace.project_names()
    except Exception:
        return None


def _next_color(data: dict) -> str:
    used = [p.get("color") for p in data["projects"]]
    palette = ["clay", "blue", "violet", "green", "amber", "rose", "teal", "zinc"]
    return min(palette, key=lambda c: (used.count(c), palette.index(c)))


def _sync(data: dict, names: list[str]) -> bool:
    """Link/create one task project per workspace project and fill project_id from topic_path; True when changed."""
    from .. import workspace
    changed = False
    projects = data["projects"]
    linked = {p.get("workspace"): p for p in projects if p.get("workspace")}
    for name in names:
        if name in linked:
            continue
        proj = next((p for p in projects if not p.get("workspace") and str(p.get("name", "")).lower() == name.lower()), None)
        if proj is None:
            proj = {"id": _new_id("p_", 4), "name": name, "color": _next_color(data)}
            while any(p["id"] == proj["id"] for p in projects):
                proj["id"] = _new_id("p_", 4)
            if name in _HIDDEN_BY_DEFAULT:
                proj["hidden"] = True
            projects.append(proj)
        proj["workspace"] = name
        linked[name] = proj
        changed = True
    for proj in projects:                           # linked to a folder that is gone (deleted by hand): free project
        ws = proj.get("workspace")
        if ws and ws not in names and not workspace.project_dir(ws).is_dir():
            proj.pop("workspace", None)
            linked.pop(ws, None)
            changed = True
    for t in data["tasks"]:
        if not t.get("project_id"):
            proj = linked.get(_ws_project(t.get("topic_path")))
            if proj:
                t["project_id"] = proj["id"]
                changed = True
    return changed


_synced: dict[str, Any] = {"key": None}


def sync_workspace() -> None:
    """Make sure every workspace project has its task project (cheap when nothing changed)."""
    names = _workspace_names()
    if names is None:
        return
    for _ in range(3):
        with _lock:
            sig = _sig(tasks_path())
            if sig is not None and sig == _cache["sig"] and (tuple(names), sig) == _synced["key"]:
                return                                 # nothing changed: skip the copy load() makes
            try:
                data = load()
            except CorruptFile:
                return
            key = (tuple(names), _cache["sig"])
            if key == _synced["key"]:
                return
            try:
                if _sync(data, names):
                    save(data)
            except _Changed:
                continue
            _synced["key"] = (tuple(names), _cache["sig"])
            return


def _rewrite_topic_paths(data: dict, old: str, new: str | None) -> bool:
    changed = False
    for t in data["tasks"]:
        tp = t.get("topic_path") or ""
        if tp == old or tp.startswith(old + "/"):
            t["topic_path"] = (new + tp[len(old):]) if new else None
            changed = True
    return changed


def on_workspace_change(change: dict) -> None:
    """Follow the workspace: a renamed project/topic keeps its tasks, a deleted project leaves a free task project."""
    action, kind = change.get("action"), change.get("kind")
    path, old = change.get("path") or "", change.get("old_path") or ""
    for _ in range(3):
        with _lock:
            try:
                data = load()
            except CorruptFile:
                return
            changed = False
            if action == "renamed" and old:
                changed = _rewrite_topic_paths(data, old, path)
                if kind == "project":
                    o, n = _ws_project(old), _ws_project(path)
                    for proj in data["projects"]:
                        if proj.get("workspace") == o:
                            proj["workspace"] = n
                            if proj.get("name") == o:
                                proj["name"] = n
                            changed = True
            elif action == "deleted":
                if kind == "project":
                    name = _ws_project(path)
                    for proj in data["projects"]:
                        if proj.get("workspace") == name:
                            proj.pop("workspace", None)
                            changed = True
                else:
                    changed = _rewrite_topic_paths(data, path, None)
            try:
                if changed:
                    save(data)
            except _Changed:
                continue
            break
    sync_workspace()


def _new_id(prefix: str, n: int) -> str:
    return prefix + secrets.token_hex(n)[:n]


def _today() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(config.load_config().get("timezone") or "UTC")).date()
    except Exception:
        return dt.date.today()


def summary() -> dict:
    """Counts used by the dashboard widget: {doing, due_today, overdue, open, items:[task]}."""
    try:
        data = load(copy_=False)
    except CorruptFile as e:
        return {"error": str(e)}
    today = _today().isoformat()
    open_ = [t for t in data["tasks"] if t["status"] != "done"]
    overdue = [t for t in open_ if t["due"] and t["due"] < today]
    due_today = [t for t in open_ if t["due"] == today]
    doing = [t for t in open_ if t["status"] == "doing"]
    items = sorted(overdue, key=lambda t: t["due"]) + due_today + [t for t in doing if t not in overdue + due_today]
    return {"open": len(open_), "doing": len(doing), "due_today": len(due_today),
            "overdue": len(overdue), "items": items, "today": today}


# ---- validation -----------------------------------------------------------------------------
class TaskIn(BaseModel):
    model_config = {"extra": "ignore"}
    title: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[Literal["todo", "doing", "done"]] = None
    priority: Optional[int] = None
    due: Optional[str] = None
    project_id: Optional[str] = None
    topic_path: Optional[str] = None
    labels: Optional[list[str]] = None
    order: Optional[float] = None


class ProjectIn(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    hidden: Optional[bool] = None


def _err(status: int, code: str, msg: str) -> HTTPException:
    return HTTPException(status, detail={"error": code, "message": msg})


def _apply(task: dict, body: TaskIn, data: dict, fields: set[str]) -> None:
    if "title" in fields:
        title = (body.title or "").strip()
        if not title or len(title) > 500:
            raise _err(400, "invalid_title", "title is required (max 500 characters)")
        task["title"] = title
    if "notes" in fields:
        task["notes"] = body.notes or ""
    if "priority" in fields:
        if body.priority is None or not 0 <= body.priority <= 3:
            raise _err(400, "invalid_priority", "priority is 0, 1, 2 or 3")
        task["priority"] = body.priority
    if "due" in fields:
        due = body.due or None
        if due is not None:
            try:
                dt.date.fromisoformat(due)
                if not _DATE.match(due):
                    raise ValueError
            except ValueError:
                raise _err(400, "invalid_due", "due must be YYYY-MM-DD") from None
        task["due"] = due
    if "project_id" in fields:
        pid = body.project_id or None
        if pid and not any(p["id"] == pid for p in data["projects"]):
            raise _err(400, "invalid_project", f"no task project {pid}")
        task["project_id"] = pid
    if "topic_path" in fields:
        tp = (body.topic_path or "").strip().strip("/")
        if tp and (".." in tp.split("/") or tp.startswith("~")):
            raise _err(400, "invalid_topic", "topic_path must be relative to the workspace")
        task["topic_path"] = tp or None
        if tp and "project_id" not in fields and not task.get("project_id"):
            proj = next((p for p in data["projects"] if p.get("workspace") and p["workspace"] == _ws_project(tp)), None)
            if proj:
                task["project_id"] = proj["id"]
    if "labels" in fields:
        labels = []
        for x in body.labels or []:
            x = str(x).strip()[:40]
            if x and x not in labels:
                labels.append(x)
        task["labels"] = labels
    if "status" in fields and body.status:
        if body.status == "done" and task.get("status") != "done":
            task["done_at"] = time.time()
        elif body.status != "done":
            task["done_at"] = None
        task["status"] = body.status
    if "order" in fields and body.order is not None:
        task["order"] = float(body.order)


def _retry_on_change(fn):
    """Run a read-modify-write handler again on the fresh file when an external edit lands between its load()
    and save() (nothing was written by the failed attempt); 409 conflict if that keeps happening."""
    @functools.wraps(fn)
    def run(*args, **kwargs):
        for _ in range(3):
            try:
                return fn(*args, **kwargs)
            except _Changed:
                continue
        raise _err(409, "conflict", "tasks.json keeps changing - try again in a moment")
    return run


def _guard(copy_: bool = True):
    try:
        return load(copy_)
    except CorruptFile as e:
        raise _err(409, "corrupt_file", str(e)) from None


# ---- tasks ----------------------------------------------------------------------------------
@router.get("")
def list_tasks():
    sync_workspace()
    data = _guard(copy_=False)
    # already plain JSON (read from tasks.json): skip jsonable_encoder, ~150 ms for 5000 tasks
    return JSONResponse({"projects": data["projects"], "tasks": data["tasks"]})


@router.post("")
@_retry_on_change
def create_task(body: TaskIn):
    fields = set(body.model_fields_set)
    if "title" not in fields:
        raise _err(400, "invalid_title", "title is required")
    with _lock:
        data = _guard()
        now = time.time()
        task: dict = _norm_task({"id": _new_id("t_", 6), "created": now, "updated": now})
        _apply(task, body, data, fields | {"title"})
        if "order" not in fields or body.order is None:
            same = [t["order"] for t in data["tasks"] if t["status"] == task["status"]]
            task["order"] = (max(same) + 1.0) if same else 1.0
        while any(t["id"] == task["id"] for t in data["tasks"]):
            task["id"] = _new_id("t_", 6)
        data["tasks"].append(task)
        save(data)
    return task


@router.patch("/projects/{pid}")
@_retry_on_change
def patch_project(pid: str, body: ProjectIn):
    with _lock:
        data = _guard()
        proj = next((p for p in data["projects"] if p["id"] == pid), None)
        if proj is None:
            raise _err(404, "not_found", f"no task project {pid}")
        _apply_project(proj, body)
        save(data)
    return proj


@router.delete("/projects/{pid}")
@_retry_on_change
def delete_project(pid: str):
    with _lock:
        data = _guard()
        proj = next((p for p in data["projects"] if p["id"] == pid), None)
        if proj is None:
            raise _err(404, "not_found", f"no task project {pid}")
        if proj.get("workspace") and proj["workspace"] in (_workspace_names() or []):
            raise _err(409, "linked_project", "this task project follows a workspace project: hide it instead")
        data["projects"] = [p for p in data["projects"] if p["id"] != pid]
        for t in data["tasks"]:
            if t.get("project_id") == pid:
                t["project_id"] = None
        save(data)
    return {"ok": True}


@router.post("/projects")
@_retry_on_change
def create_project(body: ProjectIn):
    if not (body.name or "").strip():
        raise _err(400, "invalid_name", "name is required")
    with _lock:
        data = _guard()
        proj = {"id": _new_id("p_", 4), "name": "", "color": "zinc"}
        while any(p["id"] == proj["id"] for p in data["projects"]):
            proj["id"] = _new_id("p_", 4)
        _apply_project(proj, body)
        data["projects"].append(proj)
        save(data)
    return proj


def _apply_project(proj: dict, body: ProjectIn) -> None:
    if body.name is not None:
        name = body.name.strip()
        if not name or len(name) > 80:
            raise _err(400, "invalid_name", "name is required (max 80 characters)")
        proj["name"] = name
    if body.color is not None:
        color = body.color.strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}|[a-z]{3,16}", color):
            raise _err(400, "invalid_color", "color is a palette name (e.g. blue) or #rrggbb")
        proj["color"] = color
    if body.hidden is not None:
        if body.hidden:
            proj["hidden"] = True
        else:
            proj.pop("hidden", None)


class BulkIn(BaseModel):
    model_config = {"extra": "ignore"}
    ids: list[str]
    patch: Optional[TaskIn] = None
    labels_add: Optional[list[str]] = None
    labels_remove: Optional[list[str]] = None
    delete: bool = False


BULK_MAX = 1000


@router.post("/bulk")
@_retry_on_change
def bulk_tasks(body: BulkIn):
    """Same change on many tasks in one atomic write (or delete them). Unknown ids are ignored."""
    ids = list(dict.fromkeys(str(x) for x in body.ids if x))[:BULK_MAX]
    if not ids:
        raise _err(400, "invalid_ids", "ids must list at least one task id")
    patch = body.patch or TaskIn()
    fields = set(patch.model_fields_set) - {"title", "notes", "order"}
    add = [str(x).strip()[:40] for x in body.labels_add or [] if str(x).strip()]
    remove = {str(x).strip() for x in body.labels_remove or []}
    with _lock:
        data = _guard()
        wanted = set(ids)
        targets = [t for t in data["tasks"] if t["id"] in wanted]
        if body.delete:
            data["tasks"] = [t for t in data["tasks"] if t["id"] not in wanted]
            if targets:
                save(data)
            return {"ok": True, "updated": 0, "deleted": len(targets)}
        status = patch.status if "status" in fields else None
        moving = sorted((t for t in targets if status and t["status"] != status), key=lambda t: t["order"])
        moving_ids = {t["id"] for t in moving}
        others = [t["order"] for t in data["tasks"] if t["status"] == status and t["id"] not in moving_ids]
        now = time.time()
        for t in targets:
            _apply(t, patch, data, fields)
            if add or remove:
                labels = [x for x in t["labels"] if x not in remove]
                t["labels"] = labels + [x for x in add if x not in labels]
            t["updated"] = now
        # Tasks entering a column keep their relative order: on top of "done", at the bottom elsewhere.
        if moving:
            if status == "done":
                top = min(others, default=1.0)
                for i, t in enumerate(moving):
                    t["order"] = top - len(moving) + i
            else:
                end = max(others, default=0.0)
                for i, t in enumerate(moving):
                    t["order"] = end + 1.0 + i
        if targets:
            save(data)
    return {"ok": True, "updated": len(targets), "deleted": 0}


@router.patch("/{tid}")
@_retry_on_change
def patch_task(tid: str, body: TaskIn):
    with _lock:
        data = _guard()
        task = next((t for t in data["tasks"] if t["id"] == tid), None)
        if task is None:
            raise _err(404, "not_found", f"no task {tid}")
        _apply(task, body, data, set(body.model_fields_set))
        task["updated"] = time.time()
        save(data)
    return task


@router.delete("/{tid}")
@_retry_on_change
def delete_task(tid: str):
    with _lock:
        data = _guard()
        before = len(data["tasks"])
        data["tasks"] = [t for t in data["tasks"] if t["id"] != tid]
        if len(data["tasks"]) == before:
            raise _err(404, "not_found", f"no task {tid}")
        save(data)
    return {"ok": True}


# ---- external edits watcher -----------------------------------------------------------------
_task: asyncio.Task | None = None


async def _watch(interval: float = 2.0) -> None:
    last = _sig(tasks_path())
    while True:
        await asyncio.sleep(interval)
        try:
            cur = _sig(tasks_path())
        except Exception:
            continue
        if cur != last:
            last = cur
            if cur != _cache["sig"]:                 # our own writes are already announced
                bus.invalidate("tasks")


async def startup() -> None:
    global _task
    from .. import workspace
    workspace.on_change(on_workspace_change)
    _task = asyncio.create_task(_watch())


async def shutdown() -> None:
    global _task
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
