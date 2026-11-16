"""Text-to-speech on this server for the voice mode (local voice).

Engine: Piper (https://github.com/OHF-Voice/piper1-gpl), run as a separate program from its own virtual
environment in state_dir('voice/tts') (it is GPL: never imported into this process). Voices are ONNX files
from the rhasspy/piper-voices catalogue, downloaded next to it. All public functions are blocking: call them
from a worker thread.

Used by the local voice of the voice mode (maxxing/voicecall.py), which says its replies sentence by sentence.
`spoken_text` turns markdown into plain sentences worth saying.
"""
from __future__ import annotations

import json
import logging
import re
import select
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from . import config, voice

log = logging.getLogger("maxxing.tts")

VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
# Voice id -> its model in the rhasspy/piper-voices catalogue (language/locale/name/quality), the speaker inside a
# model holding several, the language it speaks and a short name shown in Settings.
VOICES: dict[str, dict] = {
    "fr_FR-tom-medium": {"model": "fr_FR-tom-medium", "path": "fr/fr_FR/tom/medium", "lang": "fr", "name": "Tom"},
    "fr_FR-upmc-pierre": {"model": "fr_FR-upmc-medium", "path": "fr/fr_FR/upmc/medium", "speaker": 1, "lang": "fr",
                          "name": "Pierre"},
    "fr_FR-upmc-jessica": {"model": "fr_FR-upmc-medium", "path": "fr/fr_FR/upmc/medium", "speaker": 0,
                           "lang": "fr", "name": "Jessica"},
    "fr_FR-siwis-medium": {"model": "fr_FR-siwis-medium", "path": "fr/fr_FR/siwis/medium", "lang": "fr",
                           "name": "Siwis"},
    "fr_FR-gilles-low": {"model": "fr_FR-gilles-low", "path": "fr/fr_FR/gilles/low", "lang": "fr", "name": "Gilles"},
    "en_US-ryan-medium": {"model": "en_US-ryan-medium", "path": "en/en_US/ryan/medium", "lang": "en", "name": "Ryan"},
    "en_US-amy-medium": {"model": "en_US-amy-medium", "path": "en/en_US/amy/medium", "lang": "en", "name": "Amy"},
}
# Old ids (one model with several speakers was one voice): still accepted in settings.
ALIASES = {"fr_FR-upmc-medium": "fr_FR-upmc-pierre"}
DEFAULT_VOICE = {"fr": "fr_FR-tom-medium", "en": "en_US-ryan-medium"}
PIPER_SPEC = "piper-tts>=1.3,<2"
MAX_CHARS = 4000            # input of one request
KEEP_S = 600                # generated audio files are deleted after this

_lock = threading.Lock()
_install: dict = {"state": "idle"}
_install_lock = threading.Lock()


class TTSError(voice.VoiceError):
    pass


def root() -> Path:
    return config.state_dir("voice", "tts")


def piper_bin() -> Path:
    return root() / "venv" / "bin" / "piper"


def voice_file(vid: str) -> Path:
    vid = ALIASES.get(vid, vid)
    return root() / "voices" / f"{VOICES[vid]['model'] if vid in VOICES else vid}.onnx"


def installed_voices() -> list[str]:
    return [v for v in VOICES if voice_file(v).is_file() and voice_file(v).with_suffix(".onnx.json").is_file()]


def catalogue() -> list[dict]:
    return [{"id": v, "name": d["name"], "lang": d["lang"]} for v, d in VOICES.items()]


def status() -> dict:
    ready = piper_bin().is_file() and bool(installed_voices()) and bool(voice.ffmpeg_bin())
    return {"ready": ready, "engine": "piper", "voices": installed_voices(), "catalogue": catalogue(),
            "install": dict(_install)}


# ---- install -------------------------------------------------------------------------------------------------
def _uv() -> str:
    for c in (shutil.which("uv"), str(Path.home() / ".local" / "bin" / "uv"), "/usr/local/bin/uv"):
        if c and Path(c).is_file():
            return c
    raise TTSError(500, "no_uv", "uv is not installed")


def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as out:
        shutil.copyfileobj(r, out, 1024 * 1024)
    tmp.replace(dest)


