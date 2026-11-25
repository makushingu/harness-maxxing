"""Voice mode of a session: a call where a voice talks with the user and the session does the real work.
See docs/dev/API.md#voice-mode.

The voice converses on its own (small talk, news of the work, what the last answer said) and hands over anything
real: the session then gets the user's own words, never a rewrite, with `call: <language>` (it answers short, for
the ear). Without any model, this server sets aside noise, the voice's own echo, "stop" and language requests, and
keeps one language per call. The browser runs the call: it sends the messages, stops the work, and tells the voice
when a turn ended (read out) or how it goes (said now and then). Two kinds of voice:

- `local` (default): speech-to-text with the engine of Settings -> Voice, a Claude model kept running for the whole
  call (`claude -p --input-format stream-json`, no tools; actions as "@ask" / "@stop" lines) and Piper for what is
  said, sentence by sentence (maxxing/tts.py). Turn-taking: "turns" (the mic is off while the voice speaks, a tap
  cuts it) or "call" (speak over it), and the silence that ends a sentence (`silence_ms`).
- `cloud`: a realtime speech-to-speech model, OpenAI Realtime (WebRTC) or Gemini Live (WebSocket), with the same
  rules as tools. This server only mints a short-lived token with the instructions, the tools and the voice locked
  in; the API key never leaves it and the audio goes straight from the browser to the provider.

All public functions are blocking: call them from a worker thread.
"""
from __future__ import annotations

import contextlib
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
            "talker_model": "sonnet", "local_voice": "auto", "local_speed": 1.15,
            "silence_ms": 1800}
SILENCE_RANGE = (800, 5000)      # silence that ends a sentence (ms)
SPEED_RANGE = (0.8, 1.5)
OPENAI_API = "https://api.openai.com/v1"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
MAX_CALLS = 3
IDLE_S = 600                 # a local call without any turn for this long is hung up
REAP_EVERY_S = 60            # how often idle calls are looked for while one is open (a closed tab never ends it)
MAX_AUDIO_BYTES = 20 * 1024 * 1024

# Tests: httpx transport for the providers (httpx.MockTransport).
http_transport: Any = None

PROMPT = """You are Harness, the user's assistant, on a voice call with them. You hear them and they hear you. \
Behind you, your workspace does the real work: it has their projects, files, code, server, accounts, tools and the \
web, and it remembers the conversation it had with them in writing. For the user it is all you: you are one person.

Each time the user speaks, decide:
- Answer yourself: greetings, small talk, thanks, how the work is going (from what you are told about it), what \
the last finished work said (it is in this conversation), or one short question when the request is too vague to \
start.
- Hand it over: anything to look up, check, do, change, create, send, find or remember, and any question about \
their projects, files, server, accounts, code, figures or news. When in doubt, hand it over: you know nothing about \
their world on your own. Their own words are handed over as they are; never rewrite them. Then say a few natural \
words, as a person who starts working ("I'm looking.", "On it."), and stop talking.
- Something said while the work goes on ("also check the blog", "no, rather the other one"): hand it over too, it \
joins the work at once.
- Stop the work when they ask for it.
Never make up a result and never say something is done before you are told the work finished.

When the work finished: tell what the written answer says, nothing more, in one to four short sentences, as what \
you did ("I changed...", "I found..."), then its question, if any. Leave out code, paths, URLs and tables; if you \
left details out, say once that the details are written. When it failed: say so in one sentence and what the \
written answer gives as the reason. While the work goes on and you are asked for news: one short sentence, in the \
present tense, on what you are doing now.

Language: always speak the language you are told (the language of the call), whatever language the work is \
written in.
Never say the words session, Claude, Claude Code, tool, workspace, prompt or Harness.
Speak like a person on the phone: short, warm, simple sentences, no lists, no markdown, no emoji, no URLs. One \
question at a time. Do not repeat what the user just said."""

PROMPT_TOOLS = """
Tools: ask_session() hands over what the user just said (their own words, you give none); session_status() tells \
whether the work is going and on what; stop_session() stops it; read_last_answer() gives the last written answer. \
"[Session finished]" / "[Session finished: it failed]" messages tell you the work ended; "[Session working]" \
messages ask for one sentence of news.
The language of the call is the one the user speaks to you. When they ask for another one, switch to it; when they then speak their own language again for a whole sentence, switch back to it. Never stay in a language they no longer speak."""

