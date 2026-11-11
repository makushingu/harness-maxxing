"""Auth & first-run setup (public endpoints). See docs/dev/API.md#auth--setup."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import __version__, bus, config, security, twofactor
from .. import twofactor_apps as apps
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
    trust: bool = True


class TwoFactorSet(BaseModel):
    enabled: bool
    password: str | None = None         # the current password: needed to turn it off


class PasswordIn(BaseModel):
    current: str
    new: str


class TicketIn(BaseModel):
    ticket: str


class CodeIn(BaseModel):
    ticket: str
    code: str
    trust: bool = True


class PasskeyIn(BaseModel):
    ticket: str
    credential: dict
    trust: bool = True


class PasswordOnly(BaseModel):
    password: str


class SetupCodeIn(BaseModel):
    setup: str
    code: str


class PasskeyAddIn(BaseModel):
    setup: str
    credential: dict
    name: str = ""


class PasskeyRemoveIn(BaseModel):
    id: str
    password: str


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
    return {"setup_required": not security.password_is_set(),
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
        if not trusted and (twofactor.enabled() or apps.any_on()):
            return {"ok": False, "two_factor": await _second_step(request)}
        security.set_cookie(response, request)
        _alert(request, "Signed in", loud=False)
        return {"ok": True}
    if n == 3:
        _alert(request, f"{n} wrong passwords", loud=True)
    await asyncio.sleep(delay)
    raise HTTPException(401, detail={"error": "bad_password", "message": "Wrong password"})


async def _second_step(request: Request) -> dict:
    """What the sign-in page offers after the right password: a Telegram request and / or a ticket for an
    authenticator code, a recovery code or a passkey."""
    _, rp_id = apps.origin_of(request)
    found = apps.methods(rp_id)
    out: dict = {"methods": [], "expires_in": apps.TTL}
    if twofactor.enabled():
        try:
            out.update(await _challenge("login", request))
            out["methods"].append("telegram")
        except HTTPException:
            if not apps.any_on():                       # Telegram is the only way: its error stands
                raise
    if apps.any_on():
        try:
            t = apps.new_ticket(security.client_key(request), telegram=out.get("challenge"))
        except apps.Refused as e:
            raise _refused(e) from None
        out["ticket"] = t.id
        out["methods"] += found + ["recovery"]
    return out


def _refused(e: apps.Refused) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.error, "message": e.message, **e.extra})


def _signed_in(request: Request, response: Response, ticket: apps.Ticket, trust: bool, how: str, loud: bool) -> dict:
    if ticket.telegram:
        twofactor.cancel(ticket.telegram)
    security.set_cookie(response, request)
    if trust:
        twofactor.set_device_cookie(response, request)
    _alert(request, f"Signed in ({how})", loud=loud)
    return {"ok": True, "status": "approved"}


@router.post("/two-factor/code")
async def two_factor_code(body: CodeIn, request: Request, response: Response):
    """Sign-in, second step: a code of the authenticator app, or a recovery code (one use)."""
    try:
        t, how = await asyncio.to_thread(apps.check_code, body.ticket, security.client_key(request), body.code)
    except apps.Refused as e:
        if apps.take_pause_alert():                 # someone who knows the password is guessing codes
            _alert(request, "Two-step sign-in: too many wrong codes, codes paused for an hour - the password is known, "
                            "change it", loud=True)
        raise _refused(e) from None
    if how == "recovery":
        return _signed_in(request, response, t, body.trust, f"recovery code, {apps.recovery_left()} left", loud=True)
    return _signed_in(request, response, t, body.trust, "authenticator app", loud=False)


@router.post("/two-factor/passkey/options")
async def two_factor_passkey_options(body: TicketIn, request: Request):
    _, rp_id = apps.origin_of(request)
    try:
        return {"options": await asyncio.to_thread(apps.passkey_options, body.ticket, security.client_key(request), rp_id)}
    except apps.Refused as e:
        raise _refused(e) from None


@router.post("/two-factor/passkey")
async def two_factor_passkey(body: PasskeyIn, request: Request, response: Response):
    origins, rp_id = apps.origin_of(request)
    try:
        t, key = await asyncio.to_thread(apps.check_passkey, body.ticket, security.client_key(request),
                                         body.credential, origins, rp_id)
    except apps.Refused as e:
        raise _refused(e) from None
    return _signed_in(request, response, t, body.trust, f"passkey {key.get('name') or ''}".strip(), loud=False)


# ---- Settings -> Security: authenticator app, passkeys, recovery codes (signed in + the current password) ----------
async def _forget_others(request: Request, response: Response) -> None:
    """A method was removed (a lost phone or key): every other trusted browser asks again, this one stays trusted."""
    await asyncio.to_thread(twofactor.forget_devices)
    if twofactor.enabled() or apps.any_on():
        twofactor.set_device_cookie(response, request)


def _label(request: Request) -> str:
    return apps.origin_of(request)[1] or "admin"


@router.get("/two-factor/methods", dependencies=[Depends(security.require_auth)])
async def two_factor_methods(request: Request):
    return {"telegram": twofactor.enabled(), **apps.summary(apps.origin_of(request)[1])}


@router.post("/two-factor/totp/setup", dependencies=[Depends(security.require_auth)])
async def totp_setup(body: PasswordOnly, request: Request):
    await _check_current(request, body.password)
    try:
        return apps.totp_setup(_label(request))
    except apps.Refused as e:
        raise _refused(e) from None


@router.post("/two-factor/totp", dependencies=[Depends(security.require_auth)])
async def totp_confirm(body: SetupCodeIn, request: Request, response: Response):
    try:
        codes = await asyncio.to_thread(apps.totp_confirm, body.setup, body.code)
    except apps.Refused as e:
        raise _refused(e) from None
    twofactor.set_device_cookie(response, request)               # this browser stays trusted
    _alert(request, "Two-step sign-in: authenticator app added", loud=True)
    bus.invalidate("two_factor")
    return {"ok": True, "recovery_codes": codes}


@router.post("/two-factor/totp/off", dependencies=[Depends(security.require_auth)])
async def totp_off(body: PasswordOnly, request: Request, response: Response):
    await _check_current(request, body.password)
    await asyncio.to_thread(apps.totp_off)
    await _forget_others(request, response)
    _alert(request, "Two-step sign-in: authenticator app removed", loud=True)
    bus.invalidate("two_factor")
    return {"ok": True}


@router.post("/two-factor/passkeys/options", dependencies=[Depends(security.require_auth)])
async def passkey_register_options(body: PasswordOnly, request: Request):
    await _check_current(request, body.password)
    origins, rp_id = apps.origin_of(request)
    try:
        return await asyncio.to_thread(apps.passkey_register_options, origins, rp_id, _label(request))
    except apps.Refused as e:
        raise _refused(e) from None


@router.post("/two-factor/passkeys", dependencies=[Depends(security.require_auth)])
async def passkey_register(body: PasskeyAddIn, request: Request, response: Response):
    _, rp_id = apps.origin_of(request)
    try:
        key, codes = await asyncio.to_thread(apps.passkey_register, body.setup, body.credential, body.name, rp_id)
    except apps.Refused as e:
        raise _refused(e) from None
    twofactor.set_device_cookie(response, request)
    _alert(request, f"Two-step sign-in: passkey added ({key['name']})", loud=True)
    bus.invalidate("two_factor")
    return {"ok": True, "passkey": {k: key[k] for k in ("id", "name", "rp_id", "created", "last_used")},
            "recovery_codes": codes}


@router.post("/two-factor/passkeys/remove", dependencies=[Depends(security.require_auth)])
async def passkey_remove(body: PasskeyRemoveIn, request: Request, response: Response):
    await _check_current(request, body.password)
    if not await asyncio.to_thread(apps.passkey_remove, body.id):
        raise HTTPException(404, detail={"error": "not_found", "message": "No such passkey"})
    await _forget_others(request, response)
    _alert(request, "Two-step sign-in: passkey removed", loud=True)
    bus.invalidate("two_factor")
    return {"ok": True}


@router.post("/two-factor/recovery-codes", dependencies=[Depends(security.require_auth)])
async def recovery_codes(body: PasswordOnly, request: Request):
    await _check_current(request, body.password)
    try:
        codes = await asyncio.to_thread(apps.regenerate_recovery_codes)
    except apps.Refused as e:
        raise _refused(e) from None
    _alert(request, "Two-step sign-in: new recovery codes (the old ones no longer work)", loud=True)
    bus.invalidate("two_factor")
    return {"recovery_codes": codes}


async def _challenge(purpose: str, request: Request) -> dict:
    try:
        c = await asyncio.to_thread(twofactor.start, purpose, security.client_key(request),
                                    request.headers.get("user-agent", "?"))
    except twofactor.Refused as e:
        raise HTTPException(429 if e.error == "throttled" else 503,
                            detail={"error": e.error, "message": e.message}) from None
    return {"challenge": c.id, "expires_in": twofactor.TTL}


@router.post("/two-factor")
async def two_factor(body: TwoFactorIn, request: Request, response: Response):
    """Poll a challenge (or send its code): pending -> {status}; approved -> the cookie (sign-in) or on (enable)."""
    # before check(): a caller without a session must not consume an approved "enable" request (or spend its code tries)
    if twofactor.purpose(body.challenge) == "enable" and not security.is_authenticated(request):
        raise HTTPException(401, detail={"error": "auth_required", "message": "Sign in required"})
    status, c = twofactor.check(body.challenge, body.code)
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
    _alert(request, "Signed in (approved in Telegram)" if c.via == "telegram" else "Signed in (Telegram code)",
           loud=False)
    return {"ok": True, "status": "approved"}


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
    if twofactor.enabled():
        twofactor.set_device_cookie(response, request)
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response):
    await asyncio.to_thread(security.revoke_cookie, request.cookies.get(security.COOKIE))     # a copied cookie dies too
    response.delete_cookie(security.COOKIE, path="/")
    return {"ok": True}


async def _check_current(request: Request, password: str) -> None:
    """The current password of a signed-in request, or 429 / 401."""
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
    await _check_current(request, body.current)
    _check_strength(body.new)
    trusted = twofactor.device_trusted(request.cookies.get(twofactor.DEVICE_COOKIE))
    await asyncio.to_thread(security.set_password, body.new)                 # forgets every trusted browser too
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
