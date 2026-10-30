"""MCP servers (maxxing/mcp.py + /api/mcp + `maxxing mcp`), driven against the fake claude CLI."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from _org_helpers import org, client  # noqa: F401

FAKE = Path(__file__).resolve().parent / "fake_claude.py"


@pytest.fixture
def env(org, monkeypatch):  # noqa: F811
    from maxxing import config, mcp
    cdir = org.tmp / "claude"
    cdir.mkdir()
    monkeypatch.setenv("MAXXING_CLAUDE_BIN", str(FAKE))
    monkeypatch.setenv("FAKE_CLAUDE_DIR", str(org.tmp / "fake"))
    config.update_config(claude_dir=str(cdir))
    (org.ws / "projects" / "acme" / "topics" / "blog").mkdir(parents=True)
    mcp._status.clear()
    mcp._check.update(running=False, at=None)
    yield org
    for k in list(mcp._logins):
        mcp.login_cancel(k)


def _cfg(org):
    return json.loads((org.tmp / "claude" / ".claude.json").read_text())


def test_add_list_check_remove(env):
    from maxxing import mcp, vault
    vault.put("ACME_TOKEN", "x" * 30, expose=False)
    res = mcp.add("acme", {"type": "http", "url": "https://mcp.example.com/mcp",
                           "headers": {"Authorization": "Bearer ${ACME_TOKEN}"}}, None)
    assert res["exposed"] == ["ACME_TOKEN"]
    assert [r["expose"] for r in vault.list_secrets() if r["name"] == "ACME_TOKEN"] == [True]
    mcp.add("ads", {"type": "http", "url": "https://ads.example.com/mcp"}, "projects/acme/topics/blog")
    mcp.add("files", {"type": "stdio", "command": "npx -y files-mcp"}, "projects/acme/topics/blog")
    d = _cfg(env)
    assert d["mcpServers"]["acme"]["headers"]["Authorization"] == "Bearer ${ACME_TOKEN}"
    blog = str(env.ws / "projects/acme/topics/blog")
    assert d["projects"][blog]["mcpServers"]["files"] == {"type": "stdio", "command": "npx", "args": ["-y", "files-mcp"]}
    mcp.check(wait=True)
    rows = {s["name"]: s for s in mcp.servers()}
    assert rows["acme"]["state"] == "connected" and rows["acme"]["where"]["rel"] is None
    assert rows["acme"]["headers"] == {"Authorization": "Bearer ${ACME_TOKEN}"} and rows["acme"]["keys"] == ["ACME_TOKEN"]
    assert rows["ads"]["state"] == "needs_auth"
    assert rows["ads"]["where"] == {**rows["ads"]["where"], "rel": "projects/acme/topics/blog",
                                    "project": "acme", "topic": "blog"}
    assert rows["files"]["state"] == "connected"
    with pytest.raises(mcp.McpError) as e:
        mcp.add("acme", {"url": "https://mcp.example.com/x"}, None)
    assert e.value.code == "exists"
    mcp.remove(rows["ads"]["id"])
    assert "ads" not in _cfg(env)["projects"][blog]["mcpServers"]


def test_validation(env):
    from maxxing import mcp
    for name, spec, where, code in [("bad name", {"url": "https://a.example.com"}, None, "bad_name"),
                                    ("a", {"url": "ftp://a"}, None, "bad_url"),
                                    ("a", {"type": "stdio"}, None, "bad_command"),
                                    ("a", {"command": "npx 'x"}, None, "bad_command"),
                                    ("a", {"command": "npx", "args": 'a "b'}, None, "bad_command"),
                                    ("a", {"url": "https://a.example.com"}, "../etc", "bad_where"),
                                    ("a", {"url": "https://a.example.com"}, "projects/nope", "folder_missing")]:
        with pytest.raises(mcp.McpError) as e:
            mcp.add(name, spec, where)
        assert e.value.code == code


def test_failed_add_hides_the_keys_it_exposed(env, monkeypatch):
    from maxxing import mcp, vault
    vault.put("K1", "x" * 30, expose=False)

    def fail(*a, **k):
        raise mcp.McpError(400, "cli_failed", "boom")
    monkeypatch.setattr(mcp, "_cli", fail)
    with pytest.raises(mcp.McpError):
        mcp.add("acme", {"url": "https://mcp.example.com/mcp", "headers": {"Authorization": "Bearer ${K1}"}}, None)
    assert [r["expose"] for r in vault.list_secrets() if r["name"] == "K1"] == [False]


def test_literal_secret_masked_and_blanked_in_backup(env):
    from maxxing import mcp
    mcp.add("raw", {"url": "https://raw.example.com/mcp", "headers": {"X-Key": "abcd1234efgh5678ijkl9012"}}, None)
    row = next(s for s in mcp.servers() if s["name"] == "raw")
    assert row["literal_secret"] and "abcd1234" not in json.dumps(row)
    exp = mcp.export()
    assert exp == [{"name": "raw", "where": None, "config": {"type": "http", "url": "https://raw.example.com/mcp",
                                                            "headers": {"X-Key": ""}}}]


def test_restore_adds_missing(env):
    from maxxing import mcp
    items = [{"name": "a", "where": None, "config": {"type": "http", "url": "https://a.example.com/mcp"}},
             {"name": "b", "where": "projects/acme/topics/blog", "config": {"type": "stdio", "command": "x", "args": []}},
             {"name": "c", "where": "projects/gone", "config": {"type": "stdio", "command": "x", "args": []}}]
    assert mcp.restore(items) == 2
    assert mcp.restore(items) == 0
    assert {s["name"] for s in mcp.servers()} == {"a", "b"}


@pytest.mark.parametrize("bad", ["abc", ["x"], 5, None])
def test_restore_skips_a_config_that_is_not_an_object(env, bad):
    """An edited or corrupted backup: the bad item is skipped, the next ones are still restored."""
    from maxxing import mcp
    items = [{"name": "bad", "where": None, "config": bad},
             {"name": "a", "where": None, "config": {"type": "http", "url": "https://a.example.com/mcp"}}]
    assert mcp.restore(items) == 1
    assert {s["name"] for s in mcp.servers()} == {"a"}


def test_rename_moves_servers(env):
    from maxxing import mcp
    mcp.add("ads", {"type": "stdio", "command": "x"}, "projects/acme/topics/blog")
    old = env.ws / "projects/acme/topics/blog"
    new = env.ws / "projects/acme/topics/news"
    old.rename(new)
    mcp.on_workspace_change({"action": "renamed", "kind": "topic", "path": "projects/acme/topics/news",
                             "old_path": "projects/acme/topics/blog"})
    d = _cfg(env)
    assert str(old) not in d["projects"] and "ads" in d["projects"][str(new)]["mcpServers"]


def test_remove_in_deleted_folder(env):
    from maxxing import mcp
    mcp.add("ads", {"type": "stdio", "command": "x"}, "projects/acme/topics/blog")
    sid = next(s["id"] for s in mcp.servers() if s["name"] == "ads")
    (env.ws / "projects/acme/topics/blog").rmdir()
    mcp.check(wait=True)
    assert next(s for s in mcp.servers() if s["name"] == "ads")["state"] == "failed"
    mcp.remove(sid)
    assert not mcp.servers()


def test_project_mcp_json(env):
    from maxxing import mcp
    f = env.ws / "projects/acme/.mcp.json"
    f.write_text(json.dumps({"mcpServers": {"shared": {"type": "http", "url": "https://s.example.com/mcp"}}}))
    row = next(s for s in mcp.servers() if s["name"] == "shared")
    assert row["scope"] == "project" and row["where"]["rel"] == "projects/acme"
    mcp.remove(row["id"])
    assert json.loads(f.read_text()) == {"mcpServers": {}}


def test_oauth_login(env):
    from maxxing import mcp
    mcp.add("ads", {"type": "http", "url": "https://ads.example.com/mcp"}, None)
    sid = mcp.servers()[0]["id"]
    st = mcp.login_start(sid, wait=10)
    assert st["url"].startswith("https://auth.example.com/oauth/authorize")
    with pytest.raises(mcp.McpError) as e:
        mcp.login_finish(st["login"], "not a url")
    assert e.value.code == "bad_redirect"
    res = mcp.login_finish(st["login"], "http://localhost:4321/callback?code=abc&state=x", wait=10)
    assert res["ok"]
    mcp.check(wait=True)
    assert mcp.servers()[0]["state"] == "connected"
    st = mcp.login_start(sid, wait=10)
    with pytest.raises(mcp.McpError) as e:
        mcp.login_finish(st["login"], "http://localhost:4321/callback?error=denied", wait=10)
    assert e.value.code == "login_failed"
    with pytest.raises(mcp.McpError) as e:
        mcp.login_finish(st["login"], "http://localhost:4321/callback?code=1")
    assert e.value.code == "login_expired"


def test_api(env, client):  # noqa: F811
    r = client.post("/api/mcp", json={"name": "ads", "where": "projects/acme/topics/blog",
                                      "type": "http", "url": "https://ads.example.com/mcp"})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    r = client.post("/api/mcp", json={"name": "ads", "where": "projects/acme/topics/blog",
                                      "url": "https://ads.example.com/mcp"})
    assert r.status_code == 409 and r.json()["error"] == "exists"
    from maxxing import mcp
    mcp.check(wait=True)
    body = client.get("/api/mcp").json()
    assert [s["state"] for s in body["servers"]] == ["needs_auth"]
    r = client.post("/api/mcp/login", json={"id": sid})
    assert r.status_code == 200 and r.json()["url"].startswith("https://")
    r = client.post(f"/api/mcp/login/{r.json()['login']}", json={"redirect": "http://localhost:1/callback?code=z"})
    assert r.status_code == 200, r.text
    assert client.delete("/api/mcp", params={"id": sid}).status_code == 200
    assert client.get("/api/mcp").json()["servers"] == []
    assert client.delete("/api/mcp/login/nope").status_code == 200


def test_backup_snapshot_and_restore_include_mcp(env, monkeypatch):
    from maxxing import backup, mcp
    mcp.add("a", {"type": "http", "url": "https://a.example.com/mcp"}, None)
    files = backup.snapshot()
    assert json.loads(files["_maxxing/mcp.json"])[0]["name"] == "a"


def test_cli(env, capsys):
    from maxxing import cli, commands  # noqa: F401
    assert cli.main(["mcp", "add", "ads", "https://ads.example.com/mcp", "--where", "projects/acme/topics/blog"]) == 0
    assert cli.main(["mcp", "add", "loc", "--command", "npx -y loc", "--env", "A=${B}"]) == 0
    capsys.readouterr()
    assert cli.main(["mcp", "list"]) == 0
    out = capsys.readouterr().out
    assert "needs_auth" in out and "projects/acme/topics/blog" in out and "every session" in out
    assert cli.main(["mcp", "remove", "ads"]) == 1
    assert cli.main(["mcp", "remove", "ads", "--where", "projects/acme/topics/blog"]) == 0


def test_parse_list_marks_of_every_version():
    from maxxing import mcp
    out = ("Checking MCP server health…\n\n"
           "a: https://a.example.com/ (HTTP) - ✔ Connected\n"
           "b: https://b.example.com/mcp (HTTP) - ✓ Connected\n"
           "c: https://c.example.com/mcp (HTTP) - ! Needs authentication\n"
           "d: npx -y d - x - ✘ Failed to connect\n"
           "e: https://e.example.com (SSE) - ⏸ Pending approval\n"
           "f: https://f.example.com - ? Needs authentication\n")
    got = {k: v["state"] for k, v in mcp.parse_list(out).items()}
    assert got == {"a": "connected", "b": "connected", "c": "needs_auth", "d": "failed", "e": "pending", "f": "needs_auth"}


def test_claude_json_is_parsed_once_while_unchanged(env, monkeypatch):
    """The MCP page re-reads ~/.claude.json on each refresh: an unchanged (often multi-MB) file is not parsed again."""
    from maxxing import mcp
    p = env.tmp / "claude" / ".claude.json"
    p.write_text(json.dumps({"mcpServers": {"a": {"type": "http", "url": "https://a.example.com/mcp"}},
                             "projects": {f"/p{i}": {"history": ["x" * 50]} for i in range(200)}}))
    calls = []
    real = json.loads
    monkeypatch.setattr(mcp.json, "loads", lambda s, *a, **k: (calls.append(1) if '"mcpServers"' in s else None) or real(s, *a, **k))
    assert [s["name"] for s in mcp.servers()] == ["a"]
    assert [s["name"] for s in mcp.servers()] == ["a"]
    assert len(calls) == 1
    p.write_text(json.dumps({"mcpServers": {"b": {"type": "http", "url": "https://b.example.com/mcp"}}}))
    assert [s["name"] for s in mcp.servers()] == ["b"]
    assert len(calls) == 2


def test_short_or_flag_secrets_masked_in_the_list():
    from maxxing import mcp
    cfg = {"command": "npx", "args": ["-y", "pkg", "--api-key=abcdefghijklmnopqrstuvwxyz", "--token=ab12cd",
                                      "Authorization: Bearer shorttok9", "--token", "shortone", "-H", "X-Api-Key: abc",
                                      "-H", "Content-Type: application/json", "--no-auth", "/srv", "--port=8080",
                                      "--key=${KEY}"],
           "url": "https://h.example.com/mcp/abcdefghijklmnopqrstuvwxyz"}
    pub = mcp._public(cfg)
    shown = json.dumps(pub)
    for secret in ("abcdefghij", "ab12cd", "shorttok9", "shortone", "X-Api-Key: abc"):
        assert secret not in shown
    assert pub["args"][:2] == ["-y", "pkg"]
    assert pub["args"][-5:] == ["Content-Type: application/json", "--no-auth", "/srv", "--port=8080", "--key=${KEY}"]
    assert pub["literal_secret"] and pub["url"] == mcp.MASK
    assert mcp._public({"url": "https://h.example.com/v1/mcp/server-filesystem"})["url"].endswith("server-filesystem")


def test_backup_export_blanks_logins_and_flag_secrets(env):
    from maxxing import mcp
    mcp.add("db", {"type": "stdio", "command": "npx", "args": ["-y", "pg-mcp", "--token=ab12cd", "--port=8080",
                                                               "postgres://u:hunter2@h/x"],
                   "env": {"DATABASE_URL": "postgres://u:hunter2@db/x", "LOG": "debug", "REF": "pg://${U}:${P}@h"}},
            None)
    exp = json.dumps(mcp.export())
    assert "hunter2" not in exp and "ab12cd" not in exp
    cfg = mcp.export()[0]["config"]
    assert cfg["args"] == ["-y", "pg-mcp", "", "--port=8080", ""]
    assert cfg["env"] == {"DATABASE_URL": "", "LOG": "debug", "REF": "pg://${U}:${P}@h"}


def test_literal_secrets_stay_out_of_the_cli_arguments(env, monkeypatch):
    from maxxing import mcp
    seen, cli = [], mcp._cli
    monkeypatch.setattr(mcp, "_cli", lambda args, folder, **kw: (seen.append(args), cli(args, folder, **kw))[1])
    mcp.add("api", {"url": "https://api.example.com/mcp", "headers": {"Authorization": "Bearer sk-live-SECRET123456789"}},
            None)
    mcp.add("db", {"type": "stdio", "command": "x", "args": ["--token=ab12cd"], "env": {"PW": "hunter2"}},
            "projects/acme/topics/blog")
    mcp.restore([{"name": "r", "where": None, "config": {"type": "http", "url": "https://r.example.com/mcp",
                                                       "headers": {"X-Key": "restoredsecret"}}}])
    argv = json.dumps(seen)
    for secret in ("SECRET123", "ab12cd", "hunter2", "restoredsecret"):
        assert secret not in argv
    d = _cfg(env)
    blog = str(env.ws / "projects/acme/topics/blog")
    assert d["mcpServers"]["api"]["headers"]["Authorization"] == "Bearer sk-live-SECRET123456789"
    assert d["mcpServers"]["r"]["headers"] == {"X-Key": "restoredsecret"}
    assert d["projects"][blog]["mcpServers"]["db"] == {"type": "stdio", "command": "x", "args": ["--token=ab12cd"],
                                                       "env": {"PW": "hunter2"}}


def test_add_with_secrets_is_undone_when_the_config_cannot_be_completed(env, monkeypatch):
    from maxxing import mcp
    monkeypatch.setattr(mcp, "_write_cfg", lambda fn: None)    # the entry is not found where the CLI put it
    with pytest.raises(mcp.McpError) as e:
        mcp.add("api", {"url": "https://api.example.com/mcp", "headers": {"Authorization": "Bearer sk-live-SECRET1234"}},
                None)
    assert e.value.code == "not_saved"
    assert "api" not in _cfg(env).get("mcpServers", {})


def test_pc_mcp_registered_reads_no_project_file(env, monkeypatch):
    """The PC card polls mcp_registered() every 3-15 s: it must not read every project's .mcp.json."""
    from maxxing import mcp, pcbridge
    mcp.add(pcbridge.MCP_NAME, {"type": "http", "url": "https://pc.example.com/mcp"}, None)
    (env.ws / "projects" / "acme" / ".mcp.json").write_text(json.dumps({"mcpServers": {"x": {"command": "x"}}}))
    import threading
    reads = []
    real = mcp._read_mcp_json
    me = threading.get_ident()                   # add() may start a background check that lists every server
    monkeypatch.setattr(mcp, "_read_mcp_json",
                        lambda f: (threading.get_ident() == me and reads.append(f)) or real(f))
    assert pcbridge.mcp_registered() is True
    assert reads == []
    mcp.remove(mcp._id("user", None, pcbridge.MCP_NAME))
    assert pcbridge.mcp_registered() is False
    assert any(s["name"] == "x" for s in mcp.servers()) and reads
