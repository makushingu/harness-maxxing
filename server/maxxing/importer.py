"""Import the memory of another agent (Hermes, Claude Code, OpenClaw...) from a zip.

The user copies PROMPT (or `prompt(agent)`) into their old agent, which builds this tree and zips it:

    memory.md                                   who the user is, preferences, global facts
    projects/<project>/CLAUDE.md, memory.md     what the project is / its facts and decisions
    projects/<project>/topics/<topic>/CLAUDE.md, memory.md, any useful files
    skills/<name>/SKILL.md (+ files)            reusable procedures
    tasks.md, crons.md, SECRETS.md, anything else   kept aside in imports/<stamp>/ for Claude

Flow: `inspect(zip)` -> preview (what will be created / merged / skipped) -> `apply(zip)`.
Nothing is ever overwritten: an existing memory.md / CLAUDE.md gets an "## Imported" section
appended, another existing file is written as "<name> (imported).<ext>", an existing skill folder
as "<name>-imported". Files that contain a secret-shaped string are skipped (reported by kind,
never by value): keys go to Settings -> Keys. A report is written in imports/<stamp>/IMPORT_REPORT.md.
"""
from __future__ import annotations

import datetime as dt
import re
import secrets as _secrets
import shutil
import stat
import time
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from . import bus, config

MAX_FILES = 20000
MAX_TOTAL = 500 * 1024 * 1024          # uncompressed
MAX_FILE = 100 * 1024 * 1024
SCAN_MAX = 5 * 1024 * 1024             # files scanned for secrets (larger: binary data, kept)
JUNK_PARTS = {"__MACOSX", ".git", "node_modules", ".venv", "venv", "__pycache__", ".DS_Store", "Thumbs.db"}
# Harness's own folder settings (a topic's permission mode, the project order): set in the app, never by an export.
FOLDER_SETTINGS = {".maxxing.json", ".order.json"}
MEMORY_NAMES = {"memory.md", "MEMORY.md", "USER.md", "user.md"}
UPLOAD_TTL = 24 * 3600

AGENTS = ("hermes", "claude-code", "openclaw", "other")
HINTS = {
    "hermes": "You are Hermes Agent: your memory lives in ~/.hermes/ (MEMORY.md, USER.md, memories/, "
              "skills/, sessions, cron jobs). Read all of it.",
    "claude-code": "You are Claude Code: read every CLAUDE.md and memory file you use (~/.claude/CLAUDE.md, "
                   "the project folders, ~/.claude/projects/*/memory/), your skills (~/.claude/skills/, "
                   ".claude/skills/) and anything the user keeps notes in.",
    "openclaw": "You are OpenClaw: read your workspace (by default ~/.openclaw/workspace/: AGENTS.md, SOUL.md, "
                "USER.md, MEMORY.md, memory/*.md, skills/) and your scheduled jobs.",
    "other": "Read every place where you keep memory, notes, instructions, skills and scheduled jobs.",
}

PROMPT = """I am moving to Harness Maxxing, a control room for Claude Code. Please export everything you know \
and keep about me and my work into ONE zip file that it can import. {hint}

Build a folder `harness-maxxing-export/` with exactly this layout (Markdown, UTF-8):

harness-maxxing-export/
  memory.md                          # who I am, how I like to work, global facts and preferences
  projects/<project>/CLAUDE.md       # 2-5 lines: what this project is, its rules
  projects/<project>/memory.md       # durable facts, decisions, status, people, links
  projects/<project>/topics/<topic>/CLAUDE.md   # what this topic is for and how to work on it
  projects/<project>/topics/<topic>/memory.md   # facts, decisions, current state, next steps
  projects/<project>/topics/<topic>/...         # useful files (docs, plans, scripts, notes)
  skills/<skill-name>/SKILL.md       # each reusable procedure (front matter: name, description)
  tasks.md                           # my open to-dos, one per line, with project and due date if known
  crons.md                           # every recurring job: schedule (cron syntax + time zone), what it does
  SECRETS.md                         # the NAMES of the API keys / tokens / passwords I use and what for

Rules:
- A project = one area of my life or work (a business, a client, a side project). A topic = one ongoing
  subject inside it (blog, seo, orders, design...). Folder names: lowercase, digits and dashes only.
- Put each fact in the most specific place (topic > project > root). Concise, factual, dated when useful
  ("2026-05-02: switched to Stripe"). Keep what is still true; drop chit-chat and obsolete details.
- NEVER write a secret value (API key, token, password, cookie, private key) anywhere - only their names
  in SECRETS.md. Files containing secrets will be refused by the import.
- Leave out huge data, caches, media and generated files (keep the zip under 50 MB).
- Then zip it: `cd <parent> && zip -r harness-maxxing-export.zip harness-maxxing-export` and give me the
  file (or tell me its path). Finish with a short summary: how many projects, topics and skills.
"""


