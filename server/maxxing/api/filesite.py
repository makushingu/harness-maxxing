"""HTML pages rendered with their relative assets: GET /api/files/site/<token>/<relative path>.

/api/files/site-url (signed in) hands out a token valid SITE_TTL_S. This router has no cookie check: the token is
the permission. Its scope:
- by default the folder of the HTML file, but ONLY static web assets in that folder tree (`ASSETS`: pages, styles,
  scripts, wasm, pictures, fonts, audio/video) - never notes, data, documents, code or settings (.md, .json, .txt,
  .csv, .pdf, .yaml, .py, .env...): a page's scripts can read whatever its link serves, and anyone the page hands its
  own link to can too. From a topic's `attachments/` folder, pictures and media only;
- the HTML file alone when that folder is too broad - the files root, the home directory, `/`, a folder that is itself
  under a dot folder, the workspace root, `projects/`, a project or its `topics/` folder, a topic's uploads;
- never a dotfile or anything under a dot folder (.ssh, .claude, .env...), never outside files_root.
A token carries its issue time and the id of the session that asked for it: it dies when that session signs out,
when every session is signed out (`sessions_not_before`, also set when the revocation list overflows) and when the
password changes (new signing key). Every response carries `Content-Security-Policy: sandbox`
without allow-same-origin, so the page and its scripts run in an opaque origin: they cannot use the
UI session, read API responses (no CORS) or send the CSRF header.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import FileResponse

from .. import config, security
from .files import SITE_TTL_S, _err, _inside, _mime, _root

router = APIRouter(prefix="/api/files/site", tags=["files"])

SANDBOX = ("sandbox allow-scripts allow-popups allow-forms allow-modals "
           "allow-downloads; frame-ancestors 'self'")


def _sign(payload: bytes) -> str:
    return hmac.new(security._cookie_key(), b"site|" + payload, hashlib.sha256).hexdigest()[:32]


# What a page may load next to it (folder tokens): static web assets only. Data and documents (.json, .csv, .txt, .md,
# .pdf, .xml...) are left out on purpose: a folder holding a page often holds private notes or exports too, and a
# page's scripts (or whoever it sends its link to) can read whatever the link serves.
MEDIA = frozenset("""svg png jpg jpeg gif webp avif ico bmp heic mp4 webm mov m4v ogv mkv mp3 wav ogg oga opus m4a
aac flac""".split())
ASSETS = MEDIA | frozenset("html htm css js mjs wasm woff woff2 ttf otf eot".split())

def _workspace_roots() -> set[Path]:
    """Workspace folders that hold everything of a project / of all projects: a page there gets its file alone."""
    ws = config.workspace().resolve()
    out = {ws, ws / "projects", ws / "extensions"}
    try:
        for proj in (ws / "projects").iterdir():
            out |= {proj.resolve(), (proj / "topics").resolve()}

    except OSError:
        pass
    return out


def _single_file(folder: Path) -> bool:
    """A page whose folder is this broad only gets its own file (see the module docstring)."""
    f = folder.resolve()
    if f in (_root(), Path.home().resolve(), Path("/")) or f in _workspace_roots():
        return True
    if "attachments" in f.parts and config.workspace().resolve() in f.parents:
        return True                                       # a page among a topic's uploads: one file, no neighbours
    return any(part.startswith(".") for part in f.parts)


def make_token(folder: Path, ttl: int = SITE_TTL_S, file: str | None = None, session: str | None = None) -> str:
    data: dict = {"d": str(folder), "e": int(time.time()) + ttl, "i": int(time.time())}
    if file:
        data["f"] = file
    if session:
        data["s"] = session                       # signing out (that cookie revoked) ends the link too
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{payload}.{_sign(payload.encode())}"


def read_token(token: str) -> tuple[Path, str | None] | None:
    """-> (folder, single file name or None) of a valid token."""
    payload, _, sig = token.partition(".")
    try:
        if not payload or not hmac.compare_digest(sig.encode(), _sign(payload.encode()).encode()):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("d"), str) or data.get("e", 0) < time.time():
        return None
    if data.get("s") and security.session_revoked(str(data["s"])):
        return None
    if not _issued_after_sign_out(data.get("i")):
        return None
    return Path(data["d"]), (data.get("f") or None)


def _issued_after_sign_out(issued: object) -> bool:
    """A token minted before `sessions_not_before` (every browser signed out, or the revocation list overflowed)
    is dead, like the cookies of that time. Tokens without an issue time (before 2.0.0a70) are refused."""
    if not isinstance(issued, int):
        return False
    try:
        nb = float(config.load_secrets().get("sessions_not_before") or 0)
    except (TypeError, ValueError):
        nb = 0.0
    return issued >= nb


def url_for(p: Path, cookie: str | None = None) -> str:
    tok = make_token(p.parent, file=p.name if _single_file(p.parent) else None,
                     session=security.session_id(cookie) if cookie else None)
    return f"/api/files/site/{tok}/{quote(p.name)}"


def _hidden(rel: Path) -> bool:
    return any(part.startswith(".") for part in rel.parts)


@router.get("/{token}/{rel:path}")
async def site(token: str, rel: str):
    tok = read_token(token)
    if tok is None:
        raise _err(403, "expired", "This preview link expired - reopen the file")
    folder, only = tok
    base = folder.resolve()
    root = _root()
    if _hidden(Path(rel)):
        raise _err(403, "forbidden", "Hidden files are not served")
    if only is not None:                           # single-file token: that file, nothing else
        p = (folder / only).resolve()
        if rel != only or p.parent != base or not _inside(p, root):
            raise _err(403, "forbidden", "Outside the page folder")
        if _hidden(p.relative_to(root)) or p.suffix.lower().lstrip(".") not in ASSETS:
            raise _err(403, "forbidden", "Hidden files and documents are not served in a preview")
    else:
        p = (folder / rel).resolve()
        if p.is_dir():
            p = (p / "index.html").resolve()
        if not _inside(p, base) or not _inside(p, root) or _hidden(p.relative_to(base)):
            raise _err(403, "forbidden", "Outside the page folder")
        ext = p.suffix.lower().lstrip(".")
        if ext not in ASSETS:
            raise _err(403, "forbidden", "Only pages and their static assets (styles, scripts, pictures, fonts, "
                                         "media) are served in a preview")
        ws = config.workspace().resolve()
        if "attachments" in p.relative_to(base).parts and (base == ws or ws in base.parents) and ext not in MEDIA:
            # a page in a topic folder may show the pictures and videos sent in its chats, not the other files
            raise _err(403, "forbidden", "A topic's attachments are served to a page as pictures and media only")
    if not p.is_file():
        raise _err(404, "not_found", "File not found")
    return FileResponse(p, media_type=_mime(p), headers={
        "Content-Security-Policy": SANDBOX, "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=300", "Referrer-Policy": "no-referrer"})
