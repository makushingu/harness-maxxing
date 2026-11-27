"""`maxxing 2fa` - two-step sign-in (Telegram, authenticator app), from the server (the way out when Telegram does
not answer or the phone with the app is lost).

    maxxing 2fa status              on / off, Telegram linked or not, authenticator app
    maxxing 2fa off                 password only again: Telegram step and authenticator app off, recovery codes
                                    dropped (every trusted browser is forgotten)
    maxxing 2fa forget-browsers     every browser asks again at its next sign-in

Turning it on needs an approval in Telegram: Settings -> Telegram -> Two-step sign-in.
"""
from __future__ import annotations

import json

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action")
    st = sub.add_parser("status", help="on / off, Telegram linked or not")
    st.add_argument("--json", action="store_true")
    sub.add_parser("off", help="password only again (the way out when Telegram does not answer)")
    sub.add_parser("forget-browsers", help="every trusted browser asks again")


def _handler(a) -> int:
    from . import twofactor
    action = a.action or "status"
    if action == "off":
        was, app = twofactor.is_on(), twofactor.totp_on()
        twofactor.totp_off()
        twofactor.set_on(False)
        if was:
            twofactor.notify("off_cli")
        print("Two-step sign-in is off: the password alone signs in again. "
              "Turn it back on in Settings -> Security." if was or app else "Two-step sign-in was already off.")
        return 0
    if action == "forget-browsers":
        twofactor.forget_devices()
        print("Every browser will ask for a Telegram approval at its next sign-in.")
        return 0
    on, linked, app = twofactor.is_on(), twofactor.available(), twofactor.totp_on()
    if getattr(a, "json", False):
        print(json.dumps({"on": on, "telegram_linked": linked, "active": on and linked, "totp": app,
                          "recovery_codes": twofactor.recovery_left()}))
        return 0
    if app:
        print(f"Authenticator app: on ({twofactor.recovery_left()} recovery codes left). Way out: maxxing 2fa off")
    if on and linked:
        print("Two-step sign-in: on (Telegram approval for every new browser). Way out: maxxing 2fa off")
    elif on:
        print("Two-step sign-in: on, but no Telegram chat is linked - not asked until one is linked again.")
    else:
        # with the app on, sign-in does ask for a second step: only the Telegram approval is off
        print(("Telegram approval: off" if app else "Two-step sign-in: off")
              + ("" if linked else " (link Telegram first: Settings -> Telegram)") + ".")
    return 0


cli.register("2fa", "two-step sign-in (Telegram, authenticator app): status, off (way out over SSH), forget-browsers",
             _configure, _handler)
