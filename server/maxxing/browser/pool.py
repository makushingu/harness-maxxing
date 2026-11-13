"""The running profiles of the Harness Browser: one Chromium per profile, started when someone needs it, asleep when
nobody does (`max_active_profiles` at once: the oldest unused one sleeps to make room).

A turn reaches its profile with a token (`turns/<session>.json`, written by the runner, removed when the turn ends):
its folder and profile come from that file, never from the request. Each turn gets its own chrome-devtools-mcp
(started on its first call, stopped when the turn ends or after CHILD_IDLE). It sees every tab of its profile; the
ones it opened are marked as its own.

The person in the live view drives the tab shown; while they have a tab, Claude's commands on that tab wait (the other
tabs go on). Tabs unused for `tab_sleep_min` sleep (closed, kept in tabs/<profile>.json, woken by a click); a profile
stops after `idle_min` with nobody watching, no turn and no request, and its tabs come back asleep at the next start.

A profile whose exit is down (exits.py): a tool call waits `exit_wait_s` for it, then answers that the exit is offline
(the session gets a card, the user a notification); it never goes out by this server's address unless the profile
says so (`on_exit_down: vps`).
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import secrets
import time
from pathlib import Path

from .. import browser, bus, config
from . import cdm, exits, replays, rules, unit
from .live import Watcher
from .proxy import Proxy
from .tabs import Tabs, mine, public as tab_public
from .turns import check_turn, clear_turns, end_turn, read_turn, turn_alive, write_turn  # noqa: F401 - used by the API
from .view import View

log = logging.getLogger("maxxing.browser")

WATCH_EVERY = 15.0
CHILD_IDLE = 300.0                     # a turn's tools stop after this long without a call
CONTROL_IDLE = 60.0                    # the person's hand on a tab lapses after this long without input
TAB_WAIT = 100.0                       # Claude's command on a tab the person has waits at most this long
CLAUDE_BUSY = 15.0                     # Claude acted on a tab this recently: it is "using" it
EXIT_POLL = 10.0                       # a tool waiting for its exit checks it this often
TRAIL_MAX = 30                         # pages a person went to in a tab of a turn (told to Claude after)
PICTURE_MAX = 400_000                  # bytes of the picture given back to Claude with a hand-back
MEM_WARN, MEM_CRITICAL = 0.85, 0.92    # share of the server's memory (or of a browser's cap)
POLICY_KEYS = ("web", "sites")         # set at a profile's start: a change restarts it (when unused)


class Turn:
    """A turn using a profile: its tools (chrome-devtools-mcp) and what it was told."""

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
    """One running profile."""

    def __init__(self, profile: dict, tabs: Tabs) -> None:
        self.pid = profile["id"]
        self.profile = profile                      # its settings at start (POLICY_KEYS: a change restarts it)
        self.tabs = tabs
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
        self.trail: dict[str, list[dict]] = {}      # targetId -> pages the person went to
        self.mem = 0
        self.last_input = 0.0
        self.level = ""                             # CPU priority given to its unit (unit.set_level)

    @property
    def slug(self) -> str:
        return self.pid

    @property
    def run(self) -> Path:
        return browser.run_dir() / self.pid

    @property
    def data(self) -> Path:
        return browser.profile_dir(self.pid)

    def sites(self) -> list[str] | None:
        p = browser.profile(self.pid)
        return browser.sites_of(p or self.profile)

    def busy(self) -> bool:
        """Someone uses it now: a turn, a viewer, the person's hand."""
        return bool(self.turns or (self.watcher and self.watcher.viewers) or self.control)


