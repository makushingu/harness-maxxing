"""Enterprise workers: the owner's list and stop (maxxing/enterprise_workers.py). See docs/dev/API.md#enterprises."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import agents, enterprise_workers, enterprises
from ..security import require_auth

router = APIRouter(prefix="/api/enterprises", tags=["enterprises"], dependencies=[Depends(require_auth)])


def _on() -> None:
    if not enterprises.feature_on():
        raise HTTPException(404, detail={"error": "feature_off",
                                         "message": "Enterprises are off (Settings -> Features, needs Agents)"})


def _bad(e: enterprises.EnterpriseError | agents.AgentError) -> HTTPException:
    extra = getattr(e, "extra", None) or {}
    return HTTPException(e.status, detail={"error": e.code, "message": e.message, **extra})


@router.get("/{e}/workers")
def list_workers(e: str):
    _on()
    try:
        return {"items": enterprise_workers.workers(e)}
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.delete("/{e}/workers/{wid}")
def stop_worker(e: str, wid: str):
    _on()
    try:
        return enterprise_workers.stop(e, wid)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
