"""Trash: list, restore (topics with their sessions, files, single sessions), delete, empty, purge."""
from __future__ import annotations

import json
import time

from maxxing import trash

from conftest import wait_idle


def _items(client):
    return client.get("/api/trash").json()["items"]


def test_topic_restored_with_its_sessions(client, topic, mx):
    s = client.post("/api/sessions", json={"path": topic, "message": "hello NOTOOL"}).json()
    wait_idle(client, s["id"])
    (mx["ws"] / topic / "notes.md").write_text("keep me")
    assert client.delete("/api/workspace/projects/acme/topics/blog").status_code == 200
    items = _items(client)
    assert len(items) == 1
    it = items[0]
    assert it["kind"] == "topic" and it["name"] == "blog" and it["original"] == topic
    assert it["sessions"] == 1 and it["restorable"] and it["size"] > 0
    r = client.post(f"/api/trash/{it['id']}/restore").json()
    assert r["ok"] and r["restored_to"] == topic and r["sessions"] == 1
    assert (mx["ws"] / topic / "notes.md").read_text() == "keep me"
    assert client.get(f"/api/sessions/{s['id']}").json()["path"] == topic
    assert _items(client) == []
    # the session still works
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "again NOTOOL"})
    assert wait_idle(client, s["id"])["state"] == "idle"


def test_restore_next_to_a_new_topic_with_the_same_name(client, topic, mx):
    s = client.post("/api/sessions", json={"path": topic, "message": "old NOTOOL"}).json()
    wait_idle(client, s["id"])
    client.delete("/api/workspace/projects/acme/topics/blog")
    client.post("/api/workspace/projects/acme/topics", json={"name": "blog"})
    r = client.post(f"/api/trash/{_items(client)[0]['id']}/restore").json()
    assert r["restored_to"] == "projects/acme/topics/blog-restored"
    assert client.get(f"/api/sessions/{s['id']}").json()["path"] == "projects/acme/topics/blog-restored"
    paths = [t["path"] for p in client.get("/api/workspace/tree").json()["projects"] for t in p["topics"]]
    assert "projects/acme/topics/blog-restored" in paths and topic in paths


def test_deleted_session_goes_to_the_trash(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "zebra NOTOOL"}).json()
    wait_idle(client, s["id"])
    client.patch(f"/api/sessions/{s['id']}", json={"title": "Zebra plan"})
    assert client.delete(f"/api/sessions/{s['id']}").json() == {"ok": True}
    assert client.get(f"/api/sessions/{s['id']}").status_code == 404
    it = _items(client)[0]
    assert it["kind"] == "session" and it["name"] == "Zebra plan" and it["original"] == topic
    client.post(f"/api/trash/{it['id']}/restore")
    back = client.get(f"/api/sessions/{s['id']}").json()
    assert back["title"] == "Zebra plan" and back["path"] == topic and back["turns"] == 1


def test_session_of_a_deleted_topic_comes_back_at_the_root(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "x NOTOOL"}).json()
    wait_idle(client, s["id"])
    client.delete(f"/api/sessions/{s['id']}")
    sess_item = _items(client)[0]["id"]
    client.delete("/api/workspace/projects/acme/topics/blog")
    client.post(f"/api/trash/{sess_item}/restore")
    assert client.get(f"/api/sessions/{s['id']}").json()["path"] == ""


def test_file_restore_delete_empty_and_purge(client, topic, mx):
    f = mx["files"] / "draft.md"
    f.write_text("v1")
    assert client.post("/api/files/delete", json={"path": str(f)}).status_code == 200
    it = _items(client)[0]
    assert it["kind"] == "file" and it["name"] == "draft.md"
    f.write_text("v2")                                       # a new file took the name
    assert client.post(f"/api/trash/{it['id']}/restore").json()["restored_to"].endswith("draft (restored).md")
    assert (mx["files"] / "draft (restored).md").read_text() == "v1" and f.read_text() == "v2"
    # delete forever, empty
    client.post("/api/files/delete", json={"path": str(f)})
    assert client.delete(f"/api/trash/{_items(client)[0]['id']}").json() == {"ok": True}
    assert _items(client) == []
    client.post("/api/files/delete", json={"path": str(mx["files"] / "draft (restored).md")})
    assert client.delete("/api/trash").json() == {"ok": True, "deleted": 1}
    # items older than KEEP_DAYS are purged
    g = mx["files"] / "old.md"
    g.write_text("old")
    client.post("/api/files/delete", json={"path": str(g)})
    side = next(p for p in trash.trash_dir().glob("*.json"))
    d = json.loads(side.read_text())
    d["at"] = time.time() - 40 * 86400
    side.write_text(json.dumps(d))
    assert _items(client) == []
    # bad ids
    assert client.post("/api/trash/..%2Fsessions/restore").status_code in (400, 404)
    assert client.post("/api/trash/nope/restore").status_code == 404


