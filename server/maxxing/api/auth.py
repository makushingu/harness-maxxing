"""Auth & first-run setup (public endpoints). See docs/dev/API.md#auth--setup."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import __version__, bus, config, mfa, security, twofactor
from . import settings as settings_api

router = APIRouter(prefix="/api/auth", tags=["auth"], dependencies=[Depends(security.csrf_only)])


class SetupIn(BaseModel):
    token: str
    password: str


class LoginIn(BaseModel):
    password: str


class TwoFactorIn(BaseModel):
    challenge: str
    code: str | None = None
    passkey: dict | None = None         # the answer of navigator.credentials.get() (PublicKeyCredential JSON)
    trust: bool = True


class ChallengeIn(BaseModel):
    challenge: str


class CodeIn(BaseModel):
    code: str


class CurrentIn(BaseModel):
    password: str = ""


class PasskeyIn(BaseModel):
    credential: dict
    name: str = ""


class PasskeyName(BaseModel):
    name: str


class PasskeyLoginIn(BaseModel):
    credential: dict
    trust: bool = True


class PasskeyLoginSet(BaseModel):
    enabled: bool
    password: str = ""


class TwoFactorSet(BaseModel):
    enabled: bool
    password: str | None = None         # the current password: needed to turn it off


class PasswordIn(BaseModel):
    current: str
    new: str


def _check_strength(pw: str) -> None:
    if len(pw) < security.MIN_PASSWORD:
        raise HTTPException(400, detail={"error": "weak_password",
                                         "message": f"Use at least {security.MIN_PASSWORD} characters"})
    try:
        pw.encode()
    except UnicodeEncodeError:                        # a lone surrogate ("\ud800" is valid JSON): hashing raised, 500
        raise HTTPException(400, detail={"error": "invalid_password",    # not bad_password: that one means a wrong current
                                         "message": "The password has a character that cannot be stored"}) from None


@router.get("/state")
async def state(request: Request):
    cfg = config.load_config()
    rp = mfa.rp_for(request)
    return {"setup_required": not security.password_is_set(),
            "passkey_login": mfa.passkey_login_on(rp[0] if rp else None),
            "authenticated": security.is_authenticated(request),
            "version": __version__,
            "onboarding_completed": bool(cfg.get("onboarding_completed")),
            "language": cfg.get("language", "en"),
            "look": settings_api.look()}


@router.post("/setup")
async def setup(body: SetupIn, request: Request, response: Response):
    async with _SETUP_LOCK:                       # set_password runs in a thread: two setups never interleave
        return await _setup(body, request, response)


_SETUP_LOCK = asyncio.Lock()


async def _setup(body: SetupIn, request: Request, response: Response):
    if security.password_is_set():
        raise HTTPException(409, detail={"error": "already_setup", "message": "Already configured - sign in"})
    if not security.check_setup_token(body.token):
        raise HTTPException(403, detail={"error": "bad_token",
                                         "message": "Invalid or expired setup link - run `maxxing setup-link` "
                                                    "on the server for a fresh one"})
    _check_strength(body.password)
    await asyncio.to_thread(security.set_password, body.password)
    security.clear_setup_token()
    security.set_cookie(response, request)
    return {"ok": True}


_SCRYPT_SLOTS = asyncio.Semaphore(2)          # scrypt is slow on purpose: off the event loop, 2 at a time


async def _verify(password: str) -> bool:
    stored = config.get_secret("password_hash")
    if not stored:
        return False
    async with _SCRYPT_SLOTS:
        return await asyncio.to_thread(security.verify_password, password, stored)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    key = security.client_key(request)
    trusted = twofactor.device_trusted(request.cookies.get(twofactor.DEVICE_COOKIE))
    refusal, n = security.begin_attempt(key, trusted)  # before scrypt: a blocked client is never checked
    if refusal == "client":
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many attempts - try again in 15 min"})
    if refusal == "global":
        raise HTTPException(429, detail={"error": "throttled",
                                         "message": "Too many sign-in attempts on this server - try again in a few seconds"})
    ok = await _verify(body.password)
    delay = security.end_attempt(key, ok)
    if ok:
        if mfa.required() and not trusted:
            return {"ok": False, "two_factor": await _challenge("login", request)}
        security.set_cookie(response, request)
        _alert(request, "Signed in", loud=False)
        return {"ok": True}
    if n == 3:
        _alert(request, f"{n} wrong passwords", loud=True)
    await asyncio.sleep(delay)
    raise HTTPException(401, detail={"error": "bad_password", "message": "Wrong password"})


async def _challenge(purpose: str, request: Request) -> dict:
    rp = mfa.rp_for(request)
    methods = tuple(mfa.login_methods(rp[0] if rp else None)) if purpose == "login" else ("telegram",)
    try:
        c = await asyncio.to_thread(twofactor.start, purpose, security.client_key(request),
                                    request.headers.get("user-agent", "?"), methods)
    except twofactor.Refused as e:
        raise HTTPException(429 if e.error == "throttled" else 503,
                            detail={"error": e.error, "message": e.message}) from None
    return {"challenge": c.id, "expires_in": round(c.expires - c.created), "methods": list(c.methods)}


_VIA = {"telegram": "Signed in (approved in Telegram)", "code": "Signed in (Telegram code)",
        "totp": "Signed in (authenticator app)", "passkey": "Signed in (passkey)",
        "recovery": "Signed in with a recovery code"}


@router.post("/two-factor/passkey")
async def passkey_prompt(body: ChallengeIn, request: Request):
    """The options of navigator.credentials.get() for a waiting sign-in request (a new prompt replaces the last)."""
    c = twofactor.pending(body.challenge)
    if c is None or c.purpose != "login":
        raise HTTPException(410, detail={"error": "expired", "message": "The request expired - sign in again"})
    rp = mfa.rp_for(request)
    got = await asyncio.to_thread(mfa.authentication_options, rp[0]) if rp and "passkey" in c.methods else None
    if got is None:
        raise HTTPException(409, detail={"error": "passkey_unavailable",
                                         "message": "No passkey for this address - use another method"})
    c.webauthn = got[1]
    return got[0]


@router.post("/two-factor")
async def two_factor(body: TwoFactorIn, request: Request, response: Response):
    """Poll a challenge (or send its code): pending -> {status}; approved -> the cookie (sign-in) or on (enable)."""
    # before check(): a caller without a session must not consume an approved "enable" request (or spend its code tries)
    if twofactor.purpose(body.challenge) == "enable" and not security.is_authenticated(request):
        raise HTTPException(401, detail={"error": "auth_required", "message": "Sign in required"})
    if body.passkey is not None:
        await _passkey_answer(body, request)
    status, c = twofactor.check(body.challenge, body.code,
                                other=mfa.check_code if twofactor.purpose(body.challenge) == "login" else None)
    if c is not None and c.purpose == "enable" and not security.is_authenticated(request):
        raise HTTPException(401, detail={"error": "auth_required", "message": "Sign in required"})
    if status == "pending":
        return {"ok": False, "status": "pending", "expires_in": max(0, int(c.expires - time.time()))}
    if status == "bad_code":
        raise HTTPException(400, detail={"error": "bad_code", "message": "Wrong code",
                                         "tries_left": twofactor.CODE_TRIES - c.tries})
    if status == "codes_paused":
        raise HTTPException(429, detail={"error": "codes_paused",
                                         "message": "Too many wrong codes on this server - use the Allow button in "
                                                    "Telegram, or try a code again in an hour"})
    if status == "denied":
        raise HTTPException(403, detail={"error": "denied", "message": "Sign-in denied in Telegram"})
    if status == "expired":
        raise HTTPException(410, detail={"error": "expired", "message": "The request expired - sign in again"})
    if c.purpose == "enable":
        await asyncio.to_thread(twofactor.set_on, True)
        twofactor.set_device_cookie(response, request)          # this browser stays trusted
        await asyncio.to_thread(twofactor.notify, "on")
        bus.invalidate("telegram")
        return {"ok": True, "status": "approved"}
    security.set_cookie(response, request)
    if body.trust:
        twofactor.set_device_cookie(response, request)
    _alert(request, _VIA.get(c.via, "Signed in"), loud=c.via == "recovery")
    if c.via == "recovery":
        return {"ok": True, "status": "approved", "recovery_left": mfa.recovery_left()}
    return {"ok": True, "status": "approved"}


async def _passkey_answer(body: TwoFactorIn, request: Request) -> None:
    """Checks a passkey answer against the prompt kept with the request; right -> approved (the check that follows
    hands the cookie), wrong -> counts like a wrong code."""
    c = twofactor.pending(body.challenge)
    if c is None or c.purpose != "login":
        raise HTTPException(410, detail={"error": "expired", "message": "The request expired - sign in again"})
    rp, challenge = mfa.rp_for(request), c.webauthn
    c.webauthn = None                                          # one answer per prompt
    ok = bool(rp and challenge and "passkey" in c.methods
              and await asyncio.to_thread(mfa.check_assertion, body.passkey, challenge, rp))
    if ok:
        twofactor.approve(body.challenge, "passkey")
        return
    if not twofactor.failed(body.challenge):
        raise HTTPException(410, detail={"error": "expired", "message": "The request expired - sign in again"})
    raise HTTPException(400, detail={"error": "bad_passkey", "message": "This passkey was not accepted",
                                     "tries_left": twofactor.CODE_TRIES - c.tries})


@router.put("/two-factor", dependencies=[Depends(security.require_auth)])
async def set_two_factor(body: TwoFactorSet, request: Request):
    """On = a challenge first (approve it in Telegram, then poll POST /two-factor); off = the current password (a
    stolen cookie alone cannot remove the second step), then a notice in Telegram and the feed."""
    if not body.enabled:
        if not twofactor.is_on():
            return {"ok": True, "enabled": False}
        await _check_current(request, body.password or "")
        await asyncio.to_thread(twofactor.notify, "off_ui")         # before: the bridge still answers
        await asyncio.to_thread(twofactor.set_on, False)
        _alert(request, "Two-step sign-in turned off", loud=True)
        bus.invalidate("telegram")
        return {"ok": True, "enabled": False}
    if not twofactor.available():
        raise HTTPException(409, detail={"error": "not_linked", "message": "Link a Telegram chat first"})
    if twofactor.is_on():
        return {"ok": True, "enabled": True}
    return {"ok": False, "two_factor": await _challenge("enable", request)}


@router.post("/two-factor/forget-browsers", dependencies=[Depends(security.require_auth)])
async def forget_browsers(request: Request, response: Response):
    """Every trusted browser asks again, except this one."""
    await asyncio.to_thread(twofactor.forget_devices)
    if mfa.required():
        twofactor.set_device_cookie(response, request)
    return {"ok": True}


# ---- sign-in with a passkey alone --------------------------------------------------------------
@router.post("/passkey-login/options")
async def passkey_login_options(request: Request):
    """Public: the options of a passkey-only sign-in (user verification required) for this host."""
    rp = mfa.rp_for(request)
    opts = await asyncio.to_thread(mfa.login_options, rp) if rp else None
    if opts is None:
        raise HTTPException(409, detail={"error": "passkey_login_off", "message": "Sign in with the password"})
    return opts


@router.post("/passkey-login")
async def passkey_login(body: PasskeyLoginIn, request: Request, response: Response):
    """Public: a passkey answer instead of the password and the second step. Throttled like a password: a wrong
    answer counts as a failed sign-in of this client."""
    key = security.client_key(request)
    trusted = twofactor.device_trusted(request.cookies.get(twofactor.DEVICE_COOKIE))
    refusal, n = security.begin_attempt(key, trusted)
    if refusal == "client":
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many attempts - try again in 15 min"})
    if refusal == "global":
        raise HTTPException(429, detail={"error": "throttled",
                                         "message": "Too many sign-in attempts on this server - try again in a few seconds"})
    rp = mfa.rp_for(request)
    res = await asyncio.to_thread(mfa.login_check, body.credential, rp) if rp else "bad"
    delay = security.end_attempt(key, res == "ok")
    if res != "ok":
        if n == 3:
            _alert(request, f"{n} failed sign-ins", loud=True)
        await asyncio.sleep(delay)
        if res == "unknown":                     # the page tells the password manager to hide it (Signal API)
            raise HTTPException(401, detail={"error": "unknown_passkey", "rp_id": rp[0],
                                             "message": "This passkey was removed from this server"})
        raise HTTPException(401, detail={"error": "bad_passkey", "message": "This passkey was not accepted"})
    security.set_cookie(response, request)
    if body.trust and mfa.required():
        twofactor.set_device_cookie(response, request)
    _alert(request, "Signed in with a passkey (no password)", loud=False)
    return {"ok": True, "accepted": mfa.accepted(rp[0])}


@router.post("/reauth/options", dependencies=[Depends(security.require_auth)])
async def reauth_options(request: Request):
    """Options of a passkey confirmation of a sensitive action (instead of the current password)."""
    rp = mfa.rp_for(request)
    opts = await asyncio.to_thread(mfa.sudo_options, request.cookies.get(security.COOKIE), rp) if rp else None
    if opts is None:
        raise HTTPException(409, detail={"error": "passkey_unavailable",
                                         "message": "No passkey for this address - type the password"})
    return opts


@router.post("/reauth", dependencies=[Depends(security.require_auth)])
async def reauth(body: PasskeyLoginIn, request: Request):
    """A passkey answer: this session does not need the current password for SUDO_TTL (not for a password change).
    Throttled with the current-password checks."""
    key = "pw:" + security.client_key(request)
    refusal, _ = security.begin_attempt(key)
    if refusal:
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many attempts - try again in 15 min"})
    rp = mfa.rp_for(request)
    ok = bool(rp) and await asyncio.to_thread(mfa.sudo_check, request.cookies.get(security.COOKIE), body.credential, rp)
    delay = security.end_attempt(key, ok)
    if not ok:
        await asyncio.sleep(delay)
        raise HTTPException(401, detail={"error": "bad_passkey", "message": "This passkey was not accepted"})
    return {"ok": True, "expires_in": mfa.SUDO_TTL}


@router.put("/passkey-login", dependencies=[Depends(security.require_auth)])
async def set_passkey_login(body: PasskeyLoginSet, request: Request):
    """On (the default once a passkey exists; turned back on here): the current password and a passkey of this
    host first. Off: at once."""
    if body.enabled:
        rp = mfa.rp_for(request)
        if not rp or not any(p.get("rp_id") == rp[0] for p in mfa.passkeys()):
            raise HTTPException(409, detail={"error": "no_passkey", "message": "Add a passkey on this address first"})
        await _check_current(request, body.password)
    await asyncio.to_thread(mfa.set_passkey_login, body.enabled)
    _alert(request, "Sign-in with a passkey alone " + ("turned on" if body.enabled else "turned off"), loud=True)
    bus.invalidate("telegram")
    return {"ok": True, "enabled": body.enabled}


# ---- authenticator app, passkeys, recovery codes (mfa.py) -------------------------------------
@router.get("/methods", dependencies=[Depends(security.require_auth)])
async def methods(request: Request):
    rp = mfa.rp_for(request)
    out = mfa.summary()
    out["passkey_here"] = {"ok": True, "rp_id": rp[0]} if rp else {"ok": False, "reason": mfa.why_no_passkey(request)}
    return out


async def _added(request: Request, what: str) -> list[str] | None:
    """A method was turned on: the first app method -> recovery codes (returned once). This browser is NOT made
    trusted: its next sign-in asks the new method, which proves it works (Trust this browser is offered there)."""
    _alert(request, what, loud=True)
    bus.invalidate("telegram")
    if mfa.recovery_left() == 0:
        return await asyncio.to_thread(mfa.new_recovery_codes)
    return None


def _removed(request: Request, what: str) -> None:
    _alert(request, what, loud=True)
    bus.invalidate("telegram")


@router.post("/totp/setup", dependencies=[Depends(security.require_auth)])
async def totp_setup():
    """A new secret to scan (not active until confirmed with a code)."""
    if mfa.totp_on():
        raise HTTPException(409, detail={"error": "already_on", "message": "Remove the authenticator app first"})
    return await asyncio.to_thread(mfa.totp_begin)


@router.post("/totp/confirm", dependencies=[Depends(security.require_auth)])
async def totp_confirm(body: CodeIn, request: Request):
    key = "totp:" + security.client_key(request)
    refusal, _ = security.begin_attempt(key)
    if refusal:
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many attempts - try again in 15 min"})
    res = await asyncio.to_thread(mfa.totp_confirm, body.code)
    security.end_attempt(key, res == "ok")
    if res == "expired":
        raise HTTPException(410, detail={"error": "expired", "message": "The setup expired - start again"})
    if res != "ok":
        raise HTTPException(400, detail={"error": "bad_code", "message": "Wrong code - check the time of this device"})
    codes = await _added(request, "Two-step sign-in: authenticator app added")
    return {"ok": True, **({"recovery_codes": codes} if codes else {})}


@router.delete("/totp", dependencies=[Depends(security.require_auth)])
async def totp_remove(body: CurrentIn, request: Request):
    if not mfa.totp_on():
        return {"ok": True}
    await _check_current(request, body.password)
    await asyncio.to_thread(mfa.totp_off)
    _removed(request, "Two-step sign-in: authenticator app removed")
    return {"ok": True}


def _rp_or_409(request: Request) -> tuple[str, str]:
    rp = mfa.rp_for(request)
    if rp is None:
        raise HTTPException(409, detail={"error": "passkey_unavailable", "reason": mfa.why_no_passkey(request),
                                         "message": "Passkeys need an https address with a name (or localhost)"})
    return rp


@router.post("/passkeys/options", dependencies=[Depends(security.require_auth)])
async def passkey_options(request: Request):
    rp = _rp_or_409(request)
    if len(mfa.passkeys()) >= mfa.PASSKEYS_MAX:
        raise HTTPException(409, detail={"error": "too_many", "message": f"At most {mfa.PASSKEYS_MAX} passkeys"})
    return await asyncio.to_thread(mfa.registration_options, rp)


@router.post("/passkeys", dependencies=[Depends(security.require_auth)])
async def passkey_add(body: PasskeyIn, request: Request):
    rp = _rp_or_409(request)
    row = await asyncio.to_thread(mfa.register, body.credential, body.name, rp, request.headers.get("user-agent", ""))
    if row is None:
        raise HTTPException(400, detail={"error": "bad_passkey", "message": "This passkey could not be added - try again"})
    codes = await _added(request, f"Two-step sign-in: passkey added ({row['name']})")
    return {"ok": True, "passkey": row, **({"recovery_codes": codes} if codes else {})}


@router.patch("/passkeys/{pid}", dependencies=[Depends(security.require_auth)])
async def passkey_rename(pid: str, body: PasskeyName):
    if not await asyncio.to_thread(mfa.rename_passkey, pid, body.name):
        raise HTTPException(404, detail={"error": "not_found", "message": "No such passkey"})
    bus.invalidate("telegram")
    return {"ok": True}


@router.delete("/passkeys/{pid}", dependencies=[Depends(security.require_auth)])
async def passkey_remove(pid: str, body: CurrentIn, request: Request):
    if not any(p["id"] == pid for p in mfa.passkeys()):
        raise HTTPException(404, detail={"error": "not_found", "message": "No such passkey"})
    await _check_current(request, body.password)
    await asyncio.to_thread(mfa.remove_passkey, pid)
    _removed(request, "Two-step sign-in: passkey removed")
    return {"ok": True}


@router.post("/recovery-codes", dependencies=[Depends(security.require_auth)])
async def recovery_codes(body: CurrentIn, request: Request):
    """Ten new codes (the old ones stop working); only with an authenticator app or a passkey on."""
    if not mfa.app_on():
        raise HTTPException(409, detail={"error": "no_app_method",
                                         "message": "Add an authenticator app or a passkey first"})
    await _check_current(request, body.password)
    codes = await asyncio.to_thread(mfa.new_recovery_codes)
    _alert(request, "Two-step sign-in: new recovery codes", loud=True)
    return {"ok": True, "recovery_codes": codes}


@router.post("/logout")
async def logout(request: Request, response: Response):
    await asyncio.to_thread(security.revoke_cookie, request.cookies.get(security.COOKIE))     # a copied cookie dies too
    response.delete_cookie(security.COOKIE, path="/")
    return {"ok": True}


async def _check_current(request: Request, password: str, passkey_ok: bool = True) -> None:
    """The current password of a signed-in request, or 429 / 401. `passkey_ok`: a passkey confirmation of this session
    (POST /reauth, a few minutes) stands in for it."""
    if passkey_ok and not password and mfa.sudo_active(request.cookies.get(security.COOKIE)):
        return
    # a stolen cookie must not become a way to guess the password: same throttle as the sign-in, own counter
    key = "pw:" + security.client_key(request)
    refusal, _ = security.begin_attempt(key)
    if refusal:
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many attempts - try again in 15 min"})
    ok = await _verify(password)
    delay = security.end_attempt(key, ok)
    if not ok:
        await asyncio.sleep(delay)
        raise HTTPException(401, detail={"error": "bad_password", "message": "Current password is wrong"})


@router.post("/password", dependencies=[Depends(security.require_auth)])
async def change_password(body: PasswordIn, request: Request, response: Response):
    await _check_current(request, body.current, passkey_ok=False)
    _check_strength(body.new)
    trusted = twofactor.device_trusted(request.cookies.get(twofactor.DEVICE_COOKIE))
    await asyncio.to_thread(security.set_password, body.new)                 # forgets every trusted browser too
    mfa.sudo_end_all()
    security.set_cookie(response, request)
    if trusted:
        twofactor.set_device_cookie(response, request)
    return {"ok": True}


def _alert(request: Request, what: str, loud: bool) -> None:
    """Sign-in alert to Telegram (no-op until the gateway is configured)."""
    try:
        from ..telegram import gateway
        ua = request.headers.get("user-agent", "?")[:90]
        ip = security.client_key(request)       # the peer uvicorn trusts (proxy headers only from 127.0.0.1)
        gateway.alert(f"Harness Maxxing: {what}\n{ip}\n{ua}", loud=loud)
    except Exception:
        pass
    try:
        from .. import feed
        ip = security.client_key(request)
        feed.system(what, f"{ip} · {request.headers.get('user-agent', '?')[:90]}", "warning" if loud else "info",
                    "security", group=None if loud else "signin")      # sign-ins fold into one row
    except Exception:
        pass
