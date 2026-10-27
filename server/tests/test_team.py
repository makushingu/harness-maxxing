from __future__ import annotations

import secrets

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


def _wait(cond, n=50):
    import time as _t
    for _ in range(n):
        if cond():
            return True
        _t.sleep(0.02)
    return False


def test_reply_edit_delete(client, sent):
    lea = teampeer.pid(LEA)
    dm = client.post("/api/team/chats", json={"kind": "dm", "members": [lea]}).json()["id"]
    url = f"/api/team/chats/{dm}/messages"
    a = client.post(url, json={"text": "first"}).json()
    assert client.post(url, json={"text": "x", "reply_to": "m_00000000"}).status_code == 404
    b = client.post(url, json={"text": "answer", "reply_to": a["id"]}).json()
    assert sent[-1][1]["message"]["reply_to"] == a["id"]
    # edit / delete: own messages only, sent to the others
    e = client.post(f"{url}/{b['id']}/edit", json={"text": "better answer"}).json()
    assert e["text"] == "better answer" and e["edited"] and sent[-1][1] == {"type": "edit", "chat": dm, "msg": b["id"], "text": "better answer"}
    team.apply_remote(LEA, True, {"type": "message", "chat": dm, "message": {"id": "m_0123abcd", "at": 1, "text": "hers", "kind": "text", "reply_to": a["id"]}})
    hers = client.get(f"/api/team/chats/{dm}").json()["messages"]
    assert next(m for m in hers if m["id"] == "m_0123abcd")["reply_to"] == a["id"]
    assert client.post(f"{url}/m_0123abcd/edit", json={"text": "mine now"}).status_code == 403
    assert client.post(f"{url}/m_0123abcd/delete").status_code == 403
    d = client.post(f"{url}/{a['id']}/delete").json()
    assert d["deleted"] and d["text"] == "" and sent[-1][1] == {"type": "delete", "chat": dm, "msg": a["id"]}
    # the others: only the author changes a message
    team.apply_remote(LEA, True, {"type": "edit", "chat": dm, "msg": b["id"], "text": "hacked"})    # not hers: no effect
    assert next(m for m in client.get(f"/api/team/chats/{dm}").json()["messages"] if m["id"] == b["id"])["text"] == "better answer"
    team.apply_remote(LEA, True, {"type": "edit", "chat": dm, "msg": "m_0123abcd", "text": "hers, edited"})
    team.apply_remote(LEA, True, {"type": "delete", "chat": dm, "msg": "m_0123abcd"})
    m = next(m for m in client.get(f"/api/team/chats/{dm}").json()["messages"] if m["id"] == "m_0123abcd")
    assert m["deleted"] and m["text"] == ""


def test_group_add_remove_rename_leave(client, sent):
    lea, tom = teampeer.pid(LEA), teampeer.pid(TOM)
    g = client.post("/api/team/chats", json={"kind": "group", "members": [lea], "name": "Two"}).json()["id"]
    sent.clear()
    r = client.post(f"/api/team/chats/{g}/group", json={"name": "Three", "add": [tom, "nobody"]}).json()
    assert r["members"] == [lea, tom] and r["name"] == "Three"
    by = {a[0]: e for a, e in sent}
    assert by[LEA]["keys"].keys() == {TOM} and by[TOM]["keys"].keys() == {LEA} and by[LEA]["keys"][TOM] == by[TOM]["keys"][LEA]
    sent.clear()
    client.post(f"/api/team/chats/{g}/group", json={"remove": [lea]})
    by = {a[0]: e for a, e in sent}
    assert by[TOM]["keys"] == {} and by[LEA]["keys"] == {} and LEA not in {m["address"] for m in by[LEA]["members"]}
    infos = [m["info"] for m in client.get(f"/api/team/chats/{g}").json()["messages"] if m["kind"] == "info"]
    assert infos == ["joined", "removed"]
    assert client.get("/api/team").json()["chats"][0]["unread"] == 0          # info lines are never unread
    # only the creator changes a group; leaving closes it here
    other = "g_" + "ab" * 8
    team.apply_remote(TOM, True, {"type": "chat", "chat": other, "kind": "group", "name": "Tom's", "members": [{"address": TOM}, {"address": ME}], "keys": {}})
    assert client.post(f"/api/team/chats/{other}/group", json={"name": "mine"}).status_code == 403
    assert client.post(f"/api/team/chats/{other}/leave").json()["left"]
    assert sent[-1] == ([TOM], {"type": "leave", "chat": other})
    assert client.post(f"/api/team/chats/{other}/messages", json={"text": "hi"}).status_code == 409


