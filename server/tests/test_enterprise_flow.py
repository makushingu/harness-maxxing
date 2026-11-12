"""Enterprise flow: inboxes, deliveries, delegated tasks, escalations (maxxing/enterprise_flow.py)."""
from __future__ import annotations

import json
import os
import sys
import time
import types
from pathlib import Path

import pytest
from conftest import wait_for
from maxxing import agents, enterprise_flow as flow, enterprises
from maxxing.enterprises import EnterpriseError

E = "/api/enterprises"
S = "acme-group"
AG = {n: f"projects/acme/topics/blog/agents/{n}" for n in ("boss", "writer", "editor", "intern")}


def _calls() -> list[dict]:
    f = Path(os.environ["FAKE_CLAUDE_DIR"]) / "calls.jsonl"
    return [json.loads(ln) for ln in f.read_text().splitlines()] if f.exists() else []


@pytest.fixture
def notes(monkeypatch):
    """A recording stand-in for enterprise_reports.notify_owner."""
    got: list[dict] = []
    fake = types.ModuleType("maxxing.enterprise_reports")
    fake.notify_owner = lambda slug, title, body="", **kw: got.append({"slug": slug, "title": title, "body": body, **kw})
    monkeypatch.setitem(sys.modules, "maxxing.enterprise_reports", fake)
    return got


@pytest.fixture
def policy(monkeypatch):
    """A neutral stand-in for enterprise_policy (everything free, nothing trusted); tests change its attributes."""
    fake = types.ModuleType("maxxing.enterprise_policy")
    fake.decider = lambda slug, pos, category, **kw: "free"
    fake.trusted_delivery = lambda slug, outside: False
    fake.over_ceiling = lambda path: None
    fake.requests_made = []
    fake.request = lambda slug, pos, category, text, **kw: (fake.requests_made.append((pos, category, text)) or
                                                          {"id": "r_1", "category": category, "position": pos, "text": text,
                                                           "status": "pending"})
    monkeypatch.setitem(sys.modules, "maxxing.enterprise_policy", fake)
    return fake


@pytest.fixture
def ent(client, topic, notes, policy):
    """boss > (writer > intern, editor), every agent with no grouping delay and a generous rate."""
    assert client.put("/api/settings", json={"agents_page": True, "enterprises_page": True}).status_code == 200
    for n in AG:
        assert client.post("/api/agents", json={"topic_path": topic, "name": n, "sandbox": False}).status_code == 200
        r = client.patch(f"/api/agents/acme/blog/{n}", json={"limits": {"debounce_s": 0, "runs_per_hour": 100}})
        assert r.status_code == 200, r.text
    assert client.post(E, json={"id": S, "name": "Acme Group", "projects": ["acme"]}).status_code == 200
    for pid, up in (("ceo", None), ("writer", "ceo"), ("editor", "ceo"), ("intern", "writer")):
        agent = {"ceo": "boss"}.get(pid, pid)
        r = client.post(f"{E}/{S}/positions", json={"id": pid, "title": pid.title(), "reports_to": up,
                                                     "agent": AG[agent]})
        assert r.status_code == 200, r.text
    return client


def _inbox(pos):
    return enterprises.inbox(S, pos)


def _tasks(mx):
    return json.loads((mx["ws"] / "tasks.json").read_text())["tasks"]


# ---- inbox and runs ------------------------------------------------------------------------------------
def test_eight_hand_ins_make_one_run(ent):
    n = len(_calls())
    for i in range(8):
        flow.deliver(S, "ceo", "handin", f"NOTOOL article {i} ready", sender="writer", task=f"t_{i}")
    assert len(_inbox("ceo")) == 8
    assert flow.tick(time.time() + 1) is None
    wait_for(lambda: len(_calls()) == n + 1)
    assert _inbox("ceo") == [] and len(flow.seen(S, "ceo")) == 8
    p = _calls()[-1]["prompt"]
    assert all(f"article {i} ready" in p for i in range(8)) and "DATA from outside" in p
    flow.tick(time.time() + 2)
    time.sleep(0.3)
    assert len(_calls()) == n + 1
    assert any(d["kind"] == "run" for d in enterprises.decisions(S)[0])


