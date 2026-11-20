"""Compaction in agents: the owner's conversation (and a member's session in a group) is summarized like any
session from its first turn on; a run (cron, webhook, `agents run`) is one turn and is never summarized by Harness
(store.unattended, runner._auto_compact / _idle_compact, resume.candidate)."""
from __future__ import annotations

from conftest import wait_for, wait_idle
from test_agents import A, _calls, _create, _on
from maxxing import agents, config
from maxxing.sessions import resume, store
from maxxing.sessions.runner import _idle_compact


def _turns(client, sid: str, n: int) -> dict | None:
    return wait_for(lambda: (lambda x: x if x["turns"] == n and x["state"] == "idle" else None)(
        client.get(f"/api/sessions/{sid}").json()), 30)


def test_the_owners_conversation_is_compacted_from_its_first_turn(client, topic, mx):
    _on(client)
    _create(client)
    config.update_config(auto_compact_tokens=100000)
    r = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL long work BIGCTX"})
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["id"]
    assert _turns(client, sid, 2) is not None    # the turn, the summary turn
    client.post(f"/api/sessions/{sid}/messages", json={"text": "NOTOOL go on"})
    m = _turns(client, sid, 3)                   # the next message starts the fresh thread with the summary
    assert m is not None
    meta = store.read(sid)
    assert meta["csid"] != sid and agents.manager_turn(meta)
    # the fresh thread is still the manager's: its note goes with every turn, the summary turn's too
    argvs = [c["argv"] for c in _calls()[-2:]]
    assert all("manager of this agent" in a[a.index("--append-system-prompt") + 1] for a in argvs)
    assert "Summarize this conversation" in _calls()[-2]["prompt"]
    assert _calls()[-1]["prompt"].startswith("Context of this session")


def test_a_run_is_never_compacted(client, topic, mx):
    _on(client)
    _create(client)
    config.update_config(auto_compact_tokens=100000)
    run = agents.fire(A, trigger="cron:c_1", prompt="NOTOOL routine BIGCTX", source="cron")
    m = wait_idle(client, run["session"]["id"])
    assert m["turns"] == 1
    assert not any("Summarize this conversation" in c["prompt"] for c in _calls())


def test_unattended_sessions():
    run = {"cron": True, "source": "agent", "env": {"MAXXING_AGENT": A, "MAXXING_AGENT_TRIGGER": "cron:c_1"}}
    chat = {**run, "env": {"MAXXING_AGENT": A, "MAXXING_AGENT_CHAT": "1"}}
    group = {**run, "env": {"MAXXING_AGENT": A, "MAXXING_AGENT_GROUP": "projects/acme/groups/team"}}
    assert store.unattended({"cron": True}) and store.unattended(run)
    assert not store.unattended(chat) and not store.unattended(group)
    assert not store.unattended({}) and not store.unattended({**chat, "cron": False})
    assert store.unattended({"cron": True, "env": "bad"})          # a hand-edited meta: as before


def test_idle_rules_follow_the_conversation_not_the_flag():
    cfg = {"idle_compact_tokens": 5000, "idle_compact_after_s": 3600, "smart_resume_tokens": 20000}
    base = {"context_tokens": 25000, "finished_at": 1000.0, "fresh": False}
    user = {"kind": "user", "source": "agent", "text": "back"}
    chat = {**base, "cron": True, "env": {"MAXXING_AGENT_CHAT": "1"}}
    run = {**base, "cron": True, "env": {"MAXXING_AGENT_TRIGGER": "cron:c_1"}}
    assert _idle_compact(chat, user, cfg, 9000) == ("2 h", 25)
    assert _idle_compact(run, user, cfg, 9000) is None
    assert resume.candidate(chat, user, cfg, 9000) is not None
    assert resume.candidate(run, user, cfg, 9000) is None



def test_a_summary_is_never_posted_as_the_agents_answer(client, topic, mx):
    """The summary turn is Harness's own turn: costed, never a result in the flow (nor on Telegram, nor in a
    group) - like Telegram's own sessions (gateway: compact / handoff / seed)."""
    _on(client)
    _create(client)
    config.update_config(auto_compact_tokens=100000)
    r = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL PAUSE long work BIGCTX"})
    sid = r.json()["session"]["id"]
    assert _turns(client, sid, 2) is not None
    r = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL and now?"})
    assert r.json()["session"]["id"] == sid                    # the same conversation goes on
    assert _turns(client, sid, 3) is not None
    results = wait_for(lambda: (lambda x: x if len(x) == 2 else None)(
        [m for m in agents.thread(A, 50) if m.get("kind") == "result"]), 10)
    assert results is not None, [m.get("text") for m in agents.thread(A, 50)]
    # (the fake echoes the first line of its prompt: the second message carries the summary into the fresh thread)
    assert [m["text"] for m in results] == ["Echo: NOTOOL PAUSE long work BIGCTX",
                                            "Echo: Context of this session before compaction (automatic summary):"]
    assert _calls()[-1]["prompt"].endswith("NOTOOL and now?")
    # the summary still counts in the day's spending (the sessions' own costs, not the flow)
    assert agents.day_cost(A) > sum(float(m.get("cost") or 0) for m in results)
