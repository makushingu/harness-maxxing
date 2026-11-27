"""Web Push on the phone, even with the installed app closed (Settings -> Notifications -> Mobile notifications):
"Harness has finished", and what the Notifications feed says that cannot wait (a request waiting for an answer, with
its buttons; a warning; an error). See docs/dev/API.md#push and maxxing/webpush.py."""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, feed, webpush
from ..security import require_auth

log = logging.getLogger("maxxing.push")

router = APIRouter(prefix="/api/push", tags=["push"], dependencies=[Depends(require_auth)])

PREVIEW = 120
_TEXT = {
    "en": {"done": "Harness has finished", "failed": "A Harness turn failed", "test": "Mobile notifications work on this device.", "allow": "Allow", "deny": "Deny"},
    "fr": {"done": "Harness a terminé", "failed": "Un tour de Harness a échoué", "test": "Les notifications mobiles fonctionnent sur cet appareil.", "allow": "Autoriser", "deny": "Refuser"},
    "es": {"done": "Harness ha terminado", "failed": "Un turno de Harness ha fallado", "test": "Las notificaciones móviles funcionan en este dispositivo.", "allow": "Permitir", "deny": "Denegar"},
    "de": {"done": "Harness ist fertig", "failed": "Ein Durchlauf von Harness ist fehlgeschlagen", "test": "Mobile Benachrichtigungen funktionieren auf diesem Gerät.", "allow": "Erlauben", "deny": "Ablehnen"},
    "zh": {"done": "Harness 已完成", "failed": "Harness 的一个回合失败了", "test": "移动通知在此设备上可用。", "allow": "允许", "deny": "拒绝"},
    "ja": {"done": "Harness が完了しました", "failed": "Harness のターンが失敗しました", "test": "このデバイスでモバイル通知が使えます。", "allow": "許可", "deny": "拒否"},
}


def _text(key: str) -> str:
    return _TEXT.get(config.language(), _TEXT["en"])[key]


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


def _still_open(items: list[dict]) -> list[dict]:
    """Without the feed events answered since they were queued (on the computer, on Telegram, on another phone)."""
    out = []
    for m in items:
        ev = feed.get(m["event"]) if m.get("event") else None
        if m.get("event") and (not ev or ev.get("resolved") or ev.get("read")):
            continue
        out.append(m)
    return out


@router.post("/pending")
async def pending(body: Pending):
    return {"items": await asyncio.to_thread(lambda: _still_open(webpush.pending(body.device)))}


FEED_S = 3.0
_feed_last: int | None = None
_feed_task: asyncio.Task | None = None


def feed_item(ev: dict) -> dict:
    """A feed event as a phone notification. Its buttons (two at most, the ones that answer: a tap on the notification
    already opens it) only when the whole text fits: nobody allows a request cut short."""
    body = str(ev.get("body") or "")
    whole = len(body) <= webpush.BODY_MAX
    acts = [{"id": a["id"], "label": _TEXT.get(config.language(), _TEXT["en"]).get(a["id"], a.get("label") or a["id"])}
            for a in ev.get("actions") or [] if a.get("style") != "link" and a.get("id") != "open"
            and (whole or a.get("style") == "danger")][:2]
    return {"title": str(ev.get("title") or "Harness"), "body": body if whole else body[:webpush.BODY_MAX - 1] + "…",
            "url": str(ev.get("url") or "/"), "tag": f"mx-feed-{ev['id']}", "event": int(ev["id"]), "actions": acts}


def scan_feed() -> int:
    """Send the events posted to the feed since the last look (by any process: a cron run, the CLI, an agent) to the
    phones, when they ring there (feed.rings_phone). The first look only notes where the feed is."""
    global _feed_last
    if not webpush.devices():
        _feed_last = None
        return 0
    top, last = feed.max_id(), _feed_last
    if last is None or top <= last:
        _feed_last = top
        return 0
    events = feed.events_after(last, 50)
    _feed_last = events[-1]["id"] if events else top
    s, n = feed.settings(), 0
    for ev in events:
        if feed.rings_phone(ev, s):
            webpush.notify(**feed_item(ev))
            n += 1
    return n


async def _feed_loop() -> None:
    while True:
        await asyncio.sleep(FEED_S)
        try:
            await asyncio.to_thread(scan_feed)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a push problem never stops the loop
            log.exception("push: feed scan")


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
    global _feed_task, _feed_last
    _feed_last = None
    _feed_task = asyncio.create_task(_feed_loop())
