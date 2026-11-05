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

import importlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from . import bus, config

log = logging.getLogger("maxxing.feed")

LEVELS = ("info", "success", "warning", "error")
RULES = ("auto", "off", "silent", "loud")
RETENTION_DAYS = 30
GROUP_WINDOW_S = 24 * 3600
TITLE_MAX, BODY_MAX = 200, 4000
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")
# Built-in sources: they already report in their own Telegram thread (Crons; Alerts: gateway.alert / system_alert).
BUILTIN = {"crons": "Cron jobs", "system": "Harness Maxxing", "security": "Sign-ins", "health": "Server health",
           "agents": "Agents"}
OWN_THREAD = {"crons", "system", "security"}

# Alerts: an event can carry buttons (`actions`), follow something (`ref`: "approval:<id>", "health:<id>",
# "agent:<path>") and end (`resolved` = when, `resolution` = how). `act()` runs a button through the module of its
# ref kind (HANDLERS) and is idempotent: a second click on a decided request gets the same event back.
_ALERT_COLS = (("actions", "TEXT"), ("ref", "TEXT"), ("agent", "TEXT"), ("resolved", "REAL"), ("resolution", "TEXT"),
               ("hops", "INTEGER"))     # hops: posted from an agent run (its depth + 1), carried to the runs it starts
HANDLERS = {"approval": "approvals", "health": "health"}       # ref kind -> module with feed_action(value, action, by)
ACTION_STYLES = ("primary", "danger", "default", "link")
_lock = threading.Lock()
_aside_lock = config.ProcessLock("feed-aside")   # setting an unreadable feed.db aside
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
    except sqlite3.DatabaseError as e:
        if not _damaged(e):
            raise                                      # busy, disk full, too many files...: never set a good base aside
    # Unreadable feed.db (not a database, corrupted): set it aside and start a fresh one, or the feed and every
    # system notification (crons, updates, sign-ins) would fail from now on. Under a lock shared with the other
    # processes, and only if it is still unreadable: another writer may already have replaced it with a fresh
    # base holding new events, which must not be set aside in turn.
    with _aside_lock:
        try:
            return _open(path, key)
        except sqlite3.DatabaseError as e:
            if key in _ready or not _damaged(e):
                raise
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{time.monotonic_ns()}"   # never overwrites an older copy
        for suffix in ("", "-wal", "-shm"):
            try:
                os.replace(f"{path}{suffix}", f"{path}.damaged-{stamp}{suffix}")
            except OSError:
                pass
        log.warning("feed.db was unreadable: moved to feed.db.damaged-%s, starting a new feed", stamp)
        return _open(path, key)


