"""Claude's tools on the person's devices (MCP `harness-devices`, through devices_mcp.py and POST /api/devices/mcp).

Coordinates are pixels of the latest screenshot Claude got of that device (at most SHOT_MAX_W wide); the device gets
them with that picture's size (`sw`, `sh`) and converts. Every action answers with a new screenshot (SETTLE_S later).
Refused: a device offline, paused on the device, in "view" mode (only VIEW_TOOLS), outside the turn's access, while
the person has it (the live view), or a protected / locked screen (the device says so).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from . import OS_NAMES, store, visible
from .asks import ask as ask_person
from .hub import DeviceError, Offline, finite, hub

SHOT_MAX_W = 1280
SHOT_QUALITY = 70
SETTLE_S = 0.4
MAX_TEXT = 4000
MAX_TREE_NODES = 300
VIEW_TOOLS = frozenset({"devices", "screenshot", "zoom", "ui_tree", "ask_human", "wait", "screen"})
SWITCH_WAIT_S = 3.0

_D = {"device": {"type": "string", "description": "The device id (or its name) from `devices`."}}
_XY = {"x": {"type": "number"}, "y": {"type": "number"}}


def _spec(name: str, description: str, props: dict | None = None, required: list[str] | None = None) -> dict:
    p = {**({} if name == "devices" else _D), **(props or {})}
    req = ([] if name == "devices" else ["device"]) + (required or [])
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": p, "required": req}}


TOOLS = [
    _spec("devices", "List the person's devices you may use: id, name, system, online, rights (view: look only; "
                     "control: click and type), screen size, notes (what does not work there)."),
    _spec("screenshot", "A picture of the device's screen. Coordinates of the other tools are pixels of the latest "
                        "screenshot of that device."),
    _spec("zoom", "A closer picture of a part of the screen (to read small text). x, y, w, h in pixels of the latest "
                  "screenshot. Its own pixels are not coordinates for clicks.",
          {**_XY, "w": {"type": "number"}, "h": {"type": "number"}}, ["x", "y", "w", "h"]),
    _spec("click", "Click (Android: tap) at x, y.", {**_XY, "button": {"type": "string", "enum": ["left", "right", "middle"]},
                                                    "double": {"type": "boolean"}}, ["x", "y"]),
    _spec("long_press", "Press and hold at x, y (Android: long tap; a computer: hold the left button).",
          {**_XY, "ms": {"type": "integer", "description": "How long, in milliseconds (default 800)."}}, ["x", "y"]),
    _spec("move", "Move the mouse pointer to x, y (computers: menus that open on hover).", _XY, ["x", "y"]),
    _spec("drag", "Drag from x1, y1 to x2, y2 (Android: swipe).",
          {"x1": {"type": "number"}, "y1": {"type": "number"}, "x2": {"type": "number"}, "y2": {"type": "number"},
           "ms": {"type": "integer", "description": "Duration in milliseconds (default 300)."}},
          ["x1", "y1", "x2", "y2"]),
    _spec("scroll", "Scroll at x, y: dy > 0 scrolls down, dx > 0 right (in notches / screen steps).",
          {**_XY, "dx": {"type": "number"}, "dy": {"type": "number"}}, ["x", "y"]),
    _spec("type", "Type text into the focused field.", {"text": {"type": "string"}}, ["text"]),
    _spec("key", "Press a key or a shortcut: \"enter\", \"tab\", \"escape\", \"ctrl+s\", \"cmd+space\"; Android: "
                 "\"back\", \"home\", \"recents\".", {"keys": {"type": "string"}}, ["keys"]),
    _spec("ui_tree", "The elements on the screen (Android: the accessibility tree - id, role, text, frame, clickable, "
                     "editable). Cheaper and more precise than pictures for tapping and typing. Not on computers yet."),
    _spec("tap_element", "Tap an element of ui_tree by its id.", {"element": {"type": "string"}}, ["element"]),
    _spec("set_text", "Put text into an editable element of ui_tree (replaces its content).",
          {"element": {"type": "string"}, "text": {"type": "string"}}, ["element", "text"]),
    _spec("screen", "A computer with several screens: switch to another one (`devices` lists them with their number). "
                    "You then see and act on that screen only (it is also the one the person's live view shows); "
                    "answers with a screenshot of it. Use it when what you look for is not on the screen you see.",
          {"screen": {"type": "integer", "description": "The screen number from `devices`; -1 = the main screen."}},
          ["screen"]),
    _spec("apps", "The apps that can be opened on the device."),
    _spec("open_app", "Open an app by its name or id (see apps).", {"name": {"type": "string"}}, ["name"]),
    _spec("wait", "Wait a few seconds (a page loading, an animation), then look again with screenshot.",
          {"s": {"type": "number", "description": "Seconds, 0.5 to 30."}}, ["s"]),
    _spec("ask_human", "Ask the person to do a step themselves on the device (type a password or a code received by "
                       "SMS, solve a captcha, confirm a payment, choose), then wait until they hand it back (with a "
                       "word) or skip. Use it instead of guessing a password or a code.",
          {"message": {"type": "string", "description": "What they must do, one short sentence in their language "
                                                        "(shown in their notification)."}}, ["message"]),
]
NAMES = {t["name"] for t in TOOLS}


class Refused(Exception):
    pass


def _text(t: str) -> dict:
    return {"type": "text", "text": t}


def _err(t: str) -> dict:
    return {"isError": True, "content": [_text(t)]}


def _num(args: dict, k: str, default: float | None = None) -> float:
    v = args.get(k, default)
    if not finite(v):
        raise Refused(f"`{k}` must be a number")
    return float(v)


def _space(did: str, dev: dict) -> tuple[int, int]:
    """The coordinate space of a device: its latest picture's size, else its screen scaled to SHOT_MAX_W."""
    s = hub().shots.get(did)
    if s:
        return s
    scr = dev.get("screen") or (hub().conn(did).hello.get("screen") if hub().conn(did) else None) or {}
    w, h = int(scr.get("w") or 0), int(scr.get("h") or 0)
    if w <= 0 or h <= 0:
        return 0, 0
    if w > SHOT_MAX_W:
        return SHOT_MAX_W, max(1, round(h * SHOT_MAX_W / w))
    return w, h


