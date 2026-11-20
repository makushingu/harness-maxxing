"""Harness Browser (maxxing/browser): rules, proxy and exits, profiles and who uses which, tabs, ask_human, turn
tokens, runner flags, API, CLI, the live view's pace.

No real Chromium here: the parts that start one (unit.py, live.py) are tried by hand on a real server.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import threading
from pathlib import Path

import pytest

from conftest import wait_for, wait_idle

A = "projects/acme/topics/blog/agents/writer"
T = "projects/acme/topics/blog"
MCP = Path(__file__).resolve().parents[1] / "maxxing" / "browser_mcp.py"


# ---- rules ---------------------------------------------------------------------------------------------------------
def test_pages_that_can_never_be_opened():
    from maxxing.browser import rules
    for url in ("file:///etc/passwd", "chrome://settings", "view-source:https://example.com", "javascript:alert(1)",
                "devtools://devtools/x", "http://localhost:8787/", "http://127.0.0.1/", "http://[::1]/",
                "http://192.168.1.1/", "http://router.local/", "http://10.0.0.5.nip.io/", "http:/example.com",
                "http:\\\\127.0.0.1", "http://93.184.216.34/"):
        assert rules.page_refusal(url, None), url
    for url in ("https://example.com/a?b=1", "about:blank", "data:text/html,hi", None):
        assert rules.page_refusal(url, None) is None, url


def test_a_list_of_domains_allows_only_its_sites_and_their_subdomains():
    from maxxing.browser import rules
    sites = [rules.clean_site(x) for x in ["Example.com", "https://shop.acme.io/path", "*.blog.dev"]]
    assert sites == ["example.com", "shop.acme.io", "blog.dev"]
    assert [rules.clean_site(x) for x in ["co.uk", "bad site", "x"]] == [None, None, None]
    assert rules.page_refusal("https://www.example.com/", sites) is None
    assert rules.page_refusal("https://a.blog.dev/", sites) is None
    assert "not one of this agent's domains" in rules.page_refusal("https://example.org/", sites)
    assert "not one of this agent's domains" in rules.page_refusal("https://example.com.evil.io/", sites)
    assert rules.page_refusal("https://example.org/") is None              # no list: any public site
    assert rules.page_refusal("http://192.168.1.1/") and rules.page_refusal("file:///etc/passwd")


def test_devtools_commands_that_are_refused():
    from maxxing.browser import relay, rules
    for cmd in ({"id": 1, "method": "Browser.setDownloadBehavior", "params": {"behavior": "allow"}},
                {"id": 2, "method": "DOM.setFileInputFiles", "params": {"files": ["/etc/passwd"]}},
                {"id": 3, "method": "Storage.getCookies"},
                {"id": 4, "method": "Page.navigate", "params": {"url": "file:///etc/shadow"}},
                {"id": 5, "method": "Target.createTarget", "params": {"url": "http://127.0.0.1:8787/"}},
                {"id": 6, "method": "Extensions.loadUnpacked", "params": {"path": "/tmp"}},
                {"id": 7, "method": "Input.dispatchDragEvent", "params": {"data": {"files": ["/x"]}}}):
        fwd, err = relay.filter_command(json.dumps(cmd), None)
        assert fwd is None and json.loads(err)["id"] == cmd["id"], cmd
    fwd, err = relay.filter_command(json.dumps({"id": 8, "method": "Page.navigate",
                                                "params": {"url": "https://example.org/"}}), ["example.com"])
    assert fwd is None and "not one of this agent's domains" in json.loads(err)["error"]["message"]
    ok = json.dumps({"id": 9, "method": "Runtime.evaluate", "params": {"expression": "1+1"}, "sessionId": "S"})
    assert relay.filter_command(ok, None) == (ok, None)
    assert rules.check_command("x" * (2 << 20))[0] == "command too large"


def test_the_policy_blocks_local_pages_and_downloads():
    from maxxing.browser import rules
    p = rules.policy(downloads=False)
    assert "file://*" in p["URLBlocklist"] and "*" not in p["URLBlocklist"] and "URLAllowlist" not in p
    assert p["DownloadRestrictions"] == 3 and rules.policy(downloads=True)["DownloadRestrictions"] == 0


# ---- proxy ---------------------------------------------------------------------------------------------------------
def test_the_proxy_refuses_local_answers_and_raw_addresses(tmp_path, monkeypatch):
    from maxxing.browser.proxy import Proxy

    async def go():
        px = Proxy(tmp_path / "p.sock")
        loop = asyncio.get_running_loop()
        answers = {"public.test": "93.184.216.34", "rebind.test": "127.0.0.1", "lan.test": "192.168.0.4"}

        async def fake(host, port, **kw):
            if host not in answers:
                raise OSError("no such host")
            return [(2, 1, 6, "", (answers[host], port))]
        monkeypatch.setattr(loop, "getaddrinfo", fake)
        assert await px.check("public.test", 443) == ["93.184.216.34"]
        for h in ("rebind.test", "lan.test", "localhost", "127.0.0.1", "[::1]", "x.localhost", "nowhere.test"):
            assert await px.check(h, 443) is None, h
    asyncio.run(go())


def test_the_proxy_tries_ipv4_first_then_the_next_address(tmp_path, monkeypatch):
    """A site with an IPv6 address first (Wikipedia) opened through a phone exit with no IPv6 way out: IPv4 is tried
    first, and an address that fails gives way to the next one instead of failing the page."""
    from maxxing.browser import exits
    from maxxing.browser.proxy import Proxy

    async def go():
        px = Proxy(tmp_path / "p.sock")
        loop = asyncio.get_running_loop()

        async def fake(host, port, **kw):
            return [(10, 1, 6, "", ("2a02:ec80::1", port, 0, 0)), (2, 1, 6, "", ("185.15.59.224", port)),
                    (2, 1, 6, "", ("185.15.59.225", port))]
        monkeypatch.setattr(loop, "getaddrinfo", fake)
        assert await px.check("wiki.test", 443) == ["185.15.59.224", "185.15.59.225", "2a02:ec80::1"]

        async def echo(r, w):
            w.write(b"hello from the second address")
            await w.drain()
            w.close()
        srv = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        tried = []
        real = exits.open_via

        async def open_via(up, ip, p, timeout=15.0):
            tried.append(ip)
            if ip != "127.0.0.1":
                raise OSError("the SOCKS proxy could not connect (code 1)")
            return await real(up, ip, p, timeout)
        monkeypatch.setattr(exits, "open_via", open_via)

        async def check(host, p):
            return ["192.0.2.1", "127.0.0.1"]
        px.check = check
        await px.start()
        try:
            r, w = await asyncio.open_unix_connection(str(tmp_path / "p.sock"))
            w.write(f"CONNECT wiki.test:{port} HTTP/1.1\r\nHost: wiki.test\r\n\r\n".encode())
            await w.drain()
            data = b""
            while b"second address" not in data:
                chunk = await asyncio.wait_for(r.read(200), 5)
                assert chunk, data
                data += chunk
            assert data.startswith(b"HTTP/1.1 200") and tried == ["192.0.2.1", "127.0.0.1"]
            w.close()
        finally:
            await px.stop()
            srv.close()
    asyncio.run(go())


def test_the_proxy_forwards_to_the_checked_address_only(tmp_path):
    """End to end on a unix socket: a CONNECT to an allowed name reaches it, a local name gets 403."""
    from maxxing.browser.proxy import Proxy

    async def go():
        async def echo(r, w):
            w.write(b"hello from upstream")
            await w.drain()
            w.close()
        up = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = up.sockets[0].getsockname()[1]
        px = Proxy(tmp_path / "p.sock")

        async def check(host, p):
            return ["127.0.0.1"] if host == "allowed.test" else None
        px.check = check
        await px.start()
        try:
            r, w = await asyncio.open_unix_connection(str(tmp_path / "p.sock"))
            w.write(f"CONNECT allowed.test:{port} HTTP/1.1\r\nHost: allowed.test\r\n\r\n".encode())
            await w.drain()
            data = b""
            while b"hello from upstream" not in data:
                chunk = await asyncio.wait_for(r.read(200), 5)
                assert chunk, data
                data += chunk
            assert data.startswith(b"HTTP/1.1 200")
            w.close()
            r, w = await asyncio.open_unix_connection(str(tmp_path / "p.sock"))
            w.write(b"GET http://localhost/ HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await w.drain()
            data = await asyncio.wait_for(r.read(500), 5)
            assert data.startswith(b"HTTP/1.1 403") and px.blocked[-1][1] == "localhost"
            w.close()
        finally:
            await px.stop()
            up.close()
    asyncio.run(go())


# ---- ask_human (browser_mcp.py + browser/asks.py) -------------------------------------------------------------------
class Mcp:
    def __init__(self, folder: Path, url: str = "http://127.0.0.1:9/none", wait: float = 60, session: str = "sess01"):
        env = {**os.environ, "MAXXING_BROWSER_ASKS": str(folder), "MAXXING_SESSION": session,
               "MAXXING_BROWSER_OWNER": f"agent:{A}", "MAXXING_BROWSER_WAIT": str(wait),
               "MAXXING_BROWSER_URL": url, "MAXXING_BROWSER_TOKEN": "t"}
        self.p = subprocess.Popen([sys.executable, "-I", str(MCP)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, env=env)

    def send(self, msg: dict) -> None:
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def recv(self) -> dict:
        return json.loads(self.p.stdout.readline())

    def close(self) -> int:
        self.p.stdin.close()
        return self.p.wait(timeout=10)


def _files(folder: Path) -> list[dict]:
    return [json.loads(f.read_text()) for f in sorted(folder.glob("*.json"))]


def test_mcp_lists_ask_human_even_when_the_server_is_away(tmp_path):
    m = Mcp(tmp_path)
    m.send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert m.recv()["result"]["serverInfo"]["name"] == "maxxing-browser"
    m.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert [t["name"] for t in m.recv()["result"]["tools"]] == ["ask_human"]
    m.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "click", "arguments": {}}})
    r = m.recv()["result"]
    assert r["isError"] and "did not answer" in r["content"][0]["text"]
    assert m.close() == 0


def test_ask_human_waits_for_the_person(tmp_path, mx, monkeypatch):
    from maxxing import browser
    from maxxing.browser import asks
    folder = browser.asks_dir()
    folder.mkdir(parents=True)
    m = Mcp(folder)
    m.send({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "ask_human", "arguments": {"reason": "Solve the captcha", "what": "captcha"}}})
    req = wait_for(lambda: _files(folder))[0]
    assert req["status"] == "pending" and req["what"] == "captcha" and req["owner"] == f"agent:{A}"
    assert asks.pending(owner=f"agent:{A}") and asks.pending(session="sess01")[0]["reason"] == "Solve the captcha"
    asks.decide(req["id"], "done", note="signed in")
    text = m.recv()["result"]["content"][0]["text"]
    assert "handed the browser back" in text and "signed in" in text
    with pytest.raises(asks.AskError) as e:
        asks.decide(req["id"], "skip")
    assert e.value.status == 409
    m.send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "ask_human", "arguments": {"reason": "Type the code"}}})
    wait_for(lambda: len(asks.pending()) == 1)
    assert m.close() == 0                           # Claude Code gone: what waited expires
    assert all(d["status"] != "pending" for d in _files(folder)) and not asks.pending()


def test_ask_human_times_out(tmp_path, mx, monkeypatch):
    from maxxing import browser_mcp
    monkeypatch.setattr(browser_mcp, "POLL_S", 0.05)
    monkeypatch.setattr(browser_mcp, "MIN_WAIT_S", 0.3)
    monkeypatch.setenv("MAXXING_BROWSER_WAIT", "0.3")
    text = browser_mcp.ask("Sign in", "sign_in", tmp_path)
    assert "Nobody answered" in text and _files(tmp_path)[0]["status"] == "timeout"


def test_a_request_is_announced_once_and_resolved(client, topic, mx):
    from maxxing import browser, feed
    from maxxing.browser import asks
    _agent(client)
    folder = browser.asks_dir()
    folder.mkdir(parents=True, exist_ok=True)
    rid = "0123456789abcdef"
    (folder / f"{rid}.json").write_text(json.dumps({"id": rid, "session": "nosuchsession", "owner": f"agent:{A}",
                                                    "reason": "Solve the captcha", "what": "captcha",
                                                    "at": time.time(), "expires": time.time() + 600,
                                                    "status": "pending"}))
    assert asks.scan() is True and asks.scan() is False
    evs = [e for e in feed.list_events()["events"] if e.get("ref") == f"human:{rid}"]
    assert len(evs) == 1 and [a["id"] for a in evs[0]["actions"]] == ["open", "skip"]
    assert evs[0]["url"] == "/settings/browser?session=nosuchsession"
    feed.act(evs[0]["id"], "skip", by="web")
    assert json.loads((folder / f"{rid}.json").read_text())["status"] == "skip"
    ev = feed.get(evs[0]["id"])
    assert ev["resolved"] and ev["resolution"] == "Skipped"


def test_a_request_of_a_turn_that_is_gone_expires(mx):
    from maxxing import browser
    from maxxing.browser import asks
    folder = browser.asks_dir()
    folder.mkdir(parents=True, exist_ok=True)
    rid = "fedcba9876543210"
    (folder / f"{rid}.json").write_text(json.dumps({"id": rid, "session": "gone01", "owner": f"topic:{T}",
                                                    "reason": "x", "at": time.time() - 60,
                                                    "expires": time.time() + 600, "status": "pending"}))
    asks.scan()
    assert json.loads((folder / f"{rid}.json").read_text())["status"] == "expired"


# ---- settings, owners, turns ---------------------------------------------------------------------------------------
def _agent(client, **extra) -> None:
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    r = client.post("/api/agents", json={"topic_path": T, "name": "writer", **extra})
    assert r.status_code == 200, r.text


def test_an_owner_is_off_until_turned_on(client, topic, mx):
    from maxxing import browser
    _agent(client)
    assert browser.active_for(A) is None and browser.active_for(T) is None
    r = client.put("/api/browser/owner", json={"path": A, "enabled": True})
    assert r.status_code == 200, r.text
    # turned on, an agent uses its project's profile: made at its first use, with main's exit
    assert r.json()["own"] == {"enabled": True} and r.json()["profile"] == "" and r.json()["project"] == "projects/acme"
    assert browser.active_for(A) is None                 # the feature is off
    assert client.put("/api/settings", json={"browser_feature": True}).status_code == 200
    assert client.get("/api/settings").json()["browser_feature"] is True
    owner, prof, s = browser.active_for(A)
    assert owner == f"agent:{A}" and prof["id"] == "acme" and prof["project"] == "projects/acme" and "sites" not in prof
    assert client.get("/api/browser/owner", params={"path": A}).json()["from"]["profile"] == "project:projects/acme"
    assert client.delete("/api/browser/profiles/acme").status_code == 409     # a project's stays: forget it instead
    assert client.get(f"/api/agents/acme/blog/writer").json()["browser"]["enabled"] is True
    r = client.put("/api/browser/settings", json={"idle_min": 45})
    assert r.status_code == 200 and r.json()["settings"]["idle_min"] == 45
    assert client.put("/api/browser/profiles/acme", json={"name": "Acme"}).status_code == 200
    # a project turns it on for all its topics; the agent's switch is its own
    r = client.put("/api/browser/owner", json={"path": "projects/acme", "enabled": True})
    assert r.status_code == 200 and r.json()["kind"] == "project"
    assert browser.active_for(T)[1]["name"] == "Acme"
    assert json.loads((mx["ws"] / "projects/acme/.maxxing.json").read_text())["browser"] == {"enabled": True}
    assert client.get("/api/browser/owner", params={"path": T}).json()["from"]["enabled"] == "project:projects/acme"
    assert client.get("/api/browser/owner", params={"path": "projects"}).status_code == 400
    assert client.get("/api/browser/owner", params={"path": "projects/acme/topics/nope"}).status_code == 404
    st = client.get("/api/browser").json()
    assert st["feature"] is True and st["settings"]["idle_min"] == 45
    assert [p["id"] for p in st["profiles"]] == ["main", "acme"] and st["profiles"][0]["state"] == "stopped"
    assert st["profiles"][1]["agents"] == 1
    v = client.get("/api/browser/profiles/acme").json()
    assert [n["id"] for n in v["agents"]] == [f"agent:{A}"] and v["temporary"] == []
    # a topic or a project never picks a profile: its sessions use the project's
    assert client.put("/api/browser/owner", json={"path": T, "profile": "main"}).status_code == 400
    assert client.get("/api/browser/profiles/main").json()["browser"]["tabs"] == []
    assert client.get("/api/browser/profiles/nope").status_code == 404
    assert client.post("/api/browser/profiles/main/tabs/nope/show").status_code == 404


def test_the_mcp_route_needs_the_turn_token(client, mx):
    from maxxing.browser import turns
    assert client.post("/api/browser/mcp/sess01", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 403
    tok = turns.write_turn("sess01", f"topic:{T}")
    r = client.post("/api/browser/mcp/sess01", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Authorization": "Bearer nope"})
    assert r.status_code == 403
    # TestClient's peer is "testclient", not loopback: the route also checks that
    r = client.post("/api/browser/mcp/sess01", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    assert turns.check_turn("sess01", tok) and not turns.check_turn("sess01", tok + "x")
    turns.end_turn("sess01")
    assert turns.read_turn("sess01") is None


def test_the_tools_offered_never_name_a_server_file():
    from maxxing.browser import cdm
    tools = cdm.offered(cdm.shipped_tools())
    names = {t["name"] for t in tools}
    assert "navigate_page" in names and "click" in names and not names & cdm.BLOCKED_TOOLS
    for t in tools:
        assert not set((t.get("inputSchema") or {}).get("properties") or {}) & set(cdm.SERVER_FILE_ARGS), t["name"]
    nav = next(t for t in tools if t["name"] == "navigate_page")
    assert nav["description"].startswith(cdm.WHEN)


def test_a_turn_gets_the_browser_only_when_it_is_on(client, topic, mx):
    from maxxing.sessions import runner
    _agent(client)
    agent: dict = {"args": ["--allowedTools", "Read"]}
    assert runner.browser_args("sess01", A, agent) == []
    client.put("/api/settings", json={"browser_feature": True})
    client.put("/api/browser/owner", json={"path": A, "enabled": True})
    args = runner.browser_args("sess01", A, agent)
    assert args[0] == "--mcp-config" and agent["args"] == ["--allowedTools", "Read,mcp__maxxing-browser"]
    spec = json.loads(Path(args[1]).read_text())["mcpServers"]["maxxing-browser"]
    assert oct(Path(args[1]).stat().st_mode & 0o777) == "0o600"
    assert spec["env"]["MAXXING_BROWSER_OWNER"] == f"agent:{A}" and spec["env"]["MAXXING_BROWSER_URL"].endswith(
        "/api/browser/mcp/sess01")
    assert spec["env"]["MAXXING_BROWSER_PROFILE"] == "acme"            # its project's profile
    forced = {"args": [], "approvals_forced": True}
    assert "--allowedTools" not in runner.browser_args("sess02", A, forced)
    assert runner.browser_args("sess03", T, {})[0] == "--mcp-config"   # its topic says nothing: on
    client.put("/api/browser/owner", json={"path": T, "enabled": False})
    assert runner.browser_args("sess04", T, {}) == []                    # turned off
    client.put("/api/browser/owner", json={"path": A, "inherit": ["enabled"]})
    assert runner.browser_args("sess05", A, {}) == []                    # an agent that says nothing: off
    runner.browser_done("sess01")
    assert not Path(args[1]).exists()


def test_a_session_turn_lists_the_browser_tools(client, topic, mx):
    client.put("/api/settings", json={"browser_feature": True})
    client.put("/api/browser/owner", json={"path": T, "enabled": True})
    sid = client.post("/api/sessions", json={"path": T, "message": "NOTOOL hi"}).json()["id"]
    wait_idle(client, sid)
    calls = [json.loads(ln) for ln in (mx["fake_dir"] / "calls.jsonl").read_text().splitlines()]
    argv = calls[-1]["argv"]
    assert "--mcp-config" in argv and any("browser" in a for a in argv if a.endswith(".mcp.json"))
    from maxxing.browser import turns
    assert turns.read_turn(sid) is None                 # removed at the end of the turn


def test_the_owners_conversation_gets_the_browser_like_its_runs(client, topic, mx):
    """The manager turn (the owner's conversation, in the agent's sandbox) has the browser tools when its agent has
    the browser on: pre-allowed, never denied by the sandbox settings."""
    from maxxing import agents
    from maxxing.sessions import store
    from test_agent_guard import _settings
    _agent(client, sandbox=True)
    client.put("/api/settings", json={"browser_feature": True})
    client.put("/api/browser/owner", json={"path": A, "enabled": True})
    r = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL hi"})
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["id"]
    wait_idle(client, sid)
    assert agents.manager_turn(store.read(sid))
    calls = [json.loads(ln) for ln in (mx["fake_dir"] / "calls.jsonl").read_text().splitlines()]
    argv = calls[-1]["argv"]
    assert any(a.endswith(f"{sid}.mcp.json") for a in argv)
    allowed = ",".join(argv[i + 1] for i, a in enumerate(argv) if a == "--allowedTools")
    assert "mcp__maxxing-browser" in allowed
    deny = _settings(argv)["permissions"]["deny"]
    assert not [d for d in deny if "mcp__" in d]
    assert "Harness Browser" in argv[argv.index("--append-system-prompt") + 1]


def test_the_manager_asks_for_its_browser_and_turns_it_off_at_once(client, topic, mx):
    """`maxxing agents set <itself> browser.enabled=true` in the owner's conversation: more power, an approval card;
    off: safer, applied without asking."""
    from maxxing import agents, approvals
    _agent(client, sandbox=True)
    r = agents.request_change(A, {"browser": {"enabled": True}}, session="sess-mgr1")
    assert r["applied"] == [] and r["asked"] == ["browser"]
    assert not agents.load(A)["browser"].get("enabled")
    assert "browser: off -> on" in approvals.get(r["request"])["input"]["description"]
    approvals.decide(r["request"], "allow")
    assert agents.load(A)["browser"]["enabled"] is True
    r = agents.request_change(A, {"browser": {"enabled": False}}, session="sess-mgr1")
    assert r["applied"] == ["browser"] and r["asked"] == []
    assert not agents.load(A)["browser"].get("enabled")


def test_an_agent_turn_cannot_change_its_browser(monkeypatch):
    from maxxing import agent_guard
    monkeypatch.setattr(agent_guard, "agent_turn", lambda: {"path": A, "tampered": False})
    assert "not allowed" in agent_guard.check_cli(["browser", "set", A, "on"])
    assert agent_guard.check_cli(["browser", "status"]) is None
    assert "not allowed" in agent_guard.check_cli(["browser", "enable"])


def test_cli_enable_installs_first_then_switches(mx, monkeypatch, capsys):
    from maxxing import browser, cli
    from maxxing.browser import unit
    ran = []
    monkeypatch.setattr(unit, "available", lambda fresh=False: {"ok": bool(ran), "missing": [] if ran else ["socat"]})
    monkeypatch.setattr(unit, "setup", lambda log: ran.append(1) or ["installed socat"])
    assert cli.main(["browser", "enable"]) == 0 and ran and browser.feature_on()
    assert cli.main(["browser", "disable"]) == 0 and not browser.feature_on()
    monkeypatch.setattr(unit, "setup", lambda log: [])                   # nothing could be installed
    ran.clear()
    assert cli.main(["browser", "enable"]) == 1 and not browser.feature_on()


def test_cli_set_show(mx, capsys):
    from maxxing import browser, cli
    (mx["ws"] / T).mkdir(parents=True)
    assert cli.main(["browser", "set", "acme/blog", "on"]) == 0
    assert browser.own_block(f"topic:{T}") == {"enabled": True}
    assert cli.main(["browser", "profile", "add", "Shop", "--fallback-vps"]) == 0
    assert browser.profile("shop")["on_exit_down"] == "vps"
    assert cli.main(["browser", "set", "acme", "inherit", "--profile", "shop"]) == 1   # only an agent chooses
    assert browser.resolve(T)["profile"] == ""                                       # its project's, not made yet
    assert browser.active_for(T) is None                                             # the feature is off
    assert cli.main(["browser", "settings", "--tab-sleep", "30"]) == 0 and browser.settings()["tab_sleep_min"] == 30
    assert cli.main(["browser", "show", "acme/blog", "--json"]) == 0
    assert cli.main(["browser", "set", "acme/blog", "off"]) == 0
    assert browser.own_block(f"topic:{T}")["enabled"] is False
    assert cli.main(["browser", "settings", "--max-tabs", "99"]) == 1          # out of range
    assert cli.main(["browser", "profile", "rm", "main"]) == 1                 # main stays
    assert cli.main(["browser", "profile", "rm", "shop"]) == 0 and browser.profile("shop") is None
    with pytest.raises(SystemExit):
        cli.main(["browser", "set", "acme/nope", "on"])


def test_a_page_blocked_by_the_list_is_explained():
    from maxxing.browser import pool
    res = {"content": [{"type": "text", "text": "Error: net::ERR_BLOCKED_BY_ADMINISTRATOR at https://a.example.org/"}]}
    out = pool._explain(res)
    assert out["content"][-1]["text"] == pool.BLOCKED_HINT and len(res["content"]) == 1
    ok = {"content": [{"type": "text", "text": "Successfully navigated"}]}
    assert pool._explain(ok) is ok


def _browser(pid="main"):
    from maxxing import browser
    from maxxing.browser import pool as pool_mod
    from maxxing.browser.tabs import Tabs
    p = pool_mod.Pool()
    b = pool_mod.Browser(browser.profile(pid) or {"id": pid}, p.tabs(pid))
    p.browsers[pid] = b
    return p, b


def test_claude_is_told_what_the_person_did_in_a_tab_of_its_own(mx):
    from maxxing.browser import navs, pool as pool_mod
    p, b = _browser()
    t = pool_mod.Turn("s1", f"topic:{T}")
    b.tabs.claim(t.by)
    b.tabs.resolve({"targetId": "t1", "type": "page", "url": "about:blank"})       # the turn's tab
    b.tabs.resolve({"targetId": "t2", "type": "page", "url": "about:blank"})       # the person's own tab
    assert b.tabs.nav_of("t1") == "session:s1" and b.tabs.nav_of("t2") == navs.ME
    p._moved(b, "t1", "https://shop.example.com/login?token=secret", "Sign in")  # nobody took over: not a person's move
    assert b.trail == {}
    b.control = {t.nav: {"tab": "t1", "vid": 1, "at": time.time()}}
    p._moved(b, "t1", "https://shop.example.com/login?token=secret", "")
    p._moved(b, "t1", "https://shop.example.com/login?token=secret", "Sign in")    # its title came later: same entry
    p._moved(b, "t1", "https://shop.example.com/account", "My account")
    assert [x["url"] for x in b.trail["t1"]] == ["https://shop.example.com/login", "https://shop.example.com/account"]
    b.control = {navs.ME: {"tab": "t2", "vid": 1, "at": time.time()}}
    p._moved(b, "t2", "https://bank.example.com/", "My bank")                      # a tab of the person only: never told
    assert "t2" not in b.trail
    t.told_at = 0
    told = pool_mod.trail_text(p._untold(b, t))
    assert told == "https://shop.example.com/login (Sign in) -> https://shop.example.com/account (My account)"
    assert p._untold(b, t) == []                    # told once
    other = pool_mod.Turn("s2", "topic:projects/acme/topics/shop")
    other.told_at = 0
    assert p._untold(b, other) == []                # another session's browser: not told to it
    assert p._tabs_note(b, t) == []                 # the person is busy in their own browser, not in this one
    b.control[t.nav] = {"tab": "t1", "vid": 1, "at": time.time()}
    assert "The person is using the tab" in p._tabs_note(b, t)[0]["text"]

def test_a_hand_back_gives_the_pages_and_a_picture(tmp_path, mx, monkeypatch):
    from maxxing import browser_mcp
    d = {"status": "done", "note": "code typed", "page": {"url": "https://shop.example.com/account", "title": "My account"},
         "trail": [{"url": "https://shop.example.com/login", "title": "Sign in", "at": 1}], "picture": "aGVsbG8="}
    text = browser_mcp.answer(d)
    assert "went to: https://shop.example.com/login (Sign in)" in text
    assert "The page now: https://shop.example.com/account (My account)" in text and "code typed" in text
    monkeypatch.setattr(browser_mcp, "wait", lambda *a, **k: d)
    content = browser_mcp.ask_content("Sign in", "sign_in")
    assert content[1] == {"type": "image", "data": "aGVsbG8=", "mimeType": "image/jpeg"}
    monkeypatch.setattr(browser_mcp, "wait", lambda *a, **k: {"status": "skip"})
    assert [c["type"] for c in browser_mcp.ask_content("Sign in", "sign_in")] == ["text"]


def test_an_agent_waiting_in_its_browser_waits_for_the_user(client, topic, mx, monkeypatch):
    from maxxing import agents
    from maxxing.browser import asks
    _agent(client)
    monkeypatch.setattr(agents, "_metas", lambda path: [{"id": "sess01", "state": "running"}])
    assert agents.status(A)["waiting"] == 0
    monkeypatch.setitem(asks._counts, "sess01", 1)
    assert agents.status(A)["waiting"] == 1


def test_decide_keeps_only_the_hand_back_fields(mx):
    from maxxing import browser
    from maxxing.browser import asks
    folder = browser.asks_dir()
    folder.mkdir(parents=True, exist_ok=True)
    rid = "00112233445566aa"
    (folder / f"{rid}.json").write_text(json.dumps({"id": rid, "session": "s1", "owner": f"topic:{T}", "reason": "x",
                                                    "at": time.time(), "expires": time.time() + 60, "status": "pending"}))
    out = asks.decide(rid, "done", extra={"trail": [], "page": {"url": "https://a.example"}, "picture": "eA==",
                                          "status": "skip", "owner": "agent:other"})
    saved = json.loads((folder / f"{rid}.json").read_text())
    assert saved["status"] == "done" and saved["owner"] == f"topic:{T}" and saved["picture"] == "eA=="
    assert "picture" not in out and asks.get(rid)["status"] == "done"


def test_a_sandboxed_agent_browses_only_its_domains(client, topic, mx):
    from maxxing import agents, browser
    _agent(client)
    assert browser.agent_sites(f"agent:{A}") is None                          # free: any public site
    assert browser.agent_sites(f"topic:{T}") is None and browser.agent_sites("session:x") is None
    a = agents.load(A)
    agents._save(A, {**a, "sandbox": True, "domains": ["api.github.com", "*.Example.com", "not a site"]})
    assert browser.agent_sites(f"agent:{A}") == ["api.github.com", "example.com"]
    client.put("/api/settings", json={"browser_feature": True})
    assert client.put("/api/browser/owner", json={"path": A, "enabled": True}).json()["sites"] == \
        ["api.github.com", "example.com"]
    agents._save(A, {**a, "sandbox": True, "domains": []})
    assert browser.agent_sites(f"agent:{A}") == []                            # no domain: no page


def test_the_sites_of_a_turn_are_fixed_when_it_starts(client, topic, mx):
    """A sandboxed run: its domains, written in its turn file (no agent read per page); the owner's conversation
    (not sandboxed) and sessions: any public site."""
    from maxxing import agents
    from maxxing.browser import turns
    from maxxing.sessions import runner
    _agent(client)
    client.put("/api/settings", json={"browser_feature": True})
    client.put("/api/browser/owner", json={"path": A, "enabled": True})
    agents._save(A, {**agents.load(A), "sandbox": True, "domains": ["example.com"]})
    runner.browser_args("run0001", A, {"args": [], "sandbox": True})
    runner.browser_args("chat0001", A, {"args": [], "sandbox": False, "manager": True})
    assert turns.sites_of(turns.read_turn("run0001")) == ["example.com"]
    assert turns.sites_of(turns.read_turn("chat0001")) is None
    agents._save(A, {**agents.load(A), "domains": ["example.com", "example.org"]})
    assert turns.sites_of(turns.read_turn("run0001")) == ["example.com"]        # the next run gets the new list
    assert turns.sites_of({"owner": f"agent:{A}", "token": "x"}) == ["example.com", "example.org"]   # a file of before


def test_a_run_stopped_at_another_site_offers_to_add_it(client, topic, mx):
    from maxxing import agents, feed
    from maxxing.browser import domains, rules
    _agent(client)
    agents._save(A, {**agents.load(A), "sandbox": True, "domains": ["example.com"]})
    assert rules.off_domains("https://accounts.example.org/login", ["example.com"]) == "accounts.example.org"
    assert rules.off_domains("https://www.example.com/", ["example.com"]) is None        # allowed
    assert rules.off_domains("http://127.0.0.1/", ["example.com"]) is None               # never: not a domain to add
    assert rules.off_domains("file:///etc/passwd", ["example.com"]) is None
    assert domains.blocked(f"session:x", "https://example.org/", None) is None            # a session: free
    assert domains.blocked(f"agent:{A}", "https://example.org/a", ["example.com"]) == "example.org"
    domains.blocked(f"agent:{A}", "https://example.org/b", ["example.com"])                # once a day
    evs = [e for e in feed.list_events(None, False, None, 50)["events"] if e.get("ref") == f"browsersite:{A}|example.org"]
    assert len(evs) == 1 and evs[0]["actions"][0]["id"] == "add" and evs[0]["agent"] == A
    done = feed.act(evs[0]["id"], "add")
    assert agents.load(A)["domains"] == ["example.com", "example.org"]
    assert done["resolution"] == "example.org added" and done["actions"] == []


def test_a_tab_of_a_sandboxed_agent_that_left_its_domains_is_emptied(mx):
    from maxxing.browser import pool as pool_mod

    class W:
        pages = {"t1": {"url": "https://www.example.com/a"}, "t2": {"url": "https://evil.example.org/"}}
        went: list = []

        async def cdp_navigate(self, tid, url):
            self.went.append((tid, url))

    class Tabs:
        def awake(self, nav):
            return [{"target": "t1"}, {"target": "t2"}]

    b = type("B", (), {"watcher": W(), "tabs": Tabs(), "pid": "acme"})()
    t = type("T", (), {"nav": f"agent:{A}", "owner": f"agent:{A}"})()
    notes = asyncio.run(pool_mod.Pool()._keep_to(b, t, ["example.com"]))
    assert W.went == [("t2", "about:blank")] and len(notes) == 1 and "evil.example.org" in notes[0]


# ---- profiles and who uses which -------------------------------------------------------------------------------------
def test_settings_of_before_the_profiles_become_the_main_profile(mx):
    from maxxing import browser, config
    config.update_config(browser={"web": "list", "sites": ["example.com"], "profile": "keep", "idle_min": 40})
    s = browser.settings()
    assert s["idle_min"] == 40 and s["exits"] == []
    assert s["profiles"] == [{**browser.PROFILE_DEFAULTS, "id": "main"}]          # its old site list: dropped
    old = browser.profiles_dir() / "harness"
    old.mkdir(parents=True)
    (browser.home() / "tabs.json").write_text('{"tabs": []}')
    browser.migrate()
    assert browser.profile_dir("main").is_dir() and not old.exists()
    assert (browser.tabs_dir() / "main.json").is_file()


def test_profiles_are_added_changed_and_deleted(mx):
    from maxxing import browser
    shop = browser.set_profile({"name": "Boutique Paris", "web": "list", "sites": ["example.com"]})   # of before
    assert "web" not in shop and "sites" not in shop
    assert shop["id"] == "boutique-paris" and shop["exit"] == "direct" and shop["on_exit_down"] == "wait"
    assert browser.set_profile({"name": "Boutique Paris"})["id"] == "boutique-paris-2"
    with pytest.raises(browser.BrowserError):
        browser.set_profile({"exit": "nope"}, "boutique-paris")             # no such exit
    with pytest.raises(browser.BrowserError):
        browser.set_profile({"name": " "})
    with pytest.raises(browser.BrowserError):
        browser.delete_profile("main")
    browser.delete_profile("boutique-paris-2")
    assert [p["id"] for p in browser.profiles()] == ["main", "boutique-paris"]


def test_a_folder_uses_its_project_profile_and_an_agent_may_choose_another(mx):
    from maxxing import agents, browser, workspace
    (mx["ws"] / T).mkdir(parents=True)
    agents.create(T, "writer")
    browser.set_profile({"name": "Support"})
    assert browser.chain(A) == [f"agent:{A}", f"topic:{T}", "project:projects/acme"]
    assert browser.resolve(A) == {"enabled": False, "profile": "", "project": "projects/acme",
                                  "from": {"enabled": "", "profile": ""}}
    workspace.set_folder_browser("projects/acme", {"enabled": True, "profile": "support"})   # a project's pick: ignored
    r = browser.resolve(T, create=True)
    assert r["enabled"] and r["profile"] == "acme" and r["from"] == {"enabled": "project:projects/acme",
                                                                     "profile": "project:projects/acme"}
    p = browser.profile("acme")
    assert p["project"] == "projects/acme" and p["name"] == "acme"
    assert browser.ensure_project_profile("projects/acme") == "acme"                # made once
    r = browser.resolve(A)
    assert not r["enabled"] and r["profile"] == "acme"            # its switch is its own, its profile its project's
    agents.update(A, {"browser": {"enabled": True, "profile": "support"}})
    assert browser.resolve(A)["profile"] == "support" and browser.resolve(A)["from"]["profile"] == f"agent:{A}"
    browser.delete_profile("support")                              # gone: its project's again
    assert browser.resolve(A)["profile"] == "acme"
    agents.update(A, {"browser": {"profile": "own"}})              # of before: its project's
    assert "profile" not in agents.load(A)["browser"]
    # a second profile naming the same project is just a profile
    s = browser.settings()
    s["profiles"].append({**s["profiles"][1], "id": "acme-2"})
    assert browser.clean_settings(s)["profiles"][2]["project"] == ""


def test_every_project_with_agents_gets_its_profile(client, topic, mx):
    from maxxing import browser
    _agent(client)
    (mx["ws"] / "projects/empty/topics/x").mkdir(parents=True)
    client.put("/api/settings", json={"browser_feature": True})
    st = client.get("/api/browser").json()
    assert [(p["id"], p["project"]) for p in st["profiles"]] == [("main", ""), ("acme", "projects/acme")]
    # the project gone: its profile may be deleted
    import shutil
    shutil.rmtree(mx["ws"] / "projects/acme")
    assert browser.project_gone(browser.profile("acme"))
    browser.delete_profile("acme")


def test_a_new_page_belongs_to_who_asked(mx):
    from maxxing.browser.tabs import Tabs, mine
    t = Tabs("main")
    first = t.resolve({"targetId": "p0", "type": "page", "url": "about:blank"})
    assert first["by"] == {"kind": "you"}                               # nobody asked: the person's
    assert t.resolve({"targetId": "x", "type": "page", "url": "chrome://omnibox-popup.top-chrome/"}) is None
    t.claim({"kind": "session", "sid": "s1", "path": T})
    own = t.resolve({"targetId": "p1", "type": "page", "url": "about:blank"})
    assert own["by"]["sid"] == "s1" and mine(own, "s1", "") and not mine(own, "s2", "")
    popup = t.resolve({"targetId": "p2", "type": "page", "url": "https://a.example.com/", "openerId": "p1"})
    assert popup["by"]["sid"] == "s1"                                   # a popup: its opener's
    assert t.resolve({"targetId": "p1", "type": "page", "url": "https://x.example"}) is own
    t.changed({"targetId": "p1", "url": "https://shop.example.com/", "title": "Shop"})
    t.gone("p1", keep=True)                                             # asleep: kept without a page
    assert own["target"] is None and own in t.asleep()
    t.claim(own["by"], key=own["key"])                                  # woken: the same tab again
    again = t.resolve({"targetId": "p9", "type": "page", "url": "https://shop.example.com/"})
    assert again is own and own["target"] == "p9"
    t.dirty = True
    t.save()
    t2 = Tabs("main")
    t2.load()                                                           # a browser start: all asleep, blank ones gone
    assert {x["url"] for x in t2.ordered()} == {"https://shop.example.com/", "https://a.example.com/"}
    assert all(not x["target"] for x in t2.ordered())
    assert Tabs("other").file() != t2.file()


def test_a_turn_sees_only_the_tabs_of_its_own_browser(mx):
    """The relay between a turn's tools and Chromium hides the other navigators' tabs: their events are dropped, an
    auto-attach to one is detached at once (its messages dropped), they are not listed, commands naming them are
    refused; a new tab is made by the server in the turn's navigator. It still follows which page a session drives."""
    from maxxing.browser.view import OWN_IDS, View
    own = {"page1": "session:s1", "page2": "me"}
    tab_page = {"tab1": "page1", "tab2": "page2"}
    used, made = [], []

    async def page_of(tab, wait):
        return tab_page.get(tab)

    async def create(params):
        made.append(params.get("url"))
        own["page3"] = "session:s1"
        return "page3"

    async def run():
        v = View("session:s1", lambda info: own.get(info.get("targetId")), page_of, create, used.append)
        mine = {"method": "Target.targetCreated", "params": {"targetInfo": {"targetId": "page1", "type": "page"}}}
        other = {"method": "Target.targetCreated", "params": {"targetInfo": {"targetId": "page2", "type": "page"}}}
        assert (await v.incoming(mine))[0] is mine and (await v.incoming(other))[0] is None
        frame = {"method": "Target.targetCreated", "params": {"targetInfo": {"targetId": "f1", "type": "iframe"}}}
        assert (await v.incoming(frame))[0] is None                     # frames: only through a page of its own
        # a service worker serves every page of its origin, whatever the navigator: never shown, detached at once
        sw = {"targetId": "sw1", "type": "service_worker", "url": "https://bank.example/sw.js"}
        assert (await v.incoming({"method": "Target.targetCreated", "params": {"targetInfo": sw}}))[0] is None
        out, extra = await v.incoming({"method": "Target.attachedToTarget", "params": {"sessionId": "S5", "targetInfo": sw}})
        assert out is None and extra[-1]["method"] == "Target.detachFromTarget"
        assert v.outgoing({"id": 4, "method": "Runtime.evaluate", "sessionId": "S5", "params": {}})
        assert v.outgoing({"id": 3, "method": "Target.attachToTarget", "params": {"targetId": "sw1"}})
        # auto-attach to another navigator's tab: let it run, detach it, drop everything of that session
        out, extra = await v.incoming({"method": "Target.attachedToTarget", "params": {"sessionId": "S9", "targetInfo": {
            "targetId": "tab2", "type": "tab"}}})
        assert out is None and [c["method"] for c in extra] == ["Runtime.runIfWaitingForDebugger",
                                                               "Target.detachFromTarget"]
        assert all(c["id"] > OWN_IDS for c in extra)
        assert (await v.incoming({"id": extra[0]["id"], "result": {}}))[0] is None   # answers to the relay itself
        assert (await v.incoming({"method": "Page.frameNavigated", "sessionId": "S9", "params": {}}))[0] is None
        assert v.outgoing({"id": 5, "method": "Runtime.evaluate", "sessionId": "S9", "params": {}})
        assert v.outgoing({"id": 6, "method": "Target.attachToTarget", "params": {"targetId": "page2"}})
        assert v.outgoing({"id": 7, "method": "Target.closeTarget", "params": {"targetId": "page2"}})
        # its own tab: attached, followed
        await v.incoming({"method": "Target.attachedToTarget", "params": {"sessionId": "S1", "targetInfo": {
            "targetId": "tab1", "type": "tab"}}})
        await v.incoming({"method": "Target.attachedToTarget", "sessionId": "S1", "params": {"sessionId": "S2",
                                                                                           "targetInfo": {
            "targetId": "page1", "type": "page"}}})
        assert v.outgoing({"id": 8, "method": "Page.navigate", "sessionId": "S2", "params": {"url": "https://a.example"}}) is None
        assert used == ["page1"] and v.page("S2") == "page1"
        assert v.outgoing({"id": 9, "method": "Target.getTargets", "params": {}}) is None
        listed, _ = await v.incoming({"id": 9, "result": {"targetInfos": [
            {"targetId": "page1", "type": "page"}, {"targetId": "page2", "type": "page"},
            {"targetId": "tab2", "type": "tab"}, {"targetId": "b", "type": "browser"}]}})
        assert [i["targetId"] for i in listed["result"]["targetInfos"]] == ["page1", "b"]
        answer = await v.new_tab({"id": 10, "method": "Target.createTarget", "params": {"url": "https://b.example"}})
        assert answer == {"id": 10, "result": {"targetId": "page3"}} and made == ["https://b.example"]
        assert v.outgoing({"id": 11, "method": "Target.activateTarget", "params": {"targetId": "page3"}}) is None
        await v.incoming({"method": "Target.detachedFromTarget", "params": {"sessionId": "S2"}})
        assert v.page("S2") == ""
    asyncio.run(run())

