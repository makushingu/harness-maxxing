"""Writing on the E-mail page: new message, reply, reply all, forward, drafts, sending through the SMTP server of the
mailbox (never from this server directly: port 25 is blocked on most hosts and a server's IP is a poor sender).

Plain text only. The signature is part of the text the composer starts with (`signature_block`), so what is sent is
what was shown. Sending is capped per mailbox and per day
(`mail_send_per_day`) and per message (`MAX_RECIPIENTS`): this is a mailbox, not a bulk sender.
"""
from __future__ import annotations

import contextlib
import email.utils
import mimetypes
import re
import smtplib
import threading
import time
from email.message import EmailMessage
from typing import Any

from .. import config
from . import imap
from .imap import MailError

MAX_RECIPIENTS = 20
MAX_ATTACH = 25 * 1024 * 1024          # total size of the attachments of one message
DEFAULT_PER_DAY = 100
MODES = ("reply", "replyall", "forward", "draft")
# SMTP servers that file the sent copy by themselves (an IMAP copy would show the message twice)
AUTO_SENT = ("gmail.com", "googlemail.com", "office365.com", "outlook.com")

_count_lock = threading.Lock()


def _addr_list(values: Any) -> list[str]:
    """`a@x.com, "B" <b@y.com>` or a list -> ['a@x.com', 'B <b@y.com>'], each checked."""
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    out = []
    for name, addr in email.utils.getaddresses([str(v) for v in values]):
        addr = addr.strip()
        if not addr:
            continue
        if any(c in addr + name for c in "\r\n\0") or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", addr):
            raise MailError("invalid", f"invalid address: {addr or name}")
        out.append(email.utils.formataddr((name.strip(), addr)) if name.strip() else addr)
    return out


def _bare(a: str) -> str:
    return email.utils.parseaddr(a)[1].lower()


def _subject(prefix: str, subject: str) -> str:
    s = (subject or "").strip()
    if re.match(rf"^{prefix}\s*:", s, re.I):
        return s
    return f"{prefix}: {s}" if s else f"{prefix}:"


def _quote(m: dict) -> str:
    body = m.get("text")
    if body is None and m.get("html"):
        from ..cmd_mail import _html_text
        body = _html_text(m["html"])
    who = m["from"]["name"] or m["from"]["email"]
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["date"])) if m.get("date") else ""
    lines = (body or "").strip().splitlines()
    return f"\n\n{when}, {who} <{m['from']['email']}>:\n" + "\n".join("> " + ln if ln else ">" for ln in lines)


def _fmt(a: dict) -> str:
    return email.utils.formataddr((a.get("name") or "", a["email"])) if a.get("name") else a["email"]


def signature_block(acc: dict) -> str:
    sig = (acc.get("signature") or "").strip()
    return "\n\n-- \n" + sig if sig else ""


def compose(acc: dict, mode: str, folder: str, uid: int) -> dict:
    """The prefilled fields of a reply / reply all / forward of a message: {to, cc, subject, text, in_reply_to,
    references, attachments (forward only)}."""
    if mode not in MODES:
        raise MailError("invalid", f"mode: one of {', '.join(MODES)}")
    m = imap.message(acc, folder, uid, mark_seen=False)
    if mode == "draft":
        return {"to": [_fmt(x) for x in m["to"]], "cc": [_fmt(x) for x in m["cc"]], "bcc": [_fmt(x) for x in m.get("bcc") or []],
                "subject": m["subject"], "text": (m.get("text") or "").rstrip(), "in_reply_to": m.get("in_reply_to") or "",
                "references": m.get("references") or "", "attachments": m["attachments"]}
    me = (acc.get("address") or "").lower()
    refs = " ".join(x for x in ((m.get("references") or "").split() + [m.get("message_id") or ""]) if x)
    if mode == "forward":
        who = _fmt(m["from"])
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["date"])) if m.get("date") else ""
        body = m.get("text")
        if body is None and m.get("html"):
            from ..cmd_mail import _html_text
            body = _html_text(m["html"])
        head = ["", "", "---------- Forwarded message ----------", f"From: {who}", f"Date: {when}",
                f"Subject: {m['subject']}", f"To: {', '.join(_fmt(x) for x in m['to'])}"]
        if m["cc"]:
            head.append(f"Cc: {', '.join(_fmt(x) for x in m['cc'])}")
        return {"to": [], "cc": [], "subject": _subject("Fwd", m["subject"]),
                "text": signature_block(acc) + "\n".join(head) + "\n\n" + (body or "").strip(),
                "in_reply_to": "", "references": "", "attachments": m["attachments"]}
    to = [_fmt(x) for x in (m["reply_to"] or [m["from"]])]
    cc: list[str] = []
    if mode == "replyall":
        seen = {_bare(a) for a in to} | {me}
        for x in m["to"] + m["cc"]:
            if x["email"] and x["email"].lower() not in seen:
                seen.add(x["email"].lower())
                cc.append(_fmt(x))
    if (m["from"]["email"] or "").lower() == me:       # replying to one's own sent message: same recipients
        to = [_fmt(x) for x in m["to"]] or to
    return {"to": to, "cc": cc, "subject": _subject("Re", m["subject"]), "text": signature_block(acc) + _quote(m),
            "in_reply_to": m.get("message_id") or "", "references": refs, "attachments": []}


