"""Team between servers: connections, signed requests, delivery. See docs/dev/INTERNALS.md#maxxing.teampeer.

Every Harness talks straight to the others over HTTPS - no server in between, ours included. Standard library only.

Connecting (one-time invitation, the code never travels):
  A: create_invite() -> "<A address>#<code>" (32 random bytes, 15 min, one use), sent by A through a channel A trusts.
  B: join(invitation) -> POST A/api/team-peer/hello {from, to, nonce_b, proof = HMAC(code, hello|from|to|nonce_b),
     profile}. A finds the open invitation the proof matches, consumes it, answers {nonce_a, proof_a, profile}.
     Both derive the link key K = HMAC(code, key|A|B|nonce_a|nonce_b) and show the same fingerprint (sha256(K)).
  A sees a request and accepts it (or refuses): the `accept` event, signed with K, is delivered at once - an address
  B lied about cannot answer it, so the contact is not created.
Requests between servers: headers X-Team-From / -Time / -Nonce / -Sig, Sig = HMAC(K, method|path|from|to|time|nonce|
sha256(body)); refused when the time is off by more than 5 min, the nonce was seen, or no key of that sender checks.
Groups (no host): the creator sends the group to every member with, for each other member, a key for that pair (unless
they are already contacts: a key handed by someone else is never stored for a contact); each member then sends its
events straight to every other member. A group key only signs messages, votes and reactions of its own group, and only
its files: never contact events (accept, refuse, bye, profile) nor a group change.
Files stay on the sender's server: the event carries their ids, every member downloads them with a signed GET.
Outgoing requests go only to https addresses with public IPs (`team_insecure` / MAXXING_TEAM_INSECURE=1: local tests).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import bus, config

log = logging.getLogger("maxxing.teampeer")

INVITE_TTL = 15 * 60
CLOCK_SKEW = 300
NONCE_TTL = 15 * 60
TIMEOUT = 10.0
RETRY = (10, 30, 60, 300, 900, 3600, 3 * 3600, 6 * 3600)   # seconds before each new try
OUTBOX_DAYS = 7
HELLO_FAILS = 5                                            # wrong invitations per IP and hour, then refused
INBOX_PER_MIN = 240                                        # requests per sender IP and minute

_lock = threading.RLock()
_nonces: dict[str, float] = {}
_fails: dict[str, list[float]] = {}
_hits: dict[str, list[float]] = {}
_wake = threading.Event()
_worker: threading.Thread | None = None


class PeerError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---- this server's address ------------------------------------------------------------------------------------
def insecure() -> bool:
    return os.environ.get("MAXXING_TEAM_INSECURE") == "1" or bool(config.load_config().get("team_insecure"))


def _ip_kind(host: str) -> str:
    """public | tailscale | private for an IP or a host name (resolved)."""
    if host.endswith(".ts.net"):
        return "tailscale"
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        return "private"
    try:
        ips = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            ips = [ipaddress.ip_address(i[4][0]) for i in socket.getaddrinfo(host, None)]
        except OSError:
            return "unknown"
    for ip in ips:
        if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):
            return "tailscale"
        if not ip.is_global:
            return "private"
    return "public"


def normalize(address: str) -> str:
    """'https://Ui.Example.com/' -> 'https://ui.example.com' (scheme + host + port, nothing else)."""
    u = urlsplit((address or "").strip())
    if u.scheme not in ("https", "http") or not u.hostname or u.username or u.password:
        raise PeerError(400, "bad_address", "An address looks like https://ui.example.com")
    port = f":{u.port}" if u.port else ""
    return f"{u.scheme}://{u.hostname.lower()}{port}"


def readiness() -> dict:
    """Can this server connect? -> {ok, address, reason: '' | no_address | not_https | tailscale | local}."""
    raw = (config.load_config().get("public_url") or "").strip()
    if not raw:
        return {"ok": False, "address": "", "reason": "no_address"}
    try:
        addr = normalize(raw)
    except PeerError:
        return {"ok": False, "address": raw, "reason": "no_address"}
    if insecure():
        return {"ok": True, "address": addr, "reason": ""}
    host = urlsplit(addr).hostname or ""
    kind = _ip_kind(host)
    if kind == "tailscale":
        return {"ok": False, "address": addr, "reason": "tailscale"}
    if kind == "private":
        return {"ok": False, "address": addr, "reason": "local"}
    if not addr.startswith("https://"):
        return {"ok": False, "address": addr, "reason": "not_https"}
    return {"ok": True, "address": addr, "reason": ""}


def own_address() -> str:
    r = readiness()
    if not r["ok"]:
        raise PeerError(409, "not_reachable", "This server cannot connect: " + r["reason"])
    return r["address"]


def _check_target(addr: str) -> str:
    """An address we may call: https and a public IP (any in insecure mode), never this server."""
    addr = normalize(addr)
    if insecure():
        return addr
    if not addr.startswith("https://"):
        raise PeerError(400, "not_https", "Only https addresses")
    if _ip_kind(urlsplit(addr).hostname or "") != "public":
        raise PeerError(400, "not_public", "This address is not reachable from the internet")
    return addr


def pid(address: str) -> str:
    """The local person id of an address."""
    return "p_" + hashlib.sha256(address.encode()).hexdigest()[:10]


# ---- stored state ---------------------------------------------------------------------------------------------
def _path() -> Path:
    return config.state_dir("team") / "peers.json"


def _load() -> dict:
    doc = config.read_json(_path(), None)
    if not isinstance(doc, dict):
        doc = {}
    doc.setdefault("peers", {})       # address -> {key, status, name, emoji, color, fingerprint, last_seen, group_keys}
    doc.setdefault("invites", [])     # [{code, expires}]
    doc.setdefault("files", {})       # file id -> {path, chat, name, size, mime}
    doc.setdefault("outbox", [])      # [{id, to, event, tries, next, created, chat, msg}]
    return doc


def _save(doc: dict) -> None:
    config.write_json(_path(), doc, mode=0o600)
    bus.invalidate("team")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _mac(key: bytes, *parts: str) -> str:
    return hmac.new(key, "\n".join(parts).encode(), hashlib.sha256).hexdigest()


def fingerprint(key: bytes) -> str:
    h = hashlib.sha256(key).hexdigest()[:8].upper()
    return f"{h[:4]}-{h[4:]}"


def peers() -> dict:
    with _lock:
        return _load()["peers"]


def people() -> dict:
    """Contacts as Team people (accepted ones, and members of shared groups), keyed by person id."""
    out = {}
    now = time.time()
    for addr, p in peers().items():
        if p.get("status") not in ("accepted", "group"):
            continue
        seen = now - float(p.get("last_seen") or 0)
        out[pid(addr)] = {"name": p.get("name") or urlsplit(addr).hostname, "emoji": p.get("emoji", ""),
                          "color": p.get("color") or "zinc", "server": urlsplit(addr).hostname, "address": addr,
                          "status": "online" if seen < 300 else "away" if seen < 3600 else "offline",
                          "contact": p.get("status") == "accepted", "peer": True}
    return out


def connections() -> dict:
    """For the Connections dialog: readiness, contacts, requests to answer, requests sent."""
    r = readiness()
    with _lock:
        doc = _load()
        now = time.time()
        rows = [{"address": a, "id": pid(a), "name": p.get("name", ""), "emoji": p.get("emoji", ""),
                 "color": p.get("color", ""), "status": p["status"], "fingerprint": p.get("fingerprint", ""),
                 "since": p.get("since", 0), "last_seen": p.get("last_seen", 0)}
                for a, p in doc["peers"].items() if p.get("status") in ("accepted", "request", "waiting")]
        invites = sum(1 for i in doc["invites"] if i["expires"] > now)
    return r | {"insecure": insecure(), "contacts": rows, "open_invites": invites}


def _profile() -> dict:
    from .api.settings import profile
    p = profile()
    return {"name": p["name"][:32], "emoji": p["emoji"][:8], "color": p["color"][:12]}


def _clean_profile(p: dict) -> dict:
    p = p if isinstance(p, dict) else {}
    return {"name": " ".join(str(p.get("name") or "").split())[:32], "emoji": str(p.get("emoji") or "")[:8],
            "color": str(p.get("color") or "")[:12]}


# ---- connecting -----------------------------------------------------------------------------------------------
def create_invite() -> dict:
    addr = own_address()
    code = _b64(secrets.token_bytes(32))
    with _lock:
        doc = _load()
        now = time.time()
        doc["invites"] = [i for i in doc["invites"] if i["expires"] > now][-20:]
        doc["invites"].append({"code": code, "expires": now + INVITE_TTL})
        _save(doc)
    return {"invitation": f"{addr}#{code}", "expires": now + INVITE_TTL}


def join(invitation: str) -> dict:
    """B's side: use an invitation of A. -> the contact, waiting for A's answer."""
    me = own_address()
    raw = (invitation or "").strip()
    if "#" not in raw:
        raise PeerError(400, "bad_invitation", "An invitation looks like https://ui.example.com#code")
    addr_raw, code = raw.rsplit("#", 1)
    addr = _check_target(addr_raw)
    if addr == me:
        raise PeerError(400, "self", "This is your own invitation")
    try:
        key0 = _unb64(code)
    except ValueError:
        raise PeerError(400, "bad_invitation", "Damaged invitation") from None
    if len(key0) != 32:
        raise PeerError(400, "bad_invitation", "Damaged invitation")
    nonce_b = _b64(secrets.token_bytes(16))
    body = {"from": me, "to": addr, "nonce": nonce_b, "proof": _mac(key0, "hello", me, addr, nonce_b), "profile": _profile()}
    try:
        r = httpx.post(f"{addr}/api/team-peer/hello", json=body, timeout=TIMEOUT, follow_redirects=False)
    except httpx.HTTPError as e:
        raise PeerError(502, "unreachable", f"{addr} does not answer ({type(e).__name__})") from None
    if r.status_code == 409:
        raise PeerError(409, "already_connected", f"{addr} already has you as a contact or a request: ask them to remove "
                                                  "you, then use a new invitation")
    if r.status_code != 200:
        msg = "The invitation was refused (used, expired or wrong)" if r.status_code in (403, 404, 410) else f"{addr} answered {r.status_code}"
        raise PeerError(400 if r.status_code < 500 else 502, "refused", msg)
    try:
        data = r.json()
        nonce_a, proof_a = str(data["nonce"]), str(data["proof"])
    except (ValueError, KeyError, TypeError):
        raise PeerError(502, "bad_answer", "Unexpected answer") from None
    if not hmac.compare_digest(proof_a, _mac(key0, "welcome", addr, me, nonce_a, nonce_b)):
        raise PeerError(502, "bad_answer", "The other server could not prove it made this invitation")
    key = _unb64(_mac_b(key0, "key", addr, me, nonce_a, nonce_b))
    with _lock:
        doc = _load()
        doc["peers"][addr] = {**doc["peers"].get(addr, {}), **_clean_profile(data.get("profile")), "key": _b64(key),
                              "status": "waiting", "fingerprint": fingerprint(key), "since": time.time()}
        _save(doc)
    return {"address": addr, "fingerprint": fingerprint(key), "status": "waiting"}


def _mac_b(key: bytes, *parts: str) -> str:
    return _b64(hmac.new(key, "\n".join(parts).encode(), hashlib.sha256).digest())


def _rate(table: dict[str, list[float]], ip: str, limit: int, window: float) -> bool:
    now = time.time()
    if len(table) > 5000:                                  # many senders: forget those quiet for a whole window
        for k in [k for k, v in table.items() if not v or now - v[-1] >= window]:
            del table[k]
    hits = [t for t in table.get(ip, []) if now - t < window]
    table[ip] = hits
    return len(hits) >= limit


def hello(body: dict, ip: str) -> dict:
    """A's side: a server uses one of our invitations."""
    me = own_address()
    with _lock:
        if _rate(_fails, ip, HELLO_FAILS, 3600):
            raise PeerError(429, "blocked", "Too many wrong invitations")
        try:
            frm, to, nonce_b, proof = (normalize(str(body["from"])), str(body["to"]), str(body["nonce"])[:64], str(body["proof"]))
        except (KeyError, TypeError, PeerError):
            raise PeerError(400, "bad_request", "Bad request") from None
        doc = _load()
        now = time.time()
        found = None
        for inv in doc["invites"]:
            if inv["expires"] > now and hmac.compare_digest(proof, _mac(_unb64(inv["code"]), "hello", frm, me, nonce_b)):
                found = inv
        if to != me or not found or frm == me:
            _fails.setdefault(ip, []).append(now)
            raise PeerError(403, "refused", "Unknown or expired invitation")
        old = doc["peers"].get(frm, {})
        if old.get("status") in ("accepted", "waiting", "request"):
            # The key of a contact is never replaced through an invitation: whoever got the invitation could
            # otherwise speak as that contact (and cut the real one off). Remove the contact first.
            raise PeerError(409, "already_connected", "Already connected with this address: remove it first")
        if not insecure():
            _check_target(frm)                             # an address we could never answer (or refuse) is not stored
        doc["invites"].remove(found)
        key0 = _unb64(found["code"])
        nonce_a = _b64(secrets.token_bytes(16))
        key = _unb64(_mac_b(key0, "key", me, frm, nonce_a, nonce_b))
        doc["peers"][frm] = {**old, **_clean_profile(body.get("profile")), "key": _b64(key), "status": "request",
                             "fingerprint": fingerprint(key), "since": now, "last_seen": now}
        _save(doc)
    return {"nonce": nonce_a, "proof": _mac(key0, "welcome", me, frm, nonce_a, nonce_b), "profile": _profile()}


