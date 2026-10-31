"""Smart resume (sessions/resume.py + runner._take): a return after a pause gets a summary written for its message."""
from __future__ import annotations

import json
import time

import pytest

from maxxing import config
from maxxing.sessions import resume, store

from conftest import all_events, wait_for, wait_idle

def _calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def _summaries(mx) -> list[dict]:
    return [c for c in _calls(mx) if "Summarize this conversation" in c["prompt"]]


def _session(client, topic, text="long work BIGCTX NOTOOL", away=2 * 3600) -> str:
    s = client.post("/api/sessions", json={"path": topic, "message": text, "title": "Blog redesign"}).json()
    assert wait_idle(client, s["id"])["turns"] == 1
    store.update(s["id"], finished_at=time.time() - away, base_tokens=20000)
    return s["id"]


def _notes(client, sid) -> list[str]:
    return [e["text"] for e in all_events(client, sid) if e["type"] == "note"]


def test_cache_expired_gets_a_targeted_summary(client, topic, mx):
    """Cache expired, 150k >= 100k: a summary written for the message runs first (below the idle 200k), then the
    message in the fresh thread."""
    sid = _session(client, topic)
    csid = store.read(sid)["csid"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "and the tests of the parser? NOTOOL"})
    m = wait_for(lambda: (lambda x: x if x["turns"] == 3 and x["state"] == "idle" else None)(
        client.get(f"/api/sessions/{sid}").json()), 30)
    assert m is not None
    assert any(n.startswith("Back after 2 h") and "150k tokens" in n and "for your message" in n
               for n in _notes(client, sid))
    [summary] = _summaries(mx)
    assert "For the next message" in summary["prompt"]
    assert summary["prompt"].rstrip().endswith("and the tests of the parser? NOTOOL")
    meta = store.read(sid)
    assert meta["csid"] != csid and meta["context_tokens"] < 60000
    assert _calls(mx)[-1]["prompt"].endswith("and the tests of the parser? NOTOOL")


def test_warm_cache_big_context_gets_a_summary(client, topic, mx):
    """Cache still warm (20 min) but 2x the threshold (250k >= 200k): summarized too."""
    sid = _session(client, topic, away=20 * 60)
    store.update(sid, context_tokens=250000)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "next NOTOOL"})
    wait_for(lambda: client.get(f"/api/sessions/{sid}").json()["turns"] == 3, 30)
    wait_idle(client, sid)
    assert len(_summaries(mx)) == 1
    assert any(n.startswith("Back after 20 min") for n in _notes(client, sid))


def test_off_falls_back_to_the_idle_rule(client, topic, mx):
    """Smart resume off: the idle rule alone, with the plain summary."""
    assert client.put("/api/claude/settings", json={"smart_resume_tokens": 0}).json() == {"ok": True}
    config.update_config(idle_compact_tokens=100000)
    sid = _session(client, topic)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "back NOTOOL"})
    wait_for(lambda: client.get(f"/api/sessions/{sid}").json()["turns"] == 3, 30)
    wait_idle(client, sid)
    [summary] = _summaries(mx)
    assert "For the next message" not in summary["prompt"]
    assert any("the cache had expired" in n for n in _notes(client, sid))


@pytest.mark.parametrize("case", ["short_pause", "small", "off", "warm_medium", "cron"])
def test_no_summary(client, topic, mx, case):
    away = 120 if case == "short_pause" else 2 * 3600
    if case == "warm_medium":
        away = 20 * 60                                            # cache still warm: 150k < 2 x 100k
    if case == "off":
        assert client.put("/api/claude/settings", json={"smart_resume_tokens": 0}).json() == {"ok": True}
    sid = _session(client, topic, "short NOTOOL" if case == "small" else "long work BIGCTX NOTOOL", away=away)
    if case == "cron":
        from maxxing.sessions import service
        service.send_message(sid, "cron run NOTOOL", source="cron")
    else:
        client.post(f"/api/sessions/{sid}/messages", json={"text": "back NOTOOL"})
    assert wait_idle(client, sid)["turns"] == 2
    assert not _summaries(mx)


def test_stop_during_the_summary_keeps_the_message(client, topic, mx):
    """A Stop cancels the summary only: the message then runs in the full thread."""
    sid = _session(client, topic)
    csid = store.read(sid)["csid"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "back SLOW NOTOOL"})
    wait_for(lambda: _summaries(mx), 10)
    client.post(f"/api/sessions/{sid}/stop")
    last = wait_for(lambda: (lambda c: c if "Summarize" not in c["prompt"] else None)(_calls(mx)[-1]), 15)
    assert last["prompt"].endswith("back SLOW NOTOOL") and len(_summaries(mx)) == 1
    client.post(f"/api/sessions/{sid}/stop")
    wait_idle(client, sid, 15)
    assert store.read(sid)["csid"] == csid                       # the full thread, not summarized


def test_settings(client):
    assert client.get("/api/claude/status").json()["smart_resume_tokens"] == 100000
    assert client.put("/api/claude/settings", json={"smart_resume_tokens": -1}).status_code == 422
    assert client.put("/api/claude/settings", json={"smart_resume_tokens": 3_000_000}).status_code == 422
    assert client.put("/api/claude/settings", json={"smart_resume_tokens": 40000}).json() == {"ok": True}
    assert config.load_config()["smart_resume_tokens"] == 40000


# ---- units -------------------------------------------------------------------------------------
def test_candidate_rule():
    cfg = {"smart_resume_tokens": 100000, "idle_compact_after_s": 3600}
    m = {"context_tokens": 120000, "finished_at": 1000.0, "fresh": False}
    user = {"kind": "user", "source": "web"}
    assert resume.candidate(m, user, cfg, 1000 + 7200) == (7200, 120000)
    assert resume.candidate(m, user, cfg, 1000 + 1200) is None                  # warm cache, < 2 x 100k
    assert resume.candidate({**m, "context_tokens": 210000}, user, cfg, 1000 + 1200) == (1200, 210000)
    assert resume.candidate({**m, "context_tokens": 210000}, user, cfg, 1000 + 200) is None   # < 5 min
    assert resume.candidate({**m, "context_tokens": 90000}, user, cfg, 9000) is None
    assert resume.candidate(m, user, {**cfg, "smart_resume_tokens": 0}, 9000) is None
    assert resume.candidate({**m, "context_tokens": 25000}, user, {**cfg, "smart_resume_tokens": 1000}, 9000)  # -> 20k
    assert resume.candidate({**m, "base_tokens": 80000}, user, cfg, 9000) is None   # mostly the fixed context
    for mm in ({**m, "fresh": True}, {**m, "cron": True}, {**m, "plan_ready": True}):
        assert resume.candidate(mm, user, cfg, 9000) is None
    for item in ({"kind": "seed", "source": "system"}, {"kind": "user", "source": "cron"},
                 {**user, "steer": True}, {**user, "plan_approved": True}, {**user, "held": True}):
        assert resume.candidate(m, item, cfg, 9000) is None
    assert resume.candidate({**m, "cache_at": 9000 - 100}, user, cfg, 9000) is None   # a side question warmed it


def test_summary_prompt():
    p = resume.summary_prompt("fix {that} file")
    assert p.endswith("The user's next message:\nfix {that} file") and "For the next message" in p
    long = resume.summary_prompt("a" * 5000 + "b" * 5000)
    assert " … " in long and long.endswith("b" * 100) and len(long) < len(resume.SUMMARY_PROMPT) + resume.MESSAGE_CHARS
    assert resume.summary_prompt("  ").endswith("(no text, only attachments)")
