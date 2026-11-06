"""Second listen address for a reverse proxy in a container (proxylisten.py, `maxxing proxy`)."""
from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import stat
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from maxxing import config, proxylisten
from maxxing.cli import main


def run_cli(*args: str) -> int:
    return main(list(args))


def get(url: str, **kw) -> httpx.Response:
    return httpx.get(url, trust_env=False, **kw)          # never through an HTTP proxy of the environment


@pytest.fixture(autouse=True)
def _no_ufw(monkeypatch):
    monkeypatch.setattr(proxylisten, "_ufw_active", lambda: False)


def test_only_a_private_address_is_accepted():
    assert proxylisten.parse("172.17.0.1:8790") == ("172.17.0.1", 8790)
    assert proxylisten.parse("[fd00::1]:9000") == ("fd00::1", 9000)
    for bad in ("0.0.0.0:8790", "127.0.0.1:8790", "8.8.8.8:8790", "172.17.0.1", "host:8790", "172.17.0.1:80",
                "[::]:8790", "172.17.0.1:99999", "[2002::1]:8790", "[2001::1]:8790", "169.254.169.254:8790",
                "[::ffff:172.17.0.1]:8790", "100.64.0.1:8790", "198.18.0.1:8790"):
        with pytest.raises(ValueError):
            proxylisten.parse(bad)


def test_on_writes_the_traefik_block_with_a_kept_secret(mx, capsys):
    config.update_config(public_url="https://ui.example.com", port=8787)
    assert run_cli("proxy", "on") == 0
    cfg = config.load_config()
    assert cfg["proxy_listen"] == "172.17.0.1:8790"
    secret = config.get_secret("proxy_secret")
    assert len(secret) >= 40
    f = mx["state"] / "reverse-proxy.conf"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    block = f.read_text()
    assert "Host(`ui.example.com`)" in block and "http://172.17.0.1:8790" in block and secret in block
    assert secret not in capsys.readouterr().out                 # never printed
    assert run_cli("proxy", "on", "10.10.0.1:8791") == 0          # moved: same secret
    assert config.get_secret("proxy_secret") == secret
    assert proxylisten.configured() == ("10.10.0.1", 8791)
    assert run_cli("proxy", "on", "172.17.0.1:8787") == 2         # the main port
    assert run_cli("proxy", "off") == 0
    assert proxylisten.configured() is None and config.load_config()["proxy_listen"] == ""


def test_ufw_rules_follow_on_and_off(mx, monkeypatch):
    calls = []
    monkeypatch.setattr(proxylisten, "_ufw_active", lambda: True)
    monkeypatch.setattr(proxylisten.subprocess, "run", lambda cmd, **k: calls.append(cmd))
    proxylisten.enable("172.17.0.1:8790")
    assert len(calls) == 3 and all(c[:2] == ["ufw", "allow"] and "8790" in c for c in calls)
    calls.clear()
    proxylisten.disable()
    assert len(calls) == 3 and all(c[:3] == ["ufw", "delete", "allow"] for c in calls)


def test_the_socket_opens_before_its_address_exists():
    s = proxylisten.open_socket("172.31.254.253", 0)            # no interface has it: IP_FREEBIND
    try:
        assert s.getsockname()[0] == "172.31.254.253"
    finally:
        s.close()


async def _echo(scope, receive, send):
    if scope["type"] == "lifespan":                              # passes through the gate untouched
        while (m := await receive())["type"] != "lifespan.shutdown":
            await send({"type": m["type"] + ".complete"})
        return await send({"type": "lifespan.shutdown.complete"})
    if scope["type"] == "websocket":
        await receive()
        await send({"type": "websocket.accept"})
        await send({"type": "websocket.send", "text": json.dumps({"client": scope["client"][0], "scheme": scope["scheme"]})})
        return await send({"type": "websocket.close"})
    body = json.dumps({"client": scope["client"][0], "scheme": scope["scheme"],
                       "headers": [k.decode() for k, _ in scope["headers"]]}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})


class _ThreadServer(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):                                   # signals belong to the main thread
        yield


