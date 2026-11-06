"""A second listen address for a reverse proxy that runs in a container (Traefik of Dokploy or Coolify, or any proxy
in Docker): such a proxy cannot reach 127.0.0.1 of the host, so Harness Maxxing also listens on an address the
containers see (default the Docker bridge gateway 172.17.0.1:8790).

Every request on that address must carry the header X-Maxxing-Proxy with the secret of secrets.json `proxy_secret`
(the proxy adds it): without it the request is refused, so another container cannot reach the UI directly nor pass
for another visitor. With it, the visitor's address comes from the last X-Forwarded-For entry (the one the proxy
saw) and the scheme from X-Forwarded-Proto. The main address (127.0.0.1 or Tailscale) is unchanged.

config.json `proxy_listen`: "HOST:PORT" ("" = off). `maxxing proxy on|off|status` sets it and writes the Traefik
block to <state>/reverse-proxy.conf; the service must be restarted to open or close the address.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import re
import secrets as pysecrets
import shutil
import socket
import subprocess
from typing import Any

from . import config

DEFAULT = "172.17.0.1:8790"
HEADER = b"x-maxxing-proxy"
SECRET_NAME = "proxy_secret"
UFW_FROM = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")   # container networks (bridge, overlay)
UFW_COMMENT = "Harness Maxxing (proxy in a container)"
PRIVATE_NETS = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))
DOMAIN = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,61}[a-z0-9]\Z")   # = install.sh valid_domain
HEADER_TIMEOUT = 10.0       # s: a connection on the proxy address must send a whole request head in that time
MAX_CONNECTIONS = 512       # open at once on the proxy address (each idle one costs memory and a file descriptor)
MAX_PER_SOURCE = 128        # of those, from one source address (one container cannot take every place from the proxy)
MAX_HEAD = 64 * 1024        # bytes: a request head on the proxy address must fit in that (uvicorn's httptools has no cap)
IP_FREEBIND = 15            # Linux: bind before the interface exists (Docker may start after us)
IPV6_FREEBIND = 78


def parse(value: str) -> tuple[str, int]:
    """'172.17.0.1:8790' or '[fd00::1]:8790' -> (host, port). Only a private address: never public, loopback or
    every interface (0.0.0.0)."""
    v = (value or "").strip()
    host, sep, port = v.rpartition(":")
    if not sep or not port.isdigit():
        raise ValueError(f"{value!r}: expected HOST:PORT, e.g. {DEFAULT}")
    host = host.strip("[]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError(f"{host!r}: an IP address is needed (e.g. 172.17.0.1)") from None
    if not any(ip in net for net in PRIVATE_NETS):
        raise ValueError(f"{host}: only a private address the containers reach (10/8, 172.16/12, 192.168/16, "
                         "fc00::/7, e.g. 172.17.0.1), never a public one, 0.0.0.0 or 127.0.0.1")
    p = int(port)
    if not 1024 <= p <= 65535:
        raise ValueError(f"port {p}: between 1024 and 65535")
    return str(ip), p


def configured(cfg: dict | None = None) -> tuple[str, int] | None:
    """The proxy address to open, or None (off, invalid, or no secret yet)."""
    cfg = cfg if cfg is not None else config.load_config()
    try:
        addr = parse(str(cfg.get("proxy_listen") or "")) if cfg.get("proxy_listen") else None
    except ValueError:
        return None
    return addr if addr and config.get_secret(SECRET_NAME) else None


def open_socket(host: str, port: int) -> socket.socket:
    """A listening socket on host:port, even if the address is not up yet (Docker's bridge appears with Docker)."""
    v6 = ":" in host
    s = socket.socket(socket.AF_INET6 if v6 else socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.IPPROTO_IPV6 if v6 else socket.IPPROTO_IP, IPV6_FREEBIND if v6 else IP_FREEBIND, 1)
        except OSError:
            pass
        s.bind((host, port))
        s.listen(2048)
        s.set_inheritable(True)
    except OSError:
        s.close()
        raise
    return s


class Gate:
    """ASGI middleware: requests that came in on the proxy address need the secret header; the visitor's address and
    scheme are then taken from the proxy's headers. Requests on the main address pass untouched."""

    def __init__(self, app: Any, host: str, port: int, secret: str) -> None:
        self.app, self.host, self.port, self.secret = app, host, port, secret.encode()

    def _ours(self, scope: dict) -> bool:
        server = scope.get("server") or (None, None)
        return server[1] == self.port and str(server[0]).strip("[]") == self.host

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") not in ("http", "websocket") or not self._ours(scope):
            return await self.app(scope, receive, send)
        given = b""
        fwd: list[bytes] = []
        proto = b""
        headers = []
        for k, v in scope.get("headers") or []:
            if k == HEADER:
                given = v
                continue                                    # the app never sees the secret
            if k == b"x-forwarded-for":
                fwd.append(v)
            elif k == b"x-forwarded-proto":
                proto = v
                continue                                    # put back below as the single value used
            headers.append((k, v))
        if not given or not hmac.compare_digest(given, self.secret):
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
            return await send({"type": "http.response.body", "body": b"Forbidden\n"})
        scope = dict(scope, headers=headers)
        last = b",".join(fwd).split(b",")[-1].strip().decode("latin-1") if fwd else ""
        try:
            scope["client"] = (str(ipaddress.ip_address(last)), 0)
        except ValueError:
            pass
        p = proto.split(b",")[-1].strip().lower()
        if p in (b"http", b"https"):
            scope["headers"].append((b"x-forwarded-proto", p))   # cookies' Secure flag reads it (security.py)
            secure = p == b"https"
            scope["scheme"] = ("wss" if secure else "ws") if scope["type"] == "websocket" else p.decode()
        return await self.app(scope, receive, send)


def guarded_protocol(port: int, base: type | None = None) -> type:
    """The HTTP protocol of uvicorn, with two limits on the proxy address only (any container can open connections
    there, before the secret is even read): a request head must arrive within HEADER_TIMEOUT (uvicorn has no such
    timeout: half-sent requests would stay open forever) and fit in MAX_HEAD bytes, and at most MAX_CONNECTIONS at
    once, MAX_PER_SOURCE of them from one source address."""
    if base is None:
        from uvicorn.protocols.http.auto import AutoHTTPProtocol as base   # noqa: N813
    open_now: dict = {}                                     # protocol -> source address

    class Guarded(base):  # type: ignore[misc, valid-type]
        _mx_timer = None
        _mx_mark: Any = None
        _mx_head = 0

        def connection_made(self, transport: Any) -> None:
            super().connection_made(transport)
            sock = transport.get_extra_info("sockname")
            self._mx_ours = bool(sock) and sock[1] == port
            if not self._mx_ours:
                return
            peer = transport.get_extra_info("peername")
            source = peer[0] if peer else None
            if len(open_now) >= MAX_CONNECTIONS or sum(1 for s in open_now.values() if s == source) >= MAX_PER_SOURCE:
                transport.close()
                return
            open_now[self] = source
            self._mx_arm()

        def data_received(self, data: bytes) -> None:
            super().data_received(data)
            if not getattr(self, "_mx_ours", False) or self.cycle is not self._mx_mark:
                return                                      # not ours, or the head is complete (a body is not capped)
            self._mx_head += len(data)
            if self._mx_head > MAX_HEAD and self.transport and not self.transport.is_closing():
                self.transport.close()

        def _mx_arm(self) -> None:
            if self._mx_timer:
                self._mx_timer.cancel()
            self._mx_mark = self.cycle
            self._mx_head = 0
            self._mx_timer = self.loop.call_later(HEADER_TIMEOUT, self._mx_expire)

        def _mx_expire(self) -> None:
            self._mx_timer = None
            t = self.transport
            if t is None or t.is_closing() or t.get_protocol() is not self:   # closed, or now a websocket
                return
            c = self.cycle                                  # no new request head since the timer started, and
            if c is self._mx_mark and (c is None or c.response_complete):   # nothing being answered (pipelining)
                t.close()

        def handle_websocket_upgrade(self, *args: Any) -> None:
            super().handle_websocket_upgrade(*args)
            # the websocket protocol owns the connection from now on (its connection_lost is not ours): it leaves
            # the count; a websocket without the secret is closed by the Gate right away
            open_now.pop(self, None)
            if self._mx_timer:
                self._mx_timer.cancel()
                self._mx_timer = None

        def on_response_complete(self) -> None:
            super().on_response_complete()
            if getattr(self, "_mx_ours", False) and self.transport and not self.transport.is_closing():
                self._mx_arm()                              # the next request head on a kept-alive connection

        def connection_lost(self, exc: Exception | None) -> None:
            open_now.pop(self, None)
            if self._mx_timer:
                self._mx_timer.cancel()
            super().connection_lost(exc)

    return Guarded


def wrap(app: Any, cfg: dict | None = None) -> Any:
    addr = configured(cfg)
    return Gate(app, addr[0], addr[1], config.get_secret(SECRET_NAME)) if addr else app


# ---- maxxing proxy on / off -------------------------------------------------------------------------------------
def _host_of(cfg: dict) -> str:
    url = str(cfg.get("public_url") or "")
    return url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0] if url.startswith("https://") else ""


