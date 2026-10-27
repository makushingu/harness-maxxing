"""User extensions: `<workspace>/extensions/<id>/`.

    manifest.json  {"id", "name", "type": "widget"|"page", "icon", "version", "span"?, "ttl"?, "api"?}
                   ("name" may be {"en": ..., "fr": ...}: shown in the UI language)
    api.py         widget: def card(ctx) -> Card   ·   page / API: def handle(ctx, method, path, query, body)
    page.js        page: ES module exporting mount(el, ctx)

Extensions live outside the code directory so updates never touch them. Each one is isolated:
a broken manifest or an api.py that fails to import only sets that extension's `error`.
api.py is imported with importlib under the module name `mx_ext_<id>`; the module is published
in sys.modules only AFTER exec_module succeeded (never expose a half-initialised module).
Loading (the enabled check + the import) runs under `publishing()` - a lock shared across threads and processes
(flock on state/extensions.lock) that a backup restore also holds while it turns extensions off and writes their
files: a scan never imports code the restore is still holding back.

`ctx` passed to card()/handle(): {"id", "workspace", "state_dir", "secret": fn(name) -> str|None,
"config": {"timezone", "language", "public_url"}}.
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import importlib.util
import os
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from . import config

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
TYPES = ("widget", "page")
DEFAULT_TTL = 300
# The extension contract (Card schema, ctx, page ctx, maxxing.api bridge, CSS variables). An extension declares
# the version it was written for in its manifest ("api", default 1). EXT_API goes up when something is ADDED;
# EXT_API_MIN only when a release can no longer run older extensions (announced in the upgrade notes, and the
# update preflight lists the extensions to adapt before updating).
EXT_API = 1
EXT_API_MIN = 1
RESERVED_IDS = {"activity", "tasks", "day", "crons", "server", "backup", "telegram", "shopify", "usage", "customize"}   # built-in widgets
BLOCK_TYPES = {"stat", "stats", "list", "chart", "table", "progress", "markdown", "timeline"}


@dataclass
class Extension:
    id: str
    dir: Path
    name: str = ""
    names: dict[str, str] = field(default_factory=dict)   # name per language, when the manifest gives several
    type: str = "widget"
    icon: str = "puzzle"
    version: str = ""
    span: int = 1
    ttl: int = DEFAULT_TTL
    api: int = 1                           # extension API version the manifest declares
    has_api: bool = False
    has_page: bool = False
    has_html: bool = False                 # widget drawn by widget.html in a sandboxed frame
    page_v: int | None = None              # page.js mtime (ms): the UI imports page.js?v=<it> (cached until it changes)
    height: int = 260
    error: str | None = None
    module: ModuleType | None = field(default=None, repr=False)

    def label(self) -> str:
        if self.names:
            lang = str(config.load_config().get("language") or "en")
            return self.names.get(lang) or self.names.get("en") or self.name or self.id
        return self.name or self.id

    @property
    def enabled(self) -> bool:
        return self.id not in disabled_ids()

    def info(self) -> dict:
        return {"id": self.id, "name": self.label(), "type": self.type, "icon": self.icon,
                "version": self.version, "enabled": self.enabled, "error": self.error,
                "api": self.api, "has_api": self.has_api, "has_page": self.has_page, "span": self.span,
                "has_html": self.has_html, "height": self.height, "page_v": self.page_v,
                "pinned": self.type == "page" and self.id in pinned_ids()}


_lock = threading.RLock()
_pub_lock = threading.RLock()
_pub_depth = 0


@contextlib.contextmanager
def publishing():
    """Held while extensions are loaded, and by whoever changes extension code + its enabled flag together (backup
    restore): in-process re-entrant lock + an exclusive flock on state/extensions.lock (the CLI restores too)."""
    global _pub_depth
    with _pub_lock:
        fd = None
        if _pub_depth == 0:
            try:
                config.STATE.mkdir(parents=True, exist_ok=True)
                fd = os.open(config.STATE / "extensions.lock", os.O_CREAT | os.O_RDWR, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError:
                if fd is not None:
                    os.close(fd)
                fd = None
        _pub_depth += 1
        try:
            yield
        finally:
            _pub_depth -= 1
            if fd is not None:
                os.close(fd)
# Extension code runs on its own few threads: a handle() / card() that never returns (a network call without a
# timeout) only takes one of them, never the server's shared pool (streams, routes, watchers). Calls wait their
# turn (the dashboard asks every widget at once); only when every thread is held by a call past its timeout (stuck
# code) is a new call refused at once (503) instead of waiting for nothing.
EXT_WORKERS = 4
IMPORT_TIMEOUT_S = 10.0
_pool = ThreadPoolExecutor(max_workers=EXT_WORKERS, thread_name_prefix="mx-ext")
_stuck = 0
_busy_lock = threading.Lock()
_stuck_keys: set[str] = set()                      # call keys whose timed-out call still holds a thread


class ExtensionBusy(RuntimeError):
    """Every extension thread is still running earlier calls that timed out (stuck extension code)."""


def _guarded(fn: Callable[..., Any], *args: Any) -> Any:
    """A SystemExit (sys.exit) or KeyboardInterrupt raised by extension code would pass every `except Exception`
    of the server once awaited: turned into a RuntimeError, like _import does."""
    try:
        return fn(*args)
    except Exception:
        raise
    except BaseException as e:
        raise RuntimeError(f"extension stopped ({type(e).__name__})") from None


async def call(fn: Callable[..., Any], *args: Any, timeout: float, key: str | None = None) -> Any:
    """Run extension code on the extension threads, queued when they are all working; TimeoutError after
    `timeout` (waiting included; the thread stays taken until the code returns), ExtensionBusy at once when every
    thread is stuck, or when the call `key` timed out earlier and has not returned yet (a stuck card() reloaded
    again and again would otherwise take every thread)."""
    global _stuck
    with _busy_lock:
        if key is not None and key in _stuck_keys:
            raise ExtensionBusy("timed out: the previous call has not returned yet")
        if _stuck >= EXT_WORKERS:
            raise ExtensionBusy("extensions are busy (earlier calls never returned)")
    cf = _pool.submit(_guarded, fn, *args)
    try:
        return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(cf)), timeout)
    except asyncio.TimeoutError:
        if not cf.cancel():                          # still queued: dropped; running: holds a thread until it returns
            with _busy_lock:
                _stuck += 1
                if key is not None:
                    _stuck_keys.add(key)

            def done(_f: Any) -> None:
                global _stuck
                with _busy_lock:
                    _stuck -= 1
                    if key is not None:
                        _stuck_keys.discard(key)
            cf.add_done_callback(done)
        raise


_registry: dict[str, Extension] = {}
_scanned = False
_last_sig: tuple = ()
_cards: dict[str, tuple[float, dict]] = {}


def root() -> Path:
    return config.workspace() / "extensions"


def disabled_ids() -> set[str]:
    d = (config.load_config().get("extensions") or {}).get("disabled") or []
    return {x for x in d if isinstance(x, str)}


def pinned_ids() -> set[str]:
    """Page extensions shown directly in the sidebar (the others are listed under "Extensions")."""
    d = (config.load_config().get("extensions") or {}).get("pinned") or []
    return {x for x in d if isinstance(x, str)}


def set_pinned(eid: str, pinned: bool) -> bool:
    """Persist in config extensions.pinned. False if unknown or not a page."""
    ext = get(eid)
    if ext is None or ext.type != "page":
        return False
    with config._lock:
        pin = pinned_ids()
        if pinned:
            pin.add(eid)
        else:
            pin.discard(eid)
        config.update_config(extensions={"pinned": sorted(pin)})
    return True


def _module_name(eid: str) -> str:
    return "mx_ext_" + eid.replace("-", "_")


def _load_one(d: Path) -> Extension:
    ext = Extension(id=d.name, dir=d)
    try:
        if not ID_RE.match(d.name):
            raise ValueError("folder name must be a lowercase slug (a-z, 0-9, -)")
        try:
            m = json.loads((d / "manifest.json").read_text())
        except FileNotFoundError:
            raise ValueError("manifest.json is missing") from None
        except ValueError as e:
            raise ValueError(f"manifest.json is not valid JSON ({e})") from None
        if not isinstance(m, dict):
            raise ValueError("manifest.json must contain an object")
        if m.get("id", d.name) != d.name:
            raise ValueError(f"manifest id {m.get('id')!r} differs from the folder name {d.name!r}")
        raw = m.get("name")
        if isinstance(raw, dict):
            ext.names = {str(k): str(v)[:80] for k, v in raw.items() if isinstance(v, str) and v.strip()}
            raw = ext.names.get("en") or next(iter(ext.names.values()), "")
        ext.name = str(raw or d.name)[:80]
        ext.type = m.get("type", "widget")
        if ext.type not in TYPES:
            raise ValueError("type must be widget or page")
        if ext.type == "widget" and d.name in RESERVED_IDS:
            raise ValueError(f"{d.name!r} is the id of a built-in widget - rename the folder")
        try:
            ext.api = int(m.get("api") or 1)
        except (TypeError, ValueError):
            raise ValueError("manifest \"api\" must be a number (the extension API version, e.g. 1)") from None
        if ext.api > EXT_API:
            raise ValueError(f"built for extension API {ext.api}: update Harness Maxxing (this version supports "
                             f"{EXT_API_MIN}-{EXT_API})")
        if ext.api < EXT_API_MIN:
            raise ValueError(f"built for extension API {ext.api}, no longer supported ({EXT_API_MIN}-{EXT_API}): "
                             "ask Harness to update this extension")
        ext.icon = str(m.get("icon") or "puzzle")[:40]
        ext.version = str(m.get("version") or "")[:20]
        ext.span = min(3, max(1, int(m.get("span") or 1)))
        ext.ttl = max(0, int(m.get("ttl", DEFAULT_TTL)))
        ext.has_api = (d / "api.py").is_file()
        ext.has_page = (d / "page.js").is_file()
        if ext.has_page:
            ext.page_v = (d / "page.js").stat().st_mtime_ns // 1_000_000
        ext.has_html = ext.type == "widget" and (d / "widget.html").is_file()
        ext.height = min(800, max(120, int(m.get("height") or 260)))
        if ext.type == "page" and not ext.has_page:
            raise ValueError("a page extension needs page.js")
        if ext.type == "widget" and not ext.has_api and not ext.has_html:
            raise ValueError("a widget extension needs api.py with card(ctx), or widget.html")
        if ext.has_api and ext.enabled:
            ext.module = _import(ext)
            if ext.type == "widget" and not ext.has_html and not callable(getattr(ext.module, "card", None)):
                raise ValueError("api.py must define card(ctx)")
    except (Exception, SystemExit) as e:               # isolate: one bad extension never breaks the rest
        ext.error = f"{type(e).__name__}: {e}" if not isinstance(e, ValueError) else str(e)
        ext.module = None
    return ext


def _import(ext: Extension) -> ModuleType:
    name = _module_name(ext.id)
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, ext.dir / "api.py")
    if spec is None or spec.loader is None:
        raise ImportError("cannot load api.py")
    mod = importlib.util.module_from_spec(spec)
    # Run apart with a deadline: an api.py that blocks or calls sys.exit() while loading must not stop the server
    # from starting (or a rescan). A stuck import keeps its daemon thread; the extension shows the error.
    err: list[BaseException] = []

    def load() -> None:
        try:
            spec.loader.exec_module(mod)               # type: ignore[union-attr]
        except BaseException as e:                     # SystemExit too: stored on the extension
            err.append(e)
    t = threading.Thread(target=load, name=f"mx-ext-import-{ext.id}", daemon=True)
    t.start()
    t.join(IMPORT_TIMEOUT_S)
    if t.is_alive():
        raise TimeoutError(f"api.py took more than {IMPORT_TIMEOUT_S:.0f} s to load")
    if err:
        e = err[0]
        if isinstance(e, Exception):
            raise e
        raise RuntimeError(f"api.py stopped while loading ({type(e).__name__}: {e})")
    sys.modules[name] = mod                            # publish only a fully initialised module
    return mod


def _signature() -> tuple:
    """Folder names + mtimes of manifest/api/page: a change triggers a rescan (hot reload)."""
    r = root()
    if not r.is_dir():
        return ()
    out = []
    for d in sorted(r.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        stamps = []
        for f in ("manifest.json", "api.py", "page.js"):
            try:
                stamps.append((d / f).stat().st_mtime_ns)
            except OSError:
                stamps.append(None)
        out.append((d.name, *stamps))
    return tuple(out)


def scan() -> list[Extension]:
    """(Re)load every extension folder. Blocking (imports user code)."""
    global _scanned, _last_sig
    sig = _signature()
    exts: dict[str, Extension] = {}
    r = root()
    with publishing():
        if r.is_dir():
            for d in sorted(p for p in r.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
                exts[d.name] = _load_one(d)
    with _lock:
        _registry.clear()
        _registry.update(exts)
        _cards.clear()
        _scanned = True
        _last_sig = sig
    return list(exts.values())


def all_extensions() -> list[Extension]:
    sig = _signature()
    with _lock:
        if _scanned and sig == _last_sig:
            return list(_registry.values())
    return scan()


def get(eid: str) -> Extension | None:
    return next((e for e in all_extensions() if e.id == eid), None)


def set_enabled(eid: str, enabled: bool) -> bool:
    """Persist in config extensions.disabled and reload that extension. False if unknown."""
    ext = get(eid)
    if ext is None:
        return False
    with publishing():
        with config._lock:
            dis = disabled_ids()
            if enabled:
                dis.discard(eid)
            else:
                dis.add(eid)
            config.update_config(extensions={"disabled": sorted(dis)})
        fresh = _load_one(ext.dir)
    with _lock:
        _registry[eid] = fresh
        _cards.pop(eid, None)
    return True


# ---- calling extension code -----------------------------------------------------------------
def make_ctx(ext: Extension) -> dict[str, Any]:
    from . import vault
    cfg = config.load_config()
    return {"id": ext.id, "workspace": str(config.workspace()),
            "state_dir": str(config.state_dir("extensions", ext.id)),
            "secret": vault.get,
            "config": {"timezone": cfg.get("timezone", "UTC"), "language": cfg.get("language", "en"),
                       "public_url": cfg.get("public_url", "")}}


def clean_card(card: Any) -> dict:
    """Validate a Card returned by extension code (raises ValueError with a readable reason)."""
    if not isinstance(card, dict):
        raise ValueError(f"card() must return a dict, got {type(card).__name__}")
    blocks = card.get("blocks", [])
    if not isinstance(blocks, list):
        raise ValueError("card['blocks'] must be a list")
    out = {k: card[k] for k in ("title", "status", "link", "updated") if k in card}
    out["blocks"] = [b for b in blocks if isinstance(b, dict) and b.get("type") in BLOCK_TYPES]
    if out.get("status") not in (None, "ok", "warn", "error"):
        out.pop("status")
    json.dumps(out, allow_nan=False)                   # JSON serialisable as the answer is (NaN/inf: this card fails,
                                                       # not the whole dashboard)
    return out


def widget_card(ext: Extension, force: bool = False) -> dict:
    """card(ctx) through the TTL cache. Blocking; raises on extension errors.
    HTML widgets return a card pointing at their widget.html (drawn by the UI in a sandboxed frame); its
    `updated` is the file's mtime (the UI reloads the frame when it changes) or now when forced (refresh button)."""
    if ext.error:
        raise RuntimeError(ext.error)
    if ext.has_html:
        try:
            updated = time.time() if force else (ext.dir / "widget.html").stat().st_mtime
        except OSError:
            updated = time.time()
        return {"blocks": [], "html": f"/ext/{ext.id}/widget.html", "height": ext.height, "updated": updated}
    if ext.module is None:
        raise RuntimeError("extension is disabled")
    with _lock:
        hit = _cards.get(ext.id)
    if hit and not force and time.time() - hit[0] < ext.ttl:
        return hit[1]
    card = clean_card(ext.module.card(make_ctx(ext)))
    card.setdefault("updated", time.time())
    with _lock:
        _cards[ext.id] = (time.time(), card)
    return card


def handler(ext: Extension) -> Callable[..., Any]:
    fn = getattr(ext.module, "handle", None) if ext.module else None
    if not callable(fn):
        raise LookupError("this extension has no handle(ctx, method, path, query, body)")
    return fn
