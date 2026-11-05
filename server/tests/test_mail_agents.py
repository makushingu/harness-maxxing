"""Agents and the E-mail page: an agent's `mail` setting (mail/access.py), `maxxing mail` in an agent turn, the
check of the mailboxes and its trigger (mail/poll.py), messages waiting for the owner's OK (mail/outbox.py),
"seen by" (mail/store.py).

IMAP is faked here; with MAXXING_TEST_IMAP=host:port:user:password (a plain-text IMAP server, e.g. a local Dovecot)
test_real_imap_check_and_senders also runs against a real server.
"""
from __future__ import annotations

import email
import email.policy
import os
import time

import pytest

from fake_smtp import FakeSMTP
from maxxing import agents, cmd_mail, config, feed, mail
from maxxing.mail import access, imap, outbox, poll, send, store
from test_agents import A, _create
from test_agents import _on as _agents_on

PW = "pässword"
AR_OK = "mx.example.net; dkim=pass header.d=stripe.com header.s=s1; spf=pass smtp.mailfrom=bounce@stripe.com"


def _mail_on():
    c = config.load_config()
    c.update({"mail_page": True, "agents_page": True})
    config.save_config(c)


def _msg(sender: str, subject: str = "Hello", ar: list[str] | None = None) -> email.message.EmailMessage:
    m = email.message.EmailMessage()
    for h in ar or []:
        m["Authentication-Results"] = h
    m["From"], m["To"], m["Subject"] = sender, "me@example.com", subject
    m.set_content("body")
    return m


# ---------------------------------------------------------------- access.py

def test_grants_are_cleaned_and_strict_refuses_bad_values():
    g = access.clean_grants([{"account": "me-example", "senders": ["Stripe.com", "@acme.io", "bob@x.org"]},
                             {"account": "me-example"}, "junk", {"account": "BAD ID!"}])
    assert g == [{"account": "me-example", "rights": ["read", "draft"], "approve_send": "always", "trigger": None,
                  "senders": ["*@stripe.com", "*@acme.io", "bob@x.org"]}]
    for bad in ([{"account": "a", "rights": ["fly"]}], [{"account": "a", "approve_send": "maybe"}],
                [{"account": "a", "senders": ["not an address"]}]):
        with pytest.raises(access.AccessError):
            access.clean_grants(bad, strict=True)
    t = access.clean_grants([{"account": "a", "trigger": {"folder": "", "subject": "  Invoice  "}}])[0]["trigger"]
    assert t == {"enabled": True, "folder": "INBOX", "subject": "Invoice", "senders": [], "prompt": ""}
    assert agents.clean({})["mail"] == []                      # nothing by default


def test_only_the_providers_top_header_proves_the_sender():
    trusted = access.trusted_servers({"imap_host": "imap.example.net", "smtp_host": "smtp.example.net"})
    ok = _msg("billing@stripe.com", ar=[AR_OK])
    assert access.verified(access.top_result(ok), "billing@stripe.com", trusted)
    assert access.verified(access.top_result(ok), "billing@news.stripe.com", trusted)          # aligned subdomain
    assert not access.verified(access.top_result(ok), "boss@acme.io", trusted)                 # another domain
    # a header written by the sender below the provider's: the top one (a fail) is what counts
    forged = _msg("billing@stripe.com", ar=["mx.example.net; dkim=fail header.d=stripe.com; spf=softfail", AR_OK])
    assert not access.verified(access.top_result(forged), "billing@stripe.com", trusted)
    # no header of the provider: one claiming another server is not trusted
    other = _msg("billing@stripe.com", ar=["mx.attacker.test; dkim=pass header.d=stripe.com"])
    assert not access.verified(access.top_result(other), "billing@stripe.com", trusted)
    assert not access.verified("", "billing@stripe.com", trusted)
    dmarc = "mx.google.com; dmarc=pass (p=REJECT) header.from=stripe.com; dkim=pass header.i=@other.example"
    assert access.verified(dmarc, "a@stripe.com", access.trusted_servers({"imap_host": "imap.gmail.com"}))
    assert access.sender_ok({"senders": ["*@stripe.com"]}, "a@stripe.com", True)
    assert not access.sender_ok({"senders": ["*@stripe.com"]}, "a@stripe.com", False)
    assert access.sender_ok({"senders": []}, "anyone@x.org", False)
    assert access.recipients_ok({"senders": ["*@stripe.com", "bob@x.org"]}, ["a@stripe.com", "bob@x.org", "c@x.org"]) == ["c@x.org"]


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def smtp():
    s = FakeSMTP("me@example.com", PW).start()
    yield s
    s.stop()


