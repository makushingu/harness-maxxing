"""Voice mode of a session: the user talks with their session on a voice call. The session does the thinking; the
voice only carries it. See docs/dev/API.md#voice-mode.

The browser runs the call: every sentence the user says goes to the session word for word, in their language
(`sort` / `hear` set aside noise, "ok", "stop" and language requests without any model), a short acknowledgement is
said at once, and the end of each turn of the session is read out. Two kinds of voice:

- `local` (default): speech-to-text with the engine of Settings -> Voice, Piper for what is said (maxxing/tts.py),
  and a small Claude model kept running for the whole call (`claude -p --input-format stream-json`, no tools) that
  only shortens a long answer for the ear.
- `cloud`: a realtime speech-to-speech model, OpenAI Realtime (WebRTC) or Gemini Live (WebSocket), used as the voice
  (its transcription of the user is what the session gets). This server only mints a short-lived token with the
  instructions, the tools and the voice locked in; the API key never leaves it and the audio goes straight from
  the browser to the provider.

All public functions are blocking: call them from a worker thread.
"""
from __future__ import annotations

import json
import logging
import queue
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import config, tts, voice
from .voice import VoiceError

log = logging.getLogger("maxxing.voicecall")

MODES = ("local", "cloud")
PROVIDERS = ("openai", "gemini")
TALKER_MODELS = ("haiku", "sonnet")
OPENAI_VOICES = ("cedar", "marin", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")
GEMINI_VOICES = ("Charon", "Puck", "Fenrir", "Orus", "Kore", "Aoede", "Leda", "Zephyr")
DEFAULTS = {"mode": "local", "provider": None, "openai_key": None, "gemini_key": None,
            "openai_model": "gpt-realtime-2.1", "openai_voice": "cedar",
            "gemini_model": "gemini-3.8-live", "gemini_voice": "Charon",
            "talker_model": "haiku", "local_voice": "auto", "local_speed": 1.15}
SPEED_RANGE = (0.8, 1.5)
OPENAI_API = "https://api.openai.com/v1"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
MAX_CALLS = 3
IDLE_S = 600                 # a local call without any turn for this long is hung up
MAX_AUDIO_BYTES = 20 * 1024 * 1024

# Tests: httpx transport for the providers (httpx.MockTransport).
http_transport: Any = None

PROMPT = """You are Harness, the user's assistant, on a voice call with them. You hear them and they hear you. \
You are only the voice: every sentence the user says is passed, word for word, to the one who does the work (your \
workspace: it reaches their projects, files, server and accounts). For the user it is all you: you are one person.

- Never answer a request or a question yourself, never make up a result, never pretend the work is done: you know \
nothing on your own. After the user speaks, say only a few natural words that show you heard, as a person who \
starts working: "I'm looking.", "On it.", "One second, I'll check.". Say nothing after "ok", "thanks" or noise.
- When you receive "[Session finished]", read the outcome out: what it says, nothing more, in one to four short \
sentences, as what you did ("Done, I changed...", "I found..."), then the question asked, if any. Leave out code, \
paths, URLs and tables; if you left details out, say once that the details are written.
- "[Session working]" messages are for you only: say nothing.
- One language for the whole call: the user's. Switch only if they ask, or clearly speak another language.
- Never say the words session, Claude, Claude Code, tool, workspace or Harness.
- Speak like a person on the phone: short, warm, simple sentences, no lists, no markdown, no emoji."""

PROMPT_TOOLS = """
Tools, only when the user asks how it is going or asks to stop: session_status() tells whether the work is going \
on and on what; stop_session() stops it; read_last_answer() gives the last written answer, to repeat it."""

TOOLS = [
    {"name": "session_status", "description": "Whether the work is going on, for how long, its last steps and "
     "the messages waiting.", "parameters": {"type": "object", "properties": {}}},
    {"name": "stop_session", "description": "Stop the current work.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "read_last_answer", "description": "The last written answer.",
     "parameters": {"type": "object", "properties": {}}},
]


# ---- settings ---------------------------------------------------------------------------------------------------
def settings() -> dict:
    raw = config.load_config().get("voice_call") or {}
    out = {**DEFAULTS, **{k: raw[k] for k in DEFAULTS if k in raw}}
    if out["mode"] not in MODES:
        out["mode"] = "local"
    if out["provider"] not in PROVIDERS:
        out["provider"] = None
    if out["talker_model"] not in TALKER_MODELS:
        out["talker_model"] = "haiku"
    out["local_voice"] = tts.ALIASES.get(out["local_voice"], out["local_voice"])
    if out["local_voice"] not in ("auto", *tts.VOICES):
        out["local_voice"] = "auto"
    try:
        out["local_speed"] = round(min(SPEED_RANGE[1], max(SPEED_RANGE[0], float(out["local_speed"]))), 2)
    except (TypeError, ValueError):
        out["local_speed"] = DEFAULTS["local_speed"]
    return out


def update_settings(**kw: Any) -> dict:
    changes = {k: v for k, v in kw.items() if k in DEFAULTS}
    if "mode" in changes and changes["mode"] not in MODES:
        raise VoiceError(400, "invalid_mode", f"mode must be one of {', '.join(MODES)}")
    if "provider" in changes and changes["provider"] not in (*PROVIDERS, None):
        raise VoiceError(400, "invalid_provider", f"provider must be one of {', '.join(PROVIDERS)}")
    if "talker_model" in changes and changes["talker_model"] not in TALKER_MODELS:
        raise VoiceError(400, "invalid_model", f"talker_model must be one of {', '.join(TALKER_MODELS)}")
    if "openai_voice" in changes and changes["openai_voice"] not in OPENAI_VOICES:
        raise VoiceError(400, "invalid_voice", "unknown OpenAI voice")
    if "gemini_voice" in changes and changes["gemini_voice"] not in GEMINI_VOICES:
        raise VoiceError(400, "invalid_voice", "unknown Gemini voice")
    if "local_voice" in changes:
        changes["local_voice"] = tts.ALIASES.get(changes["local_voice"], changes["local_voice"])
    if "local_voice" in changes and changes["local_voice"] not in ("auto", *tts.VOICES):
        raise VoiceError(400, "invalid_voice", "unknown local voice")
    if "local_speed" in changes:
        try:
            sp = float(changes["local_speed"])
        except (TypeError, ValueError):
            sp = 0.0
        if not SPEED_RANGE[0] <= sp <= SPEED_RANGE[1]:
            raise VoiceError(400, "invalid_speed", f"local_speed must be between {SPEED_RANGE[0]} and {SPEED_RANGE[1]}")
        changes["local_speed"] = round(sp, 2)
    for k in ("openai_model", "gemini_model"):
        if k in changes and not re.fullmatch(r"[A-Za-z0-9._-]{3,80}", str(changes[k] or "")):
            raise VoiceError(400, "invalid_model", f"{k} is not a model id")
    for k in ("openai_key", "gemini_key"):
        if k in changes and changes[k] is not None:
            from . import vault
            vault.check_name(str(changes[k]))
    if changes:
        config.update_config(voice_call=changes)
    return settings()


# ---- keys -------------------------------------------------------------------------------------------------------
def _matches(provider: str, name: str) -> bool:
    n = name.upper()
    if provider == "openai":
        return "OPENAI" in n and "KEY" in n
    return ("GEMINI" in n and "KEY" in n) or n in ("GOOGLE_API_KEY", "GOOGLE_AI_API_KEY", "GOOGLE_GENAI_API_KEY")


def detected_keys() -> dict[str, list[str]]:
    """Vault keys that look like an API key of each provider (names only)."""
    from . import vault
    names = sorted(s["name"] for s in vault.list_secrets())
    return {p: [n for n in names if _matches(p, n)] for p in PROVIDERS}


def _key_name(provider: str, s: dict, found: dict[str, list[str]]) -> str | None:
    chosen = s.get(f"{provider}_key")
    if chosen and chosen in found[provider]:
        return chosen
    std = "OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY"
    if std in found[provider]:
        return std
    return found[provider][0] if len(found[provider]) == 1 else None


def status() -> dict:
    """Settings, the keys found, what is missing for each mode."""
    s = settings()
    found = detected_keys()
    provider = s["provider"]
    if provider is None:
        have = [p for p in PROVIDERS if found[p]]
        provider = have[0] if len(have) == 1 else None
    stt_ready, stt_reason = voice.readiness()
    t = tts.status()
    keys = {p: {"found": found[p], "using": _key_name(p, s, found)} for p in PROVIDERS}
    local_reason = None if stt_ready and t["ready"] else ("stt" if not stt_ready else "tts")
    if provider is None:
        cloud_reason = "choose" if all(found[p] for p in PROVIDERS) else "no_key"
    else:
        cloud_reason = None if keys[provider]["using"] else ("choose_key" if found[provider] else "no_key")
    return {"settings": s, "provider": provider, "keys": keys,
            "local": {"ready": local_reason is None, "reason": local_reason, "stt_reason": stt_reason,
                      "tts": t},
            "cloud": {"ready": cloud_reason is None, "reason": cloud_reason},
            "ready": (local_reason if s["mode"] == "local" else cloud_reason) is None,
            "voices": {"openai": list(OPENAI_VOICES), "gemini": list(GEMINI_VOICES), "local": list(tts.VOICES)},
            "speed_range": list(SPEED_RANGE)}


# ---- cloud: short-lived tokens ----------------------------------------------------------------------------------
def _http():
    import httpx
    return httpx.Client(timeout=20, transport=http_transport)


def _api_error(provider: str, r) -> VoiceError:
    try:
        body = r.json()
        msg = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
    except ValueError:
        msg = r.text[:300]
    code = "bad_key" if r.status_code in (401, 403) else "provider_error"
    return VoiceError(502, code, f"{provider}: {msg or r.status_code}")


def _openai_token(s: dict, key: str) -> dict:
    session = {
        "type": "realtime", "model": s["openai_model"], "instructions": PROMPT + PROMPT_TOOLS,
        "tools": [{"type": "function", **t} for t in TOOLS], "tool_choice": "auto",
        "audio": {"output": {"voice": s["openai_voice"]},
                  "input": {"transcription": {"model": "gpt-4o-mini-transcribe"},
                            "turn_detection": {"type": "semantic_vad"}}},
    }
    with _http() as c:
        r = c.post(f"{OPENAI_API}/realtime/client_secrets", json={"session": session},
                   headers={"Authorization": f"Bearer {key}"})
    if r.status_code >= 400:
        raise _api_error("OpenAI", r)
    data = r.json()
    token = data.get("value") or (data.get("client_secret") or {}).get("value")
    if not token:
        raise VoiceError(502, "provider_error", "OpenAI returned no token")
    return {"provider": "openai", "token": token, "model": s["openai_model"], "url": f"{OPENAI_API}/realtime/calls"}


def _gemini_token(s: dict, key: str) -> dict:
    setup = {
        "model": f"models/{s['gemini_model']}",
        "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": s["gemini_voice"]}}}},
        "systemInstruction": {"parts": [{"text": PROMPT + PROMPT_TOOLS}]},
        "tools": [{"functionDeclarations": [
            {**t, "parameters": t["parameters"] if t["parameters"]["properties"] else None} for t in TOOLS]}],
        "inputAudioTranscription": {}, "outputAudioTranscription": {},
        "contextWindowCompression": {"slidingWindow": {}},          # calls longer than 15 minutes
    }
    for f in setup["tools"][0]["functionDeclarations"]:
        if f["parameters"] is None:
            del f["parameters"]
    now = datetime.now(timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    body = {"uses": 1, "expireTime": iso(now + timedelta(minutes=30)),
            "newSessionExpireTime": iso(now + timedelta(minutes=2)), "bidiGenerateContentSetup": setup}
    with _http() as c:
        r = c.post(f"{GEMINI_API}/auth_tokens", json=body, headers={"x-goog-api-key": key})
    if r.status_code >= 400:
        raise _api_error("Gemini", r)
    token = r.json().get("name")
    if not token:
        raise VoiceError(502, "provider_error", "Gemini returned no token")
    return {"provider": "gemini", "token": token, "model": s["gemini_model"],
            "url": "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta."
                   "GenerativeService.BidiGenerateContentConstrained"}


def cloud_token() -> dict:
    st = status()
    if not st["cloud"]["ready"]:
        raise VoiceError(409, "cloud_not_ready", {"choose": "Choose OpenAI or Gemini in Settings -> Voice",
                                                   "choose_key": "Choose which key to use in Settings -> Voice"}
                         .get(st["cloud"]["reason"], "No OpenAI or Gemini key in the Keys vault"))
    from . import vault
    provider = st["provider"]
    key = (vault.get(st["keys"][provider]["using"]) or "").strip()
    if not key:
        raise VoiceError(409, "cloud_not_ready", "The key is empty")
    s = st["settings"]
    return _openai_token(s, key) if provider == "openai" else _gemini_token(s, key)


def call_languages(ui: str | None = None) -> tuple[str, ...]:
    """The languages a call listens for: the one set in Settings -> Voice (if any), the interface's (the browser's,
    else the server's), and English. The first one is expected first."""
    out: list[str] = []
    for lang in (voice.settings().get("language"), ui, config.load_config().get("language"), "en"):
        lang = str(lang or "").split("-")[0].lower()
        if re.fullmatch(r"[a-z]{2,3}", lang) and lang not in out:
            out.append(lang)
    return tuple(out)


# ---- local: the call --------------------------------------------------------------------------------------------
# The session does the thinking. Every sentence the user says goes to it word for word, in their language (the
# browser sends it, see web/src/features/voice/VoiceCall.tsx). This server only carries the voice: it hears
# (speech-to-text), sets aside what is not for the session (noise, "ok", "stop"...) without any model, says a short
# acknowledgement ready in advance, and reads the session's answers out (a small Claude model shortens a long one
# for the ear, adding nothing).
_SENTENCE = re.compile(r"(.+?[.!?…])(\s+|$)", re.S)

# Said at once, while the session works. One language per call: French and English have their phrases; another
# language gets no acknowledgement (the answer is still read out).
PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "fr": {"ack": ("Je regarde.", "D'accord, je m'en occupe.", "Une seconde, je regarde.", "Je m'en occupe."),
           "queued": ("Noté, je m'en occupe juste après.", "D'accord, je fais ça juste après."),
           "stop": ("D'accord, j'arrête.",),
           "done": ("C'est fait.",),
           "failed": ("Ça n'a pas marché, tout est écrit dans la session.",),
           "lang": ("D'accord, je parle français.",)},
    "en": {"ack": ("I'm looking.", "Okay, I'm on it.", "One second, I'll check.", "On it."),
           "queued": ("Noted, I'll do it right after.", "Okay, I'll do that right after."),
           "stop": ("Okay, I'm stopping.",),
           "done": ("Done.",),
           "failed": ("That didn't work, it's all written in the session.",),
           "lang": ("Okay, I'll speak English.",)},
}
LANG_NAMES = {"fr": ("français", "francais", "french"), "en": ("anglais", "english")}
_SPEAK_VERBS = {"parle", "parler", "parlons", "parlez", "réponds", "répondre", "répondez", "passe", "passer",
                "repasse", "repasser", "passons", "speak", "talk", "switch", "answer", "reply", "go"}
