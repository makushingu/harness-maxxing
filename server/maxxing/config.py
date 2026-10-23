"""Paths, configuration and secrets.

Everything the server persists lives under the *state dir* (MAXXING_STATE, default
/var/lib/claude-maxxing). The *workspace* (Claude's working tree) is a separate folder
whose path is stored in config.json.

config.json  - non-secret settings (readable, backed up)
secrets.json - chmod 600: password hash, cookie key, setup token, Telegram/GitHub/Claude tokens,
               user secrets (the "Keys" vault)

All writes are atomic (tmp file + rename) and guarded by a process-wide lock.
"""
from __future__ import annotations

import copy
import fcntl
import json
import logging
import os
import pickle
import pwd
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

STATE = Path(os.environ.get("MAXXING_STATE", "/var/lib/claude-maxxing"))
CODE = Path(__file__).resolve().parent.parent.parent      # repo root (…/server/maxxing -> repo)
WEB_DIST = Path(os.environ.get("MAXXING_WEB_DIST") or CODE / "web" / "dist")   # override: dev builds
DOCS_DIR = CODE / "docs" / "user"
SKILLS_DIR = CODE / "skills"
TEMPLATES_DIR = CODE / "templates"

DEFAULT_CONFIG: dict[str, Any] = {
    "workspace": "/root/maxxing",
    "files_root": "/root",
    "bind": "127.0.0.1",
    "port": 8787,
    "public_url": "",
    "timezone": "UTC",
    "system_clock": "follow",          # follow: system zone = timezone | keep: never touch it (shared server)
    # Claude Code folder (skills, ~/.claude/CLAUDE.md, transcripts, sign-in) - "" = ~/.claude. Another folder keeps
    # Harness Maxxing apart from a Claude Code already used on this server (passed as CLAUDE_CONFIG_DIR).
    "claude_dir": "",
    "language": "en",
    "default_model": "",
    "permission_mode": "bypass",          # bypass | acceptEdits | default
    # A turn that ends above this context (tokens) is followed by a summary turn and a fresh thread seeded with it
    # (the same as "Compact"): long sessions stop re-sending their whole history. 0 = off.
    "auto_compact_tokens": 400000,
    # Idle compaction: a message that comes back to a session after its prompt cache expired (last call more than
    # idle_compact_after_s ago) with a context of at least idle_compact_tokens is preceded by the same summary turn:
    # the history would be re-sent uncached anyway. 0 = off; a lower non-zero value is raised to 20000.
    "idle_compact_tokens": 200000,
    "idle_compact_after_s": 3600,
    # Claude's tools refuse to read or edit secrets.json and ~/.ssh (deny rules, every permission mode) + extra rules.
    "protect_secrets": True,
    # A new session without a title gets a short one (2-5 words) from a small model call, else from its first message.
    "short_titles": True,
    "short_titles_model": False,          # short titles by the smallest model (a call per new session) rather than locally
    "claude_deny": [],
    "claude_auto_update": False,          # Claude Code updated by the server while nothing runs (claude_update.py)
    "auto_update": False,                 # Harness updates itself while nobody is on the interface (auto_update.py)
    "claude_quiet_start": True,           # CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: faster start, smaller prompt
    "background_agents": False,           # False: each turn asks Claude for foreground subagents (spawn.agents_args)
    "onboarding_completed": False,
    "profile": {"name": "", "color": "", "emoji": ""},   # the user's pseudo: messages, notifications
    "usage_widget": False,
    "git_page": False,                 # Settings -> Features: the Git & GitHub page and its sidebar entry
    "infra_page": False,               # Settings -> Features: the Infra page (sites, databases, buckets, domains, servers)
    "infra_refresh_min": 15,
    "result_line_hidden": [],          # Sessions: parts of the line under each answer that are hidden (cost, tokens...)           # Infra: background refresh period (minutes) while the page is on
    "donation_hidden": False,          # Settings -> Support: hide the donation links shown elsewhere in the app
    "dashboard": {"order": [], "hidden": []},
    "extensions": {"disabled": [], "pinned": []},
    "telegram": {
        "chat_id": None, "chat_title": "", "user_ids": [], "bot_username": "",
        "threads": {},                     # "#crons" / "#alerts" -> thread id
        "session_threads": {},             # session id -> {tid, name}: one thread per open session
        "thread_days": 30,                 # open sessions idle longer than this lose their thread
        "sessions": {},                    # topic path -> session id (main chat when threads are off)
        "notify_crons": True, "login_alerts": True, "reply_mode": "progress",
        "mirror_web": False,               # web turns are copied into the session's thread (opt-in)
    },
    "backup": {"repo": "", "schedule": "40 4 * * *",
               "include": ["**/CLAUDE.md", "**/memory.md", "**/NOTES.md", "tasks.json",
                           "projects/*/topics/*/accounts.md", "extensions/**", ".claude/skills/**"]},
    "voice": {"engine": "off", "model": "small", "language": "auto", "auto_send": False},
    "update_verify_signature": False,      # maxxing update: the new commit (or its tag) must be signed by a known key
    "upload_max_mb": 2048,                 # per upload (one request of the UI); 0 = no cap
    "upload_min_free_mb": 1024,            # uploads refused (507) when they would leave less free disk
    # Memory cap of each turn / scheduled job unit (systemd MemoryMax: "75%" of RAM, "4G"...; "" or "infinity" = none).
    # Past it the kernel kills the biggest process of that unit only (a runaway render), not the UI or other sessions.
    "unit_memory_max": "75%",
    # systemd protections of turn / job units (sessions.spawn.UNIT_HARDENING: clock, personality, realtime); false = none.
    "unit_hardening": True,
    # Memory budget of ALL scheduled jobs running at once (MemoryMax of maxxing-jobs.slice, written by `maxxing init`):
    # several heavy jobs at night share it instead of each taking `unit_memory_max`. "" or "infinity" = none.
    "jobs_memory_max": "75%",
    # true = programs a scheduled job leaves running in the background outlive it (KillMode=process), as before
    # 2.0.0a70; `maxxing init` writes true on installs that existed before (no silent change), new ones end them.
    "cron_keep_background": False,
}

