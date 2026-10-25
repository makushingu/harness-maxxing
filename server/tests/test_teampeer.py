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