# ---------------------------------------------------------------- daily cap

def _counts_path():
    return config.state_dir("mail") / "sent-count.json"


def per_day() -> int:
    try:
        return max(0, int(config.load_config().get("mail_send_per_day", DEFAULT_PER_DAY)))
    except (TypeError, ValueError):
        return DEFAULT_PER_DAY


def sent_today(acc_id: str) -> int:
    day = time.strftime("%Y-%m-%d")
    data = config.read_json(_counts_path(), default={}) or {}
    row = data.get(acc_id) if isinstance(data, dict) else None
    return int(row.get("n", 0)) if isinstance(row, dict) and row.get("day") == day else 0


def _take(acc_id: str, n: int) -> None:
    """Count n recipients for today; refuse past the cap."""
    cap = per_day()
    day = time.strftime("%Y-%m-%d")
    with _count_lock:
        p = _counts_path()
        data = config.read_json(p, default={}) or {}
        if not isinstance(data, dict):
            data = {}
        row = data.get(acc_id) if isinstance(data.get(acc_id), dict) else {}
        used = int(row.get("n", 0)) if row.get("day") == day else 0
        if used + n > cap:
            raise MailError("limit", f"daily limit reached for this mailbox ({cap} recipients a day, "
                                     "`mail_send_per_day` in config.json). For newsletters or bulk sending use a service made for it (Resend...)")
        data[acc_id] = {"day": day, "n": used + n}
        p.parent.mkdir(parents=True, exist_ok=True)
        config.write_json(p, data)


def _give_back(acc_id: str, n: int) -> None:
    day = time.strftime("%Y-%m-%d")
    with _count_lock:
        p = _counts_path()
        data = config.read_json(p, default={}) or {}
        row = data.get(acc_id) if isinstance(data, dict) else None
        if isinstance(row, dict) and row.get("day") == day:
            row["n"] = max(0, int(row.get("n", 0)) - n)
            config.write_json(p, data)


# ---------------------------------------------------------------- building and sending

def build(acc: dict, draft: dict, files: list[tuple[str, str, bytes]] | None = None) -> tuple[EmailMessage, list[str]]:
    """The message of a draft {to, cc, bcc, subject, text, in_reply_to, references, forward: {folder, uid,
    indexes}} + uploaded files [(name, type, bytes)]. Returns (message, every recipient address)."""
    to, cc, bcc = (_addr_list(draft.get(k)) for k in ("to", "cc", "bcc"))
    subject = str(draft.get("subject") or "").strip()[:500]
    if any(c in subject for c in "\r\n\0"):
        raise MailError("invalid", "invalid subject")
    text = str(draft.get("text") or "")
    if len(text) > 2_000_000:
        raise MailError("too_large", "message text too long")
    text = text.replace("\r\n", "\n")
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((acc.get("name") or "", acc["address"])) if acc.get("name") else acc["address"]
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=acc["address"].split("@", 1)[1])
    irt = str(draft.get("in_reply_to") or "").strip()
    if irt and not any(c in irt for c in "\r\n\0"):
        msg["In-Reply-To"] = irt
        refs = str(draft.get("references") or "").strip()
        msg["References"] = refs if refs and not any(c in refs for c in "\r\n\0") else irt
    msg.set_content(text)
    total = 0
    parts: list[tuple[str, str, bytes]] = list(files or [])
    fwd = draft.get("forward") or None
    if fwd and fwd.get("indexes"):
        for i in fwd["indexes"][:50]:
            parts.append(imap.attachment(acc, str(fwd.get("folder") or "INBOX"), int(fwd["uid"]), int(i)))
    for name, ctype, data in parts:
        total += len(data)
        if total > MAX_ATTACH:
            raise MailError("too_large", "attachments larger than 25 MB in total")
        ctype = ctype or mimetypes.guess_type(name)[0] or "application/octet-stream"
        maintype, _, subtype = ctype.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=(name or "attachment").replace("/", "_")[:200])
    return msg, [_bare(a) for a in to + cc + bcc]


