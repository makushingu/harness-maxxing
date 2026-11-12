"""Enterprise flow routes and the enterprises' single background loop. See docs/dev/API.md#enterprises and
maxxing/enterprise_flow.py. The owner answers escalations here; positions answer through the CLI."""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
import os
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import agents, enterprise_flow, enterprises
from ..security import require_auth

log = logging.getLogger("maxxing.api.enterprise_flow")
router = APIRouter(prefix="/api/enterprises", tags=["enterprises"], dependencies=[Depends(require_auth)])

TICK_S = 60.0
TICKERS = ("enterprise_policy", "enterprise_reports", "enterprise_workers", "enterprise_desk")   # after the flow's tick
SLOW = ("enterprise_reports", "enterprise_desk")    # may wait on `claude -p` for minutes: own thread, own guard
_slow_guard = threading.Lock()
_slow_thread: threading.Thread | None = None
_task: asyncio.Task | None = None


def _on() -> None:
    if not enterprises.feature_on():
        raise HTTPException(404, detail={"error": "feature_off",
                                         "message": "Enterprises are off (Settings -> Features, needs Agents)"})


def _bad(e: enterprises.EnterpriseError | agents.AgentError) -> HTTPException:
    extra = getattr(e, "extra", None) or {}
    return HTTPException(e.status, detail={"error": e.code, "message": e.message, **extra})


class AnswerIn(BaseModel):
    text: str = Field(max_length=enterprise_flow.TEXT_MAX)


@router.get("/{e}/escalations")
def list_escalations(e: str):
    _on()
    try:
        enterprises.load(e)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
    return {"items": [_item(i) for i in enterprise_flow.escalations(e)]}


def _item(i: dict) -> dict:
    keys = ("id", "position", "text", "task", "level", "deadline", "status", "at", "outside", "to", "answer",
            "answered_by", "answered_at")
    return {k: i.get(k) for k in keys if k in i or k in ("id", "position", "text", "level", "deadline", "status", "at")}


@router.post("/{e}/escalations/{esc_id}/answer")
def answer_escalation(e: str, esc_id: str, body: AnswerIn):
    _on()
    try:
        return _item(enterprise_flow.answer(e, esc_id, body.text, by=None))
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


def _run_ticker(name: str, now: float) -> None:
    try:
        fn = getattr(importlib.import_module(f"{__package__.rsplit('.', 1)[0]}.{name}"), "tick", None)
    except ImportError:
        return
    try:
        if fn:
            fn(now)
    except Exception:  # noqa: BLE001
        log.exception("%s.tick", name)


def _run_slow(now: float) -> None:
    try:
        for name in SLOW:
            _run_ticker(name, now)
    finally:
        _slow_guard.release()


def tick_all(now: float | None = None) -> None:
    """One pass of every enterprise ticker, each on its own: a failure of one never stops the others. The slow ones
    (reports, desk insights) run in their own thread and a pass is skipped while the previous one still runs."""
    global _slow_thread
    now = now if now is not None else time.time()
    try:
        enterprise_flow.tick(now)
    except Exception:  # noqa: BLE001
        log.exception("enterprise_flow.tick")
    if not enterprises.feature_on():
        _run_ticker("enterprise_workers", now)            # switched off: it only retires the live workers
        return
    for name in TICKERS:
        if name not in SLOW:
            _run_ticker(name, now)
    if _slow_guard.acquire(blocking=False):
        try:
            _slow_thread = threading.Thread(target=_run_slow, args=(now,), name="enterprise-slow", daemon=True)
            _slow_thread.start()
        except BaseException:
            _slow_guard.release()                         # the thread never ran: the next pass may try again
            raise


async def _loop() -> None:
    interval = float(os.environ.get("MAXXING_ENTERPRISE_TICK_S") or TICK_S)
    while True:
        try:
            await asyncio.to_thread(tick_all)             # the first pass also resumes the inboxes after a restart
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("enterprise loop")
        await asyncio.sleep(interval)


async def startup() -> None:
    """MAXXING_ENTERPRISE_TICK=0 keeps the background loop off (tests call the tick functions directly)."""
    global _task
    if os.environ.get("MAXXING_ENTERPRISE_TICK", "1") == "0":
        return
    enterprise_flow.SERVER = True
    _task = asyncio.get_running_loop().create_task(_loop())


async def shutdown() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
