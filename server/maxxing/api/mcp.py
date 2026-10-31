"""MCP servers of Claude Code (Settings -> MCP): list with state, add, remove, OAuth connection.
See maxxing/mcp.py and docs/dev/API.md#mcp."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import bus, mcp
from ..security import require_auth

router = APIRouter(tags=["mcp"], dependencies=[Depends(require_auth)])


async def _call(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except mcp.McpError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


@router.get("/api/mcp")
async def list_servers():
    out = await _call(mcp.overview)
    if out["checked_at"] is None and not out["checking"] and out["servers"]:
        await _call(mcp.check)                   # first visit: states come in the background
        out["checking"] = True
    return out


@router.post("/api/mcp/check")
async def check():
    st = await _call(mcp.check)
    bus.invalidate("mcp")
    return {"checking": True, "checked_at": st.get("at")}


class AutoIn(BaseModel):
    enabled: bool


@router.put("/api/mcp/auto")
async def set_auto(body: AutoIn):
    """Each turn loads only the MCP servers its session needs (mcp_auto.py)."""
    from .. import config
    config.update_config(mcp_auto=body.enabled)
    if body.enabled:
        await _call(mcp.check)                   # the claude.ai connectors get known (listed to the turns)
    bus.invalidate("mcp")
    return {"ok": True, "enabled": body.enabled}


class AddIn(BaseModel):
    name: str
    where: Optional[str] = None          # workspace-relative folder (a topic); empty = every session
    type: str = "http"                   # http | sse | stdio
    url: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list[str] | str] = None
    headers: Optional[dict[str, str]] = None
    env: Optional[dict[str, str]] = None


@router.post("/api/mcp")
async def add(body: AddIn):
    spec = body.model_dump(exclude={"name", "where"})
    out = await _call(mcp.add, body.name.strip(), spec, (body.where or "").strip() or None)
    bus.invalidate("mcp")
    return out


@router.delete("/api/mcp")
async def remove(id: str):
    await _call(mcp.remove, id)
    bus.invalidate("mcp")
    return {"ok": True}


class LoginIn(BaseModel):
    id: str


@router.post("/api/mcp/login")
async def login_start(body: LoginIn):
    return await _call(mcp.login_start, body.id)


class FinishIn(BaseModel):
    redirect: str


@router.post("/api/mcp/login/{key}")
async def login_finish(key: str, body: FinishIn):
    return await _call(mcp.login_finish, key, body.redirect)


@router.delete("/api/mcp/login/{key}")
async def login_cancel(key: str):
    await _call(mcp.login_cancel, key)
    return {"ok": True}


async def startup() -> None:
    from .. import workspace
    workspace.on_change(mcp.on_workspace_change)
