"""The real mail/imap.py against a fake IMAP server (fake_imap.py), and what an agent can make `maxxing mail` (root,
outside its sandbox) do: injected IMAP commands, files swapped for links, forged sender checks, contacts, checks
running twice, mail lost past one check, a send cut in the middle, the page switched off."""
from __future__ import annotations

import email.message
import os
import threading
import time

import pytest

from fake_imap import FakeIMAP
from fake_smtp import FakeSMTP
from maxxing import agents, config, feed, mail
from maxxing.mail import access, imap, outbox, poll, store
from test_agents import A, _create
from test_agents import _on as _agents_on
from test_mail_agents import PW, _as_agent, _cli, _grant, _mail_on

GOOGLE = "mx.google.com; dkim=pass header.d={d} header.s=s1; spf=pass smtp.mailfrom=bounce@{d}"


def _raw(sender: str, subject: str = "Hello", ar: list[str] | None = None, body: str = "body") -> bytes:
    m = email.message.EmailMessage()
    for h in ar or []:
        m["Authentication-Results"] = h
    m["From"], m["To"], m["Subject"] = sender, "me@example.com", subject
    m["Message-ID"] = f"<{time.time_ns()}@{sender.split('@')[-1]}>"
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
def acc(client, topic, srv, smtp):
    _mail_on()
    a, _ = mail.add_account({"address": "me@example.com", "imap_host": "127.0.0.1", "imap_port": srv.port,
                             "imap_tls": "none", "smtp_host": "127.0.0.1", "smtp_port": smtp.port,
                             "smtp_tls": "none"}, PW)
    _agents_on(client)
    _create(client)
    yield a
    imap.forget(a["id"])


# ---------------------------------------------------------------- injected IMAP commands

def test_a_search_never_sends_its_own_imap_commands(client, acc, srv, monkeypatch, capsys):
    uid = srv.add("INBOX", _raw("bob@x.org"))
    _grant(client, rights=["read"])
    _as_agent(monkeypatch)
    for q in ('x"\r\nA9 UID STORE 1:* +FLAGS (\\Deleted)\r\nA10 EXPUNGE\r\nA11 NOOP "', "x\nA9 EXPUNGE", "x\0y\x85z "):
        code, _, err = _cli(capsys, "list", "-s", q)
        assert code == 0, err
    assert srv.sent("STORE") == [] and srv.sent("EXPUNGE") == []
    assert uid in srv.folders["INBOX"].messages
    assert not any("\r" in c or "\n" in c for c in srv.commands)
    # the text is still searched (control characters become spaces)
    assert imap._search_args("Invoice\r\n12", False, False) == (['TEXT "Invoice 12"'], None)
    assert imap._search_args("Facture n°\n12", False, False) == (["ALL"], "Facture n° 12".encode())


def test_the_real_imap_code_lists_reads_and_files(client, acc, srv):
    srv.add("INBOX", _raw("bob@x.org", "First"))
    u2 = srv.add("INBOX", _raw("ann@y.org", "Second", body="hello there"))
    res = imap.messages(acc, "INBOX")
    assert [m["subject"] for m in res["messages"]] == ["Second", "First"]
    assert imap.messages(acc, "INBOX", q="hello")["total"] == 1
    m = imap.message(acc, "INBOX", u2, mark_seen=False)
    assert "hello there" in m["text"] and "\\Seen" not in srv.folders["INBOX"].messages[u2]["flags"]
    imap.act(acc, "INBOX", [u2], "archive")
    assert len(srv.folders["Archive"].messages) == 1 and u2 not in srv.folders["INBOX"].messages


# ---------------------------------------------------------------- files: root opens what the agent named

def _agent_dir() -> str:
    return str(config.workspace() / A)


