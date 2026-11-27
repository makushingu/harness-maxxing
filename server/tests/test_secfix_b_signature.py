"""Signed versions: `maxxing update` on the branch stable installs a version only when its tag is signed by a key of
maxxing/release-signers (the file of the installed version). Real git and ssh-keygen, no fake."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from maxxing import cmd_core, config

pytestmark = pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="ssh-keygen needed")


def _git(*a, cwd):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _key(tmp_path, name):
    k = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(k)], check=True)
    return k


@pytest.fixture
def signed(tmp_path, mx, monkeypatch):
    """A repository with a signed tag v1 on its first commit and an unsigned second commit; the publisher's key."""
    repo = tmp_path / "code"
    repo.mkdir()
    _git("init", "-q", "-b", "stable", cwd=repo)
    (repo / "a").write_text("1")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "one", cwd=repo)
    key = _key(tmp_path, "publisher")
    _git("-c", "gpg.format=ssh", "-c", f"user.signingkey={key}", "tag", "-s", "-m", "1", "v1", cwd=repo)
    one = _git("rev-parse", "HEAD", cwd=repo)
    (repo / "a").write_text("2")
    _git("commit", "-q", "-am", "two", cwd=repo)
    signers = tmp_path / "release-signers"
    signers.write_text(f'p@x namespaces="git" {(tmp_path / "publisher.pub").read_text()}')
    monkeypatch.setattr(config, "CODE", repo)
    monkeypatch.setattr(cmd_core, "SIGNERS", signers)
    return {"repo": repo, "one": one, "two": _git("rev-parse", "HEAD", cwd=repo), "signers": signers, "tmp": tmp_path}


def test_a_version_signed_by_a_publisher_is_accepted(signed):
    assert cmd_core.signature_unavailable() == ""
    assert cmd_core.verify_target(signed["one"]) == (True, "tag v1 signature verified")


def test_an_unsigned_commit_or_another_key_is_refused(signed):
    assert cmd_core.verify_target(signed["two"])[0] is False
    other = _key(signed["tmp"], "other")
    signed["signers"].write_text(f'p@x namespaces="git" {(signed["tmp"] / "other.pub").read_text()}')
    assert cmd_core.verify_target(signed["one"])[0] is False          # signed, but not by a key of the file
    _git("-c", "gpg.format=ssh", "-c", f"user.signingkey={other}", "tag", "-s", "-m", "2", "v2", cwd=signed["repo"])
    assert cmd_core.verify_target(signed["two"])[0] is True


def test_a_key_listed_for_another_use_does_not_sign_versions(signed):
    pub = (signed["tmp"] / "publisher.pub").read_text()
    signed["signers"].write_text(f'p@x namespaces="file" {pub}')
    assert cmd_core.verify_target(signed["one"])[0] is False


def test_stable_mode_checks_stable_only(mx):
    assert cmd_core.signature_mode("stable") == "off"                 # off until every publisher signs
    config.update_config(update_verify_signature="stable")
    assert cmd_core.signature_mode("stable") == "auto"
    assert cmd_core.signature_mode("beta") == "off" and cmd_core.signature_mode("main") == "off"
    config.update_config(update_verify_signature=True)
    assert cmd_core.signature_mode("beta") == "on"
    config.update_config(update_verify_signature=False)
    assert cmd_core.signature_mode("stable") == "off"


def test_the_shipped_key_file_is_valid():
    """Every line of the shipped file is a key git accepts for signatures of the namespace git."""
    lines = [ln for ln in cmd_core.SIGNERS.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    assert lines
    for ln in lines:
        who, ns, kind, key = ln.split()[:4]
        assert "@" in who and ns == 'namespaces="git"' and kind == "ssh-ed25519" and len(key) == 68


def test_a_server_that_cannot_check_is_told_why(mx, monkeypatch):
    monkeypatch.setattr(cmd_core.shutil, "which", lambda n: None)
    assert "ssh-keygen" in cmd_core.signature_unavailable()
