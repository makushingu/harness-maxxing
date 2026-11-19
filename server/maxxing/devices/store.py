"""The devices' state: `<state>/devices/devices.json` (0600) and `actions.jsonl` (the tools Claude used, last 500).

    {"devices": [{id, name, os, kind, arch, version, token_hash, created, last_seen, confirmed, mode, scope,
                  caps, screen, note, ip}],
     "invites": [{code_hash, os, created, expires}]}

Tokens and codes are kept hashed. A device that paired waits (`confirmed: false`) until the user accepts it - a code
seen by someone else (a screenshot of the command) cannot plug their computer in silently; unanswered for
CANDIDATE_TTL, it is dropped (its app is told to forget the server). Removing a device revokes its token at once.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .. import config
from . import ID_RE, MODES, OS_NAMES, OSES, DevicesError, clean_scope, home, kind_of

INVITE_TTL = 15 * 60
INVITE_KEEP = 24 * 3600              # an expired code still answers `expired` (not `bad_code`) for a day
CANDIDATE_TTL = 15 * 60
MAX_INVITES = 10
MAX_DEVICES = 30
MAX_ACTIONS = 500
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I: read on a phone, typed by hand
CODE_LEN = 8
NAME_MAX = 64

_lock = threading.RLock()            # every read-modify-write of devices.json (a hello racing a removal...)


def _path() -> Path:
    return home() / "devices.json"


def _hash(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def _text(v: Any, n: int) -> str:
    """str(v) that UTF-8 can write (a lone surrogate becomes "?"), without control characters, at most n long."""
    s = str(v if v is not None else "").encode("utf-8", "replace").decode()
    return "".join(c for c in s if c >= " " and c != "\x7f").strip()[:n]


def normalize_code(code: str) -> str:
    return "".join(c for c in str(code or "").upper() if c.isalnum())


def load() -> dict:
    d = config.read_json(_path(), {}) or {}
    if not isinstance(d, dict):
        d = {}
    d["devices"] = [x for x in d.get("devices") or [] if isinstance(x, dict) and ID_RE.match(str(x.get("id") or ""))]
    d["invites"] = [x for x in d.get("invites") or [] if isinstance(x, dict) and x.get("code_hash")]
    return d


def save(d: dict) -> None:
    config.write_json(_path(), d, mode=0o600)


def _prune(d: dict, now: float) -> list[str]:
    """Drop old invitations and devices never accepted in time -> ids dropped (their apps must be told)."""
    d["invites"] = [i for i in d["invites"] if now < float(i.get("expires") or 0) + INVITE_KEEP][-MAX_INVITES * 3:]
    gone = [x["id"] for x in d["devices"] if not x.get("confirmed") and now - float(x.get("created") or 0) > CANDIDATE_TTL]
    if gone:
        d["devices"] = [x for x in d["devices"] if x["id"] not in gone]
    return gone


def devices() -> list[dict]:
    with _lock:
        d = load()
        if _prune(d, time.time()):
            save(d)
        return d["devices"]


def get(device_id: str) -> dict | None:
    return next((x for x in devices() if x["id"] == device_id), None)


# ---- invitations and pairing ---------------------------------------------------------------------------------------
def new_invite(os_name: str = "") -> dict:
    """A one-time code for one device (15 min). -> {code, os, expires_at, expires_in}."""
    if os_name and os_name not in OSES:
        raise DevicesError(422, "invalid", f"os: one of {', '.join(OSES)}")
    with _lock:
        d = load()
        now = time.time()
        _prune(d, now)
        live = [i for i in d["invites"] if now < float(i.get("expires") or 0)]
        if len(live) >= MAX_INVITES:
            raise DevicesError(429, "too_many", "Too many codes waiting: use one or wait 15 minutes")
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        inv = {"code_hash": _hash(code), "os": os_name, "created": now, "expires": now + INVITE_TTL}
        d["invites"].append(inv)
        save(d)
        return {"code": code, "os": os_name, "expires_at": inv["expires"], "expires_in": INVITE_TTL}


def invite(code: str) -> dict:
    """The invitation of this code, still valid. DevicesError 400 bad_code / 410 expired."""
    c = normalize_code(code)
    if len(c) != CODE_LEN:
        raise DevicesError(400, "bad_code", "Unknown pairing code")
    h = _hash(c)
    for i in load()["invites"]:
        if hmac.compare_digest(h, str(i.get("code_hash") or "")):
            if time.time() > float(i.get("expires") or 0):
                raise DevicesError(410, "expired", "This code expired: add the device again in Harness Maxxing")
            if i.get("used"):
                raise DevicesError(410, "expired", "This code was already used: add the device again in Harness Maxxing")
            return i
    raise DevicesError(400, "bad_code", "Unknown pairing code")


def default_name(os_name: str) -> str:
    return {"android": "Android phone", "darwin": "Mac", "windows": "Windows PC", "linux": "Linux computer"}.get(
        os_name, "Device")


def pair(code: str, info: dict, ip: str = "") -> dict:
    """POST /api/devices/pair from the app: the code is used up, the device waits for the user's yes.
    -> {device_id, token}."""
    os_name = _text(info.get("os"), 16).lower()
    if os_name not in OSES:
        raise DevicesError(422, "invalid", f"os: one of {', '.join(OSES)}")
    with _lock:                                        # check and use up the code at once: one code, one device
        inv = invite(code)
        d = load()
        _prune(d, time.time())
        if len(d["devices"]) >= MAX_DEVICES:
            raise DevicesError(409, "too_many", f"At most {MAX_DEVICES} devices: remove one first")
        for i in d["invites"]:
            if i.get("code_hash") == inv["code_hash"]:
                i["used"] = True
        token = secrets.token_urlsafe(32)
        taken = {x["id"] for x in d["devices"]}
        did = "dev_" + secrets.token_hex(4)
        while did in taken:
            did = "dev_" + secrets.token_hex(4)
        now = time.time()
        dev = {"id": did, "name": _text(info.get("name"), NAME_MAX) or default_name(os_name), "os": os_name,
               "kind": kind_of(os_name), "arch": _text(info.get("arch"), 16), "version": _text(info.get("version"), 32),
               "caps": [_text(c, 16) for c in (info.get("caps") or [])[:10] if isinstance(c, str)],
               "token_hash": _hash(token), "created": now, "last_seen": now, "confirmed": False,
               "mode": "control", "scope": ["*"], "screen": None, "note": "", "ip": _text(ip, 64)}
        d["devices"].append(dev)
        save(d)
    from .. import bus
    bus.invalidate("devices")
    return {"device_id": did, "token": token}


def device_for_token(token: str) -> dict | None:
    if not token:
        return None
    h = _hash(token)
    for x in devices():
        if hmac.compare_digest(h, str(x.get("token_hash") or "")):
            return x
    return None


def confirm(device_id: str, ok: bool) -> bool:
    """The user's answer about a device waiting. Yes: it is in. No: it is dropped (its app forgets the server)."""
    with _lock:
        d = load()
        dev = next((x for x in d["devices"] if x["id"] == device_id and not x.get("confirmed")), None)
        if dev is None:
            return False
        if ok:
            dev["confirmed"] = True
            dev["confirmed_at"] = time.time()
        else:
            d["devices"] = [x for x in d["devices"] if x["id"] != device_id]
        save(d)
    from .. import bus
    bus.invalidate("devices")
    return True