def test_claude_waits_while_the_person_has_its_tab(mx, monkeypatch):
    from maxxing.browser import pool as pool_mod
    monkeypatch.setattr(pool_mod, "TAB_WAIT", 0.6)
    p, b = _browser()

    async def run():
        b.released = asyncio.Event()
        b.state = "running"
        b.control = {"me": {"tab": "t1", "vid": 1, "name": "web", "at": time.time()}}
        b.released.clear()
        assert await p.wait_tab(b, "t2") is None                     # another tab: no wait
        assert "using this tab" in (await p.wait_tab(b, "t1"))       # gave up
        waiter = asyncio.create_task(p.wait_tab(b, "t1"))
        await asyncio.sleep(0.1)
        await p.release("main", 1)                                   # the person lets it go: Claude goes on
        assert await asyncio.wait_for(waiter, 2) is None
    asyncio.run(run())


def test_cookies_are_never_read_over_devtools():
    from maxxing.browser import rules
    # a profile's sign-ins are never read or set over DevTools (the user's accounts are in it)
    for m in ("Network.getCookies", "Network.setCookie", "Storage.getCookies", "Target.sendMessageToTarget"):
        assert rules.check_command(json.dumps({"id": 3, "method": m, "params": {}}))[0] is not None, m
    # nor any site's storage, which holds sign-in tokens too: read or written by origin, without opening the site
    bank = {"storageId": {"securityOrigin": "https://bank.example", "isLocalStorage": True}}
    for m, params in (("DOMStorage.getDOMStorageItems", bank), ("DOMStorage.setDOMStorageItem", {**bank, "key": "a", "value": "b"}),
                      ("Storage.getSharedStorageEntries", {"ownerOrigin": "https://bank.example"}),
                      ("Storage.clearDataForStorageKey", {"storageKey": "https://bank.example/", "storageTypes": "all"}),
                      ("IndexedDB.requestData", {"securityOrigin": "https://bank.example"})):
        assert rules.check_command(json.dumps({"id": 4, "method": m, "params": params}))[0] is not None, m


