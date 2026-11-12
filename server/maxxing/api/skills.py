"""The skills of this install, read-only (Settings -> Skills). See docs/dev/API.md#skills."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from .. import skills
from ..security import require_auth

router = APIRouter(prefix="/api/skills", tags=["skills"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_skills(path: str = ""):
    """`path` = a topic (`projects/<p>/topics/<t>`): only the skills its sessions see (the composer's / menu)."""
    return {"skills": await asyncio.to_thread(skills.for_topic, path) if path else await asyncio.to_thread(skills.list_skills)}
