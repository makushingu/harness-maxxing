"""`maxxing sessions token-report`: reads Claude Code transcripts (synthetic ones here)."""
from __future__ import annotations

import json

from maxxing.sessions import tokenreport


def _assistant(mid, ctx_read, write, out=100, at="2026-10-16T10:00:00Z", model="claude-opus-5-5", tool=None):
    content = [{"type": "tool_use", "id": tool[0], "name": tool[1], "input": {}}] if tool else []
    return {"type": "assistant", "timestamp": at, "message": {
        "id": mid, "model": model, "role": "assistant", "content": content,
        "usage": {"input_tokens": 1, "cache_creation_input_tokens": write, "cache_read_input_tokens": ctx_read,
                  "output_tokens": out}}}


def _user(text=None, result=None):
    if result:
        return {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": result[0], "content": result[1]}]}}
    return {"type": "user", "message": {"role": "user", "content": text}}


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n")


def test_report_buckets_rewrites_tools_and_simulation(tmp_path):
    rows = [_user("hello"), _assistant("msg_1", 0, 30_000, tool=("t1", "Bash")),
            _user(result=("t1", "x" * 5000)), _assistant("msg_2", 30_000, 450_000),
            _assistant("msg_2", 30_000, 450_000),                                       # streamed twice: counted once
            _user("next"), _assistant("msg_3", 480_000, 1000, at="2026-10-16T10:05:00Z"),
            _user("later"), _assistant("msg_4", 0, 481_000, at="2026-10-16T12:00:00Z"),  # idle > 1 h: rewritten
            _user(result=("t9", [{"type": "image", "source": {"data": "A" * 99999}}]))]
    _write(tmp_path / "proj" / "s1.jsonl", rows)
    r = tokenreport.report(tmp_path)
    assert r["sessions"] == 1 and r["calls"] == 4
    assert r["cache_rewrites"]["idle"]["count"] == 1 and r["cache_rewrites"]["idle"]["tokens"] == 481_000
    assert r["tool_results"]["Bash"] == 5000 and r["tool_results"]["(images)"] == tokenreport.IMAGE_CHARS
    assert sum(b["calls"] for b in r["buckets"]) == 4 and r["first_call_median"] == 30_001
    sims = {(s["threshold"], s["inside_turns"]): s["vs_no_compaction"] for s in r["compaction"]}
    assert sims[(400_000, True)] <= sims[(400_000, False)] <= 0
    text = tokenreport.render(r)
    assert "cache rewritten mid-session" in text and "between and inside turns" in text
