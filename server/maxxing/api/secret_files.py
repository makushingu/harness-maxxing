"""Secret files of the Keys vault. See docs/dev/API.md#settings--secrets and maxxing/vault_files.py.
No route returns a file's content."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import vault, vault_files
from ..security import require_auth

router = APIRouter(prefix="/api/secret-files", tags=["secrets"], dependencies=[Depends(require_auth)])


@router.get("")
def list_files():
    return vault_files.list_files()


@router.put("/{name}")
async def put_file(name: str, request: Request, note: Optional[str] = None, expose: Optional[bool] = None,
                   create: bool = False, filename: Optional[str] = None):
    """The raw body is the file (no multipart: bodylimit caps it at 1 MiB); an empty body changes the metadata only."""
    body = await request.body()
    try:
        await asyncio.to_thread(vault_files.put, name, body or None, filename, note, expose, create)
    except vault.VaultError as e:
        status = 409 if e.code in ("exists", "name_taken") else 400
        raise HTTPException(status, detail={"error": e.code, "message": str(e)}) from None
    return {"ok": True}


@router.delete("/{name}")
def delete_file(name: str):
    if not vault_files.delete(name):
        raise HTTPException(404, detail={"error": "not_found", "message": f"no secret file {name}"})
    return {"ok": True}
