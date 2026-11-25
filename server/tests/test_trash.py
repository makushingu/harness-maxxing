"""Trash: list, restore (topics with their sessions, files, single sessions), delete, empty, purge."""
from __future__ import annotations

import errno
import json
import os
import shutil
import time
from pathlib import Path

from maxxing import config, trash

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


def _agent(client, name="writer", **extra):
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": name, **extra})
    assert r.status_code == 200, r.text
    return f"projects/acme/topics/blog/agents/{name}"


def test_an_agent_of_a_topic_in_the_trash_waits_for_the_topic(client, topic, mx):
    _agent(client)
    assert client.delete("/api/agents/acme/blog/writer").status_code == 200
    assert client.delete("/api/workspace/projects/acme/topics/blog").status_code == 200
    by_kind = {i["kind"]: i for i in _items(client)}
    r = client.post(f"/api/trash/{by_kind['agent']['id']}/restore")
    assert r.status_code == 409 and r.json()["error"] == "topic_in_trash"
    assert not (mx["ws"] / topic).exists()
    assert client.post(f"/api/trash/{by_kind['topic']['id']}/restore").json()["restored_to"] == topic
    r = client.post(f"/api/trash/{by_kind['agent']['id']}/restore").json()
    assert r["restored_to"] == f"{topic}/agents/writer"


def test_what_a_cut_restore_left_behind_is_purged(client, mx):
    t = trash.trash_dir()
    t.mkdir(parents=True, exist_ok=True)
    old = time.time() - 40 * 86400
    left = [t / "20260101-000000-project-acme.sessions", t / "20260101-000000-project-acme.agents",
            t / "20260101-000000-notes.md.json"]
    left[0].mkdir()
    (left[0] / "x.json").write_text("{}")
    left[1].mkdir()
    left[2].write_text("{}")
    kept = t / "20260101-000000-draft.md"                    # a real item with its sidecar stays
    kept.write_text("x")
    (t / "20260101-000000-draft.md.json").write_text(json.dumps({"original": str(mx["files"] / "draft.md"),
                                                                "at": time.time()}))
    for p in left:
        os.utime(p, (old, old))
    assert trash.purge_old() == 0
    assert not any(p.exists() for p in left) and kept.exists()
    left[0].mkdir()                                          # emptying the trash takes them too
    os.utime(left[0], (old, old))
    assert client.delete("/api/trash").status_code == 200 and not any(t.iterdir())


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
    a = _agent(client, sandbox=True)                    # its settings come back with it (new agents are free)
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


def test_trash_item_id_longer_than_a_file_name_is_a_400(client, mx):
    # a name longer than 255 bytes cannot be in the trash: exists() raised "File name too long" (a 500)
    long_id = "a" * 300
    for r in (client.post(f"/api/trash/{long_id}/restore"), client.delete(f"/api/trash/{long_id}")):
        assert r.status_code == 400 and r.json()["error"] == "bad_id", r.text


