"""Voice messages (speech-to-text). See docs/dev/API.md#voice and maxxing/voice.py."""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

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


def _keep(tmp: Path, topic: str, ext: str) -> str:
    """Copy the original audio to <topic>/attachments/voice/YYYY-MM/voice-YYYYMMDD-HHMMSS<ext>."""
    from .. import workspace
    try:
        folder = workspace.topic_dir(topic) / "attachments" / "voice" / time.strftime("%Y-%m")
    except ValueError as e:
        raise VoiceError(400, "bad_path", str(e)) from None
    folder.mkdir(parents=True, exist_ok=True)
    base = f"voice-{time.strftime('%Y%m%d-%H%M%S')}"
    dest, n = folder / f"{base}{ext}", 1
    while dest.exists():
        dest, n = folder / f"{base}-{n}{ext}", n + 1
    shutil.copyfile(tmp, dest)
    return str(dest)


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), path: Optional[str] = Form(None),
                     language: Optional[str] = Form(None)):
    ext = _ext(audio)
    tmp_dir = config.state_dir("voice", "tmp")
    tmp = tmp_dir / f"in-{time.time_ns()}{ext}"
    try:
        await asyncio.to_thread(_save, audio, tmp)
        out = await asyncio.to_thread(voice.transcribe_file, tmp, language or None)
        out["audio_path"] = None
        if path is not None:
            out["audio_path"] = await asyncio.to_thread(_keep, tmp, path.strip("/"), ext)
        return out
    except VoiceError as e:
        raise _http(e) from None
    finally:
        tmp.unlink(missing_ok=True)