def _point(args: dict, sw: int, sh: int, kx: str = "x", ky: str = "y") -> tuple[int, int]:
    if not sw or not sh:
        raise Refused("Take a screenshot of this device first: coordinates are pixels of that picture.")
    x, y = _num(args, kx), _num(args, ky)
    if not (0 <= x <= sw and 0 <= y <= sh):
        raise Refused(f"({x:g}, {y:g}) is outside the screenshot ({sw}x{sh}).")
    return round(x), round(y)


WHY = {"paused": "The person paused Harness Link on {name}: wait, or ask them in your answer.",
       "protected": "{name} shows a protected screen (an app that forbids screenshots): ask the person (ask_human) "
                    "or do something else.",
       "locked": "{name} is locked: ask the person to unlock it (ask_human).",
       "unsupported": "{name} cannot do that: {message}",
       "denied": "{name} refused: {message}"}


def _device_error(dev: dict, e: DeviceError) -> str:
    return WHY.get(e.code, "{name}: {message}").format(name=dev["name"], message=e.message or e.code)


def _describe(dev: dict) -> str:
    h = hub().public(dev["id"])
    scr = (h.get("hello") or {}).get("screen") or dev.get("screen") or {}
    bits = [f"id {dev['id']}", OS_NAMES.get(dev["os"], dev["os"]), "online" if h["online"] else "offline",
            "view only" if dev.get("mode") == "view" else "control"]
    if scr.get("w"):
        bits.append(f"screen {scr.get('w')}x{scr.get('h')}")
    screens = (h.get("hello") or {}).get("screens") or []
    if len(screens) > 1:
        shown = (h.get("hello") or {}).get("display")
        cur = next((x for x in screens if x.get("i") == shown), None) or next((x for x in screens if x.get("main")), {})
        bits.append(f"{len(screens)} screens (" + "; ".join(
            f"{x['i']} {x['name']} {x['w']}x{x['h']}" + (" main" if x.get("main") else "") for x in screens) +
            f"), you see {cur.get('i', 0)} {cur.get('name', '')}: switch with the screen tool")
    if h["paused"]:
        bits.append("paused by the person")
    if h["human"]:
        bits.append("the person is using it now")
    note = (h.get("hello") or {}).get("note") or dev.get("note")
    if note:
        bits.append(f"note: {note}")
    return f"- {dev['name']}: " + ", ".join(bits)


