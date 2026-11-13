"""Separate copies (git worktrees) for the sessions of Code mode.

A session started "on a separate copy" works in its own folder and on its own branch: two sessions on the same
repository never step on each other. The copy is a `git worktree` of the topic's clone, in a visible `worktrees/`
folder of the topic (`.worktrees/` when the topic folder is itself inside the repository, so that the
repository's own tools - tests, linters, bundlers - do not walk into it). Its branch is `<prefix>/<title>`
(prefix `session` by default, per repository), renamed after the session's short title as long as nothing was
pushed. The session's cwd is the copy: Claude Code still loads the CLAUDE.md / memory.md of the topic, the
project and the workspace (they are above it) and the repository's own CLAUDE.md (inside it).

The end of a copy: a pull request (GitHub repositories), a local merge into its base (any repository), or
"discard". Merging happens in the copy first (the base is merged into the branch, a conflict is left to the user
or Claude there), then the base only moves forward. Never for agents (like the terminal).

Meta of a session: `worktree = {path, repo, branch, base, created, named, port, prepare?, included?, removed?}`.
Per-repository preferences (`prefix`, `prepare`, `copy_env`) in `<state>/worktrees.json`. A `.worktreeinclude` at
the root of the repository (gitignore syntax, as in Claude Code) names the ignored files every new copy gets.
Each copy owns a block of PORT_BLOCK ports from `port` (`MAXXING_PORT` for its turns and its preparation), so that
the dev servers of two copies never fight for 3000.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import unicodedata
from pathlib import Path

from . import codediff, config, workspace
from .gitsafe import GitError

log = logging.getLogger("maxxing.worktrees")

DIR, HIDDEN = "worktrees", ".worktrees"
DEFAULT_PREFIX = "session"
SLUG_MAX = 40
PREPARE_TIMEOUT = 15 * 60
SCAN_DEPTH = 2                       # repositories looked for under a topic folder (topic/repo, topic/x/repo)
SKIP = {"node_modules", "__pycache__", "venv", ".venv", "dist", "build", "attachments", DIR, HIDDEN}
ENV_MAX = 20                         # .env files copied at most
INCLUDE = ".worktreeinclude"
INCLUDE_MAX, INCLUDE_BYTES = 500, 200 * 1024 * 1024   # files named by .worktreeinclude: at most
PORT_START, PORT_BLOCK, PORT_SLOTS = 4100, 10, 80   # copy n gets 4100 + 10 n ... + 9
_lock = threading.Lock()


def enabled() -> bool:
    return bool(config.load_config().get("code_mode", False))


def _need_enabled() -> None:
    if not enabled():
        raise GitError(403, "code_mode_off", "separate copies need Code mode (Settings -> Features -> Sessions)")


# ---- per-repository preferences -------------------------------------------------------------------------------

def _prefs_file() -> Path:
    return config.state_dir() / "worktrees.json"


def _all_prefs() -> dict:
    try:
        d = json.loads(_prefs_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def prefs(repo: Path | str) -> dict:
    p = _all_prefs().get(str(repo)) or {}
    prefix = str(p.get("prefix") if p.get("prefix") is not None else DEFAULT_PREFIX).strip().strip("/")
    return {"prefix": prefix, "prepare": str(p.get("prepare") or ""), "copy_env": bool(p.get("copy_env"))}


def set_prefs(repo: Path | str, **kw) -> dict:
    with _lock:
        d = _all_prefs()
        cur = d.get(str(repo)) or {}
        for k in ("prefix", "prepare", "copy_env"):
            if kw.get(k) is not None:
                cur[k] = kw[k]
        d[str(repo)] = cur
        f = _prefs_file()
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=2))
        os.replace(tmp, f)
    return prefs(repo)


def check_prefix(prefix: str) -> str:
    prefix = (prefix or "").strip().strip("/")
    if prefix and (not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", prefix) or ".." in prefix
                   or len(prefix) > 40):
        raise GitError(400, "bad_prefix", "a prefix is letters, digits, '.', '_', '-' and '/' (like session or feat)")
    return prefix


# ---- names ----------------------------------------------------------------------------------------------------

def slug(text: str) -> str:
    """"Fix the login page!" -> "fix-the-login-page" (ASCII, at most SLUG_MAX characters, cut on a dash)."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    if len(t) > SLUG_MAX:
        t = t[:SLUG_MAX].rsplit("-", 1)[0] if "-" in t[:SLUG_MAX] else t[:SLUG_MAX]
    return t.strip("-")


