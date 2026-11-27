"""Harness Browser: the proxy (one request per plain connection, lookups on threads of their own, an exit never
reaches its own address), NAT64 addresses, tabs made through a browser session, frames attached by their id, the
journal, the secrets of the exits."""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import threading
import time


def test_a_nat64_address_is_judged_by_the_ipv4_inside():
    from maxxing.browser import rules
    for a in ("64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "64:ff9b::c0a8:1"):
        assert not rules.ip_public(ipaddress.ip_address(a)), a
        assert rules.local_host(f"[{a}]"), a
    assert rules.ip_public(ipaddress.ip_address("64:ff9b::5db8:d822"))          # 93.184.216.34


def test_a_plain_connection_carries_one_request_only(tmp_path):
    """A site that keeps the connection open never gets the browser's next request (another host, its cookies)."""
    from maxxing.browser.proxy import Proxy

    async def go():
        got: list[bytes] = []

        async def site(r, w):
            head = await r.readuntil(b"\r\n\r\n")
            body = await r.readexactly(5) if b"Content-Length: 5" in head else b""
            if b"chunked" in head:
                body = await r.readuntil(b"0\r\n\r\n")
            got.append(head + body)
            w.write(b"HTTP/1.1 200 OK\r\nConnection: keep-alive\r\nContent-Length: 2\r\n\r\nok")
            await w.drain()
            got.append(await r.read(4096))               # what comes next on the kept connection
            w.close()
        up = await asyncio.start_server(site, "127.0.0.1", 0)
        port = up.sockets[0].getsockname()[1]
        px = Proxy(tmp_path / "p.sock")

        async def check(host, p):
            return ["127.0.0.1"] if host == "evil.test" else None
        px.check = check
        await px.start()
        try:
            for first in (f"GET http://evil.test:{port}/ HTTP/1.1\r\nHost: evil.test\r\n\r\n",
                          f"POST http://evil.test:{port}/ HTTP/1.1\r\nHost: evil.test\r\nContent-Length: 5\r\n\r\nhello",
                          f"POST http://evil.test:{port}/ HTTP/1.1\r\nHost: evil.test\r\nTransfer-Encoding: chunked"
                          "\r\n\r\n5\r\nhello\r\n0\r\n\r\n"):
                got.clear()
                r, w = await asyncio.open_unix_connection(str(tmp_path / "p.sock"))
                w.write(first.encode())
                await w.drain()
                data = await asyncio.wait_for(r.readuntil(b"ok"), 5)
                assert data.startswith(b"HTTP/1.1 200")
                w.write(b"GET http://bank.test/secret HTTP/1.1\r\nHost: bank.test\r\nCookie: sid=123\r\n\r\n")
                with contextlib.suppress(ConnectionError):
                    await w.drain()
                assert await asyncio.wait_for(r.read(4096), 5) == b""          # closed: the browser asks again
                w.close()
                for _ in range(100):
                    if len(got) == 2:
                        break
                    await asyncio.sleep(0.02)
                assert len(got) == 2 and got[1] == b"", got
                assert b"hello" in got[0] or "hello" not in first
                assert b"bank.test" not in b"".join(got) and b"sid=123" not in b"".join(got)
        finally:
            await px.stop()
            up.close()
    asyncio.run(go())


def test_names_that_never_answer_do_not_hold_the_shared_threads(tmp_path, monkeypatch):
    from maxxing.browser import proxy

    release = threading.Event()
    calls: list[str] = []

    def stuck(host, *a, **kw):
        calls.append(host)
        release.wait(20)
        raise OSError("no answer")
    monkeypatch.setattr(proxy.socket, "getaddrinfo", stuck)
    monkeypatch.setattr(proxy, "MAX_RESOLVING", 12)

    async def go():
        px = proxy.Proxy(tmp_path / "p.sock")
        waiting = [asyncio.create_task(px.check(f"h{i}.slow.test", 443)) for i in range(40)]
        await asyncio.sleep(0.3)
        t0 = time.monotonic()
        assert await asyncio.wait_for(asyncio.to_thread(lambda: 1), 5) == 1    # the server's own pool is free
        assert time.monotonic() - t0 < 2
        assert proxy._resolving == 12 and len(calls) <= proxy.RESOLVERS
        done = [t for t in waiting if t.done()]
        assert len(done) == 28 and all(t.result() is None for t in done)       # past the cap: refused at once
        release.set()
        assert await asyncio.gather(*waiting) == [None] * 40
        for _ in range(100):
            if proxy._resolving == 0:
                break
            await asyncio.sleep(0.02)
        assert proxy._resolving == 0
    try:
        asyncio.run(go())
    finally:
        release.set()


def test_an_exit_never_reaches_its_own_address(tmp_path, mx):
    """A name pointing at the address the sites see through the exit (the house's box, from the inside): refused."""
    from maxxing.browser import exits
    from maxxing.browser.proxy import Proxy

    async def go():
        asked: list = []

        async def socks(r, w):
            asked.append(await r.read(100))
            w.close()
        srv = await asyncio.start_server(socks, "127.0.0.1", 0)
        up = exits.Upstream("socks5", "127.0.0.1", srv.sockets[0].getsockname()[1])
        px = Proxy(tmp_path / "p.sock", upstream=lambda: ("home", up))
        answers = {"box.evil.test": ["203.0.113.7"], "box6.evil.test": ["2001:db8:1:2::99"],
                   "shop.test": ["203.0.113.8"]}

        async def check(host, p):
            return answers.get(host)
        px.check = check
        await px.start()

        async def ask(host):
            r, w = await asyncio.open_unix_connection(str(tmp_path / "p.sock"))
            w.write(f"CONNECT {host}:8080 HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
            await w.drain()
            data = await asyncio.wait_for(r.read(300), 5)
            w.close()
            return data
        try:
            exits.runtime().tests["home"] = {"ok": True, "ip": "203.0.113.7"}
            assert (await ask("box.evil.test")).startswith(b"HTTP/1.1 403") and not asked
            assert not (await ask("shop.test")).startswith(b"HTTP/1.1 403") and asked
            exits.runtime().tests["home"] = {"ok": False, "error": "offline"}   # a failed test forgets nothing
            assert (await ask("box.evil.test")).startswith(b"HTTP/1.1 403")
            exits.runtime().tests["home"] = {"ok": True, "ip": "2001:db8:1:2::1"}
            assert (await ask("box6.evil.test")).startswith(b"HTTP/1.1 403")    # the same /64
            assert [h for _, h in px.blocked] == ["box.evil.test", "box.evil.test", "box6.evil.test"]
        finally:
            await px.stop()
            srv.close()
    asyncio.run(go())


def test_a_tab_asked_through_a_browser_session_is_made_by_the_server(tmp_path, monkeypatch):
    """Target.createTarget with a sessionId (after Target.attachToBrowserTarget) never reaches Chromium either."""
    import json
    from maxxing.browser import relay
    from maxxing.browser.view import View

    async def go():
        sent_up: list[str] = []
        made: list = []

        class Up:
            async def send(self, text):
                sent_up.append(text)

            async def close(self):
                pass

            def __aiter__(self):
                return self

            async def __anext__(self):
                await asyncio.sleep(3600)

        async def connect(sock, path):
            return Up()
        monkeypatch.setattr(relay, "connect", connect)

        async def create(params):
            made.append(params.get("url"))
            return "page9"
        v = View("session:s1", lambda info: None, None, create)
        inbox = [json.dumps({"id": 1, "method": "Target.createTarget", "sessionId": "B1",
                             "params": {"url": "https://a.example/"}}), None]
        out: list[dict] = []

        async def recv():
            return inbox.pop(0)

        async def send(text):
            out.append(json.loads(text))
        await relay.pump(tmp_path / "x.sock", "/devtools/browser/x", lambda: None, recv, send, v)
        assert made == ["https://a.example/"] and sent_up == []
        assert out == [{"id": 1, "sessionId": "B1", "result": {"targetId": "page9"}}]
    asyncio.run(go())


def test_a_frame_attached_by_its_id_and_any_target_command_on_a_foreign_tab_are_refused():
    from maxxing.browser.view import View

    async def go():
        navs = {"mine": "A", "theirs": "B"}
        v = View("A", lambda info: navs.get(str(info.get("targetId"))))
        for i, method in enumerate(("Target.autoAttachRelated", "Target.openDevTools", "Target.getTargetInfo",
                                    "Target.setAutoAttach")):
            assert v.outgoing({"id": i, "method": method, "params": {"targetId": "theirs"}}), method
            assert v.outgoing({"id": i, "method": method, "params": {"targetId": "mine"}}) is None, method
        # a frame of another navigator's page, attached straight from the browser: hidden, detached, its session shut
        frame = {"targetId": "f-theirs", "type": "iframe", "url": "https://bank.example/frame"}
        out, extra = await v.incoming({"method": "Target.attachedToTarget",
                                       "params": {"sessionId": "S7", "targetInfo": frame}})
        assert out is None and extra[-1]["method"] == "Target.detachFromTarget"
        assert v.outgoing({"id": 20, "method": "Runtime.evaluate", "sessionId": "S7", "params": {}})
        # a frame of a page of its own, through that page's session: shown as before
        await v.incoming({"method": "Target.attachedToTarget",
                          "params": {"sessionId": "P1", "targetInfo": {"targetId": "mine", "type": "page"}}})
        mine = {"method": "Target.attachedToTarget", "sessionId": "P1",
                "params": {"sessionId": "F1", "targetInfo": {"targetId": "f-mine", "type": "iframe"}}}
        out, extra = await v.incoming(mine)
        assert out is mine and extra == [] and v.page("F1") == "mine"
        assert v.outgoing({"id": 21, "method": "Runtime.evaluate", "sessionId": "F1", "params": {}}) is None
    asyncio.run(go())


def test_the_journal_never_keeps_a_dialog_answer_or_an_init_script():
    from maxxing.browser import replays
    s = replays.summary("handle_dialog", {"action": "accept", "promptText": "hunter2"})
    assert s == {"action": "accept", "promptText": "<7 chars>"}
    assert "token" not in str(replays.summary("navigate_page", {"initScript": "window.token='abc'"}))


def test_a_password_written_in_a_proxy_address_goes_to_the_vault(mx):
    from maxxing import vault
    from maxxing.browser import exits
    e = exits.set_exit({"name": "Rented", "type": "proxy", "url": "socks5://me:p%40ss@proxy.example.net:1080"})
    assert e["url"] == "socks5://proxy.example.net:1080" and e["user"] == "me"
    assert vault.get(exits.secret_name(e["id"])) == "p@ss"
    up = exits.runtime()._upstream(e)
    assert (up.host, up.port, up.user, up.password) == ("proxy.example.net", 1080, "me", "p@ss")
    e = exits.set_exit({"url": "http://other.example.net:8080"}, e["id"])       # no password in it: the vault's stays
    assert e["url"] == "http://other.example.net:8080" and vault.get(exits.secret_name(e["id"])) == "p@ss"


def test_the_wireguard_socks_server_asks_for_a_password(mx, monkeypatch):
    from maxxing.browser import exits
    started: list = []
    monkeypatch.setattr(exits, "wireproxy_bin", lambda: "/bin/true")
    monkeypatch.setattr(exits, "_unit_active", lambda eid: False)
    monkeypatch.setattr(exits, "stop_unit_sync", lambda eid: None)
    monkeypatch.setattr(exits, "_start_unit", lambda eid, argv, *a, **kw: started.append(argv))
    monkeypatch.setattr(exits.time, "sleep", lambda s: None)
    e = exits.set_exit({"name": "Box", "type": "wireguard"}, None, "[Interface]\nPrivateKey = x\n")
    up = exits.runtime()._upstream(e)
    conf = (exits._dir(e["id"]) / "wireproxy.conf")
    text = conf.read_text()
    assert up.user == exits.SOCKS_USER and len(up.password) == 32 and started
    assert f"Username = {up.user}\nPassword = {up.password}\n" in text and f"127.0.0.1:{up.port}" in text
    for f in (conf, exits._dir(e["id"]) / "socks"):
        assert f.stat().st_mode & 0o777 == 0o600
