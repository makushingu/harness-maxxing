"""Import from another agent (onboarding + Settings -> Import). See docs/dev/API.md#import."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from .. import importer
from ..security import require_auth

router = APIRouter(prefix="/api/import", tags=["import"], dependencies=[Depends(require_auth)])
MAX_UPLOAD = 600 * 1024 * 1024


def _err(e: importer.ImportFailed) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.code, "message": e.message})


@router.get("/prompt")
async def get_prompt(agent: str = "other"):
    agent = agent if agent in importer.AGENTS else "other"
    return {"agent": agent, "agents": list(importer.AGENTS), "prompt": importer.prompt(agent)}


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    uid, dest = importer.new_upload()
    size = 0
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, detail={"error": "too_big", "message": "The zip is larger than 600 MB"})
            f.write(chunk)
    try:
        plan = await asyncio.to_thread(importer.inspect, dest)
    except importer.ImportFailed as e:
        dest.unlink(missing_ok=True)
        raise _err(e) from None
    return {"id": uid, "name": file.filename or "export.zip", **plan}


@router.post("/{uid}/apply")
async def apply(uid: str):
    try:
        path = importer.upload_path(uid)
        res = await asyncio.to_thread(importer.apply, path)
    except importer.ImportFailed as e:
        raise _err(e) from None
    return {**res, "finish_prompt": importer.finish_prompt(res)}


@router.delete("/{uid}")
async def discard(uid: str):
    try:
        importer.discard(uid)
    except importer.ImportFailed as e:
        raise _err(e) from None
    return {"ok": True}
