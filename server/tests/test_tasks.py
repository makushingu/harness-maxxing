import json
import time

import pytest

from _org_helpers import client, org  # noqa: F401


def test_auth_and_csrf(client):
    assert client.get("/api/tasks").status_code == 200
    r = client.post("/api/tasks", json={"title": "x"}, headers={"X-Maxxing": ""})
    assert r.status_code == 403 and r.json()["error"] == "csrf"
    client.cookies.clear()
    assert client.get("/api/tasks").status_code == 401


def test_crud_and_order(client, org):
    assert client.get("/api/tasks").json() == {"projects": [], "tasks": []}
    a = client.post("/api/tasks", json={"title": " Write docs ", "priority": 2, "due": "2026-01-02",
                                        "labels": ["doc", "doc", " x "]}).json()
    assert a["id"].startswith("t_") and len(a["id"]) == 8
    assert a["title"] == "Write docs" and a["status"] == "todo" and a["labels"] == ["doc", "x"]
    assert a["done_at"] is None and a["order"] == 1.0
    b = client.post("/api/tasks", json={"title": "Second"}).json()
    assert b["order"] == 2.0
    c = client.post("/api/tasks", json={"title": "Doing", "status": "doing"}).json()
    assert c["order"] == 1.0                                        # own column

    done = client.patch(f"/api/tasks/{a['id']}", json={"status": "done"}).json()
    assert done["done_at"] and done["updated"] >= a["updated"]
    again = client.patch(f"/api/tasks/{a['id']}", json={"status": "done"}).json()
    assert again["done_at"] == done["done_at"]
    back = client.patch(f"/api/tasks/{a['id']}", json={"status": "todo", "order": 0.5, "due": None}).json()
    assert back["done_at"] is None and back["order"] == 0.5 and back["due"] is None

    assert client.delete(f"/api/tasks/{b['id']}").json() == {"ok": True}
    assert client.delete(f"/api/tasks/{b['id']}").status_code == 404
    on_disk = json.loads((org.ws / "tasks.json").read_text())
    assert on_disk["version"] == 1 and {t["id"] for t in on_disk["tasks"]} == {a["id"], c["id"]}


