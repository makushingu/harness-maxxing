"""Enterprise policy (maxxing/enterprise_policy.py, api/enterprise_policy.py): requests and who decides, grants,
envelopes, communication, trust along the chain."""
from __future__ import annotations

import json
import time

import pytest
from conftest import wait_idle
from maxxing import agents, bus, cli, enterprise_policy as pol, enterprises, feed

E = "/api/enterprises/acme-group"
P = "projects/acme/topics/blog/agents/"
BOSS, HEAD, WRITER, EDITOR, OPS = (P + n for n in ("boss", "head", "writer", "editor", "ops"))
SLUG = "acme-group"


def _agent(client, name):
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": name, "sandbox": False})
    assert r.status_code == 200, r.text


@pytest.fixture
def ent(client, topic):
    """boss -> head (marketing) -> writer, editor (marketing); boss -> ops (operations). All seated."""
    assert client.put("/api/settings", json={"agents_page": True, "enterprises_page": True}).status_code == 200
    for n in ("boss", "head", "writer", "editor", "ops"):
        _agent(client, n)
    assert client.post("/api/enterprises", json={"id": SLUG, "name": "Acme Group", "projects": ["acme"]}).status_code == 200
    assert client.patch(E, json={"departments": {"mkt": {"name": "Marketing"}, "ops": {"name": "Operations"}}}
                        ).status_code == 200
    for pid, to, dept, agent in (("boss", None, "", BOSS), ("head", "boss", "mkt", HEAD), ("writer", "head", "mkt", WRITER),
                                 ("editor", "head", "mkt", EDITOR), ("ops", "boss", "ops", OPS), ("clerk", "ops", "ops", None)):
        r = client.post(f"{E}/positions", json={"id": pid, "title": pid.title(), "reports_to": to, "department": dept,
                                                 **({"agent": agent} if agent else {})})
        assert r.status_code == 200, r.text
    return client


def _set(client, **f):
    assert client.patch(E, json=f).status_code == 200


def _raw_grants(grants):
    """Grants as an edited file would hold them (the API refuses bad ones): the runtime must still ignore them."""
    p = enterprises.folder(SLUG) / enterprises.FILE
    d = json.loads(p.read_text(encoding="utf-8"))
    d["grants"] = grants
    p.write_text(json.dumps(d), encoding="utf-8")
    enterprises.invalidate(SLUG)


def _autonomy(client, v):
    _set(client, settings={"autonomy": v})


def _msgs(pos, kind=None):
    return [m for m in enterprises.inbox(SLUG, pos) if kind is None or m["kind"] == kind]


# ---- the decider matrix ---------------------------------------------------------------------------------------
MATRIX = {                                  # category: (careful, balanced, autonomous), written out on purpose
    "assign_own": ("free", "free", "free"), "deliver_cross": ("owner", "lead", "lead"),
    "assign_cross": ("owner", "lead", "lead"), "edit_job": ("owner", "lead", "lead"), "worker": ("owner", "lead", "lead"),
    "profile_edit": ("owner", "lead", "lead"), "raise_budget": ("owner", "owner", "lead"),
    "reseat": ("owner", "owner", "lead"), "profile_terms": ("owner",) * 3, "desk_live": ("owner",) * 3,
    "hire_remove": ("owner",) * 3, "spending_high": ("owner",) * 3, "recurring": ("owner",) * 3, "publish": ("owner",) * 3,
}


def test_decider_matrix_per_profile(ent):
    assert set(MATRIX) | {"spending"} == set(pol.CATEGORIES)
    for i, profile in enumerate(pol.PROFILES):
        _autonomy(ent, profile)
        for cat, row in MATRIX.items():
            assert pol.decider(SLUG, "writer", cat) == row[i], (profile, cat)
        # the top of the chart has no lead: a "lead" row is the owner's
        for cat, row in MATRIX.items():
            assert pol.decider(SLUG, "boss", cat) == ("owner" if row[i] == "lead" else row[i]), (profile, cat)


