"""Smart resume (sessions/resume.py + runner._pop): a return after a pause is sorted by a small classifier call."""
from __future__ import annotations

import json
import time

import pytest

from maxxing import config
from maxxing.sessions import resume, store

from conftest import all_events, wait_for, wait_idle

MARK = "triage a returning user"


def _calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def _classifier_calls(mx) -> list[dict]:
    return [c for c in _calls(mx) if any(MARK in a for a in c["argv"])]


def _summaries(mx) -> list[dict]:
    return [c for c in _calls(mx) if "Summarize this conversation" in c["prompt"]]


def _session(client, topic, text="long work BIGCTX NOTOOL", away=2 * 3600) -> str:
    s = client.post("/api/sessions", json={"path": topic, "message": text, "title": "Blog redesign"}).json()
    assert wait_idle(client, s["id"])["turns"] == 1
    store.update(s["id"], finished_at=time.time() - away, base_tokens=20000)
    return s["id"]


def _notes(client, sid) -> list[str]:
    return [e["text"] for e in all_events(client, sid) if e["type"] == "note"]


def test_new_subject_compacts_first(client, topic, mx, monkeypatch):
    """NEW: the summary runs first even below the idle threshold (150k < 200k), with its own note."""
    monkeypatch.setenv("FAKE_CLAUDE_RESUME", "NEW")
    sid = _session(client, topic)
    csid = store.read(sid)["csid"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "something else entirely NOTOOL"})
    m = wait_for(lambda: (lambda x: x if x["turns"] == 3 and x["state"] == "idle" else None)(
        client.get(f"/api/sessions/{sid}").json()), 30)
    assert m is not None
    assert any(n.startswith("New subject after 2 h") and "150k tokens" in n for n in _notes(client, sid))
    assert len(_summaries(mx)) == 1
    call = _classifier_calls(mx)[0]
    for flag in ("--tools", "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
        assert flag in call["argv"]
    assert call["argv"][call["argv"].index("--model") + 1] == resume.MODEL
    assert "Session title: Blog redesign" in call["prompt"]
    assert "[User] long work BIGCTX NOTOOL" in call["prompt"] and "[Assistant] Echo:" in call["prompt"]
    assert call["prompt"].rstrip().endswith("Answer CONTINUE or NEW.") and "something else entirely" in call["prompt"]
    assert call["cwd"].endswith("claude-resume")
    meta = store.read(sid)
    assert meta["csid"] != csid and meta["context_tokens"] < 60000
    assert _calls(mx)[-1]["prompt"].endswith("something else entirely NOTOOL")


def test_follow_up_continues_without_summary(client, topic, mx, monkeypatch):
    """CONTINUE: no summary even though the idle rule (100k) would have compacted, and no note."""
    monkeypatch.setenv("FAKE_CLAUDE_RESUME", "CONTINUE")
    config.update_config(idle_compact_tokens=100000)
    sid = _session(client, topic)
    csid = store.read(sid)["csid"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "ok fix that error NOTOOL"})
    assert wait_idle(client, sid)["turns"] == 2
    assert len(_classifier_calls(mx)) == 1 and not _summaries(mx)
    assert not any("summarized" in n for n in _notes(client, sid))
    assert store.read(sid)["csid"] == csid


def test_classifier_failure_falls_back_to_the_idle_rule(client, topic, mx, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_RESUME", "FAIL")
    config.update_config(idle_compact_tokens=100000)
    sid = _session(client, topic)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "back NOTOOL"})
    m = wait_for(lambda: (lambda x: x if x["turns"] == 3 and x["state"] == "idle" else None)(
        client.get(f"/api/sessions/{sid}").json()), 30)
    assert m is not None and len(_classifier_calls(mx)) == 1 and len(_summaries(mx)) == 1
    assert any(n.startswith("Back after 2 h") for n in _notes(client, sid))


