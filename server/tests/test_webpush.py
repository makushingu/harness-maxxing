"""Web Push (Settings -> Alerts -> Mobile notifications): the ES256 signature, the devices, the empty push and
what the service worker fetches afterwards."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from maxxing import webpush
from maxxing.api import push as api_push

FCM = "https://fcm.googleapis.com/fcm/send/abc123"
SW = Path(__file__).resolve().parents[2] / "web" / "sw" / "sw.js"


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@pytest.fixture
def sent(mx, monkeypatch) -> list[dict]:
    """Every push the server would send (no network)."""
    calls: list[dict] = []
    monkeypatch.setattr(webpush, "_post", lambda endpoint, headers: calls.append({"endpoint": endpoint, "headers": headers}) or 201)
    webpush._queues.clear()
    return calls


def test_es256_matches_the_rfc_6979_vector():
    # RFC 6979 A.2.5: P-256, SHA-256, message "sample"
    d = 0xC9AFA9D845BA75166B5C215767B1D6934E50C3DB36E89B127B8A622B120F6721
    assert webpush._rfc6979_k(d, hashlib.sha256(b"sample").digest()) == 0xA6E3C57DD01ABE90086538398355DD4C3B17AA873382B0F24D6129493D8AAD60
    sig = webpush.sign(d, b"sample")
    assert sig[:32].hex().upper() == "EFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716"
    assert sig[32:].hex().upper() == "F7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8"
    pt = webpush.public_point(d)
    assert webpush.verify(pt, b"sample", sig) and not webpush.verify(pt, b"sampl", sig)
    assert not webpush.verify(pt, b"sample", sig[:-1] + bytes([sig[-1] ^ 1]))


def test_the_vapid_header_is_a_valid_jwt_for_the_push_service(mx):
    key = _b64d(webpush.public_key())
    assert len(key) == 65 and key[0] == 4
    auth = webpush.vapid_header(FCM)
    token, k = auth[len("vapid t="):].split(", k=")
    head, body, sig = token.split(".")
    assert k == webpush.public_key() and json.loads(_b64d(head)) == {"typ": "JWT", "alg": "ES256"}
    claims = json.loads(_b64d(body))
    assert claims["aud"] == "https://fcm.googleapis.com" and claims["exp"] > 0 and claims["sub"]
    point = (int.from_bytes(key[1:33], "big"), int.from_bytes(key[33:], "big"))
    assert webpush.verify(point, f"{head}.{body}".encode(), _b64d(sig))


def test_the_key_pair_is_kept_and_private(mx):
    first = webpush.public_key()
    assert webpush.public_key() == first
    f = Path(webpush._path())
    assert f.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("url", [
    "http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://evil.example.com/x",
    "https://fcm.googleapis.com.evil.com/x", "https://user@fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x", "", None,
])
def test_only_the_browsers_push_services_are_accepted(url):
    assert not webpush.allowed_endpoint(url)


@pytest.mark.parametrize("url", [FCM, "https://updates.push.services.mozilla.com/wpush/v2/x", "https://web.push.apple.com/x",
                                 "https://wns2-par02p.notify.windows.com/x"])
def test_the_known_push_services_are_accepted(url):
    assert webpush.allowed_endpoint(url)


def test_devices_api(client, sent):
    assert client.get("/api/push/key").json()["key"] == webpush.public_key()
    assert client.post("/api/push/devices", json={"endpoint": "https://evil.example.com/x"}).status_code == 400
    r = client.post("/api/push/devices", json={"endpoint": FCM, "label": "Chrome · Android"})
    assert r.status_code == 200 and r.json()["id"] == webpush.device_id(FCM)
    assert [d["label"] for d in client.get("/api/push/devices").json()] == ["Chrome · Android"]
    assert client.delete(f"/api/push/devices/{r.json()['id']}").status_code == 200
    assert client.delete(f"/api/push/devices/{r.json()['id']}").status_code == 404
    assert client.get("/api/push/devices").json() == []


def test_the_routes_need_a_sign_in(mx):
    from fastapi.testclient import TestClient
    from maxxing.app import create_app
    with TestClient(create_app()) as c:
        c.headers["X-Maxxing"] = "1"
        assert c.get("/api/push/key").status_code == 401
        assert c.post("/api/push/pending", json={"device": "x"}).status_code == 401


def test_a_push_is_empty_and_the_worker_fetches_what_to_show(client, sent):
    did = client.post("/api/push/devices", json={"endpoint": FCM}).json()["id"]
    assert client.post("/api/push/test").json() == {"sent": 1}
    assert len(sent) == 1 and sent[0]["endpoint"] == FCM
    assert sent[0]["headers"]["Authorization"].startswith("vapid t=") and sent[0]["headers"]["Content-Length"] == "0"
    items = client.post("/api/push/pending", json={"device": did}).json()["items"]
    assert len(items) == 1 and items[0]["title"] and items[0]["url"] == "/settings/alerts"
    assert client.post("/api/push/pending", json={"device": did}).json()["items"] == []     # fetched once
    assert client.post("/api/push/pending", json={"device": "nope"}).json()["items"] == []


def test_a_gone_device_is_removed(client, monkeypatch):
    monkeypatch.setattr(webpush, "_post", lambda endpoint, headers: 410)
    client.post("/api/push/devices", json={"endpoint": FCM})
    assert client.post("/api/push/test").json() == {"sent": 0}
    assert client.get("/api/push/devices").json() == []


def test_a_server_error_keeps_the_device(client, monkeypatch):
    monkeypatch.setattr(webpush, "_post", lambda endpoint, headers: 503)
    client.post("/api/push/devices", json={"endpoint": FCM})
    assert client.post("/api/push/test").json() == {"sent": 0}
    assert len(client.get("/api/push/devices").json()) == 1


def test_a_session_of_a_person_rings_and_a_job_does_not(sent, client):
    import asyncio
    client.post("/api/push/devices", json={"endpoint": FCM})
    mine = {"id": "s1", "path": "projects/acme/topics/blog", "title": "Blog", "state": "idle", "last_text": "**Done**: the post",
            "source": "web", "last_turn": {"kind": "user", "source": "web"}}
    asyncio.run(api_push._turn_end(mine, None))
    assert len(sent) == 1
    item = client.post("/api/push/pending", json={"device": webpush.device_id(FCM)}).json()["items"][0]
    assert item["tag"] == "mx-session-s1" and "Blog" in item["body"] and "Done" in item["body"]
    assert item["url"] == "/sessions?path=projects/acme/topics/blog&session=s1"
    for other in ({"source": "cron"}, {"source": "agent"}, {"last_turn": {"kind": "user", "source": "telegram"}}, {"last_turn": {"kind": "system"}}, {"push": False}):
        asyncio.run(api_push._turn_end({**mine, **other}, None))
    assert len(sent) == 1


def test_a_failed_turn_is_notified_too(sent, client):
    import asyncio
    client.post("/api/push/devices", json={"endpoint": FCM})
    asyncio.run(api_push._turn_end({"id": "s2", "path": "p", "title": "T", "state": "error", "error": "boom", "source": "web",
                                    "last_turn": {"kind": "user"}}, None))
    item = client.post("/api/push/pending", json={"device": webpush.device_id(FCM)}).json()["items"][0]
    assert "failed" in item["title"] and "boom" in item["body"]


def test_the_service_worker_shows_what_the_server_lists():
    src = SW.read_text()
    assert "addEventListener('push'" in src and "'/api/push/pending'" in src and "'X-Maxxing': '1'" in src
    assert "showNotification" in src and "addEventListener('notificationclick'" in src
    assert "url.origin !== self.location.origin" in src           # a tap only opens this app


def test_a_damaged_webpush_file_is_kept_before_a_new_key_replaces_it(mx):
    webpush.public_key()
    f = webpush._path()
    f.write_text("{bad")
    webpush.add_device(FCM)
    kept = list(f.parent.glob("webpush.json.damaged-*"))
    assert kept and kept[0].read_text() == "{bad"


@pytest.mark.parametrize("bad", [
    {"private": "zz", "devices": {}},
    {"private": "0" * 64, "devices": {}},
    {"private": "f" * 64, "devices": {}},
    {"private": "1" * 64, "devices": {"a": 5}},
])
def test_an_unusable_key_or_device_list_is_replaced_and_kept(mx, bad):
    f = webpush._path()
    f.write_text(json.dumps(bad))
    assert len(_b64d(webpush.public_key())) == 65 and webpush.devices() == []
    webpush.add_device(FCM)
    assert list(f.parent.glob("webpush.json.damaged-*"))
    assert len(webpush.devices()) == 1


def test_a_hand_edited_registration_time_does_not_break_the_devices(client):
    """A device whose `at` is text (webpush.json edited by hand) must not stop the list nor the phone notifications."""
    a = webpush.add_device("https://fcm.googleapis.com/fcm/send/a", "Phone")
    webpush.add_device("https://fcm.googleapis.com/fcm/send/b", "Tablet")
    f = Path(webpush._path())
    st = json.loads(f.read_text())
    st["devices"][a["id"]]["at"] = "x"
    f.write_text(json.dumps(st))
    assert [d["label"] for d in webpush.devices()] == ["Phone", "Tablet"]
    r = client.get("/api/push/devices")
    assert r.status_code == 200 and len(r.json()) == 2
