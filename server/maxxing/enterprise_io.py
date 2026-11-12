"""Enterprise export / import as a zip (GET /api/enterprises/{e}/export, POST /api/enterprises/import, CLI).

Export: enterprise.json (no grants, no agent paths, no envelope key or domain lists), CLAUDE.md, profile.json, files/
(size-capped, secret-scanned) and `agents/<position>.md`, one Claude Code agent file per seated position. Never keys,
vault values, decisions, tasks, inboxes or desk conversations. Import: validates the zip, creates a NEW enterprise
(slug from the zip, `-2` on conflict) with vacant positions and no linked project; the agent files are kept under
`files/imported-agents/` for the owner to hire from.
"""
from __future__ import annotations

import copy
import io
import json
import os
import re
import shutil
import stat
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from . import agents, backup, bodylimit, config, enterprises, importer
from .enterprises import EnterpriseError

MAX_ZIP = bodylimit.IMPORT_MAX          # bytes of the zip itself, on import (the request cap is the same number)
MAX_UNZIPPED = 100 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_TEXT = 1024 * 1024                  # enterprise.json, CLAUDE.md, an agent file
MAX_PROFILE = 64 * 1024
FILE_CAP = 2 * 1024 * 1024              # one file of files/ in an export
FILES_CAP = 20 * 1024 * 1024            # all of files/ in an export
FILES_COUNT = 500
IMPORTED_AGENTS = "imported-agents"     # files/<this>/<position>.md after an import
_AGENT_NAME = re.compile(r"^agents/([a-z0-9][a-z0-9-]{0,47})\.md\Z")


def _bad(code: str, msg: str, status: int = 400) -> EnterpriseError:
    return EnterpriseError(status, code, msg)


# ---- export ----------------------------------------------------------------------------------------------
def _safe_settings(d: dict) -> None:
    """Owner decisions that never travel: the public desk (switches and token) and trust along the chain."""
    s = d.setdefault("settings", {})
    s["trust_chain"] = False
    desk = s.setdefault("desk", {})
    desk["enabled"] = False
    desk["public"] = {**(desk.get("public") if isinstance(desk.get("public"), dict) else {}), "enabled": False, "token": ""}


def _reset_choices(d: dict, skipped: list[dict]) -> None:
    """An import brings no owner choice that widens power or spends money: back to the defaults, each reset listed."""
    dflt = copy.deepcopy(enterprises.DEFAULT_SETTINGS)
    s = d["settings"]

    def reset(where: dict, key: str, label: str) -> None:
        want = dflt["digest"]["enabled"] if key == "digest.enabled" else dflt.get(key)
        cur = where.get("digest", {}).get("enabled") if key == "digest.enabled" else where.get(key)
        if key != "digest.enabled" and key in where and where[key] != want:
            skipped.append({"file": label, "reason": f"{key} reset to its default: set it again if you want it"})
        if key == "digest.enabled" and cur != want:
            skipped.append({"file": label, "reason": "digest reset to its default: set it again if you want it"})
        if key == "digest.enabled":
            where["digest"] = {**where.get("digest", {}), "enabled": want}
        elif key in where:
            where[key] = copy.deepcopy(want)

    for key in ("autonomy", "workers", "communication", "allow", "weekly", "monthly", "digest.enabled"):
        reset(s, key, "settings")
    for dept, row in (d.get("departments") or {}).items():
        st = row.get("settings") if isinstance(row, dict) else None
        if isinstance(st, dict):
            for key in ("autonomy", "workers", "communication", "allow"):
                if key in st:
                    skipped.append({"file": f"department {dept}", "reason": f"{key} reset to its default: set it again if you want it"})
                    st.pop(key)


def _portable(d: dict, slug: str) -> dict:
    """The chart without anything local or sensitive: grants, agent paths, envelope key / domain lists."""
    out = copy.deepcopy(d)
    for k in ("broken", "rev"):
        out.pop(k, None)
    out["id"] = slug
    out["grants"] = []
    _safe_settings(out)
    for p in out["positions"]:
        p["agent"] = None
        p.pop("worker_template", None)
    envs = [out.get("envelope")] + [x.get("envelope") for x in out.get("departments", {}).values()]
    for env in envs:
        if isinstance(env, dict):
            env["keys"] = None
            env["domains"] = None
    return out


def _tool_names(tools: list[str]) -> list[str]:
    """Allowed tool rules ("Edit(./memory.md)", "Bash(maxxing mail:*)") reduced to Claude Code tool names."""
    return list(dict.fromkeys(t.split("(", 1)[0].strip() for t in tools if t.split("(", 1)[0].strip()))


