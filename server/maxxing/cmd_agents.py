"""`maxxing agents …` sub-commands (see maxxing/agents.py and the skill maxxing-agents).

  maxxing agents list [--json]               every agent: path, name, on/off, triggers, cost of the day
  maxxing agents run <agent> [text] [--data] start the agent now (text = its task; --data: the text is outside data)
  maxxing agents send <agent> <text>         from a turn: hand work to another agent (the text is framed as data;
                                             sender and depth come from MAXXING_AGENT / MAXXING_AGENT_DEPTH)
  maxxing agents on <agent> | off <agent>    switch an agent on or off

<agent> = projects/<p>/topics/<t>/agents/<a>, <p>/<t>/<a>, or just <a> when only one agent has that name.
Works without the server: fire() only writes files and starts the turn's unit; the server's session watcher
posts the result into the agent's thread when the turn ends.
"""
from __future__ import annotations

import json
import os
import sys

from . import cli


def _configure(p) -> None:
    sub = p.add_subparsers(dest="agents_cmd", required=True)
    s = sub.add_parser("list", help="list the agents")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("run", help="start an agent now (a new session)")
    s.add_argument("agent")
    s.add_argument("text", nargs="*", help="its task (optional: else its routine)")
    s.add_argument("--data", action="store_true", help="the text is outside data (an e-mail, a script output), "
                                                       "framed so that Claude never follows instructions in it")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("send", help="hand work to another agent (from inside a turn)")
    s.add_argument("agent")
    s.add_argument("text", nargs="+")
    s.add_argument("--json", action="store_true")
    for name, hlp in (("on", "switch an agent on"), ("off", "switch an agent off")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("agent")


def resolve(ref: str) -> str:
    """Agent path of `ref` (full path, p/t/a or a unique a). ValueError when unknown or ambiguous."""
    from . import agents
    r = (ref or "").strip().strip("/")
    if agents.is_agent_path(r):
        path = r
    elif r.count("/") == 2:
        path = agents.agent_path(*r.split("/"))
    elif r and "/" not in r:
        found = [a["path"] for a in agents.list_agents() if a["name"] == r]
        if len(found) > 1:
            raise ValueError(f"Several agents are named {r!r}: " + ", ".join(found) + " - give <project>/<topic>/<agent>")
        path = found[0] if found else ""
    else:
        path = ""
    if not path or not agents.exists(path):
        raise ValueError(f"Agent not found: {ref!r} (see `maxxing agents list`)")
    return path


def _depth() -> int:
    try:
        return max(0, int(os.environ.get("MAXXING_AGENT_DEPTH") or 0))
    except ValueError:
        return 0


def _print_fire(path: str, r: dict, as_json: bool) -> int:
    from . import agents
    if as_json:
        out = {"started": r.get("started", False), "agent": path}
        if r.get("session"):
            out["session"] = r["session"].get("id")
        if r.get("reason"):
            out["reason"] = r["reason"]
        print(json.dumps(out))
    elif r.get("started"):
        print(f"started {path}: session {r['session']['id']}")
    else:
        reason = r.get("reason") or ""
        print(f"not started: {agents.SKIP_TEXT.get(reason, reason)}", file=sys.stderr)
    return 0 if r.get("started") else 1


def _list(a) -> int:
    from . import agents
    rows = agents.list_agents(with_status=True)
    if a.json:
        print(json.dumps([{k: x.get(k) for k in ("path", "display_name", "enabled", "telegram", "approvals",
                                                  "limits", "triggers", "cost_today", "runs_last_hour")}
                          for x in rows], indent=2))
        return 0
    if not agents.feature_on():
        print("(Agents are off in Settings -> Features: their triggers still run, the page is hidden.)", file=sys.stderr)
    if not rows:
        print("No agent yet.")
        return 0
    for x in rows:
        crons = len(agents.cron_jobs(x["path"]))
        feeds = sum(1 for t in x["triggers"] if t["kind"] == "feed")
        budget = x["limits"]["usd_per_day"]
        cost = f"${x['cost_today']:.2f}" + (f"/{budget:g}" if budget else "")
        print(f"{'on ' if x['enabled'] else 'off'}  {x['path']}  {x['display_name']}  "
              f"cron:{crons} feed:{feeds}{' telegram' if x['telegram'] else ''}  today {cost}")
    return 0


def _handler(a) -> int:
    from . import agents
    if a.agents_cmd == "list":
        return _list(a)
    try:
        path = resolve(a.agent)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    if a.agents_cmd in ("on", "off"):
        agents.update(path, {"enabled": a.agents_cmd == "on"})
        print(f"{path}: {a.agents_cmd}")
        return 0
    text = " ".join(a.text).strip()
    if a.agents_cmd == "run":
        r = agents.fire(path, trigger="manual", source="command line",
                        **({"text": text} if a.data else {"prompt": text}))
        return _print_fire(path, r, a.json)
    # send: from one agent's turn to another agent - the text is the sender's output, framed as data
    sender = (os.environ.get("MAXXING_AGENT") or "").strip()
    if sender == path:
        print("An agent cannot send work to itself.", file=sys.stderr)
        return 2
    if not text:
        print("Nothing to send.", file=sys.stderr)
        return 2
    if agents.is_agent_path(sender):
        try:
            label = agents.load(sender)["name"] or agents.parse(sender)[2]
        except Exception:  # noqa: BLE001
            label = agents.parse(sender)[2]
        trigger, source = f"agent:{sender}", f"agent {label}"
    else:
        trigger, source = "agent:session", "session"
    r = agents.fire(path, trigger=trigger, text=text, source=source, depth=_depth() + 1)
    return _print_fire(path, r, a.json)


cli.register("agents", "agents: list, run, send work from one agent to another, switch on / off",
             _configure, _handler)
