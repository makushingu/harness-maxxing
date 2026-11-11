"""Agents (Settings -> Features: agents_page). See docs/dev/API.md#agents and maxxing/agents.py.

The server also runs the agents' background work: the result of every agent turn goes to its thread
(service.on_turn_end), new feed events are matched against the feed triggers every FEED_POLL_S, and the
events waiting for their debounce window are fired.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

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
    skin: Optional[str] = None
    hair: Optional[str] = None
    hair_color: Optional[str] = None
    face: Optional[str] = None
    accessory: Optional[str] = None


class Limits(BaseModel):
    usd_per_day: Optional[float] = None
    runs_per_hour: Optional[int] = None
    timeout_s: Optional[int] = None
    debounce_s: Optional[int] = None
    approval_timeout_s: Optional[int] = None
    chat_idle_h: Optional[int] = None


class Trigger(BaseModel):
    id: Optional[str] = None
    kind: Literal["feed"] = "feed"
    enabled: Optional[bool] = None
    source: Optional[str] = None
    levels: Optional[list[str]] = None
    match: Optional[str] = None
    prompt: Optional[str] = None
    hook_id: Optional[str] = None


class Rule(BaseModel):
    tool: str = "*"
    match: str = ""
    reason: Optional[str] = None


class ImportIn(BaseModel):
    topic_path: str
    markdown: str = Field(max_length=64_000)
    name: Optional[str] = None


class AgentIn(BaseModel):
    topic_path: Optional[str] = None          # create only
    name: Optional[str] = None                # create only: the folder slug
    template: Optional[str] = Field(default=None, max_length=64)   # create only: a ready-made agent, under the fields
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
    silent: Optional[bool] = None
    trust_outside: Optional[bool] = None
    keys: Optional[list[str]] = Field(default=None, max_length=50)
    limits: Optional[Limits] = None
    triggers: Optional[list[Trigger]] = None
    sandbox: Optional[bool] = None
    domains: Optional[list[str]] = Field(default=None, max_length=50)
    writable: Optional[list[str]] = Field(default=None, max_length=20)
    rules: Optional[list[Rule]] = Field(default=None, max_length=20)
    subagent: Optional[bool] = None
    chat_model: Optional[str] = Field(default=None, max_length=80)   # its model ("" = model)
    mail: Optional[list[dict]] = Field(default=None, max_length=10)    # mailboxes of the E-mail page (mail/access.py)


def _fields(body: AgentIn) -> dict:
    f = body.model_dump(exclude_none=True, exclude={"topic_path", "name", "display_name", "template"})
    if f.get("mail"):
        from .. import mail
        have = {a["id"] for a in mail.list_accounts()}
        accs = [str(g.get("account") or "").strip().lower() for g in f["mail"] if isinstance(g, dict)]
        bad = [a for a in accs if a not in have]
        if bad:
            raise HTTPException(400, detail={"error": "bad_mail", "message": f"No mailbox {bad[0]!r} on the E-mail page"})
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
    reply_to: Optional[str] = None       # a thread message: its session goes on (no new session)
    attachments: list[str] = Field(default_factory=list, max_length=agents.ATTACH_MAX)  # under <agent>/attachments/
    model: Optional[str] = Field(default=None, max_length=80)     # a new conversation's model (the owner's pick)


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


@router.get("/templates")
def list_templates(lang: Optional[str] = Query(default=None, max_length=8)):
    """The gallery of ready-made agents, texts in `lang` (default: the UI language)."""
    from .. import agent_templates, config, vault
    _on()
    have = {x["name"] for x in vault.list_secrets()}
    out = agent_templates.listing(lang or config.load_config().get("language") or "en")
    for t in out:
        t["keys_present"] = [k for k in t["keys"] if k in have]
    return {"templates": out}


@router.get("/sandbox")
def sandbox_status():
    """What the sandbox of agents needs on this server: {ok, missing: [bwrap|socat|apparmor|linux]}."""
    from .. import agent_guard
    _on()
    return agent_guard.available(fresh=True)


@router.get("/layout")
def get_layout():
    """The order of projects and agents and the project colours picked on the Agents page (agents.load_layout)."""
    _on()
    return agents.load_layout()


@router.put("/layout")
def put_layout(body: Any = Body(...)):
    _on()
    try:
        return agents.save_layout(body)
    except agents.AgentError as e:
        raise _bad(e) from None


@router.post("/import")
def import_agent(body: ImportIn):
    """Create an agent from a Claude Code agent file (.claude/agents/<name>.md)."""
    from .. import agent_format
    _on()
    try:
        return agent_format.import_md(body.topic_path, body.markdown, body.name or None)
    except ValueError as e:
        raise HTTPException(400, detail={"error": "bad_file", "message": str(e)}) from None
    except agents.AgentError as e:
        raise _bad(e) from None


@router.post("")
def create_agent(body: AgentIn):
    _on()
    if not body.topic_path or not body.name:
        raise HTTPException(400, detail={"error": "missing", "message": "topic_path and name are required"})
    fields = _fields(body)
    if body.template:                           # what the CLI's --template gives (domains, writable...), the form on top
        from .. import agent_templates, config, vault
        tpl = agent_templates.get(body.template, config.load_config().get("language") or "en")
        if tpl is None:
            raise HTTPException(400, detail={"error": "bad_template", "message": f"No template {body.template!r}"})
        fields = {**agent_templates.fields(tpl, [x["name"] for x in vault.list_secrets()]), **fields}
    try:
        return agents.create(body.topic_path, body.name, fields)
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


@router.get("/{project}/{topic}/{name}/media-roots")
def agent_media_roots(project: str, topic: str, name: str):
    """The folders whose files the agent's answers may show on its page (agent_guard.media_roots)."""
    _on()
    try:
        path = _path(project, topic, name)
    except agents.AgentError as e:
        raise _bad(e) from None
    if not agents.exists(path):
        raise HTTPException(404, detail={"error": "not_found", "message": "Agent not found"})
    from .. import agent_guard
    return {"roots": agent_guard.media_roots(path)}


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


