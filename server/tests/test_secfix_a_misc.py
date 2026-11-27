"""Regression tests of the security review of 2026-11-24: sign-in throttle, received files, Team downloads, mail
requests, Git, Infra, the Keys vault, MCP, profile photos, the update."""
from __future__ import annotations

import asyncio
import os
import struct
import subprocess
import sys
import threading
import time
import zlib

import pytest
from fastapi import HTTPException

from conftest import wait_for
from maxxing import cmd_core, codediff, config, gitview, infra, mcp, profile_photo, security, team, teampeer, vault
from maxxing.api import mail as mail_api
from maxxing.mail import outbox, send
from test_cmd_core import _git, env, repos, run_cli  # noqa: F401  (fixtures)
from test_customs import _head, _upstream_release, code  # noqa: F401  (fixtures)
from test_mail_agents import _as_agent, _cli, _grant, box, smtp  # noqa: F401  (fixtures)


# ---- sign-in throttle ---------------------------------------------------------------------------------------
@pytest.fixture
def clock(monkeypatch):
    security._fails.clear()
    security._good.clear()
    security._wide.clear()
    monkeypatch.setattr(security, "_last_global", 0.0)
    monkeypatch.setattr(security, "_last_fresh", 0.0)
    now = [time.time()]
    monkeypatch.setattr(security.time, "time", lambda: now[0])
    yield now
    security._fails.clear()
    security._wide.clear()


def _global_cap_reached():
    for n in range(security.GLOBAL_FAIL_MAX):
        assert security.begin_attempt(f"198.51.100.{n}")[0] is None


def test_new_addresses_of_one_ipv6_block_do_not_hold_the_first_try_slot(clock):
    _global_cap_reached()
    clock[0] += 10
    assert security.begin_attempt("2001:db8:1:1::/64")[0] is None          # its first address: a first try
    clock[0] += 1
    assert security.begin_attempt("2001:db8:1:2::/64")[0] is None          # the next ones share the other slot
    clock[0] += 1
    assert security.begin_attempt("2001:db8:1:3::/64")[0] == "global"
    clock[0] += security.GLOBAL_GAP_S
    assert security.begin_attempt("2001:db8:1:4::/64")[0] is None
    clock[0] += 0.5
    assert security.begin_attempt("2001:db8:ffff:1::/64")[0] is None       # someone else's first try still passes
    assert security._wide_key("pw:2001:db8:1:4::/64") == "2001:db8:1::/48" and security._wide_key("pw:198.51.100.1") is None


def test_wrong_sign_ins_of_strangers_do_not_block_a_password_change(client, clock):
    _global_cap_reached()
    assert security.begin_attempt("203.0.113.1")[0] is None                # the slot of a first try is taken...
    assert security.begin_attempt("203.0.113.2")[0] == "global"            # ...so a stranger now waits
    r = client.post("/api/auth/password", json={"current": "wrong", "new": "another long password"})
    assert r.status_code == 401 and r.json()["error"] == "bad_password", r.text    # checked, not put off (429)
    r = client.post("/api/auth/password", json={"current": "correct horse battery", "new": "another long password 42"})
    assert r.status_code == 200, r.text


# ---- received files -----------------------------------------------------------------------------------------
def test_a_received_html_file_is_shown_without_scripts_or_network(client, mx):
    ws = mx["files"] / "ws"
    config.update_config(workspace=str(ws))
    got = ws / "mail" / "attachments" / "acc1" / "abc-1" / "1" / "invoice.html"
    mine = mx["files"] / "site" / "index.html"
    for f in (got, mine):
        f.parent.mkdir(parents=True)
        f.write_text("<script>fetch('https://tracker.example/open')</script><p>hello</p>")
    csp = {}
    for name, f in (("got", got), ("mine", mine)):
        url = client.get("/api/files/site-url", params={"path": str(f)}).json()["url"]
        r = client.get(url)
        assert r.status_code == 200 and "hello" in r.text
        csp[name] = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp["got"] and "allow-scripts" not in csp["got"] and csp["got"].startswith("sandbox;")
    assert "allow-scripts" in csp["mine"] and "default-src" not in csp["mine"]


