"""Claude sign-in state from REAL calls.  STDLIB ONLY (the turn runner records into it).

A credentials file or a stored token only says a method is configured; whether it still works is
known from the last real call: every session turn (runner), every test call (Settings > Claude)
and a background verification (api/claude.py, at most every CHECK_EVERY_S). The outcome lives in
`<state>/claude-auth.json` = {ok, at, error, source:"turn"|"test"|"check", method}.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path

from . import config
from .sessions import spawn

CHECK_EVERY_S = 6 * 3600
AUTH_ERROR = re.compile(
    r"oauth (?:session|token)[^\n]{0,60}(?:expired|revoked|invalid)|could not be refreshed|"
    r"invalid api key|invalid x-api-key|please run /login|authentication_error|authentication failed|"
    r"failed to authenticate|not logged in|invalid bearer token|token has expired", re.I)


def state_file() -> Path:
    return config.STATE / "claude-auth.json"


def credentials_file() -> Path:
    return config.claude_dir() / ".credentials.json"


def plan_name(creds: object = None) -> str | None:
    """The Claude plan as Anthropic names it since 2026-10-31 (Max 5x -> "Max", Max 20x -> "Ultra"), read in the
    `claude login` credentials file (subscriptionType + rateLimitTier); None when unknown (setup-token, API key)."""
    if creds is None:
        try:
            creds = json.loads(credentials_file().read_text())
        except (OSError, ValueError, RecursionError):              # a damaged file must not break /api/usage
            return None
    o = creds.get("claudeAiOauth") if isinstance(creds, dict) else None
    if not isinstance(o, dict):
        return None
    sub = str(o.get("subscriptionType") or "").lower()
    tier = str(o.get("rateLimitTier") or "").lower()
    if sub == "ultra" or "20x" in tier or "ultra" in tier:
        return "Ultra"
    return {"pro": "Pro", "max": "Max", "team": "Team", "enterprise": "Enterprise", "free": "Free"}.get(sub)


def auth_method() -> tuple[str | None, str]:
    """(method, detail) without any network call."""
    if config.get_secret("claude_oauth_token"):
        return "oauth_token", "Long-lived token stored in Harness Maxxing"
    if config.get_secret("anthropic_api_key"):
        return "api_key", "API key stored in Harness Maxxing"
    f = credentials_file()
    if f.is_file():
        sub = plan_name()
        return "credentials", "Signed in with `claude` on this server" + (f" ({sub} plan)" if sub else "")
    return None, "Not connected"


def detect(text: str | None) -> str | None:
    """The auth error line found in a CLI output, or None."""
    if not text:
        return None
    m = AUTH_ERROR.search(text)
    if not m:
        return None
    a = text.rfind("\n", 0, m.start()) + 1
    b = text.find("\n", m.end())
    return text[a: b if b >= 0 else len(text)].strip()[:300] or m.group(0)


def last() -> dict:
    try:
        with open(state_file()) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def record(ok: bool, error: str | None = None, source: str = "turn") -> None:
    """Remember the outcome of a real call (atomic, safe across processes)."""
    data = {"ok": bool(ok), "at": time.time(), "error": None if ok else (error or "unknown error")[:400],
            "source": source, "method": auth_method()[0]}
    p = state_file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, p)
    except OSError:
        pass


def forget() -> None:
    try:
        state_file().unlink()
    except FileNotFoundError:
        pass


def _relevant(rec: dict, method: str | None) -> bool:
    """A result counts for the current method, and not when the credentials changed afterwards."""
    if not rec or rec.get("method") != method:
        return False
    if method == "credentials":
        try:
            if credentials_file().stat().st_mtime > float(rec.get("at") or 0):
                return False                           # `claude /login` again since then
        except OSError:
            return False
    return True


def status() -> dict:
    """{ok, method, detail, checked_at, error}: ok = a method is configured and the last real call
    with it did not fail on authentication (checked_at None = not verified yet)."""
    method, detail = auth_method()
    rec = last()
    out = {"ok": method is not None, "method": method, "detail": detail, "checked_at": None, "error": None}
    if method is None or not _relevant(rec, method):
        return out
    out["checked_at"] = rec.get("at")
    if rec.get("ok") is False:
        err = rec.get("error") or "unknown error"
        prefix = "Last test failed" if rec.get("source") == "test" else "Claude sign-in failed"
        out.update(ok=False, error=err, detail=f"{prefix}: {err}")
    return out


def needs_check(now: float | None = None) -> bool:
    """True when a method is configured and no real call verified it in the last CHECK_EVERY_S."""
    method, _ = auth_method()
    if method is None:
        return False
    rec = last()
    now = now or time.time()
    return not _relevant(rec, method) or now - float(rec.get("at") or 0) > CHECK_EVERY_S


# ---- plan limits seen in the turns -----------------------------------------------------------
# Claude Code prints a `rate_limit_event` in its stream-json (subscription only): the utilization (0..1) and
# reset time of the 5-hour and 7-day windows. The runner keeps the last one; reading it costs no call.

def limits_file() -> Path:
    return config.STATE / "claude-limits.json"


def record_limits(info: object) -> None:
    wins = info.get("unifiedWindows") if isinstance(info, dict) else None
    if not isinstance(wins, dict):
        return
    data: dict = {"at": time.time()}
    for key in ("five_hour", "seven_day"):
        w = wins.get(key)
        if isinstance(w, dict) and isinstance(w.get("utilization"), (int, float)) and math.isfinite(w["utilization"]):
            data[key] = {"utilization": float(w["utilization"]), "resets_at": w.get("resetsAt")}
    if len(data) == 1:
        return
    p = limits_file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, p)
    except OSError:
        pass


def limits(now: float | None = None) -> dict | None:
    """The last limits seen in a turn, as /api/usage gives them ({available, five_hour, seven_day, seen_at}):
    pct 0-100, resets_at in Unix seconds; a window whose reset time has passed is back to 0. None = never seen."""
    try:
        with open(limits_file()) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    now = time.time() if now is None else now
    out: dict = {"available": False, "five_hour": None, "seven_day": None, "source": "turn", "seen_at": None}
    at = d.get("at")
    if isinstance(at, (int, float)) and not isinstance(at, bool) and math.isfinite(at):
        out["seen_at"] = at                             # a hand-edited "x" / NaN / 1e999 would make /api/usage answer 500
    for key in ("five_hour", "seven_day"):
        w = d.get(key)
        if not isinstance(w, dict):
            continue
        reset = w.get("resets_at") if isinstance(w.get("resets_at"), (int, float)) else None
        if reset is not None and not math.isfinite(reset):
            reset = None
        u = w.get("utilization") or 0
        if not isinstance(u, (int, float)) or not math.isfinite(u):
            continue                                    # NaN / 1e999 would make /api/usage answer 500
        pct = 0.0 if reset is not None and reset <= now else min(max(round(float(u) * 100, 1), 0.0), 100.0)
        out[key] = {"pct": pct, "resets_at": None if reset is not None and reset <= now else reset}
        out["available"] = True
    return out if out["available"] else None