async def _shot(did: str, max_w: int = SHOT_MAX_W, crop: dict | None = None) -> tuple[str, int, int]:
    msg: dict = {"t": "shot", "max_w": max_w, "quality": SHOT_QUALITY}
    if crop:
        msg.update(crop)
    r = await hub().request(did, msg)
    data = str(r.get("jpeg") or "")
    w, h = int(r.get("w") or 0), int(r.get("h") or 0)
    if not data or w <= 0 or h <= 0:
        raise DeviceError("bad_answer", "the device sent no picture")
    return data, w, h


async def _picture(did: str, dev: dict, caption: str) -> list[dict]:
    data, w, h = await _shot(did)
    hub().shots[did] = (w, h)
    return [{"type": "image", "data": data, "mimeType": "image/jpeg"},
            _text(f"{caption}{dev['name']}: {w}x{h} picture (coordinates are pixels of this picture).")]


def _tree_text(nodes: list) -> str:
    lines = []
    for n in nodes[:MAX_TREE_NODES]:
        if not isinstance(n, dict):
            continue
        b = n.get("b") if isinstance(n.get("b"), list) else []
        flags = " ".join(f for f, k in (("click", "click"), ("edit", "edit"), ("focus", "focus")) if n.get(k))
        text = store._text(n.get("text"), 120)
        desc = store._text(n.get("desc"), 120)
        frame = ",".join(str(int(v)) for v in b[:4] if isinstance(v, (int, float)))
        lines.append(f"[{store._text(n.get('id'), 40)}] {store._text(n.get('role'), 40)}"
                     + (f" \"{text}\"" if text else "") + (f" ({desc})" if desc else "")
                     + (f" @{frame}" if frame else "") + (f" {flags}" if flags else ""))
    more = len(nodes) - MAX_TREE_NODES
    return "\n".join(lines) + (f"\n... {more} more elements" if more > 0 else "")


Alive = Callable[[], Awaitable[bool]]


async def call(turn: dict, sid: str, name: str, args: dict, alive: Alive | None = None) -> dict:
    """One tool call of a turn (`turn`: its file, {owner, path}). Never raises: an MCP tool result."""
    t0 = time.time()
    path = str(turn.get("path") or "")
    owner = str(turn.get("owner") or "")
    if name not in NAMES:
        return _err(f"Unknown tool {name}")
    mine = await asyncio.to_thread(visible, path)
    if name == "devices":
        if not mine:
            return {"content": [_text("No device is available to this session.")]}
        return {"content": [_text("Devices:\n" + "\n".join(_describe(d) for d in mine))]}
    ref = str(args.get("device") or "").strip()
    dev = next((d for d in mine if d["id"] == ref), None) or next(
        (d for d in mine if d["name"].casefold() == ref.casefold()), None)
    if dev is None:
        return _err(f"No device {ref[:60]!r} for this session: call `devices` to see the ones you may use.")
    did = dev["id"]
    ok, error = False, ""
    try:
        if name not in VIEW_TOOLS and dev.get("mode") == "view":
            raise Refused(f"{dev['name']} is \"view only\": you may look (screenshot, zoom, ui_tree) and guide the "
                          "person, not click or type. The person can give you control in Settings -> Devices.")
        if name == "ask_human":
            await hub().claude_acted(did, sid, owner)
            d = await ask_person(sid, owner, dev, str(args.get("message") or ""), alive)
            ok = True
            return await _answer(did, dev, d)
        if name == "wait":
            s = min(30.0, max(0.5, _num(args, "s", 2)))
            await asyncio.sleep(s)
            ok = True
            return {"content": [_text(f"Waited {s:g} s.")]}
        if not hub().online(did):
            how = ("open the Harness Link app on it" if dev.get("os") == "android" else
                   "open a terminal on it and type harness-link (Harness Link only runs while that window is open)")
            raise Refused(f"{dev['name']} is offline. Ask the person to {how}, then try again.")
        if hub().paused(did):
            raise DeviceError("paused")
        acts = name not in ("screenshot", "zoom", "ui_tree", "apps")
        if acts and hub().human_has(did):
            raise Refused(f"The person is using {dev['name']} right now: wait (then take a screenshot), or call "
                          "ask_human if you need them to do this step.")
        await hub().claude_acted(did, sid, owner)
        res = await _run(did, dev, name, args)
        ok = not res.get("isError")
        return res
    except Refused as e:
        error = str(e)
        return _err(error)
    except Offline:
        error = f"{dev['name']} went offline."
        return _err(error)
    except DeviceError as e:
        error = _device_error(dev, e)
        return _err(error)
    except asyncio.TimeoutError:
        error = f"{dev['name']} did not answer in time."
        return _err(error)
    finally:
        await asyncio.to_thread(store.log_action, did, name, args, ok, int((time.time() - t0) * 1000), sid, owner,
                                error)


