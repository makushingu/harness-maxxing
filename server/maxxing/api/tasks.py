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
from pydantic import BaseModel, Field, field_validator

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


def _no_constant(_: str) -> None:
    """NaN / Infinity written by hand in tasks.json: read as null (the JSON response refuses them)."""
    return None


def _finite(v: str) -> float | None:
    """1e999 is read as infinity: null instead, like NaN."""
    f = float(v)
    return f if math.isfinite(f) else None


_SURROGATE = re.compile(r"\\u[dD][89a-fA-F]")


def _scrub(v: Any) -> Any:
    """A lone surrogate ("\\ud800" is valid JSON) cannot be written as UTF-8: replaced by U+FFFD."""
    if isinstance(v, str):
        return v.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    if isinstance(v, list):
        return [_scrub(x) for x in v]
    if isinstance(v, dict):
        return {_scrub(k): _scrub(x) for k, x in v.items()}
    return v


def _id_of(v: Any) -> str:
    """An id written by hand: text or a number; anything else (a list, an object) is no id."""
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        return ""
    return _text(v) if v else ""


def _free_id(prefix: str, item: dict, taken: set) -> str:
    """A stable id for a hand-written item: the same file gives the same id; two identical items get two."""
    base = json.dumps(item, sort_keys=True, default=str)
    n = 0
    while True:
        new = prefix + hashlib.sha1((base + (f"#{n}" if n else "")).encode()).hexdigest()[:6]
        if new not in taken:
            return new
        n += 1


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
    if not (isinstance(out.get("due"), str) and _real_date(out["due"])):
        out["due"] = None   # "2026-13-01" crashed every page that shows the date
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


def _real_date(v: str) -> bool:
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        return False
    return bool(_DATE.match(v))


# Fields `_norm_task` may rewrite: on save, a hand-written value the API did not change is written back as it was
# ("in_progress", "2026-11-05T10:00", "urgent"...), not replaced by its normalised default.
_NORMED = ("title", "notes", "status", "priority", "due", "project_id", "topic_path", "labels", "created", "updated",
           "done_at", "order")


def _with_raw(task: dict, raw: dict | None) -> dict:
    if raw is None:
        return task
    norm = _norm_task(raw)
    out = None
    for k in _NORMED:
        if k in raw and raw[k] != norm[k] and task.get(k) == norm[k]:
            out = out or dict(task)
            out[k] = raw[k]
    return out or task


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
                raw = p.read_text() or "{}"
                data = json.loads(raw, parse_constant=_no_constant, parse_float=_finite)
                if _SURROGATE.search(raw):
                    data = _scrub(data)
            except RecursionError:                     # nested too deep to read: damaged, not a 500
                raise CorruptFile("tasks.json is nested too deeply") from None
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
        projects, seen = [], set()
        ptaken = {_id_of(x.get("id")) for x in data.get("projects") or [] if isinstance(x, dict)} - {""}
        for x in data.get("projects") or []:
            if isinstance(x, dict):
                pid = _id_of(x.get("id"))
                if not pid or pid in seen:             # hand-written (kept, like tasks) or the same id twice
                    pid = _free_id("p_", x, ptaken | seen)
                seen.add(pid)
                projects.append({**x, "id": pid})
        data["projects"] = projects
        for proj in data["projects"]:
            if "workspace" in proj and not isinstance(proj["workspace"], str):   # a list is not a dict key: _sync failed
                proj.pop("workspace")
        tasks, seen, raw = [], set(), {}
        taken = {_id_of(t.get("id")) for t in data.get("tasks") or [] if isinstance(t, dict)} - {""}
        for t in data.get("tasks") or []:
            if isinstance(t, dict):
                tid = _id_of(t.get("id"))
                if not tid or tid in seen:             # hand-written task, a list as id, or an id used twice
                    tid = _free_id("t_", t, taken)     # stable until saved
                    taken.add(tid)
                    t = {**t, "id": tid}
                seen.add(tid)
                raw[tid] = t
                tasks.append(_norm_task(t))
        data["tasks"] = tasks
        _cache["sig"], _cache["data"], _cache["raw"] = sig, (copy.deepcopy(data) if copy_ else data), raw
        return data


