"""`maxxing 2fa` - two-step sign-in, from the server (the way out when the second step cannot be answered).

    maxxing 2fa status              what is on: Telegram, authenticator app, passkeys, recovery codes left
    maxxing 2fa off                 password only again: every method off (every trusted browser is forgotten)
    maxxing 2fa off telegram|app|passkeys   one method only
    maxxing 2fa forget-browsers     every browser asks again at its next sign-in

Turning a method on happens in the web UI: Settings -> Security.
"""
from __future__ import annotations

import json

from . import cli

PARTS = ("all", "telegram", "app", "passkeys")


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action")
    st = sub.add_parser("status", help="what is on: Telegram, authenticator app, passkeys, recovery codes left")
    st.add_argument("--json", action="store_true")
    off = sub.add_parser("off", help="password only again (the way out when the second step cannot be answered)")
    off.add_argument("part", nargs="?", choices=PARTS, default="all",
                     help="one method only: telegram, app (authenticator app) or passkeys (default: all)")
    sub.add_parser("forget-browsers", help="every trusted browser asks again")


def _off(part: str) -> int:
    from . import config, mfa, twofactor
    before = mfa.summary()
    if part in ("all", "telegram") and twofactor.is_on():
        twofactor.set_on(False)
        twofactor.notify("off_cli")
    if part == "all":
        mfa.off_all()
    elif part == "app":
        config.set_secrets({"totp_secret": None, "totp_last_step": None})
    elif part == "passkeys":
        config.set_secret("passkeys", None)
    if part in ("app", "passkeys"):
        mfa._after_removal()                                       # noqa: SLF001 - same package
    if not mfa.required():
        twofactor.forget_devices()
    after = mfa.summary()
    if before == after:
        print("Nothing to turn off." if part != "all" else "Two-step sign-in was already off.")
    elif after["required"]:
        print(f"Turned off ({part}). Still asked: {_list(after)}.")
    else:
        print("Two-step sign-in is off: the password alone signs in again. Turn it back on in Settings -> Security.")
    return 0


def _list(s: dict) -> str:
    out = []
    if s["telegram"]["on"] and s["telegram"]["available"]:
        out.append("Telegram approval")
    if s["totp"]["on"]:
        out.append("authenticator app")
    if s["passkeys"]:
        out.append(f"{len(s['passkeys'])} passkey(s)")
    return ", ".join(out) or "nothing"


def _handler(a) -> int:
    from . import mfa, twofactor
    action = a.action or "status"
    if action == "off":
        return _off(getattr(a, "part", "all") or "all")
    if action == "forget-browsers":
        twofactor.forget_devices()
        print("Every browser will ask for the second step at its next sign-in.")
        return 0
    s = mfa.summary()
    if getattr(a, "json", False):
        tg = s["telegram"]
        print(json.dumps({"on": tg["on"], "telegram_linked": tg["available"], "active": s["required"],
                          "telegram": tg["on"] and tg["available"], "authenticator_app": s["totp"]["on"],
                          "passkeys": [{"name": p["name"], "host": p["rp_id"]} for p in s["passkeys"]],
                          "passkey_login": s["passkey_login"],
                          "recovery_codes_left": s["recovery_left"]}))
        return 0
    if not s["required"]:
        print("Two-step sign-in: off" + ("" if not s["telegram"]["on"] else
                                         " (Telegram approval is on, but no Telegram chat is linked)") +
              ". Turn it on in Settings -> Security.")
        return 0
    print(f"Two-step sign-in: on - {_list(s)}.")
    for p in s["passkeys"]:
        print(f"  passkey: {p['name']} ({p['rp_id']})")
    if s["passkey_login"]:
        print("  sign-in with a passkey alone: on (turn it off in Settings -> Security, or maxxing 2fa off passkeys)")
    if s["totp"]["on"] or s["passkeys"]:
        print(f"  recovery codes left: {s['recovery_left']}")
    print("Way out: maxxing 2fa off")
    return 0


cli.register("2fa", "two-step sign-in (Telegram, authenticator app, passkeys): status, off (way out over SSH), "
             "forget-browsers", _configure, _handler)
