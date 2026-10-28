"""Safety of Settings -> MCP (maxxing/mcp.py): OAuth pty lifetime, secret masking, malformed files, CLI argv."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time

import pytest

from _org_helpers import org, client  # noqa: F401
from test_mcp import env  # noqa: F401


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_login_reader_does_not_steal_a_reused_fd():
    """close() frees the fd number only once the reader thread is gone (else it reads the next owner's data)."""
    from maxxing import mcp
    r1, w1 = os.pipe()
    proc = subprocess.Popen(["sleep", "30"])
    lg = mcp._Login("user||x", proc, r1)
    time.sleep(0.1)
    lg.close()
    lg.close()                                   # idempotent
    assert proc.poll() is not None and not lg.reader.is_alive()
    r2, w2 = os.pipe()
    os.close(w1)
    got = b""
    for _ in range(20):
        os.write(w2, b"x" * 100)
        time.sleep(0.02)
    os.close(w2)
    while chunk := os.read(r2, 65536):
        got += chunk
    os.close(r2)
    assert len(got) == 2000
    with pytest.raises(mcp.McpError) as e:
        lg.write(b"late\r")
    assert e.value.code == "login_expired"


def test_login_start_does_not_leak_pty_master(env):  # noqa: F811
    from maxxing import mcp
    before = _open_fds()
    for _ in range(20):
        with pytest.raises(mcp.McpError) as e:
            mcp.login_start(f"local|{env.tmp}/gone|ads", wait=1)
        assert e.value.code == "folder_missing"
    assert _open_fds() - before < 5


def test_login_start_closes_master_when_popen_fails(env, monkeypatch):  # noqa: F811
    from maxxing import mcp
    mcp.add("ads", {"type": "http", "url": "https://ads.example.com/mcp"}, None)
    sid = mcp.servers()[0]["id"]

    def boom(*a, **k):
        raise PermissionError("denied")
    monkeypatch.setattr(mcp.subprocess, "Popen", boom)
    before = _open_fds()
    for _ in range(10):
        with pytest.raises(mcp.McpError):
            mcp.login_start(sid, wait=1)
    assert _open_fds() - before < 3


def test_cancel_during_finish_does_not_close_someone_elses_fd(env):  # noqa: F811
    from maxxing import mcp
    r1, w1 = os.pipe()
    proc = subprocess.Popen(["sleep", "30"])
    lg = mcp._Login("user||ads", proc, w1)
    mcp._logins["k"] = lg
    out = {}

    def finish():
        try:
            out["res"] = mcp.login_finish("k", "http://localhost:1/callback?code=z", wait=5)
        except Exception as e:                   # noqa: BLE001
            out["err"] = e
    t = threading.Thread(target=finish)
    t.start()
    time.sleep(0.5)
    mcp.login_cancel("k")
    r2, w2 = os.pipe()
    t.join()
    os.close(r1)
    os.fstat(r2)
    os.fstat(w2)
    os.close(r2)
    os.close(w2)
    assert isinstance(out.get("err"), mcp.McpError) and out["err"].code == "login_expired"
    with pytest.raises(mcp.McpError) as e:       # a second Finish after that: 404, not an OSError
        mcp.login_finish("k", "http://localhost:1/callback?code=z")
    assert e.value.code == "login_expired"


def test_second_finish_while_finishing_is_refused(env):  # noqa: F811
    from maxxing import mcp
    r1, w1 = os.pipe()
    lg = mcp._Login("user||ads", subprocess.Popen(["sleep", "30"]), w1)
    mcp._logins["k"] = lg
    t = threading.Thread(target=lambda: pytest.raises(mcp.McpError, mcp.login_finish, "k",
                                                      "http://localhost:1/callback?code=z", 2))
    t.start()
    time.sleep(0.3)
    with pytest.raises(mcp.McpError) as e:
        mcp.login_finish("k", "http://localhost:1/callback?code=z")
    assert e.value.code == "busy"
    t.join()
    os.close(r1)


@pytest.mark.parametrize("value", [
    "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",      # AWS-style secret ('/', runs < 20)
    "Basic dXNlcjpwYXNzd29yZA==",                   # HTTP Basic user:password
    "correcthorsebatterystaple",                     # letters only
    "s3cr3t-Pa55!",                                  # short
    "Bearer ${KEY}x9",                               # a reference plus a literal
])
def test_literal_secrets_are_masked_and_blanked(env, value):  # noqa: F811
    from maxxing import mcp
    mcp.add("s", {"type": "stdio", "command": "srv", "env": {"AWS_SECRET_ACCESS_KEY": value}}, None)
    mcp.add("h", {"type": "http", "url": "https://h.example.com/mcp", "headers": {"Authorization": value}}, None)
    rows = {s["name"]: s for s in mcp.servers()}
    assert rows["s"]["env"]["AWS_SECRET_ACCESS_KEY"] == "•••" and rows["s"]["literal_secret"]
    assert rows["h"]["headers"]["Authorization"] == "•••" and rows["h"]["literal_secret"]
    exp = {e["name"]: e["config"] for e in mcp.export()}
    assert exp["s"]["env"] == {"AWS_SECRET_ACCESS_KEY": ""} and exp["h"]["headers"] == {"Authorization": ""}
    assert value not in json.dumps(mcp.export()) + json.dumps(mcp.servers())


def test_references_and_plain_headers_stay_visible(env):  # noqa: F811
    from maxxing import mcp
    headers = {"Authorization": "Bearer ${ACME}", "X-Pair": "${U}:${P}", "Content-Type": "application/json"}
    mcp.add("h", {"type": "http", "url": "https://h.example.com/mcp?key=${ACME}", "headers": headers}, None)
    mcp.add("s", {"type": "stdio", "command": "srv", "env": {"TOKEN": "${ACME}", "EMPTY": ""}}, None)
    rows = {s["name"]: s for s in mcp.servers()}
    assert rows["h"]["headers"] == headers and rows["h"]["url"] == "https://h.example.com/mcp?key=${ACME}"
    assert rows["s"]["env"] == {"TOKEN": "${ACME}", "EMPTY": ""}
    assert not rows["h"]["literal_secret"] and not rows["s"]["literal_secret"]
    assert {e["name"]: e["config"] for e in mcp.export()}["h"]["headers"] == headers


def test_url_userinfo_and_query_values_are_masked(env):  # noqa: F811
    from maxxing import mcp
    mcp.add("u", {"type": "http", "url": "https://bob:hunter2pass@mcp.example.com/mcp?api_key=letmein&x=${K}"}, None)
    row = mcp.servers()[0]
    assert row["url"] == "https://•••@mcp.example.com/mcp?api_key=•••&x=${K}" and row["literal_secret"]
    assert mcp.export()[0]["config"]["url"] == "https://mcp.example.com/mcp?api_key=&x=${K}"
    assert "hunter2pass" not in json.dumps(mcp.servers()) + json.dumps(mcp.export())
    assert "letmein" not in json.dumps(mcp.servers()) + json.dumps(mcp.export())


@pytest.mark.parametrize("content", ['{"mcpServers": "x"}', '{"mcpServers": ["a"]}', '["a"]',
                                     '{"mcpServers": {"a": {"headers": ["x"], "env": "y", "args": "z"}}}'])
def test_malformed_mcp_json_does_not_crash_the_page(env, client, content):  # noqa: F811
    from maxxing import mcp
    (env.ws / "projects/acme/.mcp.json").write_text(content)
    assert client.get("/api/mcp").status_code == 200
    mcp.check(wait=True)


def test_malformed_claude_json_does_not_crash_the_page(env, client):  # noqa: F811
    from maxxing import mcp
    (env.tmp / "claude" / ".claude.json").write_text(
        '{"mcpServers": ["a"], "projects": {"/x": {"mcpServers": "x", "enabledMcpjsonServers": 3}}}')
    assert client.get("/api/mcp").status_code == 200
    assert mcp.export() == []
    mcp.check(wait=True)
    assert not mcp._check["running"]


def test_names_are_never_cli_options(env, monkeypatch):  # noqa: F811
    from maxxing import mcp
    for bad in ("-h", "--help", "a\n", ""):
        with pytest.raises(mcp.McpError) as e:
            mcp.add(bad, {"type": "http", "url": "https://a.example.com/mcp"}, None)
        assert e.value.code == "bad_name"
    with pytest.raises(mcp.McpError):
        mcp.parse_id("user||ads\n")
    seen = []
    real_run, real_popen = subprocess.run, subprocess.Popen
    monkeypatch.setattr(mcp.subprocess, "run", lambda a, **k: (seen.append(a), real_run(a, **k))[1])
    monkeypatch.setattr(mcp.subprocess, "Popen", lambda a, **k: (seen.append(a), real_popen(a, **k))[1])
    mcp.add("ads", {"type": "http", "url": "https://a.example.com/mcp"}, None)
    sid = mcp.servers()[0]["id"]
    mcp.login_cancel(mcp.login_start(sid, wait=10)["login"])
    mcp.remove(sid)
    for verb in ("add-json", "login", "remove"):
        argv = next(a for a in seen if verb in a)
        assert argv.index("--") == argv.index("ads") - 1, argv


def test_write_cfg_temp_file_never_world_readable(env, monkeypatch):  # noqa: F811
    from maxxing import mcp
    p = env.tmp / "claude" / ".claude.json"
    p.write_text(json.dumps({"projects": {str(env.ws / "projects/old"): {"mcpServers": {"a": {}}}}}))
    modes, names = [], []
    real = os.replace

    def spy(src, dst):
        modes.append(os.stat(src).st_mode & 0o777)
        names.append(str(src))
        return real(src, dst)
    monkeypatch.setattr(mcp.os, "replace", spy)
    old = os.umask(0o022)
    try:
        mcp.on_workspace_change({"action": "renamed", "old_path": "projects/old", "path": "projects/new"})
    finally:
        os.umask(old)
    assert modes == [0o600] and names[0] != str(p) + ".mx-tmp"
    assert str(env.ws / "projects/new") in json.loads(p.read_text())["projects"]
    assert [f.name for f in p.parent.iterdir()] == [".claude.json"]


def test_abandoned_login_is_reaped_by_the_listing_and_the_timer(env, monkeypatch):  # noqa: F811
    from maxxing import mcp
    mcp.add("ads", {"type": "http", "url": "https://ads.example.com/mcp"}, None)
    mcp.add("crm", {"type": "http", "url": "https://crm.example.com/mcp"}, None)
    ads, crm = (s["id"] for s in mcp.servers())
    lg = mcp._logins[mcp.login_start(ads, wait=10)["login"]]
    lg.started -= mcp.LOGIN_TTL + 1
    mcp.overview()
    assert lg.proc.poll() is not None and not mcp._logins
    monkeypatch.setattr(mcp, "GC_EVERY", 0.1)
    while mcp._reaper["thread"] is not None:     # the reaper of the first login stops once nothing is left
        time.sleep(0.05)
    lg = mcp._logins[mcp.login_start(crm, wait=10)["login"]]
    lg.started -= mcp.LOGIN_TTL + 1
    deadline = time.time() + 5
    while lg.proc.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    assert lg.proc.poll() is not None, "expired login still running"


def test_second_login_for_the_same_server_replaces_the_first(env):  # noqa: F811
    from maxxing import mcp
    mcp.add("ads", {"type": "http", "url": "https://ads.example.com/mcp"}, None)
    sid = mcp.servers()[0]["id"]
    first = mcp.login_start(sid, wait=10)
    lg1 = mcp._logins[first["login"]]
    second = mcp.login_start(sid, wait=10)
    assert list(mcp._logins) == [second["login"]] and lg1.proc.poll() is not None
    with pytest.raises(mcp.McpError) as e:
        mcp.login_finish(first["login"], "http://localhost:4321/callback?code=abc")
    assert e.value.code == "login_expired"
    assert mcp.login_finish(second["login"], "http://localhost:4321/callback?code=abc", wait=10)["ok"]


def test_plain_settings_survive_the_backup(env):  # noqa: F811
    """A plain setting written in clear (LOG_LEVEL=debug) is masked in the list but kept in the backup, so a restore
    gives a working server; a secret-named one is blanked even when it does not look like a token."""
    from maxxing import mcp
    mcp.add("p", {"type": "stdio", "command": "srv", "env": {"LOG_LEVEL": "debug", "DB_PASSWORD": "hunter"}}, None)
    row = {s["name"]: s for s in mcp.servers()}["p"]
    assert row["env"] == {"LOG_LEVEL": "•••", "DB_PASSWORD": "•••"}
    assert {e["name"]: e["config"] for e in mcp.export()}["p"]["env"] == {"LOG_LEVEL": "debug", "DB_PASSWORD": ""}


def test_project_server_id_outside_the_workspace_is_refused(env, client):  # noqa: F811
    """A project server id names the folder whose .mcp.json is rewritten: a workspace folder only."""
    other = env.tmp / "elsewhere"
    other.mkdir()
    body = '{"mcpServers": {"victim": {"type": "http", "url": "https://x.example/mcp"}}}'
    (other / ".mcp.json").write_text(body)
    for sid in (f"project|{other}|victim", "project||victim", "project|elsewhere|victim",
                f"project|{env.ws}/../elsewhere|victim"):
        r = client.delete("/api/mcp", params={"id": sid})
        assert r.status_code == 400, sid
    assert (other / ".mcp.json").read_text() == body
    inside = env.ws / "projects" / "acme"
    (inside / ".mcp.json").write_text(body)
    assert client.delete("/api/mcp", params={"id": f"project|{inside}|victim"}).status_code == 200
    assert "victim" not in (inside / ".mcp.json").read_text()


def test_write_cfg_waits_for_claude_codes_lock(env):  # noqa: F811
    """Claude Code holds `.claude.json.lock` while it rewrites the file: a rename of a folder waits for it and
    re-reads, so both the key Claude wrote and the renamed folder are kept."""
    from maxxing import mcp
    p = env.tmp / "claude" / ".claude.json"
    p.write_text(json.dumps({"projects": {str(env.ws / "projects/old"): {"mcpServers": {"a": {}}}}}))
    lock = p.with_name(".claude.json.lock")
    lock.mkdir()
    stale = json.loads(p.read_text())                # Claude Code read the file before taking its time
    t = threading.Thread(target=mcp.on_workspace_change,
                         args=({"action": "renamed", "old_path": "projects/old", "path": "projects/new"},))
    t.start()
    time.sleep(0.3)
    p.write_text(json.dumps({**stale, "numStartups": 7}))
    lock.rmdir()
    t.join(5)
    d = json.loads(p.read_text())
    assert d.get("numStartups") == 7 and str(env.ws / "projects/new") in d["projects"]
    assert not lock.exists()


def test_write_cfg_keeps_a_symlinked_claude_json(env):  # noqa: F811
    from maxxing import mcp
    p = env.tmp / "claude" / ".claude.json"
    real = env.tmp / "dotfiles" / "claude.json"
    real.parent.mkdir()
    real.write_text(json.dumps({"projects": {str(env.ws / "projects/old"): {"mcpServers": {"a": {}}}}}))
    p.symlink_to(real)
    mcp.on_workspace_change({"action": "renamed", "old_path": "projects/old", "path": "projects/new"})
    assert p.is_symlink()
    assert str(env.ws / "projects/new") in json.loads(real.read_text())["projects"]
    assert [f.name for f in real.parent.iterdir()] == ["claude.json"]


def test_reference_pattern_is_linear_on_unclosed_defaults(env):  # noqa: F811
    """"${A:-" repeated without "}" made REF_RE quadratic (100 kB froze the whole API for 33 s)."""
    from maxxing import mcp
    v = "${A:-" * 6000                               # 30 kB: about 3 s before the fix
    t = time.monotonic()
    mcp._only_refs(v), mcp._has_literal(v), mcp._refs({"env": {"X": v}})
    assert time.monotonic() - t < 0.5
    assert mcp._refs({"env": {"X": "${KEY:-dflt}", "Y": "Bearer ${TOK}"}}) == {"KEY", "TOK"}


def test_cfg_lock_gives_up_on_a_stale_lock_it_cannot_remove(tmp_path, monkeypatch):
    """A `.claude.json.lock` that is a file (or a full folder) cannot be taken over: wait, then write anyway."""
    from maxxing import mcp
    target = tmp_path / ".claude.json"
    lock = tmp_path / ".claude.json.lock"
    lock.write_text("x")
    os.utime(lock, (1, 1))                                   # stale
    monkeypatch.setattr(mcp, "CFG_LOCK_WAIT", 0.3)
    got = []
    t = threading.Thread(target=lambda: got.append(mcp._cfg_lock(target)), daemon=True)
    t.start()
    t.join(3)
    assert not t.is_alive() and got == [None]


def test_userinfo_pattern_is_linear_on_a_long_run_of_letters(env, client):  # noqa: F811
    """A long argument of letters with no "://" was quadratic (40 000 letters: 1.8 s); a huge value is refused."""
    from maxxing import mcp
    t = time.monotonic()
    assert not mcp._has_userinfo("a" * 200_000)
    assert time.monotonic() - t < 0.5
    assert mcp._has_userinfo("x postgres://user:pw@host")
    r = client.post("/api/mcp", json={"name": "big", "where": "", "type": "stdio", "command": "srv",
                                      "args": ["a" * 100_000]})
    assert r.status_code == 400 and "too_long" in r.text


def test_removing_a_project_server_never_empties_the_mcp_json(env, client):  # noqa: F811
    """Another server of the file holds a lone surrogate: the rewrite used to truncate the file, then fail."""
    f = env.ws / "projects" / "acme" / ".mcp.json"
    f.write_text('{"mcpServers": {"gone": {"type": "http", "url": "https://x.example/mcp"},'
                 ' "kept": {"type": "stdio", "command": "srv", "env": {"A": "\\ud800"}}}}')
    r = client.delete("/api/mcp", params={"id": f"project|{f.parent}|gone"})
    assert r.status_code == 200
    data = json.loads(f.read_text())
    assert list(data["mcpServers"]) == ["kept"] and data["mcpServers"]["kept"]["env"]["A"] == "\ud800"
    assert [p.name for p in f.parent.iterdir() if "mx-tmp" in p.name] == []


def test_a_project_server_named_by_hand_can_be_removed(env, client):  # noqa: F811
    f = env.ws / "projects" / "acme" / ".mcp.json"
    f.write_text('{"mcpServers": {"my server é": {"type": "http", "url": "https://x.example/mcp"}}}')
    from maxxing import mcp
    sid = {s["name"]: s["id"] for s in mcp.servers()}["my server é"]
    assert client.delete("/api/mcp", params={"id": sid}).status_code == 200
    assert json.loads(f.read_text())["mcpServers"] == {}
    for bad in ("-x", "a\x00b", "a\nb"):
        assert client.delete("/api/mcp", params={"id": f"project|{f.parent}|{bad}"}).status_code == 400


def test_a_fifo_or_huge_mcp_json_does_not_block_the_list(env):  # noqa: F811
    from maxxing import mcp
    os.mkfifo(env.ws / "projects" / "acme" / ".mcp.json")
    big = env.ws / "projects" / "acme" / "topics" / "blog" / ".mcp.json"
    big.write_text('{"mcpServers": {}, "x": "' + "a" * (2 << 20) + '"}')
    out: list = []
    t = threading.Thread(target=lambda: out.append(mcp.servers()), daemon=True)
    t.start()
    t.join(5)
    assert out and not [s for s in out[0] if s["scope"] == "project"]
