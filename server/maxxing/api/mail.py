"""E-mail page (Settings -> Features -> mail_page): IMAP/SMTP accounts, folders, messages, flags and moves.
Every IMAP/SMTP call runs in a thread of its own small pool (imaplib blocks): a slow or silent mail server then never
holds the threads the rest of the server shares (sign-in, approvals...). See docs/dev/API.md#mail."""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import contextvars
import functools
import json
import logging
import time
from typing import Literal, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import mail
from ..mail import imap, outbox, poll, send, store
from ..mail.imap import MailError
from ..security import require_auth

log = logging.getLogger("maxxing.mail")
router = APIRouter(prefix="/api/mail", tags=["mail"], dependencies=[Depends(require_auth)])

STATUS = {"no_account": 404, "not_found": 404, "no_folder": 404, "exists": 409, "invalid": 400, "too_large": 413,
          "no_password": 409, "changed": 409, "auth": 422, "limit": 429, "refused": 422, "forbidden": 403,
          # the mail server failed, not ours: 424, never a 5xx (a proxy such as Cloudflare may hide a 502 body);
          # mail_busy: 503 + Retry-After, the mailbox is held by another request (Cloudflare passes a 503 through)
          "smtp": 424, "unreachable": 424, "tls": 424, "connection": 424, "imap": 424,
          "mail_busy": 503}

MAIL_THREADS = 8        # one stuck account holds at most 1 + imap.MAX_WAITING of them
_pool = concurrent.futures.ThreadPoolExecutor(MAIL_THREADS, thread_name_prefix="mail")


async def _in_pool(fn, *args, **kw):
    """asyncio.to_thread, on the mail pool."""
    ctx = contextvars.copy_context()
    return await asyncio.get_running_loop().run_in_executor(_pool, functools.partial(ctx.run, fn, *args, **kw))


def _need_on() -> None:
    if not mail.enabled():
        raise HTTPException(409, detail={"error": "disabled", "message": "turn the E-mail page on in Settings -> Features"})


def _err(e: MailError) -> HTTPException:
    return HTTPException(STATUS.get(e.code, 400), detail={"error": e.code, "message": e.message},
                         headers={"Retry-After": "10"} if e.code == "mail_busy" else None)


async def _run(fn, *args, **kw):
    _need_on()
    try:
        return await _in_pool(fn, *args, **kw)
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
    poll_min: Optional[int] = None
    auth_servers: Optional[list[str]] = Field(default=None, max_length=10)


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

    def rows() -> list[dict]:               # mail.db, agents' files, maybe an MX lookup: off the event loop
        cap = send.per_day()
        return [{**mail.public(a), "sent_today": send.sent_today(a["id"]), "send_per_day": cap,
                 "agents": poll.grants_of(a["id"]), "waiting": len(outbox.pending(a["id"]))} for a in mail.list_accounts()]
    return await asyncio.to_thread(rows)


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
    res = await _run(imap.messages, _acc(acc_id), folder, max(0, page), size, q or None, unread, flagged)
    await asyncio.to_thread(_seen_by, acc_id, folder, res["messages"])
    return res


def _agent_card(path: str, cache: dict) -> dict:
    if path not in cache:
        from .. import agents
        try:
            a = agents.load(path)
            cache[path] = {"name": a["name"] or path.rsplit("/", 1)[-1], "avatar": a["avatar"],
                           "exists": agents.exists(path)}
        except Exception:  # noqa: BLE001
            cache[path] = {"name": path.rsplit("/", 1)[-1], "avatar": None, "exists": False}
    return cache[path]


def _seen_by(acc_id: str, folder: str, rows: list[dict]) -> None:
    """Each row gets `seen_by`: what the agents did with it (mail.db, never written to the mailbox)."""
    keys = {store.mkey(r.get("message_id"), folder, r.get("uid")): r for r in rows}
    try:
        got = store.seen_by(acc_id, list(keys))
    except Exception:  # noqa: BLE001 - the cache is optional
        log.exception("mail.db unreadable")
        got = {}
    cache: dict = {}
    for k, r in keys.items():
        r["seen_by"] = [{**e, **_agent_card(e["agent"], cache)} for e in got.get(k, [])]


