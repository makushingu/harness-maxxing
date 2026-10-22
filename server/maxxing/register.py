"""Saying hello to the authors (optional, fair source: nobody has to). See docs/user/23-license.md.

Two independent choices, kept in config.json "register":
- count: an anonymous daily signal (a random id given by the cloud + the version, nothing else), so the authors
  know how many servers run and which versions (security alerts). Checked by default in the onboarding,
  never turned on by an update.
- email (+ news): the server is known by an email address (pseudo of Settings -> Profile and language sent
  too). Security alerts go to every email; product news only when `news` is checked.
Neither: the cloud row is deleted and the token forgotten.

The cloud (api.harness-maxxing.com/v1/register, /v1/heartbeat) hands out the token that alone can change or
delete the row; it lives in secrets.json, never in the Keys vault.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

from . import config, license

log = logging.getLogger(__name__)

TOKEN = "register_token"          # secrets.json
EVERY = 24 * 3600
DEFAULTS = {"count": False, "email": "", "news": False, "asked": False}


def settings() -> dict:
    r = config.load_config().get("register") or {}
    return {**DEFAULTS, **{k: r[k] for k in DEFAULTS if k in r}}


def state() -> dict:
    s = settings()
    meta = config.load_config().get("register_meta") or {}
    return {**s, "registered": bool(config.get_secret(TOKEN)), "error": meta.get("error", ""),
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


def _payload(s: dict) -> dict:
    body = {"version": license.disk_version(), "email": s["email"] or None, "news": bool(s["email"] and s["news"])}
    if s["email"]:                                          # anonymous counter: the version and nothing else
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
        if not (s["count"] or s["email"]):
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
            or (new["count"] or new["email"]) != bool(config.get_secret(TOKEN)):
        return sync()
    return state()


def heartbeat_due() -> bool:
    s = settings()
    if not (s["count"] or s["email"]) or _offline():
        return False
    return time.time() - float((config.load_config().get("register_meta") or {}).get("beat_at") or 0) > EVERY - 600


def heartbeat() -> dict:
    """The daily signal (version). Unknown on the cloud (deleted from the admin) -> registered again."""
    tok = config.get_secret(TOKEN)
    if not tok:
        return sync()
    r = _call("POST", "/v1/heartbeat", {"token": tok, "version": license.disk_version()})
    if r.get("ok"):
        _meta(beat_at=time.time(), error="")
    elif r.get("error") in ("unknown_install", "bad_token"):
        config.set_secret(TOKEN, None)
        return sync()
    return r
