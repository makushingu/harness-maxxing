"""E-mail page: accounts, writing (build / compose / send / drafts), daily cap, API, CLI.

IMAP is replaced by small fakes here; SMTP runs on tests/fake_smtp.py. With MAXXING_TEST_IMAP=host:port:user:password
(a plain-text IMAP server with Sent and Drafts folders, e.g. a local Dovecot), test_real_imap_round_trip also runs
against a real server.
"""
from __future__ import annotations

import email
import email.policy
import json
import os

import pytest

from fake_smtp import FakeSMTP
from maxxing import config, mail, vault
from maxxing.mail import imap, send
from maxxing.mail.imap import MailError

PW = "pässword"            # not ASCII on purpose: smtplib alone cannot send it


def _on(**extra):
    c = config.load_config()
    c.update({"mail_page": True, **extra})
    config.save_config(c)


@pytest.fixture
def smtp():
    s = FakeSMTP("me@example.com", PW, refuse={"nobody@example.com"}).start()
    yield s
    s.stop()


@pytest.fixture
def acc(mx, smtp, monkeypatch):
    """An account whose IMAP side is faked (no IMAP server): appends, flags and drops are recorded."""
    _on()
    calls: dict[str, list] = {"append": [], "act": [], "drop": [], "drafts": []}
    monkeypatch.setattr(mail, "open_imap", lambda *a, **k: type("M", (), {"logout": lambda self: None})())
    monkeypatch.setattr(imap, "append", lambda acc, role, raw, flags="": calls["append"].append((role, raw)) or "Sent")
    monkeypatch.setattr(imap, "act", lambda acc, folder, uids, action, target=None: calls["act"].append((folder, uids, action)) or {"ok": True})
    monkeypatch.setattr(imap, "drop", lambda acc, folder, uid: calls["drop"].append((folder, uid)))

    def append_draft(acc, raw):
        calls["drafts"].append(raw)
        return "Drafts", len(calls["drafts"])
    monkeypatch.setattr(imap, "append_draft", append_draft)
    a, res = mail.add_account({"address": "me@example.com", "name": "Me", "imap_host": "127.0.0.1", "imap_port": 993,
                               "imap_tls": "ssl", "smtp_host": "127.0.0.1", "smtp_port": smtp.port, "smtp_tls": "none",
                               "signature": "Me\nACME"}, PW)
    assert res["smtp"] == "ok"
    a["_calls"] = calls
    return a


def _parsed(raw: bytes):
    return email.message_from_bytes(raw, policy=email.policy.default)


def test_the_password_stays_in_the_vault_and_out_of_sessions(acc):
    assert vault.get(acc["password_key"]) == PW
    assert "password" not in json.dumps(mail.public(acc)).replace("password_key", "").replace("has_password", "")
    assert acc["password_key"] not in vault.exposed_env()


def test_send_goes_through_the_mailbox_smtp_and_files_a_sent_copy(acc, smtp):
    r = send.send(acc, {"to": ["Bob <bob@example.com>"], "cc": "carol@example.com", "bcc": ["dan@example.com"],
                        "subject": "Héllo", "text": "Line 1\r\nLine 2"}, [("a.txt", "text/plain", b"hi")])
    assert r["ok"] and r["recipients"] == 3 and r["sent_folder"] == "Sent"
    got = smtp.messages[-1]
    assert got["from"] == "me@example.com"
    assert sorted(got["to"]) == ["bob@example.com", "carol@example.com", "dan@example.com"]
    m = _parsed(got["data"])
    assert m["Subject"] == "Héllo" and "Bcc" not in m and m["From"] == "Me <me@example.com>"
    body = m.get_body(("plain",)).get_content().replace("\r\n", "\n")      # CRLF on the wire
    assert "Line 1\nLine 2" in body and "\r" not in body
    assert [p.get_filename() for p in m.iter_attachments()] == ["a.txt"]
    assert acc["_calls"]["append"][0][0] == "sent"
    assert send.sent_today(acc["id"]) == 3


def test_gmail_files_its_own_sent_copy(acc, smtp):
    acc = {**acc, "smtp_host": "127.0.0.1"}
    assert not send._auto_sent(acc)
    assert send._auto_sent({**acc, "smtp_host": "smtp.gmail.com"})
    assert send._auto_sent({**acc, "smtp_host": "smtp.office365.com"})


