"""Harness Browser (maxxing/browser): status, settings, profiles, exits, who uses which profile, tabs, `ask_human`
answers, turns waiting for an exit, the live view, and the two loopback routes of a turn.

Signed in:
  GET  /api/browser                           feature, settings, what this server lacks, profiles (state, tabs,
                                              memory; one per project with agents is made here), navigators (the
                                              person's, agents', sessions'), exits (state, last test), asks, waiting turns
  PUT  /api/browser/navigators/me             {profile} the person's browser on another profile (its tabs move there)
  PUT  /api/browser/settings                  global settings (asks, downloads, sleep, profiles at once...)
  POST /api/browser/setup                     {exits?} install what is missing (root; in the background, see GET)
  POST /api/browser/profiles                  {name, exit?, on_exit_down?} a new profile
  GET  /api/browser/profiles/{pid}            the profile, its browser (tabs...), its agents (lasting navigators),
                                              its sessions' journal (temporary navigators), its actions
  PUT  /api/browser/profiles/{pid}            change it          DELETE: delete it (its sign-ins too; not a project's)
  POST /api/browser/profiles/{pid}/open       {nav?} start it for the person, with a tab in that navigator
  POST /api/browser/profiles/{pid}/stop | sleep | forget     forget = sign-ins, tabs and journal erased
  POST /api/browser/profiles/{pid}/tabs       {url?, nav?} a new tab of the person in a navigator (default "me")
  GET  /api/browser/profiles/{pid}/picture?nav=&w=     a small JPEG of a navigator's tab (204: not running)
  POST /api/browser/profiles/{pid}/files?nav=          the files for the page of that navigator asking for some
  POST /api/browser/profiles/{pid}/tabs/{key}/show            show it (wakes an asleep tab)    DELETE: close it
  POST /api/browser/exits                     {name, type, url?, user?, secret?, node?, login_server?} a new exit
  PUT  /api/browser/exits/{eid}               change it (secret: into the vault)    DELETE: delete it
  POST /api/browser/exits/{eid}/test          address seen, country, operator, kind, delay, speed ("direct" too)
  GET  /api/browser/exits/{eid}/tailscale     its Tailscale: signed in?, sign-in address, devices offered as exit
  POST /api/browser/exits/{eid}/tailscale     {node} use that device | {action: login|logout}
  GET  /api/browser/owner?path=               a project / topic / agent: its own block, what it gets (inherited),
                                              `sites` (a sandboxed agent's domains, null = any public site)
  PUT  /api/browser/owner                     {path, enabled?, profile? (an agent), inherit?: [enabled|profile]}
  POST /api/browser/waiting/{sid}             {action: resume|retry|dismiss} a turn stopped by a down exit
  GET  /api/browser/asks?session=&path=       pending `ask_human` requests
  POST /api/browser/asks/{id}                 {action: done|skip, note?}
  POST /api/browser/live-token                -> {token} (30 s, one use) for WS /api/browser/live?t=&profile=&nav=
Loopback only (+ a secret): POST /api/browser/mcp/{sid} (Bearer = the turn's token), WS /api/browser/cdp/{profile}
(X-Browser-Secret = the secret of a turn's tools: chrome-devtools-mcp).
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import json
import logging
import secrets
import threading
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from .. import agents, browser, bus, config
from ..browser import asks, exits, navs, pool as pool_mod, replays, unit
from ..security import COOKIE, cookie_valid, loopback as _loopback, require_auth

log = logging.getLogger("maxxing.api.browser")
router = APIRouter(prefix="/api/browser", tags=["browser"])
AUTH = [Depends(require_auth)]
LIVE_TOKEN_S = 30.0
MAX_INPUT = 8192
POLL_S = 2.0


def _err(e: browser.BrowserError | asks.AskError | agents.AgentError) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.code, "message": e.message})


def _owner(path: str) -> str:
    path = (path or "").strip().strip("/")
    owner = browser.owner_of(path)
    if not owner:
        raise HTTPException(400, detail={"error": "bad_path", "message": "A project, a topic or an agent folder"})
    if owner.startswith("agent:") and not agents.exists(path):
        raise HTTPException(404, detail={"error": "not_found", "message": "No such agent"})
    if not owner.startswith("agent:") and not (config.workspace() / path).is_dir():
        raise HTTPException(404, detail={"error": "not_found", "message": "No such folder"})
    return owner


def _nav(nav: str | None) -> str:
    nav = (nav or navs.ME).strip()
    if not navs.valid(nav):
        raise HTTPException(400, detail={"error": "bad_navigator", "message": "Not a browser of this server"})
    if navs.kind(nav) == "person" and navs.get_person(nav) is None:
        raise HTTPException(404, detail={"error": "no_navigator", "message": "No such browser"})
    return nav


def _ask_nav(a: dict) -> str:
    owner = str(a.get("owner") or "")
    return f"agent:{browser.owner_path(owner)}" if owner.startswith("agent:") else f"session:{a.get('session') or ''}"


def _profile(pid: str) -> dict:
    p = browser.profile(pid)
    if p is None:
        raise HTTPException(404, detail={"error": "no_profile", "message": "No such browser profile"})
    return p


# ---- setup (background) ------------------------------------------------------------------------------------------
_setup = {"running": False, "log": [], "error": None, "at": 0.0}


def _run_setup(with_exits: bool) -> None:
    def line(text: str) -> None:
        _setup["log"] = (_setup["log"] + [str(text)[:300]])[-40:]
    try:
        unit.setup(line)
        if with_exits:
            exits.setup_tools(log_line=line)
        _setup["error"] = None
    except Exception as e:  # noqa: BLE001
        _setup["error"] = str(e)[:500]
        log.exception("browser setup")
    finally:
        _setup["running"] = False
        unit.available(fresh=True)
        bus.invalidate("browser")


# ---- signed in ---------------------------------------------------------------------------------------------------
def _profiles_view(s: dict, navigators: list[dict] | None = None) -> list[dict]:
    p = pool_mod.pool()
    agents_on = [n for n in (navigators if navigators is not None else p.navigators()) if n["kind"] == "agent"]
    out = []
    for prof in s["profiles"]:
        b = p.browsers.get(prof["id"])
        tabs = p.tabs(prof["id"])
        out.append({**prof, "state": b.state if b else "stopped", "tabs": len(tabs.items),
                    "awake": len(tabs.awake()), "mem": b.mem if b else 0, "turns": len(b.turns) if b else 0,
                    "control": bool(b and b.control), "asks": asks.pending_for_profile(prof["id"]),
                    "has_data": browser.profile_dir(prof["id"]).is_dir(), "gone": browser.project_gone(prof),
                    "agents": len([n for n in agents_on if n["profile"] == prof["id"]])})
    return out


def _status() -> dict:
    if browser.feature_on():
        browser.ensure_projects_with_agents()
    s = browser.settings()
    rt = exits.runtime()
    rt.refresh_seen(s["exits"])                         # a connection that is up reads up, no Test needed
    navigators = pool_mod.pool().navigators()            # once: the profiles count their agents from it
    return {"feature": browser.feature_on(),
            "settings": {k: v for k, v in s.items() if k not in ("profiles", "exits")},
            "available": unit.available(),
            "tools": {"tailscale": bool(exits.tailscale_bins()), "wireguard": bool(exits.wireproxy_bin())},
            "setup": {k: _setup[k] for k in ("running", "log", "error")},
            "profiles": _profiles_view(s, navigators), "navigators": navigators,
            "exits": [rt.public(e) for e in s["exits"]],
            "direct": {"test": rt.tests.get(browser.DIRECT), "checking": browser.DIRECT in rt._refreshing},
            "summary": pool_mod.pool().summary(), "asks": asks.pending(),
            "waiting": exits._waiters()}


@router.get("", dependencies=AUTH)
async def status() -> dict:
    return await asyncio.to_thread(_status)


@router.put("/settings", dependencies=AUTH)
async def put_settings(body: dict) -> dict:
    try:
        await asyncio.to_thread(browser.set_settings, body)
    except browser.BrowserError as e:
        raise _err(e) from None
    bus.invalidate("browser", "settings")
    return await asyncio.to_thread(_status)


class SetupIn(BaseModel):
    exits: bool = False


@router.post("/setup", dependencies=AUTH)
async def setup(body: Optional[SetupIn] = None) -> dict:
    if not _setup["running"]:
        _setup.update(running=True, log=[], error=None, at=time.time())
        threading.Thread(target=_run_setup, args=(bool(body and body.exits),), daemon=True,
                         name="browser-setup").start()
    return {"running": True}


# ---- profiles ----------------------------------------------------------------------------------------------------
class ProfileIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    exit: Optional[str] = Field(default=None, max_length=40)
    on_exit_down: Optional[Literal["wait", "vps"]] = None


def _profile_view(pid: str) -> dict:
    p = _profile(pid)
    pool = pool_mod.pool()
    navigators = pool.navigators()
    live = {n["id"]: n for n in navigators if n["profile"] == pid}
    temporary = []
    for r in replays.sessions(pid):
        nav = f"session:{r['session']}"
        lab = navs.label(nav)
        temporary.append({**r, "title": lab.get("name") or "", "path": lab.get("path") or "",
                          "open": nav in live, "turns": live[nav]["turns"] if nav in live else 0})
    for nav, n in live.items():                       # open, nothing journaled yet (the person's tabs only)
        if n["kind"] == "session" and not any(f"session:{t['session']}" == nav for t in temporary):
            temporary.insert(0, {"session": n.get("session") or nav[8:], "first": n["used"], "last": n["used"],
                                 "actions": 0, "sites": [], "title": n.get("name") or "", "path": n.get("path") or "",
                                 "open": True, "turns": n["turns"]})
    return {"profile": p, "browser": pool.public(pid), "gone": browser.project_gone(p),
            "agents": [n for n in navigators if n["kind"] == "agent" and n["profile"] == pid],
            "person": [n for n in navigators if n["kind"] == "person" and n["profile"] == pid],
            "temporary": temporary, "actions": replays.actions(pid, 30),
            "asks": [a for a in asks.pending() if (a.get("profile") or browser.MAIN) == pid]}


@router.post("/profiles", dependencies=AUTH)
async def new_profile(body: ProfileIn) -> dict:
    try:
        p = await asyncio.to_thread(browser.set_profile, body.model_dump(exclude_none=True))
    except browser.BrowserError as e:
        raise _err(e) from None
    bus.invalidate("browser")
    return p


@router.get("/profiles/{pid}", dependencies=AUTH)
async def get_profile(pid: str) -> dict:
    return await asyncio.to_thread(_profile_view, pid)


@router.put("/profiles/{pid}", dependencies=AUTH)
async def put_profile(pid: str, body: ProfileIn) -> dict:
    try:
        p = await asyncio.to_thread(browser.set_profile, body.model_dump(exclude_none=True), pid)
    except browser.BrowserError as e:
        raise _err(e) from None
    bus.invalidate("browser")
    return p


@router.delete("/profiles/{pid}", dependencies=AUTH)
async def delete_profile(pid: str) -> dict:
    _profile(pid)
    try:
        await asyncio.to_thread(browser.delete_profile, pid)
    except browser.BrowserError as e:
        raise _err(e) from None
    await pool_mod.pool().forget(pid)
    await asyncio.to_thread(navs.on_profile_deleted, pid)
    bus.invalidate("browser", "workspace", "agents")
    return {"ok": True}


class OpenIn(BaseModel):
    nav: Optional[str] = Field(default=None, max_length=300)


@router.post("/profiles/{pid}/open", dependencies=AUTH)
async def open_profile(pid: str, body: Optional[OpenIn] = None) -> dict:
    p = pool_mod.pool()
    nav = _nav(body.nav if body else None)
    try:
        await p.open_for_person(pid, nav)
    except browser.BrowserError as e:
        raise _err(e) from None
    return p.public(pid, nav)


# ---- the person's navigator ----------------------------------------------------------------------------------------
class NavIn(BaseModel):
    profile: str = Field(max_length=40)


@router.put("/navigators/{nav}", dependencies=AUTH)
async def put_navigator(nav: str, body: NavIn) -> dict:
    try:
        n, old = await asyncio.to_thread(navs.update, nav, body.profile)
    except browser.BrowserError as e:
        raise _err(e) from None
    await pool_mod.pool().move_nav(nav, old, n["profile"])
    bus.invalidate("browser")
    return n


@router.post("/profiles/{pid}/stop", dependencies=AUTH)
async def stop_profile(pid: str) -> dict:
    _profile(pid)
    p = pool_mod.pool()
    await p.stop(pid, "stopped by the user")
    return p.public(pid)


@router.post("/profiles/{pid}/sleep", dependencies=AUTH)
async def sleep_tabs(pid: str) -> dict:
    _profile(pid)
    p = pool_mod.pool()
    n = await p.sleep_now(pid)
    return {**p.public(pid), "slept": n}


@router.post("/profiles/{pid}/forget", dependencies=AUTH)
async def forget(pid: str) -> dict:
    """Sign-ins (the profile's folder), its tabs and the journal of its actions are erased."""
    _profile(pid)
    p = pool_mod.pool()
    await p.forget(pid)
    return p.public(pid)


class TabIn(BaseModel):
    url: Optional[str] = Field(default=None, max_length=2000)
    nav: Optional[str] = Field(default=None, max_length=300)


@router.post("/profiles/{pid}/tabs", dependencies=AUTH)
async def new_tab(pid: str, body: TabIn) -> dict:
    _profile(pid)
    nav = _nav(body.nav)
    p = pool_mod.pool()
    try:
        await p.new_tab(pid, (body.url or "").strip(), nav)
    except browser.BrowserError as e:
        raise _err(e) from None
    return p.public(pid, nav)


@router.get("/profiles/{pid}/picture", dependencies=AUTH)
async def picture(pid: str, nav: str = navs.ME, w: int = 480) -> Response:
    """A small JPEG of a navigator's tab (the one in front, else the one used last); 204 while it is not running."""
    _profile(pid)
    data = await pool_mod.pool().thumb(pid, _nav(nav), w)
    if not data:
        return Response(status_code=204)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/profiles/{pid}/files", dependencies=AUTH)
async def give_files(pid: str, nav: str = navs.ME, files: list[UploadFile] = File(...)) -> dict:
    """The files the person picked for the page of this navigator that asked for some (its file input)."""
    _profile(pid)
    nav = _nav(nav)
    p = pool_mod.pool()
    b = p.get(pid)
    if not b or not b.watcher or not b.watcher.chooser_of(nav):
        raise HTTPException(409, detail={"error": "no_chooser", "message": "No page is asking for a file"})
    paths = []
    for f in files[:20]:
        data = await f.read(pool_mod.UPLOAD_MAX + 1)
        if len(data) > pool_mod.UPLOAD_MAX:
            raise HTTPException(413, detail={"error": "too_large",
                                             "message": f"{f.filename} is larger than {pool_mod.UPLOAD_MAX // 1024 // 1024} MB"})
        paths.append(await asyncio.to_thread(pool_mod.stage, b, f.filename or "file", data))
    try:
        await b.watcher.give_files(nav, paths)
    except (RuntimeError, PermissionError) as e:
        raise HTTPException(409, detail={"error": "no_chooser", "message": str(e)}) from None
    b.last_use = time.time()
    return p.public(pid, nav)


@router.post("/profiles/{pid}/tabs/{key}/show", dependencies=AUTH)
async def show_tab(pid: str, key: str) -> dict:
    _profile(pid)
    p = pool_mod.pool()
    try:
        await p.wake(pid, key)
    except browser.BrowserError as e:
        raise _err(e) from None
    t = p.tabs(pid).items.get(key)
    return p.public(pid, t["nav"] if t else None)


@router.delete("/profiles/{pid}/tabs/{key}", dependencies=AUTH)
async def close_tab(pid: str, key: str) -> dict:
    _profile(pid)
    p = pool_mod.pool()
    t = p.tabs(pid).items.get(key)
    await p.close_tab(pid, key)
    return p.public(pid, t["nav"] if t else None)


# ---- exits -------------------------------------------------------------------------------------------------------
class ExitIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    type: Optional[Literal["proxy", "tailscale", "wireguard"]] = None
    url: Optional[str] = Field(default=None, max_length=500)
    user: Optional[str] = Field(default=None, max_length=200)
    secret: Optional[str] = Field(default=None, max_length=16000)
    node: Optional[str] = Field(default=None, max_length=200)
    login_server: Optional[str] = Field(default=None, max_length=300)


@router.post("/exits", dependencies=AUTH)
async def new_exit(body: ExitIn) -> dict:
    if not body.type:
        raise HTTPException(400, detail={"error": "bad_exit", "message": "An exit needs a type"})
    values = body.model_dump(exclude_none=True)
    secret = values.pop("secret", None)
    try:
        e = await asyncio.to_thread(exits.set_exit, values, None, secret)
    except browser.BrowserError as ex:
        raise _err(ex) from None
    bus.invalidate("browser")
    return exits.runtime().public(e)


@router.put("/exits/{eid}", dependencies=AUTH)
async def put_exit(eid: str, body: ExitIn) -> dict:
    values = body.model_dump(exclude_none=True)
    secret = values.pop("secret", None)
    try:
        e = await asyncio.to_thread(exits.set_exit, values, eid, secret)
    except browser.BrowserError as ex:
        raise _err(ex) from None
    bus.invalidate("browser")
    return exits.runtime().public(e)


@router.delete("/exits/{eid}", dependencies=AUTH)
async def delete_exit(eid: str) -> dict:
    try:
        await asyncio.to_thread(exits.delete_exit, eid)
    except browser.BrowserError as ex:
        raise _err(ex) from None
    bus.invalidate("browser")
    return {"ok": True}


@router.post("/exits/{eid}/test", dependencies=AUTH)
async def test_exit(eid: str) -> dict:
    try:
        out = await exits.runtime().test(eid)
    except browser.BrowserError as ex:
        raise _err(ex) from None
    bus.invalidate("browser")
    return out


def _tailscale_exit(eid: str) -> dict:
    e = exits.get(eid)
    if e is None or e["type"] != "tailscale":
        raise HTTPException(404, detail={"error": "no_exit", "message": "No such Tailscale exit"})
    return e


@router.get("/exits/{eid}/tailscale", dependencies=AUTH)
async def tailscale_status(eid: str) -> dict:
    e = _tailscale_exit(eid)
    return await asyncio.to_thread(exits.Tailscale.status, e)


class TailscaleIn(BaseModel):
    node: Optional[str] = Field(default=None, max_length=200)
    action: Optional[Literal["login", "logout"]] = None


@router.post("/exits/{eid}/tailscale", dependencies=AUTH)
async def tailscale_set(eid: str, body: TailscaleIn) -> dict:
    e = _tailscale_exit(eid)

    def run() -> dict:
        if body.action == "logout":
            exits.Tailscale.logout(e)
        elif body.action == "login":
            exits.Tailscale.login(e)
        if body.node:
            exits.Tailscale.use_node(e, body.node)
            exits.set_exit({"node": body.node}, eid)
        return exits.Tailscale.status(exits.get(eid) or e)
    try:
        out = await asyncio.to_thread(run)
    except browser.BrowserError as ex:
        raise _err(ex) from None
    bus.invalidate("browser")
    return out


# ---- who uses which profile ------------------------------------------------------------------------------------------
def _owner_view(owner: str) -> dict:
    path = browser.owner_path(owner)
    s = browser.settings()
    r = browser.resolve(path, s)
    if r["enabled"] and not r["profile"] and r["project"] and browser.feature_on():
        r = browser.resolve(path, create=True)          # on: its project's profile is made now (shown, opened)
        s = browser.settings()
    chain = browser.chain(path)
    parent = browser.resolve(path.rsplit("/", 2)[0], s) if owner.startswith(("agent:", "topic:")) else None
    p = browser.profile(r["profile"], s) if r["profile"] else None
    mine = browser.project_profile(r["project"], s) if r["project"] else None
    return {"owner": owner, "path": path, "kind": owner.split(":", 1)[0], "own": browser.own_block(owner),
            "enabled": r["enabled"], "profile": r["profile"], "from": r["from"], "feature": browser.feature_on(),
            "project": r["project"], "project_profile": mine["id"] if mine else "",
            "inherited": parent, "chain": chain, "sites": browser.agent_sites(owner),
            "exit": exits.runtime().public(exits.get(p["exit"])) if p and p["exit"] != browser.DIRECT
            and exits.get(p["exit"]) else None,
            "asks": asks.pending(owner=owner)}


@router.get("/owner", dependencies=AUTH)
async def get_owner(path: str) -> dict:
    return await asyncio.to_thread(_owner_view, _owner(path))


class OwnerIn(BaseModel):
    path: str = Field(max_length=300)
    enabled: Optional[bool] = None
    profile: Optional[str] = Field(default=None, max_length=40)
    inherit: list[Literal["enabled", "profile"]] = []       # keys given back to the parent


@router.put("/owner", dependencies=AUTH)
async def put_owner(body: OwnerIn) -> dict:
    owner = _owner(body.path)
    path = browser.owner_path(owner)
    if (body.profile or "profile" in body.inherit) and not owner.startswith("agent:"):
        raise HTTPException(400, detail={"error": "bad_browser",
                                         "message": "A project's sessions use its profile: only an agent chooses"})
    if body.profile and browser.profile(body.profile) is None:
        raise HTTPException(404, detail={"error": "no_profile", "message": "No such browser profile"})

    def save() -> None:
        block = dict(browser.own_block(owner))
        if body.enabled is not None:
            block["enabled"] = body.enabled
        if body.profile:
            block["profile"] = body.profile
        for k in body.inherit:
            block.pop(k, None)
        block = browser.clean(block, strict=True)
        if owner.startswith("agent:"):
            cur = agents.load(path).get("browser") or {}
            agents.update(path, {"browser": {**{k: None for k in cur}, **block}})
        else:
            from .. import workspace
            workspace.set_folder_browser(path, block)
    try:
        await asyncio.to_thread(save)
    except (browser.BrowserError, agents.AgentError) as e:
        raise _err(e) from None
    bus.invalidate("browser", "agents", "workspace")
    return await asyncio.to_thread(_owner_view, owner)


# ---- a turn stopped by its exit ----------------------------------------------------------------------------------------
class WaitIn(BaseModel):
    action: Literal["resume", "retry", "dismiss"]


@router.post("/waiting/{sid}", dependencies=AUTH)
async def waiting(sid: str, body: WaitIn) -> dict:
    w = await asyncio.to_thread(exits.waiting_for, sid)
    if not w:
        raise HTTPException(404, detail={"error": "not_waiting", "message": "This session does not wait for an exit"})
    if body.action == "dismiss":
        await asyncio.to_thread(exits.drop_waiter, sid)
        return {"ok": True}
    if body.action == "resume":
        await asyncio.to_thread(exits.set_resume, sid)
    ok = await exits.runtime().check(w["exit"])
    return {"ok": ok, "waiting": await asyncio.to_thread(exits.waiting_for, sid)}


# ---- asks --------------------------------------------------------------------------------------------------------
@router.get("/asks", dependencies=AUTH)
async def list_asks(session: Optional[str] = None, path: Optional[str] = None) -> dict:
    owner = _owner(path) if path else None
    return {"asks": await asyncio.to_thread(asks.pending, owner, session or None)}


class AnswerIn(BaseModel):
    action: Literal["done", "skip"]
    note: Optional[str] = Field(default=None, max_length=500)


async def _decide(rid: str, action: str, note: str = "") -> dict:
    """Answer a request; "done" gives Claude what the person did (pages, the page now, a picture of it)."""
    cur = await asyncio.to_thread(asks.get, rid)
    extra = await pool_mod.pool().hand_back(cur.get("session"), str(cur.get("owner") or "")) \
        if cur and action == "done" else None
    return await asyncio.to_thread(asks.decide, rid, action, "web", note, extra)


@router.post("/asks/{rid}", dependencies=AUTH)
async def answer(rid: str, body: AnswerIn) -> dict:
    try:
        d = await _decide(rid, body.action, body.note or "")
    except asks.AskError as e:
        raise _err(e) from None
    await pool_mod.pool().release(d.get("profile") or None)   # whoever had taken over hands back with the answer
    return d


# ---- live view -----------------------------------------------------------------------------------------------------
_live: dict[str, float] = {}


@router.post("/live-token", dependencies=AUTH)
async def live_token() -> dict:
    now = time.time()
    for k, at in list(_live.items()):
        if now - at > LIVE_TOKEN_S:
            _live.pop(k, None)
    t = secrets.token_urlsafe(24)
    _live[t] = now
    return {"token": t}


def _take_token(t: str) -> bool:
    at = _live.pop(t or "", None)
    return bool(at and time.time() - at <= LIVE_TOKEN_S)


@router.websocket("/live")
async def live(ws: WebSocket):
    """Pictures of the tab shown of one navigator (binary JPEG) + its state (text JSON) while its profile runs; the
    person's mouse and keyboard on that tab ({"t":"mouse"|"wheel"|"key"|"text"|"nav"|"back"|"forward"|"reload"|"copy"|
    "dialog"|"chooser"}: the tab is theirs while they use it; {"t":"take"} / {"t":"release","done":bool,"note":...};
    {"t":"size","w","h"}; {"t":"quality","q"}). Each picture is confirmed by the page ({"t":"got"}): a few may be on
    their way at once (live.INFLIGHT), so a far connection still gets several per round trip and a slow one never a
    pile of late ones (live.Watcher.delivered). The signed-in cookie AND a live token (POST /live-token) are needed."""
    if not _take_token(ws.query_params.get("t", "")) or not cookie_valid(ws.cookies.get(COOKIE)):
        await ws.close(code=4403)
        return
    pid = ws.query_params.get("profile") or browser.MAIN
    nav = ws.query_params.get("nav") or navs.ME
    if browser.profile(pid) is None or not navs.valid(nav):
        await ws.close(code=4404)
        return
    await ws.accept()
    p = pool_mod.pool()
    vid = id(ws)
    watched: list = [None]                  # the Browser being watched
    sent = {"state": ""}
    send_lock = asyncio.Lock()
    latest: list = [None]                   # the newest picture not sent yet
    fresh = asyncio.Event()
    on_way: collections.deque = collections.deque()   # (sent at, size) of the pictures not confirmed yet

    async def send_bytes(data: bytes) -> None:
        """Never waits for the network: the pump sends the newest picture when the connection is free (one it did
        not send in time is replaced, and counted back at once)."""
        b = watched[0]
        if latest[0] is not None and b is not None and b.watcher:
            b.watcher.delivered(vid, 0, -1.0)
        latest[0] = data
        fresh.set()

    async def pump() -> None:
        while True:
            await fresh.wait()
            fresh.clear()
            data, latest[0] = latest[0], None
            if data:
                on_way.append((time.monotonic(), len(data)))
                async with send_lock:
                    await ws.send_bytes(data)

    async def send_json(d: dict) -> None:
        async with send_lock:
            await ws.send_text(json.dumps(d, ensure_ascii=False))

    async def follow() -> None:
        """Attach to the profile's browser when it (re)starts; push the navigator's state when it changes."""
        while True:
            b = p.browsers.get(pid)
            if b is not watched[0]:
                old = watched[0]
                if old is not None and old.watcher:
                    await old.watcher.unwatch(vid)
                on_way.clear()
                watched[0] = b if b and b.state == "running" and b.watcher else None
                if watched[0] is not None:
                    await watched[0].watcher.watch(vid, nav, send_bytes, ws.query_params.get("q", "auto"))
                    await p._level(watched[0])
            c = b.control.get(nav) if b else None
            st = {"t": "state", "browser": p.public(pid, nav), "me": bool(c and c["vid"] == vid),
                  "asks": [a for a in await asyncio.to_thread(asks.pending) if _ask_nav(a) == nav]}
            text = json.dumps(st, sort_keys=True, default=str)
            if text != sent["state"]:
                sent["state"] = text
                await send_json(st)
            await asyncio.sleep(0.5 if b and b.state == "starting" else 1.0)

    task = asyncio.create_task(follow())
    pumping = asyncio.create_task(pump())
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > MAX_INPUT:
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            t = ev.get("t")
            b = p.get(pid)
            if t == "got":
                if on_way:
                    at, size = on_way.popleft()
                    if b is not None and b is watched[0] and b.watcher:
                        b.watcher.delivered(vid, size, time.monotonic() - at)
                continue
            if t == "quality":
                if b and b.watcher:
                    await b.watcher.set_quality(vid, str(ev.get("q") or "auto"))
            elif t == "size":
                if b and b.watcher:
                    with contextlib.suppress(Exception):
                        await b.watcher.resize(vid, ev.get("w"), ev.get("h"), ev.get("dpr"))
            elif t == "take":
                if b:
                    p.input(b, vid, nav)
            elif t == "release":
                if ev.get("done") in (True, "done", "skip"):
                    action = "skip" if ev.get("done") == "skip" else "done"
                    for d in await asyncio.to_thread(asks.pending):
                        if _ask_nav(d) != nav:
                            continue
                        with contextlib.suppress(asks.AskError):
                            await _decide(d["id"], action, str(ev.get("note") or "")[:500])
                await p.release(pid, vid)
            elif b and b.watcher:
                c = b.control.get(nav)
                if t in ("mouse", "wheel", "key", "text", "nav", "back", "forward", "reload") and \
                        not (t == "mouse" and ev.get("type") == "move" and not (c and c["vid"] == vid)):
                    p.input(b, vid, nav)
                try:
                    why = await b.watcher.input(nav, ev)
                except Exception as e:  # noqa: BLE001 - a page that went away
                    why = str(e)[:200]
                b.last_use = time.time()
                if isinstance(why, dict):
                    await send_json(why)
                elif why:
                    await send_json({"t": "error", "text": why})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        for tk in (task, pumping):
            tk.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await tk
        b = watched[0]
        if b is not None and b.watcher:
            with contextlib.suppress(Exception):
                await b.watcher.unwatch(vid)
            with contextlib.suppress(Exception):
                await p._level(b)
        await p.release(pid, vid)          # its requests stay pending: the person may come back


# ---- loopback: a turn's tools, chrome-devtools-mcp's DevTools --------------------------------------------------------
@router.post("/mcp/{sid}")
async def mcp(sid: str, request: Request):
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not _loopback(request) or not replays.SID_RE.match(sid) or \
            not await asyncio.to_thread(pool_mod.check_turn, sid, token):
        return JSONResponse({"error": "forbidden", "message": "Not a running turn of this server"}, status_code=403)
    try:
        m = await request.json()
    except (ValueError, RecursionError):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
    if not isinstance(m, dict):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}})
    mid, method, params = m.get("id"), m.get("method"), m.get("params") or {}
    p = pool_mod.pool()
    if method == "tools/list":
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": {"tools": await p.tools()}})
    if method == "tools/call" and isinstance(params, dict):
        args = params.get("arguments")
        try:
            res = await p.call(sid, str(params.get("name") or ""), args if isinstance(args, dict) else {})
        except browser.BrowserError as e:
            res = pool_mod._error(e.message)
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": res})
    return JSONResponse({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}})


