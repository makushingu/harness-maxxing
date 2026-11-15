"""Voice mode of a session: a voice (the "talker") talks with the user in real time while the session's Claude Code
(the "thinker") does the work. See docs/dev/API.md#voice-mode.

The browser runs the call: it holds the voice, runs the voice's tools on the session (send a message, stop it, read
its state and its last answer) and tells the voice when a turn of the session ends. Two kinds of voice:

- `local` (default): speech-to-text with the engine of Settings -> Voice, a small Claude model kept running for the
  whole call (`claude -p --input-format stream-json`, no tools) and Piper for the reply, said sentence by sentence
  (maxxing/tts.py). Actions come as lines `@ask: ...` / `@stop` at the start of the voice's reply.
- `cloud`: a realtime speech-to-speech model, OpenAI Realtime (WebRTC) or Gemini Live (WebSocket). This server only
  mints a short-lived token with the instructions, the tools and the voice locked in; the API key never leaves it
  and the audio goes straight from the browser to the provider.

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
from typing import Any, Iterator

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
TURN_TIMEOUT_S = 60
MAX_AUDIO_BYTES = 20 * 1024 * 1024

# Tests: httpx transport for the providers (httpx.MockTransport).
http_transport: Any = None

PROMPT = """You are Harness, the user's assistant, on a voice call with them. You hear them and they hear you.

Language: always answer in the language the user speaks to you now. If they switch language, or ask you to speak \
another language, switch at once and stay in it.

How you work: the real work (their projects, files, code, server, accounts, anything to look up or to do) is done \
by your workspace, which you reach through your actions. For the user it is all you: you are one person.
- Small talk, confirmations, repeating something, how the work is going: answer yourself.
- You know nothing else on your own: not their projects, files, server, accounts or the news. Any real question or \
request: hand it over at once, as an instruction in the user's language that keeps their words, adding nothing of \
your own. Then say a few natural words, as a person who starts working: "I'm looking.", "Give me a second, I'll \
check.", "On it.", in the user's language. Never make up a result and never pretend the work is done.
- When you receive "[Session finished]": tell the outcome in one to three sentences as what you did ("Done, I \
changed...", "I found..."), then the question asked, if any. The user's answer to that question is handed over too.
- To stop the work when the user asks: stop it.
- Never say the words session, Claude, Claude Code, tool, instruction, task handed over, workspace or Harness \
finished: say "I", "I'm looking", "I'm on it", "I've finished".
- Speak like a person on the phone: short, warm, simple sentences, no lists, no markdown, no code, no file paths, \
no URLs, no emoji. One question at a time. Do not repeat what the user just said."""

PROMPT_TOOLS = """
Tools: ask_session(request) hands work to the session; session_status() tells whether it is working and on what; \
stop_session() stops it; read_last_answer() gives its last written answer."""

PROMPT_LOCAL = """
Your actions: start your reply with a line "@ask: <instruction>" to hand a request over, or "@stop" to stop the \
work, then say your sentence on the next line. Every user message starts with "[Session: ...]", the current state \
of the work, and "[Language: xx]", the language the user just spoke: use them, never read them out. Messages \
starting with "[Session finished]" come from your workspace, not from the user."""

TOOLS = [
    {"name": "ask_session", "description": "Hand a request or a task to the Claude Code session (it does the real "
     "work). Returns at once; the session's answer comes later as a [Session finished] message.",
     "parameters": {"type": "object", "properties": {"request": {"type": "string", "description":
                    "A clear, self-contained instruction in the user's language, keeping their words."}},
                    "required": ["request"]}},
    {"name": "session_status", "description": "Whether the session is working, for how long, its last steps and "
     "the messages waiting.", "parameters": {"type": "object", "properties": {}}},
    {"name": "stop_session", "description": "Stop the session's current work.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "read_last_answer", "description": "The session's last written answer.",
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


def call_languages() -> tuple[str, ...]:
    """The languages a call listens for: the one set in Settings -> Voice (if any), the interface's, and English."""
    out: list[str] = []
    for lang in (voice.settings().get("language"), config.load_config().get("language"), "en"):
        lang = str(lang or "").split("-")[0].lower()
        if lang and lang != "auto" and lang not in out:
            out.append(lang)
    return tuple(out)


# ---- local: the talker process ----------------------------------------------------------------------------------
_SENTENCE = re.compile(r"(.+?[.!?…:;])(\s+|$)", re.S)