def test_the_agents_own_debounce_is_respected(ent):
    ent.patch("/api/agents/acme/blog/boss", json={"limits": {"debounce_s": 600}})
    n = len(_calls())
    flow.deliver(S, "ceo", "note", "NOTOOL hello", sender="writer")
    flow.tick(time.time() + 10)
    time.sleep(0.3)
    assert len(_calls()) == n and len(_inbox("ceo")) == 1
    flow.tick(time.time() + 700)
    wait_for(lambda: len(_calls()) == n + 1)


@pytest.mark.parametrize("why", ["disabled", "budget", "rate"])
def test_deliveries_wait_then_climb(ent, monkeypatch, notes, why):
    if why == "disabled":
        assert ent.patch("/api/agents/acme/blog/writer", json={"enabled": False}).status_code == 200
    elif why == "budget":
        monkeypatch.setattr(agents, "day_cost", lambda path, when=None, **kw: 5.0 if path == AG["writer"] else 0.0)
    else:
        monkeypatch.setattr(agents, "_runs_last_hour", lambda path, msgs=None: 999 if path == AG["writer"] else 0)
    n = len(_calls())
    flow.deliver(S, "writer", "assign", "NOTOOL write", sender="ceo")
    t0 = time.time()
    flow.tick(t0 + 1)
    time.sleep(0.2)
    assert len(_calls()) == n and len(_inbox("writer")) == 1       # it waits, it is not dropped
    assert json.loads((enterprises.state(S) / "flow.json").read_text())["waits"]["writer"]["why"] == why
    flow.tick(t0 + 3 * 3600)
    assert flow.escalations(S) == []                                # not yet: escalation_timeout_h is 4
    flow.tick(t0 + 5 * 3600)
    (e,) = flow.escalations(S, open_only=True)
    assert e["position"] == "writer" and e["to"] == "ceo" and e["waiting"] == "writer"
    assert any("waited" in i["text"] for i in _inbox("ceo"))
    flow.tick(t0 + 6 * 3600)                                        # no second escalation for the same wait
    assert len(flow.escalations(S)) == 1 and not notes


def test_a_vacant_position_keeps_its_inbox_and_the_lead_hears_of_it(ent):
    assert ent.patch(f"{E}/{S}/positions/editor", json={"agent": None, "rev": ent.get(f"{E}/{S}").json()["rev"]}).status_code == 200
    flow.deliver(S, "editor", "assign", "NOTOOL x", sender="ceo")
    t0 = time.time()
    flow.tick(t0 + 1)
    flow.tick(t0 + 5 * 3600)
    assert len(_inbox("editor")) == 1
    (e,) = flow.escalations(S, open_only=True)
    assert e["to"] == "ceo"


def test_a_late_run_start_fills_the_seen_file_and_clears_the_wait(ent):
    assert ent.patch("/api/agents/acme/blog/writer", json={"enabled": False}).status_code == 200
    flow.deliver(S, "writer", "note", "NOTOOL hi", sender="ceo")
    flow.tick(time.time() + 1)
    assert ent.patch("/api/agents/acme/blog/writer", json={"enabled": True}).status_code == 200
    n = len(_calls())
    flow.tick(time.time() + 2)
    wait_for(lambda: len(_calls()) == n + 1)
    assert json.loads((enterprises.state(S) / "flow.json").read_text())["waits"] == {}


def test_trusted_delivery_gives_orders_in_clear(ent, policy):
    policy.trusted_delivery = lambda slug, outside: not outside
    n = len(_calls())
    flow.deliver(S, "writer", "assign", "NOTOOL do the thing", sender="ceo")
    flow.tick(time.time() + 1)
    wait_for(lambda: len(_calls()) == n + 1)
    p = _calls()[-1]["prompt"]
    assert "do the thing" in p and "DATA from outside" not in p
    flow.deliver(S, "writer", "assign", "NOTOOL tainted", sender="ceo", outside=True)
    pass
    wait_for(lambda: (flow.tick(time.time() + 2), len(_calls()) == n + 2)[1])
    assert "DATA from outside" in _calls()[-1]["prompt"]