PROMPT_LOCAL = """
Your reply is exactly what the user hears: never explain your reasoning, never describe what you are deciding, \
never read the bracketed lines out.

To hand over, put "@ask" alone on the first line, then your few words on the next line (never the user's words: \
they are handed over by themselves). To stop the work: "@stop" \
alone on the first line. Nothing else ever goes on an "@" line.

Each message starts with bracketed lines: "[Work: ...]" (how the work is going) and "[Language: xx]" (the language \
to speak) before what the user said; "[Work finished]", "[Work failed]" or "[Work in progress]" when it comes from \
your workspace, not from the user.

Examples:
User: [Work: idle]
[Language: fr]
Tu peux regarder si mon site marche ?
You: @ask
Je regarde, une seconde.

User: [Work: idle]
[Language: fr]
Salut, ça va ?
You: Ça va bien, merci. Qu'est-ce que je peux faire pour toi ?

User: [Work: working for 40 s; last steps: Bash: curl -I https://example.com]
[Language: fr]
Et regarde aussi le blog.
You: @ask
D'accord, j'ajoute le blog.

User: [Work: working for 2 min]
[Language: en]
Where are you at?
You: I'm still checking the server, almost there.

User: [Work finished]
[Language: fr]
## Result
The site answers in 200 ms. The SSL certificate expires in 12 days: renew it?
You: Le site répond bien, en deux cents millisecondes. Par contre, le certificat expire dans douze jours. Tu veux \
que je le renouvelle ?"""

TOOLS = [
    {"name": "ask_session", "description": "Hand over what the user just said, in their own words (it is sent "
     "as it is): the work starts, or joins the work in progress. Returns at once; the answer comes later as a "
     "[Session finished] message.", "parameters": {"type": "object", "properties": {}}},
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
    for k in ("mode", "provider", "talker_model", "local_voice", "openai_voice", "gemini_voice"):
        if out[k] is not None and not isinstance(out[k], str):
            out[k] = DEFAULTS[k]                          # a hand-edited config never breaks the voice settings
    if out["mode"] not in MODES:
        out["mode"] = "local"
    if out["provider"] not in PROVIDERS:
        out["provider"] = None
    if out["talker_model"] not in TALKER_MODELS:
        out["talker_model"] = "sonnet"
    try:
        out["silence_ms"] = int(min(SILENCE_RANGE[1], max(SILENCE_RANGE[0], int(out["silence_ms"]))))
    except (TypeError, ValueError):
        out["silence_ms"] = DEFAULTS["silence_ms"]
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
    if "silence_ms" in changes:
        try:
            ms = int(changes["silence_ms"])
        except (TypeError, ValueError):
            ms = 0
        if not SILENCE_RANGE[0] <= ms <= SILENCE_RANGE[1]:
            raise VoiceError(400, "invalid_silence", f"silence_ms must be between {SILENCE_RANGE[0]} and {SILENCE_RANGE[1]}")
        changes["silence_ms"] = ms
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
            try:
                vault.check_name(str(changes[k]))
            except vault.VaultError as e:
                raise VoiceError(400, "invalid_key_name", str(e)) from None
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
            "speed_range": list(SPEED_RANGE), "silence_range": list(SILENCE_RANGE)}


# ---- cloud: short-lived tokens ----------------------------------------------------------------------------------
def _http():
    import httpx
    return httpx.Client(timeout=20, transport=http_transport)


def _api_error(provider: str, r) -> VoiceError:
    try:
        body = r.json()
    except (ValueError, RecursionError):
        body = None
    if isinstance(body, dict):                # a proxy or a gateway may answer a list, a string or HTML
        err = body.get("error")
        msg = err.get("message") if isinstance(err, dict) else err
    else:
        msg = r.text
    code = "bad_key" if r.status_code in (401, 403) else "provider_error"
    return VoiceError(502, code, f"{provider}: {str(msg)[:300] if msg else r.status_code}")


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


def _gemini_token(s: dict, key: str, resume: str | None = None) -> dict:
    setup = {
        "model": f"models/{s['gemini_model']}",
        "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
            "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": s["gemini_voice"]}}}},
        "systemInstruction": {"parts": [{"text": PROMPT + PROMPT_TOOLS}]},
        "tools": [{"functionDeclarations": [
            {**t, "parameters": t["parameters"] if t["parameters"]["properties"] else None} for t in TOOLS]}],
        "inputAudioTranscription": {}, "outputAudioTranscription": {},
        "contextWindowCompression": {"slidingWindow": {}},          # calls longer than 15 minutes
        # Google ends a connection after about 10 minutes (goAway): the browser opens a new one with the handle of
        # the last state and the conversation goes on where it was.
        "sessionResumption": {"handle": resume} if resume else {},
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