def _damaged(e: sqlite3.DatabaseError) -> bool:
    """The file itself is broken (not a passing error such as a lock, a full disk or too many open files)."""
    text = str(e).lower()
    return "not a database" in text or "malformed" in text or "corrupt" in text


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
                CREATE TABLE IF NOT EXISTS hook_seen (hook TEXT NOT NULL, key TEXT NOT NULL, at REAL NOT NULL,
                                                      PRIMARY KEY (hook, key));
                CREATE INDEX IF NOT EXISTS hook_seen_at ON hook_seen(at);
            """)
            have = {r[1] for r in c.execute("PRAGMA table_info(events)")}
            for col, kind in _ALERT_COLS:                 # events you can act on (an agent's request...): added later
                if col not in have:
                    c.execute(f"ALTER TABLE events ADD COLUMN {col} {kind}")
            c.execute("CREATE INDEX IF NOT EXISTS events_ref ON events(ref) WHERE ref IS NOT NULL")
            _ready.add(key)
    return c


_ID_MAX = 2**63 - 1                                                   # SQLite INTEGER


def _id(v) -> int | None:
    """An event id SQLite can hold, else None (a bigger int raises OverflowError: a 500)."""
    v = int(v)
    return v if -_ID_MAX <= v <= _ID_MAX else None


def _actions(v: Any) -> list[dict]:
    try:
        a = json.loads(v) if isinstance(v, str) and v else v
    except ValueError:
        return []
    return [x for x in a if isinstance(x, dict) and x.get("id")] if isinstance(a, list) else []


def _row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "at": r["at"], "source": r["source"], "level": r["level"], "title": r["title"],
            "body": r["body"], "url": r["url"], "count": r["count"], "read": bool(r["read"]),
            "actions": _actions(r["actions"]), "ref": r["ref"], "agent": r["agent"], "resolved": r["resolved"],
            "resolution": r["resolution"] or "", "hops": r["hops"] or 0}


def clean_source(source: str | None) -> str:
    s = re.sub(r"[^a-z0-9_.-]+", "-", (source or "custom").strip().lower()).strip("-.")[:40] or "custom"
    if not SOURCE_RE.match(s):
        raise FeedError(400, "bad_source", "Source: letters, digits, - _ . (max 40)")
    return s


# ---- write ---------------------------------------------------------------------------------
def _utf8(s: str | None) -> str | None:
    """A lone surrogate (JSON "\\ud800" is valid) cannot be stored by SQLite: replaced by "?"."""
    return s.encode("utf-8", "replace").decode("utf-8") if isinstance(s, str) else s


def _clean_actions(actions: Any) -> str | None:
    out = []
    for a in (actions or [])[:4]:
        if not isinstance(a, dict) or not re.match(r"^[a-z][a-z0-9_-]{0,19}$", str(a.get("id") or "")):
            raise FeedError(400, "bad_action", "An action needs an id (a-z, 0-9, - _)")
        out.append({"id": a["id"], "label": " ".join(str(a.get("label") or a["id"]).split())[:40],
                    "style": a.get("style") if a.get("style") in ACTION_STYLES else "default"})
    return json.dumps(out) if out else None


def _clean_url(url: str | None) -> str:
    url = (url or "").strip()[:1000]
    # an app path ("/sessions?...") or a web address; "//host" and "/\\host" are other sites dressed as app paths
    return url if url and (re.match(r"^/(?![/\\])", url) or re.match(r"^https?://", url)) else ""


def post(title: str, body: str = "", level: str = "info", source: str = "custom", url: str = "",
         dedupe: str | None = None, group: str | None = None, notify: bool = True, *,
         actions: list[dict] | None = None, ref: str | None = None, agent: str | None = None,
         hops: int = 0) -> dict | None:
    """Add an event. Returns it, or None when `dedupe` says it was already posted. `actions` (buttons), `ref` (what it
    follows) and `agent` (the agent it is about) make it an alert: see act() and update(). `hops`: posted from an agent
    run (agents.scan_feed starts the runs it triggers that many hops deep)."""
    title, body, url = _utf8(title), _utf8(body), _utf8(url)
    acts = _clean_actions(actions)
    ref = (_utf8(str(ref)) or "")[:300] or None if ref else None
    agent = (_utf8(str(agent)) or "")[:300] or None if agent else None
    dedupe, group = (_utf8(str(v)) if v else v for v in (dedupe, group))
    title = " ".join((title or "").split())[:TITLE_MAX]
    if not title:
        raise FeedError(400, "empty", "An event needs a title")
    if level not in LEVELS:
        raise FeedError(400, "bad_level", f"Level: {', '.join(LEVELS)}")
    source = clean_source(source)
    body = (body or "").strip()[:BODY_MAX]
    url = _clean_url(url)
    now = time.time()
    with _conn() as c:
        if dedupe:
            dedupe = str(dedupe)[:200]
            if c.execute("SELECT 1 FROM events WHERE source=? AND dedupe=?", (source, dedupe)).fetchone():
                return None
        row = None
        if group:
            # never into a resolved one: a new failure after a recovery is a new alert, not a hidden "x2"
            row = c.execute("SELECT * FROM events WHERE source=? AND grp=? AND read=0 AND level=? AND at>? "
                            "AND resolved IS NULL ORDER BY id DESC LIMIT 1", (source, group, level, now - GROUP_WINDOW_S)).fetchone()
        if row is not None:
            c.execute("UPDATE events SET count=count+1, at=?, title=?, body=?, url=? WHERE id=?",
                      (now, title, body, url, row["id"]))
            ev = _row(c.execute("SELECT * FROM events WHERE id=?", (row["id"],)).fetchone())
            grouped = True
        else:
            try:
                cur = c.execute("INSERT INTO events(at, source, level, title, body, url, dedupe, grp, actions, ref, "
                                "agent, hops) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                (now, source, level, title, body, url, dedupe, group, acts, ref, agent,
                                 max(0, int(hops or 0)) or None))
            except sqlite3.IntegrityError:             # the same dedupe key inserted by a concurrent request
                if dedupe:
                    return None
                raise
            ev = _row(c.execute("SELECT * FROM events WHERE id=?", (cur.lastrowid,)).fetchone())
            grouped = False
            if cur.lastrowid % 50 == 0:
                c.execute("DELETE FROM events WHERE at<?", (now - RETENTION_DAYS * 86400,))
    bus.invalidate("feed", *(("agents",) if agent else ()))
    if notify and not grouped:
        _to_telegram(ev)
    elif grouped and ev.get("ref"):
        _alert_out(ev, new=False)
    return ev


def find(ref: str, open_only: bool = True) -> dict | None:
    """The newest event following `ref` (not resolved yet when `open_only`)."""
    with _conn() as c:
        r = c.execute("SELECT * FROM events WHERE ref=?" + (" AND resolved IS NULL" if open_only else "") +
                      " ORDER BY id DESC LIMIT 1", (str(ref),)).fetchone()
    return _row(r) if r else None


def agent_alerts(path: str) -> int:
    """Open, unread alerts about this agent other than its requests (those are its `waiting` count)."""
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM events WHERE agent=? AND resolved IS NULL AND read=0 "
                         "AND (ref IS NULL OR ref NOT LIKE 'approval:%')", (path,)).fetchone()[0]


def open_events(source: str) -> list[dict]:
    """The events of `source` that follow something and are not resolved yet."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM events WHERE source=? AND ref IS NOT NULL AND resolved IS NULL "
                         "ORDER BY id DESC LIMIT 500", (source,)).fetchall()
    return [_row(r) for r in rows]