def test_deliver_checks_kind_and_position(ent):
    with pytest.raises(EnterpriseError) as e:
        flow.deliver(S, "ceo", "shout", "x")
    assert e.value.code == "invalid"
    with pytest.raises(EnterpriseError) as e:
        flow.deliver(S, "nobody", "note", "x")
    assert e.value.status == 404


# ---- delegated tasks ------------------------------------------------------------------------------------
def test_assign_rules(ent, mx):
    t = flow.assign(S, "ceo", "writer", "Three articles\nabout spring", due="2026-12-01", session="s1")
    assert t["status"] == "doing" and t["labels"] == [S] and t["due"] == "2026-12-01" and t["title"] == "Three articles"
    e = t["enterprise"]
    assert (e["id"], e["owner"], e["requester"], e["parent"], e["stage"], e["hops"], e["outside"]) == \
        (S, "writer", "ceo", "", "", 1, False)
    assert _tasks(mx)[0]["enterprise"]["owner"] == "writer"
    (item,) = _inbox("writer")
    assert item["kind"] == "assign" and item["from"] == "ceo" and item["task"] == t["id"]
    assert any(d["kind"] == "assign" and d["task"] == t["id"] for d in enterprises.decisions(S)[0])
    for frm, to in (("ceo", "intern"), ("writer", "editor"), ("writer", "ceo"), ("ceo", "ceo")):
        with pytest.raises(EnterpriseError) as x:
            flow.assign(S, frm, to, "nope")
        assert x.value.status in (400, 403)
    assert flow.assign(S, "", "intern", "owner knows best")["enterprise"]["requester"] == ""
    with pytest.raises(EnterpriseError):
        flow.assign(S, "ceo", "writer", "  ")


def test_cross_department_request(ent, policy, mx):
    rev = ent.get(f"{E}/{S}").json()["rev"]
    assert ent.patch(f"{E}/{S}/positions/editor", json={"department": "ops", "rev": rev}).status_code == 200
    policy.decider = lambda slug, pos, cat, **kw: "lead"
    req = flow.assign(S, "ceo", "editor", "NOTOOL cross")
    assert req["category"] == "assign_cross" and policy.requests_made[0][:2] == ("ceo", "assign_cross")
    assert not (mx["ws"] / "tasks.json").exists() or _tasks(mx) == []
    assert _inbox("editor") == []


def test_chain_and_hops(ent, notes, mx):
    p = flow.assign(S, "", "ceo", "Big goal")
    c = flow.assign(S, "ceo", "writer", "Part", parent=p["id"])
    assert c["enterprise"]["parent"] == p["id"] and c["enterprise"]["hops"] == 2 and c["enterprise"]["chain"] == ["ceo"]
    d = flow.assign(S, "writer", "intern", "Sub-part", parent=c["id"])
    assert d["enterprise"]["hops"] == 3 and d["enterprise"]["chain"] == ["ceo", "writer"]
    # a position already in the chain of the parent is refused
    api = __import__("maxxing.api.tasks", fromlist=["x"])
    api.update_task(p["id"], {"enterprise": {**p["enterprise"], "chain": ["editor"]}})
    with pytest.raises(EnterpriseError) as x:
        flow.assign(S, "ceo", "editor", "loop", parent=p["id"])
    assert x.value.code == "in_chain"
    # over hops_per_task: refused and the owner is asked
    assert ent.patch(f"{E}/{S}", json={"settings": {"limits": {"hops_per_task": 2}}}).status_code == 200
    with pytest.raises(EnterpriseError) as x:
        flow.assign(S, "writer", "intern", "too deep", parent=c["id"])
    assert x.value.code == "too_many_hops"
    assert notes and notes[-1]["ref"].startswith(f"enterprise:esc:{S}:")
    (e,) = [i for i in flow.escalations(S, open_only=True)]
    assert e["to"] == "owner"


