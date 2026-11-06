"""Writing on the E-mail page: new message, reply, reply all, forward, drafts, sending through the SMTP server of the
mailbox (never from this server directly: port 25 is blocked on most hosts and a server's IP is a poor sender).

Plain text only. The signature is part of the text the composer starts with (`signature_block`), so what is sent is
what was shown. Sending is capped per mailbox and per day
(`mail_send_per_day`) and per message (`MAX_RECIPIENTS`): this is a mailbox, not a bulk sender.
"""
from __future__ import annotations

import contextlib
import email
import email.policy
import email.utils
import logging
import mimetypes
import re
import smtplib
import time
from email.message import EmailMessage
from typing import Any

from .. import config
from . import imap
from .imap import MailError

MAX_RECIPIENTS = 20
MAX_ATTACH = 25 * 1024 * 1024          # total size of the attachments of one message
MAX_FORWARDED = 50                      # attachments of the original a forward carries
DEFAULT_PER_DAY = 100
MODES = ("reply", "replyall", "forward", "draft")
# SMTP servers that file the sent copy by themselves (an IMAP copy would show the message twice)
AUTO_SENT = ("gmail.com", "googlemail.com", "office365.com", "outlook.com")

log = logging.getLogger("maxxing.mail")

_count_lock = config.ProcessLock("mail-sent-count")    # the server and `maxxing mail write --send` count together


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
        addr = _idna(addr)
        name = name.strip()
        if not name:
            out.append(addr)
        elif addr.isascii():
            out.append(email.utils.formataddr((name, addr)))
        else:       # non-ASCII before the @ (SMTPUTF8): formataddr cannot, the header is written as UTF-8 (`build`)
            if re.search(r'[()<>\[\]:;@\\,."]', name):
                name = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
            out.append(f"{name} <{addr}>")
    return out


def _idna(addr: str) -> str:
    """`user@例え.jp` -> `user@xn--r8jz45g.jp`: a non-ASCII domain goes out in its ASCII form (every mail server
    takes it). A non-ASCII part before the @ stays: it needs SMTPUTF8 (`send`)."""
    local, _, domain = addr.rpartition("@")
    if domain.isascii():
        return addr
    try:
        return f"{local}@{domain.encode('idna').decode('ascii')}"
    except UnicodeError:
        raise MailError("invalid", f"invalid address: {addr}") from None


def _bare(a: str) -> str:
    return email.utils.parseaddr(a)[1].lower()


def _subject(prefix: str, subject: str) -> str:
    s = (subject or "").strip()
    if re.match(rf"^{prefix}\s*:", s, re.I):
        return s
    return f"{prefix}: {s}" if s else f"{prefix}:"


QUOTED_MAX = 200_000        # characters of the original kept in a reply / forward (a sent text is capped at MAX_TEXT)
MAX_TEXT = 2_000_000


def _cut(body: str | None) -> str:
    """The text of the original, cut past QUOTED_MAX with a marker: a 5 MB log quoted whole could never be sent."""
    body = (body or "").strip()
    if len(body) <= QUOTED_MAX:
        return body
    return body[:QUOTED_MAX] + f"\n\n[... cut: {len(body) - QUOTED_MAX:,} more characters of the original message]"


def _quote(m: dict) -> str:
    body = m.get("text")
    if body is None and m.get("html"):
        from ..cmd_mail import _html_text
        body = _html_text(m["html"])
    body = _cut(body)
    who = m["from"]["name"] or m["from"]["email"]
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["date"])) if m.get("date") else ""
    lines = (body or "").strip().splitlines()
    return f"\n\n{when}, {who} <{m['from']['email']}>:\n" + "\n".join("> " + ln if ln else ">" for ln in lines)


