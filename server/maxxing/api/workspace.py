"""Workspace: projects and topics. See docs/dev/API.md#workspace."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import workspace
from ..security import require_auth
from ..workspace import WorkspaceError

router = APIRouter(prefix="/api/workspace", tags=["workspace"], dependencies=[Depends(require_auth)])


class CreateIn(BaseModel):
    name: str
    description: str = ""


class PatchIn(BaseModel):
    name: str | None = None
    description: str | None = None


class TopicPatchIn(PatchIn):
    permission_mode: str | None = None    # "" = the global setting


class ProjectPatchIn(PatchIn):
    emoji: str | None = None     # "" removes it


async def _call(fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args, **kw)
    except WorkspaceError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


@router.get("/tree")
async def tree():
    return JSONResponse(await _call(workspace.tree))   # plain JSON: skips jsonable_encoder


class OrderIn(BaseModel):
    names: list[str]


@router.put("/order")
async def project_order(body: OrderIn):
    """Projects order (drag and drop in the Sessions tree): names in order, others come after."""
    return {"projects": await _call(workspace.set_project_order, body.names)}


@router.put("/projects/{project}/order")
async def topic_order(project: str, body: OrderIn):
    """Topics order inside a project (a topic never changes project here)."""
    return {"topics": await _call(workspace.set_topic_order, project, body.names)}


@router.post("/projects")
async def create_project(body: CreateIn):
    return await _call(workspace.create_project, body.name, body.description)


@router.patch("/projects/{project}")
async def patch_project(project: str, body: ProjectPatchIn):
    return await _call(workspace.update_project, project, body.name, body.description, body.emoji)


@router.delete("/projects/{project}")
async def delete_project(project: str):
    await _call(workspace.delete_project, project)
    return {"ok": True}


@router.post("/projects/{project}/topics")
async def create_topic(project: str, body: CreateIn):
    return await _call(workspace.create_topic, project, body.name, body.description)


@router.patch("/projects/{project}/topics/{topic}")
async def patch_topic(project: str, topic: str, body: TopicPatchIn):
    return await _call(workspace.update_topic, project, topic, body.name, body.description, body.permission_mode)


@router.delete("/projects/{project}/topics/{topic}")
async def delete_topic(project: str, topic: str):
    await _call(workspace.delete_topic, project, topic)
    return {"ok": True}
