"""Voice messages (speech-to-text). See docs/dev/API.md#voice and maxxing/voice.py."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import config, voice
from ..security import require_auth
from ..voice import VoiceError

log = logging.getLogger("maxxing.api.voice")

router = APIRouter(prefix="/api/voice", tags=["voice"], dependencies=[Depends(require_auth)])

_EXT = {"audio/webm": ".webm", "video/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a",
        "video/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
        "audio/x-m4a": ".m4a", "audio/aac": ".aac", "audio/flac": ".flac"}


def _http(e: VoiceError) -> HTTPException:
    return HTTPException(e.status, detail={"error": e.code, "message": e.message})


class SettingsIn(BaseModel):
    engine: Optional[Literal["off", "local", "groq", "openai"]] = None
    model: Optional[Literal["tiny", "base", "small", "medium"]] = None
    language: Optional[str] = None
    auto_send: Optional[bool] = None
    direct: Optional[bool] = None
    mic: Optional[bool] = None
    call: Optional[bool] = None


class InstallIn(BaseModel):
    model: Optional[Literal["tiny", "base", "small", "medium"]] = None


async def startup() -> None:
    """Voice messages sent directly whose transcription was cut by a restart: start it again."""
    from ..sessions import voicejobs
    try:
        n = await asyncio.to_thread(voicejobs.resume)
        if n:
            log.info("relaunched %d voice transcription(s)", n)
    except Exception:
        log.exception("relaunching the voice transcriptions failed")


@router.get("")
async def get_voice():
    return await asyncio.to_thread(voice.status)


@router.put("/settings")
async def put_settings(body: SettingsIn):
    try:
        s = await asyncio.to_thread(voice.update_settings, **body.model_dump(exclude_none=True))
    except VoiceError as e:
        raise _http(e) from None
    return {"ok": True, "settings": s}


@router.post("/install")
async def install(body: InstallIn | None = None):
    try:
        return await asyncio.to_thread(voice.start_install, body.model if body else None)
    except VoiceError as e:
        raise _http(e) from None


@router.delete("/models/{name}")
async def delete_model(name: str):
    try:
        await asyncio.to_thread(voice.delete_model, name)
    except VoiceError as e:
        raise _http(e) from None
    return {"ok": True}


def _ext(up: UploadFile) -> str:
    ct = (up.content_type or "").split(";")[0].strip().lower()
    suf = Path(up.filename or "").suffix.lower()
    if suf and len(suf) <= 6 and suf[1:].isalnum():
        return suf
    return _EXT.get(ct, ".bin")


def _save(up: UploadFile, dest: Path) -> int:
    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = up.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > voice.MAX_UPLOAD_BYTES:
                raise VoiceError(413, "too_large", f"audio larger than {voice.MAX_UPLOAD_BYTES // 1024 // 1024} MB")
            out.write(chunk)
    if size == 0:
        raise VoiceError(422, "empty_audio", "the recording is empty")
    return size


def _topic_folder(topic: str) -> Path:
    from .. import workspace
    if not topic:                                      # "/" would be the workspace root, not a topic
        raise VoiceError(400, "bad_path", "path must be a topic")
    try:
        return workspace.topic_dir(topic) / "attachments" / "voice" / time.strftime("%Y-%m")
    except ValueError as e:
        raise VoiceError(400, "bad_path", str(e)) from None


def _keep(tmp: Path, topic: str, ext: str) -> str:
    """Copy the original audio to <topic>/attachments/voice/YYYY-MM/voice-YYYYMMDD-HHMMSS<ext>."""
    folder = _topic_folder(topic)
    folder.mkdir(parents=True, exist_ok=True)
    base = f"voice-{time.strftime('%Y%m%d-%H%M%S')}"
    dest, n = folder / f"{base}{ext}", 1
    while True:                                        # exclusive create: two recordings in the same second never share a file
        try:
            out = open(dest, "xb")
            break
        except FileExistsError:
            dest, n = folder / f"{base}-{n}{ext}", n + 1
    with out, open(tmp, "rb") as src:
        shutil.copyfileobj(src, out)
    return str(dest)


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), path: Optional[str] = Form(None),
                     language: Optional[str] = Form(None)):
    ext = _ext(audio)
    tmp_dir = config.state_dir("voice", "tmp")
    tmp = tmp_dir / f"in-{time.time_ns()}{ext}"
    try:
        await asyncio.to_thread(_save, audio, tmp)
        if path is not None:                           # refuse a bad topic before the (paid) transcription, not after
            await asyncio.to_thread(_topic_folder, path.strip("/"))
        out = await asyncio.to_thread(voice.transcribe_file, tmp, language or None)
        out["audio_path"] = None
        if path is not None:
            out["audio_path"] = await asyncio.to_thread(_keep, tmp, path.strip("/"), ext)
        return out
    except VoiceError as e:
        raise _http(e) from None
    finally:
        tmp.unlink(missing_ok=True)


# ---- voice mode (a voice talks, the session works; see maxxing/voicecall.py) -------------------------------------
class TTSInstallIn(BaseModel):
    voices: Optional[list[str]] = None


class CallSettingsIn(BaseModel):
    mode: Optional[Literal["local", "cloud"]] = None
    provider: Optional[Literal["openai", "gemini", ""]] = None
    openai_key: Optional[str] = None
    gemini_key: Optional[str] = None
    openai_model: Optional[str] = None
    openai_voice: Optional[str] = None
    gemini_model: Optional[str] = None
    gemini_voice: Optional[str] = None
    talker_model: Optional[Literal["haiku", "sonnet"]] = None
    local_voice: Optional[str] = None
    local_speed: Optional[float] = None
    silence_ms: Optional[int] = None


class CallStartIn(BaseModel):
    session: str
    language: str | None = Field(default=None, max_length=12)   # the interface language of the browser
    resume: str | None = Field(default=None, max_length=4000)  # cloud: a new token for the same call (reconnection)


@router.get("/tts")
async def get_tts():
    from .. import tts
    return await asyncio.to_thread(tts.status)


@router.post("/tts/install")
async def tts_install(body: TTSInstallIn | None = None):
    from .. import tts
    return await asyncio.to_thread(tts.start_install, body.voices if body else None)


@router.get("/said/{name}")
async def said(name: str):
    from fastapi.responses import FileResponse
    from .. import tts
    if not re.fullmatch(r"say-\d+\.wav", name):
        raise HTTPException(404)
    f = tts.out_dir() / name
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/wav", headers={"Cache-Control": "private, max-age=600"})


@router.get("/call")
async def call_status():
    from .. import voicecall
    return await asyncio.to_thread(voicecall.status)


@router.put("/call/settings")
async def call_settings(body: CallSettingsIn):
    from .. import voicecall
    changes = body.model_dump(exclude_unset=True)
    if changes.get("provider") == "":
        changes["provider"] = None
    try:
        await asyncio.to_thread(voicecall.update_settings, **changes)
    except VoiceError as e:
        raise _http(e) from None
    return await asyncio.to_thread(voicecall.status)


@router.post("/call/start")
async def call_start(body: CallStartIn):
    """Local voice: starts the talker of this session's call. Cloud voice: a short-lived token for the browser."""
    from .. import voicecall
    try:
        mode = (await asyncio.to_thread(voicecall.settings))["mode"]
        if mode == "cloud":
            out = await asyncio.to_thread(voicecall.cloud_token, body.resume)
            return {"mode": "cloud", **out}
        return await asyncio.to_thread(voicecall.start_local, body.session, body.language)
    except VoiceError as e:
        raise _http(e) from None


