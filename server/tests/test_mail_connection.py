"""The IMAP connection of a mailbox (mail/imap.py session()), its folders and the accounts file: a slow or silent mail
server never holds the rest of Harness, the folder list is not asked again for nothing, EXPUNGE only removes our
mails, roles follow the server's flags, Gmail archives to All Mail, sign-in in UTF-8, accounts.json under a lock."""
from __future__ import annotations

import concurrent.futures as cf
import email.message
import socket
import threading
import time

import pytest

from fake_imap import FakeIMAP
from maxxing import mail
from maxxing.mail import imap
from maxxing.mail.imap import MailError
from test_mail_agents import PW, _mail_on


def _raw(subject: str = "Hello", pdf: bool = False) -> bytes:
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = "a@b.example", "me@example.com", subject
    m.set_content("body")
    if pdf:
        m.add_attachment(b"%PDF-1.4 test", maintype="application", subtype="pdf", filename="doc.pdf")
        m.add_attachment(b"<script>x</script>", maintype="text", subtype="html", filename="page.html")
    return m.as_bytes()


def _account(port: int, address: str = "me@example.com") -> dict:
    a, _ = mail.add_account({"address": address, "imap_host": "127.0.0.1", "imap_port": port, "imap_tls": "none",
                             "smtp_host": "127.0.0.1", "smtp_port": 1, "smtp_tls": "none"}, PW, skip_test=True)
    return a


@pytest.fixture
def srv():
    s = FakeIMAP("me@example.com", PW).start()
    yield s
    s.stop()


@pytest.fixture
def acc(client, srv):
    _mail_on()
    a = _account(srv.port)
    yield a
    imap.forget(a["id"])


class Stuck:
    """An IMAP server that signs in, then never answers again (`greet=False`: not even the greeting)."""

    def __init__(self, greet: bool = True):
        self.greet = greet
        self.conns: list[socket.socket] = []
        self.s = socket.socket()
        self.s.bind(("127.0.0.1", 0))
        self.s.listen(50)
        self.port = self.s.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.s.accept()
            except OSError:
                return
            self.conns.append(c)
            if self.greet:
                threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        f = c.makefile("rb")
        c.sendall(b"* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] ready\r\n")
        for line in f:
            tag, _, rest = line.decode().partition(" ")
            if rest.upper().startswith("AUTHENTICATE"):
                c.sendall(b"+ \r\n")
                f.readline()
                c.sendall(f"{tag} OK signed in\r\n".encode())
            elif rest.upper().startswith(("LOGIN", "CAPABILITY")):
                c.sendall(f"{tag} OK done\r\n".encode())
            # anything else: silence

    def stop(self):
        self.s.close()
        for c in self.conns:
            c.close()


def test_a_stuck_mail_server_never_slows_the_rest_of_harness(client, monkeypatch):
    monkeypatch.setattr(imap, "TIMEOUT_S", 4)
    monkeypatch.setattr(imap, "LOCK_WAIT_S", 2)
    st = Stuck()
    _mail_on()
    a = _account(st.port)
    try:
        t0 = time.time()
        assert client.get("/api/approvals").status_code == 200
        base = time.time() - t0
        with cf.ThreadPoolExecutor(20) as ex:
            futs = [ex.submit(client.get, f"/api/mail/{a['id']}/messages") for _ in range(12)]
            time.sleep(0.5)
            slow = []
            for _ in range(5):                                   # other routes, sign-in included, answer at once
                t0 = time.time()
                assert client.get("/api/approvals").status_code == 200
                slow.append(time.time() - t0)
            codes = [f.result().status_code for f in futs]
        assert max(slow) < base + 1.0, slow
        assert codes.count(503) >= 9, codes                      # waiting callers get "busy", never a queue
        r = next(f.result() for f in futs if f.result().status_code == 503)
        assert r.json()["error"] == "mail_busy" and r.headers.get("retry-after")
        assert 424 in codes                                     # the one that held the server: it stopped answering
    finally:
        imap.forget(a["id"])
        st.stop()


