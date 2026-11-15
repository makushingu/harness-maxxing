"""Exits of the Harness Browser: where a profile's traffic leaves the server.

Sites that block (Cloudflare, Google, social networks, banks) look at the address first, and a server's address is a
datacenter's. An exit sends a profile's pages out by a "normal" address - a phone or a box at home, a rented proxy -
while Chromium, the pages and everything else stay on this server. Never the whole server: only the browser's proxy
(proxy.py) goes through an exit.

    config.json -> browser.exits: [{id, name, type, ...}]
      proxy      {url: socks5://host:port | http://host:port, user}   password: vault key BROWSER_EXIT_<ID>
      tailscale  {node, login_server}   a `tailscaled` of its own, in userspace, that only the browser uses; `node` =
                 the device chosen as exit node (a phone with "Run as exit node", a box, an Apple TV)
      wireguard  {}                     the box's WireGuard config: vault key BROWSER_EXIT_<ID>; `wireproxy`

Every exit looks the same to the proxy: an upstream SOCKS5 / HTTP proxy (`upstream()`). The proxy resolves and checks
each host on this server first (never the house's network, never a private address), then asks the exit for the
address it checked.

An exit that is down makes its profiles wait (a turn's tool waits `exit_wait_s`, then says so; a notification offers
to go on when it is back), never fall back to the server's address (unless the profile says `on_exit_down: vps`).
Tailscale and WireGuard run as their own systemd units (`maxxing-bx-<install>-<id>`), started when a profile needs them,
kept while the server runs.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import ipaddress
import json
import logging
import os
import re
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .. import browser, bus, config

log = logging.getLogger("maxxing.browser")

HOSTNAME = "harness-browser"                      # the name of this server in the user's Tailscale network
UNIT_PREFIX = "maxxing-bx-"
CHECK_HOST = ("1.1.1.1", 443)                     # a quick "does the exit carry traffic" (TCP only)
CHECK_EVERY = 30.0
SEEN_FRESH = 60.0                                  # an exit looked at (Settings -> Browser) is checked again after this
RETEST_EVERY = 3600.0                              # ... and its address tested again after this (no speed: no 2 MB)
UPSTREAM_KEEP = 20.0
DOWN_KEEP = 5.0                 # an exit found down answers so for this long before it is asked again
CONNECT_TIMEOUT = 15.0
TEST_IP_URL = "http://ip-api.com/json/?fields=status,message,country,countryCode,city,isp,org,as,mobile,proxy,hosting,query"
TEST_SPEED = ("speed.cloudflare.com", "/__down?bytes=2000000")
TAILSCALE_VERSION = "1.104.7"
TAILSCALE_SHA = {"amd64": "e56693ff74a64f2591b7e819c280635a100aae1ddfb0ef058fcd052b7cd8d16c",
                 "arm64": "d6bed2720310b328b861f943d7b4016c5358a9bad60575eb51e8143b79068484"}
WIREPROXY_VERSION = "1.1.3"
WIREPROXY_SHA = {"amd64": "e88c1d090740373fc606c1bafd81d9a5eadc642cce5667616e20e9d7a444f51c",
                 "arm64": "370e00bd2167960d1ecd1c3c1439715bbaa94a0a110a2040468670c9af6021b6"}


class ExitDown(Exception):
    """The exit of a profile carries no traffic now."""


# ---- settings ------------------------------------------------------------------------------------------------------
def secret_name(eid: str) -> str:
    return "BROWSER_EXIT_" + eid.upper().replace("-", "_")


def clean_exit(raw: object, strict: bool = False) -> dict | None:
    src = raw if isinstance(raw, dict) else {}
    eid, kind = str(src.get("id") or ""), src.get("type")

    def bad(why: str) -> None:
        if strict:
            raise browser.BrowserError(400, "bad_exit", why)
    if not browser.ID_RE.match(eid) or eid == browser.DIRECT:
        bad(f"bad exit id {eid!r}")
        return None
    if kind not in browser.EXIT_TYPES:
        bad(f"exit type: {', '.join(browser.EXIT_TYPES)}")
        return None
    out = {"id": eid, "name": browser._name(src.get("name")) or eid, "type": kind}
    if kind == "proxy":
        url = str(src.get("url") or "").strip()
        if url and "://" not in url:
            url = "socks5://" + url
        u = _parse_proxy(url)
        if u is None:
            bad("proxy: socks5://host:port or http://host:port")
            url = ""
        out.update(url=url, user=str(src.get("user") or "")[:200])
    elif kind == "tailscale":
        node = str(src.get("node") or "").strip()[:200]
        ls = str(src.get("login_server") or "").strip()[:300]
        if ls and not re.match(r"^https://[^\s/]+", ls):
            bad("login_server: an https:// address (Headscale)")
            ls = ""
        out.update(node=node, login_server=ls)
    return out


def _parse_proxy(url: str) -> tuple[str, str, int] | None:
    try:
        u = urlsplit(url)
        if u.scheme not in ("socks5", "socks5h", "http") or not u.hostname or not u.port:
            return None
        return ("http" if u.scheme == "http" else "socks5"), u.hostname, u.port
    except ValueError:
        return None


def exits(s: dict | None = None) -> list[dict]:
    return (s or browser.settings())["exits"]


def get(eid: str, s: dict | None = None) -> dict | None:
    return next((e for e in exits(s) if e["id"] == eid), None)


def set_exit(values: dict, eid: str | None = None, secret: str | None = None) -> dict:
    """Create (eid None) or change an exit; `secret` (a proxy's password, a WireGuard config, a Tailscale auth key)
    goes to the vault, never to config.json. Returns it."""
    from .. import vault
    with browser._slock:
        s = browser.settings()
        values = {k: v for k, v in (values or {}).items() if k in ("name", "type", "url", "user", "node", "login_server")}
        if eid is None:
            if len(s["exits"]) >= browser.MAX_EXITS:
                raise browser.BrowserError(409, "too_many", f"At most {browser.MAX_EXITS} exits")
            name = browser._name(values.get("name")) or str(values.get("type") or "exit")
            eid = browser.new_id(name, {e["id"] for e in s["exits"]} | {p["id"] for p in s["profiles"]})
            c = clean_exit({**values, "id": eid, "name": name}, strict=True)
            s["exits"].append(c)
        else:
            cur = get(eid, s)
            if cur is None:
                raise browser.BrowserError(404, "no_exit", "No such exit")
            values.pop("type", None)
            cur.update(clean_exit({**cur, **values}, strict=True) or {})
        if secret:
            try:
                vault.put(secret_name(eid), secret, note=f"Harness Browser: exit {eid}", expose=False)
            except vault.VaultError as e:
                raise browser.BrowserError(400, "bad_secret", str(e)) from None
        browser._save(s)
        runtime().forget(eid)
        return get(eid)  # type: ignore[return-value]


def delete_exit(eid: str) -> None:
    from .. import vault
    with browser._slock:
        s = browser.settings()
        if get(eid, s) is None:
            raise browser.BrowserError(404, "no_exit", "No such exit")
        users = [p["name"] or p["id"] for p in s["profiles"] if p["exit"] == eid]
        if users:
            raise browser.BrowserError(409, "in_use", "Used by the profile(s): " + ", ".join(users))
        s["exits"] = [e for e in s["exits"] if e["id"] != eid]
        browser._save(s)
        vault.delete(secret_name(eid))
        runtime().forget(eid)
        stop_unit_sync(eid)
        shutil.rmtree(browser.exits_dir() / eid, ignore_errors=True)


# ---- the upstream proxy ----------------------------------------------------------------------------------------------
@dataclass
class Upstream:
    kind: str                       # socks5 | http
    host: str
    port: int
    user: str = ""
    password: str = ""


async def open_via(up: Upstream | None, ip: str, port: int, timeout: float = CONNECT_TIMEOUT):
    """(reader, writer) of a TCP connection to ip:port, through the upstream (None = straight from this server)."""
    if up is None:
        return await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    r, w = await asyncio.wait_for(asyncio.open_connection(up.host, up.port), timeout)
    try:
        if up.kind == "http":
            auth = ""
            if up.user:
                tok = base64.b64encode(f"{up.user}:{up.password}".encode()).decode()
                auth = f"Proxy-Authorization: Basic {tok}\r\n"
            target = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
            w.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n{auth}\r\n".encode())
            await w.drain()
            head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), timeout)
            status = head.split(b" ", 2)[1:2]
            if status != [b"200"]:
                raise ConnectionError("the proxy refused: " + head.split(b"\r\n", 1)[0].decode("latin-1")[:80])
        else:
            await asyncio.wait_for(_socks5(r, w, up, ip, port), timeout)
        return r, w
    except BaseException:
        w.close()
        raise


async def _socks5(r: asyncio.StreamReader, w: asyncio.StreamWriter, up: Upstream, ip: str, port: int) -> None:
    w.write(b"\x05\x02\x00\x02" if up.user else b"\x05\x01\x00")
    await w.drain()
    ver, method = await r.readexactly(2)
    if ver != 5 or method == 0xFF:
        raise ConnectionError("the SOCKS proxy refused (authentication?)")
    if method == 2:
        u, p = up.user.encode()[:255], up.password.encode()[:255]
        w.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        await w.drain()
        if (await r.readexactly(2))[1] != 0:
            raise ConnectionError("the SOCKS proxy refused the user or password")
    addr = ipaddress.ip_address(ip)
    w.write(b"\x05\x01\x00" + (b"\x01" if addr.version == 4 else b"\x04") + addr.packed + struct.pack(">H", port))
    await w.drain()
    head = await r.readexactly(4)
    if head[1] != 0:
        raise ConnectionError(f"the SOCKS proxy could not connect (code {head[1]})")
    skip = {1: 4, 4: 16}.get(head[3])
    if skip is None:
        skip = (await r.readexactly(1))[0]
    await r.readexactly(skip + 2)


def _socks5_sync(sock: socket.socket, up: Upstream, ip: str, port: int) -> None:
    """The same handshake on a blocking socket (the Test, in a thread)."""
    def recv(n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError("the SOCKS proxy closed")
            out += chunk
        return out
    if up.kind == "http":
        auth = ""
        if up.user:
            auth = "Proxy-Authorization: Basic " + base64.b64encode(f"{up.user}:{up.password}".encode()).decode() + "\r\n"
        sock.sendall(f"CONNECT {ip}:{port} HTTP/1.1\r\nHost: {ip}:{port}\r\n{auth}\r\n".encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += recv(1)
        if head.split(b" ", 2)[1:2] != [b"200"]:
            raise ConnectionError("the proxy refused")
        return
    sock.sendall(b"\x05\x02\x00\x02" if up.user else b"\x05\x01\x00")
    ver, method = recv(2)
    if ver != 5 or method == 0xFF:
        raise ConnectionError("the SOCKS proxy refused (authentication?)")
    if method == 2:
        u, p = up.user.encode()[:255], up.password.encode()[:255]
        sock.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
        if recv(2)[1] != 0:
            raise ConnectionError("the SOCKS proxy refused the user or password")
    addr = ipaddress.ip_address(ip)
    sock.sendall(b"\x05\x01\x00" + (b"\x01" if addr.version == 4 else b"\x04") + addr.packed + struct.pack(">H", port))
    head = recv(4)
    if head[1] != 0:
        raise ConnectionError(f"the SOCKS proxy could not connect (code {head[1]})")
    skip = {1: 4, 4: 16}.get(head[3])
    recv((recv(1)[0] if skip is None else skip) + 2)


# ---- runtimes (tailscale, wireguard) -------------------------------------------------------------------------------
def _arch() -> str:
    import platform
    m = platform.machine().lower()
    return "arm64" if m in ("aarch64", "arm64") else "amd64"


def tools_dir() -> Path:
    return config.STATE / "tools"


def tailscale_bins() -> tuple[str, str] | None:
    """(tailscaled, tailscale): ours (maxxing browser setup --exits), else the system's."""
    d = tools_dir() / f"tailscale-{TAILSCALE_VERSION}"
    if (d / "tailscaled").is_file() and (d / "tailscale").is_file():
        return str(d / "tailscaled"), str(d / "tailscale")
    a, b = shutil.which("tailscaled"), shutil.which("tailscale")
    return (a, b) if a and b else None


def wireproxy_bin() -> str | None:
    p = tools_dir() / f"wireproxy-{WIREPROXY_VERSION}" / "wireproxy"
    return str(p) if p.is_file() else shutil.which("wireproxy")


def setup_tools(kinds: tuple[str, ...] = ("tailscale", "wireguard"), log_line=print) -> list[str]:
    """Download (checked against a pinned hash) what the exits need: tailscale, wireproxy."""
    import tarfile
    from .. import deps
    done: list[str] = []
    arch = _arch()
    if "tailscale" in kinds and not tailscale_bins():
        d = tools_dir() / f"tailscale-{TAILSCALE_VERSION}"
        with deps.work_dir() as w:
            log_line("Downloading Tailscale...")
            f = deps.fetch_verified(f"https://pkgs.tailscale.com/stable/tailscale_{TAILSCALE_VERSION}_{arch}.tgz",
                                    TAILSCALE_SHA[arch], w / "ts.tgz")
            with tarfile.open(f) as t:
                for m in t.getmembers():
                    name = m.name.rsplit("/", 1)[-1]
                    if name in ("tailscale", "tailscaled") and m.isfile():
                        d.mkdir(parents=True, exist_ok=True)
                        with t.extractfile(m) as src, open(d / name, "wb") as dst:  # type: ignore[union-attr]
                            shutil.copyfileobj(src, dst)
                        os.chmod(d / name, 0o755)
        done.append(f"Tailscale {TAILSCALE_VERSION}")
    if "wireguard" in kinds and not wireproxy_bin():
        d = tools_dir() / f"wireproxy-{WIREPROXY_VERSION}"
        with deps.work_dir() as w:
            log_line("Downloading wireproxy...")
            f = deps.fetch_verified(f"https://github.com/windtf/wireproxy/releases/download/v{WIREPROXY_VERSION}/"
                                    f"wireproxy_linux_{arch}.tar.gz", WIREPROXY_SHA[arch], w / "wp.tgz")
            with tarfile.open(f) as t:
                m = next(x for x in t.getmembers() if x.name.rsplit("/", 1)[-1] == "wireproxy" and x.isfile())
                d.mkdir(parents=True, exist_ok=True)
                with t.extractfile(m) as src, open(d / "wireproxy", "wb") as dst:  # type: ignore[union-attr]
                    shutil.copyfileobj(src, dst)
                os.chmod(d / "wireproxy", 0o755)
        done.append(f"wireproxy {WIREPROXY_VERSION}")
    return done


def unit_name(eid: str) -> str:
    import hashlib
    return UNIT_PREFIX + hashlib.sha256(str(config.state_dir().resolve()).encode()).hexdigest()[:6] + "-" + eid


def _direct() -> bool:
    return os.environ.get("MAXXING_BROWSER_LAUNCH") == "direct" or not shutil.which("systemd-run")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _unit_active(eid: str) -> bool:
    if _direct():
        return eid in _procs and _procs[eid].poll() is None
    r = subprocess.run(["systemctl", "is-active", "--quiet", unit_name(eid)], capture_output=True)
    return r.returncode == 0


_procs: dict[str, subprocess.Popen] = {}


def _start_unit(eid: str, argv: list[str], what: str) -> None:
    if _direct():
        _procs[eid] = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
        return
    cmd = ["systemd-run", "--quiet", "--collect", "--unit", unit_name(eid), "--description",
           f"Harness Maxxing: browser exit {eid} ({what})", "-p", "MemoryMax=256M", "-p", "Restart=on-failure",
           "-p", "NoNewPrivileges=yes", "-p", "ProtectHome=yes", "-p", "PrivateTmp=yes", *argv]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "").strip()[-300:] or "systemd-run failed")