def test_the_live_view_lays_the_page_out_for_its_own_size():
    """The page in front takes the live view's size (clamped), the window's extra height is learned from the first
    picture, and the page goes back to Claude's size when nobody watches."""
    from maxxing.browser import live

    class FakeCdp:
        def __init__(self):
            self.bounds = []

        async def call(self, method, params=None, session=None, timeout=30.0):
            if method == "Browser.getWindowForTarget":
                return {"windowId": 1}
            if method == "Browser.setWindowBounds":
                self.bounds.append((params["bounds"]["width"], params["bounds"]["height"]))
            return {}

    async def run():
        w = live.Watcher(None, "", lambda: None)
        w.cdp = FakeCdp()
        sc = w.screen("me")
        sc.front = sc.casting = "T1"
        w.viewer_nav[1] = "me"
        await w.resize(1, 1000, 600)
        await w.resize(1, "x", None)                  # ignored
        await w.resize(2, 500, 500)                   # not a viewer: ignored
        w._learn(sc, {"deviceWidth": 1000, "deviceHeight": 457})
        await asyncio.sleep(0.01)
        await w.resize(1, 100, 99999)
        assert w.cdp.bounds == [(1000, 600), (1000, 743), (360, 1743)]
        sc.viewers[1] = lambda d: None
        await w.unwatch(1)
        assert sc.size == live.SIZE and w.cdp.bounds[-1] == (1280, 943)

    asyncio.run(run())


