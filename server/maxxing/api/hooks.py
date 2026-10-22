"""Public endpoint of the feed's webhooks: POST /api/hooks/<token> (no session; see feedhooks.py).

The token is checked before anything is read; the body is then read in chunks and never past
feedhooks.MAX_BODY (a declared Content-Length over it is refused without reading)."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import feedhooks

router = APIRouter(prefix="/api/hooks", tags=["feed"])


async def _read_capped(request: Request, cap: int) -> bytes | None:
    """The body, or None as soon as it goes over `cap` bytes."""
    try:
        if int(request.headers.get("content-length") or 0) > cap:
            return None
    except ValueError:
        pass
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            return None
    return bytes(buf)


@router.post("/{token}")
async def deliver(token: str, request: Request):
    if await asyncio.to_thread(feedhooks.by_token, token) is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    body = await _read_capped(request, feedhooks.MAX_BODY)
    if body is None:
        return JSONResponse({"error": "too_big"}, status_code=413)
    status, out = await asyncio.to_thread(feedhooks.deliver, token, dict(request.headers), body)
    return JSONResponse(out, status_code=status)
