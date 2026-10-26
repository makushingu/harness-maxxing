from __future__ import annotations

import pytest
from conftest import wait_idle

from maxxing import config, team, teampeer

ME = "http://127.0.0.1:8801"
LEA, TOM = "http://127.0.0.1:8802", "http://127.0.0.1:8803"


@pytest.fixture
def sent(mx, monkeypatch):
    """Two accepted contacts; what would go to other servers is recorded instead."""
    monkeypatch.setenv("MAXXING_TEAM_INSECURE", "1")
    config.update_config(public_url=ME, team_page=True)
    doc = teampeer._load()
    for addr, name in ((LEA, "Lea"), (TOM, "Tom")):
        doc["peers"][addr] = {"key": teampeer._b64(b"k" * 32), "status": "accepted", "name": name}
    teampeer._save(doc)
    out: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(teampeer, "send", lambda addrs, event, msg=None: out.append((list(addrs), event)))
    return out


def test_chats_messages_reactions_read(client, sent):
    st = client.get("/api/team").json()
    lea, tom = teampeer.pid(LEA), teampeer.pid(TOM)
    assert st["chats"] == [] and {lea, tom, "me"} <= set(st["people"])
    assert client.post("/api/team/chats", json={"kind": "dm", "members": ["nobody"]}).status_code == 400
    dm = client.post("/api/team/chats", json={"kind": "dm", "members": [lea]}).json()
    assert dm["id"] == team.dm_id(ME, LEA) == team.dm_id(LEA, ME)
    assert client.post("/api/team/chats", json={"kind": "dm", "members": [lea]}).json()["id"] == dm["id"]
    m = client.post(f"/api/team/chats/{dm['id']}/messages", json={"text": "  hello  "}).json()
    assert m["text"] == "hello" and m["pending"] == [lea]
    assert sent[-1] == ([LEA], {"type": "message", "chat": dm["id"], "message": {"id": m["id"], "at": m["at"], "text": "hello", "kind": "text"}})
    assert client.post(f"/api/team/chats/{dm['id']}/messages", json={"text": " "}).status_code == 400
    team.delivered(dm["id"], m["id"], lea)
    assert "pending" not in client.get(f"/api/team/chats/{dm['id']}").json()["messages"][0]
    # reactions toggle, unknown emoji refused
    url = f"/api/team/chats/{dm['id']}/messages/{m['id']}/react"
    assert client.post(url, json={"emoji": "👍"}).json()["reactions"]["👍"] == ["me"]
    assert sent[-1][1] == {"type": "react", "chat": dm["id"], "msg": m["id"], "emoji": "👍", "on": True}
    assert "👍" not in client.post(url, json={"emoji": "👍"}).json()["reactions"]
    assert client.post(url, json={"emoji": "x"}).status_code == 400
    client.post(f"/api/team/chats/{dm['id']}/read")
    assert client.get("/api/team").json()["chats"][0]["unread"] == 0
    assert client.get("/api/team/chats/c_nope").status_code == 404


def test_group_is_sent_to_every_member_with_pair_keys(client, sent):
    lea, tom = teampeer.pid(LEA), teampeer.pid(TOM)
    g = client.post("/api/team/chats", json={"kind": "group", "members": [lea, tom], "name": "Side project"}).json()
    assert g["id"].startswith("g_") and g["members"] == [lea, tom] and g["admin"] == "me"
    by = {a[0]: e for a, e in sent}
    assert set(by) == {LEA, TOM}
    assert by[LEA]["keys"].keys() == {TOM} and by[TOM]["keys"].keys() == {LEA} and by[LEA]["keys"][TOM] == by[TOM]["keys"][LEA]
    assert {m["address"] for m in by[LEA]["members"]} == {ME, LEA, TOM}


def test_polls(client, sent):
    lea = teampeer.pid(LEA)
    c = client.post("/api/team/chats", json={"kind": "dm", "members": [lea]}).json()
    assert client.post(f"/api/team/chats/{c['id']}/polls", json={"question": "Q", "options": ["one"]}).status_code == 400
    one = client.post(f"/api/team/chats/{c['id']}/polls", json={"question": "Day?", "options": ["Mon", "Tue", "Wed"]}).json()
    a, b = one["poll"]["options"][1]["id"], one["poll"]["options"][2]["id"]
    url = f"/api/team/chats/{c['id']}/messages/{one['id']}/vote"
    mine = lambda p: [("me" in o["votes"]) for o in p["options"]]   # noqa: E731
    assert mine(client.post(url, json={"option": a}).json()["poll"]) == [False, True, False]
    assert mine(client.post(url, json={"option": b}).json()["poll"]) == [False, False, True]
    assert sent[-1][1] == {"type": "vote", "chat": c["id"], "msg": one["id"], "options": [b]}
    assert not any(mine(client.post(url, json={"option": b}).json()["poll"]))
    multi = client.post(f"/api/team/chats/{c['id']}/polls", json={"question": "What?", "options": ["x", "y"], "multi": True}).json()
    url = f"/api/team/chats/{c['id']}/messages/{multi['id']}/vote"
    for o in multi["poll"]["options"]:
        p = client.post(url, json={"option": o["id"]}).json()["poll"]
    assert mine(p) == [True, True]


