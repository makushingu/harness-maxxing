"""Notifications feed: events from the system (cron runs, updates, backups, sign-ins), from webhooks
(Stripe, Shopify, GitHub, generic JSON) and from any script (`maxxing feed post`), shown on the
dashboard and optionally posted to the Telegram "Notifications" thread. See docs/user/24-feed.md.

Storage: <state>/feed.db (sqlite3, WAL) - written by the server and by CLI processes (cron runs).
An event: {id, at, source, level, title, body, url, count, read}. `dedupe` makes a post idempotent per
source (a webhook delivered twice); `group` folds repeats into one row while it is unread ("Cron jobs
succeeded x12"). Events older than RETENTION_DAYS are removed.

Telegram routing (config `feed`): per source rule "off" | "silent" | "loud" | "auto" (default). Auto
goes by level: error -> loud, warning -> silent, info / success -> off. The built-in sources that
already have their own Telegram thread (crons, security, system) default to "off".
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

from . import bus, config

log = logging.getLogger("maxxing.feed")

LEVELS = ("info", "success", "warning", "error")
RULES = ("auto", "off", "silent", "loud")
RETENTION_DAYS = 30
GROUP_WINDOW_S = 24 * 3600
TITLE_MAX, BODY_MAX = 200, 4000
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")
# Built-in sources: they already report in their own Telegram thread (Crons; Alerts: gateway.alert / system_alert).
BUILTIN = {"crons": "Cron jobs", "system": "Harness Maxxing", "security": "Sign-ins"}
OWN_THREAD = {"crons", "system", "security"}

_lock = threading.Lock()
_ready: set[str] = set()


class FeedError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---- storage -------------------------------------------------------------------------------
def db_path() -> Path:
    return config.state_dir() / "feed.db"


def _conn() -> sqlite3.Connection:
    path = db_path()
    key = str(path)
    try:
        return _open(path, key)
    except sqlite3.DatabaseError:
        if key in _ready:
            raise
    # Unreadable feed.db (not a database, corrupted): set it aside and start a fresh one, or the feed and every
    # system notification (crons, updates, sign-ins) would fail from now on.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.replace(f"{path}{suffix}", f"{path}.damaged-{stamp}{suffix}")
        except OSError:
            pass
    log.warning("feed.db was unreadable: moved to feed.db.damaged-%s, starting a new feed", stamp)
    return _open(path, key)


def _open(path: Path, key: str) -> sqlite3.Connection:
    if not Path(path).exists():
        os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))     # private from the first byte
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    if key not in _ready:
        with _lock:
            try:
                c.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                c.close()
                raise
            c.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    at REAL NOT NULL, source TEXT NOT NULL, level TEXT NOT NULL,
                    title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
                    dedupe TEXT, grp TEXT, count INTEGER NOT NULL DEFAULT 1, read INTEGER NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS events_dedupe ON events(source, dedupe) WHERE dedupe IS NOT NULL;
                CREATE INDEX IF NOT EXISTS events_at ON events(at);
                CREATE INDEX IF NOT EXISTS events_src ON events(source, read);
            """)
            _ready.add(key)
    return c


_ID_MAX = 2**63 - 1                                                   # SQLite INTEGER


def _id(v) -> int | None:
    """An event id SQLite can hold, else None (a bigger int raises OverflowError: a 500)."""
    v = int(v)
    return v if -_ID_MAX <= v <= _ID_MAX else None


def _row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "at": r["at"], "source": r["source"], "level": r["level"], "title": r["title"],
            "body": r["body"], "url": r["url"], "count": r["count"], "read": bool(r["read"])}


def clean_source(source: str | None) -> str:
    s = re.sub(r"[^a-z0-9_.-]+", "-", (source or "custom").strip().lower()).strip("-.")[:40] or "custom"
    if not SOURCE_RE.match(s):
        raise FeedError(400, "bad_source", "Source: letters, digits, - _ . (max 40)")
    return s


