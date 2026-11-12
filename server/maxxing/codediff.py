"""What a session changed in git repositories, and the git actions behind the Changes view.

Before and after every turn, each repository the session knows is photographed: the working tree (tracked and
untracked files, `.gitignore` respected) is written into a throwaway index, then a commit object kept under
`refs/maxxing/<sid8>/<n>/{pre,post}`. The user's index, HEAD, branch and files are never touched by a photo.
Every view is then a tree-to-tree diff: one turn (pre..post), the whole session (first pre..now), what is not
committed (HEAD..now) or the whole branch (merge-base..now). The same photos give "revert to before this message".

Reads run with the same neutralised config as the Git page (`gitsafe.SAFE_GIT`: no hooks, no fsmonitor, no
filters). Writes the user asks for (commit, push) keep the repository's own hooks and filters: they are the
user's repository and the user clicked, exactly as if they had typed the command.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import config
from .gitsafe import SAFE_GIT, EMPTY_TREE, GitError, _filter_overrides

GIT_TIMEOUT = 20
WRITE_TIMEOUT = 120
REF_ROOT = "refs/maxxing"
MAX_FILES = 400                     # files listed per repository and view
MAX_DIFF_LINES = 2000               # lines of one file's diff sent at once ("show everything" lifts it)
KEEP_DAYS = 30                      # photos older than this are deleted by `prune`

# writes keep the repository's hooks (a commit-msg or pre-push hook is the owner's own rule)
_SAFE_W = tuple(a for k, v in zip(SAFE_GIT[::2], SAFE_GIT[1::2]) if not v.startswith("core.hooksPath")
                for a in (k, v))


def _env(extra: dict | None = None) -> dict:
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_PAGER": "cat", "GIT_EXTERNAL_DIFF": "",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_ATTR_SOURCE": EMPTY_TREE, **(extra or {})}


def _run(repo: Path, *args: str, env: dict | None = None, timeout: int = GIT_TIMEOUT, write: bool = False,
         check: bool = True) -> subprocess.CompletedProcess:
    pre = ["git", *(_SAFE_W if write else (*SAFE_GIT, *_filter_overrides(repo))), "-C", str(repo)]
    try:
        r = subprocess.run([*pre, *args], capture_output=True, text=True, timeout=timeout, errors="replace",
                           env=_env(env) if not write else {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})})
    except FileNotFoundError:
        raise GitError(500, "no_git", "git is not installed on this server") from None
    except ValueError:
        raise GitError(400, "bad_argument", "a git argument contains a NUL byte") from None
    except subprocess.TimeoutExpired:
        raise GitError(504, "git_timeout", f"git {args[0]} took more than {timeout} s") from None
    if check and r.returncode != 0:
        msg = (r.stderr.strip() or r.stdout.strip() or "git failed").splitlines()
        raise GitError(400, "git_failed", "\n".join(msg[-6:])[:800])
    return r


def _git(repo: Path, *args: str, **kw) -> str:
    return _run(repo, *args, **kw).stdout


# ---- repositories ---------------------------------------------------------------------------------------------

def _inside_root(p: Path) -> bool:
    root = config.files_root().resolve()
    p = p.resolve()
    return p == root or root in p.parents


def repo_of(path: str | Path) -> Path | None:
    """The repository holding `path` (a file that may not exist yet, or a folder), inside the files root."""
    p = Path(path)
    d = p if p.is_dir() else p.parent
    while not d.exists() and d != d.parent:
        d = d.parent
    try:
        top = subprocess.run(["git", *SAFE_GIT, "-C", str(d), "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, timeout=GIT_TIMEOUT, env=_env(), errors="replace")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if top.returncode != 0 or not top.stdout.strip():
        return None
    root = Path(top.stdout.strip())
    return root if _inside_root(root) else None


def checked_repo(path: str) -> Path:
    """A repository root given by the client: must be a repository's top folder inside the files root."""
    p = Path(path or "").expanduser()
    if not p.is_absolute() or not p.is_dir() or not _inside_root(p):
        raise GitError(404, "repo_not_found", "this folder is not a repository Harness can open")
    root = repo_of(p)
    if root is None or root.resolve() != p.resolve():
        raise GitError(404, "repo_not_found", "this folder is not a repository Harness can open")
    return root


def head_sha(repo: Path) -> str | None:
    return _head(repo)


def _head(repo: Path) -> str | None:
    r = _run(repo, "rev-parse", "--verify", "-q", "HEAD^{commit}", check=False)
    return r.stdout.strip() or None


