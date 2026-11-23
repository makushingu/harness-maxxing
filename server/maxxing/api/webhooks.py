"""Settings -> Automate -> Webhooks and Events (webhooks.py). See docs/dev/API.md#webhooks.

The public URL of a hook is served by api/hooks.py. A background loop hands the events of other processes (cron runs,
agent turns: the spool) and the new feed events to the "event" hooks; at start, calls left queued or running resume.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from .. import bus, webhooks
from ..security import require_auth

log = logging.getLogger("maxxing.webhooks")
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"], dependencies=[Depends(require_auth)])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except webhooks.WebhookError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


def _agent_hooks() -> dict[str, str]:
    """Feed webhook id -> the agent whose webhook trigger it is."""
    out: dict[str, str] = {}
    with contextlib.suppress(Exception):
        from .. import agents
        for a in agents.list_agents(counts=False):
            for t in a.get("triggers") or []:
                if t.get("hook_id"):
                    out[t["hook_id"]] = a["path"]
    return out


def _listing() -> dict:
    from .. import config, feedhooks
    owners = _agent_hooks()
    feed_hooks = []
    with contextlib.suppress(Exception):
        for h in feedhooks.list_hooks():
            feed_hooks.append({k: h.get(k) for k in ("id", "name", "kind", "url", "has_secret", "created")}
                              | {"agent": owners.get(h["id"])})
    public = (config.load_config().get("public_url") or "").startswith("https://")
    return {"hooks": webhooks.list_hooks(), "feed_hooks": feed_hooks, "https": public}


@router.get("")
async def list_all():
    return await asyncio.to_thread(_listing)


class HookIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    trigger: Optional[dict] = None
    action: Optional[dict] = None
    queue: Optional[dict] = None
    report: Optional[str] = None
    secret: Optional[str] = None


@router.post("")
async def create(body: HookIn):
    spec = body.model_dump(exclude_none=True)
    secret = spec.pop("secret", None)
    return await asyncio.to_thread(_call, webhooks.create, spec, secret)


@router.get("/{hid}")
async def one(hid: str):
    h = await asyncio.to_thread(_call, webhooks.get, hid)
    return await asyncio.to_thread(webhooks.public, h)


@router.patch("/{hid}")
async def patch(hid: str, body: HookIn):
    spec = body.model_dump(exclude_none=True)
    spec.pop("secret", None)
    if set(spec) <= {"enabled", "description"}:
        out: Any = None
        if "enabled" in spec:
            out = await asyncio.to_thread(_call, webhooks.set_enabled, hid, spec["enabled"])
        if "description" in spec:
            out = await asyncio.to_thread(_call, webhooks.set_description, hid, spec["description"])
        return out or await one(hid)
    return await asyncio.to_thread(_call, webhooks.update, hid, spec)


@router.delete("/{hid}")
async def delete(hid: str):
    await asyncio.to_thread(_call, webhooks.remove, hid)
    return {"ok": True}


@router.post("/{hid}/rotate")
async def rotate(hid: str):
    return await asyncio.to_thread(_call, webhooks.rotate, hid)


class SecretIn(BaseModel):
    secret: str = ""


@router.post("/{hid}/secret")
async def secret(hid: str, body: SecretIn):
    return await asyncio.to_thread(_call, webhooks.set_secret, hid, body.secret)


@router.post("/{hid}/test")
async def test(hid: str):
    return await asyncio.to_thread(_call, webhooks.test, hid)


@router.get("/{hid}/calls")
async def calls(hid: str, limit: int = Query(webhooks.KEEP_CALLS, ge=1, le=webhooks.KEEP_CALLS)):
    return {"calls": await asyncio.to_thread(_call, webhooks.calls, hid, limit)}


@router.get("/{hid}/calls/{cid}")
async def call(hid: str, cid: str):
    return await asyncio.to_thread(_call, webhooks.call, hid, cid)


@router.post("/{hid}/calls/{cid}/replay")
async def replay(hid: str, cid: str):
    return await asyncio.to_thread(_call, webhooks.replay, hid, cid)


@router.get("/{hid}/data")
async def data(hid: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
               format: str = Query("json", pattern="^(json|csv)$")):
    if format == "csv":
        text = await asyncio.to_thread(_call, webhooks.data_csv, hid)
        name = (await asyncio.to_thread(_call, webhooks.get, hid))["name"]
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:40] or "data"
        return Response(text, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{safe}.csv"'})
    rows = await asyncio.to_thread(_call, webhooks.data, hid, after, limit)
    return {"rows": rows, "stats": await asyncio.to_thread(webhooks.data_stats, hid)}


# ---- background ----------------------------------------------------------------------------
_task: asyncio.Task | None = None
SPOOL_S = 2.0
FEED_S = 5.0


def _signature() -> tuple:
    """The files the CLI may change (hooks, calls): the page refreshes when they move."""
    d = webhooks._dir()
    sig = []
    for p in [d / "hooks.json", *sorted((d / "calls").glob("*.jsonl"))]:
        with contextlib.suppress(OSError):
            st = p.stat()
            sig.append((p.name, st.st_mtime_ns, st.st_size))
    return tuple(sig)


async def _loop() -> None:
    try:
        await asyncio.to_thread(webhooks.recover)
    except Exception:  # noqa: BLE001
        log.exception("webhooks: recovery failed")
    last_feed = 0.0
    last_sig = await asyncio.to_thread(_signature)
    while True:
        await asyncio.sleep(SPOOL_S)
        try:
            if bus.browser_count():
                sig = await asyncio.to_thread(_signature)
                if sig != last_sig:
                    last_sig = sig
                    bus.invalidate("webhooks")
            n = await asyncio.to_thread(webhooks.process_spool)
            now = asyncio.get_running_loop().time()
            if now - last_feed >= FEED_S:
                last_feed = now
                n += await asyncio.to_thread(webhooks.scan_feed)
            if n:
                bus.invalidate("webhooks")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("webhooks loop")


async def startup() -> None:
    global _task
    if os.environ.get("MAXXING_WEBHOOKS_LOOP", "1") != "0":
        _task = asyncio.create_task(_loop())


async def shutdown() -> None:
    global _task
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
    _task = None
