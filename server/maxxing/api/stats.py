"""Token and cost statistics (Settings -> Stats). See docs/dev/API.md#stats."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from .. import stats
from ..security import require_auth

router = APIRouter(prefix="/api/stats", tags=["stats"], dependencies=[Depends(require_auth)])


@router.get("/tokens")
async def tokens(force: bool = False):
    return await asyncio.to_thread(stats.tokens, force)