# ---- photos ---------------------------------------------------------------------------------------------------

def snapshot(repo: Path, ref: str | None = None) -> str:
    """Photograph the working tree; returns a commit sha (kept under `ref` when given)."""
    real_index = Path(_git(repo, "rev-parse", "--git-path", "index").strip())
    if not real_index.is_absolute():
        real_index = repo / real_index
    with tempfile.TemporaryDirectory(prefix="mx-snap-") as tmp:
        idx = Path(tmp) / "index"
        if real_index.exists():
            shutil.copyfile(real_index, idx)       # a copy of the real index: only changed files are hashed again
        env = {"GIT_INDEX_FILE": str(idx)}
        _git(repo, "add", "-A", "--", ".", env=env, timeout=WRITE_TIMEOUT)
        tree = _git(repo, "write-tree", env=env).strip()
    head = _head(repo)
    ident = {"GIT_AUTHOR_NAME": "Harness", "GIT_AUTHOR_EMAIL": "harness@localhost",
             "GIT_COMMITTER_NAME": "Harness", "GIT_COMMITTER_EMAIL": "harness@localhost"}
    sha = _git(repo, "commit-tree", tree, *(["-p", head] if head else []), "-m", "Harness photo", env=ident).strip()
    if ref:
        _git(repo, "update-ref", ref, sha)
    return sha


def _ref(sid: str, n: int, side: str) -> str:
    return f"{REF_ROOT}/{sid[:8]}/{n}/{side}"


def turn_start(sid: str, n: int, repos: list[str]) -> dict[str, str]:
    """Photos before turn `n` of every known repository: {root: sha}. A repository that fails is skipped."""
    out: dict[str, str] = {}
    for r in dict.fromkeys(repos):
        try:
            out[r] = snapshot(Path(r), _ref(sid, n, "pre"))
        except (GitError, OSError):
            continue
    return out


def turn_end(sid: str, n: int, pre: dict[str, str], touched: set[str], cwd: str | None) -> dict | None:
    """Photos after turn `n`, and what the turn changed: `{"n", "repos": [...]}`, or None when nothing changed.
    Repositories first touched during the turn have no photo from before: compared with HEAD (`approx`)."""
    roots = dict.fromkeys(pre)
    for p in touched:
        r = repo_of(p if os.path.isabs(p) or not cwd else os.path.join(cwd, p))
        if r is not None:
            roots.setdefault(str(r), None)
    repos = []
    for root in roots:
        repo = Path(root)
        try:
            post = snapshot(repo, _ref(sid, n, "post"))
            base = pre.get(root)
            approx = base is None
            if base is None:
                base = _head(repo) or EMPTY_TREE
            files = numstat(repo, base, post)
        except (GitError, OSError):
            continue
        if not files:
            continue
        repos.append({**repo_head(repo), "pre": base, "post": post, "approx": approx,
                      "files": files[:MAX_FILES], "more": max(0, len(files) - MAX_FILES),
                      "add": sum(f["add"] for f in files), "del": sum(f["del"] for f in files)})
    return {"n": n, "repos": repos} if repos else None


# ---- reading --------------------------------------------------------------------------------------------------

def numstat(repo: Path, a: str, b: str, paths: list[str] | None = None) -> list[dict]:
    """Files changed between two tree-ish: [{path, old, status, add, del, binary}]."""
    st = _git(repo, "diff", "--no-color", "--no-ext-diff", "-M", "--name-status", "-z", a, b, "--", *(paths or []))
    ns = _git(repo, "diff", "--no-color", "--no-ext-diff", "-M", "--numstat", "-z", a, b, "--", *(paths or []))
    counts: dict[str, tuple[int, int, bool]] = {}
    parts = ns.split("\0")
    i = 0
    while i < len(parts) - 1:
        head = parts[i]
        if not head:
            i += 1
            continue
        fields = head.split("\t")
        if len(fields) == 3 and fields[2] == "":        # rename: the two paths follow
            path = parts[i + 2] if i + 2 < len(parts) else ""
            i += 3
        else:
            path = fields[2] if len(fields) > 2 else ""
            i += 1
        binary = fields[0] == "-"
        counts[path] = (0 if binary else int(fields[0] or 0), 0 if binary else int(fields[1] or 0), binary)
    out: list[dict] = []
    parts = st.split("\0")
    i = 0
    while i < len(parts) - 1:
        code = parts[i]
        if not code:
            i += 1
            continue
        if code[0] in "RC":
            old, path = parts[i + 1], parts[i + 2]
            i += 3
        else:
            old, path = None, parts[i + 1]
            i += 2
        add, dele, binary = counts.get(path, (0, 0, False))
        out.append({"path": path, "old": old, "status": code[0], "add": add, "del": dele, "binary": binary})
    return out


