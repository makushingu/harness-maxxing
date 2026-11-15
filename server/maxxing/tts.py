"""Spoken replies (text-to-speech) for the hands-free voice mode of a session. Experimental.

Engine: Piper (https://github.com/OHF-Voice/piper1-gpl), run as a separate program from its own virtual
environment in state_dir('voice/tts') (it is GPL: never imported into this process). Voices are ONNX files
from the rhasspy/piper-voices catalogue, downloaded next to it. All public functions are blocking: call them
from a worker thread.

What is said is not the whole answer: code blocks, tables, links and markdown are removed (`spoken_text`),
and a long answer is condensed into a few sentences by a small Claude model (`condense`).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from . import config, voice

log = logging.getLogger("maxxing.tts")

VOICES_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
# id -> path in the catalogue (language/locale/name/quality/file stem)
VOICES = {
    "fr_FR-tom-medium": "fr/fr_FR/tom/medium",
    "fr_FR-upmc-medium": "fr/fr_FR/upmc/medium",
    "fr_FR-siwis-medium": "fr/fr_FR/siwis/medium",
    "en_US-ryan-medium": "en/en_US/ryan/medium",
    "en_US-amy-medium": "en/en_US/amy/medium",
}
DEFAULT_VOICE = {"fr": "fr_FR-tom-medium", "en": "en_US-ryan-medium"}
PIPER_SPEC = "piper-tts>=1.3,<2"
MAX_CHARS = 4000            # input of one request
SHORT_CHARS = 420           # longer spoken text -> condensed
CONDENSE_MODEL = "haiku"
CONDENSE_TIMEOUT_S = 40
CONDENSE_PROMPT = (
    "You turn an assistant's written answer into what it would SAY out loud to the user, who is listening "
    "hands-free. 1 to 3 short sentences, same language as the answer, plain words: the outcome first, then any "
    "question the answer asks the user. No code, no file paths, no URLs, no lists, no markdown, no emoji. "
    "Output only the sentences."
)
KEEP_S = 600                # generated audio files are deleted after this

_lock = threading.Lock()
_install: dict = {"state": "idle"}


class TTSError(voice.VoiceError):
    pass


def root() -> Path:
    return config.state_dir("voice", "tts")


def piper_bin() -> Path:
    return root() / "venv" / "bin" / "piper"


def voice_file(vid: str) -> Path:
    return root() / "voices" / f"{vid}.onnx"


def installed_voices() -> list[str]:
    return [v for v in VOICES if voice_file(v).is_file() and voice_file(v).with_suffix(".onnx.json").is_file()]


def status() -> dict:
    ready = piper_bin().is_file() and bool(installed_voices()) and bool(voice.ffmpeg_bin())
    return {"ready": ready, "engine": "piper", "voices": installed_voices(), "catalogue": list(VOICES),
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
    want = [v for v in (voices or list(DEFAULT_VOICE.values())) if v in VOICES]
    _install.update(state="running", started=time.time(), error=None)
    try:
        if not piper_bin().is_file():
            venv = root() / "venv"
            subprocess.run([_uv(), "venv", "-q", "-p", "3.12", str(venv)], check=True, capture_output=True, timeout=300)
            subprocess.run([_uv(), "pip", "install", "-q", "-p", str(venv / "bin" / "python"), PIPER_SPEC],
                           check=True, capture_output=True, timeout=600)
        (root() / "voices").mkdir(parents=True, exist_ok=True)
        for vid in want:
            for suf in (".onnx", ".onnx.json"):
                dest = root() / "voices" / f"{vid}{suf}"
                if not dest.is_file():
                    _download(f"{VOICES_URL}/{VOICES[vid]}/{vid}{suf}", dest)
        _install.update(state="done", ended=time.time())
    except subprocess.CalledProcessError as e:
        _install.update(state="failed", error=(e.stderr or b"").decode(errors="replace")[-400:] or str(e))
    except Exception as e:  # network, disk
        _install.update(state="failed", error=str(e))
    return status()


def start_install(voices: list[str] | None = None) -> dict:
    if _install.get("state") != "running":
        threading.Thread(target=install, args=(voices,), daemon=True, name="tts-install").start()
        _install["state"] = "running"
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


def condense(text: str) -> str:
    """A long answer -> 1-3 sentences by a small Claude model; the start of the text when that fails."""
    from .sessions import spawn
    cmd = [spawn.claude_bin(), "-p", "--output-format", "json", "--model", CONDENSE_MODEL, "--tools", "",
           "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
           "--system-prompt", CONDENSE_PROMPT]
    try:
        r = subprocess.run(cmd, input=text[:MAX_CHARS], capture_output=True, text=True, timeout=CONDENSE_TIMEOUT_S,
                           cwd=config.state_dir("claude-titles"), env=spawn.claude_env(None, "default"))
        data = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
        out = str(data.get("result") or "").strip() if isinstance(data, dict) and not data.get("is_error") else ""
        if r.returncode == 0 and out:
            return spoken_text(out)
    except (subprocess.SubprocessError, OSError, ValueError):
        log.exception("condensing a spoken reply failed")
    return _cut(text, SHORT_CHARS)


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
    for f in d.glob("*.mp3"):
        try:
            if now - f.stat().st_mtime > KEEP_S:
                f.unlink()
        except OSError:
            pass
    return d


def speak(text: str, *, condensed: bool = True, voice_id: str | None = None, speed: float = 1.0) -> dict:
    """Markdown answer -> {text: what is said, file: mp3 name in out_dir(), seconds}. Raises TTSError."""
    st = status()
    if not st["ready"]:
        raise TTSError(409, "tts_not_ready", "Spoken replies are not installed")
    said = spoken_text(text[:MAX_CHARS * 3])
    if not said:
        raise TTSError(422, "nothing_to_say", "Nothing to say")
    if condensed and len(said) > SHORT_CHARS:
        said = condense(said)
    vid = voice_id if voice_id in st["voices"] else DEFAULT_VOICE.get(_lang(said))
    if vid not in st["voices"]:
        vid = st["voices"][0]
    name = f"say-{time.time_ns()}"
    wav, mp3 = out_dir() / f"{name}.wav", out_dir() / f"{name}.mp3"
    length = 1.0 / max(0.6, min(1.6, speed or 1.0))
    with _lock:
        p = subprocess.run([str(piper_bin()), "-m", str(voice_file(vid)), "-f", str(wav), "--length-scale",
                            f"{length:.2f}", "--sentence-silence", "0.25"], input=said, capture_output=True,
                           text=True, timeout=120)
    if p.returncode != 0 or not wav.is_file():
        raise TTSError(500, "tts_failed", (p.stderr or "").strip()[-300:] or "the voice could not be generated")
    q = subprocess.run([voice.ffmpeg_bin() or "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(wav),
                        "-ac", "1", "-b:a", "64k", str(mp3)], capture_output=True, text=True, timeout=120)
    try:
        import wave
        with wave.open(str(wav)) as w:
            seconds = w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        seconds = 0.0
    wav.unlink(missing_ok=True)
    if q.returncode != 0 or not mp3.is_file():
        raise TTSError(500, "tts_failed", (q.stderr or "").strip()[-300:] or "the audio could not be encoded")
    return {"text": said, "file": mp3.name, "voice": vid, "seconds": round(seconds, 1)}
