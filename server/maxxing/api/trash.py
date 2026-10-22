"""Trash endpoints (Settings -> Trash). See docs/dev/API.md#trash."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from .. import trash
from ..security import require_auth

router = APIRouter(prefix="/api/trash", tags=["trash"], dependencies=[Depends(require_auth)])


def _err(e: trash.TrashError) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.code, "message": e.message})


@router.get("")
async def list_trash():
    return {"items": await asyncio.to_thread(trash.list_items), "keep_days": trash.KEEP_DAYS}


@router.post("/{item_id}/restore")
async def restore_item(item_id: str):
    try:
        return await asyncio.to_thread(trash.restore, item_id)
    except trash.TrashError as e:
        raise _err(e) from None


@router.delete("/{item_id}")
async def delete_item(item_id: str):
    try:
        await asyncio.to_thread(trash.delete, item_id)
    except trash.TrashError as e:
        raise _err(e) from None
    return {"ok": True}


@router.delete("")
async def empty_trash():
    return {"ok": True, "deleted": await asyncio.to_thread(trash.empty)}
