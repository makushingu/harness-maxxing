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