# ---- write ---------------------------------------------------------------------------------
def _utf8(s: str | None) -> str | None:
    """A lone surrogate (JSON "\\ud800" is valid) cannot be stored by SQLite: replaced by "?"."""
    return s.encode("utf-8", "replace").decode("utf-8") if isinstance(s, str) else s


def post(title: str, body: str = "", level: str = "info", source: str = "custom", url: str = "",
         dedupe: str | None = None, group: str | None = None, notify: bool = True) -> dict | None:
    """Add an event. Returns it, or None when `dedupe` says it was already posted."""
    title, body, url = _utf8(title), _utf8(body), _utf8(url)
    dedupe, group = (_utf8(str(v)) if v else v for v in (dedupe, group))
    title = " ".join((title or "").split())[:TITLE_MAX]
    if not title:
        raise FeedError(400, "empty", "An event needs a title")
    if level not in LEVELS:
        raise FeedError(400, "bad_level", f"Level: {', '.join(LEVELS)}")
    source = clean_source(source)
    body = (body or "").strip()[:BODY_MAX]
    url = (url or "").strip()[:1000]
    # an app path ("/sessions?...") or a web address; "//host" and "/\\host" are other sites dressed as app paths
    if url and not (re.match(r"^/(?![/\\])", url) or re.match(r"^https?://", url)):
        url = ""
    now = time.time()
    with _conn() as c:
        if dedupe:
            dedupe = str(dedupe)[:200]
            if c.execute("SELECT 1 FROM events WHERE source=? AND dedupe=?", (source, dedupe)).fetchone():
                return None
        row = None
        if group:
            row = c.execute("SELECT * FROM events WHERE source=? AND grp=? AND read=0 AND level=? AND at>? "
                            "ORDER BY id DESC LIMIT 1", (source, group, level, now - GROUP_WINDOW_S)).fetchone()
        if row is not None:
            c.execute("UPDATE events SET count=count+1, at=?, title=?, body=?, url=? WHERE id=?",
                      (now, title, body, url, row["id"]))
            ev = _row(c.execute("SELECT * FROM events WHERE id=?", (row["id"],)).fetchone())
            grouped = True
        else:
            try:
                cur = c.execute("INSERT INTO events(at, source, level, title, body, url, dedupe, grp) "
                                "VALUES (?,?,?,?,?,?,?,?)", (now, source, level, title, body, url, dedupe, group))
            except sqlite3.IntegrityError:             # the same dedupe key inserted by a concurrent request
                if dedupe:
                    return None
                raise
            ev = _row(c.execute("SELECT * FROM events WHERE id=?", (cur.lastrowid,)).fetchone())
            grouped = False
            if cur.lastrowid % 50 == 0:
                c.execute("DELETE FROM events WHERE at<?", (now - RETENTION_DAYS * 86400,))
    bus.invalidate("feed")
    if notify and not grouped:
        _to_telegram(ev)
    return ev


# ---- read ----------------------------------------------------------------------------------
def list_events(source: str | None = None, unread: bool = False, before: int | None = None,
                limit: int = 50) -> dict:
    limit = max(1, min(int(limit or 50), 200))
    where, args = ["at>?"], [time.time() - RETENTION_DAYS * 86400]
    if source:
        where.append("source=?")
        args.append(source)
    if unread:
        where.append("read=0")
    if before:
        where.append("id<?")
        args.append(min(max(int(before), -_ID_MAX), _ID_MAX))
    with _conn() as c:
        rows = c.execute(f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
                         (*args, limit + 1)).fetchall()
        srcs = c.execute("SELECT source, COUNT(*) total, SUM(read=0) unread FROM events WHERE at>? "
                         "GROUP BY source ORDER BY MAX(at) DESC", (time.time() - RETENTION_DAYS * 86400,)).fetchall()
    sources = [{"source": r["source"], "total": r["total"], "unread": r["unread"] or 0} for r in srcs]
    return {"events": [_row(r) for r in rows[:limit]], "more": len(rows) > limit,
            "unread": sum(s["unread"] for s in sources), "sources": sources}