FLOCK_WAIT_S = 10.0


def _flock_within(fd: int, wait: float) -> bool:
    """Exclusive flock, waiting at most `wait` seconds: another process holding it for longer (a stuck command)
    must never freeze the server."""
    end = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= end:
                return False
            time.sleep(0.02)
        except OSError:
            return False


class ProcessLock:
    """A re-entrant lock shared by the threads of this process AND the other processes on this machine (the
    server, `maxxing` commands, cron runs): an exclusive flock on `<state>/.<name>.lock` while the outermost
    holder is inside. Read-modify-write of config.json / secrets.json / jobs.json from two processes at once would
    otherwise lose one of the changes. Without a writable state dir, or when another process keeps it more than
    FLOCK_WAIT_S, it degrades to the thread lock. Never make an HTTP call to the server while holding it."""

    def __init__(self, name: str):
        self.name = name
        self._rlock = threading.RLock()
        self._depth = 0
        self._fd: int | None = None

    def __enter__(self) -> "ProcessLock":
        self._rlock.acquire()
        if self._depth == 0:
            try:
                fd = os.open(STATE / f".{self.name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
            except OSError:
                fd = None
            if fd is not None and not _flock_within(fd, FLOCK_WAIT_S):
                os.close(fd)                           # held too long elsewhere: go on with the thread lock only
                fd = None
            self._fd = fd
        self._depth += 1
        return self

    def __exit__(self, *exc: object) -> None:
        self._depth -= 1
        if self._depth == 0 and self._fd is not None:
            fd, self._fd = self._fd, None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
        self._rlock.release()

    def acquire(self) -> None:
        self.__enter__()

    def release(self) -> None:
        self.__exit__()


_lock = ProcessLock("config")
log = logging.getLogger("maxxing.config")
_UMASK = os.umask(0o022)
os.umask(_UMASK)


def _atomic_write(path: Path, data: Any, mode: int | None = None) -> None:
    """Exclusive temp file (mkstemp: no predictable name to hijack), right permissions before any byte
    is written (`mode`, else the existing file's, else the umask default), then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None and _in_state(path):
        mode = 0o600                                    # server state: only root reads it (Telegram ids, auth status...)
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = 0o666 & ~_UMASK
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())                        # on disk before the rename: a power cut never leaves it empty
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _in_state(path: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(STATE.resolve())
    except OSError:
        return False


def tighten_state() -> int:
    """Files written before 2.0.0a48 at the top of the state folder (config.json, claude-auth.json, feed.db...) and
    the session/cron files: 0600 like the new ones. -> number of files changed."""
    n = 0
    for folder in (STATE, STATE / "sessions", STATE / "crons", STATE / "telegram"):
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_file(follow_symlinks=False) and e.stat().st_mode & 0o077:
                    os.chmod(e.path, e.stat().st_mode & 0o700)
                    n += 1
            except OSError:
                pass
    return n


def write_json(path: Path, data: Any, mode: int | None = None) -> None:
    """Atomic JSON write usable by every module (sessions, crons, tasks…)."""
    if Path(path) in (config_path(), secrets_path()):
        with _lock:
            _keep_damaged(Path(path))
            _atomic_write(Path(path), data, mode)
        return
    _atomic_write(Path(path), data, mode)    # unique temp file + rename: no lock (never the machine-wide one)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return copy.deepcopy(default)


def _document(path: Path) -> dict:
    """config.json / secrets.json: {} when missing. When damaged: {} too (the server keeps running on
    defaults) - and `_keep_damaged` saves a copy before anything overwrites it."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.error("%s is damaged (%s): using defaults, a copy is kept before the next save", path, e)
        return {}
    if not isinstance(data, dict):
        log.error("%s does not hold a JSON object: using defaults", path)
        return {}
    return data


def damaged_copy_of(path: Path) -> Path | None:
    """The copy kept of a damaged config/secrets file (doctor shows it), if any."""
    copies = sorted(path.parent.glob(path.name + ".damaged-*"))
    return copies[-1] if copies else None


def _keep_damaged(path: Path) -> None:
    """Before overwriting a file that exists but does not parse, keep it: nothing is ever lost (a
    damaged secrets.json would otherwise be replaced by an almost empty vault on the next save)."""
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as f:
            if isinstance(json.load(f), dict):
                return
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        pass
    dest = path.with_name(f"{path.name}.damaged-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, dest)
    os.chmod(dest, 0o600)
    log.error("%s was damaged: kept as %s before saving", path, dest)


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over if isinstance(over, dict) else {}).items():
        if isinstance(out.get(k), dict) and not isinstance(v, dict):
            continue                                    # a section edited into null / a string keeps its defaults
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


# ---- config.json ---------------------------------------------------------------------------
def config_path() -> Path:
    return STATE / "config.json"


_cfg_lock = threading.Lock()
_cfg_cache: dict[str, Any] = {"key": None, "blob": b""}


def load_config() -> dict:
    """config.json merged over DEFAULT_CONFIG - a fresh copy the caller may change. The merged result
    is kept (pickled) while config.json's (inode, mtime, size, ctime) and the defaults are unchanged:
    saves are atomic renames (new inode), so a write by any process is seen at once."""
    p = config_path()
    try:
        st = os.stat(p)
        fkey: tuple | None = (st.st_ino, st.st_mtime_ns, st.st_size, st.st_ctime_ns)
    except OSError:
        fkey = None
    key = (str(p), fkey, tuple((k, id(v)) for k, v in DEFAULT_CONFIG.items()))
    with _cfg_lock:
        if _cfg_cache["key"] == key:
            return pickle.loads(_cfg_cache["blob"])
    cfg = _merge(DEFAULT_CONFIG, _document(p))
    try:
        blob = pickle.dumps(cfg)
    except Exception:  # noqa: BLE001 - never cache what cannot be copied back
        return cfg
    with _cfg_lock:
        _cfg_cache.update(key=key, blob=blob)
    return cfg


def save_config(cfg: dict) -> None:
    with _lock:
        _keep_damaged(config_path())
        _atomic_write(config_path(), cfg)


def update_config(**changes: Any) -> dict:
    """Shallow-merge top-level keys (dict values are deep-merged) and save."""
    with _lock:
        cfg = load_config()
        cfg = _merge(cfg, changes)
        save_config(cfg)
        return cfg


# ---- secrets.json --------------------------------------------------------------------------
def secrets_path() -> Path:
    return STATE / "secrets.json"


def load_secrets() -> dict:
    return _document(secrets_path())


def get_secret(name: str, default: str = "") -> str:
    return load_secrets().get(name) or default


def set_secret(name: str, value: Any) -> None:
    set_secrets({name: value})


def set_secrets(values: dict[str, Any]) -> None:
    """Several secrets in one write: all of them change, or none (None or "" removes one)."""
    with _lock:
        s = load_secrets()
        for name, value in values.items():
            if value is None or value == "":
                s.pop(name, None)
            else:
                s[name] = value
        _keep_damaged(secrets_path())
        _atomic_write(secrets_path(), s, 0o600)


# ---- derived paths -------------------------------------------------------------------------
def workspace() -> Path:
    return Path(load_config()["workspace"] or DEFAULT_CONFIG["workspace"])


def files_root() -> Path:
    return Path(load_config()["files_root"] or DEFAULT_CONFIG["files_root"])


def claude_dir() -> Path:
    """Claude Code's folder: config.claude_dir, else CLAUDE_CONFIG_DIR, else ~/.claude."""
    d = load_config().get("claude_dir") or os.environ.get("CLAUDE_CONFIG_DIR")
    if d:
        return Path(d)
    return Path(os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir) / ".claude"


def state_dir(*parts: str) -> Path:
    p = STATE.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p
