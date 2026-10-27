"""Team chats (Settings -> Features -> team_page). See docs/dev/API.md#team and maxxing/team.py."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import team, teampeer
from ..security import require_auth
from ..sessions import service
from ..sessions.service import SessionError
from .sessions import save_upload

router = APIRouter(prefix="/api/team", tags=["team"], dependencies=[Depends(require_auth)])


async def _call(fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args, **kw)
    except team.TeamError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None
    except SessionError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None
    except teampeer.PeerError as e:
        raise HTTPException(e.status, detail={"error": e.code, "message": e.message}) from None


async def startup() -> None:
    teampeer.start()        # the outbox worker (idle while nothing is queued)


class ChatIn(BaseModel):
    kind: Literal["dm", "group"]
    members: list[str]
    name: str = ""
    emoji: str = ""


class FileIn(BaseModel):
    path: str


class MessageIn(BaseModel):
    text: str = ""
    reply_to: Optional[str] = None
    files: list[FileIn] = Field(default_factory=list)


class ReactIn(BaseModel):
    emoji: str


class PollIn(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)
    multi: bool = False


class VoteIn(BaseModel):
    option: str


class SummarizeIn(BaseModel):
    ids: Optional[list[str]] = None
    since: Optional[float] = None


class ForwardIn(BaseModel):
    """The (edited) text goes to `session`, or to a new session in the topic `path`."""
    text: str
    session: Optional[str] = None
    path: Optional[str] = None
    title: Optional[str] = None


@router.get("")
async def get_state():
    return await _call(team.state)


@router.post("/chats")
async def create_chat(body: ChatIn):
    return await _call(team.create_chat, body.kind, body.members, body.name, body.emoji)


@router.get("/chats/{cid}")
async def get_chat(cid: str):
    return await _call(team.messages, cid)


@router.post("/chats/{cid}/read")
async def read(cid: str):
    await _call(team.mark_read, cid)
    return {"ok": True}


class EditIn(BaseModel):
    text: str


class GroupIn(BaseModel):
    name: Optional[str] = None
    emoji: Optional[str] = None
    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class MuteIn(BaseModel):
    muted: bool


@router.post("/presence")
async def presence():
    """The UI is open (sent every few minutes while visible): contacts see the user online."""
    await asyncio.to_thread(teampeer.presence)
    return {"ok": True}


@router.post("/chats/{cid}/messages/{mid}/edit")
async def edit(cid: str, mid: str, body: EditIn):
    return await _call(team.edit_message, cid, mid, body.text)


@router.post("/chats/{cid}/messages/{mid}/delete")
async def delete(cid: str, mid: str):
    return await _call(team.delete_message, cid, mid)


@router.post("/chats/{cid}/group")
async def group(cid: str, body: GroupIn):
    return await _call(team.update_group, cid, body.name, body.emoji, body.add, body.remove)


@router.post("/chats/{cid}/leave")
async def leave(cid: str):
    return await _call(team.leave_group, cid)


@router.post("/chats/{cid}/mute")
async def mute(cid: str, body: MuteIn):
    return await _call(team.set_muted, cid, body.muted)


@router.post("/chats/{cid}/typing")
async def typing(cid: str):
    await _call(team.typing, cid)
    return {"ok": True}


@router.post("/chats/{cid}/messages")
async def send(cid: str, body: MessageIn):
    return await _call(team.send, cid, body.text, body.reply_to, [f.model_dump() for f in body.files])


@router.post("/files")
async def upload(file: list[UploadFile] = File(...)):
    """Files for a message (then sent with POST /chats/{cid}/messages `files`)."""
    folder = await _call(team.files_dir)
    return {"files": [await asyncio.to_thread(save_upload, f, folder) for f in file]}


@router.post("/chats/{cid}/messages/{mid}/react")
async def react(cid: str, mid: str, body: ReactIn):
    return await _call(team.react, cid, mid, body.emoji)


@router.post("/chats/{cid}/polls")
async def poll(cid: str, body: PollIn):
    return await _call(team.create_poll, cid, body.question, body.options, body.multi)


@router.post("/chats/{cid}/messages/{mid}/vote")
async def vote(cid: str, mid: str, body: VoteIn):
    return await _call(team.vote, cid, mid, body.option)


@router.post("/chats/{cid}/summarize")
async def summarize(cid: str, body: SummarizeIn):
    return await _call(team.summarize, cid, body.ids, body.since)


@router.post("/chats/{cid}/messages/{mid}/forward")
async def forward(cid: str, mid: str, body: ForwardIn):
    """A chat message to a session (a human click, never automatic): sent as a normal web message, with the
    message's files as attachments."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, detail={"error": "empty", "message": "Empty message"})
    found = [m for m in (await _call(team.messages, cid))["messages"] if m["id"] == mid]
    if not found:                                   # checked before anything reaches the session
        raise HTTPException(404, detail={"error": "not_found", "message": "Message not found"})
    files = [f["path"] for f in found[0].get("files") or [] if f.get("path")]   # not a file still downloading / failed
    if body.session:
        r = await _call(service.send_message, body.session, text, files, "web")
        s = r["session"]
    elif body.path:
        s = await _call(service.create_session, body.path.strip("/"), message=text, title=body.title or None,
                        attachments=files, source="web")
    else:
        raise HTTPException(400, detail={"error": "no_target", "message": "session or path"})
    msg = await _call(team.mark_sent, cid, mid, s["id"], s.get("title") or "")
    return {"session": s, "message": msg}


# ---- connections with other servers ---------------------------------------------------------------------------
class JoinIn(BaseModel):
    invitation: str


class AnswerIn(BaseModel):
    address: str
    accept: bool


class AddressIn(BaseModel):
    address: str


@router.get("/connections")
async def connections():
    return await _call(teampeer.connections)


@router.post("/connections/invite")
async def invite():
    return await _call(teampeer.create_invite)


@router.post("/connections/join")
async def join(body: JoinIn):
    return await _call(teampeer.join, body.invitation)


@router.post("/connections/answer")
async def answer(body: AnswerIn):
    return await _call(teampeer.answer, body.address, body.accept)


@router.post("/connections/remove")
async def remove(body: AddressIn):
    await _call(teampeer.forget, body.address)
    return {"ok": True}
