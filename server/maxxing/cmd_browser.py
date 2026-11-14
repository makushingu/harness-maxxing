"""`maxxing browser` - the Harness Browser (maxxing/browser) from a terminal.
Claude browses with its tools (one set per turn), never with this command: it says who may use the browser and how.

    maxxing browser status [--json]             feature, what is missing, settings, browsers, exits, requests waiting
    maxxing browser show PATH [--json]          what a project / topic / agent gets (and where it is inherited from)
    maxxing browser set PATH on|off|inherit [--profile ID|inherit]
                                                may its sessions use it (`inherit` = its parent's switch, not for an
                                                agent); sessions use their project's profile (made the first time);
                                                an agent too, unless `--profile` picks another (`inherit` = back to
                                                its project's)
    maxxing browser enable|disable              switch the feature on / off (as Settings -> Features); `enable` installs
                                                what is missing first
    maxxing browser setup [--exits]             install what it needs on this server (root): socat, Chromium, its
                                                user, its AppArmor profile, chrome-devtools-mcp (+ Tailscale and
                                                wireproxy for the exits)
    maxxing browser forget ID                   erase a browser's sign-ins, tabs and journal
    maxxing browser exit test ID|direct         the address the sites see through it, its kind, delay, speed
Advanced:
    maxxing browser settings [--ask | --no-ask] [--wait MIN] [--downloads | --no-downloads] [--idle MIN]
                             [--tab-sleep MIN] [--max-tabs N] [--max-profiles N]
    maxxing browser profile add NAME [--exit ID] [--fallback-vps]
    maxxing browser profile set ID [--name N] [--exit ID] [--fallback-vps | --wait-exit]
    maxxing browser profile rm ID               its sign-ins too (not a project's: `forget` it); its agents go back
                                                to their project's
PATH: `<p>`, `<p>/<t>`, `<p>/<t>/<agent>` or the full folder. Settings belong to the owner: refused in an agent turn.
Exits are added on the Browser page (their passwords go to the vault). A browser opens any public site, a sandboxed
agent's only its domains (`maxxing agents set PATH domains='["example.com"]'`).
"""
from __future__ import annotations

import json
import shutil
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="browser_cmd", required=True)
    s = sub.add_parser("setup", help="install what the browser needs on this server (root)")
    s.add_argument("--exits", action="store_true", help="also Tailscale and wireproxy (exits by a phone or a box)")
    sub.add_parser("enable", help="switch the feature on (installs what is missing first)")
    sub.add_parser("disable", help="switch the feature off (Settings -> Features)")
    s = sub.add_parser("status", help="feature, what is missing, settings, profiles, exits")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("settings", help="global settings (asks, downloads, sleep)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--ask", action="store_true", help="Claude may ask you to take over (captcha, sign-in)")
    g.add_argument("--no-ask", action="store_true", help="never ask you")
    s.add_argument("--wait", type=int, help="minutes Claude waits for you when it asks (default 30)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--downloads", action="store_true", help="allow downloads (into <workspace>/downloads/browser)")
    g.add_argument("--no-downloads", action="store_true")
    s.add_argument("--idle", type=int, help="minutes without use before a profile sleeps (default 30)")
    s.add_argument("--tab-sleep", type=int, help="minutes without use before a tab sleeps (default 20)")
    s.add_argument("--max-tabs", type=int, help="tabs awake at once per profile (default 12)")
    s.add_argument("--max-profiles", type=int, help="profiles running at once (default 3)")
    pr = sub.add_parser("profile", help="add, change or remove a profile").add_subparsers(dest="profile_cmd",
                                                                                         required=True)
    for name in ("add", "set"):
        s = pr.add_parser(name)
        s.add_argument("name" if name == "add" else "id")
        if name == "set":
            s.add_argument("--name")
        s.add_argument("--exit", help="an exit id (Browser page -> Exits), or direct")
        g = s.add_mutually_exclusive_group()
        g.add_argument("--fallback-vps", action="store_true", help="exit down: go out by this server's address")
        g.add_argument("--wait-exit", action="store_true", help="exit down: wait for it (default)")
    s = pr.add_parser("rm")
    s.add_argument("id")
    ex = sub.add_parser("exit", help="test an exit").add_subparsers(dest="exit_cmd", required=True)
    s = ex.add_parser("test")
    s.add_argument("id")
    s = sub.add_parser("set", help="may a project / topic / agent use the browser, and which one")
    s.add_argument("path")
    s.add_argument("state", choices=("on", "off", "inherit"), help="inherit: its parent's switch (not an agent)")
    s.add_argument("--profile", help="an agent's profile: an id, or inherit (its project's)")
    s = sub.add_parser("show", help="what a project / topic / agent gets, and from where")
    s.add_argument("path")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("forget", help="erase a profile's sign-ins, tabs and journal")
    s.add_argument("id")


