"""Token and cost statistics (Settings -> Usage). See docs/dev/API.md#stats."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import budget, stats
from ..security import require_auth

router = APIRouter(prefix="/api/stats", tags=["stats"], dependencies=[Depends(require_auth)])


@router.get("/tokens")
async def tokens(force: bool = False):
    return await asyncio.to_thread(stats.tokens, force)


@router.get("/export")
async def export(group: str = "days", format: str = "csv"):  # noqa: A002 - the query parameter name
    """The usage as a file: one grouping (days, projects, topics, agents, sessions), CSV or JSON, every session."""
    if group not in stats.EXPORT_GROUPS:
        raise HTTPException(400, detail={"error": "bad_group", "message": "group is one of " + ", ".join(stats.EXPORT_GROUPS)})
    if format not in ("csv", "json"):
        raise HTTPException(400, detail={"error": "bad_format", "message": "format is csv or json"})
    name = f"harness-usage-{group}.{format}"
    head = {"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"}
    if format == "csv":
        return Response(await asyncio.to_thread(stats.export_csv, group), media_type="text/csv; charset=utf-8", headers=head)
    cols, rows = await asyncio.to_thread(stats.export_rows, group)
    return Response(json.dumps({"group": group, "columns": cols, "rows": rows}, ensure_ascii=False),
                    media_type="application/json", headers=head)


@router.get("/budget")
async def daily_budget():
    return await asyncio.to_thread(budget.status)


async def _turn_end(session: dict, result: dict | None) -> None:
    if budget.limit() or budget._open is not False:
        await asyncio.to_thread(budget.check_quietly)


async def startup() -> None:
    from ..sessions import service
    service.on_turn_end(_turn_end)
