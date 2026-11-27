"""Search in the journal of the Harness units (Settings -> System -> Logs, `maxxing logs`).

The server and every turn / job unit log to the systemd journal. `search()` reads it with `journalctl -o json` and
filters in Python: a period, a minimum level, a text, the units of one session. Nothing is indexed or stored: the
journal is the only copy (`maxxing clean` and journald's own limits bound it).

Levels: the server writes "LEVEL logger: message" (logs.setup) and uvicorn "LEVEL:  message"; any other line takes
the journal priority (stderr of a unit = info unless the program says otherwise). A line without a level right after
one that has it (a traceback) keeps that level, so "errors only" shows the whole traceback. Every line goes through
logs.redact once more: a turn unit's output never went through the server's logging filter. STDLIB ONLY.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time

from . import logs

LEVELS = ("debug", "info", "warning", "error")
SINCE = {"15m": 900, "1h": 3600, "6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
SCAN_MAX = 20_000          # journal lines read for one search, the newest ones
LINE_MAX = 4_000           # characters kept of one line
Q_MAX = 200
_PREFIX = re.compile(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)(?::\s+| [\w.]+: )")
_NAMES = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 3}
_CONTINUES = re.compile(r"^(\s|Traceback \(most recent call last\)|[\w.]+(Error|Exception|Warning)\b)")


def _run(args: list[str]) -> str:
    """journalctl's output ("" when it is missing). Tests replace it."""
    if not shutil.which("journalctl"):
        return ""
    return subprocess.run(["journalctl", *args], capture_output=True, text=True, timeout=30).stdout


def _text(v) -> str:
    if isinstance(v, list):                             # a message that is not UTF-8: journald gives its bytes
        try:
            return bytes(v).decode("utf-8", "replace")
        except (TypeError, ValueError):
            return ""
    return v if isinstance(v, str) else ""


def _priority(v) -> int:
    try:
        p = int(v)
    except (TypeError, ValueError):
        return 1
    return 3 if p <= 3 else 2 if p == 4 else 1 if p <= 6 else 0


def parse(out: str, floor: int = 0) -> list[dict]:
    """journalctl -o json lines -> [{at, unit, level, text}], oldest first; `floor`: the lowest level kept (index of LEVELS)."""
    rows: list[dict] = []
    prev_level, prev_unit = 1, ""
    for raw in out.splitlines():
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        unit = _text(ev.get("_SYSTEMD_UNIT") or ev.get("UNIT")).removesuffix(".service")
        try:
            at = int(ev.get("__REALTIME_TIMESTAMP")) / 1e6
        except (TypeError, ValueError):
            at = 0.0
        for text in _text(ev.get("MESSAGE")).splitlines() or [""]:
            m = _PREFIX.match(text)
            if m:
                level = _NAMES[m.group(1)]
            elif unit == prev_unit and prev_level >= 2 and _CONTINUES.match(text):
                level = prev_level                      # the lines of a traceback
            else:
                level = _priority(ev.get("PRIORITY"))
            prev_level, prev_unit = level, unit
            if level < floor:
                continue                                # below the level asked: never masked nor kept
            # cut before masking (a journal line reaches 48 KB): the margin keeps a key across the cut recognised
            rows.append({"at": at, "unit": unit, "level": LEVELS[level],
                         "text": logs.redact(text[:LINE_MAX + 256])[:LINE_MAX]})
    return rows


def search(units: list[str], *, lines: int = 200, since: str = "", level: str = "", q: str = "",
           mention: dict[str, str] | None = None) -> dict:
    """The newest `lines` journal lines of `units` that match. `since`: a key of SINCE ("" = no limit but SCAN_MAX);
    `level`: the minimum one; `q`: a text, whatever its case; `mention`: {unit: text} keeps of that unit only the lines
    containing the text (the server's lines about one session). -> {lines, rows, matched, scanned, truncated}."""
    if level and level not in LEVELS:
        raise ValueError("level")
    if since and since not in SINCE:
        raise ValueError("since")
    args = ["-o", "json", "--no-pager", "-n", str(SCAN_MAX)]
    for u in units:
        args += ["-u", u]
    if since:
        args += ["--since", "@" + str(int(time.time() - SINCE[since]))]
    raw = _run(args)
    floor = LEVELS.index(level) if level else 0
    rows = parse(raw, floor)
    # journal entries, as SCAN_MAX counts them (a traceback is one entry of several lines)
    scanned = sum(1 for x in raw.splitlines() if x.startswith("{"))
    needle = q[:Q_MAX].casefold()
    mention = mention or {}
    keep = [r for r in rows
            if LEVELS.index(r["level"]) >= floor and (not needle or needle in r["text"].casefold())
            and (r["unit"] not in mention or mention[r["unit"]] in r["text"])]
    out = keep[-lines:]
    return {"lines": [format_row(r) for r in out], "rows": out, "matched": len(keep), "scanned": scanned,
            "truncated": scanned >= SCAN_MAX}


def format_row(r: dict) -> str:
    when = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(r["at"])) if r["at"] else "-"
    return f"{when} {r['unit'] or '-'}: {r['text']}"
