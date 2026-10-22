"""Lighter copies of videos for the player (see docs/dev/API.md#files).

A 1440p screen recording at 11 Mbit/s, an AV1 rush or a 500 MB export plays badly over a phone connection, and
some browsers (Safari) do not decode AV1 at all. The player can ask for a lighter copy - H.264 + AAC at 1080p,
720p or 480p, "fast start" (index first, it plays before the end has arrived) - made here with ffmpeg, one at a
time, at low priority, and kept in STATE/videos (the oldest are removed past VIDEO_CACHE_MAX).
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config

log = logging.getLogger("maxxing.videos")

QUALITIES = (1080, 720, 480)
MAXRATE = {1080: "5M", 720: "2500k", 480: "1200k"}
AUTO_Q = 720
# The original plays as it is when the browser can take it as it comes: H.264 / VP9, at most 1080p, at most 6 Mbit/s.
LIGHT_CODECS = {"h264", "vp9", "vp8"}
LIGHT_HEIGHT = 1080
LIGHT_BITRATE = 6_000_000
VIDEO_CACHE_MAX = 4 * 1024**3
PROBE_TIMEOUT_S = 15
ENCODE_TIMEOUT_S = 3 * 3600
PART_STALE_S = 3600                    # a copy in progress writes all the time: older is a dead one
MAX_QUEUED = 20                        # copies waiting behind the running one (one encode at a time)

_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mx-video")   # one encode at a time
_jobs: dict[str, dict] = {}            # cache key -> {state: queued|running|error, progress: 0-1, error}
_probes: dict[str, dict] = {}


class VideoError(Exception):
    pass


def _ident(p: Path) -> str:
    st = p.stat()
    return hashlib.sha1(f"{p}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()


def cache_dir() -> Path:
    d = config.state_dir("videos")
    d.chmod(0o700)
    return d


def variant_path(p: Path, q: int) -> Path:
    return cache_dir() / f"{_ident(p)}-{q}.mp4"


# Demuxers ffmpeg/ffprobe may pick for a video (-format_whitelist): never concat, hls or tty, which open other files
# named in the content (a link to a file outside the files root included) or draw a text file as a picture
VIDEO_FORMATS = "mov,matroska,avi"


def probe(p: Path) -> dict:
    """{width, height, codec, bitrate, duration, fps} of the first video stream (cached per file version)."""
    key = _ident(p)
    with _lock:
        if key in _probes:
            return _probes[key]
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise VideoError("ffprobe is not installed")
    r = subprocess.run([ffprobe, "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", VIDEO_FORMATS, "-select_streams", "v:0",
                        "-show_entries", "stream=codec_name,width,height,avg_frame_rate,bit_rate:format=duration,bit_rate",
                        "-of", "json", str(p)], capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        data = {}
    s = (data.get("streams") or [{}])[0]
    if not s.get("height"):
        raise VideoError("no video stream")
    fmt = data.get("format") or {}
    num, _, den = str(s.get("avg_frame_rate") or "0/1").partition("/")
    try:
        fps = round(float(num) / float(den or 1), 2)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    info = {"width": int(s.get("width") or 0), "height": int(s["height"]), "codec": s.get("codec_name") or "",
            "bitrate": int(fmt.get("bit_rate") or s.get("bit_rate") or 0),
            "duration": float(fmt.get("duration") or 0), "fps": fps}
    with _lock:
        if len(_probes) > 500:
            _probes.clear()
        _probes[key] = info
    return info


def offered(info: dict) -> list[int]:
    """Lighter heights worth offering: below the original's height."""
    return [q for q in QUALITIES if q < info["height"]]


def auto_quality(info: dict) -> int | None:
    """The copy "Auto" plays, or None when the original is light enough for any browser."""
    heavy = (info["codec"] not in LIGHT_CODECS or info["height"] > LIGHT_HEIGHT or info["bitrate"] > LIGHT_BITRATE)
    if not heavy:
        return None
    qs = offered(info)
    return AUTO_Q if AUTO_Q in qs else (qs[0] if qs else None)


