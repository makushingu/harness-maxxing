"""`maxxing telegram status|test` - inspect and test the Telegram bridge from a shell."""
from __future__ import annotations

import json

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="tg_cmd", required=True)
    s = sub.add_parser("status", help="show the Telegram configuration")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    sub.add_parser("test", help="send a test message to the linked chat")


def _handler(a) -> int:
    from .telegram import gateway
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
        print(f"threads    : {len(st['threads'])} (topics {'on' if st['topics_enabled'] else 'off'})")
        for th in st["threads"]:
            kind = f"session {th['session_id'][:8]}" if th.get("session_id") else th["path"]
            print(f"  - {th['name'] or '?'}  [{kind}]")
        s = st["settings"]
        print(f"settings   : crons={s['notify_crons']} alerts={s['login_alerts']} replies={s['reply_mode']} "
              f"thread_days={s.get('thread_days')}")
        if st["last_error"]:
            print(f"last error : {st['last_error']}")
        return 0
    if not st["configured"] or not st["chat"]:
        print("Telegram is not linked - configure it in Settings > Telegram.")
        return 1
    ok = gateway.send_test()
    print("Test message sent." if ok else "Telegram did not accept the message.")
    return 0 if ok else 1


cli.register("telegram", "Telegram bridge (status, test)", _configure, _handler)
