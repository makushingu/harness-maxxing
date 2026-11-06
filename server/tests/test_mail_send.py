"""Sending on the E-mail page against the fake IMAP and SMTP servers: Reply-To never trusted blindly, a send cut after
the message was handed over (result unknown), Bcc kept in drafts and Sent, readable names in replies and forwards,
attachment names, reply all on one's own mail, a reply sent later from Drafts, `maxxing mail read` capped."""
from __future__ import annotations

import email
import email.message
import email.policy
import time

import pytest

from fake_imap import FakeIMAP
from fake_smtp import FakeSMTP
from maxxing import mail
from maxxing.mail import imap, outbox, send, store
from maxxing.mail.imap import MailError
from test_mail_agents import PW, _cli, _mail_on


def _raw(sender: str, subject: str = "Hello", body: str = "body", **headers) -> bytes:
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, headers.pop("to", "me@example.com"), subject
    m["Message-ID"] = f"<{time.time_ns()}@{sender.split('@')[-1].strip('>')}>"
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(body)
    return m.as_bytes()


@pytest.fixture
def srv():
    s = FakeIMAP("me@example.com", PW).start()
    yield s
    s.stop()


@pytest.fixture
def smtp():
    s = FakeSMTP("me@example.com", PW).start()
    yield s
    s.stop()


@pytest.fixture
def acc(client, srv, smtp):
    _mail_on()
    a, _ = mail.add_account({"address": "me@example.com", "imap_host": "127.0.0.1", "imap_port": srv.port,
                             "imap_tls": "none", "smtp_host": "127.0.0.1", "smtp_port": smtp.port,
                             "smtp_tls": "none"}, PW)
    yield a
    imap.forget(a["id"])


def _p(raw: bytes):
    return email.message_from_bytes(raw, policy=email.policy.default)


# ---------------------------------------------------------------- Reply-To

def test_reply_to_is_shown_never_sent_to_blindly_and_never_a_contact(acc, srv, smtp, capsys, monkeypatch):
    uid = srv.add("INBOX", _raw("Accountant <acct@firm.com>", "Invoice", "Pay it", reply_to="pay@attacker.example"))
    code, out, _ = _cli(capsys, "read", str(uid))
    assert code == 0 and "Reply-To: pay@attacker.example" in out and "WARNING" in out
    code, out, err = _cli(capsys, "write", "--reply", str(uid), "--send", stdin="Yes", monkeypatch=monkeypatch)
    assert code == 1 and "pay@attacker.example" in err and not smtp.messages        # nothing went anywhere
    code, out, _ = _cli(capsys, "write", "--reply", str(uid), stdin="Yes", monkeypatch=monkeypatch)
    assert code == 0 and "To:   pay@attacker.example" in out and "Reply-To" in out    # a draft says where it goes
    code, out, _ = _cli(capsys, "write", "--reply", str(uid), "--to", "pay@attacker.example", "--send", stdin="Yes",
                        monkeypatch=monkeypatch)
    assert code == 0 and "To:   pay@attacker.example" in out and len(smtp.messages) == 1
    assert store.unknown(acc["id"], ["pay@attacker.example"]) == ["pay@attacker.example"]  # not a known contact
    assert "\\Answered" in srv.folders["INBOX"].messages[uid]["flags"]
    # the same from the page (send with `reply`), and a plain reply to the sender: that one becomes a contact
    send.send(acc, {"to": ["pay@attacker.example"], "subject": "Re", "text": "x", "reply": {"folder": "INBOX", "uid": uid}})
    assert store.unknown(acc["id"], ["pay@attacker.example"]) == ["pay@attacker.example"]
    plain = srv.add("INBOX", _raw("Bob <bob@x.org>", "Hi"))
    send.send(acc, {"to": ["bob@x.org"], "subject": "Re: Hi", "text": "x", "reply": {"folder": "INBOX", "uid": plain}})
    assert store.unknown(acc["id"], ["bob@x.org"]) == []


