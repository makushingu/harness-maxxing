"""`maxxing 2fa` - two-step sign-in with Telegram, from the server (the way out when Telegram does not answer).

    maxxing 2fa status              on / off, Telegram linked or not
    maxxing 2fa off                 password only again (every trusted browser is forgotten)
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
        was = twofactor.is_on()
        twofactor.set_on(False)
        if was:
            twofactor.notify("off_cli")
        print("Two-step sign-in is off: the password alone signs in again. "
              "Turn it back on in Settings -> Telegram." if was else "Two-step sign-in was already off.")
        return 0
    if action == "forget-browsers":
        twofactor.forget_devices()
        print("Every browser will ask for a Telegram approval at its next sign-in.")
        return 0
    on, linked = twofactor.is_on(), twofactor.available()
    if getattr(a, "json", False):
        print(json.dumps({"on": on, "telegram_linked": linked, "active": on and linked}))
        return 0
    if on and linked:
        print("Two-step sign-in: on (Telegram approval for every new browser). Way out: maxxing 2fa off")
    elif on:
        print("Two-step sign-in: on, but no Telegram chat is linked - not asked until one is linked again.")
    else:
        print("Two-step sign-in: off" + ("" if linked else " (link Telegram first: Settings -> Telegram)") + ".")
    return 0


cli.register("2fa", "two-step sign-in with Telegram: status, off (way out over SSH), forget-browsers",
             _configure, _handler)
