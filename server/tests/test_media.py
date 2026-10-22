from __future__ import annotations

import shutil
import subprocess

import pytest

from maxxing import media

from test_files import tree  # noqa: F401  (fixture)

ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@ffmpeg
def test_preview_heavy_vs_light_images(client, tree):  # noqa: F811
    big = tree / "big.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "mandelbrot=size=1600x1200", "-frames:v", "1", str(big)], check=True)
    small = tree / "small.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(small)], check=True)
    assert big.stat().st_size > 300 * 1024
    r = client.get("/api/files/preview", params={"path": str(big), "w": 800})
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and len(r.content) < big.stat().st_size / 4
    assert r.headers["cache-control"] == "private, no-cache"
    r = client.get("/api/files/preview", params={"path": str(small), "v": "123"})
    assert r.headers["content-type"] == "image/png" and r.content == small.read_bytes()
    assert "immutable" in r.headers["cache-control"]
    assert client.get("/api/files/preview", params={"path": str(tree / "b.txt")}).status_code == 415
    assert "immutable" in client.get("/api/files/raw", params={"path": str(small), "v": "1"}).headers["cache-control"]


def test_media_paths_and_warm_up(client, tree, monkeypatch):  # noqa: F811
    text = "Voici /root/a/shot.png, la vidéo (/root/a/clip.MP4) et `/root/b/c.webp`. Pas /root/a/notes.md ni http://x/y.png"
    assert media.media_paths(text) == ["/root/a/shot.png", "/root/a/clip.MP4", "/root/b/c.webp"]
    done = []
    monkeypatch.setattr(media, "_warm_one", lambda p: done.append(p))
    monkeypatch.setattr(media._pool, "submit", lambda fn, p: fn(p))
    media._seen.clear()
    media.warm_events([{"type": "assistant", "text": text}, {"type": "user", "text": "", "attachments": ["/root/a/up.jpg", "/root/a/x.pdf"]},
                       {"type": "assistant", "text": "/root/a/shot.png again"}])
    assert done == ["/root/a/shot.png", "/root/a/clip.MP4", "/root/b/c.webp", "/root/a/up.jpg"]   # once each


@ffmpeg
def test_warm_one_prepares_thumbnails(client, tree):  # noqa: F811
    from maxxing import config
    big = tree / "big2.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "mandelbrot=size=1600x1200", "-frames:v", "1", str(big)], check=True)
    before = len(list(config.state_dir("thumbs").glob("*.webp")))
    media._warm_one(str(big))
    assert len(list(config.state_dir("thumbs").glob("*.webp"))) == before + 3     # 160, 320, preview
