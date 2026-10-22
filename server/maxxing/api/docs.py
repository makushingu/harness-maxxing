"""In-app documentation from docs/user/*.md. See docs/dev/API.md#docs.

File name `NN-slug.md` -> order NN, slug `slug`. Title = first `# ` heading. Optional front
matter at the very top:
    ---
    section: Getting started
    ---
The list of every update is not a docs page: it is Settings -> Updates (GET /api/system/changelog).
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from .. import config
from ..security import require_auth

router = APIRouter(prefix="/api/docs", tags=["docs"], dependencies=[Depends(require_auth)])

_NAME = re.compile(r"^(\d+)-([a-z0-9][a-z0-9-]*)\.md$")
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
DEFAULT_SECTION = "General"


def _parse(path: Path) -> dict | None:
    m = _NAME.match(path.name)
    if m:
        order, slug = int(m.group(1)), m.group(2)
    elif re.fullmatch(r"[a-z0-9][a-z0-9-]*\.md", path.name):
        order, slug = 9999, path.stem
    else:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    meta: dict[str, str] = {}
    fm = _FRONT.match(text)
    if fm:
        for line in fm.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep:
                meta[k.strip().lower()] = v.strip().strip("\"'")
        text = text[fm.end():]
    title = meta.get("title") or next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), "")
    return {"slug": slug, "title": title or slug.replace("-", " ").capitalize(),
            "section": meta.get("section") or DEFAULT_SECTION, "order": order, "markdown": text}


_cache: tuple[tuple, list[dict]] | None = None


def all_docs() -> list[dict]:
    """Every page, parsed once per version of the folder (names, mtimes, sizes): the list, each page and the
    full-text search all read it."""
    global _cache
    d = config.DOCS_DIR
    if not d.is_dir():
        return []
    files = sorted(p for p in d.glob("*.md") if p.is_file())
    try:
        sig = (str(d), *((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files))
    except OSError:
        sig = None
    if sig is not None and _cache and _cache[0] == sig:
        return _cache[1]
    docs = [x for x in (_parse(p) for p in files) if x]
    docs.sort(key=lambda x: (x["order"], x["slug"]))
    seen, out = set(), []
    for x in docs:                                   # first file wins on duplicate slugs
        if x["slug"] not in seen:
            seen.add(x["slug"])
            out.append(x)
    if sig is not None:
        _cache = (sig, out)
    return out


@router.get("")
def list_docs(full: bool = False):
    """`?full=1`: every page with its markdown, in one response (the docs full-text search)."""
    keys = ("slug", "title", "section", "order", "markdown") if full else ("slug", "title", "section", "order")
    return [{k: x[k] for k in keys} for x in all_docs()]


@router.get("/{slug}")
def get_doc(slug: str):
    for x in all_docs():
        if x["slug"] == slug:
            return {"slug": x["slug"], "title": x["title"], "markdown": x["markdown"]}
    raise HTTPException(404, detail={"error": "not_found", "message": f"no page {slug}"})
