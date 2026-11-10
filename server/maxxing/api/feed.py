"""Notifications feed + its sources (webhooks) and Telegram rules. See docs/dev/API.md#feed."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import bus, feed, feedhooks
from ..feed import FeedError
from ..security import require_auth

router = APIRouter(prefix="/api/feed", tags=["feed"], dependencies=[Depends(require_auth)])
WATCH_S = 3.0
ALERTS_S = 30.0
log = logging.getLogger("maxxing.feed")
_task: asyncio.Task | None = None


async def _call(fn: Callable[..., Any], *a: Any, **kw: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *a, **kw)
    except FeedError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


class PostIn(BaseModel):
    title: str
    body: str = ""
    level: str = "info"
    source: str = "custom"
    url: str = ""
    dedupe: str | None = None
    group: str | None = None


class ReadIn(BaseModel):
    ids: list[int] | None = None
    source: str | None = None
    all: bool = False


class SettingsIn(BaseModel):
    telegram: bool | None = None
    rules: dict[str, str] | None = None
    health: bool | None = None


class HookIn(BaseModel):
    name: str
    kind: str
    secret: str = ""


class HookPatch(BaseModel):
    secret: str | None = None
    regenerate: bool = False


@router.get("")
async def list_events(source: str | None = None, unread: bool = False, before: int | None = None,
                      limit: int = Query(50, ge=1, le=200), pending: bool = False):
    return await _call(feed.list_events, source, unread, before, limit, pending)


@router.post("")
async def post_event(body: PostIn):
    ev = await _call(feed.post, body.title, body.body, body.level, body.source, body.url, body.dedupe, body.group)
    return {"event": ev, "duplicate": ev is None}


@router.post("/read")
async def mark_read(body: ReadIn):
    return {"unread": await _call(feed.mark_read, body.ids, body.source, body.all)}


@router.post("/{event_id}/act/{action}")
async def act(event_id: int, action: str):
    """A button of an event (Allow / Deny of an agent's request, Seen...) -> the event after it. Idempotent."""
    if feed._id(event_id) is None:
        raise HTTPException(404, detail={"error": "not_found", "message": "No such event"})
    try:
        return {"event": await _call(feed.act, event_id, action, "web")}
    except Exception as e:  # noqa: BLE001 - an approval error from its module
        status = getattr(e, "status", None)
        if isinstance(e, HTTPException) or not status:
            raise
        raise HTTPException(status, detail={"error": getattr(e, "code", "error"),
                                            "message": getattr(e, "message", str(e))}) from None


@router.delete("/{event_id}")
async def delete_event(event_id: int):
    await _call(feed.delete, event_id)
    return {"ok": True}


def _settings_view() -> dict:
    s = feed.settings()
    seen = {x["source"] for x in feed.source_counts()}
    names = list(feed.BUILTIN) + [h["name"] for h in s["hooks"]]
    names += sorted(seen - set(names))
    sources = [{"source": n, "label": feed.BUILTIN.get(n, n), "builtin": n in feed.BUILTIN,
                "rule": s["rules"].get(n, "auto"), "own_thread": n in feed.OWN_THREAD} for n in names]
    return {"telegram": s["telegram"], "health": s["health"], "sources": sources, "hooks": feedhooks.list_hooks(),
            "kinds": list(feedhooks.KINDS), "rules": list(feed.RULES)}


@router.get("/settings")
async def get_settings():
    return await _call(_settings_view)


@router.put("/settings")
async def put_settings(body: SettingsIn):
    if body.rules is not None:
        rules = {**feed.settings()["rules"], **body.rules}
    else:
        rules = None
    await _call(feed.save_settings, body.telegram, rules, None, body.health)
    return await _call(_settings_view)


@router.post("/hooks")
async def create_hook(body: HookIn):
    return await _call(feedhooks.create, body.name, body.kind, body.secret)


@router.patch("/hooks/{hid}")
async def patch_hook(hid: str, body: HookPatch):
    return await _call(feedhooks.update, hid, body.secret, body.regenerate)


@router.delete("/hooks/{hid}")
async def delete_hook(hid: str):
    await _call(feedhooks.remove, hid)
    return {"ok": True}


@router.post("/hooks/{hid}/test")
async def test_hook(hid: str):
    return {"event": await _call(feedhooks.test, hid)}


def _alerts_pass() -> None:
    """Alerts that come from a state, not an event: server health, agents' broken triggers."""
    from .. import agents, config, health
    try:
        health.sync_feed()
    except Exception:  # noqa: BLE001
        log.exception("feed: health pass failed")
    try:
        health.record_history()                     # one sample every 5 min (Settings -> System, usage history)
    except Exception:  # noqa: BLE001
        log.exception("feed: usage history failed")
    if config.load_config().get("agents_page"):
        try:
            agents.check_alerts()
        except Exception:  # noqa: BLE001
            log.exception("feed: agents pass failed")


async def _watch() -> None:
    """Events written by other processes (cron runs, `maxxing feed post`): tell the UI. Every ALERTS_S: _alerts_pass."""
    last = None
    loop = asyncio.get_running_loop()
    next_alerts = loop.time() + 20                  # not at the very start: the health cache warms up first
    while True:
        try:
            cur = await asyncio.to_thread(feed.watch_id)
            if last is not None and cur != last:
                bus.invalidate("feed")
            last = cur
        except Exception:  # noqa: BLE001 - keep watching
            pass
        if loop.time() >= next_alerts:
            next_alerts = loop.time() + ALERTS_S
            await asyncio.to_thread(_alerts_pass)
        await asyncio.sleep(WATCH_S)


async def startup() -> None:
    global _task
    _task = asyncio.create_task(_watch())


async def shutdown() -> None:
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