def answer(address: str, accept: bool) -> dict:
    """A accepts (the `accept` event must reach B: a fake address fails here) or refuses a request."""
    address = normalize(address)
    with _lock:
        p = _load()["peers"].get(address)
    if not p or p.get("status") != "request":
        raise PeerError(404, "not_found", "No request from this address")
    if not accept:
        _deliver_now(address, {"type": "refuse"})
        forget(address)
        return {"ok": True}
    _deliver_now(address, {"type": "accept", "profile": _profile()}, raise_on_error=True)
    with _lock:
        doc = _load()
        doc["peers"][address]["status"] = "accepted"
        _save(doc)
    return {"ok": True}


def forget(address: str) -> None:
    """Remove a contact (or a request): its key is deleted, nothing more is accepted from it."""
    address = normalize(address)
    with _lock:
        doc = _load()
        p = _drop_link(doc, address)
        _save(doc)
    if p and p.get("status") == "accepted":
        try:
            _deliver_now(address, {"type": "bye"}, key=_unb64(p["key"]))
        except PeerError:
            pass


def _drop_link(doc: dict, address: str) -> dict | None:
    """The contact link with an address goes (caller holds the lock and saves). Shared groups stay: it becomes a
    group member again, and only what goes to those groups stays in the outbox."""
    p = doc["peers"].pop(address, None)
    gk = (p or {}).get("group_keys") or {}
    doc["outbox"] = [o for o in doc["outbox"] if o["to"] != address or (o.get("chat") or "") in gk]
    if gk:
        doc["peers"][address] = {k: v for k, v in p.items() if k not in ("key", "fingerprint", "since")} | {"status": "group"}
    return p


