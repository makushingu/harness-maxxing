from __future__ import annotations

import os
import shutil
import subprocess
import threading
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
    assert info["has_audio"] is True and info["rotation"] == 0
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


def test_a_vertical_video_is_measured_by_its_short_side(client, mx):
    # a 9:16 video (540x960) is "540p": its copies keep the short side, not the height (a 480p copy is 480x854)
    tall = mx["files"] / "tall.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=540x960:r=25:d=1", "-c:v", "mpeg4",
                    str(tall)], check=True)
    info = client.get("/api/files/video", params={"path": str(tall)}).json()
    assert [q["q"] for q in info["qualities"]] == [480] and info["auto"] == 480
    assert client.post("/api/files/video/prepare", json={"path": str(tall), "q": 480}).status_code == 200
    assert _wait(client, tall, 480)["state"] == "ready"
    copy = videos.probe(videos.variant_path(tall, 480))
    assert (copy["width"], copy["height"]) == (480, 854)
    assert videos.variant_path(tall, 480).name.endswith("-480-r2-v.mp4")    # never an old height-scaled copy
    assert videos.auto_quality({"codec": "h264", "width": 1080, "height": 1920, "bitrate": 11_000_000}) == 720


def test_stream_keeps_its_etag_so_range_requests_stay_ranges(client, clip, mx):
    """Playing a copy touches its access time only: the ETag / Last-Modified of the next request are the same, so the
    browser's If-Range request gets its range (206), not the whole file again (200 = the playback restarts)."""
    client.post("/api/files/video/prepare", json={"path": str(clip), "q": 480})
    assert _wait(client, clip, 480)["state"] == "ready"
    f = videos.variant_path(clip, 480)
    import os
    os.utime(f, (time.time() - 7200, f.stat().st_mtime))
    params = {"path": str(clip), "q": 480}
    a = client.get("/api/files/video/stream", params=params, headers={"Range": "bytes=0-99"})
    time.sleep(0.02)
    b = client.get("/api/files/video/stream", params=params, headers={"Range": "bytes=100-199"})
    assert a.status_code == b.status_code == 206
    assert a.headers["etag"] == b.headers["etag"] and a.headers["last-modified"] == b.headers["last-modified"]
    c = client.get("/api/files/video/stream", params=params, headers={"Range": "bytes=200-299", "If-Range": a.headers["etag"]})
    assert c.status_code == 206 and len(c.content) == 100
    assert time.time() - f.stat().st_atime < 60              # still marked as recently played


def test_probe_tells_silent_clips(mx):
    p = mx["files"] / "silent.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x240:r=10:d=1", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(p)], check=True)
    info = videos.probe(p)
    assert info["has_audio"] is False and info["codec"] == "h264" and 0.5 < info["duration"] < 2


def test_rejects_bad_requests(client, clip, mx):
    assert client.post("/api/files/video/prepare", json={"path": str(clip), "q": 1080}).status_code == 422
    txt = mx["files"] / "a.txt"
    txt.write_text("x")
    assert client.get("/api/files/video", params={"path": str(txt)}).status_code == 415
    assert client.get("/api/files/video", params={"path": str(mx["files"] / "none.mp4")}).status_code == 404
    assert client.get("/api/files/video", params={"path": "/etc/passwd.mp4"}).status_code in (403, 404)


def test_auto_fallback_copy():
    light = {"codec": "h264", "height": 1080, "bitrate": 4_000_000}
    assert videos.auto_quality(light) is None
    assert videos.auto_quality({**light, "height": 1440, "bitrate": 11_000_000}) == 1080    # sharp: 1080p, not 720p
    assert videos.auto_quality({**light, "height": 2160, "codec": "hevc"}) == 1080
    assert videos.auto_quality({**light, "codec": "av1"}) == 720
    assert videos.auto_quality({**light, "bitrate": 9_000_000}) == 720
    assert videos.auto_quality({"codec": "hevc", "height": 360, "bitrate": 1}) is None   # nothing lighter
    assert videos.auto_quality({"codec": "hevc", "height": 600, "bitrate": 1}) == 480


def test_encoder_settings(tmp_path):
    cmd = videos.encode_args(tmp_path / "in.mov", 1080, tmp_path / "out.part.mp4")
    arg = lambda k: cmd[cmd.index(k) + 1]                                                   # noqa: E731
    assert (arg("-preset"), arg("-crf"), arg("-maxrate"), arg("-bufsize")) == ("faster", "20", "8M", "16M")
    cmd = videos.encode_args(tmp_path / "in.mov", 720, tmp_path / "out.part.mp4")
    assert (cmd[cmd.index("-maxrate") + 1], cmd[cmd.index("-bufsize") + 1]) == ("4M", "8M")
    cmd = videos.encode_args(tmp_path / "in.mov", 480, tmp_path / "out.part.mp4")
    assert (cmd[cmd.index("-maxrate") + 1], cmd[cmd.index("-bufsize") + 1]) == ("1500k", "3M")
    assert "-protocol_whitelist" in cmd and cmd[-1].endswith("out.part.mp4")


def test_cache_is_trimmed(mx, monkeypatch):
    import os
    d = videos.cache_dir()
    now = time.time()
    for i in range(3):
        f = d / f"k{i}-480.mp4"
        f.write_bytes(b"x" * 100)
        os.utime(f, (now - 7200 + i, now - 7200))           # played 2 h ago, oldest first
    monkeypatch.setattr(videos, "VIDEO_CACHE_MAX", 250)
    videos._trim_cache()
    assert sorted(f.name for f in d.glob("*.mp4")) == ["k1-480.mp4", "k2-480.mp4"]


def test_cache_keeps_copies_played_recently(mx, monkeypatch):
    import os
    d = videos.cache_dir()
    now = time.time()
    old, playing = d / "old-480.mp4", d / "playing-480.mp4"
    for f in (old, playing):
        f.write_bytes(b"x" * 100)
    os.utime(old, (now - 7200, now - 7200))
    os.utime(playing, (now - 60, now - 7200))               # played a minute ago (maybe still playing)
    monkeypatch.setattr(videos, "VIDEO_CACHE_MAX", 50)
    videos._trim_cache()
    assert not old.exists() and playing.exists()             # over the cap for a while rather than cut a playback


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


@pytest.mark.parametrize("body", ["sleep 60", "exec 1>&-; sleep 60"])   # stdout open, then closed
def test_a_hung_ffmpeg_is_killed_at_the_deadline(tmp_path, monkeypatch, body):
    pidf = tmp_path / "pid"
    monkeypatch.setattr(videos, "ENCODE_TIMEOUT_S", 1)
    monkeypatch.setattr(videos, "encode_args", lambda *a: ["sh", "-c", f"echo $$ > {pidf}; {body}"])
    src, dest = tmp_path / "in.mp4", tmp_path / "out.mp4"
    t = threading.Thread(target=videos._encode, args=(src, 480, dest, "k-hung", 10.0), daemon=True)
    start = time.monotonic()
    t.start()
    t.join(8)
    assert not t.is_alive() and time.monotonic() - start < 8
    assert videos._jobs.pop("k-hung")["state"] == "error"
    pid = int(pidf.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not dest.with_suffix(".part.mp4").exists()
