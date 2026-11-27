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


# ---- the Notifications feed on the phones ---------------------------------------------------------------------
def _scan(client) -> list[dict]:
    api_push.scan_feed()
    return client.post("/api/push/pending", json={"device": webpush.device_id(FCM)}).json()["items"]


def test_a_request_waiting_for_an_answer_rings_with_its_buttons(sent, client):
    from maxxing import feed
    client.post("/api/push/devices", json={"endpoint": FCM})
    api_push._feed_last = None
    assert _scan(client) == []                                    # the first look only notes where the feed is
    ev = feed.post("Blog Writer is waiting for your OK", "Bash: npm publish", "warning", "agents", "/agents?a=x",
                   ref="approval:" + "0" * 16, notify=False,
                   actions=[{"id": "allow", "label": "Allow", "style": "primary"}, {"id": "deny", "label": "Deny", "style": "danger"}])
    feed.post("All good", "", "info", "custom", notify=False)     # not something that cannot wait
    items = _scan(client)
    assert len(sent) == 1 and len(items) == 1
    assert items[0] == {"title": "Blog Writer is waiting for your OK", "body": "Bash: npm publish", "url": "/agents?a=x",
                        "tag": f"mx-feed-{ev['id']}", "event": ev["id"],
                        "actions": [{"id": "allow", "label": "Allow"}, {"id": "deny", "label": "Deny"}]}
    assert _scan(client) == []                                    # once


def test_a_request_too_long_to_show_whole_cannot_be_allowed_from_the_notification(sent, client):
    from maxxing import feed
    client.post("/api/push/devices", json={"endpoint": FCM})
    api_push._feed_last = feed.max_id()
    feed.post("Waiting", "x" * 400, "warning", "agents", ref="approval:" + "1" * 16, notify=False,
              actions=[{"id": "allow", "label": "Allow", "style": "primary"}, {"id": "open", "label": "Open", "style": "link"},
                       {"id": "deny", "label": "Deny", "style": "danger"}])
    item = _scan(client)[0]
    assert item["actions"] == [{"id": "deny", "label": "Deny"}] and len(item["body"]) == webpush.BODY_MAX


def test_an_event_answered_meanwhile_is_not_shown(sent, client):
    from maxxing import feed
    client.post("/api/push/devices", json={"endpoint": FCM})
    api_push._feed_last = feed.max_id()
    ev = feed.post("Waiting", "Bash: ls", "warning", "agents", ref="approval:" + "2" * 16, notify=False,
                   actions=[{"id": "deny", "label": "Deny", "style": "danger"}])
    api_push.scan_feed()
    feed.update(ev["id"], resolve=True, resolution="Allowed", notify=False)
    assert client.post("/api/push/pending", json={"device": webpush.device_id(FCM)}).json()["items"] == []


@pytest.mark.parametrize("mode, rings", [("all", ["Cron failed", "Waiting"]), ("asks", ["Waiting"]), ("off", [])])
def test_the_setting_says_what_of_the_feed_rings(sent, client, mode, rings):
    from maxxing import feed
    client.post("/api/push/devices", json={"endpoint": FCM})
    assert client.put("/api/feed/settings", json={"push": mode}).json()["push"] == mode
    api_push._feed_last = feed.max_id()
    feed.post("Cron failed", "exit 1", "error", "crons", notify=False)
    feed.post("Waiting", "Bash: ls", "warning", "agents", ref="approval:" + "3" * 16, notify=False,
              actions=[{"id": "deny", "label": "Deny", "style": "danger"}])
    assert [m["title"] for m in _scan(client)] == rings
    assert client.put("/api/feed/settings", json={"push": "loud"}).status_code == 400


def test_the_buttons_are_in_the_language_of_the_server(sent, client):
    from maxxing import feed
    client.post("/api/push/devices", json={"endpoint": FCM})
    client.put("/api/settings", json={"language": "fr"})
    api_push._feed_last = feed.max_id()
    feed.post("Waiting", "Bash: ls", "warning", "agents", ref="approval:" + "4" * 16, notify=False,
              actions=[{"id": "allow", "label": "Allow", "style": "primary"}, {"id": "deny", "label": "Deny", "style": "danger"}])
    assert [a["label"] for a in _scan(client)[0]["actions"]] == ["Autoriser", "Refuser"]


def test_the_service_worker_answers_a_button_through_the_feed():
    src = SW.read_text()
    assert "event.action && data.event" in src and "/api/feed/${data.event}/act/" in src
    assert "actions: m.actions.map" in src


def test_the_newer_address_of_chrome_is_a_known_push_service(client):
    assert client.post("/api/push/devices", json={"endpoint": "https://jmt17.google.com/fcm/send/abc:APA91"}).status_code == 200
    assert client.post("/api/push/devices", json={"endpoint": "https://jmt17.google.com.evil.example/fcm/send/abc"}).status_code == 400


def test_the_installed_app_is_a_share_target():
    """Every manifest (one per accent) offers the app in the share sheet, the worker keeps what is shared for the app
    and the app only takes it when it is the installed one."""
    web = SW.parents[1]
    manifests = sorted((web / "public").glob("manifest*.webmanifest"))
    assert len(manifests) >= 7
    for f in manifests:
        st = json.loads(f.read_text())["share_target"]
        assert (st["action"], st["method"], st["enctype"]) == ("/share", "POST", "multipart/form-data"), f.name
        assert st["params"]["files"][0]["name"] == "files" and {"title", "text", "url"} <= set(st["params"])
    src = SW.read_text()
    assert "pathname === '/share'" in src and "Response.redirect('/sessions?shared=1', 303)" in src
    assert ".slice(0, 10)" in src
    take = (web / "src" / "pwa" / "share.ts").read_text()
    assert take.index("isStandalone()") < take.index("cache.match('/__share/meta')")


def test_a_device_with_an_invalid_port_does_not_stop_the_others(sent, client):
    client.post("/api/push/devices", json={"endpoint": FCM})
    p = webpush._path()
    st = json.loads(p.read_text())
    st["devices"]["bad0000000000000"] = {"endpoint": "https://fcm.googleapis.com:abc/x", "label": "", "at": 0}
    p.write_text(json.dumps(st))
    assert webpush.notify("t", "b", "/") == 1
    assert [c["endpoint"] for c in sent] == [FCM]
    assert client.post("/api/push/devices", json={"endpoint": "https://fcm.googleapis.com:99999/x"}).status_code == 400