_NOISE = {"hmm", "hm", "hmmm", "mhm", "mmh", "mh", "euh", "heu", "uh", "um", "umm", "eh", "ah", "oh", "bah", "ben"}
_FILLERS = {"ok", "okay", "ok ok", "d'accord", "dac", "merci", "merci beaucoup", "ok merci", "d'accord merci",
            "super", "super merci", "parfait", "génial", "cool", "top", "très bien", "bien", "ça marche", "bon",
            "thanks", "thank you", "thanks a lot", "thank you very much", "ok thanks", "okay thanks", "great",
            "perfect", "alright", "all right", "nice", "good", "cool thanks", "got it", "i see", "je vois"}
_STOP = {"stop", "arrête", "arrete", "arrêtez", "arrête tout", "arrête toi", "arrête ça", "stoppe", "stop tout",
         "on arrête", "annule", "annule tout", "laisse tomber", "stop it", "stop that", "stop everything",
         "cancel", "cancel that", "cancel it", "halt", "never mind", "forget it"}
_LEAD = {"non", "no", "ok", "okay", "attends", "wait", "hé", "hey", "euh", "bon", "allez", "please", "stp", "s'il",
         "te", "plaît", "plait"}
# A short greeting goes to the session without an acknowledgement ("I'm looking" would sound odd).
_GREETING = re.compile(r"^(?:(?:salut|bonjour|bonsoir|coucou|hello|hi|hey|hé|yo|allo|allô)\b.*|ça va|how are you"
                       r"|tu es là|t'es là|are you there)$")
