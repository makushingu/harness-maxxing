"""Workspace-wide full-text search: one SQLite FTS5 index (stdlib, no service) over the session
messages, the text files of the workspace (memory.md / CLAUDE.md flagged as "memory") and the tasks.
See docs/dev/API.md#search.

- `<state>/search.db`: `items` (one row per message / file / task, `src` = where it comes from) +
  `fts` (external-content FTS5 over items.title/body, kept in sync by triggers) + `src` (signature of
  what was indexed: log offset, file mtime/size, tasks.json signature).
- Incremental: a session log is read from the last indexed offset (a rewritten log - compact-logs -
  is reindexed); a file is reindexed when its mtime/size changes; gone sources are dropped.
- Tokenizer `unicode61 remove_diacritics 2` (tache = tâche) with prefix indexes: every word of 3+
  characters of the query is a prefix ("fac" finds "facture"; "fa" is the word "fa"), all words must
  match, in any order. Ranked with BM25, the title weighs 4x the body. A session's title sits on its
  title row only (not on each message row): a title match never crowds out the other sessions, and a
  rename rewrites one row. Results are deduplicated in SQL (best row per session / file / task), and a
  broad query ranks only its RANK_MAX newest matching rows.
- Refresh: a background loop (api/search.py, every 30 s) and, before each query, the sessions only
  (cheap: one stat per log, only the new bytes are read). The loop re-reads the memory files (CLAUDE.md /
  memory.md at their known places: a few stats) every pass, and walks the other files only every
  FILES_EVERY_S (a direct `refresh()` always does both).
- Files: every CLAUDE.md / memory.md of the workspace root, the projects, the topics and the agents is indexed,
  outside any cap (an agent's are titled "memory.md · agent <a> (<p>/<t>)"). The other text files are spread
  fairly: one budget per topic and per agent (or per project / the workspace root for files outside topics), a cap on the entries a walk visits, and a global MAX_FILES -
  the walk stops as soon as a cap is reached. Data files (.json, .csv, .xml, .svg...) are not indexed.
  Rows that no longer follow these rules are dropped by the next full pass (FILE_RULES in meta: when it
  changes, the database is VACUUMed once so it shrinks on disk).
- WAL: a refresh that changed rows ends with `wal_checkpoint(TRUNCATE)` (short busy timeout: a query
  holding a snapshot makes it a no-op until the next pass), and `journal_size_limit` caps what an
  automatic checkpoint leaves behind, so search.db-wal stays small instead of keeping its high-water mark.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import stat
import threading
import time
import zlib
from pathlib import Path
from typing import Callable

from . import config

log = logging.getLogger("maxxing.search")

SCHEMA_VERSION = "2"                 # 2: session title on the title row only (see _migrate)
KINDS = ("session", "file", "memory", "task")
TEXT_EXT = {".md", ".markdown", ".txt", ".rst", ".org", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
            ".css", ".scss", ".html", ".htm", ".vue", ".svelte", ".astro", ".php", ".rb", ".go", ".rs", ".java",
            ".kt", ".swift", ".c", ".h", ".cpp", ".cs", ".sh", ".bash", ".zsh", ".sql", ".yaml", ".yml", ".toml",
            ".ini", ".cfg", ".conf", ".env.example", ".tex"}   # not .json/.csv/.tsv/.xml/.svg: data, not text to search
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache", ".next", "dist", "build",
             ".mypy_cache", ".pytest_cache", "attachments", ".nuxt", ".svelte-kit", "vendor", "coverage"}
SKIP_FILES = {"tasks.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock"}
MEMORY_NAMES = {"memory.md", "claude.md"}
MAX_FILE_BYTES = 256 * 1024          # bigger text files are skipped (generated data, dumps)
MAX_FILES = 20_000                   # other text files, whole workspace (memory files are not counted)
BUCKET_MIN, BUCKET_MAX = 50, 1_000    # per topic / project / root: MAX_FILES // buckets, clamped to this range
MAX_SCAN_ENTRIES = 20_000            # directory entries one bucket's walk may visit (big data folders)
FILES_EVERY_S = 600                  # background loop: full walk of the files at most this often
FILE_RULES = "2"                     # bump when the indexing rules change: rows are cleaned, then VACUUM
MAX_MESSAGE_CHARS = 20_000
READ_CHUNK = 4 * 1024 * 1024         # session log bytes read per pass and session
WAL_LIMIT = 4 * 1024 * 1024          # journal_size_limit: bytes the WAL keeps after a checkpoint
CHECKPOINT_BUSY_MS = 200             # a TRUNCATE checkpoint waits at most this long for readers
RANK_MAX = 5_000                     # a query ranks at most this many matching rows (the newest ones)
# Rows replaced as logs and files change leave free pages behind: after a files walk, search.db is VACUUMed when more
# than VACUUM_FREE of it is free (and it is at least VACUUM_MIN_BYTES), at most every VACUUM_EVERY_S.
VACUUM_FREE = 0.25
VACUUM_MIN_BYTES = 4 * 1024 * 1024
VACUUM_EVERY_S = 86400

_lock = threading.RLock()          # writer: refreshes (one connection)
_rlock = threading.Lock()          # reader: queries use their own connection (WAL), never wait on a refresh
_state = {"sessions_at": 0.0, "full_at": 0.0, "files_at": 0.0}
# session key -> (meta stat, log stat) when it was last fully indexed: an unchanged session is skipped
_seen: dict[str, tuple] = {}


# ---- storage ---------------------------------------------------------------------------------
def db_path() -> Path:
    return config.STATE / "search.db"


def _connect() -> sqlite3.Connection:
    if not db_path().exists():
        os.close(os.open(db_path(), os.O_CREAT | os.O_WRONLY, 0o600))
    con = sqlite3.connect(db_path(), timeout=10, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute(f"PRAGMA journal_size_limit={WAL_LIMIT}")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS src(key TEXT PRIMARY KEY, sig TEXT);
        CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY, src TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
            path TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
            at REAL);
        CREATE INDEX IF NOT EXISTS items_src ON items(src);
        CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
            title, body, content='items', content_rowid='id',
            tokenize="unicode61 remove_diacritics 2", prefix='2 3');
        CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
            INSERT INTO fts(rowid, title, body) VALUES (new.id, new.title, new.body); END;
        CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
            INSERT INTO fts(fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body); END;
    """ + _AU_TRIGGER)
    row = con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
    if row is None:
        con.execute("INSERT INTO meta VALUES('schema', ?)", (SCHEMA_VERSION,))
        con.commit()
    return con


