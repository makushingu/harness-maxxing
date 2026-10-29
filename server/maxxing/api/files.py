"""File browser API, confined to config `files_root`. See docs/dev/API.md#files.

Every path is absolute and must resolve (symlinks followed) inside files_root, else 403.
Mutations act on the entry itself (a symlink is moved/deleted, never its target).
"""
from __future__ import annotations

import asyncio
import bz2
import gzip
import hashlib
import lzma
import mimetypes
import os
import secrets
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .. import config, downloads, security, videos, workspace
from ..security import require_auth
from .sessions import save_upload

router = APIRouter(prefix="/api/files", tags=["files"], dependencies=[Depends(require_auth)])

READ_MAX = 2 * 1024 * 1024
THUMB_TIMEOUT_S = 30
# Thumbnails (ffmpeg / pdftoppm, up to 30 s each) run in their own small pool: a grid of 100 new photos queues
# here instead of filling the shared worker threads every other request (health, lists, settings) needs.
THUMB_JOBS = 3
_thumb_pool = ThreadPoolExecutor(max_workers=THUMB_JOBS, thread_name_prefix="mx-thumb")
SEARCH_MAX = 50
SEARCH_SCAN_MAX = 200_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache", ".next", "dist",
             "build", ".mypy_cache", ".pytest_cache", "attachments"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
# demuxers allowed for an image thumbnail (mov: AVIF / HEIC); see videos.VIDEO_FORMATS
IMAGE_FORMATS = "image2,png_pipe,apng,jpeg_pipe,jpegxl_pipe,gif,webp_pipe,bmp_pipe,tiff_pipe,ico,mov"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif", ".heic", ".heif"}
CONVERT_EXT = {".tif", ".tiff", ".heic", ".heif"}    # browsers cannot show them: the viewer always gets a WebP
PDF_EXT = {".pdf"}
ARCHIVE_MAX = 5000                                   # entries listed by /archive
ARCHIVE_READ_MAX = 256 << 20                         # a tar is read (decompressed) this far at most, then truncated
ARCHIVE_TIME_S = 3.0                                 # and for this long at most (a zip's directory too)
SITE_TTL_S = 2 * 3600


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"error": code, "message": message})


# ---- path confinement ----------------------------------------------------------------------
def _root() -> Path:
    return config.files_root().resolve()


def _inside(p: Path, root: Path) -> bool:
    return p == root or root in p.parents


def resolve(path: str | None, *, follow: bool = True, new: bool = False) -> Path:
    """Absolute path inside files_root. follow=False keeps a final symlink itself (for mutations); new=True: the
    last part is a name to create, taken as typed."""
    root = _root()
    raw = Path(path) if path else root
    if not raw.is_absolute():
        raise _err(400, "bad_path", "Paths must be absolute")
    raw = _unshow(raw.parent) / raw.name if new and raw.name else _unshow(raw)
    if any(len(os.fsencode(part)) > 255 for part in raw.parts):   # ENAMETOOLONG in mkdir/write/move: a 500
        raise _err(400, "bad_path", "A name is longer than 255 bytes")
    try:
        p = raw.resolve() if follow else raw.parent.resolve() / raw.name
        if raw.name in ("", ".", ".."):
            p = raw.resolve()
    except (ValueError, RuntimeError):               # NUL byte, symlink loop
        raise _err(400, "bad_path", "Invalid path") from None
    if not _inside(p, root):
        raise _err(403, "forbidden", "Outside the files root")
    return p


def _unshow(raw: Path) -> Path:
    """Undo _shown() for a path the UI sends back: a part with U+FFFD that does not exist is the one name of its
    folder shown that way (else unchanged, so a 404)."""
    if "\ufffd" not in str(raw) or os.path.lexists(raw):
        return raw
    cur = Path(raw.anchor)
    for part in raw.parts[1:]:
        if "\ufffd" in part and not os.path.lexists(cur / part):
            try:
                hits = [n for n in os.listdir(cur) if not n.isascii() and _shown(n) == part]
            except (OSError, ValueError):
                return raw
            if len(hits) != 1:
                return raw
            part = hits[0]
        cur = cur / part
    return cur


def _mime(p: Path) -> str:
    return mimetypes.guess_type(p.name)[0] or ("inode/directory" if p.is_dir() else "application/octet-stream")