# ---- exits ---------------------------------------------------------------------------------------------------------
def test_exits_keep_their_secret_in_the_vault(mx):
    from maxxing import browser, config, vault
    from maxxing.browser import exits
    e = exits.set_exit({"name": "Rented", "type": "proxy", "url": "proxy.example.net:1080", "user": "me"}, None, "pw")
    assert e == {"id": "rented", "name": "Rented", "type": "proxy", "url": "socks5://proxy.example.net:1080",
                 "user": "me"}
    assert vault.get("BROWSER_EXIT_RENTED") == "pw" and "pw" not in json.dumps(config.load_config())
    with pytest.raises(browser.BrowserError):
        exits.set_exit({"name": "x", "type": "proxy", "url": "ftp://a.example:21"})
    with pytest.raises(browser.BrowserError):
        exits.set_exit({"name": "x", "type": "tailscale", "login_server": "http://plain.example"})
    browser.set_profile({"name": "Shop", "exit": "rented"})
    with pytest.raises(browser.BrowserError) as err:
        exits.delete_exit("rented")
    assert err.value.code == "in_use"
    browser.set_profile({"exit": "direct"}, "shop")
    exits.delete_exit("rented")
    assert vault.get("BROWSER_EXIT_RENTED") is None and exits.exits() == []


