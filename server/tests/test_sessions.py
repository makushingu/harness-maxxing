from __future__ import annotations

import json
import time

import pytest

from maxxing.sessions import normalize, service, store

from conftest import all_events, wait_for, wait_idle


def calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def test_create_runs_first_turn(client, topic, mx):
    r = client.post("/api/sessions", json={"path": topic, "message": "Hello there", "model": "claude-haiku-4-5"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["state"] == "running" and s["title"] == "Hello there" and s["model"] == "claude-haiku-4-5"
    s = wait_idle(client, s["id"])
    assert s["state"] == "idle" and s["turns"] == 1 and s["error"] is None
    assert s["real_model"] == "claude-haiku-4-5" and s["cost_usd"] == pytest.approx(0.0123)
    assert s["context_tokens"] == 3 + 1200 + 300 and s["context_window"] == 1000000
    assert s["last_text"] == "Echo: Hello there" and s["unread"] is True
    evs = all_events(client, s["id"])
    types = [e["type"] for e in evs]
    assert types[0] == "user" and "init" in types and types[-1] == "result"
    tool = next(e for e in evs if e["type"] == "tool_use")
    assert tool["summary"] == "Bash: ls -la" and tool["name"] == "Bash"
    res = next(e for e in evs if e["type"] == "tool_result")
    assert res["tool_use_id"] == tool["id"] and "CLAUDE.md" in res["text"] and res["is_error"] is False
    result = evs[-1]
    assert result["ok"] and result["model"] == "claude-haiku-4-5" and result["usage"]["cache_read"] == 2400
    assert all(isinstance(e["at"], float) for e in evs)
    c = calls(mx)[-1]
    assert "--session-id" in c["argv"] and "--model" in c["argv"]
    assert c["prompt"] == "Hello there" and c["cwd"] == str(mx["ws"] / topic)
    # seen clears unread
    client.post(f"/api/sessions/{s['id']}/seen")
    assert client.get(f"/api/sessions/{s['id']}").json()["unread"] is False


def test_hide_message_appends_a_hide_event(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "oops NOTOOL"}).json()
    wait_idle(client, s["id"])
    user = next(e for e in all_events(client, s["id"]) if e["type"] == "user")
    assert client.post(f"/api/sessions/{s['id']}/hide", json={"at": user["at"]}).json() == {"ok": True}
    assert client.post(f"/api/sessions/{s['id']}/hide", json={"at": user["at"], "hidden": False}).status_code == 200
    client.post(f"/api/sessions/{s['id']}/hide", json={"at": user["at"], "hidden": False})  # already shown: no line
    hides = [e for e in all_events(client, s["id"]) if e["type"] == "hide"]
    assert [(h["ref"], h["hidden"]) for h in hides] == [(user["at"], True), (user["at"], False)]
    assert client.post("/api/sessions/nope/hide", json={"at": 1.0}).status_code == 404
    assert client.post(f"/api/sessions/{s['id']}/hide", json={"at": 1.5}).status_code == 404     # no such message
    assert client.post(f"/api/sessions/{s['id']}/hide", json={"at": "x"}).status_code == 422
    assert normalize.normalize({"type": "mx_hide", "ref": "bad"}) == []


def test_second_turn_resumes_and_list(client, topic, mx):
    s = client.post("/api/sessions", json={"path": topic, "message": "one NOTOOL"}).json()
    wait_idle(client, s["id"])
    r = client.post(f"/api/sessions/{s['id']}/messages", json={"text": "two NOTOOL"}).json()
    assert r["queued"] is False
    s2 = wait_idle(client, s["id"])
    assert s2["turns"] == 2
    argv = calls(mx)[-1]["argv"]
    assert argv[argv.index("--resume") + 1] == s["id"]
    lst = client.get("/api/sessions", params={"path": topic}).json()
    assert [x["id"] for x in lst] == [s["id"]]
    assert client.get("/api/sessions", params={"path": "projects/other"}).json() == []


def test_queue_of_two_messages(client, topic, mx):
    s = client.post("/api/sessions", json={"path": topic, "message": "first PAUSE NOTOOL"}).json()
    # PAUSE keeps the first turn running ~1.5 s: the next two messages are queued behind it
    r1 = client.post(f"/api/sessions/{s['id']}/messages", json={"text": "second NOTOOL"}).json()
    r2 = client.post(f"/api/sessions/{s['id']}/messages", json={"text": "third NOTOOL"}).json()
    assert r1["queued"] and r2["queued"] and r2["session"]["queue"] >= 1
    s = wait_idle(client, s["id"], 40)
    assert s["turns"] == 3
    users = [e["text"] for e in all_events(client, s["id"]) if e["type"] == "user"]
    assert users == ["first PAUSE NOTOOL", "second NOTOOL", "third NOTOOL"]


def test_stop_and_clear_queue(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "SLOW please"}).json()
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "queued"})
    wait_for(lambda: any(e["type"] == "init" for e in all_events(client, s["id"])), 10)
    assert client.delete(f"/api/sessions/{s['id']}/queue").json() == {"ok": True}
    assert client.get(f"/api/sessions/{s['id']}").json()["queue"] == 0
    t0 = time.time()
    assert client.post(f"/api/sessions/{s['id']}/stop").json() == {"ok": True}
    s = wait_idle(client, s["id"], 15)
    assert time.time() - t0 < 12
    assert s["state"] == "idle" and s["error"] is None
    notes = [e for e in all_events(client, s["id"]) if e["type"] == "note"]
    assert any(n["text"] == "Stopped." for n in notes)
    # the session keeps working after a stop
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "after stop NOTOOL"})
    assert wait_idle(client, s["id"])["last_text"] == "Echo: after stop NOTOOL"


def test_failed_turn_sets_error(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "please FAIL"}).json()
    s = wait_idle(client, s["id"])
    assert s["state"] == "error" and "simulated failure" in s["error"]
    evs = all_events(client, s["id"])
    assert any(e["type"] == "note" and e["level"] == "error" for e in evs)
    assert any(e["type"] == "result" and e["ok"] is False for e in evs)


