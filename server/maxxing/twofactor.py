"""Two-step sign-in: Telegram (Settings -> Telegram, `maxxing 2fa`) and / or an authenticator app (TOTP).

- On: config `telegram.two_factor` = true, and only effective while a bot and a chat with its owner are linked
  (`enabled()`); forgetting Telegram turns it off.
- After a right password, a browser that is not trusted gets a challenge instead of the cookie: a message in the
  "Alerts" thread with the IP, the browser, a 6-digit code and Allow / Deny buttons. The sign-in page polls
  `POST /api/auth/two-factor {challenge}` until the owner presses a button, or sends the code typed by hand
  (when the buttons do not work: gateway stopped...). Challenges live in memory (one server process): TTL s,
  CODE_TRIES wrong codes kill one, NEW_MAX new ones per client per NEW_WINDOW, at most PENDING_MAX pending.
- Turning it on is itself a challenge (purpose "enable"): it is only stored once Telegram answered, so a broken
  bridge cannot lock the owner out.
- Trusted browser: cookie `mx_device` (path /api/auth, 30 days) signed with secrets.device_key. Rotating the key
  (password change, `maxxing 2fa off|forget-browsers`, the Settings button) forgets every trusted browser.
- Authenticator app (RFC 6238: SHA1, 6 digits, 30 s): secrets.totp = {"secret": Base32, "last": last step used,
  "pending": a secret being enrolled, "pending_at"}. It is on once a code of the pending secret was typed. A code is
  accepted for the current step and the ones right before / after, once (`last`). With it on, a sign-in challenge
  takes an app code in place of the Telegram one; without Telegram the challenge is silent (no message).
- Recovery codes: secrets.recovery_codes = SHA-256 of RECOVERY_N one-time codes, each usable once in place of any
  second-step code (Telegram only too). App and recovery codes go through `security.begin_attempt` ("2f:<client>").
- Way out without the UI: `maxxing 2fa off` over SSH.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import struct
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote

from . import config, security

log = logging.getLogger("maxxing.twofactor")

DEVICE_COOKIE = "mx_device"
DEVICE_MAX_AGE = 30 * 24 * 3600
TTL = 120
GRACE = 60                     # an approved challenge stays collectable this long after TTL
CODE_TRIES = 5
NEW_MAX = 5
NEW_WINDOW = 900
PENDING_MAX = 10
PENDING_PER_CLIENT = 3         # one client can hold this many waiting requests: a full list drops the oldest
BAD_MAX = 20                   # wrong codes accepted server-wide per BAD_WINDOW; then only the Allow button works
BAD_WINDOW = 3600
_CODE_RE = re.compile(r"[0-9]{6}")
TOTP_STEP = 30
TOTP_PENDING_S = 900           # an enrolment not confirmed within this is dropped
RECOVERY_N = 10
ISSUER = "Harness Maxxing"
_B32 = "abcdefghijklmnopqrstuvwxyz234567"
_DEVICE_RE = re.compile(r"[0-9]{1,12}\.[0-9a-f]{16}\.[0-9a-f]{64}")

WORDS = {
    "en": {"login": "🔐 <b>Sign-in request</b>", "enable": "🔐 <b>Turn on two-step sign-in</b>",
           "ip": "IP", "browser": "Browser", "code": "Code", "expires": "Expires in {m} min.",
           "hint_login": "Not you? Deny it, then change the password: the right one was typed.",
           "hint_enable": "Allow to finish. From now on every new browser will need your approval here.",
           "allow": "✅ Allow", "deny": "❌ Deny",
           "allowed": "✅ Allowed", "allowed_code": "✅ Allowed with the code", "denied": "❌ Denied",
           "gone": "This request expired.",
           "on": "🔐 Two-step sign-in is on. Without the web UI (Telegram down...): on the server, run maxxing 2fa off",
           "off_cli": "🔓 Two-step sign-in was turned off from the server (maxxing 2fa off).",
           "off_ui": "🔓 Two-step sign-in was turned off from the web UI. Not you? Change the password.",
           "unlinked": "🔓 Telegram is being unlinked from the web UI: two-step sign-in is off. Not you? Change the password."},
    "fr": {"login": "🔐 <b>Demande de connexion</b>", "enable": "🔐 <b>Activer la double authentification</b>",
           "ip": "IP", "browser": "Navigateur", "code": "Code", "expires": "Expire dans {m} min.",
           "hint_login": "Ce n'est pas toi ? Refuse, puis change le mot de passe : le bon a été tapé.",
           "hint_enable": "Autorise pour terminer. Ensuite, chaque nouveau navigateur aura besoin de ton accord ici.",
           "allow": "✅ Autoriser", "deny": "❌ Refuser",
           "allowed": "✅ Autorisée", "allowed_code": "✅ Autorisée avec le code", "denied": "❌ Refusée",
           "gone": "Cette demande a expiré.",
           "on": "🔐 La double authentification est activée. Sans l'interface web (Telegram en panne…) : sur le serveur, lance maxxing 2fa off",
           "off_cli": "🔓 La double authentification a été désactivée depuis le serveur (maxxing 2fa off).",
           "off_ui": "🔓 La double authentification a été désactivée depuis l'interface web. Ce n'est pas toi ? Change le mot de passe.",
           "unlinked": "🔓 Telegram est en train d'être délié depuis l'interface web : la double authentification est désactivée. Ce n'est pas toi ? Change le mot de passe."},
}


def _w(key: str, **kw) -> str:
    lang = "fr" if config.load_config().get("language") == "fr" else "en"
    return WORDS[lang][key].format(**kw)


@dataclass
class Challenge:
    id: str
    code: str
    purpose: str               # "login" | "enable"
    ip: str
    ua: str
    expires: float
    status: str = "pending"    # pending | approved | denied
    via: str = ""              # "telegram" | "code"
    tries: int = 0
    text: str = ""
    msg: tuple[int, int] | None = None     # (chat_id, message_id) of the Telegram message
    created: float = 0.0
    delay: float = 0.0         # what the attempt limiter asks to wait after the last wrong app / recovery code
    silent: bool = False       # no Telegram message: only an app or recovery code answers it


class Refused(Exception):
    def __init__(self, error: str, message: str):
        super().__init__(message)
        self.error = error
        self.message = message


_ch: dict[str, Challenge] = {}
_new: dict[str, list[float]] = {}
_bad: list[float] = []                       # times of wrong codes (all challenges)
_lock = threading.Lock()


# ---- state ---------------------------------------------------------------------------------
def _tg() -> dict:
    return config.load_config().get("telegram") or {}


def available() -> bool:
    """A bot, a chat and its owner are linked: a request can be sent and answered."""
    tg = _tg()
    return bool(config.get_secret("telegram_token") and tg.get("chat_id") and tg.get("user_ids"))


def is_on() -> bool:
    return bool(_tg().get("two_factor"))


def enabled() -> bool:
    return is_on() and available()


def set_on(on: bool) -> None:
    with config._lock:                                          # noqa: SLF001 - same package
        cfg = config.load_config()
        tg = cfg.setdefault("telegram", {})
        if on:
            tg["two_factor"] = True
        else:
            tg.pop("two_factor", None)
        config.save_config(cfg)
    if not on:
        forget_devices()
        if not totp_on():
            config.set_secret("recovery_codes", None)


# ---- trusted browsers ----------------------------------------------------------------------
def _device_key() -> bytes:
    return security.secret_key("device_key")


def make_device_cookie() -> str:
    body = f"{int(time.time())}.{secrets.token_hex(8)}"
    return f"{body}.{hmac.new(_device_key(), body.encode(), hashlib.sha256).hexdigest()}"


def device_trusted(value: str | None) -> bool:
    if not value or not _DEVICE_RE.fullmatch(value):   # an odd (non-ASCII) cookie is just not trusted, never a 500
        return False
    body, sig = value.rsplit(".", 1)
    if not hmac.compare_digest(sig.encode(), hmac.new(_device_key(), body.encode(), hashlib.sha256).hexdigest().encode()):
        return False
    try:
        return time.time() - int(body.split(".", 1)[0]) < DEVICE_MAX_AGE
    except ValueError:
        return False


def forget_devices() -> None:
    config.set_secret("device_key", None)          # a new key is made on first use: every old cookie fails
    revoke_all()


def revoke_all() -> None:
    """Every waiting or approved request dies (password changed, two-step sign-in off, browsers forgotten): an
    Allow pressed by mistake can no longer be collected afterwards. The `maxxing` command runs in another process than
    the server: the time recorded in secrets.json makes the server drop the requests made before it too."""
    config.set_secret("challenges_not_before", time.time())
    with _lock:
        gone = list(_ch.values())
        _ch.clear()
    for c in gone:
        _close(c, _w("gone"))


# ---- authenticator app ---------------------------------------------------------------------
def totp_at(secret: str, step: int) -> str:
    """The 6-digit code of a Base32 secret for one 30 s step (RFC 6238 over RFC 4226, HMAC-SHA1)."""
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    at = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[at:at + 4])[0] & 0x7FFFFFFF) % 10 ** 6:06d}"


def _match_step(secret: str, code: str, now: float) -> int | None:
    """The step (current, or right before / after) whose code is `code`; every candidate is compared."""
    if not _CODE_RE.fullmatch(code):
        return None
    cur, found = int(now // TOTP_STEP), None
    for step in (cur - 1, cur, cur + 1):
        try:
            good = totp_at(secret, step)
        except (ValueError, TypeError):
            return None
        if hmac.compare_digest(code.encode(), good.encode()):
            found = step
    return found


def _totp() -> dict:
    v = config.load_secrets().get("totp")
    return v if isinstance(v, dict) else {}


def totp_on() -> bool:
    return bool(_totp().get("secret"))


def required() -> bool:
    """A right password is not enough to sign in from a browser that is not trusted."""
    return enabled() or totp_on()


def totp_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account or 'owner'}", safe="")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&algorithm=SHA1&digits=6&period={TOTP_STEP}"


def totp_begin() -> str:
    """Start an enrolment -> the new Base32 secret (160 bits). Not active until `totp_confirm`."""
    secret = base64.b32encode(secrets.token_bytes(20)).decode()
    with config._lock:                                          # noqa: SLF001
        config.set_secret("totp", {**_totp(), "pending": secret, "pending_at": int(time.time())})
    return secret


def totp_confirm(code: str, now: float | None = None) -> list[str] | None:
    """A code of the secret being enrolled turns the app on -> fresh recovery codes; None: wrong code / nothing to
    confirm."""
    now = time.time() if now is None else now
    with config._lock:                                          # noqa: SLF001
        st = _totp()
        pending = st.get("pending")
        try:
            fresh = 0 <= now - float(st.get("pending_at") or 0) < TOTP_PENDING_S
        except (TypeError, ValueError):
            fresh = False
        step = _match_step(str(pending), _clean(code), now) if pending and fresh else None
        if step is None:
            return None
        config.set_secret("totp", {"secret": pending, "last": step})
        return new_recovery_codes()


def totp_verify(code: str, now: float | None = None) -> bool:
    """One app code: right for a step never used before (a code seen once is refused, older steps too)."""
    now = time.time() if now is None else now
    with config._lock:                                          # noqa: SLF001
        st = _totp()
        if not st.get("secret"):
            return False
        step = _match_step(str(st["secret"]), _clean(code), now)
        try:
            last = int(st.get("last") or 0)
        except (TypeError, ValueError):
            last = 0
        if step is None or step <= last:
            return False
        config.set_secret("totp", {**st, "last": step})
        return True


def totp_off() -> None:
    with config._lock:                                          # noqa: SLF001
        config.set_secret("totp", None)
        if not enabled():
            config.set_secret("recovery_codes", None)


# ---- recovery codes ------------------------------------------------------------------------
def _clean(code: str | None) -> str:
    return re.sub(r"[\s-]", "", code or "").lower()


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8", "surrogatepass")).hexdigest()


def new_recovery_codes() -> list[str]:
    """RECOVERY_N new one-time codes (the old ones stop working); only their SHA-256 is stored."""
    codes = ["".join(secrets.choice(_B32) for _ in range(16)) for _ in range(RECOVERY_N)]
    config.set_secret("recovery_codes", [_hash(c) for c in codes])
    return ["-".join(c[i:i + 4] for i in range(0, 16, 4)) for c in codes]


def recovery_left() -> int:
    v = config.load_secrets().get("recovery_codes")
    return len(v) if isinstance(v, list) else 0


def use_recovery(code: str) -> bool:
    given = _hash(_clean(code))
    with config._lock:                                          # noqa: SLF001
        cur = config.load_secrets().get("recovery_codes")
        cur = [h for h in cur if isinstance(h, str)] if isinstance(cur, list) else []
        hit = [h for h in cur if hmac.compare_digest(h.encode(), given.encode())]
        if not hit:
            return False
        config.set_secret("recovery_codes", [h for h in cur if h not in hit] or None)
        return True


def verify_second(code: str | None) -> str | None:
    """An app code or a recovery code -> "totp" | "recovery" | None. The caller counts the attempt."""
    if totp_verify(code or ""):
        return "totp"
    if len(_clean(code)) == 16 and use_recovery(code or ""):
        return "recovery"
    return None


def set_device_cookie(response, request) -> None:
    response.set_cookie(DEVICE_COOKIE, make_device_cookie(), max_age=DEVICE_MAX_AGE, httponly=True,
                        samesite="strict", secure=security.is_https(request), path="/api/auth")


# ---- challenges ----------------------------------------------------------------------------
def _prune(now: float) -> None:
    for cid in [k for k, c in _ch.items() if now > c.expires + GRACE]:
        del _ch[cid]
    _bad[:] = [t for t in _bad if now - t < BAD_WINDOW]
    for k in list(_new):
        lst = [t for t in _new[k] if now - t < NEW_WINDOW]
        if lst:
            _new[k] = lst
        else:
            del _new[k]


def start(purpose: str, ip: str, ua: str) -> Challenge:
    """New challenge + its Telegram message (blocking: call it from a thread). Raises Refused. A sign-in with the
    authenticator app on and no Telegram (not linked, or the message was refused) gets a silent challenge."""
    silent_ok = purpose == "login" and totp_on()
    send = purpose != "login" or enabled() or not totp_on()      # the app alone: no Telegram message
    now = time.time()
    with _lock:
        _prune(now)
        if len(_new.get(ip, [])) >= NEW_MAX:
            raise Refused("throttled", "Too many sign-in requests - try again in 15 min")
        waiting = sorted((c for c in _ch.values() if c.status == "pending"), key=lambda c: c.expires)
        mine = [c for c in waiting if c.ip == ip]
        drop = mine[:max(0, len(mine) - PENDING_PER_CLIENT + 1)]       # a reloaded page replaces its old request
        rest = [c for c in waiting if c not in drop]
        drop += rest[:max(0, len(rest) - PENDING_MAX + 1)]              # full: the oldest give way (a few clients
        _new.setdefault(ip, []).append(now)                             # cannot lock the owner out), once the new
        c = Challenge(id=secrets.token_urlsafe(12), code=f"{secrets.randbelow(10 ** 6):06d}", purpose=purpose,
                      ip=ip, ua=ua[:120], expires=now + TTL, created=now)
        _ch[c.id] = c
    sent = send and _send(c)
    if not sent and silent_ok:
        c.code, c.silent = "", True
    elif not sent:
        with _lock:
            _ch.pop(c.id, None)
            sent = _new.get(ip, [])
            if now in sent:                            # a request Telegram refused does not count against the quota
                sent.remove(now)
        raise Refused("two_factor_unavailable",
                      "Telegram did not accept the sign-in request - on the server, `maxxing 2fa off` turns "
                      "two-step sign-in off")
    with _lock:                                        # one is sent: a failed send keeps the older ones answerable
        for old in drop:
            if _ch.get(old.id) is old and old.status == "pending":
                del _ch[old.id]
                _close(old, _w("gone"))
    return c


def _not_before() -> float:
    try:
        return float(config.get_secret("challenges_not_before") or 0)
    except (TypeError, ValueError):
        return 0.0


def purpose(cid: str) -> str | None:
    """What a waiting challenge is for ("login" | "enable"), without touching it; None when there is none."""
    with _lock:
        c = _ch.get(cid or "")
        return c.purpose if c else None


def check(cid: str, code: str | None = None) -> tuple[str, Challenge | None]:
    """-> (status, challenge): "pending", "approved" (consumed: only once), "denied", "expired", "bad_code"."""
    now = time.time()
    with _lock:
        _prune(now)                                 # an approved request also dies after TTL + GRACE
        c = _ch.get(cid or "")
        if c is None:
            return "expired", None
        # revoked from another process (maxxing password, 2fa off...), or no answer in time
        if c.created <= _not_before() or (c.status == "pending" and now > c.expires):
            del _ch[cid]
            _close(c, _w("gone"))
            return "expired", None
        if c.status == "denied":
            del _ch[cid]
            return "denied", c
        if c.status == "pending" and code:
            if len(_bad) >= BAD_MAX:                # code guessing from many addresses: the button still works
                return "codes_paused", c
            given = code.strip().replace(" ", "")
            via = ""
            if c.code and _CODE_RE.fullmatch(given) and hmac.compare_digest(given.encode(), c.code.encode()):
                via = "code"
            elif c.purpose == "login" and (totp_on() or recovery_left()):
                key = "2f:" + c.ip
                if security.begin_attempt(key, trusted=True)[0]:
                    return "throttled", c
                via = verify_second(given) or ""
                c.delay = security.end_attempt(key, bool(via))
            if via:
                c.status, c.via = "approved", via
                _close(c, _w("allowed_code"))
            else:
                c.tries += 1
                _bad.append(now)
                if c.tries >= CODE_TRIES:
                    del _ch[cid]
                    _close(c, _w("gone"))
                    return "expired", None
                return "bad_code", c
        if c.status == "approved":
            del _ch[cid]
            return "approved", c
        return "pending", c


def decide(cid: str, allow: bool) -> str:
    """Allow / Deny pressed in Telegram -> the text of the callback answer."""
    with _lock:
        c = _ch.get(cid)
        if c is None or c.status != "pending" or time.time() > c.expires:
            return _w("gone")
        c.status, c.via = ("approved" if allow else "denied"), "telegram"
    _close(c, _w("allowed" if allow else "denied"))
    if not allow and c.purpose == "login":
        try:
            from . import feed
            feed.system("Sign-in denied in Telegram (the password was right)", f"{c.ip} · {c.ua}", "warning",
                        "security")
        except Exception:  # noqa: BLE001
            pass
    return _w("allowed" if allow else "denied")


def reset() -> None:
    """Tests."""
    with _lock:
        _ch.clear()
        _new.clear()
        _bad.clear()


# ---- Telegram ------------------------------------------------------------------------------
def short_ua(ua: str) -> str:
    """'Chrome · Windows' from a user agent (the raw string when nothing is recognised)."""
    u = ua or ""
    browser = next((name for key, name in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"),
                                           ("CriOS/", "Chrome"), ("FxiOS/", "Firefox"), ("Chrome/", "Chrome"),
                                           ("Safari/", "Safari")) if key in u), "")
    system = next((name for key, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                                          ("Windows", "Windows"), ("Mac OS X", "macOS"), ("CrOS", "ChromeOS"),
                                          ("Linux", "Linux")) if key in u), "")
    return " · ".join(x for x in (browser, system) if x) or u[:80] or "?"


def _send(c: Challenge) -> bool:
    """The request with its Allow / Deny buttons, in Alerts (the main chat in the simple mode), loud."""
    from .telegram import client, gateway
    from .telegram.format import escape
    chat, _ = gateway._target(gateway.ALERTS)                    # noqa: SLF001
    if not gateway.token() or not chat:
        return False
    lines = [_w(c.purpose)]
    if c.purpose == "login":
        lines += [f"{_w('ip')}: {escape(c.ip)}", f"{_w('browser')}: {escape(short_ua(c.ua))}"]
    lines += [f"{_w('code')}: <code>{c.code}</code>", _w("expires", m=TTL // 60), "",
              f"<i>{_w('hint_' + c.purpose)}</i>"]
    c.text = "\n".join(lines)
    markup = client.keyboard([[(_w("allow"), f"a:{c.id}:y"), (_w("deny"), f"a:{c.id}:n")]])
    sent: list = []
    if not gateway._send_sync(gateway.ALERTS, [c.text], False, markup, sent=sent) or not sent:   # noqa: SLF001
        log.warning("two-step sign-in request not sent")
        return False
    c.msg = (chat, int(sent[-1]))
    return True


def _close(c: Challenge, line: str) -> None:
    """Remove the buttons and add the outcome (background thread, best effort)."""
    if not c.msg:
        return
    msg, c.msg = c.msg, None

    def run() -> None:
        try:
            from .telegram import client, gateway
            client.call_sync(gateway.token(), "editMessageText", chat_id=msg[0], message_id=msg[1],
                             text=f"{c.text}\n\n<b>{line}</b>", parse_mode="HTML")
        except Exception as e:  # noqa: BLE001
            log.info("two-step sign-in message not updated: %s", e)
    threading.Thread(target=run, daemon=True).start()


def notify(key: str, wait: bool = False) -> None:
    """A plain message in the "Alerts" thread, whatever the sign-in alerts setting ("on", "off_cli", "off_ui",
    "unlinked"). `wait`: sent before returning (blocking), for a bridge about to be unlinked."""
    try:
        from .telegram import gateway
        if wait:
            gateway._send_sync(gateway.ALERTS, gateway.fmt.plain(_w(key)), silent=False)      # noqa: SLF001
        else:
            gateway._post(gateway.ALERTS, gateway.fmt.plain(_w(key)), silent=False)      # noqa: SLF001
    except Exception:  # noqa: BLE001
        log.info("two-step sign-in notice not sent", exc_info=True)