# waiting for a click: a request until it is decided, any other alert until it is read (Seen, Open)
_PENDING = "actions IS NOT NULL AND resolved IS NULL AND (read=0 OR ref LIKE 'approval:%')"
_UNSET: Any = object()


def update(event_id: int, *, title: str | None = None, body: str | None = None, level: str | None = None,
           actions: Any = _UNSET, resolution: str | None = None, resolve: bool = False, read: bool | None = None,
           notify: bool = True) -> dict | None:
    """Change an event in place (its request was decided, its problem went away). `resolve` ends it: its buttons go,
    `resolution` says how. Returns the event, None when it no longer exists."""
    if _id(event_id) is None:
        return None
    sets, args = [], []
    if title is not None:
        sets.append("title=?")
        args.append(" ".join((_utf8(title) or "").split())[:TITLE_MAX] or "-")
    if body is not None:
        sets.append("body=?")
        args.append((_utf8(body) or "").strip()[:BODY_MAX])
    if level is not None:
        if level not in LEVELS:
            raise FeedError(400, "bad_level", f"Level: {', '.join(LEVELS)}")
        sets.append("level=?")
        args.append(level)
    if resolve:
        sets += ["resolved=COALESCE(resolved, ?)", "actions=NULL"]
        args.append(time.time())
    elif actions is not _UNSET:
        sets.append("actions=?")
        args.append(_clean_actions(actions))
    if resolution is not None:
        sets.append("resolution=?")
        args.append(" ".join((_utf8(resolution) or "").split())[:TITLE_MAX])
    if read is not None:
        sets.append("read=?")
        args.append(1 if read else 0)
    with _conn() as c:
        if sets:
            c.execute(f"UPDATE events SET {', '.join(sets)} WHERE id=?", (*args, int(event_id)))
        r = c.execute("SELECT * FROM events WHERE id=?", (int(event_id),)).fetchone()
    if r is None:
        return None
    ev = _row(r)
    bus.invalidate("feed", *(("agents",) if ev.get("agent") else ()))
    if notify and ev.get("ref"):
        _alert_out(ev, new=False)
    return ev


def resolve(ref: str, resolution: str = "", **kw: Any) -> dict | None:
    """End every open event following `ref` (the cause went away): an older one read or out of the grouping window
    must not keep its buttons. Returns the newest, if any."""
    with _conn() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM events WHERE ref=? AND resolved IS NULL ORDER BY id DESC",
                                       (str(ref),))]
    done = [update(i, resolve=True, resolution=resolution, **kw) for i in ids]
    return next((ev for ev in done if ev), None)


