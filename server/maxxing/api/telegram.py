"""Telegram setup & status endpoints. See docs/dev/API.md#telegram.

The gateway itself lives in maxxing.telegram.gateway; `startup()` registers the session /
workspace hooks and starts polling when a token and a linked chat exist.
"""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import feed, security, twofactor
from ..security import require_auth
from ..telegram import gateway

router = APIRouter(prefix="/api/telegram", tags=["telegram"], dependencies=[Depends(require_auth)])


class TokenIn(BaseModel):
    token: str
    password: str | None = None         # the current password: needed to change the bot while two-step sign-in is on


class ForgetIn(BaseModel):
    password: str | None = None         # the current password: needed to unlink while two-step sign-in is on


class LinkIn(BaseModel):
    password: str | None = None         # the current password: a new link replaces the chat that gets the two-step requests


class WebhookIn(BaseModel):
    token: str | None = None


class SettingsIn(BaseModel):
    mode: Literal["simple", "threads", "mirror"] | None = None
    notify_crons: bool | None = None
    notify_system: bool | None = None
    login_alerts: bool | None = None
    reply_mode: Literal["final", "progress"] | None = None
    thread_days: int | None = None
    mirror_web: bool | None = None


def _bad(code: str, e: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status, detail={"error": getattr(e, "code", None) or code, "message": str(e),
                                         **(getattr(e, "extra", None) or {})})


async def startup() -> None:
    gateway.install_hooks()
    await gateway.start()


async def shutdown() -> None:
    await gateway.stop()


@router.get("")
async def get_status():
    return gateway.status()


async def _password_if_two_step(request: Request, password: str | None) -> None:
    """Unlinking, changing the bot or linking another chat takes two-step sign-in away from the linked chat: same
    rule as turning it off in Settings."""
    if twofactor.enabled():
        from .auth import _check_current
        await _check_current(request, password or "")


@router.post("/token")
async def set_token(body: TokenIn, request: Request):
    if body.token.strip() != (gateway.token() or ""):
        await _password_if_two_step(request, body.password)
    try:
        bot = await gateway.set_token(body.token)
    except ValueError as e:
        raise _bad("bad_token", e) from None
    return {"ok": True, "bot": {"id": bot["id"], "username": bot["username"], "name": bot["name"]}}


@router.post("/webhook/remove")
async def remove_webhook(body: WebhookIn):
    """Remove the webhook of the bot being saved (`token`) or of the stored one, then save the token again."""
    try:
        return await gateway.remove_webhook(body.token)
    except ValueError as e:
        raise _bad("bad_token", e) from None


@router.post("/link")
async def new_link(request: Request, body: LinkIn | None = None):
    await _password_if_two_step(request, body.password if body else None)
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
        res = gateway.update_settings(**body.model_dump(exclude_none=True))
    except ValueError as e:
        raise _bad("invalid", e) from None
    return {"ok": True, "mode": res["mode"], "deleting": res["deleting"]}


@router.post("/test")
async def test():
    st = gateway.status()
    if not st["configured"] or not st["chat"]:
        raise HTTPException(409, detail={"error": "not_linked", "message": "Link a Telegram chat first"})
    res = await asyncio.to_thread(gateway.send_test)
    if not res["sent"]:
        raise HTTPException(502, detail={"error": "telegram_error",
                                         "message": "Telegram did not accept the message - see the server log",
                                         **res})
    return res


@router.delete("")
async def forget(request: Request, body: ForgetIn | None = None):
    await _password_if_two_step(request, body.password if body else None)
    was_on = twofactor.enabled()
    if was_on:                      # unlinking turns two-step sign-in off: say so while the bridge still answers
        await asyncio.to_thread(twofactor.notify, "unlinked", True)
    await gateway.forget()
    if was_on:
        from .. import mfa
        feed.system("Telegram unlinked: its approval is no longer asked at sign-in" if mfa.app_on()
                    else "Telegram unlinked: two-step sign-in turned off",
                    f"{security.client_key(request)} · {request.headers.get('user-agent', '?')[:90]}",
                    "warning", "security")
    return {"ok": True}
