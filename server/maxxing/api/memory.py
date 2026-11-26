"""Memory files and the manual clean (Settings -> Memory). See docs/dev/API.md#memory."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends

from .. import memory, memory_review
from ..security import require_auth

router = APIRouter(prefix="/api/memory", tags=["memory"], dependencies=[Depends(require_auth)])


@router.get("")
async def get_memory():
    limit = memory.max_lines()
    return {"max_lines": limit, "max_bytes": memory.max_bytes(limit), "files": await asyncio.to_thread(memory.files)}


@router.post("/compact")
async def compact():
    return {"session": await asyncio.to_thread(memory.start_compaction)}


# ---- memory review: after an agent's run, and once a day for the busy topics (memory_review.py) ----------------
log = logging.getLogger("maxxing.memory_review")
_task: asyncio.Task | None = None
_runs: set[asyncio.Task] = set()
DAILY_POLL_S = 600


async def _turn_end(session: dict, result: dict | None) -> None:
    if session.get("source") != "agent" or not memory_review.enabled():
        return
    t = asyncio.get_running_loop().create_task(asyncio.to_thread(memory_review.after_run, dict(session)))
    _runs.add(t)                                     # not awaited: one model call, the turn's other listeners go on
    t.add_done_callback(lambda t: (_runs.discard(t), t.cancelled() or t.exception()
                                   and log.error("memory review of a run failed: %s", t.exception())))


async def _loop() -> None:
    while True:
        await asyncio.sleep(DAILY_POLL_S)
        try:
            await asyncio.to_thread(memory_review.daily)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("daily memory review")


async def startup() -> None:
    global _task
    from ..sessions import service
    service.on_turn_end(_turn_end)
    _task = asyncio.get_running_loop().create_task(_loop())


async def shutdown() -> None:
    if _task:
        _task.cancel()
