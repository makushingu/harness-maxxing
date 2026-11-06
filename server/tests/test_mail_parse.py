"""Reading what senders write: charsets Python does not know, 8-bit headers, bidi controls, forwarded mails, MIME
nested 1000 levels deep, unclosed <script>, big inline images. None of them may fail a message or the check."""
from __future__ import annotations

import email.message
import email.parser
import email.policy
import json
import time

import pytest

from maxxing.cmd_mail import _html_text
from maxxing.mail import imap


def _render(raw: bytes) -> dict:
    return imap._render(imap._parse(raw), 1, "INBOX", [])


def _text(ctype: str, body: bytes, cte: str = "8bit") -> bytes:
    return (f"From: a@x.fr\r\nSubject: s\r\nMIME-Version: 1.0\r\nContent-Type: {ctype}\r\n"
            f"Content-Transfer-Encoding: {cte}\r\n\r\n").encode() + body


@pytest.mark.parametrize("charset", ["x-bogus", "windows-874", "iso-8859-8-i", "unknown-8bit", '"', "utf-8\x00"])
def test_an_unknown_charset_still_shows_the_text(charset):
    raw = _text(f"text/plain; charset={charset}", "Café crème\r\n".encode())
    m = _render(raw)
    assert m["text"].strip() and "Caf" in m["text"]
    html = _text(f"text/html; charset={charset}", b"<p>Prix \xe9t\xe9</p>")
    assert "Prix" in _render(html)["html"]


def test_the_charset_a_mail_really_uses():
    assert _render(_text("text/plain; charset=iso-8859-1", b"l\x92\xe9t\xe9 \x80 50\r\n"))["text"] == "l’été € 50\n"
    assert _render(_text("text/plain", "l'été\r\n".encode()))["text"] == "l'été\n"      # no charset, UTF-8
    assert _render(_text("text/plain", b"l'\xe9t\xe9\r\n"))["text"] == "l'été\n"                   # no charset, cp1252
    assert _render(_text("text/plain; charset=windows-874", "ก".encode("cp874")))["text"] == "ก"


def test_a_raw_8bit_sender_name_is_read_as_utf8():
    raw = "From: Élodie Martin <e@x.fr>\r\nSubject: Café\r\n\r\nhi\r\n".encode()
    m = _render(raw)
    assert m["from"] == {"name": "Élodie Martin", "email": "e@x.fr"} and m["subject"] == "Café"
    json.dumps(m, ensure_ascii=False).encode()                     # no lone surrogate left (was a 500)
    head = email.parser.BytesHeaderParser(policy=email.policy.default).parsebytes(raw)
    assert imap._addrs(head, "from")[0]["name"] == "Élodie Martin"
    latin = b"From: \xc9lodie <e@x.fr>\r\n\r\nhi\r\n"              # latin-1 bytes: replaced, never an error
    json.dumps(_render(latin), ensure_ascii=False).encode()


