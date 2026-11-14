"""A sandboxed agent's run stopped at a site outside its domains: a notification with **Add this domain**.

    ref  browsersite:<agent path>|<host>      (feed.HANDLERS: the button comes back to feed_action here)

Only runs get there (the owner's conversation and sessions open any public site). The owner's click adds the host to
the agent's `domains` (its commands and WebFetch too: one list); the next run opens it. One notification per agent
and host a day.
"""
from __future__ import annotations

import logging
import time

from . import rules

log = logging.getLogger("maxxing.browser")
ADD = "add"


def blocked(owner: str, url: object, sites: list[str] | None) -> str | None:
    """The host when `url` is refused only because it is not one of the agent's domains (then: the notification),
    else None. Never raises (a notification is a nicety)."""
    if sites is None or not owner.startswith("agent:"):
        return None
    host = rules.off_domains(url, sites)
    if not host:
        return None
    path = owner.split(":", 1)[1]
    try:
        from .. import agents, feed
        name = agents.load(path).get("name") or path.rsplit("/", 1)[-1]
        feed.post(f"{name}: {host} is not one of its domains",
                  f"In its sandbox, its browser opens only {', '.join(sites) or 'no site yet'}. Add {host} to let its "
                  "next runs open it (its commands too).", "warning", "agents",
                  agents._page(path),
                  dedupe=f"browsersite:{path}|{host}:{time.strftime('%Y-%m-%d')}",
                  ref=f"browsersite:{path}|{host}", agent=path,
                  actions=[{"id": ADD, "label": "Add this domain", "style": "primary"}])
    except Exception:  # noqa: BLE001
        log.exception("feed event for a blocked site failed")
    return host


def add(path: str, host: str) -> list[str]:
    """Add `host` to the agent's domains (the owner's choice) -> its domains."""
    from .. import agents
    site = rules.clean_site(host)
    if not site:
        raise ValueError(f"{host!r} is not a site name")
    cur = list(agents.load(path).get("domains") or [])
    if site not in cur:
        agents.update(path, {"domains": cur + [site]})
    return list(agents.load(path).get("domains") or [])


def feed_action(value: str, action: str, by: str, ev: dict) -> None:
    """**Add this domain** of a notification (web, Telegram): the owner's click."""
    path, _, host = value.partition("|")
    if action != ADD or not path or not host:
        return
    from .. import feed
    try:
        add(path, host)
        feed.update(ev["id"], resolution=f"{host} added", resolve=True, read=True)
    except Exception as e:  # noqa: BLE001 - the agent was deleted, a bad name: said on the event
        feed.update(ev["id"], resolution=f"Not added: {getattr(e, 'message', e)}", resolve=True, read=True)
