"""Voice messages: speech-to-text on the server (web mic button + Telegram voice notes).

Claude cannot listen to audio, so audio is transcribed here and the transcript becomes the user
message. Pluggable engines (config.json "voice.engine"):

- `local`  faster-whisper (CTranslate2, CPU int8) on this server: private, free, no key. Optional
           dependency group (`uv sync --extra voice`); models are downloaded to state_dir('voice/models')
           on demand (POST /api/voice/install) or on first use. The model is loaded lazily once, kept in
           memory and unloaded after IDLE_UNLOAD_S without use.
- `groq`   Groq API (whisper-large-v3-turbo) - key GROQ_API_KEY in the Keys vault.
- `openai` OpenAI API (gpt-4o-mini-transcribe) - key OPENAI_API_KEY in the Keys vault.
- `off`

Every input (webm/opus from browsers, ogg/opus from Telegram, m4a/mp3/wav/mp4…) is normalised by
ffmpeg to 16 kHz mono WAV (max MAX_SECONDS). One transcription at a time (process-wide lock); all
public functions are blocking - call them from a worker thread (`asyncio.to_thread`).
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable

from . import config

log = logging.getLogger("maxxing.voice")

ENGINES = ("off", "local", "groq", "openai")
MODELS = ("tiny", "base", "small", "medium")
# Approximate download size (MB) of the CTranslate2 int8/float16 checkpoints (Systran/faster-whisper-*).
MODEL_SIZE_MB = {"tiny": 75, "base": 145, "small": 485, "medium": 1530}
MAX_SECONDS = 15 * 60
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
IDLE_UNLOAD_S = 600
KEY_NAMES = {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}
API_MODELS = {"groq": "whisper-large-v3-turbo", "openai": "gpt-4o-mini-transcribe"}
# direct: the web mic sends the recording at once and the server transcribes it afterwards (like a voice note);
# off = transcribe first into the composer to review it (auto_send then sends the transcript without review).
# mic / call: the mic button (dictation, voice messages) and the voice mode button of the message boxes.
DEFAULTS = {"engine": "off", "model": "small", "language": "auto", "auto_send": False, "direct": True,
            "mic": True, "call": True}

# Tests: httpx transport for the API engines (httpx.MockTransport).
http_transport: Any = None


class VoiceError(Exception):
    """status = HTTP status for the API, code = machine code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---- settings -------------------------------------------------------------------------------
def settings() -> dict:
    v = config.load_config().get("voice") or {}
    out = {**DEFAULTS, **{k: v[k] for k in DEFAULTS if k in v}}
    if out["engine"] not in ENGINES:
        out["engine"] = "off"
    raw = (config.read_json(config.config_path(), {}) or {}).get("voice") or {}
    if out["model"] not in MODELS or "model" not in raw:
        out["model"] = recommended_model()          # small, or base on machines with < 4 GB RAM
    out["language"] = normalise_language(out.get("language"))
    out["auto_send"] = bool(out["auto_send"])
    out["direct"] = bool(out["direct"])
    out["mic"] = out["mic"] is not False
    out["call"] = out["call"] is not False
    return out


def normalise_language(lang: Any) -> str:
    s = str(lang or "auto").strip().lower()
    if s == "auto":
        return s
    if len(s) in (2, 3) and s.isascii() and s.isalpha():   # isalpha() alone accepts "éé"
        return s
    raise VoiceError(400, "invalid_language", "language must be 'auto' or an ISO 639-1 code such as 'en'")


def update_settings(**kw: Any) -> dict:
    changes = {k: v for k, v in kw.items() if k in DEFAULTS and v is not None}
    if "engine" in changes and changes["engine"] not in ENGINES:
        raise VoiceError(400, "invalid_engine", f"engine must be one of {', '.join(ENGINES)}")
    if "model" in changes and changes["model"] not in MODELS:
        raise VoiceError(400, "invalid_model", f"model must be one of {', '.join(MODELS)}")
    if "language" in changes:
        changes["language"] = normalise_language(changes["language"])
    for k in ("auto_send", "direct", "mic", "call"):
        if k in changes:
            changes[k] = bool(changes[k])
    if changes:
        config.update_config(voice=changes)
        if "model" in changes:
            _unload()
    return settings()


# ---- environment ---------------------------------------------------------------------------
def ram_gb() -> float:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024 / 1024, 1)
    except OSError:
        pass
    return 0.0


