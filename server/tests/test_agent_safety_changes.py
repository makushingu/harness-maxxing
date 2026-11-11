"""Safety settings of an agent that change after its creation: an allowed change request applies what its card showed
(items added / removed, a value from -> to) over the settings of that moment, and follows a renamed topic; a free
agent that starts reading outside text goes into its sandbox (agents.request_change / delta_fields / _auto_box)."""
from __future__ import annotations

import json

import pytest

from conftest import wait_idle
from test_agents import A, _create as _create_any, _on
from maxxing import agents, approvals, cli


def _create(client, **extra) -> dict:
    return _create_any(client, **{"sandbox": True, **extra})


def _ask(fields: dict) -> str:
    r = agents.request_change(A, fields, session="s1")
    assert r["request"], r
    return r["request"]


def _card(rid: str) -> str:
    return approvals.get(rid)["input"]["description"]


def test_an_allowed_change_adds_what_its_card_shows_over_the_settings_of_now(client, topic, mx):
    _on(client)
    _create(client, domains=["api.github.com"])
    r1, r2 = _ask({"domains": ["api.github.com", "a.example.com"]}), _ask({"domains": ["api.github.com", "b.example.com"]})
    assert _card(r1) == "domains: + a.example.com" and approvals.get(r1)["change"] == \
        {"domains": {"add": ["a.example.com"], "remove": []}}
    # the owner removes a site meanwhile: neither Allow brings it back, and the second keeps the first
    assert client.patch("/api/agents/acme/blog/writer", json={"domains": ["docs.example.com"]}).status_code == 200
    approvals.decide(r1, "allow")
    assert agents.load(A)["domains"] == ["docs.example.com", "a.example.com"]
    r = client.post(f"/api/approvals/{r2}", json={"decision": "allow"})            # the web page: same rule
    assert r.status_code == 200, r.text
    assert agents.load(A)["domains"] == ["docs.example.com", "a.example.com", "b.example.com"]
    # a request that adds and removes: exactly those items, the rest stays
    r3 = _ask({"domains": ["a.example.com", "b.example.com", "c.example.com"]})
    assert _card(r3) == "domains: + c.example.com, - docs.example.com"
    client.patch("/api/agents/acme/blog/writer", json={"domains": ["docs.example.com", "a.example.com", "z.example.com"]})
    approvals.decide(r3, "allow")
    assert agents.load(A)["domains"] == ["a.example.com", "z.example.com", "c.example.com"]
    # denied: nothing (negative)
    r4 = _ask({"domains": ["a.example.com", "evil.example.com"]})
    approvals.decide(r4, "deny")
    assert "evil.example.com" not in agents.load(A)["domains"]


def test_an_allowed_change_whose_value_changed_since_is_refused(client, topic, mx):
    _on(client)
    _create(client)
    rid = _ask({"permission_mode": "bypass"})
    assert _card(rid) == "permission_mode: (none) -> bypass"
    client.patch("/api/agents/acme/blog/writer", json={"permission_mode": "default"})
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.decide(rid, "allow")
    assert e.value.status == 409 and e.value.code == "stale_change" and "permission_mode is default" in e.value.message
    d = approvals.get(rid)
    assert d["status"] == "deny" and d["stale"] and "nothing applied" in d["message"]
    assert agents.load(A)["permission_mode"] == "default"                       # the owner's choice stays
    assert "was not applied" in agents._read_state(A)["chat_notes"][-1]           # the conversation hears why
    with pytest.raises(approvals.ApprovalError) as e:                            # closed: a second tap is 409
        approvals.decide(rid, "allow")
    assert e.value.code == "not_pending"
    # the web page and the feed's buttons: the same refusal
    rid = _ask({"limits": {"usd_per_day": 9}})
    client.patch("/api/agents/acme/blog/writer", json={"limits": {"usd_per_day": 3}})
    r = client.post(f"/api/approvals/{rid}", json={"decision": "allow"})
    assert r.status_code == 409 and "limits.usd_per_day is 3.0" in r.text
    assert agents.load(A)["limits"]["usd_per_day"] == 3
    rid = _ask({"permission_mode": "acceptEdits", "trust_outside": True})
    client.patch("/api/agents/acme/blog/writer", json={"permission_mode": "bypass"})
    approvals.feed_action(rid, "allow", "web", {"id": 0})                       # 409 swallowed: the event says it
    a = agents.load(A)
    assert approvals.get(rid)["status"] == "deny" and a["trust_outside"] is False and a["permission_mode"] == "bypass"
    # a value already set as asked: allowed, nothing else to do (not stale)
    rid = _ask({"trust_outside": True})
    client.patch("/api/agents/acme/blog/writer", json={"trust_outside": True})
    approvals.decide(rid, "allow")
    assert approvals.get(rid)["status"] == "allow" and agents.load(A)["trust_outside"] is True
    # a request saved by the version before (whole values, no delta): refused, never applied
    rid = _ask({"domains": ["x.example.com"]})
    f = approvals.folder() / f"{rid}.json"
    old = json.loads(f.read_text())
    old.pop("change")
    f.write_text(json.dumps({**old, "fields": {"domains": ["x.example.com"]}}))
    with pytest.raises(approvals.ApprovalError, match="older version"):
        approvals.decide(rid, "allow")
    assert agents.load(A)["domains"] == []


