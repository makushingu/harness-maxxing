"""Customizations of the web UI: the sources under web/ (never web/dist) are saved like any customization, and this
server builds them into <state>/web-dist (`maxxing custom build`, and after every update that carries them over).

The shipped web/dist stays untouched in the code directory: a local build is served only while it matches the web
sources that are there now (`source_key`), else the shipped build is - an update or a rollback that changes the
sources never shows a stale or broken UI. The previous build is kept (web-dist.prev) so a rollback finds it again.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from . import config

log = logging.getLogger(__name__)

STAMP = ".maxxing-build.json"
LOCK_STAMP = ".maxxing-lock"                     # in node_modules: the package-lock.json it was installed from
SKIP = ("web/dist/", "web/node_modules/")
SOURCE_MAX = 32 << 20                            # a bigger file is keyed by its size and date, never read


def build_dir() -> Path:
    return config.STATE / "web-dist"


def _prev_dir() -> Path:
    return config.STATE / "web-dist.prev"


def is_web_source(path: str) -> bool:
    """A file of the web UI's sources (what a customization may change), not its build."""
    return path.startswith("web/") and not path.startswith(SKIP) and path != "web/dist"


def _git(code: Path, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(code), *args], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, os.fsdecode(r.stdout)        # a file name that is not UTF-8 stays a valid path


def source_key(code: Path | None = None) -> str | None:
    """A hash of the web sources as they are on disk (tracked and new files, ignored ones and the build left out).
    None when the code directory is not a git clone."""
    code = code or config.CODE
    rc, out = _git(code, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "web")
    if rc != 0:
        return None
    h = hashlib.sha256()
    for rel in sorted({p for p in out.split("\0") if p and is_web_source(p)}):
        try:
            digest = _file_digest(code / rel)
        except OSError:                                # deleted but still in the index
            continue
        if digest is not None:
            h.update(os.fsencode(rel) + b"\0" + digest)
    return h.hexdigest()


def _file_digest(path: Path) -> bytes | None:
    """What a source file adds to source_key: a link by its target (like git), never followed - a link to a FIFO or
    to /dev/zero would block every page -, a regular file by its content, anything else left out."""
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        return b"link:" + os.fsencode(os.readlink(path))
    if not stat.S_ISREG(st.st_mode):
        return None
    if st.st_size > SOURCE_MAX:
        return b"big:%d:%d" % (st.st_size, st.st_mtime_ns)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):   # swapped after the lstat
            return None
        return hashlib.sha256(f.read(SOURCE_MAX)).digest()


def _stamp(d: Path) -> dict[str, Any]:
    try:
        return json.loads((d / STAMP).read_text())
    except (OSError, ValueError):
        return {}


_active: dict[str, Any] = {}


def active_dist(ttl: float = 5.0) -> Path:
    """The web build to serve: MAXXING_WEB_DIST when set (dev, tests), else this server's own build when it matches
    the web sources on disk, else the shipped web/dist. Rechecked at most every `ttl` seconds."""
    if os.environ.get("MAXXING_WEB_DIST"):
        return config.WEB_DIST
    now = time.monotonic()
    if (_active.get("path") is not None and _active.get("shipped") == (config.WEB_DIST, config.STATE)
            and now - _active.get("at", 0.0) < ttl):
        return _active["path"]
    path = config.WEB_DIST
    local = [d for d in (build_dir(), _prev_dir()) if (d / "index.html").is_file() and _stamp(d).get("key")]
    if local:
        try:
            key = source_key()
        except Exception:                               # never a page down because of a local build: the shipped one
            log.exception("web sources unreadable, the shipped web UI is served")
            key = None
        path = next((d for d in local if key and _stamp(d)["key"] == key), config.WEB_DIST)
    _active.update(path=path, at=now, shipped=(config.WEB_DIST, config.STATE))
    return path


