"""Enterprise requests: the owner's view and decision (maxxing/enterprise_policy.py). See docs/dev/API.md#enterprises."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import agents, enterprise_policy, enterprises
from ..security import require_auth

router = APIRouter(prefix="/api/enterprises", tags=["enterprises"], dependencies=[Depends(require_auth)])


def _on() -> None:
    if not enterprises.feature_on():
        raise HTTPException(404, detail={"error": "feature_off",
                                         "message": "Enterprises are off (Settings -> Features, needs Agents)"})


def _bad(e: enterprises.EnterpriseError | agents.AgentError) -> HTTPException:
    extra = getattr(e, "extra", None) or {}
    return HTTPException(e.status, detail={"error": e.code, "message": e.message, **extra})


class DecisionIn(BaseModel):
    decision: Literal["allow", "deny"]
    reason: Optional[str] = Field(None, max_length=300)


@router.get("/{e}/requests")
def list_requests(e: str):
    _on()
    try:
        return {"items": enterprise_policy.requests(e)}
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.post("/{e}/requests/{rid}")
def decide_request(e: str, rid: str, body: DecisionIn):
    _on()
    try:
        return enterprise_policy.decide(e, rid, body.decision, reason=body.reason or "", via="web")
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
