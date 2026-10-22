"""Infra page (Settings -> Features -> infra_page): sites, databases, buckets, domains and servers (read-only, except
connecting another server: /servers/connect may add the Harness SSH key to a Hostinger VPS through its API).
The snapshot is refreshed in the background (every `infra_refresh_min` minutes while the page is on, first run
1 minute after start: never during the start-up health check). See docs/dev/API.md#infra."""
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, infra
from ..infra import caddy, connect, registry
from ..security import require_auth

router = APIRouter(prefix="/api/infra", tags=["infra"], dependencies=[Depends(require_auth)])

FIRST_RUN_S = 60
TICK_S = 60
_task: asyncio.Task | None = None


async def _loop() -> None:
    await asyncio.sleep(FIRST_RUN_S)
    while True:
        try:
            if infra.enabled():
                snap = infra.load_snapshot() or {}
                period = max(5, int(config.load_config().get("infra_refresh_min") or 15)) * 60
                if time.time() - (snap.get("generated_at") or 0) >= period or infra.is_stale(snap):
                    await asyncio.to_thread(infra._safe_refresh)
        except Exception:  # noqa: BLE001 - the loop never dies
            pass
        await asyncio.sleep(TICK_S)


async def startup() -> None:
    global _task
    _task = asyncio.create_task(_loop())


async def shutdown() -> None:
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task


def _need_on() -> None:
    if not infra.enabled():
        raise HTTPException(409, detail={"error": "disabled", "message": "turn the Infra page on in Settings -> Features"})


@router.get("")
async def get_infra():
    return await asyncio.to_thread(infra.view)


@router.post("/refresh")
async def refresh():
    _need_on()
    return {"started": infra.refresh_in_background(), "refreshing": True}


class AnnotateIn(BaseModel):
    id: str
    project: Optional[str] = None
    note: Optional[str] = None
    hidden: Optional[bool] = None


def _patch_snapshot(body: AnnotateIn, cur: dict) -> None:
    """Show the change at once, without waiting for the next refresh (never over a newer snapshot)."""
    with infra.snapshot_lock:
        snap = infra.load_snapshot()
        if not snap:
            return
        for r in snap.get("resources") or []:
            if r.get("id") == body.id:
                if body.project is not None:
                    r["project"] = cur.get("project")
                if body.note is not None:
                    r["note"] = cur.get("note") or ""
                if body.hidden is not None:
                    r["hidden"] = bool(cur.get("hidden"))
        config.write_json(infra.snapshot_path(), snap)


@router.post("/annotate")
async def annotate(body: AnnotateIn):
    _need_on()
    if not body.id or len(body.id) > 600:
        raise HTTPException(400, detail={"error": "bad_id", "message": "resource id required"})
    cur = await asyncio.to_thread(registry.annotate, body.id, body.project, body.note, body.hidden)
    await asyncio.to_thread(_patch_snapshot, body, cur)
    return {"id": body.id, **cur}


@router.get("/reserved")
async def reserved():
    return {"names": caddy.reserved()}


def _after_server_change() -> None:
    if not infra.refresh_in_background():
        infra.mark_stale()                             # a refresh is running: the loop does another one after it


class ConnectIn(BaseModel):
    id: Optional[str] = None          # server:hostinger:<id>
    host: Optional[str] = None        # or any server by address
    user: str = "root"
    port: int = 22
    label: str = ""


@router.post("/servers/connect")
async def connect_server(body: ConnectIn):
    _need_on()
    try:
        if body.id:
            if not body.id.startswith("server:hostinger:"):
                raise HTTPException(400, detail={"error": "bad_id", "message": "only a Hostinger VPS connects by id"})
            s = await asyncio.to_thread(connect.connect_hostinger, body.id, body.label)
        elif body.host:
            s = await asyncio.to_thread(connect.connect_host, body.host.strip(), body.user.strip() or "root", body.port, body.label)
        else:
            raise HTTPException(400, detail={"error": "bad_request", "message": "id or host required"})
    except connect.ConnectError as e:
        if e.code == "need_key":                       # not a failure: the page shows the line to paste
            return {"connected": False, "message": str(e), **e.extra}
        raise HTTPException(409 if e.code in ("exists", "in_progress", "busy") else 422,
                            detail={"error": e.code, "message": str(e), **e.extra})
    except registry.RegistryError as e:
        raise HTTPException(400, detail={"error": e.code, "message": str(e)})
    _after_server_change()
    return {"connected": True, **{k: s.get(k) for k in ("name", "label", "host", "user", "port", "via")}}


class ServerIn(BaseModel):
    name: str
    label: Optional[str] = None


def _rename_in_snapshot(name: str, shown: str) -> None:
    """Show it at once (never over a newer snapshot written by a refresh)."""
    with infra.snapshot_lock:
        snap = infra.load_snapshot()
        if not snap:
            return
        for r in snap.get("resources") or []:
            if r.get("id") == f"server:{name}":
                r["name"] = shown
        config.write_json(infra.snapshot_path(), snap)


@router.post("/servers/rename")
async def rename_server(body: ServerIn):
    _need_on()
    try:
        s = await asyncio.to_thread(registry.rename_server, body.name, body.label or "")
    except registry.RegistryError as e:
        raise HTTPException(404, detail={"error": e.code, "message": str(e)})
    await asyncio.to_thread(_rename_in_snapshot, body.name, s.get("label") or body.name)
    from .. import bus
    bus.invalidate("infra")
    return {"name": s["name"], "label": s.get("label") or ""}


@router.post("/servers/remove")
async def remove_server(body: ServerIn):
    _need_on()
    if not await asyncio.to_thread(registry.remove_server, body.name):
        raise HTTPException(404, detail={"error": "not_found", "message": f"no server named {body.name}"})
    _after_server_change()
    return {"removed": body.name}


class DomainIn(BaseModel):
    name: str


@router.post("/domains")
async def add_domain(body: DomainIn):
    _need_on()
    try:
        name = await asyncio.to_thread(registry.add_domain, body.name)
    except registry.RegistryError as e:
        raise HTTPException(400, detail={"error": e.code, "message": str(e)})
    _after_server_change()
    return {"name": name}


@router.post("/domains/remove")
async def remove_domain(body: DomainIn):
    _need_on()
    if not await asyncio.to_thread(registry.remove_domain, body.name):
        raise HTTPException(404, detail={"error": "not_found", "message": f"{body.name} was not added by hand"})
    _after_server_change()
    return {"removed": body.name}
