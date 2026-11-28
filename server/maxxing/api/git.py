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
    number: int = Field(..., strict=True, ge=1)  # `true` would otherwise be pull request #1


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
    sha: str | None = Field(None, max_length=64)


@router.post("/api/git/pull/review")
async def pull_review(b: ReviewIn):
    return await _call(gitview.pull_review, _gh_repo(b.repo), b.number, b.event, b.body,
                       [c.model_dump() for c in b.comments], b.sha)


class MergeIn(PullAct):
    method: str = "squash"
    sha: str | None = None                      # merge only if the head is still this commit
    anyway: bool = False                        # although the repository's gate is closed (gate.py)


@router.post("/api/git/pull/merge")
async def pull_merge(b: MergeIn):
    from .. import gate, taskflow

    def run():
        full, sha = _gh_repo(b.repo), b.sha
        if not b.anyway:
            t = gate.pr_target(full, b.number)
            gate.check(t)
            sha = t.sha if t else sha             # what was verified and reviewed, nothing pushed since
        return gitview.pull_merge(full, b.number, b.method, sha)
    out = await _call(run)
    taskflow.soon()                              # the task this pull request delivers is done
    return out


class CheckAct(BaseModel):
    repo: str
    id: int = Field(..., strict=True, ge=1)


@router.get("/api/git/pull/check-log")
async def pull_check_log(repo: str, id: int):
    """The end of the log of a GitHub Actions job (a check with `job: true`)."""
    return await _call(gitview.check_log, _gh_repo(repo), id)


@router.post("/api/git/pull/check-rerun")
async def pull_check_rerun(b: CheckAct):
    return await _call(gitview.check_rerun, _gh_repo(b.repo), b.id)


@router.post("/api/git/pull/close")
async def pull_close(b: PullAct):
    return await _call(gitview.pull_close, _gh_repo(b.repo), b.number)