# OF title, body: a session moved to another topic changes the path of its rows without re-indexing them
_AU_TRIGGER = """
        CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE OF title, body ON items BEGIN
            INSERT INTO fts(fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
            INSERT INTO fts(rowid, title, body) VALUES (new.id, new.title, new.body); END;
"""


def _migrate(con: sqlite3.Connection) -> None:
    """Bring an index built by an older version up to SCHEMA_VERSION (writer connection, under _lock)."""
    row = con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
    if row and row[0] == SCHEMA_VERSION:
        return
    # 1 -> 2: the session title was copied into every message row (a session whose title matched filled the
    # results on its own, and a rename re-indexed all its messages): keep it on the title row only. One pass
    # over the message rows, once.
    t0 = time.monotonic()
    con.execute("DROP TRIGGER IF EXISTS items_au")
    con.executescript(_AU_TRIGGER)
    con.execute("UPDATE items SET title='' WHERE kind='session' AND body!='' AND title!=''")
    con.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (SCHEMA_VERSION,))
    con.commit()
    log.info("search index moved to schema %s in %.1f s", SCHEMA_VERSION, time.monotonic() - t0)


_con: sqlite3.Connection | None = None
_con_path: Path | None = None


def _db() -> sqlite3.Connection:
    """One connection per process (guarded by _lock); reopened when the state dir changes (tests)."""
    global _con, _con_path
    if _con is None or _con_path != db_path():
        if _con is not None:
            _con.close()
        _con, _con_path = _connect(), db_path()
        _migrate(_con)
        _state.update(sessions_at=0.0, full_at=0.0, files_at=0.0)   # another index: nothing is fresh
        _seen.clear()
    return _con


def _drop(con: sqlite3.Connection, key: str) -> None:
    con.execute("DELETE FROM items WHERE src=?", (key,))
    con.execute("DELETE FROM src WHERE key=?", (key,))


