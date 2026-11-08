"""Files attached to a message of an agent (POST /api/uploads?path=<agent> then .../run) or of an agent group
(.../uploads then .../messages): only files uploaded under that folder's attachments/, never a link or a path elsewhere;
the agent's sandbox keeps attachments/ read only. Agent groups in the full-text search (kind "group")."""
from __future__ import annotations

import json
import time
from pathlib import Path

from conftest import wait_for
from maxxing import agent_guard, agents, search
from test_agent_groups import G, W, _calls, _idle, _setup

A = "projects/acme/topics/blog/agents/writer"


def _agent(client) -> None:
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": "writer", "sandbox": False})
    assert r.status_code == 200, r.text


def _upload(client, url: str, name: str = "brief.txt", data: bytes = b"the brief") -> str:
    r = client.post(url, files=[("file", (name, data, "text/plain"))])
    assert r.status_code == 200, r.text
    return r.json()["files"][0]["path"]


def test_agent_message_with_files(client, topic, mx):
    _agent(client)
    p = _upload(client, f"/api/uploads?path={A}")
    assert f"/{A}/attachments/" in p
    r = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL read it", "attachments": [p]})
    assert r.status_code == 200 and r.json()["started"], r.text
    wait_for(lambda: any(p in c["prompt"] for c in _calls()))
    run = next(m for m in client.get("/api/agents/acme/blog/writer/thread").json()["messages"] if m["kind"] == "run")
    assert run["attachments"] == [p]
    wait_for(lambda: any(m["kind"] == "result" for m in client.get("/api/agents/acme/blog/writer/thread").json()["messages"]))
    # files only: still a message
    r = client.post("/api/agents/acme/blog/writer/run", json={"attachments": [p]})
    assert r.status_code == 200 and r.json()["started"], r.text


def test_agent_refuses_files_from_elsewhere(client, topic, mx):
    _agent(client)
    ws = Path(client.get("/api/workspace/tree").json()["root"])
    other = _upload(client, "/api/uploads?path=projects/acme/topics/blog")          # the topic's, not the agent's
    secret = mx["state"] / "private.txt"
    secret.write_text("private")
    att = agents.folder(A) / "attachments"
    att.mkdir(exist_ok=True)
    (att / "link.txt").symlink_to(secret)
    (att / "dir").symlink_to(mx["state"])
    for bad in (other, str(secret), str(att / "link.txt"), str(att / "dir" / "private.txt"),
                str(att / ".." / "agent.json"), "attachments/x", str(att)):
        r = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL x", "attachments": [bad]})
        assert r.status_code == 400 and r.json()["error"] == "bad_attachment", (bad, r.text)
    r = client.post("/api/agents/acme/blog/writer/run", headers={"content-type": "application/json"},
                    content=json.dumps({"text": "NOTOOL x", "attachments": [str(att / "a\ud800")]}))
    assert r.status_code == 400 and r.json()["error"] == "bad_attachment", r.text
    many = [_upload(client, f"/api/uploads?path={A}", f"f{i}.txt") for i in range(11)]
    assert client.post("/api/agents/acme/blog/writer/run", json={"text": "x", "attachments": many}).status_code == 422
    assert ws.is_dir()


def test_uploads_never_follow_a_link(client, topic, mx, tmp_path):
    _agent(client)
    att = agents.folder(A) / "attachments"
    outside = tmp_path / "outside"
    outside.mkdir()
    att.symlink_to(outside)                       # what an agent writing its own folder could do
    r = client.post(f"/api/uploads?path={A}", files=[("file", ("x.txt", b"x", "text/plain"))])
    assert r.status_code == 400 and not any(outside.iterdir())
    att.unlink()
    att.mkdir()
    (att / time.strftime("%Y-%m")).symlink_to(outside)
    r = client.post(f"/api/uploads?path={A}", files=[("file", ("x.txt", b"x", "text/plain"))])
    assert r.status_code == 400 and not any(outside.iterdir())


def test_sandbox_keeps_attachments_read_only(client, topic, mx):
    _agent(client)
    att = agents.folder(A) / "attachments"
    locked = agent_guard.locked_paths(A)
    assert str(att) in locked and att.is_dir()
    topic_dir = agents.folder(A).parent.parent
    (topic_dir / "attachments").mkdir(exist_ok=True)
    (topic_dir / "notes").mkdir()
    a = {**agents.load(A), "sandbox": True, "writable": ["."]}
    st = agent_guard.settings(A, a)
    assert str(topic_dir / "notes") in st["sandbox"]["filesystem"]["allowWrite"]
    assert str(topic_dir / "attachments") not in st["sandbox"]["filesystem"]["allowWrite"]
    assert f"Edit(/{att}/**)" in st["permissions"]["deny"]
    assert f"Edit(/{topic_dir / 'attachments'}/**)" in st["permissions"]["deny"]
    named = agent_guard.settings(A, {**a, "writable": ["attachments", "attachments/2026-11"]})
    assert str(topic_dir / "attachments") in named["sandbox"]["filesystem"]["denyWrite"]


