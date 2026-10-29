"""Downloads: the Content-Disposition of every download (files, team files, PC agent)."""
from __future__ import annotations

import os
import re
from urllib.parse import unquote

import pytest

from maxxing import config, downloads, teampeer


def _names(header: str) -> tuple[str, str]:
    """(plain filename, decoded filename*) of a Content-Disposition, checked for shape on the way."""
    header.encode("latin-1")                                       # a valid header value
    m = re.fullmatch(r"attachment; filename=\"([^\"\\\x00-\x1f]*)\"; filename\*=UTF-8''([A-Za-z0-9%!#$&+\-.^_`|~]+)", header)
    assert m, header
    assert m.group(1).isascii()
    return m.group(1), unquote(m.group(2), encoding="utf-8", errors="strict")


@pytest.mark.parametrize("name,plain,real", [
    ("report.pdf", "report.pdf", "report.pdf"),
    ("café déjà.txt", "cafe deja.txt", "café déjà.txt"),
    ("my file (1).png", "my file (1).png", "my file (1).png"),
    ('say "hi"\\now.txt', "say _hi__now.txt", 'say "hi"_now.txt'),
    ("line\nbreak\r.txt", "line_break_.txt", "line_break_.txt"),
    ("a/b.txt", "a_b.txt", "a_b.txt"),
    ("100%.txt", "100_.txt", "100%.txt"),
    ("evil\u202egnp.exe", "evilgnp.exe", "evilgnp.exe"),        # bidi override dropped
    ("報告.pdf", "download.pdf", "報告.pdf"),
    ("caf\udce9.txt", "cafe.txt", "café.txt"),                   # Latin-1 byte on disk (lone surrogate)
    ("\ud800x.txt", "?x.txt", "?x.txt"),                         # a surrogate that is no byte (JSON from a peer)
    ("", "download", "download"),
    ("...", "download", "download"),
])
def test_content_disposition(name, plain, real):
    assert _names(downloads.content_disposition(name)) == (plain, real)


def test_a_very_long_name_is_cut_and_keeps_its_extension():
    plain, real = _names(downloads.content_disposition("é" * 400 + ".tar.gz"))
    assert len(real) == downloads.NAME_MAX and real.endswith("é.gz") and plain.endswith("e.gz")


def test_raw_download_names(client, mx):
    root = mx["files"]
    for name, plain in (("café.txt", "cafe.txt"), ("a b 'c'.txt", "a b 'c'.txt"), ('q"uote.txt', "q_uote.txt")):
        (root / name).write_text("x")
        r = client.get("/api/files/raw", params={"path": str(root / name), "download": 1})
        assert r.status_code == 200 and _names(r.headers["content-disposition"]) == (plain, name)
    raw = os.fsencode(root) + b"/caf\xe9.txt"
    with open(raw, "wb") as f:
        f.write(b"latin")
    shown = str(root / "caf\ufffd.txt")                            # what the listing shows (and the UI sends back)
    r = client.get("/api/files/raw", params={"path": shown, "download": 1})
    assert r.status_code == 200 and r.content == b"latin"
    assert _names(r.headers["content-disposition"]) == ("cafe.txt", "café.txt")
    # inline: no Content-Disposition at all
    assert "content-disposition" not in client.get("/api/files/raw", params={"path": shown}).headers


def test_team_file_name_from_a_peer_is_sanitized(client, mx, monkeypatch):
    config.update_config(team_page=True)
    f = mx["files"] / "x.bin"
    f.write_bytes(b"data")
    monkeypatch.setattr(teampeer, "verify", lambda *a: ("http://127.0.0.1:8802", ""))
    monkeypatch.setattr(teampeer, "file_for", lambda *a: {"path": str(f), "name": "../evil\r\nSet-Cookie: x=1\".sh"})
    r = client.get("/api/team-peer/files/f_1")
    assert r.status_code == 200 and r.content == b"data" and "set-cookie" not in r.headers
    plain, real = _names(r.headers["content-disposition"])
    assert "/" not in real and "\n" not in real and plain == "_evil__Set-Cookie: x=1_.sh"