def test_resume_failure_falls_back_to_new_thread(client, topic, mx):
    s = client.post("/api/sessions", json={"path": topic, "message": "start NOTOOL"}).json()
    wait_idle(client, s["id"])
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "RESUME_FAIL NOTOOL"})
    s2 = wait_idle(client, s["id"])
    assert s2["state"] == "idle" and s2["turns"] == 2
    meta = store.read(s["id"])
    assert meta["csid"] != s["id"] and meta["fresh"] is False
    evs = all_events(client, s["id"])
    assert any(e["type"] == "note" and e["level"] == "warn" and "new thread" in e["text"] for e in evs)
    assert not any(e["type"] == "result" and not e["ok"] for e in evs)   # failed attempt hidden
    argv = calls(mx)[-1]["argv"]
    assert argv[argv.index("--session-id") + 1] == meta["csid"]


def test_attachments_and_uploads(client, topic, mx):
    r = client.post("/api/uploads", params={"path": topic},
                    files=[("file", ("a b.txt", b"hello", "text/plain")), ("file", ("a b.txt", b"x", "text/plain"))])
    assert r.status_code == 200, r.text
    files = r.json()["files"]
    assert files[0]["name"] == "a b.txt" and files[1]["name"] == "a b-1.txt" and files[0]["size"] == 5
    assert f"/{topic}/attachments/" in files[0]["path"]
    s = client.post("/api/sessions", json={"path": topic, "message": "see file NOTOOL",
                                           "attachments": [files[0]["path"]]}).json()
    s = wait_idle(client, s["id"])
    assert "(1 attachment received)" in s["last_text"]
    assert f"Attached files:\n- {files[0]['path']}" in calls(mx)[-1]["prompt"]
    user = all_events(client, s["id"])[0]
    assert user["attachments"] == [files[0]["path"]]
    bad = client.post("/api/sessions", json={"path": topic, "message": "x", "attachments": ["/nope/x"]})
    assert bad.status_code == 400


def test_search_patch_delete(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "find the zebra NOTOOL"}).json()
    wait_idle(client, s["id"])
    hits = client.get("/api/sessions/search", params={"q": "ZEBRA"}).json()
    assert hits and hits[0]["id"] == s["id"] and "zebra" in hits[0]["snippet"].lower()
    assert set(hits[0]) == {"id", "title", "path", "snippet", "at"}
    assert client.get("/api/sessions/search", params={"q": "nothing-like-this"}).json() == []
    p = client.patch(f"/api/sessions/{s['id']}", json={"title": "Renamed", "archived": True, "notify": True,
                                                       "model": "claude-opus-5-5"}).json()
    assert p["title"] == "Renamed" and p["archived"] and p["notify"] and p["model"] == "claude-opus-5-5"
    assert p["favorite"] is False
    fav = client.patch(f"/api/sessions/{s['id']}", json={"favorite": True}).json()
    assert fav["favorite"] is True and fav["title"] == "Renamed"          # other fields untouched
    assert client.get(f"/api/sessions/{s['id']}").json()["favorite"] is True
    assert client.patch(f"/api/sessions/{s['id']}", json={"favorite": False}).json()["favorite"] is False
    assert client.get("/api/sessions", params={"archived": 0}).json() == []
    assert len(client.get("/api/sessions", params={"archived": 1}).json()) == 1
    tp = next(t for p in client.get("/api/workspace/tree").json()["projects"] for t in p["topics"] if t["path"] == topic)
    assert (tp["session_count"], tp["archived_count"]) == (0, 1)     # the tree's archived fold counts without the list
    assert client.delete(f"/api/sessions/{s['id']}").json() == {"ok": True}
    assert client.get(f"/api/sessions/{s['id']}").status_code == 404
    assert client.get("/api/sessions/not-a-uuid").status_code == 404


def test_compact_and_handoff(client, topic, mx):
    s = client.post("/api/sessions", json={"path": topic, "message": "work NOTOOL"}).json()
    assert client.post(f"/api/sessions/{s['id']}/compact").status_code in (400, 409)  # running or empty
    wait_idle(client, s["id"])
    assert client.post(f"/api/sessions/{s['id']}/compact").json() == {"ok": True}
    s2 = wait_idle(client, s["id"])
    assert s2["turns"] == 3                     # summary turn + seeded fresh-thread turn
    meta = store.read(s["id"])
    assert meta["csid"] != s["id"]
    last = calls(mx)[-1]
    assert "--session-id" in last["argv"] and last["prompt"].startswith("Context of this session")
    new = client.post(f"/api/sessions/{s['id']}/handoff").json()
    assert new["title"].endswith("(cont.)") and new["id"] != s["id"]
    wait_for(lambda: client.get(f"/api/sessions/{s['id']}").json()["archived"], 20)
    n = wait_for(lambda: (lambda x: x if x["turns"] == 1 and x["state"] == "idle" else None)(
        client.get(f"/api/sessions/{new['id']}").json()), 20)
    assert n["path"] == topic
    users = [e for e in all_events(client, new["id"]) if e["type"] == "user"]
    assert users[0]["text"].startswith("Context carried over") and users[0]["source"] == "system"


def test_sse_stream(client, topic):
    """SSE needs a real server: TestClient buffers the whole (endless) body."""
    import socket
    import threading

    import httpx
    import uvicorn

    from maxxing import security
    from maxxing.app import create_app

    s = client.post("/api/sessions", json={"path": topic, "message": "stream me NOTOOL"}).json()
    wait_idle(client, s["id"])
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="error",
                                           timeout_graceful_shutdown=2))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    try:
        wait_for(lambda: server.started, 10)
        frames: list[tuple[str, dict]] = []
        cookies = {security.COOKIE: security.make_cookie()}
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", cookies=cookies, timeout=10) as hc:
            with hc.stream("GET", f"/api/sessions/{s['id']}/stream", params={"from": 0}) as r:
                assert r.headers["content-type"].startswith("text/event-stream")
                event = None
                for line in r.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        frames.append((event, json.loads(line[6:])))
                        if len(frames) == 2:
                            assert [f[0] for f in frames] == ["events", "state"]
                            # a meta change (and only that) brings a new state frame
                            client.patch(f"/api/sessions/{s['id']}", json={"title": "Renamed"})
                        elif len(frames) > 2:
                            break
    finally:
        server.should_exit = True
        th.join(10)
    ev = next(d for e, d in frames if e == "events")
    st = next(d for e, d in frames if e == "state")
    assert ev["events"][0]["type"] == "user" and ev["next"] > 0
    assert st["id"] == s["id"] and st["state"] == "idle"
    assert frames[2][0] == "state" and frames[2][1]["title"] == "Renamed"


