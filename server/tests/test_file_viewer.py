from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import zipfile

import pytest

from maxxing.api import filesite

from test_files import tree  # noqa: F401  (fixture)

ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def test_archive_listing(client, tree):  # noqa: F811
    z = tree / "a.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("docs/", "")
        f.writestr("docs/readme.md", "# hi")
        f.writestr("data.csv", "a,b\n1,2\n")
    r = client.get("/api/files/archive", params={"path": str(z)}).json()
    assert r["format"] == "zip" and r["count"] == 3 and r["total_size"] == 12 and not r["truncated"]
    assert {e["name"] for e in r["entries"]} == {"docs/", "docs/readme.md", "data.csv"}
    assert [e["dir"] for e in r["entries"]] == [True, False, False]
    t = tree / "b.tar.gz"
    with tarfile.open(t, "w:gz") as f:
        data = b"hello"
        info = tarfile.TarInfo("x/hello.txt")
        info.size = len(data)
        f.addfile(info, io.BytesIO(data))
    r = client.get("/api/files/archive", params={"path": str(t)}).json()
    assert r["format"] == "tar" and r["entries"][0]["name"] == "x/hello.txt" and r["entries"][0]["size"] == 5
    assert client.get("/api/files/archive", params={"path": str(tree / "b.txt")}).status_code == 415



def test_archive_bombs_are_listed_within_bounds(client, tree, monkeypatch):  # noqa: F811
    from maxxing.api import files
    # a tar.gz whose first member is big (here 24 MB of zeros, ~24 kB packed): listing reads through it, so the
    # decompressed bytes are capped and the listing is cut short, never decompressed to the end
    monkeypatch.setattr(files, "ARCHIVE_READ_MAX", 1 << 20, raising=False)
    t = tree / "bomb.tar.gz"
    with tarfile.open(t, "w:gz", compresslevel=1) as f:
        for name, size in (("zeros.bin", 24 << 20), ("after.txt", 1)):
            info = tarfile.TarInfo(name)
            info.size = size
            f.addfile(info, io.BytesIO(b"\0" * size))
    r = client.get("/api/files/archive", params={"path": str(t)}).json()
    assert r["format"] == "tar" and r["truncated"] and [e["name"] for e in r["entries"]] == ["zeros.bin"]
    # a zip's central directory is read entry by entry (never all of it loaded by zipfile.ZipFile); 70 000 entries
    # make a zip64 end record; data prepended to the archive (self-extracting) is allowed
    z = tree / "many.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("dossier/é.txt", "abc")
        for i in range(70000):
            f.writestr(f"f{i}", "")
    z2 = tree / "sfx.zip"
    with zipfile.ZipFile(z2, "w") as f:
        f.writestr("x/", "")
        f.writestr("x/y.txt", "12345")
    z2.write_bytes(b"#!/bin/sh\nexit 0\n" + z2.read_bytes())

    def no_zipfile(*a, **k):
        raise AssertionError("zipfile.ZipFile loads the whole central directory")
    monkeypatch.setattr(zipfile, "ZipFile", no_zipfile)
    r = client.get("/api/files/archive", params={"path": str(z)}).json()
    assert r["count"] == 70001 and r["truncated"] and len(r["entries"]) == files.ARCHIVE_MAX
    assert r["entries"][0] == {**r["entries"][0], "name": "dossier/é.txt", "size": 3, "dir": False}
    r = client.get("/api/files/archive", params={"path": str(z2)}).json()
    assert [(e["name"], e["size"], e["dir"]) for e in r["entries"]] == [("x/", 0, True), ("x/y.txt", 5, False)]

def test_html_site_token(client, tree):  # noqa: F811
    site = tree / "report"
    site.mkdir()
    (site / "index.html").write_text("<img src='img/logo.png'>")
    (site / "img").mkdir()
    (site / "img" / "logo.png").write_bytes(b"\x89PNG")
    url = client.get("/api/files/site-url", params={"path": str(site / "index.html")}).json()["url"]
    client.cookies.clear()                     # the page itself has no session
    r = client.get(url)
    assert r.status_code == 200 and "logo.png" in r.text
    csp = r.headers["content-security-policy"]
    assert csp.startswith("sandbox allow-scripts") and "allow-same-origin" not in csp
    assert "allow-popups-to-escape-sandbox" not in csp      # links opened from the page stay sandboxed
    base = url.rsplit("/", 1)[0]
    assert client.get(base + "/img/logo.png").content == b"\x89PNG"
    assert client.get(base + "/..%2Fb.txt").status_code in (403, 404)
    assert client.get(base + "/../b.txt").status_code in (403, 404)
    assert client.get("/api/files/site/forged.abc/index.html").status_code == 403
    expired = filesite.make_token(site, ttl=-1)
    assert client.get(f"/api/files/site/{expired}/index.html").status_code == 403


def _tiny_pdf() -> bytes:
    """A valid one-page PDF with a filled rectangle (offsets computed for the xref table)."""
    stream = b"0 0 1 rg 20 20 160 240 re f"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 280] /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


@ffmpeg
@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm not installed")
def test_pdf_thumbnail(client, tree):  # noqa: F811
    pdf = tree / "doc.pdf"
    pdf.write_bytes(_tiny_pdf())
    r = client.get("/api/files/thumb", params={"path": str(pdf), "w": 160})
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"


@ffmpeg
def test_tiff_always_converted(client, tree):  # noqa: F811
    tif = tree / "small.tiff"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(tif)], check=True)
    r = client.get("/api/files/preview", params={"path": str(tif)})
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp"


def test_archive_cut_by_the_time_cap_is_listed_again(client, mx, monkeypatch):
    """A slow moment during the first listing (time cap hit): the partial list is not cached for good."""
    from maxxing.api import files
    p = mx["files"] / "slow.zip"
    with zipfile.ZipFile(p, "w") as z:
        for i in range(50):
            z.writestr(f"f{i}.txt", "x")
    monkeypatch.setattr(files, "ARCHIVE_TIME_S", -1.0)
    first = client.get("/api/files/archive", params={"path": str(p)}).json()
    assert first["truncated"] is True
    monkeypatch.setattr(files, "ARCHIVE_TIME_S", 3.0)
    again = client.get("/api/files/archive", params={"path": str(p)}).json()
    assert again["count"] == 50 and again["truncated"] is False


def test_a_name_that_is_not_utf8_can_be_opened_renamed_and_deleted(client, mx):
    """Listed with U+FFFD in its path (UTF-8 cannot carry the raw byte): that path still opens the file."""
    import os
    root = mx["files"]
    with open(os.path.join(os.fsencode(str(root)), b"caf\xe9.txt"), "wb") as f:
        f.write(b"hello")
    e = next(e for e in client.get("/api/files/list", params={"path": str(root)}).json()["entries"]
             if e["name"].startswith("caf"))
    assert e["path"] == str(root / "caf�.txt")
    r = client.get("/api/files/read", params={"path": e["path"]})
    assert r.status_code == 200 and "hello" in r.text
    assert client.get("/api/files/read", params={"path": str(root / "nope�.txt")}).status_code == 404
    r = client.post("/api/files/move", json={"from": e["path"], "to": str(root / "cafe.txt")})
    assert r.status_code == 200 and (root / "cafe.txt").read_bytes() == b"hello"
    assert client.post("/api/files/delete", json={"path": str(root / "cafe.txt")}).status_code == 200
