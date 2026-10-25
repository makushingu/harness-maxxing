"""Memory backup to a private GitHub repository (whitelist + secret scanner + restore).

Safety rules (never relaxed):
- Only whitelisted files are copied: `backup.include` globs (relative to the workspace) plus every
  CLAUDE.md / memory.md, minus a hard deny-list (secrets, .env, keys, logs, attachments, .git…).
- Every file is scanned for secrets by FORMAT (API keys, tokens, private keys). One hit aborts the
  run before anything is committed or pushed; the report lists files and secret kinds, never values.
- The repository must be private: checked through the GitHub API at configuration time and again
  right before every push.
- The token never lands in `.git/config` or argv: git receives it per command through
  `GIT_CONFIG_COUNT/KEY/VALUE` environment variables (http.extraHeader Basic auth).

Layout:
  state_dir('backup')/repo/          working copy (branch main, remote URL without credentials)
  state_dir('backup')/history.jsonl  one line per run {at, ok, commit, files, changed, error}
  state_dir('backup')/state.json     {private, checked_at, cron_id}
  <repo>/_maxxing/config.json        non-secret, server-independent settings
  <repo>/_maxxing/crons/jobs.json    managed cron jobs
  <repo>/_maxxing/mcp.json           MCP servers of Claude Code (user + per topic), literal secrets blanked

Environment overrides (tests): MAXXING_GITHUB_API (REST base URL), MAXXING_GITHUB_GIT (git base URL,
default https://github.com; remote = <base>/<owner>/<name>.git).
"""
from __future__ import annotations

import base64
import contextlib
import fcntl
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import httpx

from . import bus, config

log = logging.getLogger("maxxing.backup")

REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
TOKEN_RE = re.compile(r"\A[\x21-\x7e]{1,255}\Z")   # printable ASCII: it goes into an HTTP header
ALWAYS = ["**/CLAUDE.md", "**/memory.md", "CUSTOMIZATIONS.md", "customizations/*.patch", "projects/*/.maxxing.json",
          "projects/*/topics/*/.maxxing.json", "projects/.order.json"]
META_DIR = "_maxxing"
CRON_NAME = "Memory backup"
MAX_FILE = 5 * 1024 * 1024
HISTORY_MAX = 500
AUTHOR = ("Harness Maxxing", "backup@localhost")

# Directories never descended into, files never copied (matched on the base name, case-insensitive).
PRUNE_DIRS = {".git", "node_modules", "attachments", ".venv", "venv", "__pycache__", ".cache", ".trash",
              ".ssh", ".gnupg", META_DIR}
DENY_FILES = [r"secrets\.json", r"keys\.json", r"\.env", r".*\.env", r"\.env\..*", r".*\.pem", r".*\.key",
              r".*\.p12", r".*\.pfx", r"id_(rsa|dsa|ecdsa|ed25519).*", r".*credentials.*", r".*\.log",
              r".*\.jsonl", r".*\.sqlite3?", r".*\.db", r"\.netrc", r"\.git-credentials", r".*\.kdbx"]
_DENY = re.compile("^(?:" + "|".join(DENY_FILES) + ")$", re.I)

