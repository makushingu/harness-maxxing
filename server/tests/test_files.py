from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from maxxing import videos


@pytest.fixture
def tree(mx):
    root = mx["files"]
    (root / "docs").mkdir()
    (root / "docs" / "a.md").write_text("# Title\n")
    (root / "b.txt").write_text("hello world")
    (root / "bin.dat").write_bytes(b"\x00\x01\x02" * 100)
    return root


def test_list_and_read(client, tree):
    r = client.get("/api/files/list", params={"path": str(tree)}).json()
    assert r["root"] == str(tree) and r["parent"] is None
    assert [e["name"] for e in r["entries"]] == ["docs", "b.txt", "bin.dat"]
    assert r["entries"][0]["type"] == "dir"
    sub = client.get("/api/files/list", params={"path": str(tree / "docs")}).json()
    assert sub["parent"] == str(tree)
    assert client.get("/api/files/list").json()["path"] == str(tree)       # default = root
    f = client.get("/api/files/read", params={"path": str(tree / "b.txt")}).json()
    assert f["content"] == "hello world" and f["size"] == 11 and f["editable"] is True
    assert client.get("/api/files/read", params={"path": str(tree / "bin.dat")}).status_code == 415
    big = tree / "big.txt"
    big.write_text("x" * (2 * 1024 * 1024 + 1))
    assert client.get("/api/files/read", params={"path": str(big)}).status_code == 413


def test_path_escape_forbidden(client, tree, mx):
    outside = mx["tmp"] / "secret.txt"
    outside.write_text("nope")
    for p in (str(outside), str(tree / ".." / "secret.txt"), "/etc/passwd"):
        assert client.get("/api/files/read", params={"path": p}).status_code == 403
    os.symlink(outside, tree / "link.txt")
    assert client.get("/api/files/read", params={"path": str(tree / "link.txt")}).status_code == 403
    assert client.get("/api/files/read", params={"path": "relative.txt"}).status_code == 400
    assert client.post("/api/files/move", json={"from": str(tree / "b.txt"),
                                                "to": str(outside.with_name("x.txt"))}).status_code == 403


def test_write_conflict(client, tree):
    p = str(tree / "b.txt")
    m = client.get("/api/files/read", params={"path": p}).json()["mtime"]
    r = client.put("/api/files/write", json={"path": p, "content": "v2", "expected_mtime": m})
    assert r.status_code == 200 and r.json()["ok"]
    r2 = client.put("/api/files/write", json={"path": p, "content": "v3", "expected_mtime": m - 10})
    assert r2.status_code == 409 and r2.json()["error"] == "conflict"
    assert (tree / "b.txt").read_text() == "v2"
    assert client.put("/api/files/write", json={"path": str(tree / "new.md"), "content": "n"}).status_code == 200


def test_mkdir_move_delete(client, tree, mx):
    assert client.post("/api/files/mkdir", json={"path": str(tree / "x" / "y")}).json() == {"ok": True}
    assert client.post("/api/files/mkdir", json={"path": str(tree / "x")}).status_code == 409
    r = client.post("/api/files/move", json={"from": str(tree / "b.txt"), "to": str(tree / "x" / "c.txt")})
    assert r.json() == {"ok": True} and (tree / "x" / "c.txt").exists()
    assert client.post("/api/files/move", json={"from": str(tree / "x"),
                                                "to": str(tree / "x" / "y" / "z")}).status_code == 400
    assert client.post("/api/files/delete", json={"path": str(tree / "x")}).json() == {"ok": True}
    assert not (tree / "x").exists()
    trash = mx["state"] / "trash"
    sidecars = [p for p in trash.iterdir() if p.suffix == ".json"]
    assert sidecars and str(tree / "x") in sidecars[0].read_text()
    assert client.post("/api/files/delete", json={"path": str(tree)}).status_code == 403


def test_raw_and_range(client, tree):
    p = str(tree / "b.txt")
    r = client.get("/api/files/raw", params={"path": p})
    assert r.content == b"hello world" and "inline" in r.headers.get("content-disposition", "inline")
    r = client.get("/api/files/raw", params={"path": p}, headers={"Range": "bytes=0-4"})
    assert r.status_code == 206 and r.content == b"hello"
    r = client.get("/api/files/raw", params={"path": p, "download": 1})
    assert "attachment" in r.headers["content-disposition"]


