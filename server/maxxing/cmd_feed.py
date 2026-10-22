"""`maxxing feed` - post to / read the notifications feed (any script can use it; see docs/user/24-feed.md)."""
from __future__ import annotations

import json
import sys
import time

from . import cli


def _configure(p) -> None:
    from . import feed
    sub = p.add_subparsers(dest="feed_cmd", required=True)
    s = sub.add_parser("post", help="add an event to the feed (dashboard, and Telegram per its rules)")
    s.add_argument("title")
    s.add_argument("--body", default="", help="details (a few lines)")
    s.add_argument("--level", default="info", choices=feed.LEVELS)
    s.add_argument("--source", default="custom", help="short name shown in the feed, e.g. mail, stock")
    s.add_argument("--url", default="", help="link opened from the event (https://... or /files?path=...)")
    s.add_argument("--dedupe", help="unique key: a second post with the same key (and source) is ignored")
    s.add_argument("--group", help="fold repeats into one unread row (e.g. --group daily-ok)")
    s.add_argument("--quiet", action="store_true", help="never post this one to Telegram")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("list", help="latest events")
    s.add_argument("--unread", action="store_true")
    s.add_argument("--source")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    sub.add_parser("read-all", help="mark every event as read")


def _run(a) -> int:
    from . import feed
    from .feed import FeedError
    try:
        if a.feed_cmd == "post":
            ev = feed.post(a.title, a.body, a.level, a.source, a.url, dedupe=a.dedupe, group=a.group,
                           notify=not a.quiet)
            if a.json:
                print(json.dumps({"event": ev, "duplicate": ev is None}))
            else:
                print("duplicate - already posted" if ev is None else f"posted #{ev['id']} ({ev['source']})")
            return 0
        if a.feed_cmd == "list":
            r = feed.list_events(a.source, a.unread, None, a.limit)
            if a.json:
                print(json.dumps(r, indent=2, ensure_ascii=False))
                return 0
            for ev in r["events"]:
                when = time.strftime("%m-%d %H:%M", time.localtime(ev["at"]))
                mark = " " if ev["read"] else "*"
                count = f" x{ev['count']}" if ev["count"] > 1 else ""
                print(f"{mark} {when}  {ev['level']:<7} {ev['source']:<12} {ev['title']}{count}")
            print(f"{r['unread']} unread")
            return 0
        print(f"{feed.mark_read(everything=True)} unread")
        return 0
    except FeedError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return 2


cli.register("feed", "Notifications feed: post an event, list, mark read", _configure, _run)