def test_a_reply_to_the_parser_rejects_is_checked_address_by_address(acc, srv, smtp, capsys, monkeypatch):
    # the raw fallback keeps the whole header as one entry: its last address alone is the sender's domain
    uid = srv.add("INBOX", _raw("Accountant <acct@firm.com>", "Invoice", "Pay it").replace(
        b"Subject:", b"Reply-To: pay@attacker.example,x@[,boss@firm.com\r\nSubject:", 1))
    code, _, _ = _cli(capsys, "write", "--reply", str(uid), "--send", stdin="Yes", monkeypatch=monkeypatch)
    assert code == 1 and not smtp.messages
    # a Reply-To on the sender's own domain still goes without --to
    ok = srv.add("INBOX", _raw("Accountant <acct@firm.com>", "Invoice", "Pay it", reply_to="billing@firm.com"))
    code, out, _ = _cli(capsys, "write", "--reply", str(ok), "--send", stdin="Yes", monkeypatch=monkeypatch)
    assert code == 0 and len(smtp.messages) == 1


# ---------------------------------------------------------------- a send cut in the middle

class _Cut(list):
    """FakeSMTP.messages that breaks the connection once the message is stored (before the final 250)."""

    def __init__(self, wait: float = 0):
        super().__init__()
        self.wait = wait

    def append(self, x):
        super().append(x)
        if self.wait:
            time.sleep(self.wait)
        raise ConnectionError("drop before 250")


def test_a_send_cut_after_the_message_is_unknown_not_refused(acc, smtp):
    smtp.messages = _Cut()
    with pytest.raises(MailError) as e:
        send.send(acc, {"to": ["a@x.org"], "subject": "s", "text": "t"})
    assert e.value.code == "sent_unknown" and "probably sent" in e.value.message
    assert len(smtp.messages) == 1 and send.sent_today(acc["id"]) == 1          # the count stays: it probably left


def test_a_timeout_after_the_message_is_unknown_too(acc, smtp, monkeypatch):
    monkeypatch.setattr(mail, "SMTP_TIMEOUT_S", 1)
    smtp.messages = _Cut(wait=3)
    with pytest.raises(MailError) as e:
        send.send(acc, {"to": ["a@x.org"], "subject": "s", "text": "t"})
    assert e.value.code == "sent_unknown" and send.sent_today(acc["id"]) == 1


def test_a_cut_before_the_message_gives_the_count_back(acc, smtp, monkeypatch):
    real = send.smtplib.SMTP.mail

    def mail_cut(self, *a, **k):
        self.close()
        return real(self, *a, **k)
    monkeypatch.setattr(send.smtplib.SMTP, "mail", mail_cut)
    with pytest.raises(MailError) as e:
        send.send(acc, {"to": ["a@x.org"], "subject": "s", "text": "t"})
    assert e.value.code == "connection" and "nothing was sent" in e.value.message
    assert send.sent_today(acc["id"]) == 0 and not smtp.messages


def test_an_allowed_message_cut_after_sending_is_not_offered_again(acc, smtp, monkeypatch):
    from maxxing import feed
    monkeypatch.setattr(outbox, "_agent_name", lambda path: "Writer")
    q = outbox.queue(acc, "acme/blog/writer", {"to": ["a@x.org"], "subject": "Hello", "text": "t"}, [], "new recipient")
    smtp.messages = _Cut()
    with pytest.raises(MailError) as e:
        outbox.approve(q["id"])
    assert e.value.code == "sent_unknown"
    assert store.outbox_get(q["id"])["status"] == "sent_unknown" and not outbox.pending()
    assert feed.find(f"mailsend:{q['id']}") is None                         # no open request left
    ev = feed.find(f"mailsend:{q['id']}", open_only=False)
    assert ev and "Sent folder" in ev["resolution"]
    assert outbox.approve(q["id"])["status"] == "sent_unknown" and len(smtp.messages) == 1    # never twice


# ---------------------------------------------------------------- Bcc, names

def test_bcc_is_kept_in_the_draft_and_sent_copy_never_transmitted(acc, srv, smtp):
    saved = send.save_draft(acc, {"to": ["a@x.org"], "bcc": ["boss@x.org"], "subject": "s", "text": "t"})
    c = send.compose(acc, "draft", saved["folder"], saved["uid"])
    assert c["bcc"] == ["boss@x.org"] and c["to"] == ["a@x.org"]
    send.send(acc, {**c, "draft": saved})
    got = smtp.messages[-1]
    assert sorted(got["to"]) == ["a@x.org", "boss@x.org"] and b"boss@x.org" not in got["data"]
    sent = [m["raw"] for m in srv.folders["Sent"].messages.values()]
    assert sent and _p(sent[-1])["Bcc"] == "boss@x.org"


