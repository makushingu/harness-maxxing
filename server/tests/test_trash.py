"""Trash: list, restore (topics with their sessions, files, single sessions), delete, empty, purge."""
from __future__ import annotations

import json
import os
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


def test_topic_of_a_project_in_the_trash_waits_for_the_project(client, topic, mx):
    """Restoring the topic first made a bare project folder, then the project came back as "acme-restored"."""
    client.delete("/api/workspace/projects/acme/topics/blog")
    client.delete("/api/workspace/projects/acme")
    by_kind = {i["kind"]: i for i in _items(client)}
    r = client.post(f"/api/trash/{by_kind['topic']['id']}/restore")
    assert r.status_code == 409 and r.json()["error"] == "project_in_trash"
    assert not (mx["ws"] / "projects/acme").exists()
    assert client.post(f"/api/trash/{by_kind['project']['id']}/restore").json()["restored_to"] == "projects/acme"
    assert client.post(f"/api/trash/{by_kind['topic']['id']}/restore").json()["restored_to"] == topic


def test_a_file_named_like_a_project_is_a_file_in_the_trash(client, mx):
    f = mx["files"] / "project-plan.md"
    f.write_text("v1")
    client.post("/api/files/delete", json={"path": str(f)})
    it = _items(client)[0]
    assert it["kind"] == "file"
    f.write_text("v2")
    assert client.post(f"/api/trash/{it['id']}/restore").json()["restored_to"].endswith("project-plan (restored).md")


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


def test_a_file_name_that_is_not_utf8_goes_to_the_trash_and_the_trash_still_lists(client, mx):
    f = mx["files"] / os.fsdecode(b"bad\xff.txt")
    f.write_text("x")
    r = client.post("/api/files/delete", content=json.dumps({"path": str(f)}),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 200 and not f.exists()
    r = client.get("/api/trash")
    assert r.status_code == 200
    it = _items(client)[0]
    assert it["name"] == "bad\ufffd.txt" and it["restorable"]
    assert client.post(f"/api/trash/{it['id']}/restore").status_code == 200
    assert (mx["files"] / "bad\ufffd.txt").read_text() == "x"


def test_an_old_entry_named_outside_utf8_does_not_break_the_listing(client, mx):
    (trash.trash_dir() / os.fsdecode(b"20260101-000000-bad\xff.txt")).write_text("x")
    assert client.get("/api/trash").status_code == 200 and _items(client) == []
    assert client.delete("/api/trash").status_code == 200 and not any(trash.trash_dir().iterdir())


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


def test_a_link_to_a_folder_is_emptied_from_the_trash_and_its_target_kept(client, topic, mx):
    from maxxing import workspace
    outside = mx["tmp"] / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x")
    os.symlink(outside, mx["ws"] / topic / "lnk")
    workspace.move_to_trash(mx["ws"] / topic / "lnk")
    assert len(client.get("/api/trash").json()["items"]) == 1
    assert client.delete("/api/trash").status_code == 200
    assert client.get("/api/trash").json()["items"] == []
    assert (outside / "keep.txt").exists()


def test_the_size_of_a_link_is_the_link_not_its_target(client, topic, mx):
    from maxxing import workspace
    outside = mx["tmp"] / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * 5000)
    os.symlink(outside, mx["ws"] / topic / "lnk")
    d = mx["ws"] / topic / "folder"
    d.mkdir()
    (d / "small.txt").write_text("abc")
    os.symlink(outside / "big.bin", d / "big-link")
    workspace.move_to_trash(mx["ws"] / topic / "lnk")
    workspace.move_to_trash(d)
    sizes = {i["name"]: i["size"] for i in client.get("/api/trash").json()["items"]}
    assert sizes["lnk"] < 1000 and 3 <= sizes["folder"] < 1000, sizes


def test_a_damaged_sidecar_does_not_break_the_trash(client, topic, mx):
    from maxxing import workspace
    for name, side in (("a.txt", {"original": 12, "at": "soon"}), ("b.txt", {"original": "x\u0000y", "at": 1e400}),
                       ("c.txt", {"title": ["x"], "at": True})):
        (mx["ws"] / topic / name).write_text("a")
        workspace.move_to_trash(mx["ws"] / topic / name)
        sc = next(j for j in trash.trash_dir().glob("*.json") if j.name.endswith(f"-{name}.json"))
        sc.write_text(json.dumps(side).replace("Infinity", "1e400"))
    r = client.get("/api/trash")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 3 and not any(i["restorable"] for i in items)
    assert trash.purge_old() == 0


