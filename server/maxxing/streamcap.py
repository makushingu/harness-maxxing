"""Caps on concurrent SSE streams (audit F01): each open stream holds a polling loop and a socket for as long as the
client keeps it, so one sign-in (or all of them together) may hold only so many. Beyond a cap the request gets a
clean `429 {"error": "too_many_streams"}` with `Retry-After` (the UI's EventSource wrapper retries with backoff).

A slot is taken when the endpoint answers and given back when the response ends - however it ends: `CappedStream`
releases it after `StreamingResponse.__call__` (also when the client left before the first frame, when the body
generator never starts), with a GC finalizer as the last resort. Releasing twice is harmless."""
from __future__ import annotations

import threading
import weakref

from fastapi.responses import JSONResponse, StreamingResponse

PER_SIGNIN = 24        # one sign-in (one browser): /api/stream + session streams of every tab and pane
TOTAL = 96             # every sign-in together
RETRY_AFTER_S = 5

_lock = threading.Lock()
_open: dict[str, int] = {}


def counts() -> tuple[int, dict[str, int]]:
    with _lock:
        return sum(_open.values()), dict(_open)


class Slot:
    def __init__(self, key: str):
        self.key = key
        self._done = False

    def release(self) -> None:
        with _lock:
            if self._done:
                return
            self._done = True
            n = _open.get(self.key, 0) - 1
            if n > 0:
                _open[self.key] = n
            else:
                _open.pop(self.key, None)


def acquire(key: str) -> Slot | None:
    """A slot for sign-in `key`, or None when that sign-in or the server is at its cap."""
    with _lock:
        if sum(_open.values()) >= TOTAL or _open.get(key, 0) >= PER_SIGNIN:
            return None
        _open[key] = _open.get(key, 0) + 1
    return Slot(key)


def too_many() -> JSONResponse:
    return JSONResponse({"error": "too_many_streams",
                         "message": "Too many live views are open; close some tabs or panes"},
                        status_code=429, headers={"Retry-After": str(RETRY_AFTER_S), "Cache-Control": "no-store"})


class CappedStream(StreamingResponse):
    def __init__(self, content, slot: Slot, **kw):
        super().__init__(content, **kw)
        self._slot = slot
        weakref.finalize(self, slot.release)

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._slot.release()


def stream_response(cookie: str | None, content_factory, **kw):
    """`CappedStream` of `content_factory()` holding a slot of the sign-in of `cookie`, or the 429. The body generator
    is only created once the slot is held."""
    from .security import session_id
    slot = acquire(session_id(cookie) if cookie else "")
    if slot is None:
        return too_many()
    try:
        return CappedStream(content_factory(), slot, **kw)
    except BaseException:
        slot.release()
        raise