def test_a_reply_flags_the_original_and_a_sent_draft_is_dropped(acc, smtp):
    send.send(acc, {"to": "bob@example.com", "subject": "Re: x", "text": "ok", "in_reply_to": "<a@x>",
                    "references": "<z@x> <a@x>", "reply": {"folder": "INBOX", "uid": 7}, "draft": {"folder": "Drafts", "uid": 3}})
    m = _parsed(smtp.messages[-1]["data"])
    assert m["In-Reply-To"] == "<a@x>" and m["References"] == "<z@x> <a@x>"
    assert ("INBOX", [7], "answered") in acc["_calls"]["act"]
    assert acc["_calls"]["drop"] == [("Drafts", 3)]


def test_recipients_are_checked_and_capped(acc, smtp):
    with pytest.raises(MailError) as e:
        send.send(acc, {"to": "", "text": "x"})
    assert e.value.code == "invalid"
    with pytest.raises(MailError):
        send.send(acc, {"to": "not an address", "text": "x"})
    with pytest.raises(MailError):
        send.send(acc, {"to": "a@example.com\r\nBcc: evil@example.com", "text": "x"})
    with pytest.raises(MailError) as e:
        send.send(acc, {"to": [f"u{i}@example.com" for i in range(send.MAX_RECIPIENTS + 1)], "text": "x"})
    assert e.value.code == "limit" and "Resend" in e.value.message
    with pytest.raises(MailError):
        send.build(acc, {"to": "a@example.com", "subject": "x\nBcc: y@example.com", "text": ""})
    assert not smtp.messages


def test_the_daily_cap_counts_recipients_and_gives_back_on_failure(acc, smtp):
    _on(mail_send_per_day=3)
    send.send(acc, {"to": ["a@example.com", "b@example.com"], "subject": "s", "text": "x"})
    with pytest.raises(MailError) as e:
        send.send(acc, {"to": ["c@example.com", "d@example.com"], "subject": "s", "text": "x"})
    assert e.value.code == "limit"
    assert send.sent_today(acc["id"]) == 2
    smtp.stop()                                        # the server is gone: the try does not use the quota
    with pytest.raises(MailError):
        send.send(acc, {"to": "c@example.com", "subject": "s", "text": "x"})
    assert send.sent_today(acc["id"]) == 2


