"""The layout of the Agents page: order of projects and agents, project colours (agents.load_layout/save_layout)."""
from __future__ import annotations

import json

from maxxing import agents, config

A = "projects/acme/topics/blog/agents/writer"
B = "projects/acme/topics/blog/agents/editor"


def _on(client) -> None:
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200


def test_store_tolerant_read_and_unknown_fields(mx):
    f = config.state_dir("agents") / "layout.json"
    assert agents.load_layout() == {"projects": [], "colors": {}, "agents": {}}
    f.write_text("{nope")                                               # damaged = empty
    assert agents.load_layout()["projects"] == []
    f.write_text(json.dumps({"projects": ["acme", "Bad Name", "acme", 3, "zeta"], "colors": {"acme": "rose", "zeta": "pink"},
                             "agents": {"acme": [A, "projects/other/topics/x/agents/y", A, B], "zeta": "x"}, "future": 1}))
    lay = agents.load_layout()
    assert lay["projects"] == ["acme", "zeta"] and lay["colors"] == {"acme": "rose"}
    assert lay["agents"] == {"acme": [A, B]} and lay["future"] == 1
    agents.save_layout({"projects": ["zeta"], "colors": {}, "agents": {}})
    assert json.loads(f.read_text())["future"] == 1                     # a newer version's field survives a save


def test_endpoints_validate(client, topic):
    _on(client)
    assert client.get("/api/agents/layout").json() == {"projects": [], "colors": {}, "agents": {}}
    good = {"projects": ["acme", "general"], "colors": {"acme": "violet"}, "agents": {"acme": [B, A]}, "junk": "x"}
    r = client.put("/api/agents/layout", json=good)
    assert r.status_code == 200, r.text
    assert r.json() == {"projects": ["acme", "general"], "colors": {"acme": "violet"}, "agents": {"acme": [B, A]}}
    assert client.get("/api/agents/layout").json()["agents"] == {"acme": [B, A]}
    for bad in ([1], {"projects": "acme"}, {"projects": ["../x"]}, {"colors": {"acme": "pink"}}, {"colors": []},
                {"agents": {"acme": ["projects/other/topics/x/agents/y"]}}, {"agents": {"acme": "x"}}, {"projects": ["acme\n"]},
                {"projects": [f"p{i}" for i in range(agents.MAX_LAYOUT_PROJECTS + 1)]}):
        r = client.put("/api/agents/layout", json=bad)
        assert r.status_code == 400 and r.json()["error"] == "bad_layout", (bad, r.text)
    assert client.get("/api/agents/layout").json()["colors"] == {"acme": "violet"}   # refused = unchanged
    r = client.put("/api/agents/layout", json={"agents": {"acme": [f" /{A}/ "]}})          # stored normalised
    assert r.status_code == 200 and r.json()["agents"] == {"acme": [A]}


def test_off_feature_hides_the_layout(client, topic):
    assert client.get("/api/agents/layout").status_code == 404
    assert client.put("/api/agents/layout", json={}).status_code == 404


def test_project_color_honours_the_override(mx):
    default = agents.project_color("acme")
    other = next(c for c in agents.AVATAR["color"] if c != default)
    agents.save_layout({"colors": {"acme": other}})
    assert agents.project_color("acme") == other
    assert agents.project_color("blog") in agents.AVATAR["color"]
    agents.save_layout({})
    assert agents.project_color("acme") == default


def test_rename_moves_the_layout(client, topic):
    _on(client)
    client.put("/api/agents/layout", json={"projects": ["acme"], "colors": {"acme": "amber"}, "agents": {"acme": [A]}})
    assert client.patch("/api/workspace/projects/acme/topics/blog", json={"name": "news"}).status_code == 200
    assert agents.load_layout()["agents"] == {"acme": ["projects/acme/topics/news/agents/writer"]}
    assert client.patch("/api/workspace/projects/acme", json={"name": "shop"}).status_code == 200
    lay = agents.load_layout()
    assert lay["projects"] == ["shop"] and lay["colors"] == {"shop": "amber"}
    assert lay["agents"] == {"shop": ["projects/shop/topics/news/agents/writer"]}
