"""Config `mcp_auto`: each turn loads only the MCP servers its session needs (maxxing/mcp_auto.py, runner, CLI)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import wait_for, wait_idle

SERVER = Path(__file__).resolve().parent.parent


def calls(mx) -> list[dict]:
    f = mx["fake_dir"] / "calls.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def flag(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


@pytest.fixture
def servers(mx, topic):
    """Claude Code's config: two user servers, one local server of the topic; one known claude.ai connector."""
    from maxxing import config, mcp_auto
    cdir = mx["tmp"] / "claude"
    cdir.mkdir()
    config.update_config(claude_dir=str(cdir))
    cwd = str(mx["ws"] / topic)
    (cdir / ".claude.json").write_text(json.dumps({
        "mcpServers": {
            "Facebook-ads": {"type": "http", "url": "https://mcp.facebook.com/ads?k=SECRETxyz"},
            "notion": {"type": "stdio", "command": "/usr/bin/npx", "args": ["-y", "@notionhq/notion-mcp-server"],
                       "env": {"NOTION_TOKEN": "${NOTION_TOKEN}"}},
            "harness-pc": {"type": "http", "url": "http://127.0.0.1:1/api/pc/mcp"},
        },
        "projects": {cwd: {"mcpServers": {"blog-db": {"type": "stdio", "command": "blog-db-mcp"}}}},
    }))
    mcp_auto.record_connectors(["claude.ai Google Drive"])
    return cwd


def _turn(client, mx, topic, text, sid=None):
    n = len(calls(mx))
    if sid is None:
        sid = client.post("/api/sessions", json={"path": topic, "message": text}).json()["id"]
    else:
        client.post(f"/api/sessions/{sid}/messages", json={"text": text})
    wait_for(lambda: len(calls(mx)) > n)
    wait_idle(client, sid)
    return sid, calls(mx)[-1]


def _loaded(argv: list[str]) -> list[str]:
    i = [k for k, a in enumerate(argv) if a == "--mcp-config"]
    out: list[str] = []
    for k in i:
        out += list(json.loads(Path(argv[k + 1]).read_text())["mcpServers"])
    return sorted(out)


# ---- pure functions ----------------------------------------------------------------------------
def test_names_in_tool_form_and_in_messages():
    from maxxing import mcp_auto
    assert mcp_auto.norm("claude.ai Google Drive") == "claude_ai_google_drive"
    assert mcp_auto.tool_server("mcp__claude_ai_Google_Drive__search") == "claude_ai_google_drive"
    assert mcp_auto.tool_server("mcp__Facebook-ads__ads_get_ad_accounts") == "facebook-ads"
    assert mcp_auto.tool_server("Bash") is None and mcp_auto.tool_server(None) is None
    names = ["Facebook-ads", "claude.ai Google Drive", "claude.ai Google Calendar", "notion", "ads-db"]
    assert mcp_auto.mentioned(names, "Look at my Facebook ads please") == {"Facebook-ads"}
    assert mcp_auto.mentioned(names, "check facebook") == {"Facebook-ads"}           # its own word
    assert mcp_auto.mentioned(names, "the file in my drive") == {"claude.ai Google Drive"}
    assert mcp_auto.mentioned(names, "something on google") == set()                 # two servers share it
    assert mcp_auto.mentioned(names, "Google Calendar tomorrow") == {"claude.ai Google Calendar"}
    assert mcp_auto.mentioned(names, "notional value, no ads") == set()               # whole words only
    assert mcp_auto.mentioned(names, "") == set()
    assert mcp_auto.resolve("google drive", names) == "claude.ai Google Drive"
    assert mcp_auto.resolve("FACEBOOK-ADS", names) == "Facebook-ads"
    assert mcp_auto.resolve("claude_ai_Google_Calendar", names) == "claude.ai Google Calendar"
    assert mcp_auto.resolve("nope", names) is None


def test_connectors_come_from_the_init_event_and_mcp_list():
    from maxxing import mcp, mcp_auto
    ev = {"type": "system", "subtype": "init", "mcp_servers": [
        {"name": "Facebook-ads", "source": "user"}, {"name": "claude.ai Brevo", "source": "claudeai"}]}
    assert mcp_auto.connectors_of_init(ev) == ["claude.ai Brevo"]
    assert mcp_auto.connectors_of_init({"type": "system"}) is None
    out = ("Checking MCP server health…\n\nclaude.ai Auberge de l'alla: https://a.example/mcp - ✔ Connected\n"
           "claude.ai Brevo: https://mcp.brevo.com/mcp - ! Needs authentication\n"
           "Facebook-ads: https://mcp.facebook.com/ads (HTTP) - ✔ Connected\n")
    assert mcp.connectors_of_list(out) == ["claude.ai Auberge de l'alla", "claude.ai Brevo"]
    assert list(mcp.parse_list(out)) == ["Facebook-ads"]


