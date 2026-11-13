"""The live view of the Harness Browser: which tab is shown, its picture (screencast) for the people watching, their
mouse and keyboard, and the person's tab actions (open, wake, close). Every page it hears of goes through the tabs
registry (tabs.py: scopes).

One DevTools connection for the browser (our own, through `relay.Cdp`: the same command rules). Pictures are only
produced while someone watches (and the picture given to Claude with a hand-back).

Smoothness: Chromium makes the next picture only once the last one is acknowledged, and we acknowledge it only when
every viewer got it (`delivered`, or ACK_LATE at worst): pictures never pile up on a slow connection, the screen shows
the newest page. The JPEG quality follows the time a picture takes to reach the slowest viewer ("auto"), between
Q_MIN and Q_MAX; pictures are never larger than the viewer's own size.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from typing import Any, Callable

from . import rules
from .relay import Cdp

log = logging.getLogger("maxxing.browser")

QUALITY = {"auto": (60, 1920, 1200), "high": (70, 1920, 1200), "low": (40, 960, 960)}   # JPEG quality, largest picture
Q_MIN, Q_MAX, Q_STEP = 30, 70, 10
SLOW_S, FAST_S = 0.25, 0.08          # a picture's way to the slowest viewer: above -> lower quality, below -> higher
ADAPT_EVERY = 3.0                    # at most one quality change this often (each one restarts the screencast)
ACK_LATE = 1.0                       # a viewer that does not confirm a picture holds the others at most this long
SIZE = (1280, 800)                  # the pages' size when nobody watches (Claude's)
MIN_SIZE, MAX_SIZE = (360, 320), (2560, 1600)
INTERNAL = ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://")   # Chromium's own UI pages


def _shown(t: dict) -> bool:
    return t.get("type") == "page" and not str(t.get("url") or "").startswith(INTERNAL)
MODS = {"alt": 1, "ctrl": 2, "meta": 4, "shift": 8}


class Watcher:
    def __init__(self, sock, path: str, sites: Callable[[], list[str] | None], tabs=None) -> None:
        self.sock, self.path, self.sites, self.registry = sock, path, sites, tabs
        self.cdp: Cdp | None = None
        self.pages: dict[str, dict] = {}            # targetId -> {url, title, at}
        self.front: str | None = None               # targetId shown / driven
        self.sessions: dict[str, str] = {}          # targetId -> DevTools session (flatten)
        self.viewers: dict[int, Callable[[Any], Any]] = {}   # id -> send(bytes | dict)
        self.quality: dict[int, str] = {}
        self.casting: str | None = None            # targetId being screencast
        self.meta: dict = {}                        # last frame metadata (device size, offsets)
        self.frame: bytes | None = None
        self.frame_at = 0.0
        self.sleeping: set[str] = set()             # targetIds closed to sleep (their tab stays)
        self.tab_page: dict[str, str] = {}          # "tab" targetId -> the page it holds (Puppeteer attaches to tabs)
        self.tab_sessions: dict[str, str] = {}      # our session on a tab target -> its targetId
        self._tab_ev: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self.size: tuple[int, int] = SIZE           # the pages' size: the live view's while someone watches
        self.sized: dict[int, tuple[int, int]] = {}   # windowId -> the size it was given
        self.extra: tuple[int, int] = (0, 0)          # window size - page size (headless still counts a toolbar)
        self.unacked: tuple[str, object] | None = None   # (DevTools session, frame id) of the picture in flight
        self.waiting: set[int] = set()                # viewers that did not confirm the last picture yet
        self._late: asyncio.TimerHandle | None = None
        self.q = QUALITY["auto"][0]                   # the quality now ("auto" moves it)
        self.trip: dict[int, float] = {}              # viewer -> smoothed time a picture takes to reach it
        self.adapted = time.monotonic()
        self.frames = 0                               # pictures made (stats)
        self.frame_bytes = 0

    async def start(self) -> None:
        self.cdp = await Cdp.open(self.sock, self.path, self._event)
        await self.cdp.call("Target.setDiscoverTargets", {"discover": True})
        for t in (await self.cdp.call("Target.getTargets")).get("targetInfos") or []:
            if self.registry is not None and t.get("type") == "page":
                self.registry.resolve(t)
            if _shown(t):
                self.pages[t["targetId"]] = {"url": t.get("url") or "", "title": t.get("title") or "",
                                             "at": time.time()}
        if self.pages:
            self.front = max(self.pages, key=lambda k: self.pages[k]["at"])
        # which page each tab target holds: attach to tabs, and under each one to its page (never waiting for us)
        await self.cdp.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False,
                                                     "flatten": True, "filter": [{"type": "tab"}]})

    async def page_of(self, tab: str, wait: float = 2.0) -> str | None:
        """The page a tab target holds (waits a little for a new tab)."""
        if tab in self.tab_page or wait <= 0:
            return self.tab_page.get(tab)
        ev = self._tab_ev.setdefault(tab, asyncio.Event())
        try:
            await asyncio.wait_for(ev.wait(), wait)
        except asyncio.TimeoutError:
            pass
        return self.tab_page.get(tab)

    async def stop(self) -> None:
        if self.cdp:
            await self.cdp.close()
            self.cdp = None

    # ---- pages -----------------------------------------------------------------------------------------------
    async def _event(self, m: dict) -> None:
        method, p = m.get("method"), m.get("params") or {}
        if method in ("Target.targetCreated", "Target.targetInfoChanged"):
            t = p.get("targetInfo") or {}
            if self.registry is not None and t.get("type") == "page":
                self.registry.resolve(t)
                self.registry.changed(t)
            if not _shown(t):
                if t.get("targetId") in self.pages:          # moved to an internal page: no longer shown
                    await self._event({"method": "Target.targetDestroyed", "params": {"targetId": t["targetId"]}})
                return
            tid = t["targetId"]
            old = self.pages.get(tid, {})
            moved = old.get("url") != t.get("url")
            self.pages[tid] = {"url": t.get("url") or "", "title": t.get("title") or "",
                               "at": time.time() if (moved or not old) else old.get("at", time.time())}
            if self.on_move and str(t.get("url") or "").startswith(("http://", "https://")):
                try:
                    self.on_move(tid, t.get("url") or "", t.get("title") or "")
                except Exception:  # noqa: BLE001
                    log.exception("browser page move")
            if (moved or method == "Target.targetCreated") and (self.may_follow is None or self.may_follow(tid)):
                await self._show(tid)
            else:
                await self._state()
        elif method == "Target.targetDestroyed":
            tid = p.get("targetId")
            if self.registry is not None:
                self.registry.gone(tid, keep=tid in self.sleeping)
            self.sleeping.discard(tid)
            self.pages.pop(tid, None)
            self.sessions.pop(tid, None)
            if self.front == tid:
                self.front = max(self.pages, key=lambda k: self.pages[k]["at"]) if self.pages else None
                await self._show(self.front)
        elif method == "Target.attachedToTarget":
            info = p.get("targetInfo") or {}
            child = str(p.get("sessionId") or "")
            parent = m.get("sessionId")
            if not parent and info.get("type") == "tab" and self.cdp:
                self.tab_sessions[child] = str(info.get("targetId") or "")
                await self.cdp.send_nowait("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False,
                                                                    "flatten": True, "filter": [{"type": "page"}]}, child)
            elif parent in self.tab_sessions and info.get("type") == "page":
                tab = self.tab_sessions[parent]
                self.tab_page[tab] = str(info.get("targetId") or "")
                if self.registry is not None:
                    self.registry.resolve(info)
                ev = self._tab_ev.pop(tab, None)
                if ev:
                    ev.set()
        elif method == "Target.detachedFromTarget":
            sid = p.get("sessionId")
            tab = self.tab_sessions.pop(str(sid or ""), None)
            if tab:
                self.tab_page.pop(tab, None)
            for k, v in list(self.sessions.items()):
                if v == sid:
                    self.sessions.pop(k, None)
                    if self.casting == k:
                        self.casting = None
        elif method == "Page.screencastFrame":
            await self._frame(m.get("sessionId"), p)

    async def _session(self, tid: str) -> str:
        if tid in self.sessions:
            return self.sessions[tid]
        assert self.cdp
        s = (await self.cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
        self.sessions[tid] = s
        await self.cdp.call("Page.enable", session=s)
        return s

    async def _show(self, tid: str | None) -> None:
        """Put a page in front (the one Claude just opened or navigated): the viewers follow it."""
        async with self._lock:
            if tid != self.front:
                self.front = tid
            if self.viewers:
                await self._cast()
        await self._state()

    # ---- screencast ------------------------------------------------------------------------------------------
    def _want(self) -> tuple[int, int, int]:
        modes = set(self.quality.values())
        mode = "low" if "low" in modes else "auto" if "auto" in modes else "high"
        q, w, h = QUALITY[mode]
        if mode == "auto":
            q = self.q
        return q, min(w, self.size[0]), min(h, self.size[1])

    async def _cast(self) -> None:
        if not self.cdp:
            return
        if self.casting and (self.casting != self.front or not self.viewers):
            s = self.sessions.get(self.casting)
            if s:
                try:
                    await self.cdp.call("Page.stopScreencast", session=s, timeout=5)
                except Exception:  # noqa: BLE001
                    pass
            self.casting = None
        if self.viewers and self.front and self.casting != self.front:
            q, w, h = self._want()
            with contextlib.suppress(Exception):
                await self._fit(self.front)
            try:
                s = await self._session(self.front)
                await self.cdp.call("Page.startScreencast", {"format": "jpeg", "quality": q, "maxWidth": w,
                                                             "maxHeight": h, "everyNthFrame": 1}, session=s)
                self.casting = self.front
            except Exception as e:  # noqa: BLE001
                log.info("screencast: %s", e)

    async def _frame(self, session: str | None, p: dict) -> None:
        if self.sessions.get(self.casting or "") != session or not self.viewers:
            if self.cdp and session:
                await self.cdp.send_nowait("Page.screencastFrameAck", {"sessionId": p.get("sessionId")}, session)
            return
        await self._ack()                           # an older one still waiting (a viewer that left)
        self.meta = p.get("metadata") or {}
        self._learn(self.meta)
        self.frame = base64.b64decode(p.get("data") or "")
        self.frame_at = time.time()
        self.frames += 1
        self.frame_bytes += len(self.frame)
        self.unacked = (str(session), p.get("sessionId"))
        self.waiting = set(self.viewers)
        self._late = asyncio.get_running_loop().call_later(ACK_LATE, lambda: asyncio.ensure_future(self._ack()))
        for send in list(self.viewers.values()):
            try:
                await send(self.frame)
            except Exception:  # noqa: BLE001
                pass

    async def _ack(self) -> None:
        """Let Chromium make the next picture."""
        if self._late is not None:
            self._late.cancel()
            self._late = None
        ack, self.unacked = self.unacked, None
        self.waiting = set()
        if ack and self.cdp:
            with contextlib.suppress(Exception):
                await self.cdp.send_nowait("Page.screencastFrameAck", {"sessionId": ack[1]}, ack[0])

    def delivered(self, vid: int, size: int, secs: float) -> None:
        """A viewer got the last picture (its page confirmed it, `secs` after it was sent)."""
        old = self.trip.get(vid)
        self.trip[vid] = secs if old is None else old * 0.7 + secs * 0.3
        self.waiting.discard(vid)
        if self.unacked and not self.waiting:
            asyncio.ensure_future(self._ack())
        self._adapt()

    def _adapt(self) -> None:
        """"auto": lower the quality while pictures are slow to arrive, raise it back when they are fast."""
        if "auto" not in self.quality.values() or not self.trip or time.monotonic() - self.adapted < ADAPT_EVERY:
            return
        slow = max(self.trip.values())
        q = self.q - Q_STEP if slow > SLOW_S else self.q + Q_STEP // 2 if slow < FAST_S else self.q
        q = max(Q_MIN, min(Q_MAX, q))
        if q != self.q:
            self.q = q
            self.adapted = time.monotonic()
            asyncio.ensure_future(self._restart_cast())

    def stats(self) -> dict:
        return {"q": self.q, "frames": self.frames, "avg_kb": round(self.frame_bytes / self.frames / 1024, 1)
                if self.frames else 0, "trip_ms": int(max(self.trip.values()) * 1000) if self.trip else None}

    async def watch(self, vid: int, send: Callable[[Any], Any], quality: str = "auto") -> None:
        self.viewers[vid] = send
        self.quality[vid] = quality if quality in QUALITY else "auto"
        await self._restart_cast()
        if self.frame:
            await send(self.frame)
        await self._state()

    async def unwatch(self, vid: int) -> None:
        self.viewers.pop(vid, None)
        self.quality.pop(vid, None)
        self.trip.pop(vid, None)
        self.waiting.discard(vid)
        if self.unacked and not self.waiting:
            await self._ack()
        if not self.viewers and self.size != SIZE:      # back to Claude's size
            self.size = SIZE
            if self.front:
                with contextlib.suppress(Exception):
                    await self._fit(self.front)
        await self._restart_cast()

    async def resize(self, w: object, h: object, dpr: object = None) -> None:
        """The live view's size (CSS pixels): the page in front is laid out for it, like a browser window (and its
        pictures are never larger)."""
        try:
            size = (max(MIN_SIZE[0], min(MAX_SIZE[0], int(w))), max(MIN_SIZE[1], min(MAX_SIZE[1], int(h))))
        except (TypeError, ValueError):
            return
        if size == self.size:
            return
        self.size = size
        if self.front:
            await self._fit(self.front)
        if self.viewers:
            await self._restart_cast()

    async def _fit(self, tid: str) -> None:
        """Give the window of this page the current size (headless: the window is the page)."""
        if not self.cdp:
            return
        win = (await self.cdp.call("Browser.getWindowForTarget", {"targetId": tid}, timeout=5)).get("windowId")
        if win is None or self.sized.get(win) == self.size:
            return
        await self.cdp.call("Browser.setWindowBounds", {"windowId": win, "bounds": {
            "width": self.size[0] + self.extra[0], "height": self.size[1] + self.extra[1]}}, timeout=5)
        self.sized[win] = self.size

    def _learn(self, meta: dict) -> None:
        """The first picture after a fit says the page's real size: learn the window's extra height once, fit again.
        (Same width = a picture taken after the fit.)"""
        try:
            dw, dh = int(meta.get("deviceWidth") or 0), int(meta.get("deviceHeight") or 0)
        except (TypeError, ValueError):
            return
        if self.extra != (0, 0) or not self.sized or not self.casting or dw != self.size[0] or not 0 < self.size[1] - dh <= 400:
            return
        self.extra = (0, self.size[1] - dh)
        self.sized.clear()
        asyncio.get_running_loop().create_task(self._refit(self.casting))

    async def _refit(self, tid: str) -> None:
        with contextlib.suppress(Exception):
            await self._fit(tid)

    async def set_quality(self, vid: int, quality: str) -> None:
        """auto (default) | high | low (a phone on a slow network)."""
        if vid in self.viewers and quality in QUALITY:
            self.quality[vid] = quality
            await self._restart_cast()

    async def _restart_cast(self) -> None:
        await self._ack()
        async with self._lock:
            if self.casting and self.cdp:
                s = self.sessions.get(self.casting)
                if s:
                    try:
                        await self.cdp.call("Page.stopScreencast", session=s, timeout=5)
                    except Exception:  # noqa: BLE001
                        pass
                self.casting = None
            await self._cast()

    # ---- state for the viewers -------------------------------------------------------------------------------
    def tabs(self) -> list[dict]:
        return [{"id": k, "url": rules_page(v["url"]), "title": v["title"][:120], "front": k == self.front}
                for k, v in sorted(self.pages.items(), key=lambda kv: kv[1]["at"])]

    def front_page(self) -> dict:
        p = self.pages.get(self.front or "", {})
        return {"url": rules_page(p.get("url", "")), "title": (p.get("title") or "")[:120]}

    on_state: Callable[[], Any] | None = None
    on_move: Callable[[str, str, str], None] | None = None     # (targetId, url, title) of a page that changed
    may_follow: Callable[[str], bool] | None = None            # a page opened / moved: show it to the viewers?

    # ---- tabs ------------------------------------------------------------------------------------------------
    async def open_tab(self, url: str = "about:blank") -> str:
        """A new page (the caller claimed its scope first: tabs.claim). Returns its targetId."""
        assert self.cdp
        r = await self.cdp.call("Target.createTarget", {"url": url or "about:blank"})
        return str(r.get("targetId") or "")

    async def close_tab(self, tid: str, sleep: bool = False) -> None:
        if not self.cdp:
            return
        if sleep:
            self.sleeping.add(tid)
        try:
            await self.cdp.call("Target.closeTarget", {"targetId": tid}, timeout=10)
        except Exception:  # noqa: BLE001 - already gone
            self.sleeping.discard(tid)
            if self.registry is not None:
                self.registry.gone(tid, keep=sleep)
            self.pages.pop(tid, None)

    async def show(self, tid: str) -> None:
        if tid in self.pages:
            self.pages[tid]["at"] = time.time()
            await self._show(tid)

    async def _state(self) -> None:
        if self.on_state:
            try:
                r = self.on_state()
                if asyncio.iscoroutine(r):
                    await r
            except Exception:  # noqa: BLE001
                log.exception("browser state")

    # ---- the person who took over ----------------------------------------------------------------------------
    async def input(self, ev: dict) -> str | None:
        """One input event from the viewer in control. Coordinates are 0..1 of the picture. Returns an error text."""
        if not self.cdp or not self.front:
            return "no page"
        s = await self._session(self.front)
        t = ev.get("t")
        dw = float(self.meta.get("deviceWidth") or 1280)
        dh = float(self.meta.get("deviceHeight") or 800)
        mods = sum(v for k, v in MODS.items() if ev.get(k))

        def xy() -> tuple[float, float]:
            return (max(0.0, min(1.0, float(ev.get("x") or 0))) * dw,
                    max(0.0, min(1.0, float(ev.get("y") or 0))) * dh)
        if t == "mouse":
            kind = {"down": "mousePressed", "up": "mouseReleased", "move": "mouseMoved"}.get(ev.get("type"))
            if not kind:
                return "bad mouse event"
            x, y = xy()
            await self.cdp.call("Input.dispatchMouseEvent", {
                "type": kind, "x": x, "y": y, "modifiers": mods,
                "button": ev.get("button") if ev.get("button") in ("left", "middle", "right") else (
                    "none" if kind == "mouseMoved" else "left"),
                "clickCount": int(ev.get("clicks") or (0 if kind == "mouseMoved" else 1))}, session=s)
        elif t == "wheel":
            x, y = xy()
            await self.cdp.call("Input.dispatchMouseEvent", {
                "type": "mouseWheel", "x": x, "y": y, "modifiers": mods,
                "deltaX": float(ev.get("dx") or 0), "deltaY": float(ev.get("dy") or 0)}, session=s)
        elif t == "key":
            kind = {"down": "keyDown", "up": "keyUp"}.get(ev.get("type"))
            if not kind:
                return "bad key event"
            key = str(ev.get("key") or "")[:32]
            params = {"type": kind, "key": key, "code": str(ev.get("code") or "")[:32], "modifiers": mods,
                      "windowsVirtualKeyCode": int(ev.get("keyCode") or 0)}
            text = str(ev.get("text") or "")
            if kind == "keyDown" and len(text) == 1 and not (mods & 6):
                params["text"] = text
            await self.cdp.call("Input.dispatchKeyEvent", params, session=s)
        elif t == "text":
            text = str(ev.get("text") or "")[:2000]
            if text:
                await self.cdp.call("Input.insertText", {"text": text}, session=s)
        elif t == "nav":
            url = str(ev.get("url") or "").strip()
            if url and "://" not in url:
                url = "https://" + url
            why = rules.page_refusal(url, self.sites())
            if why:
                return why
            await self.cdp.call("Page.navigate", {"url": url}, session=s)
        elif t in ("back", "forward"):
            h = await self.cdp.call("Page.getNavigationHistory", session=s)
            i = int(h.get("currentIndex", 0)) + (-1 if t == "back" else 1)
            entries = h.get("entries") or []
            if 0 <= i < len(entries):
                await self.cdp.call("Page.navigateToHistoryEntry", {"entryId": entries[i]["id"]}, session=s)
        elif t == "reload":
            await self.cdp.call("Page.reload", session=s)
        else:
            return "unknown event"
        return None

    async def picture(self, quality: int = 50, width: int = 960, tid: str | None = None) -> bytes | None:
        """A small picture of a page (the one shown by default)."""
        tid = tid or self.front
        if not self.cdp or not tid or tid not in self.pages:
            return None
        try:
            s = await self._session(tid)
            vp = (await self.cdp.call("Page.getLayoutMetrics", session=s, timeout=10)).get("cssVisualViewport") or {}
            cw = float(vp.get("clientWidth") or 1280)
            clip = {"x": float(vp.get("pageX") or 0), "y": float(vp.get("pageY") or 0), "width": cw,
                    "height": float(vp.get("clientHeight") or 800), "scale": min(1.0, width / cw)}
            r = await self.cdp.call("Page.captureScreenshot", {"format": "jpeg", "quality": quality, "clip": clip,
                                                               "optimizeForSpeed": True}, session=s, timeout=15)
            return base64.b64decode(r.get("data") or "")
        except Exception as e:  # noqa: BLE001
            log.info("browser picture: %s", e)
            return None


def rules_page(url: str) -> str:
    from .replays import page
    return page(url) if url.startswith(("http://", "https://")) else url[:40]


def dumps(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)
