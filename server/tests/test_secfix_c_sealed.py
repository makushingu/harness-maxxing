"""secrets.json sealed on disk (`maxxing keys encrypt` / `decrypt`): systemd-creds is a fake on PATH here."""
from __future__ import annotations

import json
import os
import stat
import textwrap

import pytest

from maxxing import cli, cmd_core, config, security, vault

FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import base64, os, sys
    action, args = sys.argv[1], sys.argv[2:]
    mode = ""
    try:
        mode = open(os.environ["FAKE_CREDS_DIR"] + "/mode").read().strip()
    except OSError:
        pass
    with open(os.environ["FAKE_CREDS_DIR"] + "/calls", "a") as f:
        f.write(action + " " + " ".join(args) + "\\n")
    name = next(a.split("=", 1)[1] for a in args if a.startswith("--name="))
    assert args[-2:] == ["-", "-"], args
    data = sys.stdin.buffer.read()
    if mode == "fail-" + action:
        sys.stderr.write("Failed to " + action + ": no key here\\n")
        sys.exit(1)
    if action == "encrypt":
        assert "--with-key=auto" in args
        sys.stdout.buffer.write(b"FAKE1:" + name.encode() + b":" + base64.b64encode(data) + b"\\n")
    elif action == "decrypt":
        head, embedded, body = data.strip().split(b":", 2)
        if head != b"FAKE1" or embedded.decode() != name:
            sys.stderr.write("bad credential\\n")
            sys.exit(1)
        out = base64.b64decode(body)
        if mode == "mismatch":
            out = out.replace(b"{", b"{ ", 1)
        sys.stdout.buffer.write(out)
    else:
        sys.exit(2)
