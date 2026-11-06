"""Agent groups (in the Agents page, Settings -> Features: agents_page). See docs/dev/API.md#agent-groups and
maxxing/agent_rooms.py. Only the owner (the signed-in user) writes to a group; its members answer in turn."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from .. import agent_rooms, agents
from ..security import require_auth

log = logging.getLogger("maxxing.api.agent_groups")
router = APIRouter(prefix="/api/agent-groups", tags=["agents"], dependencies=[Depends(require_auth)])


def _on() -> None:
    if not agents.feature_on():
        raise HTTPException(404, detail={"error": "feature_off", "message": "Agents are off (Settings -> Features)"})


def _bad(e: agents.AgentError) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.code, "message": e.message})


def _path(project: str, name: str) -> str:
    path = agent_rooms.group_path(project, name)
    if not agent_rooms.parse(path):
        raise HTTPException(400, detail={"error": "bad_path", "message": "Not a group"})
    return path


def _get(project: str, name: str) -> str:
    path = _path(project, name)
    if not agent_rooms.exists(path):
        raise HTTPException(404, detail={"error": "not_found", "message": "Group not found"})
    return path


class Member(BaseModel):
    path: str = Field(max_length=200)
    role: str = Field("", max_length=agent_rooms.ROLE_MAX)
    handle: str = Field("", max_length=48)              # its @name in the group ("": kept, else made)


class Limits(BaseModel):
    waves: Optional[int] = None
    replies: Optional[int] = None
    per_hour: Optional[int] = None


class GroupIn(BaseModel):
    project: Optional[str] = None          # create only
    name: Optional[str] = None             # create only: the folder slug
    display_name: Optional[str] = Field(None, max_length=agent_rooms.NAME_MAX)
    emoji: Optional[str] = Field(None, max_length=16)
    goal: Optional[str] = Field(None, max_length=agent_rooms.GOAL_MAX)
    members: Optional[list[Member]] = Field(None, max_length=agent_rooms.MAX_MEMBERS + 4)
    lead: Optional[str] = Field(None, max_length=200)
    shared_files: Optional[bool] = None
    trust_members: Optional[bool] = None
    limits: Optional[Limits] = None


def _fields(body: GroupIn) -> dict:
    f: dict = {}
    if body.display_name is not None:
        f["name"] = body.display_name
    for k in ("emoji", "goal", "lead", "shared_files", "trust_members"):
        v = getattr(body, k)
        if v is not None:
            f[k] = v
    if body.members is not None:
        f["members"] = [m.model_dump() for m in body.members]
    if body.limits is not None:
        f["limits"] = body.limits.model_dump()
    return f


class SayIn(BaseModel):
    text: str = Field("", max_length=agent_rooms.TEXT_MAX)
    attachments: list[str] = Field(default_factory=list, max_length=agents.ATTACH_MAX)   # from .../uploads


class PauseIn(BaseModel):
    paused: bool = True


@router.get("")
def list_groups():
    _on()
    return {"groups": agent_rooms.list_groups()}


@router.post("")
def create_group(body: GroupIn):
    _on()
    try:
        return agent_rooms.create(body.project or "", body.name or "", _fields(body))
    except agents.AgentError as e:
        raise _bad(e) from None


@router.get("/{project}/{name}")
def get_group(project: str, name: str):
    _on()
    try:
        return agent_rooms.get(_path(project, name))
    except agents.AgentError as e:
        raise _bad(e) from None


@router.patch("/{project}/{name}")
def update_group(project: str, name: str, body: GroupIn):
    _on()
    try:
        return agent_rooms.update(_get(project, name), _fields(body))
    except agents.AgentError as e:
        raise _bad(e) from None


@router.delete("/{project}/{name}")
def delete_group(project: str, name: str, keep_files: bool = Query(False)):
    _on()
    try:
        agent_rooms.delete(_get(project, name), keep_files=keep_files)
    except agents.AgentError as e:
        raise _bad(e) from None
    return {"ok": True}


@router.get("/{project}/{name}/messages")
def group_messages(project: str, name: str, limit: int = Query(200, ge=1, le=1000),
                   before: Optional[float] = Query(None), after: Optional[float] = Query(None)):
    _on()
    return {"messages": agent_rooms.room(_get(project, name), limit, before, after)}


@router.post("/{project}/{name}/messages")
def group_say(project: str, name: str, body: SayIn):
    _on()
    try:
        return agent_rooms.say(_get(project, name), body.text, body.attachments)
    except agents.AgentError as e:
        raise _bad(e) from None


@router.post("/{project}/{name}/uploads")
async def group_uploads(project: str, name: str, file: list[UploadFile] = File(...)):
    """Files for the next message of the owner, saved under <group>/attachments/YYYY-MM/ (read by every member)."""
    _on()
    from ..sessions.service import SessionError
    from .sessions import save_uploads
    path = _get(project, name)
    try:
        folder = await asyncio.to_thread(agent_rooms.attachments_dir, path)
    except SessionError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": str(e)}) from None
    return {"files": await asyncio.to_thread(save_uploads, file, folder)}


@router.post("/{project}/{name}/stop")
def group_stop(project: str, name: str):
    _on()
    agent_rooms.stop(_get(project, name))
    return {"ok": True}


@router.post("/{project}/{name}/reset")
def group_reset(project: str, name: str):
    _on()
    agent_rooms.reset(_get(project, name))
    return {"ok": True}


@router.post("/{project}/{name}/seen")
def group_seen(project: str, name: str):
    _on()
    agent_rooms.mark_seen(_get(project, name))
    return {"ok": True}


@router.post("/{project}/{name}/members/{mp}/{mt}/{ma}/pause")
def group_pause(project: str, name: str, mp: str, mt: str, ma: str, body: PauseIn):
    _on()
    try:
        return agent_rooms.set_paused(_get(project, name), agents.agent_path(mp, mt, ma), body.paused)
    except agents.AgentError as e:
        raise _bad(e) from None


async def startup() -> None:
    if agents.feature_on():
        try:
            await asyncio.to_thread(agent_rooms.recover)
        except Exception:  # noqa: BLE001
            log.exception("agent groups recovery")