def stop_unit_sync(eid: str) -> None:
    p = _procs.pop(eid, None)
    if p is not None:
        with contextlib.suppress(Exception):
            os.killpg(p.pid, 15)
        return
    if not _direct():
        subprocess.run(["systemctl", "stop", unit_name(eid)], capture_output=True, timeout=30)


def _dir(eid: str) -> Path:
    d = browser.exits_dir() / eid
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _port(eid: str) -> int | None:
    try:
        return int((_dir(eid) / "port").read_text())
    except (OSError, ValueError):
        return None


class Tailscale:
    """A `tailscaled` of the browser's own (userspace networking: no network interface, nothing else of this server
    goes through it), its state and socket in <state>/browser/exits/<id>/, its SOCKS5 server on the loopback."""

    _ups: dict[str, subprocess.Popen] = {}         # the `tailscale up` running per exit (one at a time)

    @staticmethod
    def sock(eid: str) -> Path:
        return _dir(eid) / "tailscaled.sock"

    @classmethod
    def ensure(cls, e: dict) -> int:
        """Start it when needed; its SOCKS port."""
        eid = e["id"]
        port = _port(eid)
        if port and _unit_active(eid):
            return port
        bins = tailscale_bins()
        if not bins:
            raise ExitDown("Tailscale is not installed on this server (Browser page -> the exit -> Set up)")
        port = _free_port()
        (_dir(eid) / "port").write_text(str(port))
        stop_unit_sync(eid)
        _start_unit(eid, [bins[0], "--tun=userspace-networking", f"--socks5-server=127.0.0.1:{port}",
                          f"--statedir={_dir(eid)}", f"--socket={cls.sock(eid)}", "--port=0",
                          "--no-logs-no-support"], "Tailscale")
        for _ in range(40):
            if cls.sock(eid).exists():
                break
            time.sleep(0.25)
        return port

    @classmethod
    def cli(cls, eid: str, *args: str, timeout: float = 20) -> subprocess.CompletedProcess:
        bins = tailscale_bins()
        if not bins:
            raise ExitDown("Tailscale is not installed")
        return subprocess.run([bins[1], f"--socket={cls.sock(eid)}", *args], capture_output=True, text=True,
                              timeout=timeout)

    @classmethod
    def status(cls, e: dict) -> dict:
        """{state: needs_setup|needs_login|no_node|node_offline|up|starting, auth_url, account, nodes, node, unapproved}.

        unapproved: phones / computers online in the account that are not offered as exit nodes: "Run as exit node"
        not switched on yet, or (most often) switched on but not approved in the Tailscale admin console."""
        eid = e["id"]
        if not tailscale_bins():
            return {"state": "needs_setup"}
        try:
            cls.ensure(e)
            r = cls.cli(eid, "status", "--json", timeout=10)
            st = json.loads(r.stdout or "{}")
        except (ExitDown, OSError, ValueError, subprocess.SubprocessError, RuntimeError) as ex:
            return {"state": "starting", "error": str(ex)[:200]}
        backend = st.get("BackendState")
        out: dict = {"backend": backend, "auth_url": st.get("AuthURL") or "",
                     "account": ((st.get("User") or {}).get(str((st.get("Self") or {}).get("UserID") or "")) or {})
                     .get("LoginName", ""), "nodes": [], "unapproved": []}
        for p in (st.get("Peer") or {}).values():
            if not p.get("ExitNodeOption") and p.get("Online") and (p.get("OS") or "").lower() != "linux":
                out["unapproved"].append({"name": p.get("HostName") or "", "os": p.get("OS") or ""})
            if p.get("ExitNodeOption"):
                out["nodes"].append({"id": (p.get("TailscaleIPs") or [""])[0], "name": p.get("HostName") or "",
                                     "dns": (p.get("DNSName") or "").rstrip("."), "os": p.get("OS") or "",
                                     "online": bool(p.get("Online")), "active": bool(p.get("ExitNode"))})
        ens = st.get("ExitNodeStatus") or {}
        out["node"] = next((n for n in out["nodes"] if n["active"]), None)
        if backend in ("NeedsLogin", "NoState", "Stopped", None) or out["auth_url"]:
            out["state"] = "needs_login"
            if not out["auth_url"]:
                cls.login(e)
        elif backend == "Starting":
            out["state"] = "starting"
        elif not ens:
            out["state"] = "no_node"
        elif not ens.get("Online"):
            out["state"] = "node_offline"
        else:
            out["state"] = "up"
        return out

    @classmethod
    def login(cls, e: dict) -> None:
        """`tailscale up` in the background: it gets a sign-in address (status -> auth_url) or signs in with the
        auth key of the vault."""
        from .. import vault
        eid = e["id"]
        bins = tailscale_bins()
        if not bins:
            return
        running = cls._ups.get(eid)
        if running is not None and running.poll() is None:
            return                                  # the wizard asks every few seconds: one `up` is enough
        args = [bins[1], f"--socket={cls.sock(eid)}", "up", f"--hostname={HOSTNAME}", "--accept-dns=false",
                "--accept-routes=false", "--shields-up", "--timeout=120s"]
        if e.get("login_server"):
            args.append(f"--login-server={e['login_server']}")
        key = vault.get(secret_name(eid))
        if key:
            f = _dir(eid) / "authkey"
            f.write_text(key)
            os.chmod(f, 0o600)
            args.append(f"--auth-key=file:{f}")
        if e.get("node"):
            args += [f"--exit-node={e['node']}", "--exit-node-allow-lan-access=false"]
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        cls._ups[eid] = proc
        if key:
            def forget_key() -> None:               # the key stays in the vault only
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=180)
                with contextlib.suppress(OSError):
                    (_dir(eid) / "authkey").unlink()
            threading.Thread(target=forget_key, daemon=True).start()

    @classmethod
    def use_node(cls, e: dict, node: str) -> None:
        r = cls.cli(e["id"], "set", f"--exit-node={node}", "--exit-node-allow-lan-access=false")
        if r.returncode != 0:
            raise browser.BrowserError(400, "bad_node", (r.stderr or r.stdout or "").strip()[:300] or "refused")

    @classmethod
    def logout(cls, e: dict) -> None:
        with contextlib.suppress(Exception):
            cls.cli(e["id"], "logout")


