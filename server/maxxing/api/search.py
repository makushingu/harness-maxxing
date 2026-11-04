"""Workspace-wide full-text search (sessions, files, memory, tasks). See docs/dev/API.md#search."""
from __future__ import annotations

import asyncio
import logging
import contextlib
import threading

from fastapi import APIRouter, Depends, Query, Request

from .. import search as engine
from ..security import require_auth

router = APIRouter(prefix="/api/search", tags=["search"], dependencies=[Depends(require_auth)])

log = logging.getLogger(__name__)
REFRESH_S = 30
_task: asyncio.Task | None = None


async def _loop() -> None:
    n = 0
    while True:
        try:
            await asyncio.to_thread(engine.refresh, True, None)    # memory files each pass, a full walk every FILES_EVERY_S
            n += 1
            if n % 120 == 0:                               # about once an hour: merge FTS segments
                await asyncio.to_thread(engine.optimize)
        except asyncio.CancelledError:
            raise
        except Exception:                                  # a locked / damaged index: try again next pass, never stop
            log.warning("search index refresh failed", exc_info=True)
        await asyncio.sleep(REFRESH_S)


async def startup() -> None:
    global _task
    _task = asyncio.create_task(_loop())


async def shutdown() -> None:
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task


@router.get("")
async def search(request: Request, q: str = "", kinds: str = "", limit: int = Query(30, ge=1, le=100)):
    wanted = [k for k in kinds.split(",") if k] or None
    # The palette aborts a query when the next keystroke comes: its worker thread (shared with the whole API)
    # stops too, instead of ranking for nobody.
    gone = threading.Event()
    job = asyncio.ensure_future(asyncio.to_thread(engine.search, q, wanted, limit, gone.is_set))
    while not job.done():
        await asyncio.wait({job}, timeout=0.1)
        if not job.done() and not gone.is_set() and await request.is_disconnected():
            gone.set()
    return job.result()


@router.get("/stats")
async def stats():
    return await asyncio.to_thread(engine.stats)