def test_spending_threshold_and_department_override(ent):
    _set(ent, departments={"mkt": {"name": "Marketing", "envelope": {"usd_per_day": 20}}, "ops": {"name": "Operations"}})
    _autonomy(ent, "balanced")
    assert pol.decider(SLUG, "writer", "spending", amount=10) == "lead"
    assert pol.decider(SLUG, "writer", "spending", amount=20) == "lead"
    assert pol.decider(SLUG, "writer", "spending", amount=21) == "owner"      # above the threshold: spending_high
    assert pol.decider(SLUG, "writer", "spending") == "owner"                 # undeclared
    assert pol.decider(SLUG, "ops", "spending", amount=1) == "owner"          # no threshold known for operations
    _autonomy(ent, "careful")
    assert pol.decider(SLUG, "writer", "spending", amount=10) == "owner"
    _set(ent, settings={"autonomy": "careful"}, departments={"mkt": {"name": "Marketing", "envelope": {"usd_per_day": 20},
                                                                     "settings": {"autonomy": "autonomous"}},
                                                             "ops": {"name": "Operations"}})
    assert pol.decider(SLUG, "writer", "edit_job") == "lead"                  # the department's profile wins
    assert pol.decider(SLUG, "ops", "edit_job") == "owner"


def test_invariant_outside_text_is_always_the_owners(ent):
    _autonomy(ent, "autonomous")
    for cat in pol.CATEGORIES:
        assert pol.decider(SLUG, "writer", cat, amount=1, outside=True) == "owner", cat
    r = pol.request(SLUG, "writer", "assign_own", "Hand a task to the editor", outside=True)
    assert r["status"] == "pending" and r["decider"] == "owner" and r["outside"] is True
    assert pol.decider(SLUG, "writer", "no-such-category") == "owner"


def test_invariant_nobody_decides_their_own_request(ent):
    r = pol.request(SLUG, "head", "edit_job", "Rewrite the writer's job")
    assert r["decider"] == "boss"
    with pytest.raises(enterprises.EnterpriseError) as e:
        pol.decide(SLUG, r["id"], "allow", by="head")
    assert e.value.code == "self_decision" and e.value.status == 403
    assert pol.requests(SLUG)[0]["status"] == "pending"


def test_invariant_a_lead_decides_only_its_subtree(ent):
    r = pol.request(SLUG, "writer", "edit_job", "Change the editor's job")
    assert r["decider"] == "head"
    for who in ("ops", "editor"):               # a peer, the lead of another department
        with pytest.raises(enterprises.EnterpriseError) as e:
            pol.decide(SLUG, r["id"], "allow", by=who)
        assert e.value.code == "not_in_subtree"
    with pytest.raises(enterprises.EnterpriseError) as e:       # an ancestor, but the request waits for head
        pol.decide(SLUG, r["id"], "allow", by="boss")
    assert e.value.code == "not_decider"
    assert pol.decide(SLUG, r["id"], "deny", by="head", reason="no")["status"] == "denied"


def test_invariant_owner_rows_are_never_delegable(ent):
    _autonomy(ent, "autonomous")
    until = time.time() + 5 * 86400
    _set(ent, grants=[{"id": "g1", "position": "head", "category": "publish", "ceiling": None, "until": until},
                      {"id": "g2", "position": "head", "category": "hire_remove", "ceiling": None, "until": until},
                      {"id": "g3", "position": "head", "category": "spending_high", "ceiling": 100, "until": until}])
    for cat in ("publish", "hire_remove"):
        assert pol.decider(SLUG, "writer", cat) == "owner"
    assert pol.decider(SLUG, "writer", "spending_high", amount=5) == "owner"
    r = pol.request(SLUG, "writer", "publish", "Post the launch on the public blog")
    assert r["decider"] == "owner"
    with pytest.raises(enterprises.EnterpriseError) as e:
        pol.decide(SLUG, r["id"], "allow", by="head")
    assert e.value.code == "not_decider"