def test_task_file_keeps_unknown_fields_and_tolerates_owner_edits(ent, mx):
    f = mx["ws"] / "tasks.json"
    f.write_text(json.dumps({"version": 1, "projects": [], "tasks": [
        {"id": "t_aaaaaa", "title": "mine", "status": "todo", "custom": {"keep": True}}], "extra_top": 7}))
    t = flow.assign(S, "ceo", "writer", "NOTOOL x")
    flow.done(S, "writer", t["id"], "ok")
    data = json.loads(f.read_text())
    assert data["extra_top"] == 7 and data["tasks"][0]["custom"] == {"keep": True} and len(data["tasks"]) == 2
    # the owner edits the task on the Tasks page: fields the page does not know survive our next write
    assert ent.patch(f"/api/tasks/{t['id']}", json={"title": "renamed", "priority": 2}).status_code == 200
    flow.done(S, "ceo", t["id"], "")
    row = [x for x in json.loads(f.read_text())["tasks"] if x["id"] == t["id"]][0]
    assert row["title"] == "renamed" and row["priority"] == 2 and row["status"] == "done" and row["enterprise"]["stage"] == ""
    # deleted by the owner: later references are ignored
    assert ent.delete(f"/api/tasks/{t['id']}").status_code == 200
    assert flow.done(S, "writer", t["id"], "again") == {"id": t["id"], "missing": True}
    assert flow.block(S, "writer", t["id"], "x")["missing"] is True
    assert any("no longer exists" in d["text"] for d in enterprises.decisions(S)[0])
    # assigning "again" on a deleted task creates a fresh one
    assert flow.assign(S, "ceo", "writer", "NOTOOL redo", task=t["id"])["id"] != t["id"]


def test_done_review_accept(ent, mx):
    t = flow.assign(S, "ceo", "writer", "Draft")
    tid = t["id"]
    with pytest.raises(EnterpriseError) as x:
        flow.done(S, "editor", tid, "not mine")
    assert x.value.status == 403
    r = flow.done(S, "writer", tid, "drafts/ in the shared folder")
    assert r["status"] == "doing" and r["enterprise"]["stage"] == "review"
    hand = [i for i in _inbox("ceo") if i["kind"] == "handin"]
    assert len(hand) == 1 and hand[0]["task"] == tid and "drafts/" in hand[0]["text"] and hand[0]["from"] == "writer"
    r = flow.done(S, "ceo", tid, "")
    assert r["status"] == "done" and r["enterprise"]["stage"] == "" and r["done_at"]
    # send back: one more hop, stage cleared
    t2 = flow.assign(S, "ceo", "writer", "Draft 2")
    flow.done(S, "writer", t2["id"], "v1")
    back = flow.assign(S, "ceo", "writer", "needs a shorter intro", task=t2["id"])
    assert back["id"] == t2["id"] and back["enterprise"]["hops"] == 2 and back["enterprise"]["stage"] == "" \
        and back["status"] == "doing" and "shorter intro" in back["notes"]
    with pytest.raises(EnterpriseError) as x:
        flow.assign(S, "editor", "writer", "x", task=t2["id"])
    assert x.value.status in (403,)


def test_hand_in_refused_with_open_children(ent):
    p = flow.assign(S, "ceo", "writer", "Parent")
    c = flow.assign(S, "writer", "intern", "Child", parent=p["id"])
    with pytest.raises(EnterpriseError) as x:
        flow.done(S, "writer", p["id"], "done?")
    assert x.value.code == "open_children"
    flow.done(S, "intern", c["id"], "ok")
    flow.done(S, "writer", c["id"], "")                              # the requester of the child accepts
    assert flow.done(S, "writer", p["id"], "now")["enterprise"]["stage"] == "review"


