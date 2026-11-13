"""Changes view: what a session changed in git repositories, file diffs, and the git actions the user clicks
(restore, commit, push, branch, pull request). Engine: maxxing/codediff.py. See docs/dev/API.md#code."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import codediff, config, gitview
from ..gitsafe import GitError
from ..security import require_auth
from ..sessions import spawn, store

router = APIRouter(tags=["code"], dependencies=[Depends(require_auth)])
log = logging.getLogger("maxxing.code")

REV_RE = re.compile(r"\A(?:[0-9a-f]{7,40}|now|HEAD)\Z")
SCOPES = ("turn", "session", "uncommitted", "branch")
MESSAGE_MODEL = "haiku"
MESSAGE_DIFF_CHARS = 40_000


async def _call(fn, *args, **kw):
    try:
        return await asyncio.to_thread(fn, *args, **kw)
    except GitError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


def _rev(repo: Path, rev: str) -> str:
    if not REV_RE.match(rev or ""):
        raise GitError(400, "bad_rev", "bad revision")
    return codediff.snapshot(repo) if rev == "now" else rev


def _meta(sid: str) -> dict:
    if not store.is_valid_id(sid):
        raise HTTPException(404, detail={"error": "not_found", "message": "no such session"})
    m = store.read(sid)
    if m is None:
        raise HTTPException(404, detail={"error": "not_found", "message": "no such session"})
    return m


def _turn_entries(sid: str) -> list[dict]:
    out = []
    try:
        with open(store.log_path(sid), errors="replace") as f:
            for ln in f:
                if '"mx_changes"' not in ln:
                    continue
                try:
                    ev = json.loads(ln)
                except ValueError:
                    continue
                if ev.get("type") == "mx_changes":
                    out.append(ev)
    except OSError:
        pass
    return out


def _changes(sid: str, scope: str, n: Optional[int], base: Optional[str]) -> dict:
    meta = _meta(sid)
    if scope not in SCOPES:
        raise GitError(400, "bad_scope", "scope: turn | session | uncommitted | branch")
    if scope == "turn":
        entries = _turn_entries(sid)
        if n is not None:
            entries = [e for e in entries if e.get("n") == n]
        if not entries:
            return {"scope": scope, "n": n, "repos": []}
        e = entries[-1]
        repos = []
        for r in e.get("repos") or []:
            root = Path(r.get("root") or "")
            head = codediff.repo_head(root) if root.is_dir() else {}
            repos.append({**r, **{k: head[k] for k in ("branch", "upstream", "ahead", "behind", "remote") if k in head}})
        return {"scope": scope, "n": e.get("n"), "repos": repos}
    repos = []
    for root in meta.get("code_repos") or []:
        p = Path(root)
        if not p.is_dir():
            continue
        try:
            v = codediff.view(p, scope, (meta.get("code_base") or {}).get(root), base)
        except GitError as e:
            repos.append({"root": root, "name": p.name, "error": e.message, "files": [], "add": 0, "del": 0})
            continue
        if v["files"] or scope == "branch":
            repos.append(v)
    return {"scope": scope, "n": None, "repos": repos}


@router.get("/api/sessions/{sid}/changes")
async def changes(sid: str, scope: str = "turn", n: Optional[int] = None, base: Optional[str] = None):
    return await _call(_changes, sid, scope, n, base)


@router.get("/api/code/diff")
async def diff(repo: str, a: str, b: str, path: str, old: Optional[str] = None, full: bool = False):
    def run():
        r = codediff.checked_repo(repo)
        return codediff.diff(r, _rev(r, a), _rev(r, b), path, old, full)
    return await _call(run)


@router.get("/api/code/commits")
async def commits(repo: str, base: Optional[str] = None):
    return await _call(lambda: codediff.commits(codediff.checked_repo(repo), base))


@router.get("/api/code/status")
async def status(repo: str):
    """Branch, upstream, ahead / behind, and on GitHub the open pull request of the branch and its checks."""
    def run():
        r = codediff.checked_repo(repo)
        head = codediff.repo_head(r)
        full = gitview.github_name(head.get("remote") or "") if head.get("remote") else None
        out = {**head, "dirty": codediff.dirty(r), "github": full, "pr": None, "checks": None}
        if full and head.get("branch"):
            try:
                sha = codediff.head_sha(r)
                out.update(gitview.branch_status(full, head["branch"], sha))
            except GitError as e:
                out["github_error"] = e.message
        return out
    return await _call(run)


class RestoreIn(BaseModel):
    repo: str
    source: str
    paths: Optional[list[str]] = None


@router.post("/api/code/restore")
async def restore(body: RestoreIn):
    """Put files back as in `source` (a turn's photo, HEAD...). The answer's `undo` restores what was there."""
    def run():
        r = codediff.checked_repo(body.repo)
        return codediff.restore(r, _rev(r, body.source), body.paths or None)
    return await _call(run)


class CommitIn(BaseModel):
    repo: str
    message: str
    paths: Optional[list[str]] = None
    push: bool = False


@router.post("/api/code/commit")
async def commit(body: CommitIn):
    def run():
        r = codediff.checked_repo(body.repo)
        out = codediff.commit(r, body.message, body.paths or None)
        if body.push:
            out = {**out, **codediff.push(r), "pushed": True}
        return out
    return await _call(run)


class RepoIn(BaseModel):
    repo: str


@router.post("/api/code/push")
async def push(body: RepoIn):
    return await _call(lambda: codediff.push(codediff.checked_repo(body.repo)))


class BranchIn(BaseModel):
    repo: str
    name: str


@router.post("/api/code/branch")
async def branch(body: BranchIn):
    return await _call(lambda: codediff.new_branch(codediff.checked_repo(body.repo), body.name))


class PullIn(BaseModel):
    repo: str
    title: Optional[str] = None
    body: Optional[str] = None
    base: Optional[str] = None
    draft: bool = False


def _pull(body: PullIn) -> dict:
    r = codediff.checked_repo(body.repo)
    head = codediff.repo_head(r)
    full = gitview.github_name(head.get("remote") or "") if head.get("remote") else None
    if not full:
        raise GitError(400, "not_github", "this repository has no GitHub remote named origin")
    if not head.get("branch"):
        raise GitError(400, "detached", "not on a branch: create a branch first")
    if not head.get("upstream") or head.get("ahead"):
        head = codediff.push(r)
    base = (body.base or codediff.default_base(r) or "main").removeprefix("origin/")
    if base == head["branch"]:
        raise GitError(400, "same_branch", "create a branch first: a pull request needs another branch than "
                                           f"{base}")
    subjects = [c["subject"] for c in codediff.commits(r, f"origin/{base}")]
    title = (body.title or (subjects[-1] if len(subjects) == 1 else (subjects[0] if subjects else head["branch"])))
    text = body.body if body.body is not None else "\n".join(f"- {s}" for s in reversed(subjects))
    return gitview.open_pull(full, head["branch"], base, title.strip(), text, body.draft)


@router.post("/api/code/pr")
async def pull(body: PullIn):
    return await _call(_pull, body)


class MessageIn(BaseModel):
    repo: str
    a: str = "HEAD"
    b: str = "now"


MESSAGE_PROMPT = (
    "You write git commit messages. Reply with the message only: a subject line of at most 72 characters in the "
    "imperative mood, then (only when useful) a blank line and a short body. Follow the style of the recent "
    "subjects shown. Never mention an AI, an assistant or a co-author.")


def _message(body: MessageIn) -> dict:
    r = codediff.checked_repo(body.repo)
    a, b = _rev(r, body.a), _rev(r, body.b)
    d = codediff.raw_diff(r, a, b)[:MESSAGE_DIFF_CHARS]
    if not d.strip():
        raise GitError(400, "nothing", "nothing to commit")
    recent = [c["subject"] for c in codediff.commits(r, None, 10, everything=True)] if codediff.head_sha(r) else []
    prompt = "Recent subjects:\n" + "\n".join(recent) + "\n\nDiff:\n" + d
    cmd = [spawn.claude_bin(), "-p", "--output-format", "json", "--model", MESSAGE_MODEL, "--tools", "",
           "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
           "--system-prompt", MESSAGE_PROMPT]
    try:
        p = subprocess.run(cmd, input=prompt.encode("utf-8", "replace").decode("utf-8"), capture_output=True,
                           text=True, timeout=60, cwd=config.state_dir("claude-titles"),
                           env=spawn.claude_env(None, "default"))
        data = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {}
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        log.info("commit message call failed: %s", e)
        raise GitError(502, "no_message", "Claude could not write a message - type one") from None
    text = str((data or {}).get("result") or "").strip().strip("`").strip()
    if p.returncode != 0 or not text or (data or {}).get("is_error"):
        raise GitError(502, "no_message", "Claude could not write a message - type one")
    lines = [ln for ln in text.splitlines() if not re.match(r"(?i)\s*co-authored-by:", ln)]
    return {"message": "\n".join(lines).strip()}


@router.post("/api/code/message")
async def message(body: MessageIn):
    return await _call(_message, body)


class RevertIn(BaseModel):
    n: int


def _revert(sid: str, n: int) -> dict:
    """Every repository turn `n` changed goes back to its photo from before that turn. Files only: commits made
    since stay (the answer lists them). `undo` per repository puts the current state back."""
    meta = _meta(sid)
    if store.runner_alive(sid, meta) and meta.get("state") == "running":
        raise GitError(409, "running", "wait for the end of the turn (or stop it) before going back")
    entries = [e for e in _turn_entries(sid) if e.get("n") == n]
    if not entries:
        raise GitError(404, "no_photo", "this message changed no repository")
    later = [e for e in _turn_entries(sid) if isinstance(e.get("n"), int) and e["n"] > n]
    out = []
    roots: dict[str, str] = {}
    for e in entries:
        for r in e.get("repos") or []:
            roots.setdefault(r["root"], r["pre"])
    for e in later:                                    # a later turn that changed another repository: back too
        for r in e.get("repos") or []:
            roots.setdefault(r["root"], r["pre"])
    for root, pre in roots.items():
        repo = codediff.checked_repo(root)
        res = codediff.restore(repo, pre)
        head = codediff.head_sha(repo)
        moved = head and _commit_of(repo, pre) and head != _commit_of(repo, pre)
        out.append({"root": root, "name": repo.name, **res, "commits_kept": bool(moved)})
    return {"n": n, "repos": out}


def _commit_of(repo: Path, photo: str) -> str | None:
    """The HEAD a photo was taken on (its parent)."""
    try:
        return codediff._git(repo, "rev-parse", "-q", "--verify", f"{photo}^1").strip() or None
    except GitError:
        return None


@router.post("/api/sessions/{sid}/revert")
async def revert(sid: str, body: RevertIn):
    return await _call(_revert, sid, body.n)


class UndoIn(BaseModel):
    repos: list[dict]


@router.post("/api/code/undo")
async def undo(body: UndoIn):
    """Put back what a restore or a revert replaced: [{root, undo}]."""
    def run():
        done = []
        for r in body.repos[:20]:
            repo = codediff.checked_repo(str(r.get("root") or ""))
            done.append({"root": str(repo), **codediff.restore(repo, _rev(repo, str(r.get("undo") or "")))})
        return {"repos": done}
    return await _call(run)


# ---- separate copies (worktrees.py) ---------------------------------------------------------------------------

@router.get("/api/code/copy-repos")
async def copy_repos(path: str = ""):
    """The repositories a new session of topic `path` can work on a separate copy of ([] without Code mode)."""
    from .. import worktrees
    if not worktrees.enabled():
        return {"enabled": False, "repos": []}
    return {"enabled": True, "repos": await _call(worktrees.repos_for, path.strip("/"))}


class CopyPrefsIn(BaseModel):
    repo: str
    prefix: Optional[str] = None
    prepare: Optional[str] = None
    copy_env: Optional[bool] = None


@router.put("/api/code/copy-prefs")
async def copy_prefs(body: CopyPrefsIn):
    from .. import worktrees

    def run():
        worktrees._need_enabled()
        repo = worktrees.main_clone(codediff.checked_repo(body.repo))
        prefix = worktrees.check_prefix(body.prefix) if body.prefix is not None else None
        return worktrees.set_prefs(repo, prefix=prefix, prepare=(body.prepare or "")[:500] if body.prepare is not None
                                   else None, copy_env=body.copy_env)
    return await _call(run)


@router.get("/api/sessions/{sid}/copy")
async def copy_status(sid: str):
    from .. import worktrees
    return await _call(lambda: worktrees.status(_meta(sid)))


def _idle(sid: str) -> dict:
    meta = _meta(sid)
    if store.runner_alive(sid, meta) and meta.get("state") == "running":
        raise GitError(409, "running", "wait for the end of the turn (or stop it) first")
    return meta


class CopyEndIn(BaseModel):
    message: Optional[str] = None          # commit what is not committed first, with this message


@router.post("/api/sessions/{sid}/copy/merge")
async def copy_merge(sid: str, body: CopyEndIn):
    from .. import bus, worktrees

    def run():
        meta = _idle(sid)
        wt = worktrees.live(meta)
        if wt and body.message and codediff.dirty(Path(wt["path"])):
            codediff.commit(Path(wt["path"]), body.message)
        out = worktrees.merge(meta)
        bus.invalidate("sessions")
        return out
    return await _call(run)


class CopyRemoveIn(BaseModel):
    force: bool = False                    # discard: uncommitted changes and the branch's own commits go too


@router.post("/api/sessions/{sid}/copy/remove")
async def copy_remove(sid: str, body: CopyRemoveIn):
    from .. import bus, worktrees

    def run():
        out = worktrees.remove(_idle(sid), force=body.force)
        bus.invalidate("sessions")
        return out
    return await _call(run)


@router.get("/api/code/copies")
async def copies():
    from .. import worktrees
    return await _call(worktrees.listing)


@router.get("/api/sessions/{sid}/copy/prepare-log")
async def copy_prepare_log(sid: str):
    from .. import worktrees
    _meta(sid)
    p = worktrees.prepare_log(sid)
    try:
        text = p.read_text(errors="replace")[-20_000:]
    except OSError:
        text = ""
    return {"log": text}


# ---- a session on a pull request: work on it, or have Claude review it -----------------------------------------

TOPIC_RE = re.compile(r"\A(projects/[^/]+(?:/topics/[^/]+)?)(?:/|\Z)")


def _topic_of(clone: Path) -> str | None:
    """The topic (or project) folder holding a clone, as a workspace path."""
    from .. import workspace
    try:
        rel = clone.resolve().relative_to(workspace.root().resolve()).as_posix()
    except ValueError:
        return None
    m = TOPIC_RE.match(rel)
    return m.group(1) if m else None


class PrSessionIn(BaseModel):
    repo: str                              # github:owner/name
    number: int
    review: bool = False                   # Claude reviews (plan mode) instead of working on it
    message: Optional[str] = None          # the first message (written by the UI in the user's language)
    clone: Optional[str] = None            # which local clone, when there are several


def _pr_session(body: PrSessionIn) -> dict:
    from .. import worktrees
    from ..sessions import service
    if not body.repo.startswith("github:"):
        raise GitError(400, "not_github", "pull requests need github:owner/name")
    worktrees._need_enabled()
    full = gitview._full(body.repo[7:])
    p = gitview._gh_repo(full, f"/repos/{full}/pulls/{gitview._number(body.number)}")
    head = p.get("head") or {}
    head_repo = (head.get("repo") or {}).get("full_name") or ""
    clones = [Path(r["path"]) for r in gitview.local_repos() if (r.get("github") or "").lower() == full.lower()]
    if body.clone:
        clones = [c for c in clones if str(c) == body.clone]
    placed = [(c, t) for c in clones if (t := _topic_of(c)) is not None]
    if not placed:
        raise GitError(400, "no_clone", f"clone {full} into a topic first: the session works in that topic")
    clone, topic = placed[0]
    outside = (p.get("author_association") or "") not in gitview.OWN_ROLES
    pr = {"number": p.get("number"), "ref": head.get("ref"), "base": (p.get("base") or {}).get("ref"),
          "fork": bool(head_repo) and head_repo.lower() != full.lower(), "outside": outside, "full": full,
          "url": p.get("html_url")}
    title = f"PR #{p.get('number')} {p.get('title') or ''}".strip()[:120]
    s = service.create_session(topic, message=(body.message or "").strip() or None, title=title, source="web",
                               plan_mode=body.review or outside, worktree={"repo": str(clone), "pr": pr})
    return s


@router.post("/api/code/pr-session")
async def pr_session(body: PrSessionIn):
    from ..sessions.service import SessionError

    def run():
        try:
            return _pr_session(body)
        except SessionError as e:
            raise GitError(e.status, e.code, e.message) from None
    return await _call(run)
