"""Password hashing, session cookie, login throttle, CSRF and the auth dependency.

- Password: scrypt (stdlib), stored as "scrypt$n$r$p$salt_hex$hash_hex" in secrets.json.
- Cookie `mx_session` = "<issued_at>.<nonce>.<browser id>.<hmac>" signed with secrets.cookie_key (older cookies,
  "<issued_at>.<nonce>.<hmac>" and "<issued_at>.<hmac>", stay valid: see below). Changing the password rotates the key
  (every existing cookie dies). Sign out revokes that one cookie server-side: its id (sha256 of the
  value) goes to secrets.revoked_sessions {id: expires_at} until it would have expired anyway; past
  REVOKED_MAX entries the list is replaced by secrets.sessions_not_before = now, in whole seconds (every cookie issued
  before is refused - all browsers signed out, never a cookie that comes back to life; the revocations of cookies
  issued in that same second stay listed, and a cookie issued right after still works).
- Signed-in browsers: `<state>/signins.json` {"devices": {id: {created, seen, ua, ip}}, "legacy", "since"}. A cookie
  with an id is only valid while its id is listed (disconnecting a browser removes it; a lost file signs everybody
  out, never back in). Cookies without an id (made before this list existed) stay valid until "disconnect all the
  others" (secrets.legacy_sessions_off) or a password change. `seen` / `ip` are refreshed at most every SEEN_EVERY_S.
- Throttle: per client key (socket peer), failures in a 15-min window -> delay 1,2,4,8 s,
  then 429 for the rest of the window, checked BEFORE the password (no scrypt, even a correct
  password is refused). Every attempt counts as a failure up front (parallel requests count too),
  a success clears its client. Global cap: past GLOBAL_FAIL_MAX failures from all clients in the
  window, at most one password check every GLOBAL_GAP_S for clients that already failed, and one more every
  GLOBAL_GAP_S for clients with no failure yet (others get 429 and retry): distributed guessing slows to a crawl,
  and clients that keep failing never take the slot of a first try. A browser trusted by two-step sign-in and a
  client key that signed in within GOOD_KEEP_S (in memory) skip the global cap: the owner still gets in.
- CSRF: non-GET requests must carry `X-Maxxing: 1` (a header a cross-site form cannot set).
- Streams (SSE) re-check their cookie (`StreamAuth`) before each batch they send: a sign-out, a password change,
  `sessions_not_before`, a disconnected browser or the cookie's expiry closes a stream already open. WebSockets
  (terminal, live views) do the same through `hold_socket`.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import ipaddress
import hmac
import os
import secrets
import threading
import time

from fastapi import HTTPException, Request

from . import config

COOKIE = "mx_session"
COOKIE_MAX_AGE = 30 * 24 * 3600
MIN_PASSWORD = 12                  # a new password (setup, change, CLI); existing shorter ones still sign in
FAIL_WINDOW = 900
FAIL_MAX = 8
GLOBAL_FAIL_MAX = 30
GLOBAL_GAP_S = 5.0
REVOKED_MAX = 500                  # revoked cookie ids kept; past it: sessions_not_before = now
KEEP_S = 3600                      # failures kept this long (failures_last_hour), then pruned
GOOD_KEEP_S = 30 * 24 * 3600       # a client key that signed in skips the global cap this long
GOOD_MAX = 64
SIGNINS_MAX = 50                   # signed-in browsers listed; past it the one seen longest ago is signed out
SEEN_EVERY_S = 60                  # a browser's last-seen time is written at most this often
GUARD_S = 5.0                      # an open WebSocket re-checks its cookie this often
FAILS_KEYS_MAX = 10_000             # client keys with failures kept; past it the one that failed longest ago goes

_fails: dict[str, list[float]] = {}   # ordered by last failure: a failure moves its key to the end
_fails_lock = threading.Lock()
_last_global = 0.0
_last_fresh = 0.0
_good: dict[str, float] = {}       # client key -> last successful sign-in
_wide: dict[str, float] = {}       # IPv6 /48 -> its last failure (a "fresh" client is one whose /48 has none)
WIDE_MAX = 5000


# ---- password ------------------------------------------------------------------------------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 14, 8, 1
    h = hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except Exception:
        return False


def password_is_set() -> bool:
    return bool(config.get_secret("password_hash"))


def set_password(pw: str) -> None:
    config.set_secrets({                                      # one write: never a new password with old cookies
        "password_hash": hash_password(pw),
        "cookie_key": secrets.token_hex(32),                  # invalidates every session
        "revoked_sessions": None,                             # old revocations are moot with the new key
        "device_key": None,                                   # two-step sign-in: every browser asks again
        "legacy_sessions_off": None,
    })
    with config._lock, contextlib.suppress(OSError):          # noqa: SLF001 - the old ids are dead with the old key anyway
        _write_signins({"devices": {}, "legacy": False, "since": int(time.time())})
    _seen_at.clear()
    from . import twofactor
    twofactor.revoke_all()                                    # and no request approved before can be collected


# ---- setup token ---------------------------------------------------------------------------
SETUP_TOKEN_TTL = 3600          # the first sign-in link works for 1 h (`maxxing setup-link` gives a fresh one)


def _setup_token_fresh() -> bool:
    try:
        at = float(config.get_secret("setup_token_at") or 0)
    except (TypeError, ValueError):
        at = 0
    return 0 <= time.time() - at < SETUP_TOKEN_TTL


def ensure_setup_token() -> str:
    """The current setup link token; a new one when there is none or it expired."""
    with config._lock:                    # noqa: SLF001 - two callers at once (setup-link, doctor) share one token
        tok = config.get_secret("setup_token")
        if not tok or not _setup_token_fresh():
            tok = secrets.token_urlsafe(24)
            config.set_secrets({"setup_token": tok, "setup_token_at": int(time.time())})
    return tok


def clear_setup_token() -> None:
    config.set_secrets({"setup_token": None, "setup_token_at": None})


def check_setup_token(tok: str) -> bool:
    cur = config.get_secret("setup_token")
    # bytes: a non-ASCII token is a 403, not a 500 (compare_digest refuses non-ASCII str); surrogatepass: a lone
    # surrogate from the JSON body ("\ud800") cannot be encoded otherwise
    return bool(cur) and _setup_token_fresh() and hmac.compare_digest(
        str(cur).encode(), (tok or "").encode("utf-8", "surrogatepass"))


# ---- cookie --------------------------------------------------------------------------------
def secret_key(name: str) -> bytes:
    """A signing key of secrets.json (cookie_key, device_key), made on first use."""
    k = config.get_secret(name)
    if not k:
        with config._lock:                    # noqa: SLF001 - re-read: a key made meanwhile must not be replaced
            k = config.get_secret(name)
            if not k:
                k = secrets.token_hex(32)
                config.set_secret(name, k)
    return str(k).encode()                    # str(): a hand-edited secrets.json (a number) is not a 500


def _cookie_key() -> bytes:
    return secret_key("cookie_key")


def make_cookie(ua: str = "", ip: str = "") -> str:
    """A new sign-in cookie, listed as a signed-in browser (`ua`, `ip`: what the list shows)."""
    now = int(time.time())
    did = secrets.token_hex(8)

    def add(data: dict) -> None:
        devs = data["devices"]
        for k in [k for k, d in devs.items() if _num(d, "created") + COOKIE_MAX_AGE <= now]:
            del devs[k]
        while len(devs) >= SIGNINS_MAX:
            del devs[min(devs, key=lambda k: _num(devs[k], "seen"))]
        devs[did] = {"created": now, "seen": now, "ua": (ua or "")[:200], "ip": (ip or "")[:64]}
    _edit_signins(add)
    _seen_at[did] = time.time()
    body = f"{now}.{secrets.token_hex(8)}.{did}"
    sig = hmac.new(_cookie_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


# ---- signed-in browsers --------------------------------------------------------------------
_signins_cache: dict = {"key": None, "data": None}
_seen_at: dict[str, float] = {}       # browser id -> last time its `seen` was written by this process


def signins_path():
    return config.STATE / "signins.json"


def _num(d, key: str) -> float:
    v = d.get(key) if isinstance(d, dict) else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _signins() -> dict:
    """signins.json, read-only (kept while the file is unchanged). No file yet: an installation from before the list."""
    p = signins_path()
    try:
        st = os.stat(p)
        key: tuple | None = (str(p), st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is not None and _signins_cache["key"] == key:
        return _signins_cache["data"]
    data = config.read_json(p, None) if key is not None else None
    if not isinstance(data, dict) or not isinstance(data.get("devices"), dict):
        data = {"devices": {}, "legacy": key is None, "since": int(time.time())}
    data["devices"] = {k: v for k, v in data["devices"].items() if isinstance(k, str) and isinstance(v, dict)}
    _signins_cache.update(key=key, data=data)
    return data


def _write_signins(data: dict) -> None:
    try:
        config._atomic_write(signins_path(), data, 0o600)     # noqa: SLF001
    finally:
        _signins_cache.update(key=None, data=None)


def _edit_signins(change) -> None:
    with config._lock:                                        # noqa: SLF001 - the server and `maxxing` commands
        _signins_cache.update(key=None, data=None)
        data = copy.deepcopy(_signins())
        change(data)
        _write_signins(data)


def device_id(value: str | None) -> str | None:
    """The signed-in browser id a cookie carries; None for a cookie from before the list (signature not checked)."""
    parts = (value or "").split(".")
    return parts[2] if len(parts) == 4 else None


def _seen_due(value: str | None) -> bool:
    did = device_id(value)
    return bool(did) and time.time() - _seen_at.get(did, 0.0) >= SEEN_EVERY_S


def _touch(value: str, request: Request) -> None:
    """Record that a signed-in browser was just seen (a file write: off the event loop)."""
    did = device_id(value)
    now = time.time()
    if not did or now - _seen_at.get(did, 0.0) < SEEN_EVERY_S:
        return
    if len(_seen_at) > 4 * SIGNINS_MAX:
        _seen_at.clear()
    _seen_at[did] = now
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")[:200]

    def seen(data: dict) -> None:
        d = data["devices"].get(did)
        if d is not None:
            d.update(seen=int(now), ip=ip[:64], ua=ua)
    try:
        _edit_signins(seen)
    except OSError:
        pass


def signins(current: str | None = None) -> dict:
    """What the settings show: {"devices": [{id, ua, ip, created, seen, current}], "legacy", "legacy_current"}.
    `legacy`: browsers signed in before the list existed may still be signed in (they have no entry of their own)."""
    data = _signins()
    now = time.time()
    mine = device_id(current)
    devs = [{"id": k, "ua": str(d.get("ua") or ""), "ip": str(d.get("ip") or ""), "created": int(_num(d, "created")),
             "seen": int(_num(d, "seen")), "current": k == mine}
            for k, d in data["devices"].items() if _num(d, "created") + COOKIE_MAX_AGE > now]
    devs.sort(key=lambda d: (not d["current"], -d["seen"]))
    legacy = bool(data.get("legacy")) and now - _num(data, "since") < COOKIE_MAX_AGE \
        and not config.load_secrets().get("legacy_sessions_off")
    return {"devices": devs, "legacy": legacy or (mine is None and bool(current)),
            "legacy_current": mine is None and bool(current)}


def end_signin(did: str) -> bool:
    """Disconnect one browser: its cookie is refused from now on."""
    found = []

    def drop(data: dict) -> None:
        if data["devices"].pop(did, None) is not None:
            found.append(did)
    _edit_signins(drop)
    _seen_at.pop(did, None)
    recheck_sockets()
    return bool(found)


def end_other_signins(keep: str | None) -> None:
    """Disconnect every browser but `keep` (an id), the ones from before the list included."""
    def only(data: dict) -> None:
        data["devices"] = {k: v for k, v in data["devices"].items() if k == keep}
        data["legacy"] = False
    with config._lock:                                        # noqa: SLF001
        config.set_secret("legacy_sessions_off", True)
        _edit_signins(only)
    recheck_sockets()


def _issued_at(value: str | None, key: bytes | None = None) -> int | None:
    """Issue time of a correctly signed cookie, None if forged/malformed (expiry not checked)."""
    if not value or "." not in value:
        return None
    body, sig = value.rsplit(".", 1)
    good = hmac.new(key or _cookie_key(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig.encode(), good.encode()):   # bytes: a non-ASCII cookie is refused, not a 500
        return None
    try:
        return int(body.split(".", 1)[0])
    except ValueError:
        return None


def session_id(cookie: str) -> str:
    """Public id of a sign-in cookie (what a revocation records): links handed to that session carry it."""
    return hashlib.sha256(cookie.encode()).hexdigest()[:32]


def session_revoked(sid: str) -> bool:
    revoked = config.load_secrets().get("revoked_sessions")
    return isinstance(revoked, dict) and sid in revoked


def cookie_valid(value: str | None) -> bool:
    if not value:
        return False
    s = config.load_secrets()                      # one read of secrets.json per request
    if not s.get("password_hash"):
        return False
    ts = _issued_at(value, str(s["cookie_key"]).encode() if s.get("cookie_key") else None)
    if ts is None or time.time() - ts >= COOKIE_MAX_AGE:
        return False
    try:
        if ts < float(s.get("sessions_not_before") or 0):
            return False
    except (TypeError, ValueError):
        pass
    revoked = s.get("revoked_sessions")
    if isinstance(revoked, dict) and session_id(value) in revoked:
        return False
    did = device_id(value)
    if did is None:
        return not s.get("legacy_sessions_off")
    return did in _signins()["devices"]


def revoke_cookie(value: str | None) -> bool:
    """Sign-out: this cookie is refused from now on (other browsers stay signed in)."""
    ts = _issued_at(value)
    if ts is None:
        return False
    now = time.time()
    with config._lock:
        cur = config.load_secrets().get("revoked_sessions")
        revoked = {k: v for k, v in (cur.items() if isinstance(cur, dict) else ())
                   if isinstance(v, (int, float)) and v > now}
        revoked[session_id(value)] = ts + COOKIE_MAX_AGE
        if len(revoked) > REVOKED_MAX:          # never drop a revocation: refuse every older cookie instead
            # cookie times are whole seconds: one issued later in this same second must still work, so the cutoff is
            # this second and the revocations of cookies issued in it are kept
            nb = int(now)
            revoked = {k: v for k, v in revoked.items() if v - COOKIE_MAX_AGE >= nb}
            if len(revoked) > REVOKED_MAX:      # that many sign-outs in one second: the list stays bounded
                nb, revoked = nb + 1, {}
            config.set_secrets({"sessions_not_before": nb, "revoked_sessions": revoked or None})
        else:
            config.set_secret("revoked_sessions", revoked or None)
        did = device_id(value)
        if did and did in _signins()["devices"]:
            _edit_signins(lambda data: data["devices"].pop(did, None))
    recheck_sockets()
    return True


def is_https(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme).startswith("https")


def set_cookie(response, request: Request) -> str:
    value = make_cookie(request.headers.get("user-agent", ""), request.client.host if request.client else "")
    response.set_cookie(COOKIE, value, max_age=COOKIE_MAX_AGE, httponly=True,
                        samesite="strict", secure=is_https(request), path="/")


    return value


def loopback(conn) -> bool:
    """A client of this machine reached directly (Caddy adds X-Forwarded-For: anything through it is not local).
    `conn`: a Request or a WebSocket. For the routes only this server's own processes call (a turn's MCP servers)."""
    host = conn.client.host if conn.client else ""
    local = ("127.0.0.1", "::1", config.local_host().strip("[]"))   # + the bind address (Tailscale mode)
    return host in local and "x-forwarded-for" not in conn.headers and "forwarded" not in conn.headers


# ---- throttle ------------------------------------------------------------------------------
def client_key(request: Request) -> str:
    """Who is asking, for the throttles: an IPv4 address, or the /64 of an IPv6 one (one connection usually owns a
    whole /64: counting each address apart would make the per-client limits endless)."""
    host = request.client.host if request.client else "?"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        if ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _prune(now: float) -> None:
    """Drop the clients whose last failure is old, and the oldest past FAILS_KEYS_MAX (caller holds the lock):
    `_fails` cannot grow for good. They are at the front: an attempt never goes through the whole table."""
    while _fails:
        k = next(iter(_fails))
        lst = _fails[k]
        if lst and now - lst[-1] < KEEP_S and len(_fails) <= FAILS_KEYS_MAX:
            break
        del _fails[k]


def _recent_all(now: float) -> int:
    """Failures in the window, all clients: from the end (latest failures) to the first client with none."""
    n = 0
    for lst in reversed(_fails.values()):
        if not lst or now - lst[-1] >= FAIL_WINDOW:
            break
        n += _recent(lst, now)
    return n


def _recent(lst: list[float], now: float) -> int:
    return sum(1 for t in lst if now - t < FAIL_WINDOW)


def _wide_key(key: str) -> str | None:
    """The /48 of a client key that is an IPv6 /64 (whatever its prefix, `pw:`...), else None."""
    for net in (key, key.partition(":")[2]):
        if net.endswith("/64"):
            try:
                return str(ipaddress.ip_network(net).supernet(new_prefix=48))
            except ValueError:
                continue
    return None


def begin_attempt(key: str, trusted: bool = False) -> tuple[str | None, int]:
    """Before checking a password -> (refusal, failures_in_window). refusal: "client" (this client
    is over FAIL_MAX), "global" (global cap reached, wait GLOBAL_GAP_S) or None: go ahead - the
    attempt is already recorded as a failure, `end_attempt(key, True)` clears it. `trusted`: the request holds a
    trusted-browser cookie (skips the global cap, never the per-client one)."""
    global _last_global, _last_fresh
    now = time.time()
    with _fails_lock:
        _prune(now)
        n = _recent(_fails.get(key, []), now)
        if n >= FAIL_MAX:
            return "client", n
        wide = _wide_key(key)
        known = trusted or now - _good.get(key, 0.0) < GOOD_KEEP_S
        if not known and _recent_all(now) >= GLOBAL_FAIL_MAX:
            # two slots: clients that keep failing cannot take the one of a client trying for the first time. A new
            # /64 of a /48 that failed is not a first time: one IPv6 block cannot hold that slot with new addresses
            fresh = n == 0 and now - _wide.get(wide or "", 0.0) >= FAIL_WINDOW
            last = _last_fresh if fresh else _last_global
            if now - last < GLOBAL_GAP_S:
                return "global", n
            if fresh:
                _last_fresh = now
            else:
                _last_global = now
        if wide:
            if len(_wide) >= WIDE_MAX:
                for k in [k for k, t in _wide.items() if now - t >= FAIL_WINDOW] or list(_wide)[:WIDE_MAX // 2]:
                    del _wide[k]
            _wide[wide] = now
        lst = [t for t in _fails.pop(key, []) if now - t < KEEP_S]
        lst.append(now)
        _fails[key] = lst
        _prune(now)
        return None, n + 1


def end_attempt(key: str, ok: bool) -> float:
    """After the check -> delay (s) to wait before answering a wrong password."""
    if ok:
        with _fails_lock:
            _fails.pop(key, None)
            _wide.pop(_wide_key(key) or "", None)
            _good[key] = time.time()
            if len(_good) > GOOD_MAX:
                del _good[min(_good, key=_good.__getitem__)]
        return 0.0
    with _fails_lock:
        n = _recent(_fails.get(key, []), time.time())
    return float(min(2 ** (max(n, 1) - 1), 8))


def throttle(key: str, ok: bool) -> tuple[bool, float, int]:
    """Record a whole attempt -> (blocked, delay_s, failures_in_window) (CLI / tests)."""
    refusal, n = begin_attempt(key)
    if refusal:
        return True, 0.0, n
    return False, end_attempt(key, ok), (0 if ok else n)


def failures_last_hour() -> int:
    now = time.time()
    with _fails_lock:
        return sum(1 for lst in _fails.values() for t in lst if now - t < 3600)


class StreamAuth:
    """The cookie an SSE stream was opened with, re-checked while it runs. `ok()` costs one stat of secrets.json
    while that file is unchanged (every sign-out, password change or not_before rewrites it: atomic rename), and a
    full `cookie_valid` when it changed, every RECHECK_S, and past the cookie's expiry."""

    RECHECK_S = 15.0

    def __init__(self, cookie: str | None):
        self.cookie = cookie
        self._ident: tuple | None = None
        self._at = 0.0
        self._expires = 0.0

    @staticmethod
    def _secrets_ident() -> tuple | None:
        try:
            st = os.stat(config.sealed_path() if config.secrets_sealed() else config.secrets_path())
        except OSError:
            return None
        try:
            ls = os.stat(signins_path())
            return st.st_ino, st.st_mtime_ns, st.st_size, ls.st_ino, ls.st_mtime_ns, ls.st_size
        except OSError:
            return st.st_ino, st.st_mtime_ns, st.st_size, 0, 0, 0

    def ok(self) -> bool:
        ident = self._secrets_ident()
        now = time.monotonic()
        if ident is not None and ident == self._ident and now - self._at < self.RECHECK_S \
                and time.time() < self._expires:
            return True
        if not cookie_valid(self.cookie):
            self._ident = None
            return False
        self._ident, self._at = ident, now
        self._expires = (_issued_at(self.cookie) or 0) + COOKIE_MAX_AGE
        return True


