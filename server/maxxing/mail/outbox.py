"""Messages an agent wrote that wait for the owner's OK (`approve_send`, access.py).

The message is filed in the mailbox's Drafts (the owner can open it on the E-mail page, change it and send it
there) and kept in <state>/mail/outbox/<id>/ (the draft fields + attachments) with a "to do" event in the
Notifications feed: Allow sends it through the mailbox's SMTP server, Refuse drops the draft, Open shows it on the
E-mail page. The same buttons on Telegram (feed alerts). ref of the event: `mailsend:<id>` (feed.HANDLERS).
"""
from __future__ import annotations

import contextlib
import logging
import secrets
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from .. import config
from . import store
from .imap import MailError

log = logging.getLogger("maxxing.mail")

KEEP_DAYS = 14
TEXT_SHOWN = 1500


def _dir(oid: str) -> Path:
    return config.state_dir("mail") / "outbox" / oid


def _agent_name(path: str) -> str:
    try:
        from .. import agents
        return agents.load(path)["name"] or path.rsplit("/", 1)[-1]
    except Exception:  # noqa: BLE001
        return path.rsplit("/", 1)[-1]


def page_url(acc_id: str, folder: str | None, uid: int | None) -> str:
    q = f"/mail?account={quote(acc_id)}"
    if folder and uid:
        q += f"&folder={quote(folder)}&draft={int(uid)}"
    return q


def queue(acc: dict, agent: str, draft: dict, files: list[tuple[str, str, bytes]], why: str) -> dict:
    """File the agent's message in Drafts and ask the owner. -> {id, folder, uid, waiting: True}."""
    from . import send
    from .. import feed
    saved = send.save_draft(acc, draft, files)
    oid = "o_" + secrets.token_hex(6)
    d = _dir(oid)
    d.mkdir(parents=True, exist_ok=True)
    names = []
    for i, (name, ctype, data) in enumerate(files):
        (d / f"{i}.bin").write_bytes(data)
        names.append({"name": name, "type": ctype, "size": len(data)})
    data = {"draft": {k: v for k, v in draft.items() if k != "draft"}, "files": names, "saved": saved, "why": why}
    row = {"id": oid, "account": acc["id"], "agent": agent, "at": time.time(), "status": "waiting", "data": data}
    store.outbox_put(row)
    to = ", ".join((draft.get("to") or []) + (draft.get("cc") or []) + (draft.get("bcc") or []))
    text = str(draft.get("text") or "").strip()
    if len(text) > TEXT_SHOWN:
        text = text[:TEXT_SHOWN] + " [...]"
    body = f"From: {acc['address']}\nTo: {to}\nSubject: {draft.get('subject') or ''}\n"
    if names:
        body += f"Attachments: {', '.join(n['name'] for n in names)}\n"
    body += f"\n{text}"
    ev = feed.post(f"{_agent_name(agent)} wants to send an e-mail", body, level="warning", source="mail",
                   url=page_url(acc["id"], saved.get("folder"), saved.get("uid")), ref=f"mailsend:{oid}",
                   agent=agent, actions=[{"id": "allow", "label": "Send", "style": "primary"},
                                         {"id": "deny", "label": "Refuse", "style": "danger"},
                                         {"id": "open", "label": "Open", "style": "link"}])
    if ev:
        row["event_id"] = ev["id"]
        store.outbox_put(row)
    return {"id": oid, "waiting": True, **saved}


def _files(oid: str, names: list[dict]) -> list[tuple[str, str, bytes]]:
    d = _dir(oid)
    return [(n["name"], n["type"], (d / f"{i}.bin").read_bytes()) for i, n in enumerate(names)]


def _end(row: dict, resolution: str) -> None:
    from .. import feed
    if row.get("event_id"):
        with contextlib.suppress(Exception):
            feed.update(int(row["event_id"]), resolve=True, resolution=resolution, read=True)
    with contextlib.suppress(OSError):
        shutil.rmtree(_dir(row["id"]))


def _post_agent(row: dict, text: str) -> None:
    with contextlib.suppress(Exception):
        from .. import agents
        if agents.exists(row["agent"]):
            agents.post(row["agent"], "note", text, status="mail")


