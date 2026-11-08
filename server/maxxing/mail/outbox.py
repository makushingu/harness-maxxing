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
TEXT_SHOWN = 1500                                   # in the Notifications / Telegram card
TEXT_PAGE = 100_000                                 # on the mail page


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
    cut = len(text) > TEXT_SHOWN
    if cut:
        text = text[:TEXT_SHOWN] + " [...]\n\n(Longer than shown: open it to read it all before sending it.)"
    body = f"From: {acc['address']}\nTo: {to}\nSubject: {draft.get('subject') or ''}\n"
    fwd = draft.get("forward") or {}
    fnames = list(fwd.get("names") or [])
    fnames += [f"part {i}" for i in (fwd.get("indexes") or [])[len(fnames):]]
    shown = [n["name"] for n in names] + [f"{x} (forwarded)" for x in fnames]
    if shown:                                       # every file that goes out, the forwarded ones too
        body += f"Attachments ({len(shown)}): {', '.join(shown)}\n"
    body += f"\n{text}"
    ev = feed.post(f"{_agent_name(agent)} wants to send an e-mail", body, level="warning", source="mail",
                   url=page_url(acc["id"], saved.get("folder"), saved.get("uid")), ref=f"mailsend:{oid}",
                   agent=agent, actions=([] if cut else [{"id": "allow", "label": "Send", "style": "primary"}])
                   # a cut text is never sent in one tap: the owner reads it all first (the mail page sends it)
                   + [{"id": "deny", "label": "Refuse", "style": "danger"},
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


def _mark(oid: str, status: str) -> None:
    """Written as soon as the SMTP server has the message (send.send `on_sent`), outside mail.db: if what follows
    fails (mail.db locked, the server stops during the Sent copy), `unstick` and `approve` read it and never offer
    the message again. "sent" or "sent_unknown"."""
    with contextlib.suppress(OSError):
        p = _dir(oid)
        p.mkdir(parents=True, exist_ok=True)
        (p / "result").write_text(status)


def _marked(oid: str) -> str | None:
    try:
        v = (_dir(oid) / "result").read_text().strip()
    except OSError:
        return None
    return v if v in ("sent", "sent_unknown") else None


def _finish(row: dict, status: str, by: str, done: bool = True) -> None:
    """The request of a message that went out (or probably did): every step on its own, none can undo the send.
    The files stay when the row could not be written, so the mark is still there for `unstick`."""
    oid, data = row["id"], row["data"]
    sent = status == "sent"
    note = (f"by {by}" if done else "the mail server had it before the send was interrupted") if sent \
        else "connection cut after the message was handed over: check the Sent folder"
    try:
        store.outbox_set(oid, status, note)
        saved = True
    except Exception:  # noqa: BLE001
        log.exception("mail outbox %s: %s but its row could not be written", oid, status)
        saved = False
    resolution = "Sent" if sent else "Probably sent (connection cut): check the Sent folder"
    if saved:
        _end(row, resolution)
    elif row.get("event_id"):                       # at least no Send button left
        from .. import feed
        with contextlib.suppress(Exception):
            feed.update(int(row["event_id"]), resolve=True, resolution=resolution, read=True)
    if not done:
        return
    try:
        _note_sent(row["account"], row["agent"], data["draft"], "sent",
                   f"approved ({by})" if sent else f"approved ({by}), result unknown")
    except Exception:  # noqa: BLE001
        log.exception("mail outbox %s: note of the sent message", oid)
    subject = data["draft"].get("subject") or ""
    _post_agent(row, f"E-mail \"{subject}\" sent (the owner allowed it)." if sent else
                f"E-mail \"{subject}\": the connection to the mail server broke after it received the message, it "
                "was probably sent. Do not send it again.")


def approve(oid: str, by: str = "web") -> dict:
    """Send the waiting message (once). The draft it came from is dropped by the send."""
    from . import get_account, send
    row = store.outbox_get(oid)
    if not row:
        raise MailError("not_found", "no such message waiting")
    if row["status"] != "waiting":
        return row
    if len(str(row["data"]["draft"].get("text") or "")) > TEXT_PAGE:    # no screen shows it all: the owner never read it
        raise MailError("too_long", "this message is longer than the E-mail page shows: open its draft to read it all "
                        "and send it from there")
    if not store.outbox_claim(oid, "sending"):
        return store.outbox_get(oid) or row
    row = store.outbox_get(oid) or row                  # as claimed: the owner may have just changed the draft
    data = row["data"]
    done = _marked(oid)
    if done:                            # it already went out (a row left behind by an older version): never again
        _finish(row, done, by, done=False)
        return {**row, "status": done}
    if data.get("changed"):                 # the owner rewrote it on the E-mail page: the agent's copy never goes
        store.outbox_set(oid, "waiting", "changed by the owner")
        raise MailError("changed", "the owner changed this message on the E-mail page: send it from there")
    saved = data.get("saved") or {}
    try:
        acc = get_account(row["account"])
        gone = bool(saved.get("uid")) and imap_gone(acc, saved)    # deleted from Drafts (another mail app)
        if not gone:
            res = send.send(acc, {**data["draft"], "draft": saved or None},
                            _files(oid, data.get("files") or []),      # allowed by the owner: contacts
                            on_sent=lambda status: _mark(oid, status))
    except MailError as e:
        if e.code != "sent_unknown":
            store.outbox_set(oid, "waiting", e.message)                 # surely not sent: try again
            raise
        # handed to the mail server, then the connection broke: probably sent. Never offered again as "Send" (that
        # would send it twice); the draft stays in Drafts for the owner to send by hand after checking
        _finish(row, "sent_unknown", by)
        raise
    except BaseException as e:
        if _marked(oid):                    # it went out, then the follow-ups broke (or the thread was stopped)
            _finish(row, _marked(oid) or "sent", by)
            raise
        store.outbox_set(oid, "waiting", getattr(e, "message", None) or str(e) or type(e).__name__)  # try again
        raise
    if gone:
        store.outbox_set(oid, "deleted", "the draft was deleted")
        _end(row, "Draft deleted")
        raise MailError("not_found", "the draft was deleted from the mailbox: nothing was sent")
    _finish(row, "sent", by)
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
    from . import enabled
    if action in ("allow", "deny") and not enabled():
        raise feed.FeedError(409, "mail_off", "The E-mail page is switched off (Settings -> Features)")
    try:
        if action in ("allow", "deny"):     # IMAP / SMTP work: on the mail pool, like the E-mail page's own calls
            fn = approve if action == "allow" else deny
            try:
                from ..api.mail import run_on_pool
            except Exception:  # noqa: BLE001 - no web part loaded (a script): in place
                fn(oid, by)
            else:
                run_on_pool(fn, oid, by)
    except MailError as e:                  # shown on the button that was clicked; the request stays open
        raise feed.FeedError(424 if e.code in ("smtp", "unreachable", "tls", "connection", "imap") else 409,
                             e.code, e.message) from None


def imap_gone(acc: dict, saved: dict) -> bool:
    """True only when the drafts folder answers and the draft is not in it (an IMAP error says nothing)."""
    from . import imap
    try:
        return not imap.has(acc, str(saved.get("folder") or ""), int(saved["uid"]))
    except Exception:  # noqa: BLE001
        return False


def draft_saved(acc_id: str, old: dict, new: dict) -> None:
    """The owner saved a new version of a waiting draft on the E-mail page: the request follows the new copy (so
    sending or deleting it there still ends it), and Allow no longer sends the agent's version."""
    for row in store.outbox_list("waiting", acc_id):
        saved = row["data"].get("saved") or {}
        if saved.get("folder") == old.get("folder") and int(saved.get("uid") or 0) == int(old.get("uid") or 0):
            data = {**row["data"], "saved": {"folder": new.get("folder"), "uid": new.get("uid")}, "changed": True}
            if store.outbox_data(row["id"], data) and row.get("event_id"):
                from .. import feed
                with contextlib.suppress(Exception):
                    feed.update(int(row["event_id"]), resolve=True, read=True,
                                resolution="Changed on the E-mail page: send it from there")


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
                    "at": r["at"], "to": d.get("to") or [], "cc": d.get("cc") or [], "bcc": d.get("bcc") or [], "subject": d.get("subject") or "",
                    # the whole text: the owner sends what they read (a cut one is never sent from here)
                    "text": str(d.get("text") or "")[:TEXT_PAGE], "text_cut": len(str(d.get("text") or "")) > TEXT_PAGE,
                    "files": r["data"].get("files") or [],
                    "draft": r["data"].get("saved") or None, "why": r["data"].get("why") or "",
                    "event_id": r.get("event_id"), "note": r.get("note") or ""})
    return out


