import json
import time

import httpx
import pytest

from maxxing import vault, voicecall


@pytest.fixture
def state(mx):
    yield mx
    voicecall.http_transport = None


def test_a_hand_edited_voice_config_still_loads(state):
    from maxxing import config
    config.update_config(voice_call={"local_voice": ["x"], "provider": {"a": 1}, "mode": 3})
    s = voicecall.settings()
    assert s["local_voice"] == "auto" and s["provider"] is None and s["mode"] == "local"


def test_defaults_are_local(state):
    s = voicecall.settings()
    assert s["mode"] == "local" and s["provider"] is None and s["talker_model"] == "sonnet"
    assert s["silence_ms"] == 1800 and "turn_mode" not in s


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
    with pytest.raises(voicecall.VoiceError) as e:
        voicecall.update_settings(openai_key="../../etc")   # a 400 for the API, not a 500
    assert e.value.code == "invalid_key_name"


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
    assert setup["sessionResumption"] == {}
    voicecall.cloud_token(resume="h-1")                  # a reconnection of the same call goes on from its handle
    assert seen["body"]["bidiGenerateContentSetup"]["sessionResumption"] == {"handle": "h-1"}
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
    assert "never say the words session" in p and "their own words are handed over" in p


@pytest.mark.parametrize("text,kind", [
    ("", "empty"), ("Euh...", "empty"), ("Hmm hmm", "empty"),
    ("Sous-titres réalisés par la communauté d'Amara.org", "empty"), ("Thank you for watching!", "empty"),
    ("Ok.", "skip"), ("Merci beaucoup !", "skip"), ("Thanks", "skip"),
    ("Stop.", "stop"), ("Non non, arrête !", "stop"), ("Arrête tout.", "stop"), ("Stop stop stop", "stop"),
    ("Cancel that.", "stop"),
    ("Tu peux parler en anglais ?", "lang"), ("In English please.", "lang"), ("Speak French.", "lang"),
    ("Écris l'article en anglais et publie-le sur le blog.", "ask"),
    ("That we should be able to speak French because I am speaking French.", "lang"),
    ("Réponds à ce mail en anglais.", "ask"), ("Réponds en anglais.", "lang"),     # a request, not a language switch
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
    """A call without the voice's process: `replies` are what the voice says, one per exchange."""

    def __init__(self, language="fr"):
        import threading
        self.id, self.sid, self.voice_id, self.speed = "abcdef012345", "s1", None, 1.0
        self.lock = threading.Lock()
        self.used, self.among, self.language, self.settled = 0, ("fr", "en"), language, True
        self.expecting, self.last_said, self.pending, self.turns = False, "", [], 0
        self._phrases, self.open_turn = {}, False
        self.asked: list[str] = []
        self.replies: list[str] = []

    def alive(self):
        return True

    def close(self):
        pass

    def ask(self, text):
        self.asked.append(text)
        reply = self.replies.pop(0) if self.replies else "D'accord."
        yield from (reply[i:i + 3] for i in range(0, len(reply), 3))


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


def _turn(call, **kw):
    return list(voicecall.local_turn(call.id, **kw))


def test_a_real_request_is_handed_over_in_the_users_own_words(call):
    call.replies = ["@ask: Check the website status\nJe regarde, une seconde."]
    out = _turn(call, text="Tu peux regarder si mon site marche ?", context="idle")
    assert out[0] == {"heard": "Tu peux regarder si mon site marche ?", "kind": "ask", "language": "fr"}
    assert {"action": {"type": "ask", "request": "Tu peux regarder si mon site marche ?"}} in out   # never a rewrite
    assert [x["say"] for x in out if "say" in x] == ["Je regarde, une seconde."]
    assert call.asked[0] == "[Work: idle]\n[Language: fr]\nTu peux regarder si mon site marche ?"
    assert all(lang == "fr" for _, lang in call.made)           # one voice, the call's language


def test_small_talk_is_answered_by_the_voice_and_not_handed_over(call):
    call.replies = ["Ça va bien, merci. Et toi ?", "Super. Qu'est-ce que je peux faire ?",
                    "@ask\nJe regarde."]
    assert not any("action" in x for x in _turn(call, text="Salut, ça va ?"))
    assert not any("action" in x for x in _turn(call, text="Ça va."))
    out = _turn(call, text="Regarde le blog.")
    asks = [x["action"]["request"] for x in out if "action" in x]
    assert asks == ["Regarde le blog."]                          # the small talk before is not handed over


def test_an_answer_to_the_voices_question_carries_what_came_before(call):
    call.replies = ["Quel site, le blog ou la boutique ?", "@ask\nJe regarde la boutique."]
    _turn(call, text="Regarde si le site marche.")
    out = _turn(call, text="La boutique.")
    req = [x["action"]["request"] for x in out if "action" in x][0]
    assert req.startswith("Regarde si le site marche.") and req.endswith("La boutique.") and "I asked" in req


def test_stop_noise_and_echo_need_no_model(call):
    out = _turn(call, text="Non non, arrête !")
    assert out[1] == {"action": {"type": "stop"}} and out[2]["say"] == "D'accord, j'arrête." and not call.asked
    assert _turn(call, text="Euh...")[-1] == {"done": True, "empty": True}
    saying = "J'ai vérifié les trois sites et le site b répond maintenant."
    assert _turn(call, text="vérifié les trois sites et le site", saying=saying)[0]["kind"] == "empty"
    # a "yeah" said over the voice does not cut it: it says its sentence again
    assert _turn(call, text="Ouais.", saying=saying)[-1] == {"done": True, "empty": True}
    assert not call.asked


def test_the_end_of_the_work_and_its_news_go_through_the_voice(call):
    call.replies = ["[Language: fr]. J'ai trouvé deux erreurs. Je les corrige ?", "Je lis les journaux."]
    out = _turn(call, event="Found 2 errors in the log. Fix them?")
    assert call.asked[0].startswith("[Work finished]\n[Language: fr]\nFound 2 errors")
    assert [x["say"] for x in out if "say" in x] == ["J'ai trouvé deux erreurs.", "Je les corrige ?"]
    assert call.expecting
    out = _turn(call, outcome="progress", note="Let me read the server logs.")
    assert call.asked[1].startswith("[Work in progress]") and out[0]["say"] == "Je lis les journaux."
    _turn(call, event="Boom", outcome="failed")
    assert call.asked[2].startswith("[Work failed]")


def test_when_the_voice_fails_the_words_still_go_to_the_session(call, monkeypatch):
    def broken(text):
        raise voicecall.VoiceError(504, "talker_timeout", "The voice did not answer")
        yield ""

    monkeypatch.setattr(call, "ask", broken)
    out = _turn(call, text="Regarde le serveur.")
    assert {"action": {"type": "ask", "request": "Regarde le serveur."}} in out
    assert any(x.get("code") == "talker_timeout" for x in out)


def test_action_lines_are_never_said():
    parts = lambda t: list(voicecall.reply_parts(t[i:i + 3] for i in range(0, len(t), 3)))  # noqa: E731
    assert parts("@ask: check the site\nJe regarde.") == [("action", {"type": "ask"}), ("say", "Je regarde.")]
    assert parts("Sure, stopping. @stop") == [("say", "Sure, stopping."), ("action", {"type": "stop"})]
    assert parts("[Work: idle] Bonjour.") == [("say", "Bonjour.")]


def test_turn_settings(state):
    voicecall.update_settings(silence_ms=2500)
    assert voicecall.settings()["silence_ms"] == 2500
    with pytest.raises(voicecall.VoiceError):
        voicecall.update_settings(silence_ms=100)


def test_a_message_said_on_a_call_tells_claude_it_is_on_the_phone():
    from maxxing.sessions import runner
    p = runner.build_prompt({"text": "Regarde le site", "call": "fr"})
    assert p.startswith("[Said by the user on a voice call") and "language: fr" in p and p.endswith("Regarde le site")


def test_the_first_sentence_sets_the_language_of_the_call(call, monkeypatch, tmp_path):
    from maxxing import voice
    seen = []

    def transcribe(path, language=None, among=()):
        seen.append(language)
        return {"text": "Est-ce que tu me reçois bien ?", "language": "fr"}

    monkeypatch.setattr(voice, "transcribe_file", transcribe)
    call.settled, call.language = False, "en"                 # the interface was in English
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    assert _turn(call, audio=wav)[0]["language"] == "fr"
    _turn(call, audio=wav)
    assert seen == ["auto", "fr"]


def test_the_voice_never_repeats_the_users_words(call):
    call.replies = ["@ask\nOui vas-y.\nJe mets l'alerte en place."]
    out = _turn(call, text="Oui vas-y.")
    assert [x["say"] for x in out if "say" in x] == ["Je mets l'alerte en place."]


def test_an_idle_call_is_hung_up_without_another_call_starting(call, monkeypatch):
    monkeypatch.setattr(voicecall, "REAP_EVERY_S", 0.05)
    call.used = time.time() - voicecall.IDLE_S - 1               # a tab closed without /end
    voicecall._arm_reaper()
    deadline = time.time() + 5
    while call.id in voicecall._calls and time.time() < deadline:
        time.sleep(0.02)
    assert call.id not in voicecall._calls


def test_a_provider_error_that_is_not_a_json_object_is_a_502():
    for body in (["boom"], "boom", {"error": {"code": 5}}, {"error": ["x"] * 500}):
        r = httpx.Response(503, json=body)
        e = voicecall._api_error("openai", r)
        assert e.status == 502 and e.code == "provider_error" and len(e.message) < 320, body
    assert voicecall._api_error("gemini", httpx.Response(401, text="<html>no</html>")).code == "bad_key"
