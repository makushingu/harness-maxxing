"""Web Push ("Harness has finished" on the phone, even with the installed app closed). See docs/dev/API.md#push.

Standard Web Push (VAPID, RFC 8292) with no dependency: ES256 on P-256 in pure Python (below) and EMPTY push
messages (no payload, so no RFC 8291 encryption). Nothing of the conversation goes through the push service of the
browser vendor: the push only wakes the service worker, which then asks `POST /api/push/pending` (same origin, the
app's own cookie) for what to show.

State (`webpush.json` in the state dir, mode 0600): the VAPID key pair and the devices (one per browser that
registered). The queue of what a device has not fetched yet stays in memory (at most QUEUE_MAX items, QUEUE_TTL_S old).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from . import config

log = logging.getLogger("maxxing.webpush")

FILE = "webpush.json"
QUEUE_MAX = 20
QUEUE_TTL_S = 24 * 3600
DEVICES_MAX = 20
SEND_TIMEOUT_S = 10
# The push services of the browsers. The server only ever sends to these hosts (https): an endpoint is chosen by the
# browser that registers it, so without this list a signed-in page could make the server call any address.
PUSH_HOSTS = (
    "fcm.googleapis.com",                      # Chrome, Edge, Brave, Opera, Samsung Internet (Android and desktop)
    "updates.push.services.mozilla.com",       # Firefox
    "push.services.mozilla.com",
    "web.push.apple.com",                      # Safari and the installed app on iOS / macOS
    "notify.windows.com",                      # legacy Edge
)

_lock = threading.RLock()
_queues: dict[str, list[dict]] = {}


# ---- ES256 (ECDSA P-256 + SHA-256), pure Python ----------------------------------------------------------
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
      0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _add(p: tuple | None, q: tuple | None) -> tuple | None:
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0]:
        if (p[1] + q[1]) % _P == 0:
            return None
        lam = (3 * p[0] * p[0] + _A) * pow(2 * p[1], -1, _P) % _P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, _P) % _P
    x = (lam * lam - p[0] - q[0]) % _P
    return x, (lam * (p[0] - x) - p[1]) % _P


def _mul(k: int, p: tuple) -> tuple | None:
    r = None
    while k:
        if k & 1:
            r = _add(r, p)
        p = _add(p, p)  # type: ignore[assignment]
        k >>= 1
    return r


def public_point(d: int) -> tuple[int, int]:
    pt = _mul(d, _G)
    assert pt is not None
    return pt


def _int(b: bytes) -> int:
    return int.from_bytes(b, "big")


def _rfc6979_k(d: int, digest: bytes) -> int:
    """The deterministic nonce of RFC 6979 (HMAC-SHA-256): no random generator involved, a nonce is never reused."""
    x = d.to_bytes(32, "big")
    h1 = (_int(digest) % _N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + h1, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + h1, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        cand = _int(v)
        if 1 <= cand < _N:
            return cand
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign(d: int, message: bytes) -> bytes:
    """ES256 signature of `message`: r || s, 64 bytes (the JWS form, not DER)."""
    digest = hashlib.sha256(message).digest()
    e = _int(digest) % _N
    k = _rfc6979_k(d, digest)
    while True:
        r = _mul(k, _G)[0] % _N                     # type: ignore[index]
        s = pow(k, -1, _N) * (e + r * d) % _N
        if r and s:
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")
        k = k % _N + 1                              # (practically never reached)


def verify(point: tuple[int, int], message: bytes, sig: bytes) -> bool:
    if len(sig) != 64:
        return False
    r, s = _int(sig[:32]), _int(sig[32:])
    if not (0 < r < _N and 0 < s < _N):
        return False
    e = _int(hashlib.sha256(message).digest()) % _N
    w = pow(s, -1, _N)
    pt = _add(_mul(e * w % _N, _G), _mul(r * w % _N, point))
    return pt is not None and pt[0] % _N == r


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


# ---- state -----------------------------------------------------------------------------------------------
def _path():
    return config.state_dir() / FILE


def _usable(d) -> bool:
    """A state with a private key in [1, N-1] (hex) and devices that are all dicts."""
    if not isinstance(d, dict) or not isinstance(d.get("private"), str):
        return False
    try:
        if not 0 < int(d["private"], 16) < _N:
            return False
    except ValueError:
        return False
    devices = d.get("devices")
    return devices is None or (isinstance(devices, dict) and all(isinstance(v, dict) for v in devices.values()))


def _load() -> dict:
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
        if _usable(d):
            d["devices"] = d["devices"] if isinstance(d.get("devices"), dict) else {}
            return d
    except (OSError, ValueError):
        pass
    while True:
        d = secrets.randbelow(_N)
        if d:
            break
    return {"private": f"{d:064x}", "devices": {}}


def _keep_damaged() -> None:
    """The file exists but is not a usable state (cut, edited by hand): _load made a new key out of it, so the
    first save would erase the old key and every subscribed device. Keep a copy first."""
    f = _path()
    try:
        if _usable(json.loads(f.read_text(encoding="utf-8"))):
            return
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        pass
    dest = f.with_name(f"{f.name}.damaged-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        shutil.copy2(f, dest)
        os.chmod(dest, 0o600)
        log.error("%s was damaged: kept as %s before a new key is saved", f, dest)
    except OSError:
        log.exception("could not keep a copy of the damaged %s", f)


def _save(st: dict) -> None:
    _keep_damaged()
    config.write_json(_path(), st, mode=0o600)


def _key(st: dict) -> int:
    return int(st["private"], 16)


def public_key() -> str:
    """The application server key (uncompressed P-256 point, base64url) the browser subscribes with."""
    with _lock:
        st = _load()
        if not _path().exists():
            _save(st)
        x, y = public_point(_key(st))
        return _b64(b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big"))


def device_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:16]


def allowed_endpoint(endpoint: object) -> bool:
    if not isinstance(endpoint, str) or len(endpoint) > 1000:
        return False
    u = urlsplit(endpoint)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443) or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


# ---- devices ---------------------------------------------------------------------------------------------
def devices() -> list[dict]:
    with _lock:
        return [{"id": i, "label": d.get("label") or "", "at": d.get("at") or 0}
                for i, d in sorted(_load()["devices"].items(), key=lambda kv: kv[1].get("at") or 0)]


def add_device(endpoint: str, label: str = "") -> dict:
    """Register (or refresh) a browser. ValueError: the endpoint is not one of the browsers' push services."""
    if not allowed_endpoint(endpoint):
        raise ValueError("Not a known push service endpoint.")
    with _lock:
        st = _load()
        did = device_id(endpoint)
        if did not in st["devices"] and len(st["devices"]) >= DEVICES_MAX:
            raise ValueError(f"At most {DEVICES_MAX} devices.")
        st["devices"][did] = {"endpoint": endpoint, "label": label.strip()[:60], "at": time.time()}
        _save(st)
        return {"id": did, "label": st["devices"][did]["label"]}


