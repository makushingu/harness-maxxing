from __future__ import annotations

from maxxing import config, workspace

from conftest import wait_idle


def test_create_tree_and_files(client, mx):
    r = client.post("/api/workspace/projects", json={"name": "acme", "description": "Acme shop"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p == {"name": "acme", "path": "projects/acme", "description": "Acme shop", "emoji": "", "topics": [],
                 "session_count": 0}
    t = client.post("/api/workspace/projects/acme/topics", json={"name": "blog", "description": "Posts"}).json()
    assert t["path"] == "projects/acme/topics/blog"
    assert t["telegram_thread"] is None and t["running"] == 0 and t["unread"] == 0
    claude_md = (mx["ws"] / "projects/acme/topics/blog/CLAUDE.md").read_text()
    assert "Posts" in claude_md and "@memory.md" in claude_md
    assert (mx["ws"] / "projects/acme/topics/blog/memory.md").exists()
    assert (mx["ws"] / "CLAUDE.md").exists()
    tree = client.get("/api/workspace/tree").json()
    assert tree["root"] == str(mx["ws"])
    assert tree["projects"][0]["topics"][0]["description"] == "Posts"
    assert workspace.list_topics() == [{"path": "projects/acme/topics/blog", "project": "acme",
                                        "name": "blog", "description": "Posts"}]


def test_slug_validation_and_conflicts(client):
    assert client.post("/api/workspace/projects", json={"name": "Bad Name"}).json()["error"] == "invalid_name"
    assert client.post("/api/workspace/projects", json={"name": "-x"}).status_code == 400
    assert client.post("/api/workspace/projects", json={"name": "ok"}).status_code == 200
    assert client.post("/api/workspace/projects", json={"name": "ok"}).status_code == 409
    assert client.post("/api/workspace/projects/missing/topics", json={"name": "a"}).status_code == 404


def test_description_update_keeps_user_content(client, mx):
    client.post("/api/workspace/projects", json={"name": "acme", "description": "Old"})
    f = mx["ws"] / "projects/acme/CLAUDE.md"
    f.write_text(f.read_text() + "\n## Rules\n- be nice\n")
    r = client.patch("/api/workspace/projects/acme", json={"description": "New text"})
    assert r.json()["description"] == "New text"
    body = f.read_text()
    assert "New text" in body and "Old" not in body and "## Rules" in body and "@memory.md" in body


def test_rename_remaps_sessions_and_telegram(client, topic, mx):
    config.update_config(telegram={"threads": {topic: 42}})
    s = client.post("/api/sessions", json={"path": topic, "message": "hello NOTOOL"}).json()
    wait_idle(client, s["id"])
    tree = client.get("/api/workspace/tree").json()
    assert tree["projects"][0]["topics"][0]["telegram_thread"] == 42
    r = client.patch("/api/workspace/projects/acme/topics/blog", json={"name": "news"})
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "projects/acme/topics/news"
    assert r.json()["telegram_thread"] == 42
    assert (mx["ws"] / "projects/acme/topics/news/CLAUDE.md").read_text().startswith("# Topic news")
    assert client.get(f"/api/sessions/{s['id']}").json()["path"] == "projects/acme/topics/news"
    # project rename moves everything below it
    r = client.patch("/api/workspace/projects/acme", json={"name": "acme2"})
    assert r.json()["topics"][0]["path"] == "projects/acme2/topics/news"
    assert client.get(f"/api/sessions/{s['id']}").json()["path"] == "projects/acme2/topics/news"
    assert config.load_config()["telegram"]["threads"] == {"projects/acme2/topics/news": 42}
    # the session still works from the new folder
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "again NOTOOL"})
    assert wait_idle(client, s["id"])["state"] == "idle"


def test_rename_running_topic_is_not_reported_as_existing(client, topic, mx):
    s = client.post("/api/sessions", json={"path": topic, "message": "SLOW"}).json()
    r = client.patch("/api/workspace/projects/acme/topics/blog", json={"name": "news"})
    assert r.status_code == 409 and r.json()["error"] == "has_running_sessions"
    client.post(f"/api/sessions/{s['id']}/stop")
    assert (mx["ws"] / "projects/acme/topics/blog").is_dir()


def test_delete_to_trash_and_running_conflict(client, topic, mx):
    s = client.post("/api/sessions", json={"path": topic, "message": "SLOW"}).json()
    r = client.delete("/api/workspace/projects/acme/topics/blog")
    assert r.status_code == 409 and r.json()["error"] == "has_running_sessions"
    client.post(f"/api/sessions/{s['id']}/stop")
    assert client.delete("/api/workspace/projects/acme/topics/blog").status_code == 200
    assert not (mx["ws"] / "projects/acme/topics/blog").exists()
    trash = list((mx["state"] / "trash").iterdir())
    assert any(p.name.endswith(".json") for p in trash)
    assert client.get(f"/api/sessions/{s['id']}").status_code == 404
    assert client.delete("/api/workspace/projects/acme").status_code == 200
    assert client.get("/api/workspace/tree").json()["projects"] == []


def test_on_change_callbacks(client):
    seen: list = []
    workspace.on_change(lambda change: seen.append(change))
    workspace.on_change(lambda: seen.append("noarg"))
    try:
        client.post("/api/workspace/projects", json={"name": "zeta"})
        assert {"action": "created", "kind": "project", "path": "projects/zeta", "old_path": None} in seen
        assert "noarg" in seen
    finally:
        workspace._callbacks.clear()


def test_requires_auth(mx):
    from fastapi.testclient import TestClient

    from maxxing.app import create_app
    with TestClient(create_app()) as c:
        assert c.get("/api/workspace/tree").status_code == 401


def test_project_emoji(client, mx):
    client.post("/api/workspace/projects", json={"name": "shop"})
    client.post("/api/workspace/projects/shop/topics", json={"name": "blog"})
    p = client.patch("/api/workspace/projects/shop", json={"emoji": "🛒"}).json()
    assert p["emoji"] == "🛒"
    assert client.get("/api/workspace/tree").json()["projects"][0]["emoji"] == "🛒"
    for bad in ("ab", "🛒 shop", "x" * 20, "12"):
        assert client.patch("/api/workspace/projects/shop", json={"emoji": bad}).status_code == 400
    assert client.patch("/api/workspace/projects/shop", json={"emoji": "🇫🇷"}).json()["emoji"] == "🇫🇷"   # flag: 2 code points
    # stored with the project folder: kept by a rename, listed by the backup
    p = client.patch("/api/workspace/projects/shop", json={"name": "store"}).json()
    assert p["emoji"] == "🇫🇷" and (workspace.project_dir("store") / ".maxxing.json").exists()
    from maxxing import backup
    assert "projects/store/.maxxing.json" in backup.collect(workspace.root())
    from maxxing.telegram import gateway
    assert gateway.session_label({"path": "projects/store/topics/blog", "title": "Launch plan"}) == "🇫🇷 store/blog · Launch plan"
    assert gateway.topic_label("projects/store/topics/blog") == "🇫🇷 store / blog"          # "Where?" buttons
    assert client.patch("/api/workspace/projects/store", json={"emoji": ""}).json()["emoji"] == ""
    assert not (workspace.project_dir("store") / ".maxxing.json").exists()
    assert gateway.session_label({"path": "projects/store/topics/blog", "title": "Launch plan"}) == "store/blog · Launch plan"
