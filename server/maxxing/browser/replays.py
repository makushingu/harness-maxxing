"""What each browser did: a journal of tool calls (values never written, only their length)."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from .. import browser

MAX_ACTIONS = 500
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
        with f.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except (OSError, ValueError):
        return
    try:
        if f.stat().st_size > 400_000:
            lines = f.read_text().splitlines()[-MAX_ACTIONS:]
            tmp = f.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n")
            tmp.replace(f)
    except OSError:
        pass


def actions(slug: str, n: int = 50, session: str | None = None) -> list[dict]:
    f = browser.actions_dir() / f"{slug}.jsonl"
    try:
        lines = f.read_text().splitlines()
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            e = json.loads(ln)
        except ValueError:
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
        for u in ((e.get("args") or {}).get("url"), e.get("page")):
            try:
                host = urlsplit(str(u or "")).hostname or ""
            except ValueError:
                host = ""
            if host and host not in r["sites"] and len(r["sites"]) < 12:
                r["sites"].append(host)
    return sorted(rows.values(), key=lambda r: -r["last"])[:n]