''')


@pytest.fixture
def creds(mx, tmp_path, monkeypatch):
    """A fake systemd-creds first on PATH; `mode(...)` makes it fail, `calls()` lists its runs."""
    bindir, work = tmp_path / "fakebin", tmp_path / "fakecreds"
    bindir.mkdir()
    work.mkdir()
    exe = bindir / "systemd-creds"
    exe.write_text(FAKE)
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CREDS_DIR", str(work))
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(config, "SEALED_RETRY_S", 0.0)
    config._forget_secrets()

    class Fake:
        bindir = None

        @staticmethod
        def mode(value: str = "") -> None:
            (work / "mode").write_text(value)
            config._forget_secrets()

        @staticmethod
        def calls(action: str = "") -> list[str]:
            try:
                lines = (work / "calls").read_text().splitlines()
            except OSError:
                return []
            return [l for l in lines if l.startswith(action)]

    Fake.bindir = bindir
    yield Fake
    config._forget_secrets()


def keys(*argv) -> int:
    return cli.main(["keys", *argv])


def test_nothing_changes_until_encrypt_is_run(creds):
    config.set_secret("telegram_token", "123:abc")
    assert json.loads(config.secrets_path().read_text())["telegram_token"] == "123:abc"
    assert not config.sealed_path().exists() and creds.calls() == []
    assert cmd_core.check_secrets_store()["level"] == cmd_core.INFO
    assert cmd_core.check_secrets_store()["title"] == "secrets stored in clear (0600)"
    assert "maxxing keys encrypt" in cmd_core.check_secrets_store()["fix"]


def test_encrypt_then_read_write_then_decrypt(creds, capsys):
    config.set_secret("telegram_token", "123:abc")
    vault.put("SHOP_TOKEN", "shpat_é")
    before = config.load_secrets()
    assert keys("encrypt") == 0
    assert not config.secrets_path().exists()
    sealed = config.sealed_path()
    assert stat.S_IMODE(sealed.stat().st_mode) == 0o600
    raw = sealed.read_bytes()
    assert raw.startswith(b"FAKE1:maxxing-secrets:") and b"shpat_" not in raw and b"123:abc" not in raw
    assert config.load_secrets() == before and vault.get("SHOP_TOKEN") == "shpat_é"
    assert cmd_core.check_secrets_store()["level"] == cmd_core.OK

    config.set_secret("github_token", "ghp_x")                 # a write re-seals, no clear file comes back
    vault.put("OTHER", "v2")
    config.write_json(config.secrets_path(), {**config.load_secrets(), "direct": 1})
    assert not config.secrets_path().exists()
    assert not [p.name for p in config.STATE.iterdir() if p.name.endswith(".tmp")]
    config._forget_secrets()                                   # as another process: decrypted from the file
    s = config.load_secrets()
    assert s["github_token"] == "ghp_x" and s["direct"] == 1 and vault.get("OTHER") == "v2"
    assert keys("encrypt") == 0 and "already sealed" in capsys.readouterr().out

    assert keys("decrypt") == 0
    assert not sealed.exists()
    assert stat.S_IMODE(config.secrets_path().stat().st_mode) == 0o600
    assert json.loads(config.secrets_path().read_text()) == s == config.load_secrets()
    assert keys("decrypt") == 0 and "not sealed" in capsys.readouterr().out
    config.set_secret("after", "1")
    assert not sealed.exists() and config.get_secret("after") == "1"


def test_reads_are_cached_until_the_file_changes(creds):
    config.set_secret("a", "1")
    assert keys("encrypt") == 0
    config._forget_secrets()
    n = len(creds.calls("decrypt"))
    for _ in range(20):
        assert config.load_secrets()["a"] == "1"
    assert len(creds.calls("decrypt")) == n + 1
    config.set_secret("b", "2")                                # the writer knows what it wrote
    n = len(creds.calls("decrypt"))
    assert config.load_secrets()["b"] == "2" and len(creds.calls("decrypt")) == n
    # another process replaced the file: seen through its stat
    other = {"a": "9"}
    blob = config._seal(other)
    tmp = config.sealed_path().with_name("x.tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, config.sealed_path())
    assert config.load_secrets() == other


def test_a_copy_is_returned_never_the_cache(creds):
    config.set_secret("a", {"k": 1})
    assert keys("encrypt") == 0
    config.load_secrets()["a"]["k"] = 2
    assert config.load_secrets()["a"] == {"k": 1}


def test_encrypt_refused_without_systemd_creds(creds, monkeypatch, capsys):
    config.set_secret("a", "1")
    (creds.bindir / "systemd-creds").unlink()
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    assert keys("encrypt") == 1
    err = capsys.readouterr().err
    assert "systemd-creds not found" in err and "Nothing was changed" in err
    assert not config.sealed_path().exists() and config.get_secret("a") == "1"


def test_encrypt_refused_when_not_root(creds, monkeypatch, capsys):
    config.set_secret("a", "1")
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    assert keys("encrypt") == 1 and "root" in capsys.readouterr().err
    assert keys("decrypt") == 1
    assert not config.sealed_path().exists() and creds.calls() == []


@pytest.mark.parametrize("mode", ["fail-encrypt", "fail-decrypt", "mismatch"])
def test_encrypt_refused_when_the_round_trip_fails(creds, capsys, mode):
    config.set_secret("a", "1")
    clear = config.secrets_path().read_bytes()
    creds.mode(mode)
    assert keys("encrypt") == 1
    err = capsys.readouterr().err
    assert ("round-trip check failed" in err) if mode == "mismatch" else ("no key here" in err)
    assert not config.sealed_path().exists()
    assert config.secrets_path().read_bytes() == clear
    assert not [p.name for p in config.STATE.iterdir() if p.name.endswith(".tmp")]
    creds.mode("")
    assert config.get_secret("a") == "1"


def test_encrypt_refuses_a_damaged_clear_file(creds, capsys):
    config.secrets_path().write_text("{not json")
    assert keys("encrypt") == 1 and "cannot be read" in capsys.readouterr().err
    assert config.secrets_path().read_text() == "{not json" and not config.sealed_path().exists()


def test_encrypt_warns_about_a_clear_copy_of_a_damaged_store(creds, capsys):
    from maxxing.sessions import spawn
    config.secrets_path().write_text("{not json")
    config.set_secret("telegram_token", "123:abc")             # repaired: the damaged file is kept as a copy
    copy = config.damaged_copy_of(config.secrets_path())
    assert copy and copy.read_text() == "{not json"
    copy.write_text('{"telegram_token": "123:abc"}')            # a copy that still holds a key in clear
    assert keys("encrypt") == 0
    out = capsys.readouterr().out
    assert str(copy) in out and "still in clear" in out
    rules = spawn.deny_rules({"protect_secrets": True})
    assert f"Read(/{config.STATE / 'secrets.json.damaged-*'})" in rules


def test_unreadable_store_is_loud_and_never_overwritten(creds, capsys, caplog):
    security.set_password("correct horse battery")
    config.set_secret("a", "1")
    assert keys("encrypt") == 0
    sealed, whole = config.sealed_path().read_bytes(), config.load_secrets()
    creds.mode("fail-decrypt")
    with pytest.raises(config.SecretsUnreadable, match="cannot be decrypted"):
        config.load_secrets()
    assert "cannot be decrypted" in caplog.text
    with pytest.raises(config.SecretsUnreadable):
        config.set_secret("b", "2")
    with pytest.raises(config.SecretsUnreadable):
        config.write_json(config.secrets_path(), {"b": 2})
    with pytest.raises(config.SecretsUnreadable):
        vault.put("NEW_KEY", "v")
    assert config.sealed_path().read_bytes() == sealed and not config.secrets_path().exists()
    c = cmd_core.check_secrets_store()
    assert c["level"] == cmd_core.FAIL and "cannot be decrypted" in c["detail"]
    capsys.readouterr()
    assert keys("decrypt") == 1
    assert "Nothing was changed" in capsys.readouterr().err
    assert config.sealed_path().read_bytes() == sealed and not config.secrets_path().exists()
    creds.mode("")
    assert config.load_secrets() == whole and whole["a"] == "1" and len(whole) > 1


def test_garbage_in_the_sealed_file_is_unreadable_not_empty(creds):
    config.set_secret("a", "1")
    assert keys("encrypt") == 0
    config.sealed_path().write_bytes(b"garbage")
    config._forget_secrets()
    with pytest.raises(config.SecretsUnreadable):
        config.load_secrets()
    with pytest.raises(config.SecretsUnreadable):
        config.set_secret("b", "2")
    assert config.sealed_path().read_bytes() == b"garbage"


def test_a_failed_write_keeps_the_sealed_store(creds):
    config.set_secret("a", "1")
    assert keys("encrypt") == 0
    sealed = config.sealed_path().read_bytes()
    config.load_secrets()
    (creds.bindir / ".." / "fakecreds" / "mode").write_text("fail-encrypt")   # the cache stays: the read still works
    with pytest.raises(config.SealError):
        config.set_secret("b", "2")
    assert config.sealed_path().read_bytes() == sealed
    creds.mode("")
    assert config.load_secrets() == {"a": "1"}


def test_too_large_for_systemd_creds(creds, monkeypatch):
    monkeypatch.setattr(config, "SEALED_MAX", 200)
    config.set_secret("a", "x" * 300)
    assert keys("encrypt") == 1
    assert config.secrets_path().exists() and not config.sealed_path().exists()


def test_both_files_left_by_an_interrupted_run(creds, capsys):
    config.set_secret("a", "1")
    clear = config.secrets_path().read_bytes()
    assert keys("encrypt") == 0
    config.secrets_path().write_bytes(clear)                   # as if the clear file had not been removed yet
    assert config.load_secrets() == {"a": "1"}                 # the sealed file is the store
    assert cmd_core.check_secrets_store()["level"] == cmd_core.WARN
    assert keys("encrypt") == 0 and not config.secrets_path().exists()
    config.secrets_path().write_text('{"a": "other"}')
    assert keys("encrypt") == 1 and "differ" in capsys.readouterr().err
    assert config.secrets_path().exists() and config.load_secrets() == {"a": "1"}
    assert keys("decrypt") == 0                                # the sealed content wins
    assert json.loads(config.secrets_path().read_text()) == {"a": "1"} and not config.sealed_path().exists()


def test_the_server_works_on_a_sealed_store(creds, client):
    assert keys("encrypt") == 0
    assert client.get("/api/sessions").status_code == 200       # the cookie key comes from the sealed store
    r = client.put("/api/secrets/SEALED_KEY", json={"value": "v1"})
    assert r.status_code == 200, r.text
    assert vault.get("SEALED_KEY") == "v1" and not config.secrets_path().exists()


def test_doctor_lists_the_check():
    import inspect
    assert "check_secrets_store" in inspect.getsource(cmd_core.collect_checks)
