"""First-login wizard progress. See docs/dev/API.md#onboarding.

Every check is cheap (no network call): the wizard polls it after each step.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from .. import bus, config, security, workspace
from ..security import require_auth
from .claude import auth_status

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"], dependencies=[Depends(require_auth)])


def steps() -> dict:
    cfg = config.load_config()
    try:
        has_topic = bool(workspace.list_topics())
    except OSError:
        has_topic = False
    return {"password": security.password_is_set(),
            "claude": bool(auth_status()["ok"]),
            "workspace": has_topic,
            "telegram": bool((cfg.get("telegram") or {}).get("chat_id")),
            "backup": bool((cfg.get("backup") or {}).get("repo")),
            "profile": bool((cfg.get("register") or {}).get("asked"))}


@router.get("")
async def get_onboarding():
    return {"completed": bool(config.load_config().get("onboarding_completed")),
            "steps": await asyncio.to_thread(steps)}


def _enable_pending_jobs() -> list[str]:
    """Claude signed in: the default jobs that wait for it (Memory compaction) are turned on, once."""
    if not auth_status()["ok"]:
        return []
    from .. import cmd_core
    return cmd_core.enable_pending_jobs()


@router.post("/complete")
async def complete():
    config.update_config(onboarding_completed=True)
    enabled = await asyncio.to_thread(_enable_pending_jobs)
    bus.invalidate("health")
    if enabled:
        bus.invalidate("crons")
    return {"ok": True, "jobs_enabled": enabled}
