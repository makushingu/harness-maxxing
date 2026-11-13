"""The Harness Browser of this server: one Chromium, started when someone needs it, asleep when nobody does.

A turn reaches it with a token (`turns/<session>.json`, written by the runner, removed when the turn ends): its folder
comes from that file, never from the request. Each turn gets its own chrome-devtools-mcp (started on its first call,
stopped when the turn ends or after CHILD_IDLE), which sees only the tabs of its topic / project (view.py).

The person in the live view drives the tab shown; while they have a tab, Claude's commands on that tab wait (the other
tabs go on). Tabs unused for `tab_sleep_min` sleep (closed, kept in tabs.json, woken by a click); the browser stops
after `idle_min` with nobody watching, no turn and no request, and its tabs come back asleep at the next start.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import secrets
import shutil
import time
from pathlib import Path

from .. import browser, bus, config
from . import cdm, replays, rules, unit
from .live import Watcher
from .proxy import Proxy
from .tabs import Tabs, public as tab_public
from .turns import check_turn, clear_turns, end_turn, read_turn, turn_alive, write_turn  # noqa: F401 - used by the API
from .view import View

log = logging.getLogger("maxxing.browser")

WATCH_EVERY = 15.0
CHILD_IDLE = 300.0                     # a turn's tools stop after this long without a call
CONTROL_IDLE = 60.0                    # the person's hand on a tab lapses after this long without input
TAB_WAIT = 100.0                       # Claude's command on a tab the person has waits at most this long
CLAUDE_BUSY = 15.0                     # Claude acted on a tab this recently: it is "using" it
TRAIL_MAX = 30                         # pages a person went to in a shared tab (told to Claude after)
PICTURE_MAX = 400_000                  # bytes of the picture given back to Claude with a hand-back
MEM_WARN, MEM_CRITICAL = 0.85, 0.92    # share of the server's memory (or of the browser's cap)
POLICY_KEYS = ("web", "sites", "profile", "downloads")


class Turn:
    """A turn using the browser: its tools (chrome-devtools-mcp) and what it was told."""

    def __init__(self, sid: str, owner: str) -> None:
        self.sid, self.owner = sid, owner
        self.path = browser.owner_path(owner)
        self.secret = secrets.token_urlsafe(24)
        self.child: cdm.Child | None = None
        self.lock = asyncio.Lock()
        self.last_call = time.time()
        self.told_at = time.time()
        self.last_target: str | None = None
        kind = "agent" if owner.startswith("agent:") else "session"
        self.by = {"kind": kind, "sid": sid, "path": self.path}
        if kind == "agent":
            self.by["name"] = self.path.rstrip("/").rsplit("/", 1)[-1]

    async def stop(self) -> None:
        if self.child is not None:
            with contextlib.suppress(Exception):
                await self.child.stop()
            self.child = None


class Browser:
    def __init__(self, s: dict) -> None:
        self.slug = browser.SLUG
        self.settings = s
        self.proc: asyncio.subprocess.Process | None = None
        self.ws_path = ""
        self.proxy: Proxy | None = None
        self.watcher: Watcher | None = None
        self.started = time.time()
        self.last_use = time.time()
        self.state = "starting"
        self.turns: dict[str, Turn] = {}
        self.control: dict | None = None            # {tab: targetId, vid, name, at}: the person's hand
        self.released = asyncio.Event()
        self.released.set()
        self.claude_at: dict[str, float] = {}       # targetId -> last command of a turn on it
        self.trail: dict[str, list[dict]] = {}      # targetId -> pages the person went to (shared tabs)
        self.mem = 0
        self.last_input = 0.0

    @property
    def run(self) -> Path:
        return browser.run_dir() / self.slug

    @property
    def profile(self) -> Path:
        return browser.profiles_dir() / self.slug

    def sites(self) -> list[str] | None:
        return browser.allowed_sites()


class Pool:
    def __init__(self) -> None:
        self.b: Browser | None = None
        self.tabs = Tabs()
        self._loaded = False
        self._start_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.server_mem = (0, 0)

    # compatibility for callers that list browsers
    @property
    def browsers(self) -> dict[str, Browser]:
        return {browser.SLUG: self.b} if self.b else {}

    def running(self) -> list[Browser]:
        return [self.b] if self.b and self.b.state in ("starting", "running") else []

    # ---- lifecycle -------------------------------------------------------------------------------------------
    async def ensure(self) -> Browser:
        async with self._start_lock:
            b = self.b
            if b and b.state == "running" and (b.proc is None or b.proc.returncode is None) and b.watcher \
                    and b.watcher.cdp and not b.watcher.cdp.closed:
                return b
            if b:
                await self._stop_locked("restart")
            if not self._loaded:
                self.tabs.load()
                self._loaded = True
            b = self.b = Browser(browser.settings())
            try:
                await self._start(b)
            except BaseException:
                await self._stop_locked("failed")
                raise
        self._changed()
        return b

    async def _start(self, b: Browser) -> None:
        av = await asyncio.to_thread(unit.available)
        if not av["ok"]:
            raise browser.BrowserError(503, "unavailable", "The browser is not set up on this server (missing: "
                                       + ", ".join(av["missing"]) + "). Run `maxxing browser setup` as root.")
        s = b.settings
        downloads = (config.workspace() / "downloads" / "browser") if s["downloads"] else None
        await asyncio.to_thread(unit.prepare_dirs, b.profile, b.run, s["profile"] == "fresh", downloads)
        ids = unit.user_ids()
        b.proxy = Proxy(b.run / "proxy.sock", ids[1] if ids and not unit._direct() else None)
        await b.proxy.start()
        b.proc = await unit.start(b.slug, b.profile, b.run, rules.policy(browser.allowed_sites(s), s["downloads"]),
                                  downloads)
        b.ws_path = await unit.ready(b.run, b.proc, b.slug)
        b.watcher = Watcher(b.run / "cdp.sock", b.ws_path, b.sites, self.tabs)
        b.watcher.on_state = self._changed
        b.watcher.on_move = self._moved
        b.watcher.may_follow = self._may_follow
        await b.watcher.start()
        b.state = "running"
        b.last_use = time.time()
        self.server_mem = await asyncio.to_thread(unit.server_memory)

    async def stop(self, why: str = "") -> None:
        async with self._start_lock:
            await self._stop_locked(why)
        self._changed()

    async def _stop_locked(self, why: str) -> None:
        b, self.b = self.b, None
        if not b:
            return
        b.state = "stopped"
        b.released.set()
        for t in list(b.turns.values()):
            await t.stop()
        if b.watcher is not None:
            with contextlib.suppress(Exception):
                await b.watcher.stop()
        try:
            await unit.stop(b.slug, b.proc)
        except Exception:  # noqa: BLE001
            log.exception("stopping the browser")
        if b.proxy:
            await b.proxy.stop()
        self.tabs.all_asleep()
        if b.settings.get("profile") == "fresh":
            shutil.rmtree(b.profile, ignore_errors=True)
        await asyncio.to_thread(self.tabs.save)
        log.info("Harness Browser stopped (%s)", why or "asked")

    async def stop_all(self) -> None:
        await self.stop("server stops")

    def by_secret(self, secret: str) -> tuple[Browser, Turn] | None:
        b = self.b
        if not b or not secret:
            return None
        import hmac
        for t in b.turns.values():
            if hmac.compare_digest(t.secret.encode(), secret.encode()):
                return b, t
        return None

    def _changed(self) -> None:
        try:
            bus.invalidate("browser")
        except Exception:  # noqa: BLE001
            pass

    # ---- the watcher -----------------------------------------------------------------------------------------
    def watch(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(WATCH_EVERY)
            try:
                await self.tidy()
            except Exception:  # noqa: BLE001
                log.exception("browser watcher")

    async def tidy(self) -> None:
        from . import asks
        self.server_mem = await asyncio.to_thread(unit.server_memory)
        b = self.b
        if not b or b.state != "running":
            await asyncio.to_thread(self.tabs.save)
            return
        s = browser.settings()
        now = time.time()
        dead = (b.proc is not None and b.proc.returncode is not None) or \
            (b.proc is None and not await unit.unit_active(b.slug)) or not (b.watcher and b.watcher.cdp) \
            or b.watcher.cdp.closed
        if dead:
            await self.stop("the browser stopped")
            return
        if not browser.feature_on():
            await self.stop("turned off")
            return
        for sid, t in list(b.turns.items()):
            if not await asyncio.to_thread(turn_alive, sid) or (now - t.last_call > CHILD_IDLE and not t.lock.locked()):
                await t.stop()
                b.turns.pop(sid, None)
                self._changed()
        if b.control and now - b.control["at"] > CONTROL_IDLE:
            self._release()
        busy_turns = bool(b.turns) or asks.pending_for_any()
        viewers = bool(b.watcher and b.watcher.viewers)
        if any(b.settings.get(k) != s.get(k) for k in POLICY_KEYS) and not busy_turns and not b.control:
            await self.stop("its settings changed")       # the policy and the profile mode are set at start
            return
        if not busy_turns and not viewers and not b.control and now - b.last_use > s["idle_min"] * 60:
            await self.stop("unused")
            return
        b.mem = await asyncio.to_thread(unit.memory_current, b.slug, b.proc)
        await self._sleep_tabs(s, now)
        await asyncio.to_thread(self.tabs.save)

    def mem_level(self) -> str:
        used, total = self.server_mem
        share = used / total if total else 0.0
        b = self.b
        mine = (b.mem / unit.MEMORY_MAX_BYTES) if b and b.mem else 0.0
        top = max(share, mine)
        return "critical" if top >= MEM_CRITICAL else "warn" if top >= MEM_WARN else "ok"

    async def _sleep_tabs(self, s: dict, now: float, force: int = 0) -> int:
        """Tabs unused for tab_sleep_min, above max_tabs, or (memory critical / force) the oldest ones, go to sleep."""
        b = self.b
        if not b or not b.watcher:
            return 0
        keep = {b.watcher.front} if b.watcher.viewers else set()
        if b.control:
            keep.add(b.control["tab"])
        candidates = [t for t in self.tabs.awake() if t["target"] not in keep
                      and now - b.claude_at.get(t["target"], 0) > CLAUDE_BUSY]
        candidates.sort(key=lambda t: max(t["used"], b.claude_at.get(t["target"], 0)))
        going: list[dict] = []
        for t in candidates:
            last = max(t["used"], b.claude_at.get(t["target"], 0))
            blank = not str(t["url"]).startswith(("http://", "https://"))
            if now - last > s["tab_sleep_min"] * 60 or (blank and now - last > 120 and len(self.tabs.awake()) > 1):
                going.append(t)
        over = len(self.tabs.awake()) - len(going) - s["max_tabs"]
        rest = [t for t in candidates if t not in going]
        if over > 0:
            going += rest[:over]
        if force or self.mem_level() == "critical":
            rest = [t for t in candidates if t not in going]
            going += rest[:max(force, 1) if not force else force]
        for t in going:
            await b.watcher.close_tab(t["target"], sleep=True)
        if going:
            log.info("Harness Browser: %d tab(s) asleep", len(going))
            self._changed()
        return len(going)

    # ---- a tool call of a turn -------------------------------------------------------------------------------
    async def call(self, sid: str, name: str, args: dict) -> dict:
        turn = read_turn(sid)
        if not turn:
            return _error("This turn has no browser (it ended, or the browser is off for this folder).")
        owner = turn["owner"]
        if not browser.feature_on() or not browser.owner_settings(owner)["enabled"]:
            return _error("The browser is off for this folder (its settings, or Settings -> Features).")
        if name not in {t.get("name") for t in cdm.offered(cdm.shipped_tools())} and cdm.shipped_tools():
            return _error(f"Unknown browser tool {name}")
        args = cdm.clean_args(args)
        why = rules.page_refusal(args.get("url"), browser.allowed_sites()) if isinstance(args.get("url"), str) else None
        if why:
            await asyncio.to_thread(replays.log_action, browser.SLUG,
                                    {"at": time.time(), "session": sid, "tool": name,
                                     "args": replays.summary(name, args), "ok": False, "refused": why[:200]})
            return _error(why)
        t0 = time.time()
        try:
            b = await self.ensure()
            t = await self._turn(b, sid, owner)
        except browser.BrowserError:
            raise
        except (RuntimeError, OSError, asyncio.TimeoutError) as e:
            log.warning("the browser did not start for %s: %s", sid, e)
            return _error(f"The browser did not start: {e}")
        b.last_use = t.last_call = time.time()
        told = trail_text(self._untold(b, t))
        ok = False
        try:
            async with t.lock:
                try:
                    res = await t.child.call("tools/call", {"name": name, "arguments": args})  # type: ignore[union-attr]
                except RuntimeError:
                    if t.child and t.child.alive:
                        raise
                    await t.stop()
                    t = await self._turn(b, sid, owner)
                    res = await t.child.call("tools/call", {"name": name, "arguments": args})  # type: ignore[union-attr]
            ok = not res.get("isError")
            res = _explain(res)
            if ok and name == "new_page":
                await self._drop_blank(b, t)
            extra = []
            if told:
                extra.append("[Harness Maxxing] Since your last action, the person drove a tab of yours: " + told)
            content = list(res.get("content") or [])
            if name == "list_pages":
                content += self._asleep_note(t)
            if extra:
                content = [{"type": "text", "text": x} for x in extra] + content
            return {**res, "content": content}
        except (asyncio.TimeoutError, RuntimeError) as e:
            return _error(f"Browser: {e or 'timed out'}")
        finally:
            b.last_use = t.last_call = time.time()
            page = ""
            if t.last_target and b.watcher and t.last_target in b.watcher.pages:
                page = b.watcher.pages[t.last_target].get("url") or ""
            await asyncio.to_thread(replays.log_action, browser.SLUG,
                                    {"at": t0, "session": sid, "tool": name, "args": replays.summary(name, args),
                                     "ok": ok, "ms": int((time.time() - t0) * 1000), "page": replays.page(page)})
            self._changed()

    async def _turn(self, b: Browser, sid: str, owner: str) -> Turn:
        """The turn's tools, started if needed, on a browser where the turn has at least one tab."""
        t = b.turns.get(sid)
        if t is None or t.owner != owner:
            if t is not None:
                await t.stop()
            t = b.turns[sid] = Turn(sid, owner)
            self._changed()
        if t.child is not None and t.child.alive:
            return t
        await t.stop()
        if not any(x.get("target") for x in self.tabs.visible_to(t.path)) and b.watcher:
            self.tabs.claim(browser.scope_for(t.path), t.by)        # a first tab of its own
            tid = await b.watcher.open_tab("about:blank")
            t.last_target = tid or t.last_target
        from ..pcbridge import local_host, local_port
        t.child = await cdm.Child.start(f"ws://{local_host()}:{local_port()}/api/browser/cdp/{b.slug}", t.secret)
        if t.child.tools:
            await asyncio.to_thread(cdm.remember_tools, t.child.tools)
        return t

    async def _drop_blank(self, b: Browser, t: Turn) -> None:
        """The empty tab a turn got at its start, once it opened a page of its own."""
        for tab in self.tabs.awake():
            if tab["by"].get("sid") == t.sid and tab["url"] in ("", "about:blank") and tab["target"] != t.last_target \
                    and b.watcher:
                await b.watcher.close_tab(tab["target"])

    def view_for(self, b: Browser, t: Turn) -> View:
        def sees(info: dict) -> bool:
            # a full targetInfo (an event) may be a page seen for the first time; a bare id is only looked up
            tab = self.tabs.resolve(info) if info.get("type") == "page" and "url" in info else None
            if tab is None and info.get("targetId"):
                tab = self.tabs.of_target(str(info["targetId"]))
            return bool(tab and browser.visible(tab["scope"], t.path))

        def on_create() -> None:
            self.tabs.claim(browser.scope_for(t.path), t.by)

        def on_use(target: str) -> None:
            b.claude_at[target] = time.time()
            t.last_target = target
            self.tabs.used(target)
        async def page_of(tab: str, wait: float) -> str | None:
            return await b.watcher.page_of(tab, wait) if b.watcher else None

        def page_now(tab: str) -> str | None:
            return b.watcher.tab_page.get(tab) if b.watcher else None
        return View(sees, on_create, on_use, page_of, page_now)

    async def wait_tab(self, b: Browser, target: str) -> str | None:
        """Claude's command on a tab the person has: wait until they let it go (or give up)."""
        deadline = time.monotonic() + TAB_WAIT
        while b.control and b.control.get("tab") == target and b.state == "running":
            left = deadline - time.monotonic()
            if left <= 0:
                return "The person is using this tab right now: try again later, or call ask_human."
            b.released.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(b.released.wait(), min(left, 5))
        return None

    def _asleep_note(self, t: Turn) -> list[dict]:
        sleeping = [x for x in self.tabs.visible_to(t.path) if not x.get("target")]
        if not sleeping:
            return []
        lines = "; ".join(f"{x['title'] or x['url']} ({replays.page(x['url'])})" for x in sleeping[-10:])
        return [{"type": "text", "text": "[Harness Maxxing] Asleep tabs of your topic (open one again with new_page "
                                         "and its address if you need it): " + lines}]

    def _untold(self, b: Browser, t: Turn) -> list[dict]:
        out: list[dict] = []
        for target, entries in b.trail.items():
            tab = self.tabs.of_target(target)
            if tab and browser.visible(tab["scope"], t.path):
                out += [e for e in entries if e["at"] > t.told_at]
        t.told_at = time.time()
        return sorted(out, key=lambda e: e["at"])

    async def tools(self) -> list[dict]:
        return cdm.offered(cdm.shipped_tools())

    async def scope_changed(self, key: str) -> None:
        """A tab's scope changed: the turns that saw it, or now see it, get their tools again (a fresh list)."""
        b = self.b
        tab = self.tabs.items.get(key)
        if not b or not tab or not tab.get("target"):
            return
        for sid, t in list(b.turns.items()):
            if t.lock.locked():
                continue
            await t.stop()
        self._changed()

    # ---- people ----------------------------------------------------------------------------------------------
    def _may_follow(self, target: str) -> bool:
        """Show a page Claude opened / moved to the viewers only when the person is not busy in another tab."""
        b = self.b
        if not b:
            return False
        if b.control:
            return False
        tab = self.tabs.of_target(target)
        return bool(tab and tab["scope"] != browser.ME) and time.time() - b.last_input > 30

    def _moved(self, target: str, url: str, title: str) -> None:
        b = self.b
        if not b or not b.control or b.control.get("tab") != target:
            return
        tab = self.tabs.of_target(target)
        if not tab or tab["scope"] == browser.ME:
            return                                     # a tab of the person only: never told to Claude
        url = replays.page(url)
        if title and title in url:
            title = ""
        lst = b.trail.setdefault(target, [])
        if lst and lst[-1]["url"] == url:
            lst[-1]["title"] = (title or lst[-1]["title"])[:120]
            return
        lst.append({"url": url, "title": (title or "")[:120], "at": time.time()})
        b.trail[target] = lst[-TRAIL_MAX:]

    def input(self, vid: int, name: str = "web") -> None:
        """The person used the tab shown: it is theirs until they let it go (or CONTROL_IDLE)."""
        b = self.b
        if not b or not b.watcher or not b.watcher.front:
            return
        now = time.time()
        b.last_input = b.last_use = now
        front = b.watcher.front
        if not b.control or b.control["tab"] != front or b.control["vid"] != vid:
            b.control = {"tab": front, "vid": vid, "name": name, "at": now}
            b.released.clear()
            self.tabs.used(front)
            self._changed()
        else:
            b.control["at"] = now

    def _release(self) -> None:
        b = self.b
        if b and b.control:
            b.control = None
            b.released.set()
            self._changed()

    async def release(self, vid: int | None = None) -> None:
        b = self.b
        if not b or not b.control or (vid is not None and b.control["vid"] != vid):
            return
        self._release()

    def busy(self, target: str | None) -> bool:
        """Is Claude using this tab (a command a moment ago)?"""
        b = self.b
        return bool(b and target and time.time() - b.claude_at.get(target, 0) < CLAUDE_BUSY)

    async def hand_back(self, sid: str | None) -> dict:
        """What Claude gets with a hand-back: the pages the person went to, the page now and a picture of it."""
        b = self.b
        if not b or b.state != "running" or not b.watcher:
            return {}
        t = b.turns.get(sid or "")
        target = (t.last_target if t else None) or b.watcher.front
        entries = b.trail.get(target or "", [])
        since = t.told_at if t else 0
        out: dict = {"trail": [e for e in entries if e["at"] > since][-15:]}
        if t:
            t.told_at = time.time()
        page = b.watcher.pages.get(target or "", {})
        out["page"] = {"url": replays.page(page.get("url", "")), "title": (page.get("title") or "")[:120]}
        try:
            jpeg = await b.watcher.picture(quality=55, width=1024, tid=target)
        except Exception:  # noqa: BLE001
            jpeg = None
        if jpeg and len(jpeg) <= PICTURE_MAX:
            out["picture"] = base64.b64encode(jpeg).decode()
        return out

    async def focus_session(self, sid: str) -> None:
        """Show the tab a session used last (the window opened for that session or its request)."""
        b = self.b
        t = b.turns.get(sid) if b else None
        if b and b.watcher and t and t.last_target in b.watcher.pages:
            await b.watcher.show(t.last_target)

    # ---- tabs of the person ----------------------------------------------------------------------------------
    async def open_for_person(self, scope: str | None = None) -> Browser:
        """Start the browser for the person (the live view): its last tab, else the first site of the list."""
        if not browser.feature_on():
            raise browser.BrowserError(409, "off", "The browser is off (Settings -> Features)")
        b = await self.ensure()
        if b.watcher and not any(str(t["url"]).startswith(("http://", "https://")) for t in self.tabs.awake()):
            sleeping = self.tabs.asleep()
            if sleeping:
                await self.wake(sleeping[-1]["key"])
            else:
                first = (browser.allowed_sites() or [None])[0]
                front = b.watcher.front
                if first and front and b.watcher.pages.get(front, {}).get("url") in ("", "about:blank"):
                    with contextlib.suppress(Exception):
                        await b.watcher.input({"t": "nav", "url": f"https://{first}/"})
        b.last_use = time.time()
        return b

    async def new_tab(self, url: str = "", scope: str = browser.ME) -> None:
        b = await self.ensure()
        if url:
            why = rules.page_refusal(url if "://" in url else "https://" + url, browser.allowed_sites())
            if why:
                raise browser.BrowserError(400, "refused", why)
            url = url if "://" in url else "https://" + url
        self.tabs.claim(scope, {"kind": "you"})
        tid = await b.watcher.open_tab(url or "about:blank")  # type: ignore[union-attr]
        if tid and b.watcher:
            await b.watcher.show(tid)
        await self._sleep_tabs(browser.settings(), time.time())

    async def wake(self, key: str) -> None:
        """Show a tab: awake, it is shown; asleep, its page opens again."""
        t = self.tabs.items.get(key)
        if not t:
            raise browser.BrowserError(404, "no_tab", "No such tab")
        b = await self.ensure()
        if t.get("target") and b.watcher:
            await b.watcher.show(t["target"])
            if b.control and b.control["tab"] != t["target"]:
                self._release()                        # the hand goes with the tab shown
            return
        self.tabs.claim(t["scope"], t["by"], key=key)
        tid = await b.watcher.open_tab(t["url"])  # type: ignore[union-attr]
        if tid and b.watcher:
            await b.watcher.show(tid)
        self._release()
        await self._sleep_tabs(browser.settings(), time.time())

    async def close_tab(self, key: str) -> None:
        t = self.tabs.items.get(key)
        if not t:
            return
        b = self.b
        if t.get("target") and b and b.watcher:
            await b.watcher.close_tab(t["target"])
        self.tabs.drop(key)
        self._changed()

    async def set_scope(self, key: str, scope: str) -> dict:
        t = self.tabs.set_scope(key, scope)
        if not t:
            raise browser.BrowserError(404, "no_tab", "No such tab")
        await self.scope_changed(key)
        await asyncio.to_thread(self.tabs.save)
        return t

    async def sleep_now(self) -> int:
        """The person asks: every tab not shown goes to sleep."""
        b = self.b
        if not b:
            return 0
        return await self._sleep_tabs(browser.settings(), time.time(), force=len(self.tabs.awake()))

    # ---- what the UI shows -----------------------------------------------------------------------------------
    def public(self) -> dict:
        b = self.b
        s = browser.settings()
        front = b.watcher.front if b and b.watcher else None
        used, total = self.server_mem
        out = {"state": b.state if b else "stopped", "name": browser.NAME,
               "started": b.started if b else None, "last_use": b.last_use if b else None,
               "stops_at": (b.last_use + s["idle_min"] * 60) if b else None,
               "tabs": [tab_public(t, front) for t in self.tabs.ordered()],
               "front": next((t["key"] for t in self.tabs.awake() if t["target"] == front), None),
               "page": b.watcher.front_page() if b and b.watcher else None,
               "control": bool(b and b.control), "control_by": (b.control or {}).get("name") if b else None,
               "busy": self.busy(front),
               "turns": [{"session": t.sid, "path": t.path, "kind": t.by["kind"]} for t in (b.turns.values() if b else [])],
               "session": next(iter(b.turns), None) if b else None,
               "mem": {"browser": b.mem if b else 0, "cap": unit.MEMORY_MAX_BYTES, "server_used": used,
                       "server_total": total, "level": self.mem_level()},
               "bytes": (b.proxy.bytes_in + b.proxy.bytes_out) if b and b.proxy else 0,
               "blocked": [h for _, h in list(b.proxy.blocked)[-5:]] if b and b.proxy else []}
        return out

    def tabs_of(self, path: str) -> list[dict]:
        b = self.b
        front = b.watcher.front if b and b.watcher else None
        return [tab_public(t, front) for t in self.tabs.visible_to(path)]


_pool: Pool | None = None


def pool() -> Pool:
    global _pool
    if _pool is None:
        _pool = Pool()
    return _pool


BLOCKED_HINT = ("[Harness Maxxing] ERR_BLOCKED_BY_ADMINISTRATOR = this page, or the page it redirected to (a sign-in "
                "on another domain, for example), is not one of the sites this browser may open. Tell the user which "
                "site to add to its browser settings; do not try to get around it.")


def _explain(res: dict) -> dict:
    """A page refused by the browser's own rules (the site list) comes back as a cryptic Chromium error: say why."""
    texts = [c.get("text") or "" for c in res.get("content") or [] if isinstance(c, dict)]
    if any("ERR_BLOCKED_BY_ADMINISTRATOR" in x or "This page is blocked" in x for x in texts):
        return {**res, "content": list(res.get("content") or []) + [{"type": "text", "text": BLOCKED_HINT}]}
    return res


def trail_text(trail: list[dict]) -> str:
    """"A (title) -> B (title)" of the pages a person went to; "" for none."""
    return " -> ".join(f"{x['url']}" + (f" ({x['title']})" if x.get("title") else "") for x in trail)


def _error(text: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": text}]}