def test_classifier_failure_below_the_idle_threshold_just_resumes(client, topic, mx, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_RESUME", "FAIL")              # idle rule at its default 200k > 150k
    sid = _session(client, topic)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "back NOTOOL"})
    assert wait_idle(client, sid)["turns"] == 2
    assert len(_classifier_calls(mx)) == 1 and not _summaries(mx)


@pytest.mark.parametrize("case", ["short_pause", "small", "off", "warm_medium", "cron"])
def test_no_classifier_call(client, topic, mx, monkeypatch, case):
    monkeypatch.setenv("FAKE_CLAUDE_RESUME", "NEW")
    away = 120 if case == "short_pause" else 2 * 3600
    if case == "warm_medium":
        away = 20 * 60                                            # cache still warm: only 100k+ is asked
    if case == "off":
        assert client.put("/api/claude/settings", json={"smart_resume_tokens": 0}).json() == {"ok": True}
    sid = _session(client, topic, "short NOTOOL" if case == "small" else "long work BIGCTX NOTOOL", away=away)
    if case == "warm_medium":
        store.update(sid, context_tokens=80000)
    if case == "cron":
        from maxxing.sessions import service
        service.send_message(sid, "cron run NOTOOL", source="cron")
    else:
        client.post(f"/api/sessions/{sid}/messages", json={"text": "back NOTOOL"})
    assert wait_idle(client, sid)["turns"] == 2
    assert not _classifier_calls(mx) and not _summaries(mx)


def test_warm_cache_big_context_is_asked(client, topic, mx, monkeypatch):
    """Cache still warm (20 min) but 100k+ of context: worth asking; NEW compacts."""
    monkeypatch.setenv("FAKE_CLAUDE_RESUME", "NEW")
    sid = _session(client, topic, away=20 * 60)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "new topic NOTOOL"})
    wait_for(lambda: client.get(f"/api/sessions/{sid}").json()["turns"] == 3, 30)
    wait_idle(client, sid)
    assert len(_classifier_calls(mx)) == 1 and len(_summaries(mx)) == 1
    assert any(n.startswith("New subject after 20 min") for n in _notes(client, sid))


def test_stop_during_the_classifier_call(client, topic, mx, monkeypatch):
    """The call runs outside the session lock: a Stop meanwhile clears the queue, the call is cut short and the
    session goes idle at once, with no summary and no turn."""
    monkeypatch.setenv("FAKE_CLAUDE_RESUME", "SLOW")
    sid = _session(client, topic)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "back NOTOOL"})
    wait_for(lambda: _classifier_calls(mx), 10)
    assert client.get(f"/api/sessions/{sid}").json()["queue"] == 0       # shown as being sent, not waiting
    t0 = time.time()
    client.post(f"/api/sessions/{sid}/stop")
    m = wait_idle(client, sid, 10)
    assert time.time() - t0 < 5 and m["turns"] == 1
    assert not _summaries(mx) and not store.read(sid).get("queue")


def test_message_sent_during_the_classifier_call_runs_after(client, topic, mx, monkeypatch):
    """A message queued while the call runs (no lock held) is not lost: it runs after the first one."""
    monkeypatch.setenv("FAKE_CLAUDE_RESUME", "SLOW")
    config.update_config(idle_compact_tokens=0)
    sid = _session(client, topic)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "first NOTOOL"})
    wait_for(lambda: _classifier_calls(mx), 10)
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "second NOTOOL"}).json()
    assert r["queued"] is True                                           # the runner is alive: no second runner
    client.post(f"/api/sessions/{sid}/stop")                            # cut the slow call (drops both)
    wait_idle(client, sid, 10)
    monkeypatch.setenv("FAKE_CLAUDE_RESUME", "CONTINUE")
    store.update(sid, finished_at=time.time() - 2 * 3600)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "third NOTOOL"})
    assert wait_idle(client, sid)["turns"] == 2
    assert _calls(mx)[-1]["prompt"].endswith("third NOTOOL")