def test_turn_end_seen_quickly_while_running(client, topic):
    """While a session runs the watcher passes every WATCH_RUNNING_S: a turn end (Telegram reply, cron result) is
    reported well under the idle 1 s pass."""
    import time as _t
    lags: list[float] = []

    async def cb(session, result):
        lags.append(_t.time() - (store.read(session["id"]) or {}).get("finished_at", _t.time()))
    service.on_turn_end(cb)
    try:
        service.create_session(topic, message="wait PAUSE NOTOOL")
        wait_for(lambda: lags, 15)
        assert lags[0] < 0.75, lags
    finally:
        service._turn_cbs.clear()


def test_turn_latency_recorded_for_stats(client, topic):
    from maxxing import stats
    s = client.post("/api/sessions", json={"path": topic, "message": "lat NOTOOL"}).json()
    wait_idle(client, s["id"])
    lat = store.read(s["id"])["latency"]
    assert len(lat) == 1 and 0 <= lat[0][0] <= lat[0][1] < 30
    r = stats.compute()["latency"]
    assert r["turns"] >= 1 and r["start_s"] is not None and r["first_answer_s"] >= r["start_s"]


def test_turn_end_callback_and_wait_turn(client, topic):
    got: list = []

    async def cb(session, result):
        got.append((session["id"], result))
    service.on_turn_end(cb)
    try:
        s = service.create_session(topic, message="cb NOTOOL", source="cron", cron=True,
                                   env={"MX_TEST_VAR": "42"}, timeout_s=60)
        done = service.wait_turn(s["id"], 20)
        assert done["state"] == "idle" and done["archived"] is True     # cron success folds away
        wait_for(lambda: got, 10)
        sid, result = got[0]
        assert sid == s["id"] and result["ok"] and result["type"] == "result"
        assert service.last_assistant_text(s["id"]) == "Echo: cb NOTOOL"
    finally:
        service._turn_cbs.clear()


def test_env_and_vault_and_permission(client, topic, mx):
    from maxxing import config
    config.set_secret("vault", {"MX_TEST_VAR": {"value": "secret-1", "expose": True},
                                "HIDDEN": {"value": "x", "expose": False}})
    config.set_secret("claude_oauth_token", "tok-123456789")
    config.update_config(permission_mode="acceptEdits", default_model="claude-sonnet-5-5")
    s = client.post("/api/sessions", json={"path": topic, "message": "env NOTOOL"}).json()
    wait_idle(client, s["id"])
    c = calls(mx)[-1]
    assert c["env"]["MX_TEST_VAR"] == "secret-1" and c["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-123456789"
    assert "--permission-mode" in c["argv"] and "--dangerously-skip-permissions" not in c["argv"]
    assert c["argv"][c["argv"].index("--model") + 1] == "claude-sonnet-5-5"


def test_topic_permission_deny_rules_and_turn_env(client, topic, mx):
    """A topic's own permission mode wins over the global one; every turn gets the deny rules protecting the
    secrets, the compaction window (threshold + margin) and the quiet start."""
    from maxxing import config
    from maxxing.sessions import spawn
    project, name = topic.split("/")[1], topic.split("/")[3]
    t = client.patch(f"/api/workspace/projects/{project}/topics/{name}", json={"permission_mode": "default"}).json()
    assert t["permission_mode"] == "default"
    assert client.patch(f"/api/workspace/projects/{project}/topics/{name}",
                        json={"permission_mode": "yolo"}).status_code == 400
    s = client.post("/api/sessions", json={"path": topic, "message": "env NOTOOL"}).json()
    wait_idle(client, s["id"])
    c = calls(mx)[-1]
    argv = c["argv"]
    assert argv[argv.index("--permission-mode") + 1] == "default" and "--dangerously-skip-permissions" not in argv
    rules = json.loads(argv[argv.index("--settings") + 1])["permissions"]["deny"]
    assert f"Read(/{config.STATE}/secrets.json)" in rules and any(r.startswith("Read(//") and ".ssh/**" in r for r in rules)
    assert c["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == str(400000 + spawn.COMPACT_WINDOW_MARGIN)
    assert c["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    # back to the global mode; protection, compaction and quiet start can be turned off
    client.patch(f"/api/workspace/projects/{project}/topics/{name}", json={"permission_mode": ""})
    config.update_config(protect_secrets=False, auto_compact_tokens=0, claude_quiet_start=False)
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "again NOTOOL"})
    wait_idle(client, s["id"])
    c = calls(mx)[-1]
    assert "--dangerously-skip-permissions" in c["argv"]
    # folder settings stay out of Claude's reach even with the protection off (a topic could relax its own mode)
    rules = json.loads(c["argv"][c["argv"].index("--settings") + 1])["permissions"]["deny"]
    assert rules == [f"Edit(/{config.workspace()}/**/.maxxing.json)", f"Edit(/{config.workspace()}/infra.json)"]
    assert c["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] is None
    assert c["env"]["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] is None
    config.update_config(claude_deny=["Bash(rm -rf /*)"])
    assert spawn.deny_rules(config.load_config())[2:] == ["Bash(rm -rf /*)"]
    config.update_config(claude_deny="Bash(rm:*)")      # one rule written as a string, not split per character
    assert spawn.deny_rules(config.load_config())[2:] == ["Bash(rm:*)"]


def test_dead_runner_is_repaired(client, topic):
    s = client.post("/api/sessions", json={"path": topic}).json()
    assert s["state"] == "idle" and s["turns"] == 0
    store.update(s["id"], state="running", spawned_at=time.time() - 3600, pid=None)
    s2 = client.get(f"/api/sessions/{s['id']}").json()
    assert s2["state"] == "error" and "unexpectedly" in s2["error"]


def test_dead_runner_out_of_memory_says_so(client, topic, monkeypatch):
    """A turn unit the kernel OOM-killed is reported as such, not as a reboot or a crash."""
    from types import SimpleNamespace
    from maxxing.sessions import spawn
    s = client.post("/api/sessions", json={"path": topic}).json()
    store.update(s["id"], state="running", spawned_at=time.time() - 3600, pid=None, unit="maxxing-deadbeef")
    seen = []
    monkeypatch.setattr(spawn.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(spawn.subprocess, "run", lambda cmd, **k: seen.append(cmd) or SimpleNamespace(
        returncode=0, stdout="maxxing-deadbeef.service: Failed with result 'oom-kill'.\n", stderr=""))
    s2 = client.get(f"/api/sessions/{s['id']}").json()
    assert s2["state"] == "error" and "ran out of memory" in s2["error"]
    assert seen[0][:3] == ["journalctl", "-u", "maxxing-deadbeef"]
    assert spawn.unit_end_reason("pid:123") is None and spawn.unit_end_reason(None) is None
    # an older run of the same unit name ran out of memory, the last one did not: not reported as OOM
    monkeypatch.setattr(spawn.subprocess, "run", lambda cmd, **k: SimpleNamespace(returncode=0, stderr="", stdout=(
        "Started x.\nx: Failed with result 'oom-kill'.\nStarted x.\nx: Main process exited, code=killed\n")))
    assert spawn.unit_end_reason("maxxing-deadbeef") is None
    # OOMPolicy=continue (systemd 259): no "oom-kill" result, only this line, then a clean deactivation
    monkeypatch.setattr(spawn.subprocess, "run", lambda cmd, **k: SimpleNamespace(returncode=0, stderr="", stdout=(
        "Started x.\nx: The kernel OOM killer killed some processes in this unit.\nx: Deactivated successfully.\n")))
    assert spawn.unit_end_reason("maxxing-deadbeef") == "oom"


def test_bad_path(client):
    assert client.post("/api/sessions", json={"path": "projects/nope/topics/x"}).status_code == 400
    assert client.post("/api/sessions", json={"path": "../etc"}).status_code == 400


def test_normalize_summaries():
    s = normalize.tool_summary
    assert s("Read", {"file_path": "src/app.py"}) == "Read src/app.py"
    assert s("Edit", {"file_path": "file.py"}) == "Edit file.py"
    assert s("Grep", {"pattern": "foo"}) == "Grep 'foo'"
    assert s("WebFetch", {"url": "https://example.com"}) == "WebFetch https://example.com"
    assert s("Task", {"description": "Explore code"}) == "Task: Explore code"
    assert s("Bash", {"command": "ls -la"}) == "Bash: ls -la"
    big = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t",
                                                    "content": [{"type": "text", "text": "x" * 30000}]}]}}
    ev = normalize.normalize(big)[0]
    assert len(ev["text"]) < 20_100 and "truncated" in ev["text"]
    assert normalize.normalize({"type": "assistant", "parent_tool_use_id": "x",
                                "message": {"content": [{"type": "text", "text": "sub"}]}}) == []


