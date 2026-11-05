"""E-mail page (Settings -> Features -> mail_page): any IMAP/SMTP mailbox, read and sorted from the UI, the CLI
(`maxxing mail`) and sessions. See docs/dev/API.md#mail.

Accounts live in <state>/mail/accounts.json (no secret there); each password is a Keys vault entry
`MAIL_<ID>_PASSWORD`, not exposed to sessions: Claude goes through `maxxing mail`, never through the password.
"""
from __future__ import annotations

import contextlib
import re
import smtplib
import socket
import ssl
import time
from typing import Any

from .. import config
from .imap import MailError, open_imap

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
TLS = ("ssl", "starttls", "none")
FIELDS = ("label", "address", "name", "username", "imap_host", "imap_port", "imap_tls",
          "smtp_host", "smtp_port", "smtp_tls", "signature", "poll_min", "auth_servers")

# Settings of the big providers (the rest: Thunderbird's autoconfig database, then "mail.<domain>").
KNOWN = {
    "gmail.com": ("imap.gmail.com", 993, "ssl", "smtp.gmail.com", 465, "ssl"),
    "googlemail.com": ("imap.gmail.com", 993, "ssl", "smtp.gmail.com", 465, "ssl"),
    "outlook.com": ("outlook.office365.com", 993, "ssl", "smtp-mail.outlook.com", 587, "starttls"),
    "hotmail.com": ("outlook.office365.com", 993, "ssl", "smtp-mail.outlook.com", 587, "starttls"),
    "live.com": ("outlook.office365.com", 993, "ssl", "smtp-mail.outlook.com", 587, "starttls"),
    "icloud.com": ("imap.mail.me.com", 993, "ssl", "smtp.mail.me.com", 587, "starttls"),
    "me.com": ("imap.mail.me.com", 993, "ssl", "smtp.mail.me.com", 587, "starttls"),
    "yahoo.com": ("imap.mail.yahoo.com", 993, "ssl", "smtp.mail.yahoo.com", 465, "ssl"),
    "purelymail.com": ("imap.purelymail.com", 993, "ssl", "smtp.purelymail.com", 465, "ssl"),
    "migadu.com": ("imap.migadu.com", 993, "ssl", "smtp.migadu.com", 465, "ssl"),
    "zoho.com": ("imap.zoho.eu", 993, "ssl", "smtp.zoho.eu", 465, "ssl"),
    "fastmail.com": ("imap.fastmail.com", 993, "ssl", "smtp.fastmail.com", 465, "ssl"),
    "gmx.com": ("imap.gmx.com", 993, "ssl", "mail.gmx.com", 587, "starttls"),
    "gmx.fr": ("imap.gmx.net", 993, "ssl", "mail.gmx.net", 587, "starttls"),
    "orange.fr": ("imap.orange.fr", 993, "ssl", "smtp.orange.fr", 465, "ssl"),
    "free.fr": ("imap.free.fr", 993, "ssl", "smtp.free.fr", 465, "ssl"),
    "laposte.net": ("imap.laposte.net", 993, "ssl", "smtp.laposte.net", 465, "ssl"),
}
# MX host suffix -> provider domain of KNOWN (custom domains hosted by a big provider)
MX_HINTS = {"google.com": "gmail.com", "googlemail.com": "gmail.com", "outlook.com": "outlook.com",
            "purelymail.com": "purelymail.com", "migadu.com": "migadu.com", "zoho.eu": "zoho.com",
            "zoho.com": "zoho.com", "messagingengine.com": "fastmail.com", "icloud.com": "icloud.com"}


def enabled() -> bool:
    return bool(config.load_config().get("mail_page", False))


def _path():
    return config.state_dir("mail") / "accounts.json"


def _load() -> list[dict]:
    data = config.read_json(_path(), default={}) or {}
    rows = data.get("accounts") if isinstance(data, dict) else None
    return [a for a in rows or [] if isinstance(a, dict) and a.get("id")]


def _save(rows: list[dict]) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    config.write_json(p, {"version": 1, "accounts": rows})


def password_key(acc_id: str) -> str:
    return "MAIL_" + re.sub(r"[^A-Z0-9]", "_", acc_id.upper())[:50] + "_PASSWORD"


