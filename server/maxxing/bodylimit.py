"""Request body caps for every non-multipart request under /api/, enforced before and while the body is read.

FastAPI reads (and parses) a JSON body BEFORE the route's dependencies run - the auth check included - so an
anonymous client could make the server hold any amount of JSON in memory. `BodyLimit` is an ASGI middleware that
decides from the headers alone, before a byte of the body is received:
- a mutating request to a route that needs a session, without a valid cookie -> 401 `auth_required`;
- the public sign-in routes (/api/auth/*): the CSRF header is checked first (403 `csrf`), the body is capped at
  PUBLIC_MAX (a password, a setup token or a code: a few hundred bytes);
- /api/hooks/<token> (public, the token is the permission): feedhooks.MAX_BODY;
- signed in: DEFAULT_MAX, or a larger cap for the few routes whose JSON is legitimately big (`ROUTES`).
A declared `Content-Length` over the cap -> 413 `too_large` at once; a chunked body is counted while it streams and
the request is aborted with 413 as soon as it goes over. Multipart bodies are left to `uploads.UploadGuard` (auth,
CSRF, upload_max_mb and disk checks before reading).
"""
from __future__ import annotations

import re

from fastapi import HTTPException

from .uploads import MB, _reply

PUBLIC_MAX = 64 * 1024
DEFAULT_MAX = 1 * MB
# (method, path pattern, cap) - signed-in requests only; the first match wins.
ROUTES: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("PUT", re.compile(r"^/api/files/write$"), 16 * MB),      # the editor's text (<= 2 MB read), JSON-escaped
    ("POST", re.compile(r"^/api/sessions$"), 8 * MB),         # a first message: prompts go through stdin, unbounded
    ("POST", re.compile(r"^/api/sessions/[^/]+/(messages|steer|ask)$"), 8 * MB),
    ("*", re.compile(r"^/api/ext/"), 5 * MB),                 # extension routes (api/extensions.py MAX_BODY)
)
_MUTATING = ("POST", "PUT", "PATCH", "DELETE")


def _public(path: str) -> bool:
    # /api/pc/pair (pairing code) and /api/pc/mcp (loopback + secret) check their own permission
    # /api/team-peer/* (other Harness servers) checks its own signatures
    return path.startswith(("/api/auth/", "/api/hooks/", "/api/team-peer/")) or path in ("/api/pc/pair", "/api/pc/mcp")


def cap_for(method: str, path: str, authed: bool) -> int:
    if path.startswith("/api/hooks/"):
        from .feedhooks import MAX_BODY
        return MAX_BODY
    if path == "/api/pc/mcp":                       # tool arguments (a form's text, a script)
        return DEFAULT_MAX
    if not authed:
        return PUBLIC_MAX
    for m, pat, cap in ROUTES:
        if m in ("*", method) and pat.match(path):
            return cap
    return DEFAULT_MAX


def _too_large(cap: int) -> HTTPException:
    size = f"{cap // MB} MB" if cap >= MB else f"{cap // 1024} kB"
    return HTTPException(413, detail={"error": "too_large", "message": f"Request body too large (limit {size})"})


class BodyLimit:
    """ASGI middleware (see the module docstring). Sits outside UploadGuard."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in _MUTATING \
                or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if headers.get("content-type", "").lower().startswith("multipart/"):
            return await self.app(scope, receive, send)             # UploadGuard
        path, method = scope["path"], scope["method"]
        if path.startswith("/api/auth/") and headers.get("x-maxxing") != "1":
            return await _reply(scope, receive, send, 403, "csrf", "Missing X-Maxxing header")
        from starlette.requests import Request
        from . import security
        authed = security.is_authenticated(Request(scope))
        if not authed and not _public(path):
            return await _reply(scope, receive, send, 401, "auth_required", "Sign in required")
        cap = cap_for(method, path, authed)
        try:
            length = int(headers.get("content-length", ""))
        except ValueError:
            length = None
        if length is not None and length > cap:
            e = _too_large(cap)
            return await _reply(scope, receive, send, 413, e.detail["error"], e.detail["message"])
        seen = 0

        async def counted():
            nonlocal seen
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > cap:
                    raise _too_large(cap)
            return msg

        await self.app(scope, counted, send)
