"""`maxxing 2fa` - two-step sign-in, from the server (the way out when the second step is lost).

    maxxing 2fa status              what is on: Telegram, authenticator app, passkeys, recovery codes left
    maxxing 2fa off                 password only again: every method off, every trusted browser forgotten
    maxxing 2fa forget-browsers     every browser asks again at its next sign-in

Turning a method on happens in Settings -> Security (Telegram: an approval in Telegram).
"""
from __future__ import annotations

import json

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="action")
    st = sub.add_parser("status", help="what is on: Telegram, authenticator app, passkeys")
    st.add_argument("--json", action="store_true")
    sub.add_parser("off", help="password only again (the way out when the second step is lost)")
    sub.add_parser("forget-browsers", help="every trusted browser asks again")


def _handler(a) -> int:
    from . import twofactor, twofactor_apps
    action = a.action or "status"
    if action == "off":
        was_tg = twofactor.is_on()
        twofactor.set_on(False)
        was_apps = twofactor_apps.turn_all_off()
        if was_tg:
            twofactor.notify("off_cli")
        print("Two-step sign-in is off: the password alone signs in again (authenticator app, passkeys and recovery "
              "codes removed). Turn it back on in Settings -> Security." if (was_tg or was_apps)
              else "Two-step sign-in was already off.")
        return 0
    if action == "forget-browsers":
        twofactor.forget_devices()
        print("Every browser will ask for the second step at its next sign-in.")
        return 0
    on, linked = twofactor.is_on(), twofactor.available()
    s = twofactor_apps.summary("")
    if getattr(a, "json", False):
        print(json.dumps({"on": on, "telegram_linked": linked, "active": (on and linked) or twofactor_apps.any_on(),
                          "totp": s["totp"], "passkeys": len(s["passkeys"]), "recovery_left": s["recovery_left"]}))
        return 0
    parts = []
    if on and linked:
        parts.append("Telegram approval")
    elif on:
        parts.append("Telegram (no chat linked: not asked until one is linked again)")
    if s["totp"]:
        parts.append("authenticator app")
    if s["passkeys"]:
        parts.append(f"{len(s['passkeys'])} passkey(s)")
    if parts:
        extra = f", {s['recovery_left']} recovery code(s) left" if twofactor_apps.any_on() else ""
        print(f"Two-step sign-in: on ({', '.join(parts)}{extra}). Way out: maxxing 2fa off")
    else:
        print("Two-step sign-in: off (Settings -> Security).")
    return 0


cli.register("2fa", "two-step sign-in: status, off (way out over SSH), forget-browsers", _configure, _handler)