def _entry(p: Path) -> dict | None:
    try:
        st = p.stat()
    except OSError:
        return None
    is_dir = p.is_dir()
    return {"name": _shown(p.name), "path": _shown(str(p)), "type": "dir" if is_dir else "file",
            "size": 0 if is_dir else st.st_size, "mtime": st.st_mtime,
            "mime": "inode/directory" if is_dir else _mime(p)}


async def _t(fn: Callable[..., Any], *a: Any) -> Any:
    return await asyncio.to_thread(fn, *a)


# ---- read ----------------------------------------------------------------------------------
def _shown(s: str) -> str:
    """A name the JSON answer can carry: bytes that are not UTF-8 (a Latin-1 name from a zip or an SMB copy)
    come out of os.* as lone surrogates, which UTF-8 refuses (500): shown as U+FFFD instead."""
    return s if s.isascii() else s.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def _scan_entry(d: os.DirEntry) -> dict | None:
    """_entry from a scandir entry (one stat per entry instead of two; same result, symlinks followed)."""
    try:
        st = d.stat()
    except OSError:
        return None
    is_dir = stat.S_ISDIR(st.st_mode)
    return {"name": _shown(d.name), "path": _shown(d.path), "type": "dir" if is_dir else "file",
            "size": 0 if is_dir else st.st_size, "mtime": st.st_mtime,
            "mime": "inode/directory" if is_dir else (mimetypes.guess_type(d.name)[0] or "application/octet-stream")}


def _list(p: Path) -> dict:
    if not p.is_dir():
        raise _err(404, "not_found", "Not a folder")
    try:
        with os.scandir(p) as it:
            entries = [e for e in (_scan_entry(d) for d in it) if e]
    except PermissionError:
        raise _err(403, "forbidden", "Permission denied") from None
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    root = _root()
    return {"path": _shown(str(p)), "parent": _shown(str(p.parent)) if p != root else None, "root": str(root),
            "entries": entries}


@router.get("/list")
async def list_dir(path: str = ""):
    return JSONResponse(await _t(_list, resolve(path or None)))   # plain JSON: skips jsonable_encoder


def _read(p: Path) -> dict:
    if not p.is_file():
        raise _err(404, "not_found", "File not found")
    st = p.stat()
    if st.st_size > READ_MAX:
        raise _err(413, "too_large", "File larger than 2 MB - download it instead")
    data = p.read_bytes()
    if b"\x00" in data[:8192]:
        raise _err(415, "binary", "Binary file")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _err(415, "binary", "Not a UTF-8 text file") from None
    return {"path": _shown(str(p)), "content": text, "mtime": st.st_mtime, "size": st.st_size,
            "mime": mimetypes.guess_type(p.name)[0] or "text/plain", "editable": os.access(p, os.W_OK)}


@router.get("/read")
async def read(path: str):
    return await _t(_read, resolve(path))


def _cache(v: str) -> str:
    """`v` (the file's mtime, added by the UI when it knows it) makes the URL unique per version: the
    browser keeps it for good. Without it, every load revalidates (ETag -> 304)."""
    return "private, max-age=31536000, immutable" if v else "private, no-cache"


_FILE_CSP = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"


def _file_headers(mime: str, cache: str) -> dict[str, str]:
    """Headers of a user file served from our own origin: it must never run script with the UI
    session, whatever its type (html, svg, any xml flavour...). Only passive types that cannot
    script are left without the sandbox CSP: images (not SVG), audio, video, and PDF (Chrome's PDF
    viewer does not load under `sandbox`)."""
    headers = {"Cache-Control": cache, "X-Content-Type-Options": "nosniff"}
    base = mime.split(";")[0].strip().lower()
    passive = (base.startswith(("image/", "audio/", "video/")) and base != "image/svg+xml") or base == "application/pdf"
    if not passive:
        headers["Content-Security-Policy"] = _FILE_CSP
    return headers


def _serve(p: Path, v: str, download: bool = False) -> FileResponse:
    mime = _mime(p)
    headers = _file_headers(mime, _cache(v))
    if download:
        headers["Content-Disposition"] = downloads.content_disposition(p.name)
    return FileResponse(p, media_type=mime, headers=headers)


@router.get("/raw")
async def raw(path: str, download: int = 0, v: str = ""):
    p = resolve(path)
    if not await _t(p.is_file):
        raise _err(404, "not_found", "File not found")
    return _serve(p, v, bool(download))