class ImportFailed(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def prompt(agent: str = "other") -> str:
    return PROMPT.format(hint=HINTS.get(agent, HINTS["other"]))


def slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:48].strip("-")
    return s or "imported"


# ---- uploads -------------------------------------------------------------------------------
def uploads_dir() -> Path:
    return config.state_dir("import")


def new_upload() -> tuple[str, Path]:
    for p in uploads_dir().glob("*.zip"):                # forget stale uploads
        if time.time() - p.stat().st_mtime > UPLOAD_TTL:
            p.unlink(missing_ok=True)
    uid = _secrets.token_hex(8)
    return uid, uploads_dir() / f"{uid}.zip"


def upload_path(uid: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{16}", uid or ""):
        raise ImportFailed(400, "bad_id", "Invalid import id")
    p = uploads_dir() / f"{uid}.zip"
    if not p.is_file():
        raise ImportFailed(404, "not_found", "This upload expired - send the zip again")
    return p


def discard(uid: str) -> None:
    upload_path(uid).unlink(missing_ok=True)


# ---- reading the zip -----------------------------------------------------------------------
def _claude_config(p: PurePosixPath) -> bool:
    """Claude Code configuration in the export (`.claude/settings.json` with hooks, hook scripts,
    `.mcp.json`): it would run commands in every session of that folder. Under `.claude/` only skills
    and Markdown notes are kept."""
    parts = p.parts
    if ".mcp.json" in parts:
        return True
    return any(part == ".claude" and parts[k + 1:k + 2] != ("skills",) and p.suffix.lower() != ".md"
               for k, part in enumerate(parts))


def _entries(zf: zipfile.ZipFile) -> tuple[list[tuple[zipfile.ZipInfo, PurePosixPath]], list[dict]]:
    """Safe file entries (path inside the export) + skipped ones {file, reason}."""
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise ImportFailed(413, "too_many_files", f"More than {MAX_FILES} files in the zip")
    if sum(i.file_size for i in infos) > MAX_TOTAL:
        raise ImportFailed(413, "too_big", f"More than {MAX_TOTAL // 1024 // 1024} MB once unzipped")
    skipped: list[dict] = []
    ok: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    for i in infos:
        p = PurePosixPath(i.filename.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts or not p.parts:
            skipped.append({"file": i.filename, "reason": "unsafe path"})
            continue
        if stat.S_ISLNK(i.external_attr >> 16):
            skipped.append({"file": i.filename, "reason": "symbolic link"})
            continue
        if any(part in JUNK_PARTS for part in p.parts):
            continue
        if _claude_config(p):
            skipped.append({"file": i.filename, "reason": "Claude Code settings (not imported)"})
            continue
        if any(part in FOLDER_SETTINGS for part in p.parts):
            skipped.append({"file": i.filename, "reason": "Harness folder settings (not imported)"})
            continue
        if i.file_size > MAX_FILE:
            skipped.append({"file": i.filename, "reason": "larger than 100 MB"})
            continue
        ok.append((i, p))
    # an export folder at the top ("harness-maxxing-export/...") is stripped
    tops = {p.parts[0] for _, p in ok if len(p.parts) > 1} | {"" for _, p in ok if len(p.parts) == 1}
    if len(tops) == 1 and "" not in tops and next(iter(tops)) not in ("projects", "skills"):
        ok = [(i, PurePosixPath(*p.parts[1:])) for i, p in ok]
    return ok, skipped


def _plan(zf: zipfile.ZipFile) -> dict[str, Any]:
    """What the import would do, without writing anything."""
    from . import backup, workspace
    entries, skipped = _entries(zf)
    root = workspace.root()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    projects: dict[str, dict] = {}
    items: list[dict] = []
    secrets_found: list[dict] = []
    renamed: list[dict] = []

    def proj(raw: str) -> dict:
        name = slug(raw)
        if name not in projects:
            projects[name] = {"name": name, "source": raw, "exists": (root / "projects" / name).is_dir(), "topics": {}}
            if name != raw:
                renamed.append({"from": raw, "to": name})
        return projects[name]

    for info, p in entries:
        parts = p.parts
        data_kind = "file"
        if parts[0] == "projects" and len(parts) >= 3:
            pr = proj(parts[1])
            if parts[2] == "topics" and len(parts) >= 5:
                tname = slug(parts[3])
                if tname not in pr["topics"]:
                    pr["topics"][tname] = {"name": tname, "source": parts[3], "files": 0,
                                           "exists": (root / "projects" / pr["name"] / "topics" / tname).is_dir()}
                    if tname != parts[3]:
                        renamed.append({"from": f"{parts[1]}/{parts[3]}", "to": f"{pr['name']}/{tname}"})
                pr["topics"][tname]["files"] += 1
                dest = PurePosixPath("projects", pr["name"], "topics", tname, *parts[4:])
                data_kind = "topic"
            else:
                dest = PurePosixPath("projects", pr["name"], *parts[2:])
                data_kind = "project"
        elif parts[0] == "skills" and len(parts) >= 3:
            dest = PurePosixPath(".claude", "skills", slug(parts[1]), *parts[2:])
            data_kind = "skill"
        elif len(parts) == 1 and parts[0] in MEMORY_NAMES:
            dest = PurePosixPath("memory.md")
            data_kind = "root_memory"
        else:
            dest = PurePosixPath("imports", stamp, *parts)       # tasks.md, crons.md, SECRETS.md, the rest
            data_kind = "aside"
        if info.file_size <= SCAN_MAX:
            kinds = backup.scan_bytes(zf.read(info))
            if kinds:                                          # never imported (SECRETS.md must hold names only)
                secrets_found.append({"file": str(p), "kinds": kinds})
                continue
        items.append({"src": info.filename, "dest": str(dest), "kind": data_kind, "size": info.file_size})
    skills = sorted({PurePosixPath(i["dest"]).parts[2] for i in items if i["kind"] == "skill"})
    aside = sorted(str(PurePosixPath(i["dest"]).relative_to(PurePosixPath("imports", stamp)))
                   for i in items if i["kind"] == "aside")
    return {
        "stamp": stamp,
        "projects": [{"name": pr["name"], "exists": pr["exists"],
                      "topics": sorted(pr["topics"].values(), key=lambda t: t["name"])}
                     for pr in sorted(projects.values(), key=lambda x: x["name"])],
        "skills": skills, "aside": aside, "root_memory": any(i["kind"] == "root_memory" for i in items),
        "files": len(items), "size": sum(i["size"] for i in items),
        "skipped": skipped, "secrets": secrets_found, "renamed": renamed, "_items": items,
    }


def _open(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise ImportFailed(400, "bad_zip", "This file is not a valid zip archive") from None


def inspect(path: Path) -> dict[str, Any]:
    with _open(path) as zf:
        plan = _plan(zf)
    plan.pop("_items")
    if not plan["files"]:
        raise ImportFailed(400, "empty", "Nothing to import: the zip has no projects/, skills/ or memory.md")
    return plan


# ---- applying ------------------------------------------------------------------------------
def _section(title: str, body: str) -> str:
    return f"\n\n## {title} ({dt.date.today().isoformat()})\n\n{body.strip()}\n"


def _is_template(p: Path) -> bool:
    """A memory.md nobody wrote in yet (only the generated "# ... - memory" heading)."""
    try:
        lines = [ln for ln in p.read_text(errors="replace").splitlines() if ln.strip()]
    except OSError:
        return True
    return p.name == "memory.md" and all(ln.startswith("#") for ln in lines)


def _free(p: Path) -> Path:
    if not p.exists():
        return p
    n = 1
    while True:
        cand = p.with_name(f"{p.stem} (imported{'' if n == 1 else ' ' + str(n)}){p.suffix}")
        if not cand.exists():
            return cand
        n += 1


def _check_dest(dest: Path, root: Path) -> None:
    """The real place the file would be written stays in the workspace (or its skills folder, which may be a
    link to a shared one): a link already in the workspace must not carry an import elsewhere."""
    real = dest.resolve()
    if not any(real.is_relative_to(b) for b in (root.resolve(), (root / ".claude" / "skills").resolve())):
        raise PermissionError(f"{dest} leads outside the workspace")


def apply(path: Path) -> dict[str, Any]:
    from . import workspace
    workspace.ensure_root()
    root = workspace.root()
    created_projects: list[str] = []
    created_topics: list[str] = []
    written: list[str] = []
    merged: list[str] = []
    renamed_files: list[dict] = []
    skill_dirs: dict[str, str] = {}
    with _open(path) as zf:
        plan = _plan(zf)
        if not plan["files"]:
            raise ImportFailed(400, "empty", "Nothing to import: the zip has no projects/, skills/ or memory.md")
        for pr in plan["projects"]:
            if not (root / "projects" / pr["name"]).is_dir():
                workspace.create_project(pr["name"])
                created_projects.append(pr["name"])
            for t in pr["topics"]:
                if not (root / "projects" / pr["name"] / "topics" / t["name"]).is_dir():
                    workspace.create_topic(pr["name"], t["name"])
                    created_topics.append(f"{pr['name']}/{t['name']}")
        new_levels = {f"projects/{p}" for p in created_projects} | {
            f"projects/{t.split('/')[0]}/topics/{t.split('/')[1]}" for t in created_topics}
        for item in plan["_items"]:
            data = zf.read(item["src"])
            dest = root / item["dest"]
            if item["kind"] == "skill":                      # a whole skill folder: never mixed with an existing one
                name = PurePosixPath(item["dest"]).parts[2]
                if name not in skill_dirs:
                    target = root / ".claude" / "skills" / name
                    n = 1
                    while target.exists():
                        target = target.with_name(f"{name}-imported" + ("" if n == 1 else f"-{n}"))
                        n += 1
                    skill_dirs[name] = target.name
                dest = root / ".claude" / "skills" / skill_dirs[name] / PurePosixPath(*PurePosixPath(item["dest"]).parts[3:])
            try:
                _check_dest(dest, root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.is_dir():
                    raise IsADirectoryError(str(dest))
            except (OSError, ValueError):
                plan["skipped"].append({"file": item["src"],
                                        "reason": "a folder, a file or a link is in the way (not imported)"})
                continue
            rel_parent = str(PurePosixPath(item["dest"]).parent)
            is_md_level = dest.name in ("memory.md", "CLAUDE.md") and item["kind"] in ("project", "topic", "root_memory") \
                and len(PurePosixPath(item["dest"]).parts) in (1, 3, 5)
            text = data.decode("utf-8", errors="replace")
            if is_md_level and dest.exists():
                fresh = rel_parent in new_levels
                if dest.name == "CLAUDE.md":
                    body = text if "@memory.md" in text else text.rstrip() + "\n\n@memory.md\n"
                    if fresh:
                        dest.write_text(body)
                    else:
                        dest.write_text(dest.read_text(errors="replace").rstrip() + _section("Imported instructions", text.replace("@memory.md", "")))
                elif fresh or _is_template(dest):
                    head = dest.read_text(errors="replace").strip()
                    dest.write_text((head + "\n\n" if head else "") + text.strip() + "\n")
                else:
                    dest.write_text(dest.read_text(errors="replace").rstrip() + _section("Imported", text))
                (written if fresh else merged).append(item["dest"])
                continue
            if dest.exists():
                if dest.read_bytes() == data:
                    continue
                new = _free(dest)
                renamed_files.append({"from": item["dest"], "to": str(new.relative_to(root))})
                dest = new
            dest.write_bytes(data)
            written.append(str(dest.relative_to(root)))
    report_dir = root / "imports" / plan["stamp"]
    report_dir.mkdir(parents=True, exist_ok=True)
    report = report_dir / "IMPORT_REPORT.md"
    report.write_text(_report(plan, created_projects, created_topics, written, merged, renamed_files, skill_dirs))
    path.unlink(missing_ok=True)
    bus.invalidate("workspace", "files")
    return {"ok": True, "projects": created_projects, "topics": created_topics, "files": len(written),
            "merged": merged, "renamed": renamed_files, "skills": sorted(skill_dirs.values()),
            "aside": plan["aside"], "secrets": plan["secrets"], "skipped": plan["skipped"],
            "folder": str(report_dir.relative_to(root)), "report": str(report.relative_to(root))}


def _report(plan: dict, projects: list[str], topics: list[str], written: list[str], merged: list[str],
            renamed: list[dict], skills: dict[str, str]) -> str:
    out = [f"# Import of {dt.datetime.now():%Y-%m-%d %H:%M}", "",
           f"- Projects created: {', '.join(projects) or '-'}",
           f"- Topics created: {', '.join(topics) or '-'}",
           f"- Files written: {len(written)}",
           f"- Memory / instructions merged into existing files: {', '.join(merged) or '-'}",
           f"- Skills: {', '.join(sorted(skills.values())) or '-'}"]
    if renamed:
        out += ["", "## Files kept next to an existing one", ""] + [f"- {r['from']} -> {r['to']}" for r in renamed]
    if plan["renamed"]:
        out += ["", "## Names changed to valid folder names", ""] + [f"- {r['from']} -> {r['to']}" for r in plan["renamed"]]
    if plan["aside"]:
        out += ["", "## Kept aside in this folder (to do: tasks, scheduled jobs, keys)", ""] + [f"- {a}" for a in plan["aside"]]
    if plan["secrets"]:
        out += ["", "## Refused: contain a secret (add the keys in Settings -> Keys instead)", ""] + \
               [f"- {s['file']} ({', '.join(s['kinds'])})" for s in plan["secrets"]]
    if plan["skipped"]:
        out += ["", "## Skipped", ""] + [f"- {s['file']}: {s['reason']}" for s in plan["skipped"]]
    return "\n".join(out) + "\n"


FINISH_PROMPT = """An import from my previous agent was just applied. Read {report} first, then finish it with me:
1. Look through the imported memory: merge duplicates into the right memory.md (topic > project > root), \
fix anything contradictory, keep it concise. The sections titled "## Imported" were appended to files that \
already had content.
2. tasks.md (if present in {folder}): create the open tasks in tasks.json (skill maxxing-tasks).
3. crons.md (if present): propose each recurring job as a scheduled job (skill maxxing-cron) - ask me before \
creating or enabling any.
4. SECRETS.md (if present): list the keys I need to add in Settings -> Keys (never ask me to paste them here).
5. Tell me in a few lines what was imported and what is left for me to do."""


def finish_prompt(result: dict[str, Any]) -> str:
    return FINISH_PROMPT.format(report=result.get("report", "imports/"), folder=result.get("folder", "imports/"))