def test_remote_group_changes(client, sent):
    lea, tom = teampeer.pid(LEA), teampeer.pid(TOM)
    g = "g_" + "cd" * 8
    roster = [{"address": LEA}, {"address": ME}, {"address": TOM}]
    team.apply_remote(LEA, True, {"type": "chat", "chat": g, "kind": "group", "name": "Lea's", "members": roster, "keys": {}})
    assert client.get(f"/api/team/chats/{g}").json()["chat"]["members"] == [lea, tom]   # Tom is a contact: kept without a key
    with pytest.raises(team.TeamError):                                                    # not the creator
        team.apply_remote(TOM, True, {"type": "chat", "chat": g, "kind": "group", "name": "x", "members": roster, "keys": {}})
    team.apply_remote(TOM, True, {"type": "leave", "chat": g})
    assert client.get(f"/api/team/chats/{g}").json()["chat"]["members"] == [lea]
    with pytest.raises(team.TeamError):                                                    # gone: nothing more from Tom
        team.apply_remote(TOM, True, {"type": "message", "chat": g, "message": {"id": "m_aaaabbbb", "at": 1, "text": "x", "kind": "text"}})
    team.apply_remote(LEA, True, {"type": "chat", "chat": g, "kind": "group", "name": "Lea's", "members": [{"address": LEA}], "keys": {}})
    c = client.get(f"/api/team/chats/{g}").json()["chat"]
    assert c["left"] and client.post(f"/api/team/chats/{g}/messages", json={"text": "hi"}).status_code == 409


def test_read_receipts_mute_presence(client, sent, monkeypatch):
    lea = teampeer.pid(LEA)
    signals: list[tuple[str, dict]] = []
    monkeypatch.setattr(teampeer, "signal", lambda a, e: signals.append((a, e)))
    team._read_sent.clear()
    dm = client.post("/api/team/chats", json={"kind": "dm", "members": [lea]}).json()["id"]
    client.post(f"/api/team/chats/{dm}/read")
    client.post(f"/api/team/chats/{dm}/read")                        # twice at once: one signal
    assert _wait(lambda: signals) and len(signals) == 1 and signals[0][1]["type"] == "read"
    team.apply_remote(LEA, True, {"type": "read", "chat": dm, "at": 10})
    team.apply_remote(LEA, True, {"type": "read", "chat": dm, "at": 5})       # never backwards
    team.apply_remote(LEA, True, {"type": "read", "chat": dm, "at": 9e12})    # never in the future
    seen = client.get(f"/api/team/chats/{dm}").json()["chat"]["seen"][lea]
    assert 10 < seen < 9e12
    assert client.post(f"/api/team/chats/{dm}/mute", json={"muted": True}).json()["muted"] is True
    assert "muted" not in client.post(f"/api/team/chats/{dm}/mute", json={"muted": False}).json()
    signals.clear()
    teampeer._presence_sent[0] = 0
    client.post("/api/team/presence")
    client.post("/api/team/presence")                                # throttled
    assert _wait(lambda: len(signals) == 2) and {a for a, _ in signals} == {LEA, TOM} and signals[0][1] == {"type": "presence"}