@pytest.fixture
def box(client, topic, smtp, monkeypatch):
    """A mailbox with a faked IMAP side holding INBOX messages {uid: row}, and the agent `writer` of acme/blog."""
    _mail_on()
    monkeypatch.setattr(mail, "open_imap", lambda *a, **k: type("M", (), {"logout": lambda self: None})())
    a, _ = mail.add_account({"address": "me@example.com", "imap_host": "imap.example.net", "imap_port": 993,
                             "imap_tls": "ssl", "smtp_host": "127.0.0.1", "smtp_port": smtp.port, "smtp_tls": "none"}, PW)
    rows = {
        1: {"uid": 1, "from": {"name": "Stripe", "email": "billing@stripe.com"}, "to": [], "subject": "Invoice 12",
            "date": time.time(), "seen": False, "flagged": False, "answered": False, "size": 10, "attachments": True,
            "message_id": "<m1@stripe.com>", "from_verified": True},
        2: {"uid": 2, "from": {"name": "", "email": "billing@stripe.com"}, "to": [], "subject": "Forged",
            "date": time.time(), "seen": False, "flagged": False, "answered": False, "size": 10, "attachments": False,
            "message_id": "<m2@evil>", "from_verified": False},
        3: {"uid": 3, "from": {"name": "Bob", "email": "bob@x.org"}, "to": [], "subject": "Hi",
            "date": time.time(), "seen": False, "flagged": False, "answered": False, "size": 10, "attachments": False,
            "message_id": "<m3@x.org>", "from_verified": True},
    }
    state = {"rows": rows, "marked": [], "acts": [], "drafts": []}
    monkeypatch.setattr(imap, "summaries", lambda acc, folder, uids: [dict(rows[u]) for u in uids if u in rows])

    def message(acc, folder, uid, mark_seen=True):
        if uid not in rows:
            raise imap.MailError("not_found", "gone")
        state["marked"].append(mark_seen)
        r = rows[uid]
        return {**r, "folder": folder, "cc": [], "reply_to": [], "bcc": [], "in_reply_to": "", "references": "",
                "text": f"text of {uid}", "html": None, "attachments": [], "remote_images": False}
    monkeypatch.setattr(imap, "message", message)

    def messages(acc, folder="INBOX", page=0, size=50, q=None, unread=False, flagged=False, senders=None):
        got = [dict(r) for r in rows.values() if access.sender_ok({"senders": senders or []}, r["from"]["email"], r["from_verified"])]
        return {"folder": folder, "total": len(got), "exists": len(rows), "page": 0, "size": size, "messages": got}
    monkeypatch.setattr(imap, "messages", messages)
    monkeypatch.setattr(imap, "act", lambda acc, folder, uids, action, target=None: state["acts"].append((uids, action, target)) or {"ok": True, "moved_to": target})
    monkeypatch.setattr(imap, "append", lambda *a, **k: "Sent")

    def append_draft(acc, raw):
        state["drafts"].append(raw)
        return "Drafts", 100 + len(state["drafts"])
    monkeypatch.setattr(imap, "append_draft", append_draft)
    monkeypatch.setattr(imap, "drop", lambda acc, folder, uid: state["acts"].append(([uid], "drop", folder)))
    _agents_on(client)
    _create(client)
    state["acc"] = a
    return state


def _grant(client, **g):
    r = client.patch("/api/agents/acme/blog/writer", json={"mail": [{"account": "me-example", **g}]})
    assert r.status_code == 200, r.text
    return r.json()["mail"][0]


def _as_agent(monkeypatch, path=A):
    from maxxing import agent_guard
    monkeypatch.setattr(agent_guard, "agent_turn", lambda: {"path": path, "depth": 0, "tampered": False})


def _cli(capsys, *argv, stdin: str | None = None, monkeypatch=None) -> tuple[int, str, str]:
    import io
    import sys
    from maxxing import cli
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = cli.main(["mail", *argv])
    o = capsys.readouterr()
    return code, o.out, o.err


# ---------------------------------------------------------------- the agent's setting and maxxing mail

