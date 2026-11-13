"""`maxxing browser` - the Harness Browser (maxxing/browser) from a terminal.

    maxxing browser setup                       install what it needs on this server (root): socat, Chromium, its
                                                user, its AppArmor profile, chrome-devtools-mcp
    maxxing browser status [--json]             feature, what is missing, its settings, tabs, requests waiting
    maxxing browser settings [--sites a.com,b.com | --public] [--fresh | --keep] [--ask | --no-ask] [--wait MIN]
                             [--downloads | --no-downloads] [--idle MIN] [--tab-sleep MIN] [--max-tabs N]
    maxxing browser on PATH                     the sessions of a topic (projects/<p>/topics/<t>) or an agent may use it
    maxxing browser off PATH
    maxxing browser show PATH [--json]          its switch and the tabs it sees
    maxxing browser forget                      erase the sign-ins, the tabs and the journal of its actions

PATH: `<p>/<t>` or `<p>/<t>/<agent>` work too. Settings belong to the owner: refused in an agent turn.
The running server restarts the browser when the sites, sign-ins or downloads setting changed (when nobody uses it).
"""
from __future__ import annotations

import json
import shutil
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="browser_cmd", required=True)
    sub.add_parser("setup", help="install what the browser needs on this server (root)")
    s = sub.add_parser("status", help="feature, what is missing, settings, tabs")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("settings", help="the browser's settings (sites, sign-ins, asks, sleep)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--sites", help="comma-separated sites it may open (subdomains included)")
    g.add_argument("--public", action="store_true", help="any public site")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--fresh", action="store_true", help="a new profile at every start (no sign-in kept)")
    g.add_argument("--keep", action="store_true", help="keep the sign-ins (default)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--ask", action="store_true", help="Claude may ask you to take over (captcha, sign-in)")
    g.add_argument("--no-ask", action="store_true", help="never ask you")
    s.add_argument("--wait", type=int, help="minutes Claude waits for you when it asks (default 30)")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--downloads", action="store_true", help="allow downloads (into <workspace>/downloads/browser)")
    g.add_argument("--no-downloads", action="store_true")
    s.add_argument("--idle", type=int, help="minutes without use before the browser sleeps (default 30)")
    s.add_argument("--tab-sleep", type=int, help="minutes without use before a tab sleeps (default 20)")
    s.add_argument("--max-tabs", type=int, help="tabs awake at once (default 12)")
    for name, text in (("on", "the sessions of a topic or an agent may use the browser"), ("off", "they may not")):
        s = sub.add_parser(name, help=text)
        s.add_argument("path")
    s = sub.add_parser("show", help="a topic's / an agent's switch and the tabs it sees")
    s.add_argument("path")
    s.add_argument("--json", action="store_true")
    sub.add_parser("forget", help="erase the sign-ins, the tabs and the journal")


def _path(raw: str) -> str:
    p = raw.strip().strip("/")
    if not p.startswith("projects/"):
        parts = p.split("/")
        if len(parts) == 2:
            p = f"projects/{parts[0]}/topics/{parts[1]}"
        elif len(parts) == 3:
            p = f"projects/{parts[0]}/topics/{parts[1]}/agents/{parts[2]}"
    from . import agents, browser, config
    owner = browser.owner_of(p)
    if not owner or (owner.startswith("agent:") and not agents.exists(p)) or \
            (owner.startswith("topic:") and not (config.workspace() / p).is_dir()):
        raise SystemExit(f"Not a topic or an agent folder: {raw}")
    return owner


def _switch(owner: str, enabled: bool) -> None:
    from . import agents, browser
    block = browser.clean({"enabled": enabled}, strict=True)
    path = browser.owner_path(owner)
    if owner.startswith("agent:"):
        agents.update(path, {"browser": block})
    else:
        from . import workspace
        workspace.set_topic_browser(path, block)


def _tabs(path: str | None = None) -> list[dict]:
    from . import browser
    from .browser.tabs import Tabs
    t = Tabs()
    t.load()
    return [x for x in t.ordered() if path is None or browser.visible(x["scope"], path)]