def test_deleting_files_of_the_same_name_at_once_keeps_each_one_in_the_trash(mx, tmp_path):
    import threading
    from maxxing import config, workspace
    srcs = []
    for i in range(4):
        (tmp_path / f"d{i}").mkdir()
        f = tmp_path / f"d{i}" / "notes.md"
        f.write_text(f"note {i}")
        srcs.append(f)
    go = threading.Barrier(4)
    threads = [threading.Thread(target=lambda f=f: (go.wait(), workspace.move_to_trash(f))) for f in srcs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    trash_dir = config.state_dir("trash")
    kept = sorted(p.read_text() for p in trash_dir.iterdir() if not p.name.endswith(".json"))
    assert kept == [f"note {i}" for i in range(4)]
    assert all(json.loads(p.read_text())["kind"] == "file" for p in trash_dir.glob("*.json"))


def test_restoring_a_very_long_file_name_already_taken(client, topic, mx):
    f = mx["files"] / ("a" * 250 + ".md")
    f.write_text("v1")
    assert client.post("/api/files/delete", json={"path": str(f)}).status_code == 200
    it = _items(client)[0]
    f.write_text("v2")
    r = client.post(f"/api/trash/{it['id']}/restore")
    assert r.status_code == 200
    out = Path(r.json()["restored_to"])
    assert len(out.name.encode()) <= 255 and out.name.endswith(" (restored).md")


def _trash_file(mx, topic, name="a.txt"):
    from maxxing import workspace
    (mx["ws"] / topic / name).write_text("a")
    workspace.move_to_trash(mx["ws"] / topic / name)
    return next(j for j in trash.trash_dir().glob("*.json") if j.name.endswith(f"-{name}.json"))


def test_a_relative_link_whose_target_is_not_there_is_restored_and_deleted(client, topic, mx):
    from maxxing import workspace
    d = mx["ws"] / topic
    (d / "real.txt").write_text("x")
    os.symlink("real.txt", d / "lnk")
    workspace.move_to_trash(d / "lnk")
    (item,) = _items(client)
    assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200 and os.path.islink(d / "lnk")
    workspace.move_to_trash(d / "lnk")
    assert client.delete(f"/api/trash/{_items(client)[0]['id']}").status_code == 200 and _items(client) == []


def test_json_nested_too_deep_does_not_break_the_tree_or_the_trash(client, topic, mx):
    deep = "[" * 100000
    (mx["ws"] / "projects" / ".order.json").write_text(deep)
    (mx["ws"] / "projects" / topic.split("/")[1] / ".maxxing.json").write_text(deep)
    sc = _trash_file(mx, topic)
    sc.write_text(deep)
    assert client.get("/api/trash").status_code == 200
    from maxxing import workspace
    assert isinstance(workspace.project_names(), list)


def test_a_sidecar_with_a_huge_date_or_a_lone_surrogate_still_lists(client, topic, mx):
    sc = _trash_file(mx, topic)
    sc.write_text('{"at": 1' + "0" * 400 + ', "title": "x\\ud800", "original": "y\\ud800"}')
    r = client.get("/api/trash")
    assert r.status_code == 200 and len(r.json()["items"]) == 1
    assert trash.purge_old() == 0


def test_a_broken_link_without_a_sidecar_does_not_break_the_listing_or_the_purge(client, mx):
    os.symlink("nowhere", trash.trash_dir() / "20260101-000000-dang")
    assert client.get("/api/trash").status_code == 200
    assert trash.purge_old() == 0
    assert client.delete("/api/trash").status_code == 200 and not any(trash.trash_dir().iterdir())


def test_a_damaged_session_file_is_not_deleted_by_the_restore(client, topic, mx):
    d = trash.trash_dir() / "20260101-000000-session-x"
    d.mkdir()
    sid = "01234567-89ab-4def-8123-456789abcdef"
    (d / f"{sid}.json").write_text("{bad")
    (d / f"{sid}.log").write_text("log")
    (trash.trash_dir() / (d.name + ".json")).write_text(json.dumps({"original": sid, "kind": "session", "at": time.time()}))
    r = client.post(f"/api/trash/{d.name}/restore")
    assert r.status_code == 409, r.text
    assert (d / f"{sid}.log").read_text() == "log" and len(_items(client)) == 1


def test_restore_into_a_folder_that_became_a_file_answers_409(client, topic, mx):
    from maxxing import workspace
    sub = mx["ws"] / topic / "sub"
    sub.mkdir()
    (sub / "a.md").write_text("a")
    workspace.move_to_trash(sub / "a.md")
    sub.rmdir()
    sub.write_text("now a file")
    (item,) = _items(client)
    r = client.post(f"/api/trash/{item['id']}/restore")
    assert r.status_code == 409 and len(_items(client)) == 1


def test_restore_ignores_a_session_path_that_is_not_text(mx):
    t = trash.trash_dir()
    item = t / "20260101-000001-topic-x"
    item.mkdir()
    (item / "CLAUDE.md").write_text("x")
    sess = t / (item.name + ".sessions")
    sess.mkdir()
    (sess / "11111111-2222-3333-4444-555555555555.json").write_text(json.dumps({"path": 5, "state": "idle"}))
    dest = mx["ws"] / "projects" / "p" / "topics" / "x"
    (t / (item.name + ".json")).write_text(json.dumps({"original": str(dest), "at": 2e9, "kind": "topic"}))
    r = trash.restore(item.name)
    assert r["ok"] and dest.is_dir() and r["sessions"] == 1 and not sess.exists()


def test_a_loop_of_links_or_a_name_too_long_does_not_break_the_trash(client, mx):
    f = mx["files"] / "a" / "x.md"
    f.parent.mkdir()
    f.write_text("v1")
    client.post("/api/files/delete", json={"path": str(f)})
    it = _items(client)[0]
    f.parent.rmdir()
    (mx["files"] / "a").symlink_to(mx["files"] / "b")
    (mx["files"] / "b").symlink_to(mx["files"] / "a")       # a -> b -> a
    assert [i["id"] for i in client.get("/api/trash").json()["items"]] == [it["id"]]
    assert client.post(f"/api/trash/{it['id']}/restore").status_code == 409
    side = trash.trash_dir() / f"{it['id']}.json"
    data = json.loads(side.read_text())
    data["original"] = str(mx["files"] / ("n" * 300))
    side.write_text(json.dumps(data))
    assert client.post(f"/api/trash/{it['id']}/restore").status_code == 409


def test_a_session_whose_id_is_in_use_again_is_not_deleted_by_a_restore(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "zebra NOTOOL"}).json()
    wait_idle(client, s["id"])
    from maxxing.sessions import store
    meta = store.read(s["id"])
    client.delete(f"/api/sessions/{s['id']}")
    config.write_json(store.meta_path(s["id"]), meta)       # the same id exists again
    it = _items(client)[0]
    r = client.post(f"/api/trash/{it['id']}/restore")
    assert r.status_code == 409
    assert [i["id"] for i in _items(client)] == [it["id"]]  # its copy is still in the trash


