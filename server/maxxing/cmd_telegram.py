"""`maxxing telegram status|test|mode` - inspect, test and set up the Telegram bridge from a shell."""
from __future__ import annotations

import json

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="tg_cmd", required=True)
    s = sub.add_parser("status", help="show the Telegram configuration")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    sub.add_parser("test", help="send a test message to the linked chat")
    m = sub.add_parser("mode", help="show or choose the mode: simple (one chat), threads (one thread per session), "
                                    "mirror (threads + web conversations copied)")
    m.add_argument("mode", nargs="?", choices=("simple", "threads", "mirror"))


def _age(sec: float | None) -> str:
    if sec is None:
        return "never"
    sec = int(sec)
    return f"{sec} s ago" if sec < 120 else f"{sec // 60} min ago" if sec < 7200 else f"{sec // 3600} h ago"


def _handler(a) -> int:
    # This process is not the server: status() reads the state file the server's poller writes
    # (heartbeat last_poll_ok + poller_pid, poll_error, sync_error, pending link).
    from .telegram import gateway
    if a.tg_cmd == "mode":
        if not a.mode:
            print(gateway.mode())
            return 0
        res = gateway.set_mode(a.mode, wait=True)
        print(f"Mode: {res['mode']}" + (f" - {res['deleting']} thread(s) deleted in Telegram (agents' threads kept)"
                                        if res["deleting"] else ""))
        if a.mode != "simple":
            print("The threads are created within a few minutes (or press Retry in Settings > Telegram).")
        return 0
    st = gateway.status()
    if a.tg_cmd == "status":
        if getattr(a, "json", False):
            print(json.dumps(st, indent=2))
            return 0
        bot = st["bot"] or {}
        print(f"configured : {'yes' if st['configured'] else 'no'}")
        print(f"bot        : @{bot.get('username')}" if bot else "bot        : -")
        chat = st["chat"]
        print(f"chat       : {chat['title']} ({chat['id']})" if chat else "chat       : not linked")
        if st["configured"]:
            print(f"poller     : {'running' if st['running'] else 'stopped'} · last answer from Telegram "
                  f"{_age(st.get('last_poll_age'))}")
        link = st.get("link")
        if link:
            left = "expired" if link["expired"] else f"pending ({link['expires_in'] // 60} min left)"
            print(f"link       : {left}")
        print(f"mode       : {st['mode']}" + ("" if st["topics_enabled"] or st["mode"] == "simple"
                                                 else " (threads refused by Telegram: works as simple)"))
        print(f"threads    : {len(st['threads'])} (topics {'on' if st['topics_enabled'] else 'off'})")
        for th in st["threads"]:
            kind = f"session {th['session_id'][:8]}" if th.get("session_id") else th["path"]
            print(f"  - {th['name'] or '?'}  [{kind}]")
        for th in st.get("agent_threads") or []:
            print(f"  - {th['name'] or '?'}  [agent {th['path']}]")
        s = st["settings"]
        print(f"settings   : crons={s['notify_crons']} sign-ins={s['login_alerts']} system={s['notify_system']} "
              f"replies={s['reply_mode']}" + (f" thread_days={s.get('thread_days')}" if s["mode"] != "simple" else ""))
        if st.get("poll_error"):
            print(f"poll error : {st['poll_error']}")
        if st.get("sync_error"):
            print(f"sync error : {st['sync_error']}")
        if st.get("topics_notice"):
            print("note       : threads are off for this bot - turn on Threaded Mode in @BotFather, then Retry "
                  "in Settings > Telegram")
        return 0
    if not st["configured"] or not st["chat"]:
        print("Telegram is not linked - configure it in Settings > Telegram.")
        return 1
    res = gateway.send_test()
    print("Test message sent." if res["sent"] else "Telegram did not accept the message.")
    p = res["poller"]
    print(f"Poller: {'running' if p['running'] else 'stopped'} · last answer from Telegram {_age(p['last_poll_age'])}")
    hook = res.get("webhook")
    if hook is not None:
        print(f"Webhook: {hook['url'] or 'none'}" + (f" ({hook['last_error']})" if hook.get("last_error") else ""))
    for prob in res["problems"]:
        print(f"Problem: {prob}")
    return 0 if res["ok"] else 1


cli.register("telegram", "Telegram bridge (status, test, mode)", _configure, _handler)