def test_one_append_system_prompt_flag_carries_both_texts():
    """Claude Code keeps only the LAST --append-system-prompt: the agents rule and the MCP hint share one."""
    from maxxing.sessions import spawn
    both = spawn.agents_args({}, "HINT")
    assert both[0] == "--append-system-prompt" and len(both) == 2
    assert both[1].startswith(spawn.FOREGROUND_AGENTS) and both[1].endswith("HINT")
    assert spawn.agents_args({"background_agents": True}, "HINT") == ["--append-system-prompt", "HINT"]
    assert spawn.agents_args({"background_agents": True}) == []


def test_usage_is_kept_60_days(mx):
    from maxxing import mcp_auto
    now = time.time()
    mcp_auto.record_used("projects/a/topics/b", {"notion", "harness-pc"}, now - 61 * 86400)
    mcp_auto.record_used("projects/a/topics/b", {"facebook-ads"}, now)
    assert set(mcp_auto.used("projects/a/topics/b", now)) == {"facebook-ads"}
    assert mcp_auto.used("projects/a/topics/other", now) == {}


# ---- turns ----------------------------------------------------------------------------------
def test_off_loads_everything_as_before(client, topic, mx, servers):
    sid, c = _turn(client, mx, topic, "Hi NOTOOL")
    assert "--strict-mcp-config" not in c["argv"]
    assert c["argv"].count("--append-system-prompt") == 1
    assert "maxxing mcp load" not in flag(c["argv"], "--append-system-prompt")
    assert c["env"]["MAXXING_SESSION"] == sid


def test_on_a_turn_gets_the_topic_servers_and_learns_what_it_used(client, topic, mx, servers):
    from maxxing import config
    config.update_config(mcp_auto=True)
    sid, c = _turn(client, mx, topic, "Hi NOTOOL")
    argv = c["argv"]
    assert "--strict-mcp-config" in argv and _loaded(argv) == ["blog-db"]       # the topic's own, not harness-pc
    f = Path(flag(argv, "--mcp-config"))
    assert f.stat().st_mode & 0o777 == 0o600 and f.parent.stat().st_mode & 0o777 == 0o700
    assert "SECRET" not in " ".join(argv)
    hint = flag(argv, "--append-system-prompt")
    assert argv.count("--append-system-prompt") == 1 and "run_in_background: false" in hint
    assert "Facebook-ads (http, mcp.facebook.com)" in hint and "SECRET" not in hint
    assert "notion (local program: npx @notionhq/notion-mcp-server)" in hint
    assert "claude.ai Google Drive (claude.ai connector)" in hint and "blog-db" not in hint
    assert "maxxing mcp load" in hint
    _turn(client, mx, topic, "Use it MCPUSE:Facebook-ads NOTOOL", sid)
    _, c = _turn(client, mx, topic, "Again NOTOOL", sid)
    assert _loaded(c["argv"]) == ["Facebook-ads", "blog-db"]
    assert "Facebook-ads (" not in flag(c["argv"], "--append-system-prompt")
    # another session of the same topic knows it too; the file is per session
    sid2, c2 = _turn(client, mx, topic, "Hello NOTOOL")
    assert _loaded(c2["argv"]) == ["Facebook-ads", "blog-db"] and flag(c2["argv"], "--mcp-config") != str(f)
    client.delete(f"/api/sessions/{sid2}")


def test_on_a_server_named_in_the_message_is_loaded(client, topic, mx, servers):
    from maxxing import config
    config.update_config(mcp_auto=True)
    _, c = _turn(client, mx, topic, "Let's look at the notion pages NOTOOL")
    assert _loaded(c["argv"]) == ["blog-db", "notion"]


def test_on_a_connector_needed_means_nothing_is_restricted(client, topic, mx, servers):
    from maxxing import config
    config.update_config(mcp_auto=True)
    _, c = _turn(client, mx, topic, "Find the file in my Google Drive NOTOOL")
    assert "--strict-mcp-config" not in c["argv"] and "maxxing mcp load" not in flag(c["argv"], "--append-system-prompt")