def test_steer_interrupts_and_continues(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "SLOW long job"}).json()
    sid = s["id"]
    wait_for(lambda: any(e["type"] == "init" for e in all_events(client, sid)), 10)
    assert client.post(f"/api/sessions/{sid}/steer").json()["steered"] is False      # nothing queued yet
    client.post(f"/api/sessions/{sid}/messages", json={"text": "also check X NOTOOL"})
    client.post(f"/api/sessions/{sid}/messages", json={"text": "and Y NOTOOL"})
    t0 = time.time()
    r = client.post(f"/api/sessions/{sid}/steer").json()
    assert r["steered"] is True and r["session"]["queue"] == 1                        # two messages -> one
    s = wait_idle(client, sid, 20)
    assert time.time() - t0 < 15                                                      # the SLOW turn was cut short
    assert s["state"] == "idle" and s["error"] is None and s["turns"] == 2
    evs = all_events(client, sid)
    assert [e["text"] for e in evs if e["type"] == "user"] == ["SLOW long job", "also check X NOTOOL\n\nand Y NOTOOL"]
    assert any(e["type"] == "note" and e["text"].startswith("Interrupted to take your new message") for e in evs)
    assert not any(e["type"] == "note" and e["text"] == "Stopped." for e in evs)
    last = [e["text"] for e in evs if e["type"] == "assistant"][-1]                   # fake claude echoes the prompt
    assert "interrupted your previous turn" in last


def test_queue_preview_keeps_the_last_twenty():
    from maxxing.sessions import service
    q = [{"text": f"m{i}", "attachments": [], "source": "web", "kind": "user"} for i in range(30)]
    items = service.public({"id": "s1", "state": "running", "pid": 1, "queue": q})["queue_items"]
    assert [i["text"] for i in items] == [f"m{i}" for i in range(10, 30)]
    assert service.public({"id": "s1", "state": "running", "pid": 1, "queue": q})["queue"] == 30


def test_message_held_by_an_idle_summary_is_not_counted_as_waiting():
    """The message held at the head during an idle compaction is already shown as sent: not in the queue stack too."""
    from maxxing.sessions import service
    q = [{"text": "sent", "attachments": [], "source": "web", "kind": "user", "held": True},
         {"text": "next", "attachments": [], "source": "web", "kind": "user"}]
    pub = service.public({"id": "s1", "state": "running", "pid": 1, "queue": q})
    assert pub["queue"] == 1 and [i["text"] for i in pub["queue_items"]] == ["next"]


def test_held_head_while_a_turn_starts_hides_only_itself():
    """A runner restarting with the held message at the head (running, no pid yet): that head is what is being
    sent; the next message is still waiting and counted."""
    from maxxing.sessions import service
    q = [{"text": "sent", "attachments": [], "source": "web", "kind": "user", "held": True},
         {"text": "next", "attachments": [], "source": "web", "kind": "user"}]
    pub = service.public({"id": "s1", "state": "running", "pid": None, "queue": q})
    assert pub["queue"] == 1 and [i["text"] for i in pub["queue_items"]] == ["next"]


def test_take_queue_for_editing(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "SLOW long job"}).json()
    sid = s["id"]
    wait_for(lambda: any(e["type"] == "init" for e in all_events(client, sid)), 10)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "first draft"})
    client.post(f"/api/sessions/{sid}/messages", json={"text": "second"})
    # every tab (a reload, another device) sees what is waiting, not only how many
    items = client.get(f"/api/sessions/{sid}").json()["queue_items"]
    assert items == [{"text": "first draft", "attachments": 0, "source": "web", "kind": "user"},
                     {"text": "second", "attachments": 0, "source": "web", "kind": "user"}]
    r = client.post(f"/api/sessions/{sid}/queue/take").json()
    assert [m["text"] for m in r["messages"]] == ["first draft", "second"] and r["session"]["queue"] == 0
    assert r["session"]["queue_items"] == []
    assert client.post(f"/api/sessions/{sid}/queue/take").json()["messages"] == []
    client.post(f"/api/sessions/{sid}/stop")