def test_two_restores_of_the_same_name_keep_both_files(client, mx):
    import threading
    f = mx["files"] / "doc.txt"
    for text in ("v1", "v2"):
        f.write_text(text)
        client.post("/api/files/delete", json={"path": str(f)})
        time.sleep(1.1)                                      # two different stamps in the trash
    ids = [i["id"] for i in _items(client)]
    assert len(ids) == 2
    real, gate = trash._free, threading.Barrier(2, timeout=1)

    def slow(dest):
        out = real(dest)
        try:
            gate.wait()                                      # both threads have chosen before either moves
        except threading.BrokenBarrierError:
            pass
        return out

    trash._free = slow
    try:
        ts = [threading.Thread(target=trash.restore, args=(i,)) for i in ids]
        [t.start() for t in ts]
        [t.join() for t in ts]
    finally:
        trash._free = real
    assert sorted(p.read_text() for p in mx["files"].iterdir()) == ["v1", "v2"]


def test_a_session_is_in_the_trash_with_its_sidecar_before_anything_can_empty_it(client, topic, monkeypatch):
    s = client.post("/api/sessions", json={"path": topic, "message": "zebra NOTOOL"}).json()
    wait_idle(client, s["id"])
    emptied = []
    real = config.write_json

    def hook(path, data, *a, **k):
        if Path(path).parent == trash.trash_dir():
            emptied.append(trash.empty())                   # a concurrent "empty the trash"
        return real(path, data, *a, **k)

    client.patch(f"/api/sessions/{s['id']}", json={"title": "Zebra plan"})
    monkeypatch.setattr(config, "write_json", hook)
    client.delete(f"/api/sessions/{s['id']}")
    monkeypatch.setattr(config, "write_json", real)
    assert emptied == [0] and len(_items(client)) == 1      # nothing was there to empty yet; the session stays



