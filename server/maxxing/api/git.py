"""Git: read-only view of the local clones and the GitHub account (maxxing/gitview.py).
Used by the ```git blocks of the chat and by the catalog extension `git`. See docs/dev/API.md#git."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from .. import gitview
from ..security import require_auth

router = APIRouter(tags=["git"], dependencies=[Depends(require_auth)])


async def _call(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except gitview.GitError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


def _branches(b: Optional[str]) -> list[str] | None:
    return [x.strip() for x in b.split(",") if x.strip()] if b else None


@router.get("/api/git/repos")
async def repos(refresh: bool = False):
    return await _call(gitview.overview, refresh)


@router.get("/api/git/graph")
async def graph(repo: str, limit: int = gitview.DEFAULT_LIMIT, branches: Optional[str] = None):
    return await _call(gitview.any_graph, repo, limit, _branches(branches))


@router.get("/api/git/commit")
async def commit(repo: str, sha: str):
    return await _call(gitview.any_commit, repo, sha)


@router.get("/api/git/pulls")
async def pulls(repo: str):
    if not repo.startswith("github:"):
        raise HTTPException(400, detail={"error": "not_github", "message": "pull requests need github:owner/name"})
    return await _call(gitview.github_pulls, repo[7:])
