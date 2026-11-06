"""What a send reports, against SMTP servers that refuse, stall or read slowly: an answer of the server is "not sent"
(never "probably sent"), a stall while the message is written is "not sent", only a cut after the whole message is
"probably sent". The outbox never offers again a message the server took. Non-ASCII addresses, more than 50
forwarded attachments and a huge quoted text."""
from __future__ import annotations

import email
import email.message
import email.policy
import os
import socket
import sqlite3
import threading
import time

import pytest

from maxxing import feed, mail
from maxxing.mail import outbox, send, store
from maxxing.mail.imap import MailError
from test_mail_send import _p, _raw, acc, smtp, srv  # noqa: F401 - fixtures


class _SMTP:
    """A one-purpose SMTP server. data_reply: the answer to the final "." (None = close without answering);
    rate: bytes/s it reads the message at; stall: stops reading the message after that many bytes;
    utf8: announces SMTPUTF8; mail_reply: the answer to MAIL FROM."""

    def __init__(self, data_reply: str | None = "250 queued", rate: float = 0, stall: int = 0, utf8: bool = False,
                 mail_reply: str = "250 ok"):
        self.data_reply, self.rate, self.stall, self.utf8, self.mail_reply = data_reply, rate, stall, utf8, mail_reply
        self.got_end = False
        self.messages: list[bytes] = []
        self.mail_from = ""
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.stop.is_set():
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(c,), daemon=True).start()

    def _one(self, c: socket.socket):
        f = c.makefile("rb")

        def w(x):
            c.sendall(x.encode() + b"\r\n")
        try:
            w("220 test")
            while True:
                ln = f.readline()
                if not ln:
                    return
                cmd = ln.strip().upper()
                if cmd.startswith((b"EHLO", b"HELO")):
                    w("250-test")
                    if self.utf8:
                        w("250-SMTPUTF8")
                    w("250-8BITMIME")
                    w("250 AUTH PLAIN")
                elif cmd.startswith(b"AUTH"):
                    w("235 ok")
                elif cmd.startswith(b"MAIL"):
                    self.mail_from = ln.decode("utf-8", "replace")
                    w(self.mail_reply)
                elif cmd.startswith(b"DATA"):
                    w("354 go")
                    t0, n, buf = time.time(), 0, []
                    while True:
                        if self.stall and n >= self.stall:
                            self.stop.wait(30)          # never reads the rest
                            return
                        ln = f.readline()
                        if not ln:
                            return
                        n += len(ln)
                        if self.rate:
                            lag = n / self.rate - (time.time() - t0)
                            if lag > 0:
                                time.sleep(lag)
                        if ln == b".\r\n":
                            break
                        buf.append(ln)
                    self.got_end = True
                    self.messages.append(b"".join(buf))
                    if self.data_reply is None:
                        return                          # takes it, then the connection drops
                    w(self.data_reply)
                elif cmd.startswith(b"QUIT"):
                    w("221 bye")
                    return
                else:
                    w("250 ok")
        except OSError:
            pass
        finally:
            c.close()

    def close(self):
        self.stop.set()
        self.sock.close()


@pytest.fixture
def mk():
    made: list[_SMTP] = []

    def make(**kw) -> _SMTP:
        s = _SMTP(**kw)
        made.append(s)
        return s
    yield make
    for s in made:
        s.close()


def _on(acc: dict, s: _SMTP) -> dict:
    return {**acc, "smtp_port": s.port}


# ---------------------------------------------------------------- an answer of the server = not sent

@pytest.mark.parametrize("reply", ["554 5.7.1 Message rejected: spam", "552 5.3.4 Message too big"])
def test_a_refusal_after_the_message_is_refused_not_probably_sent(acc, mk, reply):
    s = mk(data_reply=reply)
    with pytest.raises(MailError) as e:
        send.send(_on(acc, s), {"to": ["bob@x.org"], "subject": "hi", "text": "x"})
    assert e.value.code == "smtp" and "refused" in e.value.message and reply.split()[0] in e.value.message
    assert s.got_end and send.sent_today(acc["id"]) == 0                # the count is given back


def test_a_refusal_of_the_sender_says_refused_not_connection_lost(acc, mk):
    s = mk(mail_reply="553 5.7.1 sender not allowed")
    with pytest.raises(MailError) as e:
        send.send(_on(acc, s), {"to": ["bob@x.org"], "subject": "hi", "text": "x"})
    assert e.value.code == "smtp" and "sender not allowed" in e.value.message
    assert send.sent_today(acc["id"]) == 0


