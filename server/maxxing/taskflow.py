"""A task of the board and the session that does it: its branch, its pull request, its checks.

A task started from the Tasks page keeps the id of its session (`session`). While that session has a separate copy
(worktrees.py), `work` says where the code is: {branch, github, pr, checks, merged}. Read on GitHub by the round of
the pull request watch (api/code.py, every prwatch.INTERVAL) and right after Harness opens the pull request or
merges the copy. Once the pull request is merged (or the copy merged here), the task is done and the copy is
removed - only when worktrees.remove loses nothing, else it stays for the user.

tasks.json is written only when something changed; a task whose session was deleted keeps what it had.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from . import codediff, gitview, worktrees
from .codediff import GitError

log = logging.getLogger("maxxing.taskflow")


def _edit(change) -> bool:
    """Apply `change(tasks) -> bool` to the board and save it when it returns True (retried on an outside edit)."""
    from .api import tasks as board
    for _ in range(3):
        try:
            with board._lock:
                data = board.load()
                if not change(data["tasks"]):
                    return False
                board.save(data)
            return True
        except board._Changed:
            continue
        except board.CorruptFile:
            return False
    return False


def link(tid: str, sid: str) -> dict:
    """The session that does the task. A task not started yet moves to "doing"."""
    from .sessions import store
    if not store.read(sid):
        raise GitError(404, "no_session", "no such session")
    found: dict = {}

    def change(tasks: list[dict]) -> bool:
        t = next((x for x in tasks if x["id"] == tid), None)
        if t is None:
            return False
        t.update(session=sid, work=None, updated=time.time())
        if t["status"] == "todo":
            t["status"] = "doing"
        found.update(t)
        return True
    _edit(change)
    if not found:
        raise GitError(404, "not_found", f"no task {tid}")
    return found


def _mine(head: str | None, merged_sha: str, folder: Path) -> bool:
    """The merged pull request is the one of this copy: not an older one that had the same branch name."""
    return bool(head) and (head == merged_sha or codediff._run(
        folder, "merge-base", "--is-ancestor", head, merged_sha, check=False).returncode == 0)


def _read(meta: dict) -> dict | None:
    """Where the code of a session's copy is now; None without a live copy."""
    wt = worktrees.live(meta)
    if not wt:
        return None
    folder = Path(wt["path"])
    head = codediff.repo_head(folder)
    branch = head.get("branch") or wt.get("branch")
    full = gitview.github_name(head.get("remote") or "") if head.get("remote") else None
    out = {"branch": branch, "github": full, "pr": None, "checks": None, "merged": None}
    if full and branch:
        sha = codediff.head_sha(folder)
        st = gitview.branch_status(full, branch, sha)
        pr, got = st.get("pr"), st.get("merged_pr")
        if pr:
            out["pr"] = {"number": pr["number"], "url": pr["url"], "draft": pr["draft"]}
            out["checks"] = st.get("checks")
        elif got and _mine(sha, got["head_sha"], folder):
            out["merged"] = {"number": got["number"], "url": got["url"], "sha": got["head_sha"]}
    return out


def _tidy(meta: dict, sha: str | None) -> None:
    """Remove the copy of a delivered task, when nothing is lost and no turn runs in it."""
    from .sessions import store
    if not worktrees.live(meta) or (store.runner_alive(meta["id"], meta) and meta.get("state") == "running"):
        return
    try:
        worktrees.remove(meta, merged_sha=sha)
    except GitError as e:
        log.info("copy of %s kept: %s", meta["id"], e.message)


def _follow(task: dict) -> tuple[dict, bool] | None:
    """(work, delivered) of a task to write back, or None when nothing is to be read."""
    from .sessions import store
    meta = store.read(task["session"])
    if not meta:
        return None
    old = task.get("work") if isinstance(task.get("work"), dict) else None
    if old and old.get("merged"):                    # delivered: only the copy may still be there
        _tidy(meta, (old["merged"] or {}).get("sha"))
        return None
    try:
        work = _read(meta)
    except GitError as e:
        log.info("task %s not followed: %s", task["id"], e.message)
        return None
    if work is None:
        return None
    if work["merged"]:
        _tidy(meta, work["merged"]["sha"])
    return work, bool(work["merged"])


def _write(found: dict[str, tuple[dict, bool]]) -> None:
    def change(tasks: list[dict]) -> bool:
        changed = False
        for t in tasks:
            got = found.get(t["id"])
            if not got or got[0] == t.get("work"):
                continue
            t["work"], t["updated"], changed = got[0], time.time(), True
            if got[1] and t["status"] != "done":
                t.update(status="done", done_at=time.time())
        return changed
    _edit(change)


def scan(only: str | None = None) -> None:
    """One round over the tasks that have a session (`only`: the tasks of that session)."""
    from .api import tasks as board
    try:
        tasks = board.load(copy_=False)["tasks"]
    except board.CorruptFile:
        return
    found = {}
    for t in tasks:
        if not t.get("session") or (only and t["session"] != only):
            continue
        try:
            got = _follow(t)
        except Exception:
            log.exception("task %s not followed", t.get("id"))
            continue
        if got:
            found[t["id"]] = got
    if found:
        _write(found)


def merged_here(sid: str, branch: str | None) -> None:
    """The copy of `sid` was merged into its base on this server: its tasks are delivered."""
    def change(tasks: list[dict]) -> bool:
        changed = False
        for t in tasks:
            if t.get("session") == sid and not ((t.get("work") or {}).get("merged")):
                t["work"] = {"branch": branch, "github": None, "pr": None, "checks": None, "merged": {"local": True}}
                t.update(status="done", done_at=t.get("done_at") or time.time(), updated=time.time())
                changed = True
        return changed
    _edit(change)


_soon = threading.Lock()


def soon(sid: str | None = None) -> None:
    """Read the tasks again in the background, right after Harness opened or merged a pull request."""
    def run():
        if not _soon.acquire(blocking=False):
            return
        try:
            time.sleep(2)                            # GitHub lists the new pull request a moment later
            scan(sid)
        except Exception:
            log.exception("tasks not followed")
        finally:
            _soon.release()
    threading.Thread(target=run, daemon=True, name="taskflow").start()
