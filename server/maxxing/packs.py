"""Starter packs: ready-made projects for a kind of work (e-commerce, affiliate, creator, apps, second brain,
freelance). Offered at onboarding and in Settings -> Projects, or with `maxxing packs add <id>`.

A pack lives in templates/packs/<id>/:
  pack.json            {id, project, emoji, icon, title{en,fr}, description{en,fr}, topics[], crons[]}
  project/             copied to <workspace>/projects/<project>/ (CLAUDE.md, memory.md, topics/<t>/...)

Installing never overwrites: a pack is added as a new project, named after the pack or, when that name is
taken, `<project>-2`, `-3`... (the same pack can be added several times, e.g. two stores). Only files that do
not exist yet are written. Text files are rendered like the workspace
templates ({{WORKSPACE}}, {{CODE_DIR}}, {{VERSION}}). The project gets the pack's emoji unless it already has
one; `icon` (a lucide name, see web/src/components/ui/icon.tsx) is what the UI shows for the pack. The pack's scheduled jobs are created disabled (named "<job> (<project>)" for a second copy).

The `basics` pack is the default workspace (templates/workspace/projects: general/inbox, system/...): installing
it puts back the default projects and topics the user deleted, again without overwriting anything.
"""
from __future__ import annotations

import json
import logging
import shutil
import threading
from pathlib import Path

from . import config

log = logging.getLogger("maxxing.packs")

RENDERED_SUFFIXES = (".md", ".json", ".txt")


class PackError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def packs_dir() -> Path:
    return config.TEMPLATES_DIR / "packs"