def test_upload_and_search(client, tree, mx, topic):
    r = client.post("/api/files/upload", params={"dir": str(tree / "docs")},
                    files=[("file", ("up.txt", b"data", "text/plain"))])
    assert r.json()["files"][0]["path"] == str(tree / "docs" / "up.txt")
    hits = client.get("/api/files/search", params={"q": "blog"}).json()
    assert any(h["path"] == str(mx["ws"] / topic) and h["type"] == "dir" for h in hits)
    assert client.get("/api/files/search", params={"q": "memory.md"}).json()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_thumbnail(client, tree):
    img = tree / "pic.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=640x480", "-frames:v", "1",
                    str(img)], check=True)
    r = client.get("/api/files/thumb", params={"path": str(img), "w": 100})
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and r.content[:4] == b"RIFF"
    assert client.get("/api/files/thumb", params={"path": str(img), "w": 100}).content == r.content  # cached
    assert client.get("/api/files/thumb", params={"path": str(tree / "b.txt")}).status_code == 415
    # without a version the browser revalidates (a file rewritten under the same name), with one it keeps it
    assert r.headers["cache-control"] == "private, no-cache" and r.headers.get("etag")
    v = client.get("/api/files/thumb", params={"path": str(img), "w": 100, "v": "1"})
    assert "immutable" in v.headers["cache-control"]



@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_thumbnail_of_an_animated_png(client, tree):
    img = tree / "anim.png"                                  # APNG: ffmpeg's apng demuxer, not png_pipe
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=4:d=1", "-plays", "0",
                    "-f", "apng", str(img)], check=True)
    r = client.get("/api/files/thumb", params={"path": str(img), "w": 100})
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and r.content[:4] == b"RIFF"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_thumb_does_not_render_a_file_outside_the_root_through_ffconcat(client, mx):
    """A .png holding an ffconcat script + a link next to it: ffmpeg must not open the link target (outside the root),
    nor draw a text file as a picture (tty demuxer). Same for a video probed by ffprobe."""
    outside = mx["tmp"] / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text(("GITHUB_TOKEN=ghp_SECRET123 " * 3 + "\n") * 40)
    files = mx["files"]
    os.symlink(secret, files / "l.txt")
    (files / "note.png").write_text("ffconcat version 1.0\nfile l.txt\n")
    assert client.get("/api/files/raw", params={"path": str(files / "l.txt")}).status_code == 403
    r = client.get("/api/files/thumb", params={"path": str(files / "note.png"), "w": 640})
    assert not (r.status_code == 200 and r.headers["content-type"] == "image/webp" and r.content), "outside file drawn"
    clip = outside / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:d=1", str(clip)], check=True)
    os.symlink(clip, files / "l.mp4")
    (files / "fake.mp4").write_text("ffconcat version 1.0\nfile l.mp4\n")
    try:
        info = videos.probe(files / "fake.mp4")
    except videos.VideoError:
        info = {}
    assert not info.get("width"), info

def test_stat_gives_current_mtimes(client, tree, mx):
    f = tree / "pic.png"
    f.write_bytes(b"x")
    os.utime(f, (1000, 1000))
    paths = [str(f), str(tree / "nope.png"), "/etc/passwd", "relative"]
    r = client.post("/api/files/stat", json={"paths": paths})
    assert r.status_code == 200
    assert r.json()["mtimes"] == {str(f): 1000.0, str(tree / "nope.png"): None, "/etc/passwd": None, "relative": None}
    assert client.post("/api/files/stat", json={"paths": ["/x"] * 501}).status_code == 422


def test_raw_html_is_sandboxed(client, mx):
    f = mx["files"] / "evil.html"
    f.write_text("<script>alert(1)</script>")
    r = client.get("/api/files/raw", params={"path": str(f)})
    assert r.status_code == 200
    assert "sandbox" in r.headers.get("content-security-policy", "")
    assert r.headers.get("x-content-type-options") == "nosniff"


def _fake_ffmpeg(tmp, body: str):
    d = tmp / "bin"
    d.mkdir(exist_ok=True)
    f = d / "ffmpeg"
    f.write_text("#!/bin/sh\nfor a; do out=\"$a\"; done\n" + body)    # writes to its last argument
    f.chmod(0o755)
    return d


