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
    topics: Optional[list[str]] = None      # projects / topics the key is given to; [] = every topic
    create: bool = False          # "Add key": 409 exists instead of replacing a key of that name


@router.get("")
def list_secrets():
    return vault.list_secrets()


@router.put("/{name}")
def put_secret(name: str, body: SecretIn):
    try:
        vault.put(name, body.value, body.note, body.expose, create=body.create, topics=body.topics)
    except vault.VaultError as e:
        status = 409 if e.code in ("exists", "name_taken") else 400
        raise HTTPException(status, detail={"error": e.code, "message": str(e)}) from None
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
