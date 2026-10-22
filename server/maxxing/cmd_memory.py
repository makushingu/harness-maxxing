"""`maxxing memory [--json]` - memory.md files, their size and the line limit (used by the memory-compaction skill)."""
from __future__ import annotations

import json

from . import cli


def _configure(p) -> None:
    p.add_argument("--json", action="store_true", help="machine-readable output")


def _handler(a) -> int:
    from . import memory
    limit, files = memory.max_lines(), memory.files()
    if a.json:
        print(json.dumps({"max_lines": limit, "files": files}, indent=2))
        return 0
    print(f"line limit: {limit or 'none'} (Settings -> Memory)")
    for f in files:
        flag = "  <- over the limit" if f["over"] else ""
        print(f"{f['lines']:>6} lines {f['bytes'] / 1024:>7.1f} KB  {f['path']}{flag}")
    return 0


cli.register("memory", "memory.md files, sizes and the line limit", _configure, _handler)
