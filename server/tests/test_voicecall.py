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
    assert names == ["session_status", "stop_session", "read_last_answer"]     # the voice never hands work over
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
    assert "never say the words session" in p and "never answer a request" in p


@pytest.mark.parametrize("text,kind", [
    ("", "empty"), ("Euh...", "empty"), ("Hmm hmm", "empty"),
    ("Sous-titres réalisés par la communauté d'Amara.org", "empty"), ("Thank you for watching!", "empty"),
    ("Ok.", "skip"), ("Merci beaucoup !", "skip"), ("Thanks", "skip"),
    ("Stop.", "stop"), ("Non non, arrête !", "stop"), ("Arrête tout.", "stop"), ("Stop stop stop", "stop"),
    ("Cancel that.", "stop"),
    ("Tu peux parler en anglais ?", "lang"), ("In English please.", "lang"), ("Speak French.", "lang"),
    ("Écris l'article en anglais et publie-le sur le blog.", "ask"),     # a request, not a language switch
    ("Regarde si mon site marche.", "ask"), ("Arrête le serveur de test.", "ask"),
])
def test_sentences_are_sorted_without_a_model(text, kind):
    assert voicecall.classify(text)[0] == kind


def test_ok_is_sent_when_the_voice_asked_a_question():
    assert voicecall.classify("Ok.", expecting=True)[0] == "ask"
    assert voicecall.classify("Euh", expecting=True)[0] == "empty"


def test_one_language_per_call():
    assert voicecall.sort("Can you check the site is up?", "fr") == ("ask", "en")     # a whole clear sentence
    assert voicecall.sort("Ok cool", "fr") == ("skip", "fr")
    assert voicecall.sort("Deploy", "fr") == ("ask", "fr")                           # too short to tell
    assert voicecall.sort("Can you check the site is up?", "fr", heard="fr") == ("ask", "fr")   # they disagree
    assert voicecall.sort("Parle en anglais", "fr") == ("lang", "en")
    assert voicecall.sort("Podrías revisar el sitio web ahora", "fr", heard="es") == ("ask", "es")


class _Call(voicecall.LocalCall):
    """A call without the small model's process."""

    def __init__(self, language="fr"):
        import threading
        self.id, self.sid, self.voice_id, self.speed = "abcdef012345", "s1", None, 1.0
        self.lock, self.hear_lock = threading.Lock(), threading.Lock()
        self.used, self.among, self.language = 0, ("fr", "en"), language
        self.expecting, self.turns, self._phrases, self.open_turn = False, 0, {}, False
        self.asked: list[str] = []
        self.summary = "J'ai trouvé deux erreurs. Je les corrige ?"

    def alive(self):
        return True

    def close(self):
        pass

    def ask(self, text):
        self.asked.append(text)
        yield from (self.summary[i:i + 4] for i in range(0, len(self.summary), 4))


@pytest.fixture
def call(state, monkeypatch):
    from maxxing import tts
    made = []

    def synth(text, voice_id=None, speed=1.0, lang=None):
        made.append((text, lang))
        f = tts.out_dir() / f"say-{len(made)}.wav"
        f.write_bytes(b"RIFF")
        return {"file": f.name, "seconds": 1.0, "voice": "v"}

    monkeypatch.setattr(tts, "synth", synth)
    c = _Call()
    voicecall._calls[c.id] = c
    c.made = made
    yield c
    voicecall._calls.pop(c.id, None)


def test_hear_sorts_and_acknowledges_at_once(call):
    out = voicecall.hear(call.id, text="Regarde si mon site marche.")
    assert out["kind"] == "ask" and out["text"] == "Regarde si mon site marche." and out["language"] == "fr"
    assert out["say"]["say"] == "Je regarde." and out["say"]["url"].startswith("/api/voice/said/")
    assert voicecall.hear(call.id, text="Et la base de données aussi.", busy=True)["say"]["say"].endswith("juste après.")
    n = len(call.made)
    voicecall.hear(call.id, text="Je regarde encore une fois le site.")
    assert len(call.made) == n + 1
    voicecall.hear(call.id, text="Je regarde encore une fois le site.")   # phrases are generated once per call
    assert "say" not in voicecall.hear(call.id, text="Merci.")
    assert voicecall.hear(call.id, text="Arrête !")["say"]["say"] == "D'accord, j'arrête."


def test_a_short_answer_is_read_as_it_is_a_long_one_is_shortened(call):
    out = list(voicecall.speak(call.id, "C'est **fait** : le site répond. Tu veux que je publie ?"))
    assert [x.get("say") for x in out] == ["C'est fait : le site répond.", "Tu veux que je publie ?", None]
    assert out[-1] == {"done": True} and not call.asked
    assert call.expecting                                  # "oui" / "ok" now goes to the session
    assert voicecall.hear(call.id, text="Ok")["kind"] == "ask"
    long = "Voici le détail :\n\n```\nerror: x\n```\n" + "Une ligne de plus. " * 40
    out = list(voicecall.speak(call.id, long))
    assert call.asked[0].startswith("[Language: fr]\n")
    assert [x.get("say") for x in out if "say" in x] == ["J'ai trouvé deux erreurs.", "Je les corrige ?"]
    assert all(lang == "fr" for _, lang in call.made)    # one voice, the call's language
    assert list(voicecall.speak(call.id, "", "failed"))[0]["say"].startswith("Ça n'a pas marché")


def test_a_message_said_on_a_call_tells_claude_it_is_on_the_phone():
    from maxxing.sessions import runner
    p = runner.build_prompt({"text": "Regarde le site", "call": "fr"})
    assert p.startswith("[Said by the user on a voice call") and "language: fr" in p and p.endswith("Regarde le site")