def traefik_block(domain: str, host: str, port: int, secret: str) -> str:
    target = f"[{host}]" if ":" in host else host
    return f"""# Harness Maxxing behind Traefik (a Traefik in Docker: Dokploy, Coolify or your own).
# Copy this file into the folder of Traefik's dynamic configuration (file provider), e.g.
#   Dokploy: /etc/dokploy/traefik/dynamic/harness-maxxing.yml    Coolify: /data/coolify/proxy/dynamic/harness-maxxing.yml
# Check the names of the HTTPS entry point (websecure / https) and of the certificate resolver (letsencrypt) in
# your Traefik. The header below is a secret: Harness Maxxing refuses every request on {target}:{port} without it.
# Uploads that take more than a minute need a longer readTimeout on the entry point (Traefik v3: 60 s by default).
http:
  routers:
    harness-maxxing:
      rule: "Host(`{domain}`)"
      entryPoints: [websecure]
      service: harness-maxxing
      middlewares: [harness-maxxing]
      tls:
        certResolver: letsencrypt
  middlewares:
    harness-maxxing:
      headers:
        customRequestHeaders:
          X-Maxxing-Proxy: "{secret}"
  services:
    harness-maxxing:
      loadBalancer:
        servers:
          - url: "http://{target}:{port}"
"""