def cached_dist() -> Path | None:
    """The path active_dist() would answer without any work, or None when it must look again (call it off the
    event loop then: it hashes the web sources)."""
    if os.environ.get("MAXXING_WEB_DIST"):
        return config.WEB_DIST
    if _active.get("path") is not None and _active.get("shipped") == (config.WEB_DIST, config.STATE) \
            and time.monotonic() - _active.get("at", 0.0) < 5.0:
        return _active["path"]
    return None


def _sweep(parent: Path, pattern: str, age: float = 3600) -> None:
    """Leftovers of a build or a preflight killed midway (a restart, an OOM)."""
    now = time.time()
    for d in parent.glob(pattern):
        try:
            if now - d.stat().st_mtime > age:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def forget() -> None:
    _active.clear()


# ---- what needs a build ---------------------------------------------------------------------------------------
def customized_files() -> list[str]:
    """Web sources this server changed: in saved customizations, and not saved yet (uncommitted)."""
    from . import customs
    files = {f for c in customs.list_customs() for f in c["files"] if is_web_source(f)}
    files |= {f for f in customs.dirty_files() if is_web_source(f)}
    return sorted(files)


def status() -> dict[str, Any]:
    """{customized: [files], built: bool (a local build matches the sources), served: path, stamp}."""
    files = customized_files()
    forget()
    served = active_dist()
    local = served != config.WEB_DIST
    return {"customized": files, "built": local, "served": str(served), "stamp": _stamp(served) if local else {},
            "dir": str(build_dir())}


# ---- build -----------------------------------------------------------------------------------------------------
@contextmanager
def _lock():
    config.STATE.mkdir(parents=True, exist_ok=True)
    with open(config.STATE / "web-build.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _node_env() -> tuple[Path | None, dict[str, str]]:
    from . import deps
    node = deps.node_bin()
    # only what npm and node need: the install scripts of dependencies never see the server's keys
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "NODE_OPTIONS", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "no_proxy")
    env = {k: v for k, v in os.environ.items() if k in keep or k.startswith("npm_config_")}
    env.update({"CI": "1", "NODE_ENV": "production", "npm_config_update_notifier": "false"})
    if node:
        env["PATH"] = f"{node.parent}:{env.get('PATH', '/usr/bin:/bin')}"
    return node, env


def _run(cmd: list[str], cwd: Path, env: dict[str, str], timeout: float) -> tuple[bool, str]:
    try:                                        # its own process group: a timeout stops npm's children too
        p = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             start_new_session=True)
    except OSError as e:
        return False, f"{cmd[0]}: {e}"
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(p.pid, signal.SIGKILL)
        p.communicate()
        return False, f"{' '.join(cmd[:3])}: timed out after {int(timeout)} s"
    # tools may print bytes that are not UTF-8 (a file name in an error): never a reason to fail the caller
    return p.returncode == 0, out.decode("utf-8", "replace").strip()


def _install(web: Path, env: dict[str, str], node: Path, share_from: Path | None,
             install: bool = True) -> tuple[bool | None, str]:
    """node_modules for `web`: kept while package-lock.json does not change; a worktree borrows the code
    directory's when both lockfiles are the same (the preflight), else installs its own."""
    lock = (web / "package-lock.json").read_bytes() if (web / "package-lock.json").is_file() else b""
    want = hashlib.sha256(lock).hexdigest()
    mods = web / "node_modules"
    if share_from is not None:
        theirs = share_from / "node_modules"
        if (theirs / LOCK_STAMP).is_file() and (theirs / LOCK_STAMP).read_text().strip() == want:
            if not mods.exists():
                mods.symlink_to(theirs)
            return True, ""
    if mods.is_dir() and (mods / LOCK_STAMP).is_file() and (mods / LOCK_STAMP).read_text().strip() == want:
        return True, ""
    if not install:
        return None, "the build tools are not installed for these sources (package-lock.json differs)"
    npm = node.parent / "npm"
    ok, out = _run([str(npm) if npm.exists() else "npm", "ci", "--no-audit", "--no-fund", "--loglevel=error",
                    "--include=dev"], web, env, 900)
    if not ok:
        return False, "npm ci failed: " + out[-1500:]
    (mods / LOCK_STAMP).write_text(want)
    return True, ""


