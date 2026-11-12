"""Inject: a queued message is added to the turn that runs (Claude Code reads it at its next step) instead of
waiting for the whole task to end - nothing is interrupted, unlike a steer, and it never gets lost or sent twice."""
from __future__ import annotations

import json
import time

from conftest import all_events, wait_for, wait_idle

from maxxing.sessions import runner as runner_mod
from maxxing.sessions import service, store


def calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def _raw(sid: str) -> list[dict]:
    return [json.loads(x) for x in store.log_path(sid).read_text().splitlines() if x.strip()]


def _turn_started(sid: str) -> bool:
    m = store.read(sid) or {}
    return m.get("state") == "running" and bool(m.get("pid")) and "inject" in (m.get("runner_caps") or []) \
        and any(e.get("type") == "system" and e.get("subtype") == "init" for e in _raw(sid))


def _waiting(sid: str) -> bool:
    return "Waiting for a message." in store.log_path(sid).read_text()


def test_inject_adds_the_message_to_the_running_turn(client, topic, mx):
    sid = client.post("/api/sessions", json={"path": topic, "message": "WAITMSG long job NOTOOL"}).json()["id"]
    wait_for(lambda: _turn_started(sid) and _waiting(sid), 10)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "also check X", "client_id": "c-1"})
    client.post(f"/api/sessions/{sid}/messages", json={"text": "and Y"})
    r = client.post(f"/api/sessions/{sid}/inject").json()
    assert r["injected"] is True and r["reason"] is None
    s = wait_idle(client, sid, 20)
    assert s["state"] == "idle" and s["error"] is None and s["turns"] == 1          # ONE turn, nothing cut short
    assert s["queue"] == 0
    assert [x.get("continued", False) for x in calls(mx)] == [False, True]          # the same claude process
    assert calls(mx)[1]["prompt"] == "also check X\n\nand Y"                         # no steer preface
    evs = all_events(client, sid)
    users = [e for e in evs if e["type"] == "user"]
    assert [u["text"] for u in users] == ["WAITMSG long job NOTOOL", "also check X\n\nand Y"]
    assert users[1].get("injected") is True and users[1].get("client_ids") == ["c-1"]
    assert any("Read mid-turn: also check X" in e["text"] for e in evs if e["type"] == "assistant")
    assert not any(e["type"] == "note" and ("Interrupted" in e["text"] or "could not be added" in e["text"])
                   for e in evs)
    raw = [e["type"] for e in _raw(sid) if e["type"] in ("mx_user", "mx_done", "result")]
    assert raw == ["mx_user", "mx_user", "result", "mx_done"]
    # the turn's answer (Telegram, notifications) is the final one, after the added message
    m = store.read(sid) or {}
    final = [e["text"] for e in evs if e["type"] == "assistant"][-1]
    assert service.ended_turn_text(sid, m["last_turn"]["at"]) == final
    assert service.last_assistant_text(sid, turn_only=True) == final


def test_inject_as_the_turn_ends_is_answered_in_the_same_process(client, topic, mx):
    """Written while Claude writes its last answer (no further step): Claude Code answers it right after, in the
    same process - the runner reads on until it has, nothing is lost."""
    sid = client.post("/api/sessions", json={"path": topic, "message": "PAUSE short NOTOOL"}).json()["id"]
    wait_for(lambda: _turn_started(sid), 10)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "late one NOTOOL"})
    assert client.post(f"/api/sessions/{sid}/inject").json()["injected"] is True
    s = wait_idle(client, sid, 20)
    assert s["error"] is None and s["queue"] == 0
    assert [x["prompt"] for x in calls(mx)] == ["PAUSE short NOTOOL", "late one NOTOOL"]   # once each
    users = [e["text"] for e in all_events(client, sid) if e["type"] == "user"]
    assert users == ["PAUSE short NOTOOL", "late one NOTOOL"]
    assert len([e for e in _raw(sid) if e["type"] == "result"]) == 2