def remove(device_id: str) -> bool:
    with _lock:
        d = load()
        n = len(d["devices"])
        d["devices"] = [x for x in d["devices"] if x["id"] != device_id]
        if len(d["devices"]) == n:
            return False
        save(d)
    from .. import bus
    bus.invalidate("devices")
    return True


def update(device_id: str, name: str | None = None, mode: str | None = None, scope: list | None = None,
           display: int | None = None) -> dict:
    """Rename it, change its rights (view / control), who may use it, or the screen used (index in the app's
    `screens`, -1 = its main screen)."""
    with _lock:
        d = load()
        dev = next((x for x in d["devices"] if x["id"] == device_id), None)
        if dev is None:
            raise DevicesError(404, "not_found", "No such device")
        if name is not None:
            n = _text(name, NAME_MAX)
            if not n:
                raise DevicesError(422, "invalid", "A device needs a name")
            dev["name"] = n
        if mode is not None:
            if mode not in MODES:
                raise DevicesError(422, "invalid", "mode: view or control")
            dev["mode"] = mode
        if scope is not None:
            dev["scope"] = clean_scope(scope, strict=True)
        if display is not None:
            if not -1 <= int(display) < 16:
                raise DevicesError(422, "invalid", "display: -1 (the main screen) or a screen number")
            dev["display"] = int(display)
        save(d)
    from .. import bus
    bus.invalidate("devices")
    return dev


