"""Packages installed with `maxxing community install`, read-only. See docs/dev/API.md#community."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from .. import community
from ..security import require_auth

router = APIRouter(prefix="/api/community", tags=["community"], dependencies=[Depends(require_auth)])


@router.get("/installed")
async def installed():
    return {"packages": await asyncio.to_thread(community.installed)}