def _handler(a) -> int:
    from . import browser
    from .browser import asks, replays, unit
    cmd = a.browser_cmd
    try:
        if cmd == "setup":
            for line in unit.setup(print):
                print(line)
            st = unit.available(fresh=True)
            print("ready" if st["ok"] else "still missing: " + ", ".join(st["missing"]))
            if st["ok"] and not browser.feature_on():
                print("Turn it on: Settings -> Features -> Harness Browser.")
            return 0 if st["ok"] else 1
        if cmd == "status":
            st = {"feature": browser.feature_on(), "settings": browser.settings(),
                  "available": unit.available(fresh=True), "tabs": _tabs(), "asks": asks.pending()}
            if a.json:
                print(json.dumps(st, indent=2))
                return 0
            s = st["settings"]
            print(f"feature: {'on' if st['feature'] else 'off (Settings -> Features)'}")
            print("server: " + ("ready" if st["available"]["ok"] else "missing " + ", ".join(st["available"]["missing"])
                                + " -> maxxing browser setup"))
            print("sites: " + ("any public site" if s["web"] == "public" else ", ".join(s["sites"]) or "none yet"))
            print(f"sign-ins: {'kept' if s['profile'] == 'keep' else 'never kept'}; asks you: "
                  f"{'yes, waits ' + str(s['wait_min']) + ' min' if s['ask'] else 'no'}; sleeps after "
                  f"{s['idle_min']} min, a tab after {s['tab_sleep_min']} min, {s['max_tabs']} tabs awake at most")
            for t in st["tabs"]:
                print(f"tab ({t['scope']}): {t['title'] or t['url']}")
            for d in st["asks"]:
                print(f"waiting for you: {browser.owner_path(d['owner'])}: {d['reason']}")
            return 0
        if cmd == "settings":
            ch: dict = {}
            if a.public:
                ch["web"] = "public"
            if a.sites is not None:
                ch.update(web="list", sites=[x.strip() for x in a.sites.split(",") if x.strip()])
            if a.fresh or a.keep:
                ch["profile"] = "fresh" if a.fresh else "keep"
            if a.ask or a.no_ask:
                ch["ask"] = bool(a.ask)
            if a.downloads or a.no_downloads:
                ch["downloads"] = bool(a.downloads)
            for key, val in (("wait_min", a.wait), ("idle_min", a.idle), ("tab_sleep_min", a.tab_sleep),
                             ("max_tabs", a.max_tabs)):
                if val is not None:
                    ch[key] = val
            print(json.dumps(browser.set_settings(ch) if ch else browser.settings()))
            return 0
        if cmd == "forget":
            shutil.rmtree(browser.profiles_dir() / browser.SLUG, ignore_errors=True)
            (browser.home() / "tabs.json").unlink(missing_ok=True)
            replays.forget(browser.SLUG)
            print("sign-ins, tabs and journal erased (a running browser keeps them until it stops: stop it from the page)")
            return 0
        owner = _path(a.path)
        path = browser.owner_path(owner)
        if cmd in ("on", "off"):
            _switch(owner, cmd == "on")
            print(f"Harness Browser {'on' if cmd == 'on' else 'off'} for {path}"
                  + ("" if browser.feature_on() or cmd == "off" else ". The feature is off: Settings -> Features."))
            return 0
        if cmd == "show":
            s = browser.owner_settings(owner)
            info = {"owner": owner, "enabled": s["enabled"], "tabs": _tabs(path)}
            if a.json:
                print(json.dumps(info, indent=2))
                return 0
            print(f"{path}: {'may use the Harness Browser' if s['enabled'] else 'off'}")
            for t in info["tabs"]:
                print(f"tab ({t['scope']}): {t['title'] or t['url']}")
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


cli.register("browser", "the Harness Browser: setup, status, settings, on / off for a topic or an agent",
             _configure, _handler)