async def _answer(did: str, dev: dict, d: dict) -> dict:
    st = d.get("status")
    note = f" They said: {d['note']}" if d.get("note") else ""
    if st == "done":
        out = [_text(f"The person did it and handed {dev['name']} back.{note} Look at the screen again before acting.")]
        if hub().online(did) and not hub().paused(did):
            try:
                out += await _picture(did, dev, "Now: ")
            except (Offline, DeviceError, asyncio.TimeoutError):
                pass
        return {"content": out}
    if st == "skip":
        return {"content": [_text("The person skipped this step: do not try it again in this run; go on without it "
                                  "or stop." + note)]}
    if st == "timeout":
        return {"content": [_text("Nobody answered in time: give up this step for this run and say so.")]}
    return {"content": [_text("The request was cancelled.")]}


async def _run(did: str, dev: dict, name: str, args: dict) -> dict:
    h = hub()
    if name == "screenshot":
        return {"content": await _picture(did, dev, "")}
    sw, sh = _space(did, dev)
    if name == "zoom":
        x, y = _point(args, sw, sh)
        w, hh = _num(args, "w"), _num(args, "h")
        if w < 4 or hh < 4:
            raise Refused("w and h: at least 4 pixels")
        w, hh = min(w, sw - x), min(hh, sh - y)
        data, zw, zh = await _shot(did, SHOT_MAX_W, {"crop": {"x": x, "y": y, "w": round(w), "h": round(hh)},
                                                      "sw": sw, "sh": sh})
        return {"content": [{"type": "image", "data": data, "mimeType": "image/jpeg"},
                            _text(f"Zoom on ({x}, {y}) {round(w)}x{round(hh)} of {dev['name']}: {zw}x{zh} picture "
                                  "(not coordinates: click with those of the screenshot).")]}
    if name == "ui_tree":
        if "tree" not in (dev.get("caps") or []) and "tree" not in ((h.conn(did).hello if h.conn(did) else {}).get("caps") or []):
            raise Refused(f"{dev['name']} has no element tree (computers: not available yet): use screenshot.")
        r = await h.request(did, {"t": "tree", "sw": sw, "sh": sh})
        nodes = r.get("nodes") if isinstance(r.get("nodes"), list) else []
        return {"content": [_text(f"{len(nodes)} elements of {dev['name']} (frames x,y,w,h in pixels of the latest "
                                  f"screenshot, {sw}x{sh}):\n" + _tree_text(nodes))]}
    if name == "screen":
        return await _switch(did, dev, int(_num(args, "screen")))
    if name == "apps":
        r = await h.request(did, {"t": "apps"})
        apps = [a for a in r.get("apps") or [] if isinstance(a, dict)][:400]
        lines = [f"- {store._text(a.get('name'), 80)} ({store._text(a.get('id'), 120)})" for a in apps]
        return {"content": [_text(f"{len(apps)} apps on {dev['name']}:\n" + "\n".join(lines))]}
    if name == "open_app":
        want = str(args.get("name") or "").strip()
        if not want:
            raise Refused("name: the app to open")
        r = await h.request(did, {"t": "apps"})
        apps = [a for a in r.get("apps") or [] if isinstance(a, dict)]
        cf = want.casefold()
        app = next((a for a in apps if str(a.get("id")) == want), None) or \
            next((a for a in apps if str(a.get("name") or "").casefold() == cf), None) or \
            next((a for a in apps if cf in str(a.get("name") or "").casefold()), None)
        if app is None:
            raise Refused(f"No app {want[:60]!r} on {dev['name']}: see `apps`.")
        await h.request(did, {"t": "open", "app": app.get("id")})
        return await _after(did, dev, f"Opened {store._text(app.get('name'), 80)}. ")
    if name in ("tap_element", "set_text"):
        node = str(args.get("element") or "").strip()[:200]
        if not node:
            raise Refused("element: an id from ui_tree")
        msg: dict = {"t": "tap_node" if name == "tap_element" else "set_text", "node": node}
        if name == "set_text":
            text = str(args.get("text") if args.get("text") is not None else "")
            if len(text) > MAX_TEXT:
                raise Refused(f"text: at most {MAX_TEXT} characters at once")
            msg["text"] = text
        await h.request(did, msg)
        return await _after(did, dev, "Done. ")
    # pointer and keyboard
    inp: dict = {"t": "input", "sw": sw, "sh": sh}
    if name == "click":
        x, y = _point(args, sw, sh)
        button = str(args.get("button") or "left")
        if button not in ("left", "right", "middle"):
            raise Refused("button: left, right or middle")
        inp.update(a="click", x=x, y=y, button=button, double=bool(args.get("double")))
    elif name == "long_press":
        x, y = _point(args, sw, sh)
        inp.update(a="long_press", x=x, y=y, ms=int(min(5000, max(100, _num(args, "ms", 800)))))
    elif name == "move":
        x, y = _point(args, sw, sh)
        inp.update(a="move", x=x, y=y)
    elif name == "drag":
        x, y = _point(args, sw, sh, "x1", "y1")
        x2, y2 = _point(args, sw, sh, "x2", "y2")
        inp.update(a="drag", x=x, y=y, x2=x2, y2=y2, ms=int(min(5000, max(50, _num(args, "ms", 300)))))
    elif name == "scroll":
        x, y = _point(args, sw, sh)
        inp.update(a="scroll", x=x, y=y, dx=_num(args, "dx", 0), dy=_num(args, "dy", 0))
    elif name == "type":
        text = str(args.get("text") if args.get("text") is not None else "")
        if not text:
            raise Refused("text: what to type")
        if len(text) > MAX_TEXT:
            raise Refused(f"text: at most {MAX_TEXT} characters at once")
        inp.update(a="type", text=text)
    elif name == "key":
        keys = str(args.get("keys") or "").strip().lower()[:60]
        if not keys:
            raise Refused("keys: a key or a shortcut")
        inp.update(a="key", keys=keys)
    await h.request(did, inp)
    return await _after(did, dev, "Done. ")