# What Whisper writes on noise or silence (it was trained on subtitled videos).
_HALLUCINATION = re.compile(r"amara\.org|sous-titr|thanks? (?:you )?for watching|merci d'avoir regardé|"
                            r"abonnez-vous|subscribe to|^\W*(?:\.\.\.|…)\W*$", re.I)


def _norm(text: str) -> str:
    low = text.lower().replace("’", "'").replace("-", " ")
    return " ".join(re.sub(r"[^\w' ]+", " ", low).split())


def _words(norm: str) -> list[str]:
    return [w for w in norm.split() if w]


def classify(text: str, expecting: bool = False) -> tuple[str, str | None]:
    """What a transcribed sentence is, without any model -> (kind, language asked for):
    "empty" (nothing, noise, what Whisper makes up on silence), "skip" ("ok", "thanks": not sent, unless the
    voice just asked a question: `expecting`), "stop" (stop the work), "lang" (speak another language),
    "ask" (everything else: sent to the session as it is)."""
    norm = _norm(text)
    words = _words(norm)
    if not words or len(re.sub(r"\W", "", norm)) < 2 or _HALLUCINATION.search(text):
        return "empty", None
    if all(w in _NOISE for w in words):
        return "empty", None
    core = list(words)
    while len(core) > 1 and core[0] in _LEAD:
        core.pop(0)
    while len(core) > 1 and core[-1] in _LEAD:
        core.pop()
    joined = " ".join(core)
    if joined in _STOP or all(w in ("stop", "arrête", "arrete") for w in core):
        return "stop", None
    # "speak French", "parle en anglais", "can we speak in English": a speak verb right before the language name
    # ("reply to this mail in English" is a request for the session)
    for i, w in enumerate(words):
        lang = next((code for code, names in LANG_NAMES.items() if w in names), None)
        if not lang:
            continue
        before = [x for x in words[max(0, i - 3):i] if x not in ("en", "in", "to", "moi", "me", "us", "nous")]
        if (before and before[-1] in _SPEAK_VERBS) or (len(core) <= 4 and core[0] in ("en", "in")):
            return "lang", lang
    if joined in _FILLERS and not expecting:
        return "skip", None
    return "ask", None


