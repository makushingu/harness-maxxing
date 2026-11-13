"""Terminals of the web app (Settings -> Features -> Terminal, off by default): a login shell on a pseudo-terminal,
opened in a repository of a session, shown in a drawer under the conversation (web: features/terminal/).

A terminal is a child of the server (its own process group): a page reload finds it again (the output since the
start is replayed from a buffer), the server stopping or restarting ends it, like closing it or 30 min without input
or output. 4 at most. Never for agents: only the signed-in user opens one, from the web app (api/term.py).
"""
from __future__ import annotations

import asyncio
import errno
import fcntl
import logging
import os
import pty
import secrets
import shutil
import signal
import subprocess
import struct
import termios
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config

log = logging.getLogger("maxxing.terminal")

MAX_TERMS = 4
IDLE_S = 30 * 60
BUFFER_BYTES = 256 * 1024                     # replayed to a new connection (≈ a few thousand lines)
TOKEN_TTL_S = 30
READ_CHUNK = 65536


class TermError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Term:
    id: str
    cwd: str
    pid: int
    fd: int
    started: float
    title: str
    last: float = field(default_factory=time.time)
    buf: bytearray = field(default_factory=bytearray)
    listeners: set = field(default_factory=set)          # asyncio.Queue per connected browser
    tokens: dict = field(default_factory=dict)            # one-time token -> expiry
    exit: int | None = None
    proc: subprocess.Popen | None = None

    def info(self) -> dict:
        return {"id": self.id, "cwd": self.cwd, "title": self.title, "started": self.started, "last": self.last,
                "alive": self.exit is None, "clients": len(self.listeners)}


_terms: dict[str, Term] = {}
_lock = threading.Lock()
_opening = 0                                  # terminals being started: they count against MAX_TERMS too
_loop: asyncio.AbstractEventLoop | None = None


def enabled() -> bool:
    return bool(config.load_config().get("code_mode", False))


def _inside_root(p: Path) -> bool:
    root = Path(config.files_root()).resolve()
    return p == root or root in p.parents


def _shell() -> str:
    sh = os.environ.get("SHELL") or "/bin/bash"
    return sh if os.path.exists(sh) else "/bin/sh"


def _env() -> dict[str, str]:
    keep = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "SHELL", "TZ")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "MAXXING_TERMINAL": "1"})
    env.setdefault("LANG", "C.UTF-8")
    return env


def _set_size(fd: int, cols: int, rows: int) -> None:
    cols, rows = max(10, min(int(cols), 500)), max(4, min(int(rows), 300))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def open_term(cwd: str, cols: int = 100, rows: int = 30) -> Term:
    """A new terminal in `cwd` (a folder under files_root). 403 term_off, 400 bad_cwd, 409 too_many."""
    if not enabled():
        raise TermError(403, "term_off", "the terminal is off: Settings -> Features -> Terminal")
    p = Path(cwd or config.files_root()).expanduser()
    try:
        p = p.resolve(strict=True)
    except (OSError, ValueError):                 # a NUL byte or a lone surrogate in the name
        raise TermError(400, "bad_cwd", "no such folder") from None
    if not p.is_dir() or not _inside_root(p):
        raise TermError(400, "bad_cwd", "the folder must be inside the files root")
    global _opening
    with _lock:                                   # the place is taken before the shell starts: opens at once
        live = [t for t in _terms.values() if t.exit is None]
        if len(live) + _opening >= MAX_TERMS:
            raise TermError(409, "too_many", f"{MAX_TERMS} terminals are open: close one first")
        _opening += 1
    try:
        return _start(p, cols, rows)
    finally:
        with _lock:
            _opening -= 1


def _start(p: Path, cols: int, rows: int) -> Term:
    # A login shell, leader of its own session with the pty as its controlling terminal (job control, Ctrl+C):
    # `setsid -c` (util-linux). subprocess forks in C: no Python code runs in the child of this threaded server.
    fd, slave = pty.openpty()
    try:
        sh = _shell()
        proc = subprocess.Popen([shutil.which("setsid") or "setsid", "-c", sh, "-l"], stdin=slave, stdout=slave,
                                stderr=slave, cwd=p, env=_env(), close_fds=True)
    except OSError as e:
        os.close(fd)
        raise TermError(500, "no_shell", f"could not start a shell: {e}") from None
    finally:
        os.close(slave)
    pid = proc.pid
    _set_size(fd, cols, rows)
    os.set_blocking(fd, False)
    t = Term(id=secrets.token_hex(6), cwd=str(p), pid=pid, fd=fd, started=time.time(), title=p.name or "/", proc=proc)
    with _lock:
        _terms[t.id] = t
    if _loop is not None:
        _loop.call_soon_threadsafe(_watch, t)
    log.info("terminal %s opened in %s", t.id, p)
    return t