def test_an_attachment_never_lands_through_a_link(client, acc, srv, monkeypatch, capsys, tmp_path):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = "bob@x.org", "me@example.com", "File"
    m.set_content("see file")
    m.add_attachment(b"PAYLOAD", maintype="application", subtype="octet-stream", filename="a.bin")
    uid = srv.add("INBOX", m.as_bytes())
    _grant(client, rights=["read"])
    _as_agent(monkeypatch)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    d = _agent_dir()
    os.symlink(victim, f"{d}/out.bin")                                    # a link where the file goes
    code, _, err = _cli(capsys, "attachment", str(uid), "2", f"{d}/out.bin")
    assert code == 1 and victim.read_text() == "keep me" and "own folder" in err
    os.makedirs(f"{d}/files")                                             # its folder swapped for a link
    from maxxing import cmd_mail
    real = cmd_mail.Guard.writable

    def swap(self, f):                                                    # checked, then swapped
        p = real(self, f)
        if os.path.isdir(f"{d}/files") and not os.path.islink(f"{d}/files"):
            os.rmdir(f"{d}/files")
            os.symlink(tmp_path, f"{d}/files")
        return p
    monkeypatch.setattr(cmd_mail.Guard, "writable", swap)
    code, _, err = _cli(capsys, "attachment", str(uid), "2", f"{d}/files/victim.txt")
    assert code == 1 and victim.read_text() == "keep me" and "own folder" in err, err
    monkeypatch.setattr(cmd_mail.Guard, "writable", real)
    os.link(f"{d}/agent.json", f"{d}/hard.bin") if os.path.exists(f"{d}/agent.json") else None
    if os.path.exists(f"{d}/hard.bin"):                                   # a second name of a locked file
        before = open(f"{d}/agent.json", "rb").read()
        code, _, err = _cli(capsys, "attachment", str(uid), "2", f"{d}/hard.bin")
        assert code == 1 and open(f"{d}/agent.json", "rb").read() == before and "ordinary file" in err, err
    code, out, err = _cli(capsys, "attachment", str(uid), "2", f"{d}/")
    assert code == 0, err
    assert open(f"{d}/a.bin", "rb").read() == b"PAYLOAD"


def cmd_guard():
    from maxxing import cmd_mail
    return cmd_mail.Guard(A)


def test_an_attached_file_is_read_where_it_really_is(client, acc, monkeypatch, capsys):
    _grant(client, rights=["read", "draft"])
    _as_agent(monkeypatch)
    d = _agent_dir()
    secret = config.STATE / "private-note.txt"          # under the state dir: never for an agent
    secret.write_text('{"k": "SECRET"}')
    os.symlink(secret, f"{d}/notes.txt")
    code, _, err = _cli(capsys, "write", "--to", "bob@x.org", "-s", "S", "--attach", f"{d}/notes.txt", stdin="x",
                        monkeypatch=monkeypatch)
    assert code == 1 and ("not readable" in err or "of its topic only" in err), err
    g = cmd_guard()
    ok = f"{d}/ok.txt"
    open(ok, "w").write("fine")
    real = g.readable

    def swap(f):                                                         # checked, then swapped for a link
        p = real(f)
        if f == ok and not os.path.islink(ok):
            os.remove(ok)
            os.symlink(secret, ok)
        return p
    monkeypatch.setattr(g, "readable", swap)
    with pytest.raises(Exception) as e:
        g.read_file(ok, 1000)
    assert "SECRET" not in str(e.value)
    os.remove(ok)
    open(ok, "w").write("fine")
    os.link(ok, f"{d}/twice.txt")
    with pytest.raises(Exception):
        cmd_guard().read_file(ok, 1000)                                   # two names: refused
    os.remove(f"{d}/twice.txt")
    assert cmd_guard().read_file(ok, 1000)[1] == b"fine"


# ---------------------------------------------------------------- who checked the sender

def test_comments_and_quoted_strings_never_pass_a_sender():
    t = {"google.com"}
    trap = 'mx.google.com; dkim=fail (dkim=pass header.d=stripe.com) reason="dkim=pass header.d=stripe.com"'
    assert not access.verified(trap, "a@stripe.com", t)
    assert not access.verified('(mx.google.com) evil.test; dkim=pass header.d=stripe.com', "a@stripe.com", t)
    assert access.verified(GOOGLE.format(d="stripe.com"), "a@stripe.com", t)
    assert access.authserv_id("mx.google.com (comment); spf=pass") == "mx.google.com"
    assert access.authserv_id("spf=pass smtp.mailfrom=x.org") == ""      # no authserv-id


