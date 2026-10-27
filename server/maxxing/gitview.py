"""Read-only view of git repositories: the local clones under the files root, and the GitHub account of the vault
key GITHUB_TOKEN (or GH_TOKEN). Feeds the ```git blocks of the chat and the catalog extension `git`.

Local: `local_repos()` walks the files root (depth <= MAX_DEPTH, PRUNE skipped, a repository's own tree not
descended into) and summarises each clone (branch, ahead/behind, changed files, origin -> GitHub "owner/name").
`graph(path)` / `commit(path, sha)` run fixed `git` commands (no shell, no prompt, no optional locks, 10 s); a path
is only accepted when it is a repository inside the files root.
GitHub: `github_repos()` (every account behind the server's GitHub tokens - any vault key holding one, plus the
backup's - merged, best right per repository; each repository call then uses a token that sees it), `github_graph(full_name)`
(default branch + the most recent other branches merged into one history), `github_commit`, `github_pulls`.

A graph is {"repo": {...}, "commits": [{sha, parents, refs:[{name, kind: head|branch|remote|tag}], author, date,
subject}], "truncated": bool}; commits come newest first, children before parents (the UI draws the lanes).
"""
from __future__ import annotations

import calendar
import logging
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

import httpx

from . import config

log = logging.getLogger("maxxing.git")

MAX_DEPTH = 6
MAX_DIRS = 40_000                     # walk budget: a huge tree never stalls the listing
GIT_TIMEOUT = 10
DEFAULT_LIMIT = 200
MAX_LIMIT = 1000
CACHE_S = 60
PRUNE = {"node_modules", "__pycache__", "venv", "site-packages", "dist", "build", "target", "vendor", "proc", "sys",
         "snap", "attachments", "trash"}
SHA_RE = re.compile(r"\A[0-9a-fA-F]{4,40}\Z")
FULL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
GH_PATH_RE = re.compile(r"/*([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?")
SCP_REMOTE_RE = re.compile(r"(?:[^@/:]+@)?([^/:]+):(.*)")
GH_HOSTS = ("github.com", "www.github.com")
TOKEN_KEYS = ("GITHUB_TOKEN", "GH_TOKEN")
SEP = "\x00"              # field separator of our git log formats (written %x00): git keeps \x1f in names
FMT_SEP = "%x00"
MAX_BRANCHES = 20

_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


class GitError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


_building: dict[str, threading.Lock] = {}


def _cached(key: str, fn, refresh: bool = False):
    """60 s cache. Expired: the old value is returned at once and rebuilt in the background (the page never waits
    for 48 repositories x 3 git calls); `refresh` rebuilds now. One build at a time per key."""
    with _lock:
        hit = _cache.get(key)
        build_lock = _building.setdefault(key, threading.Lock())
    if hit and not refresh:
        if time.time() - hit[0] >= CACHE_S and build_lock.acquire(blocking=False):
            def rebuild() -> None:
                try:
                    val = fn()
                    with _lock:
                        _cache[key] = (time.time(), val)
                except Exception:  # noqa: BLE001 - the old value stays; the next call tries again
                    log.warning("git: background refresh of %s failed", key, exc_info=True)
                finally:
                    build_lock.release()
            threading.Thread(target=rebuild, daemon=True, name=f"git-{key[:20]}").start()
        return hit[1]
    with build_lock:
        with _lock:
            hit2 = _cache.get(key)
        if hit2 and hit2 is not hit and time.time() - hit2[0] < CACHE_S:
            return hit2[1]                                  # built by another thread while this one waited
        val = fn()
        with _lock:
            _cache[key] = (time.time(), val)
        return val


def clear_cache() -> None:
    with _lock:
        _cache.clear()
        _access.clear()


# ---- local repositories ---------------------------------------------------------------------
def _root() -> Path:
    return Path(config.load_config().get("files_root") or "/root")