def public(acc: dict) -> dict:
    from .. import vault
    from . import poll, store
    out = {k: acc.get(k) for k in ("id", *FIELDS, "password_key", "created", "smtp_checked")}
    out["has_password"] = bool(vault.get(acc.get("password_key") or ""))
    out["poll_min"] = poll.interval_min(acc)
    out["auth_servers"] = acc.get("auth_servers") or []
    try:
        from . import imap
        out["sender_check"] = imap.sender_check(acc)
    except Exception:  # noqa: BLE001
        out["sender_check"] = {"state": "none", "server": ""}
    try:
        out["last_check"] = store.last_check(acc["id"])
    except Exception:  # noqa: BLE001 - the cache is optional
        out["last_check"] = None
    return out


def list_accounts() -> list[dict]:
    return _load()


def get_account(ref: str | None) -> dict:
    """By id or address; with no reference, the only account (or the first one)."""
    rows = _load()
    if not rows:
        raise MailError("no_account", "no mailbox yet: add one on the E-mail page (or `maxxing mail add`)")
    if not ref:
        return rows[0]
    ref_l = ref.strip().lower()
    for a in rows:
        if a["id"] == ref_l or (a.get("address") or "").lower() == ref_l:
            return a
    raise MailError("no_account", f"no mailbox {ref} (accounts: {', '.join(a['address'] for a in rows)})")


def _slug(address: str, taken: set[str]) -> str:
    local, _, domain = address.lower().partition("@")
    base = re.sub(r"[^a-z0-9]+", "-", f"{local}-{domain.split('.')[0]}").strip("-")[:36] or "mail"
    s, n = base, 2
    while s in taken:
        s, n = f"{base}-{n}", n + 1
    return s


def _clean(data: dict, partial: bool = False) -> dict:
    out: dict[str, Any] = {}
    for k in FIELDS:
        if k not in data or data[k] is None:
            continue
        v = data[k]
        if k == "poll_min":
            from .poll import CHOICES
            v = int(v)
            if v not in CHOICES:
                raise MailError("invalid", f"poll_min: one of {', '.join(map(str, CHOICES))} (minutes)")
        elif k == "auth_servers":
            # the servers whose Authentication-Results are trusted (default: the mailbox's own, access.py)
            v = [str(x).strip().lower() for x in (v if isinstance(v, list) else [])
                 if HOST_RE.match(str(x).strip()) and not _is_ip(str(x).strip())][:10]   # a name: base_domain needs one
        elif k in ("imap_port", "smtp_port"):
            v = int(v)
            if not 1 <= v <= 65535:
                raise MailError("invalid", f"{k}: invalid port")
        elif k in ("imap_tls", "smtp_tls"):
            if v not in TLS:
                raise MailError("invalid", f"{k}: one of {', '.join(TLS)}")
        else:
            v = str(v).strip()
            if k == "signature":
                v = v[:2000]
            elif any(c in v for c in "\r\n\0"):
                raise MailError("invalid", f"{k}: invalid characters")
            else:
                v = v[:200]
        out[k] = v
    if "address" in out:
        out["address"] = out["address"].lower()
        if not EMAIL_RE.match(out["address"]):
            raise MailError("invalid", "invalid e-mail address")
    for k in ("imap_host", "smtp_host"):
        if k in out and not HOST_RE.match(out[k]):
            raise MailError("invalid", f"{k}: invalid server name")
    if not partial:
        for k in ("address", "imap_host", "imap_port", "imap_tls", "smtp_host", "smtp_port", "smtp_tls"):
            if k not in out:
                raise MailError("invalid", f"{k} is required")
        out.setdefault("username", out["address"])
        out.setdefault("label", "")
        out.setdefault("name", "")
        out.setdefault("signature", "")
    return out


# ---------------------------------------------------------------- detection of the server settings