def recommended_model() -> str:
    r = ram_gb()
    return "base" if 0 < r < 4 else "small"


def ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def local_installed() -> bool:
    importlib.invalidate_caches()
    return importlib.util.find_spec("faster_whisper") is not None


def models_dir() -> Path:
    return config.state_dir("voice", "models")


def model_path(name: str) -> Path:
    return models_dir() / name


def model_present(name: str) -> bool:
    p = model_path(name)
    return (p / "model.bin").is_file() and (p / "config.json").is_file()


# A model downloads into <name>.part and moves to <name> once complete: a half download is never seen as installed.
# One download at a time (install job, transcription, `maxxing update`): two never write the same folder.
_download_lock = threading.Lock()


def _part_path(name: str) -> Path:
    return models_dir() / f"{name}.part"


def _finish_download(name: str) -> None:
    part, dest = _part_path(name), model_path(name)
    if not ((part / "model.bin").is_file() and (part / "config.json").is_file()):
        return
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(part, dest)


def _dir_bytes(p: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def api_key(engine: str) -> str | None:
    name = KEY_NAMES.get(engine)
    if not name:
        return None
    from . import vault
    return (vault.get(name) or "").strip() or None   # a pasted key often ends with a newline


def readiness(s: dict | None = None) -> tuple[bool, str | None]:
    """(ready, reason). reason ∈ off | no_ffmpeg | not_installed | no_key | None."""
    s = s or settings()
    eng = s["engine"]
    if eng == "off":
        return False, "off"
    if not ffmpeg_bin():
        return False, "no_ffmpeg"
    if eng == "local" and not local_installed():
        return False, "not_installed"
    if eng in KEY_NAMES and not api_key(eng):
        return False, "no_key"
    return True, None


def status() -> dict:
    s = settings()
    ready, reason = readiness(s)
    installed = local_installed()
    return {
        "settings": s,
        "ready": ready,
        "reason": reason,
        "ffmpeg": bool(ffmpeg_bin()),
        "local": {
            "installed": installed,
            "loaded": _model_name if _model is not None else None,
            "recommended": recommended_model(),
            "ram_gb": ram_gb(),
            "cpus": os.cpu_count() or 1,
            "models": [{"id": m, "size_mb": MODEL_SIZE_MB[m], "present": model_present(m)} for m in MODELS],
        },
        "keys": {e: bool(api_key(e)) for e in KEY_NAMES},
        "key_names": dict(KEY_NAMES),
        "install": install_state(),
        "max_seconds": MAX_SECONDS,
    }


# ---- audio normalisation --------------------------------------------------------------------
_convert_slots = threading.BoundedSemaphore(2)       # ffmpeg conversions at once (a burst of voice notes)


def normalise(src: Path, dest: Path, max_seconds: int = MAX_SECONDS) -> float:
    """Any audio/video file -> 16 kHz mono 16-bit WAV at `dest`. Returns the duration in seconds.
    Raises VoiceError(422 bad_audio | 413 too_long | 503 no_ffmpeg)."""
    ff = ffmpeg_bin()
    if not ff:
        raise VoiceError(503, "no_ffmpeg", "ffmpeg is not installed on the server (apt-get install ffmpeg)")
    cmd = [ff, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-protocol_whitelist", "file",   # no URLs
           "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-t", str(max_seconds + 1), str(dest)]
    try:
        with _convert_slots:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise VoiceError(422, "bad_audio", "audio conversion timed out") from None
    if p.returncode != 0 or not dest.is_file():
        err = (p.stderr or "").strip().splitlines()
        raise VoiceError(422, "bad_audio", "unreadable audio" + (f": {err[-1][:200]}" if err else ""))
    try:
        with wave.open(str(dest), "rb") as w:
            duration = w.getnframes() / float(w.getframerate() or 16000)
    except (wave.Error, EOFError):
        raise VoiceError(422, "bad_audio", "unreadable audio") from None
    if duration > max_seconds:
        raise VoiceError(413, "too_long", f"audio longer than {max_seconds // 60} minutes")
    if duration < 0.1:
        raise VoiceError(422, "empty_audio", "the recording is empty")
    return round(duration, 2)


def _to_ogg(wav: Path, dest: Path) -> Path:
    """Compact Opus copy for the API engines (25 MB upload limits): ~3 MB for 15 minutes."""
    ff = ffmpeg_bin() or "ffmpeg"
    try:
        p = subprocess.run([ff, "-nostdin", "-loglevel", "error", "-y", "-i", str(wav), "-c:a", "libopus",
                            "-b:a", "24k", "-application", "voip", str(dest)], capture_output=True, text=True,
                           timeout=180)
    except (subprocess.SubprocessError, OSError):      # ffmpeg stuck or missing
        return wav
    if p.returncode != 0 or not dest.is_file():
        return wav                                     # WAV is accepted too (just bigger)
    return dest


# ---- local engine (faster-whisper) ----------------------------------------------------------
_model: Any = None
_model_name: str | None = None
_model_lock = threading.Lock()
_last_used = 0.0
_unload_timer: threading.Timer | None = None
_transcribe_lock = threading.Lock()                   # concurrency 1: requests queue here


def _unload() -> None:
    global _model, _model_name
    with _model_lock:
        if _model is not None:
            log.info("voice: unloading model %s", _model_name)
        _model, _model_name = None, None


def _maybe_unload() -> None:
    if time.time() - _last_used >= IDLE_UNLOAD_S - 1 and not _transcribe_lock.locked():
        _unload()


def _arm_unload() -> None:
    global _unload_timer
    if _unload_timer is not None:
        _unload_timer.cancel()
    _unload_timer = threading.Timer(IDLE_UNLOAD_S, _maybe_unload)
    _unload_timer.daemon = True
    _unload_timer.start()


def download_model(name: str) -> Path:
    """Blocking download of a faster-whisper model into state_dir('voice/models/<name>')."""
    if name not in MODELS:
        raise VoiceError(400, "invalid_model", f"unknown model {name!r}")
    if model_present(name):
        return model_path(name)
    if not local_installed():
        raise VoiceError(503, "not_installed", "local transcription is not installed (Settings → Voice → Install)")
    with _download_lock:
        if model_present(name):                        # downloaded by the install job meanwhile
            return model_path(name)
        fw_utils = importlib.import_module("faster_whisper.utils")
        from . import deps                             # the revision pinned in deps.toml, not whatever is newest
        revision = (deps.get("whisper").get("revisions") or {}).get(name)
        fw_utils.download_model(name, output_dir=str(_part_path(name)), revision=revision)
        _finish_download(name)
    if not model_present(name):
        raise VoiceError(502, "download_failed", f"model {name} could not be downloaded")
    return model_path(name)


def _load(name: str) -> Any:
    global _model, _model_name
    path = download_model(name)                        # outside _model_lock: a download of minutes must not block _unload
    with _model_lock:
        if _model is not None and _model_name == name:
            return _model
        _model, _model_name = None, None
        fw = importlib.import_module("faster_whisper")
        t0 = time.time()
        _model = fw.WhisperModel(str(path), device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 1)
        _model_name = name
        log.info("voice: model %s loaded in %.1fs", name, time.time() - t0)
        return _model


_FR_WORDS = re.compile(r"\b(?:le|la|les|des|est|une|pour|que|qui|pas|tu|je|et|du|sur|avec|ce|ça|mon|ma|on)\b")
_EN_WORDS = re.compile(r"\b(?:the|is|are|and|you|to|of|with|for|not|it|this|can|what|my|we|do|i)\b")


def text_language(text: str) -> str | None:
    """French or English from common words, None when it cannot tell (short, other language)."""
    low = text.lower()
    fr, en = len(_FR_WORDS.findall(low)), len(_EN_WORDS.findall(low))
    if fr + en < 2 or fr == en:
        return None
    return "fr" if fr > en else "en"


# Mean log-probability of a transcript below which the language is doubted (right language about -0.2 to -0.4,
# wrong one -0.45 to -0.85 with the small model).
WRONG_LANGUAGE_LOGPROB = -0.4


def _engine_local(wav: Path, language: str, s: dict) -> dict:
    global _last_used
    model = _load(s["model"])
    among = [lang for lang in (s.get("among") or ()) if lang != language]

    def run(lang: str) -> tuple[str, float, Any]:
        segments, info = model.transcribe(str(wav), language=None if lang == "auto" else lang,
                                          beam_size=1, vad_filter=True, condition_on_previous_text=False)
        segs = list(segments)
        n = sum(len(seg.text) for seg in segs) or 1
        score = sum(seg.avg_logprob * len(seg.text) for seg in segs) / n if segs else 0.0
        return " ".join(seg.text.strip() for seg in segs).strip(), score, info

    text, score, info = run(language)
    if among and language != "auto" and text and score < WRONG_LANGUAGE_LOGPROB:
        # Heard in the expected language with a poor confidence: the user may have switched. The other likely
        # languages are tried and the most confident transcript is kept (costs time only on such sentences).
        for other in among:
            t2, s2, i2 = run(other)
            if t2 and s2 > score:
                text, score, info, language = t2, s2, i2, other
        if score < WRONG_LANGUAGE_LOGPROB:                 # none of them: whatever language Whisper hears
            t2, s2, i2 = run("auto")
            if t2 and s2 > score:
                text, score, info, language = t2, s2, i2, "auto"
    lang_out = getattr(info, "language", None) or (None if language == "auto" else language)
    # Forced into French, Whisper may copy an English sentence as it is (good score): the text tells.
    if among and lang_out in ("fr", "en") and text_language(text) not in (None, lang_out) \
            and text_language(text) in (*among, language):
        lang_out = text_language(text)
    _last_used = time.time()
    _arm_unload()
    return {"text": text, "language": lang_out,
            "model": s["model"]}


# ---- API engines ----------------------------------------------------------------------------
def api_base(engine: str) -> str:
    if engine == "groq":
        return (os.environ.get("MAXXING_GROQ_API") or "https://api.groq.com/openai/v1").rstrip("/")
    return (os.environ.get("MAXXING_OPENAI_API") or "https://api.openai.com/v1").rstrip("/")


def _engine_api(engine: str, wav: Path, language: str, s: dict) -> dict:
    import httpx

    key = api_key(engine)
    if not key:
        raise VoiceError(503, "no_key", f"add {KEY_NAMES[engine]} in Settings → Keys")
    if not (key.isascii() and key.isprintable()):     # httpx cannot put it in a header (UnicodeEncodeError)
        raise VoiceError(503, "no_key", f"{KEY_NAMES[engine]} contains invalid characters, paste it again in Settings → Keys")
    model = (config.load_config().get("voice") or {}).get(f"{engine}_model") or API_MODELS[engine]
    audio = _to_ogg(wav, wav.with_suffix(".ogg"))
    verbose = model.startswith("whisper")
    data = {"model": model, "response_format": "verbose_json" if verbose else "json"}
    if language != "auto":
        data["language"] = language
    try:
        with httpx.Client(transport=http_transport, timeout=180) as c, open(audio, "rb") as f:
            mime = "audio/ogg" if audio.suffix == ".ogg" else "audio/wav"
            r = c.post(f"{api_base(engine)}/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                       data=data, files={"file": (audio.name, f, mime)})
    except httpx.HTTPError as e:   # the message may quote the request headers: never echo the key
        raise VoiceError(502, "engine_error", f"{engine}: {str(e).replace(key, '***')}") from None
    if r.status_code in (401, 403):
        raise VoiceError(502, "bad_key", f"{engine} rejected the key {KEY_NAMES[engine]}")
    if r.status_code >= 400:
        try:
            msg = (r.json().get("error") or {}).get("message") or r.text
        except Exception:  # noqa: BLE001
            msg = r.text
        raise VoiceError(502, "engine_error", f"{engine} error {r.status_code}: {_clean(str(msg)[:200])}")
    try:
        j = r.json()
    except ValueError:
        raise VoiceError(502, "engine_error", f"{engine}: unexpected answer") from None
    if not isinstance(j, dict) or not isinstance(j.get("text") or "", str):   # a proxy answering a list, null...
        raise VoiceError(502, "engine_error", f"{engine}: unexpected answer")
    lang = j.get("language") if isinstance(j.get("language"), str) else None
    if lang and not re.fullmatch(r"[A-Za-z-]{2,20}", lang):   # a code or an English name: nothing else is passed on
        lang = None
    lang = _LANG_NAMES.get(lang.lower(), lang) if lang else (None if language == "auto" else language)
    return {"text": _clean((j.get("text") or "").strip()), "language": lang, "model": model}


def _clean(text: str) -> str:
    """A lone surrogate from an engine or a proxy cannot be encoded to JSON or UTF-8: replace it."""
    return text.encode("utf-8", "replace").decode("utf-8")


# verbose_json returns English names ("french"); map the common ones to ISO codes.
_LANG_NAMES = {"english": "en", "french": "fr", "spanish": "es", "german": "de", "italian": "it",
               "portuguese": "pt", "dutch": "nl", "japanese": "ja", "chinese": "zh", "russian": "ru",
               "korean": "ko", "arabic": "ar", "polish": "pl", "turkish": "tr", "ukrainian": "uk"}

_ENGINES: dict[str, Callable[[Path, str, dict], dict]] = {
    "local": _engine_local,
    "groq": lambda wav, lang, s: _engine_api("groq", wav, lang, s),
    "openai": lambda wav, lang, s: _engine_api("openai", wav, lang, s),
}


# ---- public entry point ---------------------------------------------------------------------
def transcribe_file(src: Path, language: str | None = None, engine: str | None = None,
                    among: tuple[str, ...] = ()) -> dict:
    """Blocking. -> {text, language, duration_s, engine, model, ms}. Raises VoiceError.
    `among`: other likely languages; the local engine tries them when the transcript in `language` is doubtful."""
    s = settings()
    if engine:
        s["engine"] = engine
    s["among"] = tuple(among)
    ready, reason = readiness(s)
    if not ready:
        msgs = {"off": "voice messages are off (Settings → Voice)",
                "no_ffmpeg": "ffmpeg is not installed on the server",
                "not_installed": "local transcription is not installed (Settings → Voice → Install)",
                "no_key": f"add {KEY_NAMES.get(s['engine'], 'the API key')} in Settings → Keys"}
        raise VoiceError(409 if reason == "off" else 503, "voice_off" if reason == "off" else reason or "not_ready",
                         msgs.get(reason or "", "voice is not ready"))
    lang = normalise_language(language) if language else s["language"]
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="mx-voice-", dir=config.state_dir("voice", "tmp")) as td:
        wav = Path(td) / "audio.wav"
        duration = normalise(Path(src), wav)
        with _transcribe_lock:
            out = _ENGINES[s["engine"]](wav, lang, s)
    return {"text": out.get("text") or "", "language": out.get("language"), "duration_s": duration,
            "engine": s["engine"], "model": out.get("model"), "ms": int((time.time() - t0) * 1000)}


# ---- install / download job -----------------------------------------------------------------
_job_lock = threading.Lock()
_job: dict = {"state": "idle", "step": None, "progress": None, "model": None, "message": "", "error": None, "at": None}
_job_thread: threading.Thread | None = None


def install_state() -> dict:
    j = dict(_job)
    if j["state"] == "running" and j["step"] == "model" and j["model"]:
        expected = MODEL_SIZE_MB.get(j["model"], 1) * 1024 * 1024
        j["progress"] = round(min(0.99, _dir_bytes(_part_path(j["model"])) / expected), 3)
    return j


def code_dir() -> Path:
    return config.CODE / "server"


def uv_sync_cmd() -> list[str] | None:
    from .cmd_core import uv_bin
    uv = uv_bin()
    if not uv:
        return None
    cmd = [uv, "sync", "--no-dev", "--extra", "voice", "--quiet"]
    if (code_dir() / "uv.lock").is_file():
        cmd.insert(2, "--frozen")
    return cmd


def _marker() -> Path:
    return config.STATE / "voice" / "extra-installed"


def sync_extras() -> list[str]:
    """Extra flags for `uv sync` (maxxing update) so updates keep the voice dependencies: set once they
    were installed from the UI / installer (marker file) or while the local engine is selected."""
    return ["--extra", "voice"] if _marker().exists() or settings()["engine"] == "local" else []


def _install_deps() -> None:
    cmd = uv_sync_cmd()
    if not cmd:
        raise VoiceError(503, "no_uv", "uv not found: re-run the installer or install faster-whisper by hand")
    env = {**os.environ, "UV_PYTHON_INSTALL_DIR": str(config.STATE / "tools" / "python")}   # = deps.uv_env()
    p = subprocess.run(cmd, cwd=str(code_dir()), capture_output=True, text=True, timeout=1800, env=env)
    if p.returncode != 0:
        raise VoiceError(502, "install_failed", (p.stderr or p.stdout or "uv sync failed").strip()[-400:])
    if not local_installed():
        raise VoiceError(502, "install_failed", "faster-whisper is still not importable after uv sync")


def _download_subprocess(name: str) -> None:
    """The download runs in a child process (no heavy import in the server; progress = folder size)."""
    from . import deps                                 # the same pinned revision as download_model()
    revision = (deps.get("whisper").get("revisions") or {}).get(name) or ""
    code = ("import sys; from faster_whisper.utils import download_model as d; "
            "d(sys.argv[1], output_dir=sys.argv[2], revision=sys.argv[3] or None)")
    with _download_lock:
        if model_present(name):
            return
        p = subprocess.run([sys.executable, "-c", code, name, str(_part_path(name)), revision],
                           capture_output=True, text=True, timeout=3600)
        if p.returncode == 0:
            _finish_download(name)
    if p.returncode != 0 or not model_present(name):
        err = (p.stderr or "").strip().splitlines()
        raise VoiceError(502, "download_failed", (err[-1] if err else "download failed")[:300])


# Tests replace these two steps.
install_steps: dict[str, Callable[..., None]] = {"deps": _install_deps, "model": _download_subprocess}


def start_install(model: str | None = None) -> dict:
    """Installs faster-whisper (if needed) then downloads `model` (default: configured model), in a
    background thread. -> install_state(). Raises VoiceError(409 busy)."""
    global _job_thread
    model = model or settings()["model"]
    if model not in MODELS:
        raise VoiceError(400, "invalid_model", f"unknown model {model!r}")
    with _job_lock:
        if _job["state"] == "running":
            raise VoiceError(409, "busy", "an install is already running")
        _job.update(state="running", step="deps", progress=None, model=model, message="", error=None, at=time.time())

    def run() -> None:
        try:
            if not local_installed():
                _job.update(step="deps", message="Installing faster-whisper (uv sync --extra voice)…")
                install_steps["deps"]()
            _marker().parent.mkdir(parents=True, exist_ok=True)
            _marker().touch()
            if not model_present(model):
                _job.update(step="model", message=f"Downloading the {model} model (~{MODEL_SIZE_MB[model]} MB)…")
                install_steps["model"](model)
            _job.update(state="done", step=None, progress=1.0, message="Ready", at=time.time())
        except VoiceError as e:
            _job.update(state="error", error=e.message, message="", at=time.time())
        except Exception as e:  # noqa: BLE001
            log.exception("voice install failed")
            _job.update(state="error", error=str(e)[:300], message="", at=time.time())
        finally:
            try:
                from . import bus
                bus.invalidate("health")
            except Exception:  # noqa: BLE001
                pass

    _job_thread = threading.Thread(target=run, name="voice-install", daemon=True)
    _job_thread.start()
    return install_state()


def delete_model(name: str) -> None:
    if name not in MODELS:
        raise VoiceError(400, "invalid_model", f"unknown model {name!r}")
    with _job_lock:
        if _job["state"] == "running" and _job["model"] == name:
            raise VoiceError(409, "busy", f"the {name} model is being installed")
    if _model_name == name:
        _unload()
    shutil.rmtree(model_path(name), ignore_errors=True)
    shutil.rmtree(_part_path(name), ignore_errors=True)


# ---- doctor ----------------------------------------------------------------------------------
def doctor() -> tuple[str, str, str, str]:
    """-> (level ok|warn|info, title, detail, fix) for `maxxing doctor`."""
    s = settings()
    if s["engine"] == "off":
        return "info", "voice messages off", "", "Settings → Voice to enable them"
    ready, reason = readiness(s)
    if not ready:
        fixes = {"no_ffmpeg": "apt-get install -y ffmpeg",
                 "not_installed": f"cd {code_dir()} && uv sync --extra voice   (or Settings → Voice → Install)",
                 "no_key": f"add {KEY_NAMES.get(s['engine'], '')} in Settings → Keys"}
        return "warn", f"voice ({s['engine']}) not ready: {reason}", "", fixes.get(reason or "", "")
    if s["engine"] == "local" and not model_present(s["model"]):
        return "warn", f"voice (local): model {s['model']} not downloaded yet", "downloaded on first use", \
            "Settings → Voice → Download"
    detail = f"model {s['model']}" if s["engine"] == "local" else API_MODELS.get(s["engine"], "")
    return "ok", f"voice messages ({s['engine']})", detail, ""