@router.get("/{project}/{topic}/{name}/export")
def export_agent(project: str, topic: str, name: str):
    """The agent as a Claude Code agent file (.claude/agents/<name>.md)."""
    from fastapi.responses import PlainTextResponse
    from .. import agent_format
    _on()
    path = _path(project, topic, name)
    if not agents.exists(path):
        raise HTTPException(404, detail={"error": "not_found", "message": "Agent not found"})
    return PlainTextResponse(agent_format.export_md(path), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}.md"'})


@router.post("/{project}/{topic}/{name}/runs/{sid}/continue")
def continue_run(project: str, topic: str, name: str, sid: str):
    """Continue in Sessions: a copy of this run as a normal session of the topic (same history and Claude thread)."""
    _on()
    try:
        return {"session": agents.continue_in_sessions(_path(project, topic, name), sid)}
    except agents.AgentError as e:
        raise _bad(e) from None


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
    try:
        files = agents.checked_attachments(agents.folder(path), body.attachments)
    except agents.AgentError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None
    if files and not text:
        text = "See the attached files."
    try:                       # typed by the user: an instruction, not outside data (no markers)
        return agents.fire(path, trigger="manual", prompt=text, source="manual", reply_to=body.reply_to or None,
                           attachments=files or None, model=(body.model or "").strip() or None)
    except Exception as e:     # SessionError (bad model...)
        raise HTTPException(getattr(e, "status", 500),
                            detail={"error": getattr(e, "code", "run_failed"), "message": str(e)}) from None


@router.post("/{project}/{topic}/{name}/chat/new")
def agent_new_chat(project: str, topic: str, name: str):
    """The next message of the owner starts a new conversation."""
    _on()
    path = _path(project, topic, name)
    if not agents.exists(path):
        raise HTTPException(404, detail={"error": "not_found", "message": "Agent not found"})
    return {"ok": agents.new_chat(path)}


@router.post("/{project}/{topic}/{name}/seen")
def agent_seen(project: str, topic: str, name: str):
    _on()
    path = _path(project, topic, name)
    if not agents.exists(path):
        raise HTTPException(404, detail={"error": "not_found", "message": "Agent not found"})
    agents.mark_seen(path)
    return {"ok": True}


@router.post("/{project}/{topic}/{name}/triggers/{tid}/test")
def test_trigger(project: str, topic: str, name: str, tid: str):
    _on()
    try:
        return agents.test_trigger(_path(project, topic, name), tid)
    except agents.AgentError as e:
        raise _bad(e) from None


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
    last_scan, paused = 0.0, False
    while True:
        await asyncio.sleep(TICK_S)
        try:
            if not agents.feature_on():             # feed triggers wait; their backlog is skipped once back on
                if not paused:
                    await asyncio.to_thread(agents.pause_feed)
                    paused = True
                continue
            paused = False
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

