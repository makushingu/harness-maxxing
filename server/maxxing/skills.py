"""The skills Claude Code sees from this install, read-only (Settings -> Skills, 2.0.0a132).

Where they live, from the widest to the narrowest:
  product    ~/.claude/skills/<name> copied by `maxxing init` (overwritten by every update: read-only in the UI)
  user       ~/.claude/skills/<name>, the others (every session of this server)
  workspace  <workspace>/.claude/skills/<name>
  project    <workspace>/projects/<p>/.claude/skills/<name>
  topic      <workspace>/projects/<p>/topics/<t>/.claude/skills/<name>
Only the front matter of each SKILL.md is read (name, description, disable-model-invocation); nothing is written.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import workspace

_HEAD = 6000                                   # the front matter is at the top; never read a whole big file
_FIELD = re.compile(r"^([\w-]+):[ \t]*(.*)$")


def _front(text: str) -> dict[str, str]:
    """`key: value` pairs of the front matter (a value may go on over indented or folded lines)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    body = text[3:end if end > 0 else len(text)]
    out: dict[str, str] = {}
    key = ""
    for line in body.splitlines():
        m = _FIELD.match(line)
        if m:
            key = m.group(1)
            out[key] = m.group(2).strip()
        elif key and line[:1] in (" ", "\t"):
            out[key] = f"{out[key]} {line.strip()}".strip()
    for k, v in out.items():
        v = re.sub(r"^[|>][-+]?", "", v).strip()                  # a block scalar header: | |- |+ > >- >+
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k] = " ".join(v.split())
    return out


def _read(folder: Path, origin: str, **where: str) -> dict | None:
    f = folder / "SKILL.md"
    try:
        with f.open(encoding="utf-8", errors="replace") as fh:
            head = fh.read(_HEAD)
    except OSError:
        return None
    meta = _front(head)
    return {
        "name": meta.get("name") or folder.name,
        "folder": folder.name,
        "description": meta.get("description", "")[:600],
        "origin": origin,
        "path": str(f),
        "hidden": meta.get("disable-model-invocation", "").lower() == "true",  # only started by /name
        **where,
    }


def _utf8(p: Path) -> bool:
    """A folder name that is not UTF-8 (surrogates) cannot be sent as JSON: it is left out."""
    try:
        p.name.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def _scan(root: Path, origin: str, skip: set[str] | None = None, **where: str) -> list[dict]:
    try:
        folders = sorted(p for p in root.iterdir() if _utf8(p) and p.is_dir() and (p / "SKILL.md").is_file())
    except OSError:
        return []
    out = []
    for p in folders:
        if skip and p.name in skip:
            continue
        s = _read(p, origin, **where)
        if s:
            out.append(s)
    return out


def list_skills() -> list[dict]:
    from .cmd_core import product_skill_names, skills_target
    product = set(product_skill_names())
    user_root = skills_target()
    out = [s for s in _scan(user_root, "product") if s["folder"] in product]
    out += _scan(user_root, "user", skip=product)
    ws = workspace.root()
    out += _scan(ws / ".claude" / "skills", "workspace")
    projects = ws / "projects"
    try:
        pdirs = sorted(p for p in projects.iterdir() if _utf8(p) and p.is_dir() and not p.name.startswith("."))
    except OSError:
        pdirs = []
    for p in pdirs:
        out += _scan(p / ".claude" / "skills", "project", project=p.name)
        try:
            tdirs = sorted(t for t in (p / "topics").iterdir() if _utf8(t) and t.is_dir() and not t.name.startswith("."))
        except OSError:
            tdirs = []
        for t in tdirs:
            out += _scan(t / ".claude" / "skills", "topic", project=p.name, topic=t.name)
    return out


def for_topic(path: str) -> list[dict]:
    """The skills a session of the topic `path` (`projects/<p>/topics/<t>`, or a project, or "" = the workspace) can
    start with /name: the server's, the workspace's, its project's and its own (the slash menu of the composer)."""
    parts = (path or "").strip("/").split("/")
    project = parts[1] if len(parts) >= 2 and parts[0] == "projects" else None
    topic = parts[3] if len(parts) >= 4 and parts[2] == "topics" else None
    return [s for s in list_skills() if s["origin"] in ("product", "user", "workspace")
            or (project is not None and s.get("project") == project and (s["origin"] == "project" or s.get("topic") == topic))]