def test_grant_bounds(ent):
    _set(ent, departments={"mkt": {"name": "Marketing", "envelope": {"usd_per_day": 20}}, "ops": {"name": "Operations"}})
    _autonomy(ent, "careful")
    now = time.time()

    def grant(**kw):
        g = {"id": "g1", "position": "head", "category": "spending", "ceiling": 50, "until": now + 5 * 86400, **kw}
        _raw_grants([g])

    grant()
    assert pol.decider(SLUG, "writer", "spending", amount=40) == "lead"       # above the threshold, inside the ceiling
    assert pol._route(SLUG, "writer", "spending", 40, False)[1] == "head"
    assert pol.decider(SLUG, "writer", "spending", amount=60) == "owner"      # above the ceiling
    assert pol.decider(SLUG, "writer", "spending") == "owner"                 # undeclared
    grant(until=now - 10)
    assert pol.decider(SLUG, "writer", "spending", amount=40) == "owner"      # ended
    grant(until=now + 60 * 86400)
    assert pol.decider(SLUG, "writer", "spending", amount=40) == "owner"      # longer than 30 days
    grant(until=None)
    assert pol.decider(SLUG, "writer", "spending", amount=40) == "owner"      # no end
    grant(position="writer")
    assert pol.decider(SLUG, "writer", "spending", amount=40) == "owner"      # nobody grants itself
    grant(position="editor")
    assert pol.decider(SLUG, "writer", "spending", amount=40) == "owner"      # a peer is not above the requester
    grant(position="ops")
    assert pol.decider(SLUG, "writer", "spending", amount=40) == "owner"      # another subtree
    grant(category="edit_job", ceiling=None)
    assert pol.decider(SLUG, "writer", "edit_job") == "lead"                  # a lead row in autonomous can be delegated
    grant(category="edit_job", ceiling=None, until=time.strftime("%Y-%m-%d", time.gmtime(now + 3 * 86400)))
    assert pol.decider(SLUG, "writer", "edit_job") == "lead"                  # a date works too
    grant(category="raise_budget", ceiling=None, position="boss")
    assert pol.decider(SLUG, "writer", "raise_budget") == "lead"
    assert pol._route(SLUG, "writer", "raise_budget", None, False)[1] == "boss"
    assert pol.decider(SLUG, "writer", "raise_budget", outside=True) == "owner"


# ---- request lifecycle ----------------------------------------------------------------------------------------
def test_free_request_is_allowed_and_logged(ent):
    r = pol.request(SLUG, "writer", "assign_own", "Ask nobody")
    assert r["status"] == "allowed" and r["decider"] == "free" and r["decided_by"] == "policy"
    log = enterprises.decisions(SLUG)[0]
    assert any(x["kind"] == "request_allowed" and x["position"] == "writer" for x in log)
    assert ent.get(f"{E}/requests").json()["items"][0]["id"] == r["id"]


def test_lead_request_reaches_its_inbox_and_the_lead_decides(ent):
    r = pol.request(SLUG, "writer", "edit_job", "Make the editor's job shorter", session="s1")
    assert r["decider"] == "head" and r["status"] == "pending" and r["deadline"] > time.time()
    got = _msgs("head", "request")
    assert got and r["id"] in got[-1]["text"] and got[-1]["from"] == "writer"
    d = pol.decide(SLUG, r["id"], "allow", reason="fine", by="head")
    assert d["status"] == "allowed" and d["decided_by"] == "head"
    back = _msgs("writer", "decision")
    assert back and "allowed" in back[-1]["text"] and "fine" in back[-1]["text"]
    with pytest.raises(enterprises.EnterpriseError) as e:
        pol.decide(SLUG, r["id"], "deny", by=None)
    assert e.value.status == 409 and e.value.code == "not_pending"
    assert any(x["kind"] == "request_allowed" and x["by"] == "head" for x in enterprises.decisions(SLUG)[0])


def test_allow_never_grants(ent):
    _autonomy(ent, "autonomous")
    r = pol.request(SLUG, "writer", "deliver_cross", "Drop a file into the operations folder")
    pol.decide(SLUG, r["id"], "allow", by="head")
    assert "grants nothing" in _msgs("writer", "decision")[-1]["text"]
    r = pol.request(SLUG, "writer", "assign_cross", "Give the ops lead a task")
    pol.decide(SLUG, r["id"], "deny", by="head", reason="not now")
    assert "grants nothing" not in _msgs("writer", "decision")[-1]["text"]


def _card(r):
    return feed.find(f"enterprise:{SLUG}:{r['id']}")