class WireGuard:
    """`wireproxy`: the box's WireGuard config (from the vault) with a SOCKS5 server on the loopback."""

    @classmethod
    def ensure(cls, e: dict) -> int:
        from .. import vault
        eid = e["id"]
        port = _port(eid)
        if port and _unit_active(eid):
            return port
        binp = wireproxy_bin()
        if not binp:
            raise ExitDown("wireproxy is not installed on this server (Browser page -> the exit -> Set up)")
        conf = vault.get(secret_name(eid))
        if not conf or "[Interface]" not in conf:
            raise ExitDown("No WireGuard config for this exit yet")
        port = _free_port()
        (_dir(eid) / "port").write_text(str(port))
        f = _dir(eid) / "wireproxy.conf"
        f.write_text(conf.strip() + f"\n\n[Socks5]\nBindAddress = 127.0.0.1:{port}\n")
        os.chmod(f, 0o600)
        stop_unit_sync(eid)
        _start_unit(eid, [binp, "-c", str(f)], "WireGuard")
        time.sleep(1.0)
        return port


# ---- state of the exits ----------------------------------------------------------------------------------------------
class Runtime:
    """What is known of each exit: up / down since when, the last test, the profiles' turns waiting for it."""

    def __init__(self) -> None:
        self.state: dict[str, dict] = {}
        self.tests: dict[str, dict] = _load_tests()     # the last test of each exit survives a restart
        self._up: dict[str, tuple[float, Upstream]] = {}
        self._down: dict[str, tuple[float, str]] = {}      # the last ExitDown of each exit, kept DOWN_KEEP s
        self._making: dict[str, threading.Lock] = {}       # one _upstream at a time per exit: the others wait for it
        self._task: asyncio.Task | None = None
        self._refreshing: set[str] = set()

    def forget(self, eid: str) -> None:
        self.state.pop(eid, None)
        if self.tests.pop(eid, None) is not None:
            _save_tests(self.tests)
        self._up.pop(eid, None)
        self._down.pop(eid, None)

    def _keep_test(self, eid: str, out: dict) -> None:
        old = self.tests.get(eid) or {}
        if out.get("ok") and "mbps" not in out and old.get("ok") and old.get("mbps") is not None:
            out = {**out, "mbps": old["mbps"]}         # a quick test keeps the speed of the last full one
        self.tests[eid] = out
        _save_tests(self.tests)
        bus.invalidate("browser")

    def refresh_seen(self, exits: list[dict]) -> None:
        """Someone is looking at these exits: check the ones not checked for SEEN_FRESH s, and test again the address
        of those whose last test is missing, failed or older than RETEST_EVERY s - in the background, once at a time,
        so a connection that is up reads up without pressing Test. Never raises; no event loop = nothing."""
        loop = bus._loop
        if loop is None:
            return
        now = time.time()
        for eid in [browser.DIRECT] + [e["id"] for e in exits]:
            st, tst = self.state.get(eid) or {}, self.tests.get(eid) or {}
            age = now - float(tst.get("at") or 0)
            stale_test = age > (RETEST_EVERY if tst.get("ok") else SEEN_FRESH)
            stale_state = eid != browser.DIRECT and now - float(st.get("at") or 0) >= SEEN_FRESH
            if eid in self._refreshing or not (stale_state or stale_test):
                continue
            self._refreshing.add(eid)
            asyncio.run_coroutine_threadsafe(self._refresh(eid, stale_test), loop)

    async def _refresh(self, eid: str, stale_test: bool) -> None:
        try:
            if eid == browser.DIRECT:
                await self.test(None, speed=False)
            elif await self.check(eid) and stale_test:
                await self.test(eid, speed=False)
        except Exception:  # noqa: BLE001 - a background check
            log.exception("browser exit refresh")
        finally:
            self._refreshing.discard(eid)

    def upstream(self, e: dict) -> Upstream:
        """The exit as an upstream proxy (starts its runtime; kept UPSTREAM_KEEP s while it works: the proxy asks for
        each connection). ExitDown when it cannot carry traffic. A page opens dozens of connections at once: they share
        one computation (Tailscale runs commands), and an exit found down is not asked again for DOWN_KEEP s."""
        eid = e["id"]
        up = self._known(eid)
        if up is not None:
            return up
        with self._making.setdefault(eid, threading.Lock()):
            up = self._known(eid)
            if up is not None:
                return up
            try:
                up = self._upstream(e)
            except ExitDown as ex:
                self._down[eid] = (time.time(), str(ex))
                raise
            self._down.pop(eid, None)
            self._up[eid] = (time.time(), up)
            return up

    def _known(self, eid: str) -> Upstream | None:
        """The upstream kept for this exit, None to compute it; ExitDown again while its last one is recent."""
        hit = self._up.get(eid)
        if hit and time.time() - hit[0] < UPSTREAM_KEEP and (self.state.get(eid) or {}).get("ok", True):
            return hit[1]
        down = self._down.get(eid)
        if down and time.time() - down[0] < DOWN_KEEP:
            raise ExitDown(down[1])
        return None

    def _upstream(self, e: dict) -> Upstream:
        from .. import vault
        kind = e["type"]
        if kind == "proxy":
            p = _parse_proxy(e.get("url") or "")
            if p is None:
                raise ExitDown("This proxy has no address yet")
            return Upstream(p[0], p[1], p[2], e.get("user") or "", vault.get(secret_name(e["id"])) or "")
        if kind == "tailscale":
            st = Tailscale.status(e)
            if st["state"] != "up":
                raise ExitDown(_TS_WHY.get(st["state"], "the Tailscale exit is not ready"))
            return Upstream("socks5", "127.0.0.1", Tailscale.ensure(e))
        if kind == "wireguard":
            return Upstream("socks5", "127.0.0.1", WireGuard.ensure(e))
        raise ExitDown("unknown exit")

    async def check(self, eid: str) -> bool:
        """Does it carry traffic now? Updates its state (and tells the UI when that changed)."""
        e = get(eid)
        if e is None:
            return False
        t0 = time.monotonic()
        why = ""
        self._down.pop(eid, None)                          # a check (Retry now, Test) always asks the exit again
        try:
            up = await asyncio.to_thread(self.upstream, e)
            r, w = await open_via(up, *CHECK_HOST, timeout=10)
            w.close()
        except (ExitDown, OSError, ConnectionError, asyncio.TimeoutError, asyncio.IncompleteReadError) as ex:
            why = str(ex) or type(ex).__name__
        if self.mark(eid, not why, why, int((time.monotonic() - t0) * 1000)) and not why:
            await asyncio.to_thread(_resume_waiters, eid)
        return not why

    def mark(self, eid: str, ok: bool, why: str = "", ms: int | None = None) -> bool:
        """Record its state; True when it changed."""
        cur = self.state.get(eid) or {}
        changed = cur.get("ok") != ok
        if not ok:
            self._up.pop(eid, None)
        self.state[eid] = {"ok": ok, "since": time.time() if changed else cur.get("since", time.time()),
                           "error": why[:300], "latency_ms": ms if ok else None, "at": time.time()}
        if changed:
            bus.invalidate("browser")
        return changed

    def public(self, e: dict) -> dict:
        st = self.state.get(e["id"]) or {}
        out = {**e, "state": "up" if st.get("ok") else ("down" if st else "unknown"), "since": st.get("since"),
               "error": st.get("error") or "", "latency_ms": st.get("latency_ms"), "test": self.tests.get(e["id"]),
               "secret": bool(_has_secret(e["id"])), "checking": e["id"] in self._refreshing}
        return out

    async def test(self, eid: str | None, speed: bool = True) -> dict:
        """The address the sites see through this exit (None / "direct": the server's own), its country, operator and
        kind (an internet provider, a mobile network or a datacenter: ip-api.com), the delay and a download speed."""
        e = get(eid) if eid and eid != browser.DIRECT else None
        if eid and eid != browser.DIRECT and e is None:
            raise browser.BrowserError(404, "no_exit", "No such exit")
        try:
            up = await asyncio.to_thread(self.upstream, e) if e else None
        except ExitDown as ex:
            if e:
                self.mark(e["id"], False, str(ex))
            out = {"ok": False, "error": str(ex), "at": time.time()}
            self._keep_test(eid or browser.DIRECT, out)
            return out
        out = await asyncio.to_thread(_test_sync, up, speed)
        self._keep_test(eid or browser.DIRECT, out)
        if e and self.mark(e["id"], out["ok"], out.get("error") or "", out.get("latency_ms")) and out["ok"]:
            await asyncio.to_thread(_resume_waiters, e["id"])
        return out

    # ---- the watcher ---------------------------------------------------------------------------------------------
    def watch(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(CHECK_EVERY)
            try:
                wanted = {w["exit"] for w in _waiters()} | set(_in_use())
                for eid in wanted:
                    await self.check(eid)
            except Exception:  # noqa: BLE001
                log.exception("browser exits watcher")


_TS_WHY = {"needs_setup": "Tailscale is not installed on this server",
           "needs_login": "this server is not signed in to Tailscale yet",
           "no_node": "no exit node chosen (the phone or box)", "node_offline": "the phone / box is offline",
           "starting": "Tailscale is starting"}


def _has_secret(eid: str) -> bool:
    from .. import vault
    return bool(vault.get(secret_name(eid)))


def _in_use() -> list[str]:
    """Exits of the profiles running now."""
    from .pool import pool
    s = browser.settings()
    out = []
    for pid in pool().browsers:
        p = browser.profile(pid, s)
        if p and p["exit"] != browser.DIRECT:
            out.append(p["exit"])
    return out


def _tests_file() -> Path:
    return browser.home() / "exit-tests.json"


def _load_tests() -> dict:
    with contextlib.suppress(Exception):
        d = json.loads(_tests_file().read_text())
        if isinstance(d, dict):
            return {k: v for k, v in d.items() if isinstance(v, dict)}
    return {}


def _save_tests(tests: dict) -> None:
    with contextlib.suppress(Exception):
        config.write_json(_tests_file(), tests)


def _test_sync(up: Upstream | None, speed: bool = True) -> dict:
    t0 = time.monotonic()
    out: dict = {"ok": False, "at": time.time()}
    try:
        ip = socket.getaddrinfo("ip-api.com", 80, type=socket.SOCK_STREAM)[0][4][0]
        with _sock(up, ip, 80) as s:
            out["latency_ms"] = int((time.monotonic() - t0) * 1000)
            u = urlsplit(TEST_IP_URL)
            s.sendall(f"GET {u.path}?{u.query} HTTP/1.1\r\nHost: ip-api.com\r\nConnection: close\r\n\r\n".encode())
            body = _read_all(s, 65536).split(b"\r\n\r\n", 1)[-1]
        d = json.loads(body or b"{}")
        if d.get("status") != "success":
            raise ConnectionError(d.get("message") or "no answer")
        out.update(ok=True, ip=d.get("query"), country=d.get("country"), country_code=d.get("countryCode"),
                   city=d.get("city"), operator=d.get("isp") or d.get("org"), asn=(d.get("as") or "").split(" ", 1)[0],
                   kind="mobile" if d.get("mobile") else "hosting" if d.get("hosting") or d.get("proxy") else "isp")
    except (OSError, ValueError, ConnectionError) as ex:
        out["error"] = str(ex) or type(ex).__name__
        return out
    if not speed:
        return out
    try:                                              # the speed: 2 MB from a CDN, over TLS
        host, path = TEST_SPEED
        ip = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)[0][4][0]
        t1 = time.monotonic()
        with _sock(up, ip, 443) as raw, ssl.create_default_context().wrap_socket(raw, server_hostname=host) as s:
            s.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
            n = len(_read_all(s, 3_000_000))
        secs = max(time.monotonic() - t1, 0.001)
        out["mbps"] = round(n * 8 / secs / 1e6, 1)
    except (OSError, ConnectionError, ssl.SSLError):
        pass
    return out


