"""Extensions: list / enable / reload, API forwarding and page modules.
See docs/dev/API.md#dashboard--extensions and maxxing/extensions.py.

`ANY /api/ext/{id}/{path}` calls the extension's `handle(ctx, method, path, query, body)` in a
worker thread. The return value is sent as JSON; a `(status, body)` tuple sets the status code;
`ValueError` -> 400, `LookupError` -> 404, anything else -> 500 `extension_error`.
`GET /ext/{id}/page.js` serves the page module (auth required, never cached).
`GET /ext/ui-kit.css` serves the shared UI kit (`ui-*` classes, maxxing/assets/ui-kit.css), loaded by the app for
page extensions and inlined in every HTML widget frame.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from .. import bus, extensions
from ..security import require_auth

router = APIRouter(tags=["extensions"], dependencies=[Depends(require_auth)])
log = logging.getLogger("maxxing.extensions")
HANDLE_TIMEOUT_S = 30.0
MAX_BODY = 5 * 1024 * 1024


def _err(status: int, code: str, msg: str) -> HTTPException:
    return HTTPException(status, detail={"error": code, "message": msg})


@router.get("/api/extensions")
async def list_extensions():
    exts = await asyncio.to_thread(extensions.all_extensions)
    return [e.info() for e in exts]


class PatchIn(BaseModel):
    enabled: Optional[bool] = None
    pinned: Optional[bool] = None             # page extensions: own entry in the sidebar


@router.patch("/api/extensions/{eid}")
async def patch_extension(eid: str, body: PatchIn):
    if extensions.get(eid) is None:
        raise _err(404, "not_found", f"no extension {eid}")
    if body.pinned is not None and not await asyncio.to_thread(extensions.set_pinned, eid, body.pinned):
        raise _err(400, "not_a_page", f"{eid} is not a page extension")
    if body.enabled is not None and not await asyncio.to_thread(extensions.set_enabled, eid, body.enabled):
        raise _err(404, "not_found", f"no extension {eid}")
    bus.invalidate("extensions")
    return {"ok": True}


@router.post("/api/extensions/reload")
async def reload_extensions():
    exts = await asyncio.to_thread(extensions.scan)
    bus.invalidate("extensions")
    return [e.info() for e in exts]


def _usable(eid: str) -> extensions.Extension:
    ext = extensions.get(eid)
    if ext is None:
        raise _err(404, "not_found", f"no extension {eid}")
    if not ext.enabled:
        raise _err(404, "extension_disabled", f"extension {eid} is disabled")
    if ext.error:
        raise _err(500, "extension_error", ext.error)
    return ext


@router.api_route("/api/ext/{eid}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def forward(eid: str, path: str, request: Request):
    if any(part in (".", "..") for part in path.split("/")):   # never a path that climbs out of /api/ext/<id>/
        raise _err(400, "bad_path", "'.' and '..' are not allowed in an extension path")
    ext = await asyncio.to_thread(_usable, eid)
    body: Any = None
    if request.method != "GET":
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise _err(413, "too_large", "request body over 5 MB")
        if raw:
            try:
                body = json.loads(raw)
            except ValueError:
                body = raw.decode("utf-8", "replace")
    try:
        fn = extensions.handler(ext)
    except LookupError as e:
        raise _err(404, "no_handler", str(e)) from None
    ctx = extensions.make_ctx(ext)
    query = dict(request.query_params)
    try:
        result = await extensions.call(fn, ctx, request.method, path, query, body, timeout=HANDLE_TIMEOUT_S,
                                       key=f"handle:{eid}")    # a stuck handle() takes one thread, not all
    except extensions.ExtensionBusy as e:
        raise _err(503, "extension_busy", str(e)) from None
    except asyncio.TimeoutError:
        raise _err(504, "extension_timeout", f"handle() took more than {HANDLE_TIMEOUT_S:.0f} s") from None
    except ValueError as e:
        raise _err(400, "bad_request", str(e)) from None
    except LookupError as e:
        raise _err(404, "not_found", str(e)) from None
    except Exception as e:
        log.warning("extension %s handle failed: %s", eid, e, exc_info=True)
        raise _err(500, "extension_error", f"{type(e).__name__}: {e}") from None
    status = 200
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
        status, result = result
    if result is None:
        result = {"ok": True}
    try:
        return JSONResponse(result, status_code=status)
    except (TypeError, ValueError) as e:
        raise _err(500, "extension_error", f"handle() returned a non-JSON value ({e})") from None


@router.api_route("/api/ext/{eid}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def forward_root(eid: str, request: Request):
    return await forward(eid, "", request)


UI_KIT = Path(__file__).resolve().parent.parent / "assets" / "ui-kit.css"


_KIT: dict = {"key": None, "css": "", "etag": ""}


def _kit() -> dict:
    """The UI kit, read again only when the file changes (it is inlined in every widget frame)."""
    try:
        st = UI_KIT.stat()
        key = (st.st_mtime_ns, st.st_size)
        if _KIT["key"] != key:
            css = UI_KIT.read_text("utf-8")
            _KIT.update(key=key, css=css, etag='"' + hashlib.sha256(css.encode()).hexdigest()[:16] + '"')
    except OSError:
        _KIT.update(key=None, css="", etag="")
    return _KIT


def ui_kit_css() -> str:
    return _kit()["css"]


@router.get("/ext/ui-kit.css", include_in_schema=False)
async def ui_kit(request: Request):
    kit = await asyncio.to_thread(_kit)
    headers = {"Cache-Control": "no-cache", **({"ETag": kit["etag"]} if kit["etag"] else {})}
    if kit["etag"] and request.headers.get("if-none-match") == kit["etag"]:
        return Response(status_code=304, headers=headers)
    return Response(kit["css"], media_type="text/css; charset=utf-8", headers=headers)


def _own_file(ext: extensions.Extension, name: str) -> Path:
    """`name` inside the extension's folder, resolved: a link to a file outside it (~/.claude/.credentials.json...) is
    never served."""
    try:
        p = (ext.dir / name).resolve(strict=True)
        p.relative_to(ext.dir.resolve())
    except (OSError, ValueError):
        raise _err(404, "not_found", f"{name} of extension {ext.id} is outside its folder") from None
    return p


@router.get("/ext/{eid}/page.js", include_in_schema=False)
async def page_js(eid: str):
    ext = await asyncio.to_thread(extensions.get, eid)
    if ext is None or not ext.enabled or ext.error or not ext.has_page:
        raise _err(404, "not_found", f"no page for extension {eid}")
    return FileResponse(_own_file(ext, "page.js"), media_type="text/javascript",
                        headers={"Cache-Control": "no-store"})


# The HTML widget's frame: the bridge (maxxing.api / resize / theme, see web/src/pages/dashboard/HtmlWidget.tsx)
# then the extension's widget.html. Served as a document of its own (not an iframe srcdoc, which would inherit the
# app's strict script policy): sandboxed by the iframe AND by its own CSP, so even opened directly it has no access to
# the app, its cookies or its API. The theme comes in the URL fragment (#{"theme":..,"vars":{..}}); the UI kit
# (`ui-*` classes) is inlined after the bridge and <html> gets the `data-mx-kit` attribute it is scoped to (an attribute,
# not a class: the parser drops the attributes of the widget's own <html> that the bridge already set).
WIDGET_BRIDGE = """<!doctype html><meta charset="utf-8"><script>(function(){
var init={};try{init=JSON.parse(decodeURIComponent(location.hash.slice(1))||'{}')}catch(_){}
var seq=0,pending={},cbs=[],root=document.documentElement;
root.setAttribute('data-mx-kit','');
function apply(v){for(var k in v||{})root.style.setProperty(k,v[k]);root.dataset.theme=window.maxxing.theme;root.style.colorScheme=window.maxxing.theme}
window.maxxing={theme:init.theme||'dark',
 api:function(path,o){o=o||{};return new Promise(function(res,rej){var s=++seq;pending[s]=[res,rej];parent.postMessage({mx:'api',seq:s,path:String(path||''),method:o.method||'GET',body:o.body,query:o.query},'*')})},
 resize:function(h){parent.postMessage({mx:'resize',height:Number(h)||0},'*')},
 onTheme:function(f){cbs.push(f)}};
addEventListener('message',function(e){if(e.source!==parent)return;var m=e.data||{};
 if(m.mx==='reply'){var p=pending[m.seq];if(p){delete pending[m.seq];m.ok?p[0](m.data):p[1](new Error(m.error||'request failed'))}}
 if(m.mx==='theme'){window.maxxing.theme=m.theme;apply(m.vars);cbs.forEach(function(f){try{f(m.theme)}catch(_){}})}});
apply(init.vars);})();</script>
<style>*,*::before,*::after{box-sizing:border-box}html,body{margin:0;background:transparent;color:var(--mx-fg);font:13px/1.45 Inter,system-ui,sans-serif}</style>
"""
WIDGET_FRAME_CSP = "sandbox allow-scripts allow-pointer-lock; frame-ancestors 'self'"


@router.get("/ext/{eid}/widget-frame", include_in_schema=False)
async def widget_frame(eid: str):
    ext = await asyncio.to_thread(extensions.get, eid)
    if ext is None or not ext.enabled or ext.error or not ext.has_html:
        raise _err(404, "not_found", f"no HTML widget for extension {eid}")
    html = await asyncio.to_thread(_own_file(ext, "widget.html").read_text, "utf-8", "replace")
    kit = await asyncio.to_thread(ui_kit_css)
    return HTMLResponse(WIDGET_BRIDGE + f"<style>{kit}</style>\n" + html, headers={
        "Cache-Control": "no-store", "Content-Security-Policy": WIDGET_FRAME_CSP, "Referrer-Policy": "no-referrer"})


@router.get("/ext/{eid}/widget.html", include_in_schema=False)
async def widget_html(eid: str):
    """Raw widget.html; the UI loads it into a sandboxed iframe (srcdoc, no access to the app)."""
    ext = await asyncio.to_thread(extensions.get, eid)
    if ext is None or not ext.enabled or ext.error or not ext.has_html:
        raise _err(404, "not_found", f"no HTML widget for extension {eid}")
    return FileResponse(_own_file(ext, "widget.html"), media_type="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


async def startup() -> None:
    try:
        await asyncio.to_thread(extensions.scan)
    except Exception:
        log.exception("extension scan failed")