def test_a_cut_after_the_whole_message_is_still_probably_sent(acc, mk):
    s = mk(data_reply=None)                                 # negative: this one may have left
    with pytest.raises(MailError) as e:
        send.send(_on(acc, s), {"to": ["bob@x.org"], "subject": "hi", "text": "x"})
    assert e.value.code == "sent_unknown" and s.got_end and send.sent_today(acc["id"]) == 1


# ---------------------------------------------------------------- slow uplink, stall

def test_a_big_attachment_on_a_slow_link_goes_out(acc, mk, monkeypatch):
    """The timeout is per write, not for the whole message: 1.4 MB at 400 kB/s (~3.5 s) with a 1 s timeout."""
    monkeypatch.setattr(mail, "SMTP_TIMEOUT_S", 1)
    s = mk(rate=400_000)
    data = os.urandom(1024 * 1024)
    res = send.send(_on(acc, s), {"to": ["bob@x.org"], "subject": "r", "text": "see file"},
                    [("r.bin", "application/octet-stream", data)])
    assert res["ok"] and s.got_end
    got = _p(s.messages[0])
    assert next(got.iter_attachments()).get_content() == data


def test_a_stall_while_writing_the_message_is_not_sent(acc, mk, monkeypatch):
    monkeypatch.setattr(mail, "SMTP_TIMEOUT_S", 1)
    s = mk(stall=100_000)
    t0 = time.time()
    with pytest.raises(MailError) as e:
        send.send(_on(acc, s), {"to": ["bob@x.org"], "subject": "r", "text": "see file"},
                  [("r.bin", "application/octet-stream", os.urandom(4 * 1024 * 1024))])
    assert e.value.code == "connection" and "nothing was sent" in e.value.message
    assert not s.got_end and send.sent_today(acc["id"]) == 0 and time.time() - t0 < 20


# ---------------------------------------------------------------- the outbox after a confirmed send

def _queued(acc, monkeypatch):
    monkeypatch.setattr(outbox, "_agent_name", lambda path: "Writer")
    return outbox.queue(acc, "acme/blog/writer", {"to": ["a@x.org"], "subject": "Hello", "text": "t",
                                                  "in_reply_to": "<m1@x.org>"}, [], "new recipient")


def test_an_error_after_a_confirmed_send_never_offers_it_again(acc, smtp, monkeypatch):
    q = _queued(acc, monkeypatch)

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(store, "note", locked)
    outbox.approve(q["id"])                                 # the note fails: the send still counts as done
    assert store.outbox_get(q["id"])["status"] == "sent" and len(smtp.messages) == 1
    assert feed.find(f"mailsend:{q['id']}") is None
    assert outbox.approve(q["id"])["status"] == "sent" and len(smtp.messages) == 1


def test_a_row_left_sending_after_the_server_took_it_ends_sent(acc, smtp, monkeypatch):
    """The row could not be written (or the server stopped in the follow-ups): the mark ends it, never 'waiting'."""
    q = _queued(acc, monkeypatch)
    real = store.outbox_set

    def no_final(oid, status, *a, **k):
        if status == "sent":
            raise sqlite3.OperationalError("database is locked")
        return real(oid, status, *a, **k)
    monkeypatch.setattr(store, "outbox_set", no_final)
    outbox.approve(q["id"])
    monkeypatch.setattr(store, "outbox_set", real)
    assert store.outbox_get(q["id"])["status"] == "sending" and feed.find(f"mailsend:{q['id']}") is None
    with store.conn() as c:
        c.execute("UPDATE outbox SET done_at=done_at-? WHERE id=?", (outbox.STUCK_S + 1, q["id"]))
    assert outbox.unstick() == 0
    assert store.outbox_get(q["id"])["status"] == "sent" and not outbox.pending()
    assert outbox.approve(q["id"])["status"] == "sent" and len(smtp.messages) == 1


def test_a_send_interrupted_before_the_server_took_it_waits_again(acc, smtp, monkeypatch):
    q = _queued(acc, monkeypatch)                           # negative: no mark, so it is offered again
    assert store.outbox_claim(q["id"], "sending")
    with store.conn() as c:
        c.execute("UPDATE outbox SET done_at=done_at-? WHERE id=?", (outbox.STUCK_S + 1, q["id"]))
    assert outbox.unstick() == 1
    assert store.outbox_get(q["id"])["status"] == "waiting" and not smtp.messages