def test_mail_copies_never_follow_a_link_planted_in_their_folder(mx):
    victim = mx["tmp"] / "victim"
    (victim / "old").mkdir(parents=True)
    (victim / "old" / "keep.txt").write_text("mine")
    os.utime(victim / "old", (1, 1))
    root = mail_api._view_root()
    root.mkdir(parents=True)
    (root / "other").symlink_to(victim)                 # another account's folder: its old "copies" are not ours
    out = mail_api._save_for_view("acc1", "INBOX", 7, [(1, "a.pdf", "application/pdf", b"pdf")], "<m7@b.co>")
    assert (victim / "old" / "keep.txt").read_text() == "mine" and out[1].endswith("a.pdf")
    (root / "acc2").symlink_to(victim)                  # the account asked for is itself a link: refused
    with pytest.raises(HTTPException) as e:
        mail_api._save_for_view("acc2", "INBOX", 7, [(1, "a.pdf", "application/pdf", b"pdf")], "<m7@b.co>")
    assert e.value.status_code == 409 and sorted(p.name for p in victim.iterdir()) == ["old"]


# ---- Team ---------------------------------------------------------------------------------------------------
def test_one_sender_cannot_hold_every_download_slot(mx, monkeypatch):
    go, started = threading.Event(), []

    def fetch(address, fid, dest, max_b, chat, reserve=0):
        started.append(address)
        go.wait(10)
        return False

    monkeypatch.setattr(teampeer, "fetch_file", fetch)
    threads = [threading.Thread(target=team._fetch, args=(frm, "c1", "m1", {"fid": f"f{n}", "name": "a.bin", "size": 1}))
               for n, frm in enumerate(["https://slow.example"] * 6 + ["https://friend.example"])]
    try:
        for t in threads[:6]:
            t.start()
        wait_for(lambda: len(started) == team.SENDER_SLOTS, 5)
        threads[6].start()
        wait_for(lambda: "https://friend.example" in started, 5)        # 4 slots, the slow sender holds 2 of them
        assert started.count("https://slow.example") == team.SENDER_SLOTS
    finally:
        go.set()
        for t in threads:
            if t.ident:
                t.join(10)
    assert team._by_sender == {} and team._queued[0] == 0