@pytest.fixture
def two_addresses():
    """A real uvicorn on 127.0.0.1 (main) and 127.0.0.2 (the proxy address), as `maxxing serve` runs it."""
    secret = "s3cret-value-for-the-test"
    main = socket.socket(); main.bind(("127.0.0.1", 0)); main.listen(); main.set_inheritable(True)
    extra = proxylisten.open_socket("127.0.0.2", 0)
    port = extra.getsockname()[1]
    uc = uvicorn.Config(proxylisten.Gate(_echo, "127.0.0.2", port, secret), proxy_headers=True,
                        forwarded_allow_ips="127.0.0.1", log_level="warning", lifespan="on")
    server = _ThreadServer(uc)
    t = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[main, extra])), daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield {"main": f"http://127.0.0.1:{main.getsockname()[1]}", "proxy": f"http://127.0.0.2:{port}", "secret": secret}
    server.should_exit = True
    t.join(5)


def test_the_proxy_address_needs_the_secret(two_addresses):
    a = two_addresses
    assert get(a["proxy"] + "/").status_code == 403
    assert get(a["proxy"] + "/", headers={"X-Maxxing-Proxy": "wrong"}).status_code == 403
    r = get(a["proxy"] + "/", headers={"X-Maxxing-Proxy": a["secret"],
                                             "X-Forwarded-For": "6.6.6.6, 203.0.113.9", "X-Forwarded-Proto": "https"})
    assert r.status_code == 200
    d = r.json()
    assert d["client"] == "203.0.113.9" and d["scheme"] == "https"   # the entry the proxy added, not the forged one
    assert "x-maxxing-proxy" not in d["headers"] and "x-forwarded-for" in d["headers"]   # never local (api/pc.py)


def test_the_main_address_is_unchanged(two_addresses):
    a = two_addresses
    d = get(a["main"] + "/").json()
    assert d["client"] == "127.0.0.1" and d["scheme"] == "http"
    d = get(a["main"] + "/", headers={"X-Maxxing-Proxy": a["secret"], "X-Forwarded-For": "203.0.113.9"}).json()
    assert d["client"] == "203.0.113.9"                           # Caddy on 127.0.0.1, as before


def test_a_websocket_without_the_secret_is_refused(two_addresses):
    from websockets.sync.client import connect
    from websockets.exceptions import InvalidStatus
    url = two_addresses["proxy"].replace("http", "ws") + "/ws"
    with pytest.raises(InvalidStatus):
        connect(url, open_timeout=3, proxy=None)
    with connect(url, additional_headers={"X-Maxxing-Proxy": two_addresses["secret"], "X-Forwarded-For": "203.0.113.9",
                                          "X-Forwarded-Proto": "https"}, open_timeout=3, proxy=None) as ws:
        d = json.loads(ws.recv(timeout=3))
    assert d == {"client": "203.0.113.9", "scheme": "wss"}


# ---- install.sh: Docker on 80/443 -> maxxing proxy on ----------------------------------------------------------
INSTALL = Path(__file__).resolve().parents[2] / "install.sh"


def _snippet(tmp_path, web_busy: str, docker: str, mx_rc: int = 0, bridge: str = "172.18.0.1"
             ) -> tuple[subprocess.CompletedProcess, str]:
    calls = tmp_path / "mx-calls"
    calls.unlink(missing_ok=True)
    fake_ip = f'ip() {{ [ -n "{bridge}" ] && echo "4: docker0    inet {bridge}/16 brd 172.18.255.255 scope global"; }}; '
    script = (f'MAXXING_INSTALL_LIB=1 source "{INSTALL}"; set +e; STATE_DIR="{tmp_path}"; WORK="{tmp_path}"; '
              f'DOMAIN=ui.example.com; PORT=8787; WEB_BUSY="{web_busy}"; HAS_DOCKER={docker}; {fake_ip}'
              f'mx() {{ echo "$*" >> "{calls}"; return {mx_rc}; }}; proxy_snippet')
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin"})
    return r, calls.read_text() if calls.exists() else ""