def test_two_restores_of_the_same_session_end_in_a_trash_error_not_a_crash(client, topic, monkeypatch):
    import threading
    import time
    s = client.post("/api/sessions", json={"path": topic, "message": "x NOTOOL"}).json()
    wait_idle(client, s["id"])
    client.delete(f"/api/sessions/{s['id']}")
    item = _items(client)[0]["id"]
    real = trash._put_sessions
    monkeypatch.setattr(trash, "_put_sessions", lambda *a, **k: (time.sleep(0.3), real(*a, **k))[1])
    out: list = []

    def go():
        try:
            out.append(trash.restore(item))
        except Exception as e:  # noqa: BLE001
            out.append(e)
    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sum(isinstance(o, dict) for o in out) == 1
    assert all(isinstance(o, (dict, trash.TrashError)) for o in out), out


def test_a_failed_move_of_a_session_to_the_trash_leaves_it_in_the_store(client, topic, mx, monkeypatch):
    from maxxing.sessions import store
    s = client.post("/api/sessions", json={"path": topic, "message": "hello NOTOOL"}).json()
    wait_idle(client, s["id"])
    real, calls = trash.shutil.move, []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(src, dst)
    monkeypatch.setattr(trash.shutil, "move", flaky)
    with pytest.raises(OSError):
        trash.trash_session(s["id"])
    assert store.read(s["id"])["title"] and store.log_path(s["id"]).exists()
    assert not list(trash.trash_dir().glob("*session*"))


def _across_disks(monkeypatch):
    real = os.rename

    def rename(src, dst, *a, **k):
        if Path(src).parent == trash.trash_dir():
            raise OSError(errno.EXDEV, "cross-device")
        return real(src, dst, *a, **k)
    monkeypatch.setattr(trash.os, "rename", rename)


def test_a_failed_restore_leaves_no_partial_copy(client, topic, mx, monkeypatch):
    item = _trash_file(mx, topic, "half.txt")
    _across_disks(monkeypatch)

    def half(src, dst, **k):
        Path(dst).write_text("part")                    # a copy across disks that stops half way
        raise OSError("disk full")
    monkeypatch.setattr(trash.shutil, "copy2", half)
    r = client.post(f"/api/trash/{item.stem}/restore")
    assert r.status_code == 409
    assert not list((mx["ws"] / topic).glob("*half*")) and item.exists()


def test_a_restore_across_disks_keeps_the_copy_when_the_source_cannot_be_emptied(client, topic, mx, monkeypatch):
    from maxxing import workspace
    d = mx["ws"] / topic / "box"
    d.mkdir()
    (d / "a.txt").write_text("a")
    (d / "b.txt").write_text("b")
    workspace.move_to_trash(d)
    (item,) = _items(client)
    _across_disks(monkeypatch)

    def rmtree(path, *a, **k):
        (Path(path) / "a.txt").unlink()                 # the removal stops after a.txt
        if not k.get("ignore_errors"):
            raise OSError(errno.EPERM, "not permitted")
    monkeypatch.setattr(trash.shutil, "rmtree", rmtree)
    assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200
    assert sorted(q.name for q in d.iterdir()) == ["a.txt", "b.txt"]


def test_restoring_a_project_with_a_session_title_that_cannot_be_written_does_not_crash(client, mx, topic):
    s1 = client.post("/api/sessions", json={"path": topic, "message": "hi NOTOOL"}).json()
    s2 = client.post("/api/sessions", json={"path": topic, "message": "hi NOTOOL"}).json()
    wait_idle(client, s1["id"]); wait_idle(client, s2["id"])
    assert client.delete("/api/workspace/projects/acme").status_code == 200
    item = _items(client)[0]
    folder = next(p for p in config.state_dir("trash").iterdir() if p.is_dir() and any(p.glob("*.json")))
    meta = sorted(q for q in folder.glob("*.json") if q.stem == s2["id"])[0]
    data = json.loads(meta.read_text()); data["title"] = "\ud800"
    meta.write_text(json.dumps(data))                   # json.dumps escapes it: a lone surrogate once loaded
    r = client.post(f"/api/trash/{item['id']}/restore")
    assert r.status_code == 200, r.text