def test_a_silent_server_is_not_waited_for_again_and_again(client, monkeypatch):
    monkeypatch.setattr(imap, "CONNECT_S", 1)
    st = Stuck(greet=False)
    _mail_on()
    a = _account(st.port)
    try:
        t0 = time.time()
        with pytest.raises(MailError) as e:
            imap.folders(a)
        assert e.value.code == "unreachable" and time.time() - t0 >= 0.9
        t0 = time.time()
        for f in ("INBOX", "Invoices", "Work"):                 # the check of the mailbox, folder after folder
            with pytest.raises(MailError) as e:
                imap.new_since(a, f, None)
            assert e.value.code == "unreachable"
        assert time.time() - t0 < 0.5
        imap.forget(a["id"])                                    # settings changed: tried again at once
        t0 = time.time()
        with pytest.raises(MailError):
            imap.folders(a)
        assert time.time() - t0 >= 0.9
    finally:
        imap.forget(a["id"])
        st.stop()


def test_the_page_and_the_refresh_ask_for_every_uid_only_when_the_folder_changed(acc, srv):
    for i in range(5):
        srv.add("INBOX", _raw(f"m{i}"))
    first = imap.messages(acc, "INBOX", size=2)
    n = len(srv.sent("SEARCH"))
    again = imap.messages(acc, "INBOX", page=1, size=2)
    assert len(srv.sent("SEARCH")) == n
    assert [r["uid"] for r in first["messages"]] == [5, 4] and [r["uid"] for r in again["messages"]] == [3, 2]
    srv.add("INBOX", _raw("new"))                               # UIDNEXT moved: asked again
    assert imap.messages(acc, "INBOX", size=2)["messages"][0]["uid"] == 6
    assert len(srv.sent("SEARCH")) == n + 1
    imap.act(acc, "INBOX", [6], "trash")                         # EXISTS dropped: asked again
    assert imap.messages(acc, "INBOX", size=2)["messages"][0]["uid"] == 5
    assert imap.messages(acc, "INBOX", q="m1")["total"] == 1     # a search always asks


def test_without_uidplus_only_our_mails_are_erased(client):
    srv = FakeIMAP("me@example.com", PW, caps="IMAP4rev1 AUTH=PLAIN").start()
    _mail_on()
    a = _account(srv.port)
    try:
        other = srv.add("INBOX", _raw("marked deleted by another app"), flags=("\\Deleted",))
        mine = srv.add("INBOX", _raw("to archive"))
        imap.act(a, "INBOX", [mine], "archive")
        box = srv.folders["INBOX"].messages
        assert list(box) == [other] and "\\Deleted" in box[other]["flags"]
        assert len(srv.folders["Archive"].messages) == 1
        t1 = srv.add("Trash", _raw("t1"), flags=("\\Deleted",))
        t2 = srv.add("Trash", _raw("t2"))
        imap.act(a, "Trash", [t2], "delete")
        assert list(srv.folders["Trash"].messages) == [t1]
    finally:
        imap.forget(a["id"])
        srv.stop()


def test_the_flagged_folder_wins_over_one_only_named_like_it(acc, srv):
    sent = srv.folders.pop("Sent")
    srv.folders = {"Sent": type(sent)("Sent"), "Sent Items": sent, **srv.folders}   # a plain "Sent" listed first
    sent.name, sent.special = "Sent Items", "\\Sent"
    roles = {f["name"]: f["role"] for f in imap.folders(acc, counts=False)}
    assert roles["Sent Items"] == "sent" and roles["Sent"] is None
    assert imap.append(acc, "sent", _raw("copy")) == "Sent Items"


def test_gmail_archive_goes_to_all_mail(client):
    srv = FakeIMAP("me@example.com", PW, caps="IMAP4rev1 AUTH=PLAIN UIDPLUS MOVE X-GM-EXT-1").start()
    srv.folders.pop("Archive")
    from fake_imap import Folder
    srv.folders["[Gmail]/All Mail"] = Folder("[Gmail]/All Mail", "\\All")
    _mail_on()
    a = _account(srv.port)
    try:
        uid = srv.add("INBOX", _raw())
        assert imap.act(a, "INBOX", [uid], "archive")["moved_to"] == "[Gmail]/All Mail"
        assert "Archive" not in srv.folders and not srv.sent("CREATE")
    finally:
        imap.forget(a["id"])
        srv.stop()


def test_a_user_name_with_accents_signs_in_or_says_why(client):
    srv = FakeIMAP("jösé@example.com", "plain").start()
    try:
        imap.open_imap("127.0.0.1", srv.port, "none", "jösé@example.com", "plain").logout()   # AUTHENTICATE PLAIN
        srv.caps = "IMAP4rev1"
        with pytest.raises(MailError) as e:
            imap.open_imap("127.0.0.1", srv.port, "none", "jösé@example.com", "plain")
        assert e.value.code == "auth" and "ASCII" in e.value.message
    finally:
        srv.stop()


