"""Which tab a turn's tools (chrome-devtools-mcp, over the relay) act on, for the person's hand and the "yours" marks.

A profile is its own Chromium: every turn of that profile sees all its tabs, nothing is hidden or filtered here.
This only follows the DevTools sessions of the connection (`sessions`: sessionId -> the page targetId it drives) so
that pool.wait_tab can hold a command on a tab the person has taken over, and so that a page the tools open is known
as the turn's (`on_create` -> tabs.claim).

Puppeteer attaches to "tab" targets (each wraps a page) and to pages under them; the live view (live.Watcher) knows
which page each tab target holds (`page_now`).
"""
from __future__ import annotations

from typing import Callable


class View:
    def __init__(self, on_create: Callable[[], None], on_use: Callable[[str], None] | None = None,
                 page_now: Callable[[str], str | None] | None = None) -> None:
        """on_create(): the connection asks for a new tab. on_use(page targetId): it sent a command to that page.
        page_now(tab targetId): the page a tab target holds."""
        self.on_create, self.on_use, self.page_now = on_create, on_use, page_now
        self.sessions: dict[str, str] = {}      # sessionId -> the tab / page targetId it belongs to ("" = the browser)
        self.asked: dict[int, dict] = {}        # command id -> the command (to read its answer)

    def page(self, session: str) -> str:
        """The page targetId a DevTools session drives ("" = none known, or the browser itself)."""
        target = self.sessions.get(session) or ""
        return ((self.page_now(target) if self.page_now else None) or target) if target else ""

    # ---- the tools -> the browser ------------------------------------------------------------------------------
    def command(self, cmd: dict) -> None:
        method = str(cmd.get("method") or "")
        sid = cmd.get("sessionId")
        if sid and self.on_use:
            page = self.page(str(sid))
            if page:
                self.on_use(page)
        if method == "Target.createTarget":
            self.on_create()
        if method in ("Target.attachToTarget", "Target.attachToBrowserTarget"):
            params = cmd.get("params") if isinstance(cmd.get("params"), dict) else {}
            self.asked[int(cmd.get("id") or 0)] = {"method": method, "params": params}

    # ---- the browser -> the tools ------------------------------------------------------------------------------
    def message(self, m: dict) -> None:
        if "id" in m:
            asked = self.asked.pop(m["id"], None) if isinstance(m.get("id"), int) else None
            res = m.get("result") if isinstance(m.get("result"), dict) else {}
            if asked and res.get("sessionId"):
                t = str(asked["params"].get("targetId") or "")
                self.sessions[str(res["sessionId"])] = t
            return
        p = m.get("params") if isinstance(m.get("params"), dict) else {}
        if m.get("method") == "Target.attachedToTarget":
            info = p.get("targetInfo") if isinstance(p.get("targetInfo"), dict) else {}
            child, parent = str(p.get("sessionId") or ""), m.get("sessionId")
            target = str(info.get("targetId") or "")
            if info.get("type") == "browser":
                self.sessions[child] = ""
            elif parent and self.sessions.get(str(parent)):
                self.sessions[child] = self.sessions[str(parent)]
            elif info.get("type") in ("page", "tab"):
                self.sessions[child] = target
        elif m.get("method") == "Target.detachedFromTarget":
            self.sessions.pop(str(p.get("sessionId") or ""), None)