def test_hand_in_of_an_owner_task_notifies_the_owner(ent, notes):
    t = flow.assign(S, "", "ceo", "Owner's goal")
    flow.done(S, "ceo", t["id"], "all done")
    assert notes and "all done" in notes[-1]["body"]
    assert flow.done(S, "", t["id"], "")["status"] == "done"


def test_block(ent):
    t = flow.assign(S, "ceo", "writer", "Draft")
    r = flow.block(S, "writer", t["id"], "no access to the brief")
    assert r["enterprise"]["stage"] == "blocked" and r["enterprise"]["reason"] == "no access to the brief" \
        and r["status"] == "doing"
    note = [i for i in _inbox("ceo") if i["kind"] == "note"]
    assert note and "no access to the brief" in note[0]["text"]
    with pytest.raises(EnterpriseError):
        flow.block(S, "editor", t["id"], "x")


# ---- escalations ----------------------------------------------------------------------------------------
def test_escalation_goes_to_the_lead_and_skips_the_unavailable(ent):
    e = flow.escalate(S, "intern", "NOTOOL which tone? I recommend formal.", task="t_zz")
    assert e["to"] == "writer" and e["level"] == 0 and e["status"] == "open" and e["deadline"] > time.time()
    (item,) = _inbox("writer")
    assert item["kind"] == "escalation" and e["id"] in item["text"] and item["from"] == "intern"
    assert ent.patch("/api/agents/acme/blog/writer", json={"enabled": False}).status_code == 200
    e2 = flow.escalate(S, "intern", "again")
    assert e2["to"] == "ceo"
    log = enterprises.decisions(S)[0]
    assert any(d["kind"] == "skip" and "writer" in d["text"] and "disabled" in d["text"] for d in log)
    # the holder went away after the escalation was made: it climbs at the next tick, without waiting for the deadline
    flow.tick(time.time() + 1)
    assert {x["id"]: x["to"] for x in flow.escalations(S)}[e["id"]] == "ceo"


def test_top_of_the_chart_escalates_to_the_owner_with_a_link(ent, notes):
    e = flow.escalate(S, "ceo", "I need a decision on the budget", outside=True)
    assert e["to"] == "owner" and e["deadline"] is None and e["outside"] is True
    (n,) = notes
    assert n["url"] == f"/enterprises/{S}/overview" and n["ref"] == f"enterprise:esc:{S}:{e['id']}" and n["slug"] == S
    assert n["actions"] and n["actions"][0]["id"] == "open"
    flow.tick(time.time() + 100 * 3600)
    assert len(notes) == 1                                             # asked once


def test_silent_agent_still_notifies(ent, notes):
    assert ent.patch("/api/agents/acme/blog/boss", json={"silent": True}).status_code in (200, 422)
    flow.escalate(S, "ceo", "still shown")
    assert len(notes) == 1


def test_timeout_climbs_one_level_at_a_time(ent, notes):
    t0 = time.time()
    e = flow.escalate(S, "intern", "NOTOOL stuck")
    flow.tick(t0 + 3 * 3600)
    assert flow.escalations(S)[0]["to"] == "writer"
    flow.tick(t0 + 5 * 3600)
    cur = flow.escalations(S)[0]
    assert cur["to"] == "ceo" and cur["level"] == 1 and cur["deadline"] is not None
    assert any(i["kind"] == "escalation" and "passed up" in i["text"] for i in _inbox("ceo"))
    assert notes == []
    flow.tick(t0 + 10 * 3600)
    cur = flow.escalations(S)[0]
    assert cur["to"] == "owner" and cur["level"] == 2 and cur["deadline"] is None and cur["id"] == e["id"]
    assert len(notes) == 1 and notes[0]["body"].endswith("stuck")
    assert any(d["kind"] == "climb" for d in enterprises.decisions(S)[0])


def test_department_timeout_override_is_used(ent):
    assert ent.patch(f"{E}/{S}", json={"settings": {"escalation_timeout_h": 1}}).status_code == 200
    t0 = time.time()
    flow.escalate(S, "intern", "quick")
    flow.tick(t0 + 1.5 * 3600)
    assert flow.escalations(S)[0]["to"] == "ceo"


