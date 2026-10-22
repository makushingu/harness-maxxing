"""Customizations of the product code - recorded, so updates carry them over.

The install directory (config.CODE) is a git clone of the product. A *customization* is a local
commit on top of the upstream branch, made with `maxxing custom save "<title>" --why "<reason>"`:

    upstream (origin/main) --- A --- B --- C          <- product commits
                                            \\
                                             X --- Y  <- customizations (HEAD)

Git is the source of truth. After every change the workspace gets a readable copy, so Claude (and
the memory backup) always knows what was customized and why:

    <workspace>/CUSTOMIZATIONS.md             one section per customization (title, why, files)
    <workspace>/customizations/NNNN-*.patch   `git format-patch` export (restore on a new server)

`maxxing update` rebases the customizations onto the new version (see cmd_core.cmd_update): no
conflict -> done; conflict -> nothing changes and the topic system/harness lets Claude adapt them.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import secrets as _secrets
import subprocess
from pathlib import Path
from typing import Any

from . import config

IDENT = ["-c", "user.name=Harness Maxxing", "-c", "user.email=customizations@localhost"]
PREFIX = "custom: "
REGISTRY = "CUSTOMIZATIONS.md"
PATCH_DIR = "customizations"
PENDING = "update/pending.json"
PRE_UPDATE_REF = "refs/maxxing/pre-update"


class CustomError(Exception):
    pass


# ---- git -----------------------------------------------------------------------------------
def git(*args: str, timeout: float = 120, check: bool = False) -> tuple[int, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "GIT_PAGER": "cat"}
    try:
        r = subprocess.run(["git", *IDENT, "-C", str(config.CODE), *args], capture_output=True, text=True,
                           timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        if check:
            raise CustomError(f"git {args[0]}: {e}") from None
        return 1, str(e)
    out = (r.stdout or "") + (r.stderr or "")
    if check and r.returncode != 0:
        raise CustomError(f"git {' '.join(args[:2])} failed: {out.strip()[-400:]}")
    return r.returncode, out


def ensure_identity() -> None:
    """Commits (customizations, rebases finished by hand) need an identity and, without a terminal, an
    editor that keeps the message as is (`git rebase --continue`): set both in this clone."""
    for key, val in (("user.name", "Harness Maxxing"), ("user.email", "customizations@localhost"),
                     ("core.editor", "true")):
        code, out = git("config", "--local", "--get", key)
        if code != 0 or not out.strip():
            git("config", "--local", key, val)


def is_git() -> bool:
    return (config.CODE / ".git").exists()


def upstream(branch: str | None = None) -> str:
    """The remote branch customizations sit on (origin/<current branch>)."""
    if branch is None:
        code, out = git("rev-parse", "--abbrev-ref", "HEAD")
        branch = out.strip() if code == 0 and out.strip() not in ("", "HEAD") else "main"
    return f"origin/{branch}"


def _base(branch: str | None = None) -> str | None:
    code, out = git("merge-base", "HEAD", upstream(branch))
    return out.strip() if code == 0 and out.strip() else None


def dirty_files() -> list[str]:
    """Uncommitted changes in the code directory (tracked or new, ignored files excluded).

    `-z` keeps paths raw: without it git quotes a path with a space or an accent ("web/caf\\303\\251.js"), which
    no longer starts with web/. A rename or copy lists both paths."""
    code, out = git("status", "--porcelain", "-z", "--untracked-files=all")
    if code != 0:
        return []
    files, parts = [], out.split("\0")[:-1]           # what follows the last NUL is git's stderr, if any
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        files.append(entry[3:])
        if entry[0] in "RC" and i < len(parts):            # the original path follows in its own field
            files.append(parts[i])
            i += 1
    return files


def _trailers(body: str) -> dict[str, str]:
    out = {}
    for ln in body.splitlines():
        m = re.match(r"^(Custom-Id|Why|Saved|Check):\s*(.*)$", ln.strip())
        if m:
            out[m.group(1).lower().replace("-", "_")] = m.group(2).strip()
    return out


def list_customs(branch: str | None = None) -> list[dict[str, Any]]:
    """Local commits on top of upstream, oldest first -> [{id, title, why, saved, commit, files}]."""
    if not is_git():
        return []
    base = _base(branch)
    if not base:
        return []
    code, out = git("log", "--reverse", "--format=%H%x1f%s%x1f%b%x1e", f"{base}..HEAD")
    if code != 0:
        return []
    overrides = check_overrides()
    items = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        sha, subject, body = (rec.split("\x1f") + ["", ""])[:3]
        t = _trailers(body)
        _, files = git("diff-tree", "--no-commit-id", "--name-only", "-r", sha)
        cid = t.get("custom_id") or sha[:8]
        items.append({"id": cid, "title": subject.removeprefix(PREFIX).strip(),
                      "why": t.get("why", ""), "saved": t.get("saved", ""), "commit": sha,
                      "check": overrides.get(cid, t.get("check", "")),
                      "files": [f for f in files.splitlines() if f.strip()]})
    return items


# ---- checks: a command proving a customization still works (run by `maxxing update --verify`) --------
CHECKS = "checks.json"


def _checks_path() -> Path:
    return _workspace() / PATCH_DIR / CHECKS


def check_overrides() -> dict[str, str]:
    """Checks set after saving (`maxxing custom check`): <workspace>/customizations/checks.json wins over the
    commit's Check trailer."""
    try:
        d = json.loads(_checks_path().read_text())
    except (OSError, ValueError, KeyError):
        return {}
    return {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}


