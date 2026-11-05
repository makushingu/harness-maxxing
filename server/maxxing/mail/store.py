"""<state>/mail/mail.db: what Harness knows about the mailboxes besides the mailboxes themselves.

    poll      per mailbox and folder: UIDVALIDITY, last UID seen, last check (ok / error)
    messages  the newest mails seen by the checks (headers + a short extract): the "All mailboxes" view
    contacts  addresses the owner wrote to from Harness or allowed an agent to write to ("approve_send": "new" sends
              alone to them); never the senders of incoming mail (anyone can write first)
    seen_by   what an agent did with a mail ("read", "draft", "filed in Invoices"...), shown on the E-mail page -
              only here, never written to the mailbox (no IMAP keyword)
    outbox    messages an agent wrote that wait for the owner's click (outbox.py)

A cache: an unreadable file is set aside and started again (the mailboxes keep the mail).
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from .. import config

KEEP_MESSAGES = 500          # per mailbox
KEEP_SEEN_DAYS = 90
KEEP_CONTACT_DAYS = 730
KEEP_CONTACTS = 5000         # per mailbox
_lock = threading.Lock()
_ready: set[str] = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS poll (account TEXT NOT NULL, folder TEXT NOT NULL, uidvalidity INTEGER NOT NULL DEFAULT 0,
    last_uid INTEGER, at REAL, ok INTEGER, error TEXT, PRIMARY KEY (account, folder));
CREATE TABLE IF NOT EXISTS messages (account TEXT NOT NULL, folder TEXT NOT NULL, uid INTEGER NOT NULL,
    message_id TEXT, from_email TEXT, from_name TEXT, verified INTEGER NOT NULL DEFAULT 0, subject TEXT,
    date REAL, snippet TEXT, seen INTEGER NOT NULL DEFAULT 0, attachments INTEGER NOT NULL DEFAULT 0, at REAL NOT NULL,
    PRIMARY KEY (account, folder, uid));
CREATE INDEX IF NOT EXISTS messages_date ON messages(date);
CREATE TABLE IF NOT EXISTS contacts (account TEXT NOT NULL, address TEXT NOT NULL, at REAL NOT NULL,
    PRIMARY KEY (account, address));
CREATE TABLE IF NOT EXISTS seen_by (id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, mkey TEXT NOT NULL,
    agent TEXT NOT NULL, at REAL NOT NULL, what TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS seen_by_key ON seen_by(account, mkey);
CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, account TEXT NOT NULL, agent TEXT NOT NULL, at REAL NOT NULL,
    status TEXT NOT NULL, data TEXT NOT NULL, event_id INTEGER, done_at REAL, note TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS outbox_status ON outbox(status);
"""


def path() -> Path:
    return config.state_dir("mail") / "mail.db"


def _open(p: Path) -> sqlite3.Connection:
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        os.close(os.open(p, os.O_CREAT | os.O_WRONLY, 0o600))
    c = sqlite3.connect(p, timeout=10)
    c.row_factory = sqlite3.Row
    if str(p) not in _ready:
        with _lock:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            _migrate(c)
            _ready.add(str(p))
    return c


def _migrate(c: sqlite3.Connection) -> None:
    v = c.execute("PRAGMA user_version").fetchone()[0]
    if v < 1:
        # 1: contacts were also the senders of incoming mail (anyone could become one); auth_server per mail
        c.execute("DELETE FROM contacts")
        cols = {r[1] for r in c.execute("PRAGMA table_info(messages)")}
        if "auth_server" not in cols:
            c.execute("ALTER TABLE messages ADD COLUMN auth_server TEXT")     # NULL: noted before (not a sample)
        c.execute("PRAGMA user_version=1")
        c.commit()


@contextlib.contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    p = path()
    try:
        c = _open(p)
    except sqlite3.DatabaseError as e:
        if "not a database" not in str(e).lower() and "malformed" not in str(e).lower():
            raise
        for suffix in ("", "-wal", "-shm"):
            with contextlib.suppress(OSError):
                os.replace(f"{p}{suffix}", f"{p}.damaged{suffix}")
        _ready.discard(str(p))
        c = _open(p)
    try:
        with c:
            yield c
    finally:
        c.close()