# ---- signing --------------------------------------------------------------------------------------------------
def _scopes(p: dict) -> list[tuple[str, bytes]]:
    """(scope, key) a sender may sign with: "" = its contact link, else the id of the one group the key is for."""
    out = []
    if p.get("key") and p.get("status") in ("accepted", "waiting", "request"):
        out.append(("", _unb64(p["key"])))
    out += [(cid, _unb64(k)) for cid, k in (p.get("group_keys") or {}).items()]
    return out


def _sign(key: bytes, method: str, path: str, frm: str, to: str, body: bytes) -> dict:
    ts, nonce = str(int(time.time())), _b64(secrets.token_bytes(12))
    sig = _mac(key, method, path, frm, to, ts, nonce, hashlib.sha256(body).hexdigest())
    return {"X-Team-From": frm, "X-Team-Time": ts, "X-Team-Nonce": nonce, "X-Team-Sig": sig}


def verify(method: str, path: str, headers: dict, body: bytes, ip: str) -> tuple[str, str]:
    """-> (the sender's address, scope: "" = signed with its contact key, else the group its key is limited to),
    or PeerError 401/403/429."""
    me = own_address()
    with _lock:
        if _rate(_hits, ip, INBOX_PER_MIN, 60):
            raise PeerError(429, "throttled", "Too many requests")
        _hits.setdefault(ip, []).append(time.time())
        try:
            frm = normalize(headers.get("x-team-from", ""))
            ts = int(headers.get("x-team-time", "0"))
        except (PeerError, ValueError):
            raise PeerError(401, "unsigned", "Unsigned request") from None
        nonce, sig = headers.get("x-team-nonce", "")[:64], headers.get("x-team-sig", "")
        now = time.time()
        if abs(now - ts) > CLOCK_SKEW or not nonce or not sig:
            raise PeerError(401, "stale", "Request too old or unsigned")
        for n, t in list(_nonces.items()):
            if now - t > NONCE_TTL:
                del _nonces[n]
        if f"{frm}|{nonce}" in _nonces:
            raise PeerError(401, "replay", "Request already seen")
        p = _load()["peers"].get(frm)
        digest = hashlib.sha256(body).hexdigest()
        scope = next((s for s, k in _scopes(p or {})
                      if hmac.compare_digest(sig, _mac(k, method, path, frm, me, str(ts), nonce, digest))), None)
        if scope is None:
            raise PeerError(403, "unknown", "Unknown sender")
        _nonces[f"{frm}|{nonce}"] = now
        return frm, scope