def _lang_code(lang: Any) -> str | None:
    s = str(lang or "").lower()
    s = {"english": "en", "french": "fr", "spanish": "es", "german": "de", "italian": "it",
         "portuguese": "pt"}.get(s, s)
    return s if re.fullmatch(r"[a-z]{2,3}", s) else None


SUMMARY_PROMPT = """You turn a written answer into what is said aloud on a phone call. The answer was written \
by the user's assistant; you are that assistant's voice.

Say what the answer says, nothing more: never add facts, names, figures, advice, opinions or questions that are \
not written in it (never guess what a vague phrase like "the others" covers), never answer it, never comment on it. Keep the result, what was done, the figures that matter and the question asked at \
the end, if any. Leave out code, file paths, URLs, tables, long lists and details; if you left details out, say \
once that the details are written. Speak in the first person, as the one who did the work ("I changed...", \
"I found...").

Each message gives the language to speak, then the written answer. Speak that language, even if the answer is \
written in another one. One to four short spoken sentences, plain text, no markdown, no emoji, nothing before or \
after them: never repeat the language line."""
LANG_LABELS = {"fr": "French", "en": "English", "es": "Spanish", "de": "German", "it": "Italian", "pt": "Portuguese"}
_ECHO = re.compile(r"^\s*(?:\[[^\]]{0,40}\]|(?:language|langue)\s*:\s*\w+)\s*[.:]?\s*", re.I)