def test_bidi_controls_never_disguise_a_name():
    m = email.message.EmailMessage()
    m["From"] = "PayPal \u202emoc.lapyap\u202c <x@evil.example>"
    m["Subject"] = "Facture \u2067urgent\u2069 \u200f"
    m.set_content("x")
    m.add_attachment(b"MZ", maintype="application", subtype="octet-stream", filename="facture\u202efdp.exe")
    r = _render(m.as_bytes())
    for s in (r["from"]["name"], r["subject"], r["attachments"][0]["filename"]):
        assert not any(c in s for c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u200e\u200f\u061c"), s
    assert r["attachments"][0]["filename"] == "facturefdp.exe"


def test_a_mail_forwarded_as_attachment_is_listed_as_eml():
    raw = (b"From: a@x.fr\r\nSubject: TR: devis\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=b\r\n\r\n"
           b"--b\r\nContent-Type: text/plain\r\n\r\nvoir ci-joint\r\n"
           b"--b\r\nContent-Type: message/rfc822\r\n\r\n"
           b"From: c@y.fr\r\nSubject: Devis: mai/juin\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=c\r\n\r\n"
           b"--c\r\nContent-Type: text/plain\r\n\r\nLe prix est 4000 EUR\r\n"
           b"--c\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=inner.pdf\r\n\r\n%PDF\r\n--c--\r\n"
           b"--b\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=after.pdf\r\n\r\n%PDF\r\n--b--\r\n")
    m = _render(raw)
    assert m["text"].strip() == "voir ci-joint"
    [eml, pdf] = m["attachments"]                                  # the inner mail's own parts are in the .eml
    assert eml["filename"] == "Devis_ mai_juin.eml" and eml["content_type"] == "message/rfc822"
    msg = imap._parse(raw)
    assert pdf["filename"] == "after.pdf" and pdf["index"] == [i for i, p in enumerate(msg.walk()) if p.get_filename() == "after.pdf"][0]
    name, ctype, data = imap.part_at(msg, eml["index"])
    assert name == eml["filename"] and ctype == "message/rfc822" and b"4000 EUR" in data
    assert imap.part_at(msg, pdf["index"])[0] == "after.pdf"


def _nested(d: int) -> bytes:
    s = "From: a@b\r\nSubject: n\r\nMIME-Version: 1.0\r\n"
    s += "".join(f"Content-Type: multipart/mixed; boundary=b{i}\r\n\r\n--b{i}\r\n" for i in range(d))
    s += "Content-Type: text/plain\r\n\r\nhi\r\n" + "".join(f"--b{i}--\r\n" for i in reversed(range(d)))
    return s.encode()


@pytest.mark.parametrize("depth", [100, 1100, 3000])
def test_mime_nested_very_deep_never_fails(depth):
    m = _render(_nested(depth))
    assert m["subject"] == "n" and m["attachments"] == []
    imap._body_of(imap._parse(_nested(depth)), "plain")


def test_unclosed_script_and_style_blocks_are_linear():
    blob = "<script>" * 32000 + "<style>" * 32000 + "<head <" * 20000 + "<" * 50000
    t = time.monotonic()
    m = _render(_text("text/html; charset=utf-8", ("<p>hi</p>" + blob).encode()))
    assert "<script" not in m["html"].lower() and "hi" in m["html"]
    assert _html_text("<p>hi</p>" + blob).startswith("hi")
    assert time.monotonic() - t < 5                                # was 52 s for 256 KB of <script>
    assert imap.strip_blocks("a<SCRIPT x>b</script >c<script>d") == "ac"
    assert _html_text("<style>p{}</style><head><title>t</title></head><b>x</b><br>y") == "x\ny"


def test_a_big_mail_inlines_its_images_within_a_budget():
    m = email.message.EmailMessage()
    m["From"], m["Subject"] = "a@b.c", "pics"
    m.set_content("hi")
    m.add_alternative("<p>hi</p>" + "".join(f'<img src="cid:i{i}">' for i in range(6)), subtype="html")
    img = b"\x89PNG" + b"x" * (2 * 1024 * 1024)
    for i in range(6):
        m.get_payload()[1].add_related(img, "image", "png", cid=f"<i{i}>")
    m.add_attachment(b"y" * 1000, maintype="application", subtype="octet-stream", filename="f.bin")
    r = _render(m.as_bytes())
    shown = r["html"].count("data:image/png;base64,")
    assert 0 < shown < 6 and shown * len(img) <= imap.MAX_INLINE_TOTAL
    assert r["html"].count("about:blank") == 6 - shown
    sizes = {a["filename"]: a["size"] for a in r["attachments"]}
    assert sizes["f.bin"] == 1000 and len(sizes) == 1 + 6 - shown  # the images not inlined can be downloaded
    assert all(abs(a["size"] - len(img)) < 4 for a in r["attachments"] if a["content_type"] == "image/png")


def test_a_broken_base64_part_shows_no_text_but_opens():
    m = _render(_text("text/plain; charset=utf-8", b"@@@not base64 ===", cte="base64"))
    assert isinstance(m["text"], str)


def test_a_bad_port_in_mail_add_is_refused():
    import pytest
    from maxxing.cmd_mail import Refused, _hostport
    assert _hostport("imap.example.com:143", 993) == ("imap.example.com", 143)
    assert _hostport("imap.example.com", 993) == ("imap.example.com", 993)
    for bad in ("h:abc", "h:99999", "h:0", "h:-1", "h:１"):
        with pytest.raises(Refused):
            _hostport(bad, 993)


def test_a_name_split_across_encoded_words_is_joined():
    raw = (b"From: =?utf-8?B?SmVhbi1DaHJpc3RvcGhlIER1cG8=?=\r\n =?utf-8?B?bnQ=?= <jc@x.fr>\r\n"
           b"To: =?utf-8?q?Ann?= =?utf-8?q?_Lee?= <a@x.fr>, =?utf-8?q?B?= Smith <b@x.fr>\r\n"
           b"Subject: =?utf-8?B?SmVhbi1DaHJpc3RvcGhlIER1cG8=?=\r\n =?utf-8?B?bnQ=?=\r\n\r\nhi\r\n")
    m = _render(raw)
    assert m["from"] == {"name": "Jean-Christophe Dupont", "email": "jc@x.fr"}      # was "Dupo nt"
    assert m["subject"] == "Jean-Christophe Dupont"
    # the space of "=?q?_Lee?=" is the text's; an encoded-word next to a plain word keeps its space
    assert m["to"] == [{"name": "Ann Lee", "email": "a@x.fr"}, {"name": "B Smith", "email": "b@x.fr"}]
    plain = _render(b"From: Jean Dupont <jc@x.fr>\r\nTo: \"a =?x?= b\" <q@x.fr>\r\n\r\nhi\r\n")
    assert plain["from"]["name"] == "Jean Dupont" and plain["to"][0]["email"] == "q@x.fr"


@pytest.mark.parametrize("raw", [b"To: a@[\r\n", b"From: a@[\r\n", b"Cc: a@[\r\n", b"Reply-To: <a@[>\r\n"])
def test_an_address_header_the_parser_rejects_comes_as_it_is(raw):
    msg = imap._parse(raw + b"Subject: s\r\n\r\nbody\r\n")
    name = raw.split(b":")[0].decode()
    assert imap._hdr(msg, name) == raw.split(b": ", 1)[1].strip().decode()   # any case of the name
    got = imap._addrs(msg, name.lower())
    assert got == [{"name": "", "email": raw.split(b": ", 1)[1].strip().decode()}]
    m = imap._render(msg, 1, "INBOX", [])
    assert m["subject"] == "s" and "body" in m["text"]
    head = email.parser.BytesHeaderParser(policy=email.policy.default).parsebytes(raw + b"\r\n")
    assert imap._addrs(head, name.lower()) == got                              # the list rows' parser too


def test_a_header_with_encoded_words_the_parser_rejects_is_still_decoded():
    msg = imap._parse(b"To: =?utf-8?q?Caf=C3=A9?= a@[\r\n\r\nx\r\n")
    assert imap._hdr(msg, "to") == "Café a@["


def test_a_meeting_invite_is_listed_and_downloadable():
    raw = (b"From: a@x.fr\r\nSubject: Meeting\r\nMIME-Version: 1.0\r\n"
           b"Content-Type: multipart/alternative; boundary=b\r\n\r\n"
           b"--b\r\nContent-Type: text/plain\r\n\r\nMeeting at 10\r\n"
           b"--b\r\nContent-Type: text/html\r\n\r\n<p>Meeting at 10</p>\r\n"
           b"--b\r\nContent-Type: text/calendar; method=REQUEST; charset=utf-8\r\n\r\nBEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"
           b"--b--\r\n")
    m = _render(raw)
    assert "Meeting at 10" in m["text"] and "Meeting at 10" in m["html"]
    assert [(a["filename"], a["content_type"]) for a in m["attachments"]] == [("invite.ics", "text/calendar")]
    name, ctype, data = imap.part_at(imap._parse(raw), m["attachments"][0]["index"])
    assert (name, ctype) == ("invite.ics", "text/calendar") and data.startswith(b"BEGIN:VCALENDAR")


def _many(n: int) -> bytes:
    m = email.message.EmailMessage()
    m["From"], m["Subject"] = "a@x.fr", "many"
    m.set_content("see attached")
    for i in range(n):
        m.add_attachment(b"x", maintype="application", subtype="octet-stream", filename=f"f{i}.bin")
    return m.as_bytes()


def test_attachments_past_the_parts_limit_are_counted_not_hidden():
    m = _render(_many(1200))
    assert len(m["attachments"]) + m["attachments_more"] == 1200 and m["attachments_more"] > 0
    few = _render(_many(3))
    assert len(few["attachments"]) == 3 and few["attachments_more"] == 0
