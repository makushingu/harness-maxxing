"""Secret files of the Keys vault: storage, names, limits, exposure, API, `maxxing keys *-file`, backup exclusion."""
from __future__ import annotations

import hashlib
import io
import json
import os
import stat

import pytest
from fastapi.testclient import TestClient

from maxxing import backup, cli, config, vault, vault_files
from maxxing.sessions import spawn

BLOB = bytes(range(256)) * 4 + b"\x00\xff"          # binary, a null byte inside: a keystore is not text


def mode(p) -> str:
    return oct(stat.S_IMODE(os.stat(p).st_mode))[2:]


# ---- storage -------------------------------------------------------------------------------
def test_storage_permissions_and_binary_round_trip(mx):
    vault_files.put("ANDROID_KEYSTORE", BLOB, filename="upload.p12", note=" release ")
    d = mx["state"] / "secret-files"
    assert mode(d) == "700" and mode(d / "ANDROID_KEYSTORE") == "600"
    assert (d / "ANDROID_KEYSTORE").read_bytes() == BLOB and vault_files.read("ANDROID_KEYSTORE") == BLOB
    meta = config.load_secrets()["vault_files"]["ANDROID_KEYSTORE"]
    assert meta["sha256"] == hashlib.sha256(BLOB).hexdigest() and meta["size"] == len(BLOB)   # full one stored
    assert vault_files.list_files()[0]["sha256"] == hashlib.sha256(BLOB).hexdigest()[:12]      # short one shown
    assert meta["filename"] == "upload.p12" and meta["note"] == "release" and meta["expose"] is False
    assert "content" not in meta and not [p for p in d.iterdir() if p.name.endswith(".tmp")]


def test_a_replacement_is_atomic_and_keeps_the_metadata_it_was_not_given(mx):
    vault_files.put("CERT_FILE", b"one", filename="a.pem", note="prod", expose=True)
    d = mx["state"] / "secret-files"
    inode = os.stat(d / "CERT_FILE").st_ino
    vault_files.put("CERT_FILE", b"two-two")
    assert os.stat(d / "CERT_FILE").st_ino != inode                    # renamed over, never rewritten in place
    assert (d / "CERT_FILE").read_bytes() == b"two-two" and mode(d / "CERT_FILE") == "600"
    row = vault_files.list_files()[0]
    assert (row["filename"], row["note"], row["expose"], row["size"]) == ("a.pem", "prod", True, 7)
    vault_files.put("CERT_FILE", filename="b.pem", note="")             # metadata only: the file stays
    assert (d / "CERT_FILE").read_bytes() == b"two-two"
    assert vault_files.list_files()[0]["filename"] == "b.pem"
    with pytest.raises(vault.VaultError) as e:
        vault_files.put("CERT_FILE", b"x", create=True)
    assert e.value.code == "exists" and (d / "CERT_FILE").read_bytes() == b"two-two"


