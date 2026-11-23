from __future__ import annotations

import json

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


def test_a_topic_rename_reads_the_session_store_twice_not_three_times(client, topic, monkeypatch):
    from maxxing.sessions import service
    calls = []
    real = service.list_sessions
    monkeypatch.setattr(service, "list_sessions", lambda *a, **k: calls.append(1) or real(*a, **k))
    r = client.patch("/api/workspace/projects/acme/topics/blog", json={"name": "news"})
    assert r.status_code == 200, r.text
    assert len(calls) == 2                      # one to check and move, one for the counters of the answer


def test_rename_keeps_the_scheduled_jobs_of_the_topic(client, topic, mx):
    from maxxing import crons
    j = crons.create_job({"name": "Digest", "kind": "claude", "topic_path": topic, "prompt": "hi"})
    other = crons.create_job({"name": "Shell", "command": "true"})
    client.patch("/api/workspace/projects/acme/topics/blog", json={"name": "news"})
    assert crons.get_job(j["id"])["topic_path"] == "projects/acme/topics/news"
    client.patch("/api/workspace/projects/acme", json={"name": "acme2"})
    assert crons.get_job(j["id"])["topic_path"] == "projects/acme2/topics/news"
    assert crons.update_job(j["id"], {"name": "Digest 2"})["name"] == "Digest 2"   # still valid: editable
    assert crons.get_job(other["id"])["topic_path"] == ""


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


def test_a_name_or_path_ending_with_a_newline_is_refused(client, mx, topic):
    assert client.post("/api/workspace/projects", json={"name": "abc\n"}).status_code == 400
    assert client.post("/api/workspace/projects/acme/topics", json={"name": "new\n"}).status_code == 400
    assert not (mx["ws"] / "projects" / "abc\n").exists()
    assert workspace._PATH_RE.match("projects/acme\n") is None  # noqa: SLF001