@router.get("/{acc_id}/message")
async def get_message(acc_id: str, uid: int, folder: str = "INBOX", seen: bool = True):
    m = await _run(imap.message, _acc(acc_id), folder, uid, seen)
    m.pop("auth", None)
    await asyncio.to_thread(_seen_by, acc_id, folder, [m])
    return m


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
    res = await _run(imap.act, _acc(acc_id), body.folder, body.uids, body.action, body.target)
    if body.action in ("delete", "trash"):
        for u in body.uids:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(outbox.draft_done, acc_id, body.folder, u, "deleted")
    return res


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
    res = await _run(send.send, _acc(acc_id), draft, fs)
    d = draft.get("draft") or {}
    if d.get("uid"):                                    # a draft an agent wrote, sent by the owner from the page
        with contextlib.suppress(Exception):
            await asyncio.to_thread(outbox.draft_done, acc_id, str(d.get("folder") or ""), int(d["uid"]), "sent")
    return res


@router.post("/{acc_id}/draft")
async def post_draft(acc_id: str, data: str = Form(...), files: list[UploadFile] = File(default=[])):
    """Same body as /send: files the message in Drafts (replacing `draft` when given). Returns {folder, uid}."""
    _need_on()
    draft, fs = await _draft_and_files(data, files)
    res = await _run(send.save_draft, _acc(acc_id), draft, fs)
    d = draft.get("draft") or {}
    if d.get("uid"):                                    # an agent's waiting draft changed by the owner: its request follows
        with contextlib.suppress(Exception):
            await asyncio.to_thread(outbox.draft_saved, acc_id, {"folder": str(d.get("folder") or ""), "uid": int(d["uid"])}, res)
    return res


# ---------------------------------------------------------------- checks, all mailboxes, the agents' outbox

class RefreshIn(BaseModel):
    account: Optional[str] = None


@router.post("/refresh")
async def post_refresh(body: RefreshIn = RefreshIn()):
    """Check one mailbox (or all) now: new mail starts the agents watching it."""
    _need_on()
    accs = [_acc(body.account)] if body.account else mail.list_accounts()
    out = []
    for a in accs:
        try:
            out.append(await _in_pool(poll.poll_account, a))
        except MailError as e:
            out.append({"account": a["id"], "ok": False, "error": e.message, "new": 0, "started": 0})
        except Exception:  # noqa: BLE001 - one mailbox never fails the others
            log.exception("mail: check of %s failed", a["id"])
            out.append({"account": a["id"], "ok": False, "error": "the check failed (see the server log)", "new": 0,
                        "started": 0})
    return out


@router.get("/all")
async def get_all(limit: int = 100, before: Optional[float] = None):
    """The newest mails of every mailbox, as the last checks saw them (not live)."""
    _need_on()
    accs = {a["id"]: a for a in mail.list_accounts()}
    rows = await asyncio.to_thread(store.recent, list(accs), max(1, min(500, limit)), before)
    by: dict[str, list[dict]] = {}
    out = []
    for r in rows:
        m = {"account": r["account"], "address": accs[r["account"]]["address"], "folder": r["folder"], "uid": r["uid"],
             "message_id": r["message_id"], "from": {"email": r["from_email"], "name": r["from_name"]},
             "from_verified": bool(r["verified"]), "subject": r["subject"], "date": r["date"], "snippet": r["snippet"],
             "seen": bool(r["seen"]), "attachments": bool(r["attachments"])}
        by.setdefault(f"{r['account']}\0{r['folder']}", []).append(m)
        out.append(m)

    def notes() -> dict:
        for k, ms in by.items():
            acc_id, folder = k.split("\0", 1)
            _seen_by(acc_id, folder, ms)
        return {a: store.last_check(a) for a in accs}
    return {"messages": out, "checks": await asyncio.to_thread(notes)}


@router.get("/outbox")
async def get_outbox(account: Optional[str] = None):
    """Messages written by agents waiting for the owner's OK."""
    _need_on()
    rows = await asyncio.to_thread(outbox.pending, account)
    cache: dict = {}
    return [{**r, "avatar": _agent_card(r["agent"], cache)["avatar"]} for r in rows]


@router.post("/outbox/{oid}/{action}")
async def post_outbox(oid: str, action: Literal["send", "deny"]):
    _need_on()
    fn = outbox.approve if action == "send" else outbox.deny
    r = await _run(fn, oid, "web")
    return {"id": oid, "status": r.get("status")}


_task: Optional[asyncio.Task] = None


async def _loop() -> None:
    last_tidy = 0.0
    while True:
        await asyncio.sleep(poll.TICK_S)
        try:
            if not mail.enabled():
                continue
            await asyncio.to_thread(outbox.unstick)
            await _in_pool(poll.poll_due)
            now = time.time()
            if now - last_tidy > 86400:
                last_tidy = now
                await asyncio.to_thread(outbox.tidy)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("mail loop")


async def startup() -> None:
    global _task
    _task = asyncio.get_running_loop().create_task(_loop())


async def shutdown() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
        _task = None