SHORT_CHARS = 320          # an answer this short (once cleaned for the ear) is read as it is
SUMMARY_TIMEOUT_S = 30


class LocalCall:
    """One call: its language, the acknowledgements ready to play, and a small `claude` process kept running
    (no tools) that shortens long answers for the ear."""

    def __init__(self, sid: str, model: str, voice_id: str | None, speed: float = 1.0, ui_language: str | None = None):
        from .sessions import spawn
        self.id = uuid.uuid4().hex[:12]
        self.sid, self.voice_id, self.speed = sid, voice_id, speed
        self.lock = threading.Lock()                       # the summarizer: one answer at a time
        self.hear_lock = threading.Lock()
        self.used = time.time()
        self.among = call_languages(ui_language)
        self.language = self.among[0] if self.among else "en"   # one language per call (see hear)
        self.settled = False                               # the first sentence sets it (any language)
        self.expecting = False                             # the last thing said was a question
        self.turns = 0                                     # acknowledgements said, to vary them
        self._phrases: dict[tuple[str, str], dict] = {}
        cmd = [spawn.claude_bin(), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--include-partial-messages", "--model", model, "--tools", "",
               "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
               "--system-prompt", SUMMARY_PROMPT]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1, cwd=config.state_dir("claude-titles"),
                                     env=spawn.claude_env(None, "default"))
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.open_turn = False
        threading.Thread(target=self._read, daemon=True, name=f"voicecall-{self.id}").start()

    def _read(self) -> None:
        try:
            for line in self.proc.stdout:  # type: ignore[union-attr]
                self.lines.put(line)
        finally:
            self.lines.put(None)

    def _finish_turn(self) -> None:
        """Skip what is left of a reply nobody listens to any more (up to its end)."""
        end = time.time() + SUMMARY_TIMEOUT_S
        while time.time() < end:
            try:
                line = self.lines.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                break
            if line is None:
                break
            if '"type":"result"' in line.replace(" ", ""):
                break
        self.open_turn = False

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        try:
            self.proc.stdin.close()  # type: ignore[union-attr]
        except OSError:
            pass
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def ask(self, text: str) -> Iterator[str]:
        """Send one message to the summarizer; yields its reply as text pieces until the end of its turn."""
        if self.open_turn:                                 # the previous reply was cut (the user spoke over it)
            self._finish_turn()
        msg = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
        self.proc.stdin.write(json.dumps(msg) + "\n")      # type: ignore[union-attr]
        self.proc.stdin.flush()                            # type: ignore[union-attr]
        self.open_turn = True
        end = time.time() + SUMMARY_TIMEOUT_S
        streamed = False
        while time.time() < end:
            try:
                line = self.lines.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                break
            if line is None:
                raise VoiceError(502, "talker_stopped", "The voice stopped")
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "stream_event":
                d = (ev.get("event") or {}).get("delta") or {}
                if d.get("type") == "text_delta" and d.get("text"):
                    streamed = True
                    yield d["text"]
            elif kind == "assistant" and not streamed:     # no partial messages: the whole reply at once
                for part in (ev.get("message") or {}).get("content") or []:
                    if part.get("type") == "text":
                        yield part.get("text") or ""
            elif kind == "result":
                self.open_turn = False
                if ev.get("is_error") and not streamed:
                    raise VoiceError(502, "talker_failed", str(ev.get("result") or "The voice failed")[:300])
                return
        raise VoiceError(504, "talker_timeout", "The voice did not answer")

    # -- what is said --
    def phrase(self, kind: str, index: int | None = None) -> dict | None:
        """A phrase of PHRASES in the call's language, as audio (kept ready: generated once per call, again when
        its file expired)."""
        options = PHRASES.get(self.language, {}).get(kind)
        if not options:
            return None
        text = options[(self.turns if index is None else index) % len(options)]
        key = (self.language, text)
        got = self._phrases.get(key)
        if got and time.time() - got["at"] < tts.KEEP_S - 60 and (tts.out_dir() / got["file"]).is_file():
            return {"say": text, "url": got["url"], "seconds": got["seconds"]}
        try:
            out = tts.synth(text, self.voice_id, self.speed, self.language)
        except VoiceError:
            return None
        self._phrases[key] = {"file": out["file"], "url": f"/api/voice/said/{out['file']}",
                              "seconds": out["seconds"], "at": time.time()}
        return {"say": text, "url": self._phrases[key]["url"], "seconds": out["seconds"]}

    def prepare(self) -> None:
        """Generate the phrases of the call's language ahead (while the user says their first sentence)."""
        for kind, options in PHRASES.get(self.language, {}).items():
            for i in range(len(options)):
                self.phrase(kind, i)

    def say(self, sentence: str) -> dict | None:
        said = tts.spoken_text(sentence)
        if not said:
            return None
        try:
            out = tts.synth(said, self.voice_id, self.speed, self.language)
        except VoiceError as e:
            return {"say": said, "error": e.message}
        return {"say": said, "url": f"/api/voice/said/{out['file']}", "seconds": out["seconds"]}


