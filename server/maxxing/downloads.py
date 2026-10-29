"""Files sent to the user's device: the Content-Disposition header and a folder streamed as a zip.
See docs/dev/API.md#files.

`content_disposition()` is the one way to name a download (files, team files from a peer, the PC agent):
Starlette's own `filename=` raises on a name that is not UTF-8 on disk (lone surrogates -> 500) and sends no plain
`filename=` for the browsers that ignore `filename*=`.
"""
from __future__ import annotations

import os
import stat
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

NAME_MAX = 200                                   # characters kept of a name (extension included): browsers cut anyway
_ATTR_SAFE = "!#$&+-.^_`|~"                      # RFC 5987 attr-char besides letters and digits


def display_name(name: str) -> str:
    """A name as text: the bytes on disk read as UTF-8, else as Latin-1 (a name copied from Windows or an old zip:
    `caf\\udce9` -> `café`); no slash, backslash, control or format character (bidi overrides), never empty."""
    try:
        raw = name.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:                   # a lone surrogate that is no escaped byte (JSON from a peer)
        raw = name.encode("utf-8", "replace")
    # byte by byte: a name mixing both (`caf\xe9 été` - a Latin-1 file renamed later) keeps its UTF-8 part
    text = "".join(chr(ord(c) - 0xDC00) if "\udc80" <= c <= "\udcff" else c
                   for c in raw.decode("utf-8", "surrogateescape"))
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in "/\\" or cat == "Cc" or cat in ("Zl", "Zp"):
            out.append("_")
        elif not cat.startswith("C"):
            out.append(ch)
    text = "".join(out).strip().strip(".").strip()
    if len(text) > NAME_MAX:
        stem, dot, ext = text.rpartition(".")
        ext = ext if dot and stem and 0 < len(ext) <= 16 else ""
        text = text[: NAME_MAX - len(ext) - 1].rstrip() + ("." + ext if ext else "")
    return text or "download"


def _ascii(text: str) -> str:
    """The plain `filename=` fallback: accents dropped, every other non-ASCII, quote, backslash or % as `_`."""
    flat = unicodedata.normalize("NFKD", text)
    out = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\%' else "_"
                  for ch in flat if not unicodedata.combining(ch))
    stem, dot, ext = out.rpartition(".")
    if dot and stem and not stem.strip("_ "):     # nothing readable left but the extension
        out = "download." + ext
    return out if out.strip("_ .") else "download"


def content_disposition(name: str, kind: str = "attachment") -> str:
    """`attachment; filename="<ascii>"; filename*=UTF-8''<the real name>` for any name (see display_name)."""
    text = display_name(name)
    return f"{kind}; filename=\"{_ascii(text)}\"; filename*=UTF-8''{quote(text.encode('utf-8'), safe=_ATTR_SAFE)}"


# ---- a folder as a zip -----------------------------------------------------------------------------------------
ZIP_MAX_BYTES = 2 << 30                         # uncompressed total of a folder download
ZIP_MAX_FILES = 100_000
ZIP_CHUNK = 1 << 20
# kept as they are (deflate would gain nothing and cost CPU)
STORED_EXT = {".zip", ".gz", ".tgz", ".bz2", ".xz", ".zst", ".7z", ".rar", ".jar", ".apk", ".whl", ".docx", ".xlsx",
              ".pptx", ".odt", ".ods", ".epub", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".heif",
              ".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac",
              ".woff", ".woff2", ".pdf"}


class ZipTooLarge(Exception):
    def __init__(self, what: str):
        super().__init__(what)
        self.what = what


def zip_plan(folder: Path, root: Path) -> list[tuple[Path, str, os.stat_result | None]]:
    """What the zip of `folder` holds: (source, name in the zip, stat; None for a folder), in walk order.
    Symlinked folders are not followed; a symlinked file counts only when its target is a regular file inside `root`.
    Sockets, FIFOs and devices are left out. Raises ZipTooLarge past ZIP_MAX_BYTES / ZIP_MAX_FILES."""
    base = display_name(folder.name or "files")
    plan: list[tuple[Path, str, os.stat_result | None]] = [(folder, base + "/", None)]
    total = 0
    for top, dirs, files in os.walk(folder, followlinks=False):
        dirs.sort()
        here = Path(top)
        rel = "/".join(display_name(p) for p in here.relative_to(folder).parts)
        prefix = f"{base}/{rel}/" if rel else f"{base}/"
        for d in list(dirs):
            if (here / d).is_symlink():
                dirs.remove(d)
            else:
                plan.append((here / d, prefix + display_name(d) + "/", None))
        for f in sorted(files):
            src = here / f
            try:
                if src.is_symlink():
                    src = src.resolve()                # read through its target (opened without following links)
                    if root not in src.parents:
                        continue
                st = src.stat()
            except (OSError, RuntimeError):
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            total += st.st_size
            if total > ZIP_MAX_BYTES:
                raise ZipTooLarge("size")
            plan.append((src, prefix + display_name(f), st))
            if len(plan) > ZIP_MAX_FILES:
                raise ZipTooLarge("count")
    return plan


class _Sink:
    """The unseekable file zipfile writes into: what it wrote is taken out by the response's iterator."""
    def __init__(self) -> None:
        self.parts: list[bytes] = []

    def write(self, b: bytes) -> int:
        self.parts.append(bytes(b))
        return len(b)

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        out, self.parts = b"".join(self.parts), []
        return out


def _date(mtime: float) -> tuple[int, int, int, int, int, int]:
    t = time.localtime(mtime)
    return (1980, 1, 1, 0, 0, 0) if t.tm_year < 1980 else (min(t.tm_year, 2107), *t[1:6])


def zip_stream(plan: list[tuple[Path, str, os.stat_result | None]]) -> Iterator[bytes]:
    """The zip, produced as it is sent (a sync iterator: Starlette runs it in a worker thread). ZIP64 where needed,
    deflate level 6, stored for formats that are already compressed. A file that grew is cut at its planned size;
    one that cannot be read any more is left out."""
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for src, name, st in plan:
            if st is None:
                zi = zipfile.ZipInfo(name, _date(src.stat().st_mtime) if src.exists() else (1980, 1, 1, 0, 0, 0))
                zi.external_attr = (0o40755 << 16) | 0x10
                zi.CRC = zi.compress_size = zi.file_size = 0
                zf.mkdir(zi)
                continue
            try:                               # never a link or a FIFO put there since the plan (O_NONBLOCK: no wait)
                fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            except OSError:
                continue
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                os.close(fd)
                continue
            f = os.fdopen(fd, "rb")
            with f:
                zi = zipfile.ZipInfo(name, _date(st.st_mtime))
                zi.external_attr = (stat.S_IMODE(st.st_mode) | stat.S_IFREG) << 16
                zi.compress_type = zipfile.ZIP_STORED if src.suffix.lower() in STORED_EXT else zipfile.ZIP_DEFLATED
                zi.file_size = st.st_size                 # lets zipfile pick ZIP64 for a big entry up front
                left = st.st_size
                with zf.open(zi, "w", force_zip64=st.st_size > (1 << 30)) as out:
                    while left > 0:
                        chunk = f.read(min(ZIP_CHUNK, left))
                        if not chunk:
                            break
                        left -= len(chunk)
                        out.write(chunk)
                        if sink.parts:
                            yield sink.take()
            if sink.parts:
                yield sink.take()
    yield sink.take()                                # the central directory
