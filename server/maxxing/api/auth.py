"""Auth & first-run setup (public endpoints). See docs/dev/API.md#auth--setup."""
from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import __version__, bus, config, security, twofactor
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


class CurrentIn(BaseModel):
    password: str


class CodeIn(BaseModel):
    code: str


class TotpOffIn(BaseModel):
    password: str
    code: str


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
    await asyncio.to_thread(security.set_cookie, response, request)
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
        if twofactor.required() and not trusted:
            return {"ok": False, "two_factor": await _challenge("login", request)}
        await asyncio.to_thread(security.set_cookie, response, request)
        _alert(request, "Signed in", loud=False)
        return {"ok": True}
    if n == 3:
        _alert(request, f"{n} wrong passwords", loud=True)
    await asyncio.sleep(delay)
    raise HTTPException(401, detail={"error": "bad_password", "message": "Wrong password"})


async def _challenge(purpose: str, request: Request) -> dict:
    try:
        c = await asyncio.to_thread(twofactor.start, purpose, security.client_key(request),
                                    request.headers.get("user-agent", "?"))
    except twofactor.Refused as e:
        raise HTTPException(429 if e.error == "throttled" else 503,
                            detail={"error": e.error, "message": e.message}) from None
    methods = ([] if c.silent else ["telegram"]) + (["totp"] if purpose == "login" and twofactor.totp_on() else [])
    return {"challenge": c.id, "expires_in": twofactor.TTL, "methods": methods}


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
    if status == "throttled":
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many attempts - try again in 15 min"})
    if status == "bad_code":
        await asyncio.sleep(c.delay)
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
    await asyncio.to_thread(security.set_cookie, response, request)
    if body.trust:
        twofactor.set_device_cookie(response, request)
    if c.via == "recovery":
        _alert(request, f"Signed in with a recovery code ({twofactor.recovery_left()} left)", loud=True)
    else:
        _alert(request, {"telegram": "Signed in (approved in Telegram)", "totp": "Signed in (authenticator app)"}
               .get(c.via, "Signed in (Telegram code)"), loud=False)
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
    if twofactor.required():
        twofactor.set_device_cookie(response, request)
    return {"ok": True}


async def _check_second(request: Request, check, code: str):
    """An app / recovery code typed by a signed-in request, counted like a password -> what `check` returned, or
    429 / 400."""
    key = "2f:" + security.client_key(request)
    refusal, _ = security.begin_attempt(key, trusted=True)
    if refusal:
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many attempts - try again in 15 min"})
    got = await asyncio.to_thread(check, code)
    delay = security.end_attempt(key, bool(got))
    if not got:
        await asyncio.sleep(delay)
        raise HTTPException(400, detail={"error": "bad_code", "message": "Wrong code"})
    return got


@router.get("/second-factor", dependencies=[Depends(security.require_auth)])
async def second_factor():
    return {"telegram": twofactor.enabled(), "totp": twofactor.totp_on(),
            "recovery_left": twofactor.recovery_left() if twofactor.required() else 0}


@router.post("/totp", dependencies=[Depends(security.require_auth)])
async def totp_begin(body: CurrentIn, request: Request):
    """Start enrolling an authenticator app: the secret is shown this once; POST /totp/confirm turns it on."""
    await _check_current(request, body.password)
    secret = await asyncio.to_thread(twofactor.totp_begin)
    return {"secret": secret, "uri": twofactor.totp_uri(secret, request.url.hostname or "")}


@router.post("/totp/confirm", dependencies=[Depends(security.require_auth)])
async def totp_confirm(body: CodeIn, request: Request, response: Response):
    codes = await _check_second(request, twofactor.totp_confirm, body.code)
    twofactor.set_device_cookie(response, request)              # this browser stays trusted
    _alert(request, "Authenticator app turned on for sign-in", loud=True)
    return {"ok": True, "recovery_codes": codes}


@router.post("/totp/off", dependencies=[Depends(security.require_auth)])
async def totp_off(body: TotpOffIn, request: Request):
    """The current password and an app or recovery code: a stolen cookie, or the password alone, cannot remove it."""
    if not twofactor.totp_on():
        return {"ok": True}
    await _check_current(request, body.password)
    await _check_second(request, twofactor.verify_second, body.code)
    await asyncio.to_thread(twofactor.totp_off)
    _alert(request, "Authenticator app turned off for sign-in", loud=True)
    return {"ok": True}


@router.post("/recovery-codes", dependencies=[Depends(security.require_auth)])
async def recovery_codes(body: CurrentIn, request: Request):
    """New recovery codes (shown this once); the old ones stop working."""
    await _check_current(request, body.password)
    if not twofactor.required():
        raise HTTPException(409, detail={"error": "no_second_factor", "message": "Turn on two-step sign-in first"})
    return {"recovery_codes": await asyncio.to_thread(twofactor.new_recovery_codes)}


@router.get("/devices", dependencies=[Depends(security.require_auth)])
async def devices(request: Request):
    """The browsers signed in. `legacy`: some signed in before this list existed (one entry for all of them)."""
    out = security.signins(request.cookies.get(security.COOKIE))
    for d in out["devices"]:
        d["label"] = twofactor.short_ua(d.pop("ua"))
    return out


@router.post("/devices/disconnect-others", dependencies=[Depends(security.require_auth)])
async def disconnect_others(request: Request, response: Response):
    old = request.cookies.get(security.COOKIE)
    keep = security.device_id(old)
    if keep is None:                                            # a cookie from before the list: this browser gets one
        new = await asyncio.to_thread(security.set_cookie, response, request)
        security.move_sockets(old, new)
        keep = security.device_id(new)
    await asyncio.to_thread(security.end_other_signins, keep)
    return {"ok": True}


@router.delete("/devices/{did}", dependencies=[Depends(security.require_auth)])
async def disconnect(did: str):
    if not await asyncio.to_thread(security.end_signin, did):
        raise HTTPException(404, detail={"error": "not_found", "message": "This browser is not signed in any more"})
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
    # signed in: only this client's own cap applies (the global one would let a stranger's wrong sign-ins block
    # the owner's password change, 2FA switch or terminal)
    refusal, _ = security.begin_attempt(key, trusted=True)
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
    old = request.cookies.get(security.COOKIE)
    await asyncio.to_thread(security.set_password, body.new)                 # forgets every trusted browser too
    new = await asyncio.to_thread(security.set_cookie, response, request)
    security.move_sockets(old, new)                                          # this browser's terminals stay open
    security.recheck_sockets()
    if trusted:
        twofactor.set_device_cookie(response, request)
    return {"ok": True}


def _alert(request: Request, what: str, loud: bool) -> None:
    """Sign-in alert to Telegram (no-op until the gateway is configured)."""
    ua = request.headers.get("user-agent", "?")[:90]
    ip = security.client_key(request)           # the peer uvicorn trusts (proxy headers only from 127.0.0.1)
    try:
        from ..telegram import gateway
        gateway.alert(f"Harness Maxxing: {what}\n{ip}\n{ua}", loud=loud)
    except Exception:
        pass
    try:
        from .. import feed
        feed.system(what, f"{ip} · {ua}", "warning" if loud else "info",
                    "security", group=None if loud else "signin")      # sign-ins fold into one row
    except Exception:
        pass
