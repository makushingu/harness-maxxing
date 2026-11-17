"""Token and cost statistics (Settings -> Usage). See docs/dev/API.md#stats."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from .. import budget, stats
from ..security import require_auth

router = APIRouter(prefix="/api/stats", tags=["stats"], dependencies=[Depends(require_auth)])


@router.get("/tokens")
async def tokens(force: bool = False):
    return await asyncio.to_thread(stats.tokens, force)


@router.get("/budget")
async def daily_budget():
    return await asyncio.to_thread(budget.status)


async def _turn_end(session: dict, result: dict | None) -> None:
    if budget.limit() or budget._open is not False:
        await asyncio.to_thread(budget.check_quietly)


async def startup() -> None:
    from ..sessions import service
    service.on_turn_end(_turn_end)