@contextlib.contextmanager
def _sock(up: Upstream | None, ip: str, port: int):
    s = socket.create_connection((up.host, up.port) if up else (ip, port), timeout=CONNECT_TIMEOUT)
    try:
        s.settimeout(30)
        if up:
            _socks5_sync(s, up, ip, port)
        yield s
    finally:
        s.close()


def _read_all(s: socket.socket, cap: int) -> bytes:
    out = bytearray()
    while len(out) < cap:
        chunk = s.recv(65536)
        if not chunk:
            break
        out += chunk
    return bytes(out)


_runtime: Runtime | None = None


def runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
    return _runtime


# ---- turns waiting for an exit ---------------------------------------------------------------------------------------
def _waiting_file() -> Path:
    return browser.home() / "waiting.json"


_wcache: tuple[float, list[dict]] = (0.0, [])
_wlock = config.ProcessLock("browser-waiting")  # waiting.json: read, change, write (routes, the runner, the watch)


def _waiters() -> list[dict]:
    """The turns waiting for an exit (read again only when the file changed: the session list asks for each)."""
    global _wcache
    f = _waiting_file()
    try:
        mtime = f.stat().st_mtime
    except OSError:
        return []
    if mtime != _wcache[0]:
        try:
            d = json.loads(f.read_text())
            items = [w for w in d if isinstance(w, dict) and w.get("session") and w.get("exit")] \
                if isinstance(d, list) else []
        except (OSError, ValueError, RecursionError):   # RecursionError: JSON nested too deep
            items = []
        _wcache = (mtime, items)
    return [dict(w) for w in _wcache[1]]


