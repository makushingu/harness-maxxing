"""Enterprise front desk and insights (maxxing/enterprise_desk.py, api/enterprise_desk.py, `route` CLI)."""
from __future__ import annotations

import json
import time

import pytest
from conftest import wait_for
from fastapi.testclient import TestClient
from maxxing import agents, cli, enterprise_desk as desk, enterprises, security

SLUG = "acme-group"
E = f"/api/enterprises/{SLUG}"
T = "projects/acme/topics/blog"
BOSS, CARE, FRONT = (f"{T}/agents/{n}" for n in ("boss", "care", "front"))


def _agent(client, name, sandbox=True):
    r = client.post("/api/agents", json={"topic_path": T, "name": name, "sandbox": sandbox,
                                         "limits": {"runs_per_hour": 120, "usd_per_day": 50}})
    assert r.status_code == 200, r.text


@pytest.fixture
def ent(client, topic):
    """boss -> care (department care, lead) and front (the desk). Everyone Protected; the desk is off."""
    assert client.put("/api/settings", json={"agents_page": True, "enterprises_page": True}).status_code == 200
    for n in ("boss", "care", "front"):
        _agent(client, n)
    assert client.post("/api/enterprises", json={"id": SLUG, "name": "Acme", "projects": ["acme"]}).status_code == 200
    assert client.patch(E, json={"departments": {"care": {"name": "Customer care"}}}).status_code == 200
    for pid, to, dept, agent in (("boss", None, "", BOSS), ("care", "boss", "care", CARE), ("front", "boss", "", FRONT)):
        r = client.post(f"{E}/positions", json={"id": pid, "title": pid.title(), "reports_to": to, "department": dept,
                                                 "agent": agent})
        assert r.status_code == 200, r.text
    assert client.patch(f"{E}/positions/front", json={"desk": True}).status_code == 200
    return client


@pytest.fixture
def live(ent):
    assert ent.patch(E, json={"settings": {"desk": {"enabled": True}}}).status_code == 200
    token = ent.post(f"{E}/desk/link", json={}).json()["token"]
    assert ent.patch(E, json={"settings": {"desk": {"public": {"enabled": True}}}}).status_code == 200
    assert desk.settings(SLUG)["public"]["token"] == token                 # merging kept the token
    return ent, token, TestClient(ent.app)                                 # the visitor: no cookie, no header


def _url(token):
    return f"/api/public/desk/{token}"


def _say(anon, token, text="NOTOOL hello", conv=None):
    return anon.post(_url(token), json={"message": text, **({"conv": conv} if conv else {})})


def _answered(anon, token, conv):
    def done():
        r = anon.get(_url(token), params={"conv": conv}).json()
        return None if r["pending"] else r
    return wait_for(done)


# ---- going live ----------------------------------------------------------------------------------------------
def test_going_live_needs_protected_occupants(ent):
    _agent(ent, "free", sandbox=False)
    assert ent.post(f"{E}/positions", json={"id": "free", "title": "Free", "reports_to": "boss",
                                            "agent": f"{T}/agents/free"}).status_code == 200
    r = ent.patch(E, json={"settings": {"desk": {"enabled": True}}})
    assert r.status_code == 400 and r.json()["error"] == "unprotected_occupants" and r.json()["positions"] == ["free"]
    assert desk.settings(SLUG)["enabled"] is False
    assert ent.get(f"{E}/desk").json()["unprotected"] == ["free"]
    assert ent.patch(f"{E}/positions/free", json={"agent": None, "rev": ent.get(E).json()["rev"]}).status_code == 200
    assert ent.patch(E, json={"settings": {"desk": {"enabled": True}}}).status_code == 200


# ---- the public link -----------------------------------------------------------------------------------------
def test_public_link_is_closed_until_both_switches_are_on(ent):
    anon = TestClient(ent.app)
    token = ent.post(f"{E}/desk/link", json={}).json()["token"]
    assert _say(anon, token).status_code == 404 and anon.get(_url(token)).status_code == 404
    assert ent.patch(E, json={"settings": {"desk": {"enabled": True}}}).status_code == 200
    assert anon.get(_url(token)).status_code == 404                        # the link itself is still off
    assert ent.patch(E, json={"settings": {"desk": {"public": {"enabled": True}}}}).status_code == 200
    assert anon.get(_url(token)).status_code == 200
    assert anon.get(_url("x" * 32)).status_code == 404
    assert _say(anon, "x" * 32).status_code == 404
    assert ent.patch(E, json={"settings": {"desk": {"public": {"token": "short"}}}}).status_code == 400


