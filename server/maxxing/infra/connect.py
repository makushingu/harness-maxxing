"""Connect another server so the Infra page reads its sites and databases over SSH.

- A Hostinger VPS (seen through the Hostinger API) whose root `authorized_keys` already holds one of this server's
  public keys (`~/.ssh/*.pub`, or the Harness key) is connected on its own at a refresh (`auto_connect`): the API
  says which key, so nothing is tried blindly (no failed logins for fail2ban). Read-only, at most every 6 hours.
- Otherwise the Connect button (`connect_hostinger`) adds the Harness key `<state>/ssh/infra_ed25519.pub` to the
  VPS through the API (the only write of the Infra page on a provider), waits for it, and registers the server.
- Any other server (`connect_host`): try the Harness key, then the default SSH keys; when none works, give back the
  line to paste in its `authorized_keys`.

The name of a connected server is its short host name (`srv100200`, part of the resource ids, never changes); its
label is "VPS Hostinger" for a Hostinger VPS (renamed at will).
"""
from __future__ import annotations

import contextlib
import socket
import subprocess
import threading
import time

import httpx
from pathlib import Path

from .. import config
from . import build, providers, registry

KEY_FILE = "infra_ed25519"
AUTO_EVERY_S = 6 * 3600
ADD_WAIT_S = 60
MAX_CONNECTS = 2                       # connects running at once (each can wait ADD_WAIT_S for a new key)
_key_lock = threading.Lock()
_targets_lock = threading.Lock()
_targets: set[str] = set()             # hosts / VPS ids being connected right now
SSH_TIMEOUT = 20
HOSTINGER_LABEL = "VPS Hostinger"


class ConnectError(Exception):
    def __init__(self, message: str, code: str = "failed", **extra):
        super().__init__(message)
        self.code, self.extra = code, extra


# ---- keys ---------------------------------------------------------------------------------------
def key_path() -> Path:
    return config.STATE / "ssh" / KEY_FILE


def ensure_key() -> tuple[Path, str]:
    """The Harness SSH key of this server (made once - never twice at the same time), and its public line."""
    k = key_path()
    with _key_lock:
        try:
            if not k.is_file():
                k.parent.mkdir(parents=True, exist_ok=True)
                k.parent.chmod(0o700)
                subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C",
                                f"harness-maxxing@{socket.gethostname()}", "-f", str(k)],
                               check=True, capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
            return k, k.with_suffix(".pub").read_text().strip()
        except (OSError, subprocess.SubprocessError) as e:
            raise ConnectError(f"could not make this server's SSH key: {type(e).__name__}", "no_key") from e


@contextlib.contextmanager
def _connecting(target: str):
    """One connect per target at a time (a second tab, the CLI, the refresh), and at most MAX_CONNECTS at once."""
    with _targets_lock:
        if target in _targets:
            raise ConnectError("this server is being connected already", "in_progress")
        if len(_targets) >= MAX_CONNECTS:
            raise ConnectError("other servers are being connected - try again in a minute", "busy")
        _targets.add(target)
    try:
        yield
    finally:
        with _targets_lock:
            _targets.discard(target)


def _pub_id(line: str) -> str:
    """`ssh-ed25519 AAAA... comment` -> `ssh-ed25519 AAAA...` (what identifies a key)."""
    parts = line.split()
    return " ".join(parts[:2]) if len(parts) >= 2 else ""


def local_keys() -> dict[str, Path]:
    """Public key -> private key file, for the keys this server can log in with (never reads a private key)."""
    out: dict[str, Path] = {}
    for pub in [key_path().with_suffix(".pub"), *sorted((Path.home() / ".ssh").glob("*.pub"))]:
        priv = pub.with_suffix("")
        try:
            if priv.is_file() and pub.is_file():
                out.setdefault(_pub_id(pub.read_text()), priv)
        except OSError:
            continue
    out.pop("", None)
    return out


def can_login(host: str, user: str = "root", port: int = 22, key: str = "") -> str | None:
    """None when `ssh user@host true` works with that key (or the default keys), else the error."""
    from . import ssh_command
    try:
        r = subprocess.run(ssh_command({"host": host, "user": user, "port": port, "key": key}, "true"),
                           capture_output=True, text=True, timeout=SSH_TIMEOUT, errors="replace")
    except subprocess.TimeoutExpired:
        return "no answer"
    except OSError as e:
        return f"ssh: {e}"
    return None if r.returncode == 0 else ((r.stderr.strip().splitlines() or [f"ssh exited with {r.returncode}"])[-1][:300])


# ---- Hostinger ----------------------------------------------------------------------------------
def _registered_ips() -> set[str]:
    from . import load_snapshot
    names = {s["name"] for s in registry.servers()}
    ips = {s["host"] for s in registry.servers()}
    for r in (load_snapshot() or {}).get("resources") or []:   # their other IPs, as last read (still registered only)
        if r["kind"] == "server" and r["location"] in names:
            ips.update(r["details"].get("ips") or [])
    return ips


