"""General settings stored in config.json. See docs/dev/API.md#settings--secrets."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import bus, config, memory, profile_photo
from ..security import require_auth

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])

KEYS = ("timezone", "language", "public_url", "files_root", "presentation_default", "usage_widget", "tasks_page", "git_page", "infra_page", "team_page", "agents_page", "mail_page",
        "maxxing_mode", "memory_max_lines", "result_line_hidden", "donation_hidden", "sidebar_order")
RESULT_FIELDS = ("model", "duration", "cost", "tokens", "cache")   # parts of the line under each answer
_ROUTE = re.compile(r"^/(x/[a-z0-9][a-z0-9-]{0,47}|[a-z0-9-]{0,40})\Z")   # a page (/sessions) or a pinned extension page (/x/<id>)
_URL = config.PUBLIC_URL_RE


class SettingsIn(BaseModel):
    timezone: Optional[str] = None
    language: Optional[Literal["en", "fr"]] = None
    public_url: Optional[str] = None
    files_root: Optional[str] = None
    presentation_default: Optional[bool] = None
    usage_widget: Optional[bool] = None
    tasks_page: Optional[bool] = None
    git_page: Optional[bool] = None
    infra_page: Optional[bool] = None
    team_page: Optional[bool] = None
    agents_page: Optional[bool] = None
    maxxing_mode: Optional[bool] = None
    mail_page: Optional[bool] = None
    memory_max_lines: Optional[int] = None
    result_line_hidden: Optional[list[Literal[RESULT_FIELDS]]] = None  # type: ignore[valid-type]
    donation_hidden: Optional[bool] = None
    sidebar_order: Optional[list[str]] = None     # routes of the sidebar pages, in the order the user dragged them


def _err(code: str, msg: str) -> HTTPException:
    return HTTPException(400, detail={"error": code, "message": msg})


def current() -> dict:
    cfg = config.load_config()
    return {"timezone": cfg.get("timezone") or "UTC", "language": cfg.get("language") or "en",
            "public_url": cfg.get("public_url") or "", "files_root": cfg.get("files_root") or "/root",
            "presentation_default": bool(cfg.get("presentation_default", False)),
            "usage_widget": bool(cfg.get("usage_widget", False)),
            "tasks_page": bool(cfg.get("tasks_page", False)),
            "git_page": bool(cfg.get("git_page", False)),
            "infra_page": bool(cfg.get("infra_page", False)),
            "team_page": bool(cfg.get("team_page", False)),
            "agents_page": bool(cfg.get("agents_page", False)),
            "mail_page": bool(cfg.get("mail_page", False)),
            "maxxing_mode": bool(cfg.get("maxxing_mode", False)),
            "memory_max_lines": memory.max_lines(),
            "result_line_hidden": [f for f in RESULT_FIELDS if f in (cfg.get("result_line_hidden") or [])],
            "donation_hidden": bool(cfg.get("donation_hidden", False)),
            "sidebar_order": sidebar_order(cfg.get("sidebar_order"))}


def sidebar_order(raw: object) -> list[str]:
    """The saved sidebar order, cleaned (a hand-edited or restored config never breaks the settings or the sidebar)."""
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(r for r in raw if isinstance(r, str) and _ROUTE.match(r)))[:40]


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
    """The user's pseudo (name, color, emoji, photo): shown on their messages and used in notifications.
    Empty name = no pseudo (the UI says "You"). `photo` = the version of the photo (see maxxing/profile_photo.py),
    `photo_url` = where the UI shows it ("" = none: emoji or initials)."""
    data = config.load_config().get("profile")
    data = data if isinstance(data, dict) else {}
    photo = str(data.get("photo") or "")
    photo = photo if profile_photo.VERSION.fullmatch(photo) else ""
    return {"name": str(data.get("name") or ""), "color": str(data.get("color") or ""),
            "emoji": str(data.get("emoji") or ""), "photo": photo,
            "photo_url": f"/api/settings/profile/photo?v={photo}" if photo else ""}


def clean_profile(name: str, color: str, emoji: str) -> dict:
    """Validated pseudo: up to 32 printable characters without < >, a known color, an emoji or initials."""
    name = " ".join(_CONTROL.sub("", name or "").split())[:32]
    if color and color not in PROFILE_COLORS:
        raise _err("invalid_color", f"color: {', '.join(PROFILE_COLORS)} or empty")
    emoji = _CONTROL.sub("", (emoji or "").strip())
    if len(emoji) > 8 or any(c.isspace() for c in emoji) or not _utf8(emoji):
        raise _err("invalid_emoji", "emoji: one emoji or initials (8 characters at most) or empty")
    if not _utf8(name):                        # a lone surrogate: config.json could not be written
        raise _err("invalid_name", "name: printable characters only")
    return {"name": name, "color": color, "emoji": emoji}


def _utf8(s: str) -> bool:
    try:
        s.encode()
    except UnicodeEncodeError:
        return False
    return True


@router.get("/profile")
def get_profile():
    return profile()


def _profile_changed() -> None:
    bus.invalidate("profile")
    if config.load_config().get("team_page"):
        from .. import teampeer
        teampeer.share_profile()               # Team contacts see the new name / face


@router.put("/profile")
def put_profile(body: ProfileIn):
    new = clean_profile(body.name, body.color, body.emoji)
    old = profile()
    if new != {k: old[k] for k in new}:
        config.update_config(profile=new)      # deep-merged: the photo stays
        _profile_changed()
    return profile()


@router.get("/profile/photo")
def get_profile_photo():
    found = profile_photo.own()
    if not found or not profile()["photo"]:
        raise HTTPException(404, detail={"error": "not_found", "message": "No photo"})
    return FileResponse(found[0], media_type=found[1], headers={
        "Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})


def _save_photo(data: bytes) -> None:
    with profile_photo.own_lock:               # two uploads at once: the file kept is the version announced
        version = profile_photo.save(data)
        config.update_config(profile={"photo": version})


@router.put("/profile/photo")
async def put_profile_photo(request: Request):
    """The photo's bytes (JPEG, PNG or WebP, at most 512 KB; the UI sends a 256 px square)."""
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > profile_photo.PHOTO_MAX:
            raise _err("too_large", "The photo must be 512 KB at most")
    try:
        await asyncio.to_thread(_save_photo, bytes(data))
    except ValueError as e:
        raise _err(str(e), "A JPEG, PNG or WebP image of 512 KB at most") from None
    await asyncio.to_thread(_profile_changed)
    return profile()


