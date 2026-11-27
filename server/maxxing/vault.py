"""User secrets ("Keys" vault), stored in secrets.json under "vault":
{name: {value, note, expose, updated, topics?}}.

Secret FILES are in maxxing/vault_files.py (secrets.json "vault_files").

Secrets flagged `expose` are exported as environment variables to every Claude turn and every
shell cron job (`exposed_env(path)`, merged by the session spawner and by maxxing.crons). `topics` (a list of
`projects/<p>` or `projects/<p>/topics/<t>`) limits a key to the sessions and jobs of these projects / topics;
empty or missing: every topic.
"""
from __future__ import annotations

import re
import time
from typing import Any

from . import config

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}\Z")
TOPICS_MAX = 50
# Environment variables a secret must never shadow when exposed: system basics, and the ones that make
# shells, interpreters, git or Claude load code or send credentials somewhere else.
RESERVED = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "PWD", "TERM", "LANG", "LC_ALL", "TZ",
            "HOSTNAME", "TMPDIR", "PYTHONPATH", "LD_PRELOAD", "LD_LIBRARY_PATH",
            "LD_AUDIT", "BASH_ENV", "ENV", "PROMPT_COMMAND", "NODE_OPTIONS", "NODE_PATH",
            "PYTHONSTARTUP", "PYTHONHOME", "GIT_SSH_COMMAND", "GIT_EXEC_PATH", "ANTHROPIC_BASE_URL",
            "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CONFIG_DIR", "SHELLOPTS", "PS4", "SSH_AUTH_SOCK",
            "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
            "CLAUDE_CODE_SHELL_PREFIX", "SSH_ASKPASS", "SSH_ASKPASS_REQUIRE", "SUDO_ASKPASS", "PERL5OPT", "PERL5LIB",
            "PERL5DB", "RUBYOPT", "RUBYLIB", "JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "PAGER", "MANPAGER", "EDITOR",
            "VISUAL", "BROWSER", "LESSOPEN", "LESSCLOSE", "IFS", "ZDOTDIR", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL",
            "PIP_CONFIG_FILE", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL", "UV_DEFAULT_INDEX", "NPM_CONFIG_REGISTRY"}
# Whole families: git config/dirs/askpass, loader and interpreter hooks, TLS trust stores, config dirs.
RESERVED_PREFIXES = ("MAXXING_", "GIT_", "LD_", "DYLD_", "PYTHON", "NODE_", "BASH_", "XDG_", "SSL_")


def is_reserved(name: str) -> bool:
    """True for a name an exposed secret must never set (RESERVED, its prefixes, the *_PROXY variables)."""
    return name in RESERVED or name.startswith(RESERVED_PREFIXES) or name.endswith("_PROXY")


def internal(name: str) -> bool:
    """A key Harness keeps for itself (a mailbox's password, a browser connection's): nothing exposes it on its own."""
    return bool(re.fullmatch(r"MAIL_[A-Z0-9_]+_PASSWORD|BROWSER_EXIT_[A-Z0-9_]+", name))


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
    if is_reserved(name):
        raise VaultError(f"{name} is a reserved environment variable", "reserved_name")


def preview(value: str) -> str:
    """First 4 characters + '…' (only '…' for short values, which 4 characters would half reveal)."""
    return (value[:4] + "…") if len(value) >= 8 else "…"


def check_topics(topics: Any) -> list[str]:
    """The canonical scope: `projects/<p>` or `projects/<p>/topics/<t>` entries, without duplicates. The folders
    need not exist (a deleted topic must not make its keys unsavable)."""
    from . import workspace
    if not isinstance(topics, (list, tuple)):
        raise VaultError("topics is a list of projects/<project> or projects/<project>/topics/<topic>",
                         "invalid_topics")
    if len(topics) > TOPICS_MAX:
        raise VaultError(f"a key is limited to {TOPICS_MAX} projects or topics at most", "invalid_topics")
    out: list[str] = []
    for t in topics:
        try:
            p = workspace.normalize_path(t) if isinstance(t, str) else ""
        except ValueError:
            p = ""
        if not p or p.count("/") > 3:                       # the root, or an agent's folder
            raise VaultError(f"{t!r}: expected projects/<project> or projects/<project>/topics/<topic>",
                             "invalid_topics")
        if p not in out:
            out.append(p)
    return out