def test_settings(client):
    assert client.get("/api/claude/status").json()["smart_resume_tokens"] == 60000
    assert client.put("/api/claude/settings", json={"smart_resume_tokens": -1}).status_code == 422
    assert client.put("/api/claude/settings", json={"smart_resume_tokens": 3_000_000}).status_code == 422
    assert client.put("/api/claude/settings", json={"smart_resume_tokens": 40000}).json() == {"ok": True}
    assert config.load_config()["smart_resume_tokens"] == 40000


# ---- units -------------------------------------------------------------------------------------
def test_parse():
    for a, v in [("CONTINUE", "CONTINUE"), ("new", "NEW"), ("NEW.", "NEW"), ("**CONTINUE**", "CONTINUE"),
                 ("Answer: NEW", "NEW"), ("CONTINUE - it refers to the file", "CONTINUE"),
                 ("", None), ("maybe", None), ("NEW or CONTINUE", None), ("NEWS", None)]:
        assert resume.parse(a) == v, a


def test_candidate_rule():
    cfg = {"smart_resume_tokens": 60000, "idle_compact_after_s": 3600}
    m = {"context_tokens": 80000, "finished_at": 1000.0, "fresh": False}
    user = {"kind": "user", "source": "web"}
    assert resume.candidate(m, user, cfg, 1000 + 7200) == (7200, 80000)
    assert resume.candidate(m, user, cfg, 1000 + 1200) is None                  # warm cache, < 100k
    assert resume.candidate({**m, "context_tokens": 120000}, user, cfg, 1000 + 1200) == (1200, 120000)
    assert resume.candidate({**m, "context_tokens": 120000}, user, cfg, 1000 + 200) is None   # < 5 min
    assert resume.candidate({**m, "context_tokens": 50000}, user, cfg, 9000) is None
    assert resume.candidate(m, user, {**cfg, "smart_resume_tokens": 0}, 9000) is None
    assert resume.candidate({**m, "context_tokens": 25000}, user, {**cfg, "smart_resume_tokens": 1000}, 9000)  # -> 20k
    assert resume.candidate({**m, "base_tokens": 60000}, user, cfg, 9000) is None   # mostly the fixed context
    for mm in ({**m, "fresh": True}, {**m, "cron": True}, {**m, "plan_ready": True}):
        assert resume.candidate(mm, user, cfg, 9000) is None
    for item in ({"kind": "seed", "source": "system"}, {"kind": "user", "source": "cron"},
                 {**user, "steer": True}, {**user, "plan_approved": True}, {**user, "held": True}):
        assert resume.candidate(m, item, cfg, 9000) is None
    assert resume.candidate({**m, "cache_at": 9000 - 100}, user, cfg, 9000) is None   # a side question warmed it


def test_exchanges_and_conversation(mx):
    m = store.create(store.new_meta(str(mx["ws"]), "T"))
    sid = m["id"]
    def turn(user, answer, kind="user", source="web"):
        store.append_log(sid, {"type": "mx_user", "text": user, "kind": kind, "source": source, "at": 1})
        store.append_log(sid, {"type": "assistant", "message": {"content": [{"type": "text", "text": "partial"}]}})
        store.append_log(sid, {"type": "result", "result": answer})
    turn("one", "a1")
    turn("Summarize", "the summary", kind="compact", source="system")
    turn("two", "a2")
    turn("three " + "x" * 5000, "a3 " + "y" * 9000)
    turn("four", "a4")
    pairs = resume.exchanges(sid)
    assert [p[0][:5] for p in pairs] == ["two", "three", "four"] and pairs[-1][1] == "a4"
    text = resume.conversation(pairs)
    assert len(text) <= resume.CONVERSATION_CHARS and text.endswith("[User] four\n[Assistant] a4")
    assert "[User] two" in text and " … " in text
    assert resume.exchanges("00000000-0000-4000-8000-000000000000") == [] and resume.exchanges("bad") == []
