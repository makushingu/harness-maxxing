"""Profile photo (Settings -> Profile): kept on this server, shown to Team contacts (maxxing/profile_photo.py)."""
from __future__ import annotations

import hashlib

from maxxing import config, profile_photo, teampeer

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x01" * 64
LEA = "http://127.0.0.1:8802"
ME = "http://127.0.0.1:8801"


def _put(client, data: bytes):
    return client.put("/api/settings/profile/photo", content=data, headers={"Content-Type": "application/octet-stream"})


def test_own_photo_is_stored_served_kept_and_removed(client):
    r = _put(client, PNG)
    assert r.status_code == 200
    v = hashlib.sha256(PNG).hexdigest()[:16]
    assert r.json()["photo"] == v and r.json()["photo_url"] == f"/api/settings/profile/photo?v={v}"
    got = client.get(r.json()["photo_url"])
    assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"
    # the pseudo can change: the photo stays
    assert client.put("/api/settings/profile", json={"name": "Léa", "color": "teal", "emoji": "🔥"}).json()["photo"] == v
    assert client.get("/api/team").json()["people"]["me"]["photo_url"].endswith(v)
    assert client.delete("/api/settings/profile/photo").json()["photo"] == ""
    assert client.get("/api/settings/profile/photo").status_code == 404
    assert not profile_photo.own_path().exists()


def test_only_small_jpeg_png_or_webp(client):
    assert _put(client, b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>').status_code == 400
    assert _put(client, b"GIF89a" + b"\x00" * 20).status_code == 400
    assert _put(client, b"").status_code == 400
    assert _put(client, JPEG[:4] + b"\x00" * (profile_photo.PHOTO_MAX + 1)).status_code == 400
    assert client.get("/api/settings/profile").json()["photo"] == ""
    assert _put(client, b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 30).status_code == 200
    client.cookies.clear()
    assert client.get("/api/settings/profile/photo").status_code == 401
    assert _put(client, PNG).status_code == 401


def _contact(monkeypatch, status="accepted", photo=""):
    monkeypatch.setenv("MAXXING_TEAM_INSECURE", "1")
    for table in ("_fails", "_hits", "_nonces"):
        monkeypatch.setattr(teampeer, table, {})
    config.update_config(public_url=ME, team_page=True)
    key = b"k" * 32
    doc = teampeer._load()
    doc["peers"][LEA] = {"key": teampeer._b64(key), "status": status, "name": "Lea", "photo": photo}
    teampeer._save(doc)
    return key


def test_a_contact_gets_our_photo_with_a_signed_request_only(client, monkeypatch):
    key = _contact(monkeypatch)
    path = "/api/team-peer/photo"
    assert client.get(path).status_code == 401
    h = teampeer._sign(key, "GET", path, LEA, ME, b"")
    assert client.get(path, headers=h).status_code == 404                  # no photo yet
    _put(client, JPEG)
    h = teampeer._sign(key, "GET", path, LEA, ME, b"")
    r = client.get(path, headers=h)
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    assert client.get(path, headers=teampeer._sign(b"x" * 32, "GET", path, LEA, ME, b"")).status_code == 403
    # a request not answered yet proves nothing: no photo
    _contact(monkeypatch, status="request")
    assert client.get(path, headers=teampeer._sign(key, "GET", path, LEA, ME, b"")).status_code == 404


def test_the_profile_sent_to_contacts_carries_the_photo_version(client, monkeypatch):
    _contact(monkeypatch)
    v = _put(client, PNG).json()["photo"]
    assert teampeer._profile()["photo"] == v
    assert teampeer._clean_profile({"name": "x", "photo": "../../etc"})["photo"] == ""
    assert teampeer._clean_profile({"name": "x"})["photo"] == ""          # a server before the photos


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self, n):
        yield self._data


class _Http:
    def __init__(self, data, status=200):
        self.data, self.status, self.calls = data, status, []

    def stream(self, method, url, headers, **kw):
        self.calls.append((method, url, headers))
        return _Resp(self.status, self.data)


