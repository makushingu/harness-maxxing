"""What each browser did: a journal of tool calls (values never written, only their length)."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from urllib.parse import urlsplit

from .. import browser

MAX_ACTIONS = 500
MAX_BYTES = 400_000          # past this the journal is cut down to KEEP_BYTES (whole lines, the newest)
KEEP_BYTES = 200_000
_lock = threading.Lock()     # appends and the compaction: a line written during a compaction is never lost
SECRET_ARGS = ("value", "text", "values", "key", "keys", "function", "script", "expression", "elements")
SID_RE = re.compile(r"^[A-Za-z0-9_-]{6,80}\Z")


def page(url: object) -> str:
    """An address without its query, fragment or credentials (they may carry tokens)."""
    try:
        u = urlsplit(str(url or ""))
        host = u.hostname or ""
        return f"{u.scheme}://{host}{u.path}"[:300] if u.scheme in ("http", "https") else str(url or "")[:40]
    except ValueError:
        return ""


def summary(name: str, args: dict) -> dict:
    out: dict = {}
    for k, v in (args or {}).items():
        if k in SECRET_ARGS:
            out[k] = f"<{len(json.dumps(v)) if not isinstance(v, str) else len(v)} chars>"
        elif k == "url":
            out[k] = page(v)
        elif isinstance(v, (int, float, bool)) or (isinstance(v, str) and len(v) <= 80):
            out[k] = v
    return out


def log_action(slug: str, entry: dict) -> None:
    """Never raises: a journal that cannot be written must not break the tool call it records."""
    d = browser.actions_dir()
    f = d / f"{slug}.jsonl"
    try:
        d.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False).encode("utf-8", "replace").decode("utf-8")
        with _lock:
            with f.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            if f.stat().st_size > MAX_BYTES:
                _compact(f)
    except (OSError, ValueError):
        return


def _compact(f) -> None:
    """Keep the newest lines, at most MAX_ACTIONS and KEEP_BYTES (long lines would otherwise keep the file above
    MAX_BYTES and rewrite it at every call), through a temporary file of its own."""
    lines = f.read_bytes().splitlines()[-MAX_ACTIONS:]
    keep, size = [], 0
    for ln in reversed(lines):
        size += len(ln) + 1
        if size > KEEP_BYTES:
            break
        keep.append(ln)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=f".{f.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"".join(ln + b"\n" for ln in reversed(keep)))
        os.replace(tmp, f)
    except BaseException:
        os.unlink(tmp)
        raise


def _read(slug: str) -> list[str]:
    try:   # a byte cut in the middle of a character must not break the profile's page
        return (browser.actions_dir() / f"{slug}.jsonl").read_bytes().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def actions(slug: str, n: int = 50, session: str | None = None) -> list[dict]:
    out = []
    for ln in reversed(_read(slug)):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if session and e.get("session") != session:
            continue
        out.append(e)
        if len(out) >= n:
            break
    return out


def forget(slug: str) -> None:
    (browser.actions_dir() / f"{slug}.jsonl").unlink(missing_ok=True)


def sessions(slug: str, n: int = 30) -> list[dict]:
    """The journal of the temporary navigators of a profile (sessions'), newest first:
    [{session, first, last, actions, sites}] - sites = the hosts its pages were on."""
    rows: dict[str, dict] = {}
    for e in actions(slug, MAX_ACTIONS):
        nav = str(e.get("nav") or "")
        sid = str(e.get("session") or "")
        if not nav.startswith("session:") or not sid:
            continue
        r = rows.setdefault(sid, {"session": sid, "first": e.get("at") or 0, "last": e.get("at") or 0,
                                  "actions": 0, "sites": []})
        r["actions"] += 1
        at = e.get("at") or 0
        r["first"], r["last"] = min(r["first"], at), max(r["last"], at)
        args = e.get("args") if isinstance(e.get("args"), dict) else {}
        for u in (args.get("url"), e.get("page")):
            try:
                host = urlsplit(str(u or "")).hostname or ""
            except ValueError:
                host = ""
            if host and host not in r["sites"] and len(r["sites"]) < 12:
                r["sites"].append(host)
    return sorted(rows.values(), key=lambda r: -r["last"])[:n]
