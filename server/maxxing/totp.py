"""Time-based one-time passwords (RFC 6238, built on HOTP RFC 4226) - stdlib only.

The codes of any authenticator app (Authy, Google Authenticator, Microsoft Authenticator, Aegis, 2FAS, Bitwarden,
1Password...): HMAC-SHA1, 6 digits, a 30-second step. `verify()` accepts the step before and after the current one
(clock drift) and never a step already used (`last_step`: the caller stores the step returned).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from urllib.parse import quote, urlencode

STEP = 30
DIGITS = 6
WINDOW = 1                  # steps accepted on each side of the current one
SECRET_BYTES = 20           # 160 bits, the size RFC 4226 recommends for HMAC-SHA1
_CODE_RE = re.compile(r"[0-9]{6}")


def new_secret() -> str:
    """A fresh base32 secret (32 characters, no padding)."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = re.sub(r"[\s-]", "", secret).upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, step: int) -> str:
    """The code of one 30-second step (RFC 4226 dynamic truncation)."""
    mac = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return f"{value % 10 ** DIGITS:0{DIGITS}d}"


def now_step(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // STEP)


def verify(secret: str, code: str, last_step: int = -1, at: float | None = None) -> int | None:
    """-> the step the code matches (store it as the new `last_step`), or None: wrong, malformed, too old or
    already used. Every candidate step is compared (constant time per comparison)."""
    given = (code or "").replace(" ", "")
    if not secret or not _CODE_RE.fullmatch(given):
        return None
    now = now_step(at)
    found = None
    for step in range(now - WINDOW, now + WINDOW + 1):
        if hmac.compare_digest(code_at(secret, step).encode(), given.encode()) and step > last_step:
            found = step
    return found


def uri(secret: str, account: str, issuer: str) -> str:
    """The `otpauth://` address apps read from the QR code (Key Uri Format)."""
    label = quote(f"{issuer}:{account}", safe="")
    return f"otpauth://totp/{label}?" + urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1",
                                                   "digits": DIGITS, "period": STEP})
