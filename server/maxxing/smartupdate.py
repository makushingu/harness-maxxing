"""Smart update: know before, get help during, be sure after.

- preflight(): what the next update will do to THIS server, without touching it. The new version is checked
  out in a throw-away git worktree and every customization is replayed on it (cherry-pick): it applies,
  conflicts, or is already included in the new version (empty). Customizations that apply but touch files the
  new version also changed are flagged "review". Uncommitted edits, edits of the pre-built web UI (they cannot
  be customizations) and extensions the new version no longer supports (manifest "api") are reported too.
  Verdict: "up_to_date" | "simple" (the button just updates) | "adapt" (a Harness session adapts first).
- verify(): after an update (or on demand), every extension is loaded and every widget computed, and the check
  command of each customization (`maxxing custom save ... --check "<cmd>"`) is run. Saved as the last report.
- after_update(): the restarted server reads the marker written by `maxxing update` and runs verify(); for an
  update started from the UI (`--smart`) it also opens a Harness session that applies the workspace upgrade
  notes needing action, so the person who clicked gets them without asking.
- assist_prompt(): the prompt of the "Update with Harness" session (adapt by intent, test, then switch).

State: <state>/update/{preflight.json, report.json, after.json}.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger("maxxing.smartupdate")

PREFLIGHT = "update/preflight.json"
REPORT = "update/report.json"
AFTER = "update/after.json"
CHECK_TIMEOUT_S = 60
NOTHING_TO_DO = re.compile(r"^\s*nothing to do\b", re.I | re.M)


# ---- small helpers -------------------------------------------------------------------------------
def _path(rel: str) -> Path:
    return config.STATE / rel


def _read(rel: str) -> dict | None:
    try:
        d = json.loads(_path(rel).read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _write(rel: str, data: dict) -> dict:
    config.write_json(_path(rel), data)
    return data


def _wt_git(wt: Path, *args: str, timeout: float = 120) -> tuple[int, str]:
    from .customs import IDENT
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_EDITOR": "true", "GIT_PAGER": "cat"}
    try:
        r = subprocess.run(["git", *IDENT, "-C", str(wt), *args], capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _asks_something(note: str) -> bool:
    """An upgrade note asks for something unless its first paragraph says "Nothing to do"."""
    body = note.split("\n", 1)[1].strip() if "\n" in note else ""
    return bool(body) and not NOTHING_TO_DO.search(body.split("\n\n", 1)[0])


def upgrade_notes_to_apply(old: str, new: str, root: Path | None = None) -> list[dict]:
    """The upgrade notes between two versions that ask for something (not "Nothing to do")."""
    from .cmd_core import upgrade_notes
    out = []
    for f in upgrade_notes(old, new, root):
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        if _asks_something(text):
            out.append({"version": f.stem, "file": str(f)})
    return out


# ---- extensions: contract version ----------------------------------------------------------------
def _api_range(src: str) -> tuple[int, int]:
    """(EXT_API_MIN, EXT_API) declared by a version of extensions.py (1, 1 when absent: before versioning)."""
    hi = re.search(r"^EXT_API\s*=\s*(\d+)", src or "", re.M)
    lo = re.search(r"^EXT_API_MIN\s*=\s*(\d+)", src or "", re.M)
    top = int(hi.group(1)) if hi else 1
    return (int(lo.group(1)) if lo else 1), top


def _extensions_against(target_src: str) -> list[dict]:
    """Installed extensions the target version would not load (api outside its range)."""
    from . import extensions
    lo, hi = _api_range(target_src)
    out = []
    for e in extensions.scan():
        if e.api < lo or e.api > hi:
            out.append({"id": e.id, "name": e.label(), "api": e.api,
                        "reason": f"built for extension API {e.api}, the new version supports {lo}-{hi}"})
    return out


# ---- preflight -----------------------------------------------------------------------------------
def _signature() -> list[str]:
    """What a cached preflight depends on: local HEAD, the target, the uncommitted files."""
    from . import customs
    from .cmd_core import _rev, _current_branch
    branch = _current_branch()
    return [_rev("HEAD"), _rev(f"origin/{branch}"), ",".join(sorted(customs.dirty_files()))]


def cached_preflight() -> dict | None:
    d = _read(PREFLIGHT)
    if not d:
        return None
    try:
        if d.get("sig") != _signature():
            return None
    except Exception:  # noqa: BLE001
        return None
    return d


def preflight(branch: str | None = None, fetch: bool = True) -> dict:
    """Simulate the update on a throw-away copy. Never changes the install."""
    from . import customs
    from .cmd_core import _current_branch, _git, _rev, _version_in, changelog_since, check_update
    if not customs.is_git():
        return {"ok": False, "verdict": "unavailable", "error": f"{config.CODE} is not a git clone"}
    branch = branch or _current_branch()
    if fetch:
        info = check_update(branch)
        if not info.get("ok"):
            return {"ok": False, "verdict": "unavailable", "error": info.get("error") or "update check failed"}
    upstream = f"origin/{branch}"
    head, target = _rev("HEAD"), _rev(upstream)
    code, base = _git("merge-base", "HEAD", upstream)
    base = base.strip() if code == 0 else ""
    try:
        current = _version_in((config.CODE / "server/maxxing/__init__.py").read_text()) or ""
    except OSError:
        current = ""
    _, target_init = _git("show", f"{target}:server/maxxing/__init__.py")
    latest = _version_in(target_init) or current
    dirty = customs.dirty_files()
    web_dirty = [f for f in dirty if f.startswith("web/")]
    other_dirty = [f for f in dirty if not f.startswith("web/")]
    mine = customs.list_customs(branch)
    behind = 0
    if base and target:
        c, cnt = _git("rev-list", "--count", f"HEAD..{upstream}")
        behind = int(cnt.strip()) if c == 0 and cnt.strip().isdigit() else 0
    rep: dict[str, Any] = {
        "ok": True, "at": time.time(), "branch": branch, "current": current, "latest": latest, "behind": behind,
        "target": target[:12], "customs": [], "unsaved": other_dirty, "web_changes": web_dirty,
        "extensions": [], "notes": [], "changelog": [], "sig": None,
    }
    if behind == 0 or not target:
        rep["verdict"] = "adapt" if web_dirty else "up_to_date"
        rep["sig"] = _signature()
        return _write(PREFLIGHT, rep)
    rep["changelog"] = changelog_since("HEAD", upstream)
    _, changed = _git("diff", "--name-only", f"{base}..{target}") if base else (0, "")
    upstream_files = {f for f in changed.splitlines() if f.strip()}
    rep["upstream_files"] = len(upstream_files)
    rep["customs"] = _replay(mine, target, upstream_files)
    for f in other_dirty:                                      # unsaved: saved by the update, checked like the rest
        if f in upstream_files:
            rep.setdefault("unsaved_overlap", []).append(f)
    _, target_ext = _git("show", f"{target}:server/maxxing/extensions.py")
    try:
        rep["extensions"] = _extensions_against(target_ext)
    except Exception as e:  # noqa: BLE001 - never fail the preflight on an extension
        log.warning("preflight: extensions check failed: %s", e)
    rep["notes"] = _target_notes(current, latest, target)
    adapt = (any(c["status"] == "conflict" for c in rep["customs"]) or web_dirty or rep["extensions"]
             or rep.get("unsaved_overlap"))
    rep["verdict"] = "adapt" if adapt else "simple"
    rep["sig"] = _signature()
    return _write(PREFLIGHT, rep)


def _target_notes(current: str, latest: str, target: str) -> list[dict]:
    """Upgrade notes of the new version that ask for something (read from the target commit)."""
    from .cmd_core import _git, version_key
    lo, hi = version_key(current), version_key(latest)
    code, out = _git("ls-tree", "--name-only", f"{target}:docs/upgrade")
    if code != 0 or hi is None:
        return []
    notes = []
    for name in out.split():
        v = name.removesuffix(".md")
        k = version_key(v)
        if k is None or (lo is not None and k <= lo) or k > hi:
            continue
        _, text = _git("show", f"{target}:docs/upgrade/{name}")
        if _asks_something(text):
            notes.append({"version": v})
    return sorted(notes, key=lambda n: version_key(n["version"]) or ())


def _replay(mine: list[dict], target: str, upstream_files: set[str]) -> list[dict]:
    """Cherry-pick each customization onto the target in a temporary worktree."""
    from . import customs
    out = [{"id": c["id"], "title": c["title"], "why": c.get("why", ""), "files": c["files"],
            "check": c.get("check", ""), "status": "ok", "conflicts": [],
            "overlap": sorted(set(c["files"]) & upstream_files)} for c in mine]
    if not mine:
        return out
    tmp = Path(tempfile.mkdtemp(prefix="mx-preflight-", dir=str(config.state_dir("update"))))
    wt = tmp / "code"
    try:
        code, err = customs.git("worktree", "add", "-q", "--detach", str(wt), target, timeout=300)
        if code != 0:
            for item in out:
                item["status"] = "unknown"
            log.warning("preflight: worktree failed: %s", err.strip()[-300:])
            return out
        for item, c in zip(out, mine):
            code, msg = _wt_git(wt, "cherry-pick", "--no-commit", c["commit"])
            if code != 0:
                c2, files = _wt_git(wt, "diff", "--name-only", "--diff-filter=U")
                item["status"], item["conflicts"] = "conflict", [f for f in files.splitlines() if f.strip()]
                _wt_git(wt, "cherry-pick", "--abort")
                _wt_git(wt, "reset", "-q", "--hard")
                continue
            if _wt_git(wt, "diff", "--cached", "--quiet")[0] == 0:
                item["status"] = "included"                   # the new version already contains this change
                continue
            _wt_git(wt, "commit", "-q", "--no-verify", "-m", f"preflight {item['id']}")
            if item["overlap"]:
                item["status"] = "review"                     # applies, but on code that changed upstream
    finally:
        customs.git("worktree", "remove", "--force", str(wt), timeout=120)
        customs.git("worktree", "prune")
        shutil.rmtree(tmp, ignore_errors=True)
    return out


# ---- verification after an update ----------------------------------------------------------------
def _check_extension(e: Any) -> dict:
    from . import extensions
    item = {"id": e.id, "name": e.label(), "type": e.type, "ok": True, "error": ""}
    if not e.enabled:
        item["skipped"] = True
        return item
    if e.error:
        item.update(ok=False, error=e.error)
        return item
    try:
        if e.type == "widget" and e.has_api and not e.has_html:
            card = extensions.widget_card(e, force=True)
            if isinstance(card, dict) and card.get("status") == "error" and card.get("error"):
                item.update(ok=False, error=str(card.get("error"))[:300])
        if e.has_page:
            node = shutil.which("node")
            if node:
                r = subprocess.run([node, "--check", str(e.dir / "page.js")], capture_output=True, text=True, timeout=20)
                if r.returncode != 0:
                    item.update(ok=False, error=(r.stderr or r.stdout).strip()[-300:])
    except Exception as ex:  # noqa: BLE001 - a broken extension is a result, not a crash
        item.update(ok=False, error=f"{type(ex).__name__}: {ex}"[:300])
    return item


def _run_check(cmd: str) -> tuple[bool, str]:
    ws = Path(config.load_config().get("workspace") or config.workspace())
    try:
        r = subprocess.run(cmd, shell=True, cwd=str(ws if ws.is_dir() else config.CODE), capture_output=True,
                           text=True, timeout=CHECK_TIMEOUT_S, env={**os.environ, "MAXXING_CODE": str(config.CODE)})
    except subprocess.TimeoutExpired:
        return False, f"timed out after {CHECK_TIMEOUT_S} s"
    except OSError as e:
        return False, str(e)
    return r.returncode == 0, ((r.stdout or "") + (r.stderr or "")).strip()[-400:]


def verify() -> dict:
    """Load every extension, compute every widget, run every customization check -> the report."""
    from . import __version__, customs, extensions
    exts = [_check_extension(e) for e in extensions.scan()]
    checks = []
    for c in customs.list_customs() if customs.is_git() else []:
        if not c.get("check"):
            continue
        ok, output = _run_check(c["check"])
        checks.append({"id": c["id"], "title": c["title"], "check": c["check"], "ok": ok, "output": output})
    problems = [x for x in exts if not x["ok"]] + [x for x in checks if not x["ok"]]
    rep = {"at": time.time(), "version": __version__, "ok": not problems, "extensions": exts, "checks": checks,
           "problems": len(problems)}
    return _write(REPORT, rep)


def last_report() -> dict | None:
    return _read(REPORT)


# ---- after an update (run by the restarted server) -----------------------------------------------
def mark_updated(old_version: str, new_version: str, smart: bool) -> None:
    """Written by `maxxing update` once the new version answers."""
    _write(AFTER, {"at": time.time(), "from": old_version, "to": new_version, "smart": smart, "done": False})


def after_info() -> dict | None:
    """The last update seen by the restarted server: {to, at, notes_session?}."""
    m = _read(AFTER)
    return {k: m.get(k) for k in ("to", "at", "notes_session", "notes_path", "done")} if m else None


def update_topic_path() -> str:
    from .cmd_core import update_topic
    return "projects/" + update_topic().replace("/", "/topics/", 1)


def after_update() -> dict | None:
    """Once per update: verify, tell the user, open the notes session for a button update."""
    m = _read(AFTER)
    if not m or m.get("done"):
        return None
    m["done"] = True
    _write(AFTER, m)
    rep = verify()
    from . import feed
    if not rep["ok"]:
        names = [x.get("name") or x.get("title") for x in rep["extensions"] + rep["checks"] if not x["ok"]]
        title = f"After the update to {m['to']}: {rep['problems']} thing(s) to fix"
        body = "Not working any more: " + ", ".join(names[:5]) + ". Ask Harness to fix it (Settings -> System)."
        feed.system(title, body, "warning", "system", "/settings/system")
        from .telegram import gateway
        gateway.system_alert(f"{title}\n{body}")
    notes = upgrade_notes_to_apply(m.get("from") or "", m.get("to") or "") if m.get("smart") else []
    if notes and config.load_config().get("update_auto_notes", True):
        try:
            from .sessions import service
            s = service.create_session(update_topic_path(), message=notes_prompt(m["from"], m["to"], notes),
                                       title=f"Update {m['to']}: apply the notes", source="system")
            m["notes_session"], m["notes_path"] = s["id"], s.get("path") or update_topic_path()
            _write(AFTER, m)
        except Exception as e:  # noqa: BLE001 - the notes can still be applied by asking "update"
            log.warning("could not open the upgrade notes session: %s", e)
    return m


def notes_prompt(old: str, new: str, notes: list[dict]) -> str:
    files = "\n".join(f"- {n['file']}" for n in notes)
    return (f"Harness Maxxing was just updated from {old} to {new} with the Update button. Apply the workspace "
            f"upgrade notes below, following step 5 and 6 of this topic's CLAUDE.md (keep the user's own edits, "
            f"record the last applied version in memory.md), then tell me in two or three plain sentences what "
            f"changed for me.\n\n{files}" + _reply_in())


def _reply_in() -> str:
    return "\n\nAnswer me in French." if config.load_config().get("language") == "fr" else ""


# ---- "Update with Harness" -----------------------------------------------------------------------
def assist_prompt(rep: dict) -> str:
    """The prompt of the session that adapts this server's changes, then updates."""
    from . import customs
    lines = [f"Update Harness Maxxing from {rep.get('current')} to {rep.get('latest')} - this server has changes "
             "the update cannot carry over by itself. Here is what the preflight found "
             "(`maxxing update --preflight` shows it again):", ""]
    for c in rep.get("customs") or []:
        tag = {"conflict": "CONFLICTS with the new version", "included": "is now INCLUDED in the new version",
               "review": "applies, but touches code the new version changed", "ok": "applies cleanly",
               "unknown": "could not be checked"}.get(c["status"], c["status"])
        lines.append(f"- Customization `{c['id']}` \"{c['title']}\" {tag}"
                     + (f" ({', '.join(c['conflicts'])})" if c.get("conflicts") else "")
                     + (f". Why: {c['why']}" if c.get("why") else ""))
    if rep.get("unsaved"):
        lines.append(f"- Unsaved changes in {config.CODE}: {', '.join(rep['unsaved'][:8])}"
                     + (" (some on code the new version changed)" if rep.get("unsaved_overlap") else ""))
    if rep.get("web_changes"):
        lines.append(f"- The pre-built web UI was edited ({', '.join(rep['web_changes'][:5])}): it cannot be kept "
                     "as a customization; the update moves these edits aside (git stash).")
    for e in rep.get("extensions") or []:
        lines.append(f"- Extension `{e['id']}`: {e['reason']}")
    lines += ["", "How to do it (skill maxxing-customize):",
              "1. Read CUSTOMIZATIONS.md (what each change is FOR) and the changelog (`maxxing update --check`).",
              "2. Included in the new version: check it really does the same, then `maxxing custom drop <id>`.",
              "3. Unsaved changes: save them first with a real title and reason (`maxxing custom save ... --why ...`).",
              "4. Edits of the web UI: rebuild what they did as an extension (skill maxxing-extension), ask me "
              "before dropping anything.",
              f"5. Run `maxxing update`. On a conflict (exit 3): `cd {config.CODE} && git rebase origin/"
              f"{rep.get('branch') or 'main'}`, then for each conflicting file re-implement the INTENT of the "
              "customization on the new code (do not just pick a side), `git add`, `GIT_EDITOR=true git rebase "
              "--continue`, and finally `maxxing update --resume`.",
              "6. Extensions the new version does not support: update their code and their manifest \"api\" "
              "(docs/user/12-dashboard-widgets.md and 13-page-extensions.md of the new version).",
              "7. `maxxing update --verify`: fix whatever fails, then give each customization a check if it has "
              "none (`maxxing custom check <id> \"<command>\"`).",
              "8. Apply the upgrade notes (steps 5-6 of this topic's CLAUDE.md), then tell me in plain words what "
              "changed and what you adapted.",
              "If anything looks risky, stop and ask me: the current version keeps running until the update succeeds."]
    if customs.pending():
        lines.insert(1, "(A previous update attempt is pending: `maxxing update --resume` once the rebase is done.)")
    return "\n".join(lines) + _reply_in()


def start_assist(rep: dict | None = None) -> dict:
    """Open the Harness session that adapts the changes then updates -> the session."""
    from .sessions import service
    rep = rep or cached_preflight() or preflight()
    return service.create_session(update_topic_path(), message=assist_prompt(rep),
                                  title=f"Update to {rep.get('latest') or 'the new version'}", source="web")


def fix_prompt(rep: dict) -> str:
    bad = [f"- extension `{x['id']}`: {x['error']}" for x in rep.get("extensions", []) if not x["ok"]]
    bad += [f"- customization `{x['id']}` \"{x['title']}\": its check `{x['check']}` fails: {x['output'][-200:]}"
            for x in rep.get("checks", []) if not x["ok"]]
    return ("These stopped working after the update to " + str(rep.get("version")) + ":\n" + "\n".join(bad)
            + "\n\nFix them (skills maxxing-extension / maxxing-customize), run `maxxing update --verify` until "
              "everything passes, then tell me what you changed." + _reply_in())