@router.delete("/profile/photo")
def delete_profile_photo():
    with profile_photo.own_lock:               # never between the save and the version of an upload
        had = bool(profile()["photo"])
        if had:
            profile_photo.remove()
            config.update_config(profile={"photo": ""})
    if had:
        _profile_changed()
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
    from .. import feedback, register
    if body.email and (not _EMAIL.match(body.email.strip()) or not feedback.utf8(body.email)):
        raise _err("invalid_email", "email: a valid address or empty")
    st = await asyncio.to_thread(register.save, body.count, body.email, body.news, body.asked)
    bus.invalidate("register")
    return st


class FeedbackImageIn(BaseModel):
    mime: str
    data: str                       # base64, <= 1 MB once decoded (feedback.MAX_IMAGE)
    width: int = 0
    height: int = 0


class FeedbackIn(BaseModel):
    email: str
    type: Literal["bug", "idea", "other"] = "other"
    message: str
    image: Optional[FeedbackImageIn] = None   # the zone of the screen the user selected


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
        shot = feedback.image(body.image.mime, body.image.data, body.image.width, body.image.height) if body.image else None
        return await asyncio.to_thread(feedback.send, body.email, body.type, body.message, shot)
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
    cfg = config.load_config()      # the UI sends back every setting: the unchanged ones are neither checked nor applied
    changes = {k: v for k, v in changes.items() if k not in cfg or cfg[k] != v}
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except Exception:
            raise _err("invalid_timezone", f"unknown time zone {changes['timezone']!r}") from None
    if "public_url" in changes:
        url = changes["public_url"].strip().rstrip("/")
        if url and not (_URL.match(url) and _utf8(url)):
            raise _err("invalid_url", "public_url must look like https://ui.example.com")
        changes["public_url"] = url
    if "memory_max_lines" in changes:
        n = changes["memory_max_lines"]
        if n != 0 and not 50 <= n <= 5000:
            raise _err("invalid_memory_max_lines", "memory_max_lines is 0 (no limit) or between 50 and 5000")
    if "result_line_hidden" in changes:
        changes["result_line_hidden"] = [f for f in RESULT_FIELDS if f in changes["result_line_hidden"]]
    if "sidebar_order" in changes:
        order = changes["sidebar_order"]
        if len(order) > 40 or not all(_ROUTE.match(r) for r in order):
            raise _err("invalid_sidebar_order", "sidebar_order: at most 40 page routes like /sessions or /x/<id>")
        changes["sidebar_order"] = list(dict.fromkeys(order))
    if "files_root" in changes:
        try:
            p = Path(changes["files_root"]).expanduser() if len(changes["files_root"]) <= 4096 else None
            ok = p is not None and p.is_absolute() and p.is_dir()
            if ok:
                changes["files_root"] = str(p.resolve())
        except (RuntimeError, OSError):               # ~user that does not exist, a name too long (ENAMETOOLONG)
            ok = False
        if not ok:
            raise _err("invalid_files_root", "files_root must be an existing absolute folder")
    if changes:
        config.update_config(**changes)
        if "timezone" in changes:
            from .. import crons
            if not crons.keep_system_clock() and not crons.align_system_timezone(changes["timezone"]):
                # cron must fire at the times the UI shows: the system zone cannot be switched, so the server
                # clock is kept and the crontab lines check the schedule in the new zone
                config.update_config(system_clock="keep")
            if crons.keep_system_clock():
                crons.sync_crontab()                          # guarded lines follow the new zone
        topics = ["health"]
        if "timezone" in changes:
            topics += ["crons", "tasks"]
        if "usage_widget" in changes:
            topics.append("extensions")
        bus.invalidate(*topics)
    return current()
