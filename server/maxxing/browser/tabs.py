"""The tabs of one profile of the Harness Browser, kept in <state>/browser/tabs/<profile>.json.

    {"tabs": [{key, url, title, by: {kind: you|session|agent, sid?, name?, path?}, at, used, asleep}]}

Every turn of the profile sees all its tabs; `by` says who opened one (the tools mark it "yours" for that turn).
`key` is ours and stays the same while a tab sleeps and wakes; `target` (Chromium's id) is only known while the tab is
awake (not saved). A page Chromium opens learns who opened it the first time anyone sees it (`resolve`): the opener
of the tab that opened it (a popup), else the oldest claim waiting (a turn or a person just asked for a new tab), else
the person.
"""
from __future__ import annotations

import secrets
import time

from .. import browser, config

INTERNAL = ("chrome://", "chrome-untrusted://", "devtools://", "chrome-extension://")   # Chromium's own UI pages
CLAIM_S = 8.0                      # a claim (a new tab asked for) waits this long for its page
MAX_ASLEEP = 40
URL_MAX = 2000


class Tabs:
    def __init__(self, pid: str = browser.MAIN) -> None:
        self.pid = pid
        self.items: dict[str, dict] = {}
        self.by_target: dict[str, str] = {}
        self.claims: list[dict] = []           # {by, key?, at}
        self.dirty = False

    # ---- loading / saving --------------------------------------------------------------------------------------
    def load(self) -> None:
        """At a browser start: the tabs of before, all asleep."""
        self.items, self.by_target, self.claims = {}, {}, []
        try:
            import json
            d = json.loads(self.file().read_text())
        except (OSError, ValueError):
            return
        for t in (d.get("tabs") or [])[-MAX_ASLEEP:] if isinstance(d, dict) else []:
            if isinstance(t, dict) and t.get("key") and str(t.get("url") or "").startswith(("http://", "https://")):
                self.items[str(t["key"])] = {**_clean(t), "asleep": True, "target": None}

    def file(self):
        return browser.tabs_dir() / f"{self.pid}.json"

    def save(self) -> None:
        if not self.dirty:
            return
        self.dirty = False
        keep = [{k: v for k, v in t.items() if k != "target"} for t in self.ordered()
                if str(t.get("url") or "").startswith(("http://", "https://"))]
        try:
            browser.tabs_dir().mkdir(parents=True, exist_ok=True)
            config.write_json(self.file(), {"tabs": keep[-MAX_ASLEEP:]})
        except OSError:
            pass

    # ---- what is known -----------------------------------------------------------------------------------------
    def ordered(self) -> list[dict]:
        return sorted(self.items.values(), key=lambda t: t["at"])

    def of_target(self, target: str | None) -> dict | None:
        k = self.by_target.get(target or "")
        return self.items.get(k) if k else None

    def awake(self) -> list[dict]:
        return [t for t in self.ordered() if t.get("target")]

    def asleep(self) -> list[dict]:
        return [t for t in self.ordered() if not t.get("target")]

    # ---- new pages ---------------------------------------------------------------------------------------------
    def claim(self, by: dict, key: str | None = None) -> None:
        """Someone is about to open a page (a turn's new tab, a person's, a tab woken up): it is theirs."""
        now = time.time()
        self.claims = [c for c in self.claims if now - c["at"] < CLAIM_S] + [{"by": by, "key": key, "at": now}]

    def resolve(self, info: dict) -> dict | None:
        """The tab of a page Chromium tells about (targetInfo); a page seen for the first time learns its opener here."""
        if info.get("type") != "page" or str(info.get("url") or "").startswith(INTERNAL):
            return None
        target = str(info.get("targetId") or "")
        if not target:
            return None
        known = self.of_target(target)
        if known:
            return known
        now = time.time()
        opener = self.of_target(info.get("openerId"))
        claim = None
        if opener is None:
            self.claims = [c for c in self.claims if now - c["at"] < CLAIM_S]
            claim = self.claims.pop(0) if self.claims else None
        if claim and claim.get("key") and claim["key"] in self.items:
            t = self.items[claim["key"]]
            t.update(target=target, asleep=False, used=now)
        else:
            by = opener["by"] if opener else claim["by"] if claim else {"kind": "you"}
            t = {"key": secrets.token_hex(5), "target": target, "url": str(info.get("url") or "")[:URL_MAX],
                 "title": str(info.get("title") or "")[:200], "by": by, "at": now, "used": now, "asleep": False}
            self.items[t["key"]] = t
        self.by_target[target] = t["key"]
        self.dirty = True
        return t

    def changed(self, info: dict) -> bool:
        """A page's address or title changed. True when its address did."""
        t = self.of_target(info.get("targetId"))
        if not t:
            return False
        url = str(info.get("url") or "")[:URL_MAX]
        moved = url != t["url"]
        t["url"], t["title"] = url, str(info.get("title") or "")[:200]
        if moved:
            t["used"] = time.time()
        self.dirty = True
        return moved

    def gone(self, target: str, keep: bool = False) -> None:
        """A page closed. keep: it was put to sleep (the tab stays, without a page)."""
        k = self.by_target.pop(target, None)
        if not k or k not in self.items:
            return
        t = self.items[k]
        if keep and str(t.get("url") or "").startswith(("http://", "https://")):
            t.update(target=None, asleep=True)
        else:
            self.items.pop(k, None)
        self.dirty = True

    def all_asleep(self) -> None:
        """The browser stopped: every tab with a real page sleeps."""
        for target in list(self.by_target):
            self.gone(target, keep=True)
        self.claims = []

    def used(self, target: str) -> None:
        t = self.of_target(target)
        if t:
            t["used"] = time.time()

    def drop(self, key: str) -> None:
        t = self.items.pop(key, None)
        if t and t.get("target"):
            self.by_target.pop(t["target"], None)
        self.dirty = True


def _clean(t: dict) -> dict:
    by = t.get("by") if isinstance(t.get("by"), dict) else {"kind": "you"}
    return {"key": str(t["key"])[:20], "url": str(t.get("url") or "")[:URL_MAX], "title": str(t.get("title") or "")[:200],
            "by": {k: str(v)[:200] for k, v in by.items() if k in ("kind", "sid", "name", "path")},
            "at": float(t.get("at") or time.time()), "used": float(t.get("used") or time.time())}


def mine(t: dict, sid: str, path: str) -> bool:
    """Did this turn open it (a session: this one; an agent: any of its runs)?"""
    by = t.get("by") or {}
    return by.get("sid") == sid or (by.get("kind") == "agent" and bool(path) and by.get("path") == path)


def public(t: dict, front: str | None = None) -> dict:
    from .live import rules_page
    return {"key": t["key"], "url": rules_page(t["url"]), "title": t["title"][:120], "by": t["by"],
            "asleep": not t.get("target"), "front": bool(front and t.get("target") == front), "used": t["used"]}
