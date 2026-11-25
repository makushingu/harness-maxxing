"""Voice messages: settings/status API, ffmpeg normalisation, mocked engines (local + HTTP APIs),
install job, Telegram voice-note flow. No model, no network."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import httpx
import pytest

from maxxing import config, vault, voice

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def make_audio(path: Path, seconds: float = 1.5, codec: list[str] | None = None) -> Path:
    """A short tone encoded like a browser / Telegram would (webm/opus, ogg/opus, m4a…)."""
    codec = codec or []
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={seconds}:sample_rate=48000", "-ac", "2", *codec, str(path)],
                   check=True)
    return path


@pytest.fixture
def fake_engine(monkeypatch):
    calls: list[dict] = []

    def engine(wav: Path, lang: str, s: dict) -> dict:
        with wave.open(str(wav), "rb") as w:
            calls.append({"rate": w.getframerate(), "channels": w.getnchannels(), "lang": lang, "model": s["model"]})
        return {"text": "hello from the fake engine", "language": "en" if lang == "auto" else lang, "model": s["model"]}

    monkeypatch.setitem(voice._ENGINES, "local", engine)
    monkeypatch.setattr(voice, "local_installed", lambda: True)
    return calls


# ---- normalisation --------------------------------------------------------------------------
@pytest.mark.parametrize("name,codec", [("a.webm", ["-c:a", "libopus"]), ("a.ogg", ["-c:a", "libopus"]),
                                        ("a.m4a", ["-c:a", "aac"]), ("a.mp3", []), ("a.wav", [])])
def test_normalise_formats(mx, tmp_path, name, codec):
    src = make_audio(tmp_path / name, 1.2, codec)
    dur = voice.normalise(src, tmp_path / "out.wav")
    assert 1.0 < dur < 1.5
    with wave.open(str(tmp_path / "out.wav"), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)


def test_normalise_errors(mx, tmp_path):
    bad = tmp_path / "x.webm"
    bad.write_bytes(b"not audio at all")
    with pytest.raises(voice.VoiceError) as e:
        voice.normalise(bad, tmp_path / "o.wav")
    assert e.value.code == "bad_audio" and e.value.status == 422
    long = make_audio(tmp_path / "long.wav", 3)
    with pytest.raises(voice.VoiceError) as e:
        voice.normalise(long, tmp_path / "o2.wav", max_seconds=2)
    assert e.value.code == "too_long" and e.value.status == 413


def test_a_burst_of_voice_notes_runs_at_most_two_conversions_at_once(mx, tmp_path, monkeypatch):
    import threading
    running, peak, lock = [0], [0], threading.Lock()

    def run(cmd, **kw):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1
        return subprocess.CompletedProcess(cmd, 1, "", "boom")

    monkeypatch.setattr(voice, "ffmpeg_bin", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(voice.subprocess, "run", run)
    errors = []

    def one(i):
        try:
            voice.normalise(tmp_path / f"{i}.webm", tmp_path / f"{i}.wav")
        except voice.VoiceError as e:
            errors.append(e.code)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == ["bad_audio"] * 20 and peak[0] <= 2


# ---- settings & status ----------------------------------------------------------------------
def test_status_defaults_and_settings(client, monkeypatch):
    monkeypatch.setattr(voice, "ram_gb", lambda: 2.0)
    s = client.get("/api/voice").json()
    assert s["settings"] == {"engine": "off", "model": "base", "language": "auto", "auto_send": False, "direct": True,
                             "mic": True, "call": True}
    assert s["ready"] is False and s["reason"] == "off" and s["ffmpeg"] is True
    assert s["local"]["recommended"] == "base" and [m["id"] for m in s["local"]["models"]] == list(voice.MODELS)
    assert s["keys"] == {"groq": False, "openai": False} and s["install"]["state"] == "idle"
    monkeypatch.setattr(voice, "ram_gb", lambda: 8.0)
    assert client.get("/api/voice").json()["settings"]["model"] == "small"

    r = client.put("/api/voice/settings", json={"engine": "groq", "model": "tiny", "language": "FR", "auto_send": True})
    assert r.status_code == 200, r.text
    assert r.json()["settings"] == {"engine": "groq", "model": "tiny", "language": "fr", "auto_send": True, "direct": True,
                                     "mic": True, "call": True}
    assert config.load_config()["voice"]["engine"] == "groq"
    s = client.get("/api/voice").json()
    assert s["ready"] is False and s["reason"] == "no_key"
    vault.put("GROQ_API_KEY", "gsk_test_123456")
    s = client.get("/api/voice").json()
    assert s["ready"] is True and s["keys"]["groq"] is True
    assert client.put("/api/voice/settings", json={"engine": "nope"}).status_code == 422
    # the buttons of the message boxes can be hidden
    s = client.put("/api/voice/settings", json={"mic": False, "call": False}).json()["settings"]
    assert s["mic"] is False and s["call"] is False and s["engine"] == "groq"
    assert client.put("/api/voice/settings", json={"language": "french!"}).json()["error"] == "invalid_language"


# ---- transcribe -----------------------------------------------------------------------------
def test_transcribe_off_and_not_installed(client, tmp_path, monkeypatch):
    audio = make_audio(tmp_path / "a.webm", 1, ["-c:a", "libopus"])
    r = client.post("/api/voice/transcribe", files={"audio": ("a.webm", audio.read_bytes(), "audio/webm")})
    assert r.status_code == 409 and r.json()["error"] == "voice_off"
    client.put("/api/voice/settings", json={"engine": "local"})
    monkeypatch.setattr(voice, "local_installed", lambda: False)
    r = client.post("/api/voice/transcribe", files={"audio": ("a.webm", audio.read_bytes(), "audio/webm")})
    assert r.status_code == 503 and r.json()["error"] == "not_installed"


def test_transcribe_local_mocked_and_keep_audio(client, topic, mx, tmp_path, fake_engine):
    client.put("/api/voice/settings", json={"engine": "local", "model": "base"})
    audio = make_audio(tmp_path / "rec.webm", 1.5, ["-c:a", "libopus"])
    r = client.post("/api/voice/transcribe", files={"audio": ("blob", audio.read_bytes(), "audio/webm;codecs=opus")})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["text"] == "hello from the fake engine" and j["engine"] == "local" and j["model"] == "base"
    assert j["language"] == "en" and 1.3 < j["duration_s"] < 1.7 and j["ms"] >= 0 and j["audio_path"] is None
    assert fake_engine[0] == {"rate": 16000, "channels": 1, "lang": "auto", "model": "base"}
    # keep the audio in the topic + forced language
    r = client.post("/api/voice/transcribe", data={"path": topic, "language": "fr"},
                    files={"audio": ("rec.webm", audio.read_bytes(), "audio/webm")})
    j = r.json()
    assert j["language"] == "fr" and fake_engine[-1]["lang"] == "fr"
    kept = Path(j["audio_path"])
    assert kept.is_file() and kept.suffix == ".webm"
    assert f"/{topic}/attachments/voice/{time.strftime('%Y-%m')}/voice-" in str(kept)
    assert not list((mx["state"] / "voice" / "tmp").iterdir())            # temp files cleaned
    # unreadable upload
    r = client.post("/api/voice/transcribe", files={"audio": ("x.webm", b"garbage", "audio/webm")})
    assert r.status_code == 422 and r.json()["error"] == "bad_audio"
    r = client.post("/api/voice/transcribe", data={"path": "../etc"},
                    files={"audio": ("rec.webm", audio.read_bytes(), "audio/webm")})
    assert r.status_code == 400


# ---- API engines (httpx MockTransport) ------------------------------------------------------
@pytest.mark.parametrize("engine,key,expected_model", [("groq", "GROQ_API_KEY", "whisper-large-v3-turbo"),
                                                       ("openai", "OPENAI_API_KEY", "gpt-4o-mini-transcribe")])
def test_api_engines(mx, tmp_path, monkeypatch, engine, key, expected_model):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.headers["authorization"] != "Bearer secret-key-123":
            return httpx.Response(401, json={"error": {"message": "bad key"}})
        body = req.content
        assert b'name="model"' in body and expected_model.encode() in body and b"OggS" in body
        if expected_model.startswith("whisper"):
            return httpx.Response(200, json={"text": " Bonjour tout le monde ", "language": "french", "duration": 1.5})
        return httpx.Response(200, json={"text": "Bonjour tout le monde"})

    monkeypatch.setattr(voice, "http_transport", httpx.MockTransport(handler))
    monkeypatch.setenv(f"MAXXING_{engine.upper()}_API", "https://mock.example.com/v1")
    voice.update_settings(engine=engine)
    vault.put(key, "secret-key-123")
    audio = make_audio(tmp_path / "v.ogg", 1.5, ["-c:a", "libopus"])
    out = voice.transcribe_file(audio)
    assert out["text"] == "Bonjour tout le monde" and out["engine"] == engine and out["model"] == expected_model
    assert str(seen[0].url) == "https://mock.example.com/v1/audio/transcriptions"
    if engine == "groq":
        assert out["language"] == "fr"
    vault.put(key, "wrong-key-0000")
    with pytest.raises(voice.VoiceError) as e:
        voice.transcribe_file(audio)
    assert e.value.code == "bad_key"



def test_a_pasted_key_is_trimmed_and_never_shown_in_an_engine_error(mx, tmp_path, monkeypatch):
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.headers["authorization"])
        raise httpx.LocalProtocolError(f"Illegal header value b'{req.headers['authorization']}'")

    monkeypatch.setattr(voice, "http_transport", httpx.MockTransport(handler))
    voice.update_settings(engine="groq")
    vault.put("GROQ_API_KEY", "gsk_SECRET1234567890\n")
    with pytest.raises(voice.VoiceError) as e:
        voice.transcribe_file(make_audio(tmp_path / "v.ogg", 1.5, ["-c:a", "libopus"]))
    assert seen == ["Bearer gsk_SECRET1234567890"]
    assert e.value.code == "engine_error" and "gsk_SECRET" not in str(e.value) and "***" in str(e.value)


@pytest.mark.parametrize("answer", [["not", "an", "object"], None, "text", {"text": ["a"]}])
def test_an_engine_answer_that_is_not_an_object_is_an_engine_error(mx, tmp_path, monkeypatch, answer):
    monkeypatch.setattr(voice, "http_transport", httpx.MockTransport(lambda req: httpx.Response(200, json=answer)))
    voice.update_settings(engine="groq")
    vault.put("GROQ_API_KEY", "secret-key-123")
    with pytest.raises(voice.VoiceError) as e:
        voice.transcribe_file(make_audio(tmp_path / "v.ogg", 1.5, ["-c:a", "libopus"]))
    assert e.value.status == 502 and e.value.code == "engine_error"


def test_a_stuck_opus_conversion_falls_back_to_wav(mx, tmp_path, monkeypatch):
    wav = make_audio(tmp_path / "v.wav", 1.5, [])
    real = subprocess.run

    def run(args, *a, **kw):
        if "libopus" in args:
            raise subprocess.TimeoutExpired(args, 180)
        return real(args, *a, **kw)

    monkeypatch.setattr(voice.subprocess, "run", run)
    assert voice._to_ogg(wav, tmp_path / "v.ogg") == wav

# ---- install job ----------------------------------------------------------------------------
def test_install_job(client, mx, monkeypatch):
    state = {"installed": False}
    monkeypatch.setattr(voice, "local_installed", lambda: state["installed"])

    def deps():
        time.sleep(0.2)
        state["installed"] = True

    def model(name):
        d = voice.model_path(name)
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text("{}")
        (d / "model.bin").write_bytes(b"x" * 1000)

    monkeypatch.setitem(voice.install_steps, "deps", deps)
    monkeypatch.setitem(voice.install_steps, "model", model)
    r = client.post("/api/voice/install", json={"model": "tiny"})
    assert r.status_code == 200 and r.json()["state"] == "running" and r.json()["model"] == "tiny"
    assert client.post("/api/voice/install", json={}).json()["error"] == "busy"
    deadline = time.time() + 5
    while client.get("/api/voice").json()["install"]["state"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    s = client.get("/api/voice").json()
    assert s["install"]["state"] == "done" and s["local"]["installed"] is True
    assert next(m for m in s["local"]["models"] if m["id"] == "tiny")["present"] is True
    assert voice.sync_extras() == ["--extra", "voice"]                      # `maxxing update` keeps it
    assert client.delete("/api/voice/models/tiny").json() == {"ok": True}
    assert not voice.model_present("tiny")


def test_install_failure_reported(client, monkeypatch):
    monkeypatch.setattr(voice, "local_installed", lambda: False)

    def boom():
        raise voice.VoiceError(502, "install_failed", "no network")

    monkeypatch.setitem(voice.install_steps, "deps", boom)
    client.post("/api/voice/install", json={})
    deadline = time.time() + 5
    while voice.install_state()["state"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    assert voice.install_state()["state"] == "error" and voice.install_state()["error"] == "no network"


def test_doctor(mx, monkeypatch):
    assert voice.doctor()[0] == "info"
    voice.update_settings(engine="local", model="tiny")
    monkeypatch.setattr(voice, "local_installed", lambda: False)
    assert voice.doctor()[0] == "warn" and "not_installed" in voice.doctor()[1]
    monkeypatch.setattr(voice, "local_installed", lambda: True)
    assert "not downloaded" in voice.doctor()[1]


# ---- Telegram voice notes -------------------------------------------------------------------
from _conn_helpers import TG_TOKEN, FakeService, FakeTelegram, FakeWorkspace, bare_app, wait_for, mx_state  # noqa: E402,F401
from maxxing.api import telegram as tg_api  # noqa: E402
from maxxing.telegram import gateway  # noqa: E402

TOPIC = "projects/acme/topics/blog"


@pytest.fixture
async def tgenv(mx_state, monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setenv("MAXXING_TELEGRAM_API", fake.url)
    svc = FakeService()
    monkeypatch.setitem(sys.modules, "maxxing.sessions.service", svc)
    ws = FakeWorkspace(mx_state / "ws", [("acme", "blog")])
    monkeypatch.setitem(sys.modules, "maxxing.workspace", ws)
    monkeypatch.setattr(gateway, "_hooks", False)
    app = bare_app(tg_api.router)
    await tg_api.startup()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/telegram/token", json={"token": TG_TOKEN})
        assert r.status_code == 200, r.text
        code = (await c.post("/api/telegram/link")).json()["code"]
        fake.message(f"/start {code}")
        await wait_for(lambda: gateway.link_status()["linked"], what="link")
        await wait_for(lambda: len(gateway.tg_config().get("threads") or {}) >= 3, what="threads")    # Crons, Alerts, Notifications
        svc.create_session(TOPIC, title="Voice", source="web")
        assert (await c.post("/api/telegram/sync")).status_code == 200
        yield fake, svc
    await tg_api.shutdown()
    fake.close()


async def test_telegram_voice_note_flow(tgenv, tmp_path, monkeypatch):
    fake, svc = tgenv
    thread = gateway.thread_of(next(iter(svc.sessions)))
    ogg = make_audio(tmp_path / "v.ogg", 1.2, ["-c:a", "libopus"])
    fake.add_file("VOICE1", ogg.read_bytes(), "voice/file_3.oga")

    # engine off -> hint, nothing sent to Claude
    fake.message("", thread=thread, voice={"file_id": "VOICE1", "duration": 1, "mime_type": "audio/ogg"})
    await wait_for(lambda: any("Settings → Voice" in p["text"] for p in fake.sent()), what="off hint")
    assert svc.sent == []

    # engine on (mocked) -> transcript echoed in the thread, then sent as the user message
    monkeypatch.setitem(voice._ENGINES, "local",
                        lambda wav, lang, s: {"text": "Write the plan for tomorrow", "language": "en", "model": "base"})
    monkeypatch.setattr(voice, "local_installed", lambda: True)
    voice.update_settings(engine="local")
    fake.message("", thread=thread, voice={"file_id": "VOICE1", "duration": 1, "mime_type": "audio/ogg"})
    await wait_for(lambda: svc.sent, what="voice turn")
    echo = next(p for p in fake.sent() if p["text"].startswith("🎤 <blockquote>"))
    assert echo["message_thread_id"] == thread and "<i>Write the plan for tomorrow</i>" in echo["text"]
    sent = svc.sent[0]
    assert sent["text"] == "Write the plan for tomorrow" and sent["source"] == "telegram"
    att = sent["attachments"][0]
    assert f"/{TOPIC}/attachments/voice/" in att and att.endswith(".ogg") and Path(att).is_file()

    # video note + caption-less audio file both go through the same path
    fake.add_file("ROUND1", ogg.read_bytes(), "video_notes/file_4.mp4")
    fake.message("", thread=thread, video_note={"file_id": "ROUND1", "duration": 1, "length": 240})
    await wait_for(lambda: len(svc.sent) == 2, what="video note turn")
    assert svc.sent[1]["text"] == "Write the plan for tomorrow"

    # silence -> no turn, short reply
    monkeypatch.setitem(voice._ENGINES, "local", lambda wav, lang, s: {"text": "", "language": None, "model": "base"})
    fake.message("", thread=thread, voice={"file_id": "VOICE1", "duration": 1})
    await wait_for(lambda: any("could not hear" in p["text"] for p in fake.sent()), what="no speech")
    assert len(svc.sent) == 2

    # engine error -> warning, no turn
    def boom(wav, lang, s):
        raise voice.VoiceError(502, "engine_error", "groq error 500")
    monkeypatch.setitem(voice._ENGINES, "local", boom)
    fake.message("", thread=thread, voice={"file_id": "VOICE1", "duration": 1})
    await wait_for(lambda: any("Transcription failed: groq error 500" in p["text"] for p in fake.sent()), what="error")
    assert len(svc.sent) == 2
    json.dumps(fake.sent())                                                  # all payloads serialisable


def test_faster_whisper_can_decode_audio(tmp_path):
    """Real decoding with the installed faster-whisper + PyAV pair (PyAV 19 broke faster-whisper 1.2)."""
    import wave
    audio = pytest.importorskip("faster_whisper.audio")
    p = tmp_path / "tone.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x01" * 16000)
    samples = audio.decode_audio(str(p))
    assert len(samples) == 16000


@pytest.mark.parametrize("lang", ["éé", "日本"])
def test_a_non_ascii_language_is_refused(client, lang):
    r = client.put("/api/voice/settings", json={"language": lang})
    assert r.status_code == 400 and r.json()["error"] == "invalid_language"


def test_a_key_with_a_non_ascii_character_is_a_no_key_error(mx, tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "http_transport", httpx.MockTransport(lambda req: httpx.Response(200, json={"text": "hi"})))
    voice.update_settings(engine="groq")
    vault.put("GROQ_API_KEY", "gsk_abc’def")
    with pytest.raises(voice.VoiceError) as e:
        voice.transcribe_file(make_audio(tmp_path / "v.ogg", 1.5, ["-c:a", "libopus"]))
    assert e.value.status == 503 and e.value.code == "no_key" and "gsk_abc" not in str(e.value)


def test_the_model_download_uses_the_pinned_revision(mx, monkeypatch):
    from maxxing import deps
    seen: list[list[str]] = []

    def run(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(voice.subprocess, "run", run)
    monkeypatch.setattr(voice, "model_present", lambda name: bool(seen))      # there once downloaded
    voice._download_subprocess("tiny")
    pinned = deps.get("whisper")["revisions"]["tiny"]
    assert seen[0][-1] == pinned and "revision=sys.argv[3]" in seen[0][2]


def test_a_slash_path_never_keeps_the_audio_at_the_workspace_root(client, mx, tmp_path, fake_engine):
    client.put("/api/voice/settings", json={"engine": "local", "model": "base"})
    audio = make_audio(tmp_path / "rec.webm", 1.0, ["-c:a", "libopus"])
    r = client.post("/api/voice/transcribe", data={"path": "/"},
                    files={"audio": ("rec.webm", audio.read_bytes(), "audio/webm")})
    assert r.status_code == 400 and r.json()["error"] == "bad_path"
    from maxxing import workspace
    assert not (workspace.root() / "attachments").exists()


def test_two_recordings_kept_in_the_same_second_get_two_files(topic, mx, tmp_path, monkeypatch):
    import threading
    from maxxing.api import voice as api_voice
    barrier, real_exists = threading.Barrier(2, timeout=1), Path.exists

    def exists(self, *a, **k):                         # both requests check the name before either writes
        if self.name.startswith("voice-"):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return real_exists(self, *a, **k)

    monkeypatch.setattr(Path, "exists", exists)
    srcs = []
    for body in (b"AAAA", b"BBBB"):
        srcs.append(tmp_path / f"in-{body.decode()}.webm")
        srcs[-1].write_bytes(body)
    out: list[str] = []
    ts = [threading.Thread(target=lambda s=s: out.append(api_voice._keep(s, topic, ".webm"))) for s in srcs]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(set(out)) == 2 and sorted(Path(p).read_bytes() for p in out) == [b"AAAA", b"BBBB"]


def test_deleting_a_model_being_installed_is_refused(client, mx, monkeypatch):
    import threading
    monkeypatch.setattr(voice, "local_installed", lambda: True)
    go = threading.Event()

    def model(name):
        go.wait(5)
        d = voice.model_path(name)
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text("{}")
        (d / "model.bin").write_bytes(b"x")

    monkeypatch.setitem(voice.install_steps, "model", model)
    assert client.post("/api/voice/install", json={"model": "tiny"}).json()["state"] == "running"
    r = client.delete("/api/voice/models/tiny")
    go.set()
    assert r.status_code == 409 and r.json()["error"] == "busy"
    deadline = time.time() + 5
    while voice.install_state()["state"] == "running" and time.time() < deadline:
        time.sleep(0.05)
    assert voice.install_state()["state"] == "done" and voice.model_present("tiny")


def _fake_downloader(monkeypatch, download):
    import types
    monkeypatch.setattr(voice, "local_installed", lambda: True)
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", types.SimpleNamespace(download_model=download))


def test_a_half_downloaded_model_is_not_seen_as_installed(mx, monkeypatch):
    def download(name, output_dir, revision=None):
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "config.json").write_text("{}")
        (Path(output_dir) / "model.bin").write_bytes(b"half")
        raise OSError("connection reset")

    _fake_downloader(monkeypatch, download)
    with pytest.raises(OSError):
        voice.download_model("tiny")
    assert not voice.model_present("tiny")


def test_a_model_is_downloaded_once_when_two_ask_for_it(mx, monkeypatch):
    import threading
    calls, live, peak = [], [0], [0]

    def download(name, output_dir, revision=None):
        calls.append(output_dir)
        live[0] += 1
        peak[0] = max(peak[0], live[0])
        time.sleep(0.3)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "config.json").write_text("{}")
        (Path(output_dir) / "model.bin").write_bytes(b"full")
        live[0] -= 1

    _fake_downloader(monkeypatch, download)
    ts = [threading.Thread(target=voice.download_model, args=("tiny",)) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(calls) == 1 and peak[0] == 1 and voice.model_present("tiny")


def test_a_bad_topic_path_is_refused_before_the_transcription(client, mx, tmp_path, fake_engine):
    client.put("/api/voice/settings", json={"engine": "local", "model": "base"})
    audio = make_audio(tmp_path / "rec.webm", 1.0, ["-c:a", "libopus"])
    r = client.post("/api/voice/transcribe", data={"path": "projects/nope/topics/x"},
                    files={"audio": ("rec.webm", audio.read_bytes(), "audio/webm")})
    assert r.status_code == 400 and r.json()["error"] == "bad_path"
    assert fake_engine == []                               # the transcriber (paid in the cloud) was never called


def test_changing_the_model_does_not_wait_for_a_download(mx, monkeypatch):
    import threading
    started, release = threading.Event(), threading.Event()

    def slow_download(name):
        started.set()
        release.wait(10)
        raise voice.VoiceError(502, "download_failed", "test")

    monkeypatch.setattr(voice, "download_model", slow_download)
    t = threading.Thread(target=lambda: pytest.raises(voice.VoiceError, voice._load, "tiny"), daemon=True)
    t.start()
    assert started.wait(5)
    t0 = time.time()
    voice._unload()                                       # update_settings(model) does this
    release.set()
    t.join(5)
    assert time.time() - t0 < 2


def test_an_engine_answer_with_a_lone_surrogate_still_encodes(mx, tmp_path, monkeypatch):
    body = b'{"text": "ab\\ud800c", "language": "fr\\ud800"}'
    monkeypatch.setattr(voice, "http_transport", httpx.MockTransport(
        lambda req: httpx.Response(200, content=body, headers={"content-type": "application/json"})))
    voice.update_settings(engine="groq")
    vault.put("GROQ_API_KEY", "secret-key-123")
    out = voice.transcribe_file(make_audio(tmp_path / "v.ogg", 1.5, ["-c:a", "libopus"]))
    out["text"].encode("utf-8")
    assert out["language"] in (None, "auto") or str(out["language"]).encode("utf-8")
    assert out["text"].startswith("ab") and out["text"].endswith("c")


def test_a_voice_section_that_is_not_an_object_is_no_setting(client):
    from maxxing import config
    path = config.config_path()
    cfg = json.loads(path.read_text()) if path.exists() else {}
    path.write_text(json.dumps({**cfg, "voice": True}))
    r = client.get("/api/voice")
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["engine"] == "off"
    assert voice.update_settings(auto_send=True)["auto_send"] is True
    assert json.loads(path.read_text())["voice"]["auto_send"] is True
