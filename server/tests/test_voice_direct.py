"""Voice messages sent directly: the audio is queued at once, transcribed by the server afterwards, and the
runner sends the transcript to Claude (mocked engine, fake claude, no model)."""
from __future__ import annotations

import json
import queue
import shutil
import threading
import time
from pathlib import Path

import pytest

from maxxing import voice
from maxxing.sessions import service, store, voicejobs
from tests.conftest import all_events, wait_for, wait_idle
from tests.test_voice import make_audio

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


@pytest.fixture
def engine(monkeypatch):
    """Fake local engine; `gate` holds the transcription until it is set, `reply` is what it hears."""
    st = {"gate": threading.Event(), "reply": "bonjour depuis le micro", "fail": None}
    st["gate"].set()

    def fake(wav: Path, lang: str, s: dict) -> dict:
        assert st["gate"].wait(20)
        if st["fail"]:
            raise voice.VoiceError(502, "engine_error", st["fail"])
        return {"text": st["reply"], "language": "fr", "model": s["model"]}

    monkeypatch.setitem(voice._ENGINES, "local", fake)
    monkeypatch.setattr(voice, "local_installed", lambda: True)
    return st


def _audio(tmp_path: Path, mx) -> str:
    folder = mx["ws"] / "projects" / "acme" / "topics" / "blog" / "attachments"
    folder.mkdir(parents=True, exist_ok=True)
    return str(make_audio(folder / "voice-1.webm", 1, ["-c:a", "libopus"]))


def test_settings_default_direct(client):
    s = client.get("/api/voice").json()["settings"]
    assert s["direct"] is True
    assert client.put("/api/voice/settings", json={"direct": False}).json()["settings"]["direct"] is False


def test_voice_message_sent_then_transcribed(client, topic, mx, tmp_path, engine):
    client.put("/api/voice/settings", json={"engine": "local"})
    audio = _audio(tmp_path, mx)
    sid = client.post("/api/sessions", json={"path": topic}).json()["id"]
    engine["gate"].clear()                                 # the transcription waits: the send returns at once
    t0 = time.time()
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "", "voice": audio})
    assert r.status_code == 200, r.text
    assert time.time() - t0 < 5
    # The runner shows the audio right away and waits for its transcript.
    wait_for(lambda: any(e["type"] == "user" and e.get("voice") == [audio] for e in all_events(client, sid)))
    assert not calls(mx)
    engine["gate"].set()
    wait_idle(client, sid)
    evs = all_events(client, sid)
    heard = [e for e in evs if e["type"] == "voice_text"]
    assert heard and heard[0]["text"] == "bonjour depuis le micro" and heard[0]["error"] is None
    prompt = calls(mx)[-1]["prompt"]
    assert "bonjour depuis le micro" in prompt and "Voice message" in prompt and audio in prompt
    assert "voice_jobs" not in (store.read(sid) or {})       # consumed
    # Telegram mirror / last message: the transcript is the text
    assert service.last_user_message(sid)["text"] == "bonjour depuis le micro"