def _fmt(a: dict) -> str:
    """`Name <addr>` as a person reads it (formataddr would RFC 2047-encode a non-ASCII name: `=?utf-8?q?...?=` in
    the To field and in a forwarded text). `_addr_list` parses it back and the header is encoded when sent."""
    name = (a.get("name") or "").strip()
    if not name:
        return a["email"]
    if re.search(r'[()<>\[\]:;@\\,."]', name):
        name = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{name} <{a['email']}>"


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
                "text": signature_block(acc) + "\n".join(head) + "\n\n" + _cut(body),
                "in_reply_to": "", "references": "", "attachments": m["attachments"]}
    if (m["from"]["email"] or "").lower() == me:       # replying to one's own sent message: same recipients
        first = [x for x in m["to"] if (x["email"] or "").lower() != me] or [m["from"]]    # a note to oneself
    else:
        first = m["reply_to"] or [m["from"]]
    to: list[str] = []
    seen: set[str] = set()
    for x in first:
        if x["email"] and x["email"].lower() not in seen:
            seen.add(x["email"].lower())
            to.append(_fmt(x))
    seen.add(me)
    cc: list[str] = []
    if mode == "replyall":
        for x in m["to"] + m["cc"]:
            if x["email"] and x["email"].lower() not in seen:
                seen.add(x["email"].lower())
                cc.append(_fmt(x))
    sender = (m["from"]["email"] or "").lower()
    other = [x["email"] for x in m["reply_to"] if x["email"] and x["email"].lower() != sender]
    return {"to": to, "cc": cc, "subject": _subject("Re", m["subject"]), "text": signature_block(acc) + _quote(m),
            "in_reply_to": m.get("message_id") or "", "references": refs, "attachments": [],
            "from": m["from"]["email"] or "", "reply_to": other}    # where the answer goes instead of the sender


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
    if len(text) > MAX_TEXT:
        raise MailError("too_large", f"message text too long (at most {MAX_TEXT:,} characters)")
    text = text.replace("\r\n", "\n")
    # a non-ASCII address (before the @): headers in UTF-8 (RFC 6532), the only valid form; the default policy would
    # RFC 2047-encode the address itself, which no server reads. Sending it needs SMTPUTF8 (`send`)
    msg = EmailMessage(policy=email.policy.SMTPUTF8) if not all(a.isascii() for a in to + cc + bcc) else EmailMessage()
    msg["From"] = email.utils.formataddr((acc.get("name") or "", acc["address"])) if acc.get("name") else acc["address"]
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:             # kept in the draft and the Sent copy; smtplib's send_message never transmits it
        msg["Bcc"] = ", ".join(bcc)
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
        if len(fwd["indexes"]) > MAX_FORWARDED:        # never cut silently: the page listed them all
            raise MailError("limit", f"at most {MAX_FORWARDED} forwarded attachments per message "
                                     f"({len(fwd['indexes'])} chosen): remove some, or forward it in two messages")
        parts += _forwarded(acc, str(fwd.get("folder") or "INBOX"), int(fwd["uid"]), [int(i) for i in fwd["indexes"]])
    for name, ctype, data in parts:
        total += len(data)
        if total > MAX_ATTACH:
            raise MailError("too_large", "attachments larger than 25 MB in total")
        ctype = (ctype or "").split(";", 1)[0].strip().lower()
        if not _CTYPE.match(ctype):                     # CR/LF or parameters: not a header we write as given
            ctype = mimetypes.guess_type(_name(name))[0] or "application/octet-stream"
        if ctype == "message/rfc822":                   # a mail inside a mail: embedded as is, never base64 (RFC 2046)
            msg.add_attachment(email.message_from_bytes(data, policy=email.policy.default), filename=_name(name))
            continue
        maintype, _, subtype = ctype.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=_name(name))
    return msg, [_bare(a) for a in to + cc + bcc]


_CTYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")


def _name(name: str) -> str:
    """A file name that fits in a header: one line, no folder part, never `.` / `..` / empty."""
    n = imap._line(str(name or "")).replace("/", "_").replace("\\", "_").strip()[:200]
    return n if n.strip(".") else "attachment"


def _forwarded(acc: dict, folder: str, uid: int, indexes: list[int]) -> list[tuple[str, str, bytes]]:
    """The attachments of a forwarded message, from ONE download of it (not one per attachment), numbered like the
    reader lists them (`imap.part_at`: a forwarded mail inside it comes as its .eml)."""
    msg = imap._parse(imap.raw_message(acc, folder, uid))
    return [imap.part_at(msg, i) for i in indexes]


def _auto_sent(acc: dict) -> bool:
    h = (acc.get("smtp_host") or "").lower()
    return any(h == d or h.endswith("." + d) for d in AUTO_SENT)