def status(p: Path) -> dict:
    info = probe(p)
    ident = _ident(p)
    qualities = []
    for q in offered(info):
        key = f"{ident}-{q}"
        if (cache_dir() / f"{key}.mp4").exists():
            qualities.append({"q": q, "state": "ready", "progress": 1.0})
            continue
        with _lock:
            job = dict(_jobs.get(key) or {})
        qualities.append({"q": q, "state": job.get("state", "none"), "progress": round(job.get("progress", 0.0), 3),
                          **({"error": job["error"]} if job.get("error") else {})})
    return {**info, "qualities": qualities, "auto": auto_quality(info)}


def prepare(p: Path, q: int) -> dict:
    """Queue the copy at height `q` (no-op when it exists or is already queued)."""
    info = probe(p)
    if q not in offered(info):
        raise VideoError(f"no {q}p copy for a {info['height']}p video")
    if not shutil.which("ffmpeg"):
        raise VideoError("ffmpeg is not installed")
    key = f"{_ident(p)}-{q}"
    dest = cache_dir() / f"{key}.mp4"
    with _lock:
        if not dest.exists() and _jobs.get(key, {}).get("state") not in ("queued", "running"):
            if sum(j.get("state") == "queued" for j in _jobs.values()) >= MAX_QUEUED:
                raise VideoError("Too many video copies are waiting - try again in a moment")
            _jobs[key] = {"state": "queued", "progress": 0.0}
            _pool.submit(_encode, p, q, dest, key, info["duration"])
    return status(p)


def _encode(src: Path, q: int, dest: Path, key: str, duration: float) -> None:
    with _lock:
        _jobs[key] = {"state": "running", "progress": 0.0}
    part = dest.with_suffix(".part.mp4")
    rate = MAXRATE[q]
    nice = shutil.which("nice")
    cmd = [*([nice, "-n", "10"] if nice else []), shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-protocol_whitelist", "file", "-format_whitelist", VIDEO_FORMATS, "-i", str(src),
           "-map", "0:v:0", "-map", "0:a:0?", "-vf", f"scale=-2:{q}", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "23", "-maxrate", rate, "-bufsize", rate, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
           "-ac", "2", "-movflags", "+faststart", "-threads", "2", "-progress", "pipe:1", "-nostats", str(part)]
    err = ""
    # stderr to a file, not a pipe: a broken source can print more than a pipe holds while we read stdout, and
    # ffmpeg would then wait for us forever (the one encode slot taken for hours)
    errf = tempfile.TemporaryFile(mode="w+")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, text=True,
                                start_new_session=True)
        assert proc.stdout is not None
        for line in proc.stdout:                       # out_time_us=12345678 every ~0.5 s
            if line.startswith("out_time_us=") and duration > 0:
                try:
                    done = int(line.split("=", 1)[1]) / 1e6 / duration
                except ValueError:
                    continue
                with _lock:
                    _jobs[key]["progress"] = max(0.0, min(0.99, done))
        proc.wait(timeout=ENCODE_TIMEOUT_S)
        errf.seek(0)
        err = errf.read()[-300:]
        if proc.returncode == 0 and part.exists() and part.stat().st_size > 0:
            part.replace(dest)
            dest.chmod(0o600)
            with _lock:
                _jobs.pop(key, None)
            _trim_cache()
            return
    except Exception as e:                               # noqa: BLE001 - reported on the job
        err = str(e)
    finally:
        errf.close()
    part.unlink(missing_ok=True)
    log.warning("video copy %sp of %s failed: %s", q, src, err.strip())
    with _lock:
        _jobs[key] = {"state": "error", "progress": 0.0, "error": err.strip() or "ffmpeg failed"}


def _trim_cache() -> None:
    with _lock:
        running = {k for k, j in _jobs.items() if j.get("state") == "running"}
    for f in cache_dir().glob("*.part.mp4"):             # left by a restart in the middle of an encode
        try:
            if f.name[:-len(".part.mp4")] not in running and time.time() - f.stat().st_mtime > PART_STALE_S:
                f.unlink(missing_ok=True)
        except OSError:
            pass
    files = sorted((f for f in cache_dir().glob("*.mp4") if not f.name.endswith(".part.mp4")),
                   key=lambda f: f.stat().st_atime)
    total = sum(f.stat().st_size for f in files)
    while files and total > VIDEO_CACHE_MAX:
        f = files.pop(0)
        total -= f.stat().st_size
        f.unlink(missing_ok=True)