def _save_waiters(items: list[dict]) -> None:
    browser.home().mkdir(parents=True, exist_ok=True)
    config.write_json(_waiting_file(), items[-50:])


def waiting_for(sid: str) -> dict | None:
    return next((w for w in _waiters() if w["session"] == sid), None)


def wait_down(sid: str, owner: str, e: dict, profile: dict) -> None:
    """A turn stopped because its profile's exit is down: remember it (the session shows a card), tell the user once
    per exit going down (Notifications: Retry now / Go on when it is back)."""
    with _wlock:
        items = [w for w in _waiters() if w["session"] != sid]
        items.append({"session": sid, "owner": owner, "exit": e["id"], "profile": profile["id"], "at": time.time(),
                      "resume": False})
        _save_waiters(items)
    bus.invalidate("browser", "sessions")
    who = browser.owner_path(owner).rsplit("/", 1)[-1]
    try:
        from .. import feed
        feed.post(f"Browser exit offline: {e['name']}",
                  f"Profile {profile['name'] or profile['id']} waits for it ({who}). The browser never switches to "
                  "this server's address on its own.", "warning", "health", "/settings/browser",
                  dedupe=f"browserexit:{e['id']}:{int(runtime().state.get(e['id'], {}).get('since') or 0)}",
                  ref=f"browserexit:{e['id']}",
                  agent=browser.owner_path(owner) if owner.startswith("agent:") else None,
                  actions=[{"id": "retry", "label": "Retry now", "style": "default"},
                           {"id": "resume", "label": "Go on when it is back", "style": "primary"}])
    except Exception:  # noqa: BLE001 - the feed is a nicety
        log.exception("feed event for a browser exit failed")


