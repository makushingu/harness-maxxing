"""What a turn's tools (chrome-devtools-mcp, over the relay) see of their profile's Chromium: the tabs of their
navigator (navs.py), nothing of the others.

The tools speak DevTools to the whole browser (Puppeteer: target discovery + auto-attach). Between them and Chromium:
  - events about another navigator's tab or page are dropped (discovery, info changes, closings); when Chromium
    attaches the tools to one (auto-attach), the relay lets it run and detaches it at once, and every message of that
    session is dropped; frames and workers are seen only through a page of theirs; service and shared workers (one
    for every page of an origin, whatever its navigator) are never shown, like another navigator's tab;
  - the list of targets they ask for (Target.getTargets) keeps only theirs;
  - commands naming another navigator's tab are refused; a new tab (Target.createTarget) is made by the server in
    their navigator, in a window of its own (pool.create), and its id is answered.
A page's navigator comes from the tabs registry (a page Chromium opens learns it there: its opener, else the claim of
whoever asked for it). It also follows which page each DevTools session drives (`page`), for the person's hand.
"""
from __future__ import annotations

from typing import Awaitable, Callable

FRAMES = {"iframe", "worker", "webview", "auction_worklet", "shared_storage_worklet"}   # seen through their page only
WORKERS = {"service_worker", "shared_worker", "background_page"}   # shared by the pages of an origin: never shown
TAB_WAIT = 2.0                      # a new tab: wait this long to learn the page it holds (the watcher attaches to it)
OWN_IDS = 1_000_000_000            # ids of the commands the relay sends itself (their answers are dropped)
TARGET_COMMANDS = ("Target.attachToTarget", "Target.closeTarget", "Target.activateTarget", "Target.detachFromTarget",
                   "Target.exposeDevToolsProtocol", "Target.getTargetInfo")


