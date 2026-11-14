"""The only way out of a browser: an HTTP proxy on a unix socket of its run folder (the unit has no network; `socat`
inside it forwards 127.0.0.1:3128 here).

Every host is resolved here and refused unless all its addresses are on the public internet; the connection goes to
the address that was checked (no DNS rebinding). Names that point at a local network (localhost, *.local, nip.io...)
and raw IP addresses are refused before any lookup. Which pages may be opened (a sandboxed agent's domains) is checked
on the DevTools commands (rules.page_refusal): through this proxy pass the images, scripts and API calls of those
pages, from any public site.

A profile with an exit (exits.py) sends the connection to the checked address through it (`upstream`): the house's
network behind a phone or a box is never reached, a name is never resolved there. An exit that is down gets a 502
page and its state is marked down (the turn's tools wait for it, pool.py); never a fallback to this server's address.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from collections import deque
from pathlib import Path

from . import exits, rules

log = logging.getLogger("maxxing.browser")

HEAD_MAX = 64 * 1024
CONNECT_TIMEOUT = 15.0
IDLE_TIMEOUT = 300.0                  # a tunnel with no byte either way for this long is closed
MAX_CONNECTIONS = 256
MAX_ADDRESSES = 4
EXIT_PAGE = "The exit of this browser profile is offline ({why}). Harness Maxxing waits for it: it never uses the server's address instead."
BLOCK_PAGE = "Blocked by Harness Maxxing: {host} cannot be reached from this browser (not a public internet site)."


class Proxy:
    def __init__(self, sock: Path, gid: int | None = None, upstream=None) -> None:
        """upstream(): (exit id, exits.Upstream) of the profile now, (None, None) = straight from this server;
        raises exits.ExitDown when its exit cannot carry traffic."""
        self.sock, self.gid = sock, gid
        self.upstream = upstream
        self.server: asyncio.base_events.Server | None = None
        self.bytes_in = self.bytes_out = 0
        self.blocked: deque[tuple[float, str]] = deque(maxlen=20)
        self.open = 0

    async def start(self) -> None:
        self.sock.unlink(missing_ok=True)
        self.server = await asyncio.start_unix_server(self._handle, str(self.sock), limit=HEAD_MAX)
        os.chmod(self.sock, 0o660)
        if self.gid is not None:
            try:
                os.chown(self.sock, 0, self.gid)
            except PermissionError:
                pass

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            try:
                await asyncio.wait_for(self.server.wait_closed(), 3)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                pass
            self.server = None
        self.sock.unlink(missing_ok=True)

    # ---- one client connection -------------------------------------------------------------------------------
    async def _handle(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        if self.open >= MAX_CONNECTIONS:
            w.close()
            return
        self.open += 1
        try:
            await self._serve(r, w)
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            pass
        except Exception:  # noqa: BLE001
            log.exception("browser proxy")
        finally:
            self.open -= 1
            _close(w)

    async def _serve(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 30)
        lines = head.decode("latin-1").split("\r\n")
        parts = lines[0].split(" ")
        if len(parts) != 3:
            return await _answer(w, 400, "Bad request")
        method, target, version = parts
        if method == "CONNECT":
            host, port = _split_hostport(target, 443)
            rest = b""
        else:
            from urllib.parse import urlsplit
            try:
                u = urlsplit(target)
                host, port = (u.hostname or ""), (u.port or 80)
            except ValueError:
                return await _answer(w, 400, "Bad request")
            if u.scheme != "http":
                return await _answer(w, 400, "Only http:// through a plain request")
            path = (u.path or "/") + (f"?{u.query}" if u.query else "")
            kept = [ln for ln in lines[1:] if ln and not ln.lower().startswith(("proxy-", "connection:"))]
            rest = (f"{method} {path} {version}\r\n" + "\r\n".join(kept) + "\r\nConnection: close\r\n\r\n").encode("latin-1")
        if not host or port is None or not 0 < port < 65536:
            return await _answer(w, 400, "Bad request")
        ips = await self.check(host, port)
        if not ips:
            self.blocked.append((time.time(), host))
            return await _answer(w, 403, BLOCK_PAGE.format(host=host))
        eid, up = None, None
        try:
            if self.upstream is not None:
                eid, up = await asyncio.to_thread(self.upstream)
        except exits.ExitDown as e:
            return await _answer(w, 502, EXIT_PAGE.format(why=e))
        err: Exception | None = None
        for ip in ips[:MAX_ADDRESSES]:              # IPv4 first: a phone exit often has no IPv6 way out
            try:
                ur, uw = await exits.open_via(up, ip, port, CONNECT_TIMEOUT)
                break
            except exits.ExitDown as e:
                return await _answer(w, 502, EXIT_PAGE.format(why=e))
            except (OSError, ConnectionError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
                err = e
        else:
            if eid:                                   # the exit, or the site? a quick check says
                asyncio.get_running_loop().create_task(exits.runtime().check(eid))
            return await _answer(w, 502, f"{host} did not answer" + (f" through the exit ({err})" if eid else ""))
        try:
            if method == "CONNECT":
                w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await w.drain()
            else:
                uw.write(rest)
                await uw.drain()
            await asyncio.gather(self._pipe(r, uw, True), self._pipe(ur, w, False))
        finally:
            _close(uw)

    async def check(self, host: str, port: int) -> list[str] | None:
        """The addresses to try, IPv4 first, or None when the host is not a public internet site."""
        h = host.strip("[]").rstrip(".").lower()
        if rules.local_host(h) or rules.parse_ip(h) is not None:
            return None
        try:
            infos = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(h, port, type=socket.SOCK_STREAM), 10)
        except (OSError, asyncio.TimeoutError, UnicodeError):
            return None
        ips = []
        for *_, addr in infos:
            ip = rules.parse_ip(addr[0].split("%", 1)[0])
            if ip is None or not rules.ip_public(ip):
                return None                          # one private answer is enough to refuse (rebinding)
            if addr[0] not in ips:
                ips.append(addr[0])
        ips.sort(key=lambda a: ":" in a)             # stable: the resolver's order inside each family
        return ips or None

    async def _pipe(self, r: asyncio.StreamReader, w: asyncio.StreamWriter, out: bool) -> None:
        try:
            while True:
                data = await asyncio.wait_for(r.read(65536), IDLE_TIMEOUT)
                if not data:
                    break
                if out:
                    self.bytes_out += len(data)
                else:
                    self.bytes_in += len(data)
                w.write(data)
                await w.drain()
        except (ConnectionError, asyncio.TimeoutError, OSError):
            pass
        finally:
            _close(w)


def _split_hostport(target: str, default: int) -> tuple[str, int | None]:
    if target.startswith("["):
        host, _, rest = target[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    else:
        host, _, port = target.rpartition(":") if ":" in target else (target, "", "")
    try:
        return host, int(port) if port else default
    except ValueError:
        return host, None


async def _answer(w: asyncio.StreamWriter, status: int, text: str) -> None:
    body = text.encode()
    reason = {400: "Bad Request", 403: "Forbidden", 502: "Bad Gateway"}.get(status, "Error")
    w.write(f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n".encode() + body)
    try:
        await w.drain()
    except ConnectionError:
        pass


def _close(w: asyncio.StreamWriter) -> None:
    try:
        w.close()
    except Exception:  # noqa: BLE001
        pass
