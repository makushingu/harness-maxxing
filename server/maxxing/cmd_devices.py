"""`maxxing devices` - the person's devices Claude may use (maxxing/devices), from a terminal.
Claude uses them with its tools (mcp__harness-devices__*), never with this command.

    maxxing devices list [--json]               devices (online, rights, access), codes and requests waiting
    maxxing devices add [--os linux|darwin|windows|android]
                                                a one-time code (15 min): the command to run on the computer, or the
                                                link to open on the phone
    maxxing devices confirm ID [--refuse]       accept (or refuse) a device that paired and waits
    maxxing devices remove ID                   remove it: its app forgets this server and stops
    maxxing devices rename ID NAME
    maxxing devices mode ID view|control        view: Claude looks and guides; control: it clicks and types
    maxxing devices screen ID N|main            a computer with several screens: the one Claude sees and uses (and
                                                the live view shows); `list` shows their numbers
    maxxing devices access ID --all | [--project NAME ...] [--agent PATH ...]
                                                who may use it: every project and agent, or the ones named (an agent
                                                also needs it in its agent.json `devices`, unless it is free and named
                                                here)
    maxxing devices enable|disable              switch the feature on / off (as Settings -> Features)
ID: the device id (dev_…) or its name.
"""
from __future__ import annotations

import json
import sys
import time

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="devices_cmd", required=True)
    s = sub.add_parser("list", help="devices, codes and requests waiting")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("add", help="a one-time code to connect a device (15 min)")
    s.add_argument("--os", choices=["linux", "darwin", "windows", "android"], default="")
    s = sub.add_parser("confirm", help="accept a device waiting (or --refuse it)")
    s.add_argument("id")
    s.add_argument("--refuse", action="store_true")
    s = sub.add_parser("remove", help="remove a device (its app forgets this server)")
    s.add_argument("id")
    s = sub.add_parser("rename", help="rename a device")
    s.add_argument("id")
    s.add_argument("name")
    s = sub.add_parser("mode", help="view (Claude looks) or control (Claude acts)")
    s.add_argument("id")
    s.add_argument("mode", choices=["view", "control"])
    s = sub.add_parser("screen", help="several screens: the one Claude sees and uses")
    s.add_argument("id")
    s.add_argument("screen", help="the screen number (maxxing devices list) or main")
    s = sub.add_parser("access", help="which projects and agents may use it")
    s.add_argument("id")
    s.add_argument("--all", action="store_true", help="every project and agent")
    s.add_argument("--project", action="append", default=[], help="a project name (repeatable)")
    s.add_argument("--agent", action="append", default=[], help="an agent path, projects/<p>/topics/<t>/agents/<a>")
    sub.add_parser("enable", help="switch the feature on (Settings -> Features)")
    sub.add_parser("disable", help="switch the feature off")


def _ago(t: float | None) -> str:
    if not t:
        return "never"
    s = int(time.time() - t)
    return "now" if s < 60 else f"{s // 60} min ago" if s < 3600 else f"{s // 3600} h ago" if s < 86400 else \
        f"{s // 86400} d ago"


def _server_url() -> str:
    from . import config
    base = (config.load_config().get("public_url") or "").rstrip("/")
    return base or f"http://{config.local_host()}:{config.local_port()}"