class Pool:
    def __init__(self) -> None:
        self.browsers: dict[str, Browser] = {}
        self._tabs: dict[str, Tabs] = {}
        self._start_lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self.server_mem = (0, 0)

    def tabs(self, pid: str) -> Tabs:
        t = self._tabs.get(pid)
        if t is None:
            t = self._tabs[pid] = Tabs(pid)
            t.load()
        return t

    def running(self) -> list[Browser]:
        return [b for b in self.browsers.values() if b.state in ("starting", "running")]

    def get(self, pid: str) -> Browser | None:
        b = self.browsers.get(pid)
        return b if b and b.state == "running" else None

    # ---- lifecycle -------------------------------------------------------------------------------------------
    async def ensure(self, pid: str) -> Browser:
        p = browser.profile(pid)
        if p is None:
            raise browser.BrowserError(404, "no_profile", "No such browser profile")
        async with self._start_lock:
            b = self.browsers.get(pid)
            if b and b.state == "running" and (b.proc is None or b.proc.returncode is None) and b.watcher \
                    and b.watcher.cdp and not b.watcher.cdp.closed:
                return b
            if b:
                await self._stop_locked(pid, "restart")
            await self._make_room(pid)
            b = self.browsers[pid] = Browser(p, self.tabs(pid))
            try:
                await self._start(b)
            except BaseException:
                await self._stop_locked(pid, "failed")
                raise
        self._changed()
        return b

    async def _make_room(self, pid: str) -> None:
        """At most `max_active_profiles` running: the one unused for the longest sleeps; none free -> refused."""
        from . import asks
        limit = browser.settings()["max_active_profiles"]
        others = [b for b in self.running() if b.pid != pid]
        if len(others) < limit:
            return
        free = sorted((b for b in others if not b.busy() and not asks.pending_for_profile(b.pid)),
                      key=lambda b: b.last_use)
        if not free:
            raise browser.BrowserError(409, "too_many_profiles",
                                       f"{limit} browser profiles are in use right now (Settings -> Browser): "
                                       "try again when one is free")
        await self._stop_locked(free[0].pid, "to make room for another profile")

    async def _start(self, b: Browser) -> None:
        av = await asyncio.to_thread(unit.available)
        if not av["ok"]:
            raise browser.BrowserError(503, "unavailable", "The browser is not set up on this server (missing: "
                                       + ", ".join(av["missing"]) + "). Run `maxxing browser setup` as root.")
        s = browser.settings()
        downloads = (config.workspace() / "downloads" / "browser") if s["downloads"] else None
        await asyncio.to_thread(browser.migrate)
        await asyncio.to_thread(unit.prepare_dirs, b.data, b.run, downloads)
        ids = unit.user_ids()
        b.proxy = Proxy(b.run / "proxy.sock", ids[1] if ids and not unit._direct() else None,
                        upstream=lambda: self._upstream(b.pid))
        await b.proxy.start()
        b.proc = await unit.start(b.slug, b.data, b.run, rules.policy(b.sites(), s["downloads"]), downloads)
        b.ws_path = await unit.ready(b.run, b.proc, b.slug)
        b.watcher = Watcher(b.run / "cdp.sock", b.ws_path, b.sites, b.tabs)
        b.watcher.on_state = self._changed
        b.watcher.on_move = lambda tid, url, title: self._moved(b, tid, url, title)
        b.watcher.may_follow = lambda tid: self._may_follow(b, tid)
        await b.watcher.start()
        b.state = "running"
        b.last_use = time.time()
        self.server_mem = await asyncio.to_thread(unit.server_memory)
        await self._level(b)

    def _upstream(self, pid: str) -> tuple[str | None, exits.Upstream | None]:
        """For the proxy (in a thread): where this profile's connections go now."""
        p = browser.profile(pid)
        if not p or p["exit"] == browser.DIRECT:
            return None, None
        e = exits.get(p["exit"])
        if e is None:
            return None, None                       # its exit was deleted: the profile is back to direct
        try:
            return e["id"], exits.runtime().upstream(e)
        except exits.ExitDown:
            if p["on_exit_down"] == "vps":
                return None, None
            raise

    async def stop(self, pid: str, why: str = "") -> None:
        async with self._start_lock:
            await self._stop_locked(pid, why)
        self._changed()

    async def _stop_locked(self, pid: str, why: str) -> None:
        b = self.browsers.pop(pid, None)
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
        b.tabs.all_asleep()
        await asyncio.to_thread(b.tabs.save)
        log.info("Harness Browser profile %s stopped (%s)", pid, why or "asked")

    async def stop_all(self) -> None:
        for pid in list(self.browsers):
            await self.stop(pid, "server stops")

    def by_secret(self, pid: str, secret: str) -> tuple[Browser, Turn] | None:
        b = self.browsers.get(pid)
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

    async def _level(self, b: Browser) -> None:
        """CPU priority of its unit: first while someone watches it or Claude acts in it, last while nobody does."""
        if b.state != "running":
            return
        watched = bool(b.watcher and b.watcher.viewers) or b.control is not None
        acting = any(t.lock.locked() or time.time() - t.last_call < CLAUDE_BUSY for t in b.turns.values())
        level = "live" if watched or acting else "background"
        if level != b.level:
            b.level = level
            await asyncio.to_thread(unit.set_level, b.slug, level, b.proc)

    # ---- the watcher -----------------------------------------------------------------------------------------
    def watch(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop())
        exits.runtime().watch()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(WATCH_EVERY)
            try:
                await self.tidy()
            except Exception:  # noqa: BLE001
                log.exception("browser watcher")

    async def tidy(self) -> None:
        self.server_mem = await asyncio.to_thread(unit.server_memory)
        for pid in list(self.browsers):
            b = self.browsers.get(pid)
            if b:
                await self._tidy(b)
        for t in self._tabs.values():
            await asyncio.to_thread(t.save)

    async def _tidy(self, b: Browser) -> None:
        from . import asks
        if b.state != "running":
            return
        s = browser.settings()
        p = browser.profile(b.pid, s)
        now = time.time()
        dead = (b.proc is not None and b.proc.returncode is not None) or \
            (b.proc is None and not await unit.unit_active(b.slug)) or not (b.watcher and b.watcher.cdp) \
            or b.watcher.cdp.closed
        if dead:
            return await self.stop(b.pid, "the browser stopped")
        if not browser.feature_on() or p is None:
            return await self.stop(b.pid, "turned off" if p else "its profile was deleted")
        for sid, t in list(b.turns.items()):
            if not await asyncio.to_thread(turn_alive, sid) or (now - t.last_call > CHILD_IDLE and not t.lock.locked()):
                await t.stop()
                b.turns.pop(sid, None)
                self._changed()
        if b.control and now - b.control["at"] > CONTROL_IDLE:
            self._release(b)
        busy_turns = bool(b.turns) or asks.pending_for_profile(b.pid)
        viewers = bool(b.watcher and b.watcher.viewers)
        if any(b.profile.get(k) != p.get(k) for k in POLICY_KEYS) and not busy_turns and not b.control:
            return await self.stop(b.pid, "its sites changed")      # the policy is set at start
        if not busy_turns and not viewers and not b.control and now - b.last_use > s["idle_min"] * 60:
            return await self.stop(b.pid, "unused")
        b.mem = await asyncio.to_thread(unit.memory_current, b.slug, b.proc)
        await self._level(b)
        await self._sleep_tabs(b, s, now)

    def mem_level(self, b: Browser | None = None) -> str:
        used, total = self.server_mem
        share = used / total if total else 0.0
        mine_ = max(((x.mem / unit.MEMORY_MAX_BYTES) for x in ([b] if b else self.running()) if x.mem), default=0.0)
        top = max(share, mine_)
        return "critical" if top >= MEM_CRITICAL else "warn" if top >= MEM_WARN else "ok"

    async def _sleep_tabs(self, b: Browser, s: dict, now: float, force: int = 0) -> int:
        """Tabs unused for tab_sleep_min, above max_tabs, or (memory critical / force) the oldest ones, go to sleep."""
        if not b.watcher:
            return 0
        keep = {b.watcher.front} if b.watcher.viewers else set()
        if b.control:
            keep.add(b.control["tab"])
        tabs = b.tabs
        candidates = [t for t in tabs.awake() if t["target"] not in keep
                      and now - b.claude_at.get(t["target"], 0) > CLAUDE_BUSY]
        candidates.sort(key=lambda t: max(t["used"], b.claude_at.get(t["target"], 0)))
        going: list[dict] = []
        for t in candidates:
            last = max(t["used"], b.claude_at.get(t["target"], 0))
            blank = not str(t["url"]).startswith(("http://", "https://"))
            if now - last > s["tab_sleep_min"] * 60 or (blank and now - last > 120 and len(tabs.awake()) > 1):
                going.append(t)
        over = len(tabs.awake()) - len(going) - s["max_tabs"]
        rest = [t for t in candidates if t not in going]
        if over > 0:
            going += rest[:over]
        if force or self.mem_level(b) == "critical":
            rest = [t for t in candidates if t not in going]
            going += rest[:force or 1]
        for t in going:
            await b.watcher.close_tab(t["target"], sleep=True)
        if going:
            log.info("Harness Browser %s: %d tab(s) asleep", b.pid, len(going))
            self._changed()
        return len(going)

    # ---- a tool call of a turn -------------------------------------------------------------------------------
    async def call(self, sid: str, name: str, args: dict) -> dict:
        turn = read_turn(sid)
        if not turn:
            return _error("This turn has no browser (it ended, or the browser is off for this folder).")
        owner, pid = turn["owner"], turn.get("profile") or browser.MAIN
        on = browser.active_for(browser.owner_path(owner))
        if not on:
            return _error("The browser is off for this folder (its settings, or Settings -> Features).")
        if name not in {t.get("name") for t in cdm.offered(cdm.shipped_tools())} and cdm.shipped_tools():
            return _error(f"Unknown browser tool {name}")
        p = browser.profile(pid)
        if p is None:
            return _error("The browser profile of this turn was deleted.")
        args = cdm.clean_args(args)
        why = rules.page_refusal(args.get("url"), browser.sites_of(p)) if isinstance(args.get("url"), str) else None
        if why:
            await asyncio.to_thread(replays.log_action, pid,
                                    {"at": time.time(), "session": sid, "tool": name,
                                     "args": replays.summary(name, args), "ok": False, "refused": why[:200]})
            return _error(why)
        down = await self.exit_ready(p, sid, owner)
        if down:
            return _error(down)
        t0 = time.time()
        try:
            b = await self.ensure(pid)
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
                await self._level(b)
                try:
                    res = await t.child.call("tools/call", {"name": name, "arguments": args})  # type: ignore[union-attr]
                except RuntimeError:
                    if t.child and t.child.alive:
                        raise
                    await t.stop()
                    t = await self._turn(b, sid, owner)
                    res = await t.child.call("tools/call", {"name": name, "arguments": args})  # type: ignore[union-attr]
            ok = not res.get("isError")
            res = _explain(res, b)
            if ok and name == "new_page":
                await self._drop_blank(b, t)
            extra = []
            if told:
                extra.append("[Harness Maxxing] Since your last action, the person drove a tab of yours: " + told)
            content = list(res.get("content") or [])
            if name == "list_pages":
                content += self._tabs_note(b, t)
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
            await asyncio.to_thread(replays.log_action, pid,
                                    {"at": t0, "session": sid, "tool": name, "args": replays.summary(name, args),
                                     "ok": ok, "ms": int((time.time() - t0) * 1000), "page": replays.page(page)})
            self._changed()

    async def exit_ready(self, p: dict, sid: str, owner: str) -> str | None:
        """None when the profile's exit carries traffic (or it has none); else, after waiting `exit_wait_s` for it,
        what to tell Claude (the session gets a card and the user a notification)."""
        if p["exit"] == browser.DIRECT or p["on_exit_down"] == "vps":
            return None
        e = exits.get(p["exit"])
        if e is None:
            return None
        rt = exits.runtime()
        st = rt.state.get(e["id"]) or {}
        if st.get("ok") and time.time() - st.get("at", 0) < exits.CHECK_EVERY:
            return None
        deadline = time.monotonic() + browser.settings()["exit_wait_s"]
        while True:
            if await rt.check(e["id"]):
                if exits.waiting_for(sid):
                    await asyncio.to_thread(exits.drop_waiter, sid)
                return None
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(min(EXIT_POLL, max(0.0, deadline - time.monotonic())))
        why = (rt.state.get(e["id"]) or {}).get("error") or "offline"
        await asyncio.to_thread(exits.wait_down, sid, owner, e, p)
        return (f"The exit \"{e['name']}\" of the browser profile \"{p['name'] or p['id']}\" is offline ({why}). "
                "The browser waits for it and never uses this server's address instead (the sites would see another "
                "address and could block the accounts). Stop using the browser now, finish what you can without it "
                "and tell the user it is waiting for its exit; they can go on from the card in this session once it "
                "is back.")

    async def _turn(self, b: Browser, sid: str, owner: str) -> Turn:
        """The turn's tools, started if needed, on a profile where the turn has at least one tab."""
        t = b.turns.get(sid)
        if t is None or t.owner != owner:
            if t is not None:
                await t.stop()
            t = b.turns[sid] = Turn(sid, owner)
            self._changed()
        if t.child is not None and t.child.alive:
            return t
        await t.stop()
        if not any(x.get("target") for x in b.tabs.items.values()) and b.watcher:
            b.tabs.claim(t.by)                                       # a first tab of its own
            tid = await b.watcher.open_tab("about:blank")
            t.last_target = tid or t.last_target
        from ..pcbridge import local_host, local_port
        t.child = await cdm.Child.start(f"ws://{local_host()}:{local_port()}/api/browser/cdp/{b.slug}", t.secret)
        if t.child.tools:
            await asyncio.to_thread(cdm.remember_tools, t.child.tools)
        return t

    async def _drop_blank(self, b: Browser, t: Turn) -> None:
        """The empty tab a turn got at its start, once it opened a page of its own."""
        for tab in b.tabs.awake():
            if tab["by"].get("sid") == t.sid and tab["url"] in ("", "about:blank") and tab["target"] != t.last_target \
                    and b.watcher:
                await b.watcher.close_tab(tab["target"])

    def view_for(self, b: Browser, t: Turn) -> View:
        def on_create() -> None:
            b.tabs.claim(t.by)

        def on_use(target: str) -> None:
            b.claude_at[target] = time.time()
            t.last_target = target
            b.tabs.used(target)

        def page_now(tab: str) -> str | None:
            return b.watcher.tab_page.get(tab) if b.watcher else None
        return View(on_create, on_use, page_now)

    async def wait_tab(self, b: Browser, target: str) -> str | None:
        """Claude's command on a tab the person has: wait until they let it go (or give up)."""
        deadline = time.monotonic() + TAB_WAIT
        while b.control and b.control.get("tab") == target and b.state == "running":
            left = deadline - time.monotonic()
            if left <= 0:
                return "The person is using this tab right now: try again later, use another tab, or call ask_human."
            b.released.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(b.released.wait(), min(left, 5))
        return None

    def _tabs_note(self, b: Browser, t: Turn) -> list[dict]:
        """With list_pages: which tabs are the turn's own, which ones the person is using, the asleep ones."""
        notes = []
        ours = [x for x in b.tabs.awake() if mine(x, t.sid, t.path if t.by["kind"] == "agent" else "")]
        if ours:
            notes.append("Tabs you opened: " + "; ".join(replays.page(x["url"]) or "about:blank" for x in ours)
                         + ". The others belong to the user or to other sessions of this profile: read them if "
                           "useful, do not close or reuse them without a reason.")
        if b.control:
            page = b.watcher.pages.get(b.control["tab"], {}) if b.watcher else {}
            notes.append(f"The person is using the tab {replays.page(page.get('url', ''))} right now: commands on it "
                         "wait until they let it go.")
        sleeping = b.tabs.asleep()
        if sleeping:
            notes.append("Asleep tabs (open one again with new_page and its address if you need it): " + "; ".join(
                f"{x['title'] or x['url']} ({replays.page(x['url'])})" for x in sleeping[-10:]))
        return [{"type": "text", "text": "[Harness Maxxing] " + " ".join(notes)}] if notes else []

    def _untold(self, b: Browser, t: Turn) -> list[dict]:
        out: list[dict] = []
        for target, entries in b.trail.items():
            tab = b.tabs.of_target(target)
            if (tab and mine(tab, t.sid, t.path if t.by["kind"] == "agent" else "")) or target == t.last_target:
                out += [e for e in entries if e["at"] > t.told_at]
        t.told_at = time.time()
        return sorted(out, key=lambda e: e["at"])

    async def tools(self) -> list[dict]:
        return cdm.offered(cdm.shipped_tools())

    # ---- people ----------------------------------------------------------------------------------------------
    def _may_follow(self, b: Browser, target: str) -> bool:
        """Show a page Claude opened / moved to the viewers only when the person is not busy in another tab."""
        if b.control:
            return False
        tab = b.tabs.of_target(target)
        return bool(tab and tab["by"].get("kind") != "you") and time.time() - b.last_input > 30

    def _moved(self, b: Browser, target: str, url: str, title: str) -> None:
        if not b.control or b.control.get("tab") != target:
            return
        tab = b.tabs.of_target(target)
        if not tab or tab["by"].get("kind") == "you":
            return                                     # a tab of the person: never told to Claude
        url = replays.page(url)
        if title and title in url:
            title = ""
        lst = b.trail.setdefault(target, [])
        if lst and lst[-1]["url"] == url:
            lst[-1]["title"] = (title or lst[-1]["title"])[:120]
            return
        lst.append({"url": url, "title": (title or "")[:120], "at": time.time()})
        b.trail[target] = lst[-TRAIL_MAX:]

    def input(self, b: Browser, vid: int, name: str = "web") -> None:
        """The person used the tab shown: it is theirs until they let it go (or CONTROL_IDLE)."""
        if not b.watcher or not b.watcher.front:
            return
        now = time.time()
        b.last_input = b.last_use = now
        front = b.watcher.front
        if not b.control or b.control["tab"] != front or b.control["vid"] != vid:
            b.control = {"tab": front, "vid": vid, "name": name, "at": now}
            b.released.clear()
            b.tabs.used(front)
            self._changed()
        else:
            b.control["at"] = now

    def _release(self, b: Browser) -> None:
        if b.control:
            b.control = None
            b.released.set()
            self._changed()

    async def release(self, pid: str | None = None, vid: int | None = None) -> None:
        for b in ([self.browsers.get(pid)] if pid else list(self.browsers.values())):
            if b and b.control and (vid is None or b.control["vid"] == vid):
                self._release(b)

    def busy(self, b: Browser, target: str | None) -> bool:
        """Is Claude using this tab (a command a moment ago)?"""
        return bool(target and time.time() - b.claude_at.get(target, 0) < CLAUDE_BUSY)

    def profile_of(self, sid: str | None) -> str | None:
        """The profile a turn uses (its turn file; the running profiles when it has none)."""
        turn = read_turn(sid) if sid else None
        if turn and turn.get("profile"):
            return str(turn["profile"])
        return next((b.pid for b in self.browsers.values() if sid in b.turns), None)

    async def hand_back(self, sid: str | None) -> dict:
        """What Claude gets with a hand-back: the pages the person went to, the page now and a picture of it."""
        pid = self.profile_of(sid)
        b = self.get(pid) if pid else None
        if not b or not b.watcher:
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

    async def focus_session(self, b: Browser, sid: str) -> None:
        """Show the tab a session used last (the window opened for that session or its request)."""
        t = b.turns.get(sid)
        if b.watcher and t and t.last_target in b.watcher.pages:
            await b.watcher.show(t.last_target)

    # ---- tabs of the person ----------------------------------------------------------------------------------
    async def open_for_person(self, pid: str) -> Browser:
        """Start a profile for the person (the live view): its last tab, else the first site of its list."""
        if not browser.feature_on():
            raise browser.BrowserError(409, "off", "The browser is off (Settings -> Features)")
        p = browser.profile(pid)
        if p is None:
            raise browser.BrowserError(404, "no_profile", "No such browser profile")
        b = await self.ensure(pid)
        if b.watcher and not any(str(t["url"]).startswith(("http://", "https://")) for t in b.tabs.awake()):
            sleeping = b.tabs.asleep()
            if sleeping:
                await self.wake(pid, sleeping[-1]["key"])
            else:
                first = (browser.sites_of(p) or [None])[0]
                front = b.watcher.front
                if first and front and b.watcher.pages.get(front, {}).get("url") in ("", "about:blank"):
                    with contextlib.suppress(Exception):
                        await b.watcher.input({"t": "nav", "url": f"https://{first}/"})
        b.last_use = time.time()
        return b

    async def new_tab(self, pid: str, url: str = "") -> None:
        b = await self.ensure(pid)
        if url:
            url = url if "://" in url else "https://" + url
            why = rules.page_refusal(url, b.sites())
            if why:
                raise browser.BrowserError(400, "refused", why)
        b.tabs.claim({"kind": "you"})
        tid = await b.watcher.open_tab(url or "about:blank")  # type: ignore[union-attr]
        if tid and b.watcher:
            await b.watcher.show(tid)
        await self._sleep_tabs(b, browser.settings(), time.time())

    async def wake(self, pid: str, key: str) -> None:
        """Show a tab: awake, it is shown; asleep, its page opens again."""
        t = self.tabs(pid).items.get(key)
        if not t:
            raise browser.BrowserError(404, "no_tab", "No such tab")
        b = await self.ensure(pid)
        if t.get("target") and b.watcher:
            await b.watcher.show(t["target"])
            if b.control and b.control["tab"] != t["target"]:
                self._release(b)                       # the hand goes with the tab shown
            return
        b.tabs.claim(t["by"], key=key)
        tid = await b.watcher.open_tab(t["url"])  # type: ignore[union-attr]
        if tid and b.watcher:
            await b.watcher.show(tid)
        self._release(b)
        await self._sleep_tabs(b, browser.settings(), time.time())

    async def close_tab(self, pid: str, key: str) -> None:
        tabs = self.tabs(pid)
        t = tabs.items.get(key)
        if not t:
            return
        b = self.browsers.get(pid)
        if t.get("target") and b and b.watcher:
            await b.watcher.close_tab(t["target"])
        tabs.drop(key)
        self._changed()

    async def sleep_now(self, pid: str) -> int:
        """The person asks: every tab of the profile not shown goes to sleep."""
        b = self.get(pid)
        if not b:
            return 0
        return await self._sleep_tabs(b, browser.settings(), time.time(), force=len(b.tabs.awake()))

    async def forget(self, pid: str) -> None:
        """Sign-ins (the profile's Chromium folder), its tabs and its journal erased."""
        import shutil
        await self.stop(pid, "forget")
        await asyncio.to_thread(shutil.rmtree, browser.profile_dir(pid), True)
        tabs = self.tabs(pid)
        for key in list(tabs.items):
            tabs.drop(key)
        tabs.file().unlink(missing_ok=True)
        tabs.dirty = False
        await asyncio.to_thread(replays.forget, pid)
        self._changed()

    # ---- what the UI shows -----------------------------------------------------------------------------------
    def public(self, pid: str) -> dict:
        """One profile: its state, tabs, who has the hand, its turns, memory, traffic."""
        b = self.browsers.get(pid)
        s = browser.settings()
        tabs = self.tabs(pid)
        front = b.watcher.front if b and b.watcher else None
        return {"profile": pid, "state": b.state if b else "stopped",
                "started": b.started if b else None, "last_use": b.last_use if b else None,
                "stops_at": (b.last_use + s["idle_min"] * 60) if b else None,
                "tabs": [tab_public(t, front) for t in tabs.ordered()],
                "front": next((t["key"] for t in tabs.awake() if t["target"] == front), None),
                "page": b.watcher.front_page() if b and b.watcher else None,
                "control": bool(b and b.control), "control_by": (b.control or {}).get("name") if b else None,
                "busy": bool(b and self.busy(b, front)),
                "turns": [{"session": t.sid, "path": t.path, "kind": t.by["kind"]} for t in (b.turns.values() if b else [])],
                "mem": b.mem if b else 0, "level": b.level if b else "",
                "bytes": (b.proxy.bytes_in + b.proxy.bytes_out) if b and b.proxy else 0,
                "blocked": [h for _, h in list(b.proxy.blocked)[-5:]] if b and b.proxy else []}

    def summary(self) -> dict:
        """All profiles at a glance (the sidebar line, the page's list)."""
        used, total = self.server_mem
        running = self.running()
        return {"running": [b.pid for b in running], "mem": sum(b.mem for b in running),
                "turns": {sid: b.pid for b in running for sid in b.turns},
                "tabs": {pid: len([t for t in self.tabs(pid).awake()]) for pid in [b.pid for b in running]},
                "cap": unit.MEMORY_MAX_BYTES, "server_used": used, "server_total": total, "level": self.mem_level()}


_pool: Pool | None = None


def pool() -> Pool:
    global _pool
    if _pool is None:
        _pool = Pool()
    return _pool


BLOCKED_HINT = ("[Harness Maxxing] ERR_BLOCKED_BY_ADMINISTRATOR = this page, or the page it redirected to (a sign-in "
                "on another domain, for example), is not one of the sites this browser profile may open. Tell the user "
                "which site to add to the profile's sites (Browser page -> the profile -> Profile settings); do not try to get around it.")


def _explain(res: dict, b: Browser | None = None) -> dict:
    """A page refused by the profile's own rules (the site list) comes back as a cryptic Chromium error: say why."""
    texts = [c.get("text") or "" for c in res.get("content") or [] if isinstance(c, dict)]
    if any("ERR_BLOCKED_BY_ADMINISTRATOR" in x or "This page is blocked" in x for x in texts):
        return {**res, "content": list(res.get("content") or []) + [{"type": "text", "text": BLOCKED_HINT}]}
    return res


def trail_text(trail: list[dict]) -> str:
    """"A (title) -> B (title)" of the pages a person went to; "" for none."""
    return " -> ".join(f"{x['url']}" + (f" ({x['title']})" if x.get("title") else "") for x in trail)


def _error(text: str) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": text}]}