def _path(raw: str) -> str:
    p = raw.strip().strip("/")
    if not p.startswith("projects/"):
        parts = p.split("/")
        p = {1: f"projects/{parts[0]}", 2: f"projects/{parts[0]}/topics/{parts[-1]}"}.get(len(parts)) or (
            f"projects/{parts[0]}/topics/{parts[1]}/agents/{parts[2]}" if len(parts) == 3 else p)
    from . import agents, browser, config
    owner = browser.owner_of(p)
    if not owner or (owner.startswith("agent:") and not agents.exists(p)) or \
            (not owner.startswith("agent:") and not (config.workspace() / p).is_dir()):
        raise SystemExit(f"Not a project, a topic or an agent folder: {raw}")
    return owner


def _save(owner: str, change: dict, inherit: tuple[str, ...] = ()) -> None:
    from . import agents, browser
    block = {**browser.own_block(owner), **change}
    for k in inherit:
        block.pop(k, None)
    block = browser.clean(block, strict=True)
    path = browser.owner_path(owner)
    if owner.startswith("agent:"):
        cur = agents.load(path).get("browser") or {}
        agents.update(path, {"browser": {**{k: None for k in cur}, **block}})
    else:
        from . import workspace
        workspace.set_folder_browser(path, block)


def _profile_values(a) -> dict:
    v: dict = {}
    if getattr(a, "name", None) and a.browser_cmd == "profile" and a.profile_cmd == "set":
        v["name"] = a.name
    if a.exit:
        v["exit"] = a.exit
    if a.fallback_vps or a.wait_exit:
        v["on_exit_down"] = "vps" if a.fallback_vps else "wait"
    return v