def raw_diff(repo: Path, a: str, b: str) -> str:
    return _git(repo, "diff", "--no-color", "--no-ext-diff", "-M", "--stat", "-p", a, b)


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def diff(repo: Path, a: str, b: str, path: str, old: str | None = None, full: bool = False) -> dict:
    """One file's diff between two tree-ish, as hunks of lines [{t: ' '|'+'|'-', o, n, s}]."""
    raw = _git(repo, "diff", "--no-color", "--no-ext-diff", "-M", "-U3", a, b, "--",
               *([old] if old and old != path else []), path)
    hunks: list[dict] = []
    total = 0
    cut = False
    binary = False
    o = n = 0
    for ln in raw.split("\n"):
        if ln.startswith("Binary files"):
            binary = True
            continue
        m = _HUNK.match(ln)
        if m:
            o, n = int(m.group(1)), int(m.group(3))
            hunks.append({"head": ln, "o": o, "n": n, "lines": []})
            continue
        if not hunks or not ln or ln[0] not in " +-\\":
            continue
        if ln[0] == "\\":
            continue
        if not full and total >= MAX_DIFF_LINES:
            cut = True
            continue
        t, s = ln[0], ln[1:]
        hunks[-1]["lines"].append({"t": t, "o": o if t != "+" else None, "n": n if t != "-" else None, "s": s})
        total += 1
        if t != "+":
            o += 1
        if t != "-":
            n += 1
    return {"path": path, "hunks": hunks, "binary": binary, "cut": cut, "lines": total}


