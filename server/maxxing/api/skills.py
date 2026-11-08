"""The skills of this install, read-only (Settings -> Skills). See docs/dev/API.md#skills."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from .. import skills
from ..security import require_auth

router = APIRouter(prefix="/api/skills", tags=["skills"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_skills():
    return {"skills": await asyncio.to_thread(skills.list_skills)}
