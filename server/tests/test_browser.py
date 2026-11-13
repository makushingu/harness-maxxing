"""Harness Browser (maxxing/browser): rules, proxy, relay filter, tab scopes and what a turn sees, ask_human, turn
tokens, runner flags, API, CLI.

No real Chromium here: the parts that start one (unit.py, live.py) are tried by hand on a real server.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
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


def test_the_list_mode_allows_only_its_sites_and_their_subdomains():
    from maxxing.browser import rules
    sites = rules.clean_sites(["Example.com", "https://shop.acme.io/path", "*.blog.dev", "co.uk", "bad site", "x"])
    assert sites == ["example.com", "shop.acme.io", "blog.dev"]
    assert rules.page_refusal("https://www.example.com/", sites) is None
    assert rules.page_refusal("https://a.blog.dev/", sites) is None
    assert "not one of the sites" in rules.page_refusal("https://example.org/", sites)
    assert "not one of the sites" in rules.page_refusal("https://example.com.evil.io/", sites)


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
    assert fwd is None and "not one of the sites" in json.loads(err)["error"]["message"]
    ok = json.dumps({"id": 9, "method": "Runtime.evaluate", "params": {"expression": "1+1"}, "sessionId": "S"})
    assert relay.filter_command(ok, None) == (ok, None)
    assert rules.check_command("x" * (2 << 20))[0] == "command too large"


def test_the_policy_blocks_local_pages_and_downloads():
    from maxxing.browser import rules
    p = rules.policy(["example.com"], downloads=False)
    assert "*" in p["URLBlocklist"] and "file://*" in p["URLBlocklist"]
    assert p["URLAllowlist"] == ["about:blank", "example.com"] and p["DownloadRestrictions"] == 3
    pub = rules.policy(None, downloads=True)
    assert "*" not in pub["URLBlocklist"] and pub["DownloadRestrictions"] == 0


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
        assert await px.check("public.test", 443) == "93.184.216.34"
        for h in ("rebind.test", "lan.test", "localhost", "127.0.0.1", "[::1]", "x.localhost", "nowhere.test"):
            assert await px.check(h, 443) is None, h
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
            return "127.0.0.1" if host == "allowed.test" else None
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
    assert asks.pending_for(f"agent:{A}") and asks.pending(session="sess01")[0]["reason"] == "Solve the captcha"
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
    assert evs[0]["url"] == "/browser?session=nosuchsession"
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
    assert r.json()["settings"] == {"enabled": True} and r.json()["scope"] == f"agent:{A}"
    assert browser.active_for(A) is None                 # the feature is off
    assert client.put("/api/settings", json={"browser_feature": True}).status_code == 200
    assert client.get("/api/settings").json()["browser_feature"] is True
    owner, s = browser.active_for(A)
    assert owner == f"agent:{A}" and s["web"] == "list"
    assert client.get(f"/api/agents/acme/blog/writer").json()["browser"]["enabled"] is True
    # the browser's settings are global (one browser), a topic / an agent only has its switch
    r = client.put("/api/browser/settings", json={"sites": ["not a site"]})
    assert r.status_code == 400
    r = client.put("/api/browser/settings", json={"web": "public", "idle_min": 45})
    assert r.status_code == 200 and r.json()["idle_min"] == 45
    r = client.put("/api/browser/owner", json={"path": T, "settings": {"enabled": True, "web": "list"}})   # older client
    assert r.status_code == 200 and browser.active_for(T)[1]["web"] == "public"
    assert json.loads((mx["ws"] / T / ".maxxing.json").read_text())["browser"] == {"enabled": True}
    assert client.get("/api/browser/owner", params={"path": "projects/acme"}).status_code == 400
    assert client.get("/api/browser/owner", params={"path": "projects/acme/topics/nope"}).status_code == 404
    st = client.get("/api/browser").json()
    assert st["feature"] is True and st["settings"]["idle_min"] == 45 and st["browser"]["state"] == "stopped"
    assert st["browser"]["name"] == "Harness Browser" and st["browser"]["tabs"] == []
    assert client.put("/api/browser/tabs/nope", json={"scope": "me"}).status_code == 404
    assert client.put("/api/browser/tabs/nope", json={"scope": "topic:projects/acme/topics/nope"}).status_code == 400


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
    client.put("/api/browser/owner", json={"path": A, "settings": {"enabled": True}})
    args = runner.browser_args("sess01", A, agent)
    assert args[0] == "--mcp-config" and agent["args"] == ["--allowedTools", "Read,mcp__maxxing-browser"]
    spec = json.loads(Path(args[1]).read_text())["mcpServers"]["maxxing-browser"]
    assert oct(Path(args[1]).stat().st_mode & 0o777) == "0o600"
    assert spec["env"]["MAXXING_BROWSER_OWNER"] == f"agent:{A}" and spec["env"]["MAXXING_BROWSER_URL"].endswith(
        "/api/browser/mcp/sess01")
    forced = {"args": [], "approvals_forced": True}
    assert "--allowedTools" not in runner.browser_args("sess02", A, forced)
    assert runner.browser_args("sess03", T, {}) == []          # its topic: off
    runner.browser_done("sess01")
    assert not Path(args[1]).exists()


def test_a_session_turn_lists_the_browser_tools(client, topic, mx):
    client.put("/api/settings", json={"browser_feature": True})
    client.put("/api/browser/owner", json={"path": T, "settings": {"enabled": True, "sites": ["example.com"]}})
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
    assert agents.load(A)["browser"]["enabled"] is False
    assert "browser: off -> on" in approvals.get(r["request"])["input"]["description"]
    approvals.decide(r["request"], "allow")
    assert agents.load(A)["browser"]["enabled"] is True
    r = agents.request_change(A, {"browser": {"enabled": False}}, session="sess-mgr1")
    assert r["applied"] == ["browser"] and r["asked"] == []
    assert agents.load(A)["browser"]["enabled"] is False


def test_an_agent_turn_cannot_change_its_browser(monkeypatch):
    from maxxing import agent_guard
    monkeypatch.setattr(agent_guard, "agent_turn", lambda: {"path": A, "tampered": False})
    assert "not allowed" in agent_guard.check_cli(["browser", "on", A, "--public"])
    assert agent_guard.check_cli(["browser", "status"]) is None


def test_cli_on_off_show(mx, capsys):
    from maxxing import browser, cli
    (mx["ws"] / T).mkdir(parents=True)
    assert cli.main(["browser", "on", "acme/blog"]) == 0
    assert browser.owner_settings(f"topic:{T}") == {"enabled": True}
    assert cli.main(["browser", "settings", "--sites", "example.com,shop.example.org", "--tab-sleep", "30"]) == 0
    s = browser.settings()
    assert s["sites"] == ["example.com", "shop.example.org"] and s["tab_sleep_min"] == 30 and s["web"] == "list"
    assert cli.main(["browser", "show", "acme/blog", "--json"]) == 0
    assert cli.main(["browser", "off", "acme/blog"]) == 0
    assert browser.owner_settings(f"topic:{T}")["enabled"] is False
    assert cli.main(["browser", "settings", "--max-tabs", "99"]) == 1          # out of range
    with pytest.raises(SystemExit):
        cli.main(["browser", "on", "acme/nope"])


def test_a_page_blocked_by_the_list_is_explained():
    from maxxing.browser import pool
    res = {"content": [{"type": "text", "text": "Error: net::ERR_BLOCKED_BY_ADMINISTRATOR at https://a.example.org/"}]}
    out = pool._explain(res)
    assert out["content"][-1]["text"] == pool.BLOCKED_HINT and len(res["content"]) == 1
    ok = {"content": [{"type": "text", "text": "Successfully navigated"}]}
    assert pool._explain(ok) is ok


def test_claude_is_told_what_the_person_did_in_a_shared_tab(mx):
    from maxxing.browser import pool as pool_mod
    p = pool_mod.Pool()
    p.b = b = pool_mod.Browser({})
    p.tabs.resolve({"targetId": "t1", "type": "page", "url": "about:blank"})
    p.tabs.set_scope(p.tabs.of_target("t1")["key"], f"topic:{T}")
    p.tabs.resolve({"targetId": "t2", "type": "page", "url": "about:blank"})      # the person's own tab
    p._moved("t1", "https://shop.example.com/login?token=secret", "Sign in")     # nobody took over: not a person's move
    assert b.trail == {}
    b.control = {"tab": "t1", "vid": 1, "at": time.time()}
    p._moved("t1", "https://shop.example.com/login?token=secret", "")
    p._moved("t1", "https://shop.example.com/login?token=secret", "Sign in")    # its title came later: same entry
    p._moved("t1", "https://shop.example.com/account", "My account")
    assert [x["url"] for x in b.trail["t1"]] == ["https://shop.example.com/login", "https://shop.example.com/account"]
    b.control = {"tab": "t2", "vid": 1, "at": time.time()}
    p._moved("t2", "https://bank.example.com/", "My bank")                      # a tab of the person only: never told
    assert "t2" not in b.trail
    t = pool_mod.Turn("s1", f"topic:{T}")
    t.told_at = 0
    told = pool_mod.trail_text(p._untold(b, t))
    assert told == "https://shop.example.com/login (Sign in) -> https://shop.example.com/account (My account)"
    assert p._untold(b, t) == []                    # told once
    other = pool_mod.Turn("s2", "topic:projects/acme/topics/shop")
    other.told_at = 0
    assert p._untold(b, other) == []                # another topic never hears of it


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


# ---- tabs and what a turn sees ---------------------------------------------------------------------------------------
def test_scopes_say_who_sees_a_tab(mx):
    from maxxing import browser
    (mx["ws"] / T).mkdir(parents=True)
    agent = f"{T}/agents/writer"
    assert browser.scope_for(T) == f"topic:{T}" and browser.scope_for(agent) == f"agent:{agent}"
    assert browser.visible(f"topic:{T}", T) and browser.visible(f"topic:{T}", "projects/acme/topics/blog/sub")
    # an agent sees its own tabs only: the topic's / project's ones when the user gives it one
    assert browser.visible(f"agent:{agent}", agent) and not browser.visible(f"agent:{agent}", T)
    assert not browser.visible(f"agent:{agent}", f"{T}/agents/other")
    assert not browser.visible(f"topic:{T}", agent) and not browser.visible("project:projects/acme", agent)
    assert not browser.visible(f"topic:{T}", "projects/acme/topics/shop")
    assert browser.visible("project:projects/acme", "projects/acme/topics/shop")
    assert not browser.visible("project:projects/acme", "projects/other/topics/x")
    assert not browser.visible("me", T) and not browser.visible(None, T)
    assert browser.clean_scope(f"topic:{T}") == f"topic:{T}" and browser.clean_scope("project:projects/acme")
    assert browser.clean_scope("topic:projects/acme/topics/nope") is None and browser.clean_scope("me") == "me"
    assert browser.clean_scope("topic:../../etc") is None and browser.clean_scope("everyone") is None
    assert browser.clean_scope(f"agent:{agent}") is None                # no such agent
    (mx["ws"] / agent).mkdir(parents=True)
    (mx["ws"] / agent / "agent.json").write_text("{}")
    assert browser.clean_scope(f"agent:{agent}") == f"agent:{agent}"
    assert browser.clean_scope(f"agent:{T}/agents/../../x") is None


def test_a_new_page_takes_the_scope_of_who_asked(mx):
    from maxxing.browser.tabs import Tabs
    t = Tabs()
    first = t.resolve({"targetId": "p0", "type": "page", "url": "about:blank"})
    assert first["scope"] == "me"                                       # nobody asked: the person's
    assert t.resolve({"targetId": "x", "type": "page", "url": "chrome://omnibox-popup.top-chrome/"}) is None
    t.claim(f"topic:{T}", {"kind": "session", "sid": "s1"})
    mine = t.resolve({"targetId": "p1", "type": "page", "url": "about:blank"})
    assert mine["scope"] == f"topic:{T}" and mine["by"]["sid"] == "s1"
    popup = t.resolve({"targetId": "p2", "type": "page", "url": "https://a.example.com/", "openerId": "p1"})
    assert popup["scope"] == f"topic:{T}"                               # a popup: its opener's
    assert t.resolve({"targetId": "p1", "type": "page", "url": "https://x.example"}) is mine
    t.changed({"targetId": "p1", "url": "https://shop.example.com/", "title": "Shop"})
    t.gone("p1", keep=True)                                             # asleep: kept without a page
    assert mine["target"] is None and mine in t.asleep()
    t.claim(mine["scope"], mine["by"], key=mine["key"])                 # woken: the same tab again
    again = t.resolve({"targetId": "p9", "type": "page", "url": "https://shop.example.com/"})
    assert again is mine and mine["target"] == "p9"
    t.dirty = True
    t.save()
    t2 = Tabs()
    t2.load()                                                           # a browser start: all asleep, blank ones gone
    assert {x["url"] for x in t2.ordered()} == {"https://shop.example.com/", "https://a.example.com/"}
    assert all(not x["target"] for x in t2.ordered())


def test_a_turn_sees_only_the_tabs_of_its_topic(mx):
    from maxxing import browser
    from maxxing.browser.tabs import Tabs
    from maxxing.browser.view import View, EXTRA_ID
    tabs = Tabs()
    tabs.resolve({"targetId": "mine", "type": "page", "url": "about:blank"})
    tabs.set_scope(tabs.of_target("mine")["key"], f"topic:{T}")
    tabs.resolve({"targetId": "private", "type": "page", "url": "https://bank.example.com/"})
    holder = {"mine-tab": "mine", "private-tab": "private"}

    async def page_of(tab, wait):
        return holder.get(tab)

    def sees(info):
        tab = tabs.resolve(info) if "url" in info else tabs.of_target(info["targetId"])
        return bool(tab and browser.visible(tab["scope"], T))
    used = []
    v = View(sees, lambda: tabs.claim(f"topic:{T}", {"kind": "session"}), used.append, page_of, holder.get)

    def ev(method, params, session=None):
        m = {"method": method, "params": params}
        if session:
            m["sessionId"] = session
        return asyncio.run(v.message(m))
    info = lambda tid, kind, url="about:blank": {"targetId": tid, "type": kind, "url": url}  # noqa: E731
    assert ev("Target.targetCreated", {"targetInfo": info("private", "page", "https://bank.example.com/")}) is None
    assert ev("Target.targetCreated", {"targetInfo": info("mine", "page")}) is not None
    assert ev("Target.targetCreated", {"targetInfo": info("b1", "browser")}) is not None
    # Puppeteer attaches to tab targets: the private one is let go (run + detach), never shown
    assert ev("Target.attachedToTarget", {"sessionId": "S1", "waitingForDebugger": True,
                                          "targetInfo": info("private-tab", "tab")}) is None
    sent = [json.loads(x) for x in v.extra]
    assert [x["method"] for x in sent] == ["Runtime.runIfWaitingForDebugger", "Target.detachFromTarget"]
    assert all(x["id"] > EXTRA_ID for x in sent)
    assert asyncio.run(v.message({"id": sent[0]["id"], "result": {}})) is None      # the relay's answers: swallowed
    assert ev("Target.attachedToTarget", {"sessionId": "S2", "targetInfo": info("mine-tab", "tab")}) is not None
    assert ev("Target.attachedToTarget", {"sessionId": "S3", "targetInfo": info("mine", "page")}, "S2") is not None
    assert ev("Page.frameNavigated", {"frame": {}}, "S3") is not None
    assert ev("Page.frameNavigated", {"frame": {}}, "S1") is None
    # commands: on its sessions yes, on others / on a hidden target no
    assert v.command({"id": 5, "method": "Page.navigate", "sessionId": "S3", "params": {"url": "https://a.example"}}) is None
    assert used[-1] == "mine"
    assert v.command({"id": 6, "method": "Runtime.evaluate", "sessionId": "S1", "params": {}}) is not None
    assert v.command({"id": 7, "method": "Target.attachToTarget", "params": {"targetId": "private"}}) is not None
    assert v.command({"id": 8, "method": "Target.closeTarget", "params": {"targetId": "mine"}}) is None
    v.command({"id": 9, "method": "Target.getTargets", "params": {}})
    out = asyncio.run(v.message({"id": 9, "result": {"targetInfos": [info("mine", "page"), info("b1", "browser"),
                                                                     info("private", "page", "https://bank.example.com/")]}}))
    assert [i["targetId"] for i in out["result"]["targetInfos"]] == ["mine", "b1"]
    # a new tab it asks for is its topic's
    v.command({"id": 10, "method": "Target.createTarget", "params": {"url": "about:blank"}})
    assert ev("Target.targetCreated", {"targetInfo": info("new", "page")}) is not None
    assert tabs.of_target("new")["scope"] == f"topic:{T}"
    # a tab whose scope changes to "me" disappears for the turn
    tabs.set_scope(tabs.of_target("new")["key"], "me")
    out = ev("Target.targetInfoChanged", {"targetInfo": info("new", "page", "https://a.example/")})
    assert out == {"method": "Target.targetDestroyed", "params": {"targetId": "new"}}


def test_claude_waits_while_the_person_has_its_tab(mx, monkeypatch):
    from maxxing.browser import pool as pool_mod
    monkeypatch.setattr(pool_mod, "TAB_WAIT", 0.6)
    p = pool_mod.Pool()

    async def run():
        p.b = b = pool_mod.Browser({})
        b.state = "running"
        b.control = {"tab": "t1", "vid": 1, "name": "web", "at": time.time()}
        b.released.clear()
        assert await p.wait_tab(b, "t2") is None                     # another tab: no wait
        assert "using this tab" in (await p.wait_tab(b, "t1"))       # gave up
        waiter = asyncio.create_task(p.wait_tab(b, "t1"))
        await asyncio.sleep(0.1)
        await p.release(1)                                           # the person lets it go: Claude goes on
        assert await asyncio.wait_for(waiter, 2) is None
    asyncio.run(run())


def test_a_browser_session_does_not_get_around_the_view(mx):
    from maxxing.browser import rules
    from maxxing.browser.view import View
    hidden = {"targetId": "private", "type": "page", "url": "https://bank.example.com/"}
    v = View(lambda info: info.get("targetId") == "mine", lambda: None, None, None, lambda t: None)
    v.command({"id": 1, "method": "Target.attachToBrowserTarget", "params": {}})
    asyncio.run(v.message({"id": 1, "result": {"sessionId": "B1"}}))
    assert "B1" in v.browser_sessions
    # discovery / auto-attach through the browser session: the hidden page stays hidden
    assert asyncio.run(v.message({"method": "Target.targetCreated", "params": {"targetInfo": hidden}, "sessionId": "B1"})) is None
    assert asyncio.run(v.message({"method": "Target.attachedToTarget", "sessionId": "B1",
                                  "params": {"sessionId": "S9", "targetInfo": hidden, "waitingForDebugger": False}})) is None
    assert "S9" not in v.sessions
    assert v.command({"id": 2, "method": "Target.attachToTarget", "sessionId": "B1",
                      "params": {"targetId": "private", "flatten": True}}) is not None
    # cookies are never read or set over DevTools (everybody's sign-ins are in this one browser)
    for m in ("Network.getCookies", "Network.setCookie", "Storage.getCookies", "Target.sendMessageToTarget"):
        assert rules.check_command(json.dumps({"id": 3, "method": m, "params": {}}))[0] is not None, m


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
        w.cdp, w.front, w.casting = FakeCdp(), "T1", "T1"
        await w.resize(1000, 600)
        await w.resize("x", None)                     # ignored
        w._learn({"deviceWidth": 1000, "deviceHeight": 457})
        await asyncio.sleep(0.01)
        await w.resize(100, 99999)
        assert w.cdp.bounds == [(1000, 600), (1000, 743), (360, 1743)]
        w.viewers[1] = lambda d: None
        await w.unwatch(1)
        assert w.size == live.SIZE and w.cdp.bounds[-1] == (1280, 943)

    asyncio.run(run())