def repo_head(repo: Path) -> dict:
    branch = _run(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
    up = _run(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False).stdout.strip()
    ahead = behind = 0
    if up:
        lr = _run(repo, "rev-list", "--left-right", "--count", f"{up}...HEAD", check=False).stdout.split()
        if len(lr) == 2:
            behind, ahead = int(lr[0]), int(lr[1])
    remote = _run(repo, "remote", "get-url", "origin", check=False).stdout.strip()
    return {"root": str(repo), "name": repo.name, "branch": branch or None, "upstream": up or None,
            "ahead": ahead, "behind": behind, "remote": remote or None}


def dirty(repo: Path) -> int:
    """How many files differ from HEAD (staged, unstaged or untracked): what a commit would take."""
    out = _run(repo, "status", "--porcelain", "-z", "--untracked-files=all", check=False).stdout
    return sum(1 for e in out.split("\0") if len(e) > 3 and e[2] == " ")


def default_base(repo: Path) -> str | None:
    """The branch a feature branch is compared with: origin's HEAD, else main / master / beta that exists."""
    r = _run(repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", check=False).stdout.strip()
    cands = [r] if r else []
    cands += ["origin/main", "origin/master", "main", "master"]
    for c in cands:
        if c and _run(repo, "rev-parse", "--verify", "-q", f"{c}^{{commit}}", check=False).returncode == 0:
            return c
    return None


def view(repo: Path, scope: str, base_sha: str | None = None, base_branch: str | None = None) -> dict:
    """One repository in a view other than a single turn. `scope`: session (from `base_sha`, the session's first
    photo) | uncommitted (HEAD) | branch (merge-base with `base_branch` or the default base)."""
    now = snapshot(repo)
    if scope == "session" and base_sha:
        a = base_sha
    elif scope == "branch":
        b = base_branch or default_base(repo)
        if not b:
            raise GitError(400, "no_base", "no main branch to compare with")
        a = _git(repo, "merge-base", b, "HEAD").strip()
    else:
        a = _head(repo) or EMPTY_TREE
    files = numstat(repo, a, now)
    return {**repo_head(repo), "pre": a, "post": now, "approx": False, "files": files[:MAX_FILES],
            "more": max(0, len(files) - MAX_FILES), "add": sum(f["add"] for f in files),
            "del": sum(f["del"] for f in files)}


def commits(repo: Path, base_branch: str | None = None, limit: int = 100, everything: bool = False) -> list[dict]:
    """Commits of HEAD not in `base_branch` (the default base when None); `everything`: the last ones of HEAD."""
    b = None if everything else (base_branch or default_base(repo))
    rng = [f"{b}..HEAD"] if b else ["HEAD"]
    out = _git(repo, "log", f"-n{limit}", "--format=%H%x1f%h%x1f%s%x1f%an%x1f%at", *rng, check=False) \
        if _head(repo) else ""
    res = []
    for ln in out.splitlines():
        f = ln.split("\x1f")
        if len(f) == 5:
            res.append({"sha": f[0], "short": f[1], "subject": f[2], "author": f[3], "at": int(f[4] or 0)})
    return res


# ---- writing --------------------------------------------------------------------------------------------------

def _safe_paths(repo: Path, paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        q = (repo / p).resolve()
        if p.startswith("/") or ".." in Path(p).parts or (q != repo.resolve() and repo.resolve() not in q.parents):
            raise GitError(400, "bad_path", f"not a file of this repository: {p}")
        out.append(p)
    return out


def restore(repo: Path, source: str, paths: list[str] | None = None) -> dict:
    """Put files back as they are in `source` (a photo or commit): the given paths, or every file that differs.
    A photo of the current state is taken first, so `restore(repo, undo)` puts everything back."""
    undo = snapshot(repo, f"{REF_ROOT}/undo/{int(time.time() * 1000)}")
    changed = numstat(repo, source, undo, _safe_paths(repo, paths) if paths else None)
    restored, removed = [], []
    for f in changed:
        if f["status"] == "A":                       # absent from the source: the file goes away
            target = repo / f["path"]
            if target.is_file() or target.is_symlink():
                target.unlink()
                removed.append(f["path"])
        else:
            if f["status"] == "R" and f.get("old"):
                old = repo / f["path"]
                if old.exists():
                    old.unlink()
                restored.append(f["old"])
            else:
                restored.append(f["path"])
    if restored:
        _git(repo, "restore", f"--source={source}", "--worktree", "--", *restored, timeout=WRITE_TIMEOUT)
    return {"undo": undo, "restored": restored, "removed": removed}


def commit(repo: Path, message: str, paths: list[str] | None = None) -> dict:
    message = (message or "").strip()
    if not message:
        raise GitError(400, "no_message", "a commit message is needed")
    if paths:
        _git(repo, "add", "-A", "--", *_safe_paths(repo, paths), write=True, timeout=WRITE_TIMEOUT)
    else:
        _git(repo, "add", "-A", write=True, timeout=WRITE_TIMEOUT)
    _git(repo, "commit", "-m", message, write=True, timeout=WRITE_TIMEOUT)
    return {"sha": _git(repo, "rev-parse", "HEAD").strip(), **repo_head(repo)}


def push(repo: Path) -> dict:
    head = repo_head(repo)
    if not head["branch"]:
        raise GitError(400, "detached", "not on a branch: create a branch first")
    if head["upstream"]:
        _git(repo, "push", write=True, timeout=WRITE_TIMEOUT)
    else:
        _git(repo, "push", "-u", "origin", f"HEAD:refs/heads/{head['branch']}", write=True, timeout=WRITE_TIMEOUT)
    return repo_head(repo)


def new_branch(repo: Path, name: str) -> dict:
    name = (name or "").strip()
    if _run(repo, "check-ref-format", "--branch", name, check=False).returncode != 0:
        raise GitError(400, "bad_branch", "this is not a valid branch name")
    _git(repo, "switch", "-c", name, write=True)
    return repo_head(repo)


def prune(keep_days: int = KEEP_DAYS, live: set[str] | None = None) -> int:
    """Delete photos older than `keep_days`, or of sessions no longer in `live` (8-char prefixes)."""
    from .gitview import local_repos
    cutoff = time.time() - keep_days * 86400
    gone = 0
    for r in local_repos():
        repo = Path(r.get("path") or r.get("root") or "")
        if not repo.is_dir():
            continue
        out = _run(repo, "for-each-ref", "--format=%(refname) %(creatordate:unix)", REF_ROOT, check=False).stdout
        for ln in out.splitlines():
            ref, _, when = ln.rpartition(" ")
            parts = ref.split("/")
            old = int(when or 0) < cutoff
            dead = live is not None and len(parts) > 2 and parts[2] != "undo" and parts[2] not in live
            if old or dead:
                _run(repo, "update-ref", "-d", ref, check=False)
                gone += 1
    return gone