@router.websocket("/cdp/{pid}")
async def cdp(ws: WebSocket, pid: str):
    p = pool_mod.pool()
    found = p.by_secret(pid, ws.headers.get("x-browser-secret", ""))
    if not found or not _loopback(ws):
        await ws.close(code=4403)
        return
    b, turn = found
    await ws.accept()
    from ..browser import relay

    async def recv() -> str | None:
        try:
            return await ws.receive_text()
        except (WebSocketDisconnect, RuntimeError):
            return None
    try:
        await relay.pump(b.run / "cdp.sock", b.ws_path, lambda: turn.sites, recv, ws.send_text, view=p.view_for(b, turn),
                         wait_tab=lambda target: p.wait_tab(b, target))
    except Exception as e:  # noqa: BLE001
        log.info("browser devtools relay: %s", e)
    finally:
        with contextlib.suppress(Exception):
            await ws.close()


# ---- watcher -------------------------------------------------------------------------------------------------------
_task: asyncio.Task | None = None


async def _watch() -> None:
    await asyncio.to_thread(asks.prime)
    while True:
        await asyncio.sleep(POLL_S)
        try:
            await asyncio.to_thread(asks.scan)
        except Exception:  # noqa: BLE001
            log.exception("browser asks watcher pass failed")


async def startup() -> None:
    global _task
    await asyncio.to_thread(unit.stop_all_units)        # browsers of a previous server run
    await asyncio.to_thread(pool_mod.clear_turns)
    await asyncio.to_thread(browser.migrate)
    pool_mod.pool().watch()
    _task = asyncio.get_running_loop().create_task(_watch())


async def shutdown() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
    with contextlib.suppress(Exception):
        await asyncio.wait_for(pool_mod.pool().stop_all(), 10)