# ---- sessions --------------------------------------------------------------------------------
def _log_ident(p: Path) -> str:
    """Inode + first bytes: changes when compact-logs rewrites the file."""
    try:
        with open(p, "rb") as f:
            head = f.read(256)
        return f"{os.stat(p).st_ino}:{zlib.crc32(head):x}"
    except OSError:
        return ""


def _stat_key(p: Path) -> tuple | None:
    try:
        st = p.stat()
    except OSError:
        return None
    return st.st_ino, st.st_mtime_ns, st.st_size


def _index_sessions(con: sqlite3.Connection) -> None:
    from .sessions import normalize, store
    known = {k for (k,) in con.execute("SELECT key FROM src WHERE key LIKE 's:%'")}
    alive = set()
    for sid in store.list_ids():
        key = f"s:{sid}"
        alive.add(key)
        p = store.log_path(sid)
        stamp = (_stat_key(store.meta_path(sid)), _stat_key(p))
        if key in known and _seen.get(key) == stamp and None not in stamp:
            continue                                         # neither the meta nor the log changed
        _seen.pop(key, None)
        m = store.read(sid)
        size = stamp[1][2] if stamp[1] else -1
        if m is None or size < 0:                            # unreadable / no log: drop its rows
            alive.discard(key)
            continue
        title, path = m.get("title") or "Untitled", m.get("path") or ""
        row = con.execute("SELECT sig FROM src WHERE key=?", (key,)).fetchone()
        sig = json.loads(row[0]) if row else None
        read_all = True
        ident = _log_ident(p)
        if sig and (sig.get("ident") != ident or sig.get("offset", 0) > size):
            _drop(con, key)                                  # log rewritten: start over
            sig = None
        if sig is None:
            sig = {"offset": 0, "ident": ident, "title": title, "path": path}
            # a title row, so a session is found by its name even before any message is indexed
            con.execute("INSERT INTO items(src, kind, ref, path, title, body, at) VALUES (?,?,?,?,?,?,?)",
                        (key, "session", sid, path, title, "", m.get("updated") or m.get("created")))
        elif sig.get("title") != title or sig.get("path") != path:   # renamed, or moved to another topic
            if sig.get("title") != title:                    # the title row only (messages have no title)
                con.execute("UPDATE items SET title=? WHERE src=? AND body=''", (title, key))
            if sig.get("path") != path:                      # not indexed: no FTS work (items_au)
                con.execute("UPDATE items SET path=? WHERE src=?", (path, key))
            sig["title"], sig["path"] = title, path
        if sig["offset"] < size:
            with open(p, "rb") as f:
                f.seek(sig["offset"])
                chunk = f.read(READ_CHUNK)
            read_all = len(chunk) < READ_CHUNK               # what is left is at most an unterminated last line
            end = chunk.rfind(b"\n") + 1                     # complete lines only
            if not end and len(chunk) == READ_CHUNK:
                # One line longer than READ_CHUNK (an old unclipped tool result, a huge paste): skip it,
                # or the session would stop being indexed and re-read on every query.
                sig["offset"] += _skip_line(p, sig["offset"] + len(chunk)) - sig["offset"]
            if end:
                lines = chunk[:end].decode("utf-8", "replace").splitlines()
                for ev in normalize.normalize_lines(lines):
                    if ev.get("type") in ("user", "assistant", "voice_text") and (ev.get("text") or "").strip():
                        con.execute(
                            "INSERT INTO items(src, kind, ref, path, title, body, at) VALUES (?,?,?,?,?,?,?)",
                            (key, "session", sid, path, "", ev["text"][:MAX_MESSAGE_CHARS], ev.get("at")))
                sig["offset"] += end
        new = json.dumps(sig)
        if not row or new != row[0]:                         # unchanged (a log ending in a cut line): no write
            con.execute("INSERT OR REPLACE INTO src(key, sig) VALUES (?, ?)", (key, new))
        # all read - or only a cut last line left (a runner killed mid-write): skipped until something changes
        if sig["offset"] >= size or read_all:
            _seen[key] = stamp
    for key in known - alive:
        _drop(con, key)
        _seen.pop(key, None)