def test_owner_request_card_and_feed_buttons(ent, mx):
    r = pol.request(SLUG, "writer", "publish", "Post the launch on the public blog")
    assert r["decider"] == "owner" and r["status"] == "pending"
    ev = _card(r)
    assert ev and ev["source"] == "enterprises" and {a["id"] for a in ev["actions"]} == {"allow", "deny", "open"}
    assert feed._alert_rule(ev) == "loud"
    assert ent.post(f"/api/feed/{ev['id']}/act/open").status_code == 200
    assert pol.requests(SLUG)[0]["status"] == "pending"
    assert ent.post(f"/api/feed/{ev['id']}/act/allow").status_code == 200
    assert pol.requests(SLUG)[0]["status"] == "allowed" and pol.requests(SLUG)[0]["decided_by"] == "owner"
    assert feed.get(ev["id"])["resolved"]
    assert "allowed" in _msgs("writer", "decision")[-1]["text"]
    # deny, and a second click is harmless
    r2 = pol.request(SLUG, "editor", "recurring", "A monthly tool subscription")
    ev2 = _card(r2)
    assert ent.post(f"/api/feed/{ev2['id']}/act/deny").status_code == 200
    assert pol.requests(SLUG)[0]["status"] == "denied"
    assert ent.post(f"/api/feed/{ev2['id']}/act/deny").status_code == 200
    assert "denied" in _msgs("editor", "decision")[-1]["text"]


def test_route_decision_and_list(ent):
    r = pol.request(SLUG, "writer", "publish", "Announce the price list")
    assert ent.get(f"{E}/requests").json()["items"][0]["status"] == "pending"
    bad = ent.post(f"{E}/requests/{r['id']}", json={"decision": "maybe"})
    assert bad.status_code == 422
    assert ent.post(f"{E}/requests/nope", json={"decision": "allow"}).json()["error"] == "not_found"
    ok = ent.post(f"{E}/requests/{r['id']}", json={"decision": "deny", "reason": "later"})
    assert ok.status_code == 200 and ok.json()["status"] == "denied" and ok.json()["reason"] == "later"
    assert ent.post(f"{E}/requests/{r['id']}", json={"decision": "allow"}).json()["error"] == "not_pending"
    assert feed.get(feed.find(f"enterprise:{SLUG}:{r['id']}", open_only=False)["id"])["resolved"]
    ent.put("/api/settings", json={"enterprises_page": False})
    assert ent.get(f"{E}/requests").json()["error"] == "feature_off"
    assert ent.post(f"{E}/requests/{r['id']}", json={"decision": "allow"}).json()["error"] == "feature_off"


def test_bad_requests_are_refused(ent):
    for args, code in (((SLUG, "nobody", "publish", "x"), "bad_position"), ((SLUG, "writer", "nonsense", "x"), "bad_category"),
                       ((SLUG, "writer", "publish", "  "), "invalid")):
        with pytest.raises(enterprises.EnterpriseError) as e:
            pol.request(*args)
        assert e.value.code == code
    with pytest.raises(enterprises.EnterpriseError):
        pol.request(SLUG, "writer", "spending", "ads", amount=-3)
    assert pol.requests(SLUG) == []


# ---- climbing -------------------------------------------------------------------------------------------------
def test_request_climbs_on_timeout(ent):
    _set(ent, settings={"escalation_timeout_h": 1})
    r = pol.request(SLUG, "writer", "edit_job", "Shorten a job")
    assert r["decider"] == "head"
    pol.tick(now=r["at"] + 1800)
    assert pol.requests(SLUG)[0]["decider"] == "head"                          # not yet
    pol.tick(now=r["at"] + 3700)
    cur = pol.requests(SLUG)[0]
    assert cur["decider"] == "boss" and cur["level"] == 1 and cur["deadline"] > r["at"] + 3700
    assert _msgs("boss", "request")
    pol.tick(now=r["at"] + 7500)
    cur = pol.requests(SLUG)[0]
    assert cur["decider"] == "owner" and cur["status"] == "pending" and cur["deadline"] is None
    ev = _card(r)
    assert ev and ev["source"] == "enterprises"
    assert any(x["kind"] == "request_climbed" for x in enterprises.decisions(SLUG)[0])
    pol.tick(now=r["at"] + 99999)
    assert pol.requests(SLUG)[0]["decider"] == "owner"                         # the owner's clock does not run
    with pytest.raises(enterprises.EnterpriseError):
        pol.decide(SLUG, r["id"], "allow", by="head")                          # it left head's hands
    assert pol.decide(SLUG, r["id"], "allow")["status"] == "allowed"


