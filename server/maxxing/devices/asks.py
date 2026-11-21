"""`ask_human` on a device: Claude needs the person (a code sent by SMS, a password, a captcha, a choice).

The tool call waits here (server side, the turn's HTTP call held) until the person hands the device back with a word
("done"), skips, the wait ends (ASK_WAIT_S) or the turn stops. Announced with a card in the session (GET
/api/devices/asks?session=), a Notifications event (Open / Skip, Telegram too) and a line in an agent's thread.
Requests live in memory: a server restart ends the waiting call (Claude gets an error and may ask again).
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time

log = logging.getLogger("maxxing.devices")

ASK_WAIT_S = 600.0
DONE_TEXT = {"done": "Done by you", "skip": "Skipped", "timeout": "No answer in time", "expired": "The run stopped"}

_asks: dict[str, dict] = {}
_futs: dict[str, asyncio.Future] = {}


class AskError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _clean(text: str) -> str:
    """No lone surrogate or NUL: the request is rendered as JSON for 10 minutes."""
    return str(text).encode("utf-8", "replace").decode("utf-8").replace("\x00", "")


def public(d: dict) -> dict:
    return {k: d.get(k) for k in ("id", "session", "owner", "device", "device_name", "message", "at", "expires",
                                  "status", "note", "decided_at")}


def pending(session: str | None = None, device: str | None = None) -> list[dict]:
    return [public(d) for d in sorted(_asks.values(), key=lambda d: d["at"]) if d["status"] == "pending"
            and (session is None or d["session"] == session) and (device is None or d["device"] == device)]


def waiting(sid: str) -> int:
    return sum(1 for d in _asks.values() if d["status"] == "pending" and d["session"] == sid)


def get(rid: str) -> dict | None:
    d = _asks.get(rid)
    return public(d) if d else None


async def ask(session: str, owner: str, dev: dict, message: str, alive=None) -> dict:
    """Announce the request and wait for its answer -> the request as decided. `alive()`: is the turn still there
    (checked every 2 s; gone -> "expired")."""
    rid = secrets.token_hex(8)
    now = time.time()
    d = {"id": rid, "session": session, "owner": owner, "device": dev["id"], "device_name": dev.get("name") or "",
         "message": _clean(message or "Take over the device")[:300], "at": now, "expires": now + ASK_WAIT_S,
         "status": "pending", "note": ""}
    fut = asyncio.get_running_loop().create_future()
    _asks[rid], _futs[rid] = d, fut
    _prune()
    try:
        await asyncio.to_thread(_announce, d)
        while not fut.done():
            left = d["expires"] - time.time()
            if left <= 0:
                _finish(d, "timeout")
                break
            try:
                await asyncio.wait_for(asyncio.shield(fut), min(2.0, left))
            except asyncio.TimeoutError:
                if alive is not None and not await alive():
                    _finish(d, "expired")
    except BaseException:                          # cancelled, or alive() / the announcement failed: never left pending
        _finish(d, "expired")
        raise
    finally:
        _futs.pop(rid, None)
    return public(d)


def _finish(d: dict, status: str, note: str = "") -> None:
    if d["status"] != "pending":
        return
    d.update(status=status, note=_clean(note or "")[:500], decided_at=time.time())
    f = _futs.get(d["id"])
    if f is not None and not f.done():
        f.set_result(status)
    try:
        _resolved(d)
    except Exception:  # noqa: BLE001
        log.exception("closing a device request failed")
    from .. import bus
    bus.invalidate("devices", "sessions", "agents")


def decide(rid: str, action: str, note: str = "") -> dict:
    d = _asks.get(rid or "")
    if d is None:
        raise AskError(404, "not_found", "No such request")
    if action not in ("done", "skip"):
        raise AskError(400, "bad_action", "done or skip")
    if d["status"] != "pending":
        raise AskError(409, "decided", "This request is already answered")
    _finish(d, action, note)
    return public(d)


def decide_device(device_id: str, action: str, note: str = "") -> int:
    """The person handed a device back (live view): every request waiting on it gets the answer."""
    n = 0
    for d in list(_asks.values()):
        if d["device"] == device_id and d["status"] == "pending":
            _finish(d, action, note)
            n += 1
    return n


def _prune() -> None:
    now = time.time()
    for rid, d in list(_asks.items()):
        if d["status"] != "pending" and now - float(d.get("decided_at") or now) > 3600:
            _asks.pop(rid, None)


def feed_action(rid: str, action: str, by: str, ev: dict) -> None:
    """A button of the request's Notifications event (web or Telegram): skip. "open" only opens the page."""
    if action != "skip":
        return
    d = _asks.get(rid)
    if d is None or d["status"] != "pending":
        from .. import feed
        feed.update(ev["id"], resolve=True, resolution="The run stopped")
        return
    loop = _loop_of(rid)
    if loop is not None:
        loop.call_soon_threadsafe(_finish, d, "skip", "")
    else:
        _finish(d, "skip")


def _loop_of(rid: str):
    f = _futs.get(rid)
    try:
        return f.get_loop() if f is not None else None
    except Exception:  # noqa: BLE001
        return None


# ---- announcing ------------------------------------------------------------------------------------------------------
def _name(d: dict) -> str:
    owner = str(d.get("owner") or "")
    if owner.startswith("agent:"):
        path = owner.split(":", 1)[1]
        try:
            from .. import agents
            return agents.load(path).get("name") or path.rsplit("/", 1)[-1]
        except Exception:  # noqa: BLE001
            return path.rsplit("/", 1)[-1]
    try:
        from ..sessions import store
        m = store.read(str(d.get("session") or "")) if d.get("session") else None
        return (m or {}).get("title") or "A session"
    except Exception:  # noqa: BLE001
        return "A session"


def _announce(d: dict) -> None:
    agent = str(d.get("owner") or "")
    try:
        from .. import feed
        feed.post(f"{_name(d)} needs you on {d['device_name'] or 'a device'}", d["message"], "warning",
                  "agents" if agent.startswith("agent:") else "system", f"/settings/devices?watch={d['device']}",
                  dedupe=f"devask:{d['id']}", ref=f"devask:{d['id']}",
                  agent=agent.split(":", 1)[1] if agent.startswith("agent:") else None,
                  actions=[{"id": "open", "label": "Open the device", "style": "primary"},
                           {"id": "skip", "label": "Skip", "style": "default"}])
    except Exception:  # noqa: BLE001 - the feed is a nicety
        log.exception("feed event for a device request failed")
    _thread(d, f"Waiting for you on {d['device_name'] or 'a device'}: {d['message']}")


def _resolved(d: dict) -> None:
    st = d["status"]
    try:
        from .. import feed
        feed.resolve(f"devask:{d['id']}", DONE_TEXT.get(st, st), read=True if st in ("done", "skip") else None,
                     level="info" if st == "done" else "warning")
    except Exception:  # noqa: BLE001
        log.exception("feed event update for a device request failed")
    _thread(d, f"{d['device_name'] or 'Device'}: {DONE_TEXT.get(st, st).lower()}" + (f" ({d['note']})" if d.get("note") else ""))


def _thread(d: dict, text: str) -> None:
    owner = str(d.get("owner") or "")
    if not owner.startswith("agent:"):
        return
    try:
        from .. import agents
        path = owner.split(":", 1)[1]
        if agents.exists(path):
            agents.post(path, "note", text, session=d.get("session") or "", ask=d.get("id"))
    except Exception:  # noqa: BLE001
        log.exception("agent thread message for a device request failed")
