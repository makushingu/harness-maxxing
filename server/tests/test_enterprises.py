"""Enterprises: the structure (maxxing/enterprises.py, api/enterprises.py): chart checks, rev, hooks, trash."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from maxxing import agent_guard, agents, config, enterprises

E = "/api/enterprises"
W = "projects/acme/topics/blog/agents/writer"
R = "projects/acme/topics/blog/agents/editor"
Z = "projects/zeta/topics/news/agents/anchor"


def _on(client, enterprises_page=True, agents_page=True):
    assert client.put("/api/settings", json={"agents_page": agents_page,
                                              "enterprises_page": enterprises_page}).status_code == 200


def _agent(client, topic_path, name):
    r = client.post("/api/agents", json={"topic_path": topic_path, "name": name, "sandbox": False})
    assert r.status_code == 200, r.text
    return r.json()["path"]


@pytest.fixture
def ent(client, topic):
    """Enterprise `acme-group` linked to project acme, with agents writer and editor in acme/blog."""
    _on(client)
    _agent(client, topic, "writer")
    _agent(client, topic, "editor")
    r = client.post(E, json={"id": "acme-group", "name": "Acme Group", "emoji": "🏢", "projects": ["acme"]})
    assert r.status_code == 200, r.text
    return r.json()


def _pos(client, pid, **f):
    return client.post(f"{E}/acme-group/positions", json={"id": pid, **f})


def _chart(client):
    return client.get(f"{E}/acme-group").json()


def _err(r, status, code):
    assert r.status_code == status, r.text
    assert r.json()["error"] == code, r.text


def _file(mx):
    return mx["ws"] / "enterprises" / "acme-group" / "enterprise.json"


# ---- feature switches -----------------------------------------------------------------------------
def test_feature_off_when_either_flag_is_off(client, topic):
    _err(client.get(E), 404, "feature_off")
    _on(client, enterprises_page=True, agents_page=False)
    _err(client.get(E), 404, "feature_off")
    _on(client, enterprises_page=False, agents_page=True)
    for r in (client.get(E), client.get(E + "/templates"), client.get(E + "/x"), client.post(E, json={"id": "x"}),
              client.patch(E + "/x", json={}), client.delete(E + "/x"), client.put(E + "/x/projects", json={"projects": []}),
              client.post(E + "/x/positions", json={"id": "a"}), client.patch(E + "/x/positions/a", json={}),
              client.delete(E + "/x/positions/a"), client.post(E + "/x/positions/a/hire", json={"topic": "t"}),
              client.get(E + "/x/positions/a/inbox"), client.get(E + "/x/decisions")):
        _err(r, 404, "feature_off")
    assert enterprises.feature_on() is False
    _on(client)
    assert enterprises.feature_on() is True
    assert client.get(E).json() == {"enterprises": []}
    assert len(client.get(E + "/templates").json()["templates"]) == 4


def test_settings_flag_default_and_roundtrip(client):
    assert client.get("/api/settings").json()["enterprises_page"] is False
    assert config.DEFAULT_CONFIG["enterprises_page"] is False
    _on(client)
    assert client.get("/api/settings").json()["enterprises_page"] is True


# ---- create / read / update / delete ------------------------------------------------------------------
def test_create_and_files(client, topic, mx, ent):
    d = mx["ws"] / "enterprises" / "acme-group"
    assert (d / "CLAUDE.md").read_text().startswith("# Enterprise Acme Group")
    assert (d / "files").is_dir()
    raw = json.loads((d / "enterprise.json").read_text())
    assert raw["version"] == 1 and raw["projects"] == ["acme"] and raw["top"] == "owner" and raw["rev"] >= 1
    assert raw["settings"]["limits"] == {"depth": 4, "reports": 8, "workers_live": 5, "hops_per_task": 6}
    assert ent["id"] == "acme-group" and ent["positions"] == [] and ent["broken"] is False
    lst = client.get(E).json()["enterprises"]
    assert lst == [{"id": "acme-group", "name": "Acme Group", "emoji": "🏢", "projects": ["acme"], "positions": 0,
                    "vacant": 0, "top": "owner", "broken": False}]
    items = client.get(f"{E}/acme-group/decisions").json()["items"]
    assert items and items[0]["kind"] == "structure"


def test_slug_rules_and_errors(client, topic, ent):
    for bad in ("", "Acme", "-x", "a b", "x" * 49, "templates", "import"):
        _err(client.post(E, json={"id": bad}), 400, "invalid_name")
    _err(client.post(E, json={"id": "acme-group"}), 409, "exists")
    _err(client.post(E, json={"id": "other", "projects": ["acme"]}), 409, "project_linked")
    _err(client.post(E, json={"id": "other", "projects": ["nope"]}), 400, "bad_project")
    _err(client.post(E, json={"id": "other", "template": "nope"}), 400, "bad_template")
    assert not (Path(config.workspace()) / "enterprises" / "other").exists()
    _err(client.get(E + "/missing"), 404, "not_found")
    _err(client.delete(E + "/missing"), 404, "not_found")


def test_max_enterprises(client, topic):
    _on(client)
    for i in range(enterprises.MAX_ENTERPRISES):
        assert client.post(E, json={"id": f"e{i}"}).status_code == 200
    _err(client.post(E, json={"id": "one-more"}), 400, "too_many")


def test_patch_settings_merge_and_validation(client, ent, mx):
    r = client.patch(f"{E}/acme-group", json={"name": "Acme", "emoji": "🏭", "settings": {
        "autonomy": "careful", "limits": {"depth": 3}, "digest": {"enabled": True}},
        "envelope": {"usd_per_day": 12.5}})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["name"] == "Acme" and c["emoji"] == "🏭" and c["settings"]["autonomy"] == "careful"
    assert c["settings"]["limits"] == {"depth": 3, "reports": 8, "workers_live": 5, "hops_per_task": 6}
    assert c["settings"]["digest"]["enabled"] is True and c["settings"]["digest"]["hour"] == 8
    assert c["envelope"]["usd_per_day"] == 12.5 and c["rev"] > ent["rev"]
    _err(client.patch(f"{E}/acme-group", json={"settings": {"autonomy": "reckless"}}), 400, "invalid")
    _err(client.patch(f"{E}/acme-group", json={"settings": {"escalation_timeout_h": 100}}), 400, "invalid")
    _err(client.patch(f"{E}/acme-group", json={"envelope": {"usd_per_day": -1}}), 400, "invalid")
    _err(client.patch(f"{E}/acme-group", json={"name": ""}), 400, "invalid")
    _err(client.patch(f"{E}/acme-group", json={"top": "ghost"}), 400, "bad_position")
    r = client.patch(f"{E}/acme-group", json={"departments": {"marketing": {"name": "Marketing",
                                                                          "settings": {"autonomy": "careful"}}}})
    assert r.json()["departments"]["marketing"]["settings"] == {"autonomy": "careful"}
    _err(client.patch(f"{E}/acme-group", json={"departments": {"Bad Id": {}}}), 400, "invalid")


def test_unknown_keys_are_kept(client, ent, mx):
    f = _file(mx)
    raw = json.loads(f.read_text())
    raw["from_the_future"] = {"x": 1}
    raw["positions"] = [{"id": "ceo", "title": "CEO", "reports_to": None, "agent": None, "extra": 5}]
    f.write_text(json.dumps(raw))
    assert client.patch(f"{E}/acme-group", json={"name": "Renamed"}).status_code == 200
    raw = json.loads(f.read_text())
    assert raw["from_the_future"] == {"x": 1} and raw["positions"][0]["extra"] == 5 and raw["name"] == "Renamed"


def test_clean_defaults_and_garbage():
    d = enterprises.clean({"projects": ["acme", "BAD", "acme"], "top": ["x"], "positions": [
        {"id": "a", "reports_to": "a"}, {"id": "b", "reports_to": "zzz"}, {"id": "BAD"}, "x", {"id": "a"}],
        "settings": {"autonomy": 5, "digest": "no"}, "rev": "x"})
    assert d["projects"] == ["acme"] and d["top"] == "owner" and d["rev"] == 0
    assert [p["id"] for p in d["positions"]] == ["a", "b"] and all(p["reports_to"] is None for p in d["positions"])
    assert d["settings"]["autonomy"] == "balanced" and d["settings"]["digest"]["hour"] == 8
    assert enterprises.clean(d) == d
    assert enterprises.clean(None)["name"] == ""


def test_delete_goes_to_trash_with_its_state(client, ent, mx):
    assert _pos(client, "ceo", title="CEO").status_code == 200
    st = mx["state"] / "enterprises" / "acme-group"
    assert (st / "decisions.jsonl").is_file()
    (st / "inbox").mkdir()
    (st / "inbox" / "ceo.jsonl").write_text('{"id": "1", "kind": "ask", "text": "hi"}\n')
    assert client.delete(f"{E}/acme-group").json() == {"ok": True}
    assert not (mx["ws"] / "enterprises" / "acme-group").exists() and not st.exists()
    items = client.get("/api/trash").json()["items"]
    assert len(items) == 1 and items[0]["kind"] == "folder"
    r = client.post(f"/api/trash/{items[0]['id']}/restore").json()
    assert r["ok"] and r["restored_to"] == "enterprises/acme-group"
    c = _chart(client)
    assert [p["id"] for p in c["positions"]] == ["ceo"] and c["projects"] == ["acme"] and c["positions"][0]["inbox"] == 1
    assert (st / "decisions.jsonl").is_file() and not (mx["ws"] / "enterprises" / "acme-group" / ".state").exists()
    assert client.get(f"{E}/acme-group/decisions").json()["items"]


def test_restore_enterprise_beside_a_new_one_with_its_name(client, ent, mx):
    client.delete(f"{E}/acme-group")
    assert client.post(E, json={"id": "acme-group"}).status_code == 200
    item = client.get("/api/trash").json()["items"][0]
    r = client.post(f"/api/trash/{item['id']}/restore").json()
    assert r["restored_to"] == "enterprises/acme-group-restored"
    assert client.get(E + "/acme-group-restored").status_code == 200


# ---- positions -----------------------------------------------------------------------------------------
def test_add_positions_and_state(client, ent):
    r = _pos(client, "lead", title="Head of blog", job="Runs the blog.", department="marketing")
    assert r.status_code == 200, r.text
    assert _pos(client, "writer", title="Writer", reports_to="lead", agent=W).status_code == 200
    _pos(client, "editor", reports_to="lead")
    c = _chart(client)
    by = {p["id"]: p for p in c["positions"]}
    assert by["lead"]["state"] == "vacant" and by["lead"]["occupant"] is None and by["lead"]["department"] == "marketing"
    w = by["writer"]
    assert w["state"] == "idle" and w["occupant"]["path"] == W and w["occupant"]["sandbox"] is False
    assert w["cost_today"] == 0 and w["inbox"] == 0 and w["open_tasks"] == 0 and w["reports_to"] == "lead"
    assert c["cost_today"] == 0 and c["ceiling_hit"] is False
    assert client.get(E).json()["enterprises"][0]["vacant"] == 2
    # defaults of a position added with an id only
    assert by["editor"]["title"] == "editor" and by["editor"]["agent"] is None and by["editor"]["job"] == ""


def test_position_errors(client, ent):
    _pos(client, "lead")
    for bad in ("", "Lead", "-x"):
        _err(_pos(client, bad), 400, "invalid_name")
    _err(_pos(client, "lead"), 409, "exists")
    _err(_pos(client, "x", reports_to="ghost"), 400, "bad_position")
    _err(_pos(client, "x", agent="projects/acme/topics/blog/agents/ghost"), 400, "bad_agent")
    _err(_pos(client, "x", agent="nonsense"), 400, "bad_agent")
    _err(client.patch(f"{E}/acme-group/positions/ghost", json={"title": "x"}), 404, "not_found")
    _err(client.delete(f"{E}/acme-group/positions/ghost"), 404, "not_found")


def test_agent_of_an_unlinked_project_is_bad_agent(client, ent):
    assert client.post("/api/workspace/projects", json={"name": "zeta"}).status_code == 200
    assert client.post("/api/workspace/projects/zeta/topics", json={"name": "news"}).status_code == 200
    z = _agent(client, "projects/zeta/topics/news", "anchor")
    _err(_pos(client, "x", agent=z), 400, "bad_agent")


def test_agent_holds_one_position(client, ent):
    assert _pos(client, "a", agent=W).status_code == 200
    _err(_pos(client, "b", agent=W), 409, "agent_seated")
    _pos(client, "b")
    rev = _chart(client)["rev"]
    _err(client.patch(f"{E}/acme-group/positions/b", json={"agent": W, "rev": rev}), 409, "agent_seated")
    # a second enterprise cannot seat it either
    assert client.post("/api/workspace/projects", json={"name": "zeta"}).status_code == 200
    assert client.post(E, json={"id": "other", "projects": ["zeta"]}).status_code == 200
    seat = enterprises.seat_of(W)
    assert seat == ("acme-group", "a")


def test_depth_reports_and_cycle(client, ent):
    assert client.patch(f"{E}/acme-group", json={"settings": {"limits": {"depth": 3, "reports": 2}}}).status_code == 200
    _pos(client, "a")
    _pos(client, "b", reports_to="a")
    _pos(client, "c", reports_to="b")
    _err(_pos(client, "d", reports_to="c"), 400, "too_deep")
    _pos(client, "e", reports_to="a")
    _err(_pos(client, "f", reports_to="a"), 400, "too_many_reports")
    rev = _chart(client)["rev"]
    # a under its own descendant, and under itself
    _err(client.patch(f"{E}/acme-group/positions/a", json={"reports_to": "c", "rev": rev}), 400, "cycle")
    _err(client.patch(f"{E}/acme-group/positions/a", json={"reports_to": "a", "rev": rev}), 400, "cycle")
    # lowering the limit under an existing tree is refused
    _err(client.patch(f"{E}/acme-group", json={"settings": {"limits": {"depth": 2}}}), 400, "too_deep")
    assert _chart(client)["settings"]["limits"]["depth"] == 3
    # a move that makes the tree too deep
    _pos(client, "g")
    rev = _chart(client)["rev"]
    _err(client.patch(f"{E}/acme-group/positions/g", json={"reports_to": "c", "rev": rev}), 400, "too_deep")


def test_max_positions(client, ent, monkeypatch):
    monkeypatch.setattr(enterprises, "MAX_POSITIONS", 2)
    _pos(client, "a")
    _pos(client, "b")
    _err(_pos(client, "c"), 400, "too_many")


def test_stale_rev_for_structure_only(client, ent):
    _pos(client, "a")
    _pos(client, "b")
    rev = _chart(client)["rev"]
    # a field edit needs no rev and bumps it
    r = client.patch(f"{E}/acme-group/positions/a", json={"title": "Alpha", "job": "Does A.", "desk": True})
    assert r.status_code == 200 and r.json()["rev"] == rev + 1
    a = {p["id"]: p for p in r.json()["positions"]}["a"]
    assert a["title"] == "Alpha" and a["job"] == "Does A." and a["desk"] is True
    # a move without the rev, or with an old one: 409 stale carrying the current chart
    for body in ({"reports_to": "a"}, {"reports_to": "a", "rev": rev}):
        r = client.patch(f"{E}/acme-group/positions/b", json=body)
        _err(r, 409, "stale")
        assert r.json()["chart"]["rev"] == rev + 1
    for body in ({"agent": W}, {"agent": W, "rev": rev}):
        _err(client.patch(f"{E}/acme-group/positions/b", json=body), 409, "stale")
    r = client.patch(f"{E}/acme-group/positions/b", json={"reports_to": "a", "rev": rev + 1})
    assert r.status_code == 200
    assert {p["id"]: p for p in r.json()["positions"]}["b"]["reports_to"] == "a"
    # the same value again is not structural
    assert client.patch(f"{E}/acme-group/positions/b", json={"reports_to": "a"}).status_code == 200


def test_seat_and_vacate_with_rev(client, ent):
    _pos(client, "a")
    rev = _chart(client)["rev"]
    r = client.patch(f"{E}/acme-group/positions/a", json={"agent": W, "rev": rev})
    assert r.status_code == 200 and {p["id"]: p for p in r.json()["positions"]}["a"]["occupant"]["path"] == W
    assert enterprises.seat_of(W) == ("acme-group", "a")
    r = client.patch(f"{E}/acme-group/positions/a", json={"agent": None, "rev": rev + 1})
    assert r.status_code == 200 and {p["id"]: p for p in r.json()["positions"]}["a"]["agent"] is None
    assert enterprises.seat_of(W) is None
    kinds = [i["text"] for i in client.get(f"{E}/acme-group/decisions").json()["items"]]
    assert any("vacated" in t for t in kinds) and any("held by" in t for t in kinds)


def test_move_to_the_top_and_top_setting(client, ent):
    _pos(client, "a")
    _pos(client, "b", reports_to="a")
    assert client.patch(f"{E}/acme-group", json={"top": "a"}).json()["top"] == "a"
    _err(client.patch(f"{E}/acme-group", json={"top": "b"}), 400, "bad_position")
    rev = _chart(client)["rev"]
    r = client.patch(f"{E}/acme-group/positions/a", json={"reports_to": "b", "rev": rev})
    _err(r, 400, "cycle")
    r = client.delete(f"{E}/acme-group/positions/a?reparent_to=owner")
    assert r.status_code == 200 and r.json()["top"] == "owner"
    assert [p["reports_to"] for p in r.json()["positions"]] == [None]


def test_remove_with_reports(client, ent, mx):
    _pos(client, "a")
    _pos(client, "b", reports_to="a")
    _pos(client, "c", reports_to="a")
    _pos(client, "d")
    st = mx["state"] / "enterprises" / "acme-group" / "inbox"
    st.mkdir(parents=True, exist_ok=True)
    (st / "a.jsonl").write_text('{"id": "1"}\n')
    r = client.delete(f"{E}/acme-group/positions/a")
    _err(r, 409, "has_reports")
    assert r.json()["reports"] == ["b", "c"]
    _err(client.delete(f"{E}/acme-group/positions/a?reparent_to=ghost"), 400, "bad_position")
    _err(client.delete(f"{E}/acme-group/positions/a?reparent_to=b"), 400, "cycle")
    r = client.delete(f"{E}/acme-group/positions/a?reparent_to=d")
    assert r.status_code == 200
    by = {p["id"]: p for p in r.json()["positions"]}
    assert "a" not in by and by["b"]["reports_to"] == "d" and by["c"]["reports_to"] == "d"
    assert not (st / "a.jsonl").exists()
    # a leaf goes without parameter
    assert client.delete(f"{E}/acme-group/positions/b").status_code == 200


def test_remove_reparent_checks_limits(client, ent):
    assert client.patch(f"{E}/acme-group", json={"settings": {"limits": {"reports": 1}}}).status_code == 200
    _pos(client, "a")
    _pos(client, "b", reports_to="a")
    _pos(client, "c")
    _pos(client, "d", reports_to="c")
    _err(client.delete(f"{E}/acme-group/positions/a?reparent_to=c"), 400, "too_many_reports")


def test_worker_template_and_department(client, ent):
    _pos(client, "a")
    r = client.patch(f"{E}/acme-group/positions/a", json={
        "worker_template": {"role": "Summarises", "model": "sonnet", "usd_per_day": 0.5}, "department": "ops"})
    p = r.json()["positions"][0]
    assert p["worker_template"] == {"role": "Summarises", "model": "sonnet", "usd_per_day": 0.5} and p["department"] == "ops"
    r = client.patch(f"{E}/acme-group/positions/a", json={"worker_template": None, "department": ""})
    p = r.json()["positions"][0]
    assert "worker_template" not in p and p["department"] == ""
    _err(client.patch(f"{E}/acme-group/positions/a", json={"department": "Bad Id"}), 400, "invalid")


# ---- projects ------------------------------------------------------------------------------------------
def test_set_projects(client, ent):
    assert client.post("/api/workspace/projects", json={"name": "zeta"}).status_code == 200
    r = client.put(f"{E}/acme-group/projects", json={"projects": ["acme", "zeta", "zeta"]})
    assert r.status_code == 200 and r.json()["projects"] == ["acme", "zeta"]
    assert enterprises.enterprise_of_project("zeta") == "acme-group"
    _err(client.put(f"{E}/acme-group/projects", json={"projects": ["nope"]}), 400, "bad_project")
    assert client.post(E, json={"id": "other"}).status_code == 200
    _err(client.put(f"{E}/other/projects", json={"projects": ["zeta"]}), 409, "project_linked")
    assert client.put(f"{E}/acme-group/projects", json={"projects": ["acme"]}).status_code == 200
    assert enterprises.enterprise_of_project("zeta") is None
    assert client.put(f"{E}/other/projects", json={"projects": ["zeta"]}).status_code == 200


def test_unlink_occupied_project(client, ent):
    _pos(client, "a", agent=W)
    r = client.put(f"{E}/acme-group/projects", json={"projects": []})
    _err(r, 409, "occupied")
    assert r.json()["positions"] == ["a"]
    assert _chart(client)["projects"] == ["acme"]
    r = client.put(f"{E}/acme-group/projects", json={"projects": [], "vacate": True})
    assert r.status_code == 200 and r.json()["projects"] == [] and r.json()["positions"][0]["agent"] is None
    assert enterprises.seat_of(W) is None


# ---- hire -----------------------------------------------------------------------------------------------
def test_hire(client, ent, topic):
    _pos(client, "head", title="Head of blog", job="Runs the blog.")
    assert client.post("/api/workspace/projects", json={"name": "zeta"}).status_code == 200
    assert client.post("/api/workspace/projects/zeta/topics", json={"name": "news"}).status_code == 200
    _err(client.post(f"{E}/acme-group/positions/head/hire", json={"topic": "projects/zeta/topics/news"}), 400, "bad_project")
    _err(client.post(f"{E}/acme-group/positions/head/hire", json={"topic": "nonsense"}), 400, "bad_project")
    _err(client.post(f"{E}/acme-group/positions/ghost/hire", json={"topic": topic}), 404, "not_found")
    r = client.post(f"{E}/acme-group/positions/head/hire", json={"topic": topic})
    assert r.status_code == 200, r.text
    path = r.json()["agent"]
    assert path == "projects/acme/topics/blog/agents/head" and agents.exists(path)
    assert "Head of blog" in agents.get(path)["description"] and "Runs the blog." in agents.get(path)["description"]
    c = r.json()["enterprise"]
    assert c["positions"][0]["occupant"]["path"] == path and enterprises.seat_of(path) == ("acme-group", "head")
    _err(client.post(f"{E}/acme-group/positions/head/hire", json={"topic": topic}), 409, "not_vacant")


def _suggest(mx, pos, tid):
    f = _file(mx)
    d = json.loads(f.read_text(encoding="utf-8"))
    next(x for x in d["positions"] if x["id"] == pos)["suggested_template"] = tid
    f.write_text(json.dumps(d), encoding="utf-8", newline="")


def test_hire_with_an_agent_template(client, ent, topic, mx):
    from maxxing import agent_templates
    tpl = agent_templates.get("writer")
    _pos(client, "head", title="Head of blog", job="Runs the blog.")
    _pos(client, "b", title="Scribe", job="Writes.")
    _pos(client, "c", title="Third", job="Does the third.")
    _pos(client, "d", title="Fourth", job="Does the fourth.")
    _err(client.post(f"{E}/acme-group/positions/head/hire", json={"topic": topic, "template": "nope"}), 400, "bad_template")
    assert not (mx["ws"] / "projects/acme/topics/blog/agents/head").exists()
    r = client.post(f"{E}/acme-group/positions/head/hire", json={"topic": topic, "template": "writer"})
    assert r.status_code == 200, r.text
    a = agents.get(r.json()["agent"])
    assert a["allowed_tools"] == tpl["allowed_tools"] and a["permission_mode"] == tpl["permission_mode"]
    assert "Head of blog" in a["description"] and "Runs the blog." in a["description"] and tpl["role"] not in a["description"]
    # the suggested template of the position is the default; "" asks for none
    _suggest(mx, "b", "writer")
    _suggest(mx, "c", "writer")
    r = client.post(f"{E}/acme-group/positions/b/hire", json={"topic": topic})
    assert agents.get(r.json()["agent"])["allowed_tools"] == tpl["allowed_tools"]
    r = client.post(f"{E}/acme-group/positions/c/hire", json={"topic": topic, "template": ""})
    assert agents.get(r.json()["agent"])["allowed_tools"] != tpl["allowed_tools"]
    r = client.post(f"{E}/acme-group/positions/d/hire", json={"topic": topic})
    assert agents.get(r.json()["agent"])["allowed_tools"] != tpl["allowed_tools"]
    assert next(p for p in _chart(client)["positions"] if p["id"] == "b")["suggested_template"] == "writer"


def test_dashboard_widget_only_while_the_feature_is_on(client, ent):
    def ids():
        return {w["id"]: w for w in client.get("/api/dashboard").json()["widgets"]}
    assert "enterprises" in ids()
    card = client.get("/api/dashboard/widgets/enterprises").json()
    assert card["error"] is None and card["card"]["link"] == "/enterprises"
    stats, rows = card["card"]["blocks"]
    assert [x["label"] for x in stats["items"]] == ["Waiting", "Escalations", "Late"]
    assert rows["items"][0]["href"] == "/enterprises/acme-group" and rows["items"][0]["value"] == "$0.00"
    assert "Acme Group" in rows["items"][0]["title"]
    _on(client, enterprises_page=False)
    assert "enterprises" not in ids()
    _on(client)
    assert client.put("/api/settings", json={"language": "fr"}).status_code == 200
    assert client.get("/api/dashboard/widgets/enterprises").json()["card"]["title"] == "Entreprises"


def test_the_envelope_skip_reason_has_a_text():
    assert "envelope" in agents.SKIP_TEXT


# ---- inbox, decisions ----------------------------------------------------------------------------------
def test_inbox_and_inbox_count(client, ent, mx):
    _pos(client, "a")
    assert client.get(f"{E}/acme-group/positions/a/inbox").json() == {"items": []}
    _err(client.get(f"{E}/acme-group/positions/ghost/inbox"), 404, "not_found")
    d = mx["state"] / "enterprises" / "acme-group" / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.jsonl").write_text('{"id": "1", "kind": "escalation", "from": "b", "text": "help", "task": "t_1", "at": 5, '
                               '"outside": true}\n\nnot json\n{"id": "2", "kind": "ask", "text": "x"}\n')
    items = client.get(f"{E}/acme-group/positions/a/inbox").json()["items"]
    assert [i["id"] for i in items] == ["1", "2"]
    assert items[0] == {"id": "1", "kind": "escalation", "from": "b", "text": "help", "task": "t_1", "at": 5, "outside": True}
    assert _chart(client)["positions"][0]["inbox"] == 3  # lines that are not blank


def test_open_tasks_count(client, ent, mx):
    _pos(client, "a")
    _pos(client, "b")
    tasks = {"version": 1, "projects": [], "tasks": [
        {"id": "t_000001", "title": "x", "status": "todo", "enterprise": {"id": "acme-group", "owner": "a"}},
        {"id": "t_000002", "title": "y", "status": "doing", "enterprise": {"id": "acme-group", "owner": "a"}},
        {"id": "t_000003", "title": "z", "status": "done", "enterprise": {"id": "acme-group", "owner": "a"}},
        {"id": "t_000004", "title": "w", "status": "todo", "enterprise": {"id": "other", "owner": "a"}},
        {"id": "t_000005", "title": "v", "status": "todo"}]}
    (mx["ws"] / "tasks.json").write_text(json.dumps(tasks))
    by = {p["id"]: p for p in _chart(client)["positions"]}
    assert by["a"]["open_tasks"] == 2 and by["b"]["open_tasks"] == 0


def test_decisions_paging_and_cap(client, ent):
    for i in range(5):
        enterprises.log("acme-group", "note", f"n{i}", by="a", position="p", task="t_1", session="s", extra_key=1)
    enterprises.log("acme-group", "note", "x" * 1000)
    r = client.get(f"{E}/acme-group/decisions?limit=3").json()
    assert len(r["items"]) == 3 and r["next"] == r["items"][-1]["at"] and len(r["items"][0]["text"]) == 600
    assert r["items"][1]["text"] == "n4" and r["items"][1]["extra_key"] == 1
    r2 = client.get(f"{E}/acme-group/decisions?limit=3&before={r['next']}").json()
    assert [i["text"] for i in r2["items"]] == ["n3", "n2", "n1"] or len(r2["items"]) == 3
    seen = []
    nxt = None
    while True:
        items, nxt = enterprises.decisions("acme-group", nxt, 2)
        seen += items
        if nxt is None:
            break
    assert len(seen) == 7
    assert client.get(f"{E}/acme-group/decisions?limit=0").status_code == 422
    _err(client.get(f"{E}/missing/decisions"), 404, "not_found")


def test_decision_log_is_trimmed(ent, mx, monkeypatch):
    monkeypatch.setattr(enterprises, "DECISIONS_KEEP", 3)
    f = mx["state"] / "enterprises" / "acme-group" / "decisions.jsonl"
    f.write_text("".join(json.dumps({"at": i, "kind": "k", "text": "x" * 600}) + "\n" for i in range(4000)))
    enterprises.log("acme-group", "k", "last")
    assert len(f.read_text().splitlines()) == 3 and json.loads(f.read_text().splitlines()[-1])["text"] == "last"


# ---- lookups ---------------------------------------------------------------------------------------------
def test_lookups(client, ent):
    assert client.patch(f"{E}/acme-group", json={
        "settings": {"autonomy": "balanced"}, "departments": {"ops": {"settings": {"autonomy": "careful"}}}}
    ).status_code == 200
    _pos(client, "top", department="")
    _pos(client, "mid", reports_to="top", department="ops")
    _pos(client, "leaf", reports_to="mid", department="ops", agent=W)
    _pos(client, "other", reports_to="top")
    s = "acme-group"
    assert enterprises.lead_of(s, "leaf") == "mid" and enterprises.lead_of(s, "top") is None
    assert enterprises.reports_of(s, "top") == ["mid", "other"]
    assert enterprises.subtree(s, "top") == ["mid", "other", "leaf"] and enterprises.subtree(s, "leaf") == []
    assert enterprises.ancestors(s, "leaf") == ["mid", "top"] and enterprises.ancestors(s, "top") == []
    assert enterprises.department_of(s, "leaf") == "ops" and enterprises.department_of(s, "top") == ""
    assert enterprises.setting(s, "autonomy") == "balanced" and enterprises.setting(s, "autonomy", "top") == "balanced"
    assert enterprises.setting(s, "autonomy", "leaf") == "careful" and enterprises.setting(s, "communication", "leaf") == "leads"
    assert enterprises.position(s, "leaf")["agent"] == W and enterprises.position(s, "ghost") is None
    assert enterprises.seat_of(W) == (s, "leaf") and enterprises.enterprise_of_project("acme") == s
    # never raise
    assert enterprises.lead_of("ghost", "x") is None and enterprises.reports_of("ghost", "x") == []
    assert enterprises.subtree("ghost", "x") == [] and enterprises.ancestors("ghost", "x") == []
    assert enterprises.setting("ghost", "autonomy") is None and enterprises.seat_of("nonsense") is None
    assert enterprises.enterprise_of_project("nope") is None and enterprises.department_of("ghost", "x") == ""


def test_lookups_follow_file_changes_made_by_hand(client, ent, mx):
    _pos(client, "a")
    assert enterprises.position("acme-group", "a")["title"] == "a"
    f = _file(mx)
    raw = json.loads(f.read_text())
    raw["positions"][0]["title"] = "Edited by hand"
    f.write_text(json.dumps(raw, indent=2))
    assert enterprises.position("acme-group", "a")["title"] == "Edited by hand"


# ---- broken file ------------------------------------------------------------------------------------------
def test_broken_enterprise_json(client, ent, mx):
    _pos(client, "a", agent=W)
    f = _file(mx)
    f.write_text("{ not json")
    c = _chart(client)
    assert c["broken"] is True and c["positions"] == []
    assert client.get(E).json()["enterprises"][0]["broken"] is True
    assert enterprises.seat_of(W) is None and enterprises.enterprise_of_project("acme") is None
    assert enterprises.position("acme-group", "a") is None
    for r in (client.patch(f"{E}/acme-group", json={"name": "x"}), _pos(client, "b"),
              client.put(f"{E}/acme-group/projects", json={"projects": []}),
              client.patch(f"{E}/acme-group/positions/a", json={"title": "x"}),
              client.delete(f"{E}/acme-group/positions/a")):
        _err(r, 409, "broken")
    assert f.read_text() == "{ not json"
    agents.delete(W)                                     # hooks leave it alone too
    assert f.read_text() == "{ not json"
    f.write_text("[1, 2]")
    assert _chart(client)["broken"] is True
    # it can still be deleted (to the Trash)
    assert client.delete(f"{E}/acme-group").status_code == 200


# ---- hooks: agent deleted, renamed, project deleted -------------------------------------------------------
def test_agent_delete_vacates(client, ent):
    _pos(client, "a", title="Writer", agent=W)
    _pos(client, "b", agent=R)
    assert client.delete(f"/api/agents/acme/blog/writer").status_code == 200
    by = {p["id"]: p for p in _chart(client)["positions"]}
    assert by["a"]["agent"] is None and by["a"]["state"] == "vacant" and by["a"]["title"] == "Writer"
    assert by["b"]["agent"] == R
    assert enterprises.seat_of(W) is None
    assert any("vacated" in i["text"] for i in client.get(f"{E}/acme-group/decisions").json()["items"])


def test_missing_occupant_is_shown_vacant_with_a_reason(client, ent, mx):
    _pos(client, "a", agent=W)
    import shutil
    shutil.rmtree(mx["ws"] / W)                          # deleted by hand: no hook ran
    p = _chart(client)["positions"][0]
    assert p["state"] == "vacant" and p["occupant"] is None and p["blocked_reason"]


def test_topic_and_project_rename_follow(client, ent, topic):
    _pos(client, "a", agent=W)
    assert client.patch("/api/workspace/projects/acme/topics/blog", json={"name": "news"}).status_code == 200
    p = _chart(client)["positions"][0]
    assert p["agent"] == "projects/acme/topics/news/agents/writer" and p["occupant"]["path"] == p["agent"]
    r = client.patch("/api/workspace/projects/acme", json={"name": "zeta"})
    assert r.status_code == 200, r.text
    c = _chart(client)
    assert c["projects"] == ["zeta"] and c["positions"][0]["agent"] == "projects/zeta/topics/news/agents/writer"
    assert c["positions"][0]["occupant"] is not None
    assert enterprises.enterprise_of_project("zeta") == "acme-group" and enterprises.enterprise_of_project("acme") is None
    assert enterprises.seat_of("projects/zeta/topics/news/agents/writer") == ("acme-group", "a")


def test_project_delete_and_restore_round_trip(client, ent, topic, mx):
    _pos(client, "a", agent=W)
    _pos(client, "b", agent=R, reports_to="a")
    assert client.delete("/api/workspace/projects/acme").status_code == 200
    c = _chart(client)
    assert c["projects"] == [] and [p["agent"] for p in c["positions"]] == [None, None]
    assert [p["reports_to"] for p in c["positions"]] == [None, "a"]
    item = next(i for i in client.get("/api/trash").json()["items"] if i["kind"] == "project")
    assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200
    c = _chart(client)
    assert c["projects"] == ["acme"] and [p["agent"] for p in c["positions"]] == [W, R]
    assert not (mx["ws"] / "projects" / "acme" / enterprises.SAVED_LINKS).exists()
    assert all(p["occupant"] for p in c["positions"])


def test_project_restored_under_a_new_name(client, ent, topic, mx):
    _pos(client, "a", agent=W)
    assert client.delete("/api/workspace/projects/acme").status_code == 200
    assert client.post("/api/workspace/projects", json={"name": "acme"}).status_code == 200
    item = next(i for i in client.get("/api/trash").json()["items"] if i["kind"] == "project")
    r = client.post(f"/api/trash/{item['id']}/restore").json()
    assert r["restored_to"] == "projects/acme-restored"
    c = _chart(client)
    assert c["projects"] == ["acme-restored"] and c["positions"][0]["agent"] == "projects/acme-restored/topics/blog/agents/writer"


def test_topic_delete_vacates_and_restore_reseats(client, ent, topic):
    _pos(client, "a", agent=W)
    assert client.delete("/api/workspace/projects/acme/topics/blog").status_code == 200
    c = _chart(client)
    assert c["projects"] == ["acme"] and c["positions"][0]["agent"] is None
    item = next(i for i in client.get("/api/trash").json()["items"] if i["kind"] == "topic")
    assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200
    assert _chart(client)["positions"][0]["agent"] == W


def test_agent_restored_from_trash_is_not_reseated(client, ent):
    _pos(client, "a", agent=W)
    assert client.delete("/api/agents/acme/blog/writer").status_code == 200
    item = next(i for i in client.get("/api/trash").json()["items"] if i["kind"] == "agent")
    assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200
    assert agents.exists(W) and _chart(client)["positions"][0]["agent"] is None


def test_hooks_never_raise_without_enterprises(client, topic, mx):
    enterprises.agent_gone(W)
    enterprises.remap("projects/acme", "projects/zeta")
    enterprises.deleted_with("projects/acme", mx["ws"])
    enterprises.restored(mx["ws"] / "enterprises" / "nothing")
    enterprises.restored(mx["ws"] / "projects" / "acme", "projects/acme", "projects/acme")
    assert enterprises.list_all() == []


def test_rev_is_bumped_by_every_write(client, ent):
    r0 = _chart(client)["rev"]
    _pos(client, "a")
    client.patch(f"{E}/acme-group", json={"name": "N"})
    assert _chart(client)["rev"] == r0 + 2


# ---- agent_guard.private_paths ------------------------------------------------------------------------------
def test_private_paths_hide_other_enterprises(client, ent, topic, mx):
    assert client.post("/api/workspace/projects", json={"name": "zeta"}).status_code == 200
    assert client.post(E, json={"id": "other", "projects": ["zeta"]}).status_code == 200
    _pos(client, "a", agent=W)
    root = str(mx["ws"] / "enterprises")
    mine = agent_guard.private_paths(W)
    assert f"{root}/other" in mine and f"{root}/acme-group" not in mine
    # an agent with no seat reads none of them
    free = agent_guard.private_paths(R)
    assert f"{root}/other" in free and f"{root}/acme-group" in free
    # no enterprises folder at all: unchanged behaviour
    import shutil
    shutil.rmtree(root)
    assert not [p for p in agent_guard.private_paths(W) if "/enterprises/" in p]


def test_note_unused_ceiling_fields_roundtrip(client, ent):
    r = client.patch(f"{E}/acme-group", json={
        "objectives": [{"id": "o1", "text": "Grow", "target": 10, "unit": "posts", "value": 2, "owner": "a", "parent": ""},
                       {"text": "no id"}],
        "grants": [{"id": "g1", "position": "a", "category": "spend", "ceiling": 5, "until": "2030-01-01"}]})
    c = r.json()
    assert [o["id"] for o in c["objectives"]] == ["o1"] and c["objectives"][0]["target"] == 10
    assert c["grants"][0]["ceiling"] == 5 and c["grants"][0]["until"] == "2030-01-01"
