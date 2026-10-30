"""Lighter copies of videos for the player (see docs/dev/API.md#files).

A 1440p screen recording at 11 Mbit/s, an AV1 rush or a 500 MB export can play badly over a phone connection, and
some browsers do not decode every format (AV1 or HEVC on some, ProRes anywhere). The player plays the original
whenever the browser can decode it and asks for a lighter copy - H.264 + AAC at 1080p, 720p or 480p, "fast start"
(index first, it plays before the end has arrived) - only when the original cannot be decoded or struggles. Copies
are made here with ffmpeg, one at a time, at low priority, and kept in STATE/videos (the least recently played are
removed past VIDEO_CACHE_MAX, never one played in the last COPY_KEEP_S).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config

log = logging.getLogger("maxxing.videos")

QUALITIES = (1080, 720, 480)
# Sharp enough for screen recordings (text stays readable): crf 20 with a ceiling per height, buffer 2x the ceiling
MAXRATE = {1080: "8M", 720: "4M", 480: "1500k"}
BUFSIZE = {1080: "16M", 720: "8M", 480: "3M"}
ENCODE_PRESET = "faster"
ENCODE_CRF = "20"
COPY_REV = "r2"                        # in the copy's name: copies made with older settings are never served again
# The copy "Auto" falls back on: 1080p for an original above 1080p, else 720p for a heavy one (a codec not every
# browser plays, or more than 6 Mbit/s). Auto still plays the original first when the browser decodes it.
AUTO_TOP = 1080
LIGHT_CODECS = {"h264", "vp9", "vp8"}
LIGHT_HEIGHT = 1080
LIGHT_BITRATE = 6_000_000
VIDEO_CACHE_MAX = 4 * 1024**3
COPY_KEEP_S = 30 * 60                  # a copy played this recently is never removed (it may be playing right now)
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


def short_side(info: dict) -> int:
    """What "1080p" means: the short side, so a vertical 1080x1920 video is 1080p (its height is 1920)."""
    return min(info["width"], info["height"]) if info.get("width") else info["height"]


def _copy_key(ident: str, q: int, info: dict) -> str:
    # vertical copies were scaled by height until r2 (a "1080p" copy of a 9:16 video was 608 px wide): new names
    tall = 0 < info.get("width", 0) < info["height"]
    return f"{ident}-{q}-{COPY_REV}{'-v' if tall else ''}"


def variant_path(p: Path, q: int) -> Path:
    return cache_dir() / f"{_copy_key(_ident(p), q, probe(p))}.mp4"


# Demuxers ffmpeg/ffprobe may pick for a video (-format_whitelist): never concat, hls or tty, which open other files
# named in the content (a link to a file outside the files root included) or draw a text file as a picture
VIDEO_FORMATS = "mov,matroska,avi"


def _rotation(s: dict) -> int:
    """Quarter turns a player applies (phone videos are often stored sideways with a rotation flag)."""
    rot = 0
    for d in s.get("side_data_list") or []:
        if "rotation" in d:
            rot = d["rotation"]
    rot = rot or (s.get("tags") or {}).get("rotate") or 0
    try:
        return int(round(float(rot))) % 360
    except (TypeError, ValueError):
        return 0


def probe(p: Path) -> dict:
    """{width, height, codec, bitrate, duration, fps, has_audio, rotation} of the first video stream (cached per file
    version; `width` / `height` as coded, `rotation` 90 / 270 = shown sideways)."""
    key = _ident(p)
    with _lock:
        if key in _probes:
            return _probes[key]
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise VideoError("ffprobe is not installed")
    # every stream (not only v:0): an audio stream tells a short silent clip (played like a GIF) from a video
    r = subprocess.run([ffprobe, "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", VIDEO_FORMATS,
                        "-show_entries", "stream=codec_type,codec_name,width,height,avg_frame_rate,bit_rate:"
                        "stream_tags=rotate:stream_side_data=rotation:format=duration,bit_rate",
                        "-of", "json", str(p)], capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        data = {}
    streams = data.get("streams") or []
    s = next((x for x in streams if x.get("codec_type") == "video" and x.get("height")), {})
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
            "duration": float(fmt.get("duration") or 0), "fps": fps,
            "has_audio": any(x.get("codec_type") == "audio" for x in streams), "rotation": _rotation(s)}
    with _lock:
        if len(_probes) > 500:
            _probes.clear()
        _probes[key] = info
    return info


def offered(info: dict) -> list[int]:
    """Lighter qualities worth offering: below the original's short side."""
    return [q for q in QUALITIES if q < short_side(info)]


