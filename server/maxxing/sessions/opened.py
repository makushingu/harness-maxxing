"""The sessions open on screen, shared by every browser of the user: a session opened on the computer is open on the
phone too (a column there, a tab here), and closing it anywhere closes it everywhere. Ids only, in the order they
were opened; each browser keeps its own layout (widths, stacks, which one is in front).

`<state>/open_sessions.json` = `{"ids": [...], "rev": n}`; no file = no browser has shared its sessions yet
(`ids: null`). `rev` grows with every change: a browser ignores an answer older than the one it already applied.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from .. import bus, config

MAX_OPEN = 60                       # more than a screen ever holds: the oldest ones go
_ID = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")
_lock = threading.Lock()


def _file() -> Path:
    return config.state_dir() / "open_sessions.json"


def _ids(value) -> list[str]:
    out: list[str] = []
    for x in value if isinstance(value, list) else ():
        if isinstance(x, str) and _ID.match(x) and x not in out:
            out.append(x)
    return out


def load() -> dict:
    data = config.read_json(_file(), None)
    if not isinstance(data, dict) or not isinstance(data.get("ids"), list):
        return {"ids": None, "rev": 0}
    rev = data.get("rev")
    return {"ids": _ids(data["ids"]), "rev": rev if isinstance(rev, int) and rev > 0 else 0}


def update(add: list | None = None, remove: list | None = None, order: list | None = None) -> dict:
    """Open (`add`) and close (`remove`) sessions, then put them in `order` (the ones it does not name keep their
    place, after)."""
    opened, closed, wanted = _ids(add), set(_ids(remove)), _ids(order)
    with _lock:
        cur = load()
        ids = [x for x in (cur["ids"] or []) if x not in closed]
        ids += [x for x in opened if x not in ids and x not in closed]
        if wanted:
            rank = {x: i for i, x in enumerate(wanted)}
            ids.sort(key=lambda x: rank.get(x, len(rank)))      # stable: the others stay in their order, at the end
        ids = ids[-MAX_OPEN:]
        if cur["ids"] is not None and ids == cur["ids"]:
            return cur
        new = {"ids": ids, "rev": cur["rev"] + 1}
        config.write_json(_file(), new)
    bus.invalidate("open_sessions")
    return new


def forget(sid: str) -> None:
    """A deleted session is open nowhere."""
    with _lock:
        cur = load()
    if cur["ids"] and sid in cur["ids"]:
        update(remove=[sid])
