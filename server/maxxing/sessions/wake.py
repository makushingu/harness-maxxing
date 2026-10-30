"""Wake-ups on session file changes (inotify through `watchfiles`), instead of polling the folder.

One thread watches the sessions folder (not recursive) and, on the event loop, wakes whoever waits on a session id
(its log or meta changed: the SSE streams) and, for a meta change, the turn-end watcher (key ANY). A waiter takes
its event with `mark(key)` BEFORE it looks at the files, then awaits it with `wait(ev, timeout)`: a change made in
between has already set it, so nothing is missed. When the watch cannot run (no inotify, too many watches, another
event loop) `mark` returns None and the callers keep their short polling intervals. A sessions folder moved,
replaced (a restore) or changed in the settings is watched again from the next `mark`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path

from . import store

log = logging.getLogger("maxxing.sessions.wake")

ANY = "*"                     # key woken by any meta (<id>.json) change
DEBOUNCE_MS = 100             # changes are handed over at most this long after the first one…
STEP_MS = 50                  # …or once the folder has been quiet this long
ENABLED = os.environ.get("MAXXING_INOTIFY", "1") != "0"


class _Hub:
    def __init__(self, folder: Path, loop: asyncio.AbstractEventLoop) -> None:
        self.folder = folder
        self.ident = _ident(folder)                 # the folder watched, not its path: a replaced one is another
        self.loop = loop
        self.stop = threading.Event()
        self.ok = False
        self.events: dict[str, asyncio.Event] = {}
        self.thread = threading.Thread(target=self._run, name="session-wake", daemon=True)

    def _run(self) -> None:
        try:
            from watchfiles._rust_notify import RustNotify
            with RustNotify([str(self.folder)], False, False, 0, False, True) as w:
                self.ok = True
                while not self.stop.is_set():
                    r = w.watch(DEBOUNCE_MS, STEP_MS, 1000, self.stop)
                    if isinstance(r, set) and r:
                        keys = set()
                        for _, p in r:
                            name = os.path.basename(p)
                            if store.is_valid_id(name[:36]):
                                keys.add(name[:36])
                                if name[36:41] == ".json":
                                    keys.add(ANY)
                        if keys:
                            try:
                                self.loop.call_soon_threadsafe(self._fire, keys)
                            except RuntimeError:          # the loop is closed
                                return
        except Exception as e:  # noqa: BLE001 - no inotify: the callers poll
            log.warning("session file watch unavailable (%s): polling instead", e)
        finally:
            self.ok = False

    def _fire(self, keys: set[str]) -> None:
        for k in keys:
            ev = self.events.pop(k, None)
            if ev is not None:
                ev.set()


_hub: _Hub | None = None
_lock = threading.Lock()


def _ident(folder: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(folder)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def start() -> bool:
    """Watch the current sessions folder from the running event loop (again when either changed). -> active."""
    global _hub
    if not ENABLED:
        return False
    loop = asyncio.get_running_loop()
    folder = store.sessions_dir()
    with _lock:
        h = _hub
        if (h is not None and h.folder == folder and h.ident == _ident(folder) and h.loop is loop
                and h.thread.is_alive()):
            return True
        if h is not None:
            h.stop.set()
        _hub = _Hub(folder, loop)
        _hub.thread.start()
    return True


def stop() -> None:
    global _hub
    with _lock:
        if _hub is not None:
            _hub.stop.set()
            _hub = None


def active() -> bool:
    h = _hub
    if h is None or not h.ok or not h.thread.is_alive() or h.folder != store.sessions_dir():
        return False
    if h.ident is None or h.ident != _ident(h.folder):
        return False
    try:
        return asyncio.get_running_loop() is h.loop
    except RuntimeError:
        return False


def mark(key: str) -> asyncio.Event | None:
    """The event the next change of `key` (a session id, or ANY) sets; None when changes are not watched."""
    if not active():
        _rewatch()
        return None
    h = _hub
    assert h is not None
    ev = h.events.get(key)
    if ev is None:
        ev = h.events[key] = asyncio.Event()
    return ev


def _rewatch() -> None:
    """Watch again when the sessions folder is another one than the hub's (its path or the folder itself)."""
    h = _hub
    if h is None:
        return
    folder = store.sessions_dir()
    ident = _ident(folder)
    if ident is None or (h.folder == folder and h.ident == ident):
        return                                   # no folder yet, or the same one (the hub failed: poll)
    try:
        if asyncio.get_running_loop() is h.loop:
            start()
    except RuntimeError:
        pass


async def wait(ev: asyncio.Event | None, timeout: float) -> bool:
    """Until `ev` is set or `timeout` seconds passed (just a sleep without an event). -> woken by a change."""
    if ev is None:
        await asyncio.sleep(timeout)
        return False
    try:
        await asyncio.wait_for(ev.wait(), timeout)
        return True
    except asyncio.TimeoutError:
        return False
