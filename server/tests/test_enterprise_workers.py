"""Enterprise workers (maxxing/enterprise_workers.py, api/enterprise_workers.py, `worker` CLI) and objectives."""
from __future__ import annotations

import time

import pytest
from conftest import wait_for
from maxxing import agents, cli, enterprise_policy as pol, enterprise_workers as ew, enterprises
from maxxing.enterprises import EnterpriseError

SLUG = "acme-group"
E = f"/api/enterprises/{SLUG}"
T = "projects/acme/topics/blog"
BOSS, WRITER = f"{T}/agents/boss", f"{T}/agents/writer"
TPL = {"role": "Research helper", "model": "", "usd_per_day": 0.5}


@pytest.fixture
def ent(client, topic):
    assert client.put("/api/settings", json={"agents_page": True, "enterprises_page": True}).status_code == 200
    for n in ("boss", "writer"):
        assert client.post("/api/agents", json={"topic_path": T, "name": n, "sandbox": False,
                                                "writable": []}).status_code == 200
    assert client.post("/api/enterprises", json={"id": SLUG, "name": "Acme Group", "projects": ["acme"]}).status_code == 200
    for pid, to, agent in (("boss", None, BOSS), ("writer", "boss", WRITER)):
        r = client.post(f"{E}/positions", json={"id": pid, "title": pid.title(), "reports_to": to, "agent": agent})
        assert r.status_code == 200, r.text
    assert client.patch(f"{E}/positions/writer", json={"worker_template": TPL}).status_code == 200
    assert client.patch(E, json={"settings": {"workers": "visible"}}).status_code == 200
    return client


def _allow(monkeypatch):
    """The request is allowed at once (the matrix itself never does for `worker`)."""
    real = pol.request
    monkeypatch.setattr(pol, "request", lambda *a, **k: {**real(*a, **k), "status": "allowed"})


def test_start_needs_visible_workers_and_a_template(ent):
    for mode, code in (("discreet", "workers_discreet"), ("off", "workers_off")):
        assert ent.patch(E, json={"settings": {"workers": mode}}).status_code == 200
        with pytest.raises(EnterpriseError) as e:
            ew.start(SLUG, "writer", "NOTOOL x")
        assert e.value.code == code
    assert ent.patch(E, json={"settings": {"workers": "visible"}}).status_code == 200
    with pytest.raises(EnterpriseError) as e:
        ew.start(SLUG, "boss", "NOTOOL x")
    assert e.value.code == "no_template"


def test_request_then_decision_makes_the_worker(ent):
    r = ew.start(SLUG, "writer", "NOTOOL collect sources")
    assert r["status"] == "pending" and r["request"]["category"] == "worker"
    assert ew.workers(SLUG) == []
    ew.tick()
    assert ew.workers(SLUG) == []                                   # still waiting for the decision
    pol.decide(SLUG, r["request"]["id"], "allow")
    ew.tick()
    [w] = ew.workers(SLUG)
    a = agents.load(w["agent"])
    assert w["id"] == "writer-w1" and w["agent"] == f"{T}/agents/writer-w1" and w["status"] == "live"
    assert a["sandbox"] is True and a["keys"] == [] and a["domains"] == [] and a["triggers"] == []
    assert a["limits"]["usd_per_day"] == 0.5 and enterprises.seat_of(w["agent"]) is None
    assert w["session"]
    assert ent.get(f"{E}/workers").json()["items"][0]["id"] == "writer-w1"


def test_denied_request_makes_nothing(ent):
    r = ew.start(SLUG, "writer", "NOTOOL x")
    pol.decide(SLUG, r["request"]["id"], "deny")
    ew.tick()
    assert ew.workers(SLUG) == [] and ew._read(SLUG)["pending"] == []


def test_live_limit_and_names(ent, monkeypatch):
    _allow(monkeypatch)
    assert ent.patch(E, json={"settings": {"limits": {"workers_live": 2}}}).status_code == 200
    a = ew.start(SLUG, "writer", "NOTOOL one")
    b = ew.start(SLUG, "writer", "NOTOOL two")
    assert (a["worker"]["id"], b["worker"]["id"]) == ("writer-w1", "writer-w2")
    with pytest.raises(EnterpriseError) as e:
        ew.start(SLUG, "writer", "NOTOOL three")
    assert e.value.code == "too_many_workers"