def test_thumb_timeout_does_not_keep_a_corrupt_thumbnail(client, mx, monkeypatch):
    from maxxing.api import files as F
    bindir = _fake_ffmpeg(mx["tmp"], "printf 'RIFF\\0\\0\\0\\0WEBPpartial' > \"$out\"\nsleep 30\n")
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setattr(F, "THUMB_TIMEOUT_S", 1)
    img = mx["files"] / "big.jpg"
    img.write_bytes(b"\xff\xd8" + b"0" * 1000)
    client.get("/api/files/thumb", params={"path": str(img), "w": 320})           # ffmpeg killed mid-write
    _fake_ffmpeg(mx["tmp"], "printf 'RIFF\\0\\0\\0\\0WEBPgood-full-image' > \"$out\"\n")
    r = client.get("/api/files/thumb", params={"path": str(img), "w": 320})
    assert b"good" in r.content, r.content


def test_thumb_concurrent_requests_never_serve_a_half_written_file(client, mx, monkeypatch):
    import threading
    import time
    bindir = _fake_ffmpeg(mx["tmp"], "printf 'RIFF' > \"$out\"\nsleep 1\nprintf 'WEBP-rest-of-image' >> \"$out\"\n")
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    img = mx["files"] / "photo.jpg"
    img.write_bytes(b"\xff\xd8" + b"0" * 1000)
    out = {}

    def first():
        out["a"] = client.get("/api/files/thumb", params={"path": str(img), "w": 320}).content

    t = threading.Thread(target=first)
    t.start()
    time.sleep(0.4)                                          # the first encoder is mid-write
    out["b"] = client.get("/api/files/thumb", params={"path": str(img), "w": 320}).content
    t.join()
    assert out == {"a": b"RIFFWEBP-rest-of-image", "b": b"RIFFWEBP-rest-of-image"}, out
    assert [f.name for f in (mx["state"] / "thumbs").glob("*.part.webp")] == []


def test_list_and_search_survive_a_non_utf8_name(client, mx):
    (mx["files"] / "ok.txt").write_text("x")
    open(os.fsencode(str(mx["files"])) + b"/caf\xe9.txt", "wb").close()      # Latin-1 name (zip, SMB copy)
    open(os.fsencode(str(mx["ws"])) + b"/rapport-\xe9t\xe9.txt", "wb").close()
    r = client.get("/api/files/list", params={"path": str(mx["files"])})
    assert r.status_code == 200, r.status_code
    assert {e["name"] for e in r.json()["entries"]} >= {"ok.txt", "caf\ufffd.txt"}
    r = client.get("/api/files/search", params={"q": "rapport"})
    assert r.status_code == 200, r.status_code
    assert [e["name"] for e in r.json()] == ["rapport-\ufffdt\ufffd.txt"]


def test_write_file_with_a_long_name(client, mx):
    p = mx["files"] / ("b" * 240 + ".md")                    # legal, but too long for a temp file named after it
    p.write_text("old")
    assert client.put("/api/files/write", json={"path": str(p), "content": "new"}).status_code == 200
    assert p.read_text() == "new" and [x.name for x in mx["files"].iterdir()] == [p.name]


def test_names_over_255_bytes_are_refused_not_500(client, tree):
    long = "é" * 130                                                # 260 bytes
    assert client.post("/api/files/mkdir", json={"path": str(tree / long)}).status_code == 400
    assert client.put("/api/files/write", json={"path": str(tree / long), "content": "x"}).status_code == 400
    (tree / "a.md").write_text("a")
    r = client.post("/api/files/move", json={"from": str(tree / "a.md"), "to": str(tree / long)})
    assert r.status_code == 400 and (tree / "a.md").exists()


def test_tar_listing_with_a_latin1_name(client, tree):
    import io
    import tarfile
    p = tree / "old.tar"
    with tarfile.open(p, "w", format=tarfile.GNU_FORMAT, encoding="latin-1") as tf:
        info = tarfile.TarInfo("caf\xe9.txt")
        info.size = 2
        tf.addfile(info, io.BytesIO(b"hi"))
    r = client.get("/api/files/archive", params={"path": str(p)})
    assert r.status_code == 200
    assert [e["name"] for e in r.json()["entries"]] == ["caf�.txt"]


def test_write_with_a_lone_surrogate_is_a_400(client, tree):
    p = tree / "s.md"
    p.write_text("before")
    r = client.put("/api/files/write", content='{"path": "%s", "content": "a\\ud800b"}' % p,
                   headers={"content-type": "application/json"})
    assert r.status_code == 400 and "bad_content" in r.text
    assert p.read_text() == "before" and not [x for x in tree.iterdir() if x.name.startswith(".mx-")]