# A repository's own config can name programs git runs on a plain status / log / show (core.fsmonitor, signature
# checks, clean filters, diff drivers, hooks). Repositories found under the files root are not trusted (an extracted
# archive, a clone made by a turn): these settings are switched off on the command line, which wins over the repo.
SAFE_GIT = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "log.showSignature=false",
            "-c", "gpg.program=false", "-c", "gpg.ssh.program=false", "-c", "gpg.x509.program=false",
            "-c", "diff.external=", "-c", "core.quotepath=off")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"     # attributes read from it = none from the worktree
_filters: dict[str, tuple[tuple, list[str]]] = {}


def _filter_overrides(repo: Path) -> list[str]:
    """`-c filter.<name>.*` neutral values for every filter driver git would see for this repo: every config scope
    (local, worktree via `extensions.worktreeConfig`, included files), cached while those files are unchanged."""
    gd = repo / ".git"
    stamp = tuple((f.stat().st_mtime_ns if f.exists() else 0) for f in (gd / "config", gd / "config.worktree", gd))
    hit = _filters.get(str(repo))
    if hit and hit[0] == stamp:
        return hit[1]
    names: set[str] = set()
    cacheable = True
    try:
        r = subprocess.run(["git", *SAFE_GIT, "-C", str(repo), "config", "--includes", "--list"],
                           capture_output=True, text=True, timeout=GIT_TIMEOUT, errors="replace",
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1"})
        for ln in r.stdout.splitlines():
            m = re.match(r"filter\.(.+)\.(?:clean|smudge|process|required)=", ln)
            if m:
                names.add(m.group(1))
            if ln.startswith(("include.", "includeif.")):
                cacheable = False                         # an included file can change without touching these
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = [a for n in sorted(names) for a in ("-c", f"filter.{n}.clean=cat", "-c", f"filter.{n}.smudge=cat",
                                              "-c", f"filter.{n}.process=", "-c", f"filter.{n}.required=false")]
    if cacheable:
        _filters[str(repo)] = (stamp, out)
    return out


def _git(repo: Path, *args: str, timeout: int = GIT_TIMEOUT) -> str:
    # no `safe.directory=*`: git's own check refuses a repository owned by another user (CVE-2022-24765)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "GIT_PAGER": "cat",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_EXTERNAL_DIFF": "",
           "GIT_ATTR_SOURCE": EMPTY_TREE}
    try:
        r = subprocess.run(["git", *SAFE_GIT, *_filter_overrides(repo), "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=timeout, env=env, errors="replace")
    except FileNotFoundError:
        raise GitError(500, "no_git", "git is not installed on this server") from None
    except subprocess.TimeoutExpired:
        raise GitError(504, "git_timeout", f"git {args[0]} took more than {timeout} s") from None
    if r.returncode != 0:
        raise GitError(400, "git_failed", (r.stderr.strip().splitlines() or ["git failed"])[-1][:300])
    return r.stdout


def _is_repo(d: Path) -> bool:
    return (d / ".git").exists()


def _walk(root: Path) -> list[Path]:
    found: list[Path] = []
    budget = MAX_DIRS
    stack = [(root, 0)]
    while stack and budget > 0:
        d, depth = stack.pop()
        budget -= 1
        if _is_repo(d):
            found.append(d)
            continue                                     # a clone's own tree is not searched for more clones
        if depth >= MAX_DEPTH:
            continue
        try:
            subs = [e for e in os.scandir(d) if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue
        for e in subs:
            if e.name.startswith(".") or e.name in PRUNE:
                continue
            stack.append((Path(e.path), depth + 1))
    return sorted(found)


def github_name(remote: str) -> str | None:
    """owner/repo of a remote on github.com itself (URL or scp form `git@github.com:o/r`), else None."""
    remote = remote.strip()
    if "://" in remote:
        u = urlsplit(remote)
        host, path = u.hostname or "", u.path
    else:
        m = SCP_REMOTE_RE.fullmatch(remote)
        if not m:
            return None
        host, path = m.group(1).lower(), m.group(2)
    m = GH_PATH_RE.fullmatch(path) if host in GH_HOSTS else None
    return f"{m.group(1)}/{m.group(2)}" if m else None


def summary(repo: Path) -> dict:
    """Branch, upstream, ahead/behind, changed files, last commit and GitHub name of one clone."""
    out: dict[str, Any] = {"path": str(repo), "name": repo.name, "branch": None, "upstream": None, "ahead": 0,
                           "behind": 0, "changed": 0, "untracked": 0, "last_commit": None, "last_subject": "",
                           "remote": None, "github": None, "error": None}
    try:
        st = _git(repo, "status", "--porcelain=v1", "--branch", "--untracked-files=normal")
        lines = st.splitlines()
        head = lines[0][3:] if lines and lines[0].startswith("## ") else ""
        m = re.match(r"(?:No commits yet on |Initial commit on )?([^.\s]+(?:\.[^.\s]+)*?)(?:\.\.\.(\S+))?(?: \[(.*)\])?$", head)
        if head.startswith("HEAD (no branch)"):
            out["branch"] = None
        elif m:
            out["branch"], out["upstream"] = m.group(1), m.group(2)
            for part in (m.group(3) or "").split(", "):
                if part.startswith("ahead "):
                    out["ahead"] = int(part[6:])
                elif part.startswith("behind "):
                    out["behind"] = int(part[7:])
        for ln in lines[1:]:
            if ln.startswith("??"):
                out["untracked"] += 1
            elif ln.strip():
                out["changed"] += 1
        try:
            last = _git(repo, "log", "-1", "--no-show-signature", f"--format=%ct{FMT_SEP}%s").strip()
            if last:
                ts, subj = last.split(SEP, 1)
                out["last_commit"], out["last_subject"] = int(ts), subj
        except GitError:
            pass                                          # empty repository
        try:
            remote = _git(repo, "config", "--get", "remote.origin.url").strip()
            # never show credentials embedded in a remote URL
            out["remote"] = re.sub(r"//[^/]*@", "//", remote)
            out["github"] = github_name(remote)
        except GitError:
            pass
    except GitError as e:
        out["error"] = e.message
    return out


def _main_clone(d: Path) -> Path | None:
    """The clone a linked worktree belongs to (`.git` file -> `<clone>/.git/worktrees/<name>`), else None."""
    git = d / ".git"
    if not git.is_file():
        return None
    try:
        line = git.read_text(errors="replace").strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    gd = Path(line[7:].strip())
    gd = gd if gd.is_absolute() else (d / gd)
    if gd.parent.name != "worktrees" or gd.parent.parent.name != ".git":
        return None                                       # a submodule or a separate git dir: a repository of its own
    return gd.parent.parent.parent.resolve()


def local_repos(refresh: bool = False) -> list[dict]:
    """One entry per repository: the extra worktrees of a clone (one folder per branch) are counted on the clone
    (`worktrees`), not listed as repositories of their own. A worktree whose clone is not under the files root
    stays listed."""
    def build():
        found = _walk(_root())
        listed = {p.resolve() for p in found}
        worktrees: dict[Path, int] = {}
        repos = []
        for p in found:
            main = _main_clone(p)
            if main is not None and main in listed:
                worktrees[main] = worktrees.get(main, 0) + 1
            else:
                repos.append(p)
        with ThreadPoolExecutor(max_workers=8) as ex:
            items = list(ex.map(summary, repos))
        for it in items:
            it["worktrees"] = worktrees.get(Path(it["path"]).resolve(), 0)
        return sorted(items, key=lambda r: -(r["last_commit"] or 0))
    return _cached("local", build, refresh)


def resolve(path: str) -> Path:
    """A repository path given by the UI or a chat block: must be a clone inside the files root."""
    if not path or "\x00" in path:
        raise GitError(400, "bad_path", "repository path required")
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = _root() / p
    try:
        p = p.resolve()
        root = _root().resolve()
    except OSError:
        raise GitError(404, "not_found", f"no repository at {path}") from None
    if p != root and root not in p.parents:
        raise GitError(403, "outside_root", f"{path} is outside the files root ({root})")
    while not _is_repo(p):                                # a folder inside a clone: use the clone
        if p == root or p.parent == p:
            raise GitError(404, "not_a_repo", f"{path} is not inside a git repository")
        p = p.parent
    return p


def _refs(deco: str) -> list[dict]:
    """%D with --decorate=full ("HEAD -> refs/heads/main, refs/remotes/origin/main, tag: refs/tags/v1")."""
    refs = []
    for r in (x.strip() for x in deco.split(",") if x.strip()):
        current = r.startswith("HEAD -> ")
        if current:
            refs.append({"name": "HEAD", "kind": "head"})
            r = r[8:]
        if r == "HEAD":
            refs.append({"name": "HEAD", "kind": "head"})
        elif r.startswith("tag: refs/tags/"):
            refs.append({"name": r[15:], "kind": "tag"})
        elif r.startswith("refs/heads/"):
            refs.append({"name": r[11:], "kind": "branch", **({"current": True} if current else {})})
        elif r.startswith("refs/remotes/") and not r.endswith("/HEAD"):
            refs.append({"name": r[13:], "kind": "remote"})
    return refs


def graph(path: str, limit: int = DEFAULT_LIMIT, branches: list[str] | None = None) -> dict:
    repo = resolve(path)
    limit = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))
    if branches:
        refs = []
        for b in branches[:MAX_BRANCHES]:
            b = b.strip()
            if not b or b.startswith("-") or ".." in b:
                continue
            for cand in (b, f"origin/{b}"):
                try:
                    _git(repo, "rev-parse", "--verify", "--quiet", cand + "^{commit}")
                    refs.append(cand)
                except GitError:
                    pass
        if not refs:
            raise GitError(404, "no_branch", f"none of these branches exist: {', '.join(branches)}")
        sel = refs
    else:
        sel = ["--branches", "--remotes", "--tags"]
        try:  # an unborn HEAD (empty repository, `checkout --orphan`) is not a revision git log accepts
            _git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
            sel.append("HEAD")
        except GitError:
            pass
    try:
        raw = _git(repo, "log", "--no-show-signature", *sel, "--topo-order", "--decorate=full", f"-n{limit + 1}",
                   f"--format=%H{FMT_SEP}%P{FMT_SEP}%D{FMT_SEP}%an{FMT_SEP}%ct{FMT_SEP}%s", "--decorate-refs-exclude=refs/stash",
                   "--")  # refs only: a file named like a branch must not make them ambiguous
    except GitError as e:
        if any(m in e.message for m in ("does not have any commits", "bad default revision", "unknown revision")):
            raw = ""
        else:
            raise
    commits = []
    for ln in raw.split("\n"):                    # not splitlines(): \x1c-\x1e or \x85 in a subject are not line ends
        parts = ln.split(SEP)
        if len(parts) < 6:
            continue
        sha, parents, deco, author, ts, subject = parts[0], parts[1], parts[2], parts[3], parts[4], SEP.join(parts[5:])
        commits.append({"sha": sha, "parents": parents.split(), "refs": _refs(deco), "author": author,
                        "date": int(ts) if ts.isdecimal() and ts.isascii() else 0, "subject": subject})
    truncated = len(commits) > limit
    s = summary(repo)
    return {"repo": {**s, "kind": "local", "id": str(repo)}, "commits": commits[:limit], "truncated": truncated}


def _object_commit(repo: Path, prefix: str) -> str:
    """The commit of the one object whose id starts with `prefix` (an annotated tag gives the commit it points to)."""
    out = set()
    for obj in _git(repo, "rev-parse", "--disambiguate=" + prefix).split():
        try:
            out.add(_git(repo, "rev-parse", "--verify", "--quiet", obj + "^{commit}").strip())
        except GitError:
            pass                                          # a tree or blob
    if len(out) != 1:
        raise GitError(404, "no_commit", "no such commit")
    return out.pop()


def commit(path: str, sha: str) -> dict:
    repo = resolve(path)
    if not SHA_RE.match(sha or ""):
        raise GitError(400, "bad_sha", "invalid commit id")
    try:  # a tree, blob or annotated tag id would be "shown" as raw content with an empty author
        found = _git(repo, "rev-parse", "--verify", "--quiet", sha + "^{commit}").strip()
        if not found.startswith(sha.lower()):     # a branch or tag named like the id won: look the id itself up
            found = _object_commit(repo, sha.lower())
    except GitError:
        raise GitError(404, "no_commit", "no such commit") from None
    sha = found
    head = _git(repo, "show", "-s", "--no-show-signature", f"--format=%H{FMT_SEP}%P{FMT_SEP}%an{FMT_SEP}%ae{FMT_SEP}%ct{FMT_SEP}%B", sha)
    h, parents, an, ae, ct, body = (head.split(SEP, 5) + [""] * 6)[:6]
    files = []
    stat = _git(repo, "show", "--no-show-signature", "--no-ext-diff", "--no-textconv", "--format=", "--numstat", "-M", "--diff-merges=first-parent", sha)
    for ln in stat.splitlines():
        cols = ln.split("\t")
        if len(cols) == 3:
            add, rem, name = cols
            files.append({"path": name, "additions": int(add) if add.isdigit() else None,
                          "deletions": int(rem) if rem.isdigit() else None})
    return {"sha": h, "parents": parents.split(), "author": an, "email": ae,
            "date": int(ct) if ct.isdecimal() and ct.isascii() else 0,
            "message": body.strip(), "files": files[:300], "files_total": len(files)}


# ---- GitHub -------------------------------------------------------------------------------
def github_api() -> str:
    return os.environ.get("MAXXING_GITHUB_API", "https://api.github.com").rstrip("/")


GH_TOKEN_RE = re.compile(r"^(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]{20,}$")
PERM_RANK = {"admin": 5, "maintain": 4, "push": 3, "triage": 2, "pull": 1, "none": 0}
_access: dict[str, list[str]] = {}            # "owner/name" (lower) -> token values that see it, best right first


def tokens() -> list[tuple[str, str]]:
    """Every GitHub token the server knows, as (label, value): the vault keys whose value looks like a GitHub token
    (whatever their name), GITHUB_TOKEN / GH_TOKEN whatever their format, and the memory backup's token. A value
    present under several names counts once (first name)."""
    from . import vault
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(label: str, value: str | None) -> None:
        v = (value or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append((label, v))
    entries = vault._vault()
    for k in TOKEN_KEYS:
        add(k, (entries.get(k) or {}).get("value"))
    for k in sorted(entries):
        if GH_TOKEN_RE.match((entries[k].get("value") or "").strip()):
            add(k, entries[k]["value"])
    add("backup", config.get_secret("github_token"))
    return out


_http: httpx.Client | None = None


def _client() -> httpx.Client:
    """One connection pool for every GitHub call (a graph makes up to 15: no new TLS handshake each)."""
    global _http
    with _lock:
        if _http is None:
            _http = httpx.Client(timeout=15, limits=httpx.Limits(max_connections=16))
        return _http


def _gh(path: str, params: dict | None = None, tok: str | None = None) -> Any:
    if not tok:
        raise GitError(400, "no_token", "add a GitHub token as GITHUB_TOKEN in Settings -> Keys")
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "harness-maxxing"}
    try:
        r = _client().get(github_api() + path, headers=headers, params=params)
    except httpx.HTTPError as e:
        raise GitError(502, "github_unreachable", f"GitHub unreachable: {type(e).__name__}") from None
    if r.status_code == 401:
        # 502, not 401: a 401 from our API means "signed out" and sends the UI back to the sign-in page
        raise GitError(502, "bad_token", "GitHub refused the token (expired or revoked?)")
    if r.status_code in (403, 429) and (r.headers.get("x-ratelimit-remaining") == "0" or r.headers.get("retry-after")):
        raise GitError(429, "rate_limited", "GitHub rate limit reached - try again in a few minutes")
    if r.status_code in (403, 404):
        raise GitError(404, "not_found", "not found on GitHub (or no token has access)")
    if r.status_code >= 400:
        msg = ""
        try:
            msg = r.json().get("message", "")
        except ValueError:
            pass
        raise GitError(502, "github_error", f"GitHub {r.status_code}: {msg}"[:300])
    try:
        return r.json()
    except ValueError:
        raise GitError(502, "github_error", "GitHub sent an unreadable answer") from None


def _perm(p: dict | None) -> str:
    p = p or {}
    for k in ("admin", "maintain", "push", "triage", "pull"):
        if p.get(k):
            return k
    return "none"


def _one_token(label: str, tok: str) -> dict:
    try:
        me = _gh("/user", tok=tok)
        if not isinstance(me, dict):
            raise GitError(502, "github_error", "GitHub sent an unexpected answer")
        repos: list[dict] = []
        for page in range(1, 6):
            batch = _gh("/user/repos", {"per_page": 100, "page": page, "sort": "pushed",
                                        "affiliation": "owner,collaborator,organization_member"}, tok)
            if not isinstance(batch, list):
                break
            # an entry without the fields the page needs is skipped, not a 500 for every account
            repos += [r for r in batch if isinstance(r, dict) and isinstance(r.get("full_name"), str)
                      and isinstance(r.get("owner"), dict) and r["owner"].get("login") and r.get("name")]
            if len(batch) < 100:
                break
        return {"label": label, "tok": tok, "me": me, "repos": repos, "error": None}
    except GitError as e:
        return {"label": label, "tok": tok, "me": None, "repos": [], "error": e.message}
    except (KeyError, TypeError, AttributeError):                # an odd answer: this key only, not the whole page
        return {"label": label, "tok": tok, "me": None, "repos": [], "error": "GitHub sent an unexpected answer"}


def github_repos(refresh: bool = False) -> dict:
    """Every account behind the server's GitHub tokens, merged:
    {connected, login, accounts:[{login, name, avatar, keys:[label], repos}], errors:[{key, error}], error,
     repos:[{full_name, owner, name, private, permission (best of the tokens), keys:[label], ...}]}.
    Token values never leave the server: only their key names."""
    toks = tokens()
    if not toks:
        return {"connected": False, "login": None, "accounts": [], "errors": [], "repos": [], "error": None}

    def build():
        with ThreadPoolExecutor(max_workers=6) as ex:
            results = list(ex.map(lambda t: _one_token(*t), toks))
        accounts: dict[str, dict] = {}
        repos: dict[str, dict] = {}
        access: dict[str, list[tuple[int, str]]] = {}
        for res in results:
            if res["error"]:
                continue
            me = res["me"]
            acc = accounts.setdefault(me.get("login") or "?", {"login": me.get("login"), "name": me.get("name"),
                                                               "avatar": me.get("avatar_url"), "keys": [], "repos": 0})
            acc["keys"].append(res["label"])
            for r in res["repos"]:
                perm = _perm(r.get("permissions"))
                key = r["full_name"].lower()
                access.setdefault(key, []).append((PERM_RANK[perm], res["tok"]))
                cur = repos.get(key)
                if cur is None:
                    cur = repos[key] = {
                        "full_name": r["full_name"], "owner": r["owner"]["login"], "name": r["name"],
                        "description": r.get("description") or "", "private": bool(r.get("private")),
                        "fork": bool(r.get("fork")), "archived": bool(r.get("archived")), "permission": perm,
                        "default_branch": r.get("default_branch"), "pushed_at": r.get("pushed_at"),
                        "url": r.get("html_url"), "language": r.get("language"),
                        "stars": r.get("stargazers_count", 0), "open_issues": r.get("open_issues_count", 0),
                        "keys": [], "accounts": []}
                elif PERM_RANK[perm] > PERM_RANK[cur["permission"]]:
                    cur["permission"] = perm
                if res["label"] not in cur["keys"]:
                    cur["keys"].append(res["label"])
                if me.get("login") not in cur["accounts"]:
                    cur["accounts"].append(me.get("login"))
        for acc in accounts.values():
            acc["repos"] = sum(1 for r in repos.values() if acc["login"] in r["accounts"])
        with _lock:
            _access.clear()
            _access.update({k: [t for _, t in sorted(v, key=lambda x: -x[0])] for k, v in access.items()})
        errors = [{"key": r["label"], "error": r["error"]} for r in results if r["error"]]
        ordered = sorted(repos.values(), key=lambda r: r.get("pushed_at") or "", reverse=True)
        accs = sorted(accounts.values(), key=lambda a: -a["repos"])
        return {"connected": True, "login": accs[0]["login"] if accs else None, "accounts": accs, "errors": errors,
                "error": errors[0]["error"] if errors and not accs else None, "repos": ordered}
    return _cached("github", build, refresh)


def _repo_tokens(full: str) -> list[str]:
    """Tokens to try for one repository: those that listed it (best right first), then the others."""
    current = [t for _, t in tokens()]
    with _lock:
        known = [t for t in _access.get(full.lower(), []) if t in current]    # a key removed from the vault: gone
    if not known:                                       # only then re-list the accounts (not on every commit click)
        github_repos()
        with _lock:
            known = [t for t in _access.get(full.lower(), []) if t in current]
    return known + [t for t in current if t not in known]


def _gh_repo(full: str, path: str, params: dict | None = None) -> Any:
    """GET a repository URL with the first token that has access to it."""
    toks = _repo_tokens(full)
    if not toks:
        raise GitError(400, "no_token", "add a GitHub token as GITHUB_TOKEN in Settings -> Keys")
    last: GitError | None = None
    for tok in toks:
        try:
            return _gh(path, params, tok)
        except GitError as e:
            if e.code not in ("not_found", "bad_token"):
                raise
            if last is None or e.code == "not_found":          # "not found" says more than one refused token
                last = e
    raise last  # type: ignore[misc]


def _full(full_name: str) -> str:
    if not FULL_NAME_RE.match(full_name or "") or any(part in (".", "..") for part in full_name.split("/")):
        raise GitError(400, "bad_repo", "expected owner/name")
    return full_name


def _ts(iso: str | None) -> int:
    if not iso:
        return 0
    try:
        return calendar.timegm(time.strptime(iso.replace("Z", "")[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return 0


def github_graph(full_name: str, limit: int = DEFAULT_LIMIT, branches: list[str] | None = None,
                 max_branches: int = 12) -> dict:
    """History of the default branch (and the most recent other branches) merged into one graph."""
    full = _full(full_name)
    limit = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))
    info = _gh_repo(full, f"/repos/{full}")
    default = info.get("default_branch") or "main"
    all_b = _gh_repo(full, f"/repos/{full}/branches", {"per_page": 100})
    heads = {b["name"]: b["commit"]["sha"] for b in all_b}
    if branches:
        wanted = [b for b in (x.strip() for x in branches) if b in heads]
        if not wanted:
            raise GitError(404, "no_branch", f"none of these branches exist: {', '.join(branches)}")
    else:
        wanted = [default] + [b for b in heads if b != default]
    wanted = wanted[: max_branches + 1]

    def fetch(b: str) -> list[dict]:
        n = min(100, limit) if b == default else min(40, limit)
        return _gh_repo(full, f"/repos/{full}/commits", {"sha": b, "per_page": n})

    with ThreadPoolExecutor(max_workers=6) as ex:
        lists = list(ex.map(fetch, wanted))
    by_sha: dict[str, dict] = {}
    for lst in lists:
        for c in lst:
            if c["sha"] in by_sha:
                continue
            cm = c.get("commit") or {}
            by_sha[c["sha"]] = {"sha": c["sha"], "parents": [p["sha"] for p in c.get("parents") or []], "refs": [],
                                "author": ((cm.get("author") or {}).get("name") or (c.get("author") or {}).get("login") or ""),
                                "date": _ts((cm.get("committer") or cm.get("author") or {}).get("date")),
                                "subject": (cm.get("message") or "").split("\n", 1)[0]}
    for b, sha in heads.items():
        if sha in by_sha:
            by_sha[sha]["refs"].append({"name": b, "kind": "branch", **({"current": True} if b == default else {})})
    commits = _topo(list(by_sha.values()))
    tip_count = len(commits)
    s = {"kind": "github", "id": f"github:{full}", "name": info.get("name"), "path": None, "github": full,
         "branch": default, "private": bool(info.get("private")), "permission": _perm(info.get("permissions")),
         "url": info.get("html_url"), "description": info.get("description") or "",
         "branches": len(heads), "branches_shown": len(wanted)}
    return {"repo": s, "commits": commits[:limit], "truncated": tip_count > limit or len(heads) > len(wanted)}


def _topo(commits: list[dict]) -> list[dict]:
    """Newest first, a commit always before its parents (dates alone can disagree)."""
    by = {c["sha"]: c for c in commits}
    children: dict[str, int] = {c["sha"]: 0 for c in commits}
    for c in commits:
        for p in c["parents"]:
            if p in children:
                children[p] += 1
    ready = sorted((c for c in commits if children[c["sha"]] == 0), key=lambda c: c["date"])
    out = []
    while ready:
        c = ready.pop()                                   # newest available
        out.append(c)
        for p in c["parents"]:
            if p in children:
                children[p] -= 1
                if children[p] == 0:
                    ready.append(by[p])
                    ready.sort(key=lambda x: x["date"])
    return out


def github_commit(full_name: str, sha: str) -> dict:
    full = _full(full_name)
    if not SHA_RE.match(sha or ""):
        raise GitError(400, "bad_sha", "invalid commit id")
    c = _gh_repo(full, f"/repos/{full}/commits/{sha}")
    cm = c.get("commit") or {}
    files = [{"path": f.get("filename"), "additions": f.get("additions"), "deletions": f.get("deletions")}
             for f in c.get("files") or []]
    return {"sha": c["sha"], "parents": [p["sha"] for p in c.get("parents") or []],
            "author": (cm.get("author") or {}).get("name") or "", "email": (cm.get("author") or {}).get("email") or "",
            "date": _ts((cm.get("author") or {}).get("date")), "message": (cm.get("message") or "").strip(),
            "files": files[:300], "files_total": len(files), "url": c.get("html_url")}


def github_pulls(full_name: str) -> list[dict]:
    full = _full(full_name)
    return [{"number": p["number"], "title": p["title"], "author": (p.get("user") or {}).get("login"),
             "head": (p.get("head") or {}).get("ref"), "base": (p.get("base") or {}).get("ref"),
             "draft": bool(p.get("draft")), "url": p.get("html_url"), "updated": _ts(p.get("updated_at"))}
            for p in _gh_repo(full, f"/repos/{full}/pulls", {"state": "open", "per_page": 30})]


# ---- one entry point for the UI and the extension -----------------------------------------
def any_graph(repo: str, limit: int = DEFAULT_LIMIT, branches: list[str] | None = None) -> dict:
    """`repo` = a local path, or `github:owner/name`."""
    if repo.startswith("github:"):
        return github_graph(repo[7:], limit, branches)
    return graph(repo, limit, branches)


def any_commit(repo: str, sha: str) -> dict:
    if repo.startswith("github:"):
        return github_commit(repo[7:], sha)
    return commit(repo, sha)


def overview(refresh: bool = False) -> dict:
    """Local clones + GitHub account; each GitHub repository lists its local clones."""
    local = local_repos(refresh)
    gh = github_repos(refresh)
    clones: dict[str, list[str]] = {}
    for r in local:
        if r["github"]:
            clones.setdefault(r["github"].lower(), []).append(r["path"])
    for r in gh["repos"]:
        r["local_paths"] = clones.get(r["full_name"].lower(), [])
    return {"root": str(_root()), "local": local, "github": gh}