def _handler(a) -> int:
    from . import browser
    from .browser import asks, exits, replays, unit
    cmd = a.browser_cmd
    try:
        if cmd == "setup":
            for line in unit.setup(print):
                print(line)
            if a.exits:
                for line in exits.setup_tools(log_line=print):
                    print(line)
            st = unit.available(fresh=True)
            print("ready" if st["ok"] else "still missing: " + ", ".join(st["missing"]))
            if st["ok"] and not browser.feature_on():
                print("Turn it on: maxxing browser enable (or Settings -> Features -> Harness Browser).")
            return 0 if st["ok"] else 1
        if cmd in ("enable", "disable"):
            from . import config
            if cmd == "enable" and not unit.available(fresh=True)["ok"]:
                for line in unit.setup(print):
                    print(line)
                st = unit.available(fresh=True)
                if not st["ok"]:
                    print("still missing: " + ", ".join(st["missing"]) + " - the feature stays off", file=sys.stderr)
                    return 1
            config.update_config(browser_feature=cmd == "enable")
            print("on: every session has it from its next message (an agent once turned on); your browser: Settings "
                  "-> Browser" if cmd == "enable" else "off: no session or agent gets it any more")
            return 0
        if cmd == "status":
            s = browser.settings()
            st = {"feature": browser.feature_on(), "settings": s, "available": unit.available(fresh=True),
                  "asks": asks.pending()}
            if a.json:
                print(json.dumps(st, indent=2))
                return 0
            print(f"feature: {'on' if st['feature'] else 'off (maxxing browser enable, or Settings -> Features)'}")
            print("server: " + ("ready" if st["available"]["ok"] else "missing " + ", ".join(st["available"]["missing"])
                                + " -> maxxing browser setup"))
            print(f"asks you: {'yes, waits ' + str(s['wait_min']) + ' min' if s['ask'] else 'no'}; a profile sleeps "
                  f"after {s['idle_min']} min, a tab after {s['tab_sleep_min']} min; {s['max_active_profiles']} "
                  f"profiles at once, {s['max_tabs']} tabs awake each")
            names = {e["id"]: e["name"] for e in s["exits"]}
            for p in s["profiles"]:
                print(f"profile {p['id']} ({p['name'] or 'General'}"
                      + (f", project {p['project'].split('/', 1)[1]}" if p.get("project")
                         else ", the user's own and the projects general and system" if p["id"] == "main"
                         else ", added by hand") + f"): exit {names.get(p['exit'], p['exit'])}"
                      + ("; exit down: this server's address" if p["on_exit_down"] == "vps" else ""))
            for e in s["exits"]:
                print(f"exit {e['id']} ({e['name']}): {e['type']}")
            for d in st["asks"]:
                print(f"waiting for you: {browser.owner_path(d['owner'])}: {d['reason']}")
            return 0
        if cmd == "settings":
            ch: dict = {}
            if a.ask or a.no_ask:
                ch["ask"] = bool(a.ask)
            if a.downloads or a.no_downloads:
                ch["downloads"] = bool(a.downloads)
            for key, val in (("wait_min", a.wait), ("idle_min", a.idle), ("tab_sleep_min", a.tab_sleep),
                             ("max_tabs", a.max_tabs), ("max_active_profiles", a.max_profiles)):
                if val is not None:
                    ch[key] = val
            out = browser.set_settings(ch) if ch else browser.settings()
            print(json.dumps({k: v for k, v in out.items() if k not in ("profiles", "exits")}))
            return 0
        if cmd == "profile":
            if a.profile_cmd == "add":
                print(json.dumps(browser.set_profile({"name": a.name, **_profile_values(a)})))
            elif a.profile_cmd == "set":
                print(json.dumps(browser.set_profile(_profile_values(a), a.id)))
            else:
                browser.delete_profile(a.id)
                if shutil.which("systemctl"):                # stop its Chromium before its folder goes
                    import subprocess
                    from .browser import unit
                    subprocess.run(["systemctl", "stop", unit.unit_name(a.id)], capture_output=True, timeout=30)
                shutil.rmtree(browser.profile_dir(a.id), ignore_errors=True)
                (browser.tabs_dir() / f"{a.id}.json").unlink(missing_ok=True)
                print(f"profile {a.id} deleted")
            return 0
        if cmd == "exit":
            import asyncio
            out = asyncio.run(exits.runtime().test(a.id))
            print(json.dumps(out, indent=2))
            return 0 if out.get("ok") else 1
        if cmd == "forget":
            if browser.profile(a.id) is None:
                raise browser.BrowserError(404, "no_profile", f"No profile {a.id}")
            shutil.rmtree(browser.profile_dir(a.id), ignore_errors=True)
            (browser.tabs_dir() / f"{a.id}.json").unlink(missing_ok=True)
            replays.forget(a.id)
            print("sign-ins, tabs and journal erased (a running profile keeps them until it stops: stop it from the page)")
            return 0
        owner = _path(a.path)
        path = browser.owner_path(owner)
        if cmd == "set":
            agent = owner.startswith("agent:")
            if a.state == "inherit" and agent:
                raise browser.BrowserError(400, "bad_browser", "An agent's switch is its own: on or off")
            change: dict = {} if a.state == "inherit" else {"enabled": a.state == "on"}
            inherit = ["enabled"] if a.state == "inherit" else []
            prof = a.profile
            if prof and not agent:
                raise browser.BrowserError(400, "bad_browser", "A project's sessions use its profile: only an agent chooses")
            if prof == "inherit":
                inherit.append("profile")
            elif prof and browser.profile(prof) is None:
                raise browser.BrowserError(404, "no_profile", f"No browser profile {prof}")
            elif prof:
                change["profile"] = prof
            _save(owner, change, tuple(inherit))
            r = browser.resolve(path)
            print(f"{path}: {'may use the Harness Browser' if r['enabled'] else 'no browser'}; profile "
                  f"{r['profile'] or 'of ' + r['project'] + ' (made at first use)'}"
                  + (f" (inherited from {browser.owner_path(r['from']['profile'])})"
                     if r["from"]["profile"] and r["from"]["profile"] != owner else "")
                  + ("" if browser.feature_on() or not r["enabled"] else ". The feature is off: maxxing browser enable (or Settings -> Features)."))
            return 0
        if cmd == "show":
            r = browser.resolve(path)
            info = {"owner": owner, "own": browser.own_block(owner), **r}
            if a.json:
                print(json.dumps(info, indent=2))
                return 0

            def where(k: str) -> str:
                o = r["from"][k]
                return "" if o == owner else f" (inherited from {browser.owner_path(o)})" if o else " (default)"
            print(f"{path}: {'may use the Harness Browser' if r['enabled'] else 'off'}{where('enabled')}; "
                  f"profile {r['profile'] or 'of ' + r['project'] + ' (made at first use)'}{where('profile')}")
            return 0
    except browser.BrowserError as e:
        print(e.message, file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - AgentError and friends: their message
        msg = getattr(e, "message", None)
        if msg:
            print(msg, file=sys.stderr)
            return 1
        raise
    return 2


cli.register("browser", "the Harness Browser: setup, status, profiles, exits, on / off for a project, topic or agent",
             _configure, _handler)