def test_maxxing_mcp_load_continues_the_turn_once(client, topic, mx, servers, monkeypatch):
    from maxxing import config
    monkeypatch.setenv("FAKE_CLAUDE_MCPLOAD", "notion")
    from maxxing.sessions import store
    config.update_config(mcp_auto=True)
    sid, _ = _turn(client, mx, topic, "Need it MCPLOAD NOTOOL")
    wait_for(lambda: len(calls(mx)) >= 2)
    wait_idle(client, sid)
    c = calls(mx)
    assert len(c) == 2, [x["prompt"] for x in c]
    assert "notion is now loaded" in c[1]["prompt"] and _loaded(c[1]["argv"]) == ["blog-db", "notion"]
    assert store.read(sid)["mcp_loaded"] == ["notion"]
    out = (mx["fake_dir"] / "mcp-load.txt").read_text()
    assert out.startswith("0 notion is loaded from the next turn")
    # asked again while already loaded: no continuation
    _turn(client, mx, topic, "MCPLOAD NOTOOL", sid)
    time.sleep(0.5)
    assert len(calls(mx)) == 3


def test_continuations_stop_after_two_in_a_row(mx, servers, topic):
    from maxxing import config, mcp_auto
    from maxxing.sessions import runner, store
    config.update_config(mcp_auto=True)
    m = store.new_meta(topic, "t")
    store.create(m)
    sid = m["id"]
    r = runner.Runner(sid)
    plan = mcp_auto.Plan(["--strict-mcp-config"], "", ["blog-db"])
    for streak, expect in ((0, 1), (1, 1), (2, 0)):
        store.update(sid, mcp_loaded=[], queue=[])
        meta = store.read(sid)
        store.update(sid, mcp_loaded=["notion"])
        r._mcp_after({"text": "x", "mcp_continue": streak}, runner.Attempt(rc=0), None, config.load_config(), meta,
                     plan, False)
        q = store.read(sid)["queue"]
        assert len(q) == expect, streak
        if q:
            assert q[0]["source"] == "system" and q[0]["mcp_continue"] == streak + 1
    # nothing restricted this turn (a connector was needed): no continuation
    store.update(sid, mcp_loaded=[], queue=[])
    meta = store.read(sid)
    store.update(sid, mcp_loaded=["notion"])
    r._mcp_after({"text": "x"}, runner.Attempt(rc=0), None, config.load_config(), meta, mcp_auto.NO_PLAN, False)
    assert store.read(sid)["queue"] == []


def test_connectors_are_learnt_from_unrestricted_turns(client, topic, mx, servers):
    from maxxing import mcp_auto
    mcp_auto.record_connectors([])
    _turn(client, mx, topic, "MCPINIT NOTOOL")
    assert mcp_auto.connectors() == ["claude.ai Google Drive"]


def test_the_file_is_rewritten_only_when_it_changes(mx, servers, topic):
    from maxxing import config, mcp_auto
    config.update_config(mcp_auto=True)
    meta = {"path": topic}
    p1 = mcp_auto.plan("s1", config.load_config(), meta, servers, "hi")
    f = Path(p1.args[-1])
    before = f.stat().st_mtime_ns
    time.sleep(0.02)
    mcp_auto.plan("s1", config.load_config(), meta, servers, "hi")
    assert f.stat().st_mtime_ns == before
    mcp_auto.plan("s1", config.load_config(), meta, servers, "notion")
    assert f.stat().st_mtime_ns != before and "notion" in json.loads(f.read_text())["mcpServers"]


def test_an_unreadable_claude_config_restricts_nothing(mx, servers, topic):
    from maxxing import config, mcp_auto
    config.update_config(mcp_auto=True)
    (mx["tmp"] / "claude" / ".claude.json").write_text("{broken")
    assert mcp_auto.plan("s1", config.load_config(), {"path": topic}, servers, "hi") is mcp_auto.NO_PLAN


def test_approved_project_servers_of_parent_folders_are_kept(mx, servers, topic):
    from maxxing import config, mcp_auto
    config.update_config(mcp_auto=True)
    proj = mx["ws"] / "projects" / "acme"
    (proj / ".mcp.json").write_text(json.dumps({"mcpServers": {"shared": {"command": "x"}, "unapproved": {"command": "y"}}}))
    d = json.loads((mx["tmp"] / "claude" / ".claude.json").read_text())
    d["projects"][str(proj)] = {"enabledMcpjsonServers": ["shared"]}
    (mx["tmp"] / "claude" / ".claude.json").write_text(json.dumps(d))
    p = mcp_auto.plan("s1", config.load_config(), {"path": topic}, servers, "hi")
    assert sorted(p.loaded) == ["blog-db", "shared"]


