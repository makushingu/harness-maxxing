"""Import the memory of another agent (Hermes, Claude Code, OpenClaw...) from a zip.

The user copies PROMPT (or `prompt(agent)`) into their old agent, which builds this tree and zips it:

    memory.md                                   who the user is, preferences, global facts
    projects/<project>/CLAUDE.md, memory.md     what the project is / its facts and decisions
    projects/<project>/topics/<topic>/CLAUDE.md, memory.md, any useful files
    skills/<name>/SKILL.md (+ files)            reusable procedures (also read in skills/<category>/<name>/)
    tasks.md, crons.md, SECRETS.md, anything else   kept aside in imports/<stamp>/ for Claude

Flow: `inspect(zip)` -> preview (what will be created / merged / skipped) -> `apply(zip)`.
Nothing is ever overwritten: an existing memory.md / CLAUDE.md gets an "## Imported" section
appended, another existing file is written as "<name> (imported).<ext>", an existing skill folder
as "<name>-imported". Files that contain a secret-shaped string are skipped (reported by kind,
never by value): keys go to Settings -> Keys. Claude Code settings are never imported either: under
`.claude/` only skills and Markdown notes are kept, not hooks, `.mcp.json`, sub-agents (`.claude/agents/`)
or commands (`.claude/commands/`). A report is written in imports/<stamp>/IMPORT_REPORT.md.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import lzma
import re
import secrets as _secrets
import shutil
import stat
import threading
import time
import unicodedata
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any

from . import bus, config

MAX_FILES = 20000
MAX_TOTAL = 500 * 1024 * 1024          # uncompressed
MAX_FILE = 100 * 1024 * 1024
SCAN_MAX = 5 * 1024 * 1024             # files scanned for secrets (larger: binary data, kept)
TEXT_EXT = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".env", ".cfg", ".ini", ".csv", ".log",
                      ".py", ".js", ".ts", ".sh", ".html", ".xml", ".jsonl"})   # text over SCAN_MAX is refused, not kept unchecked
SCAN_TOTAL = 50 * 1024 * 1024          # bytes scanned per zip; files past it are not imported
JUNK_PARTS = {"__MACOSX", ".git", "node_modules", ".venv", "venv", "__pycache__", ".DS_Store", "Thumbs.db"}
# Harness's own folder settings (a topic's permission mode, the project order): set in the app, never by an export.
FOLDER_SETTINGS = {".maxxing.json", ".order.json"}
MEMORY_NAMES = {"memory.md", "MEMORY.md", "USER.md", "user.md"}
UPLOAD_TTL = 24 * 3600

AGENTS = ("hermes", "claude-code", "openclaw", "other")
HINTS = {
    "hermes": "You are Hermes Agent: everything is in ~/.hermes/ (or ~/.hermes/profiles/<name>/ when I use a "
              "profile). Read SOUL.md, memories/MEMORY.md and memories/USER.md, the skills written for me in "
              "skills/, my scheduled jobs (`hermes cron list`, cron/jobs.json) and what our past sessions "
              "(state.db, sessions/) say about my projects. Never copy .env or auth.json.",
    "claude-code": "You are Claude Code: read every CLAUDE.md and memory file you use (~/.claude/CLAUDE.md, "
                   "the project folders, ~/.claude/projects/*/memory/), your skills (~/.claude/skills/, "
                   ".claude/skills/) and anything the user keeps notes in.",
    "openclaw": "You are OpenClaw: read your workspace (by default ~/.openclaw/workspace/: AGENTS.md, SOUL.md, "
                "USER.md, IDENTITY.md, TOOLS.md, HEARTBEAT.md, MEMORY.md, memory/*.md, skills/), the skills I "
                "added in ~/.openclaw/skills/ and my scheduled jobs (they are not in the workspace: list them "
                "with your cron tool or `openclaw cron list`). Never copy openclaw.json or credentials/.",
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
- Write in the language I use with you. Only the file and folder names above stay as they are.
- Skills: only the procedures written for me or for my work, one folder per skill directly under `skills/` -
  not the stock skills that came with you.
- NEVER write a secret value (API key, token, password, cookie, private key) anywhere - only their names
  in SECRETS.md. Files containing secrets will be refused by the import.
- Leave out huge data, caches, media and generated files (keep the zip under 50 MB).
- Then zip it: `cd <parent> && zip -r harness-maxxing-export.zip harness-maxxing-export` (no `zip` command:
  `python3 -m zipfile -c harness-maxxing-export.zip harness-maxxing-export`) and give me the file, or its
  full path. Finish with a short summary: how many projects, topics and skills.
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
EMPTY = ("Nothing to import: the zip has no projects/, skills/ or memory.md (Claude Code settings, sub-agents "
         "and commands are never imported)")


def _claude_config(p: PurePosixPath) -> bool:
    """Claude Code configuration in the export (`.claude/settings.json` with hooks, hook scripts,
    `.mcp.json`): it would run commands in every session of that folder. Under `.claude/` only skills
    and Markdown notes are kept - not `agents/` and `commands/`, whose `.md` files are Claude Code
    sub-agents and slash commands (their own prompt and allowed tools), not notes."""
    parts = p.parts
    if ".mcp.json" in parts:
        return True
    return any(part == ".claude" and parts[k + 1:k + 2] != ("skills",)
               and (p.suffix.lower() != ".md" or parts[k + 1:k + 2] in (("agents",), ("commands",)))
               for k, part in enumerate(parts))


def _entries(zf: zipfile.ZipFile) -> tuple[list[tuple[zipfile.ZipInfo, PurePosixPath]], list[dict]]:
    """Safe file entries (path inside the export) + skipped ones {file, reason}."""
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_FILES:
        raise ImportFailed(413, "too_many_files", f"More than {MAX_FILES} files in the zip")
    if sum(i.file_size for i in infos) > MAX_TOTAL:
        raise ImportFailed(413, "too_big", f"More than {MAX_TOTAL // 1024 // 1024} MB once unzipped")
    if len({i.filename for i in infos}) != len(infos):
        # the scan and the write both go by name: a second entry of the same name would be written unscanned
        raise ImportFailed(400, "bad_zip", "This zip has two files with the same name")
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
    # the export folder at the top ("harness-maxxing-export/...") is stripped, and the folders above it when
    # the zip was made from higher up ("out/harness-maxxing-export/...")
    # (how many in one pass, then each path cut once: a zip nested 1000 deep cost files x depth^2 before)
    k = 0
    while ok:
        first = ok[0][1].parts
        if len(first) <= k + 1 or first[k] in ("projects", "skills"):
            break
        if any(len(p.parts) <= k + 1 or p.parts[k] != first[k] for _, p in ok):
            break
        k += 1
    if k:
        ok = [(i, PurePosixPath(*p.parts[k:])) for i, p in ok]
    return ok, skipped


def _plan(zf: zipfile.ZipFile, scans: dict[str, list[str] | None]) -> dict[str, Any]:
    """What the import would do, without writing anything. `scans` (zip name -> secret kinds,
    None = over SCAN_TOTAL) is filled in and reused, so applying does not scan the zip again."""
    from . import backup, workspace
    entries, skipped = _entries(zf)
    scanned = 0
    root = workspace.root()
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + _secrets.token_hex(2)    # two imports in one second never share a folder
    projects: dict[str, dict] = {}
    skills: dict[str, dict] = {}
    items: list[dict] = []
    secrets_found: list[dict] = []
    renamed: list[dict] = []
    memo: dict[tuple, str] = {}                  # (names in use, slug, source) -> name already given
    next_n: dict[tuple, int] = {}                # (names in use, slug) -> first "-N" not tried yet

    def unique(raw: str, taken: dict[str, dict], on_disk: Path, source: str = "") -> str:
        """Each source folder gets its own name: "Блог" and "Продажи" (or "My Blog" and "my-blog") both slug
        to one name, and the second CLAUDE.md would overwrite the first. Only the plain name merges into a folder
        already in `on_disk`: a "-2" picked here never lands in an unrelated existing one. `source` tells two
        folders of the same name apart (skills in two categories)."""
        base = name = slug(raw)
        key = (id(taken), base, source or raw)
        if key in memo and memo[key] in taken:
            return memo[key]
        n = next_n.get((id(taken), base), 2) if name in taken or (on_disk / name).exists() else 2
        while ((name in taken and taken[name]["source"] != (source or raw))
               or (name != base and name not in taken and (on_disk / name).exists())):
            name = f"{base[:44].rstrip('-')}-{n}"
            n += 1
        if name != base:
            next_n[(id(taken), base)] = n
        memo[key] = name
        return name

    def proj(raw: str) -> dict:
        name = unique(raw, projects, root / "projects")
        if name not in projects:
            projects[name] = {"name": name, "source": raw, "exists": (root / "projects" / name).is_dir(), "topics": {}}
            if name != raw:
                renamed.append({"from": raw, "to": name})
        return projects[name]

    # a skill is the folder that holds SKILL.md: Hermes sorts its skills in categories (skills/<category>/<name>/)
    skill_roots = {p.parts[1:-1] for _, p in entries
                   if p.parts[0] == "skills" and len(p.parts) >= 3 and p.name == "SKILL.md"}

    def skill_root(parts: tuple[str, ...]) -> tuple[str, ...] | None:
        """The skill folder of this file (path under skills/), None when it is in a category but in no skill."""
        inside = parts[1:-1]
        for n in range(1, len(inside) + 1):
            if inside[:n] in skill_roots:
                return inside[:n]
        return None if any(r[0] == parts[1] for r in skill_roots) else inside[:1]

    for info, p in entries:
        parts = p.parts
        data_kind = "file"
        name_b = info.filename.encode("utf-8", "replace")
        if name_kinds := sorted({kind for kind, rx in backup.LEAKS if rx.search(name_b)}):
            # a secret in the NAME of a file would be written to the disk, the report and the API answer
            secrets_found.append({"file": "(name hidden: it holds a secret)", "kinds": name_kinds})
            continue
        if parts[0] == "projects" and len(parts) >= 6 and parts[2] == "topics" and parts[4] == "agents":
            # an agent runs by itself (triggers, permissions): never planted by an import, created in Harness
            skipped.append({"file": info.filename, "reason": "agent folder (not imported: create agents in Harness)"})
            continue
        if parts[0] == "projects" and len(parts) >= 3:
            pr = proj(parts[1])
            if parts[2] == "topics" and len(parts) >= 5:
                tname = unique(parts[3], pr["topics"], root / "projects" / pr["name"] / "topics")
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
        elif parts[0] == "skills" and len(parts) >= 3 and (sroot := skill_root(parts)):
            sname = unique(sroot[-1], skills, root / ".claude" / "skills", "/".join(sroot))
            skills.setdefault(sname, {"source": "/".join(sroot)})
            dest = PurePosixPath(".claude", "skills", sname, *parts[1 + len(sroot):])
            data_kind = "skill"
        elif parts[-1] in MEMORY_NAMES and (len(parts) == 1 or parts[:-1] == ("memories",)):
            # at the root, or in memories/ (where Hermes keeps MEMORY.md and USER.md)
            dest = PurePosixPath("memory.md")
            data_kind = "root_memory"
        else:
            dest = PurePosixPath("imports", stamp, *parts)       # tasks.md, crons.md, SECRETS.md, the rest
            data_kind = "aside"
        if info.file_size > SCAN_MAX and p.suffix.lower() in TEXT_EXT:
            skipped.append({"file": info.filename,
                            "reason": f"text file over {SCAN_MAX // 1024 // 1024} MB (cannot be checked for secrets)"})
            continue
        if info.file_size <= SCAN_MAX:
            if info.filename not in scans:
                if scanned + info.file_size > SCAN_TOTAL:
                    scans[info.filename] = None
                else:
                    scanned += info.file_size
                    scans[info.filename] = backup.scan_bytes(zf.read(info))
            kinds = scans[info.filename]
            if kinds is None:                                  # unchecked: it could hold a secret
                skipped.append({"file": info.filename,
                                "reason": f"not checked for secrets (over {SCAN_TOTAL // 1024 // 1024} MB to check)"})
                continue
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
    except (zipfile.BadZipFile, OSError, ValueError):       # ValueError: an entry name that is not valid UTF-8
        raise ImportFailed(400, "bad_zip", "This file is not a valid zip archive") from None


_SCANS: dict[tuple, dict[str, list[str] | None]] = {}
_SCANS_LOCK = threading.Lock()


def _scans(path: Path) -> dict[str, list[str] | None]:
    """Secret scan results of this upload, kept while the file is unchanged (inspect, then apply)."""
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (str(path), st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)
    with _SCANS_LOCK:
        if key not in _SCANS:
            while len(_SCANS) >= 8:
                del _SCANS[next(iter(_SCANS))]
            _SCANS[key] = {}
        return _SCANS[key]


# zf.read() of an encrypted (RuntimeError, NotImplementedError) or damaged (BadZipFile: bad CRC, zlib.error,
# EOFError) entry
_UNREADABLE = (zipfile.BadZipFile, RuntimeError, zlib.error, EOFError, OSError, lzma.LZMAError, NotImplementedError)


def _unreadable() -> ImportFailed:
    return ImportFailed(400, "bad_zip", "A file of the zip cannot be read (encrypted or damaged)")


def inspect(path: Path) -> dict[str, Any]:
    try:
        with _open(path) as zf:
            plan = _plan(zf, _scans(path))
    except _UNREADABLE:
        raise _unreadable() from None
    plan.pop("_items")
    if not plan["files"]:
        raise ImportFailed(400, "empty", EMPTY)
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
        tag = f" (imported{'' if n == 1 else ' ' + str(n)}){p.suffix}"
        room = max(255 - len(tag.encode()), 1)               # a file name is at most 255 bytes
        stem = p.stem.encode()[:room].decode(errors="ignore")
        cand = p.with_name(f"{stem}{tag}")
        if not cand.exists():
            return cand
        n += 1


def _check_dest(dest: Path, root: Path) -> None:
    """The real place the file would be written stays in the workspace (or its skills folder, which may be a
    link to a shared one): a link already in the workspace must not carry an import elsewhere."""
    real = dest.resolve()
    if not any(real.is_relative_to(b) for b in (root.resolve(), (root / ".claude" / "skills").resolve())):
        raise PermissionError(f"{dest} leads outside the workspace")


_APPLY_LOCK = threading.Lock()


_IMPORT_REF_RE = re.compile(r"(?<!\S)@(?!memory\.md(?!\S))(?=[~/.\w])(?=\S*[~/.])\S*")


def _defang_imports(text: str) -> str:
    """Claude Code loads `@path` in a CLAUDE.md / memory.md into the context: an imported file must not pull in
    another file of this server (a key, a credential). The reference stays readable, in a code span."""
    return _IMPORT_REF_RE.sub(lambda m: f"`{m.group(0)}`", text)


def _strip_skill_hooks(text: str) -> str:
    """Remove the `hooks:` field of the front matter of a SKILL.md: a hook runs a command by itself."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return text
    out, skipping = [lines[0]], False
    for ln in lines[1:end]:
        if re.match(r"hooks\s*:", ln):
            skipping = True
            continue
        if skipping and (not ln.strip() or ln[:1] in (" ", "\t", "-")):
            continue
        skipping = False
        out.append(ln)
    return "\n".join(out + lines[end:])


