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
import contextlib
import functools
import logging
import os
import socket
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import exits, rules

log = logging.getLogger("maxxing.browser")

HEAD_MAX = 64 * 1024
CONNECT_TIMEOUT = 15.0
IDLE_TIMEOUT = 300.0                  # a tunnel with no byte either way for this long is closed
MAX_CONNECTIONS = 256
MAX_ADDRESSES = 4
RESOLVERS = 8                         # lookups run on threads of their own: a name that never answers holds one of these,
MAX_RESOLVING = 64                    # never the server's shared pool; past this many waiting, a host is refused
_resolver = ThreadPoolExecutor(RESOLVERS, thread_name_prefix="browser-dns")
_resolving = 0
_rlock = threading.Lock()
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
        self.exit_ip: dict[str, str] = {}        # the address the sites saw through each exit, at its last good test

    async def start(self) -> None:
        self.sock.unlink(missing_ok=True)
        self.server = await asyncio.start_unix_server(self._handle, str(self.sock), limit=HEAD_MAX)
        os.chmod(self.sock, 0o660)
        if self.gid is not None:
            with contextlib.suppress(PermissionError):
                os.chown(self.sock, 0, self.gid)

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.server.wait_closed(), 3)
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
            heads = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in kept)}
            chunked = "chunked" in heads.get("transfer-encoding", "").lower()
            length = heads.get("content-length") or "0"
            if not (length.isascii() and length.isdigit()):
                return await _answer(w, 400, "Bad request")
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
        if eid and self._exit_itself(eid, ips):
            self.blocked.append((time.time(), host))
            return await _answer(w, 403, BLOCK_PAGE.format(host=host))
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
            await self._tunnel(r, w, ur, uw, None if method == "CONNECT" else (int(length), chunked))
        finally:
            _close(uw)

    async def check(self, host: str, port: int) -> list[str] | None:
        """The addresses to try, IPv4 first, or None when the host is not a public internet site."""
        h = host.strip("[]").rstrip(".").lower()
        if rules.local_host(h) or rules.parse_ip(h) is not None:
            return None
        try:
            infos = await self._resolve(h, port)
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

    async def _tunnel(self, r: asyncio.StreamReader, w: asyncio.StreamWriter,
                      ur: asyncio.StreamReader, uw: asyncio.StreamWriter,
                      body: tuple[int, bool] | None = None) -> None:
        """Both ways of a tunnel. A way that ends cleanly (EOF) passes the half-close on and lets the other one
        finish (the client sends its request then shuts its writing side, the site still answers); a way that fails
        or stalls ends both, so a client that stopped reading does not hold its connection slot forever. `body`
        (length, chunked): a plain http request, whose way out carries that one request only (`_body`)."""
        last = [time.monotonic()]                     # the last byte either way: shared, a one-way stream stays open
        ways = {asyncio.ensure_future(self._body(r, uw, *body, last) if body else self._pipe(r, uw, True, last)),
                asyncio.ensure_future(self._pipe(ur, w, False, last))}
        try:
            while ways:
                done, ways = await asyncio.wait(ways, return_when=asyncio.FIRST_COMPLETED)
                if not all(t.result() for t in done):
                    break
        finally:
            for t in ways:
                t.cancel()
            if ways:
                await asyncio.gather(*ways, return_exceptions=True)

    async def _resolve(self, h: str, port: int) -> list:
        global _resolving
        with _rlock:
            if _resolving >= MAX_RESOLVING:
                raise OSError("too many lookups")
            _resolving += 1
        f = _resolver.submit(socket.getaddrinfo, h, port, 0, socket.SOCK_STREAM)
        f.add_done_callback(_resolved)               # when its thread is free again (or it never got one), not at the timeout
        return await asyncio.wait_for(asyncio.wrap_future(f), 10)

    def _exit_itself(self, eid: str, ips: list[str]) -> bool:
        """One of `ips` is the address the sites see through this exit (its last test): a name pointing there would
        reach the box or the router of that network from the inside (IPv6: its whole /64)."""
        seen = (exits.runtime().tests.get(eid) or {}).get("ip")
        if seen:
            self.exit_ip[eid] = str(seen)
        mine = rules.parse_ip(self.exit_ip.get(eid) or "")
        if mine is None:
            return False
        for a in ips:
            ip = rules.parse_ip(a.split("%", 1)[0])
            if ip is None or ip.version != mine.version:
                continue
            if ip == mine or (ip.version == 6 and int(ip) >> 64 == int(mine) >> 64):
                return True
        return False

    async def _body(self, r: asyncio.StreamReader, w: asyncio.StreamWriter, length: int, chunked: bool,
                    last: list[float]) -> bool:
        """A plain http request: its body goes to the site and nothing after it. A connection the site keeps open
        would otherwise carry the browser's next request, for any other host, unchecked."""
        async def idle(make):
            """A read that gives up once nothing moved either way for IDLE_TIMEOUT (the site may have answered
            and closed: then only the client could still end this way)."""
            while True:
                try:
                    return await asyncio.wait_for(make(), max(0.0, last[0] + IDLE_TIMEOUT - time.monotonic()))
                except asyncio.TimeoutError:
                    if time.monotonic() - last[0] < IDLE_TIMEOUT:
                        continue                     # the other way moved meanwhile: not idle
                    raise

        async def copy(n: int) -> None:
            while n > 0:
                data = await idle(functools.partial(r.read, min(65536, n)))
                if not data:
                    raise ConnectionError("closed")
                n -= len(data)
                await send(data)

        async def send(data: bytes) -> None:
            last[0] = time.monotonic()
            self.bytes_out += len(data)
            w.write(data)
            await asyncio.wait_for(w.drain(), IDLE_TIMEOUT)   # a site that stopped reading
        try:
            while chunked:
                line = await idle(r.readline)
                size = int(line.split(b";", 1)[0].strip(), 16)
                if size < 0:
                    raise ValueError(size)
                await send(line)
                if size == 0:
                    while line not in (b"\r\n", b"\n", b""):           # the trailers, up to the empty line
                        line = await idle(r.readline)
                        await send(line)
                    break
                await copy(size + 2)
            else:
                await copy(length)
            more = await idle(functools.partial(r.read, 1))   # the client closing, or a next request
        except (ConnectionError, OSError, ValueError, asyncio.TimeoutError):
            more = b"x"
        if not more:
            with contextlib.suppress(Exception):
                if w.can_write_eof():
                    w.write_eof()                    # the request is whole: the site may still be answering
                    return True
        _close(w)
        return not more

    async def _pipe(self, r: asyncio.StreamReader, w: asyncio.StreamWriter, out: bool,
                    last: list[float] | None = None) -> bool:
        """Copy r to w until r ends (True: the end of writing is passed on to w) or fails, stalls or goes idle
        (False: w is closed)."""
        last = last if last is not None else [time.monotonic()]
        try:
            while True:
                try:
                    data = await asyncio.wait_for(r.read(65536), max(0.0, last[0] + IDLE_TIMEOUT - time.monotonic()))
                except asyncio.TimeoutError:
                    if time.monotonic() - last[0] < IDLE_TIMEOUT:
                        continue                     # the other way moved meanwhile: not idle
                    raise
                if not data:
                    break
                last[0] = time.monotonic()
                if out:
                    self.bytes_out += len(data)
                else:
                    self.bytes_in += len(data)
                w.write(data)
                await asyncio.wait_for(w.drain(), IDLE_TIMEOUT)   # a peer that stopped reading
        except (ConnectionError, asyncio.TimeoutError, OSError):
            _close(w)
            return False
        except BaseException:
            _close(w)
            raise
        with contextlib.suppress(Exception):
            if w.can_write_eof():
                w.write_eof()                        # half-close: the other way may still be talking
                return True
        _close(w)
        return True


def _resolved(_f) -> None:
    global _resolving
    with _rlock:
        _resolving -= 1


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
    with contextlib.suppress(ConnectionError):
        await w.drain()


def _close(w: asyncio.StreamWriter) -> None:
    with contextlib.suppress(Exception):
        w.close()