def test_replies_and_forwards_show_names_not_encoded_words(acc, srv):
    uid = srv.add("INBOX", _raw("Élodie Martin <e@x.fr>", "devis", "Bonjour", to="Gérard <me@example.com>",
                                cc='"Martin, Paul" <p@x.fr>'))
    r = send.compose(acc, "replyall", "INBOX", uid)
    assert r["to"] == ["Élodie Martin <e@x.fr>"] and r["cc"] == ['"Martin, Paul" <p@x.fr>']
    fw = send.compose(acc, "forward", "INBOX", uid)
    assert "=?" not in fw["text"] and "From: Élodie Martin <e@x.fr>" in fw["text"]
    msg, rcpts = send.build(acc, {"to": r["to"], "cc": r["cc"], "text": "x"})
    assert rcpts == ["e@x.fr", "p@x.fr"] and msg["To"].addresses[0].display_name == "Élodie Martin"
    assert msg["Cc"].addresses[0].display_name == "Martin, Paul"


def test_reply_all_on_ones_own_mail_has_each_address_once(acc, srv):
    uid = srv.add("Sent", _raw("Me <me@example.com>", "Plans", to="bob@x.org, me@example.com",
                               cc="bob@x.org, carol@x.org, ME@example.com"))
    r = send.compose(acc, "replyall", "Sent", uid)
    assert r["to"] == ["bob@x.org"] and r["cc"] == ["carol@x.org"]


def test_attachment_names_and_types_cannot_break_the_headers(acc, srv, smtp, capsys, tmp_path):
    msg, _ = send.build(acc, {"to": "a@x.org", "text": "x"}, [("a\r\nX-Bad: 1.txt", "text/plain;\r\nX: y", b"1"),
                                                            ("..", "", b"2"), ("../../etc/passwd", "image/png", b"3")])
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == ["a  X-Bad: 1.txt", "attachment", ".._.._etc_passwd"]
    assert [p.get_content_type() for p in msg.iter_attachments()] == ["text/plain", "application/octet-stream", "image/png"]
    assert b"\nX-Bad" not in msg.as_bytes() and b"\nX: y" not in msg.as_bytes()
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = "x@y.org", "me@example.com", "dots"
    m.set_content("x")
    m.add_attachment(b"data", maintype="application", subtype="octet-stream", filename="..")
    uid = srv.add("INBOX", m.as_bytes())
    code, out, err = _cli(capsys, "attachment", str(uid), "2", str(tmp_path) + "/")
    assert code == 0, err
    assert (tmp_path / "part-2").read_bytes() == b"data"


# ---------------------------------------------------------------- a reply sent later from Drafts

def test_a_reply_saved_as_draft_and_sent_later_marks_the_original(acc, srv, smtp):
    uid = srv.add("INBOX", _raw("Bob <bob@x.org>", "Hi"))
    r = send.compose(acc, "reply", "INBOX", uid)
    saved = send.save_draft(acc, {**r, "text": "later" + r["text"]})
    d = send.compose(acc, "draft", saved["folder"], saved["uid"])        # reopened: no `reply`, only In-Reply-To
    send.send(acc, {**d, "draft": saved})
    assert "\\Answered" in srv.folders["INBOX"].messages[uid]["flags"]


# ---------------------------------------------------------------- read

def test_read_is_capped_and_json_has_no_inline_images(acc, srv, capsys):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = "news@x.org", "me@example.com", "News"
    m.set_content("<p>" + "word " * 10_000 + "</p><img src=\"cid:logo\">", subtype="html")
    m.add_related(b"\x89PNG" * 50_000, maintype="image", subtype="png", cid="<logo>")
    uid = srv.add("INBOX", m.as_bytes())
    code, out, _ = _cli(capsys, "read", str(uid), "--json")
    assert code == 0 and "base64" not in out and len(out) < 30_000
    import json
    j = json.loads(out)
    assert j["truncated"] > 0 and j["reply_to_differs"] == []
    code, out, _ = _cli(capsys, "read", str(uid), "--max", "100")
    assert "[cut: " in out and len(out) < 2_000
    code, out, _ = _cli(capsys, "read", str(uid), "--full", "--json")
    assert "base64" in out