async def _fake_socks(log: list, accept: bool = True):
    """A SOCKS5 server (user / password) that answers "hello via exit" whatever the address asked."""
    async def handle(r, w):
        try:
            head = await r.readexactly(2)
            await r.readexactly(head[1])
            w.write(b"\x05\x02")
            await w.drain()
            ver, ulen = await r.readexactly(2)
            user = (await r.readexactly(ulen)).decode()
            plen = (await r.readexactly(1))[0]
            pw = (await r.readexactly(plen)).decode()
            ok = accept and (user, pw) == ("me", "pw")
            w.write(b"\x01" + (b"\x00" if ok else b"\x01"))
            await w.drain()
            if not ok:
                return
            req = await r.readexactly(4)
            addr = await r.readexactly(4 if req[3] == 1 else 16)
            port = int.from_bytes(await r.readexactly(2), "big")
            import ipaddress
            log.append((str(ipaddress.ip_address(addr)), port))
            w.write(b"\x05\x00\x00\x01" + bytes(4) + b"\x00\x00")
            w.write(b"hello via exit")
            await w.drain()
        finally:
            w.close()
    return await asyncio.start_server(handle, "127.0.0.1", 0)


def test_the_proxy_goes_out_by_the_exit_to_the_checked_address(tmp_path, mx):
    """A profile with an exit: the host is checked here, the exit gets the checked address (never the name), a down
    exit gets the "offline" page, never this server's own way out."""
    from maxxing.browser import exits
    from maxxing.browser.proxy import Proxy

    async def go():
        seen: list = []
        srv = await _fake_socks(seen)
        port = srv.sockets[0].getsockname()[1]
        up = {"v": ("rented", exits.Upstream("socks5", "127.0.0.1", port, "me", "pw"))}

        def upstream():
            if isinstance(up["v"], Exception):
                raise up["v"]
            return up["v"]
        px = Proxy(tmp_path / "p.sock", upstream=upstream)

        async def check(host, p):
            return ["93.184.215.14"] if host == "shop.example.com" else None
        px.check = check
        await px.start()
        try:
            r, w = await asyncio.open_unix_connection(str(tmp_path / "p.sock"))
            w.write(b"CONNECT shop.example.com:443 HTTP/1.1\r\nHost: shop.example.com\r\n\r\n")
            await w.drain()
            data = b""
            while b"hello via exit" not in data:
                chunk = await asyncio.wait_for(r.read(200), 5)
                assert chunk, data
                data += chunk
            assert data.startswith(b"HTTP/1.1 200") and seen == [("93.184.215.14", 443)]
            w.close()
            up["v"] = exits.ExitDown("the phone is offline")
            r, w = await asyncio.open_unix_connection(str(tmp_path / "p.sock"))
            w.write(b"CONNECT shop.example.com:443 HTTP/1.1\r\nHost: shop.example.com\r\n\r\n")
            await w.drain()
            data = await asyncio.wait_for(r.read(500), 5)
            assert data.startswith(b"HTTP/1.1 502") and b"the phone is offline" in data
            w.close()
            assert seen == [("93.184.215.14", 443)]
        finally:
            await px.stop()
            srv.close()
    asyncio.run(go())


def test_an_http_proxy_exit_gets_a_connect_with_its_password():
    from maxxing.browser import exits

    async def go():
        got: list = []

        async def handle(r, w):
            got.append((await r.readuntil(b"\r\n\r\n")).decode())
            w.write(b"HTTP/1.1 200 Connection established\r\n\r\nhi")
            await w.drain()
            w.close()
        srv = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        r, w = await exits.open_via(exits.Upstream("http", "127.0.0.1", port, "me", "pw"), "93.184.215.14", 443)
        assert await r.read(10) == b"hi"
        w.close()
        srv.close()
        assert got[0].startswith("CONNECT 93.184.215.14:443 HTTP/1.1") and "Proxy-Authorization: Basic bWU6cHc=" in got[0]
    asyncio.run(go())


def test_a_tool_waits_for_its_exit_then_says_it_is_offline(client, topic, mx, monkeypatch):
    """Down exit: the tool waits `exit_wait_s`, answers that the exit is offline, the session keeps a card and the user
    gets one notification; when it comes back, a session that asked to go on gets a message."""
    from maxxing import browser, feed
    from maxxing.browser import exits, pool as pool_mod
    from maxxing.sessions import service
    monkeypatch.setattr(pool_mod, "EXIT_POLL", 0.05)
    browser.set_settings({"exit_wait_s": 0})
    exits.set_exit({"name": "Phone", "type": "proxy", "url": "socks5://127.0.0.1:9"})
    prof = browser.set_profile({"name": "Shop", "exit": "phone"})
    rt = exits.runtime()
    state = {"ok": False}

    async def check(eid):
        rt.mark(eid, state["ok"], "" if state["ok"] else "no answer")
        if state["ok"]:
            await asyncio.to_thread(exits._resume_waiters, eid)
        return state["ok"]
    monkeypatch.setattr(rt, "check", check)
    sent = []
    monkeypatch.setattr(service, "send_message", lambda sid, text, *a, **k: sent.append((sid, text)))
    p = pool_mod.Pool()
    why = asyncio.run(p.exit_ready(prof, "sess01", f"topic:{T}"))
    assert "is offline (no answer)" in why and "never uses this server's address" in why
    w = exits.waiting_for("sess01")
    assert w["exit"] == "phone" and w["profile"] == "shop" and w["resume"] is False
    ev = feed.find("browserexit:phone")
    assert ev and {a["id"] for a in ev["actions"]} == {"retry", "resume"}
    feed.act(ev["id"], "resume")                                   # "go on when it is back"
    assert exits.waiting_for("sess01")["resume"] is True
    state["ok"] = True
    assert asyncio.run(p.exit_ready(prof, "sess01", f"topic:{T}")) is None
    assert exits.waiting_for("sess01") is None
    assert asyncio.run(check("phone")) is True
    # a profile that may fall back never waits
    assert asyncio.run(p.exit_ready({**prof, "on_exit_down": "vps"}, "sess02", f"topic:{T}")) is None