def act(event_id: int, action: str, by: str = "web") -> dict:
    """A button of an event (web: POST /api/feed/{id}/act/{action}; Telegram: `al:<id>:<action>`).
    `seen` marks it read (and tells its module); the others go to the module of its ref. Idempotent: an event
    already resolved is returned as it is, whoever clicks again and wherever."""
    ev = get(event_id)
    if not ev:
        raise FeedError(404, "not_found", "No such event")
    if ev["resolved"] and action != "seen":
        return ev
    if action != "seen" and action not in {a["id"] for a in ev["actions"]}:
        raise FeedError(400, "bad_action", f"This event has no action {action!r}")
    kind, _, value = (ev.get("ref") or "").partition(":")
    mod = HANDLERS.get(kind)
    if mod and value:
        fn = getattr(importlib.import_module(f".{mod}", __package__), "feed_action", None)
        if fn:
            fn(value, action, by, ev)
    if action in ("seen", "open"):
        with _conn() as c:
            c.execute("UPDATE events SET read=1 WHERE id=?", (int(event_id),))
        bus.invalidate("feed")
    return get(event_id) or ev


def _alert_out(ev: dict, new: bool) -> bool:
    """Hand an alert to Telegram's `post_alert` / `update_alert` when that bridge has them (in a thread: never blocks
    the caller). False when it does not: the caller keeps the older way."""
    try:
        from .telegram import gateway
    except Exception:  # noqa: BLE001 - Telegram is optional
        return False
    fn = getattr(gateway, "post_alert" if new else "update_alert", None)
    if fn is None:
        return False
    out = {**ev, "telegram": _alert_rule(ev)}

    def run() -> None:
        try:
            fn(out)
        except Exception:  # noqa: BLE001
            log.exception("feed: telegram %s failed", "post_alert" if new else "update_alert")
    if bus._loop is None:                   # a CLI process (a cron run): it may exit before a thread is done
        run()
    else:
        threading.Thread(target=run, name="feed-alert", daemon=True).start()
    return True


def _alert_rule(ev: dict) -> str:
    """How Telegram should post an alert: an agent waiting for an answer is always loud, the rest follows the rules."""
    if (ev.get("ref") or "").startswith("approval:"):
        return "loud"
    s = settings()
    return rule_for(ev["source"], ev["level"], s) if s["telegram"] else "off"


def claim_delivery(hook: str, key: str, keep_s: float) -> bool:
    """A signed webhook body seen for the first time within keep_s -> True (recorded), else False. Kept apart from
    the events: a body the parser ignored, or whose event was deleted, must not post when replayed."""
    now = time.time()
    with _conn() as c:
        c.execute("DELETE FROM hook_seen WHERE at<? OR (hook=? AND key=? AND at<?)",
                  (now - RETENTION_DAYS * 86400, hook, key, now - keep_s))
        try:
            c.execute("INSERT INTO hook_seen(hook, key, at) VALUES (?,?,?)", (hook, key, now))
        except sqlite3.IntegrityError:
            return False
    return True


def release_delivery(hook: str, key: str) -> None:
    """The delivery failed (bad body, feed error): the sender's retry must not be taken for a replay."""
    with _conn() as c:
        c.execute("DELETE FROM hook_seen WHERE hook=? AND key=?", (hook, key))


# ---- read ----------------------------------------------------------------------------------
def list_events(source: str | None = None, unread: bool = False, before: int | None = None,
                limit: int = 50, pending: bool = False) -> dict:
    """Newest first. `pending`: only the alerts waiting for a click (buttons, not resolved). The totals of every
    source come along, with `pending` = how many alerts wait."""
    limit = max(1, min(int(limit or 50), 200))
    where, args = ["at>?"], [time.time() - RETENTION_DAYS * 86400]
    if source:
        where.append("source=?")
        args.append(source)
    if unread:
        where.append("read=0")
    if pending:
        where.append(_PENDING)
    if before:
        where.append("id<?")
        args.append(min(max(int(before), -_ID_MAX), _ID_MAX))
    with _conn() as c:
        rows = c.execute(f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
                         (*args, limit + 1)).fetchall()
        waiting = c.execute(f"SELECT COUNT(*) FROM events WHERE at>? AND {_PENDING}", (args[0],)).fetchone()[0]
    sources = source_counts()
    return {"events": [_row(r) for r in rows[:limit]], "more": len(rows) > limit,
            "unread": sum(s["unread"] for s in sources), "pending": waiting, "sources": sources}


def max_id() -> int:
    """Id of the newest event (0 when none)."""
    with _conn() as c:
        r = c.execute("SELECT MAX(id) FROM events").fetchone()
    return int(r[0] or 0)