def unread_count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM events WHERE read=0 AND at>?",
                         (time.time() - RETENTION_DAYS * 86400,)).fetchone()[0]


def last_id() -> int:
    with _conn() as c:
        r = c.execute("SELECT MAX(id), SUM(read) FROM events").fetchone()
    return (r[0] or 0) * 100000 + (r[1] or 0)              # changes on new events and on reads


def mark_read(ids: list[int] | None = None, source: str | None = None, everything: bool = False) -> int:
    with _conn() as c:
        if everything:
            c.execute("UPDATE events SET read=1 WHERE read=0")
        elif source:
            c.execute("UPDATE events SET read=1 WHERE read=0 AND source=?", (source,))
        elif ids:
            c.executemany("UPDATE events SET read=1 WHERE id=?", [(i,) for i in map(_id, ids[:500]) if i is not None])
    bus.invalidate("feed")
    return unread_count()


def delete(event_id: int) -> None:
    if _id(event_id) is None:
        return
    with _conn() as c:
        c.execute("DELETE FROM events WHERE id=?", (int(event_id),))
    bus.invalidate("feed")


def get(event_id: int) -> dict | None:
    if _id(event_id) is None:
        return None
    with _conn() as c:
        r = c.execute("SELECT * FROM events WHERE id=?", (int(event_id),)).fetchone()
    return _row(r) if r else None


# ---- settings ------------------------------------------------------------------------------
def settings() -> dict:
    f = config.load_config().get("feed") or {}
    rules = {k: v for k, v in (f.get("rules") or {}).items() if v in RULES}
    return {"telegram": f.get("telegram", True) is not False, "rules": rules, "hooks": list(f.get("hooks") or [])}


def save_settings(telegram: bool | None = None, rules: dict | None = None, hooks: list | None = None) -> dict:
    with config._lock:
        cfg = config.load_config()
        f = dict(cfg.get("feed") or {})
        if telegram is not None:
            f["telegram"] = bool(telegram)
        if rules is not None:
            clean = {}
            for k, v in rules.items():
                if v not in RULES:
                    raise FeedError(400, "bad_rule", f"Rule: {', '.join(RULES)}")
                if v != "auto":
                    clean[clean_source(k)] = v
            f["rules"] = clean
        if hooks is not None:
            f["hooks"] = hooks
        cfg["feed"] = f
        config.save_config(cfg)
    bus.invalidate("feed")
    return settings()


def rule_for(source: str, level: str, s: dict | None = None) -> str:
    """Effective Telegram rule of an event: "off", "silent" or "loud"."""
    s = s or settings()
    r = s["rules"].get(source, "auto")
    if r != "auto":
        return r
    if source in OWN_THREAD:
        return "off"
    return {"error": "loud", "warning": "silent"}.get(level, "off")


def _to_telegram(ev: dict) -> None:
    try:
        s = settings()
        if not s["telegram"]:
            return
        r = rule_for(ev["source"], ev["level"], s)
        if r == "off":
            return
        from .telegram import gateway
        gateway.feed_notify(ev, loud=(r == "loud"))
    except Exception:  # noqa: BLE001 - Telegram is optional
        log.exception("feed: telegram post failed")


def system(title: str, body: str = "", level: str = "info", source: str = "system", url: str = "",
           group: str | None = None, dedupe: str | None = None) -> dict | None:
    """Built-in events: never raise (the feed must not break a cron run, an update or a sign-in). Returns the
    event (None when `dedupe` says it was already posted, or it could not be recorded)."""
    try:
        return post(title, body, level, source, url, dedupe=dedupe, group=group)
    except Exception:  # noqa: BLE001
        log.exception("feed: could not record %r", title)
        return None
