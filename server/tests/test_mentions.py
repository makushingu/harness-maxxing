"""@ mentions of the composer (mentions.py) and `maxxing sessions send` (service.relay_message)."""
from __future__ import annotations

import json

from maxxing import agent_guard, cli, mentions, team
from maxxing.sessions import runner, service, store

from conftest import all_events, wait_idle


def _calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def _session(client, topic, text: str) -> dict:
    r = client.post("/api/sessions", json={"path": topic, "message": text})
    assert r.status_code == 200, r.text
    return wait_idle(client, r.json()["id"])


def test_the_list_offers_the_other_sessions_the_agents_and_team(client, topic, monkeypatch):
    a = _session(client, topic, "Blog writer")
    b = _session(client, topic, "Shop")
    rows = client.get(f"/api/sessions/{a['id']}/mentions").json()["items"]
    assert [(r["kind"], r["ref"], r["label"], r["hint"]) for r in rows] == [("session", b["id"], "Shop", "acme / blog")]
    assert client.put("/api/settings", json={"agents_page": True, "team_page": True}).status_code == 200
    assert client.post("/api/agents", json={"topic_path": topic, "name": "writer", "display_name": "Writer"}).status_code == 200
    monkeypatch.setattr(team, "recipients", lambda: [{"kind": "dm", "name": "Lea", "id": "p1"},
                                                     {"kind": "group", "name": "Side", "id": "g_1", "chat": "g_1",
                                                      "members": ["Lea", "Tom"]}])
    rows = client.get(f"/api/sessions/{a['id']}/mentions").json()["items"]
    kinds = [(r["kind"], r["label"]) for r in rows]
    assert kinds == [("session", "Shop"), ("agent", "Writer"), ("team", "Lea"), ("team", "Side")]
    assert rows[-1]["group"] and rows[-1]["hint"] == "Lea, Tom"
    assert all(r["ref"] != f"{topic}/agents/writer" for r in rows if r["kind"] == "session")   # its chat is not a session


def test_a_mention_tells_claude_the_command_and_nothing_else(client, topic, mx, monkeypatch):
    a = _session(client, topic, "Blog writer")
    b = _session(client, topic, "Shop")
    monkeypatch.setattr(team, "recipients", lambda: [{"kind": "dm", "name": "Lea", "id": "p1"}])
    client.put("/api/settings", json={"team_page": True})
    r = client.post(f"/api/sessions/{a['id']}/messages", json={
        "text": "Summarize and send it to @Shop and @Lea",
        "mentions": [{"kind": "session", "ref": b["id"]}, {"kind": "team", "ref": "p1"},
                     {"kind": "session", "ref": a["id"]},          # itself: dropped
                     {"kind": "agent", "ref": "projects/acme/topics/blog/agents/nope"},   # unknown: dropped
                     {"kind": "shell", "ref": "rm -rf /"}]})
    assert r.status_code == 200, r.text
    wait_idle(client, a["id"])
    prompt = _calls(mx)[-1]["prompt"]
    assert prompt.startswith("Summarize and send it to @Shop and @Lea\n\n[Harness: the message above names")
    assert f"- @Shop: a Harness session in acme / blog. To write to it: `maxxing sessions send {b['id'][:8]} \"<text>\"`" in prompt
    assert "- @Lea: a person on Team. To write to it: `maxxing team send p1 \"<text>\"`" in prompt
    assert "nope" not in prompt and "rm -rf" not in prompt and prompt.count("\n- @") == 2
    shown = [e for e in all_events(client, a["id"]) if e["type"] == "user"][-1]
    assert shown["text"] == "Summarize and send it to @Shop and @Lea"        # the note is not displayed


def test_sessions_send_from_a_turn_says_who_sent_it_and_stops_ping_pong(client, topic, mx, monkeypatch, capsys):
    a = _session(client, topic, "Blog writer")
    b = _session(client, topic, "Shop opening")
    meta = store.read(a["id"])
    monkeypatch.setattr(agent_guard, "turn_meta", lambda: {**meta, "turn_hops": 0})
    assert cli.main(["sessions", "send", "shop", "The", "post", "is", "online"]) == 0     # a title's beginning
    assert capsys.readouterr().out.startswith(f"sent to {b['id'][:8]} Shop opening")
    wait_idle(client, b["id"])
    prompt = _calls(mx)[-1]["prompt"]
    assert prompt.startswith(f"[Message sent by Claude from another Harness session, \"Blog writer\" ({topic}), "
                             f"id {a['id'][:8]}.")
    assert prompt.endswith("\n\nThe post is online")
    got = [e for e in all_events(client, b["id"]) if e["type"] == "user"][-1]
    assert got["text"] == "The post is online" and got["source"] == "session"
    assert got["from"] == {"session": a["id"], "title": "Blog writer"}
    assert store.read(b["id"])["turn_hops"] == 1
    # a reply from that turn is one hop more; after MAX_HOPS sends in a row it is refused
    monkeypatch.setattr(agent_guard, "turn_meta", lambda: {**store.read(b["id"]), "turn_hops": service.MAX_HOPS})
    assert cli.main(["sessions", "send", a["id"][:8], "thanks"]) == 1
    assert "at most 3" in capsys.readouterr().err
    monkeypatch.setattr(agent_guard, "turn_meta", lambda: meta)
    assert cli.main(["sessions", "send", a["id"], "me"]) == 1 and "itself" in capsys.readouterr().err
    assert cli.main(["sessions", "send", "nothing like it", "x"]) == 1
    _session(client, topic, "Shop stock")
    assert cli.main(["sessions", "send", "shop", "x"]) == 1 and "Several sessions" in capsys.readouterr().err
    assert agent_guard.agent_turn()["depth"] == 0


def test_the_owner_shell_can_send_and_list(client, topic, capsys, monkeypatch):
    b = _session(client, topic, "Shop")
    monkeypatch.setattr(agent_guard, "turn_meta", lambda: None)
    assert cli.main(["sessions", "list"]) == 0 and b["id"][:8] in capsys.readouterr().out
    assert cli.main(["sessions", "send", "Shop", "hello", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["session"] == b["id"]
    wait_idle(client, b["id"])
    got = [e for e in all_events(client, b["id"]) if e["type"] == "user"][-1]
    assert got["source"] == "cli" and "from" not in got


def test_mentions_survive_a_merge_and_the_note_lists_each_once():
    found = mentions.resolve([{"kind": "x", "ref": "y"}])
    assert found == []
    item = service._merged([{"text": "a", "mentions": [{"kind": "team", "ref": "p1", "label": "Lea", "command": "maxxing team send p1"}]},
                            {"text": "b"}])
    assert runner.build_prompt(item).startswith("a\n\nb\n\n[Harness:") and "@Lea" in runner.build_prompt(item)