def remove_device(did: str) -> bool:
    with _lock:
        st = _load()
        if st["devices"].pop(did, None) is None:
            return False
        _save(st)
        _queues.pop(did, None)
        return True


# ---- sending ---------------------------------------------------------------------------------------------
def vapid_header(endpoint: str, st: dict | None = None, now: float | None = None) -> str:
    """`Authorization` value: a JWT for the origin of the push service, signed with the server's key."""
    st = st or _load()
    u = urlsplit(endpoint)
    sub = (config.load_config().get("public_url") or "").rstrip("/")
    claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int((now or time.time()) + 12 * 3600),
              "sub": sub if sub.startswith("https://") else "mailto:push@example.com"}
    head = _b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = sign(_key(st), f"{head}.{body}".encode())
    x, y = public_point(_key(st))
    k = _b64(b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big"))
    return f"vapid t={head}.{body}.{_b64(sig)}, k={k}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):            # a push service never redirects: never follow one elsewhere
        return None


def _post(endpoint: str, headers: dict) -> int:
    req = urllib.request.Request(endpoint, data=b"", headers=headers, method="POST")
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=SEND_TIMEOUT_S) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def wake(did: str) -> str:
    """Send the empty push to one device. 'ok' | 'gone' (404 / 410: the device is removed) | 'error'."""
    with _lock:
        st = _load()
        dev = st["devices"].get(did)
    if not dev or not allowed_endpoint(dev.get("endpoint")):
        return "gone"
    try:
        code = _post(dev["endpoint"], {"Authorization": vapid_header(dev["endpoint"], st), "TTL": "3600",
                                       "Urgency": "normal", "Content-Length": "0"})
    except Exception as e:  # noqa: BLE001 - network down, DNS, TLS: the next turn tries again
        log.info("push to %s failed: %s", did, type(e).__name__)
        return "error"
    if code in (404, 410):
        remove_device(did)
        return "gone"
    if 200 <= code < 300:
        return "ok"
    log.info("push to %s: HTTP %s", did, code)
    return "error"


def notify(title: str, body: str, url: str, tag: str = "", only: str | None = None) -> int:
    """Queue one notification on every device (or `only`) and wake them: the number of devices woken."""
    now = time.time()
    with _lock:
        ids = [only] if only else list(_load()["devices"])
        for did in ids:
            q = [m for m in _queues.get(did, []) if now - m["at"] < QUEUE_TTL_S and (not tag or m.get("tag") != tag)]
            q.append({"title": title[:120], "body": body[:240], "url": url, "tag": tag, "at": now})
            _queues[did] = q[-QUEUE_MAX:]
    return sum(1 for did in ids if wake(did) == "ok")


def pending(did: str) -> list[dict]:
    """What a woken device shows (and forgets): the service worker calls this once per push."""
    now = time.time()
    with _lock:
        if did not in _load()["devices"]:
            return []
        items = [m for m in _queues.pop(did, []) if now - m["at"] < QUEUE_TTL_S]
    return [{k: m[k] for k in ("title", "body", "url", "tag")} for m in items]