def touch(address: str) -> None:
    with _lock:
        doc = _load()
        if address in doc["peers"]:
            doc["peers"][address]["last_seen"] = time.time()
            config.write_json(_path(), doc, mode=0o600)


def receive(frm: str, event: dict, scope: str = "") -> dict:
    """An event from a verified sender: contact life here, chat events in team.apply_remote(). `scope`: the group a
    group key is limited to (see verify)."""
    from . import team
    kind = event.get("type")
    if scope and (kind not in ("message", "vote", "react") or str(event.get("chat") or "") != scope):
        raise PeerError(403, "forbidden", "A group key only works in its own group")
    with _lock:
        doc = _load()
        p = doc["peers"].get(frm) or {}
        if kind == "accept":
            if p.get("status") != "waiting":
                raise PeerError(409, "unexpected", "No pending request")
            p.update(_clean_profile(event.get("profile")), status="accepted", last_seen=time.time())
            _save(doc)
            return {"ok": True}
        if kind in ("refuse", "bye"):
            if p.get("status") in ("waiting", "accepted", "request"):
                _drop_link(doc, frm)
                _save(doc)
            return {"ok": True}
        if kind == "profile" and p.get("status") == "accepted":
            p.update(_clean_profile(event.get("profile")))
            _save(doc)
            return {"ok": True}
    touch(frm)
    team.apply_remote(frm, p.get("status") == "accepted" and not scope, event)
    return {"ok": True}