def _branch_exists(repo: Path, name: str) -> bool:
    return codediff._run(repo, "rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False).returncode == 0


def _valid_branch(repo: Path, name: str) -> bool:
    return codediff._run(repo, "check-ref-format", "--branch", name, check=False).returncode == 0


def _free_branch(repo: Path, prefix: str, base_name: str, keep: str | None = None) -> str:
    stem = f"{prefix}/{base_name}" if prefix else base_name
    name, i = stem, 2
    while name != keep and _branch_exists(repo, name):
        name, i = f"{stem}-{i}", i + 1
    return name


# ---- where -------------------------------------------------------------------------------------------------

def main_clone(repo: Path) -> Path:
    """The main folder of a repository (a worktree gives its clone)."""
    common = codediff._git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    p = Path(common)
    return p.parent if p.name == ".git" else repo


def _is_clone(d: Path) -> bool:
    return (d / ".git").is_dir()


def repos_for(topic_path: str) -> list[dict]:
    """The repositories a session of this topic can copy: the one holding the topic folder, else the clones in
    it (depth <= SCAN_DEPTH). Each with its branches and preferences."""
    try:
        tdir = workspace.topic_dir(topic_path)
    except ValueError:
        raise GitError(404, "no_topic", "no such topic") from None
    found: list[Path] = []
    holder = codediff.repo_of(tdir)
    if holder is not None:
        found.append(main_clone(holder))
    else:
        def walk(d: Path, depth: int) -> None:
            try:
                kids = sorted(x for x in d.iterdir() if x.is_dir() and not x.is_symlink())
            except OSError:
                return
            for k in kids:
                if k.name in SKIP or k.name.startswith("."):
                    continue
                if _is_clone(k):
                    found.append(k)
                elif depth < SCAN_DEPTH:
                    walk(k, depth + 1)
        walk(tdir, 1)
    out = []
    for r in found[:20]:
        try:
            out.append(describe(r))
        except GitError as e:
            out.append({"root": str(r), "name": r.name, "error": e.message})
    return out


def describe(repo: Path) -> dict:
    head = codediff.repo_head(repo)
    refs = codediff._git(repo, "for-each-ref", "--sort=-committerdate", "--count=60", "--format=%(refname:short)",
                         "refs/heads", check=False).split()
    base = codediff.default_base(repo)
    from .gitview import github_name
    return {"root": str(repo), "name": repo.name, "branch": head["branch"], "branches": refs,
            "default_base": base, "github": github_name(head["remote"] or "") if head.get("remote") else None,
            **{"prefs": prefs(repo)}}


def place(topic: Path, repo: Path) -> Path:
    """The folder that holds the copies of `repo` made from `topic`."""
    t, r = topic.resolve(), repo.resolve()
    inside = t == r or r in t.parents
    return t / (HIDDEN if inside else DIR)


def _exclude(holder: Path, folder: Path) -> None:
    """Keep the copies folder out of `git status` of the repository that holds it (never its .gitignore)."""
    try:
        rel = folder.resolve().relative_to(holder.resolve())
    except ValueError:
        return
    info = Path(codediff._git(holder, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()) / "info"
    line = f"/{rel.as_posix()}/"
    f = info / "exclude"
    try:
        text = f.read_text() if f.exists() else ""
        if line not in text.splitlines():
            info.mkdir(parents=True, exist_ok=True)
            f.write_text(text + ("" if not text or text.endswith("\n") else "\n") + line + "\n")
    except OSError:
        log.warning("could not write %s", f)


# ---- creating ------------------------------------------------------------------------------------------------

def create(topic_path: str, repo: str, base: str | None, title: str, sid: str, *, pr: dict | None = None,
           prepare: str | None = None, copy_env: bool | None = None) -> dict:
    """A new copy of `repo` for session `sid`, on a new branch from `base` (default: the default base, else the
    current branch). `pr` = {number, ref, fork} to work on a pull request's branch instead."""
    _need_enabled()
    tdir = workspace.topic_dir(topic_path)
    r = main_clone(codediff.checked_repo(repo))
    if not any(Path(x["root"]) == r for x in repos_for(topic_path)):
        raise GitError(400, "not_here", "this repository is not in the session's topic")
    p = prefs(r)
    folder_root = place(tdir, r)
    holder = codediff.repo_of(folder_root.parent)
    stem = slug(title) or sid[:8]
    folder, i = folder_root / stem, 2
    while folder.exists():
        folder, i = folder_root / f"{stem}-{i}", i + 1
    folder_root.mkdir(parents=True, exist_ok=True)
    if holder is not None:
        _exclude(holder, folder_root)
    if pr:
        branch, start, track = _pr_branch(r, pr)
        codediff._git(r, "worktree", "add", str(folder), branch, write=True, timeout=codediff.WRITE_TIMEOUT)
        if track:
            codediff._run(folder, "branch", f"--set-upstream-to={track}", check=False, write=True)
        base_name = pr.get("base") or ""
    else:
        base_name = (base or "").strip() or codediff.default_base(r) or codediff.repo_head(r)["branch"] or "HEAD"
        if codediff._run(r, "rev-parse", "--verify", "-q", f"{base_name}^{{commit}}", check=False).returncode != 0:
            raise GitError(400, "bad_base", f"no branch or commit named {base_name}")
        branch = _free_branch(r, p["prefix"], stem)
        if not _valid_branch(r, branch):
            branch = _free_branch(r, p["prefix"], sid[:8])
        codediff._git(r, "worktree", "add", "--no-track", "-b", branch, str(folder), base_name, write=True,
                      timeout=codediff.WRITE_TIMEOUT)
    wt = {"path": str(folder), "repo": str(r), "branch": branch, "base": base_name.removeprefix("origin/"),
          "base_ref": base_name, "created": time.time(), "named": bool(pr)}
    if pr:
        wt["pr"] = {k: pr.get(k) for k in ("number", "url", "fork", "full") if pr.get(k) is not None}
    # a pull request from a fork or from someone outside the repository: its code is read before anything of it
    # runs, so no prepare command (`npm ci` runs its scripts) and none of the clone's ignored files (.env...)
    untrusted = bool(pr and (pr.get("fork") or pr.get("outside")))
    try:
        if not untrusted and (copy_env if copy_env is not None else p["copy_env"]):
            wt["env_copied"] = _copy_env(r, folder)
        included = [] if untrusted else _copy_included(r, folder)
        if included:
            wt["included"] = len(included)
        with _lock:
            wt["port"] = _free_ports(sid)
    except BaseException:
        undo(sid, wt)
        raise
    cmd = "" if untrusted else (prepare if prepare is not None else p["prepare"]).strip()
    if cmd:
        wt["prepare"] = {"cmd": cmd, "state": "running", "started": time.time()}
        threading.Thread(target=_prepare, args=(sid, folder, cmd, copy_env_vars(wt)), name=f"wt-prep-{sid[:8]}",
                         daemon=True).start()
    return wt


def undo(sid: str, wt: dict) -> None:
    """A copy whose session could not be made: its folder goes, and its branch unless it is a pull request's."""
    try:
        remove({"id": sid, "worktree": wt}, force=True)
    except Exception:  # noqa: BLE001 - best effort: the error that brought us here is the one to report
        log.warning("copy %s of %s not cleaned up", wt.get("path"), sid[:8])


def _pr_branch(repo: Path, pr: dict) -> tuple[str, str, str | None]:
    """Fetch a pull request's head into a local branch. Same repository: the branch itself (tracking origin);
    a fork: `pr/<n>` from refs/pull/<n>/head (pushing back is not possible)."""
    n = int(pr["number"])
    if pr.get("fork") or not pr.get("ref"):
        local = f"pr/{n}"
        codediff._git(repo, "fetch", "origin", f"+refs/pull/{n}/head:refs/heads/{local}", write=True,
                      timeout=codediff.WRITE_TIMEOUT)
        return local, local, None
    ref = str(pr["ref"])
    if not _valid_branch(repo, ref):
        raise GitError(400, "bad_branch", "the pull request's branch name is not valid here")
    codediff._git(repo, "fetch", "origin", f"+refs/heads/{ref}:refs/remotes/origin/{ref}", write=True,
                  timeout=codediff.WRITE_TIMEOUT)
    if _branch_exists(repo, ref):
        used = codediff._git(repo, "worktree", "list", "--porcelain", check=False)
        if f"branch refs/heads/{ref}\n" in used + "\n":
            raise GitError(409, "branch_in_use", f"the branch {ref} is already open in another folder")
        # only moved forward: a local branch with commits of its own is never reset
        if codediff._run(repo, "merge-base", "--is-ancestor", ref, f"origin/{ref}", check=False).returncode == 0:
            codediff._run(repo, "branch", "-f", ref, f"origin/{ref}", check=False, write=True)
    else:
        codediff._git(repo, "branch", ref, f"origin/{ref}", write=True)
    return ref, ref, f"origin/{ref}"


def _copy_env(repo: Path, folder: Path) -> list[str]:
    """Copy the ignored `.env*` files of the clone (depth <= 3) to the same place in the copy."""
    out = codediff._run(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z",
                        check=False).stdout
    done: list[str] = []
    for rel in out.split("\0"):
        name = rel.rstrip("/").rsplit("/", 1)[-1]
        if not rel or rel.endswith("/") or not name.startswith(".env") or rel.count("/") > 3:
            continue
        src, dst = repo / rel, folder / rel
        if src.is_file() and not src.is_symlink() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            done.append(rel)
        if len(done) >= ENV_MAX:
            break
    return done


def _copy_included(repo: Path, folder: Path) -> list[str]:
    """The ignored files named by the repository's `.worktreeinclude` (gitignore syntax), copied to the same place
    in the copy. Only files git ignores (a tracked file is in the copy already), never a link, capped."""
    spec = repo / INCLUDE
    if not spec.is_file() or spec.is_symlink():
        return []
    try:
        listed = codediff._run(repo, "ls-files", "--others", "--ignored", f"--exclude-from={spec}", "-z",
                               check=False, timeout=30).stdout.split("\0")
    except GitError as e:
        log.info("%s not read: %s", spec, e.message)
        return []
    listed = [x for x in listed if x and not x.endswith("/")][:INCLUDE_MAX * 4]
    ignored: list[str] = []
    for i in range(0, len(listed), 200):              # only what git ignores
        out = codediff._run(repo, "check-ignore", "--", *listed[i:i + 200], check=False).stdout
        ignored += [x for x in out.splitlines() if x]
    done: list[str] = []
    size = 0
    for rel in ignored:
        src, dst = repo / rel, folder / rel
        try:
            if not src.is_file() or src.is_symlink() or dst.exists() or folder.resolve() not in dst.resolve().parents:
                continue
            size += src.stat().st_size
            if size > INCLUDE_BYTES or len(done) >= INCLUDE_MAX:
                log.info("%s: copy limit reached, %d files copied", spec, len(done))
                break
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            done.append(rel)
        except OSError as e:
            log.info("%s not copied: %s", rel, e)
    return done


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.05)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _free_ports(sid: str) -> int:
    """The first port of a block no other live copy owns and nothing listens on (0 when all are taken)."""
    from .sessions import store
    used = set()
    for other in store.list_ids():
        if other == sid:
            continue
        w = (store.read_cached(other) or {}).get("worktree")
        if isinstance(w, dict) and not w.get("removed") and isinstance(w.get("port"), int):
            used.add(w["port"])
    for i in range(PORT_SLOTS):
        first = PORT_START + i * PORT_BLOCK
        if first not in used and not any(_listening(first + k) for k in range(PORT_BLOCK)):
            return first
    return 0


def copy_env_vars(wt: dict) -> dict[str, str]:
    """What the turns and the preparation command of a copy get: its folder and its ports."""
    out = {"MAXXING_COPY_PATH": str(wt.get("path") or "")}
    if wt.get("port"):
        out["MAXXING_PORT"] = str(wt["port"])
    return out


def prepare_log(sid: str) -> Path:
    return config.state_dir("worktrees") / f"{sid[:8]}.log"


def _prepare(sid: str, folder: Path, cmd: str, env: dict[str, str] | None = None) -> None:
    """Run the repository's preparation command (`npm ci`, `uv sync`...) once in the new copy, logged."""
    from .sessions import store
    for _ in range(100):                     # the session's meta is written right after the copy is made
        if store.read(sid) is not None:
            break
        time.sleep(0.1)
    state = "failed"
    try:
        with open(prepare_log(sid), "w") as out:
            out.write(f"$ {cmd}\n")
            out.flush()
            p = subprocess.run(["/bin/sh", "-c", cmd], cwd=folder, stdout=out, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, timeout=PREPARE_TIMEOUT, env={**os.environ, **(env or {})})
            state = "done" if p.returncode == 0 else "failed"
            out.write(f"\n[exit {p.returncode}]\n")
    except subprocess.TimeoutExpired:
        log.info("preparation of %s timed out", folder)
    except OSError as e:
        log.info("preparation of %s failed: %s", folder, e)
    try:
        with store.edit(sid) as m:
            wt = m.get("worktree")
            if isinstance(wt, dict) and isinstance(wt.get("prepare"), dict):
                wt["prepare"] = {**wt["prepare"], "state": state, "ended": time.time()}
                m["worktree"] = wt
    except KeyError:
        return
    from . import bus
    bus.invalidate("sessions")


# ---- following the session ------------------------------------------------------------------------------------

def live(meta: dict) -> dict | None:
    wt = meta.get("worktree")
    if not isinstance(wt, dict) or wt.get("removed"):
        return None
    return wt if Path(str(wt.get("path") or "")).is_dir() else None


def cwd_of(meta: dict) -> str | None:
    """The folder a session's turns run in when it has a copy (inside the files root), else None."""
    wt = live(meta)
    if not wt:
        return None
    p = Path(wt["path"]).resolve()
    return str(p) if codediff._inside_root(p) else None


def rename_for_title(sid: str, title: str) -> str | None:
    """The session got its title: its branch follows (`<prefix>/<slug>`), unless it was pushed or came from a
    pull request. Returns the new branch, or None."""
    from .sessions import store
    m = store.read(sid) or {}
    wt = live(m)
    if not wt or wt.get("pr") or not slug(title):
        return None
    folder = Path(wt["path"])
    try:
        head = codediff.repo_head(folder)
        if head["upstream"] or head["branch"] != wt["branch"] or codediff._run(
                folder, "ls-remote", "--exit-code", "--heads", "origin", wt["branch"], check=False,
                timeout=10).returncode == 0:
            return None
        r = Path(wt["repo"])
        new = _free_branch(r, prefs(r)["prefix"], slug(title), keep=wt["branch"])
        if new == wt["branch"] or not _valid_branch(r, new):
            return None
        codediff._git(folder, "branch", "-m", wt["branch"], new, write=True)
    except GitError as e:
        log.info("branch of %s not renamed: %s", sid, e.message)
        return None
    with store.edit(sid) as mm:
        w = mm.get("worktree") or {}
        if w.get("branch") == wt["branch"]:
            mm["worktree"] = {**w, "branch": new, "named": True}
    return new


def status(meta: dict) -> dict:
    """What the session bar shows: branch, base, commits ahead / behind the base, uncommitted files, upstream,
    the GitHub repository (and pull request) when there is one."""
    wt = meta.get("worktree")
    if not isinstance(wt, dict):
        raise GitError(404, "no_copy", "this session has no separate copy")
    keys = ("path", "repo", "branch", "base", "pr", "prepare", "env_copied", "included", "port", "created")
    from .prwatch import watching
    out = {**{k: wt.get(k) for k in keys}, "watch": watching(wt),
           "exists": False, "removed": bool(wt.get("removed"))}
    folder = Path(str(wt.get("path") or ""))
    if wt.get("removed") or not folder.is_dir():
        return out
    head = codediff.repo_head(folder)
    base_ref = wt.get("base_ref") or wt.get("base") or ""
    ahead = behind = 0
    if base_ref:
        lr = codediff._run(folder, "rev-list", "--left-right", "--count", f"{base_ref}...HEAD", check=False).stdout.split()
        if len(lr) == 2:
            behind, ahead = int(lr[0]), int(lr[1])
    from .gitview import github_name
    full = github_name(head["remote"] or "") if head.get("remote") else None
    out.update(exists=True, branch=head["branch"] or wt.get("branch"), ahead=ahead, behind=behind,
               dirty=codediff.dirty(folder), upstream=head["upstream"], pushed_ahead=head["ahead"],
               github=full, fork=bool((wt.get("pr") or {}).get("fork")))
    return out


def _clean_or_raise(folder: Path) -> None:
    if codediff.dirty(folder):
        raise GitError(409, "uncommitted", "commit or discard the changes of the copy first")


def merge(meta: dict) -> dict:
    """Merge the copy's branch into its base, locally. The base is merged into the branch first, in the copy (a
    conflict: aborted, the copy stays as it was); then the base moves forward to the branch (fast-forward only:
    the main folder never gets a merge commit or a conflict). The copy is removed afterwards."""
    _need_enabled()
    wt = live(meta)
    if not wt:
        raise GitError(404, "no_copy", "this session has no separate copy")
    if wt.get("pr"):
        raise GitError(400, "is_pr", "this copy works on a pull request: merge the pull request instead")
    folder, repo = Path(wt["path"]), Path(wt["repo"])
    base = wt.get("base") or ""
    if not base or not _branch_exists(repo, base):
        raise GitError(400, "no_local_base", f"no local branch {base or '?'} to merge into")
    _clean_or_raise(folder)
    if codediff._run(folder, "merge-base", "--is-ancestor", base, "HEAD", check=False).returncode != 0:
        r = codediff._run(folder, "merge", "--no-edit", base, write=True, check=False, timeout=codediff.WRITE_TIMEOUT)
        if r.returncode != 0:
            codediff._run(folder, "merge", "--abort", write=True, check=False)
            raise GitError(409, "conflict", f"{base} changed the same lines: ask Claude to merge {base} into this "
                                            "copy and settle the conflicts, then merge again")
    sha = codediff._git(folder, "rev-parse", "HEAD").strip()
    where = _checked_out(repo, base)
    if where is not None:
        r = codediff._run(where, "merge", "--ff-only", sha, write=True, check=False, timeout=codediff.WRITE_TIMEOUT)
        if r.returncode != 0:
            raise GitError(409, "base_busy", f"{where.name}: {base} has changes that the merge would overwrite - "
                                             "commit or put them aside there first")
    else:
        codediff._git(repo, "update-ref", f"refs/heads/{base}", sha, write=True)
    gone = remove(meta, force=False, delete_branch=True)
    return {"merged": True, "base": base, "sha": sha, **gone}


def _checked_out(repo: Path, branch: str) -> Path | None:
    """The folder (main clone or another worktree) where `branch` is checked out, if any."""
    out = codediff._git(repo, "worktree", "list", "--porcelain", check=False)
    cur = None
    for ln in out.splitlines():
        if ln.startswith("worktree "):
            cur = Path(ln[9:])
        elif ln == f"branch refs/heads/{branch}" and cur is not None:
            return cur
    return None


def remove(meta: dict, force: bool = False, delete_branch: bool = True, merged_sha: str | None = None) -> dict:
    """Remove the copy's folder (refused with uncommitted changes unless `force`). The branch goes too when it is
    merged into the base, has nothing of its own, its tip is in `merged_sha` (the head of its pull request, merged
    on GitHub - squash and rebase merges included), or `force` (discard); else it is kept and named."""
    wt = meta.get("worktree")
    if not isinstance(wt, dict) or wt.get("removed"):
        raise GitError(404, "no_copy", "this session has no separate copy")
    folder, repo = Path(str(wt.get("path") or "")), Path(str(wt.get("repo") or ""))
    branch = wt.get("branch") or ""
    if folder.is_dir():
        if not force:
            _clean_or_raise(folder)
        try:
            branch = codediff.repo_head(folder)["branch"] or branch
        except GitError:
            pass
        codediff._git(repo, "worktree", "remove", *(["--force"] if force else []), str(folder), write=True,
                      timeout=codediff.WRITE_TIMEOUT)
    codediff._run(repo, "worktree", "prune", check=False, write=True)
    kept = None
    if branch and delete_branch and _branch_exists(repo, branch) and (not wt.get("pr") or merged_sha):
        bases = {b for b in (wt.get("base"), wt.get("base_ref")) if b}     # main, or origin/main
        merged = any(codediff._run(repo, "merge-base", "--is-ancestor", branch, b, check=False).returncode == 0
                     for b in [*bases, *([merged_sha] if merged_sha else [])])
        if merged or force:
            codediff._run(repo, "branch", "-D", branch, check=False, write=True)
        else:
            kept = branch
    elif branch and _branch_exists(repo, branch):
        kept = branch
    from .sessions import store
    try:
        with store.edit(meta["id"]) as m:
            w = m.get("worktree") or {}
            m["worktree"] = {**w, "removed": time.time(), "kept_branch": kept}
    except KeyError:
        pass
    _follow_transcript(meta, folder)
    return {"removed": True, "kept_branch": kept}


def _follow_transcript(meta: dict, folder: Path) -> None:
    """The session goes back to its topic folder: its Claude conversation follows (`--resume` by cwd)."""
    from .sessions import service
    try:
        service._move_transcript(meta.get("csid") or meta["id"], folder, workspace.root() / (meta.get("path") or ""))
    except Exception:  # noqa: BLE001 - best effort: the runner starts a new thread otherwise
        log.info("transcript of %s not moved", meta.get("id"))


def on_delete(meta: dict) -> None:
    """A session goes to the trash: its copy goes too when nothing would be lost (no file left, no commit of its own
    that is not in its base or pushed). Otherwise it stays, listed on the Git page while the session is restorable."""
    wt = live(meta)
    if not wt:
        return
    try:
        st = status(meta)
        if st.get("dirty") or (st.get("ahead") and (not st.get("upstream") or st.get("pushed_ahead"))):
            return
        remove(meta, force=False, delete_branch=True)
    except (GitError, KeyError) as e:
        log.info("copy of %s kept: %s", meta.get("id"), getattr(e, "message", e))


def listing() -> list[dict]:
    """Every session copy still on disk (the Git page's "Separate copies")."""
    from .sessions import store
    out = []
    for sid in store.list_ids():
        m = store.read_cached(sid) or {}
        wt = live(m)
        if not wt:
            continue
        try:
            st = status(m)
        except GitError:
            continue
        out.append({"sid": m["id"], "title": m.get("title") or "", "path": m.get("path") or "",
                    "archived": bool(m.get("archived")), **st})
    return out