def test_voice_message_new_session_and_queue_preview(client, topic, mx, tmp_path, engine):
    client.put("/api/voice/settings", json={"engine": "local"})
    audio = _audio(tmp_path, mx)
    sid = client.post("/api/sessions", json={"path": topic, "message": "PAUSE"}).json()["id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "", "voice": audio}).json()
    assert r["queued"] is True
    assert r["session"]["queue_items"][-1]["voice"] is True
    wait_idle(client, sid)
    assert "bonjour depuis le micro" in calls(mx)[-1]["prompt"]
    # A new session started with a voice message
    sid2 = client.post("/api/sessions", json={"path": topic, "voice": audio}).json()["id"]
    wait_idle(client, sid2)
    assert "bonjour depuis le micro" in calls(mx)[-1]["prompt"]


def test_voice_message_errors(client, topic, mx, tmp_path, engine):
    audio = _audio(tmp_path, mx)
    sid = client.post("/api/sessions", json={"path": topic}).json()["id"]
    r = client.post(f"/api/sessions/{sid}/messages", json={"voice": audio})
    assert r.status_code == 409 and r.json()["error"] == "voice_off"      # engine off
    client.put("/api/voice/settings", json={"engine": "local"})
    r = client.post(f"/api/sessions/{sid}/messages", json={"voice": "/nope/a.webm"})
    assert r.status_code == 400
    # The engine fails: the audio stays displayed, an error note, Claude is not called.
    engine["fail"] = "engine down"
    client.post(f"/api/sessions/{sid}/messages", json={"voice": audio})
    s = wait_idle(client, sid)
    evs = all_events(client, sid)
    assert any(e["type"] == "voice_text" and "engine down" in (e["error"] or "") for e in evs)
    assert any(e["type"] == "note" and e["level"] == "error" for e in evs)
    assert not calls(mx) and s["state"] == "error"
    # Nothing heard: same.
    engine["fail"], engine["reply"] = None, "  "
    client.post(f"/api/sessions/{sid}/messages", json={"voice": audio})
    wait_idle(client, sid)
    assert not calls(mx)


def test_take_queue_and_stop(client, topic, mx, tmp_path, engine):
    client.put("/api/voice/settings", json={"engine": "local"})
    audio = _audio(tmp_path, mx)
    sid = client.post("/api/sessions", json={"path": topic, "message": "SLOW"}).json()["id"]
    wait_for(lambda: client.get(f"/api/sessions/{sid}").json().get("state") == "running" and
             (store.read(sid) or {}).get("pid"))
    client.post(f"/api/sessions/{sid}/messages", json={"voice": audio})
    wait_for(lambda: ((store.read(sid) or {}).get("voice_jobs") or {}) and
             all(j["state"] == "done" for j in store.read(sid)["voice_jobs"].values()))
    r = client.post(f"/api/sessions/{sid}/queue/take").json()
    assert r["messages"] == [{"text": "bonjour depuis le micro", "attachments": []}]
    assert not (store.read(sid) or {}).get("voice_jobs")
    # Not transcribed yet: the audio comes back attached.
    engine["gate"].clear()
    client.post(f"/api/sessions/{sid}/messages", json={"voice": audio})
    r = client.post(f"/api/sessions/{sid}/queue/take").json()
    assert r["messages"] == [{"text": "", "attachments": [audio]}]
    engine["gate"].set()
    client.post(f"/api/sessions/{sid}/stop")
    wait_idle(client, sid)


def test_stop_while_waiting_for_the_transcript(client, topic, mx, tmp_path, engine):
    client.put("/api/voice/settings", json={"engine": "local"})
    audio = _audio(tmp_path, mx)
    sid = client.post("/api/sessions", json={"path": topic}).json()["id"]
    engine["gate"].clear()
    client.post(f"/api/sessions/{sid}/messages", json={"voice": audio})
    wait_for(lambda: any(e["type"] == "user" for e in all_events(client, sid)))
    client.post(f"/api/sessions/{sid}/stop")
    s = wait_idle(client, sid)
    engine["gate"].set()
    assert s["state"] == "idle" and not calls(mx)


def test_resume_after_restart(mx, monkeypatch):
    m = store.new_meta("acme/blog", "t")
    store.create(m)
    with store.edit(m["id"]) as mm:
        job = voicejobs.new_job(mm, "/tmp/a.webm")
        mm["voice_jobs"]["vold"] = {"state": "pending", "path": "/tmp/b.webm", "at": time.time() - 2 * 86400}
    seen = []
    monkeypatch.setattr(voicejobs, "submit", lambda sid, jid, path: seen.append((sid, jid, path)))
    assert voicejobs.resume() == 1
    assert seen == [(m["id"], job["id"], "/tmp/a.webm")]
    assert list(store.read(m["id"])["voice_jobs"]) == [job["id"]]


def test_steer_while_waiting_keeps_the_voice_message(client, topic, mx, tmp_path, engine):
    client.put("/api/voice/settings", json={"engine": "local"})
    audio = _audio(tmp_path, mx)
    sid = client.post("/api/sessions", json={"path": topic}).json()["id"]
    engine["gate"].clear()
    client.post(f"/api/sessions/{sid}/messages", json={"voice": audio})
    wait_for(lambda: any(e["type"] == "user" for e in all_events(client, sid)) and (store.read(sid) or {}).get("pid"))
    client.post(f"/api/sessions/{sid}/messages", json={"text": "and also this"})
    assert client.post(f"/api/sessions/{sid}/steer").status_code == 200
    time.sleep(1)
    engine["gate"].set()
    wait_idle(client, sid)
    prompts = [c["prompt"] for c in calls(mx)]
    assert "bonjour depuis le micro" in prompts[0] and "and also this" in prompts[-1]


def test_job_submitted_while_the_idle_worker_leaves_is_still_run(monkeypatch):
    in_exit, release, done = threading.Event(), threading.Event(), []

    class Q(queue.Queue):
        first = True

        def get(self, block=True, timeout=None):
            if self.first:                         # the 60 s idle timeout expires right now
                self.first = False
                in_exit.set()
                release.wait(5)
                raise queue.Empty
            return super().get(block, timeout=0.2)

    monkeypatch.setattr(voicejobs, "_q", Q())
    monkeypatch.setattr(voicejobs, "_run", lambda *a: done.append(a))
    t = threading.Thread(target=voicejobs._loop, daemon=True)
    monkeypatch.setattr(voicejobs, "_worker", t)
    t.start()
    assert in_exit.wait(5)
    voicejobs.submit("s", "j", "/x")               # the worker is still alive: no new one is started
    release.set()
    assert wait_for(lambda: done, timeout=5), "job stranded in the queue with no worker"
    assert done == [("s", "j", "/x")]
    t.join(5)
    assert not t.is_alive() and voicejobs._worker is None


def test_voice_path_outside_the_workspace_attachments_is_refused(client, topic, mx, tmp_path, engine):
    """The transcription remuxes the file in place: only a file under an attachments/ folder of the workspace."""
    client.put("/api/voice/settings", json={"engine": "local"})
    sid = client.post("/api/sessions", json={"path": topic}).json()["id"]
    outside = make_audio(tmp_path / "elsewhere.webm", 1, ["-c:a", "libopus"])
    before = outside.read_bytes()
    loose = mx["ws"] / "projects" / "acme" / "topics" / "blog" / "voice.webm"
    shutil.copy(outside, loose)
    link = mx["ws"] / "projects" / "acme" / "topics" / "blog" / "attachments" / "link.webm"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    for p in (outside, loose, link):
        r = client.post(f"/api/sessions/{sid}/messages", json={"voice": str(p)})
        assert r.status_code == 400 and r.json()["error"] == "bad_attachment", p
    r = client.post("/api/sessions", json={"path": topic, "voice": str(outside)})
    assert r.status_code == 400
    assert outside.read_bytes() == before
    assert not calls(mx)
