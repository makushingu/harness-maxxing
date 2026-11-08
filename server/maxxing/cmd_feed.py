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


def _self_trigger(agent: str, source: str) -> str:
    """From an agent's turn: refuse a source its own feed triggers watch (it would start itself again), a webhook's
    source (only its signed deliveries post there: an agent could pass for them) and a built-in or product source."""
    if not agent:
        return ""
    from . import feed
    if source in feed.BUILTIN or source in feed.PRODUCT_SOURCES or any(h.get("name") == source for h in feed.settings()["hooks"]):
        return (f"Refused: {source!r} is a webhook or built-in source, only its own deliveries post there. "
                "Use another --source.")
    try:
        from . import agents
        if any(t.get("hook_id") and t.get("source") == source             # a deleted webhook's trigger still waits
               for x in agents.list_agents(counts=False) for t in x["triggers"]):
            return (f"Refused: {source!r} is a webhook or built-in source, only its own deliveries post there. "
                    "Use another --source.")
        if not agents.exists(agent):
            return ""
        if any(t["kind"] == "feed" and t.get("source") == source for t in agents.load(agent)["triggers"]):
            return (f"Refused: this agent watches the feed source {source!r}, posting there would start it again. "
                    "Use another --source.")
    except Exception:  # noqa: BLE001
        return ""
    return ""


def _list(feed, a) -> dict:
    """The events of `feed list`. In a sandboxed agent turn: only the sources its feed triggers watch (the feed holds
    every project's events: mail, sales, the other agents' alerts and requests)."""
    from . import agent_guard, agents
    path = agent_guard.sandboxed_turn()
    if not path:
        return feed.list_events(a.source, a.unread, None, a.limit)
    watched = sorted({t["source"] for t in agents.load(path)["triggers"] if t["kind"] == "feed" and t.get("source")})
    events: list[dict] = []
    for src in watched if not a.source else [s for s in watched if s == a.source]:
        events += feed.list_events(src, a.unread, None, a.limit)["events"]
    events = sorted(events, key=lambda e: e["id"], reverse=True)[:max(1, min(int(a.limit or 20), 200))]
    sources = [s for s in feed.source_counts() if s["source"] in watched]
    return {"events": events, "unread": sum(s["unread"] for s in sources), "sources": sources}


def _run(a) -> int:
    from . import feed
    from .feed import FeedError
    try:
        if a.feed_cmd == "post":
            from . import agent_guard, agents
            turn = agent_guard.agent_turn()         # from the turn's own session, not its (changeable) environment
            loop = _self_trigger(turn["path"], feed.clean_source(a.source))
            if loop:
                print(loop, file=sys.stderr)
                return 2
            ev = feed.post(a.title, a.body, a.level, a.source, a.url, dedupe=a.dedupe, group=a.group,
                           notify=not a.quiet and not (turn["path"] and agents.silent(turn["path"])), hops=turn["depth"] + 1 if turn["path"] else 0)
            if a.json:
                print(json.dumps({"event": ev, "duplicate": ev is None}))
            else:
                print("duplicate - already posted" if ev is None else f"posted #{ev['id']} ({ev['source']})")
            return 0
        if a.feed_cmd == "list":
            r = _list(feed, a)
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