STUCK_S = 600


def unstick() -> int:
    """A send cut in the middle (the server stopped): the message waits again, with a note to look in Sent first.
    One the SMTP server had already taken (its `result` mark) ends as sent / sent_unknown instead: never offered
    again."""
    with store.conn() as c:
        stuck = [r[0] for r in c.execute("SELECT id FROM outbox WHERE status='sending' AND done_at<?",
                                         (time.time() - STUCK_S,))]
    n = 0
    for oid in stuck:
        done = _marked(oid)
        if done:
            row = store.outbox_get(oid)
            if row and row["status"] == "sending":
                _finish(row, done, "", done=False)
            continue
        with store.conn() as c:
            n += c.execute("UPDATE outbox SET status='waiting', note=? WHERE id=? AND status='sending' AND done_at<?",
                           ("interrupted while sending: check the Sent folder before sending it again", oid,
                            time.time() - STUCK_S)).rowcount
    return n


def forget(acc_id: str) -> None:
    """The mailbox is removed: its waiting messages end, their files go."""
    for row in store.outbox_list(None, acc_id, limit=10_000):
        if row["status"] in ("waiting", "sending"):
            store.outbox_set(row["id"], "refused", "mailbox removed")
            _end(row, "Mailbox removed")
        else:
            with contextlib.suppress(OSError):
                shutil.rmtree(_dir(row["id"]))


def tidy() -> None:
    """Old decided rows and their files go; old notes and contacts too (store.prune)."""
    with contextlib.suppress(Exception):
        store.prune()
    cutoff = time.time() - KEEP_DAYS * 86400
    with store.conn() as c:
        old = [r[0] for r in c.execute("SELECT id FROM outbox WHERE status!='waiting' AND COALESCE(done_at, at)<?",
                                       (cutoff,))]
        c.execute("DELETE FROM outbox WHERE status!='waiting' AND COALESCE(done_at, at)<?", (cutoff,))
    for oid in old:
        with contextlib.suppress(OSError):
            shutil.rmtree(_dir(oid))

