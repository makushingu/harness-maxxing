"""Media warm-up for the conversations (see docs/dev/API.md#files).

A media path in a message is prepared as soon as the message reaches the UI: the chat thumbnails,
and the viewer's preview (heavy images) or poster (videos). By the time the thumbnail scrolls into
view or the user clicks it, the server answers from its cache.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("maxxing.media")

_lock = threading.Lock()

# ---- warm-up --------------------------------------------------------------------------------
MEDIA_RE = re.compile(r"(?<![\w:/.~-])(/[^\s`'\"<>()\[\]{}|]+?\.(?:png|jpe?g|gif|webp|avif|bmp|heic|tiff?|mp4|m4v|mov|webm|mkv))"
                      r"(?=$|[\s`'\"<>()\[\]{}|,;:!?]|\.(?:\s|$))", re.I)
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="media-warm")   # gentle on a 2-CPU VPS
_seen: OrderedDict[str, None] = OrderedDict()


def media_paths(text: str, limit: int = 12) -> list[str]:
    out: list[str] = []
    for m in MEDIA_RE.finditer(text or ""):
        if m.group(1) not in out:
            out.append(m.group(1))
        if len(out) >= limit:
            break
    return out


def _warm_one(path: str) -> None:
    from .api import files                        # lazy: the API module owns path checks + thumbnails
    try:
        p = files.resolve(path)
        if not p.is_file():
            return
        ext = p.suffix.lower()
        if ext in files.VIDEO_EXT:
            files._thumb(p, 320)                   # chat thumbnail
            files._thumb(p, 1280)                  # player poster
        elif ext in files.IMAGE_EXT:
            files._thumb(p, 160)                   # attachment strip
            files._thumb(p, 320)                   # chat media / viewer placeholder
            if p.stat().st_size > files.PREVIEW_MIN_BYTES and ext not in files.PREVIEW_ORIGINAL_EXT:
                files._thumb(p, files.PREVIEW_W)   # viewer preview
    except Exception as e:                          # outside the files root, unreadable, no ffmpeg...
        log.debug("warm-up skipped for %s: %s", path, e)


def warm(paths: list[str]) -> None:
    """Prepare thumbnails / previews / posters of these media paths in the background (once)."""
    for path in paths:
        with _lock:
            if path in _seen:
                continue
            _seen[path] = None
            while len(_seen) > 2000:
                _seen.popitem(last=False)
        _pool.submit(_warm_one, path)


def warm_events(evs: list[dict]) -> None:
    paths: list[str] = []
    for ev in evs:
        if ev.get("type") in ("assistant", "user"):
            paths += media_paths(ev.get("text") or "")
            paths += [a for a in ev.get("attachments") or [] if MEDIA_RE.fullmatch(a or "")]
    if paths:
        warm(paths[:24])