def install(voices: list[str] | None = None) -> dict:
    """Create the Piper environment (once) and download the voices. Blocking (about 1 minute)."""
    want = [ALIASES.get(v, v) for v in (voices or list(DEFAULT_VOICE.values()))]
    want = [v for v in want if v in VOICES]
    _install.update(state="running", started=time.time(), error=None)
    try:
        if not piper_bin().is_file():
            venv = root() / "venv"
            subprocess.run([_uv(), "venv", "-q", "-p", "3.12", str(venv)], check=True, capture_output=True, timeout=300)
            subprocess.run([_uv(), "pip", "install", "-q", "-p", str(venv / "bin" / "python"), PIPER_SPEC],
                           check=True, capture_output=True, timeout=600)
        (root() / "voices").mkdir(parents=True, exist_ok=True)
        for vid in want:
            m = VOICES[vid]
            for suf in (".onnx", ".onnx.json"):
                dest = root() / "voices" / f"{m['model']}{suf}"
                if not dest.is_file():
                    _download(f"{VOICES_URL}/{m['path']}/{m['model']}{suf}", dest)
        _install.update(state="done", ended=time.time())
    except subprocess.CalledProcessError as e:
        _install.update(state="failed", error=(e.stderr or b"").decode(errors="replace")[-400:] or str(e))
    except Exception as e:  # network, disk
        _install.update(state="failed", error=str(e))
    return status()


def start_install(voices: list[str] | None = None) -> dict:
    # "running" is set under the lock BEFORE the thread starts: set after, it hid an install that failed at once
    # (stuck "running" until a restart), and two clicks at once started two installs on the same files.
    with _install_lock:
        start = _install.get("state") != "running"
        if start:
            _install.update(state="running", started=time.time(), error=None)
    if start:
        threading.Thread(target=install, args=(voices,), daemon=True, name="tts-install").start()
    return status()


# ---- what is said --------------------------------------------------------------------------------------------
_FENCE = re.compile(r"```.*?(?:```|$)", re.S)
_TABLE = re.compile(r"(?m)^\s*\|.*\|\s*$\n?")
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_PATH = re.compile(r"(?<![\w.])(?:~|\.{1,2})?/(?:[\w.@+-]+/)+[\w.@+-]*")
_CODE = re.compile(r"`([^`\n]{1,40})`|`[^`\n]*`")
_MARK = re.compile(r"(?m)^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)")
_EMPH = re.compile(r"(\*\*|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️‍]")


def spoken_text(md: str) -> str:
    """Markdown answer -> plain sentences worth saying."""
    s = _FENCE.sub(" ", md or "")
    s = _TABLE.sub(" ", s)
    s = _IMG.sub(" ", s)
    s = _LINK.sub(r"\1", s)
    s = _URL.sub(" ", s)
    s = _PATH.sub(lambda m: " " + (Path(m.group(0)).name or "") + " ", s)
    s = _CODE.sub(lambda m: m.group(1) or " ", s)
    s = _MARK.sub("", s)
    s = _EMPH.sub(r"\2", s)
    s = _EMOJI.sub("", s)
    s = re.sub(r"\s*[—–]\s*", ", ", s)
    s = re.sub(r"(?m)^[ \t]*[:·|]+[ \t]*", "", s)
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    s = " ".join(ln if ln[-1] in ".!?:;," else ln + "." for ln in lines)
    return re.sub(r"\s{2,}", " ", s).strip()