def touch(device_id: str, **kw: Any) -> None:
    """What the app said about itself (hello): version, screen, capabilities, note; and when it was last seen."""
    with _lock:
        d = load()
        dev = next((x for x in d["devices"] if x["id"] == device_id), None)
        if dev is None:
            return
        dev.update(kw, last_seen=time.time())
        save(d)


def resolve(ref: str) -> dict | None:
    """A device by id, or by name (case-insensitive) - what the CLI and Claude may give."""
    all_ = devices()
    r = (ref or "").strip()
    return next((x for x in all_ if x["id"] == r), None) or next(
        (x for x in all_ if x["name"].casefold() == r.casefold()), None)


def public(dev: dict) -> dict:
    out = {k: dev.get(k) for k in ("id", "name", "os", "kind", "arch", "version", "created", "last_seen", "confirmed",
                                   "mode", "scope", "caps", "screen", "note", "ip", "display", "screens")}
    out["os_name"] = OS_NAMES.get(str(dev.get("os")), str(dev.get("os") or ""))
    return out


def invites_public() -> list[dict]:
    now = time.time()
    return [{"os": i.get("os") or "", "expires_at": i["expires"]} for i in load()["invites"]
            if now < float(i.get("expires") or 0) and not i.get("used")]


# ---- actions log ---------------------------------------------------------------------------------------------------
_alock = threading.Lock()
SAFE_ARGS = ("x", "y", "x2", "y2", "w", "h", "dx", "dy", "button", "double", "keys", "app", "name", "screen", "element", "ms", "s")


def log_action(device: str, tool: str, args: dict, ok: bool, ms: int, session: str = "", owner: str = "",
               error: str = "") -> None:
    """One line per tool call. Typed text is never kept (only its length)."""
    keep = {k: _text(v, 80) for k, v in (args or {}).items() if k in SAFE_ARGS}
    if "text" in (args or {}):
        keep["text"] = f"<{len(str(args['text']))} chars>"
    line = json.dumps({"at": time.time(), "device": device, "tool": tool, "args": keep, "ok": ok, "ms": ms,
                       "session": session, "owner": owner, **({"error": error[:200]} if error else {})},
                      ensure_ascii=False).encode("utf-8", "replace").decode("utf-8")      # a lone surrogate would fail the write
    p = home() / "actions.jsonl"
    try:
        with _alock:
            lines = p.read_text().split("\n")[-(MAX_ACTIONS):-1] if p.exists() else []
            fd, tmp = tempfile.mkstemp(prefix=".actions.", dir=p.parent)
            try:
                with os.fdopen(fd, "w") as f:
                    f.write("\n".join(lines + [line]) + "\n")
                os.chmod(tmp, 0o600)
                os.replace(tmp, p)
            finally:
                Path(tmp).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def actions(limit: int = 30, device: str | None = None) -> list[dict]:
    out: list[dict] = []
    try:
        # split on "\n" only: str.splitlines() also cuts on U+2028 and friends, which JSON keeps inside a string
        for ln in (home() / "actions.jsonl").read_text().split("\n"):
            try:
                a = json.loads(ln)
            except (ValueError, RecursionError):
                continue
            if isinstance(a, dict) and (device is None or a.get("device") == device):
                out.append(a)
    except OSError:
        pass
    return list(reversed(out[-limit:]))
