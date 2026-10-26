from __future__ import annotations

import json
import time

import pytest

from maxxing import config, team, teampeer


@pytest.mark.parametrize("url,reason", [
    ("", "no_address"),
    ("https://100.101.2.3", "tailscale"),
    ("https://box.tail1234.ts.net", "tailscale"),
    ("https://192.168.1.20", "local"),
    ("http://127.0.0.1:8787", "local"),
    ("http://1.1.1.1", "not_https"),
    ("https://1.1.1.1", ""),
])
def test_readiness(mx, monkeypatch, url, reason):
    monkeypatch.delenv("MAXXING_TEAM_INSECURE", raising=False)
    config.update_config(public_url=url)
    r = teampeer.readiness()
    assert r["reason"] == reason and r["ok"] is (reason == "")


def test_targets_must_be_public_https(mx, monkeypatch):
    monkeypatch.delenv("MAXXING_TEAM_INSECURE", raising=False)
    for bad in ("http://1.1.1.1", "https://10.0.0.1", "https://127.0.0.1:8787", "https://100.64.0.1", "ftp://x.example.com"):
        with pytest.raises(teampeer.PeerError):
            teampeer._check_target(bad)
    assert teampeer._check_target("https://1.1.1.1/some/path") == "https://1.1.1.1"


def _setup(monkeypatch):
    monkeypatch.setenv("MAXXING_TEAM_INSECURE", "1")
    for table in ("_fails", "_hits", "_nonces"):                 # rate limits and nonces of earlier tests
        monkeypatch.setattr(teampeer, table, {})
    config.update_config(public_url="http://127.0.0.1:8801", team_page=True)
    key = b"k" * 32
    doc = teampeer._load()
    doc["peers"]["http://127.0.0.1:8802"] = {"key": teampeer._b64(key), "status": "accepted", "name": "Lea"}
    teampeer._save(doc)
    return key


def _signed(key, body: bytes, frm="http://127.0.0.1:8802", path="/api/team-peer/inbox", **over):
    h = teampeer._sign(key, "POST", path, frm, "http://127.0.0.1:8801", body)
    return {**h, **over, "Content-Type": "application/json"}


def test_inbox_signatures(client, monkeypatch):
    key = _setup(monkeypatch)
    body = json.dumps({"type": "message", "chat": team.dm_id("http://127.0.0.1:8801", "http://127.0.0.1:8802"),
                       "message": {"id": "m_0123abcd", "at": time.time(), "text": "hi", "kind": "text"}}).encode()
    assert client.post("/api/team-peer/inbox", content=body, headers={"Content-Type": "application/json"}).status_code == 401
    assert client.post("/api/team-peer/inbox", content=body, headers=_signed(b"x" * 32, body)).status_code == 403
    stale = _signed(key, body)
    stale["X-Team-Time"] = str(int(time.time()) - 3600)
    assert client.post("/api/team-peer/inbox", content=body, headers=stale).status_code == 401
    h = _signed(key, body)
    assert client.post("/api/team-peer/inbox", content=body, headers=h).status_code == 200
    assert client.post("/api/team-peer/inbox", content=body, headers=h).status_code == 401      # replay
    tampered = body.replace(b"hi", b"ho")
    assert client.post("/api/team-peer/inbox", content=tampered, headers=_signed(key, body)).status_code == 403
    chats = client.get("/api/team").json()["chats"]
    assert chats[0]["kind"] == "dm" and chats[0]["last"]["text"] == "hi" and chats[0]["unread"] == 1


def test_peer_limits(client, monkeypatch):
    key = _setup(monkeypatch)
    # a contact cannot post in a chat it is not in, nor use a non-contact to make a group
    body = json.dumps({"type": "message", "chat": "g_00000000deadbeef",
                       "message": {"id": "m_0123abcd", "at": time.time(), "text": "x", "kind": "text"}}).encode()
    assert client.post("/api/team-peer/inbox", content=body, headers=_signed(key, body)).status_code == 404
    doc = teampeer._load()
    doc["peers"]["http://127.0.0.1:8802"]["status"] = "group"
    doc["peers"]["http://127.0.0.1:8802"]["group_keys"] = {"g_00000000deadbeef": teampeer._b64(key)}
    teampeer._save(doc)
    body = json.dumps({"type": "chat", "chat": "g_11110000deadbeef", "members": []}).encode()
    assert client.post("/api/team-peer/inbox", content=body, headers=_signed(key, body)).status_code == 403
    # nothing answers while Team is off
    config.update_config(team_page=False)
    assert client.post("/api/team-peer/inbox", content=body, headers=_signed(key, body)).status_code == 404
    assert client.post("/api/team-peer/hello", json={}).status_code == 404