def _cut(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    part = text[:n]
    end = max(part.rfind(". "), part.rfind("? "), part.rfind("! "))
    return part[: end + 1] if end > n // 3 else part.rsplit(" ", 1)[0] + "…"


def _lang(text: str) -> str:
    fr = len(re.findall(r"\b(?:le|la|les|des|est|une|pour|que|pas|tu|je|et|du|sur|avec)\b", text.lower()))
    en = len(re.findall(r"\b(?:the|is|are|and|you|to|of|with|for|not|it|this)\b", text.lower()))
    return "fr" if fr >= en else "en"


# ---- synthesis -----------------------------------------------------------------------------------------------
def out_dir() -> Path:
    d = config.state_dir("voice", "tts", "out")
    now = time.time()
    for f in [*d.glob("*.mp3"), *d.glob("*.wav")]:
        try:
            if now - f.stat().st_mtime > KEEP_S:
                f.unlink()
        except OSError:
            pass
    return d


def pick_voice(text: str, wanted: str | None = None, lang: str | None = None) -> str:
    """The voice to use for `text`: `wanted` when installed and it speaks the text's language, else the default
    voice of that language (an English sentence is never read by a French voice)."""
    have = installed_voices()
    if not have:
        raise TTSError(409, "tts_not_ready", "Spoken replies are not installed")
    lang = lang if lang in DEFAULT_VOICE else _lang(text)
    wanted = ALIASES.get(wanted or "", wanted)
    if wanted in have and VOICES[wanted]["lang"] == lang:
        return wanted
    vid = DEFAULT_VOICE.get(lang)
    if vid in have:
        return vid
    same = [v for v in have if VOICES[v]["lang"] == lang]
    return same[0] if same else (wanted if wanted in have else have[0])


_worker: subprocess.Popen | None = None
_worker_used = 0.0
WORKER_IDLE_S = 600


def _stop_worker() -> None:
    global _worker
    w, _worker = _worker, None
    if w is not None:
        try:
            w.stdin.close()  # type: ignore[union-attr]
            w.wait(timeout=3)
        except Exception:
            w.kill()


def _reap_worker() -> None:
    with _lock:
        if _worker is not None and time.time() - _worker_used > WORKER_IDLE_S:
            _stop_worker()
    if _worker is not None:
        t = threading.Timer(60, _reap_worker)
        t.daemon = True
        t.start()


def _get_worker() -> subprocess.Popen:
    """The Piper worker (tts_worker.py), started on first use and stopped after WORKER_IDLE_S without use."""
    global _worker
    if _worker is None or _worker.poll() is not None:
        script = Path(__file__).with_name("tts_worker.py")
        _worker = subprocess.Popen([str(root() / "venv" / "bin" / "python"), "-I", str(script)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, bufsize=1, cwd=str(root()))
        t = threading.Timer(60, _reap_worker)
        t.daemon = True
        t.start()
    return _worker


SYNTH_TIMEOUT_S = 30                                 # one sentence (the first one also loads its model)


def synth(text: str, voice_id: str | None = None, speed: float = 1.0, lang: str | None = None) -> dict:
    """Plain text (one or a few sentences) -> {file: WAV name in out_dir(), seconds, voice}. Raises TTSError."""
    global _worker_used
    if not (root() / "venv" / "bin" / "python").is_file():
        raise TTSError(409, "tts_not_ready", "Spoken replies are not installed")
    vid = pick_voice(text, voice_id, lang)
    wav = out_dir() / f"say-{time.time_ns()}.wav"
    req = {"text": " ".join(text[:MAX_CHARS].split()), "model": str(voice_file(vid)), "out": str(wav),
           "length": round(1.0 / max(0.6, min(1.6, speed or 1.0)), 2), "speaker": VOICES[vid].get("speaker")}
    with _lock:
        _worker_used = time.time()
        for attempt in (1, 2):                       # a dead worker is started again once
            w = _get_worker()
            try:
                w.stdin.write(json.dumps(req) + "\n")  # type: ignore[union-attr]
                w.stdin.flush()                      # type: ignore[union-attr]
                # A worker that hangs never holds the lock (and every call's voice) for good
                ready, _, _ = select.select([w.stdout], [], [], SYNTH_TIMEOUT_S)
                if not ready:
                    _stop_worker()
                    raise TTSError(504, "tts_timeout", "The voice took too long to answer")
                line = w.stdout.readline()           # type: ignore[union-attr]
            except (OSError, ValueError):
                line = ""
            if line:
                break
            _stop_worker()
    try:
        out = json.loads(line or "{}")
    except ValueError:
        out = {}
    if not out.get("ok") or not wav.is_file():
        raise TTSError(500, "tts_failed", str(out.get("error") or "the voice could not be generated")[:300])
    return {"file": wav.name, "seconds": out.get("seconds") or 0, "voice": vid}
