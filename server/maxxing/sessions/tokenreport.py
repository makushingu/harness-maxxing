"""Where the tokens of Claude sessions go - read from Claude Code's own transcripts (~/.claude/projects/*/*.jsonl).

`maxxing sessions token-report` prints it: context size per call, re-read share, cache rewrites (after an idle
hour, a model switch...), the tools whose results fill the context, and what automatic compaction at other
thresholds would have saved on the same calls (a simulation: growth between calls is replayed, a compaction
brings the context back to SUMMARY_TOKENS).
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from pathlib import Path

USAGE = re.compile(rb'"usage":\{"input_tokens":(\d+),"cache_creation_input_tokens":(\d+),'
                   rb'"cache_read_input_tokens":(\d+),"output_tokens":(\d+)')
MSG_ID = re.compile(rb'"id":"(msg_[A-Za-z0-9]+)"')
STAMP = re.compile(rb'"timestamp":"([^"]+)"')
MODEL = re.compile(rb'"model":"([^"]+)"')
BUCKETS = (100_000, 200_000, 400_000, 600_000)
REWRITE_MIN = 30_000            # cache written after the first call above this = the history was re-sent uncached
IDLE_S = 3600                   # the 1-hour prompt cache expired
SUMMARY_TOKENS = 45_000
IMAGE_CHARS = 6_000             # an image counts ~1 500 tokens in the context, whatever its base64 size         # context right after a compaction (prefix + summary), for the simulation


def _ts(line: bytes) -> float | None:
    m = STAMP.search(line)
    if not m:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(m.group(1).decode().replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_calls(path: Path) -> tuple[list[dict], dict[str, int]]:
    """One transcript -> (API calls in order, characters of tool results per tool name)."""
    calls: list[dict] = []
    tools: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    seen: set[bytes] = set()
    new_turn = True
    try:
        fh = open(path, "rb")
    except OSError:
        return [], {}
    with fh:
        for line in fh:
            if b'"role":"user"' in line:
                if b'"tool_result"' in line:
                    try:
                        content = json.loads(line).get("message", {}).get("content") or []
                    except ValueError:
                        content = []
                    for b in content if isinstance(content, list) else []:
                        if isinstance(b, dict) and b.get("type") == "tool_result":
                            c = b.get("content")
                            parts = c if isinstance(c, list) else [{"type": "text", "text": c or ""}]
                            for part in parts:
                                if not isinstance(part, dict):
                                    continue
                                if part.get("type") == "image":
                                    tools["(images)"] += IMAGE_CHARS
                                else:
                                    tools[names.get(b.get("tool_use_id") or "", "?")] += len(str(part.get("text") or ""))
                elif b'"isMeta":true' not in line:
                    new_turn = True
                continue
            m = USAGE.search(line)
            if not m or b"<synthetic>" in line:
                continue
            if b'"tool_use"' in line:
                for tid, name in re.findall(rb'"type":"tool_use","id":"([^"]+)","name":"([^"]+)"', line):
                    names[tid.decode()] = name.decode()
            mid = MSG_ID.search(line)
            key = mid.group(1) if mid else None
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            i, cw, cr, out = map(int, m.groups())
            mm = MODEL.search(line)
            calls.append({"ctx": i + cw + cr, "write": cw, "read": cr, "out": out, "turn": new_turn,
                          "at": _ts(line), "model": mm.group(1).decode() if mm else ""})
            new_turn = False
    return calls, dict(tools)


def simulate(sessions: list[list[dict]], threshold: int, inside_turns: bool) -> int:
    """Context tokens re-read by all calls if sessions were compacted at `threshold` (between turns, or also
    inside a turn). Growth between calls is replayed; a big drop in the real data (a real compaction) is kept."""
    total = 0
    for calls in sessions:
        prev, cur = None, 0
        for c in calls:
            if prev is None:
                cur = c["ctx"]
            elif c["ctx"] < prev * 0.6:
                cur = min(cur, c["ctx"])
            else:
                cur += max(0, c["ctx"] - prev)
            prev = c["ctx"]
            if threshold and cur > threshold and (c["turn"] or inside_turns):
                total += cur                      # the summary call reads everything once more
                cur = SUMMARY_TOKENS
            total += cur
    return total


def report(root: Path, days: float | None = None) -> dict:
    since = time.time() - days * 86400 if days else 0
    sessions: list[list[dict]] = []
    tools: dict[str, int] = defaultdict(int)
    for f in sorted(root.glob("*/*.jsonl")):
        try:
            if f.stat().st_mtime < since:
                continue
        except OSError:
            continue
        calls, t = read_calls(f)
        if since:
            calls = [c for c in calls if (c["at"] or since) >= since]
        if calls:
            sessions.append(calls)
        for k, v in t.items():
            tools[k] += v
    flat = [c for s in sessions for c in s]
    reads = sum(c["ctx"] for c in flat) or 1
    edges = (0,) + BUCKETS + (10**12,)
    buckets = []
    for lo, hi in zip(edges, edges[1:]):
        sel = [c for c in flat if lo <= c["ctx"] < hi]
        buckets.append({"from": lo, "to": hi if hi < 10**12 else None, "calls": len(sel),
                        "context_share": round(sum(c["ctx"] for c in sel) / reads, 3)})
    rewrites = {"idle": [0, 0], "model": [0, 0], "other": [0, 0]}
    for s in sessions:
        for prev, c in zip(s, s[1:]):
            if c["write"] < REWRITE_MIN:
                continue
            why = ("idle" if prev["at"] and c["at"] and c["at"] - prev["at"] > IDLE_S
                   else "model" if prev["model"] and c["model"] and prev["model"] != c["model"] else "other")
            rewrites[why][0] += 1
            rewrites[why][1] += c["write"]
    base = simulate(sessions, 0, False)
    sims = []
    for threshold, inside in ((400_000, False), (400_000, True), (300_000, True), (250_000, True), (200_000, True)):
        t = simulate(sessions, threshold, inside)
        sims.append({"threshold": threshold, "inside_turns": inside, "context_tokens": t,
                     "vs_no_compaction": round(t / base - 1, 3) if base else 0.0})
    return {"sessions": len(sessions), "calls": len(flat),
            "tokens": {"context_read": sum(c["read"] for c in flat), "cache_written": sum(c["write"] for c in flat),
                       "output": sum(c["out"] for c in flat)},
            "first_call_median": _median([s[0]["ctx"] for s in sessions]),
            "buckets": buckets,
            "cache_rewrites": {k: {"count": n, "tokens": t} for k, (n, t) in rewrites.items()},
            "tool_results": dict(sorted(tools.items(), key=lambda kv: -kv[1])[:8]),
            "compaction": sims}


def _median(values: list[int]) -> int:
    v = sorted(values)
    return v[len(v) // 2] if v else 0


def render(r: dict) -> str:
    k = lambda n: f"{n / 1000:,.0f}k" if n < 1e6 else f"{n / 1e6:,.1f}M"       # noqa: E731
    out = [f"{r['sessions']} sessions, {r['calls']} calls · context re-read {k(r['tokens']['context_read'])}, "
           f"cache written {k(r['tokens']['cache_written'])}, output {k(r['tokens']['output'])}",
           f"first call of a session (fixed prefix): median {k(r['first_call_median'])}", "",
           "context per call            calls   share of re-read tokens"]
    for b in r["buckets"]:
        rng = f"{k(b['from'])}-{k(b['to'])}" if b["to"] else f"{k(b['from'])}+"
        out.append(f"  {rng:24} {b['calls']:7}   {b['context_share'] * 100:5.1f} %")
    out += ["", "cache rewritten mid-session"]
    for why, label in (("idle", "after more than 1 h idle"), ("model", "after a model switch"), ("other", "other")):
        x = r["cache_rewrites"][why]
        out.append(f"  {label:26} {x['count']:5}   {k(x['tokens'])} tokens")
    out += ["", "tool results (characters kept in the context)"]
    out += [f"  {name:26} {k(n)}" for name, n in r["tool_results"].items()]
    out += ["", "automatic compaction, simulated on these calls (context tokens vs no compaction)"]
    for s in r["compaction"]:
        where = "between and inside turns" if s["inside_turns"] else "between turns"
        out.append(f"  {k(s['threshold']):>5} {where:26} {s['vs_no_compaction'] * 100:+6.1f} %")
    return "\n".join(out)