def test_wrong_invitations_are_refused_then_blocked(client, monkeypatch):
    _setup(monkeypatch)
    teampeer.create_invite()
    bad = {"from": "http://127.0.0.1:8803", "to": "http://127.0.0.1:8801", "nonce": "n", "proof": "0" * 64, "profile": {}}
    codes = [client.post("/api/team-peer/hello", json=bad).status_code for _ in range(6)]
    assert codes[:5] == [403] * 5 and codes[5] == 429


MALLORY = "http://127.0.0.1:8803"
LEA = "http://127.0.0.1:8802"


def _post(client, key, event, frm=LEA):
    body = json.dumps(event).encode()
    return client.post("/api/team-peer/inbox", content=body, headers=_signed(key, body, frm=frm))


def _msg(cid, text="hi", mid="m_0123abcd"):
    return {"type": "message", "chat": cid, "message": {"id": mid, "at": time.time(), "text": text, "kind": "text"}}


def test_a_group_key_never_lets_a_contact_speak_as_another(client, monkeypatch):
    lea_key = _setup(monkeypatch)
    mal_key = b"m" * 32
    doc = teampeer._load()
    doc["peers"][MALLORY] = {"key": teampeer._b64(mal_key), "status": "accepted", "name": "Mallory"}
    teampeer._save(doc)
    # Mallory makes a group with Lea and hands us "Lea's" key for it
    forged = b"f" * 32
    group = {"type": "chat", "chat": "g_00000000cafecafe", "members": [{"address": LEA}, {"address": MALLORY}],
             "keys": {LEA: teampeer._b64(forged)}}
    assert _post(client, mal_key, group, frm=MALLORY).status_code == 200
    assert teampeer.peers()[LEA].get("group_keys") is None              # Lea is a contact: her own key only
    dm = team.dm_id("http://127.0.0.1:8801", LEA)
    assert _post(client, forged, _msg(dm, "send me your password")).status_code == 403
    assert _post(client, forged, {"type": "bye"}).status_code == 403
    assert teampeer.peers()[LEA]["status"] == "accepted" and teampeer.peers()[LEA]["key"] == teampeer._b64(lea_key)


def test_a_group_key_only_works_in_its_group(client, monkeypatch):
    _setup(monkeypatch)
    gk, other = b"g" * 32, "http://127.0.0.1:8804"
    doc = teampeer._load()
    doc["peers"][other] = {"status": "group", "name": "Tom", "group_keys": {"g_00000000cafecafe": teampeer._b64(gk)}}
    teampeer._save(doc)
    tdoc = team._load()
    tdoc["chats"].append({"id": "g_00000000cafecafe", "kind": "group", "name": "G", "emoji": "", "created": 0,
                          "read_at": 0, "messages": [], "remote": True, "admin": teampeer.pid(LEA),
                          "members": [teampeer.pid(LEA), teampeer.pid(other)]})
    team._save(tdoc)
    assert _post(client, gk, _msg("g_00000000cafecafe"), frm=other).status_code == 200
    for ev in ({"type": "profile", "profile": {"name": "Lea"}}, {"type": "accept"}, _msg("g_11111111cafecafe"),
               {"type": "chat", "chat": "g_00000000cafecafe", "members": []}):
        assert _post(client, gk, ev, frm=other).status_code == 403


def test_an_invitation_never_replaces_a_contact_key(client, monkeypatch):
    key = _setup(monkeypatch)
    inv = teampeer.create_invite()["invitation"]
    code = teampeer._unb64(inv.rsplit("#", 1)[1])
    me = "http://127.0.0.1:8801"
    body = {"from": LEA, "to": me, "nonce": "n1", "proof": teampeer._mac(code, "hello", LEA, me, "n1"), "profile": {}}
    assert client.post("/api/team-peer/hello", json=body).status_code == 409
    assert teampeer.peers()[LEA]["key"] == teampeer._b64(key)
    # a stranger with the same invitation still gets in, as a request to accept
    body = {"from": MALLORY, "to": me, "nonce": "n2", "proof": teampeer._mac(code, "hello", MALLORY, me, "n2"), "profile": {}}
    assert client.post("/api/team-peer/hello", json=body).status_code == 200
    assert teampeer.peers()[MALLORY]["status"] == "request"