def test_cli_load_needs_a_session_and_a_known_server(mx, servers, topic):
    from maxxing import config
    from maxxing.sessions import store
    config.update_config(mcp_auto=True)
    m = store.new_meta(topic, "t")
    store.create(m)
    env = {**os.environ, "PYTHONPATH": str(SERVER), "MAXXING_STATE": str(mx["state"])}
    env.pop("MAXXING_SESSION", None)

    def run(*args, sid=None):
        e = {**env, **({"MAXXING_SESSION": sid} if sid else {})}
        return subprocess.run([sys.executable, "-m", "maxxing", "mcp", "load", *args], env=e, capture_output=True,
                              text=True, timeout=60)
    assert run("notion").returncode == 2
    r = run("nothing-like-it", sid=m["id"])
    assert r.returncode == 1 and "Facebook-ads" in r.stderr
    assert run("google drive", sid=m["id"]).returncode == 0
    assert run("--session", m["id"], "blog-db").returncode == 0
    assert store.read(m["id"])["mcp_loaded"] == ["claude.ai Google Drive", "blog-db"]


def test_api_switch_and_removed_session_drops_its_file(client, topic, mx, servers):
    from maxxing import config
    assert client.get("/api/mcp").json()["auto"] is False
    assert client.put("/api/mcp/auto", json={"enabled": True}).json()["enabled"] is True
    assert config.load_config()["mcp_auto"] is True and client.get("/api/mcp").json()["auto"] is True
    sid, c = _turn(client, mx, topic, "Hi NOTOOL")
    f = Path(flag(c["argv"], "--mcp-config"))
    assert f.exists()
    client.delete(f"/api/sessions/{sid}")
    wait_for(lambda: not f.exists())


def test_a_too_deep_mcp_json_is_skipped_not_fatal(mx, servers, topic):
    from maxxing import config, mcp_auto
    config.update_config(mcp_auto=True)
    (Path(servers) / ".mcp.json").write_text("[" * 100_000 + "]" * 100_000)
    p = mcp_auto.plan("s1", config.load_config(), {"path": topic}, servers, "hi")
    assert p.loaded == ["blog-db"]
    assert "blog-db" in mcp_auto.known_names(servers)
    (mx["tmp"] / "claude" / ".claude.json").write_text("[" * 100_000 + "]" * 100_000)
    assert mcp_auto.known_names(servers) == ["claude.ai Google Drive"]


def test_a_server_name_with_a_lone_surrogate_still_writes_the_plan(mx, servers, topic):
    from maxxing import config, mcp_auto
    config.update_config(mcp_auto=True)
    f = mx["tmp"] / "claude" / ".claude.json"
    d = json.loads(f.read_text())
    d["projects"][servers]["mcpServers"]["db\ud800"] = {"command": "x"}
    f.write_text(json.dumps(d))
    p = mcp_auto.plan("s1", config.load_config(), {"path": topic}, servers, "hi")
    assert sorted(p.loaded) == ["blog-db", "db\ud800"]
    folder = Path(p.args[-1]).parent
    assert [x.name for x in folder.iterdir() if x.name.endswith(".tmp")] == []


def test_the_hint_of_left_out_servers_is_capped(mx, servers, topic):
    from maxxing import config, mcp_auto
    config.update_config(mcp_auto=True)
    f = mx["tmp"] / "claude" / ".claude.json"
    d = json.loads(f.read_text())
    d["mcpServers"].update({f"srv{i:04d}-" + "x" * 300: {"command": "x"} for i in range(4000)})
    f.write_text(json.dumps(d))
    p = mcp_auto.plan("s1", config.load_config(), {"path": topic}, servers, "hi")
    assert p is not mcp_auto.NO_PLAN and len(p.hint) < 20_000
    assert "more" in p.hint


def test_a_second_identical_plan_compiles_and_reads_nothing(mx, servers, topic, monkeypatch):
    import re
    from maxxing import config, mcp_auto
    config.update_config(mcp_auto=True)
    f = mx["tmp"] / "claude" / ".claude.json"
    d = json.loads(f.read_text())
    d["mcpServers"].update({f"tool{i}-svc": {"command": "x"} for i in range(600)})
    f.write_text(json.dumps(d))
    text = "please use tool42 svc and the blog db"
    mcp_auto.plan("s1", config.load_config(), {"path": topic}, servers, text)
    compiled, reads = [], []
    real_compile, real_read = re._compile, type(f).read_text
    monkeypatch.setattr(re, "_compile", lambda *a: compiled.append(a[0]) or real_compile(*a))
    monkeypatch.setattr(type(f), "read_text",
                        lambda self, *a, **k: (reads.append(self.name), real_read(self, *a, **k))[1])
    p = mcp_auto.plan("s1", config.load_config(), {"path": topic}, servers, text)
    assert "tool42-svc" in p.loaded
    assert reads.count(".claude.json") == 0
    assert not [c for c in compiled if isinstance(c, str) and "(?<![0-9a-z])" in c]
    d["mcpServers"]["fresh-one"] = {"command": "x"}
    f.write_text(json.dumps(d))                 # a changed file is read again
    assert "fresh-one" in mcp_auto.known_names(servers)