def _watch(t: Term) -> None:
    assert _loop is not None
    _loop.add_reader(t.fd, _readable, t)


def _readable(t: Term) -> None:
    try:
        data = os.read(t.fd, READ_CHUNK)
    except OSError as e:
        if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            return
        data = b""
    if not data:
        _ended(t)
        return
    t.last = time.time()
    t.buf += data
    if len(t.buf) > BUFFER_BYTES:
        del t.buf[: len(t.buf) - BUFFER_BYTES]
    for q in list(t.listeners):
        q.put_nowait(data)


def _ended(t: Term) -> None:
    if _loop is not None:
        try:
            _loop.remove_reader(t.fd)
        except (ValueError, OSError):
            pass
    code = t.proc.poll() if t.proc else None
    t.exit = code if code is not None else 0
    if code is None and t.proc is not None and _loop is not None:     # end of output a moment before the exit: reap
        _loop.call_later(1.0, t.proc.poll)
    for q in list(t.listeners):
        q.put_nowait(None)
    try:
        os.close(t.fd)
    except OSError:
        pass
    with _lock:
        _terms.pop(t.id, None)
    log.info("terminal %s ended", t.id)


def get(tid: str) -> Term:
    t = _terms.get(tid)
    if t is None or t.exit is not None:
        raise TermError(404, "not_found", "no such terminal")
    return t


def listing() -> list[dict]:
    with _lock:
        return [t.info() for t in sorted(_terms.values(), key=lambda x: x.started) if t.exit is None]


def token(tid: str) -> str:
    """A one-time token to open the terminal's websocket (30 s)."""
    t = get(tid)
    now = time.time()
    t.tokens = {k: v for k, v in t.tokens.items() if v > now}
    tok = secrets.token_urlsafe(24)
    t.tokens[tok] = now + TOKEN_TTL_S
    return tok


def take_token(tid: str, tok: str) -> Term:
    t = get(tid)
    exp = t.tokens.pop(tok or "", None)
    if exp is None or exp < time.time():
        raise TermError(403, "bad_token", "expired link: reopen the terminal")
    return t


def write(t: Term, data: bytes) -> None:
    t.last = time.time()
    view = memoryview(data)
    deadline = time.time() + 2
    while view:
        try:
            n = os.write(t.fd, view)
            view = view[n:]
        except BlockingIOError:
            if time.time() > deadline:
                return
            time.sleep(0.01)
        except OSError:
            return


def resize(t: Term, cols: int, rows: int) -> None:
    try:
        _set_size(t.fd, cols, rows)
        os.killpg(os.getpgid(t.pid), signal.SIGWINCH)
    except (OSError, ValueError, ProcessLookupError):
        pass


def close(tid: str) -> bool:
    t = _terms.get(tid)
    if t is None:
        return False
    _kill(t)
    return True


def _kill(t: Term) -> None:
    for sig in (signal.SIGHUP, signal.SIGTERM):
        try:
            os.killpg(os.getpgid(t.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            break
    # the reader sees the end of file and cleans up; without a loop (tests, shutdown) do it here
    if _loop is None or not _loop.is_running():
        _ended(t)


def close_all() -> int:
    with _lock:
        ts = list(_terms.values())
    for t in ts:
        _kill(t)
    return len(ts)


def reap_idle(now: float | None = None) -> list[str]:
    now = now or time.time()
    gone = []
    with _lock:
        ts = list(_terms.values())
    for t in ts:
        if t.exit is None and now - t.last > IDLE_S:
            _kill(t)
            gone.append(t.id)
    return gone


def bind_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    global _loop
    _loop = loop


def wait_gone(tid: str, timeout: float = 5.0) -> bool:
    """True once the terminal's shell has ended (tests, `disable`)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if tid not in _terms:
            return True
        time.sleep(0.05)
    return tid not in _terms