def save(data: dict) -> None:
    """Write `data` (loaded by this request under `_lock`); raises _Changed when the file changed meanwhile."""
    with _lock:
        raw = _cache.get("raw") or {}
        out = {**data, "tasks": [_with_raw(t, raw.get(t["id"])) for t in data["tasks"]]}

        def unchanged() -> None:
            # Checked after the dump and the fsync, right before the rename: an edit landing while the file was
            # serialised (tens of ms for a big board) is not overwritten.
            if _sig(tasks_path()) != _cache["sig"]:
                _cache["sig"] = None
                raise _Changed()

        unchanged()
        config.write_json(tasks_path(), out, before_replace=unchanged)
        _cache["sig"], _cache["data"] = _sig(tasks_path()), copy.deepcopy(data)
        _cache["raw"] = {t["id"]: t for t in copy.deepcopy(out["tasks"])}
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
    listed = {id(t) for t in overdue} | {id(t) for t in due_today}
    items = sorted(overdue, key=lambda t: t["due"]) + due_today + [t for t in doing if id(t) not in listed]
    return {"open": len(open_), "doing": len(doing), "due_today": len(due_today),
            "overdue": len(overdue), "items": items, "today": today}


# ---- validation -----------------------------------------------------------------------------
class _Text(BaseModel):
    """A lone surrogate ("\\ud800" is valid JSON) cannot be written as UTF-8 to tasks.json: a 422, not a 500."""

    @field_validator("*")
    @classmethod
    def _utf8(cls, v: Any) -> Any:
        for s in v if isinstance(v, list) else (v,):
            if isinstance(s, str) and not s.isascii():
                try:
                    s.encode("utf-8")
                except UnicodeEncodeError:
                    raise ValueError("text cut inside a character (lone surrogate)") from None
        return v


class TaskIn(_Text):
    model_config = {"extra": "ignore"}
    title: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[Literal["todo", "doing", "done"]] = None
    priority: Optional[int] = None
    due: Optional[str] = None
    project_id: Optional[str] = None
    topic_path: Optional[str] = None
    labels: Optional[list[str]] = None
    order: Optional[float] = Field(None, allow_inf_nan=False)   # inf/NaN broke every later listing
    # PATCH only: the cards it was dropped between (Board). The server places it there, renumbering the column when
    # their orders are equal or too close to split (hand-written tasks all at 0, or many drops at the same place).
    prev_id: Optional[str] = None
    next_id: Optional[str] = None


class ProjectIn(_Text):
    name: Optional[str] = None
    color: Optional[str] = None
    hidden: Optional[bool] = None


LABELS_MAX = 50


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
        labels = list(dict.fromkeys(x for x in (str(x).strip()[:40] for x in body.labels or []) if x))
        if len(labels) > LABELS_MAX:
            raise _err(400, "invalid_labels", f"at most {LABELS_MAX} labels per task")
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


# ---- public helpers for other modules (enterprise delegation) --------------------------------
def get_task(tid: str) -> dict | None:
    """A copy of the task, or None (a missing, empty or damaged file reads as no task)."""
    try:
        with _lock:
            return next((copy.deepcopy(t) for t in load(copy_=False)["tasks"] if t["id"] == tid), None)
    except CorruptFile:
        return None


@_retry_on_change
def add_task(fields: dict) -> dict:
    """Create a task from plain fields (title required, unknown keys kept, e.g. `enterprise`) -> the task."""
    title = str(fields.get("title") or "").strip()
    if not title or len(title) > 500:
        raise _err(400, "invalid_title", "title is required (max 500 characters)")
    with _lock:
        data = _guard()
        now = time.time()
        task = _norm_task({**fields, "id": _new_id("t_", 6), "title": title, "created": now, "updated": now})
        if task["status"] == "done":
            task["done_at"] = now
        if "order" not in fields:
            same = [t["order"] for t in data["tasks"] if t["status"] == task["status"]]
            task["order"] = (max(same) + 1.0) if same else 1.0
        while any(t["id"] == task["id"] for t in data["tasks"]):
            task["id"] = _new_id("t_", 6)
        data["tasks"].append(task)
        save(data)
    return task