_calls: dict[str, LocalCall] = {}
_calls_lock = threading.Lock()


def _reap() -> None:
    now = time.time()
    with _calls_lock:
        for cid, c in list(_calls.items()):
            if not c.alive() or now - c.used > IDLE_S:
                _calls.pop(cid, None)
                threading.Thread(target=c.close, daemon=True).start()


def start_local(sid: str, ui_language: str | None = None) -> dict:
    st = status()
    if not st["local"]["ready"]:
        reason = st["local"]["reason"]
        raise VoiceError(409, "local_not_ready", "Turn on voice messages in Settings -> Voice" if reason == "stt"
                         else "Install the local voice in Settings -> Voice")
    _reap()
    s = st["settings"]
    with _calls_lock:
        for cid, c in list(_calls.items()):                # one call per session
            if c.sid == sid:
                _calls.pop(cid, None)
                threading.Thread(target=c.close, daemon=True).start()
        if len(_calls) >= MAX_CALLS:
            oldest = min(_calls.values(), key=lambda c: c.used)
            _calls.pop(oldest.id, None)
            threading.Thread(target=oldest.close, daemon=True).start()
        call = LocalCall(sid, s["talker_model"], None if s["local_voice"] == "auto" else s["local_voice"],
                         s["local_speed"], ui_language)
        _calls[call.id] = call
    threading.Thread(target=_warm_up, args=(call,), daemon=True, name="voicecall-warmup").start()
    return {"mode": "local", "call": call.id, "language": call.language}


