"""User secrets ("Keys" vault), stored in secrets.json under "vault":
{name: {value, note, expose, updated}}.

Secrets flagged `expose` are exported as environment variables to every Claude turn and every
shell cron job (`exposed_env()`, merged by the session spawner and by maxxing.crons).
"""
from __future__ import annotations

import re
import time
from typing import Any

from . import config

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
# Environment variables a secret must never shadow when exposed: system basics, and the ones that make
# shells, interpreters, git or Claude load code or send credentials somewhere else.
RESERVED = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "PWD", "TERM", "LANG", "LC_ALL", "TZ",
            "HOSTNAME", "TMPDIR", "PYTHONPATH", "LD_PRELOAD", "LD_LIBRARY_PATH",
            "LD_AUDIT", "BASH_ENV", "ENV", "PROMPT_COMMAND", "NODE_OPTIONS", "NODE_PATH",
            "PYTHONSTARTUP", "PYTHONHOME", "GIT_SSH_COMMAND", "GIT_EXEC_PATH", "ANTHROPIC_BASE_URL"}


class VaultError(ValueError):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def _vault() -> dict[str, dict]:
    v = config.load_secrets().get("vault")
    if not isinstance(v, dict):
        return {}
    return {k: e for k, e in v.items() if isinstance(e, dict) and isinstance(e.get("value"), str)}


def check_name(name: str) -> None:
    if not NAME_RE.match(name or ""):
        raise VaultError("names use A-Z, 0-9 and _, start with a letter (2-64 characters)", "invalid_name")
    if name in RESERVED or name.startswith("MAXXING_"):
        raise VaultError(f"{name} is a reserved environment variable", "reserved_name")


def preview(value: str) -> str:
    """First 4 characters + '…' (only '…' for short values, which 4 characters would half reveal)."""
    return (value[:4] + "…") if len(value) >= 8 else "…"


def list_secrets() -> list[dict]:
    return [{"name": k, "note": e.get("note", ""), "expose": bool(e.get("expose")),
             "updated": e.get("updated"), "preview": preview(e["value"])}
            for k, e in sorted(_vault().items())]


def get(name: str) -> str | None:
    e = _vault().get(name)
    return e["value"] if e else None


def put(name: str, value: str | None = None, note: str | None = None, expose: bool | None = None) -> None:
    """Create or update. A new secret needs a value; omitted fields keep their current value."""
    check_name(name)
    with config._lock:                                   # read-modify-write of secrets.json
        s = config.load_secrets()
        vault = s.get("vault") if isinstance(s.get("vault"), dict) else {}
        cur: dict[str, Any] = dict(vault.get(name) or {})
        if value is not None:
            if not value or len(value) > 16384:
                raise VaultError("value must be 1 to 16384 characters", "invalid_value")
            cur["value"] = value
        if not cur.get("value"):
            raise VaultError("a new secret needs a value", "value_required")
        if note is not None:
            cur["note"] = note.strip()[:200]
        if expose is not None:
            cur["expose"] = bool(expose)
        cur.setdefault("note", "")
        cur.setdefault("expose", False)
        cur["updated"] = time.time()
        vault[name] = cur
        config.set_secret("vault", vault)


def delete(name: str) -> bool:
    with config._lock:
        s = config.load_secrets()
        vault = s.get("vault") if isinstance(s.get("vault"), dict) else {}
        if name not in vault:
            return False
        vault.pop(name)
        config.set_secret("vault", vault or None)
    return True


def exposed_env() -> dict[str, str]:
    """{NAME: value} of the secrets flagged `expose` (never raises)."""
    try:
        return {k: e["value"] for k, e in _vault().items()
                if e.get("expose") and NAME_RE.match(k) and k not in RESERVED}
    except Exception:
        return {}
