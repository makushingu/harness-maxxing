"""`maxxing search "words" [--kind ...] [--in PATH] [--session ID]` - the workspace search of the interface
(search.py: past sessions, memory files and their archive, text files, tasks), for Claude: look a fact up instead of
reading logs. Every word first; when nothing holds them all, any of them, best first."""
from __future__ import annotations

import json
import os
import sys
import time

from . import cli, config

AROUND = 700          # characters shown around a hit of --session


def _configure(p) -> None:
    p.add_argument("query", nargs="*", help="words (3+ letters match as a prefix)")
    p.add_argument("--kind", default="", help="comma list: session, memory, file, task, group (default: all)")
    p.add_argument("--in", dest="within", default="", help="only under this workspace path (projects/<p>/topics/<t>)")
    p.add_argument("--session", default="", help="a session id: its matching messages, with more text around")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--json", action="store_true")


def _day(at) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(float(at)))
    except (TypeError, ValueError):
        return ""


def _clean(s: str) -> str:
    return " ".join(s.replace("\x02", "").replace("\x03", "").split())


def _rel(path: str) -> str:
    """A path relative to the workspace: sessions give "projects/<p>/topics/<t>", files and memories their full path."""
    p, ws = path.strip("/"), str(config.workspace()).strip("/")
    return "" if p == ws else p[len(ws) + 1:] if p.startswith(ws + "/") else p


def _under(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")      # projects/a, not projects/ab


def find(q: str, kinds: list[str] | None, limit: int, within: str = "", snippet: int = 16) -> tuple[list[dict], bool]:
    """-> (results, loose): every word, else any word; never the session that asks."""
    from . import search
    me = os.environ.get("MAXXING_SESSION") or ""
    within = _rel(within)
    for loose in (False, True):
        res = search.search(q, kinds, limit * (6 if within else 1), loose=loose, not_session=me, snippet=snippet)["results"]
        if within:
            res = [r for r in res if _under(_rel(r.get("path") or ""), within)]
        if res:
            return res[:limit], loose
    return [], False


def _in_session(q: str, sid: str, limit: int) -> list[dict]:
    from . import search
    match = search.fts_query_any(q)
    if not match:
        return []
    search.search(q, ["session"], 1)                           # brings the index up to date
    rows = search._reader().execute(
        "SELECT items.body, items.at FROM fts JOIN items ON items.id = fts.rowid WHERE fts MATCH ? AND items.kind='session' "
        "AND items.ref LIKE ? ORDER BY bm25(fts) LIMIT ?", (match, sid + "%", limit)).fetchall()
    words = [w.lower() for w in q.split() if len(w) > 2]
    out = []
    for body, at in rows:
        low = body.lower()
        pos = min((low.find(w) for w in words if w in low), default=0)
        a = max(0, pos - AROUND // 2)
        out.append({"at": at, "text": ("…" if a else "") + _clean(body[a:a + AROUND]) + ("…" if a + AROUND < len(body) else "")})
    return out


def _line(r: dict) -> str:
    ref = f" id={r['id'][:8]}" if r["kind"] in ("session", "group") else ""
    return f"{r['kind']}{ref} [{_day(r['at'])}] {r['title']} · {r['path']}\n    {_clean(r['snippet'])}"


def _handler(a) -> int:
    q = " ".join(a.query)
    if not q.strip():
        print("usage: maxxing search \"words\"", file=sys.stderr)
        return 2
    limit = max(1, a.limit)
    if a.session:
        hits = _in_session(q, a.session, limit)
        if a.json:
            print(json.dumps(hits, indent=2, ensure_ascii=False))
        else:
            print("\n\n".join(f"[{_day(h['at'])}] {h['text']}" for h in hits) or "nothing in this session")
        return 0
    res, loose = find(q, [k.strip() for k in a.kind.split(",") if k.strip()] or None, limit, a.within)
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if not res:
        print("nothing found: try other words (a synonym, a name, a value)")
        return 0
    if loose:
        print("(nothing holds every word: closest results, newest facts win over older ones)")
    print("\n".join(map(_line, res)))
    if any(r["kind"] == "session" for r in res):
        print('\nmore of a session: maxxing search "words" --session <id>')
    return 0


cli.register("search", "search past sessions, memory, files and tasks", _configure, _handler)
