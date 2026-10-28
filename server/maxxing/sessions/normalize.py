"""Raw log lines (Claude stream-json + our mx_* lines) -> API.md Event vocabulary.

Normalisation runs at read time and is stateless per line, so improvements apply to old sessions.
Background work (sub-agents, commands) becomes `task` events, one per task_* line, merged by the UI on the
task id. Dropped on purpose: system chatter (thinking_tokens, status, rate limits, hooks…), commands run by a sub-agent,
sub-agent internals (lines with a parent_tool_use_id), synthetic user texts (auto-compaction
summaries), and empty (redacted) thinking blocks.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Iterable

TOOL_RESULT_MAX = 20_000
SUMMARY_MAX = 120
TASK_KINDS = {"local_agent": "agent", "local_bash": "shell"}
TASK_STATES = {"completed": "completed", "failed": "failed", "stopped": "stopped", "killed": "stopped"}
# a "\\ud800"-style escape not part of a surrogate pair (a text cut inside an emoji): valid JSON, but the lone
# surrogate it decodes to cannot be encoded as UTF-8 (the events response and the search index failed on it)
_LONE_SURROGATE = re.compile(r"\\u[dD][89abAB][0-9a-fA-F]{2}(?!\\u[dD][c-fC-F])"
                             r"|(?<!\\u[dD][89abAB][0-9a-fA-F]{2})\\u[dD][c-fC-F][0-9a-fA-F]{2}")


def normalize_lines(lines: Iterable[str]) -> list[dict]:
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if _LONE_SURROGATE.search(line):
            ev = _no_surrogates(ev)
        if isinstance(ev, dict):
            try:
                out.extend(normalize(ev))
            except (AttributeError, TypeError, ValueError):     # a field of an unexpected type: skip that line
                continue
    return out


def _no_surrogates(v: Any) -> Any:
    """Lone surrogates -> U+FFFD (pairs are already joined by json.loads)."""
    if isinstance(v, str):
        return v.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    if isinstance(v, dict):
        return {_no_surrogates(k): _no_surrogates(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_no_surrogates(x) for x in v]
    return v


def normalize(ev: dict) -> list[dict]:
    """One raw event -> 0..n normalised events."""
    t = ev.get("type")
    at = _at(ev)
    if t == "mx_user":
        out = {"type": "user", "text": ev.get("text") or "", "attachments": list(ev.get("attachments") or []),
               "at": at, "source": ev.get("source") or "web"}
        if ev.get("voice"):                   # a voice message sent directly: its transcript follows (mx_voice)
            out["voice"] = [str(v) for v in ev["voice"] if v]
        return [out]
    if t == "mx_voice":
        return [{"type": "voice_text", "text": ev.get("text") or "", "error": ev.get("error") or None,
                 **({"stopped": True} if ev.get("stopped") else {}), "at": at}]
    if t == "mx_hide":
        ref = ev.get("ref")
        if not isinstance(ref, (int, float)):
            return []
        return [{"type": "hide", "ref": ref, "hidden": ev.get("hidden") is not False, "at": at}]
    if t == "mx_note":
        return [{"type": "note", "text": ev.get("text") or "", "level": ev.get("level") or "info", "at": at}]
    if t == "mx_done":
        if ev.get("code") not in (0, None) and not ev.get("stopped") and not ev.get("timed_out"):
            tail = (ev.get("stderr") or "").strip()
            text = f"Turn failed: {tail[-500:]}" if tail else f"Turn failed (exit code {ev.get('code')})."
            return [{"type": "note", "text": text, "level": "error", "at": at}]
        return []
    if ev.get("parent_tool_use_id"):
        return []
    if t == "system":
        return _system(ev, at)
    if t == "assistant":
        return _assistant(ev, at)
    if t == "user":
        return _user(ev, at)
    if t == "result":
        return [_result(ev, at)]
    return []


# ---- per type ------------------------------------------------------------------------------
def _system(ev: dict, at: float | None) -> list[dict]:
    sub = ev.get("subtype")
    if sub == "init":
        return [{"type": "init", "model": ev.get("model") or "", "cwd": ev.get("cwd") or "", "at": at}]
    if sub == "compact_boundary":
        return [{"type": "note", "text": "Harness compacted its context automatically.", "level": "info", "at": at}]
    if isinstance(sub, str) and sub.startswith("task_"):
        return _task(ev, sub, at)
    if sub == "api_retry":
        return [{"type": "note", "level": "warn", "at": at,
                 "text": f"API retry {ev.get('attempt')}/{ev.get('max_retries')}: {ev.get('error') or ''}".strip()}]
    return []


def _clip(v: Any, n: int) -> str:
    s = str(v or "").strip()
    return s if len(s) <= n else s[:n] + f"\n… (truncated, {len(s)} characters)"


def _task(ev: dict, sub: str, at: float | None) -> list[dict]:
    """task_started / task_progress / task_updated / task_notification -> a partial `task` event (only the fields
    the line carries). Commands are tasks too (foreground ones included: one may be moved to the background)."""
    tid = ev.get("task_id")
    if not isinstance(tid, str) or not tid or ev.get("owned_by_subagent"):
        return []
    out: dict[str, Any] = {"type": "task", "id": tid, "at": at}
    if isinstance(ev.get("tool_use_id"), str) and ev["tool_use_id"]:
        out["tool_use_id"] = ev["tool_use_id"]
    usage = ev.get("usage") if isinstance(ev.get("usage"), dict) else {}
    for k, key in (("total_tokens", "tokens"), ("tool_uses", "tools"), ("duration_ms", "duration_ms")):
        if isinstance(usage.get(k), (int, float)):
            out[key] = int(usage[k])
    if sub == "task_started":
        tt = ev.get("task_type")
        out.update(state="running", kind=TASK_KINDS.get(tt, "other"), background=bool(ev.get("is_backgrounded")),
                   description=_short(ev.get("description"), 200))
        if ev.get("subagent_type"):
            out["agent_type"] = str(ev["subagent_type"])
    elif sub == "task_progress":
        out["state"] = "running"
        if ev.get("description"):
            out["activity"] = _short(ev["description"])
        if ev.get("last_tool_name"):
            out["last_tool"] = str(ev["last_tool_name"])
    elif sub == "task_updated":
        patch = ev.get("patch") if isinstance(ev.get("patch"), dict) else {}
        if patch.get("status") in TASK_STATES:
            out["state"] = TASK_STATES[patch["status"]]
        elif patch.get("status") == "running":
            out["state"] = "running"
        if isinstance(patch.get("is_backgrounded"), bool):
            out["background"] = patch["is_backgrounded"]
        if "state" not in out and "background" not in out:   # nothing shown changed
            return []
    elif sub == "task_notification":
        out["state"] = TASK_STATES.get(ev.get("status"), "completed")
        if ev.get("summary"):
            out["summary"] = _clip(ev["summary"], TOOL_RESULT_MAX)
    else:
        return []
    return [out]


def _assistant(ev: dict, at: float | None) -> list[dict]:
    out = []
    for b in (ev.get("message") or {}).get("content") or []:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text" and (b.get("text") or "").strip():
            out.append({"type": "assistant", "text": b["text"], "at": at})
        elif bt == "thinking" and (b.get("thinking") or "").strip():
            out.append({"type": "thinking", "text": b["thinking"], "at": at})
        elif bt == "tool_use":
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            out.append({"type": "tool_use", "id": b.get("id") or "", "name": b.get("name") or "",
                        "input": inp, "summary": tool_summary(b.get("name") or "", inp), "at": at})
    return out


def _user(ev: dict, at: float | None) -> list[dict]:
    if ev.get("isSynthetic"):
        return []
    content = (ev.get("message") or {}).get("content")
    out = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                text = _result_text(b.get("content"))
                if len(text) > TOOL_RESULT_MAX:
                    text = text[:TOOL_RESULT_MAX] + f"\n… (truncated, {len(text)} characters)"
                out.append({"type": "tool_result", "tool_use_id": b.get("tool_use_id") or "",
                            "text": text, "is_error": bool(b.get("is_error")), "at": at})
    return out


def _result(ev: dict, at: float | None) -> dict:
    u = ev.get("usage") if isinstance(ev.get("usage"), dict) else {}
    mu = ev.get("modelUsage") if isinstance(ev.get("modelUsage"), dict) else {}
    model = max(mu, key=lambda k: (mu[k] or {}).get("costUSD") or 0) if mu else ""
    return {"type": "result", "ok": not ev.get("is_error") and ev.get("subtype", "success") == "success",
            "cost_usd": float(ev["mx_turn_cost"] if ev.get("mx_turn_cost") is not None else ev.get("total_cost_usd") or 0), "duration_ms": int(ev.get("duration_ms") or 0),
            "model": model,
            "usage": {"input": int(u.get("input_tokens") or 0), "output": int(u.get("output_tokens") or 0),
                      "cache_read": int(u.get("cache_read_input_tokens") or 0),
                      "cache_write": int(u.get("cache_creation_input_tokens") or 0)},
            "at": at}


def _result_text(c: Any) -> str:
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text") or "")
                elif b.get("type") == "image":
                    parts.append("[image]")
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(parts)
    return "" if c is None else json.dumps(c, ensure_ascii=False)


def _at(ev: dict) -> float | None:
    for k in ("at", "mx_at"):
        v = ev.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    ts = ev.get("timestamp")
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


# ---- tool summaries ------------------------------------------------------------------------
def _short(s: Any, n: int = SUMMARY_MAX) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _rel(path: Any) -> str:
    p = str(path or "")
    return _short(p, SUMMARY_MAX)


def tool_summary(name: str, inp: dict) -> str:
    """One-line human description of a tool call ("Read src/app.py", "Bash: ls -la")."""
    g = inp.get
    if name in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "NotebookRead"):
        target = g("file_path") or g("notebook_path") or g("path") or ""
        return f"{name} {_rel(target)}".strip()
    if name == "Bash":
        return _short(f"Bash: {g('command') or ''}")
    if name in ("Grep", "Glob"):
        pat = g("pattern") or ""
        where = g("path") or ""
        return _short(f"{name} '{pat}'" + (f" in {where}" if where else ""))
    if name in ("WebFetch", "WebSearch"):
        return _short(f"{name} {g('url') or g('query') or ''}")
    if name in ("Task", "Agent"):
        return _short(f"{name}: {g('description') or g('subagent_type') or ''}")
    if name == "TodoWrite":
        todos = g("todos") if isinstance(g("todos"), list) else []
        return f"TodoWrite ({len(todos)} items)"
    if name == "Skill":
        return _short(f"Skill {g('skill') or g('name') or ''}")
    if name.startswith("mcp__"):
        return _short(name.split("__", 2)[-1] + " (" + name.split("__")[1] + ")")
    for k in ("description", "command", "file_path", "path", "url", "query", "prompt"):
        if g(k):
            return _short(f"{name}: {os.path.basename(str(g(k))) if k.endswith('path') else g(k)}")
    return name