def topics_of(entry: dict) -> list[str] | None:
    """The scope of a stored entry: [] = every topic; None = unreadable (hand-edited), so given to no topic."""
    t = entry.get("topics")
    if t is None or t == []:
        return []
    if not isinstance(t, list) or not all(isinstance(x, str) and x.strip("/") for x in t):
        return None
    return [x.strip("/") for x in t]


def in_scope(entry: dict, path: str | None) -> bool:
    """True when the session / job of topic `path` ("" = the workspace root, no topic) may get this entry."""
    scope = topics_of(entry)
    if scope == []:
        return True
    p = (path or "").strip().strip("/")
    if not scope or not p:
        return False
    return any(p == s or p.startswith(s + "/") for s in scope)


def list_secrets() -> list[dict]:
    return [{"name": k, "note": e.get("note", ""), "expose": bool(e.get("expose")), "topics": topics_of(e) or [],
             "updated": e.get("updated"), "preview": preview(e["value"])}
            for k, e in sorted(_vault().items())]


def get(name: str) -> str | None:
    e = _vault().get(name)
    return e["value"] if e else None


def _is_text(v: str) -> bool:
    """Writable to secrets.json (UTF-8): False for a lone surrogate."""
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def set_note_expose(cur: dict[str, Any], note: str | None, expose: bool | None,
                    topics: list[str] | None = None) -> None:
    """The fields a text key and a secret file share (omitted ones keep their value), and the update time."""
    if topics is not None:
        scope = check_topics(topics)
        if scope:
            cur["topics"] = scope
        else:
            cur.pop("topics", None)
    if note is not None:
        if not _is_text(note):
            raise VaultError("note must be valid text", "invalid_note")
        cur["note"] = note.strip()[:200]
    if expose is not None:
        cur["expose"] = bool(expose)
    cur.setdefault("note", "")
    cur.setdefault("expose", False)
    cur["updated"] = time.time()


def put(name: str, value: str | None = None, note: str | None = None, expose: bool | None = None,
        create: bool = False, topics: list[str] | None = None) -> None:
    """Create or update. A new secret needs a value; omitted fields keep their current value.
    `topics`: the projects / topics it is given to ([] = every topic).
    `create`: only a new name (the "Add key" dialog must not replace a key of the same name)."""
    check_name(name)
    with config._lock:                                   # read-modify-write of secrets.json
        s = config.load_secrets()
        vault = s.get("vault") if isinstance(s.get("vault"), dict) else {}
        if isinstance(s.get("vault_files"), dict) and name in s["vault_files"]:
            raise VaultError(f"{name} is already a secret file", "name_taken")    # see vault_files
        if create and name in vault:
            raise VaultError(f"a key named {name} already exists", "exists")
        cur: dict[str, Any] = dict(vault.get(name) or {})
        if value is not None:
            if not value or len(value) > 16384:
                raise VaultError("value must be 1 to 16384 characters", "invalid_value")
            if "\0" in value or not _is_text(value):        # a null byte: every session and job would fail to start
                raise VaultError("value must be text without a null byte", "invalid_value")
            cur["value"] = value
        if not cur.get("value"):
            raise VaultError("a new secret needs a value", "value_required")
        set_note_expose(cur, note, expose, topics)
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


def exposed_env(path: str | None = "") -> dict[str, str]:
    """{NAME: value} of the secrets flagged `expose` that the topic `path` may get (never raises). Without a
    path (the workspace root, a job without a topic): only the keys not limited to topics."""
    try:
        return {k: e["value"] for k, e in _vault().items()
                if e.get("expose") and NAME_RE.match(k) and not is_reserved(k) and "\0" not in e["value"]
                and in_scope(e, path)}
    except Exception:
        return {}
