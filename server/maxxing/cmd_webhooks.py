"""`maxxing webhooks …`: Settings -> Automate -> Webhooks and Events, from a session or a script (webhooks.py).

  maxxing webhooks list [--json]                  every hook (both pages), its state and last call
  maxxing webhooks show <id> [--json]             one hook; --sign-secret prints the key of its signed calls
  maxxing webhooks add [--spec JSON]              create a hook from its JSON definition (or JSON on stdin)
  maxxing webhooks edit <id> [--spec JSON]        replace parts of it (top-level keys: name, description, trigger,
                                                  action, queue, report, enabled)
  maxxing webhooks describe <id> "sentence"       the sentence shown on the page
  maxxing webhooks on|off|remove <id>
  maxxing webhooks url <id>                       its URL (a hook called from outside)
  maxxing webhooks rotate <id>                    a new URL (the old one stops working)
  maxxing webhooks secret <id>                    its signing secret / phone key, read on stdin (empty: removed)
  maxxing webhooks calls <id> [--limit N] [--json]    its last calls
  maxxing webhooks call <id> <call>               one call: request, body, result
  maxxing webhooks test <id>                      run it now on a realistic sample (here, in this process)
  maxxing webhooks replay <id> <call>             run a call again (here)
  maxxing webhooks data <id> [--last N] [--csv] [--json]   the rows of a "store" hook
  maxxing webhooks run <id> <call>                (internal) the command of a call, in its systemd unit
"""
from __future__ import annotations

import datetime as dt
import json
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="wh_cmd", required=True)
    r = sub.add_parser("list", help="list the webhooks and events")
    r.add_argument("--json", action="store_true")
    r = sub.add_parser("show", help="one hook")
    r.add_argument("id")
    r.add_argument("--json", action="store_true")
    r.add_argument("--sign-secret", action="store_true", help="print the key that signs its calls (X-Harness-Signature)")
    r = sub.add_parser("add", help="create a hook from its JSON definition (--spec or stdin)")
    r.add_argument("--spec", default=None)
    r = sub.add_parser("edit", help="change a hook (JSON: the top-level keys to replace)")
    r.add_argument("id")
    r.add_argument("--spec", default=None)
    r = sub.add_parser("describe", help="the sentence shown on the page")
    r.add_argument("id")
    r.add_argument("sentence")
    for name, hlp in (("on", "switch on"), ("off", "switch off"), ("remove", "delete (its calls and data too)"),
                      ("url", "print its URL"), ("rotate", "a new URL (the old one stops working)"),
                      ("secret", "set its signing secret / key from stdin (empty: remove it)"),
                      ("test", "run it now on a sample")):
        sub.add_parser(name, help=hlp).add_argument("id")
    r = sub.add_parser("calls", help="its last calls")
    r.add_argument("id")
    r.add_argument("--limit", type=int, default=20)
    r.add_argument("--json", action="store_true")
    for name, hlp in (("call", "one call in detail"), ("replay", "run a call again"), ("run", "(internal) run a call")):
        r = sub.add_parser(name, help=hlp)
        r.add_argument("id")
        r.add_argument("call")
    r = sub.add_parser("data", help="the rows of a store hook")
    r.add_argument("id")
    r.add_argument("--last", type=int, default=20)
    r.add_argument("--csv", action="store_true")
    r.add_argument("--json", action="store_true")


def _when(ts) -> str:
    try:
        return dt.datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return "-"


def _spec(a) -> dict:
    text = a.spec if a.spec is not None else sys.stdin.read()
    try:
        spec = json.loads(text)
    except ValueError as e:
        raise SystemExit(f"the definition is not valid JSON: {e}") from None
    if not isinstance(spec, dict):
        raise SystemExit("the definition must be a JSON object")
    return spec


def _line(h: dict) -> str:
    from . import webhooks
    state = "on " if h["enabled"] else "off"
    page = "webhook" if h["trigger"]["kind"] == "in" else "event"
    last = h.get("last_call")
    last_txt = f"{last['status']} {_when(last['at'])}" if last else "never called"
    extra = "  [needs its signing secret]" if h.get("needs_secret") else ""
    return f"{h['id']}  {state}  {page:<7}  {h['name']}  - {webhooks.describe(h)}  - {last_txt}{extra}"