def test_a_provider_is_trusted_only_when_it_stamps_all_mail():
    gmail = {"address": "me@gmail.com", "imap_host": "imap.gmail.com", "smtp_host": "smtp.gmail.com"}
    stamped = [("mx.google.com", f"x@d{i % 5}.org") for i in range(20)]
    assert access.detect(stamped, "gmail.com") == "google.com"
    assert access.sender_check(gmail, "google.com", ["gmail-smtp-in.l.google.com"])["state"] == "auto"
    assert access.detect(stamped[:5], "gmail.com") == ""                  # too few mails to know
    assert access.detect([("mx.google.com", "x@a.org")] * 20, "gmail.com") == ""   # one sender only
    # a provider that writes nothing: each sender's own header is on top - nothing is trusted
    mixed = [("mx.google.com", "x@a.org"), ("", "y@b.org"), ("mail.c.org", "z@c.org")] * 6
    assert access.detect(mixed, "example.com") == ""
    own = {"address": "me@example.com", "imap_host": "mail.example.com", "smtp_host": "mail.example.com"}
    assert access.sender_check(own, "", [])["state"] == "none"
    # one server tops everything but is not a known provider: the owner confirms it (auth_servers)
    assert access.sender_check(own, "example.com", [])["state"] == "detected"
    assert access.sender_check({**own, "auth_servers": ["mail.example.com"]}, "", [])["state"] == "owner"
    # mail flooded with a header naming a known provider does not move the mailbox there
    assert access.sender_check(own, "google.com", ["mx.example.com"])["state"] == "detected"


def test_a_header_planted_by_the_sender_proves_nothing(client, acc, srv, monkeypatch):
    # the fake provider writes no Authentication-Results: a sender plants one naming the mailbox's own server
    for i in range(12):
        srv.add("INBOX", _raw(f"x@d{i % 4}.org", f"m{i}"))
    srv.add("INBOX", _raw("billing@stripe.com", "Pay", ar=["127.0.0.1; dkim=pass header.d=stripe.com"]))
    poll.poll_account(acc, fire=False)
    assert mail.public(mail.get_account(acc["id"]))["sender_check"]["state"] == "none"
    got = {m["subject"]: m["from_verified"] for m in imap.messages(acc, "INBOX")["messages"]}
    assert got["Pay"] is False
    # the owner says the provider checks the senders (it does: every mail gets its header) -> verified
    mail.update_account(acc["id"], {"auth_servers": ["imap.example.net"]})
    a = mail.get_account(acc["id"])
    srv.add("INBOX", _raw("billing@stripe.com", "Real", ar=["imap.example.net; dkim=pass header.d=stripe.com"]))
    got = {m["subject"]: m["from_verified"] for m in imap.messages(a, "INBOX")["messages"]}
    assert got["Real"] is True and got["Pay"] is False


# ---------------------------------------------------------------- the checks

def test_a_new_uidvalidity_is_a_first_look(client, acc, srv, monkeypatch):
    _grant(client, rights=["read"], trigger={"enabled": True})
    fired = []
    monkeypatch.setattr(agents, "fire", lambda path, **kw: fired.append(kw) or {"started": True})
    srv.add("INBOX", _raw("bob@x.org", "old"))
    assert poll.poll_account(acc)["started"] == 0
    srv.add("INBOX", _raw("bob@x.org", "new"))
    r = poll.poll_account(acc)
    assert r["new"] == 1 and r["started"] == 1
    srv.uidvalidity("INBOX", 99)                                          # the server rebuilt its index
    srv.add("INBOX", _raw("bob@x.org", "after"))
    r = poll.poll_account(acc)
    assert r["new"] == 0 and r["started"] == 0 and len(fired) == 1       # old mail never starts an agent again
    assert store.position(acc["id"], "INBOX")["uidvalidity"] == 99
    srv.add("INBOX", _raw("bob@x.org", "later"))
    assert poll.poll_account(acc)["new"] == 1


def test_no_mail_is_lost_past_one_check(client, acc, srv, monkeypatch):
    poll.poll_account(acc, fire=False)
    for i in range(450):
        srv.add("INBOX", _raw(f"x{i}@d.org", f"n{i}"))
    seen = []
    for _ in range(3):
        r = poll.poll_account(acc, fire=False)
        seen.append(r["new"])
    assert seen == [200, 200, 50]
    assert store.position(acc["id"], "INBOX")["last_uid"] == max(srv.folders["INBOX"].messages)
    assert not poll.due(acc)


def test_a_check_already_running_is_skipped(client, acc, srv, monkeypatch):
    import fcntl
    p = config.state_dir("mail") / f".poll-{acc['id']}.lock"
    fd = os.open(p, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)                                        # another process is checking it
    try:
        r = poll.poll_account(acc)
        assert r["skipped"] == "busy" and srv.sent("SEARCH") == []
    finally:
        os.close(fd)
    gate, out = threading.Event(), []
    real = imap.new_since

    def slow(*a, **k):
        gate.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(imap, "new_since", slow)
    t = threading.Thread(target=lambda: out.append(poll.poll_account(acc)))
    t.start()
    time.sleep(0.2)
    assert poll.poll_account(acc).get("skipped") == "busy"                # same process, another thread
    gate.set()
    t.join(10)
    assert out and out[0]["ok"] and "skipped" not in out[0]


