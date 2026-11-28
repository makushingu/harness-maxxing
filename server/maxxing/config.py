"""Paths, configuration and secrets.

Everything the server persists lives under the *state dir* (MAXXING_STATE, default
/var/lib/claude-maxxing). The *workspace* (Claude's working tree) is a separate folder
whose path is stored in config.json.

config.json  - non-secret settings (readable, backed up)
secrets.json - chmod 600: password hash, cookie key, setup token, Telegram/GitHub/Claude tokens,
               user secrets (the "Keys" vault; its files are in secret-files/, see vault_files.py)

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
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

STATE = Path(os.environ.get("MAXXING_STATE", "/var/lib/claude-maxxing"))
CODE = Path(__file__).resolve().parent.parent.parent      # repo root (…/server/maxxing -> repo)
WEB_DIST = Path(os.environ.get("MAXXING_WEB_DIST") or CODE / "web" / "dist")   # override: dev builds
DOCS_DIR = CODE / "docs" / "user"
SKILLS_DIR = CODE / "skills"
TEMPLATES_DIR = CODE / "templates"

# Names tzdata ships that are not zones: `localtime` is a link to /etc/localtime, so `timedatectl set-timezone
# localtime` makes /etc/localtime point at itself (the server falls back to UTC, cron fires an hour or more off).
# `Factory` is a placeholder zone that browsers refuse (Intl.DateTimeFormat throws: the Crons page broke).
PSEUDO_ZONES = ("localtime", "posixrules", "Factory")
PUBLIC_URL_RE = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[^\s]*)?$")   # shared by PUT /api/settings and init

DEFAULT_CONFIG: dict[str, Any] = {
    "workspace": "/root/maxxing",
    "files_root": "/root",
    "bind": "127.0.0.1",
    "port": 8787,
    # second listen address for a reverse proxy in a container ("HOST:PORT", "" = off): `maxxing proxy on`
    "proxy_listen": "",
    "public_url": "",
    "timezone": "UTC",
    "system_clock": "follow",          # follow: system zone = timezone | keep: never touch it (shared server)
    # Claude Code folder (skills, ~/.claude/CLAUDE.md, transcripts, sign-in) - "" = ~/.claude. Another folder keeps
    # Harness Maxxing apart from a Claude Code already used on this server (passed as CLAUDE_CONFIG_DIR).
    "claude_dir": "",
    "language": "en",
    "default_model": "",
    "permission_mode": "bypass",          # bypass | sandbox | acceptEdits | default | ask
    # A turn that ends above this context (tokens) is followed by a summary turn and a fresh thread seeded with it
    # (the same as "Compact"): long sessions stop re-sending their whole history. 0 = off. This threshold and the two
    # below follow the model: never above its context window - 70k (sessions/resume.fit), 130k on a 200k model.
    "auto_compact_tokens": 300000,
    # Idle compaction: a message that comes back to a session after its prompt cache expired (last call more than
    # idle_compact_after_s ago) with a context of at least idle_compact_tokens is preceded by the same summary turn:
    # the history would be re-sent uncached anyway. 0 = off; a lower non-zero value is raised to 20000.
    "idle_compact_tokens": 200000,
    "idle_compact_after_s": 3600,
    # Smart resume: a user message that comes back to a session whose cache expired (idle_compact_after_s) with at
    # least smart_resume_tokens of context, or after 5 min+ with twice that, is preceded by a summary written for
    # that message (it keeps exact what the message needs). 0 = off (idle compaction alone); a lower value -> 20000.
    "smart_resume_tokens": 100000,
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
    "mcp_auto": False,                    # True: each turn loads only the MCP servers its session needs (mcp_auto.py)
    "onboarding_completed": False,
    "profile": {"name": "", "color": "", "emoji": ""},   # the user's pseudo: messages, notifications
    "daily_budget_usd": 0.0,           # Settings -> Usage: dollars a day for the whole server (budget.py), 0 = none
    "usage_widget": False,             # Settings -> Usage: show plan usage (`maxxing init`: on for new installs since 2.0.0a132)
    "maxxing_mode": False,             # Settings -> Features (beta): a finished session comes to the front (Sessions page)
    "health_feed": False,              # server health problems also in the Notifications feed (`maxxing init`: on when new)
    "agents_page": False,              # Settings -> Features: the Agents page (lasting roles of a topic, with triggers)
                                       # (`maxxing init`: on for new installs since 2.0.0a132)
    "team_page": False,                # Settings -> Features: the Team page (chats between people) and its sidebar entry
    "tasks_page": False,               # Settings -> Features: the Tasks page, its sidebar entry and dashboard widget
                                       # (`maxxing init`: on for installs made before Tasks became optional)
    "git_page": False,                 # Settings -> Features: the Git & GitHub page and its sidebar entry
    "code_mode": False,                # Settings -> Features -> Sessions -> Code mode: the terminal drawer (POST /api/term/enable: password)
    "infra_page": False,               # Settings -> Features: the Infra page (sites, databases, buckets, domains, servers)
    "infra_refresh_min": 15,           # Infra: background refresh period (minutes) while the page is on
    "result_line_hidden": [],          # Sessions: parts of the line under each answer that are hidden (cost, tokens...)
    "donation_hidden": False,          # Settings -> About: hide the donation links shown elsewhere in the app
    "mail_page": False,                # Settings -> Features: the E-mail page (IMAP/SMTP mailboxes)
    "sidebar_order": [],               # sidebar: the pages in the order the user dragged them (routes; empty = default)
    "nav_badges_hidden": [],           # Settings -> Features -> Badges: sidebar pages whose counter badge is off (routes)
    "browser_feature": False,          # Settings -> Features: the Harness Browser (one Chromium for the user, sessions, agents)
    "browser": {},                     # its settings (maxxing/browser DEFAULTS: sites, sign-ins, asks, sleep)
    "devices_feature": False,          # Settings -> Features: Devices (Claude uses the user's computers and phones)
    "jarvis_feature": False,           # Settings -> Features: Jarvis (one assistant who runs Harness: jarvis.py)
    "jarvis": {},                      # its settings (jarvis.DEFAULTS: model, root, ask_first, internals, daily, brief, dream)
    "dashboard": {"order": [], "hidden": []},
    "extensions": {"disabled": [], "pinned": []},
    "telegram": {
        "chat_id": None, "chat_title": "", "user_ids": [], "bot_username": "",
        "threads": {},                     # "#crons" / "#alerts" -> thread id
        "session_threads": {},             # session id -> {tid, name}: one thread per open session
        "agent_threads": {},               # agent path -> {tid, name}: the thread of an agent with the telegram option
        "thread_days": 30,                 # open sessions idle longer than this lose their thread
        "notify_crons": True, "login_alerts": True, "reply_mode": "progress",
        "notify_system": True,             # update / rollback / vulnerability problems into the "Alerts" thread
        "mirror_web": False,               # older installs: mode "mirror" (read once by gateway.mode())
        # "mode" (simple | threads | mirror) has no default here: gateway.mode() tells a new install ("simple")
        # from one that already has threads, and the gateway writes the result down
    },
    "backup": {"repo": "", "schedule": "40 4 * * *",
               "include": ["**/CLAUDE.md", "**/memory.md", "**/NOTES.md", "tasks.json",
                           "projects/*/topics/*/accounts.md", "extensions/**", ".claude/skills/**"]},
    "voice": {"engine": "off", "model": "small", "language": "auto", "auto_send": False},
    "update_verify_signature": False,      # maxxing update: "stable" = a published version (branch stable) must be signed by its
                                           # publishers (maxxing/release-signers); true = every branch; false = never
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
    # Settings -> System -> CPU priorities (maxxing/cpu.py): when the processor is full, the server (UI) goes first,
    # then turns, then jobs and `maxxing heavy` (CPUWeight/IOWeight of three slices, never a cap); false = all equal.
    "cpu_priorities": True,
    # true = programs a scheduled job leaves running in the background outlive it (KillMode=process), as before
    # 2.0.0a70; `maxxing init` writes true on installs that existed before (no silent change), new ones end them.
    "cron_keep_background": False,
    # Settings -> Usage: a cron job or an agent run stopped by Claude's usage limit starts again once, this many
    # seconds after the reset (crons.limit_retry_at)
    "limit_retry": True,
    "limit_retry_delay_s": 60,
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


def _atomic_write(path: Path, data: Any, mode: int | None = None, before_replace: Callable[[], None] | None = None) -> None:
    """Exclusive temp file (mkstemp: no predictable name to hijack), right permissions before any byte
    is written (`mode`, else the existing file's, else the umask default), then rename. `before_replace` runs right
    before the rename, once the bytes are on disk: raising there leaves the file as it was."""
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
        if before_replace is not None:
            before_replace()
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


def write_json(path: Path, data: Any, mode: int | None = None, before_replace: Callable[[], None] | None = None) -> None:
    """Atomic JSON write usable by every module (sessions, crons, tasks…); `before_replace`: see _atomic_write."""
    if Path(path) == secrets_path():
        with _lock:
            if secrets_sealed():
                load_secrets()                          # raises when the sealed store cannot be read: never overwritten
                _write_sealed(data, before_replace)
                return
            _keep_damaged(Path(path))
            try:
                _atomic_write(Path(path), data, 0o600 if mode is None else mode, before_replace)
            finally:
                _forget_secrets()
        return
    if Path(path) == config_path():
        with _lock:
            _keep_damaged(Path(path))
            try:
                _atomic_write(Path(path), data, mode, before_replace)
            finally:
                _forget_secrets()
        return
    _atomic_write(Path(path), data, mode, before_replace)    # unique temp file + rename: no lock (never the machine-wide one)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, RecursionError):        # RecursionError: nested too deep
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


def damaged_copies(path: Path) -> list[Path]:
    """Every copy kept of a damaged config/secrets file, oldest first."""
    return sorted(path.parent.glob(path.name + ".damaged-*"))


def damaged_copy_of(path: Path) -> Path | None:
    """The copy kept of a damaged config/secrets file (doctor shows it), if any."""
    copies = damaged_copies(path)
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
    stamp = time.strftime('%Y%m%d-%H%M%S')
    dest = path.with_name(f"{path.name}.damaged-{stamp}")
    n = 1
    while dest.exists():                    # two damaged versions in the same second: both kept
        dest = path.with_name(f"{path.name}.damaged-{stamp}-{n}")
        n += 1
    shutil.copy2(path, dest)
    os.chmod(dest, 0o600)
    log.error("%s was damaged: kept as %s before saving", path, dest)


def keep_damaged(path: Path) -> None:
    """`_keep_damaged` for the other stores (peers.json, devices.json): call it before writing over their file."""
    try:
        _keep_damaged(Path(path))
    except OSError:
        log.exception("could not keep a copy of the damaged %s", path)


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
_cfg_cache: dict[str, Any] = {"key": None, "blob": b"", "shared": None}


def load_config() -> dict:
    """config.json merged over DEFAULT_CONFIG - a fresh copy the caller may change. The merged result
    is kept (pickled) while config.json's (inode, mtime, size, ctime) and the defaults are unchanged:
    saves are atomic renames (new inode), so a write by any process is seen at once."""
    blob, cfg = _config_cached()
    return pickle.loads(blob) if blob is not None else cfg


def _setting(name: str) -> Any:
    """One top-level setting without copying the whole config (paths asked for thousands of times per tree):
    read from the cached merged config - only for values never mutated (strings, numbers)."""
    return _config_cached()[1].get(name)


def _config_cached() -> tuple[bytes | None, dict]:
    """(pickled merged config or None when it cannot be pickled, the merged config - shared: never mutate it)."""
    p = config_path()
    try:
        st = os.stat(p)
        fkey: tuple | None = (st.st_ino, st.st_mtime_ns, st.st_size, st.st_ctime_ns)
    except OSError:
        fkey = None
    key = (str(p), fkey, tuple((k, id(v)) for k, v in DEFAULT_CONFIG.items()))
    with _cfg_lock:
        if _cfg_cache["key"] == key:
            return _cfg_cache["blob"], _cfg_cache["shared"]
    cfg = _merge(DEFAULT_CONFIG, _document(p))
    try:
        blob = pickle.dumps(cfg)
    except Exception:  # noqa: BLE001 - never cache what cannot be copied back
        return None, cfg
    with _cfg_lock:
        _cfg_cache.update(key=key, blob=blob, shared=cfg)
    return blob, cfg


def _chosen(cfg: dict, defaults: dict, raw: Any) -> dict:
    """What config.json must hold: what it held already (with its new value) and what differs from the defaults.
    `cfg` is usually load_config() + a change: writing it whole froze every default, so a default changed by a
    later release never reached an install that had saved any setting."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for k, v in cfg.items():
        d = defaults.get(k, _MISSING)
        if isinstance(v, dict) and isinstance(d, dict):
            sub = _chosen(v, d, raw.get(k))
            if sub or k in raw:
                out[k] = sub
        elif k in raw or v != d:
            out[k] = v
    return out


_MISSING = object()


def save_config(cfg: dict) -> None:
    with _lock:
        _keep_damaged(config_path())
        _atomic_write(config_path(), _chosen(cfg, DEFAULT_CONFIG, _document(config_path())))


def int_setting(cfg: dict, name: str) -> int:
    """A whole-number setting; a hand-edited "300k" / 1e999 / null gives the default, never a crashed turn."""
    for v in (cfg.get(name), DEFAULT_CONFIG.get(name)):
        try:
            return int(v or 0)
        except (TypeError, ValueError, OverflowError):
            continue
    return 0


JARVIS_PATH = "projects/jarvis/topics/main"   # Jarvis's own topic (jarvis.PATH)
JARVIS_COMPACT = 150000                     # its conversation's compaction threshold by default (jarvis.DEFAULTS)
JARVIS_IDLE_COMPACT = 60000              # Jarvis back after the cache expired: summarized past this


def session_config(cfg: dict, path: str | None) -> dict:
    """The settings a session's turn runs with: Jarvis's conversation has its own compaction threshold (its
    settings, `compact_tokens`: 0 = the same as every session). Its turns stay small: what it must keep lives in
    its brain files, not in a long thread. The idle and smart-resume thresholds never go above it."""
    if (path or "").strip("/") != JARVIS_PATH:
        return cfg
    raw = cfg.get("jarvis") if isinstance(cfg.get("jarvis"), dict) else {}
    try:
        n = int(raw.get("compact_tokens", JARVIS_COMPACT) or 0)
    except (TypeError, ValueError, OverflowError):
        n = JARVIS_COMPACT
    if n <= 0:
        return cfg
    out = {**cfg, "auto_compact_tokens": n}
    for k in ("idle_compact_tokens", "smart_resume_tokens"):
        v = int_setting(cfg, k)
        if v > 0:
            out[k] = min(v, n, JARVIS_IDLE_COMPACT)   # reports come back hours later: a cold cache is paid on less
    return out


def update_config(**changes: Any) -> dict:
    """Shallow-merge top-level keys (dict values are deep-merged) and save."""
    with _lock:
        cfg = _merge(load_config(), changes)
        save_config(cfg)
        return cfg


# ---- secrets.json --------------------------------------------------------------------------
def secrets_path() -> Path:
    return STATE / "secrets.json"


_sec_lock = threading.Lock()
_sec_cache: dict[str, Any] = {"key": None, "blob": b"", "error": "", "at": 0.0}

SEALED_NAME = "maxxing-secrets"                # the name systemd-creds binds into the sealed file
SEALED_MAX = 1024 * 1024                       # systemd-creds refuses a larger credential
SEALED_TIMEOUT_S = 30
SEALED_RETRY_S = 5.0                           # a failed decrypt of an unchanged file is not run again before that


class SecretsUnreadable(RuntimeError):
    """secrets.json.cred exists and could not be opened: nothing is read as empty, nothing is written over it."""


class SealError(RuntimeError):
    """systemd-creds missing, too old, or failing."""


def sealed_path() -> Path:
    return STATE / "secrets.json.cred"


def secrets_sealed() -> bool:
    """True once `maxxing keys encrypt` ran: the secrets are in secrets.json.cred, sealed by systemd-creds."""
    return os.path.exists(sealed_path())


def _creds(action: str, data: bytes) -> bytes:
    """`systemd-creds encrypt|decrypt` of `data`, through pipes: the clear text never touches the disk."""
    exe = shutil.which("systemd-creds")
    if not exe:
        raise SealError("systemd-creds not found (it comes with systemd 250 or later)")
    argv = [exe, action, f"--name={SEALED_NAME}"] + (["--with-key=auto"] if action == "encrypt" else []) + ["-", "-"]
    try:
        r = subprocess.run(argv, input=data, capture_output=True, timeout=SEALED_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as e:
        raise SealError(f"systemd-creds {action}: {e}") from None
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise SealError(f"systemd-creds {action} failed: {(err[-1] if err else f'exit {r.returncode}')[:300]}")
    return r.stdout


def _seal(data: dict) -> bytes:
    """`data` sealed, and checked: what comes back from a decrypt is the same document."""
    clear = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    if len(clear) > SEALED_MAX:
        raise SealError(f"the secrets take {len(clear)} bytes: systemd-creds seals {SEALED_MAX} at most")
    sealed = _creds("encrypt", clear)
    if not sealed or _creds("decrypt", sealed) != clear:
        raise SealError("round-trip check failed: what systemd-creds decrypts is not what was encrypted")
    return sealed


def _file_key(path: Path, st: os.stat_result) -> tuple:
    return str(path), st.st_ino, st.st_mtime_ns, st.st_size


def _write_sealed(data: dict, before_replace: Callable[[], None] | None = None) -> None:
    """secrets.json.cred replaced by `data`, sealed (config._lock held by the caller). Raises SealError with the
    file untouched when systemd-creds fails."""
    path = sealed_path()
    sealed = _seal(data)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(sealed)
            f.flush()
            os.fsync(f.fileno())
            key = _file_key(path, os.fstat(f.fileno()))  # unchanged by the rename
        if before_replace is not None:
            before_replace()
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
        _forget_secrets()
    try:
        blob = pickle.dumps(data)
    except Exception:  # noqa: BLE001
        return
    with _sec_lock:
        _sec_cache.update(key=key, blob=blob, error="", at=0.0)


def _load_sealed(path: Path, st: os.stat_result) -> dict:
    key = _file_key(path, st)
    with _sec_lock:
        if _sec_cache["key"] == key:
            if not _sec_cache["error"]:
                return pickle.loads(_sec_cache["blob"])
            if time.monotonic() - _sec_cache["at"] < SEALED_RETRY_S:
                raise SecretsUnreadable(_sec_cache["error"])
    try:
        try:
            sealed = path.read_bytes()
        except FileNotFoundError:
            raise
        except OSError as e:
            raise SealError(str(e)) from None
        data = json.loads(_creds("decrypt", sealed).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except (SealError, ValueError, RecursionError) as e:
        msg = (f"{path} cannot be decrypted ({e}): the secrets are unreadable and nothing is written until this is "
               f"fixed (maxxing doctor)")
        log.error("%s", msg)
        with _sec_lock:
            _sec_cache.update(key=key, blob=b"", error=msg, at=time.monotonic())
        raise SecretsUnreadable(msg) from None
    with _sec_lock:
        _sec_cache.update(key=key, blob=pickle.dumps(data), error="", at=0.0)
    return data


def _forget_secrets() -> None:
    with _sec_lock:
        _sec_cache.update(key=None, blob=b"", error="", at=0.0)


def load_secrets() -> dict:
    """The secrets - a fresh copy the caller may change. Read on every request (sign-in cookie check): the parsed
    file is kept (pickled) while its (inode, mtime, size, ctime) is unchanged, like load_config; every save here
    drops it, and a save by another process is an atomic rename (new inode).
    When secrets.json.cred exists (`maxxing keys encrypt`) it is the store, decrypted by systemd-creds once per
    version of the file; a failure raises SecretsUnreadable, never an empty store."""
    for _ in range(3):                                  # encrypt / decrypt by another process swaps the two files
        sp = sealed_path()
        try:
            return _load_sealed(sp, os.stat(sp))
        except FileNotFoundError:
            pass
        p = secrets_path()
        try:
            st = os.stat(p)
            key: tuple | None = (str(p), st.st_ino, st.st_mtime_ns, st.st_size, st.st_ctime_ns)
        except OSError:
            key = None
        if key is None and secrets_sealed():
            continue
        break
    with _sec_lock:
        if key is not None and _sec_cache["key"] == key and not _sec_cache["error"]:
            return pickle.loads(_sec_cache["blob"])
    data = _document(p)
    if key is None:
        return data
    try:
        blob = pickle.dumps(data)
    except Exception:  # noqa: BLE001 - never cache what cannot be copied back
        return data
    with _sec_lock:
        _sec_cache.update(key=key, blob=blob, error="", at=0.0)
    return data


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
        if secrets_sealed():
            _write_sealed(s)
            return
        _keep_damaged(secrets_path())
        try:
            _atomic_write(secrets_path(), s, 0o600)
        finally:
            _forget_secrets()


def secrets_status() -> dict:
    """{"sealed": bool, "ok": bool, "error": str, "both": bool} for doctor: `both` = a clear secrets.json left next
    to the sealed file (an interrupted encrypt / decrypt, or a tool that wrote it)."""
    if not secrets_sealed():
        return {"sealed": False, "ok": True, "error": "", "both": False}
    both = secrets_path().exists()
    try:
        load_secrets()
    except SecretsUnreadable as e:
        return {"sealed": True, "ok": False, "error": str(e), "both": both}
    return {"sealed": True, "ok": True, "error": "", "both": both}


def seal_secrets() -> str:
    """secrets.json -> secrets.json.cred (`maxxing keys encrypt`). The sealed file is checked by a decrypt before it
    takes its name, and the clear file goes last. -> "sealed" | "already". Raises SealError / SecretsUnreadable
    with the store left as it was."""
    with _lock:
        clear = secrets_path()
        if secrets_sealed():
            data = load_secrets()
            if clear.exists():                           # an interrupted run left both: the sealed one is the store
                if _document(clear) != data:
                    raise SealError(f"{clear} and {sealed_path().name} both exist and differ: the sealed one is in "
                                    f"use - compare them, then delete {clear.name}")
                clear.unlink()
            return "already"
        try:
            with open(clear, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError, RecursionError) as e:
            raise SealError(f"{clear} cannot be read ({e}): repair it first (maxxing doctor)") from None
        if not isinstance(data, dict):
            raise SealError(f"{clear} does not hold a JSON object: repair it first (maxxing doctor)")
        _write_sealed(data)
        _forget_secrets()
        try:
            same = load_secrets() == data                # read back from the disk by a fresh decrypt
        except SecretsUnreadable:
            same = False
        if not same:
            sealed_path().unlink(missing_ok=True)
            _forget_secrets()
            raise SealError("round-trip check failed: the sealed file was removed, secrets.json is unchanged")
        clear.unlink(missing_ok=True)
        return "sealed"


def unseal_secrets() -> str:
    """secrets.json.cred -> secrets.json, mode 600 (`maxxing keys decrypt`). -> "clear" | "already"."""
    with _lock:
        if not secrets_sealed():
            return "already"
        data = load_secrets()
        clear = secrets_path()
        _atomic_write(clear, data, 0o600)
        if _document(clear) != data:
            clear.unlink(missing_ok=True)
            raise SealError("round-trip check failed: secrets.json was not written back whole, nothing changed")
        sealed_path().unlink()
        _forget_secrets()
        return "clear"


# ---- derived paths -------------------------------------------------------------------------
def _path_setting(name: str) -> str | None:
    """A path setting, or None when it is missing or hand-edited to something that is not a string."""
    v = _setting(name)
    return v if isinstance(v, str) and v else None


def local_port() -> int:
    """The port this server listens on (`maxxing serve --port` wins over the config): its local clients (a turn's
    MCP servers, chrome-devtools-mcp) call it there."""
    return int(os.environ.get("MAXXING_LISTEN_PORT") or load_config().get("port") or 8787)


def local_host() -> str:
    """The address this server answers on from this machine: 127.0.0.1, or the `bind` address (Tailscale mode)."""
    bind = str(load_config().get("bind") or "").strip()
    if not bind or bind in ("0.0.0.0", "::", "localhost"):
        return "127.0.0.1"
    return f"[{bind}]" if ":" in bind else bind


def workspace() -> Path:
    return Path(_path_setting("workspace") or DEFAULT_CONFIG["workspace"])


def files_root() -> Path:
    return Path(_path_setting("files_root") or DEFAULT_CONFIG["files_root"])


def claude_dir() -> Path:
    """Claude Code's folder: config.claude_dir, else CLAUDE_CONFIG_DIR, else ~/.claude."""
    d = _path_setting("claude_dir") or os.environ.get("CLAUDE_CONFIG_DIR")
    if d:
        return Path(d)
    return Path(os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir) / ".claude"


def state_dir(*parts: str) -> Path:
    p = STATE.joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p
