"""Claude CLI status, authentication and defaults. See docs/dev/API.md#claude."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import claude_auth, claude_update, config
from ..security import require_auth
from ..sessions import service, spawn

router = APIRouter(prefix="/api/claude", tags=["claude"], dependencies=[Depends(require_auth)])

TEST_MODEL = "claude-haiku-4-5-20251001"
TEST_PROMPT = "Reply with the single word: ok"
TEST_TIMEOUT_S = 90
PERMISSION_MODES = ("bypass", "acceptEdits", "default")
SECRET_FOR = {"oauth_token": "claude_oauth_token", "api_key": "anthropic_api_key"}
_version_cache: dict[str, tuple[float, str | None]] = {}


# ---- detection -----------------------------------------------------------------------------
def _resolved_bin() -> str | None:
    b = spawn.claude_bin()
    if os.path.isabs(b):
        return b if os.access(b, os.X_OK) else None
    return shutil.which(b, path=spawn.base_env()["PATH"])


def claude_version() -> str | None:
    """`claude --version` (cached per binary mtime)."""
    b = _resolved_bin()
    if not b:
        return None
    try:
        key = f"{b}:{os.stat(b).st_mtime}"
    except OSError:
        return None
    if key in _version_cache:
        return _version_cache[key][1]
    try:
        r = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=20, env=spawn.base_env())
        v = (r.stdout.strip().split() or [None])[0] if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        v = None
    _version_cache[key] = (time.time(), v)
    return v


def auth_method() -> tuple[str | None, str]:
    return claude_auth.auth_method()


def auth_status() -> dict:
    """{ok, method, detail, checked_at, error} - see maxxing/claude_auth.py (real-call based)."""
    return claude_auth.status()


# ---- test call -----------------------------------------------------------------------------
def run_test(model: str = TEST_MODEL, source: str = "test", timeout_s: int = TEST_TIMEOUT_S) -> dict:
    """Real one-line call through the CLI -> {ok, model, ms, error?} (also remembered)."""
    t0 = time.time()
    out: dict = {"ok": False, "model": model, "ms": 0}
    b = _resolved_bin()
    if not b:
        out["error"] = "Claude Code is not installed"
        return _remember(out, source)
    cwd = config.state_dir("claude-test")
    try:
        r = subprocess.run([b, "-p", "--output-format", "json", "--model", model], input=TEST_PROMPT,
                           capture_output=True, text=True, timeout=timeout_s, cwd=cwd,
                           env=spawn.claude_env(None, "default"))
    except subprocess.TimeoutExpired:
        out.update(ms=int((time.time() - t0) * 1000), error=f"No answer within {timeout_s} s")
        return _remember(out, source)
    except OSError as e:
        out.update(error=str(e))
        return _remember(out, source)
    out["ms"] = int((time.time() - t0) * 1000)
    try:
        data = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except ValueError:
        data = {}
    text = str(data.get("result") or "")
    if r.returncode == 0 and not data.get("is_error") and text.strip():
        out["ok"] = True
        mu = data.get("modelUsage")
        if isinstance(mu, dict) and mu:
            out["model"] = next(iter(mu))
    else:
        out["error"] = (text or r.stderr or r.stdout or f"exit code {r.returncode}").strip()[-400:]
    return _remember(out, source)


def _remember(out: dict, source: str) -> dict:
    """Record the outcome. A background check only flips the state on a real sign-in error
    (a timeout or a network glitch is not "signed out"); an explicit test always does."""
    err = out.get("error")
    if out["ok"]:
        claude_auth.record(True, None, source)
    elif source == "test" or claude_auth.detect(err):
        claude_auth.record(False, claude_auth.detect(err) or err, source)
    return out


# ---- background verification -----------------------------------------------------------------
CHECK_POLL_S = 600
CHECK_TIMEOUT_S = 60
_task: asyncio.Task | None = None
_last_attempt = 0.0


def check_now() -> dict | None:
    """One background verification if due (no real call in the last 6 h, none attempted here
    in the last 6 h); returns the test result or None when nothing was done."""
    global _last_attempt
    if time.time() - _last_attempt < claude_auth.CHECK_EVERY_S or not claude_auth.needs_check():
        return None
    if not _resolved_bin():
        return None
    _last_attempt = time.time()
    return run_test(source="check", timeout_s=CHECK_TIMEOUT_S)


async def _checker() -> None:
    await asyncio.sleep(float(os.environ.get("MAXXING_AUTH_CHECK_DELAY", "5")))
    while True:
        try:
            await asyncio.to_thread(check_now)
        except Exception:
            pass
        await asyncio.sleep(CHECK_POLL_S)


async def startup() -> None:
    global _task
    if os.environ.get("MAXXING_AUTH_CHECK", "1") != "0":
        _task = asyncio.create_task(_checker())
    claude_update.start()


async def shutdown() -> None:
    global _task
    if _task:
        _task.cancel()
        _task = None
    claude_update.stop()


# ---- endpoints -----------------------------------------------------------------------------
@router.get("/status")
async def status():
    cfg = config.load_config()
    version = await asyncio.to_thread(claude_version)
    return {"installed": bool(await asyncio.to_thread(_resolved_bin)), "version": version,
            "auth": await asyncio.to_thread(auth_status),
            "default_model": cfg.get("default_model") or "",
            "permission_mode": cfg.get("permission_mode") or "bypass",
            "auto_compact_tokens": int(cfg.get("auto_compact_tokens") or 0),
            "idle_compact_tokens": int(cfg.get("idle_compact_tokens") or 0),
            "idle_compact_after_s": int(cfg.get("idle_compact_after_s") or 0),
            "protect_secrets": bool(cfg.get("protect_secrets", True)),
            "short_titles": bool(cfg.get("short_titles", True)),
            "short_titles_model": bool(cfg.get("short_titles_model", False)),
            "auto_update": await asyncio.to_thread(claude_update.public),
            "models": await asyncio.to_thread(service.models)}


class AuthIn(BaseModel):
    kind: Literal["oauth_token", "api_key"]
    value: str


@router.post("/auth")
async def set_auth(body: AuthIn):
    value = body.value.strip()
    if len(value) < 10 or any(c.isspace() for c in value):
        raise HTTPException(400, detail={"error": "invalid", "message": "This does not look like a token"})
    for kind, name in SECRET_FOR.items():               # one stored credential at a time
        config.set_secret(name, value if kind == body.kind else None)
    res = await asyncio.to_thread(run_test)
    return {"ok": res["ok"], **({"error": res["error"]} if not res["ok"] else {})}


@router.delete("/auth")
async def delete_auth():
    for name in SECRET_FOR.values():
        config.set_secret(name, None)
    claude_auth.forget()
    return {"ok": True}


@router.post("/test")
async def test():
    return await asyncio.to_thread(run_test)


class SettingsIn(BaseModel):
    default_model: str | None = None
    permission_mode: str | None = None
    auto_compact_tokens: int | None = Field(None, ge=0, le=2_000_000)
    idle_compact_tokens: int | None = Field(None, ge=0, le=2_000_000)
    idle_compact_after_s: int | None = Field(None, ge=300, le=7 * 86400)
    protect_secrets: bool | None = None
    short_titles: bool | None = None
    short_titles_model: bool | None = None
    claude_auto_update: bool | None = None


@router.put("/settings")
async def settings(body: SettingsIn):
    changes: dict = {}
    if body.default_model is not None:
        changes["default_model"] = body.default_model.strip()
    if body.permission_mode is not None:
        if body.permission_mode not in PERMISSION_MODES:
            raise HTTPException(400, detail={"error": "invalid",
                                             "message": "permission_mode: bypass, acceptEdits or default"})
        changes["permission_mode"] = body.permission_mode
    if body.auto_compact_tokens is not None:
        changes["auto_compact_tokens"] = body.auto_compact_tokens
    if body.idle_compact_tokens is not None:
        changes["idle_compact_tokens"] = body.idle_compact_tokens
    if body.idle_compact_after_s is not None:
        changes["idle_compact_after_s"] = body.idle_compact_after_s
    if body.protect_secrets is not None:
        changes["protect_secrets"] = body.protect_secrets
    if body.short_titles is not None:
        changes["short_titles"] = body.short_titles
    if body.short_titles_model is not None:
        changes["short_titles_model"] = body.short_titles_model
    if body.claude_auto_update is not None:
        changes["claude_auto_update"] = body.claude_auto_update
    if changes:
        config.update_config(**changes)
    return {"ok": True}
