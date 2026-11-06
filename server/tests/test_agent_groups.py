"""Agent groups: a conversation where the owner talks to agents of one project (maxxing/agent_rooms.py,
api/agent_groups.py). The fake claude answers `REPLY_AS <agent>: <text>` (AT: becomes @)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from conftest import wait_for
from maxxing import agent_rooms, agents

G = "/api/agent-groups/acme/team"
W = "projects/acme/topics/blog/agents/writer"
R = "projects/acme/topics/seo/agents/reviewer"


def _calls() -> list[dict]:
    f = Path(os.environ["FAKE_CLAUDE_DIR"]) / "calls.jsonl"
    return [json.loads(ln) for ln in f.read_text().splitlines()] if f.exists() else []


def _setup(client, **extra) -> dict:
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    assert client.post("/api/workspace/projects/acme/topics", json={"name": "seo"}).status_code == 200
    for tp, name in (("blog", "writer"), ("seo", "reviewer")):
        r = client.post("/api/agents", json={"topic_path": f"projects/acme/topics/{tp}", "name": name,
                                             "display_name": name.capitalize(), "sandbox": False})
        assert r.status_code == 200, r.text
    body = {"project": "acme", "name": "team", "display_name": "Team", "emoji": "📝",
            "goal": "Write and review the posts.",
            "members": [{"path": W, "role": "writes"}, {"path": R, "role": "reviews"}], **extra}
    r = client.post("/api/agent-groups", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _msgs(client) -> list[dict]:
    return client.get(f"{G}/messages").json()["messages"]


def _answers(client) -> list[dict]:
    return [m for m in _msgs(client) if m["kind"] in ("message", "pass", "skip") and m["author"] != "me"]


def _idle(client, n: int) -> list[dict]:
    wait_for(lambda: len(_answers(client)) >= n and not client.get(G).json()["busy"])
    return _answers(client)


def test_create_folder_and_rules(client, topic, mx):
    g = _setup(client)
    assert g["path"] == "projects/acme/groups/team" and g["display_name"] == "Team"
    assert [m["slug"] for m in g["members"]] == ["writer", "reviewer"]
    assert g["goal"] == "Write and review the posts." and g["shared_files"] and g["trust_members"]
    d = Path(client.get("/api/workspace/tree").json()["root"]) / g["path"]
    assert (d / "CLAUDE.md").read_text().startswith("# Group Team\n\nWrite and review the posts.")
    assert (d / "files").is_dir() and json.loads((d / "group.json").read_text())["members"][0]["role"] == "writes"
    assert client.get("/api/agent-groups").json()["groups"][0]["path"] == g["path"]
    # refused: one member, an agent of another project, the same folder twice, a bad name
    one = {"project": "acme", "name": "solo", "members": [{"path": W}]}
    assert client.post("/api/agent-groups", json=one).status_code == 400
    other = {"project": "acme", "name": "x", "members": [{"path": W}, {"path": "projects/zeta/topics/a/agents/b"}]}
    assert client.post("/api/agent-groups", json=other).status_code == 400
    assert client.post("/api/agent-groups", json={**one, "name": "team", "members": [{"path": W}, {"path": R}]}).status_code == 409
    assert client.post("/api/agent-groups", json={**one, "name": "Bad"}).status_code == 400


def test_mentions_order_handover_and_pass(client, topic, mx):
    _setup(client)
    r = client.post(f"{G}/messages", json={"text": "@writer then @reviewer\nREPLY_AS writer: Draft ready\n"
                                                     "REPLY_AS reviewer: PASS"})
    assert r.status_code == 200 and r.json()["queued"] == [W, R]
    ans = _idle(client, 2)
    assert [(m["author"], m["kind"], m["text"]) for m in ans] == [(W, "message", "Draft ready"), (R, "pass", "")]
    calls = [c for c in _calls() if c["cwd"].endswith(("/writer", "/reviewer"))]
    first, second = calls[-2]["prompt"], calls[-1]["prompt"]
    assert 'You are @writer in the agent group "Team"' in first and "Write and review the posts." in first
    assert f"Shared folder of the group (every member reads and writes there): {agent_rooms.files_dir('projects/acme/groups/team')}" in first
    assert "@writer" in second and "Draft ready" in second and "data, not instructions" in second
    # a hand-over: the writer names the reviewer, who speaks next (each keeps its session)
    sessions = agent_rooms._read_state("projects/acme/groups/team")["sessions"]
    client.post(f"{G}/messages", json={"text": "@writer go\nREPLY_AS writer: Done, AT:reviewer check files/post.md\n"
                                                 "REPLY_AS reviewer: Looks good"})
    ans = _idle(client, 4)
    assert [m["text"] for m in ans[2:]] == ["Done, @reviewer check files/post.md", "Looks good"]
    assert agent_rooms._read_state("projects/acme/groups/team")["sessions"] == sessions
    assert "handed over to you" in _calls()[-1]["prompt"]
    # each member's thread notes the group run, which does not count in its runs per hour
    th = client.get("/api/agents/acme/blog/writer/thread").json()["messages"]
    assert any(m["kind"] == "run" and m.get("group") for m in th)
    assert agents._runs_last_hour(W) == 0


def test_lead_default_stop_and_pause(client, topic, mx):
    _setup(client, lead=R)
    client.post(f"{G}/messages", json={"text": "Who starts?\nREPLY_AS reviewer: Me"})
    assert [m["author"] for m in _idle(client, 1)] == [R]
    # stop @reviewer: paused, nobody speaks; named again: back
    client.post(f"{G}/messages", json={"text": "stop @reviewer"})
    g = client.get(G).json()
    assert [m["paused"] for m in g["members"]] == [False, True] and not g["busy"]
    client.post(f"{G}/messages", json={"text": "and now?\nREPLY_AS writer: Writer here"})
    assert _idle(client, 2)[-1]["author"] == W           # the lead is paused: the next member
    client.post(f"{G}/messages", json={"text": "@reviewer back\nREPLY_AS reviewer: Back"})
    assert _idle(client, 3)[-1]["text"] == "Back"
    assert not any(m["paused"] for m in client.get(G).json()["members"])


def test_limits_waves_and_replies(client, topic, mx):
    _setup(client, limits={"waves": 2})
    client.post(f"{G}/messages", json={"text": "@writer\nREPLY_AS writer: AT:reviewer\nREPLY_AS reviewer: AT:writer"})
    wait_for(lambda: any(m.get("limit") == "waves" for m in _msgs(client)) and not client.get(G).json()["busy"])
    assert [m["author"] for m in _answers(client)] == [W, R]
    client.patch(G, json={"limits": {"waves": 6, "replies": 3}})
    client.post(f"{G}/messages", json={"text": "@writer again\nREPLY_AS writer: AT:reviewer\nREPLY_AS reviewer: AT:writer"})
    wait_for(lambda: any(m.get("limit") == "replies" for m in _msgs(client)) and not client.get(G).json()["busy"])
    assert len(_answers(client)) == 5


def test_trust_members_and_shared_folder_in_the_turn(client, topic, mx):
    _setup(client, trust_members=False)
    path = "projects/acme/groups/team"
    assert agents.run_settings(R, session="x", group=path)["approvals"] is False
    st = agent_rooms._read_state(path)
    st["turns"] = {"s1": {"outside": True}}
    agent_rooms._write_state(path, st)
    rs = agents.run_settings(R, session="s1", group=path)
    assert rs["approvals"] and rs["approvals_forced"]
    agents.update(R, {"sandbox": True})
    rs = agents.run_settings(R, session="s2", group=path)
    assert str(agent_rooms.files_dir(path)) in rs["settings"]["sandbox"]["filesystem"]["allowWrite"]
    assert str(agent_rooms.files_dir(path)) not in agents.run_settings(R)["settings"]["sandbox"]["filesystem"]["allowWrite"]
    client.patch(G, json={"shared_files": False})
    assert str(agent_rooms.files_dir(path)) not in \
        agents.run_settings(R, session="s3", group=path)["settings"]["sandbox"]["filesystem"]["allowWrite"]


def test_budget_skip_reset_and_delete(client, topic, mx):
    _setup(client)
    client.patch("/api/agents/acme/seo/reviewer", json={"enabled": False})
    client.post(f"{G}/messages", json={"text": "@reviewer @writer\nREPLY_AS writer: ok"})
    ans = _idle(client, 2)
    assert ans[0]["kind"] == "skip" and ans[0]["reason"] == "disabled" and ans[1]["text"] == "ok"
    assert client.post(f"{G}/reset").status_code == 200
    assert agent_rooms._read_state("projects/acme/groups/team")["sessions"] == {}
    d = Path(client.get("/api/workspace/tree").json()["root"]) / "projects/acme/groups/team"
    (d / "files" / "post.md").write_text("draft")
    assert client.delete(f"{G}?keep_files=true").status_code == 200
    assert not d.exists() and list(d.parent.glob(".kept-team-*/post.md"))
    assert client.get(G).status_code == 404


def test_owner_only_cli(client, topic, mx, monkeypatch):
    from maxxing import agent_guard
    monkeypatch.setenv("MAXXING_AGENT", W)
    assert "not allowed in an agent turn" in (agent_guard.check_cli(["agents", "group", "say", "x", "hi"]) or "")


def test_cli(client, topic, mx, capsys):
    from maxxing import cli
    _setup(client)
    assert cli.main(["agents", "group", "list"]) == 0
    assert "projects/acme/groups/team" in capsys.readouterr().out
    assert cli.main(["agents", "group", "create", "acme/duo", "--member", "writer=writes", "--member", "reviewer",
                     "--lead", "reviewer", "--no-shared-files"]) == 0
    g = agent_rooms.get("projects/acme/groups/duo")
    assert g["lead"] == R and not g["shared_files"] and g["members"][0]["role"] == "writes"
    assert cli.main(["agents", "group", "say", "acme/duo", "hello", "REPLY_AS", "reviewer:", "hi"]) == 0
    assert "next: @reviewer" in capsys.readouterr().out
    assert cli.main(["agents", "group", "show", "nope/x"]) == 2


def test_rename_topic_and_project_follow(client, topic, mx):
    _setup(client, lead=W)
    client.post(f"{G}/messages", json={"text": "@writer hi\nREPLY_AS writer: hello"})
    _idle(client, 1)
    assert client.patch("/api/workspace/projects/acme/topics/blog", json={"name": "news"}).status_code == 200
    g = client.get(G).json()
    new_w = "projects/acme/topics/news/agents/writer"
    assert [m["path"] for m in g["members"]][0] == new_w and g["lead"] == new_w and g["members"][0]["exists"]
    assert new_w in agent_rooms._read_state("projects/acme/groups/team")["sessions"]
    r = client.patch("/api/workspace/projects/acme", json={"name": "zeta"})
    assert r.status_code == 200, r.text
    g = client.get("/api/agent-groups/zeta/team").json()
    assert g["members"][0]["path"] == "projects/zeta/topics/news/agents/writer"
    msgs = client.get("/api/agent-groups/zeta/team/messages").json()["messages"]
    assert msgs[-1]["text"] == "hello" and msgs[-1]["author"] == "projects/zeta/topics/news/agents/writer"
    assert agent_rooms._read_state("projects/zeta/groups/team")["sessions"] == {}


def test_new_topic_hides_what_came_before(client, topic, mx):
    _setup(client)
    client.post(f"{G}/messages", json={"text": "@writer secret-before\nREPLY_AS writer: one"})
    _idle(client, 1)
    client.post(f"{G}/reset")
    client.post(f"{G}/messages", json={"text": "@reviewer fresh\nREPLY_AS reviewer: two"})
    _idle(client, 2)
    p = _calls()[-1]["prompt"]
    assert "You are @reviewer" in p and "secret-before" not in p and "fresh" in p


def test_same_folder_name_in_two_topics_gets_a_handle_from_its_name(client, topic, mx):
    _setup(client)
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/seo", "name": "writer",
                                         "display_name": "Rédacteur Saints", "sandbox": False})
    assert r.status_code == 200, r.text
    r = client.post("/api/agent-groups", json={"project": "acme", "name": "duo", "members": [
        {"path": W}, {"path": "projects/acme/topics/seo/agents/writer"}]})
    assert r.status_code == 200, r.text
    assert [m["handle"] for m in r.json()["members"]] == ["writer", "redacteur-saints"]   # "Writer", "Rédacteur Saints"
    q = client.post("/api/agent-groups/acme/duo/messages", json={"text": "@redacteur-saints hi"}).json()
    assert q["queued"] == ["projects/acme/topics/seo/agents/writer"]


def test_cli_update(client, topic, mx, capsys):
    from maxxing import cli
    _setup(client)
    assert cli.main(["agents", "group", "update", "acme/team", "--goal", "New goal", "--lead", "reviewer",
                     "--trust-members", "off", "--member", "reviewer=checks", "--member", "writer"]) == 0
    g = agent_rooms.get("projects/acme/groups/team")
    assert g["goal"] == "New goal" and g["lead"] == R and not g["trust_members"]
    assert [(m["handle"], m["role"]) for m in g["members"]] == [("reviewer", "checks"), ("writer", "")]


def test_a_group_folder_is_readable_by_its_members_only(client, topic):
    from maxxing import agent_guard, config
    _setup(client)
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": "outsider",
                                         "display_name": "Outsider"})
    assert r.status_code == 200, r.text
    groups = config.workspace() / "projects/acme/groups"
    (groups / ".kept-old-1700000000/files").mkdir(parents=True)
    team, kept = str(groups / "team"), str(groups / ".kept-old-1700000000")
    for member in (W, R):
        assert team not in agent_guard.private_paths(member) and kept in agent_guard.private_paths(member)
    hidden = agent_guard.private_paths("projects/acme/topics/blog/agents/outsider")
    assert team in hidden and kept in hidden


def test_deleted_member_is_dropped_on_save_and_never_picked(client, topic, mx):
    _setup(client, lead=R)
    E = "projects/acme/topics/blog/agents/editor"
    assert client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": "editor",
                                            "sandbox": False}).status_code == 200
    assert client.patch(G, json={"members": [{"path": W}, {"path": R}, {"path": E}]}).status_code == 200
    client.post(f"{G}/messages", json={"text": "@reviewer hi\nREPLY_AS reviewer: me"})
    _idle(client, 1)
    assert client.delete("/api/agents/acme/seo/reviewer").status_code == 200
    # the lead and the last speaker are gone: the next live member answers
    r = client.post(f"{G}/messages", json={"text": "hello team\nREPLY_AS writer: hi"})
    assert r.json()["queued"] == [W]
    assert _idle(client, 2)[-1]["author"] == W
    # the form sends the members it had: the deleted one is dropped (and said), not a refusal
    r = client.patch(G, json={"display_name": "Team 2", "members": [{"path": W}, {"path": R}, {"path": E}]})
    assert r.status_code == 200, r.text
    assert r.json()["dropped"] == [R] and [m["path"] for m in r.json()["members"]] == [W, E] and r.json()["lead"] == ""
    # an agent that never was a member must exist
    r = client.patch(G, json={"members": [{"path": W}, {"path": E}, {"path": "projects/acme/topics/blog/agents/nope"}]})
    assert r.status_code == 404 and r.json()["error"] == "unknown_member"


def test_room_trimmed_by_size_and_read_from_the_end(client, topic, mx, monkeypatch):
    _setup(client)
    path = "projects/acme/groups/team"
    monkeypatch.setattr(agent_rooms, "ROOM_BYTES", 20_000)
    for i in range(200):
        agent_rooms.post(path, "message", f"answer {i} " + "x" * 300, author=W)
    f = agent_rooms._state_file(path, "jsonl")
    assert f.stat().st_size <= 20_000
    msgs = agent_rooms.room(path, 1000)
    assert msgs[-1]["text"].startswith("answer 199 ") and len(msgs) < 60
    assert [m["text"][:10] for m in agent_rooms.room(path, 2)] == ["answer 198", "answer 199"]
    at = msgs[-3]["at"]
    assert [m["id"] for m in client.get(f"{G}/messages", params={"after": at}).json()["messages"]] == \
        [m["id"] for m in msgs[-2:]]
    assert agent_rooms.room(path, 5, before=msgs[-1]["at"])[-1]["id"] == msgs[-2]["id"]


def test_same_message_twice_is_posted_once(client, topic, mx):
    _setup(client)
    a = client.post(f"{G}/messages", json={"text": "@writer go\nREPLY_AS writer: done"}).json()
    b = client.post(f"{G}/messages", json={"text": "@writer go\nREPLY_AS writer: done"}).json()
    assert b["duplicate"] and b["message"]["id"] == a["message"]["id"]
    _idle(client, 1)
    assert len([m for m in _msgs(client) if m["author"] == "me"]) == 1


def test_group_events_leave_the_workspace_tree_alone(client, topic, mx, monkeypatch):
    from maxxing import bus
    _setup(client)
    sent: list = []
    monkeypatch.setattr(bus, "invalidate", lambda *t: sent.append(t))
    agent_rooms.mark_seen("projects/acme/groups/team")
    agent_rooms.post("projects/acme/groups/team", "note", "x")
    assert sent and not any("workspace" in t for t in sent)


def test_project_delete_takes_the_rooms_to_the_trash(client, topic, mx):
    _setup(client)
    path = "projects/acme/groups/team"
    client.post(f"{G}/messages", json={"text": "@writer old secret\nREPLY_AS writer: old answer"})
    _idle(client, 1)
    assert client.delete("/api/workspace/projects/acme").status_code == 200
    assert not agent_rooms._state_file(path, "jsonl").exists() and not agent_rooms._state_file(path, "json").exists()
    # the same project and group made again start clean
    assert client.post("/api/workspace/projects", json={"name": "acme"}).status_code == 200
    assert client.post("/api/workspace/projects/acme/topics", json={"name": "blog"}).status_code == 200
    _setup(client)
    assert [m["text"] for m in _msgs(client)] == ["Group created"]
    # the old project comes back next to it, with its conversation, its members following its new name
    it = next(i for i in client.get("/api/trash").json()["items"] if i["kind"] == "project")
    r = client.post(f"/api/trash/{it['id']}/restore").json()
    new = r["restored_to"]
    assert new.startswith("projects/acme-")
    pn = new.split("/")[1]
    old = client.get(f"/api/agent-groups/{pn}/team").json()
    assert [m["path"] for m in old["members"]] == [W.replace("projects/acme/", new + "/"), R.replace("projects/acme/", new + "/")]
    texts = [(m["author"], m["text"]) for m in client.get(f"/api/agent-groups/{pn}/team/messages").json()["messages"]]
    assert (W.replace("projects/acme/", new + "/"), "old answer") in texts
    assert not (Path(client.get("/api/workspace/tree").json()["root"]) / new / "groups/team/.room.jsonl").exists()


def test_a_long_room_takes_parallel_messages(client, topic, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    _setup(client)
    P = "projects/acme/groups/team"
    monkeypatch.setattr(agent_rooms, "ROOM_BYTES", 64 * 1024)
    with ThreadPoolExecutor(8) as ex:                   # one post in four rewrites the file (trim)
        list(ex.map(lambda i: agent_rooms.post(P, "note", f"{i:03} " + "x" * 10000), range(200)))
    lines = agent_rooms._state_file(P, "jsonl").read_text().splitlines()
    assert lines and all(json.loads(ln)["kind"] == "note" for ln in lines)


def test_a_turn_ending_during_the_delete_leaves_no_state_file(client, topic, monkeypatch):
    _setup(client)
    P = "projects/acme/groups/team"
    agent_rooms._write_state(P, {"current": {"path": W, "session": "s1", "at": 1, "wave": 1, "origin": "o"},
                                 "origin": "o", "turns": {"s1": {"outside": False}}})
    real = agent_rooms.load

    def load_then_delete(path):                         # the group goes while the turn's end is posted
        g = real(path)
        monkeypatch.setattr(agent_rooms, "load", real)
        agent_rooms.delete(path)
        return g
    monkeypatch.setattr(agent_rooms, "load", load_then_delete)
    agent_rooms.on_turn_end(P, W, "s1", "late", True, 0.0)
    assert not [e for e in ("json", "jsonl") if agent_rooms._state_file(P, e).exists()]


def test_a_group_made_again_does_not_get_an_old_answer(client, topic):
    _setup(client)
    P = "projects/acme/groups/team"
    agent_rooms._write_state(P, {"current": {"path": W, "session": "old", "at": 1, "wave": 1, "origin": "o"},
                                 "origin": "o", "turns": {"old": {"outside": False}}})
    assert client.delete(G).status_code == 200
    r = client.post("/api/agent-groups", json={"project": "acme", "name": "team", "members": [{"path": W}, {"path": R}]})
    assert r.status_code == 200
    agent_rooms.on_turn_end(P, W, "old", "ghost answer", True, 0.0)
    assert not [m for m in agent_rooms.room(P) if m["text"] == "ghost answer"]