def test_a_change_waiting_when_its_topic_is_renamed_applies_to_the_agent(client, topic, mx):
    _on(client)
    _create(client, domains=["api.github.com"])
    rid = _ask({"domains": ["api.github.com", "a.example.com"]})
    assert client.patch("/api/workspace/projects/acme/topics/blog", json={"name": "news"}).status_code == 200
    new = "projects/acme/topics/news/agents/writer"
    assert approvals.get(rid)["agent_path"] == new
    approvals.decide(rid, "allow")
    assert agents.load(new)["domains"] == ["api.github.com", "a.example.com"]
    # a project rename too
    rid = agents.request_change(new, {"domains": ["api.github.com", "a.example.com", "b.example.com"]},
                                session="s1")["request"]
    assert client.patch("/api/workspace/projects/acme", json={"name": "zeta"}).status_code == 200
    newer = "projects/zeta/topics/news/agents/writer"
    assert approvals.get(rid)["agent_path"] == newer
    # the agent deleted meanwhile: the Allow says so, nothing is "Allowed" (negative)
    agents.delete(newer)
    with pytest.raises(approvals.ApprovalError, match="no longer exists"):
        approvals.decide(rid, "allow")
    assert approvals.get(rid)["status"] == "deny"


def test_a_free_agent_that_starts_reading_outside_text_goes_into_its_sandbox(client, topic, mx, monkeypatch, capsys):
    _on(client)
    _create_any(client, description="")                                        # what the page creates: free
    assert agents.load(A)["sandbox"] is False
    # its conversation adds a webhook (`maxxing agents webhook` on itself): sandbox on at once, said
    monkeypatch.setenv("MAXXING_AGENT", A)
    monkeypatch.setenv("MAXXING_AGENT_CHAT", "1")
    assert cli.main(["agents", "webhook", A]) == 0
    assert "Its sandbox is now on" in capsys.readouterr().out
    assert agents.load(A)["sandbox"] is True
    assert any(m["kind"] == "note" and m.get("status") == "sandbox" for m in agents.thread(A))
    monkeypatch.delenv("MAXXING_AGENT_CHAT")
    monkeypatch.delenv("MAXXING_AGENT")
    # the owner sets it Free on purpose: later saves and more sources never turn it back on
    client.patch("/api/agents/acme/blog/writer", json={"sandbox": False})
    assert cli.main(["agents", "watch", A, "--source", "stripe"]) == 0
    assert "Its sandbox" not in capsys.readouterr().out
    client.patch("/api/agents/acme/blog/writer", json={"limits": {"usd_per_day": 3}})
    assert agents.load(A)["sandbox"] is False


def test_each_way_of_adding_outside_text_turns_the_sandbox_on(client, topic, mx, monkeypatch, capsys):
    _on(client)
    feed_t = {"kind": "feed", "source": "stripe"}
    # the owner's page: a feed trigger saved with the triggers list, then the Add webhook menu
    _create_any(client, description="")
    r = client.patch("/api/agents/acme/blog/writer", json={"triggers": [feed_t]})
    assert r.json()["sandbox"] is True and r.json()["sandbox_auto"] is True
    agents.delete(A)
    _create_any(client, description="")
    r = client.post("/api/agents/acme/blog/writer/webhook", json={"kind": "generic"})
    assert r.status_code == 200, r.text
    assert r.json()["agent"]["sandbox"] is True and r.json()["agent"]["sandbox_auto"] is True
    agents.delete(A)
    # the same save choosing Free: kept (negative)
    _create_any(client, description="")
    r = client.patch("/api/agents/acme/blog/writer", json={"triggers": [feed_t], "sandbox": False})
    assert r.json()["sandbox"] is False and "sandbox_auto" not in r.json()
    agents.delete(A)
    # a change that adds no outside source (negative)
    _create_any(client, description="")
    assert client.patch("/api/agents/acme/blog/writer", json={"model": "sonnet"}).json()["sandbox"] is False
    # the manager's `set triggers=`: applied at once with its sandbox
    r = agents.request_change(A, {"triggers": [feed_t]}, session="s1")
    assert r["applied"] == ["sandbox", "triggers"] and r["asked"] == [] and r["sandbox_auto"]
    assert agents.load(A)["sandbox"] is True
    agents.delete(A)
    # the manager asks for a mailbox: its sandbox is in the same request (on the card), nothing if denied
    _create_any(client, description="")
    grant = [{"account": "box1", "rights": ["read"]}]
    rid = agents.request_change(A, {"mail": grant}, session="s1")["request"]
    card = _card(rid)
    assert card.startswith("sandbox: off -> on; mail box1: (none) -> {")
    approvals.decide(rid, "deny")
    a = agents.load(A)
    assert a["sandbox"] is False and a["mail"] == []
    rid = agents.request_change(A, {"mail": grant}, session="s1")["request"]
    approvals.decide(rid, "allow")
    a = agents.load(A)
    assert a["sandbox"] is True and [g["account"] for g in a["mail"]] == ["box1"]
    agents.delete(A)
    # templates that read outside text: protected from the API as from the CLI; `--no-sandbox` is the owner's choice
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": "writer", "template": "support"})
    assert r.status_code == 200 and r.json()["sandbox"] is True
    assert cli.main(["agents", "create", "acme/blog/helper", "--template", "support", "--no-sandbox"]) == 0
    capsys.readouterr()
    h = agents.load("projects/acme/topics/blog/agents/helper")
    assert h["sandbox"] is False and any(t["kind"] == "feed" for t in h["triggers"])
    assert cli.main(["agents", "create", "acme/blog/helper2", "--template", "support"]) == 0
    assert agents.load("projects/acme/topics/blog/agents/helper2")["sandbox"] is True
    assert agents.load("projects/acme/topics/blog/agents/helper2")["triggers"]