def _skip_line(p: Path, pos: int) -> int:
    """Offset just past the next newline at or after `pos` (end of file if none)."""
    with open(p, "rb") as f:
        f.seek(pos)
        while True:
            block = f.read(1024 * 1024)
            if not block:
                return f.tell()
            i = block.find(b"\n")
            if i >= 0:
                return pos + i + 1
            pos += len(block)


# ---- files -----------------------------------------------------------------------------------
def _text_file(name: str) -> bool:
    low = name.lower()
    if low in SKIP_FILES:
        return False
    return Path(low).suffix in TEXT_EXT or low in MEMORY_NAMES


def _index_one(con: sqlite3.Connection, base: str, fp: str, st: os.stat_result, known: dict) -> None:
    key = f"f:{fp}"
    sig = f"{st.st_mtime_ns}:{st.st_size}"
    if known.get(key) == sig:
        return
    try:
        raw = Path(fp).read_bytes()
    except OSError:
        return
    _drop(con, key)
    if b"\0" in raw[:4096]:                                  # binary with a text extension: no rows
        con.execute("INSERT OR REPLACE INTO src(key, sig) VALUES (?, ?)", (key, sig))
        return
    name = os.path.basename(fp)
    kind = "memory" if name.lower() in MEMORY_NAMES else "file"
    rel = os.path.relpath(fp, base)
    m = _AGENT_MEM_RE.match(rel) if kind == "memory" else None
    if m:                                                    # an agent's role / memory: its name in the title
        name = f"{name} · agent {m.group(3)} ({m.group(1)}/{m.group(2)})"
    # The relative path heads the body: "acme blog" finds projects/acme/topics/blog/notes.md.
    con.execute("INSERT INTO items(src, kind, ref, path, title, body, at) VALUES (?,?,?,?,?,?,?)",
                (key, kind, fp, fp, name, f"{rel}\n{raw.decode('utf-8', 'replace')}", st.st_mtime))
    con.execute("INSERT OR REPLACE INTO src(key, sig) VALUES (?, ?)", (key, sig))


def _file_stat(fp: str, base: str) -> os.stat_result | None:
    """stat of a file worth reading, else None: only regular files (reading a FIFO named notes.md would block
    the whole index), and a link only when it points inside the workspace (else any file the service can
    read - a key, a config - would land in the index and the search results)."""
    try:
        st = os.stat(fp)
        if not stat.S_ISREG(st.st_mode):
            return None
        if os.path.islink(fp):
            root = os.path.realpath(base)
            if os.path.commonpath([os.path.realpath(fp), root]) != root:
                return None
    except (OSError, ValueError):
        return None
    return st


def _subdirs(d: str) -> list[str]:
    try:
        return sorted(e.path for e in os.scandir(d) if e.is_dir(follow_symlinks=True)
                      and e.name not in SKIP_DIRS and not e.name.startswith("."))
    except OSError:
        return []


_AGENT_MEM_RE = re.compile(r"^projects/([^/]+)/topics/([^/]+)/agents/([^/]+)/[^/]+$")


def _layout(base: str) -> tuple[list[str], list[tuple[str, set[str]]]]:
    """(folders holding the memory files, buckets = (folder, sub-folders it must not walk)).
    Memory folders: the root, every project, every topic, every agent. Buckets: every agent, every topic without
    its agents/ folder, every project without its topics/ folder, the root without projects/."""
    mem, buckets = [base], []
    projects = os.path.join(base, "projects")
    for pdir in _subdirs(projects):
        mem.append(pdir)
        tdir = os.path.join(pdir, "topics")
        topics = _subdirs(tdir)
        mem += topics
        for t in topics:
            adir = os.path.join(t, "agents")
            agents = _subdirs(adir)
            mem += agents
            buckets += [(a, set()) for a in agents]
            buckets.append((t, {adir} if agents else set()))
        buckets.append((pdir, {tdir}))
    buckets.append((base, {projects}))
    return mem, buckets


def _index_memory(con: sqlite3.Connection, base: str, mem_dirs: list[str], known: dict) -> set[str]:
    alive = set()
    for d in mem_dirs:
        try:
            entries = [e for e in os.scandir(d) if e.is_file() and e.name.lower() in MEMORY_NAMES]
        except OSError:
            continue
        for e in entries:
            st = _file_stat(e.path, base)
            if st is None or st.st_size > MAX_FILE_BYTES:
                continue
            alive.add(f"f:{e.path}")
            _index_one(con, base, e.path, st, known)
    return alive


