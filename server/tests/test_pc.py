"""Browser of my PC (pcbridge + api/pc): pairing, downloads, the agent's websocket, the DevTools relay, the local MCP."""
from __future__ import annotations

import asyncio
import json
import struct
import threading
import time

import pytest

from maxxing import pcbridge
from maxxing.api import pc as pc_api


@pytest.fixture
def pc(client, mx, monkeypatch, tmp_path):
    bins = tmp_path / "bins"
    bins.mkdir()
    for name in pcbridge.TARGETS.values():
        (bins / name).write_bytes(b"AGENT-" + name.encode())
    monkeypatch.setenv("MAXXING_PC_BIN_DIR", str(bins))
    calls = []

    async def no_mcp() -> None:
        calls.append("register")
    monkeypatch.setattr(pcbridge, "register_mcp", no_mcp)
    monkeypatch.setattr(pcbridge, "mcp_registered", lambda: bool(calls))
    return client


def _pair(c) -> tuple[str, str]:
    r = c.post("/api/pc/pairing", json={"browser": "brave", "os": "windows"})
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    r = c.post("/api/pc/pair", json={"code": code, "name": "DESKTOP-1", "os": "windows", "arch": "amd64",
                                      "browsers": ["brave", "edge", "evil"]})
    assert r.status_code == 200, r.text
    assert c.post("/api/pc/confirm", json={"id": r.json()["device_id"]}).json()["ok"]
    return code, r.json()["token"]


def test_pairing_download_and_pair(pc):
    r = pc.post("/api/pc/pairing", json={"browser": "brave", "os": "windows"})
    p = r.json()
    assert len(p["code"]) == 10 and "irm '" in p["commands"]["windows"] and p["downloads"]["windows-amd64"]
    # the download carries the trailer: server, code, browser
    d = pc.get(f"/api/pc/download/windows-amd64?code={p['code']}")
    assert d.status_code == 200 and d.headers["content-disposition"].endswith('HarnessPC.exe"')
    data = d.content
    assert data.startswith(b"AGENT-HarnessPC-windows-amd64.exe") and data.endswith(pcbridge.TRAILER_MAGIC)
    n = struct.unpack(">I", data[-12:-8])[0]
    cfg = json.loads(data[-12 - n:-12])
    assert cfg == {"server": "http://testserver", "code": p["code"], "browser": "brave", "autostart": True}
    assert "Invoke-WebRequest" in pc.get(f"/api/pc/install.ps1?code={p['code']}").text
    assert "curl -fsSL" in pc.get(f"/api/pc/install.sh?code={p['code']}&target=darwin-arm64").text
    # wrong / missing code
    assert pc.get("/api/pc/download/windows-amd64?code=NOPE").status_code == 403
    assert pc.get(f"/api/pc/download/plan9-mips?code={p['code']}").status_code == 404
    assert pc.post("/api/pc/pair", json={"code": "WRONGCODE1"}).status_code == 403
    r = pc.post("/api/pc/pair", json={"code": p["code"].lower(), "name": "PC", "browsers": ["brave", "x"]})
    assert r.status_code == 200 and r.json()["token"]
    st = pc.get("/api/pc").json()                     # waits for the user's yes: not the PC yet, no MCP
    assert st["device"] is None and st["candidate"]["name"] == "PC" and not st["mcp_registered"]
    assert not pc.post("/api/pc/confirm", json={"id": "pc_other"}).json()["ok"]
    assert pc.post("/api/pc/confirm", json={"id": r.json()["device_id"]}).json()["ok"]
    st = pc.get("/api/pc").json()
    assert st["device"]["browser"] == "brave" and st["device"]["browsers"] == ["brave"] and not st["online"]
    assert "token_hash" not in json.dumps(st) and st["pairing"] is None
    assert pc.post("/api/pc/pair", json={"code": p["code"]}).status_code == 403          # single use


def test_pairing_expires(pc, monkeypatch):
    p = pc.post("/api/pc/pairing", json={"browser": "chrome", "os": "linux"}).json()
    monkeypatch.setattr(pcbridge.time, "time", lambda: p["expires_at"] + 1)
    r = pc.post("/api/pc/pair", json={"code": p["code"]})
    assert r.status_code == 403 and r.json()["error"] == "expired"


