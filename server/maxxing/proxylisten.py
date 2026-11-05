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
    if ip.is_loopback or ip.is_unspecified or not ip.is_private:
        raise ValueError(f"{host}: only a private address the containers reach (e.g. 172.17.0.1), "
                         "never a public one, 0.0.0.0 or 127.0.0.1")
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
            secure = p == b"https"
            scope["scheme"] = ("wss" if secure else "ws") if scope["type"] == "websocket" else p.decode()
        return await self.app(scope, receive, send)


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


def enable(address: str = "", domain: str = "") -> dict:
    cfg = config.load_config()
    host, port = parse(address or str(cfg.get("proxy_listen") or "") or DEFAULT)
    if port == int(cfg.get("port") or 8787):
        raise ValueError(f"port {port} is the main port of Harness Maxxing: pick another one")
    if ":" in host and _ufw_active():
        raise ValueError(f"ufw is active: use an IPv4 address, or open {host} port {port} to your containers by hand")
    old = configured(cfg)
    secret = config.get_secret(SECRET_NAME) or pysecrets.token_urlsafe(32)
    config.set_secret(SECRET_NAME, secret)
    config.update_config(proxy_listen=f"[{host}]:{port}" if ":" in host else f"{host}:{port}")
    if old and old != (host, port):
        _ufw("delete", *old)
    ufw = _ufw("allow", host, port)
    domain = domain or _host_of(cfg) or "ui.example.com"
    f = config.STATE / "reverse-proxy.conf"           # holds the secret: 0600 (same file as install.sh writes)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(traefik_block(domain, host, port, secret))
    return {"host": host, "port": port, "domain": domain, "file": str(f), "ufw": ufw}


def disable() -> dict:
    cfg = config.load_config()
    try:                                              # even without a secret: its ufw rules still go
        old = parse(str(cfg.get("proxy_listen") or "")) if cfg.get("proxy_listen") else None
    except ValueError:
        old = None
    config.update_config(proxy_listen="")
    ufw = _ufw("delete", *old) if old else False
    return {"was": f"{old[0]}:{old[1]}" if old else "", "ufw": ufw}


def ufw_missing(host: str, port: int) -> bool:
    """ufw is active but has none of our rules for this address: the proxy in a container is blocked."""
    if ":" in host or not _ufw_active():
        return False
    r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=30)
    return not any(host in ln and f"{port}/tcp" in ln for ln in r.stdout.splitlines())


def listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False
