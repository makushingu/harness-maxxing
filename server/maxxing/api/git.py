"""Git: read-only view of the local clones and the GitHub account (maxxing/gitview.py).
Used by the ```git blocks of the chat and by the catalog extension `git`. See docs/dev/API.md#git."""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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


def _gh_repo(repo: str) -> str:
    if not repo.startswith("github:"):
        raise HTTPException(400, detail={"error": "not_github", "message": "pull requests need github:owner/name"})
    return repo[7:]


@router.get("/api/git/pulls")
async def pulls(repo: str, state: str = "open"):
    return await _call(gitview.github_pulls, _gh_repo(repo), state)


@router.get("/api/git/pull")
async def pull(repo: str, number: int):
    return await _call(gitview.github_pull, _gh_repo(repo), number)


class PullAct(BaseModel):
    repo: str
    number: int


class CommentIn(PullAct):
    body: str = Field(..., max_length=60000)


@router.post("/api/git/pull/comment")
async def pull_comment(b: CommentIn):
    return await _call(gitview.pull_comment, _gh_repo(b.repo), b.number, b.body)


class LineComment(BaseModel):
    path: str
    line: int
    side: str = "RIGHT"
    body: str = Field(..., max_length=60000)


class ReviewIn(PullAct):
    event: str                                  # APPROVE | REQUEST_CHANGES | COMMENT
    body: str = Field("", max_length=60000)
    comments: list[LineComment] = Field(default_factory=list, max_length=100)


@router.post("/api/git/pull/review")
async def pull_review(b: ReviewIn):
    return await _call(gitview.pull_review, _gh_repo(b.repo), b.number, b.event, b.body,
                       [c.model_dump() for c in b.comments])


class MergeIn(PullAct):
    method: str = "squash"
    sha: str | None = None                      # merge only if the head is still this commit


@router.post("/api/git/pull/merge")
async def pull_merge(b: MergeIn):
    return await _call(gitview.pull_merge, _gh_repo(b.repo), b.number, b.method, b.sha)


@router.post("/api/git/pull/close")
async def pull_close(b: PullAct):
    return await _call(gitview.pull_close, _gh_repo(b.repo), b.number)