PREVIEW_MIN_BYTES = 300 * 1024            # smaller images are shown as they are
PREVIEW_W = 2048                          # the viewer asks for this width (web: PREVIEW_W)
PREVIEW_ORIGINAL_EXT = {".gif", ".svg"}   # animated / vector: never flattened into a still WebP


@router.get("/preview")
async def preview(path: str, w: int = Query(2048, ge=64, le=4096), v: str = ""):
    """An image for the viewer: a WebP at most `w` px wide when the original is heavy, else the original."""
    p = resolve(path)
    if not await _t(p.is_file):
        raise _err(404, "not_found", "File not found")
    ext = p.suffix.lower()
    if ext not in IMAGE_EXT and not _mime(p).startswith("image/"):
        raise _err(415, "unsupported", "Not an image")
    size = (await _t(p.stat)).st_size
    convert = ext in CONVERT_EXT
    if not convert and (size <= PREVIEW_MIN_BYTES or ext in PREVIEW_ORIGINAL_EXT):
        return _serve(p, v)
    f, mime = await _t(_thumb, p, w)
    if f == p:                                # no ffmpeg: the original (or nothing the browser can show)
        if convert:
            raise _err(415, "unsupported", "This image format cannot be converted on this server")
        return _serve(p, v)
    return FileResponse(f, media_type=mime, headers=_file_headers(mime, _cache(v)))


def _video(path: str) -> Path:
    p = resolve(path)
    if not p.is_file():
        raise _err(404, "not_found", "File not found")
    if p.suffix.lower() not in VIDEO_EXT and not _mime(p).startswith("video/"):
        raise _err(415, "unsupported", "Not a video")
    return p


async def _video_call(fn: Callable[..., Any], *a: Any) -> Any:
    try:
        return await _t(fn, *a)
    except videos.VideoError as e:
        raise _err(422, "video_unavailable", str(e)) from e
    except subprocess.TimeoutExpired as e:
        raise _err(504, "timeout", "The video took too long to read") from e


@router.get("/video")
async def video_info(path: str):
    """Size, codec and bitrate of a video, the lighter copies it offers and their state, and the copy "Auto" plays."""
    p = await _t(_video, path)
    return await _video_call(videos.status, p)


class VideoPrepareIn(BaseModel):
    path: str
    q: int


@router.post("/video/prepare")
async def video_prepare(body: VideoPrepareIn):
    """Start making the lighter copy at height `q` (one at a time, low priority); poll GET /video for progress."""
    p = await _t(_video, body.path)
    return await _video_call(videos.prepare, p, body.q)


@router.get("/video/stream")
async def video_stream(path: str, q: int, v: str = ""):
    """The ready copy at height `q` (H.264 + AAC, fast start; Range requests supported)."""
    p = await _t(_video, path)
    f = await _t(videos.variant_path, p, q)
    if not await _t(f.is_file):
        raise _err(404, "not_ready", "This quality is not ready yet")
    # the cache drops the least recently played copies first: the access time only. A new mtime would change the
    # ETag / Last-Modified of each response, and the browser's next Range request (If-Range) would get the whole
    # file again (200) instead of its range (206): the playback restarts or stalls.
    st = await _t(f.stat)
    await _t(lambda: os.utime(f, ns=(time.time_ns(), st.st_mtime_ns)))
    return FileResponse(f, media_type="video/mp4", stat_result=st, headers=_file_headers("video/mp4", _cache(v)))


# ---- thumbnails ----------------------------------------------------------------------------
def _ffmpeg_thumb(src: Path, dest: Path, w: int, video: bool) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    scale = f"scale='min({w},iw)':-2"
    # a temp file of its own, renamed once complete: a timeout, a crash or a parallel request for the same
    # thumbnail never sees (nor keeps in the cache) a half-written WebP; .webp: _trim_thumbs sweeps crash leftovers
    tmp = dest.with_name(f"{dest.stem}.{secrets.token_hex(4)}.part.webp")
    try:
        for seek in (["-ss", "1"] if video else []), []:
            # file protocol and media demuxers only: a playlist-like input (m3u8, ffconcat...) whatever its name cannot
            # make ffmpeg fetch URLs or pipes, nor open another file (a link out of the files root) and draw it
            cmd = [ffmpeg, "-v", "error", "-y", "-protocol_whitelist", "file",
                   "-format_whitelist", videos.VIDEO_FORMATS if video else IMAGE_FORMATS, *seek, "-i", str(src),
                   "-frames:v", "1", "-vf", scale, "-c:v", "libwebp", "-quality", "78", "-f", "webp", str(tmp)]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=THUMB_TIMEOUT_S)
            except (subprocess.TimeoutExpired, OSError):
                return False
            if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                os.replace(tmp, dest)
                return True
            if not video:
                break
        return False
    finally:
        tmp.unlink(missing_ok=True)