class _Watch:
    """Tells whether the message itself went out: smtplib sends `data`, reads 354, then the whole message with its
    final "." in ONE `send`. `body` is True only once that write is complete: a failure after it says nothing about
    the result (the server may have queued it before the connection broke); a failure during it means the server
    never got the end of the message, so it was not sent.

    The message is written in chunks, each with the socket timeout: Python's timeout covers a whole `sendall`, so a
    25 MB attachment on a slow uplink timed out after 15 s although bytes kept flowing. The answer to the final "."
    then gets DATA_REPLY_S (a server may scan a big message before it answers)."""

    def __init__(self, s: smtplib.SMTP):
        self.data_cmd = self.writing = self.body = self.stopped = False
        real = s.send

        def watch(x):
            if self.stopped or self.body:               # the QUIT / RSET after the message is not the message
                return real(x)
            if self.data_cmd:
                return self._write(s, x)
            if (x if isinstance(x, str) else x.decode("ascii", "replace")).strip().lower() == "data":
                self.data_cmd = True
            return real(x)
        s.send = watch                                  # type: ignore[method-assign]

    def _write(self, s: smtplib.SMTP, x) -> None:
        data = x.encode(s.command_encoding) if isinstance(x, str) else bytes(x)
        sock = s.sock
        if sock is None:
            raise smtplib.SMTPServerDisconnected("please run connect() first")
        self.writing = True
        try:
            view = memoryview(data)
            for i in range(0, len(data), WRITE_CHUNK):
                sock.sendall(view[i:i + WRITE_CHUNK])
        except OSError as e:
            s.close()
            raise smtplib.SMTPServerDisconnected(f"{type(e).__name__} while sending the message: {e}") from None
        self.body = True                                # all of it, final "." included, is with the server
        with contextlib.suppress(OSError):
            from . import SMTP_TIMEOUT_S
            sock.settimeout(max(SMTP_TIMEOUT_S, DATA_REPLY_S))


WRITE_CHUNK = 64 * 1024     # each chunk gets the socket timeout: a stall, not a slow line, fails the send
DATA_REPLY_S = 60           # wait for the answer to the end of the message (RFC 5321 suggests up to 10 min)

UNKNOWN = ("the connection to the mail server broke after it received the message: it was probably sent. "
           "Check the Sent folder (or ask the recipient) before sending it again. The draft is kept.")


def send(acc: dict, draft: dict, files: list[tuple[str, str, bytes]] | None = None, contacts: bool = True,
         on_sent=None) -> dict:
    """Send through the SMTP server of the mailbox, file a copy in Sent, flag the replied message, drop the draft
    it came from. Returns {ok, message_id, sent_folder, recipients, to, cc, bcc}. contacts: the recipients become
    known contacts (approve_send "new") - only for what the owner sent or allowed, never for an agent's own send;
    the Reply-To of the mail answered never does by itself (it can be anyone's address).
    on_sent(status): called as soon as the SMTP server has the message ("sent", or "sent_unknown" just before that
    error), before the slow follow-ups (Sent copy...): the outbox records it there.
    MailError "sent_unknown": the connection broke or timed out after the whole message was handed over (it
    probably left): the daily count is kept, the draft too, and nothing must send it again blindly. Any answer of
    the server (554 spam, 552 too large, 5xx on MAIL / RCPT) and any failure while the message was still being
    written are "not sent": the count is given back."""
    from . import open_smtp
    msg, rcpts = build(acc, draft, files)
    if not rcpts:
        raise MailError("invalid", "no recipient")
    if len(rcpts) > MAX_RECIPIENTS:
        raise MailError("limit", f"at most {MAX_RECIPIENTS} recipients per message: for newsletters or bulk sending "
                                 "use a service made for it (Resend...)")
    _take(acc["id"], len(rcpts))
    w: _Watch | None = None

    def cut(e: BaseException) -> MailError:
        """A disconnect or timeout: after the whole message = unknown (count kept), else nothing was sent."""
        if w is not None and w.body:
            log.warning("mail %s: %s after the message was sent (%s): result unknown", acc["id"], type(e).__name__, e)
            if on_sent:
                with contextlib.suppress(Exception):
                    on_sent("sent_unknown")
            return MailError("sent_unknown", UNKNOWN)
        _give_back(acc["id"], len(rcpts))
        if w is not None and w.writing:
            return MailError("connection", f"the connection to {acc['smtp_host']} broke or stalled while the message "
                                           f"was being sent ({e}): the server never got all of it, nothing was sent. "
                                           "You can try again (large attachments need a steady connection)")
        return MailError("connection", f"connection to {acc['smtp_host']} lost before the message was sent "
                                       f"({type(e).__name__}): nothing was sent, you can try again")
    try:
        s = open_smtp(acc["smtp_host"], int(acc["smtp_port"]), acc["smtp_tls"], acc["username"], imap._password(acc))
        try:
            w = _Watch(s)
            refused = s.send_message(msg, to_addrs=rcpts)
        finally:
            if w is not None:
                w.stopped = True
            with contextlib.suppress(Exception):
                s.quit()
    # order matters: every smtplib error is an OSError (SMTPException subclasses it), so the server's answers come
    # before the disconnect / timeout branches
    except MailError:
        _give_back(acc["id"], len(rcpts))
        raise
    except smtplib.SMTPRecipientsRefused as e:
        _give_back(acc["id"], len(rcpts))
        raise MailError("refused", "every recipient was refused: " + ", ".join(e.recipients)) from None
    except smtplib.SMTPServerDisconnected as e:
        raise cut(e) from None
    except smtplib.SMTPNotSupportedError as e:         # raised before MAIL FROM: nothing went out
        _give_back(acc["id"], len(rcpts))
        if not all(a.isascii() for a in rcpts):
            raise MailError("smtp", "this mail server does not accept addresses with non-ASCII characters before "
                                    "the @ (no SMTPUTF8 support): nothing was sent") from None
        raise MailError("smtp", f"the mail server refused the message: {e}") from None
    except smtplib.SMTPException as e:                 # an answer of the server (SMTPResponseException...): not sent
        _give_back(acc["id"], len(rcpts))
        err = e.smtp_error.decode("utf-8", "replace") if isinstance(getattr(e, "smtp_error", None), bytes) else str(e)
        code = getattr(e, "smtp_code", None)
        raise MailError("smtp", f"the mail server refused the message: {f'{code} ' if code else ''}{err}") from None
    except OSError as e:                               # a socket error smtplib did not wrap (timeout, reset)
        raise cut(e) from None
    if on_sent:
        with contextlib.suppress(Exception):
            on_sent("sent")
    # the follow-ups never fail the send: the message is gone
    orig = _original(acc, draft)
    if contacts:
        skip = set(orig["reply_to"]) if orig else set(rcpts) if _is_reply(draft) else set()
        with contextlib.suppress(Exception):
            from . import store
            store.add_contacts(acc["id"], [r for r in rcpts if r not in skip])
    out: dict[str, Any] = {"ok": True, "message_id": msg["Message-ID"], "recipients": len(rcpts),
                           "refused": sorted(refused or {}), "sent_folder": None,
                           **{k: _addr_list(draft.get(k)) for k in ("to", "cc", "bcc")}}
    if not _auto_sent(acc):
        with contextlib.suppress(Exception):           # imaplib.IMAP4.error too: the message is gone
            out["sent_folder"] = imap.append(acc, "sent", msg.as_bytes(), "(\\Seen)")
    rep = draft.get("reply") or None
    target = (orig["folder"], orig["uid"]) if orig else (str(rep.get("folder") or "INBOX"), int(rep["uid"])) \
        if rep and rep.get("uid") else None
    if target:
        with contextlib.suppress(Exception):
            imap.act(acc, target[0], [target[1]], "answered")
    _drop_draft(acc, draft)
    return out


