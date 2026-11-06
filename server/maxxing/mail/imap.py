"""IMAP client of the E-mail page (stdlib imaplib): folders, message lists, one message, flags, moves, folders.

One pooled connection per account (`session()`): a page view runs 2-3 requests and an IMAP login costs a TLS
handshake + LOGIN, so the connection is kept for IDLE_S seconds and checked with NOOP before reuse. Every call
holds the account lock for its whole duration (imaplib is not thread safe).
"""
from __future__ import annotations

import base64
import contextlib
import email
import email.parser
import email.policy
import email.utils
import imaplib
import re
import socket
import ssl
import threading
import time
from email.message import EmailMessage
from typing import Any, Iterator

from . import access

TIMEOUT_S = 25
IDLE_S = 240            # a pooled connection older than this is closed instead of reused
CHECK_S = 20            # NOOP before reusing a connection idle for longer than this
MAX_FETCH = 50 * 1024 * 1024
MAX_INLINE = 3 * 1024 * 1024
PAGE = 50

imaplib._MAXLINE = 10_000_000   # long LIST/SEARCH lines on big mailboxes


class MailError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- modified UTF-7 (RFC 3501 folder names)

def mutf7_decode(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c != "&":
            out.append(c)
            i += 1
            continue
        j = s.find("-", i)
        if j < 0:
            out.append(s[i:])
            break
        chunk = s[i + 1:j]
        if not chunk:
            out.append("&")
        else:
            b = chunk.replace(",", "/")
            b += "=" * (-len(b) % 4)
            try:
                out.append(base64.b64decode(b).decode("utf-16-be"))
            except Exception:  # noqa: BLE001 - keep the raw name rather than fail
                out.append(s[i:j + 1])
        i = j + 1
    return "".join(out)


def mutf7_encode(s: str) -> str:
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            out.append("&" + b + "-")
            buf.clear()

    for c in s:
        if 0x20 <= ord(c) <= 0x7E:
            flush()
            out.append("&-" if c == "&" else c)
        else:
            buf.append(c)
    flush()
    return "".join(out)


def _q(name: str) -> str:
    """A folder name as an IMAP quoted string (modified UTF-7)."""
    return '"' + mutf7_encode(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------- connections

def _password(acc: dict) -> str:
    from .. import vault
    pw = vault.get(acc.get("password_key") or "")
    if not pw:
        raise MailError("no_password", f"the password of {acc.get('address')} is missing (Settings -> Keys: {acc.get('password_key')})")
    return pw


def open_imap(host: str, port: int, tls: str, username: str, password: str) -> imaplib.IMAP4:
    ctx = ssl.create_default_context()
    try:
        if tls == "ssl":
            m = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=TIMEOUT_S)
        else:
            m = imaplib.IMAP4(host, port, timeout=TIMEOUT_S)
            if tls == "starttls":
                m.starttls(ssl_context=ctx)
    except (socket.timeout, TimeoutError):
        raise MailError("unreachable", f"{host}:{port} does not answer (blocked port or wrong server)") from None
    except ssl.SSLError as e:
        raise MailError("tls", f"{host}:{port}: TLS error ({e.reason or e})") from None
    except (OSError, imaplib.IMAP4.error) as e:
        raise MailError("unreachable", f"{host}:{port}: {e}") from None
    try:
        if "AUTH=PLAIN" in m.capabilities and not password.isascii():
            m.authenticate("PLAIN", lambda _: f"\0{username}\0{password}".encode())
        else:
            m.login(username, password)
    except imaplib.IMAP4.error as e:
        with contextlib.suppress(Exception):
            m.shutdown()
        raise MailError("auth", f"sign-in refused by {host}: {_text(e)}") from None
    return m


class _Slot:
    def __init__(self):
        self.lock = threading.Lock()
        self.conn: imaplib.IMAP4 | None = None
        self.used = 0.0
        self.key: tuple = ()


_slots: dict[str, _Slot] = {}
_slots_lock = threading.Lock()


def _slot(acc_id: str) -> _Slot:
    with _slots_lock:
        return _slots.setdefault(acc_id, _Slot())


def _close(slot: _Slot) -> None:
    if slot.conn is not None:
        with contextlib.suppress(Exception):
            slot.conn.logout()
    slot.conn = None


def forget(acc_id: str) -> None:
    """Drop the pooled connection (account changed or deleted)."""
    s = _slot(acc_id)
    with s.lock:
        _close(s)


@contextlib.contextmanager
def session(acc: dict) -> Iterator[imaplib.IMAP4]:
    s = _slot(acc["id"])
    with s.lock:
        key = (acc["imap_host"], acc["imap_port"], acc["imap_tls"], acc["username"], acc.get("password_key"))
        now = time.time()
        if s.conn is not None and (s.key != key or now - s.used > IDLE_S):
            _close(s)
        if s.conn is not None and now - s.used > CHECK_S:
            try:
                s.conn.noop()
            except Exception:  # noqa: BLE001 - dead connection: open a new one
                s.conn = None
        if s.conn is None:
            s.conn = open_imap(acc["imap_host"], int(acc["imap_port"]), acc["imap_tls"], acc["username"], _password(acc))
            s.key = key
        try:
            yield s.conn
        except (imaplib.IMAP4.abort, OSError) as e:
            s.conn = None
            raise MailError("connection", f"connection to {acc['imap_host']} lost: {e}") from None
        finally:
            s.used = time.time()


def _text(x: Any) -> str:
    if isinstance(x, BaseException):
        x = x.args[0] if x.args else str(x)
    if isinstance(x, str) and x.startswith(("b'", 'b"')):
        x = x[2:-1]
    if isinstance(x, (list, tuple)):
        x = x[0] if x else b""
    if isinstance(x, bytes):
        return x.decode("utf-8", "replace")
    return str(x)


def _ok(typ: str, data: Any, what: str) -> Any:
    if typ != "OK":
        raise MailError("imap", f"{what}: {_text(data)}")
    return data


# ---------------------------------------------------------------- folders

_LIST = re.compile(rb'^\((?P<flags>[^)]*)\) (?P<delim>"(?:[^"\\]|\\.)*"|NIL) (?P<name>.+)$')
ROLE_FLAGS = {"\\sent": "sent", "\\drafts": "drafts", "\\trash": "trash", "\\junk": "junk", "\\archive": "archive",
              "\\all": "all", "\\flagged": "flagged"}
ROLE_NAMES = {
    "sent": {"sent", "sent items", "sent messages", "sent mail", "envoyés", "envoyes", "éléments envoyés", "messages envoyés"},
    "drafts": {"drafts", "draft", "brouillons", "brouillon"},
    "trash": {"trash", "deleted", "deleted items", "deleted messages", "bin", "corbeille", "éléments supprimés"},
    "junk": {"junk", "spam", "junk e-mail", "junk email", "bulk mail", "courrier indésirable", "indésirables", "pourriel"},
    "archive": {"archive", "archives"},
}
ROLE_ORDER = ["inbox", "drafts", "sent", "archive", "junk", "trash"]


def _unquote(b: bytes) -> str:
    s = b.decode("utf-8", "replace")
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


def _list_raw(m: imaplib.IMAP4) -> list[dict]:
    data = _ok(*m.list(), "LIST")
    out, i = [], 0
    while i < len(data):
        item = data[i]
        if isinstance(item, tuple):                  # name sent as a literal
            line, name = item[0], item[1]
            mm = _LIST.match(line.rstrip())
            if mm:
                out.append((mm.group("flags"), mm.group("delim"), name))
        elif item:
            mm = _LIST.match(item)
            if mm:
                out.append((mm.group("flags"), mm.group("delim"), mm.group("name")))
        i += 1
    folders = []
    for flags, delim, name in out:
        raw = _unquote(name)
        fl = [f.lower() for f in flags.decode().split()]
        if "\\noselect" in fl or "\\nonexistent" in fl:
            continue
        d = None if delim == b"NIL" else _unquote(delim)
        folders.append({"raw": raw, "name": mutf7_decode(raw), "delim": d, "flags": fl})
    return folders


def _role(f: dict) -> str | None:
    if f["raw"].upper() == "INBOX":
        return "inbox"
    for fl in f["flags"]:
        if fl in ROLE_FLAGS:
            return ROLE_FLAGS[fl]
    leaf = f["name"].split(f["delim"])[-1] if f["delim"] else f["name"]
    leaf = leaf.strip().lower()
    for role, names in ROLE_NAMES.items():
        if leaf in names:
            return role
    return None


def folders(acc: dict, counts: bool = True) -> list[dict]:
    with session(acc) as m:
        fs = _list_raw(m)
        seen_roles: set[str] = set()
        for f in fs:
            r = _role(f)
            f["role"] = r if r and r not in seen_roles else None   # first folder of each role wins
            if f["role"]:
                seen_roles.add(f["role"])
            f["unread"] = f["total"] = None
            if counts:
                typ, data = m.status(_q(f["name"]), "(MESSAGES UNSEEN)")
                if typ == "OK" and data and data[0]:
                    st = _text(data[0])
                    mt, mu = re.search(r"MESSAGES (\d+)", st), re.search(r"UNSEEN (\d+)", st)
                    f["total"] = int(mt.group(1)) if mt else None
                    f["unread"] = int(mu.group(1)) if mu else None
    fs.sort(key=lambda f: (ROLE_ORDER.index(f["role"]) if f["role"] in ROLE_ORDER else len(ROLE_ORDER), f["name"].lower()))
    return [{"name": f["name"], "role": f["role"], "delim": f["delim"], "unread": f["unread"], "total": f["total"]} for f in fs]


def _folder_of_role(m: imaplib.IMAP4, role: str) -> str | None:
    fs = _list_raw(m)
    for f in fs:
        if _role(f) == role:
            return f["name"]
    return None


def _prefix(m: imaplib.IMAP4) -> tuple[str, str]:
    """(personal namespace prefix, delimiter): where new folders go ("INBOX." on servers that keep every folder
    under INBOX)."""
    fs = _list_raw(m)
    delim = next((f["delim"] for f in fs if f["delim"]), "/")
    if "NAMESPACE" in m.capabilities:
        typ, data = m.namespace()
        if typ == "OK" and data:
            mm = re.match(r'^\(\("([^"]*)" (?:"((?:[^"\\]|\\.)*)"|NIL)', _text(data))
            if mm:
                return mm.group(1), (mm.group(2) or delim).replace("\\\\", "\\")
    others = [f["name"] for f in fs if f["name"].upper() != "INBOX"]
    if others and all(n.upper().startswith("INBOX" + delim) for n in others):
        return "INBOX" + delim, delim
    return "", delim


def _resolve(m: imaplib.IMAP4, name: str) -> str:
    """A folder named the way a person says it ("Invoices") -> its name on the server ("INBOX.Invoices" on servers
    that keep every folder under INBOX). Unknown names are returned as they are."""
    names = [f["name"] for f in _list_raw(m)]
    if name in names:
        return name
    prefix, _ = _prefix(m)
    if prefix and prefix + name in names:
        return prefix + name
    low = [n for n in names if n.lower() == name.lower() or n.lower() == (prefix + name).lower()]
    return low[0] if len(low) == 1 else name


def create_folder(acc: dict, name: str, parent: str | None = None) -> str:
    name = name.strip()
    if not name or len(name) > 200 or any(c in name for c in "\r\n\0*%"):
        raise MailError("invalid", "invalid folder name")
    with session(acc) as m:
        prefix, delim = _prefix(m)
        full = (parent + delim + name) if parent else (prefix + name if not name.startswith(prefix) else name)
        _ok(*m.create(_q(full)), f"create {full}")
        m.subscribe(_q(full))
    return full


def delete_folder(acc: dict, name: str) -> None:
    if name.upper() == "INBOX":
        raise MailError("invalid", "INBOX cannot be deleted")
    with session(acc) as m:
        _ok(*m.delete(_q(name)), f"delete {name}")


def rename_folder(acc: dict, name: str, new: str) -> str:
    if name.upper() == "INBOX":
        raise MailError("invalid", "INBOX cannot be renamed")
    new = new.strip()
    if not new or any(c in new for c in "\r\n\0*%"):
        raise MailError("invalid", "invalid folder name")
    with session(acc) as m:
        _, delim = _prefix(m)
        parent = name.rsplit(delim, 1)[0] + delim if delim and delim in name else ""
        full = new if (parent and new.startswith(parent)) else parent + new
        _ok(*m.rename(_q(name), _q(full)), f"rename {name}")
    return full


# ---------------------------------------------------------------- messages

HEADERS = "FROM TO CC SUBJECT DATE MESSAGE-ID CONTENT-TYPE AUTHENTICATION-RESULTS"
_UID = re.compile(rb"UID (\d+)")
_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")
_IDATE = re.compile(rb'INTERNALDATE "([^"]+)"')


def _select(m: imaplib.IMAP4, folder: str, readonly: bool) -> int:
    typ, data = m.select(_q(folder), readonly=readonly)
    if typ != "OK":
        raise MailError("no_folder", f"folder {folder}: {_text(data)}")
    try:
        return int(_text(data))
    except ValueError:
        return 0


_CONTROL = re.compile(r"[\x00-\x1f\x7f\u0080-\u009f\u2028\u2029]")


def _line(s: str) -> str:
    """A header value on one line: `=?utf-8?q?hi=0AFrom:_x?=` decodes to two lines that would read like Harness's own
    (the text of an agent's turn, `maxxing mail read`)."""
    return _CONTROL.sub(" ", s) if s else ""


def _addr(v: Any) -> list[dict]:
    try:
        return [{"name": _line(a.display_name or ""), "email": _line(a.addr_spec or "")} for a in v.addresses]
    except Exception:  # noqa: BLE001 - malformed header
        return [{"name": "", "email": _line(str(v or ""))}] if v else []


def _hdr(msg: Any, name: str) -> str:
    try:
        v = msg[name]
        return _line(str(v)) if v is not None else ""
    except Exception:  # noqa: BLE001 - undecodable header
        raw = msg.get_all(name, failobj=[None])[0] if hasattr(msg, "get_all") else None
        return _line(str(raw or ""))


def _idate(internal: bytes | None) -> float | None:
    with contextlib.suppress(Exception):
        t = imaplib.Internaldate2tuple(b'INTERNALDATE "' + internal + b'"') if internal else None
        if t:
            return time.mktime(t)
    return None


def _date(msg: Any, internal: bytes | None) -> float | None:
    try:
        d = email.utils.parsedate_to_datetime(_hdr(msg, "date"))
        if d is not None:
            return d.timestamp()
    except Exception:  # noqa: BLE001
        pass
    if internal:
        t = imaplib.Internaldate2tuple(b'INTERNALDATE "' + internal + b'"')
        if t:
            return time.mktime(t)
    return None


def _flags(raw: bytes | None) -> list[str]:
    return [f.lower() for f in (raw or b"").decode().split()]


def _fetch_summaries(m: imaplib.IMAP4, uids: list[int]) -> list[dict]:
    if not uids:
        return []
    typ, data = m.uid("FETCH", ",".join(map(str, uids)), f"(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER.FIELDS ({HEADERS})])")
    _ok(typ, data, "FETCH")
    parser = email.parser.BytesHeaderParser(policy=email.policy.default)
    rows: dict[int, dict] = {}
    for i, item in enumerate(data):
        if not isinstance(item, tuple):
            continue
        meta = item[0]
        nxt = data[i + 1] if i + 1 < len(data) else None
        if isinstance(nxt, bytes):
            meta += nxt                                # FLAGS sometimes come after the literal
        u = _UID.search(meta)
        if not u:
            continue
        uid = int(u.group(1))
        msg = parser.parsebytes(item[1])
        fm = _FLAGS.search(meta)
        fl = _flags(fm.group(1) if fm else b"")
        idate = _IDATE.search(meta)
        size = _SIZE.search(meta)
        ctype = _hdr(msg, "content-type").lower()
        rows[uid] = {
            "uid": uid,
            "from": (_addr(msg["from"]) or [{"name": "", "email": ""}])[0] if msg["from"] else {"name": "", "email": ""},
            "to": _addr(msg["to"]) if msg["to"] else [],
            "subject": _hdr(msg, "subject"),
            "date": _date(msg, idate.group(1) if idate else None),
            "received": _idate(idate.group(1) if idate else None),     # by the server (Date: is the sender's)
            "seen": "\\seen" in fl,
            "flagged": "\\flagged" in fl,
            "answered": "\\answered" in fl,
            "size": int(size.group(1)) if size else None,
            "attachments": ctype.startswith("multipart/mixed"),
            "message_id": _hdr(msg, "message-id").strip(),
            "auth": access.top_result(msg),          # replaced by from_verified (with_trust)
        }
    return [rows[u] for u in uids if u in rows]


def _search_args(q: str | None, unread: bool, flagged: bool) -> tuple[list[str], bytes | None]:
    crit: list[str] = []
    if unread:
        crit.append("UNSEEN")
    if flagged:
        crit.append("FLAGGED")
    lit = None
    if q:
        # control characters never reach the server: a CR/LF inside a quoted string would end the command and let
        # the text send its own (UID STORE \Deleted, EXPUNGE) - `maxxing mail list -s` is open to read-only agents
        q = " ".join(_CONTROL.sub(" ", q).split())[:200]
        if q and q.isascii():
            crit.append("TEXT " + '"' + q.replace("\\", "\\\\").replace('"', '\\"') + '"')
        elif q:
            lit = q.encode()
    return crit or ["ALL"], lit


_mx_cache: dict[str, tuple[float, list[str] | None]] = {}
MX_TTL_S = 86400
MX_FAIL_TTL_S = 300


def _mx_of(domain: str) -> list[str] | None:
    """MX hosts of a domain, looked up once a day (a failed lookup again after 5 min) -> None when unknown."""
    from . import _mx
    hit = _mx_cache.get(domain)
    if hit and time.time() - hit[0] < (MX_TTL_S if hit[1] is not None else MX_FAIL_TTL_S):
        return hit[1]
    mx = _mx(domain, strict=True)
    _mx_cache[domain] = (time.time(), mx)
    return mx


def sender_check(acc: dict) -> dict:
    """{state, server}: access.sender_check with what the checks noted (store.auth_samples) and the MX."""
    from . import store
    domain = (acc.get("address") or "").rsplit("@", 1)[-1].lower()
    samples: list = []
    if not acc.get("auth_servers"):
        with contextlib.suppress(Exception):
            samples = store.auth_samples(acc["id"])
    return access.sender_check(acc, samples, lambda: (_mx_of(domain) or []) if domain else [])


def trust(acc: dict) -> set[str]:
    """The base domains whose topmost Authentication-Results make a sender verified for this mailbox: the owner's
    auth_servers, or the provider found by sender_check; none otherwise."""
    c = sender_check(acc)
    if c["state"] == "owner":
        return {access.base_domain(s) for s in acc["auth_servers"]}
    return {c["server"]} if c["state"] == "auto" else set()


def with_trust(acc: dict, rows: list[dict], t: set[str] | None = None) -> list[dict]:
    """`auth` (the top Authentication-Results) -> `from_verified`: the provider checked the sender's domain;
    `auth_server`: who wrote that header (the checks note it: sender_check). t: trust(acc), computed before."""
    if t is None:
        t = trust(acc) if any(r.get("auth") for r in rows) else set()
    for r in rows:
        top = r.pop("auth", "") or ""
        r["auth_server"] = access.authserv_id(top)
        r["from_verified"] = access.verified(top, (r.get("from") or {}).get("email") or "", t)
    return rows


SCAN_MAX = 1000         # messages looked at to fill a page when an agent only sees some senders


def messages(acc: dict, folder: str = "INBOX", page: int = 0, size: int = PAGE, q: str | None = None,
             unread: bool = False, flagged: bool = False, senders: list[str] | None = None) -> dict:
    """A page of a folder, newest first. senders: only the mails from these addresses / domains whose sender the
    provider checked (an agent's `senders`, access.py); `total` then counts the matches among the newest SCAN_MAX."""
    size = max(1, min(200, size))
    t = trust(acc)                      # before the connection is held: it may look up the MX (up to 6 s)
    with session(acc) as m:
        exists = _select(m, folder, readonly=True)
        crit, lit = _search_args(q, unread, flagged)
        if senders:
            crit = [c for c in crit if c != "ALL"] + access.imap_from(senders) or ["ALL"]
        if lit is not None:
            m.literal = lit
            typ, data = m.uid("SEARCH", "CHARSET", "UTF-8", *crit if crit != ["ALL"] else [], "TEXT")
        else:
            typ, data = m.uid("SEARCH", *crit)
        _ok(typ, data, "SEARCH")
        uids = sorted((int(x) for x in _text(data).split()), reverse=True)
        if not senders:
            total = len(uids)
            rows = with_trust(acc, _fetch_summaries(m, uids[page * size:(page + 1) * size]), t)
        else:
            kept: list[dict] = []
            grant = {"senders": senders}
            for i in range(0, min(len(uids), SCAN_MAX), 100):
                for r in with_trust(acc, _fetch_summaries(m, uids[i:i + 100]), t):
                    if access.sender_ok(grant, r["from"]["email"], r["from_verified"]):
                        kept.append(r)
            total = len(kept)
            rows = kept[page * size:(page + 1) * size]
    return {"folder": folder, "total": total, "exists": exists, "page": page, "size": size, "messages": rows}


def summaries(acc: dict, folder: str, uids: list[int]) -> list[dict]:
    """The list rows of some messages (with from_verified), in the order of `uids`; missing ones are left out."""
    if not uids:
        return []
    with session(acc) as m:
        _select(m, folder, readonly=True)
        rows = _fetch_summaries(m, [int(u) for u in uids])
    return with_trust(acc, rows)


def new_since(acc: dict, folder: str, last_uid: int | None, limit: int = 50) -> dict:
    """{uidvalidity, uids, more, messages}: the oldest `limit` messages of `folder` after last_uid (more: others
    follow), or with last_uid None the newest `limit`."""
    t = trust(acc)
    with session(acc) as m:
        _select(m, folder, readonly=True)
        validity = 0
        with contextlib.suppress(Exception):
            validity = int(_text(m.response("UIDVALIDITY")[1]) or 0)
        crit = f"{int(last_uid) + 1}:*" if last_uid is not None else "1:*"
        typ, data = m.uid("SEARCH", "UID", crit)
        _ok(typ, data, "SEARCH")
        uids = sorted(int(x) for x in _text(data).split())
        more = False
        if last_uid is not None:
            uids = [u for u in uids if u > int(last_uid)]   # "N:*" also returns the last message when none is newer
            more = len(uids) > limit
            uids = uids[:limit]                 # the oldest first: the rest comes with the next check, none is lost
        else:
            uids = uids[-limit:]                # a first look: only the newest
        rows = _fetch_summaries(m, uids) if uids else []
    return {"uidvalidity": validity, "uids": uids, "more": more, "messages": with_trust(acc, rows, t)}


def _part_text(part: Any) -> str:
    try:
        return part.get_content().replace("\r\n", "\n")
    except Exception:  # noqa: BLE001 - unknown charset or broken encoding
        payload = part.get_payload(decode=True) or b""
        return payload.decode(part.get_content_charset() or "utf-8", "replace")


_CID = re.compile(r"""(["'(])cid:([^"')\s>]+)""", re.I)
_REMOTE = re.compile(r"""(?:src|background)\s*=\s*["']?\s*https?:|url\(\s*["']?https?:""", re.I)
_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.I | re.S)


