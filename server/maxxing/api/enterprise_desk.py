"""Enterprise front desk: the public chat link (no session) and the owner's views, insights and suggested FAQ entries
(maxxing/enterprise_desk.py). See docs/dev/API.md#enterprises.

The public link is an unauthenticated entry point: its token is the permission, a message is capped (`max_chars`, the
body at 64 kB by bodylimit), a visitor (client key) has `rate_per_hour` messages an hour, the run costs the desk
agent's own daily budget, and every refusal that could say too much is the same 404 / 503."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .. import agents, config, desk_page, enterprise_desk, enterprises, security
from ..security import require_auth

router = APIRouter(tags=["enterprises"])
AUTH = [Depends(require_auth)]
P = "/api/enterprises/{e}"


def _on() -> None:
    if not enterprises.feature_on():
        raise HTTPException(404, detail={"error": "feature_off",
                                         "message": "Enterprises are off (Settings -> Features, needs Agents)"})


def _bad(e: enterprises.EnterpriseError | agents.AgentError) -> HTTPException:
    extra = getattr(e, "extra", None) or {}
    return HTTPException(e.status, detail={"error": e.code, "message": e.message, **extra})


class VisitIn(BaseModel):
    message: str = Field(max_length=5000)
    conv: Optional[str] = Field(None, max_length=40)


class LinkIn(BaseModel):
    regenerate: bool = False


class SuggestionIn(BaseModel):
    action: Literal["accept", "dismiss"]
    q: Optional[str] = Field(None, max_length=300)
    a: Optional[str] = Field(None, max_length=2000)


# ---- public ----------------------------------------------------------------------------------------------
@router.get("/desk/{token}", include_in_schema=False)
def visit_page(token: str, request: Request):
    """The visitor's chat page (static, strict CSP, no cookie); 404 unless the link is live."""
    try:
        enterprise_desk.public_info(token, client=security.client_key(request))
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
    body, headers = desk_page.page(str(config.load_config().get("language") or "en"))
    return HTMLResponse(body, headers=headers)


@router.get("/api/public/desk/{token}")
def visit_get(token: str, request: Request, conv: str = ""):
    try:
        return enterprise_desk.public_info(token, conv, client=security.client_key(request))
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.post("/api/public/desk/{token}")
def visit_post(token: str, body: VisitIn, request: Request):
    try:
        return enterprise_desk.public_post(token, security.client_key(request), body.message, body.conv or "")
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


# ---- the owner ----------------------------------------------------------------------------------------------
@router.get(P + "/desk", dependencies=AUTH)
def desk(e: str):
    _on()
    try:
        return enterprise_desk.status(e)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.post(P + "/desk/link", dependencies=AUTH)
def desk_link(e: str, body: LinkIn):
    _on()
    try:
        enterprises.load(e)
        return enterprise_desk.link(e, body.regenerate)
    except (enterprises.EnterpriseError, agents.AgentError) as x:
        raise _bad(x) from None


@router.get(P + "/desk/{conv}", dependencies=AUTH)
def desk_conversation(e: str, conv: str):
    _on()
    try:
        return enterprise_desk.conversation(e, conv)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.delete(P + "/desk/{conv}", dependencies=AUTH)
def desk_delete(e: str, conv: str):
    _on()
    try:
        enterprise_desk.delete_conversation(e, conv)
        return {"ok": True}
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.get(P + "/insights", dependencies=AUTH)
def insights(e: str):
    _on()
    try:
        return enterprise_desk.insights(e)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.post(P + "/insights", dependencies=AUTH)
def insights_now(e: str):
    _on()
    try:
        enterprises.load(e)
        return {"built": (r := enterprise_desk.run_insights(e)) is not None, "insights": r or enterprise_desk.insights(e)}
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.get(P + "/profile/suggestions", dependencies=AUTH)
def suggestions(e: str):
    _on()
    try:
        return {"items": enterprise_desk.suggestions(e)}
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.post(P + "/profile/suggestions/{sid}", dependencies=AUTH)
def decide_suggestion(e: str, sid: str, body: SuggestionIn):
    _on()
    try:
        return enterprise_desk.decide_suggestion(e, sid, body.action, q=body.q or "", a=body.a or "")
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
