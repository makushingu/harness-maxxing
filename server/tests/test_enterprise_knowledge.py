"""Enterprise knowledge: the system note of a position's turns, the enterprise CLAUDE.md and the company profile
(maxxing/enterprise_knowledge.py, api/enterprise_profile.py)."""
from __future__ import annotations

import pytest
from maxxing import agents, enterprise_knowledge as ek, enterprises

E = "/api/enterprises"
W = "projects/acme/topics/blog/agents/writer"
R = "projects/acme/topics/blog/agents/editor"
S = "projects/acme/topics/blog/agents/stranger"


def _on(client, on=True):
    assert client.put("/api/settings", json={"agents_page": True, "enterprises_page": on}).status_code == 200


def _agent(client, topic_path, name):
    r = client.post("/api/agents", json={"topic_path": topic_path, "name": name, "sandbox": False})
    assert r.status_code == 200, r.text


@pytest.fixture
def ent(client, topic):
    _on(client)
    for n in ("writer", "editor", "stranger"):
        _agent(client, topic, n)
    assert client.post(E, json={"id": "acme-group", "name": "Acme Group", "projects": ["acme"]}).status_code == 200
    base = f"{E}/acme-group"
    assert client.patch(base, json={"departments": {"marketing": {"name": "Marketing", "notes": "Tone: friendly."}}}
                        ).status_code == 200
    assert client.post(f"{base}/positions", json={"id": "lead", "title": "Head of marketing", "department": "marketing",
                                                   "agent": R, "job": "Lead the marketing team."}).status_code == 200
    assert client.post(f"{base}/positions", json={"id": "writer", "title": "Articles", "reports_to": "lead",
                                                   "department": "marketing", "agent": W,
                                                   "job": "Write the blog articles."}).status_code == 200
    assert client.put(f"{base}/about", json={"text": "# Acme Group\n\nWe sell kits."}).status_code == 200
    return base


def test_note_cascade_order_and_chart_line(ent):
    n = ek.note(W)
    for part in ("We sell kits.", "Tone: friendly.", "Write the blog articles.", "'Articles' (writer)", "report to lead"):
        assert part in n, part
    assert n.index("We sell kits.") < n.index("Tone: friendly.") < n.index("Write the blog articles.") < n.index("maxxing enterprise")
    assert "maxxing enterprise" in n and "your direct reports" not in n
    lead = ek.note(R)
    assert "your direct reports: writer" in lead and "report to the owner" in lead
    assert "Lead the marketing team." in lead and "Write the blog articles." not in lead


def test_note_is_stable_capped_and_absent_when_it_should(ent, client):
    assert ek.note(W) == ek.note(W)
    assert ek.note(S) == "" and ek.note("projects/acme/topics/blog/agents/none") == ""      # no position / no agent
    assert client.put(f"{ent}/about", json={"text": "x" * 15000}).status_code == 200
    n = ek.note(W)
    assert len(n) <= ek.NOTE_MAX and "'Articles' (writer)" in n and "Write the blog articles." not in n
    assert n.endswith("show.") and n.count("x") > 1000                  # the chart line is never cut
    _on(client, on=False)
    assert ek.note(W) == ""


def test_note_reaches_both_run_settings_branches(ent):
    for kw in ({}, {"manager": True}):
        note = agents.run_settings(W, **kw)["system_note"]
        assert ek.note(W) and note.endswith(ek.note(W))
    assert ek.note(S) == "" and agents.run_settings(S)["system_note"] == agents.OWNER_NOTE


def test_note_never_raises(ent, monkeypatch):
    monkeypatch.setattr(enterprises, "load", lambda slug: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ek.note(W) == ""
    assert agents.run_settings(W)["system_note"] == agents.OWNER_NOTE


def test_about_routes(ent, client):
    r = client.get(f"{ent}/about")
    assert r.status_code == 200 and r.json()["text"].endswith("We sell kits.")
    assert r.json()["max"] == ek.ABOUT_MAX and r.json()["note_max"] == ek.NOTE_MAX
    assert client.put(f"{ent}/about", json={"text": "y" * (ek.ABOUT_MAX + 1)}).status_code in (400, 422)
    assert client.get(f"{E}/nope/about").status_code == 404
    log = client.get(f"{ent}/decisions").json()["items"]
    assert any("CLAUDE.md" in x["text"] for x in log)
    _on(client, on=False)
    assert client.get(f"{ent}/about").json()["error"] == "feature_off"


def test_profile_roundtrip_and_validation(ent, client):
    empty = client.get(f"{ent}/profile").json()
    assert empty == {"products": [], "hours": "", "terms": {}, "contact": "", "faq": []}
    body = {"products": [{"name": "Starter kit", "price": "29 USD", "url": "https://shop.example.com/starter",
                          "sku": "S1"}], "hours": "Mon-Fri 9:00-18:00", "terms": {"refund_days": 30, "ship": "2-4 days"},
            "contact": {"email": "hello@example.com"}, "faq": [{"q": "Works with model Y?", "a": "Yes."}],
            "brand": {"voice": "warm"}}
    r = client.put(f"{ent}/profile", json=body)
    assert r.status_code == 200, r.text
    got = client.get(f"{ent}/profile").json()
    assert r.json() == {"profile": got}
    assert got["products"][0] == {"name": "Starter kit", "price": "29 USD", "url": "https://shop.example.com/starter",
                                  "notes": "", "sku": "S1"}
    assert got["terms"]["refund_days"] == 30 and got["brand"] == {"voice": "warm"}
    assert ek.profile("acme-group") == got
    for bad in ({"products": [{"price": "1"}]}, {"products": "x"}, {"faq": [{"q": "only"}]}, {"terms": []},
                {"products": [{"name": str(i)} for i in range(301)]}):
        assert client.put(f"{ent}/profile", json=bad).status_code == 400, bad
    assert client.put(f"{ent}/profile", json={"brand": "z" * 70000}).status_code == 413
    assert client.get(f"{ent}/profile").json() == got                     # refused edits change nothing
    assert client.get(f"{E}/nope/profile").status_code == 404
    _on(client, on=False)
    assert client.put(f"{ent}/profile", json=body).json()["error"] == "feature_off"


def test_damaged_profile_reads_as_empty(ent, mx):
    (mx["ws"] / "enterprises" / "acme-group" / "profile.json").write_text("{not json", encoding="utf-8")
    assert ek.profile("acme-group")["products"] == []