def test_installer_opens_the_proxy_address_when_docker_holds_the_web_ports(tmp_path):
    r, calls = _snippet(tmp_path, "docker-proxy", "1")
    assert r.returncode == 0 and calls.strip() == "proxy on 172.18.0.1:8790 --domain ui.example.com"   # docker0
    assert "Traefik" in r.stdout
    r, calls = _snippet(tmp_path, "another web server", "1")          # Swarm ports: no process listens
    assert "proxy on" in calls
    r, calls = _snippet(tmp_path, "traefik", "0", bridge="")          # Traefik on the host reaches 127.0.0.1
    assert calls == "" and "127.0.0.1:8787" in (tmp_path / "reverse-proxy.conf").read_text()
    r, calls = _snippet(tmp_path, "docker-proxy", "1", bridge="")     # no docker0: said, generic block
    assert calls == "" and "docker0" in r.stdout + r.stderr
    r, calls = _snippet(tmp_path, "nginx", "1")                        # nginx keeps its own block
    assert calls == "" and "proxy_pass http://127.0.0.1:8787" in (tmp_path / "reverse-proxy.conf").read_text()
    r, calls = _snippet(tmp_path, "another web server", "0")           # no Docker: the generic block
    assert calls == "" and "127.0.0.1:8787" in (tmp_path / "reverse-proxy.conf").read_text()


def test_installer_falls_back_to_the_generic_block(tmp_path):
    r, calls = _snippet(tmp_path, "docker-proxy", "1", mx_rc=1)
    assert "proxy on" in calls and "127.0.0.1:8787" in (tmp_path / "reverse-proxy.conf").read_text()


def test_off_removes_the_ufw_rules_even_without_a_secret(mx, monkeypatch):
    calls = []
    monkeypatch.setattr(proxylisten, "_ufw_active", lambda: True)
    monkeypatch.setattr(proxylisten.subprocess, "run", lambda cmd, **k: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    config.update_config(proxy_listen="172.17.0.1:8790")              # secret lost
    proxylisten.disable()
    assert len(calls) == 3 and all(c[:2] == ["ufw", "delete"] for c in calls)
    with pytest.raises(ValueError):                                   # IPv6 + ufw: said, nothing saved
        proxylisten.enable("[fd00::1]:8790")
    assert config.load_config()["proxy_listen"] == ""


def test_the_traefik_block_is_denied_to_claude(mx):
    from maxxing.sessions import spawn
    assert any("reverse-proxy.conf" in r for r in spawn.deny_rules(config.load_config()))


def test_the_domain_and_the_secret(mx):
    with pytest.raises(ValueError):
        proxylisten.enable(domain="x`) || PathPrefix(`/`)")          # no rule injection into the block
    r = proxylisten.enable(domain="UI.Example.com")
    assert r["domain"] == "ui.example.com"
    first = config.get_secret("proxy_secret")
    proxylisten.enable(new_secret=True)
    assert config.get_secret("proxy_secret") != first
    assert config.get_secret("proxy_secret") in (mx["state"] / "reverse-proxy.conf").read_text()
    proxylisten.disable()
    assert not config.get_secret("proxy_secret") and not (mx["state"] / "reverse-proxy.conf").exists()


def test_the_scheme_header_the_app_reads_is_the_one_used(two_addresses):
    a = two_addresses
    d = get(a["proxy"] + "/", headers={"X-Maxxing-Proxy": a["secret"], "X-Forwarded-For": "203.0.113.9",
                                       "X-Forwarded-Proto": "http, https"}).json()
    assert d["scheme"] == "https" and d["headers"].count("x-forwarded-proto") == 1


@pytest.fixture
def guarded(monkeypatch):
    monkeypatch.setattr(proxylisten, "HEADER_TIMEOUT", 1.0)
    monkeypatch.setattr(proxylisten, "MAX_CONNECTIONS", 3)
    main = socket.socket(); main.bind(("127.0.0.1", 0)); main.listen(); main.set_inheritable(True)
    extra = proxylisten.open_socket("127.0.0.2", 0)
    port = extra.getsockname()[1]
    uc = uvicorn.Config(proxylisten.Gate(_echo, "127.0.0.2", port, "s"), http=proxylisten.guarded_protocol(port),
                        log_level="warning", lifespan="on")
    server = _ThreadServer(uc)
    t = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[main, extra])), daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield "127.0.0.2", port, main.getsockname()[1]
    server.should_exit = True
    t.join(5)


def test_a_half_sent_request_is_dropped_on_the_proxy_address(guarded):
    host, port, main_port = guarded
    slow = socket.create_connection((host, port))
    slow.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nX-Pad: ")       # never finishes its head
    slow.settimeout(5)
    assert slow.recv(10) == b""                                      # closed after HEADER_TIMEOUT
    keep = socket.create_connection(("127.0.0.1", main_port))       # the main address has no such limit
    keep.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nX-Pad: ")
    keep.settimeout(2)
    with pytest.raises(socket.timeout):
        keep.recv(10)
    keep.close()