def cloud_token(resume: str | None = None) -> dict:
    """A short-lived token for the browser. `resume`: Gemini's handle of a connection that ended (same call)."""
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
    return _openai_token(s, key) if provider == "openai" else _gemini_token(s, key, resume)


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
_SENTENCE = re.compile(r"(.+?[.!?…])(\s+|$)", re.S)

# Said without the voice: on "stop" (at once), when the voice failed ("ack"), for news of a tool. French and
# English; another language gets none.
PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "fr": {"ack": ("Je regarde.", "D'accord, je m'en occupe.", "Une seconde, je regarde.", "Je m'en occupe."),
           "queued": ("Je suis en train de travailler, je le prends en compte.", "Je travaille dessus, je l'ajoute."),
           "stop": ("D'accord, j'arrête.",),
           "done": ("C'est fait.",),
           "failed": ("Ça n'a pas marché, tout est écrit dans la session.",),
           "lang": ("D'accord, je parle français.",),
           "tool_read": ("Je lis des fichiers.",), "tool_edit": ("Je modifie des fichiers.",),
           "tool_run": ("Je lance des commandes.",), "tool_search": ("Je cherche.",),
           "tool_web": ("Je regarde sur internet.",), "tool_agent": ("Je confie une partie du travail.",),
           "tool_think": ("Je travaille encore.",)},
    "en": {"ack": ("I'm looking.", "Okay, I'm on it.", "One second, I'll check.", "On it."),
           "queued": ("I'm working on it, I'll take that into account.", "I'm on it, I'm adding that."),
           "stop": ("Okay, I'm stopping.",),
           "done": ("Done.",),
           "failed": ("That didn't work, it's all written in the session.",),
           "lang": ("Okay, I'll speak English.",),
           "tool_read": ("I'm reading files.",), "tool_edit": ("I'm changing files.",),
           "tool_run": ("I'm running commands.",), "tool_search": ("I'm searching.",),
           "tool_web": ("I'm looking on the web.",), "tool_agent": ("I'm handing part of the work out.",),
           "tool_think": ("Still working.",)},
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

# Said over the voice, these only show the user listens: the voice is not cut ("oui", "non" may answer it: they cut).
_BACKCHANNEL = _FILLERS | {"ouais", "ouais ouais", "ah ouais", "ah oui", "ah", "ah ok", "mh", "mmh", "hm", "hmm",
                           "hum", "ok ok ok", "voilà", "exactement", "carrément", "yeah", "yeah yeah", "uh huh",
                           "mhm", "right", "exactly", "sure"}


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


_ECHO = re.compile(r"^\s*(?:\[[^\]]{0,60}\]|(?:language|langue)\s*:\s*\w+)\s*[.:]?\s*", re.I)
TURN_TIMEOUT_S = 60
MAX_PENDING = 4            # user sentences kept to hand over with the next one (after a question of the voice)


class LocalCall:
    """One call: its language, a few phrases kept ready, and the voice (a `claude` process kept running, no tools)
    that talks with the user and decides when the session works."""

    def __init__(self, sid: str, model: str, voice_id: str | None, speed: float = 1.0, ui_language: str | None = None):
        from .sessions import spawn
        self.id = uuid.uuid4().hex[:12]
        self.sid, self.voice_id, self.speed = sid, voice_id, speed
        self.lock = threading.Lock()                       # one exchange with the voice at a time
        self.used = time.time()
        self.among = call_languages(ui_language)
        self.language = self.among[0] if self.among else "en"   # one language per call
        self.settled = False                               # the first sentence sets it (any language)
        self.expecting = False                             # the voice's last line was a question
        self.last_said = ""                                # the voice's last line
        self.pending: list[tuple[str, str]] = []           # (the voice's question before, what the user said)
        self.turns = 0
        self._phrases: dict[tuple[str, str], dict] = {}
        cmd = [spawn.claude_bin(), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--include-partial-messages", "--model", model, "--tools", "",
               "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
               "--system-prompt", PROMPT + PROMPT_LOCAL]
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
        end = time.time() + TURN_TIMEOUT_S
        while time.time() < end:
            try:
                line = self.lines.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                break
            if line is None or '"type":"result"' in line.replace(" ", ""):
                break
        self.open_turn = False

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self.proc.stdin.close()  # type: ignore[union-attr]
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def ask(self, text: str) -> Iterator[str]:
        """Send one message to the voice; yields its reply as text pieces until the end of its turn."""
        if self.open_turn:                                 # the previous reply was cut (the user spoke over it)
            self._finish_turn()
            text = "[They went on before your reply ended: answer what they said as a whole]\n" + text
        msg = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
        self.proc.stdin.write(json.dumps(msg) + "\n")      # type: ignore[union-attr]
        self.proc.stdin.flush()                            # type: ignore[union-attr]
        self.open_turn = True
        end = time.time() + TURN_TIMEOUT_S
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
        """A phrase of PHRASES in the call's language, as audio (generated once per call, again when its file
        expired)."""
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
        """Generate the phrases said without the voice ahead (while the user says their first sentence)."""
        for kind in ("stop", "ack"):
            for i in range(len(PHRASES.get(self.language, {}).get(kind) or ())):
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
_reaper: threading.Timer | None = None


