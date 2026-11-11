"""Two-step sign-in with an authenticator app (TOTP) or passkeys (WebAuthn), and recovery codes.

These sit next to the Telegram approval (`twofactor.py`): two-step sign-in is required as soon as one method is on
(`required()`), and the sign-in challenge of `twofactor` accepts any method that is on. Everything lives in
secrets.json (mode 600):

- `totp_secret` (base32) and `totp_last_step` (the last step used: a code works once);
- `passkeys`: [{id, public_key (base64url COSE key), sign_count, name, rp_id, transports, created, last_used}] and
  `passkey_user` (the random WebAuthn user handle of this server);
- `recovery_codes`: SHA-256 hashes of the unused codes (made when the first app method is turned on; dropped
  when the last one is removed). A code is 10 random characters (~49 bits), so a plain hash is enough.

Passkeys only work on a secure origin with a name (https://ui.example.com, or http://localhost): the relying party
id is the host of the request (`rp_for`), and a passkey only signs for the host it was made on. Over
http://<tailscale ip> the app code and the recovery codes still work.

Sign-in with a passkey alone (on as soon as a passkey is added; config `passkey_login: false` = turned off, turning
it back on needs the current password): the sign-in page asks the browser for a passkey of this host before any
password; the passkey must verify its user
(fingerprint, face, PIN), which makes it two factors by itself. `passkey_login_on(rp_id)` = the flag and a passkey
for that host.

Confirming a sensitive action with a passkey ("sudo", like GitHub): a passkey answer (user verification required)
lets this browser session skip the current password for SUDO_TTL - removing a method, new recovery codes, turning
an option back on, unlinking Telegram; never changing the password itself. Grants live in memory, keyed by a hash of
the session cookie.

Way out without the UI: `maxxing 2fa off` over SSH turns every method off.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from . import config, totp

log = logging.getLogger("maxxing.mfa")

ISSUER = "Harness Maxxing"
RECOVERY_COUNT = 10
_RECOVERY_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"       # no 0/o, 1/l/i: read and typed by hand
_RECOVERY_RE = re.compile(r"[a-z0-9]{10}")
SETUP_TTL = 600             # an authenticator app set up but not confirmed is forgotten after 10 min
WEBAUTHN_TTL = 300          # a passkey prompt (registration) stays answerable 5 min
WEBAUTHN_TIMEOUT_MS = 120_000
PASSKEYS_MAX = 20
NAME_MAX = 60
# AAGUID -> the name a person knows (a passkey added without a name gets it; rename it anytime). Others: the browser.
PROVIDERS = {
    "d548826e-79b4-db40-a3d8-11116f7e8349": "Bitwarden",
    "bada5566-a7aa-401f-bd96-45619a55120d": "1Password",
    "531126d6-e717-415c-9320-3d9aa6981239": "Dashlane",
    "50726f74-6f6e-5061-7373-50726f746f6e": "Proton Pass",
    "fdb141b2-5d84-443e-8a35-4698c205a502": "KeePassXC",
    "fbfc3007-154e-4ecc-8c0b-6e020557d7bd": "iCloud Keychain",
    "dd4ec289-e01d-41c9-bb89-70fa845d4bf2": "iCloud Keychain",
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google Password Manager",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome on Mac",
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
    "53414d53-554e-4700-0000-000000000000": "Samsung Pass",
}

_lock = threading.Lock()
_totp_setup: dict[str, Any] = {}                 # {"secret", "expires"} - one setup at a time, this process
_reg: dict[str, dict] = {}                       # registration challenge (base64url) -> {rp_id, origin, expires}
_login: dict[str, dict] = {}                     # passkey-only sign-in challenge (base64url) -> {rp_id, origin, expires}
LOGIN_PROMPTS_MAX = 20                           # waiting passkey-only prompts (all clients): the oldest gives way
SUDO_TTL = 300                                   # a passkey confirmation stands in for the password this long
_reauth: dict[str, dict] = {}                    # session hash -> {challenge, rp_id, origin, expires}
_sudo: dict[str, float] = {}                     # session hash -> until


# ---- state ---------------------------------------------------------------------------------
def totp_on() -> bool:
    return bool(config.get_secret("totp_secret"))


def passkeys() -> list[dict]:
    raw = config.load_secrets().get("passkeys")
    return [p for p in raw if isinstance(p, dict) and p.get("id") and p.get("public_key")] if isinstance(raw, list) else []


def app_on() -> bool:
    """An authenticator app or a passkey is set (the methods that do not need Telegram)."""
    return totp_on() or bool(passkeys())


def required() -> bool:
    """A new browser needs a second step after the password (any method)."""
    from . import twofactor
    return twofactor.enabled() or app_on()


def passkey_login_flag() -> bool:
    """On unless turned off (config `passkey_login: false`); effective only with a passkey (`passkey_login_on`)."""
    return config.load_config().get("passkey_login") is not False


def passkey_login_on(rp_id: str | None) -> bool:
    """A passkey alone signs in on this host: the option is on and a passkey was made for it."""
    return bool(rp_id) and passkey_login_flag() and any(p.get("rp_id") == rp_id for p in passkeys())


def set_passkey_login(on: bool) -> None:
    with config._lock:                                         # noqa: SLF001 - same package
        cfg = config.load_config()
        if on:
            cfg.pop("passkey_login", None)                     # the default
        else:
            cfg["passkey_login"] = False
        config.save_config(cfg)


def recovery_left() -> int:
    raw = config.load_secrets().get("recovery_codes")
    return len(raw) if isinstance(raw, list) else 0


def summary() -> dict:
    """For the UI and `maxxing 2fa status` (no secret)."""
    from . import twofactor
    return {"required": required(),
            "telegram": {"available": twofactor.available(), "on": twofactor.is_on()},
            "totp": {"on": totp_on()},
            "passkeys": [{k: p.get(k) for k in ("id", "name", "rp_id", "created", "last_used")} for p in passkeys()],
            "passkey_login": passkey_login_flag() and bool(passkeys()),
            "passkey_user": config.get_secret("passkey_user") or None,     # WebAuthn user handle (Signal API)
            "recovery_left": recovery_left()}


def login_methods(rp_id: str | None) -> list[str]:
    """What a sign-in challenge offers, in the order the page shows them. "passkey" only when a passkey was made
    for the host the browser uses (`rp_id`)."""
    from . import twofactor
    out = []
    if rp_id and any(p.get("rp_id") == rp_id for p in passkeys()):
        out.append("passkey")
    if totp_on():
        out.append("totp")
    if twofactor.enabled():
        out.append("telegram")
    if recovery_left():
        out.append("recovery")
    return out


def _after_removal() -> None:
    """The last app method is gone: its recovery codes go too; nothing left at all: trusted browsers are forgotten."""
    if not app_on():
        config.set_secret("recovery_codes", None)
    if not passkeys():
        set_passkey_login(True)                                # back to the default for the next passkey
    if not required():
        from . import twofactor
        twofactor.forget_devices()


# ---- authenticator app (TOTP) ----------------------------------------------------------------
def _account() -> str:
    host = urlsplit(str(config.load_config().get("public_url") or "")).hostname
    if host:
        return host
    import socket
    return socket.gethostname() or "server"


def totp_begin() -> dict:
    """A new secret to scan; on only after `totp_confirm` with a code from it (a typo in the app cannot lock the
    owner out). Replaces a setup in progress, never the secret in use."""
    secret = totp.new_secret()
    with _lock:
        _totp_setup.clear()
        _totp_setup.update(secret=secret, expires=time.time() + SETUP_TTL)
    return {"secret": secret, "uri": totp.uri(secret, _account(), ISSUER), "expires_in": SETUP_TTL}


def totp_confirm(code: str) -> str:
    """-> "ok" (on now), "bad_code" or "expired" (no setup in progress)."""
    with _lock:
        secret, expires = _totp_setup.get("secret"), _totp_setup.get("expires", 0)
        if not secret or time.time() > expires:
            _totp_setup.clear()
            return "expired"
        step = totp.verify(secret, code)
        if step is None:
            return "bad_code"
        _totp_setup.clear()
    config.set_secrets({"totp_secret": secret, "totp_last_step": step})
    return "ok"


def totp_off() -> bool:
    was = totp_on()
    config.set_secrets({"totp_secret": None, "totp_last_step": None})
    with _lock:
        _totp_setup.clear()
    _after_removal()
    return was


def _check_totp(code: str) -> bool:
    with config._lock:                                         # noqa: SLF001 - one code, one use, across processes
        s = config.load_secrets()
        secret = s.get("totp_secret")
        if not secret:
            return False
        try:
            last = int(s.get("totp_last_step") or -1)
        except (TypeError, ValueError):
            last = -1
        step = totp.verify(str(secret), code, last)
        if step is None:
            return False
        config.set_secret("totp_last_step", step)
    return True


# ---- recovery codes --------------------------------------------------------------------------
def _norm(code: str) -> str:
    return re.sub(r"[\s-]", "", code or "").lower()


def _hash(code: str) -> str:
    return hashlib.sha256(_norm(code).encode()).hexdigest()


def is_recovery_format(code: str) -> bool:
    return bool(_RECOVERY_RE.fullmatch(_norm(code)))


def new_recovery_codes() -> list[str]:
    """Ten fresh codes (shown once): the old ones stop working."""
    codes = ["".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10)) for _ in range(RECOVERY_COUNT)]
    codes = [f"{c[:5]}-{c[5:]}" for c in codes]
    config.set_secret("recovery_codes", [_hash(c) for c in codes])
    return codes


def _use_recovery(code: str) -> bool:
    if not is_recovery_format(code):
        return False
    h = _hash(code)
    with config._lock:                                         # noqa: SLF001
        stored = config.load_secrets().get("recovery_codes")
        if not isinstance(stored, list):
            return False
        hit = next((x for x in stored if isinstance(x, str) and hmac.compare_digest(x, h)), None)
        if hit is None:
            return False
        stored.remove(hit)
        config.set_secret("recovery_codes", stored or None)
    return True


def check_code(code: str) -> str | None:
    """A code typed at sign-in that is not Telegram's: "totp" or "recovery" when it is right (and now used), else
    None."""
    given = (code or "").strip()
    if totp_on() and re.fullmatch(r"[0-9]{3} ?[0-9]{3}", given) and _check_totp(given.replace(" ", "")):
        return "totp"
    if _use_recovery(given):
        return "recovery"
    return None


# ---- passkeys (WebAuthn) ---------------------------------------------------------------------
def rp_for(request) -> tuple[str, str] | None:
    """(relying party id, origin) of the page that sent `request`, or None when passkeys cannot work there: the
    browser allows them on https with a host name, and on localhost (secure context); never on a bare IP."""
    scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").split(",")[0].strip().lower()
    host = request.headers.get("host") or ""
    hostname = (urlsplit(f"//{host}").hostname or "").lower()
    if not hostname:
        return None
    try:
        ipaddress.ip_address(hostname)
        return None
    except ValueError:
        pass
    local = hostname == "localhost" or hostname.endswith(".localhost")
    if scheme != "https" and not local:
        return None
    return hostname, f"{scheme}://{host.lower()}"


def why_no_passkey(request) -> str:
    """Why `rp_for` refused: "ip" (an address, not a name) or "http" (no TLS)."""
    host = (urlsplit(f"//{request.headers.get('host') or ''}").hostname or "")
    try:
        ipaddress.ip_address(host)
        return "ip"
    except ValueError:
        return "http"


def _b64(data: bytes) -> str:
    from webauthn.helpers import bytes_to_base64url
    return bytes_to_base64url(data)


def _user_handle() -> bytes:
    from webauthn.helpers import base64url_to_bytes
    with config._lock:                                         # noqa: SLF001
        h = config.get_secret("passkey_user")
        if not h:
            h = _b64(secrets.token_bytes(16))
            config.set_secret("passkey_user", h)
    return base64url_to_bytes(str(h))


def _prune_reg(now: float) -> None:
    for k in [k for k, v in _reg.items() if now > v["expires"]]:
        del _reg[k]


def registration_options(rp: tuple[str, str]) -> dict:
    """The options of `navigator.credentials.create()` for a new passkey of this server (JSON-ready)."""
    from webauthn import generate_registration_options, options_to_json
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                          ResidentKeyRequirement, UserVerificationRequirement)
    rp_id, origin = rp
    name = str((config.load_config().get("profile") or {}).get("name") or "").strip() or "owner"
    opts = generate_registration_options(
        rp_id=rp_id, rp_name=ISSUER, user_id=_user_handle(), user_name=name[:NAME_MAX],
        user_display_name=f"{name[:NAME_MAX]} ({ISSUER})", timeout=WEBAUTHN_TIMEOUT_MS,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED, user_verification=UserVerificationRequirement.PREFERRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(p["id"]))
                             for p in passkeys() if p.get("rp_id") == rp_id])
    now = time.time()
    with _lock:
        _prune_reg(now)
        while len(_reg) >= 5:                                  # a few tabs at most: the oldest prompt gives way
            del _reg[min(_reg, key=lambda k: _reg[k]["expires"])]
        _reg[_b64(opts.challenge)] = {"rp_id": rp_id, "origin": origin, "expires": now + WEBAUTHN_TTL}
    return json.loads(options_to_json(opts))


def _client_challenge(credential: dict) -> str:
    """The challenge the browser signed (clientDataJSON), to find the matching prompt."""
    from webauthn.helpers import base64url_to_bytes
    try:
        data = json.loads(base64url_to_bytes(credential["response"]["clientDataJSON"]))
        return str(data.get("challenge") or "")
    except Exception:  # noqa: BLE001 - any malformed credential is just refused
        return ""


def _default_name(aaguid: str, ua: str) -> str:
    """The provider of a known AAGUID ("Bitwarden"), else the browser and system it was made in."""
    if aaguid in PROVIDERS:
        return PROVIDERS[aaguid]
    from .twofactor import short_ua
    where = short_ua(ua) if ua else ""
    return f"Passkey · {where}" if where and where != "?" else "Passkey"


def register(credential: dict, name: str, rp: tuple[str, str], ua: str = "") -> dict | None:
    """Verifies the browser's answer to `registration_options` and stores the passkey -> its public row, or None
    (no matching prompt, wrong origin, bad signature...). No `name`: `_default_name`."""
    from webauthn import verify_registration_response
    from webauthn.helpers import base64url_to_bytes
    ch = _client_challenge(credential)
    with _lock:
        _prune_reg(time.time())
        pending = _reg.pop(ch, None)
    if not pending or (pending["rp_id"], pending["origin"]) != rp:
        return None
    try:
        v = verify_registration_response(credential=credential, expected_challenge=base64url_to_bytes(ch),
                                         expected_rp_id=rp[0], expected_origin=rp[1])
    except Exception as e:  # noqa: BLE001
        log.info("passkey registration refused: %s", e)
        return None
    transports = (credential.get("response") or {}).get("transports")
    row = {"id": _b64(v.credential_id), "public_key": _b64(v.credential_public_key), "sign_count": v.sign_count,
           "name": (name or "").strip()[:NAME_MAX] or _default_name(str(v.aaguid or ""), ua), "rp_id": rp[0],
           "transports": [t for t in transports if isinstance(t, str)][:8] if isinstance(transports, list) else [],
           "created": int(time.time()), "last_used": None}
    with config._lock:                                         # noqa: SLF001
        rows = passkeys()
        if any(p["id"] == row["id"] for p in rows):
            return None
        if len(rows) >= PASSKEYS_MAX:
            return None
        config.set_secret("passkeys", rows + [row])
        set_passkey_login(True)                                # a new passkey signs in alone (Settings turns it off)
    return {k: row[k] for k in ("id", "name", "rp_id", "created", "last_used")}


def rename_passkey(pid: str, name: str) -> bool:
    with config._lock:                                         # noqa: SLF001
        rows = passkeys()
        hit = next((p for p in rows if p["id"] == pid), None)
        if hit is None:
            return False
        hit["name"] = (name or "").strip()[:NAME_MAX] or hit["name"]
        config.set_secret("passkeys", rows)
    return True


def remove_passkey(pid: str) -> bool:
    with config._lock:                                         # noqa: SLF001
        rows = passkeys()
        left = [p for p in rows if p["id"] != pid]
        if len(left) == len(rows):
            return False
        config.set_secret("passkeys", left or None)
    _after_removal()
    return True


def authentication_options(rp_id: str, verify_user: bool = False) -> tuple[dict, bytes] | None:
    """The options of `navigator.credentials.get()` for a sign-in on `rp_id` and the challenge to keep with the
    sign-in request; None when no passkey was made for that host. `verify_user`: the passkey must check its user
    (passkey-only sign-in)."""
    from webauthn import generate_authentication_options, options_to_json
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import (AuthenticatorTransport, PublicKeyCredentialDescriptor,
                                          UserVerificationRequirement)
    mine = [p for p in passkeys() if p.get("rp_id") == rp_id]
    if not mine:
        return None
    known = {t.value for t in AuthenticatorTransport}

    def desc(p: dict) -> PublicKeyCredentialDescriptor:
        ts = [AuthenticatorTransport(t) for t in p.get("transports") or [] if t in known]
        return PublicKeyCredentialDescriptor(id=base64url_to_bytes(p["id"]), transports=ts or None)
    opts = generate_authentication_options(rp_id=rp_id, timeout=WEBAUTHN_TIMEOUT_MS,
                                           allow_credentials=[desc(p) for p in mine],
                                           user_verification=UserVerificationRequirement.REQUIRED if verify_user
                                           else UserVerificationRequirement.PREFERRED)
    return json.loads(options_to_json(opts)), opts.challenge


def check_assertion(credential: dict, challenge: bytes, rp: tuple[str, str], verify_user: bool = False) -> bool:
    """Verifies a sign-in answer against the challenge kept with the sign-in request; updates the signature counter
    (a cloned authenticator whose counter goes back is refused by the library). `verify_user`: the authenticator
    must say it checked its user (UV flag)."""
    from webauthn import verify_authentication_response
    cid = str(credential.get("id") or credential.get("rawId") or "") if isinstance(credential, dict) else ""
    row = next((p for p in passkeys() if p["id"] == cid and p.get("rp_id") == rp[0]), None)
    if row is None:
        return False
    from webauthn.helpers import base64url_to_bytes
    try:
        v = verify_authentication_response(credential=credential, expected_challenge=challenge, expected_rp_id=rp[0],
                                           expected_origin=rp[1], credential_public_key=base64url_to_bytes(row["public_key"]),
                                           credential_current_sign_count=int(row.get("sign_count") or 0),
                                           require_user_verification=verify_user)
    except Exception as e:  # noqa: BLE001
        log.info("passkey sign-in refused: %s", e)
        return False
    with config._lock:                                         # noqa: SLF001
        rows = passkeys()
        for p in rows:
            if p["id"] == cid:
                p["sign_count"], p["last_used"] = v.new_sign_count, int(time.time())
        config.set_secret("passkeys", rows)
    return True


# ---- passkey-only sign-in ----------------------------------------------------------------------
def login_options(rp: tuple[str, str]) -> dict | None:
    """Options of a passkey-only sign-in prompt for this host (kept LOGIN_PROMPTS_MAX at most, WEBAUTHN_TTL)."""
    if not passkey_login_on(rp[0]):
        return None
    got = authentication_options(rp[0], verify_user=True)
    if got is None:
        return None
    now = time.time()
    with _lock:
        for k in [k for k, v in _login.items() if now > v["expires"]]:
            del _login[k]
        while len(_login) >= LOGIN_PROMPTS_MAX:
            del _login[min(_login, key=lambda k: _login[k]["expires"])]
        _login[_b64(got[1])] = {"rp_id": rp[0], "origin": rp[1], "expires": now + WEBAUTHN_TTL}
    return got[0]


def login_check(credential: dict, rp: tuple[str, str]) -> str:
    """A passkey-only sign-in answer -> "ok", "unknown" (no such passkey here: the page tells the password manager,
    Signal API) or "bad". Needs a prompt of this host (answerable once), the option still on, a passkey that
    verified its user."""
    from webauthn.helpers import base64url_to_bytes
    ch = _client_challenge(credential) if isinstance(credential, dict) else ""
    with _lock:
        pending = _login.pop(ch, None)
    if not pending or time.time() > pending["expires"] or (pending["rp_id"], pending["origin"]) != rp:
        return "bad"
    if not passkey_login_on(rp[0]):
        return "bad"
    cid = str(credential.get("id") or "")
    if not any(p["id"] == cid and p.get("rp_id") == rp[0] for p in passkeys()):
        return "unknown"
    try:
        challenge = base64url_to_bytes(ch)
    except Exception:  # noqa: BLE001
        return "bad"
    return "ok" if check_assertion(credential, challenge, rp, verify_user=True) else "bad"


def accepted(rp_id: str) -> dict:
    """The passkeys this host accepts, for the Signal API (password managers hide the others)."""
    return {"rp_id": rp_id, "user": config.get_secret("passkey_user") or None,
            "ids": [p["id"] for p in passkeys() if p.get("rp_id") == rp_id]}


# ---- confirming a sensitive action with a passkey ("sudo") -------------------------------------
def _session_key(cookie: str | None) -> str:
    return hashlib.sha256((cookie or "").encode()).hexdigest()


def sudo_options(cookie: str | None, rp: tuple[str, str]) -> dict | None:
    """Options of a passkey confirmation for this browser session (the last prompt only)."""
    got = authentication_options(rp[0], verify_user=True)
    if got is None or not cookie:
        return None
    now = time.time()
    with _lock:
        for k in [k for k, v in _reauth.items() if now > v["expires"]]:
            del _reauth[k]
        _reauth[_session_key(cookie)] = {"challenge": got[1], "rp_id": rp[0], "origin": rp[1],
                                         "expires": now + WEBAUTHN_TTL}
    return got[0]


def sudo_check(cookie: str | None, credential: dict, rp: tuple[str, str]) -> bool:
    """A passkey confirmation of this session: right -> the password is not asked for SUDO_TTL."""
    k = _session_key(cookie)
    with _lock:
        pending = _reauth.pop(k, None)
    if not cookie or not pending or time.time() > pending["expires"] or (pending["rp_id"], pending["origin"]) != rp:
        return False
    if not check_assertion(credential, pending["challenge"], rp, verify_user=True):
        return False
    with _lock:
        _sudo[k] = time.time() + SUDO_TTL
    return True


def sudo_active(cookie: str | None) -> bool:
    if not cookie:
        return False
    with _lock:
        until = _sudo.get(_session_key(cookie), 0)
    return time.time() < until


def sudo_end_all() -> None:
    """The password changed or two-step sign-in was reset: no confirmation stands any more."""
    with _lock:
        _sudo.clear()
        _reauth.clear()


# ---- way out ---------------------------------------------------------------------------------
def off_all() -> None:
    """`maxxing 2fa off`: the authenticator app, every passkey and the recovery codes (Telegram: twofactor.set_on)."""
    config.set_secrets({"totp_secret": None, "totp_last_step": None, "passkeys": None, "recovery_codes": None})
    set_passkey_login(True)
    with _lock:
        _totp_setup.clear()
        _reg.clear()
        _login.clear()
        _reauth.clear()
        _sudo.clear()


def reset() -> None:
    """Tests."""
    with _lock:
        _totp_setup.clear()
        _reg.clear()
        _login.clear()
        _reauth.clear()
        _sudo.clear()