def test_a_lead_that_cannot_decide_is_skipped(ent):
    agents.update(HEAD, {"enabled": False})
    r = pol.request(SLUG, "writer", "edit_job", "Shorten a job")
    assert r["decider"] == "boss"
    assert any(x["kind"] == "request_skipped" for x in enterprises.decisions(SLUG)[0])
    agents.update(BOSS, {"enabled": False})
    assert pol.request(SLUG, "writer", "edit_job", "Another")["decider"] == "owner"


def test_tick_drops_ended_grants_and_waits_while_off(ent):
    now = time.time()
    _raw_grants([{"id": "old", "position": "head", "category": "edit_job", "ceiling": None, "until": now - 5},
                 {"id": "live", "position": "head", "category": "edit_job", "ceiling": None, "until": now + 86400}])
    pol.tick(now=now)
    assert [g["id"] for g in ent.get(E).json()["grants"]] == ["live"]
    assert any(x["kind"] == "grant_expired" for x in enterprises.decisions(SLUG)[0])
    ent.put("/api/settings", json={"enterprises_page": False})
    pol.tick(now=now + 10 * 86400)                                              # off: nothing runs
    ent.put("/api/settings", json={"enterprises_page": True})
    assert [g["id"] for g in ent.get(E).json()["grants"]] == ["live"]


# ---- envelopes: budget ----------------------------------------------------------------------------------------
def _flush_alerts():
    import threading
    for t in threading.enumerate():
        if t.name == "enterprise-envelope-alert":
            t.join(5)


def _costs(monkeypatch, table):
    monkeypatch.setattr(agents, "day_cost", lambda path, when=None, **kw: table.get(path, 0.0))


def test_department_ceiling_gate_cap_and_one_notification(ent, monkeypatch):
    _set(ent, departments={"mkt": {"name": "Marketing", "envelope": {"usd_per_day": 1}}, "ops": {"name": "Operations"}})
    _costs(monkeypatch, {WRITER: 0.5, EDITOR: 0.2})
    assert pol.over_ceiling(WRITER) is None and agents.gate(WRITER) is None
    assert pol.cap(WRITER, 5.0) == pytest.approx(0.3) and pol.cap(WRITER, 0.1) == 0.1
    args = agents.run_settings(WRITER)["args"]                                # capped below its own budget
    assert args[args.index("--max-budget-usd") + 1] == "0.30"
    assert "0.30" not in agents.run_settings(OPS)["args"]                     # another department: not capped
    _costs(monkeypatch, {WRITER: 0.7, EDITOR: 0.4})
    assert "Marketing" in pol.over_ceiling(WRITER)
    assert agents.gate(WRITER) == "envelope" and agents.gate(EDITOR) == "envelope" and agents.gate(OPS) is None
    assert agents.SKIP_TEXT["envelope"]
    assert pol.cap(WRITER, 5.0) == 0.01
    for _ in range(3):
        pol.over_ceiling(EDITOR)
    _flush_alerts()
    evs = [e for e in feed.list_events(source="enterprises")["events"] if "daily budget" in e["title"]]
    assert len(evs) == 1                                                       # once per envelope per day
    r = agents.fire(WRITER, trigger="manual", prompt="NOTOOL hi")
    assert r["started"] is False and r["reason"] == "envelope"