def _is_ip(v: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(v.strip("[]"))
        return True
    except ValueError:
        return False


def _mx(domain: str, strict: bool = False) -> list[str] | None:
    """MX hosts through DNS over HTTPS (no resolver library needed). A failed lookup: [] (None when strict)."""
    import httpx
    from ..infra.dnsinfo import doh_api
    try:
        r = httpx.get(doh_api(), params={"name": domain, "type": "MX"}, headers={"accept": "application/dns-json"},
                      timeout=6)
        r.raise_for_status()
        ans = r.json().get("Answer") or []
        hosts = [a["data"].split()[-1].rstrip(".").lower() for a in ans if a.get("type") == 15]
        return [h for h in hosts if h]                 # "0 ." = null MX (the domain takes no mail)
    except Exception:  # noqa: BLE001
        return None if strict else []


def _ispdb(domain: str) -> dict | None:
    import xml.etree.ElementTree as ET
    import httpx
    for url in (f"https://autoconfig.thunderbird.net/v1.1/{domain}",):
        try:
            r = httpx.get(url, timeout=6)
            if r.status_code != 200:
                continue
            root = ET.fromstring(r.text)
            inc = root.find(".//incomingServer[@type='imap']")
            out = root.find(".//outgoingServer[@type='smtp']")
            if inc is None or out is None:
                continue
            tls = lambda s: {"SSL": "ssl", "STARTTLS": "starttls"}.get((s or "").upper(), "ssl")  # noqa: E731
            return {"imap_host": inc.findtext("hostname"), "imap_port": int(inc.findtext("port") or 993),
                    "imap_tls": tls(inc.findtext("socketType")),
                    "smtp_host": out.findtext("hostname"), "smtp_port": int(out.findtext("port") or 465),
                    "smtp_tls": tls(out.findtext("socketType"))}
        except Exception:  # noqa: BLE001
            continue
    return None


def detect(address: str) -> dict:
    """Best guess of the IMAP/SMTP settings of an address: {source, imap_*, smtp_*, mx}."""
    address = address.strip().lower()
    if not EMAIL_RE.match(address):
        raise MailError("invalid", "invalid e-mail address")
    domain = address.split("@", 1)[1]

    def known(d: str, source: str) -> dict:
        ih, ip, it, sh, sp, st = KNOWN[d]
        return {"source": source, "imap_host": ih, "imap_port": ip, "imap_tls": it,
                "smtp_host": sh, "smtp_port": sp, "smtp_tls": st}

    if domain in KNOWN:
        return {**known(domain, "known"), "mx": []}
    mx = _mx(domain)
    for host in mx:
        for suffix, d in MX_HINTS.items():
            if host == suffix or host.endswith("." + suffix):
                return {**known(d, "mx"), "mx": mx}
    got = _ispdb(domain)
    if got and got.get("imap_host"):
        return {"source": "autoconfig", **got, "mx": mx}
    # shared hosting (cPanel...): the MX host usually serves IMAP and SMTP too
    host = mx[0] if mx else f"mail.{domain}"
    return {"source": "guess", "imap_host": host, "imap_port": 993, "imap_tls": "ssl",
            "smtp_host": host, "smtp_port": 465, "smtp_tls": "ssl", "mx": mx}


# ---------------------------------------------------------------- connection tests

SMTP_TIMEOUT_S = 15


def open_smtp(host: str, port: int, tls: str, username: str, password: str) -> smtplib.SMTP:
    ctx = ssl.create_default_context()
    try:
        if tls == "ssl":
            s: smtplib.SMTP = smtplib.SMTP_SSL(host, port, context=ctx, timeout=SMTP_TIMEOUT_S)
        else:
            s = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_S)
            s.ehlo()
            if tls == "starttls":
                s.starttls(context=ctx)
                s.ehlo()
    except (socket.timeout, TimeoutError):
        raise MailError("unreachable", f"{host}:{port} does not answer (port blocked by this server's host, or wrong server)") from None
    except ssl.SSLError as e:
        raise MailError("tls", f"{host}:{port}: TLS error ({e.reason or e})") from None
    except (OSError, smtplib.SMTPException) as e:
        raise MailError("unreachable", f"{host}:{port}: {e}") from None
    try:
        if password.isascii() and username.isascii():
            s.login(username, password)
        else:                                          # smtplib only sends ASCII: AUTH PLAIN in UTF-8 by hand
            import base64
            tok = base64.b64encode(f"\0{username}\0{password}".encode()).decode()
            code, resp = s.docmd("AUTH", "PLAIN " + tok)
            if code not in (235, 503):
                raise smtplib.SMTPAuthenticationError(code, resp)
    except smtplib.SMTPException as e:
        with contextlib.suppress(Exception):
            s.close()
        msg = e.smtp_error.decode("utf-8", "replace") if isinstance(getattr(e, "smtp_error", None), bytes) else str(e)
        raise MailError("auth", f"sign-in refused by {host}: {msg}") from None
    return s