def prune() -> None:
    """Old notes of the agents, old contacts (outbox.tidy, daily)."""
    now = time.time()
    with conn() as c:
        c.execute("DELETE FROM seen_by WHERE at<?", (now - KEEP_SEEN_DAYS * 86400,))
        c.execute("DELETE FROM contacts WHERE at<?", (now - KEEP_CONTACT_DAYS * 86400,))
        for (acc,) in c.execute("SELECT DISTINCT account FROM contacts").fetchall():
            c.execute("DELETE FROM contacts WHERE account=? AND rowid NOT IN (SELECT rowid FROM contacts WHERE "
                      "account=? ORDER BY at DESC LIMIT ?)", (acc, acc, KEEP_CONTACTS))


def mkey(message_id: str | None, folder: str = "", uid: int | None = None) -> str:
    """What a mail is known by: its Message-ID (kept when it moves), else folder + UID."""
    mid = (message_id or "").strip()
    return mid[:300] if mid else f"{folder}#{uid}"


# ---------------------------------------------------------------- poll positions

def position(account: str, folder: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM poll WHERE account=? AND folder=?", (account, folder)).fetchone()
    return dict(r) if r else None


def set_position(account: str, folder: str, *, uidvalidity: int | None = None, last_uid: int | None = None,
                 ok: bool, error: str = "") -> None:
    with conn() as c:
        cur = c.execute("SELECT * FROM poll WHERE account=? AND folder=?", (account, folder)).fetchone()
        uv = uidvalidity if uidvalidity is not None else (cur["uidvalidity"] if cur else 0)
        lu = last_uid if last_uid is not None else (cur["last_uid"] if cur else None)
        c.execute("INSERT OR REPLACE INTO poll(account, folder, uidvalidity, last_uid, at, ok, error) "
                  "VALUES (?,?,?,?,?,?,?)", (account, folder, uv, lu, time.time(), 1 if ok else 0, error[:500]))


def last_check(account: str) -> dict | None:
    """The newest check of a mailbox: {at, ok, error}."""
    with conn() as c:
        r = c.execute("SELECT at, ok, error FROM poll WHERE account=? AND at IS NOT NULL ORDER BY at DESC LIMIT 1",
                      (account,)).fetchone()
    return {"at": r["at"], "ok": bool(r["ok"]), "error": r["error"] or ""} if r else None


def forget_account(account: str) -> None:
    with conn() as c:
        for t in ("poll", "messages", "contacts", "seen_by", "outbox"):
            c.execute(f"DELETE FROM {t} WHERE account=?", (account,))


# ---------------------------------------------------------------- messages cache and contacts

def remember(account: str, folder: str, rows: list[dict], snippets: dict[int, str] | None = None) -> None:
    now = time.time()
    with conn() as c:
        for r in rows:
            f = r.get("from") or {}
            c.execute("INSERT INTO messages(account, folder, uid, message_id, from_email, from_name, "
                      "verified, subject, date, snippet, seen, attachments, at, auth_server) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account, folder, uid) DO UPDATE SET "
                      "message_id=excluded.message_id, from_email=excluded.from_email, from_name=excluded.from_name, "
                      "verified=excluded.verified, subject=excluded.subject, date=excluded.date, seen=excluded.seen, "
                      "attachments=excluded.attachments, at=excluded.at, auth_server=excluded.auth_server, "
                      "snippet=CASE WHEN excluded.snippet!='' THEN excluded.snippet ELSE messages.snippet END",
                      (account, folder, int(r["uid"]), r.get("message_id") or "", (f.get("email") or "").lower(),
                       f.get("name") or "", 1 if r.get("from_verified") else 0, r.get("subject") or "",
                       r.get("date"), (snippets or {}).get(int(r["uid"]), ""), 1 if r.get("seen") else 0,
                       1 if r.get("attachments") else 0, now, str(r.get("auth_server") or "")[:200]))
        c.execute("DELETE FROM messages WHERE account=? AND rowid NOT IN (SELECT rowid FROM messages WHERE account=? "
                  "ORDER BY COALESCE(date, at) DESC LIMIT ?)", (account, account, KEEP_MESSAGES))


AUTH_SAMPLES = 50


def auth_samples(account: str) -> list[tuple[str, str]]:
    """(authserv-id of the topmost Authentication-Results, sender) of the newest mails the checks noted (access.detect)."""
    with conn() as c:
        rows = c.execute("SELECT auth_server, from_email FROM messages WHERE account=? AND folder='INBOX' AND "
                         "auth_server IS NOT NULL ORDER BY COALESCE(date, at) DESC LIMIT ?",
                         (account, AUTH_SAMPLES)).fetchall()
    return [(r["auth_server"] or "", r["from_email"] or "") for r in rows]


def add_contacts(account: str, addresses: list[str]) -> None:
    now = time.time()
    with conn() as c:
        for a in addresses:
            if a and "@" in a:
                c.execute("INSERT OR REPLACE INTO contacts(account, address, at) VALUES (?,?,?)",
                          (account, a.strip().lower(), now))


def unknown(account: str, addresses: list[str]) -> list[str]:
    """The addresses the owner never wrote to from Harness (nor allowed an agent to)."""
    out = []
    with conn() as c:
        for a in addresses:
            if not c.execute("SELECT 1 FROM contacts WHERE account=? AND address=?", (account, a.lower())).fetchone():
                out.append(a)
    return out


def recent(accounts: list[str], limit: int = 100, before: float | None = None) -> list[dict]:
    """The newest cached mails of these mailboxes ("All mailboxes")."""
    if not accounts:
        return []
    q = ",".join("?" * len(accounts))
    args: list[Any] = list(accounts)
    extra = ""
    if before:
        extra = " AND COALESCE(date, at) < ?"
        args.append(before)
    with conn() as c:
        rows = c.execute(f"SELECT * FROM messages WHERE account IN ({q}){extra} ORDER BY COALESCE(date, at) DESC "
                         "LIMIT ?", (*args, max(1, min(500, limit)))).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- what the agents did

def note(account: str, key: str, agent: str, what: str, detail: str = "") -> None:
    now = time.time()
    with conn() as c:
        last = c.execute("SELECT id, what, detail, at FROM seen_by WHERE account=? AND mkey=? AND agent=? "
                         "ORDER BY id DESC LIMIT 1", (account, key, agent)).fetchone()
        if last and last["what"] == what and last["detail"] == detail and now - last["at"] < 3600:
            c.execute("UPDATE seen_by SET at=? WHERE id=?", (now, last["id"]))
        else:
            c.execute("INSERT INTO seen_by(account, mkey, agent, at, what, detail) VALUES (?,?,?,?,?,?)",
                      (account, key, agent, now, what, detail[:300]))


def seen_by(account: str, keys: list[str]) -> dict[str, list[dict]]:
    """{mail key: [{agent, at, what, detail}, ... oldest first]}."""
    out: dict[str, list[dict]] = {}
    keys = [k for k in dict.fromkeys(keys) if k]
    for i in range(0, len(keys), 400):
        part = keys[i:i + 400]
        with conn() as c:
            rows = c.execute(f"SELECT mkey, agent, at, what, detail FROM seen_by WHERE account=? AND mkey IN "
                             f"({','.join('?' * len(part))}) ORDER BY id", (account, *part)).fetchall()
        for r in rows:
            out.setdefault(r["mkey"], []).append({"agent": r["agent"], "at": r["at"], "what": r["what"],
                                                  "detail": r["detail"]})
    return out


# ---------------------------------------------------------------- outbox rows

def outbox_put(row: dict) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO outbox(id, account, agent, at, status, data, event_id, done_at, note) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (row["id"], row["account"], row["agent"], row["at"], row["status"],
                                                 json.dumps(row["data"]), row.get("event_id"), row.get("done_at"),
                                                 row.get("note") or ""))


def _outbox_row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["data"] = json.loads(d["data"] or "{}")
    return d


def outbox_get(oid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM outbox WHERE id=?", (oid,)).fetchone()
    return _outbox_row(r) if r else None


def outbox_list(status: str | None = "waiting", account: str | None = None, limit: int = 100) -> list[dict]:
    sql, args = "SELECT * FROM outbox WHERE 1=1", []
    if status:
        sql += " AND status=?"
        args.append(status)
    if account:
        sql += " AND account=?"
        args.append(account)
    with conn() as c:
        rows = c.execute(sql + " ORDER BY at DESC LIMIT ?", (*args, limit)).fetchall()
    return [_outbox_row(r) for r in rows]


def outbox_claim(oid: str, status: str, note: str = "") -> bool:
    """waiting -> status, once: two clicks at the same time never send twice."""
    with conn() as c:
        n = c.execute("UPDATE outbox SET status=?, done_at=?, note=? WHERE id=? AND status='waiting'",
                      (status, time.time(), note[:500], oid)).rowcount
    return n == 1


def outbox_set(oid: str, status: str, note: str = "") -> None:
    with conn() as c:
        c.execute("UPDATE outbox SET status=?, done_at=?, note=? WHERE id=?", (status, time.time(), note[:500], oid))