def test_enterprise_ceiling_counts_every_member_and_holds(ent, monkeypatch):
    _set(ent, envelope={"usd_per_day": 2})
    _costs(monkeypatch, {WRITER: 0.5, OPS: 0.6, BOSS: 0.4})
    assert pol.cap(OPS, 9.0) == pytest.approx(0.5)
    assert agents.gate(EDITOR) is None
    monkeypatch.setattr(agents, "_held", lambda st, but=None: 0.5)           # runs in progress hold the rest
    assert agents.gate(EDITOR) == "busy" and pol.ceiling_held(EDITOR)
    assert pol.cap(OPS, 9.0) == 0.01
    ent.put("/api/settings", json={"enterprises_page": False})
    assert pol.over_ceiling(WRITER) is None and pol.cap(OPS, 9.0) == 9.0 and not pol.has_ceiling(OPS)


# ---- envelopes: keys and domains ------------------------------------------------------------------------------
def test_exceeds_envelope_and_over_envelope(ent):
    _set(ent, envelope={"keys": ["K1"], "domains": ["*.example.com", "api.other.org"]})
    url = "/api/agents/acme/blog/writer"
    r = ent.patch(url, json={"domains": ["evil.net"]})
    assert r.status_code == 400 and r.json()["error"] == "exceeds_envelope" and "evil.net" in r.json()["message"]
    r = ent.patch(url, json={"keys": ["K2"]})
    assert r.status_code == 400 and r.json()["error"] == "exceeds_envelope"
    assert ent.patch(url, json={"domains": ["api.example.com", "https://api.other.org/"], "keys": ["K1"]}).status_code == 200
    assert ent.patch(url, json={"domains": ["*.example.com"]}).status_code == 200
    assert ent.patch(url, json={"domains": ["example.com.evil.net"]}).status_code == 400
    assert ent.patch("/api/agents/acme/blog/editor", json={"domains": ["x.com"]}).status_code == 400
    # a department's own list binds tighter than the enterprise's
    _set(ent, departments={"mkt": {"name": "Marketing", "envelope": {"domains": ["api.example.com"]}},
                           "ops": {"name": "Operations"}})
    assert ent.patch(url, json={"domains": ["api.example.com", "docs.example.com"]}).status_code == 400
    # narrowing never edits an agent: it is flagged, and what it already had stays allowed
    assert pol.over_envelope(SLUG) == [{"position": "writer", "what": "domains: *.example.com"}]
    assert agents.load(WRITER)["domains"] == ["*.example.com"]
    assert ent.patch(url, json={"domains": ["*.example.com"], "approvals": True}).status_code == 200   # no widening
    assert ent.patch(url, json={"domains": []}).status_code == 200
    assert pol.over_envelope(SLUG) == []
    # off: no check
    ent.put("/api/settings", json={"enterprises_page": False})
    assert ent.patch(url, json={"domains": ["evil.net"]}).status_code == 200


def test_apply_change_follows_the_envelope(ent):
    _set(ent, envelope={"domains": ["*.example.com"]})
    with pytest.raises(agents.AgentError) as e:
        agents.apply_change(WRITER, {"domains": {"add": ["evil.net"], "remove": []}})
    assert e.value.code == "exceeds_envelope"
    agents.apply_change(WRITER, {"domains": {"add": ["ok.example.com"], "remove": []}})
    assert agents.load(WRITER)["domains"] == ["ok.example.com"]


# ---- communication --------------------------------------------------------------------------------------------
def test_can_send_in_the_three_modes(ent):
    _set(ent, settings={"communication": "strict"})
    assert pol.can_send(WRITER, HEAD) is None and pol.can_send(HEAD, WRITER) is None     # lead and report
    msg = pol.can_send(WRITER, EDITOR)
    assert msg and "Head" in msg and "strict" in msg                                      # names who to go through
    assert pol.can_send(HEAD, OPS)
    assert pol.can_send(WRITER, OPS)
    _set(ent, settings={"communication": "leads"})
    assert pol.can_send(HEAD, OPS) is None and pol.can_send(OPS, HEAD) is None            # lead to lead
    assert pol.can_send(WRITER, EDITOR) and pol.can_send(WRITER, OPS)
    _set(ent, settings={"communication": "open"})
    assert pol.can_send(WRITER, EDITOR)
    _set(ent, settings={"communication": "open", "allow": [["editor", "writer"]]})
    assert pol.can_send(WRITER, EDITOR) is None and pol.can_send(EDITOR, WRITER) is None
    assert pol.can_send(WRITER, OPS)
    # a department can speak differently
    _set(ent, settings={"communication": "strict"}, departments={
        "mkt": {"name": "Marketing", "settings": {"communication": "open", "allow": [["writer", "ops"]]}},
        "ops": {"name": "Operations"}})
    assert pol.can_send(WRITER, OPS) is None
    # outside the enterprise, no sender, the feature off: never refused
    assert pol.can_send("projects/zz/topics/t/agents/x", WRITER) is None and pol.can_send("", WRITER) is None
    assert pol.can_send(WRITER, "projects/zz/topics/t/agents/x") is None
    _set(ent, settings={"communication": "strict"})
    ent.put("/api/settings", json={"enterprises_page": False})
    assert pol.can_send(WRITER, EDITOR) is None