def _parse(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[return-value]


def _parts(msg: EmailMessage) -> tuple[Any, Any, list[tuple[int, Any]]]:
    plain = html = None
    with contextlib.suppress(Exception):
        plain = msg.get_body(preferencelist=("plain",))
    with contextlib.suppress(Exception):
        html = msg.get_body(preferencelist=("html",))
    leaves = [(i, p) for i, p in enumerate(msg.walk()) if not p.is_multipart()]
    return plain, html, leaves


def _render(msg: EmailMessage, uid: int, folder: str, seen_flags: list[str]) -> dict:
    plain, html, leaves = _parts(msg)
    html_s = _part_text(html) if html is not None else None
    cids: dict[str, str] = {}
    attachments = []
    for idx, p in leaves:
        if p is plain or p is html:
            continue
        ctype = p.get_content_type()
        cid = (p.get("content-id") or "").strip().strip("<>")
        payload = None
        if cid and ctype.startswith("image/") and html_s and ("cid:" + cid) in html_s:
            payload = p.get_payload(decode=True) or b""
            if len(payload) <= MAX_INLINE:
                cids[cid] = f"data:{ctype};base64," + base64.b64encode(payload).decode()
                continue
        name = _line(p.get_filename() or "")
        if not name and p.get_content_disposition() != "attachment" and ctype.startswith("text/"):
            continue                                  # alternative bodies already shown
        if payload is None:
            payload = p.get_payload(decode=True) or b""
        attachments.append({"index": idx, "filename": name or f"part-{idx}.{ctype.split('/')[-1]}",
                            "content_type": ctype, "size": len(payload)})
    if html_s is not None:
        html_s = _SCRIPT.sub("", html_s)
        html_s = _CID.sub(lambda mm: mm.group(1) + cids.get(mm.group(2), "about:blank"), html_s)
    return {
        "uid": uid, "folder": folder,
        "from": (_addr(msg["from"]) or [{"name": "", "email": ""}])[0] if msg["from"] else {"name": "", "email": ""},
        "to": _addr(msg["to"]) if msg["to"] else [],
        "cc": _addr(msg["cc"]) if msg["cc"] else [],
        "reply_to": _addr(msg["reply-to"]) if msg["reply-to"] else [],
        "bcc": _addr(msg["bcc"]) if msg["bcc"] else [],
        "in_reply_to": _hdr(msg, "in-reply-to"),
        "subject": _hdr(msg, "subject"),
        "date": _date(msg, None),
        "message_id": _hdr(msg, "message-id"),
        "references": _hdr(msg, "references"),
        "text": _part_text(plain) if plain is not None else None,
        "html": html_s,
        "remote_images": bool(html_s and _REMOTE.search(html_s)),
        "attachments": attachments,
        "auth": access.top_result(msg),
        "seen": "\\seen" in seen_flags, "flagged": "\\flagged" in seen_flags, "answered": "\\answered" in seen_flags,
    }


def _fetch_raw(m: imaplib.IMAP4, uid: int) -> tuple[bytes, list[str]]:
    typ, data = m.uid("FETCH", str(uid), "(RFC822.SIZE FLAGS)")
    _ok(typ, data, "FETCH")
    meta = b" ".join(x if isinstance(x, bytes) else x[0] for x in data if x)
    if not _UID.search(meta) and b"RFC822.SIZE" not in meta:
        raise MailError("not_found", f"message {uid} not found (moved or deleted)")
    size = _SIZE.search(meta)
    if size and int(size.group(1)) > MAX_FETCH:
        raise MailError("too_large", "message larger than 50 MB")
    fl = _flags(_FLAGS.search(meta).group(1)) if _FLAGS.search(meta) else []
    typ, data = m.uid("FETCH", str(uid), "(BODY.PEEK[])")
    _ok(typ, data, "FETCH")
    raw = next((x[1] for x in data if isinstance(x, tuple)), None)
    if raw is None:
        raise MailError("not_found", f"message {uid} not found (moved or deleted)")
    return raw, fl


def message(acc: dict, folder: str, uid: int, mark_seen: bool = True) -> dict:
    with session(acc) as m:
        _select(m, folder, readonly=not mark_seen)
        raw, fl = _fetch_raw(m, uid)
        if mark_seen and "\\seen" not in fl:
            m.uid("STORE", str(uid), "+FLAGS.SILENT", "(\\Seen)")
            fl.append("\\seen")
    return with_trust(acc, [_render(_parse(raw), uid, folder, fl)])[0]


def attachment(acc: dict, folder: str, uid: int, index: int) -> tuple[str, str, bytes]:
    with session(acc) as m:
        _select(m, folder, readonly=True)
        raw, _ = _fetch_raw(m, uid)
    msg = _parse(raw)
    for i, p in enumerate(msg.walk()):
        if i == index and not p.is_multipart():
            ctype = p.get_content_type()
            return _line(p.get_filename() or "") or f"part-{i}.{ctype.split('/')[-1]}", ctype, p.get_payload(decode=True) or b""
    raise MailError("not_found", "attachment not found")


def raw_message(acc: dict, folder: str, uid: int) -> bytes:
    with session(acc) as m:
        _select(m, folder, readonly=True)
        raw, _ = _fetch_raw(m, uid)
    return raw


# ---------------------------------------------------------------- actions

ACTIONS = ("seen", "unseen", "flag", "unflag", "move", "archive", "trash", "junk", "inbox", "delete")
STORE = {"seen": ("+FLAGS.SILENT", "(\\Seen)"), "unseen": ("-FLAGS.SILENT", "(\\Seen)"),
         "answered": ("+FLAGS.SILENT", "(\\Answered)"),
         "flag": ("+FLAGS.SILENT", "(\\Flagged)"), "unflag": ("-FLAGS.SILENT", "(\\Flagged)")}


def _move(m: imaplib.IMAP4, uids: str, target: str) -> None:
    if "MOVE" in m.capabilities:
        _ok(*m.uid("MOVE", uids, _q(target)), f"move to {target}")
        return
    _ok(*m.uid("COPY", uids, _q(target)), f"copy to {target}")
    m.uid("STORE", uids, "+FLAGS.SILENT", "(\\Deleted)")
    if "UIDPLUS" in m.capabilities:
        m.uid("EXPUNGE", uids)
    else:
        m.expunge()


def act(acc: dict, folder: str, uids: list[int], action: str, target: str | None = None) -> dict:
    """Flag, move, archive, trash, mark as junk, back to the inbox, or delete for good (only from the trash or
    junk folder). Returns {"ok", "moved_to"}. The archive folder is created when the account has none."""
    if action not in ACTIONS and action != "answered":
        raise MailError("invalid", f"unknown action {action}")
    uids = sorted({int(u) for u in uids if int(u) > 0})
    if not uids:
        raise MailError("invalid", "no message")
    us = ",".join(map(str, uids))
    moved_to = None
    with session(acc) as m:
        _select(m, folder, readonly=False)
        if action in STORE:
            _ok(*m.uid("STORE", us, *STORE[action]), action)
        elif action == "delete":
            here = next((f for f in _list_raw(m) if f["name"] == folder), None)
            if not here or _role(here) not in ("trash", "junk"):
                raise MailError("invalid", "delete for good only works from the trash or the junk folder; use trash")
            m.uid("STORE", us, "+FLAGS.SILENT", "(\\Deleted)")
            if "UIDPLUS" in m.capabilities:
                m.uid("EXPUNGE", us)
            else:
                m.expunge()
        else:
            if action == "move":
                if not target:
                    raise MailError("invalid", "move needs a target folder")
                moved_to = _resolve(m, target)
            elif action == "inbox":
                moved_to = "INBOX"
            else:
                moved_to = _folder_of_role(m, action)
                if not moved_to:
                    if action != "archive":
                        raise MailError("no_folder", f"this account has no {action} folder")
                    prefix, _ = _prefix(m)
                    moved_to = prefix + "Archive"
                    _ok(*m.create(_q(moved_to)), f"create {moved_to}")
                    m.subscribe(_q(moved_to))
                    _select(m, folder, readonly=False)
            if moved_to == folder:
                return {"ok": True, "moved_to": None}
            _move(m, us, moved_to)
    return {"ok": True, "moved_to": moved_to}


def append(acc: dict, role: str, raw: bytes, flags: str = "(\\Seen)") -> str | None:
    """Store a message in the folder of `role` (sent copy, draft). Returns the folder or None when there is none."""
    with session(acc) as m:
        target = _folder_of_role(m, role)
        if not target:
            return None
        _ok(*m.append(_q(target), flags, imaplib.Time2Internaldate(time.time()), raw), f"append to {target}")
    return target


_APPENDUID = re.compile(r"APPENDUID \d+ (\d+)")


def append_draft(acc: dict, raw: bytes) -> tuple[str | None, int]:
    """File a draft in the drafts folder. Returns (folder, uid); uid 0 when the server does not tell it."""
    with session(acc) as m:
        target = _folder_of_role(m, "drafts")
        if not target:
            return None, 0
        typ, data = m.append(_q(target), "(\\Draft \\Seen)", imaplib.Time2Internaldate(time.time()), raw)
        _ok(typ, data, f"append to {target}")
        got = _APPENDUID.search(_text(data))
        if got:
            return target, int(got.group(1))
        mid = re.search(rb"^Message-ID:\s*(\S+)", raw, re.I | re.M)
        if mid:                                        # no UIDPLUS: find it back by its Message-ID
            _select(m, target, readonly=True)
            typ, data = m.uid("SEARCH", "HEADER", "Message-ID", '"' + mid.group(1).decode("ascii", "replace").replace('"', "") + '"')
            uids = [int(x) for x in _text(data).split()] if typ == "OK" else []
            if uids:
                return target, max(uids)
    return target, 0


def has(acc: dict, folder: str, uid: int) -> bool:
    """Whether message `uid` is still in `folder` (not flagged deleted). Raises MailError when the server does not say."""
    with session(acc) as m:
        _select(m, folder, readonly=True)
        typ, data = m.uid("SEARCH", "UID", str(int(uid)), "UNDELETED")
        _ok(typ, data, "SEARCH")
        return int(uid) in {int(x) for x in _text(data).split()}


def drop(acc: dict, folder: str, uid: int) -> None:
    """Delete a draft for good (a draft replaced by its new version, or sent). Only in the drafts folder."""
    with session(acc) as m:
        here = next((f for f in _list_raw(m) if f["name"] == folder), None)
        if not here or _role(here) != "drafts":
            raise MailError("invalid", "only a draft can be dropped")
        _select(m, folder, readonly=False)
        m.uid("STORE", str(uid), "+FLAGS.SILENT", "(\\Deleted)")
        if "UIDPLUS" in m.capabilities:
            m.uid("EXPUNGE", str(uid))
        else:
            m.expunge()