def _walk_bucket(con: sqlite3.Connection, base: str, root: str, skip: set[str], budget: int, known: dict,
                 alive: set[str]) -> tuple[int, bool]:
    """Index up to `budget` text files under `root`; memory files met on the way (deeper than the known places)
    are indexed outside the budget. -> (files counted, the walk was cut by a cap)."""
    count = scanned = 0
    for cur, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")
                         and os.path.join(cur, d) not in skip)
        scanned += len(files) + len(dirs)
        for name in sorted(files):
            if count >= budget:
                return count, True
            low = name.lower()
            fp = os.path.join(cur, name)
            if low in MEMORY_NAMES:
                if f"f:{fp}" not in alive:
                    st = _file_stat(fp, base)
                    if st is not None and st.st_size <= MAX_FILE_BYTES:
                        alive.add(f"f:{fp}")
                        _index_one(con, base, fp, st, known)
                continue
            if not _text_file(name):
                continue
            st = _file_stat(fp, base)
            if st is None or st.st_size > MAX_FILE_BYTES:
                continue
            count += 1
            alive.add(f"f:{fp}")
            _index_one(con, base, fp, st, known)
        if scanned >= MAX_SCAN_ENTRIES:
            return count, True
    return count, False


def _index_files(con: sqlite3.Connection, deep: bool = True) -> dict:
    """Memory files always; with `deep`, the other files too (and the rows outside the rules are dropped)."""
    base = str(config.workspace())
    known = {k: s for k, s in con.execute("SELECT key, sig FROM src WHERE key LIKE 'f:%'")}
    mem_dirs, buckets = _layout(base)
    alive = _index_memory(con, base, mem_dirs, known)
    if not deep:
        for key in known:                                   # a memory file deleted since the last pass
            if os.path.basename(key).lower() in MEMORY_NAMES and key not in alive and not os.path.exists(key[2:]):
                _drop(con, key)
        return {"memory": len(alive), "deep": False}
    per = max(BUCKET_MIN, min(BUCKET_MAX, MAX_FILES // max(1, len(buckets))))
    total, cut = 0, 0
    for root, skip in buckets:
        left = MAX_FILES - total
        if left <= 0:
            cut += 1
            continue
        n, was_cut = _walk_bucket(con, base, root, skip, min(per, left), known, alive)
        total += n
        cut += was_cut
    gone = set(known) - alive
    for key in gone:
        _drop(con, key)
    return {"memory": len(mem_dirs), "files": total, "buckets": len(buckets), "per_bucket": per,
            "cut": cut, "dropped": len(gone), "deep": True}


# ---- tasks -----------------------------------------------------------------------------------
def _index_tasks(con: sqlite3.Connection) -> None:
    from .api import tasks as tasks_api
    p = tasks_api.tasks_path()
    try:
        st = os.stat(p)
        sig = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        sig = "none"
    row = con.execute("SELECT sig FROM src WHERE key='t:tasks'").fetchone()
    if row and row[0] == sig:
        return
    con.execute("DELETE FROM items WHERE src='t:tasks'")
    try:
        data = tasks_api.load(copy_=False) if sig != "none" else {"tasks": []}   # read only: the shared cache
    except Exception:                                        # corrupt file: keep nothing, retry later
        data = {"tasks": []}
    for t in data.get("tasks", []):
        if not isinstance(t, dict) or not t.get("id"):
            continue
        body = "\n".join(filter(None, [t.get("notes") or "", " ".join(t.get("labels") or [])]))
        con.execute("INSERT INTO items(src, kind, ref, path, title, body, at) VALUES (?,?,?,?,?,?,?)",
                    ("t:tasks", "task", t["id"], t.get("topic_path") or "", t.get("title") or "", body,
                     t.get("updated")))
    con.execute("INSERT OR REPLACE INTO src(key, sig) VALUES ('t:tasks', ?)", (sig,))


# ---- refresh ---------------------------------------------------------------------------------
def refresh(full: bool = True, deep: bool | None = True) -> None:
    """Bring the index up to date (sessions always; memory files and tasks when `full`; the other files
    when `deep` - None = only if the last walk is older than FILES_EVERY_S, what the background loop asks)."""
    with _lock:
        con = _db()
        vacuum = walk = False
        try:
            before = con.total_changes
            _index_sessions(con)
            _state["sessions_at"] = time.time()
            if full:
                walk = deep if deep is not None else time.time() - _state["files_at"] >= FILES_EVERY_S
                info = _index_files(con, walk)
                _index_tasks(con)
                _state["full_at"] = time.time()
                if walk:
                    _state["files_at"] = time.time()
                    _state["files"] = info
                    row = con.execute("SELECT v FROM meta WHERE k='file_rules'").fetchone()
                    if not row or row[0] != FILE_RULES:
                        con.execute("INSERT OR REPLACE INTO meta VALUES('file_rules', ?)", (FILE_RULES,))
                        vacuum = info.get("dropped", 0) > 0
            con.commit()
        except Exception:
            con.rollback()
            _seen.clear()                                    # what was marked as indexed was rolled back
            log.exception("search index refresh failed")
            return
        if vacuum:                                          # rules changed and rows went away: give the space back
            try:
                # FTS5 keeps deleted rows as tombstones in its segments: rebuild it from items, then VACUUM
                con.execute("INSERT INTO fts(fts) VALUES('rebuild')")
                con.commit()
                checkpoint(con)
                con.execute("VACUUM")
                log.info("search index cleaned up and compacted (%s)", _state.get("files"))
            except sqlite3.Error as e:
                log.warning("search index VACUUM skipped: %s", e)
        elif walk:
            reclaim(con)
        if con.total_changes != before:
            checkpoint(con)


def reclaim(con: sqlite3.Connection | None = None, force: bool = False) -> bool:
    """VACUUM search.db when too much of it is free pages (see VACUUM_FREE). -> True when it ran."""
    with _lock:
        con = con or _db()
        if not force and time.time() - _state.get("vacuum_at", 0.0) < VACUUM_EVERY_S:
            return False
        try:
            pages = con.execute("PRAGMA page_count").fetchone()[0]
            free = con.execute("PRAGMA freelist_count").fetchone()[0]
            size = con.execute("PRAGMA page_size").fetchone()[0]
        except sqlite3.Error:
            return False
        if not pages or pages * size < VACUUM_MIN_BYTES or free / pages <= VACUUM_FREE:
            return False
        _state["vacuum_at"] = time.time()
        try:
            checkpoint(con)
            con.execute("VACUUM")
            checkpoint(con)
        except sqlite3.Error as e:
            log.warning("search index VACUUM skipped: %s", e)
            return False
        log.info("search index compacted: %d of %d pages were free", free, pages)
        return True


def checkpoint(con: sqlite3.Connection | None = None) -> tuple[int, int, int] | None:
    """Copy the WAL into search.db and truncate it -> (busy, wal frames, frames copied), None on error.
    busy=1: a reader held an older snapshot (nothing truncated, the next pass tries again)."""
    with _lock:
        con = con or _db()
        try:
            con.execute(f"PRAGMA busy_timeout={CHECKPOINT_BUSY_MS}")
            return tuple(con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
        except sqlite3.Error as e:
            log.info("search index checkpoint skipped: %s", e)
            return None
        finally:
            con.execute("PRAGMA busy_timeout=10000")


def optimize() -> None:
    with _lock:
        con = _db()
        con.execute("INSERT INTO fts(fts) VALUES('optimize')")
        con.commit()
        checkpoint(con)


# ---- query -----------------------------------------------------------------------------------
_WORD = re.compile(r"\w+", re.UNICODE)


def fts_query(q: str) -> str | None:
    """User text -> FTS5 query: every word is required, as a prefix when it has 3+ characters (a 2-letter
    prefix matches most of the index: "de", "th"...)."""
    words = _WORD.findall(q or "")[:12]
    if not words:
        return None
    return " ".join(f'"{w}"*' if len(w) >= 3 else f'"{w}"' for w in words)


_rcon: sqlite3.Connection | None = None
_rcon_path: Path | None = None


def _reader() -> sqlite3.Connection:
    global _rcon, _rcon_path
    if _rcon is None or _rcon_path != db_path():
        if _rcon is not None:
            _rcon.close()
        _rcon, _rcon_path = _connect(), db_path()
    return _rcon


def search(q: str, kinds: list[str] | None = None, limit: int = 30,
           cancelled: Callable[[], bool] | None = None) -> dict:
    """`cancelled`: True once nobody waits for the answer (the palette sent the next query): stops waiting for
    the reader and interrupts the query."""
    t0 = time.perf_counter()
    gone = cancelled or (lambda: False)
    match = fts_query(q)
    wanted = [k for k in (kinds or KINDS) if k in KINDS]
    if not match or not wanted or len(q.strip()) < 2:
        return {"results": [], "took_ms": 0}
    # Sessions are brought up to date first (one stat per log, only new bytes are read), so a message that
    # just arrived is found - unless a refresh is already running: then the query does not wait for it
    # (the request threads are shared with the whole API). Files and tasks follow the background loop.
    if _lock.acquire(blocking=False):
        try:
            _db()                                            # (re)opens the index of the current state dir
            refresh(full=_state["full_at"] == 0)             # nothing built yet (just started): build it
        finally:
            _lock.release()
    marks = ",".join("?" * len(wanted))
    while not _rlock.acquire(timeout=0.05):                  # one reader: queries take turns
        if gone():
            return {"results": [], "took_ms": 0, "cancelled": True}
    try:
        if gone():
            return {"results": [], "took_ms": 0, "cancelled": True}
        con = _reader()
        con.set_progress_handler(lambda: 1 if gone() else 0, 20_000)
        try:
            # only the RANK_MAX newest matching rows are ranked: the rowid of the oldest of them bounds the query
            # (a rowid range is cheap for FTS5; `rowid IN (...)` would run the match once per row)
            floor = con.execute(
                f"""SELECT MIN(id) FROM (SELECT fts.rowid AS id FROM fts JOIN items ON items.id = fts.rowid
                    WHERE fts MATCH ? AND items.kind IN ({marks}) ORDER BY fts.rowid DESC LIMIT ?)""",
                (match, *wanted, RANK_MAX)).fetchone()[0] or 0
            # best row per session / file / task (bare columns of MIN)
            # (MATERIALIZED: bm25/snippet cannot run inside the aggregate itself)
            rows = con.execute(
                f"""WITH hits AS MATERIALIZED (
                        SELECT items.kind AS kind, items.ref AS ref, items.path AS path, items.title AS title,
                               items.at AS at, snippet(fts, 1, char(2), char(3), '…', 16) AS snip,
                               bm25(fts, 4.0, 1.0) AS score
                        FROM fts JOIN items ON items.id = fts.rowid
                        WHERE fts MATCH ? AND fts.rowid >= ? AND items.kind IN ({marks}))
                    SELECT kind, ref, path, title, at, snip, MIN(score) AS best FROM hits
                    GROUP BY kind, ref ORDER BY best LIMIT ?""",
                (match, floor, *wanted, limit)).fetchall()
            untitled = [f"s:{r[1]}" for r in rows if r[0] == "session" and not r[3]]
            titles = dict(con.execute(
                f"SELECT ref, title FROM items WHERE body='' AND src IN ({','.join('?' * len(untitled))})",
                untitled).fetchall()) if untitled else {}
        except sqlite3.OperationalError:
            if gone():                                       # interrupted by the progress handler
                return {"results": [], "took_ms": 0, "cancelled": True}
            raise
        finally:
            con.set_progress_handler(None, 0)
    finally:
        _rlock.release()
    out = []
    for kind, ref, path, title, at, snip, score in rows:
        title = title or titles.get(ref) or "Untitled"       # a message row: the title of its session
        if not snip.strip() and kind == "session":
            snip = title
        out.append({"kind": kind, "id": ref, "path": path, "title": title, "snippet": snip, "at": at,
                    "score": round(-score, 3)})
    return {"results": out, "took_ms": round((time.perf_counter() - t0) * 1000, 1)}


def stats() -> dict:
    with _lock:
        con = _db()
        counts = dict(con.execute("SELECT kind, COUNT(DISTINCT ref) FROM items GROUP BY kind").fetchall())
    try:
        size = db_path().stat().st_size
    except OSError:
        size = 0
    return {"counts": counts, "bytes": size, "refreshed_at": _state["full_at"] or None,
            "files_walked_at": _state["files_at"] or None, "files": _state.get("files")}