def test_steer_twice_in_a_row(client, topic):
    s = client.post("/api/sessions", json={"path": topic, "message": "SLOW first"}).json()
    sid = s["id"]
    wait_for(lambda: any(e["type"] == "init" for e in all_events(client, sid)), 10)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "SLOW second"})
    assert client.post(f"/api/sessions/{sid}/steer").json()["interrupted"] is True
    # the steered turn is running (its own init) - steer it again
    wait_for(lambda: sum(e["type"] == "init" for e in all_events(client, sid)) >= 2 or
             [e["text"] for e in all_events(client, sid) if e["type"] == "user"][-1] == "SLOW second", 15)
    wait_for(lambda: client.get(f"/api/sessions/{sid}").json()["queue"] == 0, 15)
    time.sleep(1.0)
    client.post(f"/api/sessions/{sid}/messages", json={"text": "third NOTOOL"})
    assert client.post(f"/api/sessions/{sid}/steer").json()["steered"] is True
    s = wait_idle(client, sid, 25)
    evs = all_events(client, sid)
    assert [e["text"] for e in evs if e["type"] == "user"] == ["SLOW first", "SLOW second", "third NOTOOL"]
    assert sum(1 for e in evs if e["type"] == "note" and e["text"].startswith("Interrupted")) == 2


def test_hud_message_gets_the_hud_preface_and_inline_images(client, topic, mx):
    s = client.post("/api/sessions", json={"path": topic, "message": "first NOTOOL"}).json()
    sid = s["id"]
    wait_idle(client, sid, 20)
    up = client.post("/api/uploads", params={"path": topic},
                     files=[("file", ("screen.webp", _png(64, 32), "image/webp")),   # a PNG named .webp
                            ("file", ("notes.txt", b"hello", "text/plain"))]).json()["files"]
    paths = [f["path"] for f in up]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "what is wrong NOTOOL", "attachments": paths, "hud": True})
    wait_for(lambda: client.get(f"/api/sessions/{sid}").json()["turns"] == 2, 20)
    evs = all_events(client, sid)
    assert [e["text"] for e in evs if e["type"] == "user"][-1] == "what is wrong NOTOOL"  # the log keeps the user text
    last = [e["text"] for e in evs if e["type"] == "assistant"][-1]                       # fake claude echoes the prompt
    assert "Sent from the HUD" in last
    first, hud = calls(mx)[0], calls(mx)[-1]
    assert "--input-format" not in first["argv"] and first["images"] == 0                 # plain messages: unchanged
    assert hud["argv"][hud["argv"].index("--input-format") + 1] == "stream-json"
    assert hud["images"] == 1                                                             # the image inline, not the .txt
    assert all(p in hud["prompt"] for p in paths)                                         # paths still listed (annotations)


def _png(w: int, h: int) -> bytes:
    import struct
    import zlib
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\x00" + b"\x00" * w for _ in range(min(h, 2)))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_inline_images_are_checked(tmp_path):
    import json as _json
    from maxxing.sessions import runner
    ws, out = tmp_path / "ws", tmp_path / "elsewhere"
    ws.mkdir(), out.mkdir()
    ok, renamed, huge, notimg, outside = ws / "a.png", ws / "b.jpg", ws / "c.png", ws / "d.png", out / "e.png"
    ok.write_bytes(_png(40, 20))
    renamed.write_bytes(_png(40, 20))                     # a PNG named .jpg: sent as image/png
    huge.write_bytes(_png(9000, 10))                      # wider than the API accepts: left to Read
    notimg.write_bytes(b"not an image")
    outside.write_bytes(_png(40, 20))                     # outside the workspace: left to Read
    assert runner.image_info(_png(40, 20)) == ("image/png", 40, 20)
    item = {"hud": True, "attachments": [str(notimg), str(huge), str(outside), str(ok), str(renamed)]}
    payload, json_in = runner.stdin_payload("look", item, ws.resolve())
    assert json_in
    blocks = _json.loads(payload)["message"]["content"]
    assert [b["type"] for b in blocks] == ["text", "image", "image"]
    assert {b["source"]["media_type"] for b in blocks[1:]} == {"image/png"}
    assert runner.stdin_payload("look", {"attachments": [str(ok)]}, ws.resolve()) == ("look", False)  # not HUD
    assert runner.stdin_payload("look", {"hud": True, "attachments": [str(notimg)]}, ws.resolve()) == ("look", False)


def test_plan_mode_then_approve(client, topic, mx):
    s = client.post("/api/sessions", json={"path": topic, "message": "add a greet function NOTOOL", "plan_mode": True}).json()
    sid = s["id"]
    assert s["plan_mode"] is True and s["plan_ready"] is False
    s = wait_idle(client, sid, 20)
    assert s["plan_mode"] is True and s["plan_ready"] is True                # a plan is waiting for the user
    first = calls(mx)[-1]
    assert first["argv"][first["argv"].index("--permission-mode") + 1] == "plan"
    assert "--dangerously-skip-permissions" not in first["argv"]
    assert first["prompt"].startswith("[Plan mode is on")
    # feedback: still plan mode
    client.post(f"/api/sessions/{sid}/messages", json={"text": "also handle empty names NOTOOL"})
    wait_for(lambda: client.get(f"/api/sessions/{sid}").json()["turns"] == 2, 20)
    s = wait_idle(client, sid, 20)
    assert s["plan_ready"] is True and "plan" in calls(mx)[-1]["argv"]
    # validation: plan mode off, Claude told to implement it, the conversation shows the user's text
    r = client.post(f"/api/sessions/{sid}/plan/approve", json={"text": "Plan validé : vas-y. NOTOOL"}).json()
    assert r["session"]["plan_mode"] is False and r["session"]["plan_ready"] is False
    wait_for(lambda: client.get(f"/api/sessions/{sid}").json()["turns"] == 3, 20)
    s = wait_idle(client, sid, 20)
    assert s["plan_mode"] is False and s["plan_ready"] is False
    last = calls(mx)[-1]
    assert "plan" not in last["argv"] and "validated your plan" in last["prompt"]
    assert "Plan mode is on" not in last["prompt"]
    users = [e["text"] for e in all_events(client, sid) if e["type"] == "user"]
    assert users[-1] == "Plan validé : vas-y. NOTOOL"
    # toggled from the header
    assert client.patch(f"/api/sessions/{sid}", json={"plan_mode": True}).json()["plan_mode"] is True
    off = client.patch(f"/api/sessions/{sid}", json={"plan_mode": False}).json()
    assert off["plan_mode"] is False and off["plan_ready"] is False


