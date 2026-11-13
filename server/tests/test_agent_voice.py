"""A voice message to an agent sent directly, as in a session: the recording goes at once into its conversation,
the server transcribes it (voicejobs) and the words fill the owner's message of the thread; the owner's pick of
model and effort for a new conversation (mocked engine, fake claude)."""
from __future__ import annotations

import shutil
import time

import pytest

from conftest import wait_for, wait_idle
from test_agents import A, _calls, _create, _on
from test_voice import make_audio
from test_voice_direct import engine  # noqa: F401 - fixture

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")

RUN = "/api/agents/acme/blog/writer/run"


def _thread(client) -> list[dict]:
    return client.get("/api/agents/acme/blog/writer/thread").json()["messages"]


def _audio(mx, name: str = "voice-1.webm") -> str:
    folder = mx["ws"] / A / "attachments"
    folder.mkdir(parents=True, exist_ok=True)
    return str(make_audio(folder / name, 1, ["-c:a", "libopus"]))


def test_a_voice_message_starts_the_conversation_then_its_words_fill_the_thread(client, topic, mx, engine):  # noqa: F811
    _on(client)
    _create(client, sandbox=False)
    client.put("/api/voice/settings", json={"engine": "local"})
    audio = _audio(mx)
    engine["gate"].clear()                                 # the transcription waits: the send returns at once
    t0 = time.time()
    r = client.post(RUN, json={"voice": audio, "model": "haiku", "effort": "high"})
    assert r.status_code == 200 and r.json()["started"], r.text
    assert time.time() - t0 < 5
    s = r.json()["session"]
    assert s["model"] == "haiku" and s["effort"] == "high"
    mine = [m for m in _thread(client) if m["kind"] == "run"][-1]
    assert mine["voice"] == [audio] and mine["text"] == "" and mine.get("owner")
    assert not _calls()
    engine["gate"].set()
    wait_idle(client, s["id"])
    prompt = _calls()[-1]["prompt"]
    assert "bonjour depuis le micro" in prompt and "Run your routine" not in prompt
    mine = wait_for(lambda: [m for m in _thread(client) if m["id"] == mine["id"] and m["text"]])[0]
    assert mine["text"] == "bonjour depuis le micro" and "voice_error" not in mine
    # the next one goes on in the same conversation
    audio2 = _audio(mx, "voice-2.webm")
    r = client.post(RUN, json={"voice": audio2}).json()
    assert r["continued"] and r["session"]["id"] == s["id"]
    wait_idle(client, s["id"])
    assert wait_for(lambda: [m for m in _thread(client) if audio2 in (m.get("voice") or []) and m["text"]])


def test_a_voice_message_nobody_heard_says_so_and_a_recording_from_elsewhere_is_refused(client, topic, mx, engine):  # noqa: F811
    _on(client)
    _create(client, sandbox=False)
    client.put("/api/voice/settings", json={"engine": "local"})
    engine["fail"] = "engine down"
    audio = _audio(mx)
    sid = client.post(RUN, json={"voice": audio}).json()["session"]["id"]
    wait_idle(client, sid)
    mine = wait_for(lambda: [m for m in _thread(client) if m.get("voice_error")])[0]
    assert "engine down" in mine["voice_error"] and mine["voice"] == [audio]
    outside = mx["ws"] / "projects" / "acme" / "topics" / "blog" / "attachments"
    outside.mkdir(parents=True, exist_ok=True)
    elsewhere = str(make_audio(outside / "v.webm", 1, ["-c:a", "libopus"]))
    r = client.post(RUN, json={"voice": elsewhere})
    assert r.status_code == 400 and r.json()["error"] == "bad_attachment"
