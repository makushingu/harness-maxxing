"""License: the optional Enterprise key of this server, and the move of old installs to git.

Harness Maxxing is fair source (2.0.0a87): every install gets its code from the public git repository (`stable`).
An Enterprise key is only recorded (`activate`: the license server checks it and counts this server, one key = one
server); it never changes how the server runs nor where its code comes from.

Installs from before 2.0.0a87 got their code from signed archives (`license_token` in secrets.json, `enabled()`).
Their old code still downloads the newest archive; as soon as this code runs there, `move_to_git()` turns the code
directory into a clone of the public repository on `stable` (same version, customizations kept), triggered at
start, every few hours and by `maxxing update` (see api/system.py and cmd_core.cmd_update). Downloading,
verifying and importing archives is gone from this code: those servers never need it again.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import __version__, config

API = os.environ.get("MAXXING_LICENSE_API", "https://api.harness-maxxing.com").rstrip("/")
KEY = "license_key"          # secrets.json
TOKEN = "license_token"      # secrets.json: set only on a server still on signed archives (before a87)
SEAT = "license_seat"        # secrets.json (activation token of a key: only to free the seat, `release`)
USER_AGENT = f"harness-maxxing/{__version__}"


class LicenseError(RuntimeError):
    def __init__(self, message: str, code: str = "error", data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.data = data or {}


def enabled() -> bool:
    """This install still runs the code of a signed archive (before 2.0.0a87): it moves to git soon."""
    return bool(config.get_secret(TOKEN))


def machine_id() -> str:
    """One-way fingerprint of this machine (the raw id never leaves the server)."""
    for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            raw = Path(p).read_text().strip()
            if raw:
                break
        except OSError:
            continue
    else:
        f = config.state_dir() / "machine-id"
        if not f.exists():
            f.write_text(uuid.uuid4().hex)
        raw = f.read_text().strip()
    return hashlib.sha256(f"harness-maxxing:{raw}".encode()).hexdigest()


def os_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def _post(path: str, body: dict, timeout: float = 25) -> dict:
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", "user-agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read() or b"{}")
        except ValueError:
            j = {}
        raise LicenseError(j.get("message") or f"license server answered HTTP {e.code}", j.get("error") or f"http_{e.code}", j) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise LicenseError(f"cannot reach the license server ({API}): {e}", "network") from None


def _save_info(lic: dict | None = None, **extra) -> dict:
    cur = config.load_config().get("license") or {}
    if lic:
        cur.update({k: lic.get(k) for k in ("email", "kind", "status", "max_servers", "updates_until", "expires_at", "channel")})
    cur.update(extra)
    config.update_config(license=cur)
    return cur


def status() -> dict:
    """What the UI / doctor show (no secret). `enabled` = still on signed archives; `has_key` = an Enterprise key
    is recorded (fair source: the key is a right of use, it changes nothing in how the server runs)."""
    info = dict(config.load_config().get("license") or {})
    key = config.get_secret(KEY)
    info.update(enabled=enabled(), has_key=bool(key), key_hint=(key[:7] + "…" + key[-4:]) if key else "", api=API)
    return info


def disk_version(code: Path | None = None) -> str:
    try:
        src = ((code or config.CODE) / "server" / "maxxing" / "__init__.py").read_text()
        for line in src.splitlines():
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return __version__


def activate(key: str, version: str | None = None) -> dict:
    """Record an Enterprise key on this server: the license server checks it and counts this server (one key =
    one server) -> its answer. Since 2.0.0a88 the code keeps coming from git: the activation token only frees
    the seat later (SEAT), it no longer switches the server to signed archives (TOKEN)."""
    r = _post("/v1/activate", {"key": key.strip(), "machine_id": machine_id(), "hostname": socket.gethostname(),
                               "os": os_name(), "version": version or disk_version()})
    config.set_secret(KEY, key.strip().upper())
    if enabled():
        config.set_secret(TOKEN, r["token"])          # still on archives (a pre-a87 install): moves to git soon
    else:
        config.set_secret(SEAT, r["token"])
    _save_info(r.get("license"), activation_id=r.get("activation_id"), activated_at=time.time(), message="")
    return r


def remove_key() -> dict:
    """Forget the Enterprise key; frees its seat on the license server when it can (offline: forgotten anyway)."""
    freed = False
    if config.get_secret(SEAT) and not enabled():
        try:
            release()
            freed = True
        except LicenseError:
            pass
    config.set_secret(KEY, None)
    config.set_secret(SEAT, None)
    with config._lock:                     # replaced, not merged: update_config would keep the old info
        cfg = config.load_config()
        cfg["license"] = {k: v for k, v in (cfg.get("license") or {}).items() if k in ("moved_to_git",)}
        config.save_config(cfg)
    return {"ok": True, "freed": freed}


def release() -> dict:
    """Free this server's place on the license (moving to another server)."""
    tok = config.get_secret(TOKEN) or config.get_secret(SEAT)
    if not tok:
        raise LicenseError("this server has no license", "no_license")
    r = _post("/v1/release", {"token": tok, "machine_id": machine_id()})
    config.set_secret(SEAT, None)       # TOKEN stays on a server still on archives: it marks the move to git to do
    _save_info(released_at=time.time())
    return r


def _git(code: Path, *args: str, env: dict | None = None, timeout: float = 120) -> str:
    p = subprocess.run(["git", "-C", str(code), *args], capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, **(env or {})})
    if p.returncode != 0:
        raise LicenseError(f"git {args[0]} failed: {(p.stderr or p.stdout).strip()[-300:]}", "git")
    return p.stdout.strip()


