"""Scheduled jobs. See docs/dev/API.md#crons and maxxing/crons.py.

Runs are recorded by `maxxing cron run` in another process, so a small watcher polls the
mtime of runs.jsonl / jobs.json / the lock dir every 2 s and invalidates the "crons" bus topic.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import bus, crons
from ..security import require_auth

router = APIRouter(prefix="/api/crons", tags=["crons"], dependencies=[Depends(require_auth)])


class CronIn(BaseModel):
    name: Optional[str] = None
    schedule: Optional[str] = None
    kind: Optional[Literal["shell", "claude"]] = None
    command: Optional[str] = None
    topic_path: Optional[str] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    reuse_session: Optional[bool] = None
    enabled: Optional[bool] = None
    notify: Optional[Literal["never", "failure", "always"]] = None
    timeout_s: Optional[int] = None
    permission_mode: Optional[Literal["", "bypass", "acceptEdits", "default"]] = None


def _bad(e: crons.CronError) -> HTTPException:
    status = 409 if e.code == "already_running" else 502 if e.code in ("crontab_error", "spawn_failed") else 400
    return HTTPException(status, detail={"error": e.code, "message": str(e)})


def _missing(cid: str) -> HTTPException:
    return HTTPException(404, detail={"error": "not_found", "message": f"no job {cid}"})


@router.get("")
def list_crons():
    return {"jobs": crons.list_jobs(), "external": crons.external_jobs()}


@router.post("")
def create_cron(body: CronIn):
    try:
        job = crons.create_job(body.model_dump(exclude_none=True))
    except crons.CronError as e:
        raise _bad(e) from None
    bus.invalidate("crons")
    return job


@router.get("/runs")
def runs(cron_id: str = "", limit: int = Query(50, ge=1, le=crons.MAX_RUNS)):
    return crons.read_runs(cron_id or None, limit)


@router.get("/preview")
def preview(schedule: str = ""):
    try:
        expr = crons.parse(schedule)
    except crons.CronError as e:
        return {"valid": False, "human": "", "next": [], "error": str(e)}
    return {"valid": True, "human": crons.humanize(expr.source), "next": crons.next_runs(expr.source, 5)}


@router.get("/{cid}")
def get_cron(cid: str):
    job = crons.get_job(cid)
    if job is None:
        raise _missing(cid)
    return job


@router.patch("/{cid}")
def patch_cron(cid: str, body: CronIn):
    try:
        job = crons.update_job(cid, body.model_dump(exclude_none=True))
    except crons.CronError as e:
        raise _bad(e) from None
    if job is None:
        raise _missing(cid)
    bus.invalidate("crons")
    return job


@router.delete("/{cid}")
def delete_cron(cid: str):
    try:
        found = crons.delete_job(cid)
    except crons.CronError as e:
        raise _bad(e) from None
    if not found:
        raise _missing(cid)
    bus.invalidate("crons")
    return {"ok": True}


@router.post("/{cid}/run")
def run_now(cid: str):
    if crons._raw_job(cid) is None:
        raise _missing(cid)
    try:
        crons.spawn_run(cid)
    except crons.CronError as e:
        raise _bad(e) from None
    except (OSError, ValueError) as e:
        raise HTTPException(502, detail={"error": "spawn_failed", "message": str(e)}) from None
    bus.invalidate("crons")
    return {"ok": True}


# ---- watcher --------------------------------------------------------------------------------
_task: asyncio.Task | None = None


def _signature() -> tuple:
    sig = []
    for p in (crons.runs_path(), crons.jobs_path()):
        try:
            st = os.stat(p)
            sig.append((st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append(None)
    lock_dir = crons.config.state_dir("crons", "locks")
    sig.append(tuple(sorted(cid for cid in (f.stem for f in lock_dir.glob("*.lock")) if crons.is_running(cid))))
    return tuple(sig)


async def _watch(interval: float = 2.0) -> None:
    last = await asyncio.to_thread(_signature)
    while True:
        await asyncio.sleep(interval)
        try:
            cur = await asyncio.to_thread(_signature)
        except Exception:
            continue
        if cur != last:
            last = cur
            bus.invalidate("crons", "health")


async def startup() -> None:
    global _task
    _task = asyncio.create_task(_watch())


async def shutdown() -> None:
    global _task
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
