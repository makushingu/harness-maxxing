"""What a turn did, step by step: model calls and tool calls with their time, tokens and outcome.

Read from the session's raw log at the moment it is asked (GET /api/sessions/{sid}/turns[/{n}], `maxxing sessions
trace`): nothing more is stored and a running turn pays nothing for it. A turn is what lies between an `mx_user` line
and its `mx_done` (runner.py); Claude Code's own lines carry `mx_at` (when the runner read them).

Steps:
- `model`: one call to the model = the assistant lines sharing a message id (one line per content block, the same
  usage on each: counted once). `context` = the tokens the call read (new input + cache read + cache written), as
  the API reported them when the answer started. Claude Code does not log what each call wrote: output tokens and
  cost exist per turn only (the `result` line), never per step.
- `tool`: one tool call, from its `tool_use` block to its `tool_result`: `duration_s` between the two, `error`.
- `note`: a line Harness wrote in the turn (`mx_note`: a retry, a limit...).
Steps of a sub-agent have `sub: true`.

A log compacted by `maxxing sessions compact-logs` keeps every line this reads (it clips tool outputs only).
"""
from __future__ import annotations

import json

from . import normalize, store

STEPS_MAX = 3000           # steps kept of one turn (the first ones)
PROMPT_MAX = 300
TEXT_MAX = 200
_KEYS = (("input", "input_tokens"), ("output", "output_tokens"),
         ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens"))


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else None


def _tokens(usage) -> dict:
    u = usage if isinstance(usage, dict) else {}
    out = {}
    for k, src in _KEYS:
        try:
            out[k] = max(0, int(u.get(src) or 0))
        except (TypeError, ValueError, OverflowError):
            out[k] = 0
    return out


def _new_turn(n: int, ev: dict) -> dict:
    text = ev.get("text") if isinstance(ev.get("text"), str) else ""
    return {"n": n, "at": _num(ev.get("at")), "prompt": text[:PROMPT_MAX], "source": str(ev.get("source") or ""),
            "kind": str(ev.get("kind") or ""), "state": "running", "duration_s": None, "cost_usd": None, "model": "",
            "tokens": {k: 0 for k, _ in _KEYS}, "model_calls": 0, "tool_calls": 0, "errors": 0, "steps_dropped": 0,
            "steps": [], "_calls": {}, "_tools": {}}


def _add_step(t: dict, step: dict) -> dict | None:
    if len(t["steps"]) >= STEPS_MAX:
        t["steps_dropped"] += 1
        return None
    t["steps"].append(step)
    return step


def _assistant(t: dict, ev: dict, at: float | None, detail: bool) -> None:
    msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
    sub = bool(ev.get("parent_tool_use_id"))
    mid = msg.get("id") if isinstance(msg.get("id"), str) else None
    call = t["_calls"].get(mid) if mid else None
    if call is None:
        model = msg.get("model") if isinstance(msg.get("model"), str) else ""
        tk = _tokens(msg.get("usage"))
        call = {"kind": "model", "at": at, "model": model, "tokens": tk, "sub": sub, "text_chars": 0, "thinking": False}
        if mid:
            t["_calls"][mid] = call
        t["model_calls"] += 1
        if not t.get("_reported"):
            for k in tk:
                t["tokens"][k] += tk[k]
        if model and not sub:
            t["model"] = model
        if detail:
            _add_step(t, call)
    else:                                                  # a later line of the same call: its usage only grows
        tk = _tokens(msg.get("usage"))
        if any(tk[k] > call["tokens"][k] for k in tk):
            for k in tk:
                grown = max(tk[k], call["tokens"][k])
                if not t.get("_reported"):
                    t["tokens"][k] += grown - call["tokens"][k]
                call["tokens"][k] = grown
    blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            call["text_chars"] += len(b["text"])
        elif b.get("type") == "thinking":
            call["thinking"] = True
        elif b.get("type") == "tool_use":
            t["tool_calls"] += 1
            name = b.get("name") if isinstance(b.get("name"), str) else "?"
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            try:
                summary = normalize.tool_summary(name, inp)
            except Exception:  # noqa: BLE001 - an odd input never breaks the trace
                summary = name
            step = {"kind": "tool", "at": at, "name": name[:TEXT_MAX], "summary": str(summary)[:TEXT_MAX], "sub": sub,
                    "duration_s": None, "error": False, "done": False}
            if isinstance(b.get("id"), str):
                t["_tools"][b["id"]] = step
            if detail:
                _add_step(t, step)


def _user(t: dict, ev: dict, at: float | None) -> None:
    msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
    for b in msg.get("content") if isinstance(msg.get("content"), list) else []:
        if not isinstance(b, dict) or b.get("type") != "tool_result":
            continue
        step = t["_tools"].pop(b.get("tool_use_id"), None) if isinstance(b.get("tool_use_id"), str) else None
        if step is None:
            continue
        step["done"] = True
        step["error"] = b.get("is_error") is True
        if step["error"]:
            t["errors"] += 1
        if at is not None and step["at"] is not None:
            step["duration_s"] = round(max(0.0, at - step["at"]), 3)


def _result(t: dict, ev: dict) -> None:
    cost = _num(ev.get("mx_turn_cost"))
    if cost is None:
        cost = _num(ev.get("total_cost_usd"))
    if cost is not None:
        t["cost_usd"] = round(cost, 6)
    if ev.get("is_error") is True:
        t["state"] = "failed"
    if isinstance(ev.get("usage"), dict):                  # what Settings -> Usage counts for this turn
        t["tokens"], t["_reported"] = _tokens(ev["usage"]), True
    ms = _num(ev.get("duration_ms"))
    if ms is not None:
        t["api"] = {"duration_s": round(ms / 1000, 3), "first_token_s": round(_num(ev.get("ttft_ms")) / 1000, 3)
                    if _num(ev.get("ttft_ms")) is not None else None, "model_turns": ev.get("num_turns")
                    if isinstance(ev.get("num_turns"), int) else None}


def _done(t: dict, ev: dict) -> None:
    end = _num(ev.get("at"))
    if end is not None and t["at"] is not None:
        t["duration_s"] = round(max(0.0, end - t["at"]), 3)
    code = ev.get("code")
    if ev.get("timed_out") is True:
        t["state"] = "timed_out"
    elif ev.get("stopped") is True:
        t["state"] = "stopped"
    elif t["state"] != "failed":
        t["state"] = "done" if code in (0, None) else "failed"
    t["code"] = code if isinstance(code, int) else None


def _close(t: dict, detail: bool) -> dict:
    t.pop("_calls")
    t.pop("_tools")
    # tokens: the turn's `result` line when it has one, else the sum of its model calls (a turn cut short)
    t["tokens_source"] = "result" if t.pop("_reported", False) else "calls"
    for st in t["steps"]:
        if st["kind"] == "model":                          # per call: what it read, never what it wrote (see above)
            tk = st.pop("tokens")
            st["context"] = tk["input"] + tk["cache_read"] + tk["cache_write"]
            st["cache_read"], st["cache_write"] = tk["cache_read"], tk["cache_write"]
    t["total_tokens"] = sum(t["tokens"].values())
    if not detail:
        t.pop("steps")
        t.pop("steps_dropped")
    return t


def _read(sid: str, want: int | None) -> list[dict]:
    """The turns of a log: every one without its steps (`want` None), or only turn `want` with them."""
    turns: list[dict] = []
    cur: dict | None = None
    n = 0
    try:
        f = open(store.log_path(sid), encoding="utf-8", errors="replace")
    except OSError:
        return []
    with f:
        for raw in f:
            if '"stream_event"' in raw[:40]:
                continue
            is_user = '"mx_user"' in raw[:64]
            if cur is None and not is_user:
                continue
            if want is not None and cur is not None and cur["n"] != want and not is_user:
                continue                                   # another turn: its lines are not parsed
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            kind = ev.get("type")
            if kind == "mx_user" and ev.get("injected") is True and cur is not None:
                # a message added to the running turn (runner._inject_step): part of that turn, not a new one
                if want is None or cur["n"] == want:
                    if want is not None:
                        text = ev.get("text") if isinstance(ev.get("text"), str) else ""
                        _add_step(cur, {"kind": "note", "at": _num(ev.get("at")), "level": "info",
                                        "text": f"message added: {text}"[:TEXT_MAX]})
                continue
            if kind == "mx_user":
                if cur is not None:                        # a turn without its mx_done (crash): closed as it is
                    if want is None or cur["n"] == want:
                        turns.append(_close(cur, want is not None))
                    if want is not None and cur["n"] == want:
                        return turns
                n += 1
                cur = _new_turn(n, ev)
                continue
            if cur is None or (want is not None and cur["n"] != want):
                continue
            detail = want is not None
            at = _num(ev.get("mx_at"))
            if kind == "assistant":
                _assistant(cur, ev, at, detail)
            elif kind == "user":
                _user(cur, ev, at)
            elif kind == "result":
                _result(cur, ev)
            elif kind == "mx_note" and detail:
                _add_step(cur, {"kind": "note", "at": _num(ev.get("at")), "level": str(ev.get("level") or "info"),
                                "text": str(ev.get("text") or "")[:TEXT_MAX]})
            elif kind == "mx_done":
                _done(cur, ev)
                if want is None or cur["n"] == want:
                    turns.append(_close(cur, detail))
                    if want is not None:
                        return turns
                cur = None
    if cur is not None and (want is None or cur["n"] == want):
        turns.append(_close(cur, want is not None))
    return turns


def turns(sid: str) -> list[dict]:
    """Every turn of the session, oldest first, without the steps."""
    return _read(sid, None)


def turn(sid: str, n: int) -> dict | None:
    """Turn `n` (1 = the first) with its steps; None when the session has no such turn."""
    found = _read(sid, n)
    return found[0] if found else None
