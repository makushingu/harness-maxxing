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


def test_a_refused_file_removes_the_ones_saved_before_it(client, mx):
    # all or nothing: a client retrying the request must not find f0.bin kept (and get f0-1.bin)
    config.update_config(upload_max_mb=1)
    r = client.post("/api/files/upload", params={"dir": str(mx["files"])},
                    files=[("file", (f"f{i}.bin", b, "application/octet-stream"))
                           for i, b in enumerate([b"a" * 1000, b"x" * (uploads.MB + 1000)])])
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    assert not (mx["files"] / "f0.bin").exists() and not (mx["files"] / "f1.bin").exists()


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


def test_uploads_are_spooled_on_disk_under_the_state_dir(client, mx, monkeypatch):
    """Not in the system temp dir (often a tmpfs: the whole upload sat in RAM); its free space is what is checked."""
    import tempfile
    from starlette import formparsers
    dirs, seen = [], []
    real = tempfile.SpooledTemporaryFile

    def spy(*a, **kw):
        dirs.append(kw.get("dir"))
        return real(*a, **kw)
    monkeypatch.setattr(tempfile, "SpooledTemporaryFile", spy)
    monkeypatch.setattr(uploads, "free_bytes", lambda p: (seen.append(str(p)), 1 << 40)[1])
    assert formparsers.SpooledTemporaryFile is uploads._spooled
    assert _post(client, mx["files"], b"x" * (2 * uploads.MB)).status_code == 200
    spool = str(config.STATE / "tmp" / "uploads")
    assert dirs == [spool] and spool in seen
    assert (mx["files"] / "up.bin").stat().st_size == 2 * uploads.MB


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


def test_infinite_upload_max_mb_falls_back_to_the_default(mx):
    # a hand-edited 1e999 loads as inf: int(inf) raises OverflowError, which broke every upload
    config.update_config(upload_max_mb=float("inf"), upload_min_free_mb=float("-inf"))
    assert uploads.limits() == (2048 * uploads.MB, 1024 * uploads.MB)
