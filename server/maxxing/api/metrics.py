"""Prometheus metrics (`GET /metrics`, bearer token) and their switch. See metrics.py and docs/dev/API.md#metrics."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import metrics
from ..security import require_auth

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def scrape(request: Request):
    """**Public** route (no cookie): 404 while switched off, 401 without the bearer token."""
    if not metrics.enabled():
        raise HTTPException(404, detail={"error": "not_found", "message": "Not found"})
    if not metrics.authorized(request.headers.get("authorization")):
        raise HTTPException(401, detail={"error": "auth_required", "message": "Bearer token required"},
                            headers={"WWW-Authenticate": "Bearer"})
    return Response(await asyncio.to_thread(metrics.render), media_type=metrics.CONTENT_TYPE,
                    headers={"Cache-Control": "no-store"})


class MetricsBody(BaseModel):
    enabled: bool


@router.get("/api/system/metrics", dependencies=[Depends(require_auth)])
async def get_metrics():
    return await asyncio.to_thread(metrics.status)


@router.put("/api/system/metrics", dependencies=[Depends(require_auth)])
async def put_metrics(body: MetricsBody):
    token = await asyncio.to_thread(metrics.set_enabled, body.enabled)
    return {**await asyncio.to_thread(metrics.status), "token": token}


@router.post("/api/system/metrics/token", dependencies=[Depends(require_auth)])
async def rotate_token():
    token = await asyncio.to_thread(metrics.new_token)
    return {**await asyncio.to_thread(metrics.status), "token": token}
