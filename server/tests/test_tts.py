from maxxing import tts


def test_spoken_text_drops_code_links_and_markdown():
    md = ("Done. **Tests**: 12 pass ✅\n\n```bash\nnpm run build\n```\n- File `/srv/acme/web/App.tsx` changed — see "
          "[the PR](https://example.com/pr/1)\n| a | b |\n|---|---|\nShall I push?")
    assert tts.spoken_text(md) == "Done. Tests: 12 pass. File App.tsx changed, see the PR. Shall I push?"


def test_cut_stops_at_a_sentence():
    assert tts._cut("One. Two three four. Five six seven eight nine.", 25) == "One. Two three four."


def test_synth_needs_the_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("MAXXING_STATE", str(tmp_path))
    import pytest
    with pytest.raises(tts.TTSError) as e:
        tts.synth("hello")
    assert e.value.code == "tts_not_ready"


def test_a_voice_only_reads_its_language(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "installed_voices", lambda: ["fr_FR-upmc-pierre", "fr_FR-tom-medium", "en_US-ryan-medium"])
    assert tts.pick_voice("Je regarde ça tout de suite.", "fr_FR-upmc-pierre") == "fr_FR-upmc-pierre"
    assert tts.pick_voice("I am looking at it, give me a second.", "fr_FR-upmc-pierre") == "en_US-ryan-medium"
    assert tts.pick_voice("Je regarde ça.", "fr_FR-upmc-medium") == "fr_FR-upmc-pierre"   # old id
    assert tts.VOICES["fr_FR-upmc-pierre"]["speaker"] == 1


def test_a_hanging_voice_worker_fails_the_sentence_instead_of_blocking(tmp_path, monkeypatch):
    """A Piper worker that never answers: the sentence fails after SYNTH_TIMEOUT_S, the worker is stopped and the
    next sentence is not stuck behind it (the lock is free)."""
    import stat
    import time
    import pytest
    monkeypatch.setattr(tts, "root", lambda: tmp_path / "tts")
    monkeypatch.setattr(tts, "out_dir", lambda: tmp_path)
    py = tts.root() / "venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\nexec sleep 30\n")
    py.chmod(py.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(tts, "SYNTH_TIMEOUT_S", 0.5)
    monkeypatch.setattr(tts, "pick_voice", lambda *a, **k: next(iter(tts.VOICES)))
    t0 = time.time()
    with pytest.raises(tts.TTSError) as e:
        tts.synth("bonjour")
    assert e.value.code == "tts_timeout" and time.time() - t0 < 5
    assert tts._lock.acquire(timeout=1)
    tts._lock.release()
    assert tts._worker is None or tts._worker.poll() is not None
