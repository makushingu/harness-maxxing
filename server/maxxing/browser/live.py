"""The live view of the Harness Browser: for each navigator (navs.py) the tab it shows, its picture (screencast) for
the people watching it, their mouse and keyboard, and the person's tab actions (open, wake, close). Every page it hears
of goes through the tabs registry (tabs.py: its navigator and who opened it).

One DevTools connection for the browser (our own, through `relay.Cdp`: the same command rules). Each navigator is a
window of its own: its first tab opens a new window (Target.createTarget newWindow), the next ones are opened from a
page of that window (window.open, noopener + noreferrer, from an isolated world so the page cannot change it), and land
in it. Every navigator's tab in front paints at once, at its own size; a tab put in front is made the active one of its
window (a tab left behind paints nothing). Pictures are only produced while someone
watches a navigator (and the picture given to Claude with a hand-back, the agent's card).

Smoothness: Chromium makes the next picture only once the last one is acknowledged. We acknowledge it at once while
every viewer has fewer than INFLIGHT pictures on their way (`delivered` counts them back), so a far viewer still gets
several pictures per round trip, and a slow one never gets a pile of late ones. The JPEG quality ("auto") follows the
time a picture spends queued on the way to the slowest viewer (its round trip minus the fastest one seen: the
distance alone lowers nothing), between Q_MIN and Q_MAX; pictures are never larger than the viewer's own size.
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
from .navs import ME
from .relay import Cdp

log = logging.getLogger("maxxing.browser")

QUALITY = {"auto": (60, 1920, 1200), "high": (70, 1920, 1200), "low": (40, 960, 960)}   # JPEG quality, largest picture
Q_MIN, Q_MAX, Q_STEP = 30, 70, 10
SLOW_S, FAST_S = 0.25, 0.08          # time a picture waits on the way (above the network's own delay): lower / raise
ADAPT_EVERY = 4.0                    # at most one quality change this often (each one restarts the screencast)
INFLIGHT = 3                         # pictures on their way to one viewer before the browser waits for it
ACK_LATE = 1.0                       # a viewer that does not confirm pictures holds the others at most this long
SIZE = (1280, 800)                  # the pages' size when nobody watches (Claude's)
MIN_SIZE, MAX_SIZE = (360, 320), (2560, 1600)
INTERNAL = ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://")   # Chromium's own UI pages


def _shown(t: dict) -> bool:
    return t.get("type") == "page" and not str(t.get("url") or "").startswith(INTERNAL)


MODS = {"alt": 1, "ctrl": 2, "meta": 4, "shift": 8}
COPY_JS = "(() => { const e = document.activeElement; if (e && (e.tagName === 'TEXTAREA' || (e.tagName === 'INPUT' && " \
          "typeof e.selectionStart === 'number'))) return e.value.slice(e.selectionStart, e.selectionEnd); " \
          "return String(getSelection ? getSelection() : ''); })()"


class Screen:
    """What one navigator shows: its tab in front, the people watching it and the pictures on their way."""

    def __init__(self, nav: str) -> None:
        self.nav = nav
        self.front: str | None = None               # targetId shown / driven
        self.viewers: dict[int, Callable[[Any], Any]] = {}   # id -> send(bytes)
        self.quality: dict[int, str] = {}
        self.casting: str | None = None             # targetId being screencast
        self.meta: dict = {}                        # last frame metadata (device size, offsets)
        self.frame: bytes | None = None
        self.frame_of: str | None = None            # the targetId of that picture
        self.frame_at = 0.0
        self.size: tuple[int, int] = SIZE           # its pages' size: the live view's while someone watches
        self.unacked: tuple[str, object] | None = None   # (DevTools session, frame id) of a picture not acknowledged
        self.inflight: dict[int, int] = {}          # viewer -> pictures sent, not confirmed yet
        self._late: asyncio.TimerHandle | None = None
        self.q = QUALITY["auto"][0]                 # the quality now ("auto" moves it)
        self.trip: dict[int, float] = {}            # viewer -> smoothed round trip of a picture
        self.fastest: dict[int, float] = {}         # viewer -> fastest round trip seen (the network's own delay)
        self.adapted = time.monotonic()
        self.frames = 0                             # pictures made (stats)
        self.frame_bytes = 0

    def want(self) -> tuple[int, int, int]:
        modes = set(self.quality.values())
        mode = "low" if "low" in modes else "auto" if "auto" in modes else "high"
        q, w, h = QUALITY[mode]
        if mode == "auto":
            q = self.q
        return q, min(w, self.size[0]), min(h, self.size[1])

    def room(self) -> bool:
        """Every viewer may take one more picture."""
        return all(self.inflight.get(v, 0) < INFLIGHT for v in self.viewers)


class Watcher:
    def __init__(self, sock, path: str, tabs=None) -> None:
        self.sock, self.path, self.registry = sock, path, tabs
        self.cdp: Cdp | None = None
        self.pages: dict[str, dict] = {}            # targetId -> {url, title, at}
        self.sessions: dict[str, str] = {}          # targetId -> DevTools session (flatten)
        self.screens: dict[str, Screen] = {}        # navigator -> what it shows
        self.viewer_nav: dict[int, str] = {}        # viewer -> the navigator it watches
        self.sleeping: set[str] = set()             # targetIds closed to sleep (their tab stays)
        self.tab_page: dict[str, str] = {}          # "tab" targetId -> the page it holds (Puppeteer attaches to tabs)
        self.tab_sessions: dict[str, str] = {}      # our session on a tab target -> its targetId
        self._tab_ev: dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()
        self.sized: dict[int, tuple[int, int]] = {}   # windowId -> the size it was given
        self.extra: tuple[int, int] = (0, 0)          # window size - page size (headless still counts a toolbar)
        self.dialogs: dict[str, dict] = {}            # targetId -> its alert / confirm / prompt {type, message, default}
        self.choosers: dict[str, dict] = {}           # targetId -> its file request {node, multiple}
        self._opened: dict[str, asyncio.Future] = {}  # targetId of a page asked to open a tab -> that tab's targetId

    on_state: Callable[[], Any] | None = None
    on_move: Callable[[str, str, str], None] | None = None     # (targetId, url, title) of a page that changed
    may_follow: Callable[[str], bool] | None = None            # a page opened / moved: show it to its navigator?

    # ---- navigators --------------------------------------------------------------------------------------------
    def nav_of(self, tid: str | None) -> str:
        n = self.registry.nav_of(tid) if self.registry is not None and tid else None
        return n or ME

    def screen(self, nav: str) -> Screen:
        sc = self.screens.get(nav)
        if sc is None:
            sc = self.screens[nav] = Screen(nav)
        return sc

    def front(self, nav: str) -> str | None:
        sc = self.screens.get(nav)
        return sc.front if sc else None

    def watched(self, nav: str | None = None) -> bool:
        if nav is not None:
            sc = self.screens.get(nav)
            return bool(sc and sc.viewers)
        return any(sc.viewers for sc in self.screens.values())

    def shown(self) -> set[str]:
        """The tabs in front of a navigator someone watches."""
        return {sc.front for sc in self.screens.values() if sc.viewers and sc.front}

    def _latest(self, nav: str) -> str | None:
        mine = [k for k in self.pages if self.nav_of(k) == nav]
        return max(mine, key=lambda k: self.pages[k]["at"]) if mine else None

    # ---- start / stop ------------------------------------------------------------------------------------------
    async def start(self) -> None:
        self.cdp = await Cdp.open(self.sock, self.path, self._event)
        await self.cdp.call("Target.setDiscoverTargets", {"discover": True})
        for t in (await self.cdp.call("Target.getTargets")).get("targetInfos") or []:
            if self.registry is not None and t.get("type") == "page":
                self.registry.resolve(t)
            if _shown(t):
                self.pages[t["targetId"]] = {"url": t.get("url") or "", "title": t.get("title") or "",
                                             "at": time.time()}
        for tid in self.pages:
            nav = self.nav_of(tid)
            if self.screen(nav).front is None:
                self.screen(nav).front = self._latest(nav)
        # which page each tab target holds: attach to tabs, and under each one to its page (never waiting for us)
        await self.cdp.call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False,
                                                     "flatten": True, "filter": [{"type": "tab"}]})

    async def page_of(self, tab: str, wait: float = 2.0) -> str | None:
        """The page a tab target holds (waits a little for a new tab)."""
        if tab in self.tab_page or wait <= 0:
            return self.tab_page.get(tab)
        ev = self._tab_ev.setdefault(tab, asyncio.Event())
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(ev.wait(), wait)
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
            waiting = self._opened.get(str(t.get("openerId") or "")) if method == "Target.targetCreated" else None
            if waiting is not None and not waiting.done():
                waiting.set_result(tid)
            old = self.pages.get(tid, {})
            moved = old.get("url") != t.get("url")
            self.pages[tid] = {"url": t.get("url") or "", "title": t.get("title") or "",
                               "at": time.time() if (moved or not old) else old.get("at", time.time())}
            if self.on_move and str(t.get("url") or "").startswith(("http://", "https://")):
                try:
                    self.on_move(tid, t.get("url") or "", t.get("title") or "")
                except Exception:  # noqa: BLE001
                    log.exception("browser page move")
            sc = self.screen(self.nav_of(tid))
            if sc.front is None or ((moved or method == "Target.targetCreated") and sc.front != tid
                                    and (self.may_follow is None or self.may_follow(tid))):
                await self._show(tid)
            else:
                await self._state()
        elif method == "Target.targetDestroyed":
            tid = p.get("targetId")
            self.dialogs.pop(tid, None)
            self.choosers.pop(tid, None)
            nav = self.nav_of(tid)
            if self.registry is not None:
                self.registry.gone(tid, keep=tid in self.sleeping)
            self.sleeping.discard(tid)
            self.pages.pop(tid, None)
            self.sessions.pop(tid, None)
            for sc in self.screens.values():
                if sc.front == tid:
                    if sc.casting == tid:
                        sc.casting = None
                    sc.front = None
                    nxt = self._latest(sc.nav) or self._latest(nav)
                    if nxt:
                        await self._show(nxt)
            await self._state()
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
                    for sc in self.screens.values():
                        if sc.casting == k:
                            sc.casting = None
        elif method == "Page.screencastFrame":
            await self._frame(m.get("sessionId"), p)
        elif method == "Page.javascriptDialogOpening":
            tid = self._tid_of(m.get("sessionId"))
            if tid:
                self.dialogs[tid] = {"type": str(p.get("type") or "alert"),
                                     "message": str(p.get("message") or "")[:2000],
                                     "default": str(p.get("defaultPrompt") or "")[:500]}
                await self._state()
        elif method == "Page.javascriptDialogClosed":
            tid = self._tid_of(m.get("sessionId"))
            if tid and self.dialogs.pop(tid, None) is not None:
                await self._state()
        elif method == "Page.fileChooserOpened":
            tid = self._tid_of(m.get("sessionId"))
            if tid and p.get("backendNodeId"):
                self.choosers[tid] = {"node": int(p["backendNodeId"]), "multiple": p.get("mode") == "selectMultiple"}
                await self._state()

    def _tid_of(self, session: object) -> str | None:
        return next((k for k, v in self.sessions.items() if v == session), None)

    async def _session(self, tid: str) -> str:
        if tid in self.sessions:
            return self.sessions[tid]
        assert self.cdp
        s = (await self.cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
        self.sessions[tid] = s
        await self.cdp.call("Page.enable", session=s)
        with contextlib.suppress(Exception):           # a file input clicked by the person: we hand it the files
            await self.cdp.call("Page.setInterceptFileChooserDialog", {"enabled": True}, session=s)
        return s

    async def cdp_navigate(self, tid: str, url: str) -> None:
        assert self.cdp
        await self.cdp.call("Page.navigate", {"url": url}, session=await self._session(tid), timeout=5)

    async def _show(self, tid: str) -> None:
        """Put a page in front of its navigator (one Claude just opened or moved to, or one the person picked)."""
        sc = self.screen(self.nav_of(tid))
        async with self._lock:
            sc.front = tid
            if self.cdp:
                # a tab left behind is hidden for Chromium: it paints nothing (no pictures) until it is the active one
                with contextlib.suppress(Exception):
                    await self.cdp.call("Target.activateTarget", {"targetId": tid}, timeout=5)
            if sc.viewers:
                await self._cast(sc)
        await self._state()

    # ---- screencast ------------------------------------------------------------------------------------------
    async def _cast(self, sc: Screen) -> None:
        if not self.cdp:
            return
        if sc.casting and (sc.casting != sc.front or not sc.viewers):
            s = self.sessions.get(sc.casting)
            if s:
                with contextlib.suppress(Exception):
                    await self.cdp.call("Page.stopScreencast", session=s, timeout=5)
            sc.casting = None
        if sc.viewers and sc.front and sc.casting != sc.front:
            q, w, h = sc.want()
            with contextlib.suppress(Exception):
                await self._fit(sc.front, sc.size)
            try:
                s = await self._session(sc.front)
                await self.cdp.call("Page.startScreencast", {"format": "jpeg", "quality": q, "maxWidth": w,
                                                             "maxHeight": h, "everyNthFrame": 1}, session=s)
                sc.casting = sc.front
            except Exception as e:  # noqa: BLE001
                log.info("screencast: %s", e)

    def _screen_casting(self, session: str | None) -> Screen | None:
        return next((sc for sc in self.screens.values()
                     if sc.casting and self.sessions.get(sc.casting) == session), None)

    async def _frame(self, session: str | None, p: dict) -> None:
        sc = self._screen_casting(session)
        if sc is None or not sc.viewers:
            if self.cdp and session:
                await self.cdp.send_nowait("Page.screencastFrameAck", {"sessionId": p.get("sessionId")}, session)
            return
        await self._ack(sc)                          # an older one still held (a viewer that left)
        sc.meta = p.get("metadata") or {}
        self._learn(sc, sc.meta)
        sc.frame = base64.b64decode(p.get("data") or "")
        sc.frame_of = sc.casting
        sc.frame_at = time.time()
        sc.frames += 1
        sc.frame_bytes += len(sc.frame)
        for vid, send in list(sc.viewers.items()):
            if sc.inflight.get(vid, 0) >= INFLIGHT:
                continue                             # it gets a newer one once it caught up
            sc.inflight[vid] = sc.inflight.get(vid, 0) + 1
            with contextlib.suppress(Exception):
                await send(sc.frame)
        sc.unacked = (str(session), p.get("sessionId"))
        if sc.room():
            await self._ack(sc)
        else:
            sc._late = asyncio.get_running_loop().call_later(ACK_LATE, lambda: asyncio.ensure_future(self._ack(sc)))

    async def _ack(self, sc: Screen) -> None:
        """Let Chromium make the next picture of this navigator."""
        if sc._late is not None:
            sc._late.cancel()
            sc._late = None
        ack, sc.unacked = sc.unacked, None
        if ack and self.cdp:
            with contextlib.suppress(Exception):
                await self.cdp.send_nowait("Page.screencastFrameAck", {"sessionId": ack[1]}, ack[0])

    def delivered(self, vid: int, size: int, secs: float) -> None:
        """A viewer got a picture (its page confirmed it, `secs` after it was sent; < 0: one replaced by a newer one
        before it left)."""
        sc = self.screens.get(self.viewer_nav.get(vid, ""))
        if sc is None:
            return
        sc.inflight[vid] = max(0, sc.inflight.get(vid, 0) - 1)
        if secs < 0:
            if sc.unacked and sc.room():
                asyncio.ensure_future(self._ack(sc))
            return
        old = sc.trip.get(vid)
        sc.trip[vid] = secs if old is None else old * 0.7 + secs * 0.3
        sc.fastest[vid] = min(sc.fastest.get(vid, secs), secs)
        if sc.unacked and sc.room():
            asyncio.ensure_future(self._ack(sc))
        self._adapt(sc)

    def _adapt(self, sc: Screen) -> None:
        """"auto": lower the quality while pictures queue on their way, raise it back when they flow."""
        if "auto" not in sc.quality.values() or not sc.trip or time.monotonic() - sc.adapted < ADAPT_EVERY:
            return
        queued = max(sc.trip[v] - sc.fastest.get(v, sc.trip[v]) for v in sc.trip)
        q = sc.q - Q_STEP if queued > SLOW_S else sc.q + Q_STEP // 2 if queued < FAST_S else sc.q
        q = max(Q_MIN, min(Q_MAX, q))
        if q != sc.q:
            sc.q = q
            sc.adapted = time.monotonic()
            asyncio.ensure_future(self._restart_cast(sc))

    async def watch(self, vid: int, nav: str, send: Callable[[Any], Any], quality: str = "auto") -> None:
        sc = self.screen(nav)
        self.viewer_nav[vid] = nav
        sc.viewers[vid] = send
        sc.quality[vid] = quality if quality in QUALITY else "auto"
        sc.inflight[vid] = 0
        if sc.front is None:
            sc.front = self._latest(nav)
        if sc.front and self.cdp:
            with contextlib.suppress(Exception):
                await self.cdp.call("Target.activateTarget", {"targetId": sc.front}, timeout=5)
        await self._restart_cast(sc)
        if sc.frame:
            sc.inflight[vid] = 1
            await send(sc.frame)
        await self._state()

    async def unwatch(self, vid: int) -> None:
        nav = self.viewer_nav.pop(vid, None)
        sc = self.screens.get(nav or "")
        if sc is None:
            return
        sc.viewers.pop(vid, None)
        for d in (sc.quality, sc.trip, sc.fastest, sc.inflight):
            d.pop(vid, None)
        if sc.unacked and sc.room():
            await self._ack(sc)
        if not sc.viewers and sc.size != SIZE:      # back to Claude's size
            sc.size = SIZE
            if sc.front:
                with contextlib.suppress(Exception):
                    await self._fit(sc.front, sc.size)
        await self._restart_cast(sc)

    async def resize(self, vid: int, w: object, h: object) -> None:
        """A viewer's size (CSS pixels): the page in front of its navigator is laid out for it, like a browser window
        (and its pictures are never larger)."""
        sc = self.screens.get(self.viewer_nav.get(vid, ""))
        if sc is None:
            return
        try:
            size = (max(MIN_SIZE[0], min(MAX_SIZE[0], int(w))), max(MIN_SIZE[1], min(MAX_SIZE[1], int(h))))
        except (TypeError, ValueError):
            return
        if size == sc.size:
            return
        sc.size = size
        if sc.front:
            await self._fit(sc.front, size)
        if sc.viewers:
            await self._restart_cast(sc)

    async def _fit(self, tid: str, size: tuple[int, int]) -> None:
        """Give the window of this page a size (headless: the window is the page)."""
        if not self.cdp:
            return
        win = (await self.cdp.call("Browser.getWindowForTarget", {"targetId": tid}, timeout=5)).get("windowId")
        if win is None or self.sized.get(win) == size:
            return
        await self.cdp.call("Browser.setWindowBounds", {"windowId": win, "bounds": {
            "width": size[0] + self.extra[0], "height": size[1] + self.extra[1]}}, timeout=5)
        self.sized[win] = size

    def _learn(self, sc: Screen, meta: dict) -> None:
        """The first picture after a fit says the page's real size: learn the window's extra height once, fit again.
        (Same width = a picture taken after the fit.)"""
        try:
            dw, dh = int(meta.get("deviceWidth") or 0), int(meta.get("deviceHeight") or 0)
        except (TypeError, ValueError):
            return
        if self.extra != (0, 0) or not self.sized or not sc.casting or dw != sc.size[0] or \
                not 0 < sc.size[1] - dh <= 400:
            return
        self.extra = (0, sc.size[1] - dh)
        self.sized.clear()
        asyncio.get_running_loop().create_task(self._refit(sc.casting, sc.size))

    async def _refit(self, tid: str, size: tuple[int, int]) -> None:
        with contextlib.suppress(Exception):
            await self._fit(tid, size)

    async def set_quality(self, vid: int, quality: str) -> None:
        """auto (default) | high | low (a phone on a slow network)."""
        sc = self.screens.get(self.viewer_nav.get(vid, ""))
        if sc is not None and vid in sc.viewers and quality in QUALITY:
            sc.quality[vid] = quality
            await self._restart_cast(sc)

    async def _restart_cast(self, sc: Screen) -> None:
        await self._ack(sc)
        async with self._lock:
            if sc.casting and self.cdp:
                s = self.sessions.get(sc.casting)
                if s:
                    with contextlib.suppress(Exception):
                        await self.cdp.call("Page.stopScreencast", session=s, timeout=5)
                sc.casting = None
            await self._cast(sc)

    # ---- state for the viewers -------------------------------------------------------------------------------
    def front_page(self, nav: str) -> dict | None:
        tid = self.front(nav)
        if not tid:
            return None
        p = self.pages.get(tid, {})
        return {"url": rules_page(p.get("url", "")), "title": (p.get("title") or "")[:120]}

    # ---- tabs ------------------------------------------------------------------------------------------------
    async def open_tab(self, url: str = "about:blank", nav: str | None = None) -> str:
        """A new page in the navigator's window (a new window for its first tab). The caller claimed it first
        (tabs.claim) and holds the profile's creation lock. Returns its targetId."""
        assert self.cdp
        url = url or "about:blank"
        src = self._window_page(nav) if nav else None
        if src:
            with contextlib.suppress(Exception):
                tid = await self._open_from(src, url)
                if tid:
                    return tid
        size = self.screen(nav).size if nav else SIZE
        r = await self.cdp.call("Target.createTarget", {"url": url, "newWindow": True,
                                                        "width": size[0], "height": size[1] + self.extra[1]})
        return str(r.get("targetId") or "")

    def _window_page(self, nav: str) -> str | None:
        """A page of the navigator's window to open its next tab from: the one in front, else its newest. Not one
        showing a dialog (it would not run), nor an error page (it may not open anything)."""
        def ok(k: str) -> bool:
            url = str(self.pages.get(k, {}).get("url") or "")
            return k not in self.dialogs and (url.startswith(("http://", "https://")) or url in ("", "about:blank"))
        front = self.front(nav)
        if front in self.pages and ok(front):
            return front
        mine = [k for k in self.pages if self.nav_of(k) == nav and ok(k)]
        return max(mine, key=lambda k: self.pages[k]["at"]) if mine else None

    async def _open_from(self, src: str, url: str) -> str | None:
        """window.open from a page (its window gets the tab): in an isolated world, so a page cannot replace
        window.open; noopener + noreferrer, so the new page knows nothing of it."""
        assert self.cdp
        s = await self._session(src)
        tree = await self.cdp.call("Page.getFrameTree", session=s, timeout=3)
        frame = ((tree.get("frameTree") or {}).get("frame") or {}).get("id")
        ctx = (await self.cdp.call("Page.createIsolatedWorld", {"frameId": frame, "worldName": "maxxing"},
                                   session=s, timeout=3)).get("executionContextId")
        fut = self._opened[src] = asyncio.get_running_loop().create_future()
        try:
            await self.cdp.call("Runtime.evaluate", {
                "expression": f"window.open({json.dumps(url)}, '_blank', 'noopener,noreferrer'), 1",
                "contextId": ctx, "userGesture": True, "returnByValue": True}, session=s, timeout=3)
            return await asyncio.wait_for(fut, 2)
        finally:
            self._opened.pop(src, None)

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
    async def input(self, nav: str, ev: dict) -> str | dict | None:
        """One input event from a viewer of `nav` in control. Coordinates are 0..1 of the picture. Returns an error
        text, or a message for that viewer ({"t": "copied", "text"})."""
        sc = self.screens.get(nav)
        t = ev.get("t")
        if t == "dialog":
            return await self._answer_dialog(nav, ev)
        if t == "chooser":                              # the person closed the file window without a file
            for tid in [k for k in self.choosers if self.nav_of(k) == nav]:
                self.choosers.pop(tid, None)
            await self._state()
            return None
        if not self.cdp or not sc or not sc.front:
            return "no page"
        s = await self._session(sc.front)
        dw = float(sc.meta.get("deviceWidth") or sc.size[0])
        dh = float(sc.meta.get("deviceHeight") or sc.size[1])
        mods = sum(v for k, v in MODS.items() if ev.get(k))

        def xy() -> tuple[float, float]:
            return (max(0.0, min(1.0, float(ev.get("x") or 0))) * dw,
                    max(0.0, min(1.0, float(ev.get("y") or 0))) * dh)
        if t == "mouse":
            kind = {"down": "mousePressed", "up": "mouseReleased", "move": "mouseMoved"}.get(ev.get("type"))
            if not kind:
                return "bad mouse event"
            x, y = xy()
            await self.cdp.send_nowait("Input.dispatchMouseEvent", {
                "type": kind, "x": x, "y": y, "modifiers": mods,
                "button": ev.get("button") if ev.get("button") in ("left", "middle", "right") else (
                    "none" if kind == "mouseMoved" else "left"),
                "clickCount": int(ev.get("clicks") or (0 if kind == "mouseMoved" else 1))}, session=s)
        elif t == "wheel":
            x, y = xy()
            await self.cdp.send_nowait("Input.dispatchMouseEvent", {
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
            await self.cdp.send_nowait("Input.dispatchKeyEvent", params, s)
        elif t == "text":
            text = str(ev.get("text") or "")[:2000]
            if text:
                await self.cdp.send_nowait("Input.insertText", {"text": text}, s)
        elif t == "nav":
            from .. import browser
            engine = browser.settings()["search"]
            url = rules.address(ev.get("url"), engine)
            if not url:
                return None
            why = rules.page_refusal(url)
            if why:
                return why
            await self.cdp.send_nowait("Page.navigate", {"url": url}, s)   # a "leave this page?" may hold it
        elif t == "copy":
            r = await self.cdp.call("Runtime.evaluate", {"expression": COPY_JS, "returnByValue": True}, session=s, timeout=5)
            text = str(((r.get("result") or {}).get("value")) or "")[:100_000]
            return {"t": "copied", "text": text}
        elif t in ("back", "forward"):
            h = await self.cdp.call("Page.getNavigationHistory", session=s)
            i = int(h.get("currentIndex", 0)) + (-1 if t == "back" else 1)
            entries = h.get("entries") or []
            if 0 <= i < len(entries):
                await self.cdp.send_nowait("Page.navigateToHistoryEntry", {"entryId": entries[i]["id"]}, s)
        elif t == "reload":
            await self.cdp.send_nowait("Page.reload", None, s)
        else:
            return "unknown event"
        return None

    def _asking_tid(self, table: dict[str, dict], nav: str) -> str | None:
        """The tab of `nav` with a dialog / a file request: the one in front first."""
        front = self.front(nav)
        if front in table:
            return front
        return next((k for k in table if self.nav_of(k) == nav), None)

    async def _answer_dialog(self, nav: str, ev: dict) -> None:
        tid = self._asking_tid(self.dialogs, nav)
        if not tid or not self.cdp:
            return None
        d = self.dialogs.pop(tid)
        ds = await self._session(tid)
        params: dict = {"accept": bool(ev.get("accept"))}
        if d["type"] == "prompt" and ev.get("accept"):
            params["promptText"] = str(ev.get("text") or "")[:2000]
        with contextlib.suppress(RuntimeError):     # already closed by the page or by Claude
            await self.cdp.call("Page.handleJavaScriptDialog", params, session=ds)
        await self._state()
        return None

    def chooser_of(self, nav: str) -> dict | None:
        tid = self._asking_tid(self.choosers, nav)
        return {"tid": tid, **self.choosers[tid]} if tid else None

    async def give_files(self, nav: str, paths: list[str]) -> None:
        """The files the person picked for the page of `nav` that asked (paths as Chromium sees them)."""
        c = self.chooser_of(nav)
        if not c or not self.cdp:
            raise RuntimeError("no page is asking for a file")
        s = await self._session(c["tid"])
        self.choosers.pop(c["tid"], None)
        await self.cdp.call("DOM.setFileInputFiles", {"files": paths[: (20 if c["multiple"] else 1)],
                                                      "backendNodeId": c["node"]}, session=s, timeout=15)
        await self._state()

    def asking(self, nav: str) -> dict:
        """What a page of this navigator waits for from the person: its dialog, its file window."""
        dt, ct = self._asking_tid(self.dialogs, nav), self._asking_tid(self.choosers, nav)
        return {"dialog": dict(self.dialogs[dt]) if dt else None,
                "chooser": {"multiple": self.choosers[ct]["multiple"]} if ct else None}

    def stats(self, nav: str) -> dict:
        sc = self.screens.get(nav)
        return {"frames": sc.frames, "bytes": sc.frame_bytes, "quality": sc.q} if sc else {}

    async def picture(self, quality: int = 50, width: int = 960, tid: str | None = None) -> bytes | None:
        """A small picture of a page."""
        if not self.cdp or not tid or tid not in self.pages:
            return None
        # A page someone watches: its last live picture. A clipped screenshot rescales the page for a moment, and
        # the live view would show it small ("zoomed out") every time a card refreshes its picture.
        for sc in self.screens.values():
            if sc.viewers and sc.casting == tid and sc.frame_of == tid and sc.frame:
                return sc.frame
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
