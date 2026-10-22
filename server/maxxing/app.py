"""FastAPI application factory.

- Loads every router listed in maxxing.api.ROUTERS (a missing/broken module is logged, the
  rest of the app still starts).
- Errors are always JSON: {"error": code, "message": text}.
- Serves the built SPA (web/dist): hashed assets cached forever, index.html never cached,
  unknown non-API paths fall back to index.html (client-side routing).
- Security headers on every response (`_SecurityHeaders`), never overriding a header a route set.
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import importlib
import logging
import mimetypes
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__, bodylimit, bus, config, streamcap, uploads
from .api import ROUTERS
from .security import require_auth

log = logging.getLogger("maxxing")


def _load_modules() -> list:
    mods = []
    for name in ROUTERS:
        try:
            mods.append(importlib.import_module(f"maxxing.api.{name}"))
        except ModuleNotFoundError as e:
            if e.name == f"maxxing.api.{name}":
                log.warning("router %s not implemented yet", name)
            else:
                log.exception("router %s failed to import", name)
        except Exception:
            log.exception("router %s failed to import", name)
    return mods


# Same-origin framing stays allowed: the UI shows PDFs (/api/files/raw) and HTML pages (/api/files/site)
# in its own iframes. The SPA document gets a minimal CSP (its pre-paint script is inline).
# Permissions-Policy: no page of the app (nor a widget or an HTML file shown in it) may use the camera, location,
# payments, USB/serial/HID devices...; the microphone stays allowed for the app itself (voice messages).
_PERMISSIONS = (b"camera=(), geolocation=(), payment=(), usb=(), serial=(), hid=(), bluetooth=(), midi=(), "
                b"magnetometer=(), gyroscope=(), accelerometer=(), display-capture=(), microphone=(self)")
_HEADERS = [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"SAMEORIGIN"),
            (b"referrer-policy", b"same-origin"), (b"permissions-policy", _PERMISSIONS)]
_SPA_CSP = b"frame-ancestors 'self'; object-src 'none'; base-uri 'self'"
_INLINE_SCRIPT = re.compile(rb"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
_csp_cache: dict = {}


def _app_csp(index: Path) -> str:
    """The app page's policy: scripts only from this server, plus its own inline boot scripts (by hash) - an
    injected <script> or a script from elsewhere does not run. Recomputed when index.html changes."""
    try:
        st = index.stat()
    except OSError:
        return _SPA_CSP.decode()
    key = (st.st_mtime_ns, st.st_size)
    if _csp_cache.get("key") != key:
        hashes = " ".join(f"'sha256-{base64.b64encode(hashlib.sha256(m).digest()).decode()}'"
                          for m in _INLINE_SCRIPT.findall(index.read_bytes()))
        _csp_cache.update(key=key, value=f"{_SPA_CSP.decode()}; script-src 'self' {hashes}".strip())
    return _csp_cache["value"]


class _SecurityHeaders:
    """ASGI middleware (no buffering: SSE streams pass through untouched)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                have = {k.lower() for k, _ in headers}
                extra = [(k, v) for k, v in _HEADERS if k not in have]
                ctype = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if (ctype.startswith(b"text/html") and b"content-security-policy" not in have
                        and not scope["path"].startswith("/api/")):
                    extra.append((b"content-security-policy", _SPA_CSP))
                message = {**message, "headers": headers + extra}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app() -> FastAPI:
    mods = _load_modules()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.bind_loop(asyncio.get_running_loop())
        try:
            await asyncio.to_thread(config.tighten_state)
        except Exception:
            log.exception("tightening the state files failed")
        for m in mods:
            if hasattr(m, "startup"):
                try:
                    await m.startup()
                except Exception:
                    log.exception("startup of %s failed", m.__name__)
        yield
        for m in reversed(mods):
            if hasattr(m, "shutdown"):
                try:
                    await m.shutdown()
                except Exception:
                    log.exception("shutdown of %s failed", m.__name__)

    app = FastAPI(title="Harness Maxxing", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException):
        d = exc.detail
        body = d if isinstance(d, dict) else {"error": _code(exc.status_code), "message": str(d)}
        return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return JSONResponse({"error": "invalid", "message": f"{where}: {first.get('msg', 'invalid')}"},
                            status_code=422)

    @app.exception_handler(Exception)
    async def _crash(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"error": "internal", "message": "Internal server error (details in the server log)"},
                            status_code=500)

    for m in mods:
        if hasattr(m, "router"):
            app.include_router(m.router)

    @app.get("/api/stream", dependencies=[Depends(require_auth)])
    async def stream(request: Request):
        from .security import COOKIE
        cookie = request.cookies.get(COOKIE)
        return streamcap.stream_response(cookie, lambda: bus.stream(cookie), media_type="text/event-stream",
                                         headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def api_404(rest: str):
        raise HTTPException(404, detail={"error": "not_found", "message": f"/api/{rest}"})

    _mount_spa(app)
    app.add_middleware(JsonGzip)
    app.add_middleware(uploads.UploadGuard)        # multipart: auth + size/disk checks before the body is read
    app.add_middleware(bodylimit.BodyLimit)        # every other body: auth / CSRF + size cap before it is read
    # Added last = outermost: security headers see the final (possibly gzipped) response.
    app.add_middleware(_SecurityHeaders)
    return app


def _accepts(request_headers: dict[str, str], coding: str) -> bool:
    for part in request_headers.get("accept-encoding", "").split(","):
        name, _, params = part.strip().partition(";")
        if name.strip().lower() == coding:
            q = params.strip()
            return not (q.startswith("q=") and q[2:].strip() in ("0", "0.0", "0.00", "0.000"))
    return False


class JsonGzip:
    """Gzips JSON API responses (>= 1 kB) for clients that accept it, when nothing sits in front of the server:
    Tailscale / local access (in domain mode Caddy's `encode` compresses, a proxied request - X-Forwarded-For - is
    left to the proxy). A list of 300 sessions: 175 kB -> 13 kB. Streams (SSE, files) are never touched: only a
    complete single-message `application/json` body is compressed."""

    MIN = 1024
    THREAD = 256 * 1024          # bigger bodies are compressed off the event loop

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        hdrs = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        if "x-forwarded-for" in hdrs or not _accepts(hdrs, "gzip"):
            return await self.app(scope, receive, send)
        start: dict | None = None
        passthrough = False

        async def wrapped(msg) -> None:
            nonlocal start, passthrough
            if passthrough:
                return await send(msg)
            if msg["type"] == "http.response.start":
                start = msg
                return
            passthrough = True
            if msg["type"] != "http.response.body" or start is None:   # e.g. http.response.pathsend
                if start is not None:
                    await send(start)
                return await send(msg)
            body = msg.get("body", b"")
            headers = [(k, v) for k, v in start.get("headers", [])]
            names = {k.lower(): v for k, v in headers}
            if (msg.get("more_body") or len(body) < self.MIN or b"content-encoding" in names
                    or not names.get(b"content-type", b"").startswith(b"application/json")):
                await send(start)
                return await send(msg)
            z = await asyncio.to_thread(gzip.compress, body, 5) if len(body) > self.THREAD else gzip.compress(body, 5)
            headers = [(k, v) for k, v in headers if k.lower() not in (b"content-length", b"vary")]
            vary = names.get(b"vary")
            headers += [(b"content-encoding", b"gzip"), (b"content-length", str(len(z)).encode()),
                        (b"vary", vary + b", Accept-Encoding" if vary else b"Accept-Encoding")]
            await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": z})

        await self.app(scope, receive, wrapped)


def _code(status: int) -> str:
    return {400: "bad_request", 401: "auth_required", 403: "forbidden", 404: "not_found",
            409: "conflict", 413: "too_large", 429: "throttled"}.get(status, "error")


_PWA_TYPES = {
    "sw.js": "text/javascript; charset=utf-8",
    "manifest.webmanifest": "application/manifest+json",
    "offline.html": "text/html; charset=utf-8",
}


def _accepts_br(request: Request) -> bool:
    for part in request.headers.get("accept-encoding", "").split(","):
        name, _, params = part.strip().partition(";")
        if name.strip().lower() == "br":
            q = params.strip()
            return not (q.startswith("q=") and q[2:].strip() in ("0", "0.0", "0.00", "0.000"))
    return False


_index_gz_cache: dict = {}


def _index_gz(index: Path) -> bytes | None:
    """index.html gzipped, recomputed when it changes."""
    try:
        st = index.stat()
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    if _index_gz_cache.get("key") != key:
        _index_gz_cache.update(key=key, body=gzip.compress(index.read_bytes(), 6))
    return _index_gz_cache["body"]


def _mount_spa(app: FastAPI) -> None:
    dist: Path = config.WEB_DIST
    index = dist / "index.html"

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def spa(path: str, request: Request):
        if path.startswith("api/"):
            raise HTTPException(404, detail={"error": "not_found", "message": path})
        f = (dist / path).resolve()
        if path and f.is_file() and dist.resolve() in f.parents:
            # PWA files: the service worker, its manifest and the offline page must be revalidated on every
            # load (a stale sw.js would pin users to an old build); hashed assets never change.
            if path in _PWA_TYPES:
                return FileResponse(f, media_type=_PWA_TYPES[path], headers={"Cache-Control": "no-cache"})
            if "/assets/" in f.as_posix():
                cache = "public, max-age=31536000, immutable"
                # Hashed JS/CSS ship with a Brotli twin built by Vite (`<name>.br`, ~18 % smaller than gzip).
                # The reverse proxy leaves an already-encoded response alone.
                br = f.with_name(f.name + ".br")
                if f.suffix in (".js", ".css") and br.is_file():
                    vary = {"Cache-Control": cache, "Vary": "Accept-Encoding"}
                    if _accepts_br(request):
                        return FileResponse(br, media_type=mimetypes.guess_type(f.name)[0],
                                            headers={**vary, "Content-Encoding": "br"})
                    return FileResponse(f, headers=vary)
            elif path.startswith("icons/"):
                cache = "public, max-age=604800"
            else:
                cache = "public, max-age=3600"
            return FileResponse(f, headers={"Cache-Control": cache})
        if not index.exists():
            return JSONResponse({"error": "no_ui", "message": "web/dist is missing - build the UI"},
                                status_code=503)
        headers = {"Cache-Control": "no-store", "Content-Security-Policy": _app_csp(index)}
        # No proxy in front (Tailscale / local access): the app page is sent gzipped (14 kB -> ~5 kB); behind
        # Caddy, its `encode` does it.
        if "x-forwarded-for" not in request.headers and _accepts(dict(request.headers), "gzip"):
            body = await asyncio.to_thread(_index_gz, index)
            if body is not None:
                return Response(body, media_type="text/html", headers={**headers, "Content-Encoding": "gzip",
                                                                       "Vary": "Accept-Encoding"})
        return FileResponse(index, headers=headers)
