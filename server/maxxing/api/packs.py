"""Starter packs (Settings -> Projects, onboarding). See docs/dev/API.md#packs."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from .. import packs
from ..security import require_auth

router = APIRouter(prefix="/api/packs", tags=["packs"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_packs():
    return {"packs": await asyncio.to_thread(packs.list_packs)}


@router.post("/{pid}/install")
async def install(pid: str):
    try:
        return await asyncio.to_thread(packs.install, pid)
    except packs.PackError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None
