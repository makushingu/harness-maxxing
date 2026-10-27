"""Dashboard: built-in widgets + extension widgets. See docs/dev/API.md#dashboard--extensions.

Every widget is computed in a worker thread with a timeout; a failing widget returns
`card: null, error: "<reason>"` and never breaks the page. The page does not wait for a slow widget: after
SOFT_S it is listed with `pending: true` and keeps computing; `GET /widgets/{id}` then joins that same
computation (one at a time per widget). Layout (order + hidden ids) is
stored in config.json `dashboard`. Hidden widgets are listed (`hidden: true`, card null) so
the UI can offer to show them again.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import bus, config, extensions, widgets
from ..security import require_auth

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_auth)])
log = logging.getLogger("maxxing.dashboard")
TIMEOUT_S = 20.0
SOFT_S = 1.5
_inflight: dict[str, asyncio.Task] = {}


def _defs() -> list[dict[str, Any]]:
    """Every widget that can be shown, in layout order."""
    defs: list[dict[str, Any]] = [{"id": b.id, "title": widgets.t(b.title), "icon": b.icon, "span": b.span,
                                   "source": "builtin"} for b in widgets.available() if b.id != widgets.CUSTOMIZE_ID]
    for e in extensions.all_extensions():
        if e.type == "widget" and e.enabled:
            # the resolved extension rides along (not sent): no rescan of the folder per widget
            defs.append({"id": e.id, "title": e.label(), "icon": e.icon, "span": e.span, "source": "extension",
                         "_ext": e})
    custom = next(b for b in widgets.BUILTINS if b.id == widgets.CUSTOMIZE_ID)
    defs.append({"id": custom.id, "title": widgets.t(custom.title), "icon": custom.icon, "span": custom.span,
                 "source": "builtin"})
    layout = config.load_config().get("dashboard") or {}
    order = [x for x in layout.get("order") or [] if isinstance(x, str)]
    # never arranged (no saved order): the default set; once saved, exactly what the user chose
    hidden = set(layout.get("hidden") or []) if order else widgets.default_hidden()
    rank = {wid: i for i, wid in enumerate(order)}
    # stable: unknown ids keep the default order, after the saved ones; "Make it yours" stays last until placed
    defs.sort(key=lambda d: rank.get(d["id"], len(order) + (d["id"] == custom.id)))
    for d in defs:
        d["hidden"] = d["id"] in hidden
    return defs


def _compute(d: dict, force: bool) -> dict:
    if d["source"] == "builtin":
        return widgets.card(d["id"], force)
    ext = d.get("_ext") or extensions.get(d["id"])
    if ext is None:
        raise RuntimeError("extension not found")
    return widgets.strip_none(extensions.widget_card(ext, force))


def _task(d: dict, force: bool) -> asyncio.Task:
    """The running computation of a widget, shared by concurrent requests (a forced one starts afresh)."""
    wid = d["id"]
    task = _inflight.get(wid)
    if task is None or force:
        # extension cards on the extension threads (a stuck card() never takes the server's shared pool)
        run = (asyncio.wait_for(asyncio.to_thread(_compute, d, force), TIMEOUT_S) if d["source"] == "builtin"
               else extensions.call(_compute, d, force, timeout=TIMEOUT_S, key=f"card:{wid}"))
        task = asyncio.ensure_future(run)
        _inflight[wid] = task

        def done(t: asyncio.Task, wid: str = wid) -> None:
            if _inflight.get(wid) is t:
                del _inflight[wid]
            if not t.cancelled():
                t.exception()                          # retrieved: no "never retrieved" warning
        task.add_done_callback(done)
    return task


async def _render(d: dict, force: bool = False, soft: float | None = None) -> dict:
    out = {**{k: v for k, v in d.items() if k != "_ext"}, "card": None, "error": None}
    if d["hidden"]:
        return out
    task = _task(d, force)
    try:
        out["card"] = await (asyncio.wait_for(asyncio.shield(task), soft) if soft else task)
    except asyncio.TimeoutError:
        if soft and not task.done():
            out["pending"] = True
        else:
            out["error"] = f"timed out after {TIMEOUT_S:.0f} s"
    except extensions.ExtensionBusy as e:
        out["error"] = str(e)
    except ImportError as e:
        out["error"] = f"not available yet ({e.name or e})"
    except Exception as e:
        log.warning("widget %s failed: %s", d["id"], e)
        out["error"] = f"{type(e).__name__}: {e}"[:500]
    return out


@router.get("")
async def dashboard(force: bool = False):
    defs = await asyncio.to_thread(_defs)
    return {"widgets": list(await asyncio.gather(*(_render(d, force, SOFT_S) for d in defs)))}


@router.get("/widgets/{wid}")
async def one_widget(wid: str, force: bool = False):
    defs = await asyncio.to_thread(_defs)
    d = next((x for x in defs if x["id"] == wid), None)
    if d is None:
        raise HTTPException(404, detail={"error": "not_found", "message": f"no widget {wid}"})
    return await _render({**d, "hidden": False}, force)


class LayoutIn(BaseModel):
    order: list[str] = []
    hidden: list[str] = []


@router.put("/layout")
def layout(body: LayoutIn):
    def dedupe(xs: list[str]) -> list[str]:
        return list(dict.fromkeys(x for x in xs if isinstance(x, str) and 0 < len(x) <= 64))[:200]
    config.update_config(dashboard={"order": dedupe(body.order), "hidden": dedupe(body.hidden)})
    bus.invalidate("extensions")
    return {"ok": True}