def _auto_sent(acc: dict) -> bool:
    h = (acc.get("smtp_host") or "").lower()
    return any(h == d or h.endswith("." + d) for d in AUTO_SENT)


def send(acc: dict, draft: dict, files: list[tuple[str, str, bytes]] | None = None) -> dict:
    """Send through the SMTP server of the mailbox, file a copy in Sent, flag the replied message, drop the draft
    it came from. Returns {ok, message_id, sent_folder, recipients}."""
    from . import open_smtp
    msg, rcpts = build(acc, draft, files)
    if not rcpts:
        raise MailError("invalid", "no recipient")
    if len(rcpts) > MAX_RECIPIENTS:
        raise MailError("limit", f"at most {MAX_RECIPIENTS} recipients per message: for newsletters or bulk sending "
                                 "use a service made for it (Resend...)")
    _take(acc["id"], len(rcpts))
    try:
        s = open_smtp(acc["smtp_host"], int(acc["smtp_port"]), acc["smtp_tls"], acc["username"], imap._password(acc))
        try:
            refused = s.send_message(msg, to_addrs=rcpts)
        finally:
            with contextlib.suppress(Exception):
                s.quit()
    except MailError:
        _give_back(acc["id"], len(rcpts))
        raise
    except smtplib.SMTPRecipientsRefused as e:
        _give_back(acc["id"], len(rcpts))
        raise MailError("refused", "every recipient was refused: " + ", ".join(e.recipients)) from None
    except smtplib.SMTPException as e:
        _give_back(acc["id"], len(rcpts))
        err = e.smtp_error.decode("utf-8", "replace") if isinstance(getattr(e, "smtp_error", None), bytes) else str(e)
        raise MailError("smtp", f"the mail server refused the message: {err}") from None
    with contextlib.suppress(Exception):
        from . import store
        store.add_contacts(acc["id"], rcpts)
    out: dict[str, Any] = {"ok": True, "message_id": msg["Message-ID"], "recipients": len(rcpts),
                           "refused": sorted(refused or {}), "sent_folder": None}
    # the follow-ups never fail the send: the message is gone
    if not _auto_sent(acc):
        with contextlib.suppress(MailError, OSError):
            out["sent_folder"] = imap.append(acc, "sent", msg.as_bytes(), "(\\Seen)")
    rep = draft.get("reply") or None
    if rep and rep.get("uid"):
        with contextlib.suppress(MailError, OSError, ValueError):
            imap.act(acc, str(rep.get("folder") or "INBOX"), [int(rep["uid"])], "answered")
    _drop_draft(acc, draft)
    return out


def _drop_draft(acc: dict, draft: dict) -> None:
    d = draft.get("draft") or None
    if d and d.get("uid"):
        with contextlib.suppress(MailError, OSError, ValueError):
            imap.drop(acc, str(d.get("folder") or ""), int(d["uid"]))


def save_draft(acc: dict, draft: dict, files: list[tuple[str, str, bytes]] | None = None) -> dict:
    """File the message in Drafts (replacing the previous version of the same draft). Returns {folder, uid}."""
    msg, _ = build(acc, draft, files)
    folder, uid = imap.append_draft(acc, msg.as_bytes())
    if not folder:
        raise MailError("no_folder", "this mailbox has no drafts folder")
    prev = draft.get("draft") or None
    if prev and prev.get("uid") and not (prev.get("folder") == folder and int(prev["uid"]) == uid):
        _drop_draft(acc, draft)
    return {"folder": folder, "uid": uid}