def _pdf_thumb(src: Path, dest: Path, w: int) -> bool:
    """First page of a PDF -> WebP (pdftoppm renders it, ffmpeg encodes it)."""
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        return False
    with tempfile.TemporaryDirectory(prefix="mx-pdf-") as tmp:
        out = Path(tmp) / "page"
        try:
            r = subprocess.run([pdftoppm, "-f", "1", "-l", "1", "-singlefile", "-png", "-scale-to", str(w),
                                str(src), str(out)], capture_output=True, timeout=THUMB_TIMEOUT_S)
        except (subprocess.TimeoutExpired, OSError):
            return False
        png = out.with_suffix(".png")
        if r.returncode != 0 or not png.exists():
            return False
        return _ffmpeg_thumb(png, dest, w, False)


THUMB_WIDTHS = (160, 320, 640, 1280, 2048, 4096)   # a few sizes per file (any width asked maps up to one)
THUMBS_MAX = 512 * 1024**2                         # the thumbnail cache, oldest first beyond it
_thumbs_trimmed = 0.0


def _trim_thumbs() -> None:
    """Keep state/thumbs under THUMBS_MAX (checked at most every 10 min, after a new thumbnail)."""
    global _thumbs_trimmed
    now = time.time()
    if now - _thumbs_trimmed < 600:
        return
    _thumbs_trimmed = now
    files = []
    for f in config.state_dir("thumbs").glob("*.webp"):
        try:
            st = f.stat()
        except OSError:
            continue
        files.append((st.st_mtime, st.st_size, f))
    total = sum(x[1] for x in files)
    for _, size, f in sorted(files, key=lambda x: x[0]):
        if total <= THUMBS_MAX * 0.8:
            break
        f.unlink(missing_ok=True)
        total -= size


def _thumb(p: Path, w: int) -> tuple[Path, str]:
    if not p.is_file():
        raise _err(404, "not_found", "File not found")
    w = next((b for b in THUMB_WIDTHS if b >= w), THUMB_WIDTHS[-1])
    ext = p.suffix.lower()
    if ext in PDF_EXT:
        st = p.stat()
        key = hashlib.sha1(f"{p}|{st.st_mtime_ns}|{w}|pdf".encode()).hexdigest()
        dest = config.state_dir("thumbs") / f"{key}.webp"
        if dest.exists():
            return dest, "image/webp"
        if _pdf_thumb(p, dest, w):
            _trim_thumbs()
            return dest, "image/webp"
        raise _err(415, "unsupported", "Thumbnail unavailable (pdftoppm missing or failed)")
    video = ext in VIDEO_EXT
    if not video and ext not in IMAGE_EXT and not _mime(p).startswith("image/"):
        raise _err(415, "unsupported", "No thumbnail for this file type")
    st = p.stat()
    key = hashlib.sha1(f"{p}|{st.st_mtime_ns}|{w}".encode()).hexdigest()
    dest = config.state_dir("thumbs") / f"{key}.webp"
    if dest.exists():
        return dest, "image/webp"
    if _ffmpeg_thumb(p, dest, w, video):
        _trim_thumbs()
        return dest, "image/webp"
    if video:
        raise _err(415, "unsupported", "Thumbnail unavailable (ffmpeg missing or failed)")
    return p, _mime(p)                        # fallback: the original image


GIF_ANIM_MAX = 8 * 1024**2                # anim=1: a GIF up to this size is served as it is (it moves), else a still


@router.get("/thumb")
async def thumb(path: str, w: int = Query(320, ge=16, le=4096), v: str = "", anim: int = 0):
    p = resolve(path)
    if anim and p.suffix.lower() == ".gif" and await _t(p.is_file) and (await _t(p.stat)).st_size <= GIF_ANIM_MAX:
        return _serve(p, v)
    f, mime = await asyncio.get_running_loop().run_in_executor(_thumb_pool, _thumb, p, w)
    return FileResponse(f, media_type=mime, headers=_file_headers(mime, _cache(v)))


