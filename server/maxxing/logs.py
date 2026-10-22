"""Server logging: INFO to the journal, never a secret.

httpx logs every request URL at INFO, and Telegram puts the bot token in the URL
(https://api.telegram.org/bot<token>/getUpdates) - so HTTP client logs are lowered to WARNING
and every record goes through a redaction filter as a second line of defence."""
from __future__ import annotations

import logging
import re

_PATTERNS = [
    (re.compile(r"/bot\d+:[A-Za-z0-9_-]+"), "/bot<redacted>"),                      # Telegram bot token
    (re.compile(r"\b\d{6,}:AA[A-Za-z0-9_-]{30,}"), "<telegram-token>"),
    (re.compile(r"\b(sk-ant-[a-z]+\d*-)[A-Za-z0-9_-]{16,}"), r"\1<redacted>"),      # Anthropic keys / OAuth tokens
    (re.compile(r"\b(gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}"), r"\1<redacted>"),   # GitHub tokens
    (re.compile(r"\b(gsk_|sk-)[A-Za-z0-9_-]{20,}"), r"\1<redacted>"),               # Groq / OpenAI keys
]


def redact(text: str) -> str:
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken record is not our problem
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        return True


def setup(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    f = RedactSecrets()
    for h in logging.getLogger().handlers:
        if not any(isinstance(x, RedactSecrets) for x in h.filters):
            h.addFilter(f)