def _smtp_answering(auth_line: bytes, offer_auth: bool) -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()

    def run():
        c, _ = s.accept()
        f = c.makefile("rb")
        c.sendall(b"220 fake ESMTP\r\n")
        for line in f:
            cmd = line[:4].upper()
            if cmd in (b"EHLO", b"HELO"):
                c.sendall(b"250-fake\r\n250-AUTH PLAIN\r\n250 8BITMIME\r\n" if offer_auth else b"250-fake\r\n250 8BITMIME\r\n")
            elif cmd == b"AUTH":
                c.sendall(auth_line)
            elif cmd == b"QUIT":
                c.sendall(b"221 bye\r\n")
                break
            else:
                c.sendall(b"250 ok\r\n")
        c.close()
        s.close()
    threading.Thread(target=run, daemon=True).start()
    return s.getsockname()[1]


@pytest.mark.parametrize("offer_auth", [True, False])
def test_an_smtp_503_is_never_a_sign_in(offer_auth):
    port = _smtp_answering(b"503 5.5.1 Error: authentication not enabled\r\n", offer_auth)
    with pytest.raises(MailError) as e:
        mail.open_smtp("127.0.0.1", port, "none", "me@example.com", "pässword")
    assert e.value.code == "auth"


def test_two_mailboxes_added_at_once_are_both_kept(client, monkeypatch):
    _mail_on()

    def slow_test(acc, pw):
        time.sleep(0.3)
        return {"imap": "ok", "smtp": "error", "smtp_error": "x", "smtp_code": "unreachable"}
    monkeypatch.setattr(mail, "test", slow_test)
    data = {"imap_host": "127.0.0.1", "imap_port": 1, "imap_tls": "none", "smtp_host": "127.0.0.1", "smtp_port": 1,
            "smtp_tls": "none"}
    with cf.ThreadPoolExecutor(2) as ex:
        list(ex.map(lambda ad: mail.add_account({**data, "address": ad}, PW), ["a@example.com", "b@example.com"]))
    assert {a["address"] for a in mail.list_accounts()} == {"a@example.com", "b@example.com"}
    a = mail.get_account("a@example.com")
    with cf.ThreadPoolExecutor(2) as ex:                         # a change tested while the mailbox is removed
        f = ex.submit(mail.update_account, a["id"], {"imap_port": 2}, None)
        time.sleep(0.1)
        mail.delete_account(a["id"])
        with pytest.raises(MailError) as e:
            f.result()
    assert e.value.code == "no_account"
    assert [x["address"] for x in mail.list_accounts()] == ["b@example.com"]


def test_a_pdf_opens_in_the_browser_and_html_stays_sandboxed(client, acc, srv):
    uid = srv.add("INBOX", _raw(pdf=True))
    m = client.get(f"/api/mail/{acc['id']}/message", params={"uid": uid}).json()
    idx = {x["content_type"]: x["index"] for x in m["attachments"]}
    pdf = client.get(f"/api/mail/{acc['id']}/attachment", params={"uid": uid, "index": idx["application/pdf"], "inline": 1})
    assert pdf.headers["content-type"] == "application/pdf" and pdf.headers["content-disposition"].startswith("inline")
    assert "content-security-policy" not in pdf.headers and pdf.headers["x-content-type-options"] == "nosniff"
    html = client.get(f"/api/mail/{acc['id']}/attachment", params={"uid": uid, "index": idx["text/html"], "inline": 1})
    assert html.headers["content-type"] == "application/octet-stream" and html.headers["content-security-policy"] == "sandbox"
    dl = client.get(f"/api/mail/{acc['id']}/attachment", params={"uid": uid, "index": idx["application/pdf"]})
    assert dl.headers["content-security-policy"] == "sandbox" and dl.headers["content-disposition"].startswith("attachment")


def test_an_8bit_attachment_type_downloads_instead_of_a_500(client, acc, srv):
    """`image/\\xe9` read as image/\\ufffd passed as an image, then the header could not be encoded (500)."""
    uid = srv.add("INBOX", b"From: a@b.co\r\nTo: me@example.com\r\nSubject: x\r\nContent-Type: multipart/mixed; boundary=B"
                  b"\r\n\r\n--B\r\nContent-Type: text/plain\r\n\r\nhi\r\n--B\r\nContent-Type: image/\xe9; name=a.png\r\n\r\nxx"
                  b"\r\n--B--\r\n")
    r = client.get(f"/api/mail/{acc['id']}/attachment", params={"uid": uid, "index": 2, "inline": 1})
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment")
