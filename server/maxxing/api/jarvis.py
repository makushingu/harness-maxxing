"""Jarvis (Settings -> Features -> Jarvis): its conversation, its work board, its settings. See docs/dev/API.md#jarvis.
A loop starts the morning brief and the night pass at their time; a turn-end callback reports the answers of the
sessions it handed work to (jarvis.on_turn_end)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import bus, jarvis
from ..security import require_auth

log = logging.getLogger("maxxing.jarvis")
router = APIRouter(prefix="/api/jarvis", tags=["jarvis"], dependencies=[Depends(require_auth)])
TICK_S = 30.0
WATCH_S = 2.0                          # how often work.json is checked for changes made by another process
_task: asyncio.Task | None = None
_watch: asyncio.Task | None = None


async def _call(fn, *a, **kw):
    from ..sessions import service
    try:
        return await asyncio.to_thread(fn, *a, **kw)
    except (jarvis.JarvisError, service.SessionError) as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


@router.get("")
async def get_jarvis():
    return await _call(jarvis.status)


@router.post("/open")
async def open_conversation():
    """The page opens: its conversation (made the first time) -> the status."""
    await _call(jarvis.conversation)
    return await _call(jarvis.status)


@router.post("/new")
async def new_conversation():
    await _call(jarvis.new_conversation)
    return await _call(jarvis.status)


class SettingsIn(BaseModel):
    model: Optional[str] = None
    dream_model: Optional[str] = None
    root: Optional[bool] = None
    ask_first: Optional[bool] = None
    internals: Optional[bool] = None
    daily: Optional[bool] = None
    brief: Optional[str] = None
    dream: Optional[str] = None
    compact_tokens: Optional[int] = None
    telegram: Optional[str] = None
    reuse: Optional[bool] = None
    archive_done: Optional[bool] = None


@router.put("/settings")
async def put_settings(body: SettingsIn):
    await _call(jarvis.save_settings, body.model_dump(exclude_none=True))
    return await _call(jarvis.status)


@router.post("/work/{ref}/close")
async def close_work(ref: str):
    await _call(jarvis.close, ref)
    return await _call(jarvis.status)


@router.post("/brief")
async def brief_now():
    await _call(jarvis.brief)
    return await _call(jarvis.status)


@router.post("/dream")
async def dream_now():
    s = await _call(jarvis.dream)
    return {"session": s}


async def _turn_end(session: dict, result: dict | None) -> None:
    await asyncio.to_thread(jarvis.on_turn_end, session, result)


async def _loop() -> None:
    while True:
        try:
            await asyncio.sleep(TICK_S)
            await asyncio.to_thread(jarvis.tick)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("jarvis loop")


def _work_sig() -> tuple | None:
    try:
        st = jarvis._work_file().stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


async def _watch_work(interval: float = WATCH_S) -> None:
    """The board is also written by other processes (`maxxing sessions new|send`, `maxxing agents run` started from
    its conversation), whose `bus.invalidate` reaches no browser: a change of work.json is announced from here."""
    last = _work_sig()
    while True:
        await asyncio.sleep(interval)
        cur = _work_sig()
        if cur != last:
            last = cur
            bus.invalidate("jarvis")


async def startup() -> None:
    global _task, _watch
    from ..sessions import service
    service.on_turn_end(_turn_end)
    if jarvis.feature_on():             # a new version: its role and skills are brought up to date at once
        try:
            await asyncio.to_thread(jarvis.ensure)
        except Exception:  # noqa: BLE001
            log.exception("jarvis: folder update")
    _task = asyncio.get_running_loop().create_task(_loop())
    _watch = asyncio.get_running_loop().create_task(_watch_work())


async def shutdown() -> None:
    global _task, _watch
    for t in (_task, _watch):
        if t is not None:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
    _task = _watch = None