def test_presence_from_a_contact_only(client, sent):
    teampeer.receive(LEA, {"type": "presence"})
    assert client.get("/api/team").json()["people"][teampeer.pid(LEA)]["status"] == "online"
    doc = teampeer._load()
    doc["peers"]["http://127.0.0.1:8804"] = {"status": "group", "group_keys": {"g_" + "ef" * 8: "k"}}
    teampeer._save(doc)
    with pytest.raises(teampeer.PeerError):
        teampeer.receive("http://127.0.0.1:8804", {"type": "presence"})


def test_typing_flood_is_one_timer(client, sent, monkeypatch):
    started = []
    class T:
        def __init__(self, *a, **k):
            self.daemon = True
        def start(self):
            started.append(1)
    monkeypatch.setattr(team.threading, "Timer", T)
    team._typing.clear()
    dm = client.post("/api/team/chats", json={"kind": "dm", "members": [teampeer.pid(LEA)]}).json()["id"]
    for _ in range(100):
        team.apply_remote(LEA, True, {"type": "typing", "chat": dm})
    assert len(started) == 1


def test_hostile_events_are_harmless(client, sent):
    lea = teampeer.pid(LEA)
    dm = client.post("/api/team/chats", json={"kind": "dm", "members": [lea]}).json()["id"]
    # NaN / infinity never get saved (they would break every page)
    for at in ("nan", float("inf"), "x"):
        team.apply_remote(LEA, True, {"type": "message", "chat": dm, "message": {"id": "m_" + secrets.token_hex(4), "at": at, "text": "t", "kind": "text"}})
    team.apply_remote(LEA, True, {"type": "read", "chat": dm, "at": "nan"})
    assert client.get(f"/api/team/chats/{dm}").status_code == 200 and client.get("/api/team").status_code == 200
    # a roster of a group we are not in stores nothing
    before = len(teampeer._load()["peers"])
    fake = [{"address": f"http://127.0.0.1:{9000 + i}"} for i in range(40)]
    team.apply_remote(LEA, True, {"type": "chat", "chat": "g_" + "12" * 8, "kind": "group", "members": fake,
                                  "keys": {m["address"]: teampeer._b64(b"x" * 32) for m in fake}})
    assert len(teampeer._load()["peers"]) == before and client.get("/api/team/chats/g_" + "12" * 8).status_code == 404
    # bad keys are skipped; a peer's name is not changed by another group's roster
    g = "g_" + "34" * 8
    other = "http://127.0.0.1:8805"
    team.apply_remote(LEA, True, {"type": "chat", "chat": g, "kind": "group", "members": [{"address": LEA}, {"address": ME}, {"address": other, "name": "Zoe"}],
                                  "keys": {other: "not-a-key"}})
    assert other not in teampeer._load()["peers"]
    team.apply_remote(LEA, True, {"type": "chat", "chat": g, "kind": "group", "members": [{"address": LEA}, {"address": ME}, {"address": other, "name": "Zoe"}],
                                  "keys": {other: teampeer._b64(b"z" * 32)}})
    g2 = "g_" + "56" * 8
    team.apply_remote(TOM, True, {"type": "chat", "chat": g2, "kind": "group", "members": [{"address": TOM}, {"address": ME}, {"address": other, "name": "Fake"}],
                                  "keys": {other: teampeer._b64(b"y" * 32)}})
    assert teampeer._load()["peers"][other]["name"] == "Zoe"
    # a group left by choice: a late roster does not bring us back
    client.post(f"/api/team/chats/{g}/leave")
    team.apply_remote(LEA, True, {"type": "chat", "chat": g, "kind": "group", "members": [{"address": LEA}, {"address": ME}], "keys": {}})
    assert client.get(f"/api/team/chats/{g}").json()["chat"]["left"] == "self"
    # removed: the group's keys go
    team.apply_remote(TOM, True, {"type": "chat", "chat": g2, "kind": "group", "members": [{"address": TOM}], "keys": {}})
    assert g2 not in (teampeer._load()["peers"].get(other, {}).get("group_keys") or {})
    # a taken id or someone else's message: no error, nothing changes
    mine = client.post(f"/api/team/chats/{dm}/messages", json={"text": "mine"}).json()
    team.apply_remote(LEA, True, {"type": "message", "chat": dm, "message": {"id": mine["id"], "at": 1, "text": "spoof", "kind": "text"}})
    team.apply_remote(LEA, True, {"type": "edit", "chat": dm, "msg": mine["id"], "text": "hacked"})
    team.apply_remote(LEA, True, {"type": "delete", "chat": dm, "msg": mine["id"]})
    m = next(x for x in client.get(f"/api/team/chats/{dm}").json()["messages"] if x["id"] == mine["id"])
    assert m["text"] == "mine" and m["author"] == "me" and not m.get("deleted")


