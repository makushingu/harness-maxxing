"""The devices' websockets (WS /api/devices/ws, out of each Harness Link): many devices at once, requests with ids.

Server -> device: `shot`, `input`, `tree`, `tap_node`, `set_text`, `apps`, `open` (answered `ok` / `err` with the same
`id`), `state` (no answer: who is using it), `unpair`. Device -> server: `hello`, `paused`, answers. Protocol:
link/PROTOCOL.md (v2).

Who has the device: Claude (its tools, `busy` while it acts), or the person (the live view: they take over, then hand
back with a word). While the person has it, Claude's input is refused.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import math
import logging
import time
from typing import Any, Callable

from . import store

log = logging.getLogger("maxxing.devices")

MAX_FRAME = 16 * 1024 * 1024
CLAUDE_BUSY_S = 15.0                 # Claude's last action this long ago: the device stops showing "Claude is using it"
LIVE_FPS = 3.0
LIVE_MAX_W = 1280
LIVE_QUALITY = 55
TIMEOUTS = {"shot": 20.0, "input": 15.0, "tree": 20.0, "tap_node": 15.0, "set_text": 15.0, "apps": 20.0, "open": 20.0}


def finite(v) -> bool:
    """A real, finite number (a huge integer such as 10**400 is not: math.isfinite raises OverflowError on it)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:
        return False


class Offline(Exception):
    pass