def set_check(cid: str, command: str) -> dict[str, Any]:
    _find(cid)
    d = check_overrides()
    command = " ".join((command or "").split())
    if command:
        d[cid] = command
    else:
        d.pop(cid, None)
    p = _checks_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    config.write_json(p, d)
    return export()


# ---- registry (workspace copy) -------------------------------------------------------------
def _workspace() -> Path:
    return Path(config.load_config()["workspace"])


def export(branch: str | None = None) -> dict[str, Any]:
    """Rewrite CUSTOMIZATIONS.md and customizations/*.patch from git. Returns the list."""
    items = list_customs(branch)
    ws = _workspace()
    if not ws.is_dir():                                  # no workspace yet: git keeps everything anyway
        return {"customs": items, "registry": None}
    pdir = ws / PATCH_DIR
    if pdir.is_dir():
        for p in pdir.glob("*.patch"):
            p.unlink()
    if items:
        pdir.mkdir(parents=True, exist_ok=True)
        base = _base(branch)
        git("format-patch", "-q", "--zero-commit", "--no-signature", "-o", str(pdir), f"{base}..HEAD")
    elif pdir.is_dir() and not any(pdir.iterdir()):
        pdir.rmdir()
    reg = ws / REGISTRY
    if items:
        reg.write_text(render_registry(items))
    elif reg.exists():
        reg.unlink()
    return {"customs": items, "registry": str(reg) if items else None}


def render_registry(items: list[dict[str, Any]]) -> str:
    lines = [
        "# Customizations of Harness Maxxing",
        "",
        "Changes made to the product code on this server, kept as local commits in the code directory",
        f"({config.CODE}) and carried over by `maxxing update`. Generated by `maxxing custom` - do not",
        "edit by hand (the commit messages are the source). Patches: `customizations/` next to this file.",
        "",
    ]
    for it in items:
        lines += [f"## {it['title']}", "",
                  f"- id: `{it['id']}`" + (f" · saved {it['saved']}" if it["saved"] else ""),
                  f"- why: {it['why'] or '(not given)'}",
                  f"- check: `{it['check']}`" if it.get("check") else "- check: (none - `maxxing custom check <id> \"<command>\"`)",
                  "- files: " + ", ".join(f"`{f}`" for f in it["files"]), ""]
    return "\n".join(lines)


# ---- save / drop / restore -----------------------------------------------------------------
def save(title: str, why: str = "", files: list[str] | None = None, check: str = "") -> dict[str, Any]:
    """Commit the uncommitted changes of the code directory as one customization."""
    if not is_git():
        raise CustomError(f"{config.CODE} is not a git clone")
    title = " ".join((title or "").split())[:120]
    if not title:
        raise CustomError("give the customization a title: maxxing custom save \"what it does\" --why \"...\"")
    changed = dirty_files()
    if not changed:
        raise CustomError("nothing to save: no uncommitted change in " + str(config.CODE))
    web = [f for f in changed if f.startswith("web/")]
    if web:
        raise CustomError("changes under web/ cannot be customizations (the web UI is shipped pre-built and "
                          "cannot be rebuilt on this server): build an extension instead (" + ", ".join(web[:3]) + ")")
    ensure_identity()
    if files:
        git("add", "--", *files, check=True)
    else:
        git("add", "-A", check=True)
    cid = f"c-{dt.datetime.now():%Y%m%d}-{_secrets.token_hex(2)}"
    msg = f"{PREFIX}{title}\n\nCustom-Id: {cid}\nWhy: {' '.join((why or '').split()) or '-'}\n" \
          f"Saved: {dt.datetime.now():%Y-%m-%d %H:%M}\n" + \
          (f"Check: {' '.join(check.split())}\n" if (check or "").strip() else "")
    git("commit", "-q", "-m", msg, check=True)
    return {"id": cid, **export()}


