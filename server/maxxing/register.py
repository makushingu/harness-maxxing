"""Saying hello to the authors (optional, fair source: nobody has to). See docs/user/23-license.md.

Two independent choices, kept in config.json "register":
- count: an anonymous daily signal, so the authors know how many servers run, which versions (security alerts),
  on which systems and whether they are healthy: a random id given by the cloud, the version, the system
  (`os`, `arch`) and a few short health codes (`health`). No email, IP, hostname, path or content. On by default
  (Settings -> Profile; since 2.0.0a94 not in the onboarding); `maxxing init` of 2.0.0a94 turns it on once for
  the installs that were never asked (`register_migrated_a94`). MAXXING_NO_TELEMETRY=1 or DO_NOT_TRACK=1 in the
  service environment turns it off whatever the setting.
- email (+ news): the server is known by an email address (pseudo of Settings -> Profile and language sent
  too). Security alerts go to every email; product news only when `news` is checked.
Neither: the cloud archives the row (never contacted again) and the token is forgotten.

The cloud (api.harness-maxxing.com/v1/register, /v1/heartbeat) hands out the token that alone can change or
stop the row; it lives in secrets.json, never in the Keys vault.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import time
from pathlib import Path
import urllib.error
import urllib.request

from . import config, license

log = logging.getLogger(__name__)

TOKEN = "register_token"          # secrets.json
EVERY = 24 * 3600
DEFAULTS = {"count": True, "email": "", "news": False, "asked": False}
MIGRATED = "register_migrated_a94"   # config.json: the one-time "counter on unless the user was asked" is done
OS_RELEASE = Path("/etc/os-release")
OPT_OUT_ENV = ("MAXXING_NO_TELEMETRY", "DO_NOT_TRACK")
HEALTH_RE = re.compile(r"^[a-z_]{1,24}$")
HEALTH_MAX = 10


def migrate(raw: dict) -> bool:
    """Once (2.0.0a94, run by `maxxing init`, so by every update): the anonymous counter is turned on for an install
    whose user never saw the choice. One who saw it (asked) keeps what they chose. Edits `raw`; True when changed."""
    if raw.get(MIGRATED):
        return False
    reg = raw.get("register") if isinstance(raw.get("register"), dict) else {}
    if not reg.get("asked"):
        raw["register"] = {**reg, "count": True}
    raw[MIGRATED] = True
    return True


def blocked() -> bool:
    """MAXXING_NO_TELEMETRY / DO_NOT_TRACK set (to anything but 0/false/no): no anonymous counter, whatever the
    setting."""
    return any(os.environ.get(k, "").strip().lower() not in ("", "0", "false", "no") for k in OPT_OUT_ENV)


def settings() -> dict:
    r = config.load_config().get("register") or {}
    return {**DEFAULTS, **{k: r[k] for k in DEFAULTS if k in r}}


def counting(s: dict | None = None) -> bool:
    """The anonymous counter really runs: checked and not blocked by the environment."""
    return bool((s or settings())["count"]) and not blocked()


def _on(s: dict) -> bool:
    return counting(s) or bool(s["email"])


def state() -> dict:
    s = settings()
    meta = config.load_config().get("register_meta") or {}
    return {**s, "count_blocked": blocked(), "registered": bool(config.get_secret(TOKEN)), "error": meta.get("error", ""),
            "synced_at": meta.get("synced_at", 0)}


def _call(method: str, path: str, body: dict) -> dict:
    """The cloud's JSON answer, error answers included ({"ok": false, "error": ...}); raises only when offline."""
    req = urllib.request.Request(license.API + path, data=json.dumps(body).encode(), method=method,
                                 headers={"content-type": "application/json", "user-agent": license.USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read() or b"{}") or {"ok": False, "error": f"http_{e.code}"}
        except ValueError:
            return {"ok": False, "error": f"http_{e.code}"}


def _offline() -> bool:
    return os.environ.get("MAXXING_LICENSE_PING") == "0"   # tests and air-gapped installs: never call the cloud


def os_name() -> str:
    """"Ubuntu 24.04" (NAME + VERSION_ID of /etc/os-release, else PRETTY_NAME, else the kernel name), <= 40 chars."""
    info: dict[str, str] = {}
    try:
        for line in OS_RELEASE.read_text(errors="replace").splitlines():
            k, sep, v = line.partition("=")
            if sep:
                info[k.strip()] = v.strip().strip('"\'')
    except OSError:
        pass
    name = " ".join(x for x in (info.get("NAME", ""), info.get("VERSION_ID", "")) if x) if info.get("NAME") \
        else info.get("PRETTY_NAME") or platform.system()
    return re.sub(r"[^\w .+()/-]", "", name).strip()[:40]


def arch() -> str:
    return re.sub(r"[^\w-]", "", platform.machine())[:16]


def health_codes() -> list[str]:
    """A few short codes of what the health check already computed (cached, no network): <= 10, /^[a-z_]{1,24}$/."""
    codes: list[str] = []
    try:
        from . import health
        h = health.collect()
        issues = [i.get("code", "") for i in h.get("issues") or []]
        codes.append("service_down" if "service_down" in issues else "service_ok")
        codes.append("claude_signed_in" if h.get("claude_auth") else "claude_signed_out")
        codes += [c for c in issues if c not in ("service_down", "claude_auth")]
    except Exception:  # noqa: BLE001 - the signal goes without health codes
        codes.append("health_unknown")
    try:
        from . import customs
        if (customs.pending() or {}).get("reason"):
            codes.append("update_failed")
    except Exception:  # noqa: BLE001
        pass
    cfg = config.load_config()
    if (cfg.get("telegram") or {}).get("chat_id"):
        codes.append("telegram_on")
    if (cfg.get("backup") or {}).get("repo"):
        codes.append("backup_on")
    out: list[str] = []
    for c in codes:
        if isinstance(c, str) and HEALTH_RE.match(c) and c not in out:
            out.append(c)
    return out[:HEALTH_MAX]


def anonymous() -> dict:
    """What the anonymous counter adds to the version: the system and the health codes. None when it is off (an
    install known only by its email: what the cloud kept of them is cleared)."""
    return {"os": os_name(), "arch": arch(), "health": health_codes()}


def _payload(s: dict) -> dict:
    body = {"version": license.disk_version(), "email": s["email"] or None, "news": bool(s["email"] and s["news"])}
    body.update(anonymous() if counting(s) else {"os": None, "arch": None, "health": None})
    if s["email"]:                                          # anonymous counter: no pseudo, no language
        cfg = config.load_config()
        body["pseudo"] = ((cfg.get("profile") or {}).get("name") or "")[:40]
        body["lang"] = cfg.get("language") or "en"
    return body


def _meta(**kw) -> None:
    config.update_config(register_meta={**(config.load_config().get("register_meta") or {}), **kw})


def sync() -> dict:
    """Make the cloud match the settings: create / update the row, or delete it. Never raises."""
    s, tok = settings(), config.get_secret(TOKEN)
    if _offline():
        return state()
    try:
        if not _on(s):
            if tok:
                _call("DELETE", "/v1/register", {"token": tok})
                config.set_secret(TOKEN, None)
            _meta(error="", synced_at=time.time(), beat_at=0)
            return state()
        r = _call("POST", "/v1/register", {**_payload(s), **({"token": tok} if tok else {})})
        if not r.get("ok") and r.get("error") in ("unknown_install", "bad_token") and tok:
            config.set_secret(TOKEN, None)                  # deleted on the cloud side: register again
            r = _call("POST", "/v1/register", _payload(s))
        if r.get("ok") and r.get("token"):
            config.set_secret(TOKEN, r["token"])
            _meta(error="", synced_at=time.time(), beat_at=time.time())
        else:
            _meta(error=str(r.get("message") or r.get("error") or "unreachable")[:200])
    except Exception as e:  # noqa: BLE001 - offline: the daily signal tries again
        _meta(error=type(e).__name__)
    return state()


def save(count: bool | None = None, email: str | None = None, news: bool | None = None, asked: bool | None = None) -> dict:
    cur = settings()
    new = dict(cur)
    if count is not None:
        new["count"] = bool(count)
    if email is not None:
        new["email"] = email.strip().lower()[:254]
    if news is not None:
        new["news"] = bool(news)
    if asked is not None:
        new["asked"] = bool(asked)
    if not new["email"]:
        new["news"] = False
    config.update_config(register=new)
    if {k: new[k] for k in ("count", "email", "news")} != {k: cur[k] for k in ("count", "email", "news")} \
            or _on(new) != bool(config.get_secret(TOKEN)):
        return sync()
    return state()


def heartbeat_due() -> bool:
    s = settings()
    if _offline():
        return False
    if not _on(s):                                          # e.g. MAXXING_NO_TELEMETRY set after a count-only row:
        return bool(config.get_secret(TOKEN))               # the row is deleted (heartbeat -> sync)
    return time.time() - float((config.load_config().get("register_meta") or {}).get("beat_at") or 0) > EVERY - 600


def heartbeat() -> dict:
    """The daily signal (version, + system and health codes when the counter is on). Unknown on the cloud (deleted
    from the admin) -> registered again."""
    tok = config.get_secret(TOKEN)
    s = settings()
    if not tok or not _on(s):
        return sync()
    r = _call("POST", "/v1/heartbeat", {"token": tok, "version": license.disk_version(),
                                         **(anonymous() if counting(s) else {})})
    if r.get("ok"):
        _meta(beat_at=time.time(), error="")
    elif r.get("error") in ("unknown_install", "bad_token"):
        config.set_secret(TOKEN, None)
        return sync()
    return r