def test_a_download_that_crawls_is_dropped(tmp_path, monkeypatch):
    now = [1000.0]

    class R:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def iter_bytes(self, n):
            for _ in range(1000):
                now[0] += 30                             # 100 bytes every 30 s
                yield b"x" * 100

    class C:
        def stream(self, *a, **k): return R()

    monkeypatch.setattr(teampeer.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(teampeer, "_http", lambda: C())
    monkeypatch.setattr(teampeer, "_key_to", lambda *a: b"k")
    monkeypatch.setattr(teampeer, "_sign", lambda *a: {})
    monkeypatch.setattr(teampeer, "own_address", lambda: "me")
    monkeypatch.setattr(teampeer, "_check_target", lambda a: "http://x")
    assert teampeer.fetch_file("peer", "f1", tmp_path / "a", 0, "chat") is False
    assert now[0] - 1000.0 < 300 and not list(tmp_path.iterdir())       # given up after minutes, not FETCH_DEADLINE


def test_a_group_member_named_like_a_contact_shows_its_server(mx):
    with teampeer._lock:
        doc = teampeer._load()
        doc["peers"]["https://alice.example"] = {"status": "accepted", "name": "Alice", "key": "k"}
        doc["peers"]["https://evil.example"] = {"status": "group", "name": "alice", "group_keys": {"c1": "k"}}
        doc["peers"]["https://bob.example"] = {"status": "group", "name": "Bob", "group_keys": {"c1": "k"}}
        teampeer._save(doc)
    names = {p["server"]: p["name"] for p in teampeer.people().values()}
    assert names == {"alice.example": "Alice", "evil.example": "alice (evil.example)", "bob.example": "Bob"}


# ---- mail requests ------------------------------------------------------------------------------------------
def test_a_long_subject_or_list_of_recipients_never_hides_the_text_behind_send(mx, monkeypatch):
    from maxxing import feed
    posted = []
    monkeypatch.setattr(send, "save_draft", lambda acc, draft, files: {"folder": "Drafts", "uid": 1})
    monkeypatch.setattr(feed, "post", lambda title, body, **kw: posted.append((body, kw["actions"])) or {"id": 1})
    acc = {"id": "acc1", "address": "me@x.org"}
    outbox.queue(acc, "p/t/agents/a", {"to": ["bob@x.org"], "subject": "Re: " + "A" * 3900, "text": "wire 9000 EUR"}, [], "why")
    outbox.queue(acc, "p/t/agents/a", {"to": [f"u{n}@x.org" for n in range(300)], "subject": "S", "text": "hello"}, [], "why")
    outbox.queue(acc, "p/t/agents/a", {"to": ["bob@x.org"], "subject": "S", "text": "hello"}, [], "why")
    for body, actions in posted[:2]:
        assert len(body) <= feed.BODY_MAX and "Longer than shown" in body
        assert "allow" not in {a["id"] for a in actions}
    assert "wire 9000 EUR" in posted[0][0] and "hello" in posted[1][0]
    assert "allow" in {a["id"] for a in posted[2][1]} and "Longer than shown" not in posted[2][0]


def test_an_agent_cannot_pile_up_requests_to_send(client, box, monkeypatch, capsys, smtp):  # noqa: F811
    _grant(client, rights=["read", "send"], approve_send="always")
    _as_agent(monkeypatch)
    monkeypatch.setattr(outbox, "WAITING_MAX", 2)
    for _ in range(2):
        code_, out, _err = _cli(capsys, "write", "--reply", "3", "--send", stdin="Thanks!", monkeypatch=monkeypatch)
        assert code_ == 0 and "waits for the owner's OK" in out
    code_, out, err = _cli(capsys, "write", "--reply", "3", "--send", stdin="Thanks!", monkeypatch=monkeypatch)
    assert code_ != 0 and "already wait for the owner's OK" in out + err
    assert len(outbox.pending()) == 2 and len(box["drafts"]) == 2 and not smtp.messages


# ---- Telegram -----------------------------------------------------------------------------------------------
def test_unlinking_telegram_forgets_the_trusted_browsers(mx):
    from maxxing import twofactor
    from maxxing.telegram import gateway
    config.set_secret("device_key", "old-key")
    asyncio.run(gateway.forget())
    assert config.get_secret("device_key") != "old-key"
    assert not twofactor.device_trusted("anything")


# ---- update -------------------------------------------------------------------------------------------------
def test_the_update_installs_the_commit_that_was_checked(code, monkeypatch, capsys):  # noqa: F811
    """origin/<branch> moves between the signature check and the merge (another fetch ran): the commit that was
    checked is installed, not the newer one nobody verified."""
    clone, work = code["clone"], code["work"]
    _upstream_release(work, "1.1.0")
    checked = []

    def verify(target):
        checked.append(target)
        _upstream_release(work, "6.6.6", extra="unsigned.txt")
        _git("fetch", "-q", "origin", cwd=clone)
        return True, "signed"

    config.update_config(update_verify_signature=True)
    monkeypatch.setattr(cmd_core, "verify_target", verify)
    assert run_cli("update") == 0, capsys.readouterr().out
    assert len(checked) == 1 and _head(clone) == checked[0] and not (clone / "unsigned.txt").exists()
    assert '"1.1.0"' in (clone / "server/maxxing/__init__.py").read_text()


# ---- Git ----------------------------------------------------------------------------------------------------
def test_the_changes_view_never_shows_the_credentials_of_a_remote(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    for args in (["init", "-q"], ["remote", "add", "origin", "https://x-access-token:ghp_SECRETsecret1234@github.com/o/r.git"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    assert codediff.repo_head(repo)["remote"] == "https://github.com/o/r.git"


def test_a_review_is_pinned_to_the_commit_that_was_read(monkeypatch):
    sent = []
    monkeypatch.setattr(gitview, "_gh_send", lambda full, path, body, *a, **k: sent.append(body) or {"id": 1, "state": "APPROVED"})
    gitview.pull_review("o/r", 5, "APPROVE", sha="a" * 40)
    gitview.pull_review("o/r", 5, "APPROVE")
    gitview.pull_review("o/r", 5, "APPROVE", sha="not a sha")
    assert sent[0]["commit_id"] == "a" * 40 and "commit_id" not in sent[1] and "commit_id" not in sent[2]


# ---- Infra --------------------------------------------------------------------------------------------------
def test_what_a_remote_server_prints_is_read_up_to_a_cap():
    t0 = time.time()
    r = infra._run_capped([sys.executable, "-c", "import sys\nwhile True: sys.stdout.write('x' * 65536)"], "", 30, cap=1 << 20)
    assert len(r.stdout) <= 1 << 20 and r.returncode != 0 and time.time() - t0 < 20
    r = infra._run_capped([sys.executable, "-c", "import sys; print(sys.stdin.read().upper()); sys.stderr.write('e')"], "ok", 30)
    assert (r.returncode, r.stdout.strip(), r.stderr) == (0, "OK", "e")
    with pytest.raises(subprocess.TimeoutExpired):
        infra._run_capped([sys.executable, "-c", "import time; time.sleep(30)"], "", 0.5)


# ---- Keys and MCP -------------------------------------------------------------------------------------------
def test_names_that_make_programs_run_code_are_reserved():
    for name in ("CLAUDE_CODE_SHELL_PREFIX", "SSH_ASKPASS", "PERL5OPT", "JAVA_TOOL_OPTIONS", "PAGER", "LESSOPEN", "PIP_INDEX_URL"):
        assert vault.is_reserved(name), name
    for name in ("ANTHROPIC_API_KEY", "STRIPE_KEY", "SSH_DEPLOY_KEY", "UV_PUBLISH_TOKEN"):
        assert not vault.is_reserved(name), name


def test_an_mcp_server_never_exposes_a_mailbox_password_by_naming_it(mx):
    vault.put("MAIL_ACC1_PASSWORD", value="imap-secret", expose=False)
    vault.put("BROWSER_EXIT_E1", value="proxy-secret", expose=False)
    vault.put("NOTION_KEY", value="notion-secret", expose=False)
    cfg = {"command": "npx", "env": {"A": "${MAIL_ACC1_PASSWORD}", "B": "${BROWSER_EXIT_E1}", "C": "${NOTION_KEY}"}}
    assert mcp._expose_refs(cfg) == ["NOTION_KEY"]
    assert {r["name"] for r in vault.list_secrets() if r.get("expose")} == {"NOTION_KEY"}


def test_a_secret_written_in_the_command_stays_out_of_the_process_list():
    secret = "sk-live-4f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c"
    shown = mcp._redacted({"command": f"server --api-key={secret}", "args": ["--port", "1"]})
    assert secret not in str(shown) and shown["command"] and shown["args"] == ["--port", "1"]
    assert mcp._redacted({"command": "npx", "args": ["-y", "pkg"]})["command"] == "npx"


# ---- pictures -----------------------------------------------------------------------------------------------
def _png(w: int, h: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + chunk(b"IEND", b"")


def test_a_small_file_that_declares_huge_dimensions_is_not_a_profile_photo(mx):
    assert profile_photo.dimensions(_png(30000, 30000)) == (30000, 30000)
    with pytest.raises(ValueError, match="too_large"):
        profile_photo.save(_png(30000, 30000))
    assert profile_photo.save(_png(512, 512))
    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 9 + b"\xff\xdb\x00\x04\x00\x00" + b"\xff\xc2\x00\x11\x08\x75\x30\x75\x31" + b"\x00" * 12
    assert profile_photo.dimensions(jpeg) == (0x7531, 0x7530) and profile_photo.oversized(jpeg)
    vp8x = b"RIFF\x00\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00\x00\x00\x00\x00" + (29999).to_bytes(3, "little") + (99).to_bytes(3, "little")
    assert profile_photo.dimensions(vp8x) == (30000, 100) and profile_photo.oversized(vp8x)
    assert profile_photo.dimensions(b"\xff\xd8\xff") is None and not profile_photo.oversized(b"\xff\xd8\xff")


def test_thumbnails_are_made_under_a_memory_cap(monkeypatch, tmp_path):
    from maxxing.api import files
    seen = []
    monkeypatch.setattr(files.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(files.subprocess, "run", lambda cmd, **k: seen.append(cmd) or subprocess.CompletedProcess(cmd, 1, b"", b""))
    files._ffmpeg_thumb(tmp_path / "a.png", tmp_path / "a.webp", 320, False)
    cmd = seen[0]
    assert cmd[cmd.index("/usr/bin/prlimit") + 1] == f"--as={files.THUMB_MEM}" and cmd.index("/usr/bin/prlimit") < cmd.index("/usr/bin/ffmpeg")


# ---- installer ----------------------------------------------------------------------------------------------
def test_the_installer_closes_an_old_cache_folder_and_names_an_open_caddy_admin(tmp_path):
    from pathlib import Path
    script = (Path(__file__).resolve().parents[2] / "install.sh").read_text()
    fn = script[script.index("cache_ready() {"):script.index("cache_clear() {")]
    cache = tmp_path / "cache"
    cache.mkdir(mode=0o777)
    cache.chmod(0o777)
    r = subprocess.run(["bash", "-c", f'CACHE_DIR="{cache}"\n{fn}\ncache_ready && echo ready'], capture_output=True, text=True)
    assert r.stdout.strip() == "ready" and (cache.stat().st_mode & 0o777) == 0o700
    assert "admin API on 127.0.0.1:2019" in script