def test_validation(client):
    assert client.post("/api/tasks", json={}).json()["error"] == "invalid_title"
    assert client.post("/api/tasks", json={"title": "  "}).status_code == 400
    assert client.post("/api/tasks", json={"title": "x", "due": "2026-13-01"}).json()["error"] == "invalid_due"
    assert client.post("/api/tasks", json={"title": "x", "priority": 7}).json()["error"] == "invalid_priority"
    assert client.post("/api/tasks", json={"title": "x", "project_id": "p_nope"}).json()["error"] == "invalid_project"
    assert client.post("/api/tasks", json={"title": "x", "status": "later"}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x", "topic_path": "../etc"}).status_code == 400
    assert client.patch("/api/tasks/t_nope", json={"title": "y"}).status_code == 404


def test_projects(client):
    p = client.post("/api/tasks/projects", json={"name": "Acme", "color": "blue"}).json()
    assert p["id"].startswith("p_") and len(p["id"]) == 6
    t = client.post("/api/tasks", json={"title": "x", "project_id": p["id"]}).json()
    assert t["project_id"] == p["id"]
    p2 = client.patch(f"/api/tasks/projects/{p['id']}", json={"color": "#aabbcc"}).json()
    assert p2 == {**p, "color": "#aabbcc"}
    assert client.patch(f"/api/tasks/projects/{p['id']}", json={"color": "red; x"}).status_code == 400
    assert client.post("/api/tasks/projects", json={"name": ""}).status_code == 400
    assert client.delete(f"/api/tasks/projects/{p['id']}").json() == {"ok": True}
    data = client.get("/api/tasks").json()
    assert data["projects"] == [] and data["tasks"][0]["project_id"] is None
    assert client.delete(f"/api/tasks/projects/{p['id']}").status_code == 404


def test_external_edits_and_unknown_fields(client, org):
    f = org.ws / "tasks.json"
    f.write_text(json.dumps({"version": 1, "owner": "claude", "projects": [],
                             "tasks": [{"id": "t_aaaaaa", "title": "Hand made", "status": "weird", "extra": [1]},
                                       {"title": "No id"}]}))
    data = client.get("/api/tasks").json()
    ids = [t["id"] for t in data["tasks"]]
    assert ids[0] == "t_aaaaaa" and data["tasks"][0]["status"] == "todo"
    assert ids[1].startswith("t_") and client.get("/api/tasks").json()["tasks"][1]["id"] == ids[1]   # stable
    client.patch("/api/tasks/t_aaaaaa", json={"title": "Edited"})
    raw = json.loads(f.read_text())
    assert raw["owner"] == "claude" and raw["tasks"][0]["extra"] == [1] and raw["tasks"][0]["title"] == "Edited"

    time.sleep(0.01)                                                   # Claude edits the file again
    raw["tasks"].append({"id": "t_bbbbbb", "title": "From Claude", "status": "doing"})
    f.write_text(json.dumps(raw))
    assert "t_bbbbbb" in [t["id"] for t in client.get("/api/tasks").json()["tasks"]]


def test_corrupt_file_never_overwritten(client, org):
    f = org.ws / "tasks.json"
    f.write_text('{"tasks": [')
    r = client.get("/api/tasks")
    assert r.status_code == 409 and r.json()["error"] == "corrupt_file"
    assert client.post("/api/tasks", json={"title": "x"}).status_code == 409
    assert f.read_text() == '{"tasks": ['


def test_summary(client, org):
    from maxxing.api import tasks
    today = tasks._today().isoformat()
    client.post("/api/tasks", json={"title": "late", "due": "2000-01-01"})
    client.post("/api/tasks", json={"title": "today", "due": today})
    client.post("/api/tasks", json={"title": "doing", "status": "doing"})
    client.post("/api/tasks", json={"title": "done", "status": "done", "due": "2000-01-01"})
    s = tasks.summary()
    assert (s["overdue"], s["due_today"], s["doing"], s["open"]) == (1, 1, 1, 3)
    assert [t["title"] for t in s["items"]] == ["late", "today", "doing"]


def test_summary_does_not_compare_every_doing_task_with_every_listed_one(monkeypatch):
    from maxxing.api import tasks
    compared = [0]

    class Task(dict):
        def __eq__(self, other):
            compared[0] += 1
            return dict.__eq__(self, other)
        __hash__ = None

    today = tasks._today().isoformat()
    rows = [Task(id=f"t{i}", status="doing", due="2000-01-01" if i % 2 else None) for i in range(400)]
    monkeypatch.setattr(tasks, "load", lambda copy_=True: {"tasks": rows, "projects": []})
    s = tasks.summary()
    assert (s["doing"], s["overdue"], len(s["items"])) == (400, 200, 400) and today
    assert compared[0] < 400


def test_labels_are_capped(client):
    many = [f"l{i}" for i in range(51)]
    r = client.post("/api/tasks", json={"title": "t", "labels": many})
    assert r.status_code == 400 and "invalid_labels" in r.text
    t = client.post("/api/tasks", json={"title": "t", "labels": many[:50] + many[:50]}).json()
    assert t["labels"] == many[:50]
    r = client.post("/api/tasks/bulk", json={"ids": [t["id"]], "labels_add": ["extra"]})
    assert r.status_code == 400 and "invalid_labels" in r.text
    r = client.post("/api/tasks/bulk", json={"ids": [t["id"]], "labels_add": many[:10]})
    assert r.status_code == 200


def test_bulk(client, org):
    p = client.post("/api/tasks/projects", json={"name": "Site", "color": "blue"}).json()
    ids = [client.post("/api/tasks", json={"title": f"T{i}", "labels": ["old"]}).json()["id"] for i in range(3)]
    d = client.post("/api/tasks", json={"title": "Done already", "status": "done"}).json()

    r = client.post("/api/tasks/bulk", json={"ids": ids[:2] + ["t_nope"], "patch": {"status": "done", "priority": 3,
                                             "project_id": p["id"], "due": "2026-03-01"},
                                             "labels_add": ["new"], "labels_remove": ["old"]})
    assert r.json() == {"ok": True, "updated": 2, "deleted": 0}
    tasks = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    for i in ids[:2]:
        t = tasks[i]
        assert t["status"] == "done" and t["done_at"] and t["priority"] == 3 and t["project_id"] == p["id"]
        assert t["due"] == "2026-03-01" and t["labels"] == ["new"]
    # moved tasks land on top of "done", keeping their relative order
    done = sorted((t for t in tasks.values() if t["status"] == "done"), key=lambda t: t["order"])
    assert [t["id"] for t in done] == ids[:2] + [d["id"]]
    assert tasks[ids[2]]["status"] == "todo" and tasks[ids[2]]["labels"] == ["old"]

    r = client.post("/api/tasks/bulk", json={"ids": ids[:2], "patch": {"due": None, "status": "todo"}})
    assert r.json()["updated"] == 2
    tasks = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert tasks[ids[0]]["due"] is None and tasks[ids[0]]["done_at"] is None
    assert tasks[ids[0]]["order"] > tasks[ids[2]]["order"]               # appended at the bottom of "todo"

    assert client.post("/api/tasks/bulk", json={"ids": ids, "patch": {"project_id": "p_nope"}}).status_code == 400
    assert client.post("/api/tasks/bulk", json={"ids": []}).status_code == 400
    assert client.post("/api/tasks/bulk", json={"ids": ids[:2], "delete": True}).json()["deleted"] == 2
    assert {t["id"] for t in client.get("/api/tasks").json()["tasks"]} == {ids[2], d["id"]}


def test_bulk_lands_below_selected_tasks_already_there(client, org):
    a = client.post("/api/tasks", json={"title": "A", "status": "doing", "order": 100}).json()
    client.post("/api/tasks", json={"title": "X", "status": "doing", "order": 10})
    b = client.post("/api/tasks", json={"title": "B"}).json()
    client.post("/api/tasks/bulk", json={"ids": [a["id"], b["id"]], "patch": {"status": "doing"}})
    tasks = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert tasks[b["id"]]["order"] > tasks[a["id"]]["order"]


@pytest.fixture
def wsclient(org, monkeypatch):
    from fastapi.testclient import TestClient
    from maxxing import app as app_module
    from maxxing import security
    from _org_helpers import ORG_ROUTERS, PASSWORD
    monkeypatch.setattr(app_module, "ROUTERS", ORG_ROUTERS + ["workspace"])
    security.set_password(PASSWORD)
    with TestClient(app_module.create_app()) as c:
        c.post("/api/auth/login", json={"password": PASSWORD}, headers={"X-Maxxing": "1"})
        c.headers["X-Maxxing"] = "1"
        yield c


def test_workspace_projects_are_task_projects(wsclient, org):
    client = wsclient
    free = client.post("/api/tasks/projects", json={"name": "Acme", "color": "blue"}).json()
    assert client.post("/api/workspace/projects", json={"name": "acme"}).status_code == 200
    client.post("/api/workspace/projects", json={"name": "blog"})
    data = client.get("/api/tasks").json()
    by_ws = {p.get("workspace"): p for p in data["projects"]}
    assert by_ws["acme"]["id"] == free["id"]                       # same name: linked, not duplicated
    assert by_ws["blog"]["name"] == "blog" and by_ws["blog"]["color"]
    assert len([p for p in data["projects"] if p["name"].lower() == "acme"]) == 1
    # a linked project cannot be deleted, it can be hidden
    blog = by_ws["blog"]
    assert client.delete(f"/api/tasks/projects/{blog['id']}").json()["error"] == "linked_project"
    assert client.patch(f"/api/tasks/projects/{blog['id']}", json={"hidden": True}).json()["hidden"] is True
    assert "hidden" not in client.patch(f"/api/tasks/projects/{blog['id']}", json={"hidden": False}).json()
    # a task in a topic gets the topic's project
    client.post("/api/workspace/projects/blog/topics", json={"name": "posts"})
    t = client.post("/api/tasks", json={"title": "x", "topic_path": "projects/blog/topics/posts"}).json()
    assert t["project_id"] == blog["id"]
    # a hand-written task with a topic but no project is attached on read
    raw = json.loads((org.ws / "tasks.json").read_text())
    raw["tasks"].append({"id": "t_hand01", "title": "hand", "topic_path": "projects/acme"})
    (org.ws / "tasks.json").write_text(json.dumps(raw))
    hand = next(x for x in client.get("/api/tasks").json()["tasks"] if x["id"] == "t_hand01")
    assert hand["project_id"] == free["id"]
    # rename follows (project name, link and topic paths)
    assert client.patch("/api/workspace/projects/blog", json={"name": "journal"}).status_code == 200
    data = client.get("/api/tasks").json()
    j = next(p for p in data["projects"] if p["id"] == blog["id"])
    assert j["workspace"] == "journal" and j["name"] == "journal"
    assert next(x for x in data["tasks"] if x["id"] == t["id"])["topic_path"] == "projects/journal/topics/posts"
    client.patch("/api/workspace/projects/journal/topics/posts", json={"name": "notes"})
    assert next(x for x in client.get("/api/tasks").json()["tasks"]
                if x["id"] == t["id"])["topic_path"] == "projects/journal/topics/notes"
    # deleting the workspace project keeps its tasks in a free project
    assert client.delete("/api/workspace/projects/journal").status_code == 200
    data = client.get("/api/tasks").json()
    j = next(p for p in data["projects"] if p["id"] == blog["id"])
    assert "workspace" not in j and next(x for x in data["tasks"] if x["id"] == t["id"])["project_id"] == blog["id"]
    assert client.delete(f"/api/tasks/projects/{blog['id']}").json() == {"ok": True}


def test_system_project_hidden_by_default(client, org):
    (org.ws / "projects" / "system").mkdir(parents=True, exist_ok=True)       # created by hand
    proj = next(p for p in client.get("/api/tasks").json()["projects"] if p.get("workspace") == "system")
    assert proj["hidden"] is True


def test_infinite_order_is_refused_and_the_list_still_loads(client, org):
    a = client.post("/api/tasks", json={"title": "a"}).json()
    raw = '{"title": "b", "order": 1e999}'
    assert client.post("/api/tasks", content=raw, headers={"content-type": "application/json"}).status_code == 422
    r = client.patch(f"/api/tasks/{a['id']}", content='{"order": 1e999}', headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert client.get("/api/tasks").status_code == 200


def test_bulk_over_the_limit_is_refused_not_cut(client, org):
    from maxxing.api import tasks as tasks_api
    ids = [client.post("/api/tasks", json={"title": f"t{i}"}).json()["id"] for i in range(3)]
    tasks_api.BULK_MAX, old = 2, tasks_api.BULK_MAX
    try:
        r = client.post("/api/tasks/bulk", json={"ids": ids, "patch": {"status": "done"}})
    finally:
        tasks_api.BULK_MAX = old
    assert r.status_code == 400 and "too_many_ids" in r.text
    assert all(t["status"] == "todo" for t in client.get("/api/tasks").json()["tasks"])
