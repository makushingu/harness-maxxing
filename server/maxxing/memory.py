"""Second-brain hygiene: the memory.md files of the workspace, their size, and the limit (lines and weight) the
memory-compaction skill enforces (Settings -> Memory, `maxxing memory`). See docs/dev/API.md#memory."""
from __future__ import annotations

import os
import stat
import time
from pathlib import Path

from . import config

DEFAULT_MAX_LINES = 100
LINES_PER_KB = 10              # the limit also weighs the file: 100 lines = 10 KB. A memory.md is loaded by every
                               # session of its folder and sent again IN FULL each time it changes (Claude Code
                               # re-reads instruction files when a turn starts), so a few very long bullets cost
                               # as much as many lines - and fill the context until the session is summarized
READ_MAX = 8 << 20             # bytes read to count the lines of one file: a bigger one is over any limit anyway


_counted: dict[str, tuple[tuple[int, int], int, int]] = {}   # path -> ((mtime_ns, size), lines, bytes)


def max_lines() -> int:
    """0 = no limit (the skill then only compacts what is long, redundant or outdated)."""
    v = config.load_config().get("memory_max_lines", DEFAULT_MAX_LINES)
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return DEFAULT_MAX_LINES


def max_bytes(limit: int | None = None) -> int:
    """The weight that goes with the line limit (0 = no limit)."""
    return (max_lines() if limit is None else limit) * 1024 // LINES_PER_KB


def files() -> list[dict]:
    """Every memory.md (global, projects, topics, agents) -> [{path (workspace-relative), level, lines, bytes, over,
    heavy}]: `over` = above the limit, in lines or in weight; `heavy` = in weight."""
    ws = config.workspace()
    limit = max_lines()
    weight = max_bytes(limit)
    found: list[tuple[str, Path]] = [("global", ws / "memory.md")] + [
        (level, p) for level, pattern in (("project", "*/memory.md"), ("topic", "*/topics/*/memory.md"),
                                          ("agent", "*/topics/*/agents/*/memory.md"))
        for p in sorted((ws / "projects").glob(pattern))]
    out = []
    for gone in set(_counted) - {p.relative_to(ws).as_posix() for _, p in found}:
        _counted.pop(gone, None)
    for level, p in found:
        rel = p.relative_to(ws).as_posix()
        try:
            rel.encode()                               # a folder named in another encoding cannot be shown in JSON
            st = os.stat(p)
            if not stat.S_ISREG(st.st_mode):          # a FIFO or a link to /dev/zero would never end
                continue
            key = (st.st_mtime_ns, st.st_size)
            hit = _counted.get(rel)
            if hit and hit[0] == key:                  # unchanged since the last count: not read again
                lines, size = hit[1], hit[2]
            else:
                with open(p, "rb") as f:
                    data = f.read(READ_MAX)
                lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
                size = max(st.st_size, len(data))
                _counted[rel] = (key, lines, size)
        except (OSError, UnicodeEncodeError):
            continue
        heavy = bool(limit) and size > weight
        out.append({"path": rel, "level": level, "lines": lines, "bytes": size,
                    "over": heavy or (bool(limit) and lines > limit), "heavy": heavy})
    return out


def compact_prompt(limit: int) -> str:
    rule = (f"Limit: every memory.md must end with at most {limit} lines and {max_bytes(limit) // 1024} KB (long "
            f"bullets shortened to one or two lines) - compact AND reorganise the files above it (and only those, "
            f"plus files that are redundant or contradictory)."
            if limit else "No line limit: compact only the files that need it.")
    return ("Use the memory-compaction skill now (manual clean started from Settings -> Memory). " + rule +
            " End with one line per file changed (before -> after lines and KB) or 'nothing to compact'.")


def start_compaction() -> dict:
    """Starts a Claude session at the workspace root that runs the skill now -> the Session."""
    from .sessions import service
    when = time.strftime("%Y-%m-%d %H:%M")
    return service.create_session("", message=compact_prompt(max_lines()), title=f"Memory clean - {when}")