def test_validation_and_public_routes_need_no_cookie(pc, mx):
    assert pc.post("/api/pc/pairing", json={"browser": "netscape", "os": "windows"}).status_code == 422
    assert pc.put("/api/pc/settings", json={"idle_min": 0}).status_code == 422
    assert pc.put("/api/pc/settings", json={"idle_min": 15}).json() == {"idle_min": 15}
    from fastapi.testclient import TestClient
    from maxxing.app import create_app
    with TestClient(create_app()) as anon:
        assert anon.get("/api/pc").status_code == 401
        assert anon.post("/api/pc/pairing", json={"browser": "brave", "os": "windows"}).status_code == 401
        assert anon.post("/api/pc/pair", json={"code": "X"}).status_code == 403          # reached, refused by code
        assert anon.post("/api/pc/mcp", json={}).status_code == 403                      # not loopback


def test_mcp_needs_loopback_and_secret(pc, monkeypatch):
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert pc.post("/api/pc/mcp", json=rpc).status_code == 403                           # testclient is not local
    monkeypatch.setattr(pc_api, "_loopback", lambda conn: True)
    assert pc.post("/api/pc/mcp", json=rpc, headers={"Authorization": "Bearer nope"}).status_code == 403
    h = {"Authorization": f"Bearer {pcbridge.load()['mcp_secret']}"}
    r = pc.post("/api/pc/mcp", json={"jsonrpc": "2.0", "id": 0, "method": "initialize",
                                     "params": {"protocolVersion": "2025-06-18"}}, headers=h).json()
    assert r["result"]["serverInfo"]["name"] == "harness-pc"
    assert pc.post("/api/pc/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                   headers=h).status_code == 202
    tools = pc.post("/api/pc/mcp", json=rpc, headers=h).json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"navigate_page", "click", "take_screenshot"} <= names and not names & pcbridge.BLOCKED_TOOLS
    # PC offline: a clear message, no crash, logged
    r = pc.post("/api/pc/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                     "params": {"name": "navigate_page", "arguments": {"url": "https://x.y"}}},
                headers=h).json()["result"]
    assert r["isError"] and "not reachable" in r["content"][0]["text"]
    r = pc.post("/api/pc/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                     "params": {"name": "upload_file", "arguments": {"filePath": "/etc/passwd"}}},
                headers=h).json()["result"]
    assert r["isError"] and "Unknown tool" in r["content"][0]["text"]
    assert pc.get("/api/pc").json()["actions"][0]["tool"] == "navigate_page"


class FakeAgent:
    """The PC side of /api/pc/ws in a thread: launch / open / data echo / close."""

    def __init__(self, ws) -> None:
        self.ws, self.got, self.stop = ws, [], False
        self.t = threading.Thread(target=self.run, daemon=True)

    def run(self) -> None:
        ws = self.ws
        ws.send_json({"t": "hello", "v": "0.1.0", "os": "windows", "name": "PC", "browsers": ["brave"],
                      "running": False})
        while not self.stop:
            try:
                m = ws.receive_json()
            except Exception:  # noqa: BLE001
                return
            self.got.append(m)
            t = m.get("t")
            if t == "launch":
                ws.send_json({"t": "launched", "id": m["id"], "ok": True})
            elif t == "close":
                ws.send_json({"t": "closed", "id": m["id"], "ok": True})
            elif t == "open":
                ws.send_json({"t": "opened", "ch": m["ch"], "ok": True})
            elif t == "data":
                ws.send_json({"t": "data", "ch": m["ch"], "d": "echo:" + m["d"]})
            elif t == "unpair":
                return


