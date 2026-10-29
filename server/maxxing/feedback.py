"""Feedback to the authors: the Feedback button at the bottom of the sidebar (bug report, idea, anything).

Sent to api.harness-maxxing.com/v1/feedback with the version of this server and the language. The email address is
required (against abuse, and so the authors can answer); the last one used is remembered in config.json
"feedback_email" (first time: the email of Settings -> Profile -> Harness Maxxing team, if any). Nothing else is
sent: no logs, no files, no session content.
"""
from __future__ import annotations

import http.client
import re
import urllib.error

from . import config, license, register

TYPES = ("bug", "idea", "other")
MAX_MESSAGE = 4000
MAX_EMAIL = 254                    # as register.save
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
LANGS = ("en", "fr", "es", "de", "it", "pt")


def utf8(s: str) -> bool:
    """False for a lone surrogate ("\\ud800" is valid JSON): it cannot be written to config.json."""
    try:
        s.encode()
        return True
    except UnicodeEncodeError:
        return False


class FeedbackError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


def defaults() -> dict:
    cfg = config.load_config()
    return {"email": cfg.get("feedback_email") or register.settings().get("email") or "", "version": license.disk_version()}


def send(email: str, kind: str, message: str) -> dict:
    """Send one message; raises FeedbackError (code, message, http status) when it did not go."""
    email, message = (email or "").strip(), (message or "").strip()
    if len(email) > MAX_EMAIL or not _EMAIL.match(email) or not utf8(email):
        raise FeedbackError("invalid_email", "Enter a valid email address")
    if len(message) < 3:
        raise FeedbackError("message_required", "Write your message")
    if len(message) > MAX_MESSAGE:
        raise FeedbackError("too_long", f"{MAX_MESSAGE} characters at most")
    if register._offline():
        raise FeedbackError("offline", "This server does not talk to the Harness Maxxing cloud", 503)
    cfg = config.load_config()
    lang = cfg.get("language") or "en"
    body = {"email": email, "type": kind if kind in TYPES else "other", "message": message, "version": license.disk_version(),
            "lang": lang if lang in LANGS else "en", "name": ((cfg.get("profile") or {}).get("name") or "")[:100]}
    try:
        r = register._call("POST", "/v1/feedback", body)
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        raise FeedbackError("unreachable", "The Harness Maxxing cloud cannot be reached, try again later", 502) from None
    if not r.get("ok"):
        code = r.get("error") or "failed"
        raise FeedbackError(code, r.get("message") or "Not sent", 429 if code == "rate" else 400)
    config.update_config(feedback_email=email)
    return {"ok": True}