def _warm_up(call: LocalCall) -> None:
    """Load the speech-to-text model and prepare the phrases while the user says their first sentence."""
    try:
        vs = voice.settings()
        if vs["engine"] == "local" and voice.local_installed() and voice.model_present(vs["model"]):
            voice._load(vs["model"])
            voice._arm_unload()
        call.prepare()
    except Exception:
        log.debug("voice call warm-up failed", exc_info=True)


def end_local(cid: str) -> None:
    with _calls_lock:
        c = _calls.pop(cid, None)
    if c:
        c.close()


def _call(cid: str) -> LocalCall:
    with _calls_lock:
        c = _calls.get(cid)
    if not c or not c.alive():
        raise VoiceError(404, "no_call", "This call ended")
    c.used = time.time()
    return c


def hear(cid: str, audio: Path | None = None, text: str | None = None, busy: bool = False) -> dict:
    """One sentence of the user -> {text, language, kind, say?}. `kind`: see classify; "ask" = the browser sends
    `text` to the session (in `language`), "stop" = it stops the work, "empty" / "skip" = nothing to do (the voice
    goes on where it was). `say`: the acknowledgement to play at once ({say, url, seconds}), if any. `busy`: the
    session is working (the sentence waits for its turn: "I'll do it right after")."""
    c = _call(cid)
    with c.hear_lock:
        lang_heard = None
        if audio is not None:
            # Forced into the wrong language, Whisper translates: the first sentence is heard in any language and
            # sets the call's language (the interface language is only a guess).
            out = voice.transcribe_file(audio, c.language if c.settled else "auto", among=c.among if c.settled else ())
            text = (out.get("text") or "").strip()
            lang_heard = _lang_code(out.get("language"))
            if not c.settled and text and lang_heard:
                c.language, c.settled = lang_heard, True
        text = (text or "").strip()
        kind, c.language = sort(text, c.language, c.expecting, lang_heard)
        res: dict[str, Any] = {"text": text, "language": c.language, "kind": kind}
        if kind == "ask" and len(_words(_norm(text))) <= 4 and _GREETING.match(_norm(text)):
            c.expecting = False
        elif kind in ("ask", "stop", "lang"):
            c.expecting = False
            said = c.phrase("queued" if kind == "ask" and busy else "ack" if kind == "ask" else kind)
            if kind == "ask":
                c.turns += 1
            if said:
                res["say"] = said
        c.used = time.time()
        return res