Step = Callable[[str], None]


def build(code: Path | None = None, out: Path | None = None, share_from: Path | None = None,
          progress: Step | None = None, install: bool = True) -> dict[str, Any]:
    """Typecheck and build the web UI of `code` (default: the code directory) into `out` (default: this server's
    build, swapped in atomically, the previous one kept). -> {ok, error, seconds, dir}; `install=False` (the
    preflight) never runs npm: {ok: False, skipped: True} when the tools are missing. Never raises."""
    t0 = time.monotonic()
    try:
        return _build(code, out, share_from, progress, install)
    except Exception as e:                              # a full disk, an unreadable tree: a failed build, not a trace
        log.exception("web UI build failed")
        return {"ok": False, "error": f"build failed: {e}", "seconds": round(time.monotonic() - t0)}


def _build(code: Path | None, out: Path | None, share_from: Path | None, progress: Step | None,
           install: bool) -> dict[str, Any]:
    code = code or config.CODE
    say = progress or (lambda _m: None)
    t0 = time.monotonic()
    web = code / "web"
    if not (web / "package.json").is_file():
        return {"ok": False, "error": f"no web sources in {code}"}
    node, env = _node_env()
    if node is None:
        return {"ok": False, "error": "Node.js not found (maxxing deps list)"}
    final = out or build_dir()
    key = source_key(code)                              # before building: a source edited meanwhile is not in it
    with _lock():
        _sweep(final.parent, final.name + ".new-*")
        say("installing the build tools (npm ci, once per version)")
        ok, err = _install(web, env, node, share_from, install)
        if not ok:
            return {"ok": False, "skipped": ok is None, "error": err, "seconds": round(time.monotonic() - t0)}
        say("checking the types (tsc)")
        # always a full check: tsc's incremental state may come from another tree (a borrowed node_modules)
        ok, msg = _run([str(node), "node_modules/typescript/bin/tsc", "-b", "--force"],
                       web, env, 600)
        if not ok:
            return {"ok": False, "error": "type errors:\n" + msg[-3000:], "seconds": round(time.monotonic() - t0)}
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=final.name + ".new-", dir=str(final.parent)))
        try:
            say("building (vite)")
            ok, msg = _run([str(node), "node_modules/vite/bin/vite.js", "build", "--outDir", str(tmp), "--emptyOutDir",
                            "--logLevel", "warn"], web, env, 900)
            if not ok or not (tmp / "index.html").is_file():
                return {"ok": False, "error": "build failed:\n" + msg[-3000:], "seconds": round(time.monotonic() - t0)}
            rc, head = _git(code, "rev-parse", "HEAD")
            (tmp / STAMP).write_text(json.dumps({"key": key, "commit": head.strip() if rc == 0 else "",
                                                 "built_at": time.time()}))
            if out is None:                             # this server's build: keep the previous one for a rollback
                prev, old = _prev_dir(), final.with_name(final.name + ".old")
                shutil.rmtree(old, ignore_errors=True)
                if final.exists():
                    final.rename(old)
                try:
                    tmp.rename(final)
                except OSError:
                    if old.exists():
                        old.rename(final)               # the current build stays served, the previous one kept
                    raise
                if old.exists():
                    if key is not None and _stamp(old).get("key") == key:
                        shutil.rmtree(old, ignore_errors=True)   # the same sources rebuilt: the previous one stays
                    else:
                        shutil.rmtree(prev, ignore_errors=True)
                        old.rename(prev)
                forget()
            else:
                shutil.rmtree(final, ignore_errors=True)
                tmp.rename(final)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)      # moved into place on success: nothing is left
    return {"ok": True, "error": "", "seconds": round(time.monotonic() - t0), "dir": str(final)}