def test_a_folder_named_like_a_companion_is_not_mixed_with_the_sessions_of_a_deleted_topic(client, topic, mx, monkeypatch):
    from maxxing import workspace
    monkeypatch.setattr(workspace.time, "strftime", lambda *a, **k: "20260101-000000")   # the same second
    name = topic.rsplit("/", 1)[-1]
    odd = mx["files"] / f"topic-{name}.sessions"
    odd.mkdir()
    (odd / "precious.txt").write_text("keep")
    workspace.move_to_trash(odd)
    sid = client.post("/api/sessions", json={"path": topic, "message": "NOTOOL hi"}).json()["id"]
    wait_idle(client, sid)
    workspace.delete_topic(topic.split("/")[1], name)
    assert sorted(x.name for x in trash.trash_dir().joinpath(f"20260101-000000-topic-{name}.sessions").iterdir()) == ["precious.txt"]
    for it in [i for i in _items(client) if i["name"].endswith(f"topic-{name}")]:
        assert client.post(f"/api/trash/{it['id']}/restore").status_code == 200
    kept = [i for i in _items(client) if i["name"].endswith(".sessions")]
    assert kept, "the folder must still be in the trash"
    assert (trash.trash_dir() / kept[0]["id"] / "precious.txt").read_text() == "keep"


def test_session_copies_left_by_a_topic_restore_stay_listed_and_are_not_purged(client, topic, mx):
    from maxxing import workspace
    from maxxing.sessions import store
    s = client.post("/api/sessions", json={"path": topic, "message": "zebra NOTOOL"}).json()
    wait_idle(client, s["id"])
    meta = store.read(s["id"])
    workspace.delete_topic(topic.split("/")[1], topic.rsplit("/", 1)[-1])
    config.write_json(store.meta_path(s["id"]), meta)       # that session id exists again: its copy cannot go back
    (it,) = [i for i in _items(client) if i["kind"] == "topic"]
    assert client.post(f"/api/trash/{it['id']}/restore").status_code == 200
    left = [i for i in _items(client) if i["kind"] == "session"]
    assert len(left) == 1
    old = time.time() - 31 * 86400
    for q in trash.trash_dir().iterdir():
        if q.name.endswith(".sessions"):
            os.utime(q, (old, old))
    trash.purge_old()
    assert [i["id"] for i in _items(client) if i["kind"] == "session"] == [left[0]["id"]]


def test_restoring_a_session_never_overwrites_a_log_that_is_already_there(client, topic):
    from maxxing.sessions import store
    s = client.post("/api/sessions", json={"path": topic, "message": "zebra NOTOOL"}).json()
    wait_idle(client, s["id"])
    client.delete(f"/api/sessions/{s['id']}")
    store.log_path(s["id"]).write_text("mine")              # a log of that id stands there without its meta
    it = _items(client)[0]
    assert client.post(f"/api/trash/{it['id']}/restore").status_code == 409
    assert store.log_path(s["id"]).read_text() == "mine" and [i["id"] for i in _items(client)] == [it["id"]]


def test_a_session_whose_log_cannot_move_stays_listed_after_its_topic_is_restored(client, topic, monkeypatch):
    import shutil
    from maxxing import workspace
    from maxxing.sessions import store
    s = client.post("/api/sessions", json={"path": topic, "message": "zebra NOTOOL"}).json()
    wait_idle(client, s["id"])
    workspace.delete_topic(topic.split("/")[1], topic.rsplit("/", 1)[-1])
    real = shutil.move

    def move(src, dst, *a, **k):
        if str(src).endswith(".log"):
            raise OSError("disk full")
        return real(src, dst, *a, **k)
    monkeypatch.setattr(trash.shutil, "move", move)
    (it,) = [i for i in _items(client) if i["kind"] == "topic"]
    assert client.post(f"/api/trash/{it['id']}/restore").status_code == 200
    assert not store.meta_path(s["id"]).exists()
    assert [i["kind"] for i in _items(client)] == ["session"]     # still there to restore again, not hidden