# Secret FORMATS (not words: memory files legitimately mention variable names).
LEAKS: list[tuple[str, re.Pattern[bytes]]] = [(k, re.compile(p.encode())) for k, p in [
    ("Anthropic API key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("GitHub token", r"github_pat_[A-Za-z0-9_]{20,}"),
    ("GitHub token", r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{30,}"),
    ("Slack token", r"(?<![A-Za-z0-9_])xox[abprs]-[A-Za-z0-9-]{10,}"),
    ("AWS access key", r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"),
    ("private key", r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"),
    ("Telegram bot token", r"(?<![A-Za-z0-9_:])\d{8,10}:[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"),
    ("API key (sk-)", r"(?<![A-Za-z0-9_-])sk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    ("Shopify token", r"(?<![A-Za-z0-9_])shp(?:at|ss|ca|pa)_[a-fA-F0-9]{30,}"),
    ("Stripe key", r"(?<![A-Za-z0-9_])(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}"),
    ("Stripe webhook secret", r"(?<![A-Za-z0-9_])whsec_[A-Za-z0-9+/=]{24,}"),
    ("Google API key", r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])"),
    ("npm token", r"(?<![A-Za-z0-9_])npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])"),
    ("Hugging Face token", r"(?<![A-Za-z0-9_])hf_[A-Za-z0-9]{30,}"),
    ("SendGrid key", r"(?<![A-Za-z0-9_])SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}"),
    # a login in an address (postgres://user:password@host): a password of 6+ characters mixing letters and digits,
    # not a placeholder (${PASS}, <password>)
    ("password in a URL", r"[A-Za-z][A-Za-z0-9+.-]{0,20}://[^\s/:@]{1,100}:(?![$<{])(?=[^\s/@]{0,200}\d)"
                          r"(?=[^\s/@]{0,200}[A-Za-z])[^\s/@'\"<>]{6,200}@"),
    ("JSON web token", r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    # a password written next to its label (accounts.md is backed up): a value of 8+ characters mixing letters and
    # digits, not a sentence ("password: in the vault"), a placeholder (<...>, `...`), a variable ($DB_PASS), a link
    # nor a password manager's name ("Password: 1Password")
    # The lookaheads are bounded: unbounded, a long token such as "password:password:..." rescans the rest of the
    # line at every label and the scan turns quadratic (minutes for a few hundred kB). Quotes around the label and
    # the value are allowed so JSON passwords ("password": "...") are caught too.
    ("password", r"(?i)(?:password|passwd|mot de passe|mdp)[\"']?[ \t]*[:=][ \t]*[\"']?(?!\$)(?![^\s]{0,256}://)"
                 r"(?!(?:1password|bitwarden|keepass\w*|lastpass|dashlane|protonpass|keychain)\b)"
                 r"(?=[^\s`'\"<>()]{0,128}\d)(?=[^\s`'\"<>()]{0,128}[A-Za-z])[^\s`'\"<>()]{8,}"),
]]

# Config keys restored from a backup (paths, network and Telegram ids are server-specific).
RESTORABLE_CONFIG = ("timezone", "language", "default_model", "permission_mode", "dashboard", "extensions",
                     "usage_widget", "git_page", "infra_page", "team_page", "maxxing_mode")


class BackupError(Exception):
    """A backup/restore step failed; `code` is a machine code for the API."""

    def __init__(self, message: str, code: str = "backup_failed", files: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.files = files or []


# =============================================================================================
# Config / state
# =============================================================================================
def github_api() -> str:
    return os.environ.get("MAXXING_GITHUB_API", "https://api.github.com").rstrip("/")


def git_base() -> str:
    return os.environ.get("MAXXING_GITHUB_GIT", "https://github.com").rstrip("/")


def _dir() -> Path:
    return config.state_dir("backup")


def _wc() -> Path:
    return _dir() / "repo"


def load_state() -> dict:
    return config.read_json(_dir() / "state.json", {}) or {}


def _update_state(**kw: Any) -> None:
    st = load_state()
    st.update(kw)
    config.write_json(_dir() / "state.json", st)


def _settings() -> dict:
    return config.load_config()["backup"]


def _token() -> str:
    return config.get_secret("github_token")


def remote_url(repo: str) -> str:
    """Remote URL WITHOUT credentials."""
    return f"{git_base()}/{repo}.git"


@contextlib.contextmanager
def _flock() -> Iterator[None]:
    """One backup/restore at a time across processes (UI + cron)."""
    f = open(_dir() / "lock", "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BackupError("Another backup or restore is running - try again in a minute.", "busy") from None
        yield
    finally:
        f.close()


# =============================================================================================
# GitHub API
# =============================================================================================
def _gh(method: str, path: str, tok: str, body: dict | None = None) -> tuple[int, Any]:
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "claude-maxxing"}
    try:
        with httpx.Client(timeout=20) as c:
            r = c.request(method, github_api() + path, headers=headers, json=body)
    except httpx.HTTPError as e:
        raise BackupError(f"GitHub unreachable: {type(e).__name__}", "github_unreachable") from None
    try:
        data = r.json()
    except ValueError:
        data = None
    return r.status_code, data


def _gh_error(status: int, data: Any, what: str) -> BackupError:
    msg = (data or {}).get("message") if isinstance(data, dict) else None
    if status == 401:
        return BackupError("GitHub rejected the token (expired or revoked?).", "bad_token")
    if status == 404:
        return BackupError(f"{what}: not found, or the token cannot see it.", "not_found")
    if status == 403:
        return BackupError(f"{what}: permission denied by GitHub ({msg or 'forbidden'}).", "forbidden")
    return BackupError(f"{what}: GitHub error {status} ({msg or 'unknown'}).", "github_error")


def repo_info(repo: str, tok: str) -> dict:
    """GET /repos/{repo} -> the repository JSON (raises BackupError)."""
    status, data = _gh("GET", f"/repos/{repo}", tok)
    if status != 200 or not isinstance(data, dict):
        raise _gh_error(status, data, f"Repository {repo}")
    return data


def check_private(repo: str, tok: str) -> dict:
    """Refuse anything but a private repository (called before every push)."""
    info = repo_info(repo, tok)
    private = info.get("private") is True
    _update_state(private=private, checked_at=time.time())
    if not private:
        raise BackupError(f"{repo} is PUBLIC - nothing is pushed. Make it private on GitHub first.", "public_repo")
    return info


def create_repo(repo: str, tok: str) -> dict:
    """Create a private, empty repository for the token's user (or an organisation)."""
    owner, name = repo.split("/", 1)
    status, me = _gh("GET", "/user", tok)
    if status != 200 or not isinstance(me, dict):
        raise _gh_error(status, me, "Token owner")
    body = {"name": name, "private": True, "auto_init": False,
            "description": "Harness Maxxing memory backup (private)"}
    path = "/user/repos" if owner.lower() == str(me.get("login", "")).lower() else f"/orgs/{owner}/repos"
    status, data = _gh("POST", path, tok, body)
    if status not in (200, 201) or not isinstance(data, dict):
        if status == 422:
            raise BackupError(f"Could not create {repo}: {(data or {}).get('message', 'invalid')} "
                              "(does it already exist?)", "create_failed")
        raise _gh_error(status, data, f"Creating {repo}")
    return data


def configure(repo: str, tok: str, create: bool = False) -> dict:
    """POST /api/backup/config: verify (or create) the private repo, then store it -> {ok, private, error?}."""
    repo = (repo or "").strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
    tok = (tok or "").strip() or _token()
    if not REPO_RE.match(repo):
        return {"ok": False, "private": None, "error": "Repository must look like owner/name."}
    if not tok:
        return {"ok": False, "private": None, "error": "A GitHub token is required."}
    if not TOKEN_RE.match(tok):
        return {"ok": False, "private": None,
                "error": "This GitHub token is not valid (letters, digits and symbols only, no spaces or accents)."}
    created = False
    try:
        try:
            info = repo_info(repo, tok)
        except BackupError as e:
            if e.code != "not_found" or not create:
                raise
            info = create_repo(repo, tok)
            created = True
        if info.get("private") is not True:
            _update_state(private=False, checked_at=time.time())
            return {"ok": False, "private": False,
                    "error": f"{repo} is public. A memory backup must go to a PRIVATE repository."}
        perms = info.get("permissions")
        if isinstance(perms, dict) and perms.get("push") is False:
            return {"ok": False, "private": True, "error": "This token cannot push to the repository."}
    except BackupError as e:
        return {"ok": False, "private": None, "error": str(e)}
    try:
        with _flock():                                         # never pull the working copy from under a run
            old = _settings().get("repo")
            config.set_secret("github_token", tok)
            config.update_config(backup={"repo": repo})
            _update_state(private=True, checked_at=time.time())
            if old and old != repo:
                shutil.rmtree(_wc(), ignore_errors=True)       # new repo -> fresh working copy
    except BackupError as e:
        return {"ok": False, "private": True, "error": str(e)}
    sched = ensure_schedule()
    bus.invalidate("backup", "crons")
    out: dict[str, Any] = {"ok": True, "private": True, "created": created}
    if sched.get("error"):
        out["warning"] = sched["error"]
    return out


def forget() -> None:
    """DELETE /api/backup: forget repo + token, remove the scheduled job and the working copy.
    BackupError("busy") while a backup or restore runs."""
    with _flock():
        remove_schedule()
        config.set_secret("github_token", None)
        config.update_config(backup={"repo": ""})
        shutil.rmtree(_wc(), ignore_errors=True)
        _update_state(private=None, checked_at=None, cron_id=None)
    bus.invalidate("backup", "crons")


# =============================================================================================
# Scheduling (managed cron job)
# =============================================================================================
def _crons():
    try:
        from . import crons
        return crons
    except ImportError:
        return None


def ensure_schedule() -> dict:
    """Create/update the "Memory backup" shell cron job running `maxxing backup run`."""
    crons = _crons()
    if crons is None:
        return {"error": "The crons module is not available: the backup is not scheduled."}
    s = _settings()
    fields = {"name": CRON_NAME, "schedule": s.get("schedule") or "40 4 * * *", "kind": "shell",
              "command": f"{crons.maxxing_bin()} backup run", "notify": "failure", "timeout_s": 1800,
              "enabled": bool(s.get("repo"))}
    try:
        job = _find_job(crons)
        job = crons.update_job(job["id"], fields) if job else crons.create_job(fields)
        if job:
            _update_state(cron_id=job["id"])
        return {"job": job}
    except Exception as e:
        log.warning("could not schedule the backup: %s", e)
        return {"error": f"Could not schedule the backup: {e}"}


def _find_job(crons) -> dict | None:
    cid = load_state().get("cron_id")
    jobs = crons.list_jobs()
    return (next((j for j in jobs if j.get("id") == cid), None)
            or next((j for j in jobs if j.get("name") == CRON_NAME and "backup run" in j.get("command", "")), None))


def remove_schedule() -> None:
    crons = _crons()
    if crons is None:
        return
    try:
        job = _find_job(crons)
        if job:
            crons.delete_job(job["id"])
    except Exception as e:
        log.warning("could not remove the backup job: %s", e)


MAX_INCLUDE = 100            # patterns
MAX_PATTERN = 200            # characters
MAX_DEEP = 3                 # `**` per pattern: each one is a `.*` the regex may backtrack over
MAX_STARS = 16               # `*` per pattern: each one is a `[^/]*`, `*a*a*a…` backtracks as well


def clean_schedule(schedule: Any) -> str:
    """A backup schedule from the UI or a restored config.json: a valid cron expression."""
    if not isinstance(schedule, str) or not schedule.strip():
        raise BackupError("Invalid schedule", "invalid_schedule")
    crons = _crons()
    if crons is not None:
        try:
            schedule = crons.validate(schedule)
        except ValueError as e:
            raise BackupError(str(e), "invalid_schedule") from None
    return schedule.strip()


def clean_include(include: Any) -> list[str]:
    """Backup patterns from the UI or a restored config.json: relative to the workspace, bounded."""
    if not isinstance(include, list) or len(include) > MAX_INCLUDE:
        raise BackupError(f"Invalid patterns (a list of at most {MAX_INCLUDE})", "invalid_include")
    clean = []
    for g in include:
        if not isinstance(g, str):
            raise BackupError(f"Invalid pattern: {g!r}", "invalid_include")
        g = g.strip()
        while g.startswith("./"):
            g = g[2:]
        if not g or g.startswith(("/", "~")) or ".." in Path(g).parts:
            raise BackupError(f"Invalid pattern: {g!r} (must be relative to the workspace)", "invalid_include")
        if len(g) > MAX_PATTERN or len(re.findall(r"\*\*+", g)) > MAX_DEEP or g.count("*") > MAX_STARS:
            raise BackupError(f"Invalid pattern: {g[:60]!r} (at most {MAX_PATTERN} characters, {MAX_DEEP} ** and "
                              f"{MAX_STARS} *)", "invalid_include")
        clean.append(g)
    return clean


def update_settings(schedule: str | None = None, include: list[str] | None = None) -> None:
    """PUT /api/backup/settings."""
    changes: dict[str, Any] = {}
    if schedule is not None:
        changes["schedule"] = clean_schedule(schedule)
    if include is not None:
        changes["include"] = clean_include(include)
    if changes:
        with config._lock:                                          # noqa: SLF001 - lists must be replaced
            cfg = config.load_config()
            cfg["backup"].update(changes)
            config.save_config(cfg)
        if "schedule" in changes and _settings().get("repo"):
            ensure_schedule()
        bus.invalidate("backup")


# =============================================================================================
# Collect + scan
# =============================================================================================
def glob_re(pattern: str) -> re.Pattern[str]:
    """Glob -> regex on POSIX relative paths: `**/` = any dirs (incl. none), `*` stays in a segment."""
    pattern = re.sub(r"\*{3,}", "**", re.sub(r"(?:\*\*/)+", "**/", pattern))   # `**/**/` = `**/`, `***` = `**`
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


def denied(rel: str) -> bool:
    """Hard deny-list (applies to whitelisted files too)."""
    parts = rel.split("/")
    return bool(_DENY.match(parts[-1])) or any(p in PRUNE_DIRS for p in parts[:-1])


def _patterns(include: Any) -> list[str]:
    """The include patterns that pass `clean_include` (one saved before it existed is skipped), + ALWAYS."""
    out = []
    for g in include if isinstance(include, list) else []:
        try:
            out += clean_include([g])
        except BackupError:
            log.warning("backup: include pattern %.60r ignored (invalid)", g)
    return out + ALWAYS


def collect(root: Path | None = None, include: list[str] | None = None) -> dict[str, Path]:
    """Whitelisted workspace files -> {relative posix path: absolute path}."""
    root = (root or config.workspace()).resolve()
    pats = [glob_re(p) for p in _patterns(include if include is not None else _settings().get("include"))]
    out: dict[str, Path] = {}
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE_DIRS
                             and not (Path(dirpath) / d).is_symlink())
        base = Path(dirpath)
        for fn in sorted(filenames):
            p = base / fn
            rel = p.relative_to(root).as_posix()
            if p.is_symlink() or not p.is_file() or denied(rel):
                continue
            if not any(r.match(rel) for r in pats):
                continue
            try:
                if p.stat().st_size > MAX_FILE:
                    log.warning("backup: %s skipped (larger than 5 MB)", rel)
                    continue
            except OSError:
                continue
            out[rel] = p
    return out


def scan_bytes(data: bytes) -> list[str]:
    """Secret kinds found in a blob (empty = clean); UTF-16 text (BOM, or NULs between ASCII) is decoded first."""
    blobs = [data]
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(data) > 1 and data.count(b"\0") * 3 > len(data)):
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                blobs.append(data.decode(enc).encode())
            except UnicodeDecodeError:
                continue
    return sorted({kind for kind, rx in LEAKS for b in blobs if rx.search(b)})


def scan(files: dict[str, bytes]) -> list[dict]:
    """-> [{file, kinds}] for every file containing a secret-shaped string."""
    hits = []
    for rel, data in sorted(files.items()):
        kinds = scan_bytes(data)
        if kinds:
            hits.append({"file": rel, "kinds": kinds})
    return hits


def sanitized_config() -> dict:
    """Non-secret, server-independent settings exported to `_maxxing/config.json`."""
    cfg = config.load_config()
    out = {k: cfg.get(k) for k in RESTORABLE_CONFIG if k in cfg}
    tg = cfg.get("telegram") or {}
    out["telegram"] = {k: tg.get(k) for k in ("notify_crons", "login_alerts", "reply_mode", "reply_mode_chosen")}
    b = cfg.get("backup") or {}
    out["backup"] = {"schedule": b.get("schedule"), "include": b.get("include")}
    return out


def _cron_jobs_file() -> Path:
    crons = _crons()
    return crons.jobs_path() if crons is not None and hasattr(crons, "jobs_path") \
        else config.STATE / "crons" / "jobs.json"


def snapshot() -> dict[str, bytes]:
    """Everything that goes into the repo: whitelisted files + `_maxxing/` exports."""
    files: dict[str, bytes] = {}
    for rel, p in collect().items():
        try:
            files[rel] = p.read_bytes()
        except OSError as e:
            log.warning("backup: cannot read %s: %s", rel, e)
    files[f"{META_DIR}/config.json"] = (json.dumps(sanitized_config(), indent=2, ensure_ascii=False)
                                        + "\n").encode()
    jobs = _cron_jobs_file()
    if jobs.is_file():
        files[f"{META_DIR}/crons/jobs.json"] = jobs.read_bytes()
    try:
        from . import mcp
        servers = mcp.export()
        if servers:
            files[f"{META_DIR}/mcp.json"] = (json.dumps(servers, indent=2, ensure_ascii=False) + "\n").encode()
    except Exception as e:                                         # noqa: BLE001
        log.warning("backup: MCP servers not exported: %s", e)
    files[f"{META_DIR}/README.md"] = (b"# Harness Maxxing memory backup\n\nPrivate backup of the workspace memory "
                          b"(CLAUDE.md, memory.md, tasks, extensions, skills) made by Harness Maxxing.\n"
                          b"Restore: Settings > Backup > Restore, or `maxxing backup restore`.\n")
    return files


# =============================================================================================
# git
# =============================================================================================
def _auth_env(tok: str | None) -> dict[str, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/echo", "LC_ALL": "C",
           "GIT_CONFIG_NOSYSTEM": "1"}
    if tok:
        b64 = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
        env.update(GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="http.extraHeader",
                   GIT_CONFIG_VALUE_0=f"Authorization: Basic {b64}",
                   GIT_CONFIG_KEY_1="credential.helper", GIT_CONFIG_VALUE_1="")
    return env


def _scrub(text: str, tok: str | None) -> str:
    if tok:
        text = text.replace(tok, "<token>")
        text = text.replace(base64.b64encode(f"x-access-token:{tok}".encode()).decode(), "<token>")
    return text


def git(*args: str, cwd: Path, tok: str | None = None, check: bool = True,
        timeout: int = 300) -> subprocess.CompletedProcess:
    """Run git with credentials passed through the environment only."""
    try:
        r = subprocess.run(["git", *args], cwd=cwd, env=_auth_env(tok), capture_output=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        raise BackupError(f"git {args[0]} timed out", "git_timeout") from None
    except FileNotFoundError:
        raise BackupError("git is not installed on this server", "no_git") from None
    if check and r.returncode != 0:
        err = _scrub(r.stderr.decode(errors="replace").strip(), tok)[-600:]
        raise BackupError(f"git {args[0]} failed: {err}", "git_failed")
    return r


def _out(r: subprocess.CompletedProcess) -> str:
    return r.stdout.decode(errors="replace").strip()


def prepare(repo: str, tok: str) -> tuple[Path, str | None]:
    """Working copy ready on top of origin/main -> (path, remote head sha or None)."""
    wc = _wc()
    wc.mkdir(parents=True, exist_ok=True)
    if not (wc / ".git").is_dir():
        git("init", "-q", "-b", "main", cwd=wc)
    git("config", "user.name", AUTHOR[0], cwd=wc)
    git("config", "user.email", AUTHOR[1], cwd=wc)
    git("config", "core.hooksPath", "/dev/null", cwd=wc)
    url = remote_url(repo)
    if git("remote", "get-url", "origin", cwd=wc, check=False).returncode == 0:
        git("remote", "set-url", "origin", url, cwd=wc)
    else:
        git("remote", "add", "origin", url, cwd=wc)
    git("fetch", "-q", "--prune", "origin", cwd=wc, tok=tok)
    r = git("rev-parse", "--verify", "-q", "refs/remotes/origin/main", cwd=wc, check=False)
    remote = _out(r) if r.returncode == 0 else None
    if remote:
        git("symbolic-ref", "HEAD", "refs/heads/main", cwd=wc)
        git("reset", "-q", "--mixed", remote, cwd=wc)
    return wc, remote


def _materialize(wc: Path, files: dict[str, bytes]) -> None:
    for child in wc.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for rel, data in files.items():
        dest = wc / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def _head(wc: Path) -> str | None:
    r = git("rev-parse", "--verify", "-q", "HEAD", cwd=wc, check=False)
    return _out(r) if r.returncode == 0 else None


# =============================================================================================
# Run / history / status
# =============================================================================================
def _history_path() -> Path:
    return _dir() / "history.jsonl"


def _record(entry: dict) -> None:
    p = _history_path()
    try:
        lines = p.read_text().splitlines() if p.exists() else []
    except OSError:
        lines = []
    lines = (lines + [json.dumps(entry, ensure_ascii=False)])[-HISTORY_MAX:]
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, p)
    bus.invalidate("backup", "health")


def history(limit: int = 100) -> list[dict]:
    """Most recent first."""
    out = []
    try:
        for ln in _history_path().read_text().splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    except OSError:
        pass
    return list(reversed(out))[:limit]


def _stamp() -> str:
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(config.load_config().get("timezone") or "UTC"))
    except Exception:
        now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M")


def run() -> dict:
    """Back up now -> {ok, commit, files, changed, error?, code?, leaks?}. Never raises."""
    started = time.time()
    entry: dict[str, Any] = {"at": started, "ok": False, "commit": None, "files": 0, "changed": False,
                             "error": None}
    try:
        with _flock():
            repo, tok = _settings().get("repo"), _token()
            if not repo or not tok:
                raise BackupError("The backup is not configured (repository + token).", "not_configured")
            check_private(repo, tok)
            files = snapshot()
            leaks = scan(files)
            if leaks:
                raise BackupError("Secret-looking content found - nothing was committed or pushed. "
                                  "Remove the secrets (or the files from the whitelist) and run again: "
                                  + ", ".join(f"{h['file']} ({', '.join(h['kinds'])})" for h in leaks[:20]),
                                  "secret_found", leaks)
            wc, remote = prepare(repo, tok)
            _materialize(wc, files)
            # --force: a .gitignore copied from the workspace (or a global one) must not drop collected files
            git("add", "-A", "--force", cwd=wc)
            changed = git("diff", "--cached", "--quiet", cwd=wc, check=False).returncode != 0
            if changed:
                git("commit", "-q", "--no-verify", "-m", f"backup {_stamp()}", cwd=wc)
            head = _head(wc)
            if head and head != remote:
                check_private(repo, tok)                    # still private right before pushing?
                git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=wc, tok=tok)
            entry.update(ok=True, commit=head, files=len(files), changed=changed)
    except BackupError as e:
        entry.update(error=str(e), code=e.code)
        if e.files:
            entry["leaks"] = e.files
    except Exception as e:                                   # pragma: no cover - defensive
        log.exception("backup failed")
        entry.update(error=f"{type(e).__name__}: {e}", code="internal")
    entry["duration_s"] = round(time.time() - started, 2)
    if entry.get("code") != "busy":
        _record(entry)
    return entry


def status() -> dict:
    """GET /api/backup payload."""
    s = _settings()
    st = load_state()
    h = history(1)
    last = None
    if h:
        last = {k: h[0].get(k) for k in ("at", "ok", "commit", "files", "error")}
    configured = bool(s.get("repo") and _token())
    return {"configured": configured, "repo": s.get("repo") or "",
            "private": st.get("private") if configured else None,
            "schedule": s.get("schedule"), "include": list(s.get("include") or []), "always": list(ALWAYS),
            "last": last}


def last_success_age_h() -> float | None:
    """Hours since the last successful backup (health check); None if never."""
    for e in history(HISTORY_MAX):
        if e.get("ok"):
            return (time.time() - float(e.get("at") or 0)) / 3600
    return None


# =============================================================================================
# Restore
# =============================================================================================
def _safe_rel(name: str) -> str | None:
    p = Path(name)
    if p.is_absolute() or ".." in p.parts or not name or name.startswith("/"):
        return None
    return p.as_posix()


def _extract(wc: Path, rev: str) -> dict[str, bytes]:
    data = git("archive", "--format=tar", rev, cwd=wc).stdout
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        for m in tf.getmembers():
            rel = _safe_rel(m.name)
            if not m.isfile() or rel is None:
                continue
            f = tf.extractfile(m)
            if f is not None:
                out[rel] = f.read()
    return out


def restore(ref: str | None = None, hold: bool | None = None) -> dict:
    """Restore whitelisted files from the backup repo -> {ok, files, unchanged, trash, error?}.

    Existing files that differ are moved to state_dir('trash')/backup-restore-<ts>/ first.
    `_maxxing/crons/jobs.json` replaces the cron jobs (crontab re-synced); `_maxxing/config.json`
    restores only server-independent settings. `hold`: True = keep what would run code here off (as on a server
    in use) even on a new server (the installer does that, then asks), None = decided by `_fresh_server()`.
    """
    try:
        with _flock():
            repo, tok = _settings().get("repo"), _token()
            if not repo or not tok:
                raise BackupError("The backup is not configured (repository + token).", "not_configured")
            wc, remote = prepare(repo, tok)
            rev = ref or remote
            if not rev:
                raise BackupError("The backup repository is empty.", "empty")
            if ref and git("rev-parse", "--verify", "-q", f"{ref}^{{commit}}", cwd=wc, check=False).returncode:
                raise BackupError(f"Unknown revision {ref!r}.", "bad_ref")
            files = _extract(wc, rev)
            return _apply(files, hold)
    except BackupError as e:
        return {"ok": False, "files": 0, "error": str(e), "code": e.code}


def _apply(files: dict[str, bytes], hold: bool | None = None) -> dict:
    root = config.workspace()
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    trash = config.STATE / "trash" / f"backup-restore-{time.strftime('%Y%m%d-%H%M%S')}"
    restored, unchanged = [], 0
    hooks_held: list[str] = []
    # A new server (no session yet: the installer's restore, a move) gets everything back as it was. A server in use
    # keeps what the backup would run here off until the user turns it on (whoever can push to the backup repository
    # must not get code run on it).
    if hold is None:
        hold = not _fresh_server()
    hooks_kept: dict[str, object] = {}
    skipped: list[str] = []

    def put(dest: Path, data: bytes, rel_trash: str) -> bool:
        nonlocal unchanged
        moved = None
        if dest.is_file():
            try:
                if dest.read_bytes() == data:
                    unchanged += 1
                    return False
            except OSError:
                pass
            t = trash / rel_trash
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(t))
            moved = t
        tmp = dest.with_name(dest.name + ".restore-tmp")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            os.replace(tmp, dest)
        except OSError as e:                       # a folder where the file goes, a read-only disk...: the rest goes on
            log.warning("restore: %s skipped: %s", rel_trash, e)
            skipped.append(rel_trash)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            if moved is not None and not dest.exists():  # the file in place stays in place, not in the trash
                try:
                    shutil.move(str(moved), str(dest))
                except OSError:
                    pass
            return False
        return True

    # A server in use only writes what its own backup would save (include + ALWAYS); anything else (a `.mcp.json`, a
    # script, a settings file someone pushed to the repository) is kept aside in the trash until `release_held()`.
    allowed = [glob_re(p) for p in _patterns(_settings().get("include"))] if hold else None
    outside: list[str] = []
    todo = []
    for rel, data in sorted(files.items()):
        if rel.startswith(META_DIR + "/") or denied(rel):
            continue
        dest = (root / rel)
        if root not in dest.resolve().parents:
            continue
        if allowed is not None and not any(r.match(rel) for r in allowed):
            aside = trash / "outside" / rel
            aside.parent.mkdir(parents=True, exist_ok=True)
            aside.write_bytes(data)
            outside.append(rel)
            continue
        todo.append((rel, dest, data))
    from . import extensions
    ext_held: list[str] = []
    # Extension code is turned off BEFORE a byte of it is written, under the lock the extension loader holds: a scan
    # running meanwhile (hot reload, another request, the server while the CLI restores) never imports it.
    with extensions.publishing():
        if hold:
            ext_held = _hold_new_extension_code([rel for rel, dest, data in todo if _differs(dest, data)])
        for rel, dest, data in todo:
            if hold:
                data, stripped = _strip_hooks(rel, data)
                if stripped is not None:
                    hooks_held.append(rel)
                    hooks_kept[rel] = stripped
            if put(dest, data, "workspace/" + rel):
                restored.append(rel)

    crons_restored = False
    held: dict[str, list[str]] = {"crons": [], "extensions": []}
    held_job_ids: list[str] = []
    jobs = files.get(f"{META_DIR}/crons/jobs.json")
    if jobs is not None:
        try:
            if hold:
                jobs, held["crons"], held_job_ids = _hold_new_jobs(jobs)
            else:
                json.loads(jobs)
            if put(_cron_jobs_file(), jobs, "state/crons/jobs.json"):
                crons_restored = True
                crons = _crons()
                if crons is not None and hasattr(crons, "sync_crontab"):
                    crons.sync_crontab()
        except Exception as e:
            log.warning("restore: cron jobs not restored: %s", e)
    mcp_added = 0
    held["mcp"] = []
    mcp_blob = files.get(f"{META_DIR}/mcp.json")
    if mcp_blob is not None:
        try:
            from . import mcp
            remote, local = _split_mcp(json.loads(mcp_blob))
            if not hold:
                remote, local = remote + local, []
            mcp_added = mcp.restore(remote)
            have = {(x["name"], x["where"]["rel"]) for x in mcp.servers() if x["scope"] in ("user", "local")}
            local = [it for it in local if (it.get("name"), it.get("where")) not in have]
            if local:
                t = trash / "mcp-held.json"
                t.parent.mkdir(parents=True, exist_ok=True)
                t.write_text(json.dumps(local, indent=2, ensure_ascii=False) + "\n")
                os.chmod(t, 0o600)
                held["mcp"] = [str(it.get("name")) for it in local]
        except Exception as e:                                     # noqa: BLE001
            log.warning("restore: MCP servers not restored: %s", e)
    cfg_blob = files.get(f"{META_DIR}/config.json")
    if cfg_blob is not None:
        try:
            saved = json.loads(cfg_blob)
            changes = {k: saved[k] for k in RESTORABLE_CONFIG if k in saved}
            if isinstance(saved.get("telegram"), dict):
                changes["telegram"] = {k: v for k, v in saved["telegram"].items()
                                       if k in ("notify_crons", "login_alerts", "reply_mode", "reply_mode_chosen") and v is not None}
            if isinstance(saved.get("backup"), dict):
                with config._lock:                                       # noqa: SLF001
                    cfg = config.load_config()
                    for k, clean in (("schedule", clean_schedule), ("include", clean_include)):
                        if saved["backup"].get(k):
                            try:
                                cfg["backup"][k] = clean(saved["backup"][k])
                            except BackupError as e:      # the same checks as Settings: else the current value stays
                                log.warning("backup: restored %s ignored: %s", k, e)
                    config.save_config(cfg)
            if ext_held and isinstance(changes.get("extensions"), dict):
                # the saved settings bring their own disabled list: what this restore holds stays off in the same
                # write (never a moment where held code looks enabled)
                ext = dict(changes["extensions"])
                dis = ext.get("disabled") if isinstance(ext.get("disabled"), list) else []
                ext["disabled"] = sorted({x for x in dis if isinstance(x, str)} | set(ext_held))
                changes["extensions"] = ext
            if changes:
                config.update_config(**changes)
        except (ValueError, TypeError) as e:
            log.warning("restore: config not restored: %s", e)
    held["extensions"] = ext_held
    held["hooks"] = hooks_held
    if hooks_kept:                                   # kept aside, to put back by hand once checked
        t = trash / "hooks-held.json"
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(json.dumps(hooks_kept, indent=2, ensure_ascii=False) + "\n")
        os.chmod(t, 0o600)
    # not run by the restore, but worth a look before use: skills (instructions + scripts), product patches
    held["review"] = [r for r in restored if "/.claude/skills/" in "/" + r or r.startswith("customizations/")][:50] \
        if hold else []
    if outside:
        held["outside"] = outside
    if held["crons"] or held["extensions"] or held["hooks"] or held["mcp"] or held["review"] or outside:
        manifest = trash / HELD_FILE                 # what `release_held()` turns on once the user said so
        manifest.parent.mkdir(parents=True, exist_ok=True)
        config.write_json(manifest, {"at": time.time(), "cron_ids": held_job_ids, **held, "released": False})
        os.chmod(manifest, 0o600)
        _update_state(held=str(manifest))
        what = [f"{len(held['crons'])} job(s): {', '.join(held['crons'][:10])}" if held["crons"] else "",
                f"{len(held['extensions'])} extension(s) with code: {', '.join(held['extensions'][:10])}"
                if held["extensions"] else "",
                f"hooks / commands removed from {', '.join(held['hooks'][:5])} (saved in {trash / 'hooks-held.json'})"
                if held["hooks"] else "",
                f"{len(held['mcp'])} local MCP server(s) not added back: {', '.join(held['mcp'][:10])} (saved in "
                f"{trash / 'mcp-held.json'}, add them again in Settings -> MCP)" if held["mcp"] else "",
                f"to review before use: {len(held['review'])} skill / customization file(s)" if held["review"] else "",
                f"{len(outside)} file(s) outside the backup list kept aside: {', '.join(outside[:5])} (in "
                f"{trash / 'outside'})" if outside else ""]
        try:
            from . import feed
            feed.system("Restored but turned off - check them first",
                        "The backup brought code that runs on this server; it stays off until you turn it on: "
                        + "; ".join(w for w in what if w) + ". Crons and Extensions pages.",
                        "warning", "security", group="backup-restore-held")
        except Exception:                          # the notice is a convenience: the restore itself is done
            log.warning("restore: notice not posted", exc_info=True)
    from . import trash as trash_mod
    trash_mod.invalidate_sizes()                   # previous versions were written into the trash
    bus.invalidate("backup", "workspace", "tasks", "crons", "extensions", "mcp")
    return {"ok": True, "files": len(restored), "restored": restored[:200], "unchanged": unchanged,
            "skipped": skipped[:200],
            "crons": crons_restored, "mcp": mcp_added, "held": held, "trash": str(trash) if trash.exists() else None}


def _differs(dest: Path, data: bytes) -> bool:
    """Would the restore write `data` to `dest` (missing or different)?"""
    try:
        return not dest.is_file() or dest.read_bytes() != data
    except OSError:
        return True


def _split_mcp(items: object) -> tuple[list[dict], list[dict]]:
    """MCP servers of a backup -> (remote, local). A local (stdio) server is a command Claude Code starts at every
    turn: like a new cron job, it never comes back on its own (whoever can push to the backup repository must not
    get code run here); remote servers (an URL) are only reached, they are restored."""
    remote, local = [], []
    for it in items if isinstance(items, list) else []:
        cfg = it.get("config") if isinstance(it, dict) else None
        if not isinstance(cfg, dict):
            continue
        if cfg.get("command") or cfg.get("type", "stdio" if not cfg.get("url") else "http") == "stdio":
            local.append(it)
        else:
            remote.append(it)
    return remote, local


_JOB_CODE = ("kind", "command", "prompt", "topic_path", "permission_mode", "model")   # what decides what a job runs


def _hold_new_jobs(blob: bytes) -> tuple[bytes, list[str], list[str]]:
    """Jobs of a restored jobs.json run code here (a shell command as root, a Claude prompt with its permission
    mode): the ones this server does not already have exactly the same come back disabled (whoever can push to the
    backup repository must not get code run here)."""
    data = json.loads(blob)
    current = {_job_key(j) for j in _current_jobs()}
    names, ids = [], []
    for j in (data.get("jobs") if isinstance(data, dict) else None) or []:
        if isinstance(j, dict) and j.get("enabled", True) and _job_key(j) not in current \
                and not (j.get("kind", "shell") == "shell" and _OWN_JOB.match(str(j.get("command") or ""))):
            j["enabled"] = False
            names.append(str(j.get("name") or j.get("id")))
            ids.append(str(j.get("id")))
    return (json.dumps(data, indent=2, ensure_ascii=False).encode() if names else blob), names, ids


def _job_key(j: dict) -> tuple:
    return (j.get("id"), *(str(j.get(k) or ("shell" if k == "kind" else "")) for k in _JOB_CODE))


_OWN_JOB = re.compile(r"^(/[\w./-]+/)?maxxing backup run$")       # Harness' own memory backup job


def _current_jobs() -> list[dict]:
    try:
        data = json.loads(_cron_jobs_file().read_text())
        return [j for j in data.get("jobs") or [] if isinstance(j, dict)]
    except (OSError, ValueError, AttributeError):
        return []


_EXT_CODE = (".py", ".js", ".mjs", ".html", ".htm")


def _hold_new_extension_code(restored: list[str]) -> list[str]:
    """Extensions any of whose code files the restore is about to write are disabled (Python runs inside the
    server - an api.py imports its sibling modules -, scripts and HTML inside the signed-in app). Called before the
    files are written, under `extensions.publishing()`."""
    ids = sorted({rel.split("/")[1] for rel in restored
                  if rel.startswith("extensions/") and rel.count("/") >= 2 and rel.lower().endswith(_EXT_CODE)})
    if ids:
        with config._lock:                                           # noqa: SLF001
            cfg = config.load_config()
            ext = cfg.get("extensions") if isinstance(cfg.get("extensions"), dict) else {}
            dis = {x for x in ext.get("disabled") or [] if isinstance(x, str)} | set(ids)
            config.update_config(extensions={**ext, "disabled": sorted(dis)})
    return ids


_CLAUDE_SETTINGS = re.compile(r"(^|/)\.claude/settings(\.local)?\.json$")


# Claude Code settings that run a command or redirect Claude (hooks, status line, key helpers, environment, the
# project's .mcp.json servers): not restored as is on a server in use.
HELD_SETTINGS = ("hooks", "statusLine", "apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "otelHeadersHelper",
                 "env", "enableAllProjectMcpServers", "enabledMcpjsonServers")


def _strip_hooks(rel: str, data: bytes) -> tuple[bytes, object]:
    """Claude Code settings of the workspace: the HELD_SETTINGS keys are taken out on a server in use.
    -> (data to write, {"settings": {key: value}} taken out, the raw text if unreadable, or None)."""
    if not _CLAUDE_SETTINGS.search(rel):
        return data, None
    try:
        d = json.loads(data)
    except ValueError:
        return b"{}\n", data.decode(errors="replace")               # unreadable: not restored, kept aside
    if not isinstance(d, dict):
        return b"{}\n", data.decode(errors="replace")
    held = {k: d.pop(k) for k in HELD_SETTINGS if k in d}
    if held:
        return (json.dumps(d, indent=2) + "\n").encode(), {"settings": held}
    return data, None


def _fresh_server() -> bool:
    """No session was ever started here: a new install (the installer's restore, a move to a new server)."""
    try:
        from .sessions import store
        return not any(True for _ in store.list_ids())
    except Exception:  # noqa: BLE001 - unknown: treat as a server in use (the careful side)
        return False


def restore_from(repo: str, tok: str, ref: str | None = None, hold: bool | None = None) -> dict:
    """Installer bootstrap: configure an existing private backup repo, then restore it."""
    res = configure(repo, tok, create=False)
    if not res.get("ok"):
        return {"ok": False, "files": 0, "error": res.get("error")}
    return restore(ref, hold)


# ---- held items (restored but kept off) --------------------------------------------------------
HELD_FILE = "held.json"


def held_lines(held: dict) -> list[str]:
    """Human summary of what a restore kept off (CLI, installer)."""
    out = []
    if held.get("crons"):
        out.append(f"{len(held['crons'])} scheduled job(s) disabled: {', '.join(held['crons'][:10])}")
    if held.get("extensions"):
        out.append(f"{len(held['extensions'])} extension(s) with code disabled: {', '.join(held['extensions'][:10])}")
    if held.get("hooks"):
        out.append(f"Claude Code hooks / commands taken out of: {', '.join(held['hooks'][:5])}")
    if held.get("mcp"):
        out.append(f"{len(held['mcp'])} local MCP server(s) not added: {', '.join(held['mcp'][:10])}")
    if held.get("outside"):
        out.append(f"{len(held['outside'])} file(s) outside the backup list kept aside: {', '.join(held['outside'][:5])}"
                   + (" ..." if len(held["outside"]) > 5 else ""))
    if held.get("review"):
        out.append(f"{len(held['review'])} skill / customization file(s) to review: {', '.join(held['review'][:5])}"
                   + (" ..." if len(held["review"]) > 5 else ""))
    return out


def held_manifest() -> tuple[Path | None, dict | None]:
    """The last restore's held items -> (path, data); (None, None) when nothing is held."""
    p = load_state().get("held")
    if not p:
        return None, None
    path = Path(p)
    data = config.read_json(path, None)
    return (path, data) if isinstance(data, dict) else (None, None)


def release_held() -> dict:
    """Turn on what the last restore kept off: its cron jobs, extensions, Claude Code hooks / commands, local MCP
    servers and the files outside the backup list (`maxxing backup release`, the installer after the user's yes).
    -> {ok, crons, extensions, hooks, mcp, files}."""
    path, m = held_manifest()
    if not m or m.get("released"):
        return {"ok": True, "nothing": True, "crons": [], "extensions": [], "hooks": [], "mcp": 0, "files": []}
    out: dict[str, Any] = {"ok": True, "crons": [], "extensions": [], "hooks": [], "mcp": 0, "files": []}
    crons = _crons()
    for cid in m.get("cron_ids") or []:
        try:
            if crons is not None and crons.update_job(cid, {"enabled": True}):
                out["crons"].append(cid)
        except Exception as e:                                     # noqa: BLE001
            log.warning("release: job %s not enabled: %s", cid, e)
    ids = set(m.get("extensions") or [])
    if ids:
        with config._lock:                                           # noqa: SLF001
            cfg = config.load_config()
            ext = cfg.get("extensions") if isinstance(cfg.get("extensions"), dict) else {}
            dis = [x for x in ext.get("disabled") or [] if x not in ids]
            config.update_config(extensions={**ext, "disabled": dis})
        out["extensions"] = sorted(ids)
    root = config.workspace().resolve()
    for rel in m.get("outside") or []:
        src, dest = path.parent / "outside" / str(rel), root / str(rel)
        if root not in dest.resolve().parents or not src.is_file() or dest.exists():
            continue                                                   # written here since: leave it to the user
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        out["files"].append(rel)
    hooks = config.read_json(path.parent / "hooks-held.json", {}) or {}
    for rel, val in hooks.items() if isinstance(hooks, dict) else []:
        dest = root / rel
        if root not in dest.resolve().parents or not _CLAUDE_SETTINGS.search(rel):
            continue
        if isinstance(val, str):                                       # the file was unreadable: put it back as is
            data = val
        else:
            keys = val["settings"] if isinstance(val, dict) and set(val) == {"settings"} \
                and isinstance(val["settings"], dict) else {"hooks": val}  # before 2.0.0a79: the hooks alone
            cur = config.read_json(dest, {}) or {}
            if not isinstance(cur, dict) or any(k in cur for k in keys):
                continue                                               # changed since: leave it to the user
            data = json.dumps({**cur, **keys}, indent=2) + "\n"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(data)
        out["hooks"].append(rel)
    local = config.read_json(path.parent / "mcp-held.json", []) or []
    if local:
        try:
            from . import mcp
            out["mcp"] = mcp.restore(local)
        except Exception as e:                                     # noqa: BLE001
            log.warning("release: MCP servers not added: %s", e)
    config.write_json(path, {**m, "released": True, "released_at": time.time()})
    bus.invalidate("crons", "extensions", "mcp", "workspace")
    return out