class View:
    def __init__(self, nav: str, nav_of: Callable[[dict], str | None],
                 page_of: Callable[[str, float], Awaitable[str | None]] | None = None,
                 create: Callable[[dict], Awaitable[str]] | None = None,
                 on_use: Callable[[str], None] | None = None) -> None:
        """nav: the navigator of this connection. nav_of(targetInfo | {targetId}): the navigator of a page (None:
        unknown). page_of(tab targetId, wait): the page a tab target holds. create(params): a new tab of this
        navigator, its targetId. on_use(page targetId): the tools sent a command to that page."""
        self.nav, self.nav_of, self.page_of, self.create, self.on_use = nav, nav_of, page_of, create, on_use
        self.sessions: dict[str, str] = {}      # sessionId -> the tab / page targetId it belongs to ("" = the browser)
        self.asked: dict[int, dict] = {}        # command id -> the command (to read its answer)
        self.seen: set[str] = set()             # targets shown to the tools (theirs)
        self.hidden: set[str] = set()           # targets of other navigators
        self.hidden_sessions: set[str] = set()
        self._own = OWN_IDS

    # ---- whose is it -------------------------------------------------------------------------------------------
    def page(self, session: str) -> str:
        """The page targetId a DevTools session drives ("" = none known, or the browser itself)."""
        return self.sessions.get(session) or ""

    async def visible(self, info: dict) -> bool:
        tid = str(info.get("targetId") or "")
        kind = info.get("type")
        if tid in self.seen:
            return True
        if tid in self.hidden:
            return False
        if kind in WORKERS:
            ok = False
        elif kind == "page":
            ok = self.nav_of(info) == self.nav
        elif kind == "tab":
            page = await self.page_of(tid, TAB_WAIT) if self.page_of else None
            ok = bool(page) and self.nav_of({"targetId": page}) == self.nav
        else:
            return True
        (self.seen if ok else self.hidden).add(tid)
        return ok

    def allowed(self, tid: str) -> bool:
        """A command may name this target: one shown to the tools, or one that is not a tab / page at all."""
        return tid in self.seen or (tid not in self.hidden and self.nav_of({"targetId": tid}) in (None, self.nav))

    def _cmd(self, method: str, params: dict, session: str | None = None) -> dict:
        self._own += 1
        m: dict = {"id": self._own, "method": method, "params": params}
        if session:
            m["sessionId"] = session
        return m

    # ---- the browser -> the tools ------------------------------------------------------------------------------
    async def incoming(self, m: dict) -> tuple[dict | None, list[dict]]:
        """(the message for the tools or None, commands the relay sends the browser itself)."""
        sid = m.get("sessionId")
        if sid and sid in self.hidden_sessions:
            return None, []
        if "id" in m:
            mid = m.get("id")
            if isinstance(mid, int) and mid > OWN_IDS:
                return None, []
            asked = self.asked.pop(mid, None) if isinstance(mid, int) else None
            res = m.get("result") if isinstance(m.get("result"), dict) else {}
            if asked and asked["method"] == "Target.getTargets":
                infos = [i for i in res.get("targetInfos") or [] if isinstance(i, dict)]
                keep = [i for i in infos if i.get("type") not in FRAMES and await self.visible(i)]
                return {**m, "result": {**res, "targetInfos": keep}}, []
            if asked and res.get("sessionId"):
                self.sessions[str(res["sessionId"])] = str(asked["params"].get("targetId") or "")
            return m, []
        method = m.get("method")
        p = m.get("params") if isinstance(m.get("params"), dict) else {}
        if method in ("Target.targetCreated", "Target.targetInfoChanged"):
            info = p.get("targetInfo") if isinstance(p.get("targetInfo"), dict) else {}
            if info.get("type") in FRAMES or not await self.visible(info):
                return None, []
        elif method == "Target.targetDestroyed":
            tid = str(p.get("targetId") or "")
            if tid in self.hidden:
                self.hidden.discard(tid)
                return None, []
            self.seen.discard(tid)
        elif method == "Target.attachedToTarget":
            info = p.get("targetInfo") if isinstance(p.get("targetInfo"), dict) else {}
            child = str(p.get("sessionId") or "")
            target = str(info.get("targetId") or "")
            parent_page = self.sessions.get(str(sid)) if sid else None
            if (info.get("type") in ("page", "tab") or info.get("type") in WORKERS) and not await self.visible(info):
                self.hidden_sessions.add(child)
                return None, [self._cmd("Runtime.runIfWaitingForDebugger", {}, child),
                              self._cmd("Target.detachFromTarget", {"sessionId": child}, sid)]
            if info.get("type") == "browser":
                self.sessions[child] = ""
            elif info.get("type") in ("page", "tab"):
                self.sessions[child] = target
            elif parent_page:
                self.sessions[child] = parent_page          # a frame / worker of a page: that page
        elif method == "Target.detachedFromTarget":
            gone = str(p.get("sessionId") or "")
            if gone in self.hidden_sessions:
                self.hidden_sessions.discard(gone)
                return None, []
            self.sessions.pop(gone, None)
        return m, []

    # ---- the tools -> the browser ------------------------------------------------------------------------------
    def outgoing(self, cmd: dict) -> str | None:
        """Why this command is refused (None: it goes on)."""
        method = str(cmd.get("method") or "")
        sid = cmd.get("sessionId")
        if sid and sid in self.hidden_sessions:
            return "This tab belongs to another browser."
        params = cmd.get("params") if isinstance(cmd.get("params"), dict) else {}
        if method in TARGET_COMMANDS and params.get("targetId") and not self.allowed(str(params["targetId"])):
            return "This tab belongs to another browser: use the tabs of yours (list_pages) or open one (new_page)."
        if sid and self.on_use:
            page = self.page(str(sid))
            if page:
                self.on_use(page)
        if method in ("Target.attachToTarget", "Target.attachToBrowserTarget", "Target.getTargets"):
            self.asked[int(cmd.get("id") or 0)] = {"method": method, "params": params}
        return None

    async def new_tab(self, cmd: dict) -> dict:
        """Target.createTarget, made by the server in this navigator: the answer for the tools."""
        assert self.create is not None
        params = cmd.get("params") if isinstance(cmd.get("params"), dict) else {}
        try:
            tid = await self.create(params)
        except Exception as e:  # noqa: BLE001
            return {"id": cmd.get("id"), "error": {"code": -32000, "message": str(e)[:300] or "no new tab"}}
        self.seen.add(tid)
        self.hidden.discard(tid)
        return {"id": cmd.get("id"), "result": {"targetId": tid}}