def approve(oid: str, by: str = "web") -> dict:
    """Send the waiting message (once). The draft it came from is dropped by the send."""
    from . import get_account, send
    row = store.outbox_get(oid)
    if not row:
        raise MailError("not_found", "no such message waiting")
    if row["status"] != "waiting":
        return row
    if not store.outbox_claim(oid, "sending"):
        return store.outbox_get(oid) or row
    data = row["data"]
    try:
        acc = get_account(row["account"])
        draft = {**data["draft"], "draft": data.get("saved") or None}
        res = send.send(acc, draft, _files(oid, data.get("files") or []))
    except (MailError, OSError) as e:
        store.outbox_set(oid, "waiting", getattr(e, "message", str(e)))   # the owner may try again
        raise
    store.add_contacts(row["account"], [send._bare(a) for k in ("to", "cc", "bcc") for a in data["draft"].get(k) or []])
    _note_sent(row["account"], row["agent"], data["draft"], "sent", f"approved ({by})")
    store.outbox_set(oid, "sent", f"by {by}")
    _end(row, "Sent")
    _post_agent(row, f"E-mail \"{data['draft'].get('subject') or ''}\" sent (the owner allowed it).")
    return {**row, "status": "sent", "result": res}


def deny(oid: str, by: str = "web") -> dict:
    """Refuse the waiting message: its draft is dropped, nothing is sent."""
    from . import get_account, send
    row = store.outbox_get(oid)
    if not row:
        raise MailError("not_found", "no such message waiting")
    if not store.outbox_claim(oid, "refused", f"by {by}"):
        return store.outbox_get(oid) or row
    with contextlib.suppress(Exception):
        send._drop_draft(get_account(row["account"]), {"draft": row["data"].get("saved")})
    _end(row, "Refused")
    _post_agent(row, f"E-mail \"{row['data']['draft'].get('subject') or ''}\" refused by the owner: not sent.")
    return {**row, "status": "refused"}


def feed_action(oid: str, action: str, by: str, ev: dict) -> None:
    """A button of the event (web or Telegram): allow / deny. Open only shows the draft."""
    from .. import feed
    try:
        if action == "allow":
            approve(oid, by)
        elif action == "deny":
            deny(oid, by)
    except MailError as e:                  # shown on the button that was clicked; the request stays open
        raise feed.FeedError(424 if e.code in ("smtp", "unreachable", "tls", "connection", "imap") else 409,
                             e.code, e.message) from None


def draft_done(acc_id: str, folder: str, uid: int, how: str) -> None:
    """The owner sent (or deleted) a waiting draft from the E-mail page: its request ends there."""
    for row in store.outbox_list("waiting", acc_id):
        saved = row["data"].get("saved") or {}
        if saved.get("folder") == folder and int(saved.get("uid") or 0) == int(uid):
            if store.outbox_claim(row["id"], how, "from the E-mail page"):
                _end(row, "Sent from the E-mail page" if how == "sent" else "Draft deleted")
                if how == "sent":
                    _note_sent(acc_id, row["agent"], row["data"]["draft"], "sent", "changed by the owner")


def _note_sent(acc_id: str, agent: str, draft: dict, what: str, detail: str) -> None:
    rep = draft.get("reply") or {}
    if draft.get("in_reply_to"):
        store.note(acc_id, store.mkey(draft["in_reply_to"]), agent, "replied" if what == "sent" else what, detail)
    elif rep.get("uid"):
        store.note(acc_id, store.mkey(None, rep.get("folder") or "INBOX", int(rep["uid"])), agent, what, detail)


def pending(acc_id: str | None = None) -> list[dict]:
    out = []
    for r in store.outbox_list("waiting", acc_id):
        d = r["data"]["draft"]
        out.append({"id": r["id"], "account": r["account"], "agent": r["agent"], "agent_name": _agent_name(r["agent"]),
                    "at": r["at"], "to": d.get("to") or [], "cc": d.get("cc") or [], "subject": d.get("subject") or "",
                    "text": str(d.get("text") or "")[:4000], "files": r["data"].get("files") or [],
                    "draft": r["data"].get("saved") or None, "why": r["data"].get("why") or "",
                    "event_id": r.get("event_id"), "note": r.get("note") or ""})
    return out


def tidy() -> None:
    """Old decided rows and their files go."""
    cutoff = time.time() - KEEP_DAYS * 86400
    with store.conn() as c:
        old = [r[0] for r in c.execute("SELECT id FROM outbox WHERE status!='waiting' AND COALESCE(done_at, at)<?",
                                       (cutoff,))]
        c.execute("DELETE FROM outbox WHERE status!='waiting' AND COALESCE(done_at, at)<?", (cutoff,))
    for oid in old:
        with contextlib.suppress(OSError):
            shutil.rmtree(_dir(oid))