def _read(pid: str) -> dict | None:
    d = packs_dir() / pid
    try:
        data = json.loads((d / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("id") != pid or not (d / "project").is_dir():
        return None
    return data


BASICS = "basics"
BASICS_TEXT = {
    "title": {"en": "Default projects", "fr": "Projets de base"},
    "description": {"en": "general/inbox and system (tutorial, help, Harness): puts back the ones you deleted, "
                          "never overwrites.",
                    "fr": "general/inbox et system (tutoriel, aide, Harness) : remet ceux que vous avez supprimés, "
                          "sans rien écraser."},
}


def _basics_root() -> Path:
    return config.TEMPLATES_DIR / "workspace" / "projects"


def _basics_summary(lang: str) -> dict:
    from . import workspace
    ws = workspace.root()
    topics = [f"{p.name}/{t.name}" for p in sorted(_basics_root().iterdir()) if p.is_dir()
              for t in sorted((p / "topics").iterdir()) if t.is_dir()] if _basics_root().is_dir() else []
    present = [t for t in topics if (ws / "projects" / t.split("/")[0] / "topics" / t.split("/")[1]).is_dir()]
    return {"id": BASICS, "project": ", ".join(sorted({t.split("/")[0] for t in topics})), "emoji": "🏠", "icon": "home",
            "title": BASICS_TEXT["title"].get(lang) or BASICS_TEXT["title"]["en"],
            "description": BASICS_TEXT["description"].get(lang) or BASICS_TEXT["description"]["en"],
            "topics": topics, "crons": [], "basics": True,
            "installed": len(present) == len(topics), "partial": 0 < len(present) < len(topics),
            "project_exists": bool(present)}


def _copy_missing(src_root: Path, dst_root: Path, rel_prefix: str, variables: dict) -> list[str]:
    from .cmd_core import render_template
    created: list[str] = []
    for src in sorted(src_root.rglob("*")):
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        elif not dst.exists() and not dst.is_symlink():  # a dangling link is never written through
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:                                       # nor a linked folder leading out of the destination
                dst.parent.resolve().relative_to(dst_root.resolve())
            except ValueError:
                continue
            if src.suffix in RENDERED_SUFFIXES:
                dst.write_text(render_template(src.read_text(encoding="utf-8"), variables), encoding="utf-8")
                shutil.copymode(src, dst)
            else:
                shutil.copy2(src, dst)
            created.append(f"{rel_prefix}/{rel}")
    return created


def _free_name(ws: Path, base: str) -> str:
    if not (ws / "projects" / base).exists():
        return base
    n = 2
    while (ws / "projects" / f"{base}-{n}").exists():
        n += 1
    return f"{base}-{n}"


ORDER = ["ecommerce", "affiliate", "creator", "apps", "second-brain", "freelance"]


def _ids() -> list[str]:
    if not packs_dir().is_dir():
        return []
    found = [p.name for p in packs_dir().iterdir() if p.is_dir() and (p / "pack.json").is_file()]
    return sorted(found, key=lambda x: (ORDER.index(x) if x in ORDER else len(ORDER), x))


def _summary(data: dict, lang: str) -> dict:
    from . import workspace
    pick = lambda v: (v.get(lang) or v.get("en") or "") if isinstance(v, dict) else str(v or "")   # noqa: E731
    project = data.get("project") or data["id"]
    pdir = workspace.root() / "projects" / project
    topics = [t for t in data.get("topics", []) if isinstance(t, str)]
    present = [t for t in topics if (pdir / "topics" / t).is_dir()]
    return {
        "id": data["id"], "project": project, "emoji": data.get("emoji", ""), "icon": data.get("icon", ""),
        "title": pick(data.get("title")), "description": pick(data.get("description")),
        "topics": topics, "crons": [c.get("name", "") for c in data.get("crons", []) if isinstance(c, dict)],
        "installed": pdir.is_dir() and len(present) == len(topics),
        "partial": pdir.is_dir() and 0 < len(present) < len(topics),
        "project_exists": pdir.is_dir(), "basics": False,
    }


def list_packs(lang: str | None = None) -> list[dict]:
    lang = lang or str(config.load_config().get("language") or "en")
    out = []
    if _basics_root().is_dir():
        out.append(_basics_summary(lang))
    for pid in _ids():
        data = _read(pid)
        if data:
            out.append(_summary(data, lang))
    return out


_install_lock = threading.Lock()


def install(pid: str, lang: str | None = None) -> dict:
    """Add the pack as a new project (missing files only), set the emoji, create its jobs (disabled). One install
    at a time: the free project name, the copy and the job names are chosen from what is already there."""
    with _install_lock:
        return _install(pid, lang)


def _install(pid: str, lang: str | None) -> dict:
    from . import workspace
    from .cmd_core import template_vars
    lang = lang or str(config.load_config().get("language") or "en")
    ws = workspace.ensure_root()
    variables = template_vars(ws)
    if pid == BASICS and _basics_root().is_dir():
        created = _copy_missing(_basics_root(), ws / "projects", "projects", variables)
        _invalidate(False)
        return {"ok": True, "pack": _basics_summary(lang), "project": "", "created_files": len(created), "jobs": []}
    data = _read(pid) if pid in _ids() else None
    if not data:
        raise PackError(404, "unknown_pack", f"Unknown pack: {pid}")
    base = data.get("project") or pid
    workspace.check_slug(base)
    project = _free_name(ws, base)
    created = _copy_missing(packs_dir() / pid / "project", ws / "projects" / project, f"projects/{project}", variables)
    if project != base:
        # the pack's files name their project in their title line ("# Project ecommerce")
        head = f"# Project {base}"
        for f in (ws / "projects" / project / "CLAUDE.md", ws / "projects" / project / "memory.md"):
            txt = f.read_text(encoding="utf-8") if f"projects/{project}/{f.name}" in created else ""
            if txt.startswith(head) and txt[len(head):len(head) + 1] in (" ", "\n"):
                f.write_text(f"# Project {project}" + txt[len(head):], encoding="utf-8")
    if data.get("emoji") and not workspace.project_emoji(project):
        try:
            workspace.set_project_emoji(project, workspace.check_emoji(data["emoji"]))
        except Exception:  # noqa: BLE001 - an emoji is a nice-to-have
            log.exception("pack %s: could not set the emoji", pid)
    jobs = _create_jobs(data, project, suffix="" if project == base else f" ({project})")
    _invalidate(bool(jobs))
    return {"ok": True, "pack": _summary(data, lang), "project": project, "created_files": len(created), "jobs": jobs}


def _invalidate(crons_too: bool) -> None:
    try:
        from . import bus
        bus.invalidate("workspace")
        if crons_too:
            bus.invalidate("crons")
    except Exception:  # noqa: BLE001
        pass


def _create_jobs(data: dict, project: str, suffix: str = "") -> list[str]:
    from . import crons
    made: list[str] = []
    try:
        names = {j.get("name") for j in crons.list_jobs()}
    except Exception:  # noqa: BLE001
        names = set()
    for c in data.get("crons", []):
        if not isinstance(c, dict) or not c.get("name") or c["name"] + suffix in names:
            continue
        topic = c.get("topic") or ""
        job = {"name": c["name"] + suffix, "schedule": c.get("schedule", "0 9 * * 1"), "kind": "claude",
               "topic_path": f"projects/{project}/topics/{topic}" if topic else f"projects/{project}",
               "prompt": c.get("prompt", ""), "model": "", "reuse_session": False, "enabled": False,
               "notify": c.get("notify", "always"), "timeout_s": int(c.get("timeout_s", 900))}
        try:
            crons.create_job(job)
            made.append(c["name"] + suffix)
        except Exception as e:  # noqa: BLE001 - a bad job must not block the pack
            log.warning("pack %s: job %r not created: %s", data.get("id"), c.get("name"), e)
    return made
