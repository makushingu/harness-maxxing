"""Second-brain hygiene: the memory.md files of the workspace, their size, and the line limit the
memory-compaction skill enforces (Settings -> Memory, `maxxing memory`). See docs/dev/API.md#memory."""
from __future__ import annotations

import time
from pathlib import Path

from . import config

DEFAULT_MAX_LINES = 200


def max_lines() -> int:
    """0 = no limit (the skill then only compacts what is long, redundant or outdated)."""
    v = config.load_config().get("memory_max_lines", DEFAULT_MAX_LINES)
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return DEFAULT_MAX_LINES


def files() -> list[dict]:
    """Every memory.md (global, projects, topics) -> [{path (workspace-relative), level, lines, bytes, over}]."""
    ws = config.workspace()
    limit = max_lines()
    found: list[tuple[str, Path]] = [("global", ws / "memory.md")]
    for p in sorted((ws / "projects").glob("*/memory.md")):
        found.append(("project", p))
    for p in sorted((ws / "projects").glob("*/topics/*/memory.md")):
        found.append(("topic", p))
    out = []
    for level, p in found:
        try:
            data = p.read_bytes()
        except OSError:
            continue
        lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        out.append({"path": p.relative_to(ws).as_posix(), "level": level, "lines": lines, "bytes": len(data),
                    "over": bool(limit) and lines > limit})
    return out


def compact_prompt(limit: int) -> str:
    rule = (f"Line limit: every memory.md must end with at most {limit} lines - compact AND reorganise the files "
            f"above it (and only those, plus files that are redundant or contradictory)."
            if limit else "No line limit: compact only the files that need it.")
    return ("Use the memory-compaction skill now (manual clean started from Settings -> Memory). " + rule +
            " End with one line per file changed (before -> after lines) or 'nothing to compact'.")


def start_compaction() -> dict:
    """Starts a Claude session at the workspace root that runs the skill now -> the Session."""
    from .sessions import service
    when = time.strftime("%Y-%m-%d %H:%M")
    return service.create_session("", message=compact_prompt(max_lines()), title=f"Memory clean - {when}")
