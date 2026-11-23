"""DevTools between a client of this server (chrome-devtools-mcp, the live view) and a browser's cdp.sock.

Every command going to the browser passes `rules.check_command` (rules.json) and, when it opens a page, the allowed
sites (`rules.page_refusal`): a refused one gets a DevTools error answer, the browser never sees it. A turn's tools
see only their navigator's tabs (view.py: what is dropped, refused, made by the server), and wait while the person has
the tab they act on.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

from websockets.asyncio.client import unix_connect
from websockets.exceptions import ConnectionClosed

from . import rules

log = logging.getLogger("maxxing.browser")
MAX_FRAME = 64 * 1024 * 1024
OPENS_PAGE = {"Page.navigate", "Target.createTarget"}


def filter_command(raw: str | bytes, sites: list[str] | None) -> tuple[str | None, str | None]:
    """(what to send to the browser, or None) and (the error answer for the client, or None)."""
    why, cmd = rules.check_command(raw)
    if why is None and cmd and cmd.get("method") in OPENS_PAGE:
        url = (cmd.get("params") or {}).get("url")
        if isinstance(url, str) and url:
            why = rules.page_refusal(url, sites)
    if why is not None:
        return None, rules.refusal(cmd, why)
    return (raw.decode() if isinstance(raw, bytes) else raw), None


async def connect(sock: Path, path: str):
    return await unix_connect(str(sock), "ws://localhost" + path, max_size=MAX_FRAME, ping_interval=None,
                              open_timeout=10)


async def pump(sock: Path, path: str, sites: Callable[[], list[str] | None],
               recv: Callable[[], Awaitable[str | None]], send: Callable[[str], Awaitable[None]],
               view=None, wait_tab: Callable[[str], Awaitable[str | None]] | None = None) -> None:
    """Relay one client (recv/send: its side) to the browser until either side closes. view (view.View): what a
    turn's tools may see (their navigator's tabs); wait_tab(targetId): waits while the person has that tab, returns
    why it gave up (or None)."""
    up = await connect(sock, path)

    async def down() -> None:
        try:
            async for msg in up:
                text = msg if isinstance(msg, str) else msg.decode()
                if view is not None:
                    try:
                        m = json.loads(text)
                    except ValueError:
                        m = None
                    if isinstance(m, dict):
                        out, extra = await view.incoming(m)
                        for c in extra:
                            await up.send(json.dumps(c))
                        if out is None:
                            continue
                        if out is not m:
                            text = json.dumps(out)
                await send(text)
        except ConnectionClosed:
            pass

    async def out() -> None:
        while True:
            msg = await recv()
            if msg is None:
                return
            fwd, err = filter_command(msg, sites())
            if fwd is not None and view is not None:
                try:
                    cmd = json.loads(fwd)
                except ValueError:
                    cmd = {}
                why = None if isinstance(cmd, dict) else "not a DevTools command"
                if why is None and cmd.get("method") == "Target.createTarget" and not cmd.get("sessionId"):
                    await send(json.dumps(await view.new_tab(cmd)))
                    continue
                if why is None:
                    why = view.outgoing(cmd)
                if why is None and wait_tab is not None and cmd.get("sessionId"):
                    target = view.page(str(cmd["sessionId"]))
                    if target:
                        why = await wait_tab(target)
                if why is not None:
                    fwd, err = None, rules.refusal(cmd if isinstance(cmd, dict) else None, why)
            if fwd is not None:
                await up.send(fwd)
            elif err is not None:
                await send(err)

    tasks = [asyncio.create_task(down()), asyncio.create_task(out())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await up.close()


class Cdp:
    """A small DevTools client of our own (live view, pictures): calls with answers, events to a callback.

    Events are handed to the callback in order by a task of their own, so a callback may make calls (their answers
    are read meanwhile) and a slow one never holds the answers of the others."""

    def __init__(self, ws, on_event: Callable[[dict], Awaitable[None] | None] | None = None) -> None:
        self.ws, self.on_event = ws, on_event
        self._id = 0
        self._wait: dict[int, asyncio.Future] = {}
        self._events: asyncio.Queue = asyncio.Queue()
        self._task = asyncio.create_task(self._read())
        self._etask = asyncio.create_task(self._dispatch()) if on_event is not None else None

    @classmethod
    async def open(cls, sock: Path, path: str, on_event=None) -> "Cdp":
        return cls(await connect(sock, path), on_event)

    @property
    def closed(self) -> bool:
        return self._task.done()

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                f = self._wait.pop(m.get("id"), None) if "id" in m else None
                if f is not None:
                    if not f.done():
                        f.set_result(m)
                elif self.on_event is not None:
                    self._events.put_nowait(m)
        except ConnectionClosed:
            pass
        finally:
            for f in self._wait.values():
                if not f.done():
                    f.set_exception(ConnectionError("the browser closed"))
            self._events.put_nowait(None)

    async def _dispatch(self) -> None:
        while True:
            m = await self._events.get()
            if m is None:
                return
            try:
                r = self.on_event(m)
                if asyncio.iscoroutine(r):
                    await r
            except Exception:  # noqa: BLE001
                log.exception("browser event handler")

    async def call(self, method: str, params: dict | None = None, session: str | None = None,
                   timeout: float = 30.0) -> dict:
        self._id += 1
        msg: dict = {"id": self._id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        raw = json.dumps(msg)
        why, _ = rules.check_command(raw)
        if why:
            raise PermissionError(why)
        f = asyncio.get_running_loop().create_future()
        self._wait[self._id] = f
        await self.ws.send(raw)
        m = await asyncio.wait_for(f, timeout)
        if "error" in m:
            raise RuntimeError(str((m["error"] or {}).get("message") or m["error"]))
        return m.get("result") or {}

    async def send_nowait(self, method: str, params: dict | None = None, session: str | None = None) -> None:
        self._id += 1
        msg: dict = {"id": self._id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        raw = json.dumps(msg)
        if rules.check_command(raw)[0] is None:
            await self.ws.send(raw)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.ws.close()
        self._task.cancel()
        if self._etask is not None:
            self._etask.cancel()