def test_sizes_cached_and_purge_at_most_hourly(client, mx, monkeypatch):
    f = mx["files"] / "big.bin"
    f.write_bytes(b"x" * 1000)
    client.post("/api/files/delete", json={"path": str(f)})
    it = _items(client)[0]
    assert it["size"] == 1000
    walks = []
    real = trash._size
    monkeypatch.setattr(trash, "_size", lambda p: walks.append(p) or real(p))
    assert _items(client)[0]["size"] == 1000 and walks == []           # cached
    (trash.trash_dir() / it["id"]).write_bytes(b"y" * 10)             # the item changed -> walked again
    assert _items(client)[0]["size"] == 10 and walks
    purges = []
    monkeypatch.setattr(trash, "purge_old", lambda days=trash.KEEP_DAYS: purges.append(1) or 0)
    for _ in range(3):
        _items(client)
    assert purges == []                                                # purged by the first listing already
    trash.invalidate_sizes()
    _items(client)
    _items(client)
    assert purges == [1]


def test_listing_reused_until_an_entry_changes(client, mx, monkeypatch):
    f = mx["files"] / "a.md"
    f.write_text("a")
    client.post("/api/files/delete", json={"path": str(f)})
    assert len(_items(client)) == 1
    builds = []
    real = trash._build
    monkeypatch.setattr(trash, "_build", lambda t, root: builds.append(1) or real(t, root))
    _items(client)
    assert builds == []                                                # nothing changed: same listing
    g = mx["files"] / "b.md"
    g.write_text("b")
    client.post("/api/files/delete", json={"path": str(g)})            # a new entry
    assert len(_items(client)) == 2 and builds == [1]
    side = next(p for p in trash.trash_dir().glob("*.json"))           # a sidecar rewritten (any process)
    d = json.loads(side.read_text())
    d["title"] = "Renamed"
    side.write_text(json.dumps(d))
    assert "Renamed" in {i["name"] for i in _items(client)} and builds == [1, 1]
    d["at"] = time.time() - 40 * 86400                                 # expired: hidden at once
    side.write_text(json.dumps(d) + " ")
    assert len(_items(client)) == 1


def test_file_with_a_long_name_goes_to_the_trash_and_back(client, mx):
    f = mx["files"] / ("a" * 250 + ".txt")                   # 254 bytes: a legal name, too long with the stamp
    f.write_text("x")
    assert client.post("/api/files/delete", json={"path": str(f)}).status_code == 200
    it = _items(client)[0]
    assert it["name"] == f.name and it["restorable"]
    assert client.post(f"/api/trash/{it['id']}/restore").status_code == 200 and f.read_text() == "x"


def test_long_name_cut_inside_a_character_still_lists(client, mx):
    f = mx["files"] / ("a" + "日" * 70 + ".txt")             # cut at 180 bytes lands inside a 3-byte character
    f.write_text("x")
    assert client.post("/api/files/delete", json={"path": str(f)}).status_code == 200
    r = client.get("/api/trash")
    assert r.status_code == 200
    it = _items(client)[0]
    assert it["name"] == f.name
    assert client.post(f"/api/trash/{it['id']}/restore").status_code == 200 and f.read_text() == "x"


def test_deleted_json_file_is_listed_restored_and_emptied(client, mx):
    f = mx["files"] / "export.json"
    f.write_text('{"a": 1}')
    assert client.post("/api/files/delete", json={"path": str(f)}).status_code == 200
    items = _items(client)
    assert [i["name"] for i in items] == ["export.json"] and items[0]["restorable"]
    assert client.post(f"/api/trash/{items[0]['id']}/restore").status_code == 200 and f.read_text() == '{"a": 1}'
    g = mx["files"] / "old.sessions"
    g.write_text("x")
    for p in (f, g):
        client.post("/api/files/delete", json={"path": str(p)})
    assert sorted(i["name"] for i in _items(client)) == ["export.json", "old.sessions"]
    assert client.delete("/api/trash").json() == {"ok": True, "deleted": 2}
    assert list(trash.trash_dir().iterdir()) == []