def test_a_description_that_is_not_utf8_is_refused_before_anything_is_created(client, mx, topic):
    bad = {"name": "psur", "description": "a\ud800b"}
    r = client.post("/api/workspace/projects", content=json.dumps(bad), headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"] == "bad_description"
    assert not (mx["ws"] / "projects/psur").exists()
    assert client.post("/api/workspace/projects", json={"name": "psur"}).status_code == 200
    r = client.post("/api/workspace/projects/acme/topics", content=json.dumps(bad),
                    headers={"content-type": "application/json"})
    assert r.status_code == 400 and not (mx["ws"] / "projects/acme/topics/psur").exists()
    r = client.patch("/api/workspace/projects/acme", content=json.dumps({"name": "acme2", "description": "\ud800"}),
                     headers={"content-type": "application/json"})
    assert r.status_code == 400 and (mx["ws"] / "projects/acme").is_dir()


def _tree_node(client, project, topic=None):
    p = next(p for p in client.get("/api/workspace/tree").json()["projects"] if p["name"] == project)
    return p if topic is None else next(t for t in p["topics"] if t["name"] == topic)


def test_a_refused_topic_rename_saves_nothing_else(client):
    client.post("/api/workspace/projects", json={"name": "acme"})
    for t in ("blog", "news"):
        client.post("/api/workspace/projects/acme/topics", json={"name": t})
    url = "/api/workspace/projects/acme/topics/blog"
    before = _tree_node(client, "acme", "blog")
    r = client.patch(url, json={"name": "Bad Name!", "permission_mode": "ask"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_name"
    assert _tree_node(client, "acme", "blog") == before
    r = client.patch(url, json={"name": "news", "permission_mode": "ask"})
    assert r.status_code == 409 and r.json()["error"] == "exists"
    assert _tree_node(client, "acme", "blog") == before
    r = client.patch(url, json={"permission_mode": "ask", "allowed_tools": ["a\nb"]})
    assert r.status_code == 400 and _tree_node(client, "acme", "blog") == before


def test_a_refused_topic_rename_of_a_busy_topic_saves_nothing_else(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "SLOW"}).json()
    client.post("/api/workspace/projects/acme/topics", json={"name": "news"})
    before = _tree_node(client, "acme", "blog")
    r = client.patch("/api/workspace/projects/acme/topics/blog", json={"name": "news", "permission_mode": "ask"})
    assert r.status_code == 409 and r.json()["error"] == "has_running_sessions"
    assert _tree_node(client, "acme", "blog") == before
    client.post(f"/api/sessions/{s['id']}/stop")


def test_a_refused_project_rename_saves_nothing_else(client, topic):
    client.post("/api/workspace/projects", json={"name": "shop"})
    before = _tree_node(client, "acme")["emoji"]
    r = client.patch("/api/workspace/projects/acme", json={"name": "Bad Name!", "emoji": "🛒"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_name"
    assert _tree_node(client, "acme")["emoji"] == before
    r = client.patch("/api/workspace/projects/acme", json={"name": "shop", "emoji": "🛒"})
    assert r.status_code == 409 and r.json()["error"] == "exists"
    assert _tree_node(client, "acme")["emoji"] == before
    s = client.post("/api/sessions", json={"path": topic, "message": "SLOW"}).json()
    r = client.patch("/api/workspace/projects/acme", json={"name": "shop2", "emoji": "🛒"})
    assert r.status_code == 409 and r.json()["error"] == "has_running_sessions"
    assert _tree_node(client, "acme")["emoji"] == before
    client.post(f"/api/sessions/{s['id']}/stop")


def test_a_lone_surrogate_emoji_is_refused(client, mx):
    """Valid JSON (`\\ud800`) that no UTF-8 file can hold: bad_emoji, not a 500 from the metadata write."""
    client.post("/api/workspace/projects", json={"name": "shop"})
    r = client.patch("/api/workspace/projects/shop", content=b'{"emoji": "\\ud800"}',
                     headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"] == "bad_emoji", r.text


def test_concurrent_writes_to_a_topics_settings_keep_every_change(client, monkeypatch):
    import threading
    import time
    client.post("/api/workspace/projects", json={"name": "acme"})
    client.post("/api/workspace/projects/acme/topics", json={"name": "blog"})
    path = "projects/acme/topics/blog"
    write = config.write_json
    monkeypatch.setattr(config, "write_json", lambda *a, **k: (time.sleep(0.002), write(*a, **k))[1])
    rules = [f"Bash(tool{i}:*)" for i in range(15)]
    jobs = [lambda r=r: workspace.add_topic_allowed_tool(path, r) for r in rules]
    jobs += [lambda i=i: workspace.set_folder_browser(path, {"enabled": True, "profile": f"p{i}"}) for i in range(15)]
    jobs += [lambda: workspace.update_topic("acme", "blog", permission_mode="ask") for _ in range(5)]
    threads = [threading.Thread(target=j) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(workspace.topic_allowed_tools(path)) == sorted(rules)
    assert workspace.folder_browser(path)["enabled"] is True
    assert workspace.topic_permission_mode(path) == "ask"


def test_an_unread_session_that_failed_is_counted_as_an_error(monkeypatch):
    """The tree's counter turns red: `errors` = the unread sessions whose last turn failed (not archived)."""
    from maxxing.sessions import service
    p = "projects/acme/topics/blog"
    rows = [{"path": p, "archived": False, "state": "error", "unread": True},
            {"path": p, "archived": False, "state": "idle", "unread": True},
            {"path": p, "archived": False, "state": "error", "unread": False},
            {"path": p, "archived": True, "state": "error", "unread": True}]
    monkeypatch.setattr(service, "list_sessions", lambda archived=None: rows)
    assert workspace._session_stats()[p] == {"sessions": 3, "archived": 1, "running": 0, "unread": 2, "errors": 1}


def test_updating_a_project_keeps_the_bytes_of_the_rest_of_claude_md(client, mx):
    client.post("/api/workspace/projects", json={"name": "acme", "description": "Shop"})
    f = mx["ws"] / "projects/acme/CLAUDE.md"
    f.write_bytes(f.read_bytes() + b"\n## Notes\ncaf\xe9 latin-1\n")
    r = client.patch("/api/workspace/projects/acme", json={"description": "New shop"})
    assert r.status_code == 200, r.text
    got = f.read_bytes()
    assert b"## Notes\ncaf\xe9 latin-1\n" in got and b"New shop" in got and b"\xef\xbf\xbd" not in got
    assert not (mx["ws"] / "projects/acme/CLAUDE.md.tmp").exists()


def test_a_description_with_a_claude_md_marker_line_is_refused(client, mx):
    for bad in ("a\n@memory.md\nb", "a\n## Notes\nb"):
        r = client.post("/api/workspace/projects", json={"name": "acme", "description": bad})
        assert r.status_code == 400 and r.json()["error"] == "bad_description"
    assert client.post("/api/workspace/projects", json={"name": "acme", "description": "a\nb ## c"}).status_code == 200
    r = client.patch("/api/workspace/projects/acme", json={"description": "x\n@memory.md\ny"})
    assert r.status_code == 400


def test_a_broken_symlink_in_the_way_is_a_409_not_a_500(client, mx):
    (mx["ws"] / "projects").mkdir(exist_ok=True)
    (mx["ws"] / "projects" / "dang").symlink_to(mx["ws"] / "nowhere")
    r = client.post("/api/workspace/projects", json={"name": "dang"})
    assert r.status_code == 409 and r.json()["error"] == "exists", r.text
    assert client.post("/api/workspace/projects", json={"name": "ok"}).status_code == 200
    (mx["ws"] / "projects" / "ok" / "topics" / "t").symlink_to(mx["ws"] / "nowhere")
    r = client.post("/api/workspace/projects/ok/topics", json={"name": "t"})
    assert r.status_code == 409 and r.json()["error"] == "exists", r.text


def test_a_huge_description_is_refused(client, mx, topic):
    r = client.post("/api/workspace/projects", json={"name": "big", "description": "x" * 100_000})
    assert r.status_code == 400 and r.json()["error"] == "bad_description"
    assert not (mx["ws"] / "projects/big").exists()
    assert client.post("/api/workspace/projects", json={"name": "big", "description": "x" * 2000}).status_code == 200


def test_parallel_edits_of_a_claude_md_do_not_share_a_temporary_file(client, mx):
    import threading
    from maxxing import workspace
    assert client.post("/api/workspace/projects", json={"name": "par"}).status_code == 200
    errors: list[BaseException] = []

    def work(n):
        try:
            for i in range(40):
                workspace.update_project("par", description=f"d{n}-{i}")
        except BaseException as e:      # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, errors[:1]
    assert "@memory.md" in (mx["ws"] / "projects/par/CLAUDE.md").read_text()


def test_claude_md_that_is_a_pipe_or_a_device_does_not_hang_or_crash_the_tree(mx):
    import os
    from maxxing import config, workspace
    ws = config.workspace()
    for name, make in (("fifo", lambda p: os.mkfifo(p)), ("zero", lambda p: p.symlink_to("/dev/zero"))):
        d = ws / "projects" / name
        d.mkdir(parents=True)
        make(d / "CLAUDE.md")
        make(d / ".maxxing.json")
        assert workspace.read_description(d) == ""
        assert workspace._folder_meta(d) == {}
    big = ws / "projects" / "big"
    big.mkdir()
    (big / "CLAUDE.md").write_text("# Big\n\n" + "x" * (workspace.SMALL_FILE_MAX * 4))
    assert len(workspace.read_description(big)) <= workspace.SMALL_FILE_MAX


def test_a_description_with_a_nul_or_control_character_is_refused(client, mx, topic):
    for bad in ("a\x00b", "a\x07b"):
        r = client.post("/api/workspace/projects", json={"name": "pnul", "description": bad})
        assert r.status_code == 400 and r.json()["error"] == "bad_description"
    assert not (mx["ws"] / "projects/pnul").exists()
    assert client.post("/api/workspace/projects", json={"name": "pnul", "description": "two\nlines\tok"}).status_code == 200