class LocalCall:
    """One call: a `claude` process (the talker) kept running, fed one message per user turn."""

    def __init__(self, sid: str, model: str, voice_id: str | None, speed: float = 1.0):
        from .sessions import spawn
        self.id = uuid.uuid4().hex[:12]
        self.sid, self.voice_id, self.speed = sid, voice_id, speed
        self.lock = threading.Lock()
        self.used = time.time()
        cmd = [spawn.claude_bin(), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--include-partial-messages", "--model", model, "--tools", "",
               "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
               "--system-prompt", PROMPT + PROMPT_LOCAL]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1, cwd=config.state_dir("claude-titles"),
                                     env=spawn.claude_env(None, "default"))
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.open_turn = False
        self.among = call_languages()
        self.language: str | None = None                   # the language of the user's last sentence
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
        """Send one message to the talker; yields its reply as text pieces until the end of its turn."""
        if self.open_turn:                                 # the previous reply was cut (the user spoke over it)
            self._finish_turn()
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


_calls: dict[str, LocalCall] = {}
_calls_lock = threading.Lock()


def _reap() -> None:
    now = time.time()
    with _calls_lock:
        for cid, c in list(_calls.items()):
            if not c.alive() or now - c.used > IDLE_S:
                _calls.pop(cid, None)
                threading.Thread(target=c.close, daemon=True).start()


def start_local(sid: str) -> dict:
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
                         s["local_speed"])
        _calls[call.id] = call
    threading.Thread(target=_warm_up, daemon=True, name="voicecall-warmup").start()
    return {"mode": "local", "call": call.id}


def _warm_up() -> None:
    """Load the speech-to-text model and start Piper while the user says their first sentence."""
    try:
        vs = voice.settings()
        if vs["engine"] == "local" and voice.local_installed() and voice.model_present(vs["model"]):
            voice._load(vs["model"])
            voice._arm_unload()
        tts.synth("ok")
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


def parse_action(line: str) -> dict | None:
    m = re.match(r"\s*@(ask|stop)\b\s*:?\s*(.*)$", line, re.I)
    if not m:
        return None
    kind = m.group(1).lower()
    if kind == "ask":
        req = m.group(2).strip()
        return {"type": "ask", "request": req} if req else None
    return {"type": "stop"}


def local_turn(cid: str, *, audio: Path | None = None, text: str | None = None, event: str | None = None,
               context: str = "", language: str | None = None) -> Iterator[dict]:
    """One exchange: the user's audio (or text), or an event from Harness -> the voice's reply.
    Yields {heard}, {action}, {say, url, seconds}, {error}, then {done}."""
    c = _call(cid)
    with c.lock:
        if audio is not None:
            # Heard in the language of the last sentence; when it sounds wrong, the user's other likely languages
            # are tried: they can switch language at any time.
            if language:
                out = voice.transcribe_file(audio, language)
            else:
                out = voice.transcribe_file(audio, c.language or (c.among[0] if c.among else "auto"), among=c.among)
            text = (out.get("text") or "").strip()
            if text and out.get("language"):
                c.language = str(out["language"])
            yield {"heard": text}
            if not text:
                yield {"done": True, "empty": True}
                return
        if event:
            message = f"[Session finished]\n{event.strip()[:6000]}"
        elif text:
            lang = f"\n[Language: {c.language}]" if c.language else ""
            message = f"[Session: {context.strip() or 'unknown'}]{lang}\n{text.strip()}"
        else:
            yield {"done": True, "empty": True}
            return
        buf, head_done = "", False
        for piece in c.ask(message):
            buf += piece
            if not head_done:                                 # action lines come first
                while "\n" in buf:
                    first, rest = buf.split("\n", 1)
                    act = parse_action(first)
                    if act is None and first.strip():
                        head_done = True
                        break
                    if act:
                        yield {"action": act}
                    buf = rest
                if not head_done:
                    if buf.lstrip().startswith("@") or not buf.strip():
                        continue
                    head_done = True
            while True:
                m = _SENTENCE.match(buf)
                if not m or len(m.group(1).strip()) < 2:
                    break
                yield from _say(c, m.group(1))
                buf = buf[m.end():]
        if not head_done and buf.strip():
            act = parse_action(buf)
            if act:
                yield {"action": act}
                buf = ""
        if buf.strip():
            yield from _say(c, buf)
        c.used = time.time()
        yield {"done": True}


def _say(c: LocalCall, sentence: str) -> Iterator[dict]:
    said = tts.spoken_text(sentence)
    if not said:
        return
    try:
        out = tts.synth(said, c.voice_id, c.speed)
    except VoiceError as e:
        yield {"say": said, "error": e.message}
        return
    yield {"say": said, "url": f"/api/voice/said/{out['file']}", "seconds": out["seconds"]}