def _role_of(path: str) -> str:
    try:
        text = (agents.folder(path) / "CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [ln for ln in text.splitlines() if not ln.startswith("# Agent") and ln.strip() != "@memory.md"]
    return "\n".join(lines).strip()


def _agent_file(pos: dict, path: str) -> str | None:
    """A Claude Code agent file (front matter name / description / tools / model + the role), None when unusable."""
    if not agents.exists(path):
        return None
    a = agents.load(path)
    role = _role_of(path) or pos["job"] or pos["title"]
    if backup.scan_bytes(role.encode("utf-8")):
        return None
    desc = " ".join((pos["title"] + ": " + (pos["job"] or role)).split())[:300]
    head = ["---", f"name: {pos['id']}", f"description: {json.dumps(desc, ensure_ascii=False)}"]
    tools = _tool_names(a.get("allowed_tools") or [])
    if tools:
        head.append("tools: " + ", ".join(tools))
    head.append(f"model: {a.get('model') or 'inherit'}")
    return "\n".join(head) + "\n---\n\n" + role + "\n"


def _add(z: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, time.localtime()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    z.writestr(info, data)


def _files(root: Path) -> list[tuple[str, bytes]]:
    """Regular files of files/ within the caps, without junk, symlinks or anything that looks like a secret."""
    out: list[tuple[str, bytes]] = []
    total = 0
    if not root.is_dir():
        return out
    for cur, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(x for x in dirs if x not in importer.JUNK_PARTS and not Path(cur, x).is_symlink())
        for n in sorted(names):
            f = Path(cur, n)
            rel = f.relative_to(root).as_posix()
            if n in importer.JUNK_PARTS or f.is_symlink() or importer._claude_config(PurePosixPath(rel)):
                continue
            try:
                if f.stat().st_size > FILE_CAP:
                    continue
                data = f.read_bytes()
            except OSError:
                continue
            if total + len(data) > FILES_CAP or len(out) >= FILES_COUNT or backup.scan_bytes(data):
                continue
            total += len(data)
            out.append((rel, data))
    return out


def export_zip(slug: str) -> bytes:
    d = enterprises.load(slug)
    if d.get("broken"):
        raise _bad("broken", "enterprise.json cannot be read: fix it before exporting", 409)
    root = enterprises.folder(slug)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        _add(z, "enterprise.json", (json.dumps(_portable(d, slug), indent=2, ensure_ascii=False) + "\n").encode())
        for name in ("CLAUDE.md", enterprises.PROFILE_FILE):
            f = root / name
            try:
                data = f.read_bytes()
            except OSError:
                continue
            if len(data) <= MAX_TEXT and not backup.scan_bytes(data):
                _add(z, name, data)
        for rel, data in _files(root / "files"):
            _add(z, "files/" + rel, data)
        for p in d["positions"]:
            if p["agent"]:
                text = _agent_file(p, p["agent"])
                if text:
                    _add(z, f"agents/{p['id']}.md", text.encode("utf-8"))
    return buf.getvalue()


# ---- import ----------------------------------------------------------------------------------------------
def _entries(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Validated entries by safe path; anything unexpected refuses the whole zip (nothing is written yet)."""
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_ENTRIES:
        raise _bad("too_many_files", f"More than {MAX_ENTRIES} files in the zip", 413)
    if sum(i.file_size for i in infos) > MAX_UNZIPPED:
        raise _bad("too_big", f"More than {MAX_UNZIPPED // 1024 // 1024} MB once unzipped", 413)
    out: dict[str, zipfile.ZipInfo] = {}
    for i in infos:
        raw = i.filename.replace("\\", "/")
        p = PurePosixPath(raw)
        if p.is_absolute() or ".." in p.parts or not p.parts or re.match(r"^[A-Za-z]:", raw):
            raise _bad("unsafe_path", f"Unsafe path in the zip: {i.filename!r}")
        if stat.S_ISLNK(i.external_attr >> 16):
            raise _bad("symlink", f"A symbolic link in the zip: {i.filename!r}")
        if any(part in importer.JUNK_PARTS for part in p.parts):
            continue
        if importer._claude_config(p):
            raise _bad("claude_config", f"Claude Code settings are never imported: {i.filename!r}")
        name = p.as_posix()
        top = p.parts[0]
        if name in ("enterprise.json", "CLAUDE.md", enterprises.PROFILE_FILE) or _AGENT_NAME.match(name) \
                or (top == "files" and len(p.parts) > 1):
            out[name] = i
        else:
            raise _bad("unexpected_file", f"Unexpected file in the zip: {i.filename!r}")
    if "enterprise.json" not in out:
        raise _bad("not_an_export", "Not an enterprise export: enterprise.json is missing")
    return out


def _read(zf: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int) -> bytes:
    if info.file_size > cap:
        raise _bad("too_big", f"{info.filename!r} is larger than {cap // 1024} KB" if cap < 1 << 20 else
                   f"{info.filename!r} is larger than {cap // 1024 // 1024} MB", 413)
    try:
        return zf.read(info)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError, ValueError):
        raise _bad("bad_zip", f"Cannot read {info.filename!r} (damaged or encrypted)") from None


def _free_slug(base: str) -> str:
    n = 1
    while True:
        cand = base if n == 1 else f"{base[:48 - len(str(n)) - 1].rstrip('-')}-{n}"
        if not enterprises.folder(cand).exists() and cand not in enterprises.RESERVED:
            return cand
        n += 1


def _confine(root: Path, rel: str) -> Path:
    dest = (root / rel).resolve()
    if root.resolve() not in dest.parents:
        raise _bad("unsafe_path", f"Unsafe path in the zip: {rel!r}")
    return dest


def import_zip(data: bytes) -> dict:
    if len(data) > MAX_ZIP:
        raise _bad("too_big", f"The zip is larger than {MAX_ZIP // 1024 // 1024} MB", 413)
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError):
        raise _bad("bad_zip", "Not a zip file") from None
    with zf:
        entries = _entries(zf)
        raw = _read(zf, entries["enterprise.json"], MAX_TEXT)
        if backup.scan_bytes(raw):
            raise _bad("secret_found", "enterprise.json contains something that looks like a secret")
        try:
            src = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise _bad("not_an_export", "enterprise.json is not valid JSON") from None
        if not isinstance(src, dict):
            raise _bad("not_an_export", "enterprise.json is not an object")
        want = src.get("id")
        base = want if isinstance(want, str) and enterprises._slug_ok(want) else importer.slug(str(src.get("name") or ""))
        d = enterprises.clean(src)
        d.pop("id", None)
        d.update(rev=1, projects=[], grants=[])
        _safe_settings(d)
        skipped: list[dict] = []
        _reset_choices(d, skipped)
        for p in d["positions"]:
            p["agent"] = None
            if p.pop("worker_template", None):
                skipped.append({"file": f"position {p['id']}", "reason": "worker template: approve it again"})
        enterprises._check_tree(d)
        blobs: list[tuple[str, bytes]] = []
        for name, info in entries.items():
            if name == "enterprise.json":
                continue
            if name == "CLAUDE.md" or _AGENT_NAME.match(name):
                body = _read(zf, info, MAX_TEXT)
            elif name == enterprises.PROFILE_FILE:
                body = _read(zf, info, MAX_PROFILE)
                try:
                    ok = isinstance(json.loads(body.decode("utf-8")), dict)
                except (ValueError, UnicodeDecodeError):
                    ok = False
                if not ok:
                    skipped.append({"file": name, "reason": "not a JSON object"})
                    continue
            else:
                body = _read(zf, info, FILE_CAP)
            if backup.scan_bytes(body):
                skipped.append({"file": name, "reason": "looks like a secret"})
                continue
            rel = f"files/{IMPORTED_AGENTS}/{name[7:]}" if name.startswith("agents/") else name
            blobs.append((rel, body))
    with enterprises._lock:
        if len(enterprises.names()) >= enterprises.MAX_ENTERPRISES:
            raise _bad("too_many", f"At most {enterprises.MAX_ENTERPRISES} enterprises")
        slug = _free_slug(base)
        root = enterprises.folder(slug)
        root.mkdir(parents=True)
        try:
            (root / "files").mkdir(exist_ok=True)
            if not any(r == "CLAUDE.md" for r, _ in blobs):
                (root / "CLAUDE.md").write_text(f"# Enterprise {d['name'] or slug}\n\n", encoding="utf-8")
            for rel, body in sorted(blobs, key=lambda b: b[0].startswith("files/" + IMPORTED_AGENTS)):
                dest = _confine(root, rel)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(body)
            shutil.rmtree(enterprises._peek(slug), ignore_errors=True)
            config.write_json(root / enterprises.FILE, d)
        except BaseException:                           # a half-made folder would keep the name taken
            shutil.rmtree(root, ignore_errors=True)
            raise
        enterprises.log(slug, "structure", "Enterprise imported from a zip (positions vacant, no project linked)")
    enterprises.invalidate(slug)
    return {**enterprises.get(slug), "skipped": skipped}
