"""E-mail page (Settings -> Features -> mail_page): IMAP/SMTP accounts, folders, messages, flags and moves.
Every IMAP call runs in a thread (imaplib blocks). See docs/dev/API.md#mail."""
from __future__ import annotations

import asyncio
import json
from typing import Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import mail
from ..mail import imap, send
from ..mail.imap import MailError
from ..security import require_auth

router = APIRouter(prefix="/api/mail", tags=["mail"], dependencies=[Depends(require_auth)])

STATUS = {"no_account": 404, "not_found": 404, "no_folder": 404, "exists": 409, "invalid": 400, "too_large": 413,
          "no_password": 409, "auth": 422, "limit": 429, "refused": 422,
          # the mail server failed, not ours: 424, never a 5xx (a proxy such as Cloudflare may hide a 502 body)
          "smtp": 424, "unreachable": 424, "tls": 424, "connection": 424, "imap": 424}


def _need_on() -> None:
    if not mail.enabled():
        raise HTTPException(409, detail={"error": "disabled", "message": "turn the E-mail page on in Settings -> Features"})


def _err(e: MailError) -> HTTPException:
    return HTTPException(STATUS.get(e.code, 400), detail={"error": e.code, "message": e.message})


async def _run(fn, *args, **kw):
    _need_on()
    try:
        return await asyncio.to_thread(fn, *args, **kw)
    except MailError as e:
        raise _err(e) from None


def _acc(acc_id: str) -> dict:
    try:
        return mail.get_account(acc_id)
    except MailError as e:
        raise _err(e) from None


Tls = Literal["ssl", "starttls", "none"]


class AccountIn(BaseModel):
    address: str
    password: str = Field(min_length=1, max_length=1024)
    label: str = ""
    name: str = ""
    username: Optional[str] = None
    imap_host: str
    imap_port: int = 993
    imap_tls: Tls = "ssl"
    smtp_host: str
    smtp_port: int = 465
    smtp_tls: Tls = "ssl"
    signature: str = ""


class AccountPatch(BaseModel):
    password: Optional[str] = Field(default=None, max_length=1024)
    label: Optional[str] = None
    name: Optional[str] = None
    username: Optional[str] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_tls: Optional[Tls] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_tls: Optional[Tls] = None
    signature: Optional[str] = None


class DetectIn(BaseModel):
    address: str


class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent: Optional[str] = None


class RenameIn(BaseModel):
    name: str
    new_name: str = Field(min_length=1, max_length=200)


class ActionIn(BaseModel):
    folder: str = "INBOX"
    uids: list[int] = Field(min_length=1, max_length=1000)
    action: Literal[imap.ACTIONS]  # type: ignore[valid-type]
    target: Optional[str] = None


@router.get("/accounts")
async def get_accounts():
    _need_on()
    cap = send.per_day()
    return [{**mail.public(a), "sent_today": send.sent_today(a["id"]), "send_per_day": cap} for a in mail.list_accounts()]


@router.post("/detect")
async def post_detect(body: DetectIn):
    return await _run(mail.detect, body.address)


@router.post("/accounts")
async def post_account(body: AccountIn):
    data = body.model_dump(exclude={"password"})
    if not data.get("username"):
        data["username"] = body.address.strip()
    acc, result = await _run(mail.add_account, data, body.password)
    return {"account": mail.public(acc), "test": result}


@router.patch("/accounts/{acc_id}")
async def patch_account(acc_id: str, body: AccountPatch):
    data = body.model_dump(exclude={"password"}, exclude_none=True)
    acc, result = await _run(mail.update_account, acc_id, data, body.password or None)
    return {"account": mail.public(acc), "test": result}


@router.delete("/accounts/{acc_id}")
async def delete_account(acc_id: str):
    await _run(mail.delete_account, acc_id)
    return {"ok": True}


@router.post("/accounts/{acc_id}/test")
async def test_account(acc_id: str):
    from .. import vault
    acc = _acc(acc_id)
    return await _run(mail.test, acc, vault.get(acc.get("password_key") or "") or "")