def test_read_says_how_many_parts_are_not_listed(acc, srv, capsys):
    from test_mail_parse import _many
    import json
    uid = srv.add("INBOX", _many(1200))
    code, out, _ = _cli(capsys, "read", str(uid))
    more = int(out.split(" more parts not listed")[0].rsplit("\n", 1)[-1])
    assert code == 0 and more > 0 and out.count("\nAttachment ") + more == 1200
    code, out, _ = _cli(capsys, "read", str(uid), "--json")
    assert json.loads(out)["attachments_more"] == more
    few = srv.add("INBOX", _many(3))                     # under the limit: no line, the count is 0
    code, out, _ = _cli(capsys, "read", str(few))
    assert code == 0 and "not listed" not in out and out.count("\nAttachment ") == 3
    assert json.loads(_cli(capsys, "read", str(few), "--json")[1])["attachments_more"] == 0

def test_a_cut_right_after_the_data_command_is_not_sent(acc, smtp, monkeypatch):
    real = send.smtplib.SMTP.getreply
    calls = []

    def getreply(self):
        calls.append(1)
        if getattr(self, "_mx_data", False):            # the answer to DATA never comes
            self.close()
            raise send.smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
        return real(self)
    real_putcmd = send.smtplib.SMTP.putcmd

    def putcmd(self, cmd, args=""):
        if cmd.lower() == "data":
            self._mx_data = True
        return real_putcmd(self, cmd, args)
    monkeypatch.setattr(send.smtplib.SMTP, "getreply", getreply)
    monkeypatch.setattr(send.smtplib.SMTP, "putcmd", putcmd)
    with pytest.raises(MailError) as e:
        send.send(acc, {"to": ["a@x.org"], "subject": "s", "text": "t"})
    assert e.value.code == "connection" and send.sent_today(acc["id"]) == 0


def test_forwarding_a_mail_with_a_mail_attached_keeps_both(acc, srv, smtp):
    inner = _p(_raw("x@y.org", "Inner", "inside"))
    outer = email.message.EmailMessage()
    outer["From"], outer["To"], outer["Subject"] = "a@x.org", "me@example.com", "Outer"
    outer.set_content("see attached")
    outer.add_attachment(inner, filename="Inner.eml")
    outer.add_attachment(b"%PDF-1.4 x", maintype="application", subtype="pdf", filename="f.pdf")
    uid = srv.add("INBOX", outer.as_bytes())
    fw = send.compose(acc, "forward", "INBOX", uid)
    idx = [a["index"] for a in fw["attachments"]]
    assert len(idx) == 2
    send.send(acc, {**fw, "to": ["b@x.org"], "forward": {"folder": "INBOX", "uid": uid, "indexes": idx}})
    got = _p(smtp.messages[-1]["data"])
    parts = {p.get_filename(): p for p in got.iter_attachments()}
    assert set(parts) == {"Inner.eml", "f.pdf"}
    assert parts["Inner.eml"].get_content_type() == "message/rfc822"
    assert (parts["Inner.eml"]["Content-Transfer-Encoding"] or "7bit").lower() != "base64"
    assert parts["f.pdf"].get_content() == b"%PDF-1.4 x"


@pytest.mark.parametrize("field", ["to", "cc", "bcc"])
@pytest.mark.parametrize("value", ["c@d.com>", "(c@d.com", "a@b.com, c@d.com>", "Bob <>", "a@b.com;c@d.com"])
def test_an_address_the_parser_rejects_is_refused_not_dropped(acc, field, value):
    draft = {"to": "a@x.org", "text": "t"} | {field: value}
    with pytest.raises(MailError) as e:
        send.build(acc, draft)
    assert e.value.code == "invalid"
    msg, rcpts = send.build(acc, {"to": "a@x.org, ", "cc": ", b@x.org,", "text": "t"})      # stray commas are fine
    assert rcpts == ["a@x.org", "b@x.org"]

