"""Enterprises (Settings -> Features: enterprises_page, needs agents_page). See docs/dev/API.md#enterprises and
maxxing/enterprises.py. Only the owner (the signed-in user) edits the chart."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .. import agents, enterprises
from ..security import require_auth

log = logging.getLogger("maxxing.api.enterprises")
router = APIRouter(prefix="/api/enterprises", tags=["enterprises"], dependencies=[Depends(require_auth)])


def _on() -> None:
    if not enterprises.feature_on():
        raise HTTPException(404, detail={"error": "feature_off",
                                         "message": "Enterprises are off (Settings -> Features, needs Agents)"})


def _bad(e: enterprises.EnterpriseError | agents.AgentError) -> HTTPException:
    extra = getattr(e, "extra", None) or {}
    return HTTPException(e.status, detail={"error": e.code, "message": e.message, **extra})


class EnterpriseIn(BaseModel):
    id: Optional[str] = Field(None, max_length=200)     # create only: the folder slug (checked: invalid_name)
    name: Optional[str] = Field(None, max_length=enterprises.NAME_MAX)
    emoji: Optional[str] = Field(None, max_length=16)
    projects: Optional[list[str]] = Field(None, max_length=100)    # create only: PUT .../projects afterwards
    template: Optional[str] = Field(None, max_length=48)           # create only
    top: Optional[str] = Field(None, max_length=48)
    settings: Optional[dict[str, Any]] = None
    envelope: Optional[dict[str, Any]] = None
    departments: Optional[dict[str, Any]] = None
    objectives: Optional[list[dict[str, Any]]] = Field(None, max_length=200)
    grants: Optional[list[dict[str, Any]]] = Field(None, max_length=200)


class ProjectsIn(BaseModel):
    projects: list[str] = Field(max_length=100)
    vacate: bool = False


class PositionIn(BaseModel):
    id: Optional[str] = Field(None, max_length=200)     # add only (checked: invalid_name)
    rev: Optional[int] = None                           # edit: the chart's rev (required to move, seat or vacate)
    title: Optional[str] = Field(None, max_length=enterprises.TITLE_MAX)
    reports_to: Optional[str] = Field(None, max_length=48)
    department: Optional[str] = Field(None, max_length=48)
    agent: Optional[str] = Field(None, max_length=200)  # edit: null = vacate
    job: Optional[str] = Field(None, max_length=enterprises.JOB_MAX)
    worker_template: Optional[dict[str, Any]] = None
    desk: Optional[bool] = None


class HireIn(BaseModel):
    topic: str = Field(max_length=200)
    name: Optional[str] = Field(None, max_length=48)
    template: Optional[str] = Field(None, max_length=64)


def _given(body: BaseModel, skip: tuple[str, ...] = ()) -> dict:
    """The fields the request sent (a null one is a value: vacate, no lead), not the model's defaults."""
    return {k: v for k, v in body.model_dump(exclude_unset=True).items() if k not in skip}


@router.get("")
def list_enterprises():
    _on()
    return {"enterprises": enterprises.list_all()}


@router.post("")
def create_enterprise(body: EnterpriseIn):
    _on()
    f = _given(body, ("id", "top", "settings", "envelope", "departments", "objectives", "grants"))
    try:
        return enterprises.create(body.id or "", f)
    except enterprises.EnterpriseError as e:
        raise _bad(e) from None


@router.get("/templates")
def templates():
    _on()
    return {"templates": enterprises.list_templates()}


@router.post("/import")
async def import_enterprise(request: Request):
    """The body is the zip itself (no multipart); a new enterprise is created from it."""
    _on()
    from .. import enterprise_io
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > enterprise_io.MAX_ZIP:
            raise HTTPException(413, detail={"error": "too_big", "message": "The zip is larger than 50 MB"})
    try:
        return await asyncio.to_thread(enterprise_io.import_zip, bytes(buf))
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.get("/{e}/export")
async def export_enterprise(e: str):
    _on()
    from .. import enterprise_io
    try:
        data = await asyncio.to_thread(enterprise_io.export_zip, e)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{e}.zip"'})


@router.get("/{e}")
def get_enterprise(e: str):
    _on()
    try:
        return enterprises.get(e)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.patch("/{e}")
def update_enterprise(e: str, body: EnterpriseIn):
    _on()
    try:
        return enterprises.update(e, _given(body, ("id", "projects", "template")))
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.delete("/{e}")
def delete_enterprise(e: str):
    _on()
    try:
        enterprises.delete(e)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
    return {"ok": True}


@router.put("/{e}/projects")
def put_projects(e: str, body: ProjectsIn):
    _on()
    try:
        return enterprises.set_projects(e, body.projects, body.vacate)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.post("/{e}/positions")
def add_position(e: str, body: PositionIn):
    _on()
    try:
        return enterprises.add_position(e, _given(body, ("rev",)))
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.patch("/{e}/positions/{pos}")
def update_position(e: str, pos: str, body: PositionIn):
    _on()
    try:
        return enterprises.update_position(e, pos, _given(body, ("id", "rev")), rev=body.rev)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.delete("/{e}/positions/{pos}")
def remove_position(e: str, pos: str, reparent_to: Optional[str] = Query(None, max_length=48)):
    _on()
    try:
        return enterprises.remove_position(e, pos, reparent_to or None)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.post("/{e}/positions/{pos}/hire")
def hire(e: str, pos: str, body: HireIn):
    _on()
    try:
        path = enterprises.hire(e, pos, body.topic, body.name, body.template)
        return {"agent": path, "enterprise": enterprises.get(e)}
    except (enterprises.EnterpriseError, agents.AgentError) as x:
        raise _bad(x) from None


@router.get("/{e}/positions/{pos}/inbox")
def inbox(e: str, pos: str):
    _on()
    try:
        return {"items": enterprises.inbox(e, pos)}
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.get("/{e}/decisions")
def decisions(e: str, before: Optional[float] = None, limit: int = Query(50, ge=1, le=200)):
    _on()
    try:
        enterprises.load(e)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
    items, nxt = enterprises.decisions(e, before, limit)
    return {"items": items, "next": nxt}


async def startup() -> None:
    """Nothing runs by itself yet; MAXXING_ENTERPRISE_TICK=0 keeps the future background tick off (tests)."""
    if os.environ.get("MAXXING_ENTERPRISE_TICK", "1") == "0":
        return