def test_inject_without_stream_input_runs_after_the_turn(client, topic, mx, monkeypatch):
    monkeypatch.setenv("MAXXING_STREAM_INPUT", "0")
    sid = client.post("/api/sessions", json={"path": topic, "message": "PAUSE short NOTOOL"}).json()["id"]
    wait_for(lambda: _turn_started(sid), 10)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "after NOTOOL"})
    assert client.post(f"/api/sessions/{sid}/inject").json()["injected"] is True
    s = wait_idle(client, sid, 20)
    assert s["error"] is None and s["turns"] == 2 and s["queue"] == 0
    assert [x.get("continued", False) for x in calls(mx)] == [False, False]
    evs = all_events(client, sid)
    assert [e["text"] for e in evs if e["type"] == "user"] == ["PAUSE short NOTOOL", "after NOTOOL"]
    assert not any(e.get("injected") for e in evs if e["type"] == "user")
    assert any(e["type"] == "note" and "could not be added" in e["text"] for e in evs)


def test_inject_keeps_telegram_refs_on_the_turn(client, topic, mx):
    sid = client.post("/api/sessions", json={"path": topic, "message": "WAITMSG job NOTOOL"}).json()["id"]
    wait_for(lambda: _turn_started(sid) and _waiting(sid), 10)
    service.send_message(sid, "from the phone", source="telegram", ref="tg-7")
    assert service.inject(sid)["injected"] is True
    wait_for(lambda: not (store.read(sid) or {}).get("queue"), 10)
    assert "tg-7" in service.live_refs(sid)                                         # still to answer: this turn
    wait_idle(client, sid, 20)
    assert (store.read(sid) or {})["last_turn"]["refs"] == ["tg-7"]                 # answered by it


def test_inject_refusals(client, topic, mx):
    sid = client.post("/api/sessions", json={"path": topic, "message": "NOTOOL quick"}).json()["id"]
    wait_idle(client, sid, 10)
    assert client.post(f"/api/sessions/{sid}/inject").json() | {"session": None} == \
        {"injected": False, "reason": "idle", "session": None}
    sid = client.post("/api/sessions", json={"path": topic, "message": "SLOW job"}).json()["id"]
    wait_for(lambda: _turn_started(sid), 10)
    assert service.inject(sid)["reason"] == "idle"                                   # nothing queued
    client.post(f"/api/sessions/{sid}/messages", json={"text": "next NOTOOL"})
    with store.edit(sid) as m:                                                       # a runner from before inject
        caps, m["runner_caps"] = m["runner_caps"], ["steer"]
    assert service.inject(sid)["reason"] == "unsupported"
    with store.edit(sid) as m:
        m["runner_caps"] = caps
        m["queue"][0]["voice"] = [{"id": "v1", "path": "/x.ogg"}]
    assert service.inject(sid)["reason"] == "voice"
    with store.edit(sid) as m:
        m["queue"][0].pop("voice")
        m["queue"][0]["plan_approved"] = True
    assert service.inject(sid)["reason"] == "plan"
    assert not any(x.get("inject") for x in (store.read(sid) or {})["queue"])        # the queue is unchanged
    client.post(f"/api/sessions/{sid}/stop")


def test_an_inject_that_missed_its_turn_runs_as_a_normal_message():
    r = runner_mod.Runner("x" * 12)
    m = {"queue": [{"text": "hi", "attachments": [], "source": "web", "kind": "user", "inject": "oldturn"}]}
    item = r._take(m, m["queue"], {}, time.time())
    assert item["text"] == "hi" and "inject" not in item and r.turn_id != "oldturn"


def test_ended_turn_ignores_injected_messages():
    evs = [{"type": "user", "at": 1.0}, {"type": "assistant", "text": "a"},
           {"type": "user", "at": 2.0, "injected": True}, {"type": "assistant", "text": "b"},
           {"type": "result"}, {"type": "user", "at": 3.0}]
    assert service._ended_turn(evs, 1.0, False) == (1, 5)