# ---- open WebSockets -----------------------------------------------------------------------
_guards: set = set()


class _Guard:
    def __init__(self, cookie: str | None):
        self.auth = StreamAuth(cookie)
        self.wake = asyncio.Event()
        self.loop = asyncio.get_running_loop()


def hold_socket(ws, code: int = 4401) -> asyncio.Task:
    """Closes an accepted WebSocket when the cookie it was opened with stops being valid: checked every GUARD_S (a
    change made by a `maxxing` command) and at once after a sign-out, a password change or a disconnection made by
    this process. Cancel the task when the socket ends."""
    g = _Guard(ws.cookies.get(COOKIE))

    async def run() -> None:
        _guards.add(g)
        try:
            while True:
                g.wake.clear()
                if not g.auth.ok():
                    break
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(g.wake.wait(), GUARD_S)
            with contextlib.suppress(Exception):
                await ws.close(code=code)
        finally:
            _guards.discard(g)
    return asyncio.create_task(run())


def recheck_sockets() -> None:
    """Every open WebSocket checks its cookie now (any thread)."""
    for g in list(_guards):
        with contextlib.suppress(RuntimeError):
            g.loop.call_soon_threadsafe(g.wake.set)


def move_sockets(old: str | None, new: str) -> None:
    """The WebSockets opened with cookie `old` go on with `new` (the browser that changed the password)."""
    for g in list(_guards):
        if old and g.auth.cookie == old:
            g.auth = StreamAuth(new)


# ---- dependencies --------------------------------------------------------------------------
def is_authenticated(request: Request) -> bool:
    return cookie_valid(request.cookies.get(COOKIE))


async def require_auth(request: Request) -> None:
    """Router dependency: authenticated + CSRF header on mutating methods."""
    if not is_authenticated(request):
        raise HTTPException(401, detail={"error": "auth_required", "message": "Sign in required"})
    value = request.cookies.get(COOKIE)
    if _seen_due(value):
        await asyncio.to_thread(_touch, value, request)
    csrf_only(request)


def csrf_only(request: Request) -> None:
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-maxxing") != "1":
        raise HTTPException(403, detail={"error": "csrf", "message": "Missing X-Maxxing header"})