@_retry_on_change
def update_task(tid: str, fields: dict) -> dict:
    """Set plain fields on a task (a nested value such as `enterprise` is replaced whole) -> the task; 404 if gone."""
    with _lock:
        data = _guard()
        task = next((t for t in data["tasks"] if t["id"] == tid), None)
        if task is None:
            raise _err(404, "not_found", f"no task {tid}")
        was = task["status"]
        task.update({k: v for k, v in fields.items() if k not in ("id", "created")})
        task.update(_norm_task(task))
        if task["status"] != was:
            task["done_at"] = time.time() if task["status"] == "done" else None
        task["updated"] = time.time()
        save(data)
    return task


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


class BulkIn(_Text):
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
    ids = list(dict.fromkeys(str(x) for x in body.ids if x))
    if not ids:
        raise _err(400, "invalid_ids", "ids must list at least one task id")
    if len(ids) > BULK_MAX:                             # never apply part of the change in silence
        raise _err(400, "too_many_ids", f"at most {BULK_MAX} tasks per request")
    patch = body.patch or TaskIn()
    fields = set(patch.model_fields_set) - {"title", "notes", "order"}
    add = list(dict.fromkeys(str(x).strip()[:40] for x in body.labels_add or [] if str(x).strip()))
    if len(add) > LABELS_MAX:
        raise _err(400, "invalid_labels", f"at most {LABELS_MAX} labels per task")
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
                kept = set(labels)
                t["labels"] = labels + [x for x in add if x not in kept]
                if len(t["labels"]) > LABELS_MAX:
                    raise _err(400, "invalid_labels", f"at most {LABELS_MAX} labels per task")
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
        fields = set(body.model_fields_set)
        was = task["status"]
        _apply(task, body, data, fields)
        if body.prev_id or body.next_id:
            _place(task, data, body.prev_id, body.next_id)
        elif task["status"] != was and body.order is None:
            # Like the Board and the bulk path: on top of "done", at the bottom elsewhere (the old column's
            # order could leave it past the first page of Done).
            others = [t["order"] for t in data["tasks"] if t["status"] == task["status"] and t is not task]
            if task["status"] == "done":
                task["order"] = min(others, default=1.0) - 1.0
            else:
                task["order"] = max(others, default=0.0) + 1.0
        task["updated"] = time.time()
        save(data)
    return task


def _place(task: dict, data: dict, prev_id: str | None, next_id: str | None) -> None:
    """Order `task` right before `next_id` (else right after `prev_id`) in its column, sorted like the UI
    (order, then created)."""
    col = sorted((t for t in data["tasks"] if t["status"] == task["status"] and t is not task),
                 key=lambda t: (t["order"], t["created"]))
    ids = [t["id"] for t in col]
    if next_id in ids:
        i = ids.index(next_id)
    elif prev_id in ids:
        i = ids.index(prev_id) + 1
    else:
        return                                          # neighbours gone meanwhile: keep the order sent
    prev = col[i - 1]["order"] if i > 0 else None
    nxt = col[i]["order"] if i < len(col) else None
    if prev is None and nxt is None:
        return
    if prev is not None and nxt is not None:
        order = (prev + nxt) / 2 if nxt - prev > 1e-6 else None
    else:
        order = nxt - 1.0 if prev is None else prev + 1.0
    # strictly between its neighbours, else no room (1e300 - 1.0 == 1e300): renumber the column
    if order is not None and (prev is None or prev < order) and (nxt is None or order < nxt):
        task["order"] = order
    else:
        col.insert(i, task)
        for n, t in enumerate(col):
            t["order"] = float(n + 1)


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