def test_a_connection_looked_at_is_checked_and_tested_by_itself(mx, monkeypatch):
    """Settings -> Browser read: an exit never checked (a restart) is checked and its address tested in the
    background, without the 2 MB speed test; the last test is kept on disk; looking again a moment later does nothing."""
    from maxxing import bus
    from maxxing.browser import exits
    exits.set_exit({"name": "Phone", "type": "proxy", "url": "socks5://127.0.0.1:9"})
    rt = exits.Runtime()
    calls = []

    async def check(eid):
        calls.append(("check", eid))
        rt.mark(eid, True, "", 30)
        return True

    async def test(eid, speed=True):
        calls.append(("test", eid, speed))
        rt._keep_test(eid or "direct", {"ok": True, "ip": "203.0.113.7", "at": time.time()})
        return rt.tests[eid or "direct"]
    monkeypatch.setattr(rt, "check", check)
    monkeypatch.setattr(rt, "test", test)
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    monkeypatch.setattr(bus, "_loop", loop)
    try:
        rt.refresh_seen(exits.exits())
        deadline = time.time() + 3
        while (rt._refreshing or len(calls) < 3) and time.time() < deadline:
            time.sleep(0.02)
        assert ("check", "phone") in calls and ("test", "phone", False) in calls and ("test", None, False) in calls
        assert rt.public(exits.get("phone"))["state"] == "up"
        n = len(calls)
        rt.refresh_seen(exits.exits())                               # fresh: nothing to do
        time.sleep(0.1)
        assert len(calls) == n
    finally:
        loop.call_soon_threadsafe(loop.stop)
    assert exits.Runtime().tests["phone"]["ip"] == "203.0.113.7"   # kept through a restart
    rt._keep_test("phone", {"ok": True, "ip": "x", "mbps": 12.5, "at": 1})
    rt._keep_test("phone", {"ok": True, "ip": "y", "at": 2})          # a quick test keeps the last speed
    assert rt.tests["phone"]["mbps"] == 12.5


def test_a_profile_whose_exit_is_gone_never_goes_out_directly(mx):
    """config.json edited by hand: the exit a profile names is gone. It is read back as is and treated as down."""
    import pytest as _pytest
    from maxxing import browser, config
    from maxxing.browser import exits, pool as pool_mod
    cfg = config.load_config()
    cfg["browser"] = {"profiles": [{"id": "shop", "name": "Shop", "exit": "phone"}]}
    config.save_config(cfg)
    prof = browser.profile("shop")
    assert prof["exit"] == "phone"
    p = pool_mod.Pool()
    with _pytest.raises(exits.ExitDown):
        p._upstream("shop")
    assert "no longer exists" in asyncio.run(p.exit_ready(prof, "sess01", f"topic:{T}"))
    assert asyncio.run(p.exit_ready({**prof, "on_exit_down": "vps"}, "s", "x")) is None
    # and it never stops a save of anything else: settings, another profile, a project's profile made on first use
    assert browser.set_settings({"ask": False})["ask"] is False
    assert browser.set_profile({"name": "New"})["name"] == "New"
    assert browser.profile("shop")["exit"] == "phone"            # still waiting for its connection, never direct
    assert browser.ensure_project_profile("projects/acme")
    # `main` itself on a gone connection: a project's profile made from it waits for that connection too
    cfg = config.load_config()
    cfg["browser"]["profiles"][0]["exit"] = "phone"
    config.save_config(cfg)
    assert browser.profile(browser.ensure_project_profile("projects/blog"))["exit"] == "phone"
    with _pytest.raises(browser.BrowserError):                   # a new value naming no connection: refused
        browser.set_profile({"exit": "nowhere"}, "shop")


def test_exits_come_back_and_resume_the_turns_that_asked(mx, monkeypatch):
    from maxxing.browser import exits
    from maxxing.sessions import service, store
    sent = []
    monkeypatch.setattr(service, "send_message", lambda sid, text, *a, **k: sent.append(sid))
    monkeypatch.setattr(store, "read", lambda sid: {"id": sid, "state": "idle"})
    e = {"id": "phone", "name": "Phone"}
    exits.wait_down("sess01", f"topic:{T}", e, {"id": "shop", "name": "Shop"})
    exits.wait_down("sess02", f"topic:{T}", e, {"id": "shop", "name": "Shop"})
    exits.set_resume("sess01")
    exits._resume_waiters("phone")
    assert sent == ["sess01"] and exits._waiters() == []


def test_the_session_list_reads_the_turns_waiting_for_an_exit_once(mx, monkeypatch):
    from maxxing.browser import exits
    from maxxing.sessions import service, store
    metas = [store.create(store.new_meta(T, f"s{i}")) for i in range(3)]
    exits.wait_down(metas[1]["id"], f"topic:{T}", {"id": "phone", "name": "Phone"}, {"id": "shop", "name": "Shop"})
    reads = []
    real = exits._waiters
    monkeypatch.setattr(exits, "_waiters", lambda: reads.append(1) or real())
    rows = {s["id"]: s for s in service.list_sessions()}
    assert len(reads) == 1                                     # not once a session
    assert rows[metas[1]["id"]]["browser_exit"]["exit"] == "phone"
    assert rows[metas[0]["id"]]["browser_exit"] is None and rows[metas[2]["id"]]["browser_exit"] is None
    assert service.get_session(metas[1]["id"])["browser_exit"]["exit"] == "phone"


def test_too_many_profiles_put_the_oldest_unused_one_to_sleep(mx, monkeypatch):
    from maxxing import browser
    from maxxing.browser import pool as pool_mod
    browser.set_settings({"max_active_profiles": 2})
    for n in ("A", "B", "C"):
        browser.set_profile({"name": n})
    p = pool_mod.Pool()
    stopped = []

    async def stop(pid, why):
        stopped.append(pid)
        p.browsers.pop(pid, None)
    monkeypatch.setattr(p, "_stop_locked", stop)
    for pid, used in (("a", 10), ("b", 20)):
        b = p.browsers[pid] = pool_mod.Browser(browser.profile(pid), p.tabs(pid))
        b.state, b.last_use = "running", used
    asyncio.run(p._make_room("c"))
    assert stopped == ["a"]
    p.browsers["a"] = b = pool_mod.Browser(browser.profile("a"), p.tabs("a"))
    b.state = "running"
    b.turns["s"] = pool_mod.Turn("s", f"topic:{T}")
    p.browsers["b"].control = {"tab": "x", "vid": 1, "at": time.time()}
    with pytest.raises(browser.BrowserError) as err:
        asyncio.run(p._make_room("c"))
    assert err.value.code == "too_many_profiles"


# ---- the live view's pace ------------------------------------------------------------------------------------------
def test_a_card_picture_of_a_watched_page_is_its_live_picture():
    """A clipped screenshot rescales the page for a moment: the live view would show it small every time a card
    refreshes. A page someone watches gives its last live picture instead; one nobody watches is captured."""
    from maxxing.browser import live

    class FakeCdp:
        def __init__(self):
            self.calls = []

        async def call(self, method, params=None, session=None, timeout=30.0):
            self.calls.append(method)
            if method == "Page.captureScreenshot":
                return {"data": base64.b64encode(b"shot").decode()}
            return {}

    async def run():
        w = live.Watcher(None, "", lambda: None)
        w.cdp = FakeCdp()
        w.sessions = {"t1": "s1", "t2": "s2"}
        w.pages = {"t1": {"url": "https://example.com/"}, "t2": {"url": "https://example.org/"}}
        sc = w.screen("me")
        sc.viewers = {1: lambda b: None}
        sc.casting, sc.frame, sc.frame_of = "t1", b"live", "t1"
        assert await w.picture(tid="t1") == b"live"
        assert "Page.captureScreenshot" not in w.cdp.calls
        assert await w.picture(tid="t2") == b"shot"            # not the one watched
        sc.frame_of = "t2"                                       # a picture of the tab shown before
        assert await w.picture(tid="t1") == b"shot"
    asyncio.run(run())


def test_pictures_flow_while_every_viewer_has_room_and_wait_for_the_slowest():
    """Chromium makes the next picture only after our ack. We ack at once while every viewer has fewer than INFLIGHT
    pictures on their way (a far viewer gets several per round trip); a viewer at its limit holds the next ack until
    it confirms one, and gets no picture meanwhile. Pictures that queue lower the quality ("auto"); distance alone
    (the fastest round trip) does not."""
    from maxxing.browser import live

    class FakeCdp:
        def __init__(self):
            self.sent = []

        async def send_nowait(self, method, params=None, session=None):
            self.sent.append((method, (params or {}).get("sessionId")))

        async def call(self, method, params=None, session=None, timeout=30.0):
            self.sent.append((method, params))
            return {}

    async def run():
        w = live.Watcher(None, "", lambda: None)
        w.cdp = FakeCdp()
        sc = w.screen("me")
        sc.front = sc.casting = "T1"
        w.sessions["T1"] = "S1"
        got = {1: 0, 2: 0}

        def sender(vid):
            async def send(data):
                got[vid] += 1
            return send
        await w.watch(1, "me", sender(1))
        await w.watch(2, "me", sender(2))
        acks = lambda: [x for x in w.cdp.sent if x[0] == "Page.screencastFrameAck"]
        for n in range(live.INFLIGHT):
            await w._frame("S1", {"sessionId": 10 + n, "data": "aGk=", "metadata": {}})
        assert got == {1: live.INFLIGHT, 2: live.INFLIGHT}
        assert [a[1] for a in acks()] == [10, 11]                 # the third one waits: no room left
        w.delivered(1, 2, 0.30)
        await asyncio.sleep(0)
        assert len(acks()) == 2                                    # viewer 2 is still full
        w.delivered(2, 2, 0.31)
        await asyncio.sleep(0.01)
        assert [a[1] for a in acks()] == [10, 11, 12]
        await w._frame("S1", {"sessionId": 13, "data": "aGk=", "metadata": {}})
        assert got == {1: live.INFLIGHT + 1, 2: live.INFLIGHT + 1}
        # far but flowing (0.3 s each, never more): the quality does not go down (it may go up)
        sc.adapted = 0
        q = sc.q
        w.delivered(1, 2, 0.30)
        assert sc.q >= q
        # queueing (round trips much above the fastest one): it goes down
        sc.adapted = 0
        q = sc.q
        w.delivered(2, 2, 3.0)
        assert sc.q == q - live.Q_STEP and sc.want()[0] == sc.q
        await w.unwatch(1)
        await w.unwatch(2)
        assert w.watched() is False
    asyncio.run(run())

