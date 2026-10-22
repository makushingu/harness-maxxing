from __future__ import annotations


def _projects(client):
    return [p["name"] for p in client.get("/api/workspace/tree").json()["projects"]]


def _topics(client, project):
    return next([t["name"] for t in p["topics"]] for p in client.get("/api/workspace/tree").json()["projects"] if p["name"] == project)


def test_projects_and_topics_keep_the_dragged_order(client, mx):
    for p in ("alpha", "beta", "gamma"):
        assert client.post("/api/workspace/projects", json={"name": p}).status_code == 200
    for t in ("blog", "orders", "social"):
        client.post("/api/workspace/projects/beta/topics", json={"name": t})
    assert _projects(client) == ["alpha", "beta", "gamma"]                       # default: A -> Z
    r = client.put("/api/workspace/order", json={"names": ["gamma", "alpha", "nope"]})
    assert r.status_code == 200 and r.json()["projects"] == ["gamma", "alpha", "beta"]
    assert _projects(client) == ["gamma", "alpha", "beta"]                       # unlisted ones come after
    assert client.put("/api/workspace/projects/beta/order", json={"names": ["social", "blog", "orders"]}).status_code == 200
    assert _topics(client, "beta") == ["social", "blog", "orders"]
    # a new topic / project goes after the ordered ones; renames keep their place
    client.post("/api/workspace/projects/beta/topics", json={"name": "ads"})
    assert _topics(client, "beta") == ["social", "blog", "orders", "ads"]
    client.patch("/api/workspace/projects/beta/topics/blog", json={"name": "journal"})
    assert _topics(client, "beta") == ["social", "journal", "orders", "ads"]
    client.patch("/api/workspace/projects/gamma", json={"name": "omega"})
    assert _projects(client)[:2] == ["omega", "alpha"]
    # emoji and order share the project's .maxxing.json
    client.patch("/api/workspace/projects/beta", json={"emoji": "🛒"})
    assert _topics(client, "beta")[0] == "social"
    assert client.put("/api/workspace/projects/nope/order", json={"names": []}).status_code == 404
    # the Telegram "Where?" list and other users follow the same order
    from maxxing import workspace
    assert [t["name"] for t in workspace.list_topics() if t["project"] == "beta"][:2] == ["social", "journal"]
