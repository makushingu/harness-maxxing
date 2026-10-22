"""Upload limits (maxxing/uploads.py): size cap, free-disk reserve, auth before the body is read."""
from __future__ import annotations

from fastapi.testclient import TestClient

from maxxing import config, uploads


def _post(c, folder, data=b"data", **kw):
    return c.post("/api/files/upload", params={"dir": str(folder)},
                  files=[("file", ("up.bin", data, "application/octet-stream"))], **kw)


def test_defaults(mx):
    cfg = config.load_config()
    config.save_config({k: cfg[k] for k in ("workspace", "files_root")})
    assert uploads.limits() == (2048 * uploads.MB, 1024 * uploads.MB)
    config.update_config(upload_max_mb="junk", upload_min_free_mb=-5)
    assert uploads.limits() == (2048 * uploads.MB, 0)


def test_cap_refuses_before_reading(client, mx):
    config.update_config(upload_max_mb=1)
    r = _post(client, mx["files"], b"x" * (3 * uploads.MB))
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    assert not (mx["files"] / "up.bin").exists()
    assert _post(client, mx["files"], b"small").status_code == 200


def test_cap_per_file_in_save_upload(client, mx, monkeypatch):
    # just under the request ceiling (cap + 1 MB of framing) but over the cap for the file itself
    config.update_config(upload_max_mb=1)
    r = _post(client, mx["files"], b"x" * (uploads.MB + 1000))
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    assert not (mx["files"] / "up.bin").exists()


def test_cap_while_streaming_without_content_length(client, mx):
    config.update_config(upload_max_mb=1)

    def body():
        for _ in range(4):
            yield b"x" * uploads.MB
    r = client.post("/api/files/upload", params={"dir": str(mx["files"])}, content=body(),
                    headers={"Content-Type": "multipart/form-data; boundary=zz"})
    assert r.status_code == 413 and r.json()["error"] == "too_large"


def test_disk_reserve(client, mx, monkeypatch):
    monkeypatch.setattr(uploads, "free_bytes", lambda p: 1500 * uploads.MB)
    config.update_config(upload_min_free_mb=1024)
    assert _post(client, mx["files"], b"x" * 1000).status_code == 200
    config.update_config(upload_min_free_mb=1500)
    r = _post(client, mx["files"], b"x" * 1000)
    assert r.status_code == 507 and r.json()["error"] == "disk_full"
    # destination check (temp dir fine, destination nearly full)
    config.update_config(upload_min_free_mb=10)
    monkeypatch.setattr(uploads, "free_bytes",
                        lambda p: 10 * uploads.MB if str(p) == str(mx["files"]) else 1 << 40)
    r = _post(client, mx["files"], b"x" * 1000)
    assert r.status_code == 507
    assert list(mx["files"].iterdir()) == [mx["files"] / "up.bin"]     # only the first upload


def test_chat_uploads_share_the_limits(client, mx, topic):
    config.update_config(upload_max_mb=1)
    r = client.post("/api/uploads", params={"path": topic},
                    files=[("file", ("big.bin", b"x" * (3 * uploads.MB), "application/octet-stream"))])
    assert r.status_code == 413


def test_multipart_needs_auth_before_body(mx):
    from maxxing.app import create_app
    from maxxing import security
    security.set_password("rightpassword")
    with TestClient(create_app()) as c:
        r = _post(c, mx["files"], headers={"X-Maxxing": "1"})
        assert r.status_code == 401 and r.json()["error"] == "auth_required"
        c.cookies.set(security.COOKIE, security.make_cookie())
        assert _post(c, mx["files"]).status_code == 403                      # no CSRF header
        assert _post(c, mx["files"], headers={"X-Maxxing": "1"}).status_code == 200