def test_a_link_standing_in_the_place_of_a_deleted_file_does_not_stop_its_restore(client, topic, mx, tmp_path):
    from maxxing import workspace
    d = mx["ws"] / topic
    (d / "a.txt").write_text("x")
    workspace.move_to_trash(d / "a.txt")
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("outside")
    os.symlink(elsewhere, d / "a.txt")
    (item,) = _items(client)
    assert client.post(f"/api/trash/{item['id']}/restore").status_code == 200
    assert elsewhere.read_text() == "outside" and (d / "a (restored).txt").read_text() == "x"


def test_a_topic_deleted_from_the_file_manager_comes_back_with_a_slug_name(client, topic, mx):
    config.save_config({**config.load_config(), "files_root": str(mx["tmp"])})    # the workspace is under the files root
    assert client.post("/api/files/delete", json={"path": str(mx["ws"] / topic)}).json() == {"ok": True}
    assert client.post("/api/workspace/projects/acme/topics", json={"name": "blog"}).status_code == 200
    (it,) = [i for i in _items(client) if i["kind"] == "topic"]
    r = client.post(f"/api/trash/{it['id']}/restore").json()
    assert r["ok"] and (mx["ws"] / "projects/acme/topics/blog-restored").is_dir()


def test_an_old_item_with_a_damaged_sidecar_is_not_purged_at_once(client, topic, mx):
    from maxxing import workspace
    f = mx["ws"] / topic / "old.txt"
    f.write_text("x")
    os.utime(f, (time.time() - 90 * 86400,) * 2)
    workspace.move_to_trash(f)
    side = next(trash.trash_dir().glob("*old.txt.json"))
    side.write_text("{not json")
    assert trash.purge_old() == 0
    assert any(trash.trash_dir().glob("*old.txt"))


def test_a_restore_across_disks_of_a_multibyte_name_keeps_the_temporary_name_short(client, topic, mx, monkeypatch):
    """The temporary copy was cut at 200 characters, not bytes: 120 accented letters made "File name too long"."""
    name = "é" * 120 + ".txt"
    (mx["ws"] / topic / name).write_text("a")
    from maxxing import workspace
    workspace.move_to_trash(mx["ws"] / topic / name)
    _across_disks(monkeypatch)
    (item,) = [i for i in client.get("/api/trash").json()["items"] if i["name"] == name]
    r = client.post(f"/api/trash/{item['id']}/restore")
    assert r.status_code == 200, r.text
    assert (mx["ws"] / topic / name).read_text() == "a"


def test_a_move_to_the_trash_that_fails_after_the_copy_leaves_no_duplicate(client, topic, mx, monkeypatch):
    from maxxing import workspace
    f = mx["ws"] / topic / "dup.txt"
    f.write_text("a")

    def copy_then_fail(src, dst):
        shutil.copy2(src, dst)
        raise OSError(errno.EIO, "cannot remove the source")
    monkeypatch.setattr(workspace.shutil, "move", copy_then_fail)
    with pytest.raises(OSError):
        workspace.move_to_trash(f)
    assert f.read_text() == "a"
    assert list(trash.trash_dir().iterdir()) == []


def test_an_edit_under_way_does_not_bring_a_trashed_session_back(mx):
    import threading
    from maxxing.sessions import store
    sid = store.create(store.new_meta("", "Ghost"))["id"]
    store.append_log(sid, {"type": "user", "text": "hi"})
    inside, go, out = threading.Event(), threading.Event(), {}

    def end_of_turn():                                  # e.g. the runner saving its end of turn
        with store.edit(sid) as m:
            inside.set()
            go.wait(5)
            m["state"] = "idle"
    t = threading.Thread(target=end_of_turn)
    t.start()
    assert inside.wait(5)
    d = threading.Thread(target=lambda: out.setdefault("dest", trash.trash_session(sid)))
    d.start()
    time.sleep(0.3)
    go.set()
    t.join(5)
    d.join(5)
    assert store.read(sid) is None and sid not in store.list_ids()
    assert sorted(p.name for p in out["dest"].iterdir()) == [f"{sid}.json", f"{sid}.log"]
    assert json.loads((out["dest"] / f"{sid}.json").read_text())["state"] == "idle"   # the edit was kept