def _handler(a) -> int:
    from . import config, devices
    from .devices import dist, store
    cmd = a.devices_cmd
    try:
        if cmd in ("enable", "disable"):
            config.update_config(devices_feature=cmd == "enable")
            print("on: add a device in Settings -> Devices or with `maxxing devices add`" if cmd == "enable" else
                  "off: no session or agent gets the devices any more")
            return 0
        if cmd == "list":
            devs = store.devices()
            if a.json:
                print(json.dumps({"feature": devices.feature_on(), "devices": [store.public(d) for d in devs],
                                  "invites": store.invites_public(), "available": dist.available()}, indent=2))
                return 0
            if not devices.feature_on():
                print("Devices are off (maxxing devices enable, or Settings -> Features).")
            if not devs:
                print("No device. Add one: maxxing devices add")
            for d in devs:
                state = "waiting for your OK (maxxing devices confirm " + d["id"] + ")" if not d.get("confirmed") \
                    else f"seen {_ago(d.get('last_seen'))}"
                print(f"{d['id']}  {d['name']}  ({devices.OS_NAMES.get(d['os'], d['os'])}"
                      f"{', ' + d['version'] if d.get('version') else ''})  {d['mode']}  "
                      f"access: {', '.join(d.get('scope') or []) or 'nobody'}  {state}")
                screens = d.get("screens") or []             # as the app last described them
                if len(screens) > 1:
                    cur = d.get("display") if isinstance(d.get("display"), int) and d["display"] >= 0 else \
                        next((x["i"] for x in screens if x.get("main")), 0)
                    for x in screens:
                        mark = "*" if x["i"] == cur else " "
                        print(f"    {mark} screen {x['i']}  {x['name']}  {x['w']}x{x['h']}{'  main' if x.get('main') else ''}")
            n = len(store.invites_public())
            if n:
                print(f"{n} code(s) waiting to be used")
            return 0
        if cmd == "add":
            if not devices.feature_on():
                print("Devices are off: maxxing devices enable", file=sys.stderr)
                return 1
            inv = store.new_invite(a.os)
            base, code = _server_url(), inv["code"]
            cmds = dist.commands(base, code)
            print(f"Code {code} - valid 15 minutes, once. Do not share it.")
            if a.os in ("", "linux", "darwin"):
                print(f"Linux / Mac, in a Terminal:\n  {cmds['sh']}")
            if a.os in ("", "windows"):
                print(f"Windows, in PowerShell:\n  {cmds['ps1']}")
            if a.os in ("", "android"):
                print(f"Android: open {base}/link/{code} on the phone (or type the server {base} and the code in "
                      "Harness Link)")
            if not dist.available():
                print("Note: Harness Link is not available for download on this server yet.", file=sys.stderr)
            print("Then accept the device: maxxing devices confirm <id> (or Settings -> Devices).")
            if a.os != "android":
                print("On a computer, Harness Link runs only in that terminal window; later, type harness-link in a "
                      "terminal whenever Claude may use it.")
            return 0
        dev = store.resolve(a.id)
        if dev is None:
            print(f"No device {a.id!r} (maxxing devices list)", file=sys.stderr)
            return 1
        if cmd == "confirm":
            if not store.confirm(dev["id"], not a.refuse):
                print(f"{dev['name']} is not waiting for an answer", file=sys.stderr)
                return 1
            print(("refused: its app forgets this server" if a.refuse else f"{dev['name']} accepted"))
            return 0
        if cmd == "remove":
            store.remove(dev["id"])
            print(f"{dev['name']} removed: its app forgets this server within a few seconds")
            return 0
        if cmd == "rename":
            print(store.update(dev["id"], name=a.name)["name"])
            return 0
        if cmd == "mode":
            store.update(dev["id"], mode=a.mode)
            print(f"{dev['name']}: {'view only' if a.mode == 'view' else 'control'}")
            return 0
        if cmd == "screen":
            want = a.screen.strip().lower()
            if want != "main" and not want.lstrip("-").isdigit():
                print("screen: a number (maxxing devices list) or main", file=sys.stderr)
                return 1
            n = -1 if want == "main" else int(want)
            out = store.update(dev["id"], display=n)
            print(f"{dev['name']}: " + ("the main screen" if out.get("display", -1) < 0 else f"screen {out['display']}") +
                  " (Harness Link switches within a few seconds)")
            return 0
        if cmd == "access":
            scope = ["*"] if a.all else [f"project:{p}" for p in a.project] + [f"agent:{p.strip('/')}" for p in a.agent]
            out = store.update(dev["id"], scope=scope)
            print(f"{dev['name']}: " + (", ".join(out["scope"]) or "nobody"))
            return 0
    except devices.DevicesError as e:
        print(e.message, file=sys.stderr)
        return 1
    return 2


cli.register("devices", "the person's devices Claude may use (computers, phones with Harness Link)", _configure, _handler)