class CallSortIn(BaseModel):
    text: str = Field(max_length=10_000)
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}$")
    expecting: bool = False


@router.post("/call/sort")
async def call_sort(body: CallSortIn):
    """Cloud voice: what a sentence transcribed by the provider is (as /hear), and the call's language after it."""
    from .. import voicecall
    kind, language = voicecall.sort(body.text, body.language, body.expecting)
    return {"kind": kind, "language": language}


def _cid(cid: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{12}", cid):
        raise HTTPException(404)


@router.post("/call/{cid}/turn")
async def call_turn(cid: str, audio: Optional[UploadFile] = File(None), text: Optional[str] = Form(None),
                    event: Optional[str] = Form(None), outcome: str = Form("answer"),
                    note: Optional[str] = Form(None), tool: Optional[str] = Form(None),
                    context: Optional[str] = Form(None), busy: bool = Form(False),
                    saying: Optional[str] = Form(None)):
    """One exchange of a local call, streamed as NDJSON lines: {heard, kind, language}, {action}, {say, url,
    seconds}, {error, code}, {language}, {done, empty?}."""
    from fastapi.responses import StreamingResponse
    from .. import voicecall
    _cid(cid)
    if outcome not in ("answer", "failed", "done", "progress"):
        raise HTTPException(400, "outcome must be answer, failed, done or progress")
    tmp: Path | None = None
    if audio is not None:
        tmp = config.state_dir("voice", "tmp") / f"call-{time.time_ns()}{_ext(audio)}"
        try:
            size = await asyncio.to_thread(_save, audio, tmp)
            if size > voicecall.MAX_AUDIO_BYTES:
                raise VoiceError(413, "too_large", "audio too long")
        except VoiceError as e:
            tmp.unlink(missing_ok=True)
            raise _http(e) from None

    def lines():
        try:
            for item in voicecall.local_turn(cid, audio=tmp, text=text, event=event, outcome=outcome,
                                             note=(note or "")[:3000], tool=(tool or "")[:120],
                                             context=(context or "")[:1000], busy=busy,
                                             saying=(saying or "")[:2000]):
                yield json.dumps(item, ensure_ascii=False) + "\n"
        except VoiceError as e:
            yield json.dumps({"error": e.message, "code": e.code}, ensure_ascii=False) + "\n"
        except Exception as e:  # never cut the stream without a word
            log.exception("voice call turn failed")
            yield json.dumps({"error": str(e) or "failed", "code": "failed"}) + "\n"
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/call/{cid}/end")
async def call_end(cid: str):
    from .. import voicecall
    await asyncio.to_thread(voicecall.end_local, cid)
    return {"ok": True}
