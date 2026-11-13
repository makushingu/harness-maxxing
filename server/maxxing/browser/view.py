"""What a turn's browser tools (chrome-devtools-mcp, over the relay) see of the Harness Browser: only the tabs whose
scope covers the turn's folder.

Puppeteer attaches to "tab" targets (each wraps a page) and to pages under them; the live view (live.Watcher) learns
which page each tab target holds (`page_of`). The relay passes every message of that connection through a View:
- browser-level `Target.*` events: only visible pages / tabs (and the `browser` target); frames and workers are only
  seen when they attach under a session of a visible page;
- an auto-attach to a hidden tab / page is dropped; when it waits for its debuggers, the relay lets it run and
  detaches (`extra` commands: sent upstream, their answers swallowed);
- commands on a session or a targetId it does not see are refused; `Target.getTargets` answers are filtered;
- `Target.createTarget` claims the new page for the turn (tabs.claim), so it gets the turn's topic.
The same connection's commands on a tab the person has taken over wait (pool.wait_tab) before they go.
"""
from __future__ import annotations

import json
from typing import Awaitable, Callable

from . import rules

EXTRA_ID = 1_000_000_000            # ids of the relay's own commands on this connection
TARGET_ARG = ("Target.attachToTarget", "Target.activateTarget", "Target.closeTarget", "Target.getTargetInfo",
              "Target.detachFromTarget", "Target.exposeDevToolsProtocol", "Target.autoAttachRelated")
BROWSER_EVENTS_WITH_TARGET = ("Target.targetCreated", "Target.targetInfoChanged", "Target.targetDestroyed",
                              "Target.targetCrashed")
ASKED = ("Target.getTargets", "Target.attachToTarget", "Target.createTarget", "Target.attachToBrowserTarget")
NOT_YOURS = "This page is not one of yours."