async def _switch(did: str, dev: dict, n: int) -> dict:
    """Show another screen of the device (the choice of Settings -> Devices too), then a picture of it."""
    h = hub()
    hello = h.conn(did).hello if h.conn(did) else {}
    screens = hello.get("screens") or []
    if len(screens) < 2:
        raise Refused(f"{dev['name']} has a single screen.")
    nums = [x["i"] for x in screens]
    if n != -1 and n not in nums:
        raise Refused(f"{dev['name']} has no screen {n}: " + ", ".join(f"{x['i']} {x['name']}" for x in screens) + ".")
    want = n if n >= 0 else next((x["i"] for x in screens if x.get("main")), nums[0])
    await asyncio.to_thread(store.update, did, display=n)
    await h.access_changed(did)
    end = time.monotonic() + SWITCH_WAIT_S                # the app says hello again on the new screen
    while time.monotonic() < end and (h.conn(did).hello if h.conn(did) else {}).get("display") != want:
        await asyncio.sleep(0.05)
    h.shots.pop(did, None)                                # the old picture's pixels are no longer coordinates
    name = next(x["name"] for x in screens if x["i"] == want)
    return {"content": await _picture(did, dev, f"Now on screen {want} ({name}). ")}


async def _after(did: str, dev: dict, said: str) -> dict:
    await asyncio.sleep(SETTLE_S)
    try:
        return {"content": await _picture(did, dev, said + "Now: ")}
    except (Offline, DeviceError, asyncio.TimeoutError):
        return {"content": [_text(said + "(no new screenshot: take one)")]}