def add_group_peer(address: str, chat: str, key: str, profile: dict) -> None:
    """A member of a group we were added to: we may talk with it about that chat only. A contact (or a pending
    request) keeps its own link key: a key handed by the group's creator would let the creator speak as it."""
    address = normalize(address)
    with _lock:
        doc = _load()
        p = doc["peers"].setdefault(address, {"status": "group"})
        if p.get("status") != "group":
            return
        p.setdefault("group_keys", {})[chat] = key
        p.update(_clean_profile(profile))
        _save(doc)


def new_pair_key() -> str:
    return _b64(secrets.token_bytes(32))


# ---- delivery -------------------------------------------------------------------------------------------------
def _key_to(address: str, chat: str | None) -> bytes:
    with _lock:
        p = _load()["peers"].get(address) or {}
    if p.get("status") == "accepted" or (p.get("status") in ("waiting", "request") and p.get("key")):
        return _unb64(p["key"])
    gk = (p.get("group_keys") or {}).get(chat or "")
    if gk:
        return _unb64(gk)
    raise PeerError(404, "no_key", "Not connected with " + address)


def _post(address: str, event: dict, key: bytes) -> httpx.Response:
    me = own_address()
    path = "/api/team-peer/inbox"
    body = json.dumps(event, separators=(",", ":")).encode()
    headers = _sign(key, "POST", path, me, address, body) | {"Content-Type": "application/json"}
    return httpx.post(address + path, content=body, headers=headers, timeout=TIMEOUT, follow_redirects=False)


def _deliver_now(address: str, event: dict, raise_on_error: bool = False, key: bytes | None = None) -> bool | None:
    """True = delivered, False = to retry, None = never deliverable (no key any more)."""
    try:
        r = _post(_check_target(address), event, key or _key_to(address, event.get("chat")))
        if r.status_code == 200:
            return True
        err = f"{address} answered {r.status_code}"
    except httpx.HTTPError as e:
        err = f"{address} does not answer ({type(e).__name__})"
    except PeerError as e:                     # no key any more, or the address does not resolve right now
        if raise_on_error:
            raise
        return None if e.code == "no_key" else False
    if raise_on_error:
        raise PeerError(502, "unreachable", err)
    return False


