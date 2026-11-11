"""The newest Claude models, read from Anthropic. See docs/dev/INTERNALS.md#maxxingclaude_models.

Once a day (and at the first start) GET https://api.anthropic.com/v1/models is read with the Claude credentials of
the server (the setup-token or API key of secrets.json, else the `claude login` access token while it is valid) and
the newest model of each family (opus, sonnet, haiku, fable) is kept. Model pickers, Telegram and the Claude
settings list these (service.models()). When a family gets a newer model and the default model (config
`default_model`) was the previous newest of that family, the default moves to the new one: someone who picked
"the best Sonnet" keeps the best Sonnet. A model picked by hand on a topic, a job or an agent is never changed.

Without credentials or network the last list read stays (FALLBACK before the first read).
State: <state>/claude-models.json = {checked_at, latest: [id], all: [id], error}.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from . import config

log = logging.getLogger("maxxing.claude_models")

URL = "https://api.anthropic.com/v1/models?limit=1000"
CHECK_EVERY_S = 24 * 3600
RETRY_S = 3600                     # after a failed read
FIRST_DELAY_S = 60
TIMEOUT_S = 15
FAMILIES = ("opus", "sonnet", "haiku", "fable")
FALLBACK = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]
_ID = re.compile(r"claude-(opus|sonnet|haiku|fable)-[a-z0-9.-]+")
_lock = threading.Lock()
_task: asyncio.Task | None = None


def state_file() -> Path:
    return config.STATE / "claude-models.json"


def load() -> dict:
    d = config.read_json(state_file(), {})
    return d if isinstance(d, dict) else {}


def family(mid: str) -> str:
    parts = (mid or "").split("-")
    return parts[1] if len(parts) > 1 and parts[0] == "claude" else ""


def version_key(mid: str) -> tuple:
    """claude-opus-5-5 -> (5, 5, 0); claude-haiku-4-5-20251001 -> (4, 5, 0) (a date is not a version)."""
    v = [int(x) for x in mid.split("-")[2:] if x.isdigit() and len(x) < 4][:3]
    return tuple(v + [0] * (3 - len(v)))


def newest(ids: list[str]) -> list[str]:
    """The newest id of each family, in FAMILIES order."""
    best: dict[str, str] = {}
    for mid in ids:
        f = family(mid)
        if f in FAMILIES and _ID.fullmatch(mid) and (f not in best or version_key(mid) > version_key(best[f])):
            best[f] = mid
    return [best[f] for f in FAMILIES if f in best]


def latest() -> list[str]:
    """The newest model of each family (last list read, else FALLBACK)."""
    got = load().get("latest")
    if isinstance(got, list) and got and all(isinstance(m, str) for m in got):
        return list(got)
    return list(FALLBACK)


def latest_of(fam: str) -> str:
    return next((m for m in latest() if family(m) == fam), next(m for m in FALLBACK if family(m) == fam))


def _headers() -> dict[str, str] | None:
    """Anthropic headers for the server's Claude credentials, None when there are none usable."""
    h = {"anthropic-version": "2023-06-01"}
    s = config.load_secrets()
    tok = s.get("claude_oauth_token") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    key = s.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not tok and not key:
        from . import claude_auth
        try:
            o = json.loads(claude_auth.credentials_file().read_text()).get("claudeAiOauth") or {}
        except (OSError, ValueError, AttributeError):
            o = {}
        if o.get("accessToken") and float(o.get("expiresAt") or 0) / 1000 > time.time() + 60:
            tok = o["accessToken"]
    if tok:
        return {**h, "Authorization": f"Bearer {tok}", "anthropic-beta": "oauth-2025-04-20"}
    if key:
        return {**h, "x-api-key": str(key)}
    return None


def fetch_ids() -> list[str]:
    """Model ids Anthropic lists for these credentials. Raises RuntimeError on any failure."""
    import httpx
    h = _headers()
    if not h:
        raise RuntimeError("no Claude credentials")
    try:
        r = httpx.get(URL, headers=h, timeout=TIMEOUT_S)
    except httpx.HTTPError as e:
        raise RuntimeError(f"network: {type(e).__name__}") from None
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    try:
        data = r.json().get("data") or []
    except (ValueError, AttributeError, RecursionError):
        raise RuntimeError("bad answer") from None
    if not isinstance(data, list):
        raise RuntimeError("bad answer")
    return [m["id"] for m in data if isinstance(m, dict) and isinstance(m.get("id"), str) and _ID.fullmatch(m["id"])]


def _follow_default(old: list[str], new: list[str]) -> str | None:
    """Move `default_model` to the new newest of its family when it was the previous newest. Returns the new id."""
    cur = (config.load_config().get("default_model") or "").strip()
    if not cur or cur not in old:
        return None
    nxt = next((m for m in new if family(m) == family(cur)), None)
    if not nxt or nxt == cur or version_key(nxt) <= version_key(cur):
        return None
    config.update_config(default_model=nxt)
    log.info("default model %s -> %s", cur, nxt)
    return nxt


def refresh(now: float | None = None, force: bool = False) -> dict:
    """Read the list when due (or `force`) -> the state. Never raises."""
    now = time.time() if now is None else now
    with _lock:
        d = load()
        wait = RETRY_S if d.get("error") else CHECK_EVERY_S
        if not force and now - float(d.get("checked_at") or 0) < wait:
            return d
        old = latest()
        try:
            ids = fetch_ids()
            new = newest(ids)
            if not new:
                raise RuntimeError("no Claude model listed")
        except RuntimeError as e:
            d.update(checked_at=now, error=str(e))
            config.write_json(state_file(), d, mode=0o600)
            return d
        d = {"checked_at": now, "latest": new, "all": sorted(set(ids)), "error": None}
        config.write_json(state_file(), d, mode=0o600)
        if new != old:
            try:
                moved = _follow_default(old, new)
            except Exception:
                log.exception("could not move the default model")
                moved = None
            if moved:
                d["default_moved_to"] = moved
            from .sessions import service
            service.forget_models_cache()
        return d


async def _loop() -> None:
    await asyncio.sleep(float(os.environ.get("MAXXING_CLAUDE_MODELS_DELAY", FIRST_DELAY_S)))
    while True:
        try:
            await asyncio.to_thread(refresh)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Claude models check failed")
        await asyncio.sleep(RETRY_S)


def start() -> None:
    """Started with the server, like the Claude Code updates (only the installed server, never a test copy)."""
    global _task
    from . import claude_update
    flag = os.environ.get("MAXXING_CLAUDE_MODELS", "")
    here = flag == "1" if flag in ("0", "1") else claude_update.installed_server()
    if not here:
        return
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop())


def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None
