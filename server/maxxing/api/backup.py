"""Memory backup endpoints. See docs/dev/API.md#backup. Long work runs in worker threads."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import backup
from ..security import require_auth

router = APIRouter(prefix="/api/backup", tags=["backup"], dependencies=[Depends(require_auth)])


class ConfigIn(BaseModel):
    repo: str
    token: str = ""
    create: bool = False


class SettingsIn(BaseModel):
    schedule: str | None = None
    include: list[str] | None = None


class RestoreIn(BaseModel):
    ref: str | None = None


@router.get("")
async def get_status():
    return await asyncio.to_thread(backup.status)


@router.post("/config")
async def post_config(body: ConfigIn):
    return await asyncio.to_thread(backup.configure, body.repo, body.token, body.create)


@router.put("/settings")
async def put_settings(body: SettingsIn):
    try:
        await asyncio.to_thread(backup.update_settings, body.schedule, body.include)
    except backup.BackupError as e:
        raise HTTPException(400, detail={"error": e.code, "message": str(e)}) from None
    return {"ok": True}


@router.post("/run")
async def run():
    res = await asyncio.to_thread(backup.run)
    if res.get("code") == "busy":
        raise HTTPException(409, detail={"error": "busy", "message": res["error"]})
    return {k: res.get(k) for k in ("ok", "commit", "files", "changed", "error", "code", "leaks")
            if res.get(k) is not None or k in ("ok", "commit", "files")}


@router.get("/history")
async def get_history(limit: int = 100):
    return await asyncio.to_thread(backup.history, max(1, min(limit, 500)))


@router.post("/restore")
async def post_restore(body: RestoreIn | None = None):
    res = await asyncio.to_thread(backup.restore, body.ref if body else None)
    if not res.get("ok"):
        status = 409 if res.get("code") in ("busy", "not_configured", "empty") else 400
        raise HTTPException(status, detail={"error": res.get("code") or "restore_failed",
                                            "message": res.get("error") or "Restore failed"})
    return res


@router.delete("")
async def forget():
    try:
        await asyncio.to_thread(backup.forget)
    except backup.BackupError as e:
        raise HTTPException(409 if e.code == "busy" else 400, detail={"error": e.code, "message": str(e)}) from None
    return {"ok": True}