def send(addresses: list[str], event: dict, msg: str | None = None) -> None:
    """Queue an event for each address (delivered by the worker, retried for OUTBOX_DAYS)."""
    if not addresses:
        return
    now = time.time()
    with _lock:
        doc = _load()
        for a in addresses:
            doc["outbox"].append({"id": _b64(secrets.token_bytes(8)), "to": a, "event": event, "tries": 0, "next": now,
                                  "created": now, "chat": event.get("chat"), "msg": msg})
        config.write_json(_path(), doc, mode=0o600)
    _wake.set()


def _run_outbox() -> None:
    while True:
        _wake.wait(5)
        _wake.clear()
        try:
            if readiness()["ok"]:
                _outbox_round()
        except Exception:                      # never let the worker die
            log.exception("team outbox")


def _outbox_round() -> None:
    """One pass over the due events. A failed address waits for its next try, the others still go."""
    from . import team
    now = time.time()
    with _lock:
        due = [o for o in _load()["outbox"] if o["next"] <= now]
    down: set[str] = set()                     # failed this round: its other events wait
    for o in due:
        if o["to"] in down:
            continue
        try:
            ok = _deliver_now(o["to"], o["event"])
        except Exception:                      # one bad entry never stops the others
            log.exception("team outbox entry %s", o.get("id"))
            ok = False
        if ok is False:
            down.add(o["to"])
        with _lock:
            doc = _load()
            cur = next((x for x in doc["outbox"] if x["id"] == o["id"]), None)
            if cur is None:
                continue
            if ok is not False or now - cur["created"] > OUTBOX_DAYS * 86400:
                doc["outbox"].remove(cur)      # delivered, never deliverable (None) or too old
            else:
                cur["tries"] += 1
                cur["next"] = now + RETRY[min(cur["tries"] - 1, len(RETRY) - 1)]
            config.write_json(_path(), doc, mode=0o600)
        if ok and o.get("msg"):
            team.delivered(o["chat"], o["msg"], pid(o["to"]))


def start() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run_outbox, name="team-outbox", daemon=True)
        _worker.start()


# ---- files ----------------------------------------------------------------------------------------------------
def share_file(path: str, chat: str, meta: dict) -> str:
    fid = _b64(secrets.token_bytes(12))
    with _lock:
        doc = _load()
        doc["files"][fid] = {"path": path, "chat": chat, "name": meta["name"], "size": meta["size"], "mime": meta["mime"]}
        config.write_json(_path(), doc, mode=0o600)
    return fid


def file_for(frm: str, fid: str, scope: str = "") -> dict:
    """A file we shared, asked by a verified member of its chat (with a group key: a file of that group only)."""
    from . import team
    with _lock:
        f = _load()["files"].get(fid)
    if not f or (scope and f["chat"] != scope) or not team.is_member(f["chat"], pid(frm)) or not Path(f["path"]).is_file():
        raise PeerError(404, "not_found", "No such file")
    return f


FETCH_DEADLINE = 30 * 60                                   # a download that takes longer is dropped


def fetch_file(address: str, fid: str, dest: Path, max_bytes: int, chat: str, reserve: int = 0) -> bool:
    """Download a file of a member (signed GET) into `dest`, at most max_bytes, leaving `reserve` bytes free on the
    disk, within FETCH_DEADLINE. False on any failure (nothing left behind but `dest` as the caller made it)."""
    from .uploads import free_bytes
    path = f"/api/team-peer/files/{fid}"
    tmp = dest.with_name(dest.name + ".part")
    end = time.monotonic() + FETCH_DEADLINE
    try:
        headers = _sign(_key_to(address, chat), "GET", path, own_address(), address, b"")
        with httpx.stream("GET", _check_target(address) + path, headers=headers, timeout=60, follow_redirects=False) as r:
            if r.status_code != 200:
                return False
            n = checked = 0
            with open(tmp, "wb") as out:
                for chunk in r.iter_bytes(1 << 16):
                    n += len(chunk)
                    if (max_bytes and n > max_bytes) or time.monotonic() > end:
                        raise OSError("too large or too slow")
                    if n - checked >= 32 << 20 or checked == 0:  # the disk, now and every 32 MB
                        checked = n
                        if free_bytes(dest.parent) - len(chunk) < reserve:
                            raise OSError("disk full")
                    out.write(chunk)
            tmp.replace(dest)
            return True
    except (httpx.HTTPError, PeerError, OSError):
        tmp.unlink(missing_ok=True)
        return False
