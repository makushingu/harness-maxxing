"""Downloads: the Content-Disposition of every download (files, team files, PC agent) and folders as a zip."""
from __future__ import annotations

import io
import os
import re
import zipfile
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


@pytest.fixture
def tree(mx):
    root = mx["files"]
    d = root / "proj"
    (d / "sub" / "deep").mkdir(parents=True)
    (d / "empty").mkdir()
    (d / "a.txt").write_text("hello " * 1000)
    (d / "sub" / "pic.png").write_bytes(os.urandom(5000))
    (d / "sub" / "deep" / "x.md").write_text("# x\n")
    return root


def _get_zip(client, path):
    r = client.get("/api/files/zip", params={"path": str(path)})
    return r, (zipfile.ZipFile(io.BytesIO(r.content)) if r.status_code == 200 else None)


def test_zip_of_a_folder(client, tree):
    r, z = _get_zip(client, tree / "proj")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert _names(r.headers["content-disposition"]) == ("proj.zip", "proj.zip")
    assert r.headers["cache-control"] == "no-store"
    assert z.testzip() is None
    assert sorted(z.namelist()) == ["proj/", "proj/a.txt", "proj/empty/", "proj/sub/", "proj/sub/deep/",
                                    "proj/sub/deep/x.md", "proj/sub/pic.png"]
    assert z.read("proj/a.txt") == (tree / "proj" / "a.txt").read_bytes()
    assert z.getinfo("proj/a.txt").compress_type == zipfile.ZIP_DEFLATED
    assert z.getinfo("proj/sub/pic.png").compress_type == zipfile.ZIP_STORED
    assert z.read("proj/sub/pic.png") == (tree / "proj" / "sub" / "pic.png").read_bytes()
    assert client.get("/api/files/zip", params={"path": str(tree / "proj"), "check": 1}).json() == {"count": 3, "size": 11004}


def test_zip_refuses_files_and_paths_outside(client, tree, mx):
    assert client.get("/api/files/zip", params={"path": str(tree / "proj" / "a.txt")}).status_code == 404
    assert client.get("/api/files/zip", params={"path": str(mx["tmp"])}).status_code == 403
    assert client.get("/api/files/zip", params={"path": "/etc"}).status_code == 403


def test_zip_never_follows_a_link_out_of_the_root(client, tree, mx):
    secret = mx["tmp"] / "outside"
    secret.mkdir()
    (secret / "key.txt").write_text("secret")
    proj = tree / "proj"
    os.symlink(secret, proj / "linkdir")
    os.symlink(secret / "key.txt", proj / "linkfile.txt")
    os.symlink(proj / "a.txt", proj / "inside.txt")                # a link inside the root is fine
    os.mkfifo(proj / "pipe")                                       # never read (it would hang)
    os.symlink("/proc/self/root/etc", proj / "proc")
    r, z = _get_zip(client, proj)
    names = z.namelist()
    assert "proj/inside.txt" in names and z.read("proj/inside.txt") == (proj / "a.txt").read_bytes()
    assert not [n for n in names if "link" in n or "pipe" in n or "proc" in n]
    assert b"secret" not in r.content
    # the folder itself through a link out of the root
    os.symlink(secret, tree / "out")
    assert client.get("/api/files/zip", params={"path": str(tree / "out")}).status_code == 403


def test_zip_caps(client, tree, monkeypatch):
    monkeypatch.setattr(downloads, "ZIP_MAX_BYTES", 3000)
    r = client.get("/api/files/zip", params={"path": str(tree / "proj"), "check": 1})
    assert r.status_code == 413 and r.json()["error"] == "too_large"
    assert client.get("/api/files/zip", params={"path": str(tree / "proj")}).status_code == 413
    monkeypatch.setattr(downloads, "ZIP_MAX_BYTES", 1 << 30)
    monkeypatch.setattr(downloads, "ZIP_MAX_FILES", 3)
    assert client.get("/api/files/zip", params={"path": str(tree / "proj")}).status_code == 413


def test_zip_names_that_are_not_utf8(client, tree):
    d = tree / "proj"
    os.close(os.open(os.fsencode(d) + b"/caf\xe9.txt", os.O_CREAT | os.O_WRONLY))
    r, z = _get_zip(client, d)
    assert "proj/café.txt" in z.namelist()


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


def test_zip_skips_a_file_swapped_for_a_link_after_the_plan(tree, mx):
    proj, secret = tree / "proj", mx["tmp"] / "secret.txt"
    secret.write_text("secret")
    plan = downloads.zip_plan(proj, tree)
    (proj / "a.txt").unlink()
    os.symlink(secret, proj / "a.txt")
    (proj / "sub" / "deep" / "x.md").unlink()
    os.mkfifo(proj / "sub" / "deep" / "x.md")                      # a FIFO would block a plain open()
    z = zipfile.ZipFile(io.BytesIO(b"".join(downloads.zip_stream(plan))))
    assert "proj/a.txt" not in z.namelist() and "proj/sub/deep/x.md" not in z.namelist()
    assert "proj/sub/pic.png" in z.namelist()
