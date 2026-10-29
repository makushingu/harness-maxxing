"""Files sent to the user's device: the Content-Disposition header. See docs/dev/API.md#files.

`content_disposition()` is the one way to name a download (files, team files from a peer, the PC agent):
Starlette's own `filename=` raises on a name that is not UTF-8 on disk (lone surrogates -> 500) and sends no plain
`filename=` for the browsers that ignore `filename*=`.
"""
from __future__ import annotations

import unicodedata
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
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
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