def _reap() -> None:
    now = time.time()
    with _calls_lock:
        for cid, c in list(_calls.items()):
            if not c.alive() or now - c.used > IDLE_S:
                _calls.pop(cid, None)
                threading.Thread(target=c.close, daemon=True).start()


def _arm_reaper() -> None:
    """While a local call is open, hang up the idle ones every REAP_EVERY_S (not only when another call starts)."""
    global _reaper
    with _calls_lock:
        if _reaper is not None or not _calls:
            return
        _reaper = threading.Timer(REAP_EVERY_S, _reap_tick)
        _reaper.daemon = True
        _reaper.start()


def _reap_tick() -> None:
    global _reaper
    with _calls_lock:
        _reaper = None
    _reap()
    _arm_reaper()


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
    _arm_reaper()
    threading.Thread(target=_warm_up, args=(call,), daemon=True, name="voicecall-warmup").start()
    return {"mode": "local", "call": call.id, "language": call.language,
            "silence_ms": s["silence_ms"]}


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


def is_echo(text: str, saying: str) -> bool:
    """The mic heard the voice itself: most words of the transcript are words of the sentence it was saying."""
    heard = _words(_norm(text))
    said = set(_words(_norm(saying)))
    if not heard or not said:
        return False
    return sum(w in said for w in heard) / len(heard) >= 0.6


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


def parse_action(line: str) -> dict | None:
    m = re.match(r"\s*@(ask|stop)\b", line, re.I)
    return {"type": m.group(1).lower()} if m else None


_INLINE_ACTION = re.compile(r"(?<=\S)[ \t]+(@(?:ask|stop)\b)", re.I)


def reply_parts(pieces: Iterable[str]) -> Iterator[tuple[str, Any]]:
    """The voice's streamed reply -> ("action", {"type": "ask"|"stop"}) for every action line, wherever it is, and
    ("say", sentence) for the rest, sentence by sentence as soon as each one is complete. A line starting with "@" is
    never said (an "@ask: ..." request text is dropped: the user's own words are handed over); an echo of the
    bracketed lines ("[Language: fr]") neither."""
    buf, bol, head = "", True, True

    def drain(final: bool) -> Iterator[tuple[str, Any]]:
        nonlocal buf, bol
        while buf:
            if bol and buf.lstrip().startswith("@"):
                if "\n" not in buf and not final:
                    return                                    # wait for the whole line
                line, _, buf = buf.partition("\n")
                if (act := parse_action(line)):
                    yield "action", act
                continue
            line, nl, rest = buf.partition("\n")
            m = _SENTENCE.match(line)
            if m and len(m.group(1).strip()) >= 2:
                yield "say", m.group(1).strip()
                buf = line[m.end():].lstrip(" \t") + nl + rest
                bol = True                                    # "Sure. @stop": an action may follow a sentence
                continue
            if nl or final:
                if line.strip():
                    yield "say", line.strip()
                buf, bol = rest, True
                if not nl:
                    return
                continue
            bol = bol and not line.strip()
            return

    for piece in pieces:
        buf += piece
        if head:
            if len(buf) < 24 and not buf.rstrip().endswith(("]", ".", "\n")):
                continue
            buf, head = _ECHO.sub("", buf, count=1).lstrip(" \t"), False
        buf = _INLINE_ACTION.sub(r"\n\1", buf)                # "Sure. @ask" on one line: the action on its own
        yield from drain(False)
    yield from drain(True)


def _small(text: str) -> bool:
    n = _norm(text)
    return len(_words(n)) < 3 or bool(_GREETING.match(n)) or n in _FILLERS


def _handover(c: LocalCall) -> str:
    """What goes to the session on "@ask": the user's own words, never a rewrite. When they were answering a
    question of the voice, what they said before (not small talk) comes first, with that question."""
    items = c.pending[-MAX_PENDING:]
    c.pending = []
    if not items:
        return ""
    kept = [it for it in items[:-1] if not _small(it[1])] + [items[-1]]
    out: list[str] = []
    for i, (question, words) in enumerate(kept):
        if i and question:
            out.append(f'(I asked: "{question}")')
        out.append(words)
    return "\n".join(out)