class View:
    def __init__(self, sees: Callable[[dict], bool], on_create: Callable[[], None],
                 on_use: Callable[[str], None] | None = None,
                 page_of: Callable[[str, float], Awaitable[str | None]] | None = None,
                 page_now: Callable[[str], str | None] | None = None) -> None:
        """sees(targetInfo of a page): may this connection see it (resolves its scope). on_create(): the connection
        asks for a new tab. on_use(page targetId): it sent a command to that page. page_of(tab targetId, wait) /
        page_now(tab targetId): the page a tab target holds (waiting a little / known now)."""
        self.sees, self.on_create, self.on_use = sees, on_create, on_use
        self.page_of, self.page_now = page_of, page_now
        self.sessions: dict[str, str] = {}      # sessionId -> the page targetId it belongs to ("" = the browser)
        self.browser_sessions: set[str] = set() # sessions on the browser target: filtered like the connection itself
        self.shown: set[str] = set()            # tab / page targetIds this connection was told about
        self.asked: dict[int, dict] = {}        # command id -> the command (to read its answer)
        self._extra = EXTRA_ID
        self.extra: list[str] = []              # commands of the relay to send upstream (drained by the relay)

    # ---- visibility --------------------------------------------------------------------------------------------
    async def page_for(self, info: dict, wait: float = 2.0) -> str | None:
        """The page targetId behind a target it may see, else None."""
        kind, target = info.get("type"), str(info.get("targetId") or "")
        if kind == "page":
            return target if self.sees(info) else None
        if kind == "tab" and self.page_of is not None:
            page = await self.page_of(target, wait)
            return page if page and self.sees({"targetId": page, "type": "page"}) else None
        return None

    def page_known(self, target: str) -> str | None:
        """Sync: the page of a tab / page targetId it may see (from what is known now)."""
        if self.sees({"targetId": target, "type": "page"}):
            return target
        page = self.page_now(target) if self.page_now else None
        return page if page and self.sees({"targetId": page, "type": "page"}) else None

    # ---- the tools -> the browser ------------------------------------------------------------------------------
    def command(self, cmd: dict) -> str | None:
        """None = it may go; else why it is refused."""
        method = str(cmd.get("method") or "")
        params = cmd.get("params") if isinstance(cmd.get("params"), dict) else {}
        sid = cmd.get("sessionId")
        if sid:
            page = self.sessions.get(str(sid))
            if page is None:
                return NOT_YOURS
            if self.on_use and page:
                self.on_use(page)
        if method in TARGET_ARG and params.get("targetId"):
            t = str(params["targetId"])
            if t not in self.shown and not self.page_known(t):
                return NOT_YOURS
        if method == "Target.createTarget":
            self.on_create()
        if method in ASKED:
            self.asked[int(cmd.get("id") or 0)] = {"method": method, "params": params}
        return None

    # ---- the browser -> the tools ------------------------------------------------------------------------------
    async def message(self, m: dict) -> dict | None:
        """The message to pass on (maybe changed), or None to drop it."""
        if "id" in m:
            mid = m.get("id")
            if isinstance(mid, int) and mid >= EXTRA_ID:
                return None
            asked = self.asked.pop(mid, None) if isinstance(mid, int) else None
            if asked and "result" in m:
                return self._answer(asked, m)
            return m
        method = m.get("method")
        p = m.get("params") if isinstance(m.get("params"), dict) else {}
        sid = m.get("sessionId")
        if sid in self.browser_sessions:
            sid = None                               # events of a browser session: same filter as browser-level ones
        if method == "Target.attachedToTarget":
            return await self._attached(m, p, sid)
        if method == "Target.detachedFromTarget":
            child = str(p.get("sessionId") or "")
            if (sid and sid not in self.sessions) or child not in self.sessions:
                return None
            self.sessions.pop(child, None)
            return m
        if sid:
            return m if sid in self.sessions else None
        if method in BROWSER_EVENTS_WITH_TARGET:
            info = p.get("targetInfo") if isinstance(p.get("targetInfo"), dict) else {"targetId": p.get("targetId")}
            target = str(info.get("targetId") or p.get("targetId") or "")
            if method in ("Target.targetDestroyed", "Target.targetCrashed"):
                if target in self.shown:
                    self.shown.discard(target)
                    return m
                return None
            if info.get("type") == "browser":
                return m
            if info.get("type") in ("page", "tab") and await self.page_for(info, 1.0 if target in self.shown else 2.0):
                self.shown.add(target)
                return m
            if target in self.shown:                # no longer visible (its scope changed): gone for them
                self.shown.discard(target)
                return {"method": "Target.targetDestroyed", "params": {"targetId": target}}
            return None
        return m

    async def _attached(self, m: dict, p: dict, sid: str | None) -> dict | None:
        info = p.get("targetInfo") if isinstance(p.get("targetInfo"), dict) else {}
        child = str(p.get("sessionId") or "")
        target = str(info.get("targetId") or "")
        if sid:                                      # under one of its sessions: the page of a tab, a frame, a worker
            if sid in self.sessions:
                self.sessions[child] = target if info.get("type") == "page" and not self.sessions[sid] else \
                    self.sessions[sid]
                if info.get("type") == "page":
                    self.shown.add(target)
                return m
            self._let_go(child, p.get("waitingForDebugger"), sid)
            return None
        if info.get("type") == "browser":
            self.sessions[child] = ""
            self.browser_sessions.add(child)
            return m
        page = await self.page_for(info)
        if page:
            self.sessions[child] = page
            self.shown.add(target)
            return m
        self._let_go(child, p.get("waitingForDebugger"), None)
        return None

    def _let_go(self, child: str, waiting: object, parent: str | None) -> None:
        """A tab / page / worker this connection must not see was attached to it: let it run, detach."""
        if not child:
            return
        if waiting:
            self._send("Runtime.runIfWaitingForDebugger", {}, child)
        self._send("Target.detachFromTarget", {"sessionId": child}, parent)

    def _send(self, method: str, params: dict, session: str | None) -> None:
        self._extra += 1
        msg: dict = {"id": self._extra, "method": method, "params": params}
        if session:
            msg["sessionId"] = session
        self.extra.append(json.dumps(msg))

    def _answer(self, asked: dict, m: dict) -> dict:
        method, params = asked["method"], asked["params"]
        res = m.get("result") if isinstance(m.get("result"), dict) else {}
        if method == "Target.getTargets":
            infos = []
            for i in res.get("targetInfos") or []:
                if not isinstance(i, dict):
                    continue
                if i.get("type") == "browser" or (i.get("type") in ("page", "tab")
                                                  and self.page_known(str(i.get("targetId") or ""))):
                    infos.append(i)
                    if i.get("type") != "browser":
                        self.shown.add(str(i.get("targetId")))
            return {**m, "result": {**res, "targetInfos": infos}}
        if method == "Target.attachToTarget" and res.get("sessionId"):
            t = str(params.get("targetId") or "")
            self.sessions[str(res["sessionId"])] = self.page_known(t) or t
        if method == "Target.attachToBrowserTarget" and res.get("sessionId"):
            self.sessions[str(res["sessionId"])] = ""
            self.browser_sessions.add(str(res["sessionId"]))
        if method == "Target.createTarget" and res.get("targetId"):
            self.shown.add(str(res["targetId"]))
        return m


def refusal(raw: str | bytes, why: str) -> str:
    try:
        cmd = json.loads(raw)
    except ValueError:
        cmd = {}
    return rules.refusal(cmd if isinstance(cmd, dict) else {}, why)
