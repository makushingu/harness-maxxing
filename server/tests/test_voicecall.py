import json

import httpx
import pytest

from maxxing import vault, voicecall


@pytest.fixture
def state(mx):
    yield mx
    voicecall.http_transport = None


def test_defaults_are_local(state):
    s = voicecall.settings()
    assert s["mode"] == "local" and s["provider"] is None and s["talker_model"] == "haiku"


def test_keys_are_detected_and_chosen(state):
    vault.put("OPENAI_API_KEY", "sk-test")
    st = voicecall.status()
    assert st["keys"]["openai"] == {"found": ["OPENAI_API_KEY"], "using": "OPENAI_API_KEY"}
    assert st["provider"] == "openai"                     # the only provider with a key
    vault.put("ACME_GEMINI_API_KEY", "g1")
    vault.put("BLOG_GEMINI_API_KEY", "g2")
    voicecall.update_settings(mode="cloud")
    st = voicecall.status()
    assert st["provider"] is None and st["cloud"]["reason"] == "choose"
    voicecall.update_settings(provider="gemini")
    st = voicecall.status()
    assert st["cloud"]["reason"] == "choose_key"          # two Gemini keys: the user picks one
    voicecall.update_settings(gemini_key="BLOG_GEMINI_API_KEY")
    assert voicecall.status()["cloud"]["ready"]


def test_bad_settings_are_refused(state):
    with pytest.raises(voicecall.VoiceError):
        voicecall.update_settings(mode="phone")
    with pytest.raises(voicecall.VoiceError):
        voicecall.update_settings(openai_voice="robot")


def test_gemini_token_locks_the_setup(state):
    vault.put("GEMINI_API_KEY", "g-key")
    voicecall.update_settings(mode="cloud", provider="gemini")
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("x-goog-api-key"), json.loads(req.content)
        return httpx.Response(200, json={"name": "auth_tokens/abc"})

    voicecall.http_transport = httpx.MockTransport(handler)
    out = voicecall.cloud_token()
    assert out["provider"] == "gemini" and out["token"] == "auth_tokens/abc"
    assert seen["url"].endswith("/v1beta/auth_tokens") and seen["key"] == "g-key"
    setup = seen["body"]["bidiGenerateContentSetup"]
    assert setup["model"] == "models/gemini-3.8-live" and seen["body"]["uses"] == 1
    names = [f["name"] for f in setup["tools"][0]["functionDeclarations"]]
    assert names == ["ask_session", "session_status", "stop_session", "read_last_answer"]
    assert "g-key" not in json.dumps(out)


def test_openai_token(state):
    vault.put("OPENAI_API_KEY", "sk-x")
    voicecall.update_settings(mode="cloud")

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        assert req.headers["authorization"] == "Bearer sk-x"
        assert body["session"]["audio"]["output"]["voice"] == "cedar"
        assert body["session"]["tools"][0]["type"] == "function"
        return httpx.Response(200, json={"value": "ek_123"})

    voicecall.http_transport = httpx.MockTransport(handler)
    out = voicecall.cloud_token()
    assert out == {"provider": "openai", "token": "ek_123", "model": "gpt-realtime-2.1",
                   "url": "https://api.openai.com/v1/realtime/calls"}


def test_provider_error_is_explained(state):
    vault.put("OPENAI_API_KEY", "bad")
    voicecall.update_settings(mode="cloud")
    voicecall.http_transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": {"message": "Incorrect API key"}}))
    with pytest.raises(voicecall.VoiceError) as e:
        voicecall.cloud_token()
    assert e.value.code == "bad_key" and "Incorrect API key" in e.value.message


def test_actions_are_parsed():
    assert voicecall.parse_action("@ask: fix the mic button") == {"type": "ask", "request": "fix the mic button"}
    assert voicecall.parse_action("@stop") == {"type": "stop"}
    assert voicecall.parse_action("Sure, on it.") is None


def test_local_speed_and_voice_settings(state):
    assert voicecall.settings()["local_speed"] == 1.15
    voicecall.update_settings(local_speed=1.3, local_voice="fr_FR-upmc-pierre")
    s = voicecall.settings()
    assert s["local_speed"] == 1.3 and s["local_voice"] == "fr_FR-upmc-pierre"
    with pytest.raises(voicecall.VoiceError):
        voicecall.update_settings(local_speed=3)
    voicecall.update_settings(local_voice="fr_FR-upmc-medium")    # old id of a voice with several speakers
    assert voicecall.settings()["local_voice"] == "fr_FR-upmc-pierre"


def test_a_call_listens_for_the_interface_language_and_english(state):
    from maxxing import config
    cfg = config.load_config()
    cfg["language"] = "fr"
    config.write_json(config.config_path(), cfg)
    assert voicecall.call_languages() == ("fr", "en")
    assert voicecall.call_languages("de-DE") == ("de", "fr", "en")      # the browser's language comes first


def test_the_voice_never_names_the_machinery():
    p = voicecall.PROMPT.lower()
    assert "never say the words session" in p and "switch at once" in p


def _parts(text, size=3):
    return list(voicecall.reply_parts(text[i:i + size] for i in range(0, len(text), size)))


def test_action_lines_are_never_said_wherever_they_are():
    assert _parts("@ask: check the site\nJe regarde. Un instant.") == [
        ("action", {"type": "ask", "request": "check the site"}), ("say", "Je regarde."), ("say", "Un instant.")]
    # reasoning first, the action alone on its line, its request on the next one
    out = _parts("Okay.\n@ask:\nCheck whether the site is up.\nI'm looking.")
    assert ("action", {"type": "ask", "request": "Check whether the site is up."}) in out
    assert not any(k == "say" and "@" in v for k, v in out)
    assert _parts("Sure, stopping. @stop") == [("say", "Sure, stopping."), ("action", {"type": "stop"})]
    assert _parts("Hello there") == [("say", "Hello there")]