def test_agents_send_is_refused_between_peers(ent, capsys, monkeypatch):
    monkeypatch.setattr(bus, "_loop", None)
    _set(ent, settings={"communication": "strict"})
    monkeypatch.setenv("MAXXING_AGENT", WRITER)
    monkeypatch.setenv("MAXXING_AGENT_DEPTH", "0")
    assert cli.main(["agents", "send", "editor", "NOTOOL hello"]) == 2
    err = capsys.readouterr().err
    assert "strict" in err and "Head" in err
    assert not [m for m in agents.thread(EDITOR) if m["kind"] == "run"]
    assert cli.main(["agents", "send", "head", "NOTOOL hello", "--json"]) == 0           # its own lead
    r = json.loads(capsys.readouterr().out)
    wait_idle(ent, r["session"])
    _set(ent, settings={"communication": "open", "allow": [["writer", "editor"]]})
    assert cli.main(["agents", "send", "editor", "NOTOOL hello", "--json"]) == 0
    wait_idle(ent, json.loads(capsys.readouterr().out)["session"])
    _set(ent, settings={"communication": "strict"})
    assert cli.main(["agents", "run", "editor", "NOTOOL again"]) == 2                    # `run` is a send too


# ---- trust along the chain ------------------------------------------------------------------------------------
def test_trusted_delivery(ent):
    assert pol.trusted_delivery(SLUG, False) is False                                   # off by default
    _set(ent, settings={"trust_chain": True})
    assert pol.trusted_delivery(SLUG, False) is True
    assert pol.trusted_delivery(SLUG, True) is False                                    # an outside run in the chain


# ---- the source is the product's ------------------------------------------------------------------------------
def test_agents_cannot_post_as_the_enterprise(ent, monkeypatch):
    assert "enterprises" in feed.PRODUCT_SOURCES
    monkeypatch.setenv("MAXXING_AGENT", WRITER)
    monkeypatch.setenv("MAXXING_AGENT_DEPTH", "0")
    assert cli.main(["feed", "post", "Pay the invoice", "--source", "enterprises"]) == 2
    assert feed.list_events(source="enterprises")["events"] == []
    monkeypatch.delenv("MAXXING_AGENT")
    assert feed.HANDLERS["enterprise"] == "enterprise_policy"


# ---- reserved ids, outside mark, overrides, grants, workers, shares ------------------------------------------
def test_a_position_named_owner_has_no_owner_right(ent):
    for pid in ("owner", "server", "policy", "visitor", "free", "esc", "none"):
        r = ent.post(f"{E}/positions", json={"id": pid, "title": pid})
        assert r.status_code == 400 and r.json()["error"] == "invalid", pid
    assert enterprises.clean({"positions": [{"id": "owner"}, {"id": "ok"}]})["positions"][0]["id"] == "ok"
    r = pol.request(SLUG, "writer", "edit_job", "Change a job")
    with pytest.raises(enterprises.EnterpriseError) as e:
        pol.decide(SLUG, r["id"], "allow", by="owner")
    assert e.value.status == 403


def test_decision_carries_the_outside_mark_of_the_deciding_run(ent):
    r = pol.request(SLUG, "writer", "edit_job", "Another job")
    pol.decide(SLUG, r["id"], "allow", by="head", outside=True)
    assert _msgs("writer", "decision")[-1]["outside"] is True


