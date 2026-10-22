"""General settings stored in config.json. See docs/dev/API.md#settings--secrets."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import bus, config, memory
from ..security import require_auth

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])

KEYS = ("timezone", "language", "public_url", "files_root", "presentation_default", "usage_widget", "git_page", "infra_page", "memory_max_lines",
        "result_line_hidden")
RESULT_FIELDS = ("model", "duration", "cost", "tokens", "cache")   # parts of the line under each answer
_URL = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[^\s]*)?$")


class SettingsIn(BaseModel):
    timezone: Optional[str] = None
    language: Optional[Literal["en", "fr"]] = None
    public_url: Optional[str] = None
    files_root: Optional[str] = None
    presentation_default: Optional[bool] = None
    usage_widget: Optional[bool] = None
    git_page: Optional[bool] = None
    infra_page: Optional[bool] = None
    memory_max_lines: Optional[int] = None
    result_line_hidden: Optional[list[Literal[RESULT_FIELDS]]] = None  # type: ignore[valid-type]


def _err(code: str, msg: str) -> HTTPException:
    return HTTPException(400, detail={"error": code, "message": msg})


def current() -> dict:
    cfg = config.load_config()
    return {"timezone": cfg.get("timezone") or "UTC", "language": cfg.get("language") or "en",
            "public_url": cfg.get("public_url") or "", "files_root": cfg.get("files_root") or "/root",
            "presentation_default": bool(cfg.get("presentation_default", False)),
            "usage_widget": bool(cfg.get("usage_widget", False)),
            "git_page": bool(cfg.get("git_page", False)),
            "infra_page": bool(cfg.get("infra_page", False)),
            "memory_max_lines": memory.max_lines(),
            "result_line_hidden": [f for f in RESULT_FIELDS if f in (cfg.get("result_line_hidden") or [])]}


ACCENTS = ("blue", "clay", "violet", "green", "amber", "rose")


class LookIn(BaseModel):
    theme: Literal["dark", "light", "system"]
    accent: Literal[ACCENTS]  # type: ignore[valid-type]
    tint: Literal["neutral", "tinted"] = "neutral"


def look() -> dict | None:
    """The look last chosen in a signed-in browser (theme, accent, tint): the sign-in page and browsers that never
    chose one show it. Not a secret - /api/auth/state returns it before sign-in."""
    data = config.load_config().get("look")
    try:
        return LookIn(**data).model_dump() if isinstance(data, dict) else None
    except ValueError:
        return None


@router.put("/look")
def put_look(body: LookIn):
    if body.model_dump() != look():
        config.update_config(look=body.model_dump())
    return {"ok": True, "look": look()}


PROFILE_COLORS = ("clay", "blue", "violet", "green", "amber", "rose", "teal", "zinc")   # = the task project swatches
_CONTROL = re.compile(r"[\x00-\x1f\x7f<>]")


class ProfileIn(BaseModel):
    name: str = ""
    color: str = ""
    emoji: str = ""


def profile() -> dict:
    """The user's pseudo (name, color, emoji): shown on their messages and used in notifications.
    Empty name = no pseudo (the UI says "You")."""
    data = config.load_config().get("profile")
    data = data if isinstance(data, dict) else {}
    return {"name": str(data.get("name") or ""), "color": str(data.get("color") or ""),
            "emoji": str(data.get("emoji") or "")}


def clean_profile(name: str, color: str, emoji: str) -> dict:
    """Validated pseudo: up to 32 printable characters without < >, a known color, an emoji or initials."""
    name = " ".join(_CONTROL.sub("", name or "").split())[:32]
    if color and color not in PROFILE_COLORS:
        raise _err("invalid_color", f"color: {', '.join(PROFILE_COLORS)} or empty")
    emoji = _CONTROL.sub("", (emoji or "").strip())
    if len(emoji) > 8 or any(c.isspace() for c in emoji):
        raise _err("invalid_emoji", "emoji: one emoji or initials (8 characters at most) or empty")
    return {"name": name, "color": color, "emoji": emoji}


@router.get("/profile")
def get_profile():
    return profile()


@router.put("/profile")
def put_profile(body: ProfileIn):
    new = clean_profile(body.name, body.color, body.emoji)
    if new != profile():
        config.update_config(profile=new)
        bus.invalidate("profile")
    return profile()


class RegisterIn(BaseModel):
    count: Optional[bool] = None
    email: Optional[str] = None
    news: Optional[bool] = None
    asked: Optional[bool] = None


_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@router.get("/register")
def get_register():
    from .. import register
    return register.state()


@router.put("/register")
async def put_register(body: RegisterIn):
    """Say hello to the authors or stop (docs/user/23-license.md). Talks to the cloud: in a thread."""
    from .. import register
    if body.email and not _EMAIL.match(body.email.strip()):
        raise _err("invalid_email", "email: a valid address or empty")
    st = await asyncio.to_thread(register.save, body.count, body.email, body.news, body.asked)
    bus.invalidate("register")
    return st


class FeedbackIn(BaseModel):
    email: str
    type: Literal["bug", "idea", "other"] = "other"
    message: str


@router.get("/feedback")
def get_feedback():
    """What the Feedback dialog prefills: the last email used, the version sent along."""
    from .. import feedback
    return feedback.defaults()


@router.post("/feedback")
async def post_feedback(body: FeedbackIn):
    """Send a bug report / idea to the authors (api.harness-maxxing.com/v1/feedback). Email required."""
    from .. import feedback
    try:
        return await asyncio.to_thread(feedback.send, body.email, body.type, body.message)
    except feedback.FeedbackError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": str(e)}) from None


class LicenseIn(BaseModel):
    key: str


def _license_state() -> dict:
    from .. import license
    st = license.status()
    return {k: st.get(k) for k in ("has_key", "key_hint", "kind", "email", "max_servers", "expires_at", "activated_at",
                                   "enabled", "moved_to_git")}


@router.get("/license")
def get_license():
    """The optional Enterprise key (docs/user/23-license.md). Never the key itself."""
    return _license_state()


@router.put("/license")
async def put_license(body: LicenseIn):
    from .. import license
    key = body.key.strip()
    if not re.fullmatch(r"(?i)HM(-[A-Z0-9]{4}){4}", key):
        raise _err("invalid_key", "a key looks like HM-XXXX-XXXX-XXXX-XXXX")
    try:
        await asyncio.to_thread(license.activate, key)
    except license.LicenseError as e:
        raise _err(e.code or "license", str(e)) from None
    bus.invalidate("license")
    return _license_state()


@router.delete("/license")
async def delete_license():
    from .. import license
    await asyncio.to_thread(license.remove_key)
    bus.invalidate("license")
    return _license_state()


@router.get("")
def get_settings():
    return current()


@router.put("")
def put_settings(body: SettingsIn):
    changes = body.model_dump(exclude_none=True)
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except Exception:
            raise _err("invalid_timezone", f"unknown time zone {changes['timezone']!r}") from None
    if "public_url" in changes:
        url = changes["public_url"].strip().rstrip("/")
        if url and not _URL.match(url):
            raise _err("invalid_url", "public_url must look like https://ui.example.com")
        changes["public_url"] = url
    if "memory_max_lines" in changes:
        n = changes["memory_max_lines"]
        if n != 0 and not 50 <= n <= 5000:
            raise _err("invalid_memory_max_lines", "memory_max_lines is 0 (no limit) or between 50 and 5000")
    if "result_line_hidden" in changes:
        changes["result_line_hidden"] = [f for f in RESULT_FIELDS if f in changes["result_line_hidden"]]
    if "files_root" in changes:
        p = Path(changes["files_root"]).expanduser()
        if not p.is_absolute() or not p.is_dir():
            raise _err("invalid_files_root", "files_root must be an existing absolute folder")
        changes["files_root"] = str(p.resolve())
    if changes:
        config.update_config(**changes)
        if "timezone" in changes:
            from .. import crons
            if crons.keep_system_clock():
                crons.sync_crontab()                          # guarded lines follow the new zone
            else:
                crons.align_system_timezone(changes["timezone"])  # cron must fire at the times the UI shows
        topics = ["health"]
        if "timezone" in changes:
            topics += ["crons", "tasks"]
        if "usage_widget" in changes:
            topics.append("extensions")
        bus.invalidate(*topics)
    return current()