def test_tailscale_names_the_devices_online_but_not_approved_as_exit(monkeypatch):
    """A phone with "Run as exit node" on is no exit until approved in the Tailscale console: the wizard says so."""
    from maxxing.browser import exits
    st = {"BackendState": "Running", "Self": {"UserID": 1}, "User": {"1": {"LoginName": "me@example.com"}},
          "Peer": {"a": {"HostName": "localhost", "OS": "iOS", "Online": True, "TailscaleIPs": ["100.1.1.1"]},
                   "b": {"HostName": "box", "OS": "linux", "Online": True, "TailscaleIPs": ["100.1.1.2"]},
                   "c": {"HostName": "pixel", "OS": "android", "Online": True, "ExitNodeOption": True,
                         "TailscaleIPs": ["100.1.1.3"]}}}
    monkeypatch.setattr(exits, "tailscale_bins", lambda: ("tailscaled", "tailscale"))
    monkeypatch.setattr(exits.Tailscale, "ensure", classmethod(lambda cls, e: 0))
    monkeypatch.setattr(exits.Tailscale, "cli", classmethod(
        lambda cls, eid, *a, timeout=20: subprocess.CompletedProcess(a, 0, json.dumps(st), "")))
    out = exits.Tailscale.status({"id": "phone"})
    assert out["state"] == "no_node"
    assert out["unapproved"] == [{"name": "localhost", "os": "iOS"}]
    assert [n["name"] for n in out["nodes"]] == ["pixel"]


def test_the_unit_script_sets_its_own_home():
    """A launcher's --setenv=HOME (a wrapper) wins over the unit's Environment=: in a read-only HOME, Chromium's crash
    handler stops it at once. The unit script sets HOME itself (not in direct mode, where MX_RUN is the home)."""
    from maxxing.browser import unit
    sh = unit.HOST_SH.read_text()
    assert '[ -z "$MX_RUN" ] && export HOME=/tmp' in sh
    assert sh.index("export HOME=/tmp") < sh.index("exec ")


def test_the_address_bar_searches_what_is_not_an_address():
    from maxxing.browser import rules
    assert rules.address("example.com") == "https://example.com"
    assert rules.address("fr.wikipedia.org/wiki/Paris") == "https://fr.wikipedia.org/wiki/Paris"
    assert rules.address("https://shop.example.com/a?b=1") == "https://shop.example.com/a?b=1"
    assert rules.address("about:blank") == "about:blank"
    assert rules.address("chat gpt") == "https://www.google.com/search?q=chat+gpt"
    assert rules.address("météo paris") == "https://www.google.com/search?q=m%C3%A9t%C3%A9o+paris"
    assert rules.address("python") == "https://www.google.com/search?q=python"
    assert rules.address("  ") == ""
    assert rules.address("chat gpt", "duckduckgo") == "https://duckduckgo.com/?q=chat+gpt"
    assert rules.address("chat gpt", "bing") == "https://www.bing.com/search?q=chat+gpt"
    from maxxing import browser
    assert browser.clean_settings({})["search"] == "google"
    assert browser.clean_settings({"search": "bing"})["search"] == "bing"
    with pytest.raises(browser.BrowserError):
        browser.clean_settings({"search": "altavista"}, strict=True)


def test_files_reach_a_page_only_from_the_uploads_folder():
    """DOM.setFileInputFiles stays refused, except for files copied into a profile's uploads folder."""
    import json
    from maxxing.browser import rules

    def why(files):
        return rules.check_command(json.dumps({"id": 1, "method": "DOM.setFileInputFiles",
                                               "params": {"files": files, "backendNodeId": 3}}))[0]
    assert why(["/mxrun/uploads/ab12/cv.pdf"]) is None
    for bad in (["/etc/passwd"], ["/mxrun/uploads/../cdp.sock"], ["/mxprofile/Default/Cookies"], [],
                ["/mxrun/uploads/a/x.pdf", "/root/.ssh/id_ed25519"]):
        assert why(bad), bad
    assert rules.check_command(json.dumps({"id": 2, "method": "Page.setInterceptFileChooserDialog",
                                           "params": {"enabled": True}}))[0] is None


def test_claude_gives_a_page_only_files_of_its_folder(tmp_path, monkeypatch):
    from maxxing import browser, config
    from maxxing.browser import pool as pool_mod
    monkeypatch.setenv("MAXXING_BROWSER_LAUNCH", "direct")
    ws = tmp_path / "ws"
    topic = ws / "projects" / "acme" / "topics" / "blog"
    (topic / "attachments").mkdir(parents=True)
    (topic / "attachments" / "cv.pdf").write_bytes(b"%PDF-1.4")
    (ws / "projects" / "acme" / "topics" / "other").mkdir(parents=True)
    (ws / "projects" / "acme" / "topics" / "other" / "secret.txt").write_text("no")
    monkeypatch.setattr(config, "workspace", lambda: ws)

    class B:
        run = tmp_path / "run" / "main"
    out = pool_mod.claude_file(B(), "projects/acme/topics/blog", "attachments/cv.pdf")
    assert out.startswith(str(B.run / "uploads")) and Path(out).read_bytes() == b"%PDF-1.4"
    assert pool_mod.claude_file(B(), "projects/acme/topics/blog/agents/writer", str(topic / "attachments" / "cv.pdf"))
    for bad in ("../other/secret.txt", str(ws / "projects/acme/topics/other/secret.txt"), "/etc/passwd", "nope.pdf"):
        with pytest.raises(browser.BrowserError):
            pool_mod.claude_file(B(), "projects/acme/topics/blog", bad)


def test_an_agent_uses_its_project_profile_unless_it_chooses_another(client, topic, mx):
    from maxxing import agents, browser
    _agent(client)
    client.put("/api/settings", json={"browser_feature": True})
    assert client.put("/api/browser/profiles/main", json={"on_exit_down": "vps"}).status_code == 200
    r = client.put("/api/browser/owner", json={"path": A, "enabled": True}).json()
    assert r["enabled"] and browser.active_for(A)[1]["id"] == "acme" and browser.profile("acme")["on_exit_down"] == "vps"
    assert r["sites"] is None                                                  # a free agent: any public site
    assert client.put("/api/browser/owner", json={"path": A, "profile": "main"}).json()["profile"] == "main"
    r = client.put("/api/browser/owner", json={"path": A, "inherit": ["profile"]}).json()
    assert r["profile"] == "acme" and [p["id"] for p in browser.profiles()] == ["main", "acme"]
    assert client.put("/api/browser/owner", json={"path": T, "inherit": ["profile"]}).status_code == 400
    agents.update(A, {"browser": {"profile": "main"}})       # its manager's change card
    assert browser.resolve(A)["profile"] == "main" and browser.active_for(A)[1]["id"] == "main"

def test_a_profile_picture_is_empty_while_it_sleeps(client, mx):
    """The agent panel's card never starts a browser to draw it."""
    client.put("/api/settings", json={"browser_feature": True})
    assert client.get("/api/browser/profiles/main/picture").status_code == 204
    assert client.get("/api/browser/profiles/nope/picture").status_code == 404
    assert client.post("/api/browser/profiles/main/files", files={"files": ("a.txt", b"x")}).status_code == 409


# ---- navigators ----------------------------------------------------------------------------------------------------
def test_the_person_has_one_navigator_on_any_profile(mx):
    """"me" always exists (on main); it moves to another profile; a profile deleted sends it back to main."""
    from maxxing import browser
    from maxxing.browser import navs
    assert [n["id"] for n in navs.person()] == ["me"] and navs.profile_of("me") == "main"
    browser.set_profile({"name": "Shop"})
    row, old = navs.update("me", profile="shop")
    assert old == "main" and row["profile"] == "shop" and navs.profile_of("me") == "shop"
    navs.on_profile_deleted("shop")
    assert navs.profile_of("me") == "main"
    assert navs.get_person("me-2") is None
    assert navs.valid("agent:projects/acme/topics/blog/agents/writer") and navs.valid("session:abcdef12")
    assert not navs.valid("agent:../x y") and not navs.valid("you")
    assert navs.of_turn("s1", f"topic:{T}") == "session:s1"
    assert navs.of_turn("s1", "agent:projects/acme/topics/blog/agents/writer") == "agent:projects/acme/topics/blog/agents/writer"

def test_a_tab_belongs_to_the_navigator_that_opened_it(mx):
    """A claimed page lands in the claim's navigator; a popup in its opener's; an unknown one in the person's first;
    a tab woken up keeps its key; old saved tabs learn their navigator from who opened them."""
    from maxxing.browser.tabs import Tabs, _clean
    t = Tabs("main")
    c = t.claim({"kind": "session", "sid": "s1"}, "session:s1")
    assert t.resolve({"targetId": "p1", "type": "page", "url": "about:blank"})["nav"] == "session:s1"
    t.unclaim(c)
    assert t.resolve({"targetId": "p2", "type": "page", "url": "https://a.example/", "openerId": "p1"})["nav"] == "session:s1"
    assert t.resolve({"targetId": "p3", "type": "page", "url": "https://b.example/"})["nav"] == "me"
    t.assign("p3", {"kind": "agent", "path": "projects/acme/topics/blog/agents/writer"}, "agent:projects/acme/topics/blog/agents/writer")
    assert t.nav_of("p3") == "agent:projects/acme/topics/blog/agents/writer" and [x["key"] for x in t.of_nav("session:s1")] == [t.of_target("p1")["key"],
                                                                                          t.of_target("p2")["key"]]
    t.gone("p2", keep=True)
    key = next(x["key"] for x in t.asleep("session:s1"))
    t.resolve({"targetId": "p4", "type": "page", "url": "https://a.example/", "openerId": "p1"})
    t.assign("p4", {"kind": "session", "sid": "s1"}, "session:s1", key)
    assert t.of_target("p4")["key"] == key and not t.asleep("session:s1")
    assert _clean({"key": "k", "url": "https://x/", "by": {"kind": "agent", "path": "projects/acme/topics/blog/agents/w"}})["nav"] \
        == "agent:projects/acme/topics/blog/agents/w"
    moved = t.take([key])
    other = Tabs("shop")
    other.put(moved)
    assert other.asleep("session:s1")[0]["key"] == key and key not in t.items


