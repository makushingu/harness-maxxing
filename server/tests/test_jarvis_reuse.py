"""Jarvis continues a recent session of the topic (jarvis.topic_sessions, `maxxing sessions list --topic`) and archives
the sessions it started once their work is closed (jarvis.close, _archivable; meta owner_at / jarvis_made)."""
from __future__ import annotations

import json
import time

import pytest

from conftest import wait_idle
from maxxing import config, jarvis
from maxxing.sessions import service, store


@pytest.fixture
def on(client):
    assert client.put("/api/settings", json={"jarvis_feature": True}).status_code == 200
    client.post("/api/jarvis/open")
    return client


def _made(client, topic: str, title: str = "Next post") -> dict:
    """A session started for Jarvis's board (what `maxxing sessions new` from its turn does)."""
    s = client.post("/api/sessions", json={"path": topic, "title": title}).json()
    store.update(s["id"], jarvis_made=True)
    jarvis.register(s["id"], topic, title, "write the post")
    return s


def test_the_owner_s_messages_are_dated_not_those_of_sessions(client, topic):
    s = client.post("/api/sessions", json={"path": topic}).json()
    service.relay_message(s["id"], "from another session", sender={"id": "x" * 36, "title": "t", "path": "p"})
    wait_idle(client, s["id"])
    assert not store.read(s["id"]).get("owner_at")
    service.send_message(s["id"], "a cron", source="cron")
    wait_idle(client, s["id"])
    assert not store.read(s["id"]).get("owner_at")
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "me"})
    assert time.time() - store.read(s["id"])["owner_at"] < 5
    t = client.post("/api/sessions", json={"path": topic}).json()
    service.send_message(t["id"], "from my phone", source="telegram")
    assert store.read(t["id"]).get("owner_at")


def test_closed_work_archives_the_session_jarvis_started(on, topic):
    s = _made(on, topic)
    item = jarvis.close(1)
    assert item["archived"] is True
    m = store.read(s["id"])
    assert m["archived"] and m["jarvis_archived"]


@pytest.mark.parametrize("case", ["owner_wrote", "not_made", "question", "setting_off", "other_open_work", "brief",
                                  "reported_elsewhere"])
def test_closed_work_keeps_the_session(on, topic, case):
    s = on.post("/api/sessions", json={"path": topic}).json()
    if case != "not_made":
        store.update(s["id"], jarvis_made=True)
    if case == "owner_wrote":
        store.update(s["id"], owner_at=time.time() - 86400)
    if case == "setting_off":
        jarvis.save_settings({"archive_done": False})
    item = jarvis.register(s["id"], topic, "t", "b", to="c" * 36 if case == "reported_elsewhere" else "",
                           kind="brief" if case == "brief" else "")
    if case == "question":
        w = jarvis._read_work()
        w["items"][0]["question"] = True
        jarvis._write_work(w)
    if case == "other_open_work":
        w = jarvis._read_work()
        w["items"].append({**w["items"][0], "id": 99})
        jarvis._write_work(w)
    assert not jarvis.close(item["id"]).get("archived")
    assert not store.read(s["id"]).get("archived")


def test_a_send_brings_back_what_jarvis_archived(on, topic):
    s = _made(on, topic)
    jarvis.close(1)
    service.relay_message(s["id"], "one more thing", sender={"id": "x" * 36, "title": "Jarvis", "path": jarvis.PATH})
    m = store.read(s["id"])
    assert not m["archived"] and not m.get("jarvis_archived")


def test_topic_sessions_says_which_one_may_be_continued(on, topic, mx):
    other = "projects/shop/topics/other"
    (mx["ws"] / other).mkdir(parents=True, exist_ok=True)
    now = time.time()
    free = _made(on, topic, "Free")
    busy = on.post("/api/sessions", json={"path": topic, "title": "Busy"}).json()
    store.update(busy["id"], owner_at=now - 60)
    old_owner = on.post("/api/sessions", json={"path": topic, "title": "Owner yesterday"}).json()
    store.update(old_owner["id"], owner_at=now - 86400)
    full = on.post("/api/sessions", json={"path": topic, "title": "Full"}).json()
    store.update(full["id"], context_tokens=290000)
    before = on.post("/api/sessions", json={"path": topic, "title": "Before the field"}).json()
    store.update(before["id"], last_turn={"at": now - 120, "source": "web"})
    stale = on.post("/api/sessions", json={"path": topic, "title": "Stale"}).json()
    store.update(stale["id"], updated=now - 31 * 86400)
    hidden = on.post("/api/sessions", json={"path": topic, "title": "Archived by the owner"}).json()
    store.update(hidden["id"], archived=True)
    done = _made(on, topic, "Done")
    jarvis.close(2)                                         # archived by Jarvis: listed, it may follow it up
    elsewhere = on.post("/api/sessions", json={"path": other, "title": "Other topic"}).json()
    rows = {r["title"]: r for r in jarvis.topic_sessions(topic, now=now)}
    assert set(rows) == {"Free", "Busy", "Owner yesterday", "Full", "Before the field", "Done"}
    assert rows["Free"]["reusable"] and rows["Free"]["started_by_jarvis"]
    assert rows["Busy"]["why_not"] == "owner_active"
    assert rows["Owner yesterday"]["reusable"] and rows["Owner yesterday"]["owner_wrote"]
    assert rows["Full"]["why_not"] == "context_full"
    assert rows["Before the field"]["why_not"] == "owner_active"
    assert rows["Done"]["archived"] and rows["Done"]["reusable"]
    assert elsewhere["id"] not in {r["id"] for r in jarvis.topic_sessions(topic, now=now)}
    assert free["id"] in {r["id"] for r in jarvis.topic_sessions(topic, now=now)}


