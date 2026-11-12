"""Enterprise knowledge: the enterprise CLAUDE.md (`about`) and the company profile. See docs/dev/API.md#enterprises.
The owner's writes apply directly."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import agents, enterprise_knowledge, enterprises
from ..security import require_auth

router = APIRouter(prefix="/api/enterprises", tags=["enterprises"], dependencies=[Depends(require_auth)])


def _on() -> None:
    if not enterprises.feature_on():
        raise HTTPException(404, detail={"error": "feature_off",
                                         "message": "Enterprises are off (Settings -> Features, needs Agents)"})


def _bad(e: enterprises.EnterpriseError | agents.AgentError) -> HTTPException:
    extra = getattr(e, "extra", None) or {}
    return HTTPException(e.status, detail={"error": e.code, "message": e.message, **extra})


class AboutIn(BaseModel):
    text: str = Field(max_length=enterprise_knowledge.ABOUT_MAX * 2)


@router.get("/{e}/about")
def get_about(e: str):
    _on()
    try:
        text = enterprise_knowledge.about(e)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
    return {"text": text, "max": enterprise_knowledge.ABOUT_MAX, "note_max": enterprise_knowledge.NOTE_MAX}


@router.put("/{e}/about")
def put_about(e: str, body: AboutIn):
    _on()
    try:
        text = enterprise_knowledge.set_about(e, body.text)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
    return {"text": text, "max": enterprise_knowledge.ABOUT_MAX, "note_max": enterprise_knowledge.NOTE_MAX}


@router.get("/{e}/profile")
def get_profile(e: str):
    _on()
    try:
        return enterprise_knowledge.profile(e)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.put("/{e}/profile")
def put_profile(e: str, body: dict[str, Any]):
    _on()
    try:
        return {"profile": enterprise_knowledge.set_profile(e, body)}
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
