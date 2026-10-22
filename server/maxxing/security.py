"""Password hashing, session cookie, login throttle, CSRF and the auth dependency.

- Password: scrypt (stdlib), stored as "scrypt$n$r$p$salt_hex$hash_hex" in secrets.json.
- Cookie `mx_session` = "<issued_at>.<nonce>.<hmac>" signed with secrets.cookie_key (cookies from
  before 2.0.0a32 are "<issued_at>.<hmac>" and stay valid). Changing the password rotates the key
  (every existing cookie dies). Sign out revokes that one cookie server-side: its id (sha256 of the
  value) goes to secrets.revoked_sessions {id: expires_at} until it would have expired anyway; past
  REVOKED_MAX entries the list is replaced by secrets.sessions_not_before = now (every cookie issued
  before is refused - all browsers signed out, never a cookie that comes back to life).
- Throttle: per client key (socket peer), failures in a 15-min window -> delay 1,2,4,8 s,
  then 429 for the rest of the window, checked BEFORE the password (no scrypt, even a correct
  password is refused). Every attempt counts as a failure up front (parallel requests count too),
  a success clears its client. Global cap: past GLOBAL_FAIL_MAX failures from all clients in the
  window, at most one password check every GLOBAL_GAP_S for everyone (others get 429 and retry):
  distributed guessing slows to a crawl, the owner still gets in.
- CSRF: non-GET requests must carry `X-Maxxing: 1` (a header a cross-site form cannot set).
- Streams (SSE) re-check their cookie (`StreamAuth`) before each batch they send: a sign-out, a password change,
  `sessions_not_before` or the cookie's expiry closes a stream already open.
"""
from __future__ import annotations

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

_fails: dict[str, list[float]] = {}
_fails_lock = threading.Lock()
_last_global = 0.0


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
    })
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
    tok = config.get_secret("setup_token")
    if not tok or not _setup_token_fresh():
        tok = secrets.token_urlsafe(24)
        config.set_secret("setup_token", tok)
        config.set_secret("setup_token_at", int(time.time()))
    return tok


def clear_setup_token() -> None:
    config.set_secret("setup_token", None)
    config.set_secret("setup_token_at", None)


def setup_token_expires_at() -> float | None:
    try:
        at = float(config.get_secret("setup_token_at") or 0)
    except (TypeError, ValueError):
        return None
    return at + SETUP_TOKEN_TTL if at and config.get_secret("setup_token") else None


def check_setup_token(tok: str) -> bool:
    cur = config.get_secret("setup_token")
    # bytes: a non-ASCII token is a 403, not a 500 (compare_digest refuses non-ASCII str)
    return bool(cur) and _setup_token_fresh() and hmac.compare_digest(str(cur).encode(), (tok or "").encode())


# ---- cookie --------------------------------------------------------------------------------
def _cookie_key() -> bytes:
    k = config.get_secret("cookie_key")
    if not k:
        k = secrets.token_hex(32)
        config.set_secret("cookie_key", k)
    return str(k).encode()                    # str(): a hand-edited secrets.json (a number) is not a 500


def make_cookie() -> str:
    ts = str(int(time.time()))
    body = f"{ts}.{secrets.token_hex(8)}"
    sig = hmac.new(_cookie_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _cookie_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


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
    return _cookie_id(cookie)


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
    return not (isinstance(revoked, dict) and _cookie_id(value) in revoked)


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
        revoked[_cookie_id(value)] = ts + COOKIE_MAX_AGE
        if len(revoked) > REVOKED_MAX:          # never drop a revocation: refuse every older cookie instead
            config.set_secret("sessions_not_before", int(now) + 1)
            revoked = {}
        config.set_secret("revoked_sessions", revoked or None)
    return True


def set_cookie(response, request: Request) -> None:
    https = request.headers.get("x-forwarded-proto", request.url.scheme).startswith("https")
    response.set_cookie(COOKIE, make_cookie(), max_age=COOKIE_MAX_AGE, httponly=True,
                        samesite="strict", secure=https, path="/")


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
    """Drop old failures and empty clients (caller holds the lock): `_fails` cannot grow for good."""
    for k in list(_fails):
        lst = [t for t in _fails[k] if now - t < KEEP_S]
        if lst:
            _fails[k] = lst
        else:
            del _fails[k]


def _recent(lst: list[float], now: float) -> int:
    return sum(1 for t in lst if now - t < FAIL_WINDOW)


def begin_attempt(key: str) -> tuple[str | None, int]:
    """Before checking a password -> (refusal, failures_in_window). refusal: "client" (this client
    is over FAIL_MAX), "global" (global cap reached, wait GLOBAL_GAP_S) or None: go ahead - the
    attempt is already recorded as a failure, `end_attempt(key, True)` clears it."""
    global _last_global
    now = time.time()
    with _fails_lock:
        _prune(now)
        n = _recent(_fails.get(key, []), now)
        if n >= FAIL_MAX:
            return "client", n
        if sum(_recent(lst, now) for lst in _fails.values()) >= GLOBAL_FAIL_MAX:
            if now - _last_global < GLOBAL_GAP_S:
                return "global", n
            _last_global = now
        _fails.setdefault(key, []).append(now)
        return None, n + 1


def end_attempt(key: str, ok: bool) -> float:
    """After the check -> delay (s) to wait before answering a wrong password."""
    if ok:
        with _fails_lock:
            _fails.pop(key, None)
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
            st = os.stat(config.secrets_path())
        except OSError:
            return None
        return st.st_ino, st.st_mtime_ns, st.st_size

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


# ---- dependencies --------------------------------------------------------------------------
def is_authenticated(request: Request) -> bool:
    return cookie_valid(request.cookies.get(COOKIE))


async def require_auth(request: Request) -> None:
    """Router dependency: authenticated + CSRF header on mutating methods."""
    if not is_authenticated(request):
        raise HTTPException(401, detail={"error": "auth_required", "message": "Sign in required"})
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-maxxing") != "1":
        raise HTTPException(403, detail={"error": "csrf", "message": "Missing X-Maxxing header"})


def csrf_only(request: Request) -> None:
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-maxxing") != "1":
        raise HTTPException(403, detail={"error": "csrf", "message": "Missing X-Maxxing header"})
