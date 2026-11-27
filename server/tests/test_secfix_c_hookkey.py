"""The access key of a phone webhook (`?key=`, Bearer, X-Harness-Key): only its SHA-256 is stored."""
from __future__ import annotations

import hashlib
import json

from maxxing import config, webhooks

KEY = "k3y-of-my-phone"
HASH = "sha256:" + hashlib.sha256(KEY.encode()).hexdigest()


def _shell(name: str, **trigger) -> dict:
    return {"name": name, "trigger": {"kind": "in", "reply": "wait", **trigger}, "action": {"kind": "shell", "command": "echo ok"}}


def _tok(h: dict) -> str:
    return h["url"].rsplit("/", 1)[1]


def _stored(h: dict) -> str:
    return config.load_secrets()["webhooks"][h["id"]].get("secret", "")


def _on_disk() -> str:
    return config.secrets_path().read_text()


def test_a_key_given_at_creation_or_later_is_stored_hashed(client):
    a = client.post("/api/webhooks", json={**_shell("a", source="phone"), "secret": KEY}).json()
    assert a["has_secret"] and _stored(a) == HASH and KEY not in _on_disk()
    b = client.post("/api/webhooks", json=_shell("b", source="phone")).json()
    assert client.post(f"/api/webhooks/{b['id']}/secret", json={"secret": KEY}).json()["has_secret"]
    assert _stored(b) == HASH and KEY not in _on_disk()
    for h in (a, b):
        url = f"/api/hooks/{_tok(h)}"
        assert client.get(url).status_code == 401
        assert client.get(url + "?key=wrong").status_code == 401
        assert client.get(url + "?key=" + HASH).status_code == 401          # the stored hash is not a key
        assert client.get(url + "?key=" + KEY).status_code == 200
        assert client.get(url, headers={"Authorization": "Bearer " + KEY}).status_code == 200
        assert client.get(url, headers={"X-Harness-Key": KEY}).status_code == 200
    assert KEY not in json.dumps(client.get("/api/webhooks").json())
    assert not client.post(f"/api/webhooks/{b['id']}/secret", json={"secret": ""}).json()["has_secret"]
    assert client.get(f"/api/hooks/{_tok(b)}").status_code == 200


def _clear_key(h: dict) -> None:
    """As an earlier version stored it."""
    store = config.load_secrets()["webhooks"]
    store[h["id"]]["secret"] = KEY
    config.set_secret("webhooks", store)
    assert KEY in _on_disk()


def test_a_clear_key_is_converted_at_the_first_call(client):
    h = client.post("/api/webhooks", json=_shell("old", source="phone")).json()
    _clear_key(h)
    assert client.get(f"/api/hooks/{_tok(h)}?key=wrong").status_code == 401   # a refused call converts it too
    assert _stored(h) == HASH and KEY not in _on_disk()
    assert client.get(f"/api/hooks/{_tok(h)}?key={KEY}").status_code == 200
    assert _stored(h) == HASH


def test_a_clear_key_is_converted_by_any_write_of_the_store(client):
    h = client.post("/api/webhooks", json=_shell("old", source="phone")).json()
    _clear_key(h)
    client.post("/api/webhooks", json=_shell("another"))
    assert _stored(h) == HASH and KEY not in _on_disk()
    assert client.get(f"/api/hooks/{_tok(h)}?key={KEY}").status_code == 200


def test_conversion_failing_does_not_stop_the_call(client, monkeypatch):
    h = client.post("/api/webhooks", json=_shell("old", source="phone")).json()
    _clear_key(h)
    monkeypatch.setattr(webhooks, "_hash_phone_keys", lambda *a: 1 / 0)
    assert client.get(f"/api/hooks/{_tok(h)}?key={KEY}").status_code == 200
    assert client.get(f"/api/hooks/{_tok(h)}?key=wrong").status_code == 401


def test_signing_secrets_of_other_sources_stay_usable(client):
    g = client.post("/api/webhooks", json={**_shell("g", source="github"), "secret": "whsec"}).json()
    assert _stored(g) == "whsec"
    p = client.patch(f"/api/webhooks/{g['id']}", json={"trigger": {"kind": "in", "source": "phone"}})
    assert p.status_code == 200, p.text
    assert _stored(g) == "sha256:" + hashlib.sha256(b"whsec").hexdigest()    # now a phone key: hashed
    assert client.get(f"/api/hooks/{_tok(g)}?key=whsec").status_code == 202
    # back to a signed source: the hash is no signing secret anyone knows, calls are refused until a new one is set
    assert client.patch(f"/api/webhooks/{g['id']}", json={"trigger": {"kind": "in", "source": "github"}}).status_code == 200
    assert client.post(f"/api/hooks/{_tok(g)}", content=b"{}").status_code == 401
