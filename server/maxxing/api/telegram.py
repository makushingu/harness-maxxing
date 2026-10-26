"""Telegram setup & status endpoints. See docs/dev/API.md#telegram.

The gateway itself lives in maxxing.telegram.gateway; `startup()` registers the session /
workspace hooks and starts polling when a token and a linked chat exist.
"""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..security import require_auth
from ..telegram import gateway

router = APIRouter(prefix="/api/telegram", tags=["telegram"], dependencies=[Depends(require_auth)])


class TokenIn(BaseModel):
    token: str


class SettingsIn(BaseModel):
    notify_crons: bool | None = None
    notify_system: bool | None = None
    login_alerts: bool | None = None
    reply_mode: Literal["final", "progress"] | None = None
    thread_days: int | None = None
    mirror_web: bool | None = None


def _bad(code: str, e: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status, detail={"error": code, "message": str(e)})


async def startup() -> None:
    gateway.install_hooks()
    await gateway.start()


async def shutdown() -> None:
    await gateway.stop()


@router.get("")
async def get_status():
    return gateway.status()


@router.post("/token")
async def set_token(body: TokenIn):
    try:
        bot = await gateway.set_token(body.token)
    except ValueError as e:
        raise _bad("bad_token", e) from None
    return {"ok": True, "bot": {"id": bot["id"], "username": bot["username"], "name": bot["name"]}}


@router.post("/link")
async def new_link():
    try:
        link = gateway.new_link()
    except ValueError as e:
        raise _bad("not_configured", e, 409) from None
    await gateway.start()
    return link


@router.get("/link")
async def get_link():
    return gateway.link_status()


@router.post("/sync")
async def sync():
    try:
        res = await gateway.sync()
    except ValueError as e:
        raise _bad("not_configured", e, 409) from None
    if res.get("error") and not res.get("created") and not gateway.tg_config().get("chat_id"):
        raise HTTPException(409, detail={"error": "not_linked", "message": res["error"]})
    return res


@router.put("/settings")
async def put_settings(body: SettingsIn):
    try:
        gateway.update_settings(**body.model_dump(exclude_none=True))
    except ValueError as e:
        raise _bad("invalid", e) from None
    return {"ok": True}


@router.post("/test")
async def test():
    st = gateway.status()
    if not st["configured"] or not st["chat"]:
        raise HTTPException(409, detail={"error": "not_linked", "message": "Link a Telegram chat first"})
    ok = await asyncio.to_thread(gateway.send_test)
    if not ok:
        raise HTTPException(502, detail={"error": "telegram_error",
                                         "message": "Telegram did not accept the message - see the server log"})
    return {"ok": True}


@router.delete("")
async def forget():
    await gateway.forget()
    return {"ok": True}