# ---- archives ------------------------------------------------------------------------------
class _ReadCap(Exception):
    pass


class _Capped:
    """Decompressed stream of a tar: listing its members reads through their data, so a small "bomb" would keep a
    thread busy for minutes. Raises _ReadCap past ARCHIVE_READ_MAX bytes or ARCHIVE_TIME_S."""

    def __init__(self, f, deadline: float):
        self.f, self.n, self.deadline = f, 0, deadline

    def read(self, size: int = -1) -> bytes:
        if self.n > ARCHIVE_READ_MAX or time.monotonic() > self.deadline:
            raise _ReadCap
        data = self.f.read(min(size, 1 << 20) if size and size > 0 else 1 << 20)
        self.n += len(data)
        return data


def _decompressed(f):
    head = f.read(6)
    f.seek(0)
    if head[:2] == b"\x1f\x8b":
        return gzip.GzipFile(fileobj=f)
    if head[:3] == b"BZh":
        return bz2.BZ2File(f)
    if head == b"\xfd7zXZ\x00":
        return lzma.LZMAFile(f)
    return f


def _zip_directory(f, deadline: float):
    """Entries of a zip's central directory, read one by one (zipfile.ZipFile loads all of them first: 400k entries
    cost seconds and hundreds of MB). Yields (name, size, is_dir, date_time); raises zipfile.BadZipFile."""
    size = f.seek(0, os.SEEK_END)
    f.seek(max(0, size - 65558))
    tail = f.read()
    i = tail.rfind(b"PK\x05\x06")
    if i < 0 or len(tail) - i < 22:
        raise zipfile.BadZipFile("no end of central directory")
    eocd = size - len(tail) + i
    _, _, _, _, n, cd_size, cd_off, _ = struct.unpack("<4s4H2LH", tail[i:i + 22])
    if n == 0xFFFF or cd_size == 0xFFFFFFFF or cd_off == 0xFFFFFFFF:      # zip64: the real values are elsewhere
        loc = tail[i - 20:i] if i >= 20 else b""
        if loc[:4] != b"PK\x06\x07":
            raise zipfile.BadZipFile("zip64 locator missing")
        f.seek(struct.unpack("<Q", loc[8:16])[0])
        rec = f.read(56)
        if rec[:4] != b"PK\x06\x06":
            raise zipfile.BadZipFile("zip64 end record missing")
        n, cd_size, cd_off = struct.unpack("<QQQ", rec[32:56])
        eocd = struct.unpack("<Q", loc[8:16])[0]
    f.seek(max(0, eocd - cd_size))                  # like zipfile: data prepended to the archive is allowed
    for _ in range(n):
        if time.monotonic() > deadline:
            raise _ReadCap
        h = f.read(46)
        if len(h) < 46 or h[:4] != b"PK\x01\x02":
            raise zipfile.BadZipFile("bad central directory entry")
        flags, tm, dt, usize, nlen, xlen, clen = struct.unpack("<8xH2x2H8xL3H", h[:34])
        raw = f.read(nlen)
        extra = f.read(xlen)
        f.seek(clen, os.SEEK_CUR)
        if usize == 0xFFFFFFFF:                     # zip64 extra field: original size first
            j = 0
            while j + 4 <= len(extra):
                tag, ln = struct.unpack("<HH", extra[j:j + 4])
                if tag == 1 and ln >= 8:
                    usize = struct.unpack("<Q", extra[j + 4:j + 12])[0]
                    break
                j += 4 + ln
        name = raw.decode("utf-8" if flags & 0x800 else "cp437", "replace")
        yield name, usize, name.endswith("/"), ((dt >> 9) + 1980, (dt >> 5) & 15, dt & 31, tm >> 11, (tm >> 5) & 63, (tm & 31) * 2)


_archive_cache: dict[tuple, dict] = {}