def test_answers(ent, notes):
    e = flow.escalate(S, "intern", "NOTOOL which tone?")
    with pytest.raises(EnterpriseError) as x:
        flow.answer(S, e["id"], "formal", by="ceo")                    # not the holder
    assert x.value.status == 403
    r = flow.answer(S, e["id"], "formal", by="writer")
    assert r["status"] == "answered" and r["answered_by"] == "writer"
    (a,) = [i for i in _inbox("intern") if i["kind"] == "answer"]
    assert a["from"] == "writer" and "formal" in a["text"]
    with pytest.raises(EnterpriseError) as x:
        flow.answer(S, e["id"], "again")
    assert x.value.status == 409
    with pytest.raises(EnterpriseError) as x:
        flow.answer(S, "e_nope", "x")
    assert x.value.status == 404
    flow.tick(time.time() + 50 * 3600)                                 # an answered one never climbs
    assert notes == [] and flow.escalations(S)[0]["to"] == "writer"


def test_owner_answer_route(ent, notes):
    e = flow.escalate(S, "ceo", "need the owner")
    r = ent.get(f"{E}/{S}/escalations")
    assert r.status_code == 200
    (it,) = r.json()["items"]
    assert it["id"] == e["id"] and it["position"] == "ceo" and it["status"] == "open" and it["level"] == 0
    assert ent.post(f"{E}/{S}/escalations/{e['id']}/answer", json={"text": " "}).status_code == 400
    r = ent.post(f"{E}/{S}/escalations/{e['id']}/answer", json={"text": "Go ahead"})
    assert r.status_code == 200 and r.json()["status"] == "answered"
    (a,) = [i for i in _inbox("ceo") if i["kind"] == "answer"]
    assert a["from"] == "" and "Go ahead" in a["text"]
    assert ent.post(f"{E}/{S}/escalations/{e['id']}/answer", json={"text": "x"}).status_code == 409
    assert ent.post(f"{E}/{S}/escalations/e_zzz/answer", json={"text": "x"}).status_code == 404
    assert ent.get(f"{E}/nope/escalations").status_code == 404
    # the owner may also answer an escalation still held by a position
    e2 = flow.escalate(S, "intern", "ask the owner anyway")
    assert ent.post(f"{E}/{S}/escalations/{e2['id']}/answer", json={"text": "ok"}).status_code == 200


def test_routes_are_off_with_the_feature(client, topic):
    assert client.get(f"{E}/x/escalations").status_code == 404
    assert client.get(f"{E}/x/escalations").json()["error"] == "feature_off"
    assert client.post(f"{E}/x/escalations/e_1/answer", json={"text": "a"}).json()["error"] == "feature_off"


# ---- pause and restart ----------------------------------------------------------------------------------
def test_clocks_pause_while_the_feature_is_off(ent):
    t0 = time.time()
    e = flow.escalate(S, "intern", "NOTOOL stuck")
    flow.deliver(S, "editor", "note", "NOTOOL x", sender="ceo")
    assert ent.patch("/api/agents/acme/blog/editor", json={"enabled": False}).status_code == 200
    assert ent.put("/api/settings", json={"enterprises_page": False}).status_code == 200
    flow.tick(t0 + 1 * 3600)                                           # off: paused, nothing happens
    flow.tick(t0 + 30 * 3600)
    assert ent.put("/api/settings", json={"enterprises_page": True}).status_code == 200
    flow.tick(t0 + 50 * 3600)                                          # back, after 49 h of pause: no burst
    cur = flow.escalations(S)[0]
    assert cur["to"] == "writer" and cur["level"] == 0
    assert len(_inbox("editor")) == 1
    flow.tick(t0 + 50 * 3600 + 3 * 3600)
    assert flow.escalations(S)[0]["level"] == 0
    flow.tick(t0 + 50 * 3600 + 5 * 3600)
    assert {x["id"]: x["to"] for x in flow.escalations(S)}[e["id"]] == "ceo"