def test_malformed_event_is_a_400(client, sent, monkeypatch):
    from maxxing.api import teampeer as api_peer
    monkeypatch.setattr(teampeer, "verify", lambda *a, **k: (LEA, ""))
    dm = client.post("/api/team/chats", json={"kind": "dm", "members": [teampeer.pid(LEA)]}).json()["id"]
    r = client.post("/api/team-peer/inbox", json={"type": "vote", "chat": dm, "msg": "m_00000000", "options": 5})
    assert r.status_code in (400, 404)
    r = client.post("/api/team-peer/inbox", json={"type": "message", "chat": dm, "message": {"id": "m_11112222", "text": "x", "kind": "poll", "poll": {"options": 3}}})
    assert r.status_code == 400
    assert api_peer.log.name == "maxxing.teampeer"


def test_a_damaged_team_file_is_kept_aside(client, sent):
    team._path().parent.mkdir(parents=True, exist_ok=True)
    team._path().write_text('{"chats": [ broken')
    assert client.post("/api/team/chats", json={"kind": "dm", "members": [teampeer.pid(LEA)]}).status_code == 200
    kept = list(team._path().parent.glob("team.json.damaged-*"))
    assert len(kept) == 1 and kept[0].read_text() == '{"chats": [ broken'
    assert len(team.state()["chats"]) == 1


def test_a_file_path_with_a_nul_byte_is_a_400(client, sent):
    c = client.post("/api/team/chats", json={"kind": "dm", "members": [teampeer.pid(LEA)]}).json()
    r = client.post(f"/api/team/chats/{c['id']}/messages", json={"text": "x", "files": [{"path": "/tmp/a\u0000b"}]})
    assert r.status_code == 400


def _received_file(monkeypatch, fetch) -> tuple[str, str]:
    import time
    monkeypatch.setattr(teampeer, "fetch_file", fetch)
    dm = team.dm_id(ME, LEA)
    team.apply_remote(LEA, True, {"type": "message", "chat": dm, "message": {
        "id": "m_0000000a", "at": time.time(), "kind": "text", "text": "see", "files": [{"id": "f0", "name": "a.txt", "size": 3}]}})
    _wait(lambda: not any(f.get("pending") for m in team.messages(dm)["messages"] for f in m["files"]))
    return dm, "m_0000000a"


def test_forward_checks_the_message_first_and_skips_files_not_received(client, topic, sent, monkeypatch):
    from maxxing.sessions import store
    dm, mid = _received_file(monkeypatch, lambda *a, **k: False)
    before = len(store.list_ids())
    r = client.post(f"/api/team/chats/{dm}/messages/m_ffffffff/forward", json={"text": "x", "path": topic})
    assert r.status_code == 404 and len(store.list_ids()) == before     # nothing reached a session
    r = client.post(f"/api/team/chats/{dm}/messages/{mid}/forward", json={"text": "Read this", "path": topic})
    assert r.status_code == 200, r.text
    wait_idle(client, r.json()["session"]["id"])