def local_turn(cid: str, *, audio: Path | None = None, text: str | None = None, event: str | None = None,
               outcome: str = "answer", note: str | None = None, tool: str | None = None, context: str = "",
               busy: bool = False, saying: str = "") -> Iterator[dict]:
    """One exchange of a local call -> NDJSON items. The user's audio (or text): {heard, kind, language} first
    (kind as `classify`; "empty" = noise or the voice's own echo, nothing else follows), then the voice's reply:
    {action: {type: "ask", request} | {type: "stop"}}, {say, url, seconds} sentence by sentence, {done}. `request`
    is the user's own words. Or an event: `event` = the session's answer of an ended turn (`outcome` "answer" /
    "failed" / "done"), or `outcome` "progress" (`note`, `tool`: what the running turn does) -> what the voice says.
    `context`: the session's state line. `saying`: the sentence the voice was saying when the user started."""
    c = _call(cid)
    with c.lock:
        lang = c.language
        if audio is not None or text is not None:
            lang_heard = None
            if audio is not None:
                # Forced into the wrong language Whisper translates: the first sentence is heard in any language and
                # sets the call's language (the interface language is only a guess).
                out = voice.transcribe_file(audio, c.language if c.settled else "auto",
                                            among=c.among if c.settled else ())
                text = (out.get("text") or "").strip()
                lang_heard = _lang_code(out.get("language"))
                if not c.settled and text and lang_heard:
                    c.language, c.settled = lang_heard, True
            text = (text or "").strip()
            if saying and is_echo(text, saying):
                text = ""                                     # the voice heard itself: it goes on
            kind, c.language = sort(text, c.language, c.expecting, lang_heard)
            if kind not in ("empty", "stop") and saying and _norm(text) in _BACKCHANNEL:
                kind = "empty"                                # a "yeah" over the voice: it says its sentence again
            if kind == "skip":
                kind = "ask"                                  # "ok", "thanks": the voice answers, nothing handed over
            yield {"heard": text, "kind": kind, "language": c.language}
            if kind == "empty":
                yield {"done": True, "empty": True}
                return
            if kind == "stop":
                c.pending = []
                yield {"action": {"type": "stop"}}
                if (p := c.phrase("stop")):
                    yield p
                c.expecting = False
                yield {"done": True}
                return
            c.pending.append((c.last_said if c.expecting else "", text))
            work = context.strip() or ("working" if busy else "idle")
            message = f"[Work: {work}]\n[Language: {c.language}]\n{text}"
        elif outcome == "progress":
            what = (note or "").strip()[:1500] or f"using the tool {tool or 'unknown'}"
            message = f"[Work in progress]\n[Language: {c.language}]\nLast note: {what}"
        else:
            body = (event or "").strip()[:8000]
            head = {"failed": "[Work failed]", "done": "[Work finished]"}.get(outcome, "[Work finished]")
            message = f"{head}\n[Language: {c.language}]\n" + (body or "(Done, no written answer.)")
        said: list[str] = []
        handed = False
        user_words = _norm(text or "") if (audio is not None or text) else ""
        try:
            for kind, value in reply_parts(c.ask(message)):
                if kind == "action":
                    if value["type"] == "ask" and not handed and c.pending:
                        handed = True
                        yield {"action": {"type": "ask", "request": _handover(c)}}
                    elif value["type"] == "stop":
                        c.pending = []
                        yield {"action": {"type": "stop"}}
                elif user_words and (nv := _norm(value)) and (nv == user_words
                                                               or (len(nv.split()) >= 3 and nv in user_words)):
                    continue                                  # the voice repeating the user's words
                elif (item := c.say(value)):
                    said.append(item["say"])
                    yield item
        except VoiceError as e:
            # The voice failed: what the user said still goes to the session, with a phrase said without the voice.
            if (audio is not None or text) and not handed and c.pending:
                yield {"action": {"type": "ask", "request": _handover(c)}}
                if (p := c.phrase("ack")):
                    yield p
            yield {"error": e.message, "code": e.code}
        if said:
            c.last_said = said[-1]
            c.expecting = said[-1].rstrip().endswith("?")
        if (audio is not None or text) and not handed and not c.expecting:
            c.pending = []                                    # small talk the voice answered: nothing to hand over
        if lang != c.language:
            yield {"language": c.language}
        c.used = time.time()
        c.turns += 1
        yield {"done": True}