def _wait(pred, what, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out: {what}")


def test_agent_tunnel_and_tool_call(pc, monkeypatch):
    _, token = _pair(pc)
    with pytest.raises(Exception):
        with pc.websocket_connect("/api/pc/ws", headers={"Authorization": "Bearer bad"}) as ws:
            ws.receive_json()
    monkeypatch.setattr(pc_api, "_loopback", lambda conn: True)

    class FakeChild:
        alive = True

        async def call(self, method, params, timeout=0):
            assert method == "tools/call"
            return {"content": [{"type": "text", "text": f"did {params['name']}"}]}

        async def stop(self):
            FakeChild.alive = False

    async def get_child():
        return FakeChild()
    monkeypatch.setattr(pcbridge.hub(), "get_child", get_child)
    with pc.websocket_connect("/api/pc/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
        agent = FakeAgent(ws)
        agent.t.start()
        _wait(lambda: pc.get("/api/pc").json()["online"], "online")
        h = {"Authorization": f"Bearer {pcbridge.load()['mcp_secret']}"}
        r = pc.post("/api/pc/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                                         "params": {"name": "list_pages", "arguments": {}}}, headers=h).json()
        assert r["result"]["content"][0]["text"] == "did list_pages"
        assert any(m["t"] == "launch" and m["browser"] == "brave" for m in agent.got)
        assert pc.get("/api/pc").json()["browser_running"]
        # the DevTools relay: local socket <-> PC
        with pc.websocket_connect("/api/pc/cdp", headers={"X-PC-Secret": pcbridge.load()["cdp_secret"]}) as cdp:
            cdp.send_text('{"id":1,"method":"Browser.getVersion"}')
            assert cdp.receive_text() == 'echo:{"id":1,"method":"Browser.getVersion"}'
        _wait(lambda: any(m["t"] == "end" for m in agent.got), "channel end")
        assert pc.post("/api/pc/stop").json()["ok"]
        _wait(lambda: any(m["t"] == "close" for m in agent.got), "close")
        assert not pc.get("/api/pc").json()["browser_running"]
        assert pc.delete("/api/pc").json()["ok"]
        _wait(lambda: any(m["t"] == "unpair" for m in agent.got), "unpair")
        agent.stop = True
    assert pc.get("/api/pc").json()["device"] is None


def test_cdp_relay_refuses_without_secret(pc, monkeypatch):
    monkeypatch.setattr(pc_api, "_loopback", lambda conn: True)
    with pytest.raises(Exception):
        with pc.websocket_connect("/api/pc/cdp", headers={"X-PC-Secret": "nope"}) as ws:
            ws.receive_text()


def test_idle_closes_the_browser(pc, monkeypatch):
    import asyncio
    hub = pcbridge.Hub()
    closed = []

    async def close_browser():
        closed.append(True)
        hub.running = False
    hub.close_browser = close_browser
    hub.running, hub.last_use = True, time.time() - 3600
    real_sleep = asyncio.sleep

    async def fast(_s):
        await real_sleep(0)
        if closed:
            raise asyncio.CancelledError()

    async def run():
        monkeypatch.setattr(pcbridge.asyncio, "sleep", fast)
        try:
            await hub._idle_watch()
        except asyncio.CancelledError:
            pass
    asyncio.run(run())
    assert closed == [True]


def test_parallel_calls_share_one_child_and_a_disconnect_stops_it(monkeypatch):
    import asyncio
    starts, stopped = [], []

    class Fake:
        alive = True

        async def stop(self):
            stopped.append(self)

    async def start():
        starts.append(1)
        await asyncio.sleep(0.05)                      # slow start: the second call must wait for it
        return Fake()
    monkeypatch.setattr(pcbridge.Child, "start", staticmethod(start))

    async def run():
        hub = pcbridge.Hub()
        a, b = await asyncio.gather(hub.get_child(), hub.get_child())
        assert a is b and len(starts) == 1
        hub.ws = object()
        hub._disconnected()
        await asyncio.sleep(0.01)
        assert stopped == [a] and hub.child is None
    asyncio.run(run())


def test_local_port_follows_serve_port(monkeypatch):
    monkeypatch.setenv("MAXXING_LISTEN_PORT", "8793")
    assert pcbridge.local_port() == 8793 and pcbridge.mcp_url() == "http://127.0.0.1:8793/api/pc/mcp"
    monkeypatch.delenv("MAXXING_LISTEN_PORT")
    assert pcbridge.local_port() == int(pcbridge.config.load_config().get("port") or 8787)


def test_a_pc_waits_for_confirmation_and_a_refused_one_unpairs(pc):
    p = pc.post("/api/pc/pairing", json={"browser": "chrome", "os": "linux"}).json()
    r = pc.post("/api/pc/pair", json={"code": p["code"], "name": "STRANGER"}).json()
    with pc.websocket_connect("/api/pc/ws", headers={"Authorization": f"Bearer {r['token']}"}) as ws:
        ws.send_json({"t": "hello", "v": "0.1.0", "name": "STRANGER"})
        time.sleep(0.3)
        assert not pc.get("/api/pc").json()["online"]            # held: nothing relayed before the yes
        assert not pc.post("/api/pc/confirm", json={"id": r["device_id"], "ok": False}).json()["ok"]
        assert ws.receive_json() == {"t": "unpair"}
    st = pc.get("/api/pc").json()
    assert st["device"] is None and st["candidate"] is None
    with pytest.raises(Exception):                                  # its token is gone
        with pc.websocket_connect("/api/pc/ws", headers={"Authorization": f"Bearer {r['token']}"}) as ws:
            ws.receive_json()


def test_tools_never_open_local_files_nor_touch_server_files(pc, monkeypatch):
    monkeypatch.setattr(pc_api, "_loopback", lambda conn: True)
    h = {"Authorization": f"Bearer {pcbridge.load()['mcp_secret']}"}
    tools = pc.post("/api/pc/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers=h).json()
    props = {k for t in tools["result"]["tools"] for k in (t["inputSchema"].get("properties") or {})}
    assert "url" in props and not props & {"filePath", "sourcePath"}
    for url in ("file:///C:/Users/", " FILE:///etc/passwd", "chrome://settings", "view-source:https://x",
                "about:config", "javascript:alert(1)"):
        r = pc.post("/api/pc/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                         "params": {"name": "new_page", "arguments": {"url": url}}}, headers=h).json()
        assert r["result"]["isError"] and "Only http(s)" in r["result"]["content"][0]["text"], url
    pcbridge._log_action("navigate_page", {"url": "https://acme.test:8443/cb?code=SECRET#tok"}, True, 1)
    assert pcbridge.actions(1)[0]["args"]["url"] == "https://acme.test:8443/cb"


# ---- adapted at integration -----------------------------------------------------------------------------------
def test_no_agent_to_download_hides_the_feature(client, mx, monkeypatch):
    monkeypatch.delenv("MAXXING_PC_BIN_DIR", raising=False)
    monkeypatch.setattr(pcbridge, "_manifest", lambda: {"version": "", "files": {}})
    assert client.get("/api/pc").json()["available"] is False
    r = client.post("/api/pc/pairing", json={"browser": "brave", "os": "windows"})
    assert r.status_code == 409 and r.json()["error"] == "no_agent"
    assert client.post("/api/pc/mcp/register").status_code == 409            # no PC: nothing registered


def test_unpair_drives_the_agent_socket_on_the_server_loop(pc):
    import asyncio
    _, _token = _pair(pc)
    hub = pcbridge.hub()
    seen = []

    class Sock:
        async def send_text(self, _t):
            seen.append(asyncio.get_running_loop())

        async def close(self, code=1000):
            seen.append(asyncio.get_running_loop())
    hub.ws, hub.device_id = Sock(), pcbridge.load()["device"]["id"]
    try:
        assert pc.delete("/api/pc").json()["ok"]
        _wait(lambda: len(seen) >= 2, "unpair sent")
        # the socket belongs to the server's loop: a loop of a worker thread (asyncio.run, closed since) breaks it
        assert all(not lp.is_closed() for lp in seen)
    finally:
        hub.ws, hub.device_id = None, None


def test_a_failed_start_kills_chrome_devtools_mcp_and_hides_the_server_env(mx, monkeypatch, tmp_path):
    import asyncio
    import os
    node = tmp_path / "node"
    node.write_text(f"#!/bin/sh\necho $$ > {tmp_path}/pid\nenv > {tmp_path}/env\nexec sleep 30\n")
    node.chmod(0o755)
    monkeypatch.setattr(pcbridge.shutil, "which", lambda n: str(node) if n == "node" else None)

    async def entry():
        return tmp_path / "cdm.js"
    monkeypatch.setattr(pcbridge, "ensure_cdm", entry)
    monkeypatch.setattr(pcbridge, "START_TIMEOUT", 0.5)
    monkeypatch.setenv("MX_TEST_VAULT_KEY", "s3cret")
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(pcbridge.Child.start())
    pid = int((tmp_path / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    env = (tmp_path / "env").read_text()
    assert "MX_TEST_VAULT_KEY" not in env and "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1" in env


@pytest.mark.parametrize("url", [
    "http://localhost:3000/", "http://127.1/", "http://2130706433/", "http://0x7f000001/", "http://192.168.1.1/",
    "https://10.0.0.5/admin", "http://172.20.0.1", "http://[::1]:8080/", "http://[::ffff:192.168.0.1]/",
    "http://169.254.169.254/latest", "http://router/", "http://nas.local/", "http://printer.lan/",
    "http://app.localhost/", "http://100.100.100.100/",
    # written so that urlsplit finds no (or another) host while the browser of the PC reads a local one
    "http:127.0.0.1/", "http:\\\\127.0.0.1\\", "http:/127.0.0.1/", "http:///192.168.1.1/", "HTTP:/192.168.1.1/",
    "http://127.0.0.%31/", "http://\uff11\uff12\uff17.0.0.1/", "http://127\uff0e0\u30020.1/", "http://12\t7.0.0.1/",
    "http://127.0.0.1.nip.io/", "http://192-168-1-1.sslip.io/", "http://localtest.me/", "http://app.lvh.me/",
    "http://[::1%25eth0]/"])
def test_local_network_of_the_pc_is_refused(url):
    assert "local network" in (pcbridge._bad_url({"url": url}) or ""), url


@pytest.mark.parametrize("url", ["https://example.com/", "https://8.8.8.8/", "http://x.y", "about:blank",
                                 "https://shop.example.co.uk/cart?x=1", "https://user@example.com/a\\b",
                                 "https://caf\u00e9.example/", "https://www.nip.io.example.com/"])
def test_internet_pages_are_allowed(url):
    assert pcbridge._bad_url({"url": url}) is None


def test_a_tool_error_does_not_restart_the_browser(pc, monkeypatch):
    import asyncio
    hub = pcbridge.hub()
    stops = []

    class Child:
        alive = True

        async def call(self, method, params, timeout=0):
            raise RuntimeError("no element with uid 9")

    async def get_child():
        return Child()

    async def nothing():
        return None

    async def stop_child():
        stops.append(1)
    monkeypatch.setattr(hub, "get_child", get_child)
    monkeypatch.setattr(hub, "ensure_browser", nothing)
    monkeypatch.setattr(hub, "stop_child", stop_child)
    hub.ws = object()
    try:
        r = asyncio.run(pcbridge.tools_call("click", {"uid": "9"}))
    finally:
        hub.ws = None
    assert r["isError"] and "uid 9" in r["content"][0]["text"] and stops == []


def test_the_waiting_pc_shows_where_it_connected_from(pc):
    p = pc.post("/api/pc/pairing", json={"browser": "chrome", "os": "linux"}).json()
    pc.post("/api/pc/pair", json={"code": p["code"], "name": "PC"})
    assert pc.get("/api/pc").json()["candidate"]["ip"] == "testclient"


def test_tailscale_bind_is_the_local_address(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.delenv("MAXXING_LISTEN_PORT", raising=False)
    monkeypatch.setattr(pcbridge.config, "load_config", lambda: {"bind": "100.101.102.103", "port": 8787})
    assert pcbridge.mcp_url() == "http://100.101.102.103:8787/api/pc/mcp"
    conn = SimpleNamespace(client=SimpleNamespace(host="100.101.102.103"), headers={})
    assert pc_api._loopback(conn)
    assert not pc_api._loopback(SimpleNamespace(client=SimpleNamespace(host="100.101.102.104"), headers={}))
    monkeypatch.setattr(pcbridge.config, "load_config", lambda: {"bind": "0.0.0.0", "port": 8787})
    assert pcbridge.mcp_url() == "http://127.0.0.1:8787/api/pc/mcp"


def test_hello_racing_unpair_does_not_bring_the_pc_back(mx, monkeypatch):
    """The agent's hello (_touch_device) reads devices.json, unpair lands before it writes: the PC stays unpaired."""
    d = pcbridge.load()
    d["device"] = {"id": "pc_x", "token_hash": "h"}
    pcbridge.save(d)
    real, slow = pcbridge.load, threading.local()

    def load():
        r = real()
        if getattr(slow, "on", False):
            time.sleep(0.3)                          # the hello's read-modify-write is slow
        return r
    monkeypatch.setattr(pcbridge, "load", load)

    def hello():
        slow.on = True
        pcbridge._touch_device(version="1")
    t = threading.Thread(target=hello)
    t.start()
    time.sleep(0.1)
    pcbridge._unpair_state()
    t.join(5)
    assert real().get("device") is None


class _FakeWS:
    def __init__(self, frames):
        self.f = list(frames)

    async def receive_text(self):
        if not self.f:
            raise RuntimeError("end")
        return self.f.pop(0)

    async def send_text(self, t):
        pass

    async def close(self, code=1000):
        pass


@pytest.mark.parametrize("bad", [{"t": "hello", "browsers": 5}, {"t": "hello", "browsers": [["x"]]},
                                 {"t": "data", "ch": 1, "d": 5}, {"t": "hello", "v": {"a": 1}, "browsers": None}])
def test_malformed_agent_frame_does_not_end_the_link(mx, bad):
    async def go():
        h = pcbridge.Hub()
        h._chans[1] = asyncio.Queue()
        try:
            await h.serve(_FakeWS([json.dumps(bad), json.dumps({"t": "hello", "v": "1"})]), {"id": "pc_1"})
        except RuntimeError as e:
            return str(e)                            # every frame was read: the link survived the bad one
        return "ended"
    assert asyncio.run(go()) == "end"


@pytest.mark.parametrize("m", [
    {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": [1]},
    {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_pages", "arguments": "x"}},
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": "x"},
])
def test_mcp_params_of_the_wrong_type_get_a_json_rpc_error(mx, m):
    r = asyncio.run(pc_api._rpc(m))
    assert r["error"]["code"] == -32602 and r["id"] == 1


def test_ensure_mcp_puts_the_entry_back_for_a_paired_pc(monkeypatch):
    calls = []
    monkeypatch.setattr(pcbridge, "load", lambda: {"device": {"id": "pc_1"}, "mcp_secret": "s"})
    monkeypatch.setattr(pcbridge, "mcp_registered", lambda: bool(calls))
    monkeypatch.setattr(pcbridge, "_replace_mcp", lambda mcp, spec: calls.append(spec))
    monkeypatch.setattr(pcbridge, "_ensure_at", {"t": -1e9})
    assert pcbridge.ensure_mcp() is True and calls[0]["url"].endswith("/api/pc/mcp")
    assert pcbridge.ensure_mcp() is False                                    # throttled
    monkeypatch.setattr(pcbridge, "_ensure_at", {"t": -1e9})
    assert pcbridge.ensure_mcp() is False and len(calls) == 1                # already registered: nothing to do
    monkeypatch.setattr(pcbridge, "_ensure_at", {"t": -1e9})
    monkeypatch.setattr(pcbridge, "load", lambda: {})
    monkeypatch.setattr(pcbridge, "mcp_registered", lambda: False)
    assert pcbridge.ensure_mcp() is False and len(calls) == 1                # no PC paired: nothing


def test_ensure_mcp_does_not_leave_an_entry_when_unpaired_meanwhile(monkeypatch):
    state = {"dev": {"device": {"id": "pc_1"}, "mcp_secret": "s"}}
    removed = []
    monkeypatch.setattr(pcbridge, "load", lambda: state["dev"])
    monkeypatch.setattr(pcbridge, "mcp_registered", lambda: False)

    def add(mcp, spec):                                  # the user unpairs while `claude mcp add-json` runs
        state["dev"] = {"mcp_secret": "s"}
    monkeypatch.setattr(pcbridge, "_replace_mcp", add)
    monkeypatch.setattr(pcbridge, "_remove_mcp", lambda mcp: removed.append(1))
    monkeypatch.setattr(pcbridge, "_ensure_at", {"t": -1e9})
    assert pcbridge.ensure_mcp() is False and removed == [1]


def test_turn_start_does_not_wait_for_the_mcp_repair(monkeypatch):
    from maxxing.sessions import spawn
    monkeypatch.setattr(pcbridge, "ensure_mcp", lambda: time.sleep(2))
    monkeypatch.setattr(spawn, "_start_direct", lambda sid: "pid:1")
    monkeypatch.setenv("MAXXING_SPAWN", "direct")
    t = time.monotonic()
    assert spawn.start("s_x") == "pid:1"
    assert time.monotonic() - t < 1


def test_mcp_config_args_point_at_a_private_file_only_when_paired(tmp_path, monkeypatch):
    monkeypatch.setattr(pcbridge, "_dir", lambda: tmp_path)
    monkeypatch.setattr(pcbridge, "load", lambda: {})
    assert pcbridge.mcp_config_args() == []
    monkeypatch.setattr(pcbridge, "load", lambda: {"device": {"id": "pc_1"}, "mcp_secret": "topsecret"})
    args = pcbridge.mcp_config_args()
    f = tmp_path / "mcp-config.json"
    assert args == ["--mcp-config", str(f)] and "topsecret" not in " ".join(args)
    assert json.loads(f.read_text())["mcpServers"]["harness-pc"]["url"].endswith("/api/pc/mcp")
    assert oct(f.stat().st_mode & 0o777) == "0o600"