def test_side_question_answers_without_touching_the_session(client, topic, mx):
    empty = client.post("/api/sessions", json={"path": topic}).json()
    r = client.post(f"/api/sessions/{empty['id']}/ask", json={"question": "what now?"})
    assert r.status_code == 409 and r.json()["error"] == "no_thread"                 # nothing to ask about yet
    s = client.post("/api/sessions", json={"path": topic, "message": "build the thing NOTOOL"}).json()
    sid = s["id"]
    s = wait_idle(client, sid, 20)
    events_before = all_events(client, sid)
    r = client.post(f"/api/sessions/{sid}/ask", json={"question": "  where are you at?  "})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["answer"].startswith("Echo: [Side question") and "duration_ms" in d and "cost_usd" in d
    call = calls(mx)[-1]
    argv = call["argv"]
    assert argv[argv.index("--resume") + 1] == sid                                        # the session's own thread
    assert "--fork-session" in argv and "--no-session-persistence" in argv                 # a throwaway copy
    assert argv[argv.index("--permission-mode") + 1] == "plan"                            # read-only
    assert call["prompt"].endswith("where are you at?")
    after = client.get(f"/api/sessions/{sid}").json()
    assert after["turns"] == s["turns"] and after["queue"] == 0                           # the session is untouched
    assert all_events(client, sid) == events_before                                       # nothing logged
    assert client.post(f"/api/sessions/{sid}/ask", json={"question": " "}).status_code == 400


@pytest.mark.parametrize("out,status", [("[1]", 502), ("123", 502),
                                        (json.dumps({"result": "hi", "total_cost_usd": "n/a", "duration_ms": "x"}), 200)])
def test_side_question_with_an_odd_answer_line(client, tmp_path, monkeypatch, out, status):
    """A last line that is not an object is a failed question (502), a cost that is not a number counts as 0."""
    from maxxing import config
    from maxxing.sessions import aside, spawn
    fake = tmp_path / "claude"
    fake.write_text(f"#!/bin/sh\ncat >/dev/null\necho '{out}'\n")
    fake.chmod(0o755)
    monkeypatch.setattr(spawn, "claude_bin", lambda: str(fake))
    try:
        r = aside._run({"id": "s", "model": ""}, "c", str(tmp_path), config.load_config(), "q")
    except service.SessionError as e:
        assert (e.status, e.code) == (status, "ask_failed")
    else:
        assert status == 200 and r["answer"] == "hi" and r["cost_usd"] == 0 and r["duration_ms"] >= 0


def test_move_session_to_another_topic(client, topic, mx):
    from pathlib import Path
    from maxxing import workspace
    from maxxing.sessions import spawn
    client.post("/api/workspace/projects/acme/topics", json={"name": "shop"})
    s = client.post("/api/sessions", json={"path": topic, "message": "hello"}).json()
    wait_idle(client, s["id"])
    csid = store.read(s["id"]).get("csid") or s["id"]
    projects = Path(spawn.base_env()["HOME"]) / ".claude" / "projects"
    old = projects / service._claude_slug(workspace.root() / topic) / f"{csid}.jsonl"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("{}\n")
    p = client.patch(f"/api/sessions/{s['id']}", json={"path": "projects/acme/topics/shop"}).json()
    assert p["path"] == "projects/acme/topics/shop"
    new = projects / service._claude_slug(workspace.root() / "projects/acme/topics/shop") / f"{csid}.jsonl"
    assert new.is_file() and not old.exists()                   # --resume still finds the conversation
    assert [x["id"] for x in client.get("/api/sessions", params={"path": "projects/acme/topics/shop"}).json()] == [s["id"]]
    assert client.patch(f"/api/sessions/{s['id']}", json={"path": "projects/acme/topics/nope"}).status_code == 400
    # the next turn runs in the new folder
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "again"})
    wait_idle(client, s["id"])
    assert client.get(f"/api/sessions/{s['id']}").json()["path"] == "projects/acme/topics/shop"
    # refused while a turn runs
    slow = client.post("/api/sessions", json={"path": topic, "message": "SLOW please"}).json()
    r = client.patch(f"/api/sessions/{slow['id']}", json={"path": "projects/acme/topics/shop"})
    assert r.status_code == 409 and r.json()["error"] == "busy"
    client.post(f"/api/sessions/{slow['id']}/stop")


def test_move_rechecks_the_session_is_idle_under_the_lock(client, topic, mx, monkeypatch):
    """A turn starts (message queued) between the idle check and the move: refused, the session stays put."""
    from maxxing import workspace
    client.post("/api/workspace/projects/acme/topics", json={"name": "shop"})
    s = client.post("/api/sessions", json={"path": topic, "message": "hello"}).json()
    wait_idle(client, s["id"])
    real = workspace.topic_dir

    def racing(p):
        d = real(p)
        store.update(s["id"], state="running", queue=[{"text": "hi", "attachments": [], "source": "web"}])
        return d
    monkeypatch.setattr(workspace, "topic_dir", racing)
    with pytest.raises(service.SessionError) as e:
        service.move_session(s["id"], "projects/acme/topics/shop")
    assert e.value.status == 409 and store.read(s["id"])["path"] == topic
    store.update(s["id"], state="idle", queue=[])


def test_auto_compact_after_a_big_context(client, topic, mx):
    from maxxing import config
    assert client.get("/api/claude/status").json()["auto_compact_tokens"] == 400000
    assert client.put("/api/claude/settings", json={"auto_compact_tokens": 100000}).json() == {"ok": True}
    s = client.post("/api/sessions", json={"path": topic, "message": "long work BIGCTX NOTOOL"}).json()
    s2 = wait_for(lambda: (lambda x: x if x["turns"] == 3 and x["state"] == "idle" else None)(
        client.get(f"/api/sessions/{s['id']}").json()), 30)
    assert s2 is not None                       # the turn, the summary turn, the seeded fresh-thread turn
    evs = all_events(client, s["id"])
    notes = [e["text"] for e in evs if e["type"] == "note"]
    assert any("150k tokens" in n for n in notes) and any(n.startswith("Context compacted") for n in notes)
    assert store.read(s["id"])["csid"] != s["id"]
    # below the threshold, or off: nothing happens
    config.update_config(auto_compact_tokens=0)
    s3 = client.post("/api/sessions", json={"path": topic, "message": "again BIGCTX NOTOOL"}).json()
    assert wait_idle(client, s3["id"])["turns"] == 1


