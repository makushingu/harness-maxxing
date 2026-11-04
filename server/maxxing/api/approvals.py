"""Approvals API: the tool calls an agent waits on (Allow / Deny), and the watcher that notices new requests.

GET  /api/approvals?session=<sid>    pending requests (of one session), oldest first
POST /api/approvals/{id}             {decision: "allow"|"deny", message?} -> the request as decided

The requests are written by another process (approval_mcp.py, under Claude Code): the watcher looks at the folder
every 2 s (like api/crons.py does for runs) and invalidates the bus topics "approvals" and "sessions".
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import approvals
from ..security import require_auth

log = logging.getLogger("maxxing.api.approvals")

router = APIRouter(prefix="/api/approvals", tags=["approvals"], dependencies=[Depends(require_auth)])


class DecisionIn(BaseModel):
    decision: Literal["allow", "deny"]
    message: Optional[str] = Field(default=None, max_length=approvals.MESSAGE_MAX)


def _err(e: approvals.ApprovalError) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.code, "message": e.message})


@router.get("")
async def list_pending(session: Optional[str] = Query(default=None, max_length=64)) -> dict:
    return {"approvals": await asyncio.to_thread(approvals.pending, session or None)}


@router.post("/{rid}")
async def decide(rid: str, body: DecisionIn) -> dict:
    try:
        return await asyncio.to_thread(approvals.decide, rid, body.decision, body.message or "")
    except approvals.ApprovalError as e:
        raise _err(e) from None


# ---- watcher --------------------------------------------------------------------------------------
_task: asyncio.Task | None = None
POLL_S = 2.0


async def _watch() -> None:
    await asyncio.to_thread(approvals.prime)
    while True:
        await asyncio.sleep(POLL_S)
        try:
            await asyncio.to_thread(approvals.scan)
        except Exception:  # noqa: BLE001 - keep watching
            log.exception("approvals watcher pass failed")


async def startup() -> None:
    global _task
    _task = asyncio.get_running_loop().create_task(_watch())


async def shutdown() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