def auto_quality(info: dict) -> int | None:
    """The copy "Auto" falls back on when the browser cannot decode the original or it struggles: 1080p above 1080p,
    720p for a heavy original at most 1080p, None when the original is light enough for any browser (or nothing
    lighter exists)."""
    qs = offered(info)
    if short_side(info) > LIGHT_HEIGHT:
        return AUTO_TOP if AUTO_TOP in qs else (qs[0] if qs else None)
    if info["codec"] in LIGHT_CODECS and info["bitrate"] <= LIGHT_BITRATE:
        return None
    return 720 if 720 in qs else (qs[0] if qs else None)


def status(p: Path) -> dict:
    info = probe(p)
    ident = _ident(p)
    qualities = []
    for q in offered(info):
        key = _copy_key(ident, q, info)
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
        raise VideoError(f"no {q}p copy for a {short_side(info)}p video")
    if not shutil.which("ffmpeg"):
        raise VideoError("ffmpeg is not installed")
    key = _copy_key(_ident(p), q, info)
    dest = cache_dir() / f"{key}.mp4"
    with _lock:
        if not dest.exists() and _jobs.get(key, {}).get("state") not in ("queued", "running"):
            if sum(j.get("state") == "queued" for j in _jobs.values()) >= MAX_QUEUED:
                raise VideoError("Too many video copies are waiting - try again in a moment")
            _jobs[key] = {"state": "queued", "progress": 0.0}
            _pool.submit(_encode, p, q, dest, key, info["duration"])
    return status(p)


def encode_args(src: Path, q: int, part: Path) -> list[str]:
    """The ffmpeg command making the copy whose short side is `q` into `part` (ffmpeg rotates the frames first, so
    `iw` / `ih` are as shown)."""
    nice = shutil.which("nice")
    return [*([nice, "-n", "10"] if nice else []), shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-y",
            "-protocol_whitelist", "file", "-format_whitelist", VIDEO_FORMATS, "-i", str(src),
            "-map", "0:v:0", "-map", "0:a:0?", "-vf", f"scale='if(gt(iw,ih),-2,{q})':'if(gt(iw,ih),{q},-2)'", "-c:v", "libx264", "-preset", ENCODE_PRESET,
            "-crf", ENCODE_CRF, "-maxrate", MAXRATE[q], "-bufsize", BUFSIZE[q], "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", "-threads", "2",
            "-progress", "pipe:1", "-nostats", str(part)]


def _kill(proc: subprocess.Popen) -> None:
    """Kill ffmpeg's whole group (nice + ffmpeg, started in a session of their own) and reap it."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _encode(src: Path, q: int, dest: Path, key: str, duration: float) -> None:
    with _lock:
        _jobs[key] = {"state": "running", "progress": 0.0}
    part = dest.with_suffix(".part.mp4")
    cmd = encode_args(src, q, part)
    err = ""
    # stderr to a file, not a pipe: a broken source can print more than a pipe holds while we read stdout, and
    # ffmpeg would then wait for us forever (the one encode slot taken for hours)
    errf = tempfile.TemporaryFile(mode="w+")
    proc: subprocess.Popen | None = None
    timer: threading.Timer | None = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, text=True,
                                start_new_session=True)
        # the deadline runs from the start: a hung ffmpeg that keeps stdout open would block the loop below
        timer = threading.Timer(ENCODE_TIMEOUT_S, _kill, (proc,))
        timer.daemon = True
        timer.start()
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
        if proc.returncode == -signal.SIGKILL:
            err = f"ffmpeg took longer than {ENCODE_TIMEOUT_S} s"
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
        if timer is not None:
            timer.cancel()
        if proc is not None and proc.poll() is None:     # never leave it holding the encode slot's CPU
            _kill(proc)
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
    files = []
    for f in cache_dir().glob("*.mp4"):
        if f.name.endswith(".part.mp4"):
            continue
        try:
            files.append((f.stat(), f))
        except OSError:
            pass
    files.sort(key=lambda x: x[0].st_atime)              # GET /video/stream sets the atime (only): least recently played first
    total = sum(st.st_size for st, _ in files)
    recent = time.time() - COPY_KEEP_S
    for st, f in files:
        if total <= VIDEO_CACHE_MAX:
            break
        if st.st_atime > recent:                         # may be playing right now: over the cap for a while instead
            continue
        total -= st.st_size
        f.unlink(missing_ok=True)