def _vps_host(v: dict) -> str:
    ips = v.get("ips") or []
    return next((i for i in ips if ":" not in i), ips[0] if ips else "")


def _label(base: str = HOSTINGER_LABEL) -> str:
    taken = {s.get("label") for s in registry.servers()}
    if base not in taken:
        return base
    n = 2
    while f"{base} {n}" in taken:
        n += 1
    return f"{base} {n}"


def _register_vps(v: dict, key: Path, label: str = "") -> dict:
    name = registry.free_name(v.get("hostname") or "vps-hostinger")
    return registry.add_server(name, _vps_host(v), "root", 22, str(key), label=label or _label())


def _matching_key(vm_id) -> Path | None:
    mine = local_keys()
    return next((mine[k] for k in providers.hostinger_ssh_keys(vm_id) if k in mine), None)


def auto_connect(hvps: list[dict]) -> list[dict]:
    """Connect the running Hostinger VPS that already accept one of our keys. Returns the servers added."""
    added: list[dict] = []
    if not isinstance(hvps, list):
        return added
    seen_path = config.STATE / "infra" / "autoconnect.json"
    seen = config.read_json(seen_path, {}) or {}
    known = _registered_ips()
    now = time.time()
    for v in hvps:
        vid = str(v.get("id"))
        if v.get("state") != "running" or set(v.get("ips") or []) & known or now - seen.get(vid, 0) < AUTO_EVERY_S:
            continue
        seen[vid] = now
        try:
            with _connecting(f"server:hostinger:{vid}"):     # not while the Connect button does the same
                key = _matching_key(vid)
                if key and _vps_host(v) not in _registered_ips() and can_login(_vps_host(v), key=str(key)) is None:
                    added.append(_register_vps(v, key))
        except (providers.ProviderError, registry.RegistryError, ConnectError, OSError):
            continue
    config.write_json(seen_path, seen)
    return added


def _hostinger_vps(rid: str) -> dict:
    from . import load_snapshot
    for r in (load_snapshot() or {}).get("resources") or []:
        if r["id"] == rid and r["details"].get("hostinger"):
            return r["details"]["hostinger"]
    raise ConnectError("this Hostinger VPS is not in the inventory (refresh the page)", "not_found")


def connect_hostinger(rid: str, label: str = "") -> dict:
    """Connect `server:hostinger:<id>`: with a key it already accepts, else by adding the Harness key."""
    with _connecting(rid):
        return _connect_hostinger(rid, label)


def _connect_hostinger(rid: str, label: str) -> dict:
    v = _hostinger_vps(rid)
    host = _vps_host(v)
    if not host:
        raise ConnectError("this VPS has no IP address", "no_ip")
    if host in _registered_ips():
        raise ConnectError("this VPS is already connected", "exists")
    try:
        key = _matching_key(v["id"])
        if key and can_login(host, key=str(key)) is None:
            return {**_register_vps(v, key, label), "via": "existing_key"}
        key, pub = ensure_key()
        providers.hostinger_add_ssh_key(v["id"], pub)
    except providers.ProviderError as e:
        raise ConnectError(f"Hostinger: {e.message}", e.code) from e
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        raise ConnectError(f"Hostinger unreachable or odd answer ({type(e).__name__})", "hostinger_error") from e
    deadline, err = time.time() + ADD_WAIT_S, None
    while time.time() < deadline:
        err = can_login(host, key=str(key))
        if err is None:
            return {**_register_vps(v, key, label), "via": "added_key"}
        time.sleep(5)
    raise ConnectError(f"the key was added to the VPS but SSH still refuses it: {err}", "ssh_refused")


# ---- any server ---------------------------------------------------------------------------------
def connect_host(host: str, user: str = "root", port: int = 22, label: str = "") -> dict:
    """Connect a server by address. When no key works: ConnectError(code="need_key") with the line to paste."""
    registry.check_server("x", host, user, port)
    with _connecting(host):
        return _connect_host(host, user, port, label)


def _connect_host(host: str, user: str, port: int, label: str) -> dict:
    if host in _registered_ips():
        raise ConnectError("this server is already connected", "exists")
    key, pub = ensure_key()
    for k in (str(key), ""):
        if can_login(host, user, port, k) is None:
            name = registry.free_name(label or ("server" if build.is_ip(host) else host))
            return {**registry.add_server(name, host, user, port, k, label=label), "via": "existing_key" if k == "" else "harness_key"}
    raise ConnectError("no SSH key of this server is accepted there yet", "need_key", public_key=pub,
                       command=f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo 'no-agent-forwarding,no-X11-forwarding {pub}' >> ~/.ssh/authorized_keys"
                               " && chmod 600 ~/.ssh/authorized_keys")