def test_files_and_forward_to_sessions(client, topic, sent):
    c = client.post("/api/team/chats", json={"kind": "dm", "members": [teampeer.pid(LEA)]}).json()
    up = client.post("/api/team/files", files=[("file", ("notes.txt", b"hello", "text/plain"))]).json()["files"][0]
    m = client.post(f"/api/team/chats/{c['id']}/messages", json={"files": [{"path": up["path"]}]}).json()
    assert m["files"][0]["name"] == "notes.txt" and m["files"][0]["fid"] and m["text"] == ""
    assert sent[-1][1]["message"]["files"] == [{"id": m["files"][0]["fid"], "name": "notes.txt", "size": 5, "mime": "text/plain"}]
    assert client.post(f"/api/team/chats/{c['id']}/messages", json={"files": [{"path": "/etc/passwd"}]}).status_code == 400
    url = f"/api/team/chats/{c['id']}/messages/{m['id']}/forward"
    r = client.post(url, json={"text": "Read this", "path": topic, "title": "Notes"})
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["id"]
    wait_idle(client, sid)
    r = client.post(url, json={"text": "And this", "session": sid})
    assert r.status_code == 200 and len(r.json()["message"]["sent"]) == 2
    wait_idle(client, sid)
    assert client.post(url, json={"text": "x"}).status_code == 400
    assert client.post(url, json={"text": " ", "session": sid}).status_code == 400


def test_summary_of_chosen_messages(client, sent):
    c = client.post("/api/team/chats", json={"kind": "dm", "members": [teampeer.pid(LEA)]}).json()
    ids = [client.post(f"/api/team/chats/{c['id']}/messages", json={"text": t}).json()["id"] for t in ("one", "two", "three")]
    m = client.post(f"/api/team/chats/{c['id']}/summarize", json={"ids": ids[:2]}).json()
    assert m["kind"] == "summary" and m["text"] and m["summary"]["count"] == 2
    assert sent[-1][1]["message"]["kind"] == "summary"
    assert client.post(f"/api/team/chats/{c['id']}/summarize", json={"ids": ids[:1]}).status_code == 409
    # default: since the last summary
    assert client.post(f"/api/team/chats/{c['id']}/summarize", json={}).status_code == 409


def test_team_page_setting(client):
    assert client.get("/api/settings").json()["team_page"] is False
    assert client.put("/api/settings", json={"team_page": True}).json()["team_page"] is True


def test_typing_is_a_passing_signal(client, sent, monkeypatch):
    lea = teampeer.pid(LEA)
    signals: list[tuple[str, dict]] = []
    monkeypatch.setattr(teampeer, "signal", lambda a, e: signals.append((a, e)))
    monkeypatch.setattr(team.threading, "Timer", lambda *a, **k: type("T", (), {"daemon": True, "start": lambda self: None})())
    team._typing.clear()
    team._typing_sent.clear()
    dm = client.post("/api/team/chats", json={"kind": "dm", "members": [lea]}).json()
    n = len(sent)
    for _ in range(3):                                   # several keystrokes: one signal, never queued
        assert client.post(f"/api/team/chats/{dm['id']}/typing").status_code == 200
    import time as _t
    for _ in range(50):
        if signals:
            break
        _t.sleep(0.02)
    assert signals == [(LEA, {"type": "typing", "chat": dm["id"]})] and len(sent) == n
    # Lea writes: shown in the state until her message arrives
    team.apply_remote(LEA, True, {"type": "typing", "chat": dm["id"]})
    assert client.get("/api/team").json()["typing"] == {dm["id"]: [lea]}
    team.apply_remote(LEA, True, {"type": "typing", "chat": "d_unknown"})    # not a chat of ours: ignored
    team.apply_remote(LEA, True, {"type": "message", "chat": dm["id"], "message": {"id": "m_0123abcd", "at": 1, "text": "hi", "kind": "text"}})
    assert client.get("/api/team").json()["typing"] == {}


def test_profile_change_goes_to_contacts(client, sent):
    client.put("/api/settings/profile", json={"name": "Romy", "color": "teal", "emoji": ""})
    addrs, event = sent[-1]
    assert set(addrs) == {LEA, TOM} and event == {"type": "profile", "profile": {"name": "Romy", "emoji": "", "color": "teal"}}
    st = client.get("/api/team").json()
    assert st["people"][teampeer.pid(LEA)]["last_seen"] == 0