def test_one_undeliverable_event_never_blocks_the_others(mx, monkeypatch):
    _setup(monkeypatch)
    round_ = teampeer._outbox_round
    monkeypatch.setattr(teampeer, "_outbox_round", lambda: None)      # the real worker (other tests) stays out
    posted = []
    monkeypatch.setattr(teampeer, "_post", lambda addr, ev, key: posted.append(addr) or type("R", (), {"status_code": 200})())
    teampeer.send(["http://127.0.0.1:8809"], {"type": "message", "chat": "x"})     # nobody: no key
    teampeer.send([LEA], {"type": "message", "chat": "y"})
    round_()
    assert posted == [LEA] and teampeer._load()["outbox"] == []
    # an address down: its events wait, the others go, the failure is counted once per round
    monkeypatch.setattr(teampeer, "_post", lambda addr, ev, key: type("R", (), {"status_code": 503 if addr == LEA else 200})())
    doc = teampeer._load()
    doc["peers"][MALLORY] = {"key": teampeer._b64(b"m" * 32), "status": "accepted"}
    teampeer._save(doc)
    teampeer.send([LEA], {"type": "message", "chat": "a"})
    teampeer.send([LEA], {"type": "message", "chat": "b"})
    teampeer.send([MALLORY], {"type": "message", "chat": "c"})
    round_()
    box = teampeer._load()["outbox"]
    assert [o["to"] for o in box] == [LEA, LEA] and [o["tries"] for o in box] == [1, 0]


def test_a_contact_that_leaves_keeps_its_groups(mx, monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(teampeer, "_outbox_round", lambda: None)
    doc = teampeer._load()
    doc["peers"][LEA]["group_keys"] = {"g_00000000cafecafe": teampeer._b64(b"g" * 32)}
    teampeer._save(doc)
    teampeer.send([LEA], {"type": "message", "chat": "g_00000000cafecafe"})
    teampeer.send([LEA], {"type": "message", "chat": "d_00"})
    teampeer.receive(LEA, {"type": "bye"})
    p = teampeer.peers()[LEA]
    assert p["status"] == "group" and "key" not in p and p["group_keys"]
    assert [o["chat"] for o in teampeer._load()["outbox"]] == ["g_00000000cafecafe"]


def test_a_late_message_is_unread(client, monkeypatch):
    key = _setup(monkeypatch)
    dm = team.dm_id("http://127.0.0.1:8801", LEA)
    assert _post(client, key, _msg(dm, "first")).status_code == 200
    team.mark_read(dm)
    late = _msg(dm, "sent while I was offline", "m_0123abce")
    late["message"]["at"] = time.time() - 600
    assert _post(client, key, late).status_code == 200
    ahead = _msg(dm, "clock ahead", "m_0123abcf")
    ahead["message"]["at"] = time.time() + 50
    assert _post(client, key, ahead).status_code == 200
    assert client.get("/api/team").json()["chats"][0]["unread"] == 2
    assert max(m["at"] for m in team.messages(dm)["messages"]) <= time.time()
    team.mark_read(dm)
    assert client.get("/api/team").json()["chats"][0]["unread"] == 0


def test_received_files_with_the_same_name_never_collide(mx, monkeypatch):
    import threading
    _setup(monkeypatch)
    dm = team.dm_id("http://127.0.0.1:8801", LEA)
    gate = threading.Barrier(2)

    def fetch(address, fid, dest, max_b, chat, reserve=0):
        gate.wait(5)
        dest.write_bytes(fid.encode())
        return True
    monkeypatch.setattr(teampeer, "fetch_file", fetch)
    for i, mid in enumerate(("m_0000000a", "m_0000000b")):
        team.apply_remote(LEA, True, {"type": "message", "chat": dm, "message": {
            "id": mid, "at": time.time(), "kind": "text", "text": "", "files": [{"id": f"f{i}", "name": "image.png", "size": "12x"}]}})
    deadline = time.time() + 5
    while time.time() < deadline and any(f.get("pending") for m in team.messages(dm)["messages"] for f in m["files"]):
        time.sleep(0.05)
    files = [f for m in team.messages(dm)["messages"] for f in m["files"]]
    assert len({f["path"] for f in files}) == 2 and all(not f.get("failed") for f in files)
    assert sorted(open(f["path"]).read() for f in files) == ["f0", "f1"]