def _is_reply(draft: dict) -> bool:
    return bool((draft.get("reply") or {}).get("uid") or str(draft.get("in_reply_to") or "").strip())


def _original(acc: dict, draft: dict) -> dict | None:
    """The mail a reply answers: {folder, uid, from, reply_to (addresses other than From)}. From `reply` {folder,
    uid}, else found by its Message-ID (a reply saved as a draft and sent later). None when unknown."""
    if not _is_reply(draft):
        return None
    rep = draft.get("reply") or {}
    irt = str(draft.get("in_reply_to") or "").strip()
    try:
        with imap.session(acc) as m:
            if rep.get("uid"):
                folder, uid = str(rep.get("folder") or "INBOX"), int(rep["uid"])
                imap._select(m, folder, readonly=True)
            else:
                if not re.match(r"^<[^<>\s\"\\]+>$", irt):
                    return None
                folder, uid = "", 0
                for f in ("INBOX", imap._folder_of_role(m, "archive")):
                    if not f:
                        continue
                    imap._select(m, f, readonly=True)
                    typ, data = m.uid("SEARCH", "HEADER", "Message-ID", f'"{irt}"')
                    found = (data[0] or b"").split() if typ == "OK" and data else []
                    if found:
                        folder, uid = f, int(found[-1])
                        break
                if not uid:
                    return None
            typ, data = m.uid("FETCH", str(uid), "(BODY.PEEK[HEADER.FIELDS (FROM REPLY-TO)])")
            raw = next((x[1] for x in data or [] if isinstance(x, tuple)), None) if typ == "OK" else None
    except Exception:  # noqa: BLE001 - the message is gone: a follow-up only
        return None
    if raw is None:
        return None
    h = email.message_from_bytes(raw)
    sender = _bare(str(h.get("from") or ""))
    others = {a.lower() for _, a in email.utils.getaddresses([str(v) for v in h.get_all("reply-to") or []]) if a}
    return {"folder": folder, "uid": uid, "from": sender, "reply_to": others - {sender}}


def _drop_draft(acc: dict, draft: dict) -> None:
    d = draft.get("draft") or None
    if d and d.get("uid"):
        with contextlib.suppress(Exception):
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