def set_resume(sid: str | None = None, eid: str | None = None, on: bool = True) -> int:
    """Go on when it is back (a session's card, or every turn waiting for that exit)."""
    with _wlock:
        items = _waiters()
        n = 0
        for w in items:
            if (sid and w["session"] == sid) or (eid and w["exit"] == eid):
                w["resume"] = on
                n += 1
        _save_waiters(items)
    bus.invalidate("browser", "sessions")
    return n


def drop_waiter(sid: str) -> None:
    with _wlock:
        items = [w for w in _waiters() if w["session"] != sid]
        _save_waiters(items)
    bus.invalidate("browser", "sessions")


def _resume_waiters(eid: str) -> None:
    """The exit is back: the turns that asked to go on get a message (as typed in their session); the others only
    lose their card."""
    keep, go = [], []
    with _wlock:
        for w in _waiters():
            (go if w["exit"] == eid else keep).append(w)
        if not go:
            return
        _save_waiters(keep)
    bus.invalidate("browser", "sessions")
    from ..sessions import service, store
    for w in go:
        if not w.get("resume"):
            continue
        m = store.read(w["session"])
        if not m or m.get("state") == "running":
            continue
        try:
            service.send_message(w["session"], "[Harness Maxxing] The browser's exit is back online: go on with what "
                                 "you were doing in the browser.", None, "browser")
        except Exception:  # noqa: BLE001
            log.exception("resuming a session after its browser exit came back")
    with contextlib.suppress(Exception):
        from .. import feed
        feed.resolve(f"browserexit:{eid}", "Back online")


def feed_action(eid: str, action: str, by: str, ev: dict) -> None:
    """Buttons of the "exit offline" notification: test now, go on (every waiting turn) when it is back."""
    if action == "resume":
        set_resume(eid=eid)
    elif action == "retry":
        loop = bus._loop
        if loop is not None:
            asyncio.run_coroutine_threadsafe(runtime().check(eid), loop)
