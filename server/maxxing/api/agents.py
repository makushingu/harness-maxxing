"""Agents (Settings -> Features: agents_page). See docs/dev/API.md#agents and maxxing/agents.py.

The server also runs the agents' background work: the result of every agent turn goes to its thread
(service.on_turn_end), new feed events are matched against the feed triggers every FEED_POLL_S, and the
events waiting for their debounce window are fired.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import agents
from ..security import require_auth

log = logging.getLogger("maxxing.api.agents")
router = APIRouter(prefix="/api/agents", tags=["agents"], dependencies=[Depends(require_auth)])


def _on() -> None:
    if not agents.feature_on():
        raise HTTPException(404, detail={"error": "feature_off", "message": "Agents are off (Settings -> Features)"})


def _bad(e: agents.AgentError) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.code, "message": e.message})


def _path(project: str, topic: str, name: str) -> str:
    return agents.agent_path(project, topic, name)


class Avatar(BaseModel):
    color: Optional[str] = None
    eyes: Optional[str] = None
    mouth: Optional[str] = None
    hat: Optional[str] = None
    bg: Optional[str] = None


class Limits(BaseModel):
    usd_per_day: Optional[float] = None
    runs_per_hour: Optional[int] = None
    timeout_s: Optional[int] = None
    debounce_s: Optional[int] = None
    approval_timeout_s: Optional[int] = None


class Trigger(BaseModel):
    id: Optional[str] = None
    kind: Literal["feed"] = "feed"
    enabled: Optional[bool] = None
    source: Optional[str] = None
    levels: Optional[list[str]] = None
    match: Optional[str] = None
    prompt: Optional[str] = None
    hook_id: Optional[str] = None


class AgentIn(BaseModel):
    topic_path: Optional[str] = None          # create only
    name: Optional[str] = None                # create only: the folder slug
    display_name: Optional[str] = None
    description: Optional[str] = None         # the role (CLAUDE.md)
    avatar: Optional[Avatar] = None
    enabled: Optional[bool] = None
    model: Optional[str] = None
    permission_mode: Optional[Literal["", "bypass", "acceptEdits", "default"]] = None
    allowed_tools: Optional[list[str]] = None
    disallowed_tools: Optional[list[str]] = None
    telegram: Optional[bool] = None
    approvals: Optional[bool] = None
    limits: Optional[Limits] = None
    triggers: Optional[list[Trigger]] = None


def _fields(body: AgentIn) -> dict:
    f = body.model_dump(exclude_none=True, exclude={"topic_path", "name", "display_name"})
    if body.display_name is not None:
        f["name"] = body.display_name
    for k in ("avatar", "limits"):
        if k in f:
            f[k] = {a: b for a, b in f[k].items() if b is not None}
    if "triggers" in f:
        f["triggers"] = [{a: b for a, b in t.items() if b is not None} for t in f["triggers"]]
    return f


class RunIn(BaseModel):
    text: Optional[str] = None


class WebhookIn(BaseModel):
    kind: Literal["generic", "stripe", "shopify", "github"] = "generic"
    prompt: Optional[str] = None
    levels: Optional[list[str]] = None
    match: Optional[str] = None


class CronIn(BaseModel):
    name: Optional[str] = None
    schedule: Optional[str] = None
    prompt: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("")
def list_agents():
    _on()
    return {"agents": agents.list_agents(with_status=True), "avatar": {k: list(v) for k, v in agents.AVATAR.items()}}


@router.post("")
def create_agent(body: AgentIn):
    _on()
    if not body.topic_path or not body.name:
        raise HTTPException(400, detail={"error": "missing", "message": "topic_path and name are required"})
    try:
        return agents.create(body.topic_path, body.name, _fields(body))
    except agents.AgentError as e:
        raise _bad(e) from None


@router.get("/{project}/{topic}/{name}")
def get_agent(project: str, topic: str, name: str):
    _on()
    try:
        a = agents.get(_path(project, topic, name))
    except agents.AgentError as e:
        raise _bad(e) from None
    return {**a, "crons": agents.cron_jobs(a["path"])}


@router.patch("/{project}/{topic}/{name}")
def update_agent(project: str, topic: str, name: str, body: AgentIn):
    _on()
    try:
        return agents.update(_path(project, topic, name), _fields(body))
    except agents.AgentError as e:
        raise _bad(e) from None


@router.delete("/{project}/{topic}/{name}")
def delete_agent(project: str, topic: str, name: str):
    _on()
    try:
        agents.delete(_path(project, topic, name))
    except agents.AgentError as e:
        raise _bad(e) from None
    return {"ok": True}


@router.get("/{project}/{topic}/{name}/thread")
def agent_thread(project: str, topic: str, name: str, limit: int = Query(100, ge=1, le=500),
                 before: Optional[float] = None):
    _on()
    path = _path(project, topic, name)
    if not agents.exists(path):
        raise HTTPException(404, detail={"error": "not_found", "message": "Agent not found"})
    return {"messages": agents.thread(path, limit, before)}


@router.post("/{project}/{topic}/{name}/run")
def run_agent(project: str, topic: str, name: str, body: RunIn):
    _on()
    path = _path(project, topic, name)
    if not agents.exists(path):
        raise HTTPException(404, detail={"error": "not_found", "message": "Agent not found"})
    text = (body.text or "").strip()
    try:                       # typed by the user: an instruction, not outside data (no markers)
        return agents.fire(path, trigger="manual", prompt=text, source="manual")
    except Exception as e:     # SessionError (bad model...)
        raise HTTPException(getattr(e, "status", 500),
                            detail={"error": getattr(e, "code", "run_failed"), "message": str(e)}) from None


@router.post("/{project}/{topic}/{name}/webhook")
def add_webhook(project: str, topic: str, name: str, body: WebhookIn):
    _on()
    try:
        return agents.add_webhook(_path(project, topic, name), body.kind, body.prompt or "", body.levels or [],
                                  body.match or "")
    except agents.AgentError as e:
        raise _bad(e) from None


@router.post("/{project}/{topic}/{name}/crons")
def add_cron(project: str, topic: str, name: str, body: CronIn):
    """A cron trigger = a Claude cron job in the agent folder (shown on the Crons page too)."""
    _on()
    try:
        return agents.add_cron(_path(project, topic, name), body.schedule or "", body.prompt or "", body.name or "",
                               body.enabled is not False)
    except agents.AgentError as e:
        raise _bad(e) from None


# ---- background work (server) ----------------------------------------------------------------------
_task: asyncio.Task | None = None
TICK_S = 2.0


async def _loop() -> None:
    last_scan = 0.0
    while True:
        await asyncio.sleep(TICK_S)
        try:
            if not agents.feature_on():
                continue
            now = asyncio.get_running_loop().time()
            if now - last_scan >= agents.FEED_POLL_S:
                last_scan = now
                await asyncio.to_thread(agents.scan_feed)
            if agents.debouncer.pending:
                await asyncio.to_thread(agents.flush_due)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("agents loop")


async def _turn_end(session: dict, result: dict | None) -> None:
    if agents.is_agent_path(session.get("path")) and session.get("source") == "agent":
        await asyncio.to_thread(agents.on_turn_end, session, result)


async def startup() -> None:
    global _task
    from ..sessions import service
    service.on_turn_end(_turn_end)
    _task = asyncio.get_running_loop().create_task(_loop())


async def shutdown() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None