def test_a_link_or_a_file_in_place_of_the_folder(client, topic, mx, tmp_path):
    _agent(client)
    att = agents.folder(A) / "attachments"
    p = _upload(client, f"/api/uploads?path={A}")
    real = tmp_path / "real"
    att.rename(real)
    att.symlink_to(real)                          # the same file, through a link to the folder
    linked = str(att / Path(p).relative_to(att).as_posix())
    r = client.post("/api/agents/acme/blog/writer/run", json={"text": "x", "attachments": [linked]})
    assert r.status_code == 400 and r.json()["error"] == "bad_attachment"
    att.unlink()
    att.write_text("not a folder")
    r = client.post(f"/api/uploads?path={A}", files=[("file", ("x.txt", b"x", "text/plain"))])
    assert r.status_code == 400 and r.json()["error"] == "bad_path"


def test_group_message_with_files(client, topic, mx):
    g = _setup(client)
    p = _upload(client, f"{G}/uploads", "plan.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 32)
    assert f"/{g['path']}/attachments/" in p
    r = client.post(f"{G}/messages", json={"text": "@writer\nREPLY_AS writer: Seen", "attachments": [p]})
    assert r.status_code == 200 and r.json()["queued"] == [W], r.text
    _idle(client, 1)
    mine = next(m for m in client.get(f"{G}/messages").json()["messages"] if m["author"] == "me")
    assert mine["attachments"] == [p]
    call = [c for c in _calls() if c["cwd"].endswith("/writer")][-1]["prompt"]
    assert "Files the owner attached to it (read them): " + p in call and f"- {p}" in call   # text + attached
    # files without text: the lead (or first member) answers
    r = client.post(f"{G}/messages", json={"attachments": [p]})
    assert r.status_code == 200 and r.json()["queued"], r.text
    # refused: a file of the agent's folder, of the shared folder, nothing at all
    shared = Path(agents.folder(g["path"])) / "files" / "x.txt"
    shared.write_text("x")
    for bad in ([str(shared)], [_upload(client, f"/api/uploads?path={W}")]):
        r = client.post(f"{G}/messages", json={"text": "hi", "attachments": bad})
        assert r.status_code == 400 and r.json()["error"] == "bad_attachment"
    assert client.post(f"{G}/messages", json={"text": "  "}).status_code == 400
    assert client.post("/api/agent-groups/acme/nope/uploads", files=[("file", ("x", b"x"))]).status_code == 404


def test_group_conversations_are_searched(client, topic, mx):
    _setup(client)
    r = client.post(f"{G}/messages", json={"text": "@writer the zanzibar launch\nREPLY_AS writer: Draft about quokkas"})
    assert r.status_code == 200
    _idle(client, 1)
    hits = client.get("/api/search", params={"q": "quokkas"}).json()["results"]
    hit = next(h for h in hits if h["kind"] == "group")
    assert hit["path"] == "projects/acme/groups/team" and hit["title"] == "Team" and "@writer" in hit["snippet"]
    assert any(h["kind"] == "group" for h in client.get("/api/search", params={"q": "zanzibar"}).json()["results"])
    assert any(h["kind"] == "group" for h in client.get("/api/search", params={"q": "Team"}).json()["results"])
    # a new message is found at the next search (only the new lines are read)
    r = client.post(f"{G}/messages", json={"text": "@writer the wombat\nREPLY_AS writer: Wombats noted"})
    _idle(client, 2)
    hit = [h for h in client.get("/api/search", params={"q": "wombats"}).json()["results"] if h["kind"] == "group"]
    assert hit and hit[0]["title"] == "Team"
    assert len([h for h in client.get("/api/search", params={"q": "quokkas"}).json()["results"] if h["kind"] == "group"]) == 1
    # Agents off: no group in the results; a deleted group leaves the index
    assert client.put("/api/settings", json={"agents_page": False}).status_code == 200
    assert not [h for h in client.get("/api/search", params={"q": "quokkas"}).json()["results"] if h["kind"] == "group"]
    assert client.get("/api/search", params={"q": "quokkas", "kinds": "group"}).json()["results"] == []
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    assert client.delete(G).status_code == 200
    search.refresh(full=False)
    assert not [h for h in client.get("/api/search", params={"q": "quokkas"}).json()["results"] if h["kind"] == "group"]
