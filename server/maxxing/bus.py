"""Global invalidation bus -> `GET /api/stream` (SSE).

Any code (async or a worker thread) calls `invalidate("sessions", "tasks")`; every connected
browser receives `event: invalidate` with the topics and refetches the matching queries.
Topics: sessions, workspace, tasks, crons, telegram, backup, health, extensions.
"""
from __future__ import annotations

import asyncio
import json
import threading

_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None
_lock = threading.Lock()
_browsers = 0                                   # open /api/stream connections of signed-in browsers


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def _publish(topics: tuple[str, ...]) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(topics)
        except asyncio.QueueFull:                # a stalled client: merge instead of losing topics
            merged = set(topics)
            while not q.empty():
                merged.update(q.get_nowait())
            q.put_nowait(tuple(sorted(merged)))


def browser_count() -> int:
    """Browsers on the interface right now (an open tab holds one stream)."""
    return _browsers


def subscribe(maxsize: int = 200) -> asyncio.Queue:
    """Server-side listener (on the bound loop): receives the same topic tuples as the browsers."""
    q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def invalidate(*topics: str) -> None:
    """Thread-safe: may be called from the event loop or from any thread."""
    if not topics or _loop is None or _loop.is_closed():
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is _loop:
        _publish(topics)
    else:
        try:
            _loop.call_soon_threadsafe(_publish, topics)
        except RuntimeError:          # loop closed between the check and the call
            pass


async def stream(cookie: str | None = None, check: bool = True):
    """Async generator of SSE frames for one client. Its sign-in cookie is re-checked before every frame (at least
    every 15 s, the ping): signed out, password changed or expired -> the stream ends (`check=False`: no cookie
    check, server-side callers only)."""
    from .security import StreamAuth
    auth = StreamAuth(cookie) if check else None
    global _browsers
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    if check:
        _browsers += 1
    try:
        yield "retry: 3000\n\n"
        while True:
            try:
                topics = await asyncio.wait_for(q.get(), timeout=15)
            except asyncio.TimeoutError:
                if auth is not None and not auth.ok():
                    return
                yield ": ping\n\n"
                continue
            if auth is not None and not auth.ok():
                return
            merged = set(topics)
            while not q.empty():                       # coalesce bursts
                merged.update(q.get_nowait())
            yield "event: invalidate\ndata: " + json.dumps({"topics": sorted(merged)}) + "\n\n"
    finally:
        _subscribers.discard(q)
        if check:
            _browsers -= 1