def test_the_daily_cap_is_counted_under_a_lock_shared_with_other_processes(acc):
    import fcntl
    import threading
    _on(mail_send_per_day=3)
    fd = os.open(config.STATE / ".mail-sent-count.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)                     # another process (`maxxing mail write --send`) is counting
    t = threading.Thread(target=send._take, args=(acc["id"], 2))
    t.start()
    t.join(0.3)
    assert t.is_alive() and send.sent_today(acc["id"]) == 0      # waits for it instead of reading a stale count
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    t.join(5)
    assert send.sent_today(acc["id"]) == 2


def test_every_recipient_refused_is_an_error(acc, smtp):
    with pytest.raises(MailError) as e:
        send.send(acc, {"to": "nobody@example.com", "subject": "s", "text": "x"})
    assert e.value.code == "refused"
    r = send.send(acc, {"to": ["nobody@example.com", "bob@example.com"], "subject": "s", "text": "x"})
    assert r["refused"] == ["nobody@example.com"]


ORIGINAL = {
    "uid": 7, "folder": "INBOX", "from": {"name": "Bob", "email": "bob@example.com"},
    "to": [{"name": "", "email": "me@example.com"}, {"name": "Carol", "email": "carol@example.com"}],
    "cc": [{"name": "", "email": "dan@example.com"}, {"name": "", "email": "ME@example.com"}], "reply_to": [], "bcc": [],
    "subject": "Plans", "date": 1_790_000_000, "message_id": "<m1@example.com>", "references": "<m0@example.com>",
    "in_reply_to": "", "text": "Hello\nSee you", "html": None, "attachments": [{"index": 3, "filename": "a.pdf", "content_type": "application/pdf", "size": 10}],
}


def test_compose_reply_reply_all_forward(acc, monkeypatch):
    monkeypatch.setattr(imap, "message", lambda *a, **k: dict(ORIGINAL))
    r = send.compose(acc, "reply", "INBOX", 7)
    assert r["to"] == ["Bob <bob@example.com>"] and r["cc"] == []
    assert r["subject"] == "Re: Plans" and r["in_reply_to"] == "<m1@example.com>"
    assert r["references"] == "<m0@example.com> <m1@example.com>"
    assert r["text"].startswith("\n\n-- \nMe\nACME\n\n") and "> Hello\n> See you" in r["text"]
    ra = send.compose(acc, "replyall", "INBOX", 7)
    assert ra["cc"] == ["Carol <carol@example.com>", "dan@example.com"]       # never oneself
    fw = send.compose(acc, "forward", "INBOX", 7)
    assert fw["to"] == [] and fw["subject"] == "Fwd: Plans" and fw["attachments"][0]["index"] == 3
    assert "Forwarded message" in fw["text"] and "See you" in fw["text"]
    monkeypatch.setattr(imap, "message", lambda *a, **k: {**ORIGINAL, "subject": "RE: Plans"})
    assert send.compose(acc, "reply", "INBOX", 7)["subject"] == "RE: Plans"
    with pytest.raises(MailError):
        send.compose(acc, "nope", "INBOX", 7)


def test_forwarded_attachments_are_read_from_the_mailbox(acc, smtp, monkeypatch):
    from email.message import EmailMessage
    orig = EmailMessage()
    orig.set_content("x")
    for i in range(8):
        orig.add_attachment(b"%PDF-" + str(i).encode(), maintype="application", subtype="pdf", filename=f"a{i}.pdf")
    fetched = []
    monkeypatch.setattr(imap, "raw_message", lambda acc, folder, uid: fetched.append(uid) or orig.as_bytes())
    send.send(acc, {"to": "bob@example.com", "subject": "Fwd", "text": "x",
                    "forward": {"folder": "INBOX", "uid": 7, "indexes": list(range(2, 10))}})
    m = _parsed(smtp.messages[-1]["data"])
    att = list(m.iter_attachments())
    assert [a.get_filename() for a in att] == [f"a{i}.pdf" for i in range(8)] and att[0].get_content() == b"%PDF-0"
    assert fetched == [7]                                   # one download of the mail, not one per attachment
    with pytest.raises(MailError) as e:
        send.build(acc, {"to": "bob@example.com", "forward": {"folder": "INBOX", "uid": 7, "indexes": [1, 99]}})
    assert e.value.code == "not_found"


def test_attachments_over_25_mb_are_refused(acc):
    with pytest.raises(MailError) as e:
        send.build(acc, {"to": "a@example.com", "text": ""}, [("big.bin", "", b"0" * (send.MAX_ATTACH + 1))])
    assert e.value.code == "too_large"


def test_a_draft_saved_again_replaces_the_previous_one(acc):
    d1 = send.save_draft(acc, {"to": "bob@example.com", "subject": "Draft", "text": "v1"})
    assert d1 == {"folder": "Drafts", "uid": 1}
    d2 = send.save_draft(acc, {"to": "bob@example.com", "subject": "Draft", "text": "v2", "draft": d1})
    assert d2["uid"] == 2 and acc["_calls"]["drop"] == [("Drafts", 1)]
    assert "v2" in _parsed(acc["_calls"]["drafts"][-1]).get_body(("plain",)).get_content()


# ---------------------------------------------------------------- API

def test_api_is_off_until_switched_on(client):
    assert client.get("/api/mail/accounts").status_code == 409
    assert client.get("/api/settings").json()["mail_page"] is False
    assert client.put("/api/settings", json={"mail_page": True}).json()["mail_page"] is True
    assert client.get("/api/mail/accounts").json() == []


def test_api_send_with_attachments_and_the_cap(client, acc, smtp):
    rows = client.get("/api/mail/accounts").json()
    assert rows[0]["sent_today"] == 0 and rows[0]["send_per_day"] == send.DEFAULT_PER_DAY
    data = {"to": ["bob@example.com"], "cc": [], "bcc": [], "subject": "From the page", "text": "Hi"}
    r = client.post(f"/api/mail/{acc['id']}/send", data={"data": json.dumps(data)},
                    files=[("files", ("n.txt", b"note", "text/plain"))])
    assert r.status_code == 200, r.text
    m = _parsed(smtp.messages[-1]["data"])
    assert [p.get_filename() for p in m.iter_attachments()] == ["n.txt"]
    assert client.get("/api/mail/accounts").json()[0]["sent_today"] == 1
    _on(mail_send_per_day=1)
    r = client.post(f"/api/mail/{acc['id']}/send", data={"data": json.dumps(data)})
    assert r.status_code == 429 and r.json()["error"] == "limit", r.json()
    assert client.post(f"/api/mail/{acc['id']}/send", data={"data": "[1]"}).status_code == 400


def test_api_draft_and_compose(client, acc, monkeypatch):
    monkeypatch.setattr(imap, "message", lambda *a, **k: dict(ORIGINAL))
    r = client.get(f"/api/mail/{acc['id']}/compose", params={"mode": "replyall", "uid": 7})
    assert r.status_code == 200 and r.json()["subject"] == "Re: Plans"
    r = client.post(f"/api/mail/{acc['id']}/draft", data={"data": json.dumps({"to": ["bob@example.com"], "text": "x"})})
    assert r.json() == {"folder": "Drafts", "uid": 1}


# ---------------------------------------------------------------- CLI

def test_cli_write_saves_a_draft_unless_send(acc, smtp, monkeypatch, capsys):
    import io
    from maxxing import cli
    monkeypatch.setattr("sys.stdin", io.StringIO("Thanks, see you Monday."))
    assert cli.main(["mail", "write", "--to", "bob@example.com", "-s", "Monday"]) == 0
    assert "draft saved" in capsys.readouterr().out
    body = _parsed(acc["_calls"]["drafts"][-1]).get_body(("plain",)).get_content()
    assert body.startswith("Thanks, see you Monday.\n\n-- \nMe\nACME")
    assert not smtp.messages
    monkeypatch.setattr("sys.stdin", io.StringIO("Now."))
    assert cli.main(["mail", "write", "--to", "bob@example.com", "-s", "Now", "--send"]) == 0
    assert len(smtp.messages) == 1


# ---------------------------------------------------------------- a real IMAP server (opt-in)

@pytest.mark.skipif(not os.environ.get("MAXXING_TEST_IMAP"), reason="MAXXING_TEST_IMAP=host:port:user:password not set")
def test_real_imap_round_trip(mx, smtp):
    host, port, user, pw = os.environ["MAXXING_TEST_IMAP"].split(":", 3)
    _on()
    smtp.user, smtp.password = user, pw
    a, res = mail.add_account({"address": user, "imap_host": host, "imap_port": int(port), "imap_tls": "none",
                               "smtp_host": "127.0.0.1", "smtp_port": smtp.port, "smtp_tls": "none"}, pw)
    assert res["imap"] == "ok" and res["smtp"] == "ok"
    names = {f["role"]: f["name"] for f in imap.folders(a)}
    sent_before = imap.messages(a, names["sent"])["total"]
    send.send(a, {"to": user, "subject": "Round trip é", "text": "body"}, [("x.txt", "text/plain", b"x")])
    assert imap.messages(a, names["sent"])["total"] == sent_before + 1
    with imap.session(a) as m:                         # deliver it to the inbox (the fake SMTP does not)
        m.append('"INBOX"', "()", None, smtp.messages[-1]["data"])
    top = imap.messages(a, "INBOX", q="Round trip")["messages"][0]
    fw = send.compose(a, "forward", "INBOX", top["uid"])
    d = send.save_draft(a, {**fw, "to": [user], "forward": {"folder": "INBOX", "uid": top["uid"], "indexes": [x["index"] for x in fw["attachments"]]}})
    back = send.compose(a, "draft", d["folder"], d["uid"])
    assert back["subject"] == "Fwd: Round trip é" and [x["filename"] for x in back["attachments"]] == ["x.txt"]
    send.send(a, {**back, "draft": d, "forward": {"folder": d["folder"], "uid": d["uid"], "indexes": [x["index"] for x in back["attachments"]]},
                  "reply": {"folder": "INBOX", "uid": top["uid"]}})
    assert imap.messages(a, d["folder"], q="Round trip")["total"] == 0           # the draft is gone once sent
    assert imap.message(a, "INBOX", top["uid"])["answered"]
    imap.act(a, "INBOX", [top["uid"]], "trash")
