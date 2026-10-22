from __future__ import annotations

import shutil
import subprocess
import time

import pytest

from maxxing import videos

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


@pytest.fixture
def clip(mx):
    p = mx["files"] / "clip.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=960x540:r=25:d=1", "-f", "lavfi",
                    "-i", "sine=d=1", "-c:v", "mpeg4", "-shortest", str(p)], check=True)
    return p


def _wait(client, p, q, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        info = client.get("/api/files/video", params={"path": str(p)}).json()
        st = next(x for x in info["qualities"] if x["q"] == q)
        if st["state"] in ("ready", "error"):
            return st
        time.sleep(0.2)
    raise AssertionError("copy not made in time")


def test_info_prepare_and_stream(client, clip, mx):
    info = client.get("/api/files/video", params={"path": str(clip)}).json()
    assert (info["width"], info["height"], info["codec"]) == (960, 540, "mpeg4")
    assert [q["q"] for q in info["qualities"]] == [480] and info["qualities"][0]["state"] == "none"
    assert info["auto"] == 480                      # not H.264: Auto plays a copy
    assert client.get("/api/files/video/stream", params={"path": str(clip), "q": 480}).status_code == 404
    r = client.post("/api/files/video/prepare", json={"path": str(clip), "q": 480})
    assert r.status_code == 200 and r.json()["qualities"][0]["state"] in ("queued", "running", "ready")
    assert _wait(client, clip, 480)["state"] == "ready"
    r = client.get("/api/files/video/stream", params={"path": str(clip), "q": 480})
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    assert videos.probe(videos.variant_path(clip, 480))["codec"] == "h264"
    # fast start: the index (moov) comes before the data (mdat)
    assert r.content.find(b"moov") < r.content.find(b"mdat")
    r = client.get("/api/files/video/stream", params={"path": str(clip), "q": 480}, headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.content) == 10
    assert (mx["state"] / "videos").stat().st_mode & 0o077 == 0


def test_rejects_bad_requests(client, clip, mx):
    assert client.post("/api/files/video/prepare", json={"path": str(clip), "q": 1080}).status_code == 422
    txt = mx["files"] / "a.txt"
    txt.write_text("x")
    assert client.get("/api/files/video", params={"path": str(txt)}).status_code == 415
    assert client.get("/api/files/video", params={"path": str(mx["files"] / "none.mp4")}).status_code == 404
    assert client.get("/api/files/video", params={"path": "/etc/passwd.mp4"}).status_code in (403, 404)


def test_auto_keeps_light_originals():
    light = {"codec": "h264", "height": 1080, "bitrate": 4_000_000}
    assert videos.auto_quality(light) is None
    assert videos.auto_quality({**light, "height": 1440, "bitrate": 11_000_000}) == 720
    assert videos.auto_quality({**light, "codec": "av1"}) == 720
    assert videos.auto_quality({"codec": "hevc", "height": 360, "bitrate": 1}) is None   # nothing lighter


def test_cache_is_trimmed(mx, monkeypatch):
    d = videos.cache_dir()
    for i in range(3):
        (d / f"k{i}-480.mp4").write_bytes(b"x" * 100)
        time.sleep(0.01)
    monkeypatch.setattr(videos, "VIDEO_CACHE_MAX", 250)
    videos._trim_cache()
    assert sorted(f.name for f in d.glob("*.mp4")) == ["k1-480.mp4", "k2-480.mp4"]


def test_stale_part_files_are_cleaned(mx, monkeypatch):
    import os
    d = videos.cache_dir()
    old = time.time() - 7 * 86400
    stale, live, fresh = (d / f"{k}-720.part.mp4" for k in ("dead", "busy", "new"))
    for f in (stale, live, fresh):
        f.write_bytes(b"x" * 100)
    for f in (stale, live):
        os.utime(f, (old, old))
    monkeypatch.setitem(videos._jobs, "busy-720", {"state": "running", "progress": 0.5})
    videos._trim_cache()
    assert not stale.exists() and live.exists() and fresh.exists()   # a restart left it; still encoding; just started