def test_damaged_session_file_never_stops_turn_ends(client, topic):
    """A hand-edited session file (turns "x", finished_at "?") is skipped by the watcher; the other sessions'
    turn ends are still reported (C5)."""
    bad = service.create_session(topic, message="bad NOTOOL")
    service.wait_turn(bad["id"], 20)
    store.update(bad["id"], turns="x", finished_at="?", cost_usd=None)
    assert service.public(store.read(bad["id"]))["turns"] == 0
    got: list = []

    async def cb(session, result):
        got.append(session["id"])
    service.on_turn_end(cb)
    try:
        s = service.create_session(topic, message="ok NOTOOL")
        wait_for(lambda: s["id"] in got, 15)
    finally:
        service._turn_cbs.clear()


def test_turn_ends_when_a_background_program_keeps_the_output_open(client, topic, monkeypatch):
    """Claude exits but a program it started in its own session holds stdout: the turn still ends (C6)."""
    monkeypatch.setenv("MAXXING_STDOUT_GRACE_S", "1")
    t0 = time.time()
    s = client.post("/api/sessions", json={"path": topic, "message": "orphan ORPHAN NOTOOL"}).json()
    wait_idle(client, s["id"], 15)
    assert time.time() - t0 < 12
    assert service.last_assistant_text(s["id"]).startswith("Echo:")


def test_turn_ends_when_a_background_program_keeps_writing(client, topic, monkeypatch):
    """Same with a program that keeps printing (`npm run dev`): the lines never let the queue go quiet."""
    monkeypatch.setenv("MAXXING_STDOUT_GRACE_S", "1")
    t0 = time.time()
    s = client.post("/api/sessions", json={"path": topic, "message": "chatty CHATTY NOTOOL"}).json()
    wait_idle(client, s["id"], 20)
    assert time.time() - t0 < 15


def _calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def _idle_session(client, topic, text="long work BIGCTX NOTOOL", **kw) -> str:
    s = client.post("/api/sessions", json={"path": topic, "message": text, **kw}).json()
    assert wait_idle(client, s["id"])["turns"] == 1
    # back two hours later (the cache expired); the session grew over turns: its thread started at 20k (CLAUDE.md...)
    store.update(s["id"], finished_at=time.time() - 2 * 3600, base_tokens=20000)
    return s["id"]


def test_idle_compaction_runs_before_the_message_of_a_big_session(client, topic, mx):
    st = client.get("/api/claude/status").json()
    assert st["idle_compact_tokens"] == 200000 and st["idle_compact_after_s"] == 3600
    assert client.put("/api/claude/settings", json={"idle_compact_tokens": 100000}).json() == {"ok": True}
    sid = _idle_session(client, topic)                       # 150k tokens of context
    csid = store.read(sid)["csid"]
    client.post(f"/api/sessions/{sid}/messages", json={"text": "back again NOTOOL"})
    m = wait_for(lambda: (lambda x: x if x["turns"] == 3 and x["state"] == "idle" else None)(
        client.get(f"/api/sessions/{sid}").json()), 30)
    assert m is not None                         # the turn, the summary turn, the message (it carries the seed)
    notes = [e["text"] for e in all_events(client, sid) if e["type"] == "note"]
    assert any(n.startswith("Back after 2 h") and "150k tokens" in n for n in notes)
    assert any(n.startswith("Context compacted") for n in notes)
    prompts = [c["prompt"] for c in _calls(mx)]
    assert "Summarize this conversation" in prompts[-2]
    assert prompts[-1].startswith("Context of this session before compaction") and prompts[-1].endswith("back again NOTOOL")
    meta = store.read(sid)
    assert meta["csid"] != csid and not meta["fresh"] and meta["context_tokens"] < 60000
    users = [e for e in all_events(client, sid) if e["type"] == "user"]
    assert users[-1]["text"] == "back again NOTOOL"          # the seed is not displayed in the message


@pytest.mark.parametrize("case", ["recent", "small", "off", "cron", "aside"])
def test_idle_compaction_skipped(client, topic, mx, case):
    from maxxing import config
    config.update_config(idle_compact_tokens=100000)          # below the 150k of BIGCTX: only `case` skips it
    sid = _idle_session(client, topic, "short NOTOOL" if case == "small" else "long work BIGCTX NOTOOL")
    if case == "recent":
        store.update(sid, finished_at=time.time() - 600)
    elif case == "off":
        assert client.put("/api/claude/settings", json={"idle_compact_tokens": 0}).json() == {"ok": True}
        assert config.load_config()["idle_compact_tokens"] == 0
    elif case == "aside":
        store.update(sid, cache_at=time.time() - 60)           # a side question warmed the cache meanwhile
    if case == "cron":
        service.send_message(sid, "cron run NOTOOL", source="cron")
    else:
        client.post(f"/api/sessions/{sid}/messages", json={"text": "back NOTOOL"})
    m = wait_idle(client, sid)
    assert m["turns"] == 2
    assert not any("Summarize this conversation" in c["prompt"] for c in _calls(mx))


def test_stop_during_the_idle_summary_keeps_the_waiting_message(client, topic, mx, monkeypatch):
    """Stop while the idle-compaction summary runs cancels the summary only: the message behind it still runs."""
    from maxxing import config
    config.update_config(idle_compact_tokens=100000)          # below the 150k of BIGCTX
    sid = _idle_session(client, topic)
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0.5")
    client.post(f"/api/sessions/{sid}/messages", json={"text": "my important message NOTOOL"})
    wait_for(lambda: (store.read(sid) or {}).get("turn_kind") == "compact" and store.read(sid).get("pid"), 10)
    assert client.get(f"/api/sessions/{sid}").json()["queue"] == 0       # sent, not "1 waiting" on top of it
    client.post(f"/api/sessions/{sid}/stop")
    wait_for(lambda: any("my important message" in c["prompt"] for c in _calls(mx)), 20)
    wait_idle(client, sid)
    users = [e["text"] for e in all_events(client, sid) if e["type"] == "user"]
    assert users[-1] == "my important message NOTOOL"
    assert not store.read(sid).get("queue")