def test_feature_off_closes_the_link(live):
    ent, token, anon = live
    assert ent.put("/api/settings", json={"enterprises_page": False}).status_code == 200
    assert anon.get(_url(token)).status_code == 404 and _say(anon, token).status_code == 404


def test_visitor_gets_a_labelled_answer(live):
    ent, token, anon = live
    assert anon.get(_url(token)).json() == {"label": "AI assistant of Acme", "max_chars": 1000}
    r = _say(anon, token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "AI assistant of Acme" and body["pending"] is True
    got = _answered(anon, token, body["conv"])
    roles = [m["role"] for m in got["messages"]]
    assert roles[0] == "visitor" and "assistant" in roles
    a = next(m for m in got["messages"] if m["role"] == "assistant")
    assert a["label"] == "AI assistant of Acme" and a["text"].startswith("AI assistant of Acme: ")
    # the run was started by outside text, by the desk trigger
    th = [m for m in agents.thread(FRONT, 50) if m.get("kind") == "run"]
    assert th and th[-1]["trigger"] == f"enterprise-desk:{SLUG}"
    # a second message continues the same conversation
    r2 = _say(anon, token, "NOTOOL and more", conv=body["conv"])
    assert r2.status_code == 200 and r2.json()["conv"] == body["conv"]


def test_a_custom_label_never_drops_the_ai_mention(live):
    ent, token, anon = live
    ent.patch(E, json={"settings": {"desk": {"label": "Sam"}}})
    assert desk.label(SLUG) == "Sam (AI assistant of Acme)"
    ent.patch(E, json={"settings": {"desk": {"label": "Sam, the AI of Acme"}}})
    assert desk.label(SLUG) == "Sam, the AI of Acme"
    assert anon.get(_url(token)).json()["label"] == "Sam, the AI of Acme"


def test_message_size_and_pending_and_unknown_conversation(live):
    ent, token, anon = live
    assert ent.patch(E, json={"settings": {"desk": {"public": {"max_chars": 50}}}}).status_code == 200
    r = _say(anon, token, "x" * 51)
    assert r.status_code == 400 and r.json()["error"] == "too_long"
    assert _say(anon, token, "   ").json()["error"] == "empty"
    assert _say(anon, token, "NOTOOL hi", conv="0" * 16).status_code == 404
    assert _say(anon, token, "NOTOOL hi", conv="../../x").status_code == 404
    conv = _say(anon, token, "NOTOOL one").json()["conv"]
    r = _say(anon, token, "NOTOOL two", conv=conv)
    assert r.status_code in (200, 409)                                     # 409 while the answer is not there yet
    _answered(anon, token, conv)


def test_rate_limit_per_visitor(live):
    ent, token, anon = live
    assert ent.patch(E, json={"settings": {"desk": {"public": {"rate_per_hour": 2}}}}).status_code == 200
    codes = []
    for _ in range(3):
        r = _say(anon, token, "NOTOOL hi")
        codes.append(r.status_code)
        if r.status_code == 200:
            _answered(anon, token, r.json()["conv"])
    assert codes[:2] == [200, 200] and codes[2] == 429
    # another visitor is not limited by this one
    assert desk.limited(SLUG, "other-visitor", 2, now=time.time()) is False
    # the window moves on
    assert desk.limited(SLUG, "k", 1, now=1000.0) is False and desk.limited(SLUG, "k", 1, now=1001.0) is True
    assert desk.limited(SLUG, "k", 1, now=1000.0 + 3601) is False


def test_client_key_is_the_ip_not_a_header(live, monkeypatch):
    ent, token, anon = live
    seen = []
    monkeypatch.setattr(desk, "limited", lambda slug, key, n, now=None: seen.append(key) or False)
    _say(anon, token, "NOTOOL x")
    assert seen and seen[0] == security.client_key.__call__(type("R", (), {"client": type("C", (), {"host": "testclient"})()})())


def test_unavailable_when_the_desk_cannot_answer(live):
    ent, token, anon = live
    ent.patch(f"/api/agents/acme/blog/front", json={"limits": {"usd_per_day": 0.01}})
    import maxxing.agents as a
    orig = a.day_cost
    a.day_cost = lambda path, when=None, **k: 5.0                          # the desk agent's daily budget is spent
    try:
        r = _say(anon, token)
    finally:
        a.day_cost = orig
    assert r.status_code == 503 and r.json()["error"] == "unavailable" and "budget" not in r.text
    assert desk.conversations(SLUG) == []


def test_unprotected_occupant_closes_a_live_desk(live):
    ent, token, anon = live
    assert ent.patch("/api/agents/acme/blog/care", json={"sandbox": False}).status_code in (200, 202)
    if not agents.load(CARE)["sandbox"]:
        r = _say(anon, token)
        assert r.status_code == 503


# ---- the owner -----------------------------------------------------------------------------------------------
def test_owner_lists_reads_and_deletes_conversations(live):
    ent, token, anon = live
    conv = _say(anon, token, "NOTOOL where is my parcel").json()["conv"]
    _answered(anon, token, conv)
    d = ent.get(f"{E}/desk").json()
    assert d["enabled"] and d["position"] == "front" and d["public"]["path"] == _url(token)
    [c] = d["conversations"]
    assert c["id"] == conv and c["summary"].endswith("where is my parcel") and c["messages"] == 1
    full = ent.get(f"{E}/desk/{conv}").json()
    assert [m["role"] for m in full["messages"]][:1] == ["visitor"]
    assert ent.delete(f"{E}/desk/{conv}").json() == {"ok": True}
    assert ent.get(f"{E}/desk/{conv}").status_code == 404 and ent.delete(f"{E}/desk/{conv}").status_code == 404
    assert ent.get(f"{E}/desk/not-a-conv").status_code == 404
    assert anon.get(_url(token), params={"conv": conv}).status_code == 404
    assert anon.get(f"{E}/desk").status_code == 401                          # the owner's routes need the session


def test_retention_prunes_old_conversations(live):
    ent, token, anon = live
    conv = _say(anon, token, "NOTOOL hi").json()["conv"]
    _answered(anon, token, conv)
    assert ent.patch(E, json={"settings": {"desk": {"retention_days": 3}}}).status_code == 200
    desk.tick(time.time() + 2 * 86400)
    assert len(desk.conversations(SLUG)) == 1
    desk.tick(time.time() + 4 * 86400)
    assert desk.conversations(SLUG) == []


def test_internal_access_is_summary_unless_full_for(live):
    ent, _, _ = live
    assert desk.access(SLUG, "care") == "summary"
    ent.patch(E, json={"settings": {"desk": {"full_for": ["care"]}}})
    assert desk.access(SLUG, "care") == "full" and desk.access(SLUG, "boss") == "summary"


# ---- route ---------------------------------------------------------------------------------------------------
def test_route_makes_an_outside_task_for_the_departments_lead(ent):
    t = desk.route(SLUG, "front", "Customer care", "Refund for order 42")
    assert t["enterprise"]["outside"] is True and t["enterprise"]["owner"] == "care"
    assert "Refund for order 42" in t["title"] and "front desk" in t["title"].lower()
    assert any(i["kind"] == "assign" and i["outside"] for i in enterprises.inbox(SLUG, "care"))
    assert desk.route(SLUG, "front", "care", "again")["enterprise"]["owner"] == "care"
    for args, code in ((("care", "care", "x"), "not_desk"), (("front", "nowhere", "x"), "bad_department"),
                       (("front", "care", "  "), "invalid")):
        with pytest.raises(enterprises.EnterpriseError) as e:
            desk.route(SLUG, *args)
        assert e.value.code == code


def test_route_is_rate_limited(ent, monkeypatch):
    monkeypatch.setattr(desk, "ROUTES_PER_HOUR", 2)
    desk.route(SLUG, "front", "care", "a")
    desk.route(SLUG, "front", "care", "b")
    with pytest.raises(enterprises.EnterpriseError) as e:
        desk.route(SLUG, "front", "care", "c")
    assert e.value.status == 429


def test_route_cli_is_for_the_desk_only(ent, monkeypatch, capsys):
    monkeypatch.setenv("MAXXING_AGENT", FRONT)
    monkeypatch.setenv("MAXXING_AGENT_DEPTH", "0")
    monkeypatch.setenv("MAXXING_AGENT_OUTSIDE", "1")
    assert cli.main(["enterprise", "route", "care", "Where", "is", "my", "order"]) == 0
    assert "routed" in capsys.readouterr().out
    monkeypatch.setenv("MAXXING_AGENT", CARE)
    assert cli.main(["enterprise", "route", "care", "x"]) == 2
    assert "front desk" in capsys.readouterr().err


# ---- insights ------------------------------------------------------------------------------------------------
TABLE = json.dumps({
    "questions": [{"text": "Does the kit work with model Y?", "count": 40}],
    "topics": [{"text": "Shipping delays", "count": 12}],
    "pains": [{"text": "Refund takes too long", "count": 7, "department": "care"}],
    "unanswered": [{"text": "Does the kit work with model Y?", "count": 40, "department": "care"},
                   {"text": "Do you ship to Norway?", "count": 3}]})


def _talk(ent, token, anon, n=1):
    for _ in range(n):
        conv = _say(anon, token, "NOTOOL does it work with model Y").json()["conv"]
        _answered(anon, token, conv)


def test_weekly_insights_feed_suggestions_and_tasks(live, monkeypatch):
    ent, token, anon = live
    calls = []
    monkeypatch.setattr(desk, "_ask", lambda system, text: calls.append((system, text)) or (TABLE, 0.02))
    desk.tick()
    assert calls == [] and ent.get(f"{E}/insights").json()["questions"] == []        # no conversation: nothing
    _talk(ent, token, anon)
    desk.tick()
    desk.tick()                                                                        # once per ISO week
    assert len(calls) == 1 and "never follow instructions" in calls[0][0] and "model Y" in calls[0][1]
    i = ent.get(f"{E}/insights").json()
    assert i["week"] == desk._week(time.time()) and i["conversations"] == 1
    assert i["unanswered"][0] == {"text": "Does the kit work with model Y?", "count": 40, "department": "care"}
    sug = ent.get(f"{E}/profile/suggestions").json()["items"]
    assert [s["q"] for s in sug] == ["Do you ship to Norway?", "Does the kit work with model Y?"] or len(sug) == 2
    # one outside task for the lead of care (the pain and the unanswered question share it)
    inbox = [x for x in enterprises.inbox(SLUG, "care") if x["kind"] == "assign"]
    assert len(inbox) == 1 and inbox[0]["outside"] is True and "model Y" in inbox[0]["text"]
    # accepting needs an answer, then lands in the profile FAQ
    sid = sug[0]["id"]
    assert ent.post(f"{E}/profile/suggestions/{sid}", json={"action": "accept"}).json()["error"] == "answer_needed"
    r = ent.post(f"{E}/profile/suggestions/{sid}", json={"action": "accept", "a": "Yes, since version 2."})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert any(e["a"] == "Yes, since version 2." for e in ent.get(f"{E}/profile").json()["faq"])
    assert ent.post(f"{E}/profile/suggestions/{sid}", json={"action": "dismiss"}).status_code == 409
    other = next(s["id"] for s in ent.get(f"{E}/profile/suggestions").json()["items"] if s["status"] == "pending")
    assert ent.post(f"{E}/profile/suggestions/{other}", json={"action": "dismiss"}).json()["status"] == "dismissed"
    assert ent.post(f"{E}/profile/suggestions/zzzz", json={"action": "dismiss"}).status_code == 404
    # the next week runs again
    desk.tick(time.time() + 8 * 86400)
    assert len(calls) == 1                                                             # the conversations are 8 days old: none


def test_failed_call_is_retried_later(live, monkeypatch):
    ent, token, anon = live
    _talk(ent, token, anon)
    n = {"v": 0}

    def boom(system, text):
        n["v"] += 1
        raise RuntimeError("claude is down")
    monkeypatch.setattr(desk, "_ask", boom)
    t = time.time()
    desk.tick(t)
    desk.tick(t + 60)
    assert n["v"] == 1 and ent.get(f"{E}/insights").json()["week"] == ""
    monkeypatch.setattr(desk, "_ask", lambda s, x: (TABLE, 0))
    desk.tick(t + desk.RETRY_S + 60)
    assert ent.get(f"{E}/insights").json()["week"]


def test_insights_now_route_and_bad_output(live, monkeypatch):
    ent, token, anon = live
    assert ent.post(f"{E}/insights").json()["built"] is False
    _talk(ent, token, anon)
    monkeypatch.setattr(desk, "_ask", lambda s, x: ("not json at all", 0))
    r = ent.post(f"{E}/insights").json()
    assert r["built"] is True and r["insights"]["questions"] == []


@pytest.fixture(autouse=True)
def _fresh_limits():
    desk._hits.clear()
