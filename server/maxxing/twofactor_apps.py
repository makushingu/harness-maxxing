"""Two-step sign-in without Telegram: an authenticator app (TOTP), passkeys / security keys (WebAuthn), recovery codes.

- Any of them on = a second step after the right password, like Telegram's (`twofactor.py`); several can be on, the
  sign-in page offers each. Trusted browsers (`mx_device`) are shared with Telegram's two-step sign-in.
- After the right password the server hands out a ticket (memory, TTL s, bound to the client): proof that the password
  was right, spent once by one second step. CODE_TRIES wrong codes kill it; BAD_MAX wrong codes server-wide per
  BAD_WINDOW pause the codes (a passkey still works). `twofactor.revoke_all()` (password changed, 2FA off, browsers
  forgotten, from the server process or `maxxing`) kills every ticket.
- secrets.json: `totp_secret` (base32), `totp_last` (last accepted time step: a code is never accepted twice),
  `passkeys` [{id, public_key, sign_count, name, rp_id, transports, created, last_used}] (ids and keys base64url),
  `recovery_codes` [sha256 hex] (one use each, made when the first app method is turned on, gone with the last one).
- A passkey belongs to the address it was made on (WebAuthn relying party = the host name of the page): one made on
  ui.example.com is not offered on another address. WebAuthn needs HTTPS (or localhost).
- Way out without the UI: `maxxing 2fa off` over SSH turns every method off.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import config

log = logging.getLogger("maxxing.twofactor_apps")

TTL = 300                      # a ticket (sign-in) or a setup (Settings) lives this long
CODE_TRIES = 5
BAD_MAX = 20
BAD_WINDOW = 3600
TICKETS_MAX = 50               # waiting tickets kept (the oldest give way)
TICKETS_PER_CLIENT = 3         # live tickets of one client; more than that within TTL/3 is refused
OPTIONS_MAX = 10               # passkey prompts per ticket
TOTP_DRIFT = 1                 # a code of the previous or next 30 s step is accepted too (clock drift)
RECOVERY_COUNT = 10
PASSKEYS_MAX = 20
ISSUER = "Harness Maxxing"
_TOTP_RE = re.compile(r"[0-9]{6}")
_RECOVERY_RE = re.compile(r"[a-z0-9]{5}-?[a-z0-9]{5}")
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"          # no 0/o, 1/l/i: read from paper


class Refused(Exception):
    def __init__(self, status: int, error: str, message: str, **extra):
        super().__init__(message)
        self.status, self.error, self.message, self.extra = status, error, message, extra


@dataclass
class Ticket:
    id: str
    ip: str
    expires: float
    created: float
    tries: int = 0
    challenge: bytes | None = None            # WebAuthn challenge of the last passkey options
    rp_id: str = ""
    telegram: str | None = None               # the Telegram challenge started with it (closed on success)
    options: int = 0                          # passkey prompts asked with it


@dataclass
class Setup:
    id: str
    kind: str                                 # "totp" | "passkey"
    expires: float
    secret: str = ""
    challenge: bytes = b""
    rp_id: str = ""
    origins: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


_tickets: dict[str, Ticket] = {}
_setups: dict[str, Setup] = {}
_bad: list[float] = []
_pause_alerted = 0.0
_lock = threading.Lock()


# ---- state -----------------------------------------------------------------------------------
def _passkeys() -> list[dict]:
    raw = config.load_secrets().get("passkeys")
    return [p for p in raw if isinstance(p, dict) and p.get("id") and p.get("public_key")] if isinstance(raw, list) else []


def totp_on() -> bool:
    return bool(config.get_secret("totp_secret"))


def methods(rp_id: str | None = None) -> list[str]:
    """The app methods on: "totp", "passkey" (with rp_id: only when a passkey of that address exists)."""
    out = ["totp"] if totp_on() else []
    keys = _passkeys()
    if keys and (rp_id is None or any(k.get("rp_id") == rp_id for k in keys)):
        out.append("passkey")
    return out


def any_on() -> bool:
    return totp_on() or bool(_passkeys())


def recovery_left() -> int:
    codes = config.load_secrets().get("recovery_codes")
    return len(codes) if isinstance(codes, list) else 0


def summary(rp_id: str) -> dict:
    return {"totp": totp_on(), "recovery_left": recovery_left(), "rp_id": rp_id,
            "passkeys": [{"id": k["id"], "name": k.get("name") or "", "rp_id": k.get("rp_id") or "",
                          "created": k.get("created"), "last_used": k.get("last_used")} for k in _passkeys()]}


def _new_recovery_codes() -> list[str]:
    codes = ["".join(secrets.choice(_ALPHABET) for _ in range(10)) for _ in range(RECOVERY_COUNT)]
    config.set_secret("recovery_codes", [_hash(c) for c in codes])
    return [f"{c[:5]}-{c[5:]}" for c in codes]


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()       # random 50-bit codes, one use: a fast hash is enough


def regenerate_recovery_codes() -> list[str]:
    if not any_on():
        raise Refused(409, "no_method", "Turn on an authenticator app or a passkey first")
    return _new_recovery_codes()


def _after_change() -> list[str] | None:
    """New recovery codes when the first app method was just turned on; none left once the last is off."""
    with config._lock:                                                          # noqa: SLF001 - same package
        if not any_on():
            config.set_secrets({"recovery_codes": None, "recovery_codes_made": None})
            return None
        if recovery_left() == 0 and not config.load_secrets().get("recovery_codes_made"):
            config.set_secret("recovery_codes_made", True)
            return _new_recovery_codes()
    return None


def turn_all_off() -> bool:
    """`maxxing 2fa off`: every app method, passkey and recovery code goes. -> something was on."""
    was = any_on()
    config.set_secrets({"totp_secret": None, "totp_last": None, "passkeys": None, "recovery_codes": None,
                        "recovery_codes_made": None})
    from . import twofactor
    twofactor.forget_devices()                     # every trusted browser asks again (and every ticket dies)
    return was


# ---- tickets (sign-in) ----------------------------------------------------------------------
def _not_before() -> float:
    try:
        return float(config.get_secret("challenges_not_before") or 0)
    except (TypeError, ValueError):
        return 0.0


def _prune(now: float) -> None:
    for d in (_tickets, _setups):
        for k in [k for k, v in d.items() if now > v.expires]:
            del d[k]
    _bad[:] = [t for t in _bad if now - t < BAD_WINDOW]


def new_ticket(ip: str, telegram: str | None = None) -> Ticket:
    """Refused 429 past TICKETS_PER_CLIENT live tickets of this client: a password thief cannot flood the list."""
    now = time.time()
    with _lock:
        _prune(now)
        mine = sorted((t for t in _tickets.values() if t.ip == ip), key=lambda t: t.created)
        if len(mine) >= TICKETS_PER_CLIENT and now - mine[-TICKETS_PER_CLIENT].created < TTL / 3:
            raise Refused(429, "throttled", "Too many sign-in requests - try again in a few minutes")
        # a reloaded page replaces its own oldest ticket; a full list drops the oldest of anybody
        drop = mine[:max(0, len(mine) - TICKETS_PER_CLIENT + 1)]
        rest = sorted((t for t in _tickets.values() if t not in drop), key=lambda t: t.created)
        for old in drop + rest[:max(0, len(rest) - TICKETS_MAX + 1)]:
            _tickets.pop(old.id, None)
        t = Ticket(id=secrets.token_urlsafe(18), ip=ip, expires=now + TTL, created=now, telegram=telegram)
        _tickets[t.id] = t
    return t


def take_pause_alert() -> bool:
    """True once when wrong codes just paused the codes: the owner should know the password is known."""
    global _pause_alerted
    with _lock:
        if len(_bad) >= BAD_MAX and time.time() - _pause_alerted > BAD_WINDOW:
            _pause_alerted = time.time()
            return True
    return False


def _ticket(tid: str, ip: str) -> Ticket:
    """The live ticket of this client (lock held), or Refused 410."""
    t = _tickets.get(tid or "")
    if t is None or t.ip != ip or time.time() > t.expires or t.created <= _not_before():
        if t is not None and t.ip == ip:
            del _tickets[t.id]
        raise Refused(410, "expired", "The sign-in request expired - sign in again")
    return t


def ticket_methods(tid: str, ip: str) -> Ticket:
    with _lock:
        return _ticket(tid, ip)


def _spend(t: Ticket) -> Ticket:
    _tickets.pop(t.id, None)
    return t


def _wrong(t: Ticket) -> None:
    t.tries += 1
    _bad.append(time.time())
    if t.tries >= CODE_TRIES:
        del _tickets[t.id]
        raise Refused(410, "expired", "Too many wrong codes - sign in again")
    raise Refused(400, "bad_code", "Wrong code", tries_left=CODE_TRIES - t.tries)


def _totp_step(secret: str, code: str, now: float) -> int | None:
    """The 30 s step this code belongs to (within TOTP_DRIFT), or None."""
    import pyotp
    totp, step = pyotp.TOTP(secret), int(now // 30)
    hit = None
    for s in range(step - TOTP_DRIFT, step + TOTP_DRIFT + 1):          # every step compared: no early exit timing
        if hmac.compare_digest(totp.generate_otp(s).encode(), code.encode()):
            hit = s
    return hit


def _check_totp(code: str, now: float) -> bool:
    """A right code of a step newer than the last accepted one (lock held): a code read over the shoulder cannot be
    used again."""
    secret = config.get_secret("totp_secret")
    if not secret:
        return False
    step = _totp_step(str(secret), code, now)
    try:
        last = int(config.get_secret("totp_last") or 0)
    except (TypeError, ValueError):
        last = 0
    if step is None or step <= last:
        return False
    config.set_secret("totp_last", step)
    return True


def _use_recovery(code: str) -> bool:
    with config._lock:                                                          # noqa: SLF001
        stored = config.load_secrets().get("recovery_codes")
        if not isinstance(stored, list):
            return False
        h = _hash(code.replace("-", ""))
        hit = next((s for s in stored if isinstance(s, str) and hmac.compare_digest(s, h)), None)
        if hit is None:
            return False
        config.set_secret("recovery_codes", [s for s in stored if s != hit] or None)
        return True


def check_code(tid: str, ip: str, code: str) -> tuple[Ticket, str]:
    """An authenticator code or a recovery code for this ticket -> (spent ticket, "totp" | "recovery"). Refused."""
    given = (code or "").strip().lower().replace(" ", "")
    now = time.time()
    with _lock:
        _prune(now)
        t = _ticket(tid, ip)
        if len(_bad) >= BAD_MAX:
            raise Refused(429, "codes_paused", "Too many wrong codes on this server - use a passkey, or try again "
                                               "in an hour")
        if _TOTP_RE.fullmatch(given) and totp_on() and _check_totp(given, now):
            return _spend(t), "totp"
        if _RECOVERY_RE.fullmatch(given) and any_on() and _use_recovery(given):
            return _spend(t), "recovery"
        _wrong(t)
    raise AssertionError("unreachable")


# ---- WebAuthn ---------------------------------------------------------------------------------
def origin_of(request) -> tuple[list[str], str]:
    """([accepted origins], rp_id) of the page that called: Host + the scheme the proxy reports (as the cookies do),
    and the public URL of Settings -> System when it has the same host (a proxy that drops X-Forwarded-Proto).
    The browser signs its real origin and rp_id: these headers can only make a check fail, never pass a forged one."""
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip() or "http"
    host = (request.headers.get("host") or request.url.netloc or "").strip()
    rp_id = (urlsplit(f"//{host}").hostname or "").lower()
    origins = [f"{scheme}://{host}".lower()]
    public = urlsplit(str(config.load_config().get("public_url") or ""))
    if public.scheme in ("http", "https") and (public.hostname or "").lower() == rp_id:
        origins.append(f"{public.scheme}://{public.netloc}".lower())
    return list(dict.fromkeys(origins)), rp_id


def _b64(b: bytes) -> str:
    from webauthn.helpers import bytes_to_base64url
    return bytes_to_base64url(b)


def _unb64(s: str) -> bytes:
    from webauthn.helpers import base64url_to_bytes
    return base64url_to_bytes(s)


def passkey_options(tid: str, ip: str, rp_id: str) -> dict:
    """navigator.credentials.get() options for this ticket (only the passkeys of this address)."""
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement
    keys = [k for k in _passkeys() if k.get("rp_id") == rp_id]
    if not keys:
        raise Refused(409, "no_passkey", "No passkey was added on this address")
    from webauthn.helpers.structs import AuthenticatorTransport
    known = {t.value for t in AuthenticatorTransport}
    with _lock:
        t = _ticket(tid, ip)
        t.options += 1
        if t.options > OPTIONS_MAX:
            del _tickets[t.id]
            raise Refused(410, "expired", "Too many passkey requests - sign in again")
        opts = generate_authentication_options(
            rp_id=rp_id, timeout=120_000, user_verification=UserVerificationRequirement.PREFERRED,
            allow_credentials=[PublicKeyCredentialDescriptor(
                id=_unb64(k["id"]), transports=[AuthenticatorTransport(x) for x in k.get("transports") or [] if x in known] or None)
                for k in keys])
        t.challenge, t.rp_id = opts.challenge, rp_id
    return json.loads(options_to_json(opts))


def check_passkey(tid: str, ip: str, credential: dict, origin: list[str], rp_id: str) -> tuple[Ticket, dict]:
    """The signed answer of navigator.credentials.get() -> (spent ticket, the passkey used). Refused."""
    from webauthn import verify_authentication_response
    from webauthn.helpers.exceptions import WebAuthnException
    with _lock:
        t = _ticket(tid, ip)
        if not t.challenge or t.rp_id != rp_id:
            raise Refused(400, "bad_passkey", "Ask for the passkey again")
        challenge, t.challenge = t.challenge, None             # one answer per challenge
    cid = credential.get("id") if isinstance(credential, dict) else None
    with config._lock:                                                          # noqa: SLF001
        keys = _passkeys()
        key = next((k for k in keys if k["id"] == cid and k.get("rp_id") == rp_id), None)
        if key is None:
            raise Refused(400, "bad_passkey", "This passkey is not known here")
        try:
            v = verify_authentication_response(
                credential=credential, expected_challenge=challenge, expected_rp_id=rp_id, expected_origin=origin,
                credential_public_key=_unb64(key["public_key"]), credential_current_sign_count=int(key.get("sign_count") or 0))
        except (WebAuthnException, ValueError, KeyError, TypeError) as e:
            log.info("passkey sign-in refused: %s", e)                  # the details stay in the log
            raise Refused(400, "bad_passkey", "The passkey answer was refused") from None
        key["sign_count"], key["last_used"] = int(v.new_sign_count), int(time.time())
        config.set_secret("passkeys", keys)
    with _lock:
        t = _ticket(tid, ip)
        return _spend(t), key


# ---- Settings: authenticator app --------------------------------------------------------------
def totp_setup(label: str) -> dict:
    """A new secret to scan (not active until confirmed with a code)."""
    import pyotp
    if totp_on():
        raise Refused(409, "already_on", "An authenticator app is already set up - turn it off first")
    now = time.time()
    s = Setup(id=secrets.token_urlsafe(18), kind="totp", expires=now + TTL, secret=pyotp.random_base32(32))
    with _lock:
        _prune(now)
        _setups[s.id] = s
    return {"setup": s.id, "secret": s.secret, "expires_in": TTL,
            "uri": pyotp.TOTP(s.secret).provisioning_uri(name=label or "admin", issuer_name=ISSUER)}


def _setup(sid: str, kind: str) -> Setup:
    s = _setups.get(sid or "")
    if s is None or s.kind != kind or time.time() > s.expires:
        raise Refused(410, "expired", "The setup expired - start again")
    return s


def totp_confirm(sid: str, code: str) -> list[str] | None:
    """The first code of the app proves it was scanned: the secret becomes active. -> recovery codes (first method)."""
    given = (code or "").strip().replace(" ", "")
    now = time.time()
    with _lock:
        s = _setup(sid, "totp")
        step = _totp_step(s.secret, given, now) if _TOTP_RE.fullmatch(given) else None
        if step is None:
            raise Refused(400, "bad_code", "Wrong code - check the time of the phone")
        del _setups[sid]
    config.set_secrets({"totp_secret": s.secret, "totp_last": step})
    return _after_change()


def totp_off() -> None:
    config.set_secrets({"totp_secret": None, "totp_last": None})
    _after_change()


# ---- Settings: passkeys -----------------------------------------------------------------------
def _user_id() -> bytes:
    uid = config.get_secret("webauthn_user")
    if not uid:
        with config._lock:                                                      # noqa: SLF001
            uid = config.get_secret("webauthn_user") or secrets.token_hex(16)
            config.set_secret("webauthn_user", uid)
    return bytes.fromhex(str(uid))


def passkey_register_options(origins: list[str], rp_id: str, label: str) -> dict:
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                          ResidentKeyRequirement, UserVerificationRequirement)
    if not rp_id:
        raise Refused(400, "bad_origin", "Unknown address")
    keys = _passkeys()
    if len(keys) >= PASSKEYS_MAX:
        raise Refused(409, "too_many", f"At most {PASSKEYS_MAX} passkeys - remove one first")
    opts = generate_registration_options(
        rp_id=rp_id, rp_name=ISSUER, user_name=label or "admin", user_id=_user_id(), user_display_name=label or "admin",
        timeout=120_000,
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.PREFERRED,
                                                               user_verification=UserVerificationRequirement.PREFERRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=_unb64(k["id"])) for k in keys if k.get("rp_id") == rp_id])
    now = time.time()
    s = Setup(id=secrets.token_urlsafe(18), kind="passkey", expires=now + TTL, challenge=opts.challenge, rp_id=rp_id,
              origins=origins)
    with _lock:
        _prune(now)
        _setups[s.id] = s
    return {"setup": s.id, "options": json.loads(options_to_json(opts))}


def passkey_register(sid: str, credential: dict, name: str, rp_id: str) -> tuple[dict, list[str] | None]:
    from webauthn import verify_registration_response
    from webauthn.helpers.exceptions import WebAuthnException
    with _lock:
        s = _setup(sid, "passkey")
        del _setups[sid]                                      # one answer per setup
    if rp_id != s.rp_id:
        raise Refused(400, "bad_passkey", "The address changed during the setup - start again")
    try:
        v = verify_registration_response(credential=credential, expected_challenge=s.challenge,
                                         expected_rp_id=s.rp_id, expected_origin=s.origins)
    except (WebAuthnException, ValueError, KeyError, TypeError) as e:
        log.info("passkey refused: %s", e)
        raise Refused(400, "bad_passkey", "The passkey was refused") from None
    transports = (credential.get("response") or {}).get("transports") if isinstance(credential, dict) else None
    key = {"id": _b64(v.credential_id), "public_key": _b64(v.credential_public_key), "sign_count": int(v.sign_count),
           "name": (name or "").strip()[:60] or "Passkey", "rp_id": s.rp_id, "created": int(time.time()),
           "last_used": None, "transports": [t for t in transports if isinstance(t, str)][:8] if isinstance(transports, list) else []}
    with config._lock:                                                          # noqa: SLF001
        keys = [k for k in _passkeys() if (k["id"], k.get("rp_id")) != (key["id"], key["rp_id"])]
        config.set_secret("passkeys", keys + [key])
    return key, _after_change()


def passkey_remove(pid: str) -> bool:
    with config._lock:                                                          # noqa: SLF001
        keys = _passkeys()
        rest = [k for k in keys if k["id"] != pid]
        if len(rest) == len(keys):
            return False
        config.set_secret("passkeys", rest or None)
    _after_change()
    return True


# ---- revocation ---------------------------------------------------------------------------------
def revoke_all() -> None:
    """Every ticket and setup dies (called by twofactor.revoke_all; other processes: challenges_not_before)."""
    with _lock:
        _tickets.clear()
        _setups.clear()


def reset() -> None:
    """Tests."""
    with _lock:
        _tickets.clear()
        _setups.clear()
        _bad.clear()