def test(acc: dict, password: str) -> dict:
    """Sign in to IMAP and SMTP. When the SMTP port does not answer (many VPS hosts block 465 and 25), 587 with
    STARTTLS is tried: `smtp` then holds the settings that worked. Raises MailError on IMAP failure."""
    m = open_imap(acc["imap_host"], int(acc["imap_port"]), acc["imap_tls"], acc["username"], password)
    with contextlib.suppress(Exception):
        m.logout()
    tries = [(int(acc["smtp_port"]), acc["smtp_tls"])]
    if (587, "starttls") not in tries:
        tries.append((587, "starttls"))
    if (465, "ssl") not in tries:
        tries.append((465, "ssl"))
    err: MailError | None = None
    for port, tls in tries:
        try:
            s = open_smtp(acc["smtp_host"], port, tls, acc["username"], password)
            with contextlib.suppress(Exception):
                s.quit()
            return {"imap": "ok", "smtp": "ok", "smtp_port": port, "smtp_tls": tls,
                    "smtp_changed": (port, tls) != tries[0]}
        except MailError as e:
            if e.code != "unreachable":
                return {"imap": "ok", "smtp": "error", "smtp_error": e.message, "smtp_code": e.code}
            err = err or e
    return {"imap": "ok", "smtp": "error", "smtp_error": err.message if err else "", "smtp_code": "unreachable"}


# ---------------------------------------------------------------- CRUD

def add_account(data: dict, password: str, skip_test: bool = False) -> tuple[dict, dict]:
    from .. import vault
    acc = _clean(data)
    if not password:
        raise MailError("invalid", "the password is required")
    rows = _load()
    if any(a.get("address") == acc["address"] for a in rows):
        raise MailError("exists", f"{acc['address']} is already there")
    result = {"imap": "skipped", "smtp": "skipped"} if skip_test else test(acc, password)
    if result.get("smtp") == "ok":
        acc["smtp_port"], acc["smtp_tls"] = result["smtp_port"], result["smtp_tls"]
        acc["smtp_checked"] = time.time()
    acc["id"] = _slug(acc["address"], {a["id"] for a in rows})
    acc["password_key"] = password_key(acc["id"])
    acc["created"] = time.time()
    vault.put(acc["password_key"], password, note=f"E-mail page: password of {acc['address']}", expose=False)
    rows.append(acc)
    _save(rows)
    return acc, result


def update_account(acc_id: str, data: dict, password: str | None = None) -> tuple[dict, dict | None]:
    from .. import vault
    from . import imap
    rows = _load()
    cur = next((a for a in rows if a["id"] == acc_id), None)
    if not cur:
        raise MailError("no_account", f"no mailbox {acc_id}")
    changes = _clean(data, partial=True)
    new = {**cur, **changes}
    result = None
    server_change = any(new.get(k) != cur.get(k) for k in ("imap_host", "imap_port", "imap_tls", "smtp_host", "smtp_port", "smtp_tls", "username"))
    if password or server_change:
        pw = password or vault.get(cur.get("password_key") or "") or ""
        result = test(new, pw)
        if result.get("smtp") == "ok":
            new["smtp_port"], new["smtp_tls"] = result["smtp_port"], result["smtp_tls"]
            new["smtp_checked"] = time.time()
    if password:
        vault.put(new["password_key"], password, note=f"E-mail page: password of {new['address']}", expose=False)
    rows = [new if a["id"] == acc_id else a for a in rows]
    _save(rows)
    imap.forget(acc_id)
    return new, result


def delete_account(acc_id: str) -> None:
    from .. import vault
    from . import imap
    rows = _load()
    cur = next((a for a in rows if a["id"] == acc_id), None)
    if not cur:
        raise MailError("no_account", f"no mailbox {acc_id}")
    _save([a for a in rows if a["id"] != acc_id])
    if cur.get("password_key"):
        vault.delete(cur["password_key"])
    imap.forget(acc_id)
    with contextlib.suppress(Exception):
        from . import outbox
        outbox.forget(acc_id)               # its waiting messages end ("Mailbox removed"), before their rows go
    with contextlib.suppress(Exception):
        from . import store
        store.forget_account(acc_id)