def _archive(p: Path) -> dict:
    """List an archive without extracting anything (zip, tar, tar.gz/bz2/xz, single .gz). Bounded: at most
    ARCHIVE_MAX entries, ARCHIVE_READ_MAX decompressed bytes and ARCHIVE_TIME_S (then `truncated`); cached per file
    version, unless the time cap cut it."""
    if not p.is_file():
        raise _err(404, "not_found", "File not found")
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    if key in _archive_cache:
        return _archive_cache[key]
    name = p.name.lower()
    entries: list[dict] = []
    truncated = timed_out = False
    count = 0
    total = 0
    deadline = time.monotonic() + ARCHIVE_TIME_S
    try:
        if zipfile.is_zipfile(p):
            fmt = "zip"
            with p.open("rb") as f:
                try:
                    for fname, size, is_dir, dt in _zip_directory(f, deadline):
                        count += 1
                        total += size
                        if len(entries) < ARCHIVE_MAX:
                            entries.append({"name": fname, "size": size, "dir": is_dir,
                                            "mtime": time.mktime(dt + (0, 0, -1)) if dt[0] > 1980 else None})
                        else:
                            truncated = True
                except _ReadCap:
                    truncated = True
                    timed_out = time.monotonic() > deadline
        elif tarfile.is_tarfile(p):
            fmt = "tar"
            with p.open("rb") as raw, _decompressed(raw) as f, tarfile.open(fileobj=_Capped(f, deadline), mode="r|") as tf:
                try:
                    for m in tf:
                        count += 1
                        total += m.size
                        if count > ARCHIVE_MAX:
                            truncated = True
                            break
                        entries.append({"name": _shown(m.name) + ("/" if m.isdir() else ""), "size": m.size,
                                        "dir": m.isdir(), "mtime": m.mtime or None})
                except _ReadCap:
                    truncated = True
                    timed_out = time.monotonic() > deadline
        elif name.endswith(".gz"):
            fmt = "gzip"
            with p.open("rb") as f:
                f.seek(-4, os.SEEK_END)
                size = int.from_bytes(f.read(4), "little")
            entries.append({"name": _shown(p.name[:-3]), "size": size, "dir": False, "mtime": None})
            count, total = 1, size
        else:
            raise _err(415, "unsupported", "This archive format cannot be listed (zip, tar and gz can)")
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError, lzma.LZMAError, struct.error, ValueError) as e:
        raise _err(415, "unsupported", f"Unreadable archive: {type(e).__name__}") from None
    out = {"path": _shown(str(p)), "format": fmt, "entries": entries, "count": count, "total_size": total,
           "truncated": truncated, "size": st.st_size}
    if timed_out:                                     # a slow moment, not the file: list it again next time
        return out
    if len(_archive_cache) >= 32:
        _archive_cache.pop(next(iter(_archive_cache), None), None)
    _archive_cache[key] = out
    return out


@router.get("/archive")
async def archive(path: str):
    return await _t(_archive, resolve(path))


# ---- HTML pages ----------------------------------------------------------------------------
@router.get("/site-url")
async def site_url(path: str, request: Request):
    """A short-lived URL rendering an HTML file with its relative assets (images, CSS, scripts next to
    it). The page runs sandboxed in an opaque origin: no access to the UI session (see filesite.py)."""
    from . import filesite

    p = resolve(path)
    if not await _t(p.is_file):
        raise _err(404, "not_found", "File not found")
    if p.suffix.lower() not in (".html", ".htm"):
        raise _err(415, "unsupported", "Only an HTML page can be opened as a site")
    url = await _t(filesite.url_for, p, request.cookies.get(security.COOKIE))
    return {"url": url, "expires_in": SITE_TTL_S}


class StatIn(BaseModel):
    paths: list[str] = Field(max_length=500)


def _stat(paths: list[str]) -> dict:
    out: dict[str, float | None] = {}
    for raw in paths:
        try:
            out[raw] = resolve(raw).stat().st_mtime
        except (HTTPException, OSError, ValueError, RuntimeError):     # RuntimeError: a symlink loop (< 3.13)
            out[raw] = None
    return {"mtimes": out}


@router.post("/stat")
async def stat_paths(body: StatIn):
    """Current mtime of the files shown as previews (null = missing / outside): the UI puts it in their URLs, so
    a file rewritten under the same name shows its new version."""
    return await _t(_stat, body.paths)


# ---- mutations -----------------------------------------------------------------------------
class WriteIn(BaseModel):
    path: str
    content: str
    expected_mtime: float | None = None


class PathIn(BaseModel):
    path: str


class MoveIn(BaseModel):
    from_: str = Field(alias="from")
    to: str


