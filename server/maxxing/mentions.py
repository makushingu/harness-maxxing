"""@ mentions of the composer: who a session's message can name - the other sessions, the agents, the Team contacts
and groups - and what Claude reads with the message (the command that writes to each of them).

Nothing is sent here: the message goes to the session as usual and Claude sends, if the message asks it to, with
`maxxing sessions send`, `maxxing agents send` or `maxxing team send` (one hop more each time, see
`sessions.service.MAX_HOPS`). The client sends {kind, ref} only; the label and the command come from here, so a
message can never make Claude run a command of the page's choosing.
"""
from __future__ import annotations

import re

from . import config

KINDS = ("session", "agent", "team")
MAX = 8                                   # mentions read per message
SESSIONS = 60                             # most recent sessions offered


def _topic(path: str) -> str:
    m = re.match(r"^projects/([^/]+)/topics/([^/]+)", path or "")
    return f"{m.group(1)} / {m.group(2)}" if m else (path or "")


def candidates(exclude: str = "") -> list[dict]:
    """[{kind, ref, label, hint, state?, group?}]: sessions (running first, then the most recent; not archived, not
    an agent's), agents (Agents page on), Team contacts and groups (Team page on)."""
    from . import agents
    from .sessions import service
    rows: list[dict] = []
    sess = [s for s in service.list_sessions(archived=False)
            if s["id"] != exclude and not agents.is_agent_path(s["path"])]
    sess.sort(key=lambda s: (s["state"] != "running", -(s.get("updated") or 0)))
    rows += [{"kind": "session", "ref": s["id"], "label": s["title"], "hint": _topic(s["path"]), "state": s["state"]}
             for s in sess[:SESSIONS]]
    if agents.feature_on():
        for a in agents.list_agents(counts=False):
            if not a.get("broken"):
                rows.append({"kind": "agent", "ref": a["path"], "label": a["display_name"], "hint": _topic(a["path"]),
                             "avatar": a.get("avatar") or None})
    if config.load_config().get("team_page"):
        from . import team
        for r in team.recipients():
            rows.append({"kind": "team", "ref": r["id"], "label": r["name"], "group": r["kind"] == "group",
                         "hint": ", ".join(r.get("members") or []) if r["kind"] == "group" else ""})
    return rows


def resolve(items: list[dict] | None, sender: str = "") -> list[dict]:
    """The mentions of a message ({kind, ref} from the page) -> [{kind, ref, label, where?, command}], unknown or
    repeated ones dropped. `command` is what Claude runs, followed by the text."""
    from . import agents
    from .sessions import service
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    team_rows = None
    for it in (items or [])[:MAX * 2]:
        kind, ref = str((it or {}).get("kind") or ""), str((it or {}).get("ref") or "").strip()
        if kind not in KINDS or not ref or (kind, ref) in seen or len(out) >= MAX:
            continue
        seen.add((kind, ref))
        if kind == "session":
            s = service.get_session(ref) if ref != sender else None
            if s:
                out.append({"kind": kind, "ref": ref, "label": s["title"], "where": _topic(s["path"]),
                            "command": f"maxxing sessions send {ref[:8]}"})
        elif kind == "agent":
            if agents.is_agent_path(ref) and agents.exists(ref):
                a = agents.load(ref)
                out.append({"kind": kind, "ref": ref, "label": a["name"] or agents.parse(ref)[2],
                            "where": _topic(ref), "command": f"maxxing agents send {ref}"})
        else:
            if team_rows is None:
                from . import team
                team_rows = team.recipients() if config.load_config().get("team_page") else []
            r = next((x for x in team_rows if ref in (x["id"], x.get("chat"))), None)
            if r:
                out.append({"kind": kind, "ref": r["id"], "label": r["name"], "group": r["kind"] == "group",
                            "command": f"maxxing team send {r['id']}"})
    return out