def test_deliveries_stay_in_the_inbox_while_off_and_a_tick_resumes_them(ent):
    assert ent.put("/api/settings", json={"enterprises_page": False}).status_code == 200
    n = len(_calls())
    flow.deliver(S, "ceo", "handin", "NOTOOL late", sender="writer")
    flow.tick(time.time() + 10)
    time.sleep(0.2)
    assert len(_calls()) == n and len(_inbox("ceo")) == 1
    assert ent.put("/api/settings", json={"enterprises_page": True}).status_code == 200
    # a "restarted" server holds no timer and no pending map: the files are all it needs
    assert flow._timers == {}
    flow.tick(time.time() + 20)
    wait_for(lambda: len(_calls()) == n + 1)
    assert _inbox("ceo") == []


def test_tick_all_runs_the_other_tickers(ent, monkeypatch):
    from maxxing.api import enterprise_flow as api
    seen = []
    for name in api.TICKERS:
        m = types.ModuleType(f"maxxing.{name}")
        m.tick = (lambda nm: lambda now=None: seen.append(nm))(name)
        monkeypatch.setitem(sys.modules, f"maxxing.{name}", m)
    bad = types.ModuleType("maxxing.enterprise_reports")
    bad.tick = lambda now=None: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setitem(sys.modules, "maxxing.enterprise_reports", bad)
    api.tick_all(time.time())
    wait_for(lambda: not api._slow_guard.locked())
    assert sorted(seen) == ["enterprise_desk", "enterprise_policy", "enterprise_workers"]


def test_every_ticking_module_is_scheduled():
    from maxxing.api import enterprise_flow as api
    root = Path(enterprises.__file__).parent
    ticking = {f.stem for f in root.glob("enterprise_*.py")
               if "\ndef tick(" in f.read_text(encoding="utf-8") and f.stem != "enterprise_flow"}
    assert ticking == set(api.TICKERS) and set(api.SLOW) <= ticking


def test_a_slow_ticker_never_holds_back_the_flow(ent, monkeypatch):
    import threading
    from maxxing.api import enterprise_flow as api
    gate, started = threading.Event(), threading.Event()
    slow = types.ModuleType("maxxing.enterprise_reports")
    slow.tick = lambda now=None: (started.set(), gate.wait(10))
    monkeypatch.setitem(sys.modules, "maxxing.enterprise_reports", slow)
    flow.deliver(S, "ceo", "note", "NOTOOL hello", sender="writer")
    n = len(_calls())
    t0 = time.time()
    api.tick_all(time.time() + 1)
    assert started.wait(5) and time.time() - t0 < 5
    wait_for(lambda: len(_calls()) == n + 1)                           # the delivery started while reports run
    api.tick_all(time.time() + 2)                                      # skipped: the previous pass still runs
    gate.set()
    wait_for(lambda: not api._slow_guard.locked())


def test_a_position_named_owner_has_no_owner_right(ent):
    with pytest.raises(EnterpriseError) as x:
        flow.assign(S, "owner", "writer", "as the owner")              # the word is a plain (unknown) position id
    assert x.value.code == "bad_position"
    assert flow._who(None) == "" and flow._who("") == "" and flow._who("owner") == "owner"


def test_an_answer_from_an_outside_run_is_outside_data(ent):
    e = flow.escalate(S, "intern", "NOTOOL which tone?")
    flow.answer(S, e["id"], "formal", by="writer", outside=True)
    (a,) = [i for i in _inbox("intern") if i["kind"] == "answer"]
    assert a["outside"] is True
    e2 = flow.escalate(S, "intern", "NOTOOL again?")
    flow.answer(S, e2["id"], "casual", by="writer")
    assert [i["outside"] for i in _inbox("intern") if i["kind"] == "answer"] == [True, False]