def test_approvals_run_on_the_mail_pool(acc, smtp, monkeypatch):
    q = _queued(acc, monkeypatch)
    seen = []
    real = outbox.approve
    monkeypatch.setattr(outbox, "approve", lambda oid, by: (seen.append(threading.current_thread().name),
                                                            real(oid, by)))
    t = threading.Thread(target=outbox.feed_action, args=(q["id"], "allow", "web", {}), name="shared")
    t.start()
    t.join(30)
    assert seen and seen[0].startswith("mail") and len(smtp.messages) == 1


# ---------------------------------------------------------------- non-ASCII addresses

def test_a_non_ascii_address_with_a_name_builds_a_valid_header(acc):
    msg, rcpts = send.build(acc, {"to": ["Jürgen <jürgen@müller.de>", "日本 <user@例え.jp>"], "subject": "s",
                                  "text": "t"})
    assert rcpts == ["jürgen@xn--mller-kva.de", "user@xn--r8jz45g.jp"]
    raw = msg.as_bytes()
    assert "To: Jürgen <jürgen@xn--mller-kva.de>, 日本 <user@xn--r8jz45g.jp>".encode() in raw
    assert b"=?utf-8?" not in raw.split(b"\r\n\r\n")[0].split(b"Subject")[0]


def test_an_ascii_address_keeps_the_usual_encoding(acc):
    msg, rcpts = send.build(acc, {"to": ["Jürgen <j@x.org>"], "subject": "s", "text": "t"})
    assert rcpts == ["j@x.org"] and b"To: =?utf-8?q?J=C3=BCrgen?= <j@x.org>" in msg.as_bytes()


def test_a_non_ascii_domain_goes_out_in_its_ascii_form(acc, smtp):
    send.send(acc, {"to": ["日本 <user@例え.jp>"], "subject": "s", "text": "t"})
    assert smtp.messages[-1]["to"] == ["user@xn--r8jz45g.jp"]


def test_a_non_ascii_local_part_needs_smtputf8(acc, mk):
    s = mk()
    with pytest.raises(MailError) as e:                     # the server does not support it: a clear error
        send.send(_on(acc, s), {"to": ["Jürgen <jürgen@müller.de>"], "subject": "s", "text": "t"})
    assert e.value.code == "smtp" and "SMTPUTF8" in e.value.message and send.sent_today(acc["id"]) == 0
    u = mk(utf8=True)
    assert send.send(_on(acc, u), {"to": ["Jürgen <jürgen@müller.de>"], "subject": "s", "text": "t"})["ok"]
    assert "SMTPUTF8" in u.mail_from and "To: Jürgen <jürgen@xn--mller-kva.de>".encode() in u.messages[0]


# ---------------------------------------------------------------- forward of many attachments, huge quote

def _many(srv, n: int) -> int:
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = "a@x.org", "me@example.com", "Photos"
    m.set_content("see")
    for i in range(n):
        m.add_attachment(f"photo {i}".encode(), maintype="image", subtype="jpeg", filename=f"p{i}.jpg")
    return srv.add("INBOX", m.as_bytes())


def test_forwarding_more_than_50_attachments_is_refused_not_cut(acc, srv, smtp):
    uid = _many(srv, 60)
    fw = send.compose(acc, "forward", "INBOX", uid)
    idx = [a["index"] for a in fw["attachments"]]
    assert len(idx) == 60
    with pytest.raises(MailError) as e:
        send.send(acc, {**fw, "to": ["b@x.org"], "forward": {"folder": "INBOX", "uid": uid, "indexes": idx}})
    assert e.value.code == "limit" and "50" in e.value.message and not smtp.messages
    send.send(acc, {**fw, "to": ["b@x.org"], "forward": {"folder": "INBOX", "uid": uid, "indexes": idx[:50]}})
    assert len(list(_p(smtp.messages[-1]["data"]).iter_attachments())) == 50     # 50: all of them go


def test_a_reply_to_a_huge_mail_quotes_a_part_and_can_be_sent(acc, srv, smtp):
    uid = srv.add("INBOX", _raw("bob@x.org", "Logs", "line of log\n" * 300_000))      # 3.6 M characters
    for mode in ("reply", "forward"):
        c = send.compose(acc, mode, "INBOX", uid)
        assert len(c["text"]) < send.MAX_TEXT and "[... cut: " in c["text"]
        send.send(acc, {**c, "to": c["to"] or ["b@x.org"], "text": "Seen.\n" + c["text"]})
    small = srv.add("INBOX", _raw("bob@x.org", "Hi", "short body"))     # negative: a normal mail is quoted whole
    c = send.compose(acc, "reply", "INBOX", small)
    assert "> short body" in c["text"] and "[... cut" not in c["text"]
