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


def _too_large() -> HTTPException:
    return HTTPException(413, detail={"error": "too_large",
                                      "message": f"a file has 1 byte to {vault_files.MAX_SIZE // 1024 // 1024} MiB"})


async def _read_body(request: Request) -> bytes:
    """The raw body, refused as soon as it goes over MAX_SIZE (never held whole when too big)."""
    try:
        if int(request.headers.get("content-length", "")) > vault_files.MAX_SIZE:
            raise _too_large()
    except ValueError:
        pass
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > vault_files.MAX_SIZE:
            raise _too_large()
    return bytes(buf)


@router.put("/{name}")
async def put_file(name: str, request: Request, note: Optional[str] = None, expose: Optional[bool] = None,
                   create: bool = False, filename: Optional[str] = None):
    """The raw body is the file, sent as application/octet-stream (or without a type); an empty body changes the
    metadata only. Any other type -> 415: a multipart body would skip bodylimit's 1 MiB cap (UploadGuard's is GBs)."""
    ctype = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if ctype not in ("", "application/octet-stream"):
        raise HTTPException(415, detail={"error": "unsupported_media_type",
                                         "message": "send the file as the raw body (application/octet-stream)"})
    body = await _read_body(request)
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
