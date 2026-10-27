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
        raise HTTPException(400, detail={"error": "bad_password",
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
    refusal, n = security.begin_attempt(key)          # before scrypt: a blocked client is never checked
    if refusal == "client":
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many attempts - try again in 15 min"})
    if refusal == "global":
        raise HTTPException(429, detail={"error": "throttled",
                                         "message": "Too many sign-in attempts on this server - try again in a few seconds"})
    ok = await _verify(body.password)
    delay = security.end_attempt(key, ok)
    if ok:
        if twofactor.enabled() and not twofactor.device_trusted(request.cookies.get(twofactor.DEVICE_COOKIE)):
            return {"ok": False, "two_factor": await _challenge("login", request)}
        security.set_cookie(response, request)
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
    """On = a challenge first (approve it in Telegram, then poll POST /two-factor); off = at once."""
    if not body.enabled:
        await asyncio.to_thread(twofactor.set_on, False)
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


@router.post("/password", dependencies=[Depends(security.require_auth)])
async def change_password(body: PasswordIn, request: Request, response: Response):
    # a stolen cookie must not become a way to guess the password: same throttle as the sign-in, own counter
    key = "pw:" + security.client_key(request)
    refusal, _ = security.begin_attempt(key)
    if refusal:
        raise HTTPException(429, detail={"error": "throttled", "message": "Too many attempts - try again in 15 min"})
    ok = await _verify(body.current)
    delay = security.end_attempt(key, ok)
    if not ok:
        await asyncio.sleep(delay)
        raise HTTPException(401, detail={"error": "bad_password", "message": "Current password is wrong"})
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