def apply(path: Path) -> dict[str, Any]:
    """One import applied at a time (a double click on Apply raced on the projects and topics it creates)."""
    from . import workspace
    if not _APPLY_LOCK.acquire(blocking=False):
        raise ImportFailed(409, "busy", "An import is already being applied")
    try:
        if not path.is_file():
            raise ImportFailed(404, "not_found", "This upload expired - send the zip again")
        return _apply(path)
    except workspace.WorkspaceError as e:
        raise ImportFailed(409, "conflict", str(e)) from None
    finally:
        _APPLY_LOCK.release()


def _apply(path: Path) -> dict[str, Any]:
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
        try:
            plan = _plan(zf, _scans(path))
        except _UNREADABLE:
            raise _unreadable() from None
        if not plan["files"]:
            raise ImportFailed(400, "empty", EMPTY)
        try:
            for item in plan["_items"]:                      # big files are not read by the plan: check them before any write
                if item["size"] > SCAN_MAX:
                    with zf.open(item["src"]) as src:
                        while src.read(1024 * 1024):
                            pass
        except _UNREADABLE:
            raise _unreadable() from None
        try:
            for pr in plan["projects"]:
                if not (root / "projects" / pr["name"]).is_dir():
                    workspace.create_project(pr["name"])
                    created_projects.append(pr["name"])
                for t in pr["topics"]:
                    if not (root / "projects" / pr["name"] / "topics" / t["name"]).is_dir():
                        workspace.create_topic(pr["name"], t["name"])
                        created_topics.append(f"{pr['name']}/{t['name']}")
        except Exception:                                    # a topic that cannot be made: no half-created project is left behind
            for t in reversed(created_topics):
                with contextlib.suppress(Exception):
                    workspace.delete_topic(*t.split("/"))
            for name in reversed(created_projects):
                with contextlib.suppress(Exception):
                    workspace.delete_project(name)
            raise
        new_levels = {f"projects/{p}" for p in created_projects} | {
            f"projects/{t.split('/')[0]}/topics/{t.split('/')[1]}" for t in created_topics}
        for item in plan["_items"]:
            try:
                data = zf.read(item["src"])
            except _UNREADABLE:
                raise _unreadable() from None
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
            if item["kind"] == "skill" and dest.name.lower() == "skill.md":
                data = _strip_skill_hooks(data.decode("utf-8", errors="replace")).encode("utf-8")
            elif dest.name in ("CLAUDE.md", "memory.md"):
                data = _defang_imports(data.decode("utf-8", errors="replace")).encode("utf-8")
            rel_parent = str(PurePosixPath(item["dest"]).parent)
            is_md_level = dest.name in ("memory.md", "CLAUDE.md") and item["kind"] in ("project", "topic", "root_memory") \
                and len(PurePosixPath(item["dest"]).parts) in (1, 3, 5)
            text = data.decode("utf-8", errors="replace")
            if is_md_level and dest.exists():
                fresh = rel_parent in new_levels
                if dest.name == "CLAUDE.md":
                    body = text if "@memory.md" in text else text.rstrip() + "\n\n@memory.md\n"
                    if fresh:
                        # the text under the first "# " heading is the description shown in the app: without a
                        # heading in the imported file, the generated one ("# Topic blog") stays above it
                        head = dest.read_text(errors="replace").splitlines()[:1]
                        if head and head[0].startswith("# ") and not re.search(r"^# ", text, re.M):
                            body = head[0] + "\n\n" + body.lstrip()
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
