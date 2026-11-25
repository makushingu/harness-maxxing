"""Getting-started guide: progress and the cards Opus writes. See docs/dev/API.md#guide."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import guide
from ..security import require_auth

router = APIRouter(prefix="/api/guide", tags=["guide"], dependencies=[Depends(require_auth)])


class CardsIn(BaseModel):
    steps: list[str]
    force: bool = False


@router.get("")
async def get_guide(context: bool = False):
    """context=1: also what Harness sees (the first dialog); without: the progress alone (polled while cards are written)."""
    if not context:
        return await asyncio.to_thread(guide.state)
    st, ctx = await asyncio.gather(asyncio.to_thread(guide.state), asyncio.to_thread(guide.context))
    return {**st, "context": ctx}


@router.put("")
async def put_guide(body: dict[str, Any]):
    return await asyncio.to_thread(guide.update, body)


@router.post("/cards")
async def post_cards(body: CardsIn):
    await asyncio.to_thread(guide.request_cards, body.steps[:6], body.force)
    return await asyncio.to_thread(guide.state)


@router.post("/reset")
async def post_reset():
    return await asyncio.to_thread(guide.reset)
