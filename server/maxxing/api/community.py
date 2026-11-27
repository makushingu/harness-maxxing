"""Packages from outside: what was installed, the catalogue of the website, check and install of one listing.
See docs/dev/API.md#community."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import community
from ..security import require_auth

router = APIRouter(prefix="/api/community", tags=["community"], dependencies=[Depends(require_auth)])


class InstallBody(BaseModel):
    sha256: str
    read_it: bool = False
    force: bool = False


async def _run(fn, *a, **kw):
    try:
        return await asyncio.to_thread(fn, *a, **kw)
    except community.NeedsConfirmation as e:
        raise HTTPException(409, str(e)) from None
    except community.PackageChanged as e:
        raise HTTPException(409, str(e)) from None
    except community.PackageError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/installed")
async def installed():
    return {"packages": await asyncio.to_thread(community.installed)}


@router.get("/catalogue")
async def catalogue(fresh: bool = False):
    return {"items": await _run(community.catalogue, fresh)}


@router.post("/catalogue/{slug}/check")
async def check(slug: str):
    return await _run(community.check_listing, slug)


@router.post("/catalogue/{slug}/install")
async def install(slug: str, body: InstallBody):
    r = await _run(community.install_listing, slug, body.sha256, read_it=body.read_it, force=body.force)
    return {"kind": r["kind"], "id": r["id"], "record": r["record"]}