def test_sessions_list_topic_cli(on, topic, capsys):
    from maxxing import cli
    _made(on, topic, "Next post")
    p = topic.split("/")
    assert cli.main(["sessions", "list", "--topic", f"{p[1]}/{p[3]}", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["title"] == "Next post" and rows[0]["reusable"] is True


def test_sessions_new_from_jarvis_marks_the_session(on, topic, monkeypatch, capsys):
    from maxxing import agent_guard, cli
    jsid = jarvis.current_session()
    monkeypatch.setattr(agent_guard, "turn_meta", lambda: {"id": jsid, "title": "Jarvis", "path": jarvis.PATH})
    p = topic.split("/")
    assert cli.main(["sessions", "new", f"{p[1]}/{p[3]}", "--title", "Post", "--json"]) == 0
    sid = json.loads(capsys.readouterr().out)["session"]
    assert store.read(sid)["jarvis_made"] is True
    monkeypatch.setattr(agent_guard, "turn_meta", lambda: {"id": "y" * 36, "title": "A session", "path": topic})
    assert cli.main(["sessions", "new", f"{p[1]}/{p[3]}", "--title", "Not Jarvis", "--json"]) == 0
    assert not store.read(json.loads(capsys.readouterr().out)["session"]).get("jarvis_made")


def test_sessions_new_from_jarvis_points_to_a_reusable_session_first(on, topic, monkeypatch, capsys):
    from maxxing import agent_guard, cli
    jsid = jarvis.current_session()
    monkeypatch.setattr(agent_guard, "turn_meta", lambda: {"id": jsid, "title": "Jarvis", "path": jarvis.PATH})
    old = _made(on, topic, "Next post")
    p = topic.split("/")
    before = len(service.list_sessions(path=topic))
    assert cli.main(["sessions", "new", f"{p[1]}/{p[3]}", "--title", "Post 2", "--json"]) == 3
    err = capsys.readouterr().err
    assert old["id"][:8] in err and "--fresh" in err and "sessions send" in err
    assert len(service.list_sessions(path=topic)) == before        # nothing created
    assert cli.main(["sessions", "new", f"{p[1]}/{p[3]}", "--title", "Other", "--fresh", "invoices, not posts",
                     "--json"]) == 0
    sid = json.loads(capsys.readouterr().out)["session"]
    assert [i["fresh"] for i in jarvis.work() if i["session"] == sid] == ["invoices, not posts"]
    jarvis.save_settings({"reuse": False})
    assert cli.main(["sessions", "new", f"{p[1]}/{p[3]}", "--title", "Third", "--json"]) == 0


def test_the_refusal_lists_the_closest_subject_first(on, topic, monkeypatch, capsys):
    from maxxing import agent_guard, cli
    jsid = jarvis.current_session()
    monkeypatch.setattr(agent_guard, "turn_meta", lambda: {"id": jsid, "title": "Jarvis", "path": jarvis.PATH})
    ya = _made(on, topic, "YA")
    _made(on, topic, "GW pricing")
    _made(on, topic, "Montage vidéo")
    p = topic.split("/")
    assert cli.main(["sessions", "new", f"{p[1]}/{p[3]}", "stratégie pubs", "--title", "YA : pubs adultes"]) == 3
    err = capsys.readouterr().err
    assert err.splitlines()[1].strip().startswith(ya["id"][:8])
    assert cli.main(["sessions", "new", f"{p[1]}/{p[3]}", "le montage de la video"]) == 3
    assert "Montage" in capsys.readouterr().err.splitlines()[1]


def test_the_rules_follow_the_settings(on, mx):
    rules = jarvis.folder() / "rules.md"
    assert "sessions list --topic" in rules.read_text() and "archives its session" in rules.read_text()
    jarvis.save_settings({"reuse": False, "archive_done": False})
    text = rules.read_text()
    assert "always gets a new session" in text and "leaves its session as it is" in text
    assert config.load_config()["jarvis"]["reuse"] is False
