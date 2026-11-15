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