def _handler(a) -> int:
    from . import webhooks
    W = webhooks.WebhookError
    try:
        c = a.wh_cmd
        if c == "run":
            return webhooks.run_shell(a.id, a.call)
        if c == "list":
            hooks = webhooks.list_hooks()
            if a.json:
                print(json.dumps(hooks, indent=2, ensure_ascii=False))
            elif not hooks:
                print("no webhooks nor events (Settings -> Automate)")
            for h in hooks if not a.json else []:
                print(_line(h))
            return 0
        if c == "show":
            if a.sign_secret:
                print(webhooks.sign_secret(a.id) or "(this hook does not sign its calls: action.sign is off)")
                return 0
            h = webhooks.public(webhooks.get(a.id))
            print(json.dumps(h, indent=2, ensure_ascii=False) if a.json else _line(h) + (f"\nURL: {h['url']}" if h["url"] else ""))
            return 0
        if c == "add":
            h = webhooks.create(_spec(a))
            print(f"created {h['id']}: {webhooks.describe(h)}")
            if h["url"]:
                print(f"URL: {h['url']}")
            if h.get("needs_secret"):
                print(f"Calls are refused until its signing secret is set: maxxing webhooks secret {h['id']} (value on stdin)")
            return 0
        if c == "edit":
            h = webhooks.update(a.id, _spec(a))
            print(f"updated {h['id']}: {webhooks.describe(h)}")
            return 0
        if c == "describe":
            webhooks.set_description(a.id, a.sentence)
            return 0
        if c in ("on", "off"):
            webhooks.set_enabled(a.id, c == "on")
            return 0
        if c == "remove":
            webhooks.remove(a.id)
            print(f"removed {a.id}")
            return 0
        if c in ("url", "rotate"):
            h = webhooks.rotate(a.id) if c == "rotate" else webhooks.public(webhooks.get(a.id), stats=False)
            if not h["url"]:
                print("this hook has no URL (an event hook, or no public address: Settings -> General)", file=sys.stderr)
                return 1
            print(h["url"])
            return 0
        if c == "secret":
            webhooks.set_secret(a.id, sys.stdin.read().strip())
            print("secret saved" if webhooks.public(webhooks.get(a.id), stats=False)["has_secret"] else "secret removed")
            return 0
        if c == "calls":
            rows = webhooks.calls(a.id, max(1, min(a.limit, webhooks.KEEP_CALLS)))
            if a.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
                return 0
            for r in rows:
                took = f" {r['duration_s']:.1f}s" if isinstance(r.get("duration_s"), (int, float)) else ""
                err = f"  ({r['error']})" if r.get("error") else ""
                print(f"{r['id']}  {_when(r['at'])}  {r['status']:<8} {r.get('trigger', ''):<6} {r.get('summary', '')}{took}{err}")
            return 0
        if c == "call":
            print(json.dumps(webhooks.call(a.id, a.call), indent=2, ensure_ascii=False))
            return 0
        if c in ("test", "replay"):
            rec = webhooks.test(a.id, inline=True) if c == "test" else webhooks.replay(a.id, a.call, inline=True)
            print(f"{rec.get('status')} - {rec.get('summary', '')}" + (f" ({rec['error']})" if rec.get("error") else ""))
            if rec.get("output"):
                print(rec["output"])
            return 0 if rec.get("status") == "ok" else 1
        if c == "data":
            if a.csv:
                sys.stdout.write(webhooks.data_csv(a.id, limit=max(1, a.last)))
                return 0
            rows = webhooks.data(a.id, limit=max(1, min(a.last, 1000)))
            if a.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
            for r in rows if not a.json else []:
                print(f"{r['id']}  {_when(r['at'])}  {json.dumps(r.get('fields') or r['data'], ensure_ascii=False)[:300]}")
            return 0
    except W as e:
        print(f"{e.code}: {e.message}", file=sys.stderr)
        return 1
    return 2


cli.register("webhooks", "webhooks and events: automations without AI (list, add, edit, test, calls, data…)",
             _configure, _handler)