class DeviceError(Exception):
    """An `err` answer of the device (code: paused, protected, locked, unsupported, bad_request...)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code, self.message = code, message or code


class Conn:
    def __init__(self, ws: Any, device_id: str) -> None:
        self.ws = ws
        self.id = device_id
        self.hello: dict = {}
        self.paused = False
        self.since = time.time()
        self._ids = 0
        self.wait: dict[int, asyncio.Future] = {}
        self.lock = asyncio.Lock()
        self.busy: tuple[bool, str] = (False, "")
        self.access: tuple[bool, str] | None = None   # (accepted, mode) last told to the app
        self.display: int | None = None               # the screen last asked of the app
        self.watched = False                          # the app was told someone watches the live view


class Hub:
    def __init__(self) -> None:
        self.conns: dict[str, Conn] = {}
        self.human: dict[str, tuple[int, float]] = {}          # device -> (viewer id, since): the person has it
        self.claude_at: dict[str, float] = {}                 # device -> Claude's last action
        self.used_by: dict[str, dict] = {}                    # device -> {session, owner, at}: who used it last
        self.shots: dict[str, tuple[int, int]] = {}           # device -> (w, h) of the last picture Claude got
        self.viewers: dict[str, dict[int, Callable[[Any], None]]] = {}
        self._frames: dict[str, asyncio.Task] = {}
        self._ticker: asyncio.Task | None = None

    # ---- state ----
    def online(self, device_id: str) -> bool:
        return device_id in self.conns

    def conn(self, device_id: str) -> Conn | None:
        return self.conns.get(device_id)

    def paused(self, device_id: str) -> bool:
        c = self.conns.get(device_id)
        return bool(c and c.paused)

    def human_has(self, device_id: str) -> bool:
        return device_id in self.human

    def public(self, device_id: str) -> dict:
        c = self.conns.get(device_id)
        u = self.used_by.get(device_id)
        claude = time.time() - self.claude_at.get(device_id, 0) < CLAUDE_BUSY_S
        return {"online": c is not None, "paused": bool(c and c.paused), "human": device_id in self.human,
                "claude": claude, "used_by": u if u and claude else None, "watched": bool(self.viewers.get(device_id)),
                "hello": ({k: c.hello.get(k) for k in ("v", "os", "arch", "caps", "screen", "note", "screens", "display")}
                          if c else None)}

    # ---- the app's connection ----
    async def serve(self, ws: Any, dev: dict) -> None:
        old = self.conns.get(dev["id"])
        if old is not None:                            # a reconnect: the old socket is dead or a duplicate
            await self._close(old, 4000)
        c = Conn(ws, dev["id"])
        self.conns[dev["id"]] = c
        self._ensure_ticker()
        _invalidate()
        try:
            await self._state(c)
            await self._access(c, dev)
            await self._watch(c)
            while True:
                try:
                    raw = await ws.receive_text()
                except KeyError:                       # a binary frame: not part of the protocol
                    continue
                if len(raw) > MAX_FRAME:
                    continue
                try:
                    msg = json.loads(raw)
                except (ValueError, RecursionError):
                    continue
                if isinstance(msg, dict):
                    try:
                        await self._on(c, msg)
                    except (TypeError, ValueError, AttributeError, KeyError) as e:   # a malformed frame only
                        log.warning("device %s: frame %r ignored: %s", c.id, msg.get("t"), e)
        finally:
            if self.conns.get(dev["id"]) is c:
                self._gone(c)

    async def _on(self, c: Conn, msg: dict) -> None:
        t = msg.get("t")
        if t == "hello":
            scr = msg.get("screen") if isinstance(msg.get("screen"), dict) else {}
            screen = {k: scr.get(k) for k in ("w", "h", "scale")
                      if finite(scr.get(k))} or None
            caps = [store._text(x, 16) for x in (msg.get("caps") or [])[:10] if isinstance(x, str)]
            screens = []
            for x in (msg.get("screens") or [])[:16] if isinstance(msg.get("screens"), list) else []:
                if isinstance(x, dict) and isinstance(x.get("i"), int):
                    screens.append({"i": x["i"], "name": store._text(x.get("name"), 64),
                                    "w": x.get("w") if isinstance(x.get("w"), int) else 0,
                                    "h": x.get("h") if isinstance(x.get("h"), int) else 0, "main": bool(x.get("main"))})
            c.hello = {"v": store._text(msg.get("v"), 32), "os": store._text(msg.get("os"), 16),
                       "arch": store._text(msg.get("arch"), 16), "name": store._text(msg.get("name"), 64),
                       "caps": caps, "screen": screen, "note": store._text(msg.get("note"), 1000),
                       "screens": screens, "display": msg.get("display") if isinstance(msg.get("display"), int) else None}
            await asyncio.to_thread(store.touch, c.id, version=c.hello["v"], arch=c.hello["arch"], caps=caps,
                                    screen=screen, note=c.hello["note"], screens=screens)
            _invalidate()
        elif t == "paused":
            c.paused = bool(msg.get("on"))
            _invalidate()
        elif t in ("ok", "err"):
            fut = c.wait.get(msg.get("id")) if isinstance(msg.get("id"), int) else None
            if fut and not fut.done():
                fut.set_result(msg)

    def _gone(self, c: Conn) -> None:
        self.conns.pop(c.id, None)
        self.human.pop(c.id, None)
        for f in c.wait.values():
            if not f.done():
                f.set_exception(Offline())
        with contextlib.suppress(Exception):
            store.touch(c.id)                           # last seen
        _invalidate()

    async def _close(self, c: Conn, code: int) -> None:
        if self.conns.get(c.id) is c:
            self._gone(c)
        with contextlib.suppress(Exception):
            await c.ws.close(code=code)

    async def unpair(self, device_id: str) -> None:
        """Removed or refused: the app forgets this server and stops (its token is already revoked)."""
        c = self.conns.get(device_id)
        self.used_by.pop(device_id, None)
        self.shots.pop(device_id, None)
        if c is None:
            return
        with contextlib.suppress(Exception):
            await self.send(c, {"t": "unpair"})
        await self._close(c, 4001)

    # ---- requests ----
    async def send(self, c: Conn, msg: dict) -> None:
        async with c.lock:
            await c.ws.send_text(json.dumps(msg))

    async def request(self, device_id: str, msg: dict, timeout: float | None = None) -> dict:
        """Send a request, wait for its answer. Offline / DeviceError / asyncio.TimeoutError."""
        c = self.conns.get(device_id)
        if c is None:
            raise Offline()
        if c.paused:
            raise DeviceError("paused", "paused on the device")
        c._ids += 1
        rid = c._ids
        fut = asyncio.get_running_loop().create_future()
        c.wait[rid] = fut
        try:
            try:
                await self.send(c, {**msg, "id": rid})
            except Exception as e:  # noqa: BLE001 - the socket went away mid-send
                raise Offline() from e
            r = await asyncio.wait_for(fut, timeout or TIMEOUTS.get(str(msg.get("t")), 20.0))
        finally:
            c.wait.pop(rid, None)
        if r.get("t") == "err":
            raise DeviceError(str(r.get("code") or "error")[:40], store._text(r.get("message"), 1000))
        return r

    # ---- who has it ----
    async def _state(self, c: Conn) -> None:
        if c.id in self.human:
            want = (True, "human")
        elif time.time() - self.claude_at.get(c.id, 0) < CLAUDE_BUSY_S:
            want = (True, "claude")
        else:
            want = (False, "")
        if want != c.busy:
            c.busy = want
            with contextlib.suppress(Exception):
                await self.send(c, {"t": "state", "busy": want[0], "by": want[1] or None})

    async def _access(self, c: Conn, dev: dict | None) -> None:
        """Tell the app whether it is accepted and its mode, when that changed (its terminal says it)."""
        if dev is None:
            return
        want = (bool(dev.get("confirmed")), "control" if dev.get("mode") == "control" else "view")
        if want != c.access:
            c.access = want
            with contextlib.suppress(Exception):
                await self.send(c, {"t": "access", "ok": want[0], "mode": want[1]})
        disp = dev.get("display") if isinstance(dev.get("display"), int) else -1
        if disp != (c.display if c.display is not None else -1) or (c.display is None and disp >= 0):
            c.display = disp
            with contextlib.suppress(Exception):
                await self.send(c, {"t": "display", "i": disp})

    async def _watch(self, c: Conn) -> None:
        """Tell the app when the live view opens and closes (its terminal says so instead of listing pictures)."""
        on = bool(self.viewers.get(c.id))
        if on != c.watched:
            c.watched = on
            with contextlib.suppress(Exception):
                await self.send(c, {"t": "watch", "on": on})

    async def access_changed(self, device_id: str) -> None:
        """Accepted, or its mode changed: told to the app now (the ticker would within 3 s)."""
        c = self.conns.get(device_id)
        if c is not None:
            await self._access(c, await asyncio.to_thread(store.get, device_id))

    async def claude_acted(self, device_id: str, session: str = "", owner: str = "") -> None:
        now = time.time()
        fresh = now - self.claude_at.get(device_id, 0) >= CLAUDE_BUSY_S or \
            (self.used_by.get(device_id) or {}).get("session") != session
        self.claude_at[device_id] = now
        self.used_by[device_id] = {"session": session, "owner": owner, "at": now}
        c = self.conns.get(device_id)
        if c is not None:
            await self._state(c)
        if fresh:
            _invalidate()

    async def take(self, device_id: str, vid: int) -> None:
        cur = self.human.get(device_id)
        if cur is None or cur[0] != vid:
            self.human[device_id] = (vid, time.time())
            _invalidate()
        c = self.conns.get(device_id)
        if c is not None:
            await self._state(c)

    async def release(self, device_id: str, vid: int | None = None) -> bool:
        cur = self.human.get(device_id)
        if cur is None or (vid is not None and cur[0] != vid):
            return False
        self.human.pop(device_id, None)
        c = self.conns.get(device_id)
        if c is not None:
            await self._state(c)
        _invalidate()
        return True

    def _ensure_ticker(self) -> None:
        if self._ticker is None or self._ticker.done():
            self._ticker = asyncio.get_running_loop().create_task(self._tick())

    async def _tick(self) -> None:
        """Claude idle for a while: the device stops saying "Claude is using it". A device removed from elsewhere
        (`maxxing devices remove`): its app is told to forget this server."""
        while True:
            await asyncio.sleep(3)
            try:
                known = {d["id"]: d for d in await asyncio.to_thread(store.devices)} if self.conns else {}
            except Exception:  # noqa: BLE001 - an unreadable file: check again next time
                known = {i: None for i in self.conns}
            for c in list(self.conns.values()):
                if c.id not in known:
                    await self.unpair(c.id)
                    continue
                await self._access(c, known[c.id])    # accepted / mode changed from the CLI
                if c.busy == (True, "claude"):
                    await self._state(c)
                    if not c.busy[0]:
                        _invalidate()

    # ---- live pictures ----
    def watch(self, device_id: str, vid: int, push: Callable[[Any], None]) -> None:
        """`push(jpeg bytes)` never waits (the viewer keeps only the newest picture)."""
        self.viewers.setdefault(device_id, {})[vid] = push
        t = self._frames.get(device_id)
        if t is None or t.done():
            self._frames[device_id] = asyncio.get_running_loop().create_task(self._pictures(device_id))
        self._tell_watch(device_id)
        _invalidate()

    def unwatch(self, device_id: str, vid: int) -> None:
        v = self.viewers.get(device_id) or {}
        v.pop(vid, None)
        if not v:
            self.viewers.pop(device_id, None)
            t = self._frames.pop(device_id, None)
            if t is not None:
                t.cancel()
        self._tell_watch(device_id)
        _invalidate()

    def _tell_watch(self, device_id: str) -> None:
        c = self.conns.get(device_id)
        if c is not None and c.watched != bool(self.viewers.get(device_id)):
            asyncio.get_running_loop().create_task(self._watch(c))

    async def _pictures(self, device_id: str) -> None:
        """~3 pictures a second while someone watches; nothing asked of the device otherwise."""
        import base64
        while self.viewers.get(device_id):
            t0 = time.monotonic()
            try:
                r = await self.request(device_id, {"t": "shot", "max_w": LIVE_MAX_W, "quality": LIVE_QUALITY,
                                                   "live": True})
                data = base64.b64decode(str(r.get("jpeg") or ""), validate=False)
                if data:
                    for push in list((self.viewers.get(device_id) or {}).values()):
                        push(data)
            except (Offline, DeviceError, asyncio.TimeoutError, ValueError):
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("live pictures of %s", device_id)
                await asyncio.sleep(1.0)
            await asyncio.sleep(max(0.05, 1.0 / LIVE_FPS - (time.monotonic() - t0)))

    async def shutdown(self) -> None:
        for t in [self._ticker, *self._frames.values()]:
            if t is not None:
                t.cancel()
        for c in list(self.conns.values()):
            with contextlib.suppress(Exception):
                await c.ws.close(code=1001)


def _invalidate() -> None:
    from .. import bus
    bus.invalidate("devices")


_hub = Hub()


def hub() -> Hub:
    return _hub
