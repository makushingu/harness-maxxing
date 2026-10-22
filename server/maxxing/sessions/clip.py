"""Shrink raw log lines before they are written.  STDLIB ONLY (used by the runner).

Tool outputs (file reads, command output, images) are ~90 % of a long session's log and the UI
only shows a short head of each. The runner clips them at write time; `maxxing sessions
compact-logs` applies the same function to existing logs. The stream-json structure is kept
(same keys, same block types); a clipped value ends with a marker giving the original size and the
block gets `mx_clipped: <original characters>`.

Two kinds of system lines are also slimmed: `system/init` keeps only INIT_KEEP (Claude repeats the whole
tool / skill / slash-command list there at every turn, ~20 KB, read by nothing) and progress-only lines
(DROP_SUBTYPES: `system/thinking_tokens`, dropped by normalize.py anyway) are not written at all.
"""
from __future__ import annotations

import json
from typing import Any

RESULT_MAX = 2_000            # characters kept per tool result
INPUT_MAX = 20_000            # characters kept per large tool input field (Write content, Edit strings…)
INPUT_FIELDS = ("content", "old_string", "new_string", "new_source", "text")
DUPLICATES = ("tool_use_result", "toolUseResult")   # raw copies of the tool output (never displayed)
INIT_KEEP = ("type", "subtype", "cwd", "session_id", "model", "permissionMode", "apiKeySource",
             "claude_code_version", "output_style", "fast_mode_state", "mcp_servers", "uuid", "mx_at")
DROP_SUBTYPES = ("thinking_tokens",)                 # system progress lines: never written


def keep_event(ev: dict) -> bool:
    """False for progress-only system lines that are not written to the log."""
    return not (ev.get("type") == "system" and ev.get("subtype") in DROP_SUBTYPES)


def _slim_init(ev: dict) -> bool:
    extra = [k for k in ev if k not in INIT_KEEP]
    for k in extra:
        del ev[k]
    return bool(extra)


def _cut(s: str, limit: int) -> str:
    return s[:limit] + f"\n[… clipped by Harness Maxxing: {len(s):,} characters in total]"


def _clip_result_content(c: Any) -> tuple[Any, int]:
    """(new content, original size in characters; 0 = unchanged)."""
    if isinstance(c, str):
        return (_cut(c, RESULT_MAX), len(c)) if len(c) > RESULT_MAX else (c, 0)
    if isinstance(c, list):
        total, changed, out = 0, False, []
        for x in c:
            if isinstance(x, dict) and x.get("type") == "image":
                out.append({"type": "text", "text": "[image]"})
                total += len(json.dumps(x.get("source") or "")) if isinstance(x.get("source"), dict) else 0
                changed = True
            elif isinstance(x, dict) and isinstance(x.get("text"), str):
                total += len(x["text"])
                if len(x["text"]) > RESULT_MAX:
                    out.append({**x, "text": _cut(x["text"], RESULT_MAX)})
                    changed = True
                else:
                    out.append(x)
            else:
                out.append(x)
        return (out, max(total, 1)) if changed else (c, 0)
    return c, 0


def _clip_input(inp: dict) -> bool:
    changed = False
    for k in INPUT_FIELDS:
        v = inp.get(k)
        if isinstance(v, str) and len(v) > INPUT_MAX:
            inp[k] = _cut(v, INPUT_MAX)
            changed = True
    edits = inp.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict) and _clip_input(e):
                changed = True
    return changed


def clip_event(ev: dict) -> bool:
    """Clip one parsed raw event in place; True when something changed."""
    t = ev.get("type")
    changed = False
    msg = ev.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if t == "system":
        return _slim_init(ev) if ev.get("subtype") == "init" else False
    if t == "user":
        for k in DUPLICATES:
            if k in ev:
                ev.pop(k)
                changed = True
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and not b.get("mx_clipped"):
                    new, size = _clip_result_content(b.get("content"))
                    if size:
                        b["content"], b["mx_clipped"] = new, size
                        changed = True
    elif t == "assistant" and isinstance(content, list):
        for b in content:
            if (isinstance(b, dict) and b.get("type") == "tool_use" and isinstance(b.get("input"), dict)
                    and not b.get("mx_clipped")):
                if _clip_input(b["input"]):
                    b["mx_clipped"] = True
                    changed = True
    return changed


def drop_line(line: bytes | str) -> bool:
    """True for a raw line that is not kept (see keep_event); cheap test first."""
    marker = b"thinking_tokens" if isinstance(line, bytes) else "thinking_tokens"
    if marker not in line or len(line) > 4096:
        return False
    try:
        ev = json.loads(line)
    except ValueError:
        return False
    return isinstance(ev, dict) and not keep_event(ev)


def clip_line(line: str) -> str:
    """Clip one raw NDJSON line (returned unchanged when it is small, not JSON or untouched)."""
    if len(line) <= RESULT_MAX:
        return line
    try:
        ev = json.loads(line)
    except ValueError:
        return line
    if not isinstance(ev, dict) or not clip_event(ev):
        return line
    return json.dumps(ev, ensure_ascii=False)