def test_a_contacts_photo_is_fetched_once_per_version_and_checked(client, monkeypatch):
    v = hashlib.sha256(PNG).hexdigest()[:16]
    key = _contact(monkeypatch, photo=v)
    http = _Http(PNG)
    monkeypatch.setattr(teampeer, "_http", lambda: http)
    monkeypatch.setattr(profile_photo, "_failed", {})
    person = client.get("/api/team").json()["people"][teampeer.pid(LEA)]
    assert person["photo_url"] == f"/api/team/people/{teampeer.pid(LEA)}/photo?v={v}"
    r = client.get(person["photo_url"])
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    method, url, h = http.calls[0]
    assert (method, url) == ("GET", LEA + "/api/team-peer/photo")
    assert h["X-Team-Sig"] == teampeer._mac(key, "GET", "/api/team-peer/photo", ME, LEA, h["X-Team-Time"], h["X-Team-Nonce"],
                                            hashlib.sha256(b"").hexdigest())
    assert client.get(person["photo_url"]).status_code == 200 and len(http.calls) == 1   # cached
    # another version: bytes that do not match it, or not an image, are refused and not asked again at once
    v2 = hashlib.sha256(JPEG).hexdigest()[:16]
    _contact(monkeypatch, photo=v2)
    http.data = PNG
    url2 = f"/api/team/people/{teampeer.pid(LEA)}/photo?v={v2}"
    assert client.get(url2).status_code == 404
    assert client.get(url2).status_code == 404 and len(http.calls) == 2
    # a version it does not have, a bad id: nothing asked
    assert client.get(f"/api/team/people/{teampeer.pid(LEA)}/photo?v={'0' * 16}").status_code == 404
    assert client.get("/api/team/people/..%2F..%2Fx/photo?v=" + v).status_code == 404
    assert len(http.calls) == 2
    profile_photo._failed.clear()
    http.data = JPEG
    assert client.get(url2).status_code == 200
    assert sorted(p.name for p in (config.STATE / "team" / "photos").iterdir()) == [f"{teampeer.pid(LEA)}-{v2}"]


def test_a_slow_or_doubled_photo_fetch_never_holds_the_server(client, monkeypatch):
    v = hashlib.sha256(PNG).hexdigest()[:16]
    _contact(monkeypatch, photo=v)
    http = _Http(PNG)
    monkeypatch.setattr(teampeer, "_http", lambda: http)
    monkeypatch.setattr(profile_photo, "_failed", {})
    url = f"/api/team/people/{teampeer.pid(LEA)}/photo?v={v}"
    key = f"{teampeer.pid(LEA)}-{v}"
    profile_photo._busy.add(key)                 # already being fetched by another request: no second download
    try:
        assert client.get(url).status_code == 404 and http.calls == []
    finally:
        profile_photo._busy.discard(key)
    monkeypatch.setattr(teampeer, "PHOTO_DEADLINE", -1)     # past the deadline for the whole photo: dropped
    assert client.get(url).status_code == 404 and len(http.calls) == 1
    assert not (config.STATE / "team" / "photos").exists() or not any((config.STATE / "team" / "photos").iterdir())