def _write(p: Path, content: str, expected: float | None) -> dict:
    if p.is_dir():
        raise _err(400, "is_dir", "Path is a folder")
    if not p.parent.is_dir():
        raise _err(404, "not_found", "Parent folder not found")
    if p.exists() and expected is not None and abs(p.stat().st_mtime - expected) > 1e-3:
        raise _err(409, "conflict", "The file changed on disk since it was opened")
    mode = p.stat().st_mode & 0o7777 if p.exists() else None
    # a fresh temp file next to it (never an existing name: a link planted there would send the text elsewhere)
    # short and fixed prefix: a long file name plus the suffix would pass the 255-byte limit
    fd, name = tempfile.mkstemp(prefix=".mx-", suffix=".mx-tmp", dir=p.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            try:
                f.write(content)
            except UnicodeEncodeError:                  # a lone surrogate (\ud800) passes JSON, not UTF-8
                raise _err(400, "bad_content", "The text holds a character that cannot be saved") from None
        os.chmod(tmp, mode if mode is not None else 0o666 & ~config._UMASK)   # noqa: SLF001 (umask read once)
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)
    return {"ok": True, "mtime": p.stat().st_mtime}



@router.put("/write")
async def write(body: WriteIn):
    return await _t(_write, resolve(body.path, follow=True), body.content, body.expected_mtime)


def _mkdir(p: Path) -> dict:
    if p.exists() or p.is_symlink():
        raise _err(409, "exists", "Already exists")
    try:
        p.mkdir(parents=True)
    except (FileExistsError, NotADirectoryError):
        raise _err(409, "exists", "A file is in the way") from None
    return {"ok": True}


@router.post("/mkdir")
async def mkdir(body: PathIn):
    return await _t(_mkdir, resolve(body.path, follow=False, new=True))


def _guard_workspace(p: Path) -> None:
    """The workspace (or a folder holding it) is never moved/deleted here; a folder under a running session is
    refused like the workspace API does (409 has_running_sessions)."""
    ws = workspace.root().resolve()
    if p == ws or p in ws.parents:
        raise _err(403, "forbidden", "Cannot move or delete the workspace")
    if ws in p.parents:
        try:
            workspace._ensure_idle(str(p.relative_to(ws)))      # noqa: SLF001
        except workspace.WorkspaceError as e:
            raise _err(e.status, e.code, e.message) from None


def _move(src: Path, dst: Path) -> dict:
    if not src.exists() and not src.is_symlink():
        raise _err(404, "not_found", "Source not found")
    if src == _root():
        raise _err(403, "forbidden", "Cannot move the files root")
    _guard_workspace(src)
    if dst.exists() or dst.is_symlink():
        raise _err(409, "exists", "Destination already exists")
    if src.is_dir() and _inside(dst, src):
        raise _err(400, "bad_path", "Cannot move a folder into itself")
    if not dst.parent.is_dir():
        raise _err(404, "not_found", "Destination folder not found")
    shutil.move(str(src), str(dst))
    return {"ok": True}


@router.post("/move")
async def move(body: MoveIn):
    return await _t(_move, resolve(body.from_, follow=False), resolve(body.to, follow=False, new=True))


def _delete(p: Path) -> dict:
    if p == _root():
        raise _err(403, "forbidden", "Cannot delete the files root")
    if not p.exists() and not p.is_symlink():
        raise _err(404, "not_found", "Not found")
    _guard_workspace(p)
    workspace.move_to_trash(p)
    return {"ok": True}


@router.post("/delete")
async def delete(body: PathIn):
    return await _t(_delete, resolve(body.path, follow=False))


@router.post("/upload")
async def upload(dir: str, file: list[UploadFile] = File(...)):
    folder = resolve(dir)
    if not await _t(folder.is_dir):
        raise _err(404, "not_found", "Folder not found")
    return {"files": [await _t(save_upload, f, folder) for f in file]}


# ---- search --------------------------------------------------------------------------------
def _search(q: str) -> list[dict]:
    term = q.strip().lower()
    if len(term) < 2:
        return []
    out: list[dict] = []
    scanned = 0
    base = workspace.root()
    for cur, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".cache"))
        for name in dirs + sorted(files):
            scanned += 1
            if term in name.lower():
                kind = "dir" if name in dirs else "file"
                out.append({"path": _shown(os.path.join(cur, name)), "name": _shown(name), "type": kind})
                if len(out) >= SEARCH_MAX:
                    return out
        if scanned > SEARCH_SCAN_MAX:
            break
    return out


@router.get("/search")
async def search(q: str = ""):
    return await _t(_search, q)
