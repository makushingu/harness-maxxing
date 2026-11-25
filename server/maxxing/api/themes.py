"""Installed themes, read-only (Settings -> Appearance). Installed by Claude with `maxxing themes install`.
See docs/dev/API.md#themes."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import themes
from ..security import require_auth

router = APIRouter(prefix="/api/themes", tags=["themes"], dependencies=[Depends(require_auth)])


@router.get("")
async def list_themes():
    return await asyncio.to_thread(themes.list_themes)


@router.get("/{tid}/file/{name}")
async def theme_file(tid: str, name: str):
    f = await asyncio.to_thread(themes.file_path, tid, name)
    if not f:
        raise HTTPException(404, "no such file in this theme")
    return FileResponse(f, media_type=themes.IMAGE_TYPES[f.suffix.lower()],
                        headers={"Cache-Control": "private, max-age=300, stale-while-revalidate=604800", "X-Content-Type-Options": "nosniff"})