def test_worker_ends_when_its_run_and_task_are_done(ent, monkeypatch):
    _allow(monkeypatch)
    w = ew.start(SLUG, "writer", "NOTOOL sources", task="t_x")["worker"]
    wait_for(lambda: ew._result(w["agent"], w["session"]) is not None)
    done = {"v": False}
    monkeypatch.setattr(ew, "_task_done", lambda t: done["v"])
    ew.tick()
    assert agents.exists(w["agent"])                                # the task is not done: it stays
    done["v"] = True
    ew.tick()
    assert not agents.exists(w["agent"])
    assert ew.workers(SLUG)[0]["status"] == "done"
    assert any(i["kind"] == "handin" and "writer-w1" in i["text"] for i in enterprises.inbox(SLUG, "writer"))


def test_worker_goes_after_24_hours(ent, monkeypatch):
    _allow(monkeypatch)
    w = ew.start(SLUG, "writer", "NOTOOL sources", task="t_x")["worker"]
    wait_for(lambda: ew._result(w["agent"], w["session"]) is not None)
    monkeypatch.setattr(ew, "_task_done", lambda t: False)
    ew.tick(w["created"] + ew.TTL_S - 60)
    assert agents.exists(w["agent"])
    ew.tick(w["created"] + ew.TTL_S + 60)
    assert not agents.exists(w["agent"]) and ew.workers(SLUG)[0]["status"] == "expired"


def test_owner_stops_a_worker(ent, monkeypatch):
    _allow(monkeypatch)
    w = ew.start(SLUG, "writer", "NOTOOL sources")["worker"]
    r = ent.delete(f"{E}/workers/{w['id']}")
    assert r.status_code == 200 and r.json()["status"] == "stopped" and not agents.exists(w["agent"])
    assert ent.delete(f"{E}/workers/{w['id']}").status_code == 409
    assert ent.delete(f"{E}/workers/nope").status_code == 404


def test_off_forbids_the_subagent_tool(ent):
    assert "--disallowedTools" not in agents.run_settings(WRITER)["args"]
    assert ent.patch(E, json={"settings": {"workers": "off"}}).status_code == 200
    args = agents.run_settings(WRITER)["args"]
    assert args[args.index("--disallowedTools") + 1].split(",") == ["Agent", "Task"]


def test_note_says_how_workers_work(ent):
    from maxxing import enterprise_knowledge as k
    assert "sub-agents" not in k.note(WRITER) and "worker start" in k.note(WRITER)
    assert ent.patch(E, json={"settings": {"workers": "discreet"}}).status_code == 200
    assert "sub-agents" in k.note(WRITER)


def test_cli_worker_commands(ent, monkeypatch, capsys):
    _allow(monkeypatch)
    monkeypatch.setenv("MAXXING_AGENT", WRITER)
    monkeypatch.setenv("MAXXING_AGENT_DEPTH", "0")
    assert cli.main(["enterprise", "worker", "start", "NOTOOL", "summarize", "--for", "t_1"]) == 0
    assert "writer-w1 started" in capsys.readouterr().out
    assert cli.main(["enterprise", "worker", "list", "--json"]) == 0
    assert "writer-w1" in capsys.readouterr().out
    assert cli.main(["enterprise", "worker", "stop", "writer-w1"]) == 2
    assert "owner" in capsys.readouterr().err and agents.exists(f"{T}/agents/writer-w1")
    monkeypatch.delenv("MAXXING_AGENT")
    assert cli.main(["enterprise", "worker", "stop", "writer-w1", "--enterprise", SLUG]) == 0
    assert not agents.exists(f"{T}/agents/writer-w1")


def test_objectives_end_to_end(ent, monkeypatch, capsys):
    assert ent.patch(E, json={"objectives": [
        {"id": "traffic", "text": "More traffic", "target": 20, "unit": "%", "value": 0, "owner": "writer", "parent": ""}]}
    ).status_code == 200
    assert cli.main(["enterprise", "objective", "set", "traffic", "5", "--as", "writer", "--enterprise", SLUG]) == 0
    assert cli.main(["enterprise", "objective", "set", "traffic", "9", "--as", "boss", "--enterprise", SLUG]) == 2
    capsys.readouterr()
    [o] = enterprises.objectives_progress(SLUG)
    assert o["value"] == 5 and o["progress"] == 25
    monkeypatch.setenv("MAXXING_AGENT", WRITER)
    monkeypatch.setenv("MAXXING_AGENT_DEPTH", "0")
    assert cli.main(["enterprise", "objective", "set", "traffic", "10"]) == 0
    assert ent.get(E).json()["objectives"][0]["value"] == 10
    assert ent.get(f"{E}/overview").json()["objectives"][0]["progress"] == 50
