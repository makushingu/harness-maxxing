"""Memory files and the manual clean (Settings -> Memory). See docs/dev/API.md#memory."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from .. import memory
from ..security import require_auth

router = APIRouter(prefix="/api/memory", tags=["memory"], dependencies=[Depends(require_auth)])


@router.get("")
async def get_memory():
    limit = memory.max_lines()
    return {"max_lines": limit, "max_bytes": memory.max_bytes(limit), "files": await asyncio.to_thread(memory.files)}


@router.post("/compact")
async def compact():
    return {"session": await asyncio.to_thread(memory.start_compaction)}
