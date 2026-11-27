"""Public endpoint of the webhooks: GET/POST /api/hooks/<token> (no session; the token is the permission).

A token of a hook of Settings -> Automate -> Webhooks (webhooks.py) is served first: GET or POST, JSON, forms,
multipart files, a reply at once (202) or the result of the action ("wait"). Any other token is a webhook of the
notifications feed (feedhooks.py, POST only). Bodies are capped by bodylimit.py (the hook's own `max_mb`).
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from .. import feedhooks, webhooks

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
    request._body = bytes(buf)          # noqa: SLF001 - read once: request.form() parses it again from here
    return request._body


def _json(out: dict) -> JSONResponse:
    headers = {"Retry-After": str(out["retry_after"])} if out.get("retry_after") else None
    return JSONResponse(out["json"], status_code=out["status"], headers=headers)


async def _ours(token: str, request: Request, hook: dict) -> Response:
    cap = hook["trigger"]["max_mb"] * webhooks.MB
    body = b"" if request.method == "GET" else await _read_capped(request, cap)
    if body is None:
        return JSONResponse({"error": "too_big"}, status_code=413)
    fields = files = None
    if body and request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        try:
            form = await request.form(max_files=webhooks.FILES_MAX, max_fields=500)
        except Exception:  # noqa: BLE001 - a broken multipart body
            return JSONResponse({"error": "bad_form"}, status_code=400)
        fields, files = {}, []
        for key, v in form.multi_items():
            if hasattr(v, "read"):
                files.append((key, getattr(v, "filename", "") or "", await v.read()))
            else:
                fields[key] = v
        await form.close()
    out = await asyncio.to_thread(webhooks.receive, token, request.method, dict(request.headers),
                                  dict(request.query_params), body, fields, files)
    if not out.get("wait"):
        return _json(out)
    try:
        await asyncio.to_thread(webhooks.dispatcher.wait, out["call"], webhooks.WAIT_S)
    finally:
        webhooks.dispatcher.sync_release(out["hook"])
    status, data, ctype = await asyncio.to_thread(webhooks.reply_of, out["hook"], out["call"])
    # the target / the script picks the type: on the UI's origin it must never render as a page that runs script
    return Response(data, status_code=status, media_type=ctype, headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.api_route("/{token}", methods=["GET", "POST"])
async def deliver(token: str, request: Request):
    found = await asyncio.to_thread(webhooks.by_token, token)
    if found is not None:
        return await _ours(token, request, found[0])
    if request.method != "POST" or await asyncio.to_thread(feedhooks.by_token, token) is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    body = await _read_capped(request, feedhooks.MAX_BODY)
    if body is None:
        return JSONResponse({"error": "too_big"}, status_code=413)
    status, out = await asyncio.to_thread(feedhooks.deliver, token, dict(request.headers), body)
    return JSONResponse(out, status_code=status)
