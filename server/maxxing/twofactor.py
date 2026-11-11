"""Two-step sign-in: the sign-in challenge, the Telegram approval (Settings -> Telegram, `maxxing 2fa`) and trusted
browsers. The authenticator app, passkeys and recovery codes are in `mfa.py`; a challenge accepts every method that
is on (`Challenge.methods`).

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
- With an authenticator app or passkeys on too, the sign-in challenge lasts APP_TTL (time to open the app) and
  accepts their answer (`check(..., other=mfa.check_code)`, `approve(cid, "passkey")`); without Telegram 2FA no
  message is sent, and a Telegram that refuses the message no longer blocks the sign-in.
- Way out without the UI: `maxxing 2fa off` over SSH.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass

from . import config

log = logging.getLogger("maxxing.twofactor")

DEVICE_COOKIE = "mx_device"
DEVICE_MAX_AGE = 30 * 24 * 3600
TTL = 120
APP_TTL = 300                  # a challenge that also accepts an authenticator app code or a passkey
GRACE = 60                     # an approved challenge stays collectable this long after TTL
CODE_TRIES = 5
NEW_MAX = 5
NEW_WINDOW = 900
PENDING_MAX = 10
PENDING_PER_CLIENT = 3         # one client can hold this many waiting requests: a full list drops the oldest
BAD_MAX = 20                   # wrong codes accepted server-wide per BAD_WINDOW; then only the Allow button works
BAD_WINDOW = 3600
_CODE_RE = re.compile(r"[0-9]{6}")
_DEVICE_RE = re.compile(r"[0-9]{1,12}\.[0-9a-f]{16}\.[0-9a-f]{64}")

WORDS = {
    "en": {"login": "🔐 <b>Sign-in request</b>", "enable": "🔐 <b>Turn on two-step sign-in</b>",
           "ip": "IP", "browser": "Browser", "code": "Code", "expires": "Expires in {m} min.",
           "hint_login": "Not you? Deny it, then change the password: the right one was typed.",
           "hint_enable": "Allow to finish. From now on every new browser will need your approval here.",
           "allow": "✅ Allow", "deny": "❌ Deny",
           "allowed": "✅ Allowed", "allowed_code": "✅ Allowed with the code", "denied": "❌ Denied",
           "gone": "This request expired.",
           "gone_other": "✅ Signed in with another method.",
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
           "gone_other": "✅ Connexion validée par une autre méthode.",
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
    methods: tuple[str, ...] = ("telegram",)   # what this challenge accepts: telegram, totp, passkey, recovery
    webauthn: bytes | None = None          # the challenge of the last passkey prompt (mfa.authentication_options)


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


# ---- trusted browsers ----------------------------------------------------------------------
def _device_key() -> bytes:
    k = config.get_secret("device_key")
    if not k:
        with config._lock:                    # noqa: SLF001 - re-read: a key made meanwhile must not be replaced
            k = config.get_secret("device_key")
            if not k:
                k = secrets.token_hex(32)
                config.set_secret("device_key", k)
    return str(k).encode()                    # str(): a hand-edited secrets.json (a number) is not a 500


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


def set_device_cookie(response, request) -> None:
    https = request.headers.get("x-forwarded-proto", request.url.scheme).startswith("https")
    response.set_cookie(DEVICE_COOKIE, make_device_cookie(), max_age=DEVICE_MAX_AGE, httponly=True,
                        samesite="strict", secure=https, path="/api/auth")


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


def start(purpose: str, ip: str, ua: str, methods: tuple[str, ...] = ("telegram",)) -> Challenge:
    """New challenge + its Telegram message when it accepts "telegram" (blocking: call it from a thread). Raises
    Refused. A challenge with other methods too lasts APP_TTL and survives a Telegram that refuses the message."""
    now = time.time()
    methods = tuple(methods) or ("telegram",)
    ttl = TTL if methods == ("telegram",) else APP_TTL
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
                      ip=ip, ua=ua[:120], expires=now + ttl, created=now, methods=methods)
        _ch[c.id] = c
    if "telegram" in methods and not _send(c) and methods == ("telegram",):
        with _lock:
            _ch.pop(c.id, None)
            sent = _new.get(ip, [])
            if now in sent:                            # a request Telegram refused does not count against the quota
                sent.remove(now)
        raise Refused("two_factor_unavailable",
                      "Telegram did not accept the sign-in request - on the server, `maxxing 2fa off` turns "
                      "two-step sign-in off")
    if "telegram" in methods and c.msg is None:        # Telegram refused, the other methods remain
        c.methods = tuple(m for m in methods if m != "telegram")
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


def check(cid: str, code: str | None = None, other=None) -> tuple[str, Challenge | None]:
    """-> (status, challenge): "pending", "approved" (consumed: only once), "denied", "expired", "bad_code".
    `other(code)` -> "totp" | "recovery" | None: a code that is not the Telegram one (mfa.check_code), tried only
    when the challenge accepts those methods."""
    now = time.time()
    with _lock:
        _prune(now)                                 # an approved request also dies after TTL + GRACE
        c = _ch.get(cid or "")
        if c is None:
            return "expired", None
        if c.created <= _not_before():              # revoked from another process (maxxing password, 2fa off...)
            del _ch[cid]
            _close(c, _w("gone"))
            return "expired", None
        if c.status == "pending" and now > c.expires:
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
            via = None
            if "telegram" in c.methods and _CODE_RE.fullmatch(given) and hmac.compare_digest(given.encode(), c.code.encode()):
                via = "code"
            elif other is not None and set(c.methods) & {"totp", "recovery"}:
                via = other(code)
                if via is not None and via not in c.methods:
                    via = None
            if via is not None:
                c.status, c.via = "approved", via
                _close(c, _w("allowed_code") if via == "code" else _w("gone_other"))
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


def pending(cid: str) -> Challenge | None:
    """A challenge still waiting for an answer (not consumed, not expired, not revoked) - to attach a passkey
    prompt to it or to check one against it."""
    now = time.time()
    with _lock:
        c = _ch.get(cid or "")
        if c is None or c.status != "pending" or now > c.expires or c.created <= _not_before():
            return None
        return c


def approve(cid: str, via: str) -> bool:
    """Approved by another method than Telegram (a passkey checked by the caller)."""
    with _lock:
        c = _ch.get(cid or "")
        if c is None or c.status != "pending" or time.time() > c.expires:
            return False
        c.status, c.via = "approved", via
    _close(c, _w("gone_other"))
    return True


def failed(cid: str) -> bool:
    """A wrong answer by another method (a passkey that did not verify): counts like a wrong code. -> False once
    the challenge died of it."""
    with _lock:
        c = _ch.get(cid or "")
        if c is None:
            return False
        c.tries += 1
        _bad.append(time.time())
        if c.tries >= CODE_TRIES:
            del _ch[cid]
            _close(c, _w("gone"))
            return False
        return True


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