def test_the_mail_setting_names_mailboxes_of_the_page(client, box):
    r = client.patch("/api/agents/acme/blog/writer", json={"mail": [{"account": "nope"}]})
    assert r.status_code == 400 and "bad_mail" in r.text
    r = client.patch("/api/agents/acme/blog/writer", json={"mail": [{"account": "me-example", "rights": ["fly"]}]})
    assert r.status_code == 400
    g = _grant(client, rights=["read", "send"], approve_send="new")
    assert g["rights"] == ["read", "send"] and g["approve_send"] == "new"
    accs = client.get("/api/mail/accounts").json()
    assert accs[0]["agents"][0]["agent"] == A and accs[0]["poll_min"] == 10


def test_an_agent_without_the_mailbox_sees_nothing(client, box, monkeypatch, capsys):
    _as_agent(monkeypatch)
    code, out, err = _cli(capsys, "list")
    assert code == 1 and "no mailbox" in err
    code, out, err = _cli(capsys, "add", "x@example.com", stdin="pw", monkeypatch=monkeypatch)
    assert code == 1 and "never adds a mailbox" in err


def test_rights_and_senders_limit_the_cli(client, box, monkeypatch, capsys):
    _grant(client, rights=["read"], senders=["*@stripe.com"])
    _as_agent(monkeypatch)
    code, out, _ = _cli(capsys, "list")
    assert code == 0 and "Invoice 12" in out and "Forged" not in out and "Hi" not in out   # unchecked sender hidden
    code, out, _ = _cli(capsys, "read", "1")
    assert code == 0 and "text of 1" in out and box["marked"] == [False]                  # never marked read
    assert _cli(capsys, "read", "2")[0] == 1                                              # forged: not found
    assert _cli(capsys, "read", "3")[0] == 1                                              # not on the list
    code, _, err = _cli(capsys, "archive", "1")
    assert code == 1 and "may not file" in err and not box["acts"]
    code, _, err = _cli(capsys, "write", "--to", "bob@x.org", "-s", "x", stdin="hi", monkeypatch=monkeypatch)
    assert code == 1 and "may not write drafts" in err
    seen = store.seen_by("me-example", ["<m1@stripe.com>"])["<m1@stripe.com>"]
    assert seen[0]["agent"] == A and seen[0]["what"] == "read"


def test_moves_marks_and_files(client, box, monkeypatch, capsys, mx):
    _grant(client, rights=["read", "move", "mark", "draft"])
    _as_agent(monkeypatch)
    assert _cli(capsys, "move", "1", "--to", "Invoices")[0] == 0
    assert _cli(capsys, "seen", "3")[0] == 0
    assert box["acts"] == [([1], "move", "Invoices"), ([3], "seen", None)]
    got = store.seen_by("me-example", ["<m1@stripe.com>", "<m3@x.org>"])
    assert got["<m1@stripe.com>"][0]["what"] == "filed" and got["<m1@stripe.com>"][0]["detail"] == "Invoices"
    assert got["<m3@x.org>"][0]["what"] == "marked read"
    # attachments are saved in the agent's own folder only; files attached come from its topic
    code, _, err = _cli(capsys, "attachment", "1", "0", "/tmp/x.pdf")
    assert code == 1 and "own folder" in err
    secret = mx["tmp"] / "secret.txt"
    secret.write_text("s")
    code, _, err = _cli(capsys, "write", "--to", "bob@x.org", "--attach", str(secret), stdin="hi", monkeypatch=monkeypatch)
    assert code == 1 and "files of its topic" in err
    ok = mx["ws"] / "projects/acme/topics/blog/notes.txt"
    ok.write_text("n")
    code, out, _ = _cli(capsys, "write", "--to", "bob@x.org", "--attach", str(ok), "-s", "S", stdin="hi", monkeypatch=monkeypatch)
    assert code == 0 and "draft saved" in out and len(box["drafts"]) == 1