def test_department_overrides_are_whitelisted(ent):
    r = ent.patch(E, json={"departments": {"mkt": {"name": "M", "settings": {"trust_chain": True}}}})
    assert r.status_code == 400 and r.json()["error"] == "invalid"
    assert ent.patch(E, json={"departments": {"mkt": {"name": "M", "settings": {"autonomy": "careful"}}}}).status_code == 200


def test_grants_are_validated_and_logged(ent):
    g = {"id": "g1", "position": "head", "category": "edit_job", "ceiling": None}
    assert ent.patch(E, json={"grants": [{**g, "until": time.time() + 60 * 86400}]}).status_code == 400
    assert ent.patch(E, json={"grants": [{**g, "position": "nobody", "until": time.time() + 86400}]}).status_code == 400
    assert ent.patch(E, json={"grants": [{**g, "until": time.time() + 86400}]}).status_code == 200
    assert any(x["kind"] == "grant" and "g1 made" in x["text"] for x in enterprises.decisions(SLUG)[0])
    assert ent.patch(E, json={"grants": []}).status_code == 200
    assert any(x["kind"] == "grant" and "g1 revoked" in x["text"] for x in enterprises.decisions(SLUG)[0])


def test_allowed_request_applies_or_says_the_owner_does(ent):
    r = pol.request(SLUG, "head", "edit_job", "New job", payload={"position": "writer", "job": "Write posts"})
    pol.decide(SLUG, r["id"], "allow")
    assert enterprises.position(SLUG, "writer")["job"] == "Write posts"
    _autonomy(ent, "autonomous")
    r = pol.request(SLUG, "writer", "raise_budget", "More money")
    pol.decide(SLUG, r["id"], "allow", by="head")
    assert "the owner applies it" in _msgs("writer", "decision")[-1]["text"]


def test_worker_spending_counts_in_the_envelope(ent, monkeypatch):
    from maxxing import enterprise_workers as ew
    _set(ent, departments={"mkt": {"name": "Marketing", "envelope": {"usd_per_day": 1}}, "ops": {"name": "Operations"}})
    _costs(monkeypatch, {})
    w = P + "writer-w1"
    monkeypatch.setattr(ew, "seat_of_worker", lambda path: (SLUG, "writer") if path == w else None, raising=False)
    monkeypatch.setattr(ew, "cost_today", lambda slug, pos=None: 1.5, raising=False)
    monkeypatch.setattr(agents, "exists", lambda p, _e=agents.exists: True if p == w else _e(p))
    assert "Marketing" in pol.over_ceiling(w) and "Marketing" in pol.over_ceiling(WRITER)
    _flush_alerts()


def test_budgetless_agent_holds_a_bounded_share(ent, monkeypatch):
    _set(ent, departments={"mkt": {"name": "Marketing", "envelope": {"usd_per_day": 5}}, "ops": {"name": "Operations"}})
    _costs(monkeypatch, {})
    agents.update(WRITER, {"limits": {"usd_per_day": 0}})
    assert pol.cap(WRITER, float("inf")) == pol.UNBUDGETED_RUN_USD
    args = agents.run_settings(WRITER)["args"]
    assert args[args.index("--max-budget-usd") + 1] == "0.50"
    _set(ent, departments={"mkt": {"name": "Marketing"}, "ops": {"name": "Operations"}})
    assert "--max-budget-usd" not in agents.run_settings(WRITER)["args"]


def test_blocked_state_and_requester_reassigned(ent):
    import json as _j
    f = enterprises.state(SLUG) / "flow.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_j.dumps({"waits": {"writer": {"since": 1, "why": "budget"}}}), encoding="utf-8")
    p = next(x for x in enterprises.get(SLUG)["positions"] if x["id"] == "writer")
    assert p["state"] == "blocked" and p["blocked_reason"] == "budget"
    from maxxing.api import tasks as tasks_api
    t = tasks_api.add_task({"title": "T", "enterprise": {"id": SLUG, "owner": "ops", "requester": "head"}})
    ent.request  # noqa: B018
    enterprises.remove_position(SLUG, "head", reparent_to="boss")
    assert tasks_api.get_task(t["id"])["enterprise"]["requester"] == "boss"