def test_side_question_on_a_session_deleted_meanwhile_is_not_a_500(client, topic, monkeypatch):
    """A side question whose session is deleted while Claude answers returns normally (was a KeyError -> 500)."""
    from maxxing.sessions import aside
    s = client.post("/api/sessions", json={"path": topic, "message": "hello NOTOOL"}).json()
    wait_idle(client, s["id"])
    real = aside._run

    def run_then_delete(*a, **kw):
        out = real(*a, **kw)
        service.delete_session(s["id"])
        return out
    monkeypatch.setattr(aside, "_run", run_then_delete)
    r = client.post(f"/api/sessions/{s['id']}/ask", json={"question": "what did we do?"})
    assert r.status_code in (200, 404)


def test_idle_compaction_settings_validation(client):
    from maxxing import config
    assert client.put("/api/claude/settings", json={"idle_compact_tokens": -1}).status_code == 422
    assert client.put("/api/claude/settings", json={"idle_compact_after_s": 10}).status_code == 422
    assert client.put("/api/claude/settings", json={"idle_compact_tokens": 5000, "idle_compact_after_s": 7200}).json() == {"ok": True}
    cfg = config.load_config()
    assert cfg["idle_compact_tokens"] == 5000 and cfg["idle_compact_after_s"] == 7200


def test_idle_compaction_rule():
    from maxxing.sessions.runner import _idle_compact
    cfg = {"idle_compact_tokens": 5000, "idle_compact_after_s": 3600}
    m = {"context_tokens": 25000, "finished_at": 1000.0, "fresh": False}
    user = {"kind": "user", "source": "web"}
    assert _idle_compact(m, user, cfg, 1000 + 7200) == ("2 h", 25)    # a low threshold is raised to 20k
    assert _idle_compact({**m, "context_tokens": 19000}, user, cfg, 1000 + 7200) is None
    assert _idle_compact(m, user, cfg, 1000 + 3000) is None
    assert _idle_compact(m, user, cfg, 1000 + 3700) == ("62 min", 25)
    assert _idle_compact({**m, "fresh": True}, user, cfg, 9000) is None          # no thread yet / just compacted
    assert _idle_compact({**m, "plan_ready": True}, user, cfg, 9000) is None
    for item in ({"kind": "seed", "source": "system"}, {"kind": "compact", "source": "system"},
                 {"kind": "user", "source": "web", "steer": True}, {"kind": "user", "source": "web", "plan_approved": True}):
        assert _idle_compact(m, item, cfg, 9000) is None
    assert _idle_compact(m, {"kind": "user", "source": "telegram"}, cfg, 9000) == ("2 h", 25)
    # a context that is mostly the fixed part of every thread (CLAUDE.md, memory): nothing to save
    assert _idle_compact({**m, "base_tokens": 24000}, user, cfg, 9000) is None
    assert _idle_compact({**m, "base_tokens": 12000}, user, cfg, 9000) == ("2 h", 25)


def test_queue_preview_skips_the_message_being_sent_and_cuts_long_texts():
    from maxxing.sessions import service
    long = "x" * 1000
    m = {"state": "running", "pid": None, "queue": [{"text": "starting"}, {"text": long, "attachments": ["/a", "/b"], "source": "telegram"},
                                                  "junk", {"text": "summary", "source": "system", "kind": "compact"}]}
    p = service._queue_preview(m)
    assert [q["text"][:7] for q in p] == ["x" * 7, "summary"] and len(p[0]["text"]) == service.QUEUE_PREVIEW_CHARS
    assert p[0]["attachments"] == 2 and p[0]["source"] == "telegram" and p[1]["kind"] == "compact"
    assert service._waiting(m) == 3 and service._queue_preview({"queue": "bad"}) == []


def test_turns_ask_for_foreground_agents(client, topic, mx):
    """Claude Code sends subagents to the background by default (the turn then waits for them): every turn asks
    for foreground ones, unless config `background_agents` is on."""
    from maxxing import config
    s = client.post("/api/sessions", json={"path": topic, "message": "Hi NOTOOL"}).json()
    wait_idle(client, s["id"])
    argv = calls(mx)[-1]["argv"]
    assert "run_in_background: false" in argv[argv.index("--append-system-prompt") + 1]
    config.update_config(background_agents=True)
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "Again NOTOOL"})
    wait_for(lambda: len(calls(mx)) >= 2)
    wait_idle(client, s["id"])
    assert "--append-system-prompt" not in calls(mx)[-1]["argv"]


def test_a_lone_surrogate_in_a_request_is_a_422_not_a_500(client, topic, mx):
    def send(method, url, raw):
        return client.request(method, url, content=raw, headers={"content-type": "application/json"})
    sid = client.post("/api/sessions", json={"path": topic, "title": "ok"}).json()["id"]
    cut = '"\\ud800x"'
    for method, url, raw in [("POST", "/api/sessions", f'{{"path": "{topic}", "title": {cut}}}'),
                             ("POST", "/api/sessions", f'{{"path": "{topic}", "message": {cut}}}'),
                             ("POST", f"/api/sessions/{sid}/messages", f'{{"text": {cut}}}'),
                             ("POST", f"/api/sessions/{sid}/messages", f'{{"text": "a", "attachments": [{cut}]}}'),
                             ("PATCH", f"/api/sessions/{sid}", f'{{"title": {cut}}}'),
                             ("PATCH", f"/api/sessions/{sid}", f'{{"model": {cut}}}')]:
        r = send(method, url, raw)
        assert r.status_code == 422 and r.json()["error"] == "invalid", (url, raw, r.status_code)
    assert client.get(f"/api/sessions/{sid}").json()["title"] == "ok"
    emoji = send("PATCH", f"/api/sessions/{sid}", '{"title": "\\ud83d\\ude00 ok"}')
    assert emoji.status_code == 200 and emoji.json()["title"] == "😀 ok"


def test_a_model_id_is_checked_before_it_reaches_the_command_line(client, topic, mx):
    sid = client.post("/api/sessions", json={"path": topic, "title": "ok"}).json()["id"]
    for bad in ("a\x00b", "--dangerously-skip-permissions", "opus sonnet", "x" * 101):
        r = client.patch(f"/api/sessions/{sid}", json={"model": bad})
        assert r.status_code == 400 and r.json()["error"] == "bad_model", bad
        r = client.post("/api/sessions", json={"path": topic, "model": bad})
        assert r.status_code == 400 and r.json()["error"] == "bad_model", bad
    for good in ("claude-opus-5-5[1m]", "sonnet", " opus ", ""):
        r = client.patch(f"/api/sessions/{sid}", json={"model": good})
        assert r.status_code == 200 and r.json()["model"] == good.strip()
