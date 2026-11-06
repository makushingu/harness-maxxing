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