def test_sending_waits_for_the_owner_then_goes(client, box, monkeypatch, capsys, smtp):
    _grant(client, rights=["read", "send"], approve_send="always")
    _as_agent(monkeypatch)
    code, out, _ = _cli(capsys, "write", "--reply", "3", stdin="Thanks!", monkeypatch=monkeypatch)
    assert code == 1                                                    # no draft right: --send only
    code, out, _ = _cli(capsys, "write", "--reply", "3", "--send", stdin="Thanks!", monkeypatch=monkeypatch)
    assert code == 0 and "waits for the owner's OK" in out and not smtp.messages
    [w] = outbox.pending()
    assert w["agent"] == A and w["to"] == ["Bob <bob@x.org>"] and w["draft"] == {"folder": "Drafts", "uid": 101}
    ev = feed.find(f"mailsend:{w['id']}")
    assert ev and {a["id"] for a in ev["actions"]} == {"allow", "deny", "open"} and ev["level"] == "warning"
    assert ev["url"] == "/mail?account=me-example&folder=Drafts&draft=101"
    r = client.post(f"/api/feed/{ev['id']}/act/allow")
    assert r.status_code == 200, r.text
    assert len(smtp.messages) == 1 and smtp.messages[0]["to"] == ["bob@x.org"]
    assert ([101], "drop", "Drafts") in box["acts"] and not outbox.pending()
    assert feed.get(ev["id"])["resolution"] == "Sent"
    client.post(f"/api/feed/{ev['id']}/act/allow")                      # a second click sends nothing
    assert len(smtp.messages) == 1
    assert store.seen_by("me-example", ["<m3@x.org>"])["<m3@x.org>"][-1]["what"] == "replied"


def test_approve_new_sends_alone_to_people_the_owner_wrote_to(client, box, monkeypatch, capsys, smtp):
    _grant(client, rights=["read", "send"], approve_send="new")
    store.remember("me-example", "INBOX", [box["rows"][3]])            # bob wrote: anyone can write first
    _as_agent(monkeypatch)
    code, out, _ = _cli(capsys, "write", "--reply", "3", "--send", stdin="ok", monkeypatch=monkeypatch)
    assert code == 0 and "new recipient: bob@x.org" in out and not smtp.messages
    [w] = outbox.pending()
    assert client.post(f"/api/mail/outbox/{w['id']}/send").json()["status"] == "sent"     # the owner allows it...
    assert len(smtp.messages) == 1 and store.unknown("me-example", ["bob@x.org"]) == []   # ...bob is known now
    assert _cli(capsys, "write", "--to", "bob@x.org", "-s", "Again", "--send", stdin="x", monkeypatch=monkeypatch)[0] == 0
    assert len(smtp.messages) == 2                                      # alone this time
    code, out, _ = _cli(capsys, "write", "--to", "new@y.org", "-s", "Hello", "--send", stdin="x", monkeypatch=monkeypatch)
    assert code == 0 and "new recipient: new@y.org" in out and len(smtp.messages) == 2
    [w] = outbox.pending()
    assert client.post(f"/api/mail/outbox/{w['id']}/deny").json()["status"] == "refused"
    assert store.unknown("me-example", ["new@y.org"]) == ["new@y.org"]


def test_an_agent_sending_alone_makes_no_contact(client, box, monkeypatch, capsys, smtp):
    _grant(client, rights=["read", "send"], approve_send="never")
    _as_agent(monkeypatch)
    assert _cli(capsys, "write", "--to", "eve@z.org", "-s", "S", "--send", stdin="x", monkeypatch=monkeypatch)[0] == 0
    assert len(smtp.messages) == 1 and store.unknown("me-example", ["eve@z.org"]) == ["eve@z.org"]


def test_senders_also_limit_the_recipients(client, box, monkeypatch, capsys, smtp):
    _grant(client, rights=["read", "draft", "send"], approve_send="never", senders=["bob@x.org"])
    _as_agent(monkeypatch)
    code, _, err = _cli(capsys, "write", "--to", "eve@z.org", "--send", stdin="x", monkeypatch=monkeypatch)
    assert code == 1 and "only writes to bob@x.org" in err
    assert _cli(capsys, "write", "--to", "bob@x.org", "-s", "S", "--send", stdin="x", monkeypatch=monkeypatch)[0] == 0
    assert len(smtp.messages) == 1


def test_the_owner_sending_the_draft_from_the_page_ends_the_request(client, box, monkeypatch, capsys, smtp):
    _grant(client, rights=["read", "send"])
    _as_agent(monkeypatch)
    _cli(capsys, "write", "--to", "bob@x.org", "-s", "S", "--send", stdin="x", monkeypatch=monkeypatch)
    [w] = outbox.pending()
    import json
    r = client.post("/api/mail/me-example/send", data={"data": json.dumps(
        {"to": ["bob@x.org"], "subject": "S (changed)", "text": "y", "draft": w["draft"]})})
    assert r.status_code == 200, r.text
    assert not outbox.pending() and feed.find(f"mailsend:{w['id']}", open_only=False)["resolution"] == "Sent from the E-mail page"


