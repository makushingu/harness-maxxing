"""Keys vault. See docs/dev/API.md#settings--secrets and maxxing/vault.py."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import vault
from ..security import require_auth

router = APIRouter(prefix="/api/secrets", tags=["secrets"], dependencies=[Depends(require_auth)])


class SecretIn(BaseModel):
    value: Optional[str] = None
    note: Optional[str] = None
    expose: Optional[bool] = None


def _bad(e: vault.VaultError) -> HTTPException:
    return HTTPException(400, detail={"error": e.code, "message": str(e)})


@router.get("")
def list_secrets():
    return vault.list_secrets()


@router.put("/{name}")
def put_secret(name: str, body: SecretIn):
    try:
        vault.put(name, body.value, body.note, body.expose)
    except vault.VaultError as e:
        raise _bad(e) from None
    return {"ok": True}


@router.get("/{name}/reveal")
def reveal(name: str):
    v = vault.get(name)
    if v is None:
        raise HTTPException(404, detail={"error": "not_found", "message": f"no secret {name}"})
    return {"value": v}


@router.delete("/{name}")
def delete_secret(name: str):
    if not vault.delete(name):
        raise HTTPException(404, detail={"error": "not_found", "message": f"no secret {name}"})
    return {"ok": True}