def test_restore_never_writes_outside_the_workspace(client, topic, mx):
    from maxxing import workspace
    target = mx["tmp"] / "elsewhere" / "pwn.txt"
    climb = str(mx["ws"] / topic / "../../../../../pwn.txt")             # the folder above the workspace
    for name, original in (("a.txt", str(target)), ("b.txt", climb)):
        (mx["ws"] / topic / name).write_text("a")
        workspace.move_to_trash(mx["ws"] / topic / name)
        sc = next(j for j in trash.trash_dir().glob("*.json") if j.name.endswith(f"-{name}.json"))
        sc.write_text(json.dumps({"original": original, "at": 1}))
        r = client.post(f"/api/trash/{sc.name[:-5]}/restore")
        assert r.status_code == 409, r.text
    assert not target.exists() and not (mx["ws"].parent / "pwn.txt").exists()
    sid = client.post("/api/sessions", json={"path": topic}).json()["id"]
    assert client.delete(f"/api/sessions/{sid}").status_code == 200
    item = next(i for i in client.get("/api/trash").json()["items"] if i["kind"] == "session")
    sc = trash.trash_dir() / (item["id"] + ".json")
    sc.write_text(json.dumps({**json.loads(sc.read_text()), "path": "../../outside"}))
    r = client.post(f"/api/trash/{item['id']}/restore")
    assert r.status_code == 200 and r.json()["restored_to"] == "", r.text


def _agent(client, name="writer"):
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": name})
    assert r.status_code == 200, r.text
    return f"projects/acme/topics/blog/agents/{name}"


def test_a_new_agent_in_a_recreated_topic_starts_empty_and_the_restored_topic_gets_its_thread(client, topic):
    from maxxing import agents, crons
    a = _agent(client)
    agents.post(a, "result", "SECRET RESULT OF OLD AGENT")
    agents.remember_telegram(a, [101], "msg_a")
    job = client.post("/api/agents/acme/blog/writer/crons", json={"prompt": "NOTOOL x"}).json()
    assert client.delete("/api/workspace/projects/acme/topics/blog").status_code == 200
    assert crons.get_job(job["id"]) is None
    client.post("/api/workspace/projects/acme/topics", json={"name": "blog"})
    _agent(client)
    assert [m["text"] for m in agents.thread(a)] == ["Agent created"]
    assert agents.telegram_reply_to(a, 101) is None
    item = next(i for i in _items(client) if i["kind"] == "topic")
    assert client.delete("/api/agents/acme/blog/writer").status_code == 200    # nothing left at the old path
    r = client.post(f"/api/trash/{item['id']}/restore").json()
    assert r["restored_to"] == "projects/acme/topics/blog-restored"
    old = "projects/acme/topics/blog-restored/agents/writer"
    assert "SECRET RESULT OF OLD AGENT" in [m["text"] for m in agents.thread(old)]
    assert agents.telegram_reply_to(old, 101) == "msg_a"
    assert crons.get_job(job["id"])["topic_path"] == old
    assert agents.thread(a) == []


def test_a_restored_agent_whose_name_was_taken_comes_back_as_an_agent(client, topic):
    from maxxing import agents, crons
    a = _agent(client)
    run = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL hi"}).json()
    wait_idle(client, run["session"]["id"])
    job = client.post("/api/agents/acme/blog/writer/crons", json={"prompt": "NOTOOL x"}).json()
    assert client.delete("/api/agents/acme/blog/writer").status_code == 200
    _agent(client)
    item = next(i for i in _items(client) if i["kind"] == "agent")
    assert not [i for i in _items(client) if i["name"].endswith(".agents")]   # the state box is not an item
    r = client.post(f"/api/trash/{item['id']}/restore").json()
    new = "projects/acme/topics/blog/agents/writer-restored"
    assert r["restored_to"] == new
    assert sorted(agents.names("acme", "blog")) == ["writer", "writer-restored"]
    assert client.get(f"/api/sessions/{run['session']['id']}").json()["path"] == new
    assert any(m["kind"] == "run" for m in agents.thread(new))
    assert crons.get_job(job["id"])["topic_path"] == new
    assert agents.run_settings(new)["sandbox"] is True
    assert [m["text"] for m in agents.thread(a)] == ["Agent created"]


import pytest  # noqa: E402


@pytest.mark.parametrize("linked", [False, True])
def test_an_agent_comes_back_with_its_crons_and_thread_even_through_a_linked_workspace(client, topic, mx, linked):
    """The workspace may sit behind a symbolic link (/root/maxxing -> /data/maxxing): the restore still brings back
    the agent's cron jobs and thread and empties its .agents box (negative case: a plain workspace, as before)."""
    from maxxing import agents, config, crons
    A = "projects/acme/topics/blog/agents/writer"
    if linked:
        link = mx["tmp"] / "wslink"
        link.symlink_to(mx["ws"])
        cfg = config.load_config()
        cfg["workspace"] = str(link)
        config.save_config(cfg)
        assert config.workspace() == link
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    assert client.post("/api/agents", json={"topic_path": topic, "name": "writer"}).status_code == 200
    job = client.post("/api/agents/acme/blog/writer/crons", json={"schedule": "0 9 * * *", "prompt": "NOTOOL x"}).json()
    agents.post(A, "note", "hello thread")
    assert client.delete("/api/agents/acme/blog/writer").status_code == 200
    assert crons.get_job(job["id"]) is None
    it = next(i for i in _items(client) if i["kind"] == "agent")
    assert it["original"] == f"{topic}/agents/writer"                    # shown relative, not as a full path
    assert client.post(f"/api/trash/{it['id']}/restore").status_code == 200
    assert crons.get_job(job["id"]) is not None
    assert "hello thread" in [m["text"] for m in agents.thread(A)]
    assert not [p.name for p in config.state_dir("trash").iterdir() if p.name.endswith(".agents")]