# ---------------------------------------------------------------- the check and the trigger

def test_the_check_starts_one_turn_per_check_for_matching_mail(client, box, monkeypatch):
    _grant(client, rights=["read", "draft"], senders=["*@stripe.com"],
           trigger={"enabled": True, "folder": "INBOX", "prompt": "File the invoices."})
    rows = box["rows"]
    fired: list[dict] = []
    monkeypatch.setattr(agents, "fire", lambda path, **kw: fired.append({"path": path, **kw}) or {"started": True})
    pending = {"uids": [1, 2, 3]}

    def new_since(acc, folder, last_uid, limit=50):
        uids = [u for u in pending["uids"] if last_uid is None or u > last_uid]
        return {"uidvalidity": 7, "uids": uids, "messages": [dict(rows[u]) for u in uids if u in rows]}
    monkeypatch.setattr(imap, "new_since", new_since)
    acc = box["acc"]
    r = poll.poll_account(acc)
    assert r["ok"] and r["started"] == 0 and not fired                  # first check: where the mailbox is
    assert store.position("me-example", "INBOX")["last_uid"] == 3
    rows[4] = {**rows[1], "uid": 4, "subject": "Invoice 13", "message_id": "<m4@stripe.com>"}
    rows[5] = {**rows[1], "uid": 5, "subject": "Invoice 14", "message_id": "<m5@stripe.com>"}
    rows[6] = {**rows[2], "uid": 6, "message_id": "<m6@evil>"}           # forged sender: not for this agent
    rows[7] = {**rows[1], "uid": 7, "from": {"name": "", "email": "me@example.com"}, "message_id": "<m7@me>"}
    pending["uids"] = [1, 2, 3, 4, 5, 6, 7]
    r = poll.poll_account(acc)
    assert r["new"] == 4 and r["started"] == 1 and len(fired) == 1
    f = fired[0]
    assert f["path"] == A and f["trigger"] == "mail:me-example" and f["prompt"] == "File the invoices."
    assert "UID: 4" in f["text"] and "UID: 5" in f["text"] and "UID: 6" not in f["text"] and "UID: 7" not in f["text"]
    assert "text of 4" in f["text"] and f["wait"] is True
    assert store.seen_by("me-example", ["<m4@stripe.com>"])["<m4@stripe.com>"][0]["what"] == "seen"
    assert poll.poll_account(acc)["started"] == 0                       # nothing new
    allm = client.get("/api/mail/all").json()
    assert {m["uid"] for m in allm["messages"]} >= {4, 5, 6} and allm["checks"]["me-example"]["ok"]
    assert next(m for m in allm["messages"] if m["uid"] == 4)["seen_by"][0]["name"] == "Writer"


def test_a_busy_agent_gets_the_mail_later(client, box, monkeypatch):
    _grant(client, rights=["read"], trigger={"enabled": True})
    answers = [{"started": False, "reason": "busy"}, {"started": False, "reason": "busy"}, {"started": True}]
    fired = []
    monkeypatch.setattr(agents, "fire", lambda path, **kw: fired.append(kw) or answers.pop(0))
    rows = box["rows"]
    acc = box["acc"]
    assert poll._fire(A, acc, "INBOX", [rows[1]], {1: "body one"}, "p") is False
    assert poll._fire(A, acc, "INBOX", [rows[3]], {3: "body three"}, "p") is False
    assert poll.retry_pending() == 1
    text = fired[-1]["text"]                                             # both mails, rebuilt with ONE fresh marker
    assert "body one" in text and "body three" in text and "UID: 1" in text and "UID: 3" in text
    marks = {w for w in text.split() if w.startswith("MAIL-")}
    assert len(marks) == 1 and marks.isdisjoint(fired[0]["text"].split())
    assert poll.retry_pending() == 0


def test_check_interval_and_refresh(client, box, monkeypatch):
    assert client.patch("/api/mail/accounts/me-example", json={}).status_code == 200
    from maxxing.mail import _clean
    with pytest.raises(imap.MailError):
        _clean({"poll_min": 7}, partial=True)
    mail.update_account("me-example", {"poll_min": 30})
    acc = mail.get_account("me-example")
    assert poll.interval_min(acc) == 30 and poll.due(acc)
    monkeypatch.setattr(imap, "new_since", lambda *a, **k: {"uidvalidity": 1, "uids": [], "messages": []})
    r = client.post("/api/mail/refresh", json={}).json()
    assert r[0]["ok"] and not poll.due(mail.get_account("me-example"))
    assert client.get("/api/mail/accounts").json()[0]["last_check"]["ok"] is True