def test_new_tabs_are_made_one_at_a_time_in_their_navigator(mx):
    """pool.create holds the profile's lock: the page Chromium announces is the one asked for, in its navigator,
    even when the answer comes before the announcement."""
    from maxxing.browser import pool as pool_mod
    p, b = _browser()

    class FakeWatcher:
        n = 0

        async def open_tab(self, url, nav):
            FakeWatcher.n += 1
            await asyncio.sleep(0.01)
            return f"new{FakeWatcher.n}"
    b.watcher = FakeWatcher()

    async def run():
        a, c = await asyncio.gather(p.create(b, {"kind": "agent", "path": "projects/acme/topics/blog/agents/w"}, "",
                                             "agent:projects/acme/topics/blog/agents/w"),
                                    p.create(b, {"kind": "you"}, "https://a.example/", "me"))
        assert b.tabs.nav_of(a) == "agent:projects/acme/topics/blog/agents/w" and b.tabs.nav_of(c) == "me"
        assert b.tabs.claims == []
    asyncio.run(run())
    assert pool_mod.Turn("s9", "agent:projects/acme/topics/blog/agents/w").nav == "agent:projects/acme/topics/blog/agents/w"


def test_a_navigator_id_names_an_agent_folder_or_nothing():
    from maxxing.browser import navs
    assert navs.valid("agent:projects/acme/topics/blog/agents/writer") and navs.valid("me") and not navs.valid("me-2")
    for bad in ("agent:projects/../topics/x/agents/y", "agent:projects/a/topics/b/agents/..",
                "agent:projects/a/topics/b", "agent:projects/a/topics/b/agents/w/x", "me-x", "session:a b"):
        assert not navs.valid(bad), bad


def test_the_api_moves_the_person_navigator(client, mx):
    from maxxing import browser
    from maxxing.browser import pool as pool_mod
    st = client.get("/api/browser").json()
    assert [n["id"] for n in st["navigators"] if n["kind"] == "person"] == ["me"]
    assert client.post("/api/browser/navigators", json={}).status_code in (404, 405)   # no second one
    assert client.put("/api/browser/navigators/me", json={"profile": "nope"}).status_code == 404
    pool_mod.pool().tabs("main").claim({"kind": "you"}, "me")
    pool_mod.pool().tabs("main").resolve({"targetId": "x1", "type": "page", "url": "https://a.example/"})
    pool_mod.pool().tabs("main").gone("x1", keep=True)
    browser.set_profile({"name": "Shop"})
    assert client.put("/api/browser/navigators/me", json={"profile": "shop"}).status_code == 200
    assert pool_mod.pool().tabs("shop").asleep("me") and not pool_mod.pool().tabs("main").of_nav("me")
    assert client.get("/api/browser/profiles/main/picture?nav=../x").status_code == 400
    assert client.get("/api/browser/profiles/main/picture?nav=me-9").status_code == 400   # only one: me


def test_a_session_navigator_is_temporary_and_journaled(client, mx):
    """Its tabs close once the session has had no turn for idle_min; the profile's journal keeps a line."""
    import time as _t
    from maxxing.browser import pool as pool_mod, replays
    tabs = pool_mod.pool().tabs("main")
    tabs.claim({"kind": "session", "sid": "sess01"}, "session:sess01")
    tabs.resolve({"targetId": "x1", "type": "page", "url": "https://a.example/"})
    tabs.gone("x1", keep=True)
    replays.log_action("main", {"at": _t.time() - 60, "session": "sess01", "nav": "session:sess01",
                                "tool": "navigate_page", "args": {"url": "https://a.example/x"}, "ok": True})
    replays.log_action("main", {"at": _t.time(), "session": "sess02", "nav": "agent:" + A, "tool": "click", "ok": True})
    v = client.get("/api/browser/profiles/main").json()
    assert [(r["session"], r["sites"], r["open"]) for r in v["temporary"]] == [("sess01", ["a.example"], True)]
    asyncio.run(pool_mod.pool()._close_sessions())
    assert tabs.of_nav("session:sess01")                   # used just now: kept
    for t in tabs.of_nav("session:sess01"):
        t["used"] = 0
    asyncio.run(pool_mod.pool()._close_sessions())
    assert not tabs.of_nav("session:sess01")
    v = client.get("/api/browser/profiles/main").json()
    assert [(r["session"], r["open"]) for r in v["temporary"]] == [("sess01", False)]


def test_general_and_system_use_the_general_profile(client, mx):
    """The projects general and system have no profile of their own: their sessions use `main` ("General"). A
    profile made for one of them before stays as a profile of its own (no project: it can be deleted)."""
    from maxxing import browser
    from maxxing import config
    s = browser.settings()
    s["profiles"].append({**browser.PROFILE_DEFAULTS, "id": "general", "name": "general", "project": "projects/general"})
    config.update_config(browser=s)                     # as an older version wrote it
    assert any(p["id"] == "general" for p in browser.profiles())
    for project in ("projects/general", "projects/system"):
        assert browser.ensure_project_profile(project) == browser.MAIN
        assert browser.resolve(f"{project}/topics/inbox")["profile"] == browser.MAIN
    assert browser.resolve("projects/acme/topics/blog", create=True)["profile"] not in ("", browser.MAIN)
    assert all(p.get("project") != "projects/general" for p in browser.profiles())


def test_an_infinite_number_in_the_settings_is_refused(mx):
    from maxxing import browser, config
    with pytest.raises(browser.BrowserError) as e:
        browser.set_settings({"max_tabs": float("inf")})      # a raw body {"max_tabs": 1e999}
    assert e.value.status == 400 and e.value.code == "bad_browser"
    config.update_config(browser={"exit_wait_s": float("-inf")})   # written by hand: the default, never a crash
    assert browser.settings()["exit_wait_s"] == browser.DEFAULTS["exit_wait_s"]


def test_profiles_made_at_the_same_time_are_all_kept(mx, monkeypatch):
    from maxxing import browser, config
    real = config.update_config

    def slow(**kw):
        time.sleep(0.05)
        return real(**kw)
    monkeypatch.setattr(config, "update_config", slow)
    ts = [threading.Thread(target=browser.set_profile, args=({"name": f"prof{i}"},)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(p["id"] for p in browser.profiles()) == ["main"] + [f"prof{i}" for i in range(8)]


def test_a_json_file_nested_too_deep_reads_as_empty(mx):
    from maxxing import browser, browser_mcp
    from maxxing.browser import exits, navs, turns
    deep = "[" * 100000 + "]" * 100000
    browser.home().mkdir(parents=True, exist_ok=True)
    sid = "0" * 8 + "-0000-0000-0000-" + "0" * 12
    for f in (browser.home() / "deep.json", browser.home() / "waiting.json", browser.home() / "navigators.json",
              turns.turn_file(sid)):
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(deep)
    assert browser_mcp.read(browser.home() / "deep.json") is None
    assert exits._waiters() == [] and turns.read_turn(sid) is None
    assert navs.person()[0]["id"] == navs.ME


def test_turns_waiting_for_an_exit_at_the_same_time_are_all_kept(mx, monkeypatch):
    from maxxing import bus, config
    from maxxing.browser import exits
    real = config.write_json

    def slow(*a, **kw):
        time.sleep(0.05)
        return real(*a, **kw)
    monkeypatch.setattr(config, "write_json", slow)
    monkeypatch.setattr(bus, "invalidate", lambda *a: None)
    monkeypatch.setattr("maxxing.feed.post", lambda *a, **kw: None)
    e, prof = {"id": "phone", "name": "Phone"}, {"id": "main", "name": "Main"}
    ts = [threading.Thread(target=exits.wait_down, args=(f"t{i}", "session:x", e, prof)) for i in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(w["session"] for w in exits._waiters()) == ["t0", "t1"]


@pytest.mark.parametrize("down", [True, False], ids=["down", "cold"])
def test_connections_through_an_exit_share_one_lookup(mx, monkeypatch, down):
    from maxxing.browser import exits
    rt, calls = exits.Runtime(), []

    def lookup(e):
        calls.append(e["id"])
        time.sleep(0.1)                                   # Tailscale: systemctl, tailscale status
        if down:
            raise exits.ExitDown("the Tailscale exit is not ready")
        return exits.Upstream("socks5", "127.0.0.1", 1080)
    monkeypatch.setattr(rt, "_upstream", lookup)
    out: list = []

    def connect():
        try:
            out.append(rt.upstream({"id": "ts", "type": "tailscale"}))
        except exits.ExitDown as ex:
            out.append(str(ex))
    ts = [threading.Thread(target=connect) for _ in range(30)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(out) == 30 and len(calls) == 1


def test_a_lone_surrogate_in_a_tool_argument_never_breaks_the_journal(mx):
    from maxxing.browser import replays
    replays.log_action("main", {"at": 1, "tool": "click", "args": replays.summary("click", {"uid": "\ud800"})})
    replays.log_action("main", {"at": 2, "tool": "navigate_page", "args": replays.summary("navigate_page", {"url": "about:\ud800"})})
    got = replays.actions("main")
    assert [e["at"] for e in got] == [2, 1]
    assert got[1]["args"]["uid"] == "?"


def test_a_running_profile_never_waits_behind_another_profile_starting(mx):
    from types import SimpleNamespace
    p, b = _browser()
    b.state = "running"
    b.watcher = SimpleNamespace(cdp=SimpleNamespace(closed=False))

    async def go():
        await p._start_lock.acquire()                  # another profile is starting (up to 30 s)
        try:
            return await asyncio.wait_for(p.ensure("main"), 2)
        finally:
            p._start_lock.release()
    assert asyncio.run(go()) is b


def test_turn_ids_reject_a_trailing_newline():
    from maxxing.browser import replays, turns
    assert turns.SID_RE.match("abcdef")
    assert not turns.SID_RE.match("abcdef\n")
    assert not replays.SID_RE.match("abcdef\n")


def test_a_browser_ask_with_a_bad_timestamp_does_not_break_the_listing(tmp_path, mx):
    from maxxing import browser
    from maxxing.browser import asks
    folder = browser.asks_dir()
    folder.mkdir(parents=True)
    ok = {"id": "a" * 16, "session": "s1", "owner": "web", "at": time.time(), "status": "pending"}
    bad = {**ok, "id": "b" * 16, "at": "yesterday"}
    (folder / f"{ok['id']}.json").write_text(json.dumps(ok))
    (folder / f"{bad['id']}.json").write_text(json.dumps(bad))
    assert [d["id"] for d in asks.pending()] == [ok["id"]]
    asks.scan()
    asks.prime()


def test_a_decision_is_announced_once_even_if_the_scan_runs_in_between(tmp_path, mx, monkeypatch):
    from maxxing import browser
    from maxxing.browser import asks
    folder = browser.asks_dir()
    folder.mkdir(parents=True)
    rid = "0123456789abcdef"
    assert asks.ID_RE.match(rid) and not asks.ID_RE.match(rid + "\n")
    from maxxing import browser_mcp
    browser_mcp.write_atomic(folder / f"{rid}.json", {"id": rid, "status": "pending", "at": time.time(), "owner": "x"})
    asks._seen[rid] = "pending"
    done = []

    def fake_done(d):
        done.append(d["id"])
        if len(done) == 1:
            asks.scan()                                  # the periodic scan runs between the write and the bookkeeping
    monkeypatch.setattr(asks, "_done", fake_done)
    asks.decide(rid, "skip")
    assert done == [rid]
