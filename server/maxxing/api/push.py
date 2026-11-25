"""Web Push: "Harness has finished" on the phone, even with the installed app closed (Settings -> Alerts ->
Mobile notifications). See docs/dev/API.md#push and maxxing/webpush.py."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, webpush
from ..security import require_auth

log = logging.getLogger("maxxing.push")

router = APIRouter(prefix="/api/push", tags=["push"], dependencies=[Depends(require_auth)])

PREVIEW = 120
_TEXT = {
    "en": {"done": "Harness has finished", "failed": "A Harness turn failed", "test": "Mobile notifications work on this device."},
    "fr": {"done": "Harness a terminé", "failed": "Un tour de Harness a échoué", "test": "Les notifications mobiles fonctionnent sur cet appareil."},
}


def _text(key: str) -> str:
    return _TEXT.get(config.load_config().get("language", "en"), _TEXT["en"])[key]


class Device(BaseModel):
    endpoint: str
    label: str = ""


class Pending(BaseModel):
    device: str


@router.get("/key")
async def key():
    return {"key": await asyncio.to_thread(webpush.public_key)}


@router.get("/devices")
async def devices():
    return await asyncio.to_thread(webpush.devices)


@router.post("/devices")
async def add_device(body: Device):
    try:
        return await asyncio.to_thread(webpush.add_device, body.endpoint, body.label)
    except ValueError as e:
        raise HTTPException(400, detail={"error": "bad_endpoint", "message": str(e)})


@router.delete("/devices/{did}")
async def remove_device(did: str):
    if not await asyncio.to_thread(webpush.remove_device, did):
        raise HTTPException(404, detail={"error": "not_found", "message": "No such device"})
    return {"ok": True}


@router.post("/test")
async def test():
    n = await asyncio.to_thread(webpush.notify, _text("done"), _text("test"), "/settings/alerts", "mx-push-test")
    return {"sent": n}


@router.post("/pending")
async def pending(body: Pending):
    return {"items": await asyncio.to_thread(webpush.pending, body.device)}


def rings(session: dict) -> bool:
    """The same rule as the Telegram bell, for every session: a turn of a person that ended, not a job's or an
    agent's, not one answered on Telegram already, and not a session muted on the phones (`push` False)."""
    if session.get("push") is False:
        return False
    last = session.get("last_turn") if isinstance(session.get("last_turn"), dict) else {}
    return session.get("source") not in ("cron", "agent") and not session.get("cron") \
        and (last.get("kind") or "user") == "user" and (last.get("source") or "web") not in ("telegram", "cron", "system", "agent")


async def _turn_end(session: dict, result: dict | None) -> None:
    if not rings(session) or not await asyncio.to_thread(webpush.devices):
        return
    from ..telegram import format as fmt
    failed = session.get("state") == "error"
    title = session.get("title") or "Session"
    detail = str(session.get("error") or "error") if failed else fmt.preview(session.get("last_text") or "", PREVIEW)
    url = f"/sessions?path={quote(str(session.get('path') or ''), safe='/')}&session={quote(str(session.get('id') or ''))}"
    try:
        await asyncio.to_thread(webpush.notify, _text("failed" if failed else "done"),
                                f"{title} - {detail}"[:240] if detail else title, url, f"mx-session-{session.get('id')}")
    except Exception:  # noqa: BLE001 - a push problem never touches the turn
        log.exception("push of session %s", session.get("id"))


async def startup() -> None:
    from ..sessions import service
    service.on_turn_end(_turn_end)
