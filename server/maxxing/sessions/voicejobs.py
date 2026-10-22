"""Voice messages sent directly: the audio is queued at once like an attachment, transcribed here afterwards.

The web composer uploads the recording and sends it right away (POST /api/sessions/{id}/messages with
`voice`); the queue item carries `voice: [{id, path}]` and the session meta `voice_jobs[id]` tracks the
transcription: {state: pending|done|error, path, text, error, at}. Transcription runs in the server process
(the local model stays warm there) on one worker thread; the runner of the session waits for the result
before it shows the transcript and sends it to Claude (runner.Runner._voice). A server restart relaunches
the pending jobs (`resume()`, called at startup).
"""
from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from .. import bus, voice
from . import store, titles

log = logging.getLogger("maxxing.voicejobs")

STALE_S = 24 * 3600               # a job no runner consumed (session stopped, runner died) is dropped after this

_q: "queue.Queue[tuple[str, str, str]]" = queue.Queue()
_worker: threading.Thread | None = None
_lock = threading.Lock()


def new_job(meta: dict, path: str) -> dict:
    """Registers a pending job in `meta` (inside a store.edit) and returns the queue item entry {id, path}."""
    jid = f"v{time.time_ns():x}"
    meta.setdefault("voice_jobs", {})[jid] = {"state": "pending", "path": path, "at": time.time()}
    return {"id": jid, "path": path}


def submit(sid: str, jid: str, path: str) -> None:
    global _worker
    with _lock:                                    # same lock as the idle exit of _loop: a job never misses a worker
        _q.put((sid, jid, path))
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_loop, name="voice-jobs", daemon=True)
            _worker.start()


def _loop() -> None:
    global _worker
    while True:
        try:
            sid, jid, path = _q.get(timeout=60)
        except queue.Empty:
            with _lock:
                if not _q.empty():                 # a job came in while leaving: keep working
                    continue
                if _worker is threading.current_thread():
                    _worker = None                 # idle: the next submit starts a new worker
                return
        try:
            _run(sid, jid, path)
        except Exception:                          # never kill the worker
            log.exception("voice job %s/%s failed", sid, jid)


def _run(sid: str, jid: str, path: str) -> None:
    m = store.read(sid)
    if not m or ((m.get("voice_jobs") or {}).get(jid) or {}).get("state") != "pending":
        return                                     # session deleted, job dropped or already done
    _fix_duration(Path(path))
    try:
        out = voice.transcribe_file(Path(path))
        res = {"state": "done", "text": (out.get("text") or "").strip(), "engine": out.get("engine"),
               "duration_s": out.get("duration_s")}
    except voice.VoiceError as e:
        res = {"state": "error", "error": e.message}
    except Exception as e:
        log.exception("transcription failed for %s", path)
        res = {"state": "error", "error": f"transcription failed: {e}"[:300]}
    if store.read(sid) is None:
        return
    with store.edit(sid) as m:
        jobs = m.get("voice_jobs")
        if isinstance(jobs, dict) and isinstance(jobs.get(jid), dict):
            jobs[jid].update(res, at=time.time())
    if res.get("text"):
        titles.first_message(sid, res["text"])    # a session started by a voice message gets its title from it
    bus.invalidate("sessions")


def _fix_duration(src: Path) -> None:
    """Browsers record WebM without a duration (the player shows 0:00 and cannot seek): remux it once, in place."""
    ff = voice.ffmpeg_bin()
    if not ff or src.suffix.lower() != ".webm" or not src.is_file():
        return
    tmp = src.with_name(f".{src.name}.remux.webm")
    try:
        r = subprocess.run([ff, "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-c", "copy", str(tmp)],
                           capture_output=True, timeout=120)
        if r.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0:
            os.replace(tmp, src)
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        tmp.unlink(missing_ok=True)


def resume() -> int:
    """Startup: relaunch the jobs left pending by a restart, drop the stale ones. -> jobs relaunched."""
    n, now = 0, time.time()
    for sid in store.list_ids():
        m = store.read(sid)
        jobs = (m or {}).get("voice_jobs")
        if not isinstance(jobs, dict) or not jobs:
            continue
        stale = [j for j, v in jobs.items() if not isinstance(v, dict) or now - float(v.get("at") or 0) > STALE_S]
        if stale:
            with store.edit(sid) as mm:
                for j in stale:
                    (mm.get("voice_jobs") or {}).pop(j, None)
        for j, v in jobs.items():
            if j not in stale and v.get("state") == "pending" and v.get("path"):
                submit(sid, j, str(v["path"]))
                n += 1
    return n