def _ufw_active() -> bool:
    if not shutil.which("ufw"):
        return False
    r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=30)
    return r.returncode == 0 and "Status: active" in r.stdout


def _ufw(action: str, host: str, port: int) -> bool:
    """Lets the private networks (containers: bridge, overlay) reach the proxy address; the secret header still
    guards it. action allow | delete. False when ufw is off (nothing to do) or a rule failed."""
    if ":" in host or not _ufw_active():
        return False
    ok = True
    for net in UFW_FROM:
        cmd = ["ufw", "allow", "from", net, "to", host, "port", str(port), "proto", "tcp"]
        if action == "delete":
            cmd = ["ufw", "delete", *cmd[1:]]
        else:
            cmd += ["comment", UFW_COMMENT]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ok = ok and getattr(r, "returncode", 0) == 0
    return ok


def saved(cfg: dict) -> tuple[str, int] | None:
    try:
        return parse(str(cfg.get("proxy_listen") or "")) if cfg.get("proxy_listen") else None
    except ValueError:
        return None


def enable(address: str = "", domain: str = "", new_secret: bool = False) -> dict:
    cfg = config.load_config()
    host, port = parse(address or str(cfg.get("proxy_listen") or "") or DEFAULT)
    domain = (domain or _host_of(cfg) or "ui.example.com").lower()
    if len(domain) > 253 or not DOMAIN.match(domain):
        raise ValueError(f"{domain!r}: not a domain name (e.g. ui.example.com)")
    if port == int(cfg.get("port") or 8787):
        raise ValueError(f"port {port} is the main port of Harness Maxxing: pick another one")
    if ":" in host and _ufw_active():
        raise ValueError(f"ufw is active: use an IPv4 address, or open {host} port {port} to your containers by hand")
    old = saved(cfg)
    secret = (not new_secret and config.get_secret(SECRET_NAME)) or pysecrets.token_urlsafe(32)
    config.set_secret(SECRET_NAME, secret)
    config.update_config(proxy_listen=f"[{host}]:{port}" if ":" in host else f"{host}:{port}")
    if old and old != (host, port):
        _ufw("delete", *old)
    ufw = _ufw("allow", host, port)
    f = config.STATE / "reverse-proxy.conf"           # holds the secret: 0600 (same file as install.sh writes)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(traefik_block(domain, host, port, secret))
    return {"host": host, "port": port, "domain": domain, "file": str(f), "ufw": ufw}


def disable() -> dict:
    cfg = config.load_config()
    old = saved(cfg)                                 # even without a secret: its ufw rules still go
    config.update_config(proxy_listen="")
    config.set_secret(SECRET_NAME, None)              # a new one next time: the old block is worthless
    (config.STATE / "reverse-proxy.conf").unlink(missing_ok=True)
    ufw = _ufw("delete", *old) if old else False
    return {"was": f"{old[0]}:{old[1]}" if old else "", "ufw": ufw}


def ufw_missing(host: str, port: int) -> bool:
    """ufw is active but has none of our rules for this address: the proxy in a container is blocked."""
    if ":" in host or not _ufw_active():
        return False
    r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=30)
    return not any(host in ln and f"{port}/tcp" in ln for ln in r.stdout.splitlines())


def address_present(host: str) -> bool:
    """Some interface of this server has this address (Docker's bridge appears only once Docker runs)."""
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, 0))
        except OSError:
            return False
    return True


def listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False