def test_an_agent_refresh_starts_no_agent(client, acc, srv, monkeypatch, capsys):
    _grant(client, rights=["read"], trigger={"enabled": True})
    fired = []
    monkeypatch.setattr(agents, "fire", lambda path, **kw: fired.append(kw) or {"started": True})
    poll.poll_account(acc)
    srv.add("INBOX", _raw("bob@x.org", "new"))
    _as_agent(monkeypatch)
    code, out, _ = _cli(capsys, "refresh")
    assert code == 0 and "1 new, 0 agent run" in out and not fired


# ---------------------------------------------------------------- contacts, outbox, page off

def test_incoming_mail_makes_nobody_a_contact(client, acc, srv):
    poll.poll_account(acc, fire=False)
    srv.add("INBOX", _raw("eve@evil.test", "hi"))
    poll.poll_account(acc, fire=False)
    assert store.unknown(acc["id"], ["eve@evil.test"]) == ["eve@evil.test"]


def test_a_send_cut_in_the_middle_waits_again(client, acc, monkeypatch, capsys, smtp):
    _grant(client, rights=["read", "send"], approve_send="always")
    _as_agent(monkeypatch)
    assert _cli(capsys, "write", "--to", "bob@x.org", "-s", "S", "--send", stdin="x", monkeypatch=monkeypatch)[0] == 0
    [w] = outbox.pending()
    from maxxing.mail import send

    def boom(*a, **k):
        raise RuntimeError("cut")
    monkeypatch.setattr(send, "send", boom)
    with pytest.raises(RuntimeError):
        outbox.approve(w["id"])
    assert store.outbox_get(w["id"])["status"] == "waiting"             # any failure: the owner may try again
    store.outbox_claim(w["id"], "sending")                                 # the server stopped mid-send
    with store.conn() as c:
        c.execute("UPDATE outbox SET done_at=? WHERE id=?", (time.time() - 3600, w["id"]))
    assert outbox.unstick() == 1
    row = store.outbox_get(w["id"])
    assert row["status"] == "waiting" and "Sent folder" in row["note"]


def test_an_agent_sees_only_its_own_waiting_messages(client, acc, monkeypatch, capsys, smtp):
    _grant(client, rights=["read", "send"], approve_send="always")
    _as_agent(monkeypatch)
    assert _cli(capsys, "write", "--to", "bob@x.org", "-s", "Mine", "--send", stdin="x", monkeypatch=monkeypatch)[0] == 0
    store.outbox_put({"id": "o_other", "account": acc["id"], "agent": "projects/acme/topics/blog/agents/other",
                      "at": time.time(), "status": "waiting", "data": {"draft": {"subject": "Theirs"}}})
    code, out, _ = _cli(capsys, "outbox")
    assert "Mine" in out and "Theirs" not in out
    code, _, err = _cli(capsys, "list", "-a", "someone@else.org")
    assert code == 1 and "me@example.com" in err and "someone" in err
    mail.add_account({"address": "boss@example.com", "imap_host": "127.0.0.1", "imap_port": 1, "imap_tls": "none",
                      "smtp_host": "127.0.0.1", "smtp_port": 1, "smtp_tls": "none"}, "pw", skip_test=True)
    code, _, err = _cli(capsys, "list", "-a", "nobody@x.org")
    assert "boss@example.com" not in err                                  # the other mailboxes stay unnamed


def test_the_page_switched_off_stops_the_cli_and_the_buttons(client, acc, monkeypatch, capsys, smtp):
    _grant(client, rights=["read", "send"], approve_send="always")
    _as_agent(monkeypatch)
    assert _cli(capsys, "write", "--to", "bob@x.org", "-s", "S", "--send", stdin="x", monkeypatch=monkeypatch)[0] == 0
    [w] = outbox.pending()
    c = config.load_config()
    c["mail_page"] = False
    config.save_config(c)
    code, _, err = _cli(capsys, "list")
    assert code == 1 and "switched off" in err
    r = client.post(f"/api/feed/{w['event_id']}/act/allow")
    assert r.status_code == 409 and not smtp.messages
    assert feed.get(w["event_id"])["resolved"] in (0, False, None)