def test_two_photos_sent_at_once_keep_the_file_and_its_version_together(client):
    import threading
    pngs = [PNG + bytes([i]) * 8 for i in range(2)]
    errors = []

    def send(data):
        for _ in range(30):
            try:
                if _put(client, data).status_code != 200:
                    errors.append("status")
            except Exception as e:                           # noqa: BLE001 - any failure is the bug
                errors.append(repr(e))
    threads = [threading.Thread(target=send, args=(d,)) for d in pngs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    v = client.get("/api/settings/profile").json()["photo"]
    assert hashlib.sha256(profile_photo.own_path().read_bytes()).hexdigest()[:16] == v
    assert not list(profile_photo.own_path().parent.glob("*.part"))


def test_a_photo_removed_during_an_upload_never_leaves_a_version_without_its_file(client, monkeypatch):
    import threading
    import time
    assert _put(client, PNG).status_code == 200
    real, saving = profile_photo.save, threading.Event()

    def slow(data):
        v = real(data)
        saving.set()
        time.sleep(0.3)                                      # the file is there, the version not yet written
        return v
    monkeypatch.setattr(profile_photo, "save", slow)
    t = threading.Thread(target=_put, args=(client, JPEG))
    t.start()
    assert saving.wait(5)
    client.delete("/api/settings/profile/photo")
    t.join()
    p = client.get("/api/settings/profile").json()
    assert not p["photo_url"] or client.get(p["photo_url"]).status_code == 200


def test_failed_photo_fetches_are_not_remembered_for_strangers_nor_forever(client, monkeypatch):
    import time
    v = hashlib.sha256(PNG).hexdigest()[:16]
    _contact(monkeypatch, photo=v)
    monkeypatch.setattr(teampeer, "_http", lambda: _Http(JPEG))      # bytes that do not match the version
    monkeypatch.setattr(profile_photo, "_failed", {})
    for i in range(50):                                              # ids and versions nobody announced
        assert client.get(f"/api/team/people/p_{i:06x}/photo?v={i:016x}").status_code == 404
    assert profile_photo._failed == {}
    profile_photo._failed["p_000001-" + "1" * 16] = time.time() - profile_photo.RETRY_S - 1
    assert client.get(f"/api/team/people/{teampeer.pid(LEA)}/photo?v={v}").status_code == 404
    assert list(profile_photo._failed) == [f"{teampeer.pid(LEA)}-{v}"]   # the stale entry purged


def test_a_lone_surrogate_in_the_pseudo_is_a_400_not_a_500(client):
    import json
    before = client.get("/api/settings/profile").json()
    for field in ("name", "emoji"):
        body = {"name": "Léa", "color": "", "emoji": "", field: "\ud800"}
        r = client.put("/api/settings/profile", content=json.dumps(body), headers={"content-type": "application/json"})
        assert r.status_code == 400
    assert client.get("/api/settings/profile").json() == before


def _cache_files():
    d = config.STATE / "team" / "photos"
    return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


def _fetched(client, monkeypatch, data, v):
    monkeypatch.setattr(teampeer, "_http", lambda: _Http(data))
    monkeypatch.setattr(profile_photo, "_failed", {})
    return client.get(f"/api/team/people/{teampeer.pid(LEA)}/photo?v={v}")


def test_a_forgotten_contacts_photo_is_deleted_and_never_served(client, monkeypatch):
    v = hashlib.sha256(PNG).hexdigest()[:16]
    _contact(monkeypatch, photo=v)
    assert _fetched(client, monkeypatch, PNG, v).status_code == 200
    assert _cache_files() == [f"{teampeer.pid(LEA)}-{v}"]
    monkeypatch.setattr(teampeer, "_deliver_now", lambda *a, **k: True)
    teampeer.forget(LEA)
    assert _cache_files() == []
    # a copy left on disk (a server before this fix) is not served for someone we do not know
    d = config.STATE / "team" / "photos"
    (d / f"{teampeer.pid(LEA)}-{v}").write_bytes(PNG)
    assert client.get(f"/api/team/people/{teampeer.pid(LEA)}/photo?v={v}").status_code == 404


def test_a_removed_or_replaced_photo_drops_the_old_copy(client, monkeypatch):
    v = hashlib.sha256(PNG).hexdigest()[:16]
    _contact(monkeypatch, photo=v)
    assert _fetched(client, monkeypatch, PNG, v).status_code == 200
    teampeer.receive(LEA, {"type": "profile", "profile": {"name": "Lea", "photo": ""}})
    assert _cache_files() == []
    assert client.get(f"/api/team/people/{teampeer.pid(LEA)}/photo?v={v}").status_code == 404
    # another contact's photo is not touched
    other = "https://other.example.com"
    doc = teampeer._load()
    doc["peers"][other] = {"key": teampeer._b64(b"o" * 32), "status": "accepted", "photo": v}
    teampeer._save(doc)
    d = config.STATE / "team" / "photos"
    (d / f"{teampeer.pid(other)}-{v}").write_bytes(PNG)
    teampeer.receive(LEA, {"type": "profile", "profile": {"name": "Lea", "photo": v}})
    assert _cache_files() == [f"{teampeer.pid(other)}-{v}"]


def test_a_group_members_photo_follows_its_changes_and_goes_with_the_group(client, monkeypatch):
    _contact(monkeypatch, status="group")
    doc = teampeer._load()
    doc["peers"][LEA] = {"status": "group", "name": "Lea", "photo": "", "group_keys": {"g_one": teampeer._b64(b"g" * 32)}}
    teampeer._save(doc)
    v = hashlib.sha256(PNG).hexdigest()[:16]
    # the creator's roster fills a photo we did not have (member seen before 2.0.0a132), never adds a stranger
    teampeer.add_group_peers("g_one", [(LEA, None, {"name": "Renamed", "photo": v}),
                                       ("https://stranger.example.com", None, {"photo": v})])
    peers = teampeer.peers()
    assert peers[LEA]["photo"] == v and peers[LEA]["name"] == "Lea" and "https://stranger.example.com" not in peers
    assert _fetched(client, monkeypatch, PNG, v).status_code == 200
    # the member changes its photo: it tells us through its group key, only the photo is taken
    v2 = hashlib.sha256(JPEG).hexdigest()[:16]
    teampeer.receive(LEA, {"type": "profile", "chat": "g_one", "profile": {"name": "Evil", "photo": v2}}, scope="g_one")
    assert teampeer.peers()[LEA]["photo"] == v2 and teampeer.peers()[LEA]["name"] == "Lea"
    assert _cache_files() == []
    # an event for another group with this key is refused
    import pytest
    with pytest.raises(teampeer.PeerError):
        teampeer.receive(LEA, {"type": "profile", "chat": "g_two", "profile": {"photo": v}}, scope="g_one")
    assert _fetched(client, monkeypatch, JPEG, v2).status_code == 200
    teampeer.drop_chat_keys("g_one")                 # we left the last group shared with her
    assert LEA not in teampeer.peers() and _cache_files() == []


def test_our_photo_reaches_group_members_who_are_not_contacts(client, monkeypatch):
    _contact(monkeypatch)
    doc = teampeer._load()
    member = "https://member.example.com"
    doc["peers"][member] = {"status": "group", "group_keys": {"g_one": teampeer._b64(b"g" * 32)}}
    teampeer._save(doc)
    monkeypatch.setattr(teampeer._wake, "set", lambda: None)
    v = _put(client, PNG).json()["photo"]
    out = {o["to"]: o["event"] for o in teampeer._load()["outbox"]}
    assert out[LEA]["profile"]["photo"] == v and "chat" not in out[LEA]
    assert out[member] == {"type": "profile", "chat": "g_one", "profile": {"photo": v}}