def test_timers_only_in_the_server(ent, monkeypatch):
    monkeypatch.setenv("MAXXING_ENTERPRISE_TICK", "1")
    monkeypatch.setattr(flow, "SERVER", False)
    flow.deliver(S, "ceo", "note", "NOTOOL hello", sender="writer")
    assert flow._timers == {}
    monkeypatch.setattr(flow, "SERVER", True)
    monkeypatch.setattr(flow.threading, "Timer", lambda *a, **k: types.SimpleNamespace(
        daemon=False, start=lambda: flow._timers.setdefault("started", 1)))
    flow.deliver(S, "ceo", "note", "NOTOOL again", sender="writer")
    assert ("acme-group", "ceo") in flow._timers
    flow._timers.clear()


def test_send_back_goes_to_the_owner_of_the_task(ent, mx):
    t = flow.assign(S, "ceo", "writer", "Draft")
    with pytest.raises(EnterpriseError) as x:
        flow.assign(S, "ceo", "editor", "redo", task=t["id"])           # a position that never had it
    assert x.value.code == "invalid"
    with pytest.raises(EnterpriseError) as x:
        flow.assign(S, "writer", "intern", "redo", task=t["id"])        # not the requester
    assert x.value.code == "not_yours"
    back = flow.assign(S, "", "writer", "owner notes", task=t["id"])    # the owner acts on any task
    assert back["enterprise"]["requester"] == "ceo" and back["enterprise"]["hops"] == 2
    assert flow.assign(S, "ceo", "writer", "notes", task=t["id"])["enterprise"]["hops"] == 3


def test_the_parent_defaults_to_the_task_delivered_in_the_session(ent, mx):
    top = flow.assign(S, "", "ceo", "Big goal")
    path = flow._inbox_dir(S) / "ceo.seen.jsonl"
    flow._write(path, [{"id": "i_1", "kind": "assign", "task": top["id"], "from": "", "text": "x", "run": "sess-1"}])
    kid = flow.assign(S, "ceo", "writer", "Part", session="sess-1")      # no --parent
    e = kid["enterprise"]
    assert e["parent"] == top["id"] and e["hops"] == 2 and e["chain"] == ["ceo"]
    other = flow.assign(S, "ceo", "editor", "Other", session="sess-2")  # another run: nothing inherited
    assert other["enterprise"]["parent"] == "" and other["enterprise"]["hops"] == 1


def test_the_parent_also_defaults_from_a_handin_or_an_answer(ent, mx):
    top = flow.assign(S, "ceo", "writer", "Part")                        # ceo asked, writer hands in, ceo's next run
    path = flow._inbox_dir(S) / "ceo.seen.jsonl"
    flow._write(path, [{"id": "i_1", "kind": "handin", "task": top["id"], "from": "writer", "text": "x", "run": "sess-9"}])
    nxt = flow.assign(S, "ceo", "editor", "Next", session="sess-9")
    assert nxt["enterprise"]["parent"] == top["id"] and nxt["enterprise"]["hops"] == 2


def test_a_full_inbox_logs_what_it_drops(ent, monkeypatch):
    monkeypatch.setattr(flow, "INBOX_MAX", 2)
    for i in range(3):
        flow.deliver(S, "ceo", "note", f"NOTOOL n{i}", sender="writer")
    assert [i["text"] for i in _inbox("ceo")] == ["NOTOOL n1", "NOTOOL n2"]
    assert any("dropped" in d["text"] for d in enterprises.decisions(S)[0])


def test_climb_rechecks_after_computing_the_target(ent, notes):
    e = flow.escalate(S, "intern", "NOTOOL slow answer")
    real = flow._target

    def target(slug, pos):
        flow.answer(S, e["id"], "late", by="writer")                   # answered while the target is computed
        return real(slug, pos)
    flow._target = target
    try:
        flow._climb(S, e["id"], time.time(), "no answer in time")
    finally:
        flow._target = real
    assert flow.escalations(S)[0]["status"] == "answered" and flow.escalations(S)[0]["to"] == "writer"