def _find(cid: str) -> dict[str, Any]:
    items = list_customs()
    for it in items:
        if cid and it["id"] == cid:
            return it
    hits = [it for it in items if len(cid) >= 4 and it["commit"].startswith(cid)]   # "" or "a" would pick the first one
    if len(hits) > 1:
        raise CustomError(f"{cid!r} matches several customizations: give a longer id (see: maxxing custom list)")
    if hits:
        return hits[0]
    raise CustomError(f"no customization {cid!r} (see: maxxing custom list)")


def drop(cid: str) -> dict[str, Any]:
    """Remove one customization (the later ones are replayed on top)."""
    if dirty_files():
        raise CustomError("uncommitted changes in the code directory: save or discard them first")
    it = _find(cid)
    code, out = git("rebase", "-q", "--onto", f"{it['commit']}^", it["commit"])
    if code != 0:
        git("rebase", "--abort")
        raise CustomError("a later customization depends on this one - nothing changed: " + out.strip()[-300:])
    return {"dropped": it, **export()}


def restore(from_dir: Path | None = None) -> dict[str, Any]:
    """Apply the exported patches (e.g. after restoring the memory backup on a new server)."""
    pdir = from_dir or (_workspace() / PATCH_DIR)
    patches = sorted(pdir.glob("*.patch")) if pdir.is_dir() else []
    if not patches:
        return {"applied": 0, **export()}
    have = {it["id"] for it in list_customs()}
    todo = [p for p in patches if _patch_id(p) not in have]
    if not todo:
        return {"applied": 0, **export()}
    code, out = git("am", "-q", "-3", *map(str, todo))
    if code != 0:
        git("am", "--abort")
        from .cmd_core import update_topic
        raise CustomError("the saved customizations do not apply to this version - ask Claude in the topic "
                          f"{update_topic()} to adapt them: " + out.strip()[-300:])
    return {"applied": len(todo), **export()}


def preview(from_dir: Path | None = None) -> list[dict[str, Any]]:
    """The saved patches `restore()` would apply, without applying them -> [{file, id, title, stat}]
    (the installer shows them after a memory restore and asks before re-applying)."""
    pdir = from_dir or (_workspace() / PATCH_DIR)
    patches = sorted(pdir.glob("*.patch")) if pdir.is_dir() else []
    have = {it["id"] for it in list_customs()} if patches and is_git() else set()
    out = []
    for p in patches:
        if _patch_id(p) in have:
            continue
        try:
            m = re.search(r"^Subject:\s*(?:\[PATCH[^\]]*\]\s*)?(.+)$", p.read_text(errors="replace"), re.M)
        except OSError:
            m = None
        code, stat = git("apply", "--stat", "--", str(p))
        out.append({"file": p.name, "id": _patch_id(p), "title": (m.group(1).strip() if m else p.stem),
                    "stat": stat.strip() if code == 0 else "(cannot be read as a patch)"})
    return out


def _patch_id(p: Path) -> str:
    try:
        m = re.search(r"^Custom-Id:\s*(\S+)", p.read_text(errors="replace"), re.M)
    except OSError:
        return ""
    return m.group(1) if m else ""


# ---- pending update (conflict / failed health check) ---------------------------------------
def pending_path() -> Path:
    return config.STATE / PENDING


def pending() -> dict[str, Any] | None:
    try:
        d = json.loads(pending_path().read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def set_pending(**info: Any) -> dict[str, Any]:
    d = {"at": dt.datetime.now().timestamp(), **info}
    config.write_json(pending_path(), d)
    return d


def clear_pending() -> None:
    try:
        pending_path().unlink()
    except FileNotFoundError:
        pass


def conflicts() -> list[str]:
    code, out = git("diff", "--name-only", "--diff-filter=U")
    return [f for f in out.splitlines() if f.strip()] if code == 0 else []


def rebase_in_progress() -> bool:
    g = config.CODE / ".git"
    return (g / "rebase-merge").exists() or (g / "rebase-apply").exists()


def summary(branch: str | None = None) -> dict[str, Any]:
    """For doctor, status and the UI."""
    if not is_git():
        return {"git": False, "customs": [], "dirty": [], "pending": None, "rebase": False}
    return {"git": True, "customs": list_customs(branch), "dirty": dirty_files(), "pending": pending(),
            "rebase": rebase_in_progress()}