@router.get("/{acc_id}/folders")
async def get_folders(acc_id: str, counts: bool = True):
    return await _run(imap.folders, _acc(acc_id), counts)


@router.post("/{acc_id}/folders")
async def post_folder(acc_id: str, body: FolderIn):
    return {"name": await _run(imap.create_folder, _acc(acc_id), body.name, body.parent)}


@router.put("/{acc_id}/folders")
async def rename_folder(acc_id: str, body: RenameIn):
    return {"name": await _run(imap.rename_folder, _acc(acc_id), body.name, body.new_name)}


@router.delete("/{acc_id}/folders")
async def delete_folder(acc_id: str, name: str):
    await _run(imap.delete_folder, _acc(acc_id), name)
    return {"ok": True}


@router.get("/{acc_id}/messages")
async def get_messages(acc_id: str, folder: str = "INBOX", page: int = 0, size: int = imap.PAGE, q: str = "",
                       unread: bool = False, flagged: bool = False):
    return await _run(imap.messages, _acc(acc_id), folder, max(0, page), size, q or None, unread, flagged)


@router.get("/{acc_id}/message")
async def get_message(acc_id: str, uid: int, folder: str = "INBOX", seen: bool = True):
    return await _run(imap.message, _acc(acc_id), folder, uid, seen)


@router.get("/{acc_id}/attachment")
async def get_attachment(acc_id: str, uid: int, index: int, folder: str = "INBOX", inline: bool = False):
    name, ctype, data = await _run(imap.attachment, _acc(acc_id), folder, uid, index)
    # only images and PDF open in the browser; everything else downloads (an HTML attachment never renders here)
    safe_inline = inline and (ctype.startswith("image/") and ctype != "image/svg+xml" or ctype == "application/pdf")
    disp = "inline" if safe_inline else "attachment"
    return Response(data, media_type=ctype if safe_inline else "application/octet-stream", headers={
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(name)}",
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.post("/{acc_id}/actions")
async def post_action(acc_id: str, body: ActionIn):
    return await _run(imap.act, _acc(acc_id), body.folder, body.uids, body.action, body.target)


@router.get("/{acc_id}/compose")
async def get_compose(acc_id: str, mode: str, uid: int, folder: str = "INBOX"):
    """The prefilled fields of a reply, reply all, forward, or of a draft opened again."""
    return await _run(send.compose, _acc(acc_id), mode, folder, uid)


MAX_FILES = 30


async def _draft_and_files(data: str, files: list[UploadFile]) -> tuple[dict, list[tuple[str, str, bytes]]]:
    try:
        draft = json.loads(data)
        assert isinstance(draft, dict)
    except (ValueError, AssertionError):
        raise HTTPException(400, detail={"error": "invalid", "message": "data: a JSON object"}) from None
    if len(files) > MAX_FILES:
        raise HTTPException(400, detail={"error": "invalid", "message": f"at most {MAX_FILES} attachments"})
    out, total = [], 0
    for f in files:
        b = await f.read(send.MAX_ATTACH + 1)
        total += len(b)
        if total > send.MAX_ATTACH:
            raise HTTPException(413, detail={"error": "too_large", "message": "attachments larger than 25 MB in total"})
        out.append((f.filename or "attachment", f.content_type or "", b))
    return draft, out


@router.post("/{acc_id}/send")
async def post_send(acc_id: str, data: str = Form(...), files: list[UploadFile] = File(default=[])):
    """multipart: `data` = JSON {to, cc, bcc, subject, text, in_reply_to, references, reply: {folder, uid},
    forward: {folder, uid, indexes}, draft: {folder, uid}} + `files` (attachments)."""
    _need_on()
    draft, fs = await _draft_and_files(data, files)
    return await _run(send.send, _acc(acc_id), draft, fs)


@router.post("/{acc_id}/draft")
async def post_draft(acc_id: str, data: str = Form(...), files: list[UploadFile] = File(default=[])):
    """Same body as /send: files the message in Drafts (replacing `draft` when given). Returns {folder, uid}."""
    _need_on()
    draft, fs = await _draft_and_files(data, files)
    return await _run(send.save_draft, _acc(acc_id), draft, fs)