def test_a_finished_request_and_a_websocket_are_not_cut(guarded):
    host, port, _ = guarded
    with httpx.Client(trust_env=False) as c:                          # kept-alive connection, 2 requests 1.5 s apart
        assert c.get(f"http://{host}:{port}/", headers={"X-Maxxing-Proxy": "s"}).status_code == 200
        time.sleep(1.5)
        assert c.get(f"http://{host}:{port}/", headers={"X-Maxxing-Proxy": "s"}).status_code == 200
    from websockets.sync.client import connect
    with connect(f"ws://{host}:{port}/ws", additional_headers={"X-Maxxing-Proxy": "s"}, open_timeout=3,
                 proxy=None) as ws:
        time.sleep(1.5)                                               # past HEADER_TIMEOUT: still open
        assert json.loads(ws.recv(timeout=3))["scheme"] == "ws"


def test_the_proxy_address_caps_its_connections(guarded):
    host, port, _ = guarded
    socks = [socket.create_connection((host, port)) for _ in range(3)]   # MAX_CONNECTIONS = 3 here
    time.sleep(0.2)
    extra = socket.create_connection((host, port))
    extra.settimeout(3)
    assert extra.recv(10) == b""
    for x in socks:
        x.close()


def test_closed_websockets_give_their_place_back(guarded):
    host, port, _ = guarded
    from websockets.sync.client import connect
    for _ in range(5):                                                # MAX_CONNECTIONS = 3 here
        with connect(f"ws://{host}:{port}/ws", additional_headers={"X-Maxxing-Proxy": "s"}, open_timeout=3,
                     proxy=None) as ws:
            ws.recv(timeout=3)
    time.sleep(0.2)
    assert get(f"http://{host}:{port}/", headers={"X-Maxxing-Proxy": "s"}).status_code == 200


def test_installer_goes_on_without_docker0_under_set_e(tmp_path):
    script = (f'MAXXING_INSTALL_LIB=1 source "{INSTALL}"; set -euo pipefail; STATE_DIR="{tmp_path}"; WORK="{tmp_path}"; '
              'DOMAIN=ui.example.com; PORT=8787; WEB_BUSY=docker-proxy; HAS_DOCKER=1; '
              'ip() { return 1; }; mx() { return 0; }; proxy_snippet; echo REACHED')
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin"})
    assert "REACHED" in r.stdout and "docker0" in r.stdout + r.stderr


def test_a_huge_request_head_is_cut_on_the_proxy_address(guarded, monkeypatch):
    host, port, main_port = guarded
    monkeypatch.setattr(proxylisten, "MAX_HEAD", 4096, raising=False)
    big = socket.create_connection((host, port))
    big.settimeout(0.5)                                               # well before HEADER_TIMEOUT (1 s here)
    try:
        big.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nX-Maxxing-Proxy: s\r\nX-Pad: " + b"a" * 200_000)
    except OSError:
        pass                                                          # cut while sending: what we want
    try:
        assert big.recv(10) == b""
    except ConnectionResetError:
        pass
    with httpx.Client(trust_env=False) as c:                          # a normal head, and a big body, still pass
        r = c.post(f"http://{host}:{port}/", headers={"X-Maxxing-Proxy": "s"}, content=b"b" * 100_000)
        assert r.status_code == 200


def test_one_source_cannot_take_every_place(guarded, monkeypatch):
    host, port, _ = guarded
    monkeypatch.setattr(proxylisten, "MAX_PER_SOURCE", 2, raising=False)           # MAX_CONNECTIONS = 3 here
    socks = [socket.create_connection((host, port), source_address=("127.0.0.5", 0)) for _ in range(2)]
    time.sleep(0.2)
    third = socket.create_connection((host, port), source_address=("127.0.0.5", 0))
    third.settimeout(0.5)                                             # well before HEADER_TIMEOUT (1 s here)
    assert third.recv(10) == b""                                      # this source is at its cap
    with httpx.Client(trust_env=False) as c:                          # the proxy (another address) still gets in
        assert c.get(f"http://{host}:{port}/", headers={"X-Maxxing-Proxy": "s"}).status_code == 200
    for x in socks:
        x.close()