# ---- move to git (fair source) -----------------------------------------------------------------
GIT_URL = os.environ.get("MAXXING_GIT_URL", "https://github.com/makushingu/harness-maxxing.git")
GIT_BRANCH = "stable"
PRE_GIT_REF = "refs/maxxing/pre-git"          # HEAD before the move (to inspect or go back by hand)


def _version_at(code: Path, rev: str) -> str | None:
    try:
        src = _git(code, "show", f"{rev}:server/maxxing/__init__.py")
    except LicenseError:
        return None
    for line in src.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return None


_move_lock = threading.Lock()


def move_to_git(code: Path | None = None) -> dict:
    """Harness Maxxing is fair source: a licensed install leaves the signed archives for the public repository.
    The code directory gets `origin` = GIT_URL, its branch becomes `stable` at the same version (the GitHub commit
    with the same files, else the same version number) with the customizations rebased on top, and the activation
    token is forgotten (the key stays: Settings -> License). Then `maxxing update` works as on any git install.
    Never raises: {ok, moved?, skipped?, error?}. Nothing changes until the very end; a failure is retried later."""
    if not _move_lock.acquire(blocking=False):
        return {"ok": False, "error": "already moving"}
    try:
        return _move_to_git(code)
    finally:
        _move_lock.release()


def _move_to_git(code: Path | None) -> dict:
    from . import customs
    code = code or config.CODE
    if not enabled():
        return {"ok": True, "moved": False, "skipped": "not a licensed install"}
    if not (code / ".git").exists():
        return {"ok": False, "error": "no git directory in the code folder"}
    if customs.rebase_in_progress() or customs.pending():
        return {"ok": False, "error": "an update is being finished (customizations being adapted): later"}
    if customs.dirty_files():
        return {"ok": False, "error": "uncommitted changes in the code folder: `maxxing update` saves them first "
                                      "(edits of web/ cannot be kept: undo them)"}
    try:
        cur = _git(code, "rev-parse", "--abbrev-ref", "HEAD")
        if cur == "HEAD":
            return {"ok": False, "error": "detached HEAD (a version under test): later"}
        head = _git(code, "rev-parse", "HEAD")
        # the licensed version that runs (a newer archive may be fetched but not installed): customizations = base..HEAD
        base = _git(code, "merge-base", head, f"refs/remotes/origin/{cur}")
        try:
            _git(code, "remote", "get-url", "origin")
            _git(code, "remote", "set-url", "origin", GIT_URL)
        except LicenseError:
            _git(code, "remote", "add", "origin", GIT_URL)
        _git(code, "fetch", "-q", "origin", "--", f"+refs/heads/{GIT_BRANCH}:refs/remotes/origin/{GIT_BRANCH}",
             env={"GIT_TERMINAL_PROMPT": "0"}, timeout=300)
        tree, version = _git(code, "rev-parse", f"{base}^{{tree}}"), _version_at(code, base)
        target = None
        for rec in _git(code, "log", "--format=%H %T", "-n", "500", f"refs/remotes/origin/{GIT_BRANCH}").splitlines():
            sha, t = rec.split()
            if t == tree:
                target = sha
                break
            if target is None and version and _version_at(code, sha) == version:
                target = sha                                   # same version, keep looking for the same files
        if not target:
            return {"ok": False, "error": f"{version or 'this version'} is not on {GIT_BRANCH} yet: later"}
        _git(code, "update-ref", PRE_GIT_REF, head)
        if _git(code, "branch", "--list", GIT_BRANCH):
            _git(code, "branch", "-m", GIT_BRANCH, f"{GIT_BRANCH}-before-git-{int(time.time())}")
        _git(code, "checkout", "-q", "-b", GIT_BRANCH)
        customs.ensure_identity()
        p = subprocess.run(["git", "-C", str(code), "rebase", "-q", "--onto", target, base, GIT_BRANCH],
                           capture_output=True, text=True, timeout=300)
        if p.returncode != 0:
            subprocess.run(["git", "-C", str(code), "rebase", "--abort"], capture_output=True, timeout=60)
            _git(code, "checkout", "-q", "-f", cur)
            _git(code, "branch", "-D", GIT_BRANCH)
            return {"ok": False, "error": "a customization does not apply on the git version: "
                                          + (p.stderr or p.stdout).strip()[-300:]}
        _git(code, "branch", "--set-upstream-to", f"origin/{GIT_BRANCH}", GIT_BRANCH)
        _git(code, "branch", "-D", cur)
        _git(code, "update-ref", "-d", f"refs/remotes/origin/{cur}")
    except (LicenseError, OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e)[-300:]}
    config.set_secret(SEAT, config.get_secret(TOKEN))  # the key keeps its seat (freed by `remove_key`)
    config.set_secret(TOKEN, None)
    _save_info(moved_to_git=time.time(), move_error="")
    return {"ok": True, "moved": True, "branch": GIT_BRANCH, "commit": target, "version": version}


def try_move_to_git() -> dict:
    """move_to_git() + the outcome kept in config.json "license" (move_error), for doctor and the UI."""
    r = move_to_git()
    if not r.get("ok") and r.get("error") != "already moving":   # the other trigger is on it
        _save_info(move_error=r.get("error") or "?", move_tried_at=time.time())
    return r


def move_due() -> bool:
    last = (config.load_config().get("license") or {}).get("move_tried_at") or 0
    return time.time() - float(last) > 6 * 3600
