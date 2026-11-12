"""Enterprises: Overview, reports (daily digest, weekly review, monthly report). See docs/dev/API.md#enterprises."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import agents, enterprise_reports, enterprises
from ..security import require_auth

router = APIRouter(prefix="/api/enterprises", tags=["enterprises"], dependencies=[Depends(require_auth)])


def _on() -> None:
    if not enterprises.feature_on():
        raise HTTPException(404, detail={"error": "feature_off",
                                         "message": "Enterprises are off (Settings -> Features, needs Agents)"})


def _bad(e: enterprises.EnterpriseError | agents.AgentError) -> HTTPException:
    extra = getattr(e, "extra", None) or {}
    return HTTPException(e.status, detail={"error": e.code, "message": e.message, **extra})


class BuildIn(BaseModel):
    kind: str = "daily"


# Plain `def` routes: FastAPI runs them in its thread pool, which the Claude call of a build needs.
@router.get("/{e}/overview")
def overview(e: str):
    _on()
    try:
        return enterprise_reports.overview(e)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.get("/{e}/reports")
def list_reports(e: str):
    _on()
    try:
        return {"items": enterprise_reports.reports(e)}
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.get("/{e}/reports/{name}")
def get_report(e: str, name: str):
    _on()
    try:
        return enterprise_reports.report(e, name)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None


@router.post("/{e}/reports")
def build_report(e: str, body: BuildIn):
    _on()
    try:
        r = enterprise_reports.build(e, body.kind)
    except enterprises.EnterpriseError as x:
        raise _bad(x) from None
    return {"built": r is not None, "report": r}