def test_a_failed_save_of_a_new_file_leaves_no_orphan(mx, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(config, "set_secret", boom)
    with pytest.raises(OSError):
        vault_files.put("NEW_FILE", b"data")
    assert not (mx["state"] / "secret-files" / "NEW_FILE").exists()


def test_a_failed_metadata_save_keeps_the_old_bytes_with_the_old_entry(mx, monkeypatch):
    vault_files.put("KEPT_FILE", b"old bytes", note="v1")
    before = config.load_secrets()["vault_files"]["KEPT_FILE"]

    def boom(*a, **k):
        raise OSError("disk full")
    with monkeypatch.context() as m:
        m.setattr(config, "set_secret", boom)
        with pytest.raises(OSError):
            vault_files.put("KEPT_FILE", b"new bytes, longer", note="v2")
    d = mx["state"] / "secret-files"
    assert (d / "KEPT_FILE").read_bytes() == b"old bytes"
    assert config.load_secrets()["vault_files"]["KEPT_FILE"] == before
    assert before["sha256"] == hashlib.sha256(b"old bytes").hexdigest() and before["size"] == 9
    assert sorted(p.name for p in d.iterdir()) == ["KEPT_FILE"]                     # no temp file left


def test_a_failed_rename_restores_the_entry(mx, monkeypatch):
    vault_files.put("SWAP_FILE", b"old")
    before = config.load_secrets()["vault_files"]["SWAP_FILE"]

    def boom(*a, **k):
        raise OSError("rename failed")
    with monkeypatch.context() as m:
        m.setattr(vault_files.os, "replace", boom)
        with pytest.raises(OSError):
            vault_files.put("SWAP_FILE", b"new")
    assert vault_files.read("SWAP_FILE") == b"old"
    assert config.load_secrets()["vault_files"]["SWAP_FILE"] == before


def test_crash_leftovers_are_swept_but_never_a_stored_file(mx):
    vault_files.put("REAL_FILE", b"keep me")
    d = mx["state"] / "secret-files"
    old_tmp, new_tmp, orphan = d / ".REAL_FILE.abc.tmp", d / ".OTHER.def.tmp", d / "ORPHAN_FILE"
    for p in (old_tmp, new_tmp, orphan):
        p.write_bytes(b"left over")
    past = __import__("time").time() - vault_files.STALE_TMP_S - 60
    os.utime(old_tmp, (past, past))
    os.utime(orphan, (past, past))
    (d / "sub").mkdir()
    vault_files.list_files()                                    # listing alone changes nothing
    assert orphan.exists()
    vault_files.put("OTHER_FILE", b"x")
    names = sorted(p.name for p in d.iterdir())
    assert names == [".OTHER.def.tmp", "OTHER_FILE", "REAL_FILE", "sub"]       # a recent temp may be a live write
    assert vault_files.read("REAL_FILE") == b"keep me"
    new_tmp.write_bytes(b"x")
    os.utime(new_tmp, (past, past))
    orphan.write_bytes(b"again")
    assert vault_files.delete("NOT_THERE") is False                              # delete sweeps as well
    assert sorted(p.name for p in d.iterdir()) == ["OTHER_FILE", "REAL_FILE", "sub"]


def test_filename_is_display_only_and_sanitized(mx):
    vault_files.put("F_ONE", b"x", filename="../../etc/pass\x00wd\n")
    vault_files.put("F_TWO", b"x", filename="C:\\Users\\me\\key.jks")
    vault_files.put("F_THREE", b"x", filename="a" * 300)
    vault_files.put("F_FOUR", b"x")
    names = {r["name"]: r["filename"] for r in vault_files.list_files()}
    assert names["F_ONE"] == "passwd" and names["F_TWO"] == "key.jks" and len(names["F_THREE"]) == 100
    assert names["F_FOUR"] == "F_FOUR"
    assert sorted(p.name for p in (mx["state"] / "secret-files").iterdir()) == ["F_FOUR", "F_ONE", "F_THREE", "F_TWO"]


# ---- names and limits ----------------------------------------------------------------------
def test_names_follow_the_text_keys_rules(mx):
    for bad in ("lower", "1ABC", "A", "WITH-DASH", "PATH", "MAXXING_STATE", "X" * 65, "FOO\n", "../ETC"):
        with pytest.raises(vault.VaultError):
            vault_files.put(bad, b"x")
    assert vault_files.list_files() == [] and not (mx["state"] / "secret-files").exists()


def test_a_name_is_a_text_key_or_a_file_never_both(mx):
    vault.put("TAKEN_KEY", "secret-value")
    with pytest.raises(vault.VaultError) as e:
        vault_files.put("TAKEN_KEY", b"x")
    assert e.value.code == "name_taken"
    vault_files.put("TAKEN_FILE", b"x")
    with pytest.raises(vault.VaultError) as e:
        vault.put("TAKEN_FILE", "text")
    assert e.value.code == "name_taken" and vault.get("TAKEN_FILE") is None


def test_size_limits(mx):
    with pytest.raises(vault.VaultError) as e:
        vault_files.put("EMPTY_ONE", b"")
    assert e.value.code == "invalid_value"
    with pytest.raises(vault.VaultError) as e:
        vault_files.put("TOO_BIG", b"x" * (vault_files.MAX_SIZE + 1))
    assert e.value.code == "invalid_value"
    with pytest.raises(vault.VaultError) as e:
        vault_files.put("NO_CONTENT")
    assert e.value.code == "file_required"
    vault_files.put("ONE_BYTE", b"x")
    vault_files.put("ONE_MIB", b"x" * vault_files.MAX_SIZE)
    assert {r["name"]: r["size"] for r in vault_files.list_files()} == {"ONE_BYTE": 1, "ONE_MIB": vault_files.MAX_SIZE}


def test_a_note_that_is_not_text_is_refused(mx):
    with pytest.raises(vault.VaultError) as e:
        vault_files.put("BAD_NOTE", b"x", note="a\ud800b")
    assert e.value.code == "invalid_note" and vault_files.list_files() == []


# ---- listing, exposure, delete -------------------------------------------------------------
def test_the_list_never_holds_the_content(mx):
    vault_files.put("LEAK_CHECK", b"TOP-SECRET-BYTES", filename="k.json", note="n", expose=True)
    rows = vault_files.list_files()
    assert set(rows[0]) == {"name", "filename", "size", "sha256", "note", "expose", "updated"}
    assert "TOP-SECRET-BYTES" not in json.dumps(rows)


def test_exposed_env_is_the_path_never_the_content(mx):
    vault_files.put("SA_JSON", b"TOP-SECRET-BYTES", expose=True)
    vault_files.put("PRIVATE_FILE", b"x", expose=False)
    vault.put("TEXT_KEY", "text-value", expose=True)
    path = str(mx["state"] / "secret-files" / "SA_JSON")
    assert vault_files.exposed_files_env() == {"SA_JSON": path}
    env = spawn.auth_env()
    assert env["SA_JSON"] == path and env["TEXT_KEY"] == "text-value" and "PRIVATE_FILE" not in env
    assert "TOP-SECRET-BYTES" not in json.dumps(env)
    assert "SA_JSON" not in spawn.auth_env(keys=["TEXT_KEY"])             # an agent's turn: text keys it lists only
    (mx["state"] / "secret-files" / "SA_JSON").unlink()                    # file gone: nothing exported, no error
    assert vault_files.exposed_files_env() == {}


def test_exposed_env_skips_reserved_names_and_links_and_never_raises(mx, monkeypatch):
    vault_files.put("LINKED", b"x", expose=True)
    p = mx["state"] / "secret-files" / "LINKED"
    p.unlink()
    p.symlink_to("/etc/hostname")
    config.set_secret("vault_files", {**config.load_secrets()["vault_files"],
                                      "PATH": {"expose": True, "size": 1}, "lower": {"expose": True}})
    assert vault_files.exposed_files_env() == {}
    monkeypatch.setattr(vault_files, "_meta", lambda: 1 / 0)
    assert vault_files.exposed_files_env() == {}


def test_cron_shell_jobs_get_the_path(mx):
    from maxxing import crons
    vault_files.put("JOB_FILE", b"x", expose=True)
    env = crons._job_env({"id": "j1", "name": "job"})
    assert env["JOB_FILE"] == str(mx["state"] / "secret-files" / "JOB_FILE")


def test_delete_removes_the_file_and_the_entry(mx):
    vault_files.put("GONE_SOON", b"x")
    assert vault_files.delete("GONE_SOON") is True and vault_files.delete("GONE_SOON") is False
    assert not (mx["state"] / "secret-files" / "GONE_SOON").exists()
    assert vault_files.list_files() == [] and "vault_files" not in config.load_secrets()


def test_a_failed_metadata_save_on_delete_keeps_the_file(mx, monkeypatch):
    vault_files.put("KEEP_ME", b"precious")
    def boom(*a, **k):
        raise OSError("disk full")
    with monkeypatch.context() as m:
        m.setattr(config, "set_secret", boom)
        with pytest.raises(OSError):
            vault_files.delete("KEEP_ME")
    assert vault_files.read("KEEP_ME") == b"precious" and [f["name"] for f in vault_files.list_files()] == ["KEEP_ME"]


def test_protect_secrets_denies_the_folder(mx):
    rules = spawn.deny_rules({"protect_secrets": True})
    assert f"Read(/{mx['state']}/secret-files/**)" in rules and f"Edit(/{mx['state']}/secret-files/**)" in rules


# ---- backup --------------------------------------------------------------------------------
def test_the_backup_never_holds_the_files_or_their_metadata(mx):
    ws = mx["ws"]
    (ws / "memory.md").write_text("- note\n")
    vault_files.put("BACKUP_FILE", b"TOP-SECRET-BYTES", filename="store.jks", expose=True)
    (ws / "projects" / "acme" / "secret-files").mkdir(parents=True)   # a workspace folder of that name is not special
    (ws / "projects" / "acme" / "secret-files" / "memory.md").write_text("- kept\n")
    snap = backup.snapshot()
    assert "memory.md" in snap and "projects/acme/secret-files/memory.md" in snap
    assert not any("BACKUP_FILE" in rel for rel in snap)
    assert b"TOP-SECRET-BYTES" not in b"".join(snap.values()) and b"vault_files" not in b"".join(snap.values())
    assert not backup.denied("projects/acme/secret-files/memory.md") and backup.scan(snap) == []


def test_the_backup_skips_the_vault_folder_even_inside_the_workspace(mx, monkeypatch):
    inner = mx["ws"] / "state"
    monkeypatch.setattr(vault_files, "files_dir", lambda: inner / "secret-files")
    vault_files.put("INNER_FILE", b"TOP-SECRET-BYTES")
    (inner / "secret-files" / "memory.md").write_text("TOP-SECRET-BYTES")      # would match ALWAYS otherwise
    (inner / "memory.md").write_text("- state note\n")
    snap = backup.collect()
    assert "state/memory.md" in snap and not any("secret-files" in rel for rel in snap)


# ---- API -----------------------------------------------------------------------------------
def test_api_put_list_update_delete(client, mx):
    assert client.get("/api/secret-files").json() == []
    r = client.put("/api/secret-files/GCP_SA", content=BLOB, params={"note": "ci", "expose": "true", "filename": "sa.p12"},
                   headers={"content-type": "application/octet-stream"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    row = client.get("/api/secret-files").json()[0]
    assert row["name"] == "GCP_SA" and row["filename"] == "sa.p12" and row["note"] == "ci" and row["expose"] is True
    assert row["size"] == len(BLOB) and row["sha256"] == hashlib.sha256(BLOB).hexdigest()[:12]
    assert vault_files.read("GCP_SA") == BLOB
    assert client.put("/api/secret-files/GCP_SA", params={"expose": "false"}).status_code == 200   # metadata only
    assert vault_files.read("GCP_SA") == BLOB and client.get("/api/secret-files").json()[0]["expose"] is False
    assert client.delete("/api/secret-files/GCP_SA").json() == {"ok": True}
    assert client.delete("/api/secret-files/GCP_SA").status_code == 404
    assert client.get("/api/secret-files").json() == []


def test_api_errors(client, mx):
    for bad in ("lower", "PATH", "MAXXING_X"):
        r = client.put(f"/api/secret-files/{bad}", content=b"x")
        assert r.status_code == 400 and r.json()["error"] in ("invalid_name", "reserved_name"), bad
    assert client.put("/api/secret-files/NEW_ONE").json()["error"] == "file_required"
    assert client.put("/api/secret-files/ONE_MIB", content=b"x" * vault_files.MAX_SIZE).status_code == 200
    r = client.put("/api/secret-files/TOO_BIG", content=b"x" * (vault_files.MAX_SIZE + 1))
    assert r.status_code == 413 and r.json()["error"] == "too_large" and not vault_files.exists("TOO_BIG")
    assert client.put("/api/secret-files/ONE_MIB", content=b"y", params={"create": "true"}).status_code == 409
    client.put("/api/secrets/TEXT_KEY", json={"value": "v"})
    r = client.put("/api/secret-files/TEXT_KEY", content=b"x")
    assert r.status_code == 409 and r.json()["error"] == "name_taken"
    r = client.put("/api/secrets/ONE_MIB", json={"value": "v"})
    assert r.status_code == 409 and r.json()["error"] == "name_taken"
    assert client.get("/api/secrets").json()[0]["name"] == "TEXT_KEY" and len(client.get("/api/secrets").json()) == 1


def test_api_refuses_other_content_types_and_streams_the_size_check(client, mx, monkeypatch):
    big = b"x" * (vault_files.MAX_SIZE + 1)
    r = client.put("/api/secret-files/MULTI_PART", files={"file": ("a.bin", big)})
    assert r.status_code == 415 and r.json()["error"] == "unsupported_media_type"
    r = client.put("/api/secret-files/JSON_BODY", json={"x": 1})
    assert r.status_code == 415 and r.json()["error"] == "unsupported_media_type"
    r = client.put("/api/secret-files/WITH_PARAM", content=b"ok",
                   headers={"content-type": "application/octet-stream; charset=binary"})
    assert r.status_code == 200 and vault_files.read("WITH_PARAM") == b"ok"
    assert not vault_files.exists("MULTI_PART") and not vault_files.exists("JSON_BODY")

    def chunks():                                   # no Content-Length (chunked): counted while it streams
        for _ in range(4):
            yield b"y" * (vault_files.MAX_SIZE // 2)
    from maxxing import bodylimit
    monkeypatch.setattr(bodylimit, "DEFAULT_MAX", 64 * vault_files.MAX_SIZE)      # the route's own limit, not the cap
    r = client.put("/api/secret-files/CHUNKED", content=chunks(), headers={"content-type": "application/octet-stream"})
    assert r.status_code == 413 and r.json()["error"] == "too_large" and not vault_files.exists("CHUNKED")


def test_api_needs_auth_and_csrf_and_has_no_content_endpoint(client, mx):
    client.put("/api/secret-files/SOME_FILE", content=b"TOP-SECRET-BYTES")
    for path in ("", "/SOME_FILE", "/SOME_FILE/reveal", "/SOME_FILE/content", "/SOME_FILE/download"):
        r = client.get(f"/api/secret-files{path}")
        assert b"TOP-SECRET-BYTES" not in r.content, path
        if path:
            assert r.status_code in (404, 405), path                         # no route returns the file
    csrf = client.put("/api/secret-files/SOME_FILE", content=b"x", headers={"x-maxxing": ""})
    assert csrf.status_code == 403
    client.cookies.clear()
    for verb, path in (("get", ""), ("put", "/SOME_FILE"), ("delete", "/SOME_FILE")):
        assert client.request(verb, f"/api/secret-files{path}").status_code == 401, (verb, path)
    assert vault_files.read("SOME_FILE") == b"TOP-SECRET-BYTES"


# ---- CLI -----------------------------------------------------------------------------------
def run(monkeypatch, *argv, stdin=b""):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(stdin)))
    return cli.main(["keys", *argv])


def test_cli_put_get_list_delete(mx, monkeypatch, capsysbinary):
    src = mx["tmp"] / "upload.p12"
    src.write_bytes(BLOB)
    assert run(monkeypatch, "put-file", "ANDROID_KEYSTORE", str(src), "--note", "release") == 0
    assert vault_files.read("ANDROID_KEYSTORE") == BLOB
    row = vault_files.list_files()[0]
    assert row["filename"] == "upload.p12" and row["note"] == "release" and row["expose"] is True   # new: exposed
    assert vault_files.exposed_files_env() == {"ANDROID_KEYSTORE": str(mx["state"] / "secret-files" / "ANDROID_KEYSTORE")}
    assert run(monkeypatch, "put-file", "ANDROID_KEYSTORE", "-", stdin=b"new bytes") == 0   # update keeps note, exposure
    row = vault_files.list_files()[0]
    assert row["note"] == "release" and row["expose"] is True and row["size"] == 9
    vault.put("TEXT_KEY", "t-value", note="plain")
    capsysbinary.readouterr()
    assert run(monkeypatch, "list") == 0
    out = capsysbinary.readouterr().out.decode()
    lines = {ln.split()[0]: ln for ln in out.splitlines()}
    assert " file " in lines["ANDROID_KEYSTORE"] and " file " not in lines["TEXT_KEY"] and "new bytes" not in out
    assert run(monkeypatch, "list", "--json") == 0
    rows = {r["name"]: r for r in json.loads(capsysbinary.readouterr().out.decode())}
    assert rows["TEXT_KEY"]["kind"] == "text" and "sha256" not in rows["TEXT_KEY"]
    assert rows["ANDROID_KEYSTORE"]["kind"] == "file" and rows["ANDROID_KEYSTORE"]["size"] == 9
    assert rows["ANDROID_KEYSTORE"]["filename"] == "upload.p12"
    assert rows["ANDROID_KEYSTORE"]["sha256"] == hashlib.sha256(b"new bytes").hexdigest()[:12]
    assert run(monkeypatch, "get-file", "ANDROID_KEYSTORE") == 0
    assert capsysbinary.readouterr().out == b"new bytes"
    assert run(monkeypatch, "delete-file", "ANDROID_KEYSTORE") == 0
    assert vault_files.read("ANDROID_KEYSTORE") is None
    assert run(monkeypatch, "get-file", "ANDROID_KEYSTORE") == 1 and run(monkeypatch, "delete-file", "ANDROID_KEYSTORE") == 1


def test_cli_get_file_output_is_private_and_never_overwrites_by_default(mx, monkeypatch):
    vault_files.put("OUT_FILE", BLOB)
    dest = mx["tmp"] / "out.bin"
    assert run(monkeypatch, "get-file", "OUT_FILE", "--output", str(dest)) == 0
    assert dest.read_bytes() == BLOB and mode(dest) == "600"
    dest.write_bytes(b"mine")
    assert run(monkeypatch, "get-file", "OUT_FILE", "--output", str(dest)) == 1 and dest.read_bytes() == b"mine"
    dest.chmod(0o644)
    assert run(monkeypatch, "get-file", "OUT_FILE", "--output", str(dest), "--force") == 0
    assert dest.read_bytes() == BLOB and mode(dest) == "600"


def test_cli_get_file_on_a_terminal_prints_text_only(mx, monkeypatch, capsysbinary):
    vault_files.put("BIN_FILE", BLOB)
    vault_files.put("TXT_FILE", b'{"type": "service_account"}\n')
    vault_files.put("ESC_FILE", b"text \x1b]0;title\x07")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert run(monkeypatch, "get-file", "BIN_FILE") == 2 and run(monkeypatch, "get-file", "ESC_FILE") == 2
    out = capsysbinary.readouterr()
    assert out.out == b"" and b"-o FILE" in out.err
    assert run(monkeypatch, "get-file", "TXT_FILE") == 0
    assert capsysbinary.readouterr().out == b'{"type": "service_account"}\n'


def test_cli_get_file_into_a_closed_pipe_is_quiet(mx, monkeypatch, capsys):
    vault_files.put("PIPE_FILE", BLOB)

    class Closed(io.BytesIO):
        def write(self, b):
            raise BrokenPipeError(32, "Broken pipe")
    devnull = os.open(os.devnull, os.O_WRONLY)
    fake = io.TextIOWrapper(Closed())
    fake.fileno = lambda: devnull                     # dup2 target, not the test's real stdout
    monkeypatch.setattr("sys.stdout", fake)
    monkeypatch.setattr(fake, "isatty", lambda: False)
    try:
        assert run(monkeypatch, "get-file", "PIPE_FILE") == 141
    finally:
        os.close(devnull)


def test_cli_get_file_output_leaves_no_partial_file(mx, monkeypatch):
    vault_files.put("PART_FILE", BLOB)
    dest = mx["tmp"] / "out" / "part.bin"
    dest.parent.mkdir()
    real = os.fsync

    def boom(fd):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(os, "fsync", boom)
    assert run(monkeypatch, "get-file", "PART_FILE", "-o", str(dest)) == 1
    monkeypatch.setattr(os, "fsync", real)
    assert list(dest.parent.iterdir()) == []
    link = mx["tmp"] / "out" / "link"
    link.symlink_to(mx["tmp"] / "out" / "target")
    assert run(monkeypatch, "get-file", "PART_FILE", "-o", str(link)) == 1          # a dangling link is kept too
    assert link.is_symlink() and not (mx["tmp"] / "out" / "target").exists()


def test_cli_get_and_delete_of_a_file_name_point_to_the_file_commands(mx, monkeypatch, capsys):
    vault_files.put("ONLY_FILE", b"x")
    vault.put("ONLY_TEXT", "v")
    assert run(monkeypatch, "get", "ONLY_FILE") == 1 and "get-file ONLY_FILE" in capsys.readouterr().err
    assert run(monkeypatch, "delete", "ONLY_FILE") == 1 and "delete-file ONLY_FILE" in capsys.readouterr().err
    assert vault_files.exists("ONLY_FILE")
    assert run(monkeypatch, "get-file", "ONLY_TEXT") == 1 and "keys get" in capsys.readouterr().err
    assert run(monkeypatch, "delete-file", "ONLY_TEXT") == 1 and "keys delete" in capsys.readouterr().err
    assert run(monkeypatch, "get", "NOTHING_HERE") == 1 and "no such key" in capsys.readouterr().err


def test_cli_put_file_refusals(mx, monkeypatch):
    big = mx["tmp"] / "big.bin"
    big.write_bytes(b"x" * (vault_files.MAX_SIZE + 1))
    assert run(monkeypatch, "put-file", "BIG_FILE", str(big)) == 2
    assert run(monkeypatch, "put-file", "NOPE_FILE", str(mx["tmp"] / "missing")) == 2
    assert run(monkeypatch, "put-file", "EMPTY_FILE", "-", stdin=b"") == 2
    assert run(monkeypatch, "put-file", "bad-name", "-", stdin=b"x") == 2
    vault.put("TEXT_KEY", "v")
    assert run(monkeypatch, "put-file", "TEXT_KEY", "-", stdin=b"x") == 2          # a text key already has the name
    assert run(monkeypatch, "put-file", "PRIVATE_FILE", "-", "--no-expose", stdin=b"x") == 0
    assert "PRIVATE_FILE" not in vault_files.exposed_files_env()
    assert vault_files.list_files()[0]["name"] == "PRIVATE_FILE" and len(vault_files.list_files()) == 1


def test_an_agent_turn_cannot_use_the_file_commands(mx, monkeypatch, capsys):
    vault_files.put("AGENT_FILE", b"TOP-SECRET-BYTES", expose=True)
    monkeypatch.setenv("MAXXING_AGENT", "acme/blog/help")
    for argv in (("put-file", "AGENT_FILE", "-"), ("get-file", "AGENT_FILE"), ("delete-file", "AGENT_FILE")):
        assert run(monkeypatch, *argv, stdin=b"other") == 1, argv
    assert "TOP-SECRET-BYTES" not in capsys.readouterr().out
    assert vault_files.read("AGENT_FILE") == b"TOP-SECRET-BYTES"


def test_an_agent_turn_lists_only_its_own_text_keys(mx, monkeypatch, capsys):
    from maxxing import agents
    vault.put("MINE", "v1", note="its key")
    vault.put("OWNER_STRIPE_LIVE", "v2", note="Stripe live key of client Acme")
    vault_files.put("GCP_SA", b"{}", note="prod GCP", expose=True)
    monkeypatch.setenv("MAXXING_AGENT", "acme/blog/help")
    monkeypatch.setattr(agents, "exists", lambda p: True)
    monkeypatch.setattr(agents, "load", lambda p: {"keys": ["MINE", "GCP_SA"]})
    for argv in (("list",), ("list", "--json")):
        assert run(monkeypatch, *argv) == 0
        out = capsys.readouterr().out
        assert "MINE" in out and "OWNER_STRIPE_LIVE" not in out and "Acme" not in out and "GCP_SA" not in out, argv
    monkeypatch.delenv("MAXXING_AGENT")                  # the owner still sees everything
    assert run(monkeypatch, "list") == 0
    out = capsys.readouterr().out
    assert "MINE" in out and "OWNER_STRIPE_LIVE" in out and "GCP_SA" in out


def test_any_cli_command_into_a_closed_pipe_is_quiet(mx, monkeypatch):
    for i in range(400):
        vault.put(f"PIPE_{i}", "v", note="a note long enough to fill the pipe buffer " * 3)
    r, w = os.pipe()
    os.close(r)                                       # `| head` that already left
    fake = io.TextIOWrapper(os.fdopen(w, "wb"), write_through=True)
    monkeypatch.setattr("sys.stdout", fake)
    try:
        assert run(monkeypatch, "list", "--json") == 141
    finally:
        monkeypatch.undo()
        fake.close()                                  # w now points at /dev/null: closes quietly


def test_a_broken_pipe_of_the_command_itself_is_still_an_error(mx, monkeypatch):
    from maxxing import cmd_keys
    r, w = os.pipe()                                  # stdout's reader is still there
    fake = io.TextIOWrapper(os.fdopen(w, "wb"), write_through=True)
    monkeypatch.setattr("sys.stdout", fake)

    def boom(a):
        raise BrokenPipeError(32, "Broken pipe")      # a socket or a child of the command
    monkeypatch.setattr(cmd_keys, "_handler", boom)
    monkeypatch.setitem(cli.COMMANDS, "keys", (*cli.COMMANDS["keys"][:2], boom))
    try:
        with pytest.raises(BrokenPipeError):
            cli.main(["keys", "list"])
    finally:
        monkeypatch.undo()
        fake.close()
        os.close(r)
