"""Upload limits: a size cap and a free-disk reserve, enforced before and while the body is read.

Starlette spools every multipart file to the temp dir BEFORE the endpoint (and its auth dependency)
runs, so the checks live in an ASGI middleware (`UploadGuard`, multipart requests under /api/):
- the session cookie and the CSRF header are checked first: no byte of an unauthenticated body is read;
- `Content-Length` above `upload_max_mb` -> 413 `too_large`; a body that would not fit in the temp dir
  with TMP_MARGIN (min(upload_min_free_mb, 128 MB)) to spare -> 507 `disk_full` - both before reading.
  The temp dir is often a small tmpfs (RAM): the full reserve is for the destination disk only;
- while streaming (also without Content-Length) the same two limits abort the request.
`save_upload` (api/sessions.py) then checks each file against the cap and the destination's free space
(`check_room`) and counts bytes while copying.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from . import config

MB = 1024 * 1024
DEFAULT_MAX_MB = 2048
DEFAULT_MIN_FREE_MB = 1024
_CHECK_EVERY = 16 * MB             # free space re-checked every 16 MB received
TMP_MARGIN = 128 * MB              # what must stay free in the temp dir while spooling (capped by the reserve)


def _num(key: str, default: int) -> int:
    try:
        v = int(config.load_config().get(key, default))
    except (TypeError, ValueError):
        return default
    return max(v, 0)


def limits() -> tuple[int, int]:
    """-> (max bytes per upload, bytes that must stay free). upload_max_mb 0 = no cap."""
    return _num("upload_max_mb", DEFAULT_MAX_MB) * MB, _num("upload_min_free_mb", DEFAULT_MIN_FREE_MB) * MB


def free_bytes(path: str | Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 1 << 62                 # unknown: never refuse because of a failed statvfs


def too_large(max_b: int) -> HTTPException:
    return HTTPException(413, detail={"error": "too_large",
                                      "message": f"File too large (limit {max_b // MB} MB, setting upload_max_mb)"})


def disk_full(reserve: int) -> HTTPException:
    return HTTPException(507, detail={"error": "disk_full",
                                      "message": f"Not enough free disk space on the server (at least "
                                                 f"{reserve // MB} MB must stay free) - free some space and retry"})


def check_room(folder: str | Path, size: int) -> None:
    """Raise 413/507 if `size` bytes may not be written into `folder`."""
    max_b, reserve = limits()
    if max_b and size > max_b:
        raise too_large(max_b)
    if free_bytes(folder) - size < reserve:
        raise disk_full(reserve)


class UploadGuard:
    """ASGI middleware for multipart requests under /api/ (see the module docstring)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in ("POST", "PUT", "PATCH") \
                or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if not headers.get("content-type", "").lower().startswith("multipart/"):
            return await self.app(scope, receive, send)
        from . import security
        from starlette.requests import Request
        if not security.is_authenticated(Request(scope)):
            return await _reply(scope, receive, send, 401, "auth_required", "Sign in required")
        if headers.get("x-maxxing") != "1":
            return await _reply(scope, receive, send, 403, "csrf", "Missing X-Maxxing header")
        max_b, reserve = limits()
        reserve = min(reserve, TMP_MARGIN)          # temp dir: the body must fit, the full reserve is for the disk
        tmp = tempfile.gettempdir()
        try:
            length = int(headers.get("content-length", ""))
        except ValueError:
            length = None
        try:
            if length is not None:
                if max_b and length > max_b + MB:        # + multipart framing
                    raise too_large(max_b)
                if free_bytes(tmp) - length < reserve:
                    raise disk_full(reserve)
        except HTTPException as e:
            return await _reply(scope, receive, send, e.status_code, e.detail["error"], e.detail["message"])
        seen = 0
        next_check = _CHECK_EVERY

        async def counted():
            nonlocal seen, next_check
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if max_b and seen > max_b + MB:
                    raise too_large(max_b)
                if seen >= next_check:
                    next_check = seen + _CHECK_EVERY
                    if free_bytes(tmp) < reserve:
                        raise disk_full(reserve)
            return msg

        await self.app(scope, counted, send)


async def _reply(scope, receive, send, status: int, error: str, message: str) -> None:
    await JSONResponse({"error": error, "message": message}, status_code=status,
                       headers={"Connection": "close"})(scope, receive, send)