def sort(text: str, current: str, expecting: bool = False, heard: str | None = None) -> tuple[str, str]:
    """classify + the call's language after this sentence -> (kind, language). One language per call: it changes
    when the user asks, or when a whole sentence is clearly in another one (`heard`, the language the speech-to-text
    found, and the words agree; without `heard`, the words alone), never on a short or doubtful sentence."""
    kind, asked = classify(text, expecting)
    if kind == "lang" and asked:
        return kind, asked
    if kind == "ask" and len(_words(_norm(text))) >= 3:
        by_words = voice.text_language(text)
        if by_words and by_words != current and (heard is None or heard == by_words):
            return kind, by_words
        if heard and heard not in ("fr", "en") and heard != current and len(_words(_norm(text))) >= 4:
            return kind, heard                              # a language the words cannot tell: the engine's word
    return kind, current


def _plain(answer: str) -> bool:
    """Short and made of sentences: read as it is."""
    if "```" in answer or re.search(r"(?m)^\s*\|.*\|\s*$", answer):
        return False
    return len(tts.spoken_text(answer)) <= SHORT_CHARS


def _sentences(text: str) -> Iterator[str]:
    text = " ".join(text.split())
    while text:
        m = _SENTENCE.match(text)
        if not m:
            yield text
            return
        yield m.group(1)
        text = text[m.end():]


def _summary_request(lang: str, answer: str) -> str:
    return f"Speak {LANG_LABELS.get(lang, lang)}.\n\nWritten answer:\n{answer[:8000]}"


def _streamed_sentences(pieces: Iterable[str]) -> Iterator[str]:
    buf, head = "", True
    for piece in pieces:
        buf += piece
        if head:                                           # an echo of the request is never said
            if len(buf) < 24 and not buf.strip().endswith(("]", ".")):
                continue
            buf, head = _ECHO.sub("", buf, count=1), False
        while True:
            m = _SENTENCE.match(buf)
            if not m or not m.group(2):                    # the end of a sentence is known once a space follows
                break
            if len(m.group(1).strip()) >= 2:
                yield m.group(1)
            buf = buf[m.end():]
    if buf.strip():
        yield buf


def speak(cid: str, answer: str = "", outcome: str = "answer") -> Iterator[dict]:
    """The session's answer, read out -> {say, url, seconds} sentence by sentence, then {done}. `outcome`:
    "answer", "failed" (the turn failed) or "done" (ended without a written answer). A long answer is shortened
    for the ear by the small model (nothing added); everything stays written in the session."""
    c = _call(cid)
    answer = (answer or "").strip()
    said: list[str] = []
    if outcome == "failed" or not answer:
        p = c.phrase("failed" if outcome == "failed" else "done")
        if p:
            said.append(p["say"])
            yield p
    else:
        with c.lock:
            plain = _plain(answer)
            try:
                parts = (_sentences(tts.spoken_text(answer)) if plain
                         else _streamed_sentences(c.ask(_summary_request(c.language, answer))))
                for sentence in parts:
                    if (item := c.say(sentence)):
                        said.append(item["say"])
                        yield item
            except VoiceError:
                if said or plain:
                    raise
                log.info("voice call: no summary, the start of the answer is read", exc_info=True)
                for sentence in list(_sentences(tts.spoken_text(answer)))[:3]:
                    if (item := c.say(sentence)):
                        said.append(item["say"])
                        yield item
    c.expecting = bool(said) and said[-1].rstrip().endswith("?")
    c.used = time.time()
    yield {"done": True}