def test_messages_show_what_the_agents_did(client, box, monkeypatch):
    store.note("me-example", "<m1@stripe.com>", A, "draft", "draft ready")
    res = client.get("/api/mail/me-example/messages").json()
    m1 = next(m for m in res["messages"] if m["uid"] == 1)
    assert m1["seen_by"][0]["what"] == "draft" and m1["seen_by"][0]["name"] == "Writer" and m1["seen_by"][0]["avatar"]
    assert next(m for m in res["messages"] if m["uid"] == 3)["seen_by"] == []


def test_mail_templates_need_a_mailbox(client, box, capsys):
    from maxxing import cli
    assert cli.main(["agents", "create", "acme/blog/sorter", "--template", "mail-sort"]) == 2
    assert "--mail MAILBOX" in capsys.readouterr().err
    assert cli.main(["agents", "create", "acme/blog/sorter", "--template", "mail-sort", "--mail", "me@example.com"]) == 0
    a = agents.load("projects/acme/topics/blog/agents/sorter")
    assert a["mail"][0]["account"] == "me-example" and a["mail"][0]["rights"] == ["read", "move"]
    assert a["mail"][0]["trigger"]["enabled"] and "Bash(maxxing mail:*)" in a["allowed_tools"]
    assert [w[0] for w in poll.watchers("me-example")] == ["projects/acme/topics/blog/agents/sorter"]


def test_a_sandboxed_agent_may_run_maxxing_mail(monkeypatch):
    from maxxing import agent_guard
    monkeypatch.setattr(agent_guard, "sandboxed_turn", lambda: A)
    monkeypatch.setattr(agent_guard, "agent_turn", lambda: {"path": A, "depth": 0, "tampered": False})
    assert agent_guard.check_cli(["mail", "list"]) is None
    assert agent_guard.check_cli(["mail", "write", "--send"]) is None
    assert agent_guard.check_cli(["mail", "add", "x@y.z"]) is not None


# ---------------------------------------------------------------- against a real IMAP server

@pytest.mark.skipif(not os.environ.get("MAXXING_TEST_IMAP"), reason="MAXXING_TEST_IMAP not set")
def test_real_imap_check_and_senders(mx, monkeypatch):
    host, port, user, pw = os.environ["MAXXING_TEST_IMAP"].split(":", 3)
    _mail_on()
    a, _ = mail.add_account({"address": user, "imap_host": host, "imap_port": int(port), "imap_tls": "none",
                             "smtp_host": host, "smtp_port": 2525, "smtp_tls": "none"}, pw, skip_test=True)
    mail.update_account(a["id"], {"auth_servers": ["mx.example.net"]})
    a = mail.get_account(a["id"])
    poll.poll_account(a, fire=False)                                    # where the mailbox is now
    tag = f"T{int(time.time() * 1000)}"
    with imap.session(a) as m:
        for sender, ar in (("billing@stripe.com", [AR_OK]), ("billing@stripe.com", []),
                           ("bob@x.org", ["mx.example.net; dkim=pass header.d=x.org"])):
            m.append('"INBOX"', "()", None, _msg(sender, f"{tag} {sender} {len(ar)}", ar).as_bytes())
    got = imap.messages(a, "INBOX", q=tag)["messages"]
    assert sorted((x["from"]["email"], x["from_verified"]) for x in got) == [
        ("billing@stripe.com", False), ("billing@stripe.com", True), ("bob@x.org", True)]
    only = imap.messages(a, "INBOX", q=tag, senders=["*@stripe.com"])["messages"]
    assert [(x["from"]["email"], x["from_verified"]) for x in only] == [("billing@stripe.com", True)]
    res = poll.poll_account(a, fire=False)
    assert res["ok"] and res["new"] >= 3
    assert {r["subject"] for r in store.recent([a["id"]], 10)} >= {x["subject"] for x in got}
    with imap.session(a) as m:                                           # clean up
        m.select('"INBOX"')
        typ, data = m.uid("SEARCH", f'SUBJECT "{tag}"')
        for u in data[0].split():
            m.uid("STORE", u, "+FLAGS.SILENT", "(\\Deleted)")
        m.expunge()
