"""An import only writes plain files inside the workspace, and a file that cannot be placed is skipped, not a 500."""
from __future__ import annotations

import io
import json
import os
import zipfile

from maxxing import config, workspace


def _zip(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _import(client, files: dict[str, str | bytes]):
    up = client.post("/api/import/upload", files={"file": ("x.zip", _zip(files), "application/zip")})
    assert up.status_code == 200, up.text
    return client.post(f"/api/import/{up.json()['id']}/apply")


def test_a_file_where_a_folder_is_expected_is_skipped_not_half_applied(client, mx):
    """`projects/zeta/topics` as a file: the new project already has a `topics` folder there. The import stopped
    with a 500 half-way (project created, no report); now that file is skipped and the rest goes in."""
    r = _import(client, {"projects/zeta/memory.md": "- fact\n", "projects/zeta/topics": "oops\n",
                         "projects/zeta/notes/a.md": "kept\n"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(s["file"].endswith("projects/zeta/topics") for s in body["skipped"]), body["skipped"]
    assert (mx["ws"] / "projects/zeta/topics").is_dir()
    assert (mx["ws"] / "projects/zeta/notes/a.md").read_text() == "kept\n"
    assert "- fact" in (mx["ws"] / "projects/zeta/memory.md").read_text()
    assert (mx["ws"] / body["report"]).is_file()


def test_a_file_in_the_way_of_a_folder_is_skipped(client, mx):
    """The workspace has a file where the export has a folder."""
    assert client.post("/api/workspace/projects", json={"name": "p"}).status_code == 200
    (mx["ws"] / "projects/p/docs").write_text("a file\n")
    r = _import(client, {"projects/p/docs/guide.md": "x\n", "projects/p/other.md": "y\n"})
    assert r.status_code == 200, r.text
    assert any(s["file"].endswith("projects/p/docs/guide.md") for s in r.json()["skipped"])
    assert (mx["ws"] / "projects/p/docs").read_text() == "a file\n"
    assert (mx["ws"] / "projects/p/other.md").read_text() == "y\n"


def test_an_import_cannot_set_folder_settings(client, mx):
    """`.maxxing.json` holds a topic's permission mode: an export could turn on "bypass permissions" for the topic it
    creates (the importer already refused `.claude/settings.json`). `.order.json` (project order) is refused too."""
    config.update_config(permission_mode="default")
    r = _import(client, {"projects/p/topics/t/memory.md": "- x\n",
                         "projects/p/topics/t/.maxxing.json": json.dumps({"permission_mode": "bypass"}),
                         "projects/.order.json": json.dumps({"projects": ["p"]})})
    assert r.status_code == 200, r.text
    assert workspace.topic_permission_mode("projects/p/topics/t") == ""
    reasons = {s["file"]: s["reason"] for s in r.json()["skipped"]}
    assert "projects/p/topics/t/.maxxing.json" in reasons and "projects/.order.json" in reasons


def test_an_import_never_writes_through_a_link_out_of_the_workspace(client, mx):
    """A topic holds a link to a folder outside the workspace (a repository, say): the import followed it."""
    assert client.post("/api/workspace/projects", json={"name": "p"}).status_code == 200
    assert client.post("/api/workspace/projects/p/topics", json={"name": "t"}).status_code == 200
    outside = mx["tmp"] / "outside"
    outside.mkdir()
    os.symlink(str(outside), str(mx["ws"] / "projects/p/topics/t/repo"))
    os.symlink(str(outside / "planted.md"), str(mx["ws"] / "projects/p/topics/t/link.md"))
    r = _import(client, {"projects/p/topics/t/repo/planted.sh": "echo pwned\n",
                         "projects/p/topics/t/link.md": "through a file link\n",
                         "projects/p/topics/t/fine.md": "ok\n"})
    assert r.status_code == 200, r.text
    assert list(outside.iterdir()) == []
    assert (mx["ws"] / "projects/p/topics/t/fine.md").read_text() == "ok\n"


def test_the_secret_scan_has_a_budget_and_apply_does_not_scan_again(client, mx, monkeypatch):
    """A 97 KB zip of 20 x 5 MB of zeros took 80 s to scan at upload, and apply scanned it all again.
    Now at most SCAN_TOTAL bytes are scanned (the rest is skipped, unchecked) and apply reuses the scan."""
    from maxxing import backup, importer
    monkeypatch.setattr(importer, "SCAN_TOTAL", 3000)
    seen: list[int] = []
    real = backup.scan_bytes
    monkeypatch.setattr(backup, "scan_bytes", lambda data: seen.append(len(data)) or real(data))
    files = {f"projects/p/notes/{n}.md": b"\0" * 1000 for n in range(5)}
    up = client.post("/api/import/upload", files={"file": ("x.zip", _zip(files), "application/zip")})
    assert up.status_code == 200, up.text
    assert sum(seen) <= 3000, seen
    unchecked = [s for s in up.json()["skipped"] if "not checked" in s["reason"]]
    assert len(unchecked) == 2, up.json()["skipped"]
    seen.clear()
    r = client.post(f"/api/import/{up.json()['id']}/apply")
    assert r.status_code == 200, r.text
    assert seen == []
    assert len(list((mx["ws"] / "projects/p/notes").iterdir())) == 3


def _upload(client, data: bytes):
    return client.post("/api/import/upload", files={"file": ("x.zip", data, "application/zip")})


def test_an_encrypted_or_damaged_zip_is_a_400_and_is_not_kept(client, mx):
    """zf.read() raised RuntimeError (encrypted entry) or BadZipFile (bad CRC): a 500, and the upload stayed."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("memory.md", "hi there, kept content\n")
    plain = buf.getvalue()
    enc = bytearray(plain)
    enc[6] |= 1                                                   # local header: "encrypted" flag
    central = plain.index(b"PK\x01\x02")
    enc[central + 8] |= 1                                         # central directory: same flag
    damaged = plain.replace(b"kept content", b"kxpt content")      # stored data no longer matches its CRC
    for data in (bytes(enc), damaged):
        r = _upload(client, data)
        assert r.status_code == 400 and r.json()["error"] == "bad_zip", r.text
    from maxxing import importer
    assert not any(importer.uploads_dir().iterdir())
