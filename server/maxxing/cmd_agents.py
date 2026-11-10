"""`maxxing agents …` sub-commands (see maxxing/agents.py and the skill maxxing-agents).

  maxxing agents list [--json]               every agent: path, name, on/off, triggers, cost of the day
  maxxing agents run <agent> [text] [--data] start the agent now (text = its task; --data: the text is outside data)
  maxxing agents send <agent> <text>         from a turn: hand work to another agent (the text is framed as data;
                                             sender and depth come from the agent run of the turn)
  maxxing agents on <agent> | off <agent>    switch an agent on or off
  maxxing agents create <p>/<t>/<a> --role … create an agent (what a session runs when the user asks for one)
  maxxing agents show <agent>                its agent.json, role, triggers, cron jobs, webhook URLs (JSON)
  maxxing agents set <agent> FIELD=VALUE …   change its settings (in its own conversation, a safety setting waits for
                                             the owner's OK)
  maxxing agents cron <agent> --schedule …   add a schedule (a Claude cron job in the agent folder); --job ID changes
                                             or removes (--remove) one of its schedules
  maxxing agents webhook <agent> [--kind …]  add a webhook (a feed hook + a feed trigger on it); prints its URL
  maxxing agents watch <agent> --source …    add a feed trigger on existing events (a source, levels, words)
  maxxing agents export <agent> [-o FILE]    the agent as a Claude Code agent file (.claude/agents/<name>.md)
  maxxing agents import FILE --topic <p>/<t> create an agent from a Claude Code agent file
  maxxing agents sandbox-setup               install what the sandbox needs (root): bubblewrap, socat, AppArmor
  maxxing agents group list|show|create|update|say  agent groups (agent_rooms.py): a conversation of the owner with
                                             2-6 agents of one project (owner only: refused in agent turns)

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
    for name, hlp in (("on", "switch an agent on"), ("off", "switch an agent off"),
                      ("silent", "the agent works without notifying you (no Telegram, alerts read, nothing unread)"),
                      ("loud", "the agent notifies you again")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("agent")
    s = sub.add_parser("templates", help="the ready-made agents (gallery of New agent)")
    s.add_argument("--lang", default="", help="en, fr (default: the UI language)")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("create", help="create an agent in a topic")
    s.add_argument("where", help="<project>/<topic>/<agent> (agent = 1-48 lowercase letters, digits, dashes)")
    s.add_argument("--name", default="", help="display name (default: the folder name)")
    role = s.add_mutually_exclusive_group()
    role.add_argument("--role", help="its role: the first paragraph of its CLAUDE.md")
    role.add_argument("--role-file", help="a file holding the role (several paragraphs)")
    s.add_argument("--template", default="", help="start from a ready-made agent (`maxxing agents templates`): its "
                   "role, safety settings and first trigger; the other options override it")
    s.add_argument("--lang", default="", help="language of the template texts (en, fr; default: the UI language)")
    s.add_argument("--permission", choices=("bypass", "acceptEdits", "default"), help="default: the topic's mode")
    s.add_argument("--model", default="", help="default: the model of the topic")
    s.add_argument("--approvals", action="store_true", help="ask before risky actions (answered in the UI)")
    s.add_argument("--telegram", action="store_true", help="its own Telegram thread (results + messages start it)")
    s.add_argument("--keys", default="", help="Keys vault entries its turns see, comma-separated (default: none)")
    s.add_argument("--domains", default="", help="hosts its shell commands may reach in its sandbox, comma-separated "
                                                 "(e.g. api.github.com,*.example.com; default: none)")
    s.add_argument("--writable", default="", help="folders of the topic it may write in besides its own, comma-"
                                                  "separated (. = the whole topic)")
    s.add_argument("--mail", default="", metavar="MAILBOX", help="a mailbox of the E-mail page it may use (id or "
                   "address): read + drafts, or what a mail template says (`maxxing mail accounts`)")
    s.add_argument("--no-sandbox", action="store_true", help="no sandbox: its commands reach the whole server")
    s.add_argument("--trust-outside", action="store_true",
                   help="runs started by outside events (webhooks, feed, other agents) do not ask first: risky")
    s.add_argument("--usd-per-day", type=float, help="daily budget in $ (default 2, 0 = none)")
    s.add_argument("--runs-per-hour", type=int, help="default 6, 0 = no limit")
    s.add_argument("--off", action="store_true", help="create it switched off")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("show", help="an agent's settings, role, triggers, cron jobs and webhook URLs (JSON)")
    s.add_argument("agent")
    s = sub.add_parser("export", help="the agent as a Claude Code agent file (.claude/agents/<name>.md)")
    s.add_argument("agent")
    s.add_argument("-o", "--output", default="", help="write it to this file (default: print it)")
    s = sub.add_parser("import", help="create an agent from a Claude Code agent file (.claude/agents/<name>.md)")
    s.add_argument("file")
    s.add_argument("--topic", required=True, help="<project>/<topic> where it lives")
    s.add_argument("--name", default="", help="folder name (default: from the file)")
    sub.add_parser("sandbox-setup", help="install what the agents' sandbox needs (root): bubblewrap, socat, AppArmor")
    s = sub.add_parser("group", help="agent groups: the owner talks to 2-6 agents of one project")
    gs = s.add_subparsers(dest="group_cmd", required=True)
    g = gs.add_parser("list", help="list the groups")
    g.add_argument("--json", action="store_true")
    g = gs.add_parser("show", help="a group: members, goal, options and its last messages (JSON)")
    g.add_argument("group", help="<project>/<group>")
    g.add_argument("--messages", type=int, default=20)
    g = gs.add_parser("create", help="create a group in a project")
    g.add_argument("group", help="<project>/<group> (group = 1-48 lowercase letters, digits, dashes)")
    g.add_argument("--member", action="append", required=True,
                   help="an agent of the project: <agent> or <agent>=<its role in the group> (2 to 6 times)")
    g.add_argument("--name", default="", help="display name (default: the folder name)")
    g.add_argument("--emoji", default="")
    g.add_argument("--goal", default="", help="what the group is for (its CLAUDE.md)")
    g.add_argument("--lead", default="", help="the member who answers when the message names nobody")
    g.add_argument("--no-shared-files", action="store_true", help="no shared folder")
    g.add_argument("--ask-on-handover", action="store_true",
                   help="a hand-over between members asks before risky tools (members do not trust each other)")
    g.add_argument("--json", action="store_true")
    g = gs.add_parser("update", help="change a group: name, emoji, goal, members, lead, options")
    g.add_argument("group", help="<project>/<group>")
    g.add_argument("--member", action="append", help="replaces the members: <agent> or <agent>=<role> (2 to 6 times)")
    g.add_argument("--name")
    g.add_argument("--emoji")
    g.add_argument("--goal", help="what the group is for (its CLAUDE.md)")
    g.add_argument("--lead", help="a member, or \"\" for none")
    g.add_argument("--shared-files", choices=("on", "off"))
    g.add_argument("--trust-members", choices=("on", "off"), help="off: a hand-over asks before risky tools")
    g.add_argument("--json", action="store_true")
    g = gs.add_parser("say", help="write to the group as the owner (the members answer in turn)")
    g.add_argument("group", help="<project>/<group>")
    g.add_argument("text", nargs="+")
    s = sub.add_parser("set", help="change an agent's settings (its manager: a safety setting waits for the owner's OK)")
    s.add_argument("agent")
    s.add_argument("values", nargs="*", help='FIELD=VALUE (JSON values: approvals=true, domains=\'["example.com"]\', '
                                            'limits.usd_per_day=3, model=sonnet)')
    s.add_argument("--json", dest="fields", default="", help="the fields as one JSON object")
    s = sub.add_parser("cron", help="add a schedule to an agent, or change / remove one of its schedules (--job)")
    s.add_argument("agent")
    s.add_argument("--schedule", default="", help='5-field cron, server time zone, e.g. "0 8 * * 1"')
    s.add_argument("--prompt", default="", help='what to do each time (default "Run your routine.")')
    s.add_argument("--name", default="", help="name of the cron job")
    s.add_argument("--job", default="", help="change this cron job of the agent (its id: `maxxing agents show`)")
    s.add_argument("--remove", action="store_true", help="with --job: remove it")
    onoff = s.add_mutually_exclusive_group()
    onoff.add_argument("--on", dest="enabled", action="store_const", const=True, default=None)
    onoff.add_argument("--off", dest="enabled", action="store_const", const=False)
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("webhook", help="add a webhook to an agent and print its URL")
    s.add_argument("agent")
    s.add_argument("--kind", choices=("generic", "stripe", "shopify", "github"), default="generic")
    s.add_argument("--prompt", default="", help="what to do with each event (default: handle it per the role)")
    s.add_argument("--levels", default="", help="only these levels, comma-separated (info,success,warning,error)")
    s.add_argument("--match", default="", help="only events containing these words")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("watch", help="start an agent on feed events of a source")
    s.add_argument("agent")
    s.add_argument("--source", required=True, help="the feed source to watch (see the feed page or `maxxing feed list`)")
    s.add_argument("--levels", default="", help="only these levels, comma-separated")
    s.add_argument("--match", default="", help="only events containing these words")
    s.add_argument("--prompt", default="", help="what to do with the events")
    s.add_argument("--json", action="store_true")


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


def _turn() -> dict:
    """The agent run this command comes from ({path, depth}; path "" for the owner): see agent_guard.agent_turn."""
    from . import agent_guard
    return agent_guard.agent_turn()


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
    from . import agent_guard
    if agent_guard.sandboxed_turn():                # a sandboxed agent sees who it can hand work to, nothing more
        rows = [{"path": x["path"], "display_name": x["display_name"]} for x in rows]
        if a.json:
            print(json.dumps(rows, indent=2))
        else:
            for x in rows:
                print(f"{x['path']}  {x['display_name']}")
        return 0
    if a.json:
        print(json.dumps([{k: x.get(k) for k in ("path", "display_name", "enabled", "silent", "telegram", "approvals",
                                                  "limits", "triggers", "cost_today", "runs_last_hour")}
                          for x in rows], indent=2))
        return 0
    if not agents.feature_on():
        print("(Agents are off in Settings -> Features: the page is hidden; schedules, Telegram and agents/run/send "
              "still start them, feed and webhook events do not - those that come meanwhile are skipped.)", file=sys.stderr)
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


def _levels(v: str) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _lang(a) -> str:
    from . import config
    return (a.lang or config.load_config().get("language") or "en").strip()


def _templates(a) -> int:
    from . import agent_templates
    rows = agent_templates.listing(_lang(a))
    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    for t in rows:
        when = f"cron {t['cron']['schedule']}" if t.get("cron") else f"webhook {t['webhook']['kind']}" if t.get("webhook") else ""
        print(f"{t['id']:<10} {t['name']:<24} {when:<20} {t['summary']}")
    return 0


def _create(a) -> int:
    import random
    from . import agents
    where = a.where.strip("/")
    parts = list(agents.parse(where) or ()) if where.startswith("projects/") else where.split("/")
    if len(parts) != 3:
        print("Give <project>/<topic>/<agent>, e.g. acme/blog/editor", file=sys.stderr)
        return 2
    project, topic, name = parts
    if a.role_file:
        try:
            role = open(a.role_file, encoding="utf-8").read().strip()
        except (OSError, ValueError) as e:                  # ValueError: not UTF-8 text
            print(f"Cannot read {a.role_file}: {e}", file=sys.stderr)
            return 2
    else:
        role = (a.role or "").strip()
    tpl = None
    if a.template:
        from . import agent_templates, vault
        tpl = agent_templates.get(a.template, _lang(a))
        if tpl is None:
            print(f"No template {a.template!r}: see `maxxing agents templates`", file=sys.stderr)
            return 2
    elif not role:
        print("Give its role: --role TEXT, --role-file FILE or --template ID", file=sys.stderr)
        return 2
    limits = {k: v for k, v in (("usd_per_day", a.usd_per_day), ("runs_per_hour", a.runs_per_hour)) if v is not None}
    keys = [k.strip() for k in a.keys.split(",") if k.strip()]
    fields = {"avatar": {**{k: random.choice(list(v)) for k, v in agents.AVATAR.items()},
                         "color": agents.project_color(project)}, "permission_mode": "",
              **(agent_templates.fields(tpl, [x["name"] for x in vault.list_secrets()]) if tpl else {})}
    if a.mail:
        from . import mail
        from .mail.imap import MailError
        try:
            acc_id = mail.get_account(a.mail)["id"]
        except MailError as e:
            print(e.message, file=sys.stderr)
            return 2
        tm = (tpl or {}).get("mail") or {}
        fields["mail"] = [{"account": acc_id, "rights": tm.get("rights") or ["read", "draft"],
                           "approve_send": tm.get("approve_send") or "always", "senders": tm.get("senders") or [],
                           "trigger": tm.get("trigger") or {"enabled": True, "folder": "INBOX", "prompt": ""}}]
        if not tpl:
            fields.setdefault("allowed_tools", [])
    elif tpl and tpl.get("mail"):
        print("This template is made for a mailbox: add --mail MAILBOX (`maxxing mail accounts`)", file=sys.stderr)
        return 2
    fields.update({"name": a.name or fields.get("name") or name, "model": a.model, "telegram": a.telegram,
                   "enabled": not a.off, "trust_outside": a.trust_outside,
                   "approvals": a.approvals or bool(fields.get("approvals")),
                   "limits": {**(fields.get("limits") or {}), **limits}})
    if role:
        fields["description"] = role
    if a.permission:
        fields["permission_mode"] = a.permission
    if keys:
        fields["keys"] = keys
    for k in ("domains", "writable"):
        v = [x.strip() for x in getattr(a, k).split(",") if x.strip()]
        if v:
            fields[k] = v
    if a.no_sandbox:
        fields["sandbox"] = False
    try:
        r = agents.create(f"projects/{project}/topics/{topic}", name, fields)
    except agents.AgentError as e:
        print(e.message, file=sys.stderr)
        return 2
    extra: dict = {}
    if tpl and tpl.get("cron"):
        try:
            extra["cron"] = agents.add_cron(r["path"], tpl["cron"]["schedule"], tpl["cron"]["prompt"], "")["id"]
        except Exception as e:  # noqa: BLE001 - the agent exists: say what is missing
            print(f"schedule not added: {e}", file=sys.stderr)
    if tpl and tpl.get("webhook"):
        try:
            hook = agents.add_webhook(r["path"], tpl["webhook"]["kind"], tpl["webhook"]["prompt"], [], "")["hook"]
            extra["webhook"] = hook.get("url")
        except Exception as e:  # noqa: BLE001
            print(f"webhook not added: {e}", file=sys.stderr)
    if a.json:
        print(json.dumps({"agent": r["path"], **extra}))
    else:
        print(f"created {r['path']}")
        if r.get("keys"):
            print(f"keys: {', '.join(r['keys'])}")
        if extra.get("cron"):
            print(f"schedule: {tpl['cron']['schedule']}")
        if extra.get("webhook"):
            print(f"webhook URL: {extra['webhook']}")
        if tpl and tpl.get("needs"):
            print(f"to connect: {tpl['needs']}")
        if not agents.feature_on():
            print("(The Agents page is off: Settings -> Features -> Agents shows it. Schedules and Telegram run anyway, "
                  "feed and webhook triggers only once it is on.)",
                  file=sys.stderr)
    return 0


def _sandbox_setup() -> int:
    from . import agent_guard
    if os.geteuid() != 0:
        print("Run it as root.", file=sys.stderr)
        return 2
    try:
        done = agent_guard.setup()
    except Exception as e:  # noqa: BLE001 - apt or apparmor_parser failed: say it
        print(f"sandbox setup failed: {e}", file=sys.stderr)
        return 1
    st = agent_guard.available(fresh=True)
    print("\n".join(done) or "nothing to do")
    print("sandbox: ready" if st["ok"] else f"sandbox: still missing {', '.join(st['missing'])}")
    return 0 if st["ok"] else 1


def _import(a) -> int:
    from . import agent_format, agents
    t = a.topic.strip("/")
    topic = t if t.startswith("projects/") else ("projects/{}/topics/{}".format(*t.split("/")) if t.count("/") == 1 else "")
    if not topic:
        print("Give --topic <project>/<topic>", file=sys.stderr)
        return 2
    try:
        text = open(a.file, encoding="utf-8").read()
        r = agent_format.import_md(topic, text, a.name or None)
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    except agents.AgentError as e:
        print(e.message, file=sys.stderr)
        return 2
    print(f"created {r['path']}")
    if r["ignored"]:
        print("not imported (no equivalent in Harness): " + ", ".join(r["ignored"]), file=sys.stderr)
    return 0


def _group_path(ref: str) -> str:
    from . import agent_rooms
    r = (ref or "").strip().strip("/")
    path = r if agent_rooms.parse(r) else (agent_rooms.group_path(*r.split("/")) if r.count("/") == 1 else "")
    if not path or not agent_rooms.exists(path):
        raise ValueError(f"Group not found: {ref!r} (see `maxxing agents group list`)")
    return path


def _group(a) -> int:
    from . import agent_rooms, agents
    try:
        if a.group_cmd == "list":
            rows = agent_rooms.list_groups()
            if a.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
            elif not rows:
                print("No group yet.")
            for x in [] if a.json else rows:
                print(f"{x['path']}  {x['emoji']} {x['display_name']}  "
                      + " ".join("@" + m["slug"] + (" (paused)" if m["paused"] else "") for m in x["members"])
                      + ("  speaking" if x["busy"] else ""))
            return 0
        if a.group_cmd == "create":
            if a.group.count("/") != 1:
                print("Give <project>/<group>", file=sys.stderr)
                return 2
            project, name = a.group.split("/")
            members = []
            for m in a.member:
                ref, _, role = m.partition("=")
                members.append({"path": resolve(ref), "role": role.strip()})
            lead = resolve(a.lead) if a.lead else ""
            g = agent_rooms.create(project, name, {"name": a.name, "emoji": a.emoji, "goal": a.goal, "lead": lead,
                                                    "members": members, "shared_files": not a.no_shared_files,
                                                    "trust_members": not a.ask_on_handover})
            print(json.dumps({"group": g["path"]}) if a.json else f"group created: {g['path']}")
            return 0
        path = _group_path(a.group)
        if a.group_cmd == "show":
            print(json.dumps({**agent_rooms.get(path), "messages": agent_rooms.room(path, max(1, a.messages))},
                             indent=2, ensure_ascii=False))
            return 0
        if a.group_cmd == "update":
            f: dict = {}
            for k in ("name", "emoji", "goal"):
                if getattr(a, k) is not None:
                    f[k] = getattr(a, k)
            if a.member:
                f["members"] = [{"path": resolve(m.partition("=")[0]), "role": m.partition("=")[2].strip()}
                                for m in a.member]
            if a.lead is not None:
                f["lead"] = resolve(a.lead) if a.lead else ""
            if a.shared_files:
                f["shared_files"] = a.shared_files == "on"
            if a.trust_members:
                f["trust_members"] = a.trust_members == "on"
            g = agent_rooms.update(path, f)
            print(json.dumps({"group": g["path"]}) if a.json else f"group updated: {g['path']} - members "
                  + " ".join("@" + m["handle"] for m in g["members"]))
            return 0
        if a.group_cmd == "say":
            r = agent_rooms.say(path, " ".join(a.text))
            hs = agent_rooms.handles(agent_rooms.load(path))
            print("sent; " + ("next: " + ", ".join("@" + hs.get(p, agent_rooms.slug(p)) for p in r["queued"])
                              if r["queued"] else "nobody answers (all named members are paused)"))
            return 0
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except agents.AgentError as e:
        print(e.message, file=sys.stderr)
        return 2
    return 2


def _values(a) -> dict:
    """`set` FIELD=VALUE words (+ --json) -> agent.json fields; a.b=VALUE goes in the object a (limits.usd_per_day)."""
    out: dict = {}
    if a.fields:
        d = json.loads(a.fields)
        if not isinstance(d, dict):
            raise ValueError("--json: a JSON object")
        out.update(d)
    for w in a.values:
        k, sep, v = w.partition("=")
        if not sep or not k.strip():
            raise ValueError(f"{w!r}: FIELD=VALUE")
        try:
            val = json.loads(v)
        except ValueError:
            val = v
        k = k.strip()
        if "." in k:
            top, sub = k.split(".", 1)
            out.setdefault(top, {})
            if not isinstance(out[top], dict):
                raise ValueError(f"{top}: an object")
            out[top][sub] = val
        else:
            out[k] = val
    if not out:
        raise ValueError("Nothing to change: FIELD=VALUE ... or --json '{...}'")
    return out


def _set(path: str, a) -> int:
    from . import agents
    try:
        fields = _values(a)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    turn = _turn()
    if turn.get("manager") and turn["path"] == path:
        r = agents.request_change(path, fields, session=turn["session"])
    else:                                              # the owner (shell, session): everything at once
        agents.update(path, fields)
        r = {"applied": sorted(fields), "asked": [], "request": ""}
    if r["applied"]:
        print("changed: " + ", ".join(r["applied"]))
    if r["asked"]:
        print("waiting for the owner's OK (safety settings, applied once allowed): " + ", ".join(r["asked"]))
    return 0


def _cron_job(path: str, a) -> int:
    from . import bus, crons
    job = crons.get_job(a.job)
    if not job or job.get("topic_path") != path:
        print(f"{a.job}: not a cron job of this agent (see `maxxing agents show`)", file=sys.stderr)
        return 2
    if a.remove:
        crons.delete_job(a.job)
        bus.invalidate("crons", "agents")
        print(f"schedule removed: {a.job}")
        return 0
    fields = {k: v for k, v in (("schedule", a.schedule), ("prompt", a.prompt), ("name", a.name)) if v}
    if a.enabled is not None:
        fields["enabled"] = a.enabled
    if not fields:
        print("Nothing to change: --schedule, --prompt, --name, --on / --off or --remove", file=sys.stderr)
        return 2
    try:
        crons.update_job(a.job, fields)
    except crons.CronError as e:
        print(str(e), file=sys.stderr)
        return 2
    bus.invalidate("crons", "agents")
    print(f"schedule changed: {a.job} ({', '.join(sorted(fields))})")
    return 0


def _handler(a) -> int:
    from . import agents
    if a.agents_cmd == "list":
        return _list(a)
    if a.agents_cmd == "create":
        return _create(a)
    if a.agents_cmd == "templates":
        return _templates(a)
    if a.agents_cmd == "sandbox-setup":
        return _sandbox_setup()
    if a.agents_cmd == "import":
        return _import(a)
    if a.agents_cmd == "group":
        return _group(a)
    try:
        path = resolve(a.agent)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    if a.agents_cmd in ("on", "off"):
        agents.update(path, {"enabled": a.agents_cmd == "on"})
        print(f"{path}: {a.agents_cmd}")
        return 0
    if a.agents_cmd in ("silent", "loud"):
        agents.update(path, {"silent": a.agents_cmd == "silent"})
        print(f"{path}: {a.agents_cmd}")
        return 0
    if a.agents_cmd == "export":
        from . import agent_format
        md = agent_format.export_md(path)
        if a.output:
            try:
                with open(a.output, "w", encoding="utf-8") as f:
                    f.write(md)
            except OSError as e:
                print(f"Cannot write {a.output}: {e}", file=sys.stderr)
                return 2
            print(f"written {a.output}")
        else:
            sys.stdout.write(md)
        return 0
    if a.agents_cmd == "show":
        from . import agent_guard
        own = agent_guard.sandboxed_turn()
        if own and own != path:
            print("Refused: in a sandboxed agent turn, `maxxing agents show` shows this agent only "
                  "(`maxxing agents list` gives the others' paths and names).", file=sys.stderr)
            return 2
        d = agents.get(path)
        try:
            role = (agents.folder(path) / "CLAUDE.md").read_text(encoding="utf-8")
        except OSError:
            role = ""
        print(json.dumps({**{k: d.get(k) for k in ("path", "display_name", "enabled", "model", "permission_mode",
                                                    "approvals", "trust_outside", "keys", "telegram", "silent", "sandbox", "domains",
                                                    "writable", "rules", "subagent", "chat_model", "limits", "triggers")},
                          "claude_md": role, "crons": [{k: j.get(k) for k in ("id", "name", "schedule", "prompt", "enabled")}
                                                       for j in agents.cron_jobs(path)],
                          "webhooks": [{k: v for k, v in h.items() if not own or k != "url"}
                                       for h in agents.hooks(path)]}, indent=2, ensure_ascii=False))
        return 0
    try:
        if a.agents_cmd == "set":
            return _set(path, a)
        if a.agents_cmd == "cron" and a.job:
            return _cron_job(path, a)
        if a.agents_cmd == "cron":
            if not a.schedule:
                print("--schedule is needed to add a schedule (or --job ID to change one)", file=sys.stderr)
                return 2
            job = agents.add_cron(path, a.schedule, a.prompt, a.name, enabled=a.enabled is not False)
            print(json.dumps({"cron": job.get("id")}) if a.json else f"schedule added: {job.get('id')} ({a.schedule})")
            return 0
        if a.agents_cmd == "webhook":
            hook = agents.add_webhook(path, a.kind, a.prompt, _levels(a.levels), a.match)["hook"]
            if a.json:
                print(json.dumps({k: hook.get(k) for k in ("id", "name", "kind", "url")}))
            else:
                print(f"webhook added: source {hook['name']}\nURL: {hook.get('url')}")
                if a.kind != "generic":
                    print(f"Set its signing secret in the agent page -> Triggers (a {a.kind} webhook refuses "
                          "deliveries until then).", file=sys.stderr)
            return 0
        if a.agents_cmd == "watch":
            agents.add_trigger(path, {"kind": "feed", "source": a.source.strip(), "levels": _levels(a.levels),
                                      "match": a.match, "prompt": a.prompt})
            print(json.dumps({"agent": path}) if a.json else f"{path} now watches the feed source {a.source.strip()}")
            return 0
    except agents.AgentError as e:
        print(e.message, file=sys.stderr)
        return 2
    text = " ".join(a.text).strip()
    turn = _turn()
    sender = turn["path"]
    if a.agents_cmd == "run" and not sender:
        r = agents.fire(path, trigger="manual", source="command line",
                        **({"text": text} if a.data else {"prompt": text}))
        return _print_fire(path, r, a.json)
    # send (or run from an agent's turn): from one agent's turn to another agent - the text is the sender's output,
    # framed as data, one hop more
    if sender == path:
        print("An agent cannot send work to itself.", file=sys.stderr)
        return 2
    if not text and a.agents_cmd == "send":
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
    r = agents.fire(path, trigger=trigger, text=text, source=source, depth=turn["depth"] + 1)
    return _print_fire(path, r, a.json)


cli.register("agents", "agents: create, add triggers, list, run, send work from one agent to another, switch on / off",
             _configure, _handler)