def events_after(after_id: int, limit: int = 200) -> list[dict]:
    """Events newer than `after_id`, oldest first (agents.scan_feed). A folded event keeps its id: not seen again."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?",
                         (min(max(int(after_id), 0), _ID_MAX), max(1, min(int(limit), 1000)))).fetchall()
    return [_row(r) for r in rows]


_counts: dict = {}


def _db_stamp(path: Path) -> tuple:
    out = []
    for suffix in ("", "-wal"):
        try:
            st = os.stat(f"{path}{suffix}")
        except OSError:
            st = None
        # An empty WAL is re-created by every new connection: only a WAL holding pages says something changed.
        out.append((st.st_mtime_ns, st.st_size, st.st_ino) if st and (st.st_size or not suffix) else None)
    return tuple(out)


def _aggregate(c: sqlite3.Connection, cutoff: float) -> list[dict]:
    srcs = c.execute("SELECT source, COUNT(*) total, SUM(read=0) unread, MAX(at) last FROM events WHERE at>? "
                     "GROUP BY source ORDER BY MAX(at) DESC", (cutoff,)).fetchall()
    return [{"source": r["source"], "total": r["total"], "unread": r["unread"] or 0, "last": r["last"]} for r in srcs]


def source_counts() -> list[dict]:
    """Per-source totals for the chips. Counting the whole journal is linear in its size, so the result is kept
    until feed.db (or its WAL) changes - written by this process or another one - or a minute passes (retention)."""
    path = db_path()
    with _conn() as c:
        key = (str(path), _db_stamp(path), int(time.time() // 60))
        hit = _counts.get(key[0])
        if hit and hit[0] == key:
            return [dict(x) for x in hit[1]]
        sources = _aggregate(c, time.time() - RETENTION_DAYS * 86400)
    _counts[key[0]] = (key, sources)
    return [dict(x) for x in sources]


def unread_count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM events WHERE read=0 AND at>?",
                         (time.time() - RETENTION_DAYS * 86400,)).fetchone()[0]


def last_id() -> int:
    with _conn() as c:
        r = c.execute("SELECT MAX(id), SUM(read) FROM events").fetchone()
    return (r[0] or 0) * 100000 + (r[1] or 0)              # changes on new events and on reads


_watch_lock = threading.Lock()
_watch: dict = {"ident": None, "conn": None, "stamp": None, "last": 0}


def watch_id() -> int:
    """last_id() for the watcher that tells the UI about events written by other processes (a pass every few
    seconds): nothing is read while feed.db and its WAL are unchanged, and the read goes through one connection
    kept open (opened again when feed.db is replaced) instead of a new one per pass."""
    path = db_path()
    with _watch_lock:
        stamp = (str(path), _db_stamp(path))
        if stamp == _watch["stamp"]:
            return _watch["last"]
        try:
            ident: tuple | None = (str(path), os.stat(path).st_ino)
        except OSError:
            ident = None
        c = _watch["conn"]
        if ident is None or ident != _watch["ident"] or c is None:
            if c is not None:
                c.close()
            _watch.update(conn=None, ident=None, stamp=None)
            _conn().close()                             # creates / repairs the database and its table
            c = sqlite3.connect(path, timeout=10, check_same_thread=False)    # used under _watch_lock only
            _watch.update(conn=c, ident=ident)
        try:
            r = c.execute("SELECT MAX(id), SUM(read) FROM events").fetchone()
        except sqlite3.Error:
            c.close()
            _watch.update(conn=None, ident=None, stamp=None)
            raise
        last = (r[0] or 0) * 100000 + (r[1] or 0)
        _watch.update(stamp=stamp, last=last)
        return last


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
    return {"telegram": f.get("telegram", True) is not False, "rules": rules, "hooks": list(f.get("hooks") or []),
            "health": bool(config.load_config().get("health_feed"))}


def save_settings(telegram: bool | None = None, rules: dict | None = None, hooks: list | None = None,
                  health: bool | None = None) -> dict:
    with config._lock:
        cfg = config.load_config()
        if health is not None:
            cfg["health_feed"] = bool(health)
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
    if ev.get("ref"):
        # an alert: Telegram's post_alert when it exists; else the older way, except the requests of agents that
        # approvals.py already posts with their own buttons
        if _alert_out(ev, new=True) or ev["ref"].startswith("approval:"):
            return
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
