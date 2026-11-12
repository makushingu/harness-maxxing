"""`maxxing enterprise …` sub-commands (see maxxing/enterprises.py and the skill maxxing-enterprises).

Structure (the owner's: refused in every agent turn):
  maxxing enterprise list [--json]                         the enterprises: id, name, positions, vacant, projects
  maxxing enterprise create SLUG [--name N] [--emoji E] [--project P ...] [--json]
  maxxing enterprise link SLUG PROJECT ... | unlink SLUG PROJECT ... [--vacate]   projects of the enterprise
  maxxing enterprise position add SLUG ID [--title T] [--reports-to P] [--agent A] [--department D] [--job T | --job-file F]
  maxxing enterprise position move SLUG ID --reports-to P | seat SLUG ID --agent A | vacate SLUG ID
  maxxing enterprise position remove SLUG ID [--reparent-to P]
  maxxing enterprise settings SLUG KEY=VALUE ... [--department D]    a setting (dotted: digest.enabled=true), a department's
                                                           override / `name` / `notes`, or name, emoji, top, envelope.*
  maxxing enterprise grant SLUG POSITION --category C --ceiling N --until DATE | --revoke ID   delegated approval (30 days at most)
  maxxing enterprise report SLUG [--daily|--weekly|--monthly] [--now] [--json]   print the last report; --now builds one
  maxxing enterprise decisions SLUG [--since DATE] [--limit N] [--json]   the decision log
  maxxing enterprise export SLUG [-o FILE]  |  import FILE [--json]       the enterprise as a zip / from a zip
Readable by an agent of the enterprise (a sandboxed turn sees its own position, its lead and its reports only):
  maxxing enterprise show [SLUG] [--json]                  the chart as a tree, with every position's state
  maxxing enterprise profile [--section S] [--json]        the company profile (S: products, hours, terms, contact, faq)
From an agent turn, as the position of the caller (the owner passes --as POSITION, --enterprise SLUG when several):
  maxxing enterprise assign POSITION TEXT [--due D] [--parent T] [--task T]   a task for a direct report
  maxxing enterprise done TASK TEXT | block TASK TEXT      hand in / report a blocker on a task of the caller
  maxxing enterprise escalate TEXT [--task T]              ask one level up
  maxxing enterprise answer ID TEXT                        answer an escalation
  maxxing enterprise request CATEGORY TEXT [--amount N]    an organizational request, routed by category
  maxxing enterprise decide ID allow|deny [REASON]         decide a request
  maxxing enterprise objective set ID VALUE                the value of an objective (its owner position only)
  maxxing enterprise route DEPARTMENT TEXT                 the front desk passes a request on (a task marked outside)
  maxxing enterprise worker start TEXT [--for TASK] | list | stop ID   temporary workers (stop: the owner)

Works without the server: the commands call the enterprise modules and write the files directly.
Exit codes: 0 done, 1 valid but nothing done, 2 error or refusal (message on stderr).
"""
from __future__ import annotations

import importlib
import json
import sys
import time

from . import cli

TURN_CMDS = ("assign", "done", "block", "escalate", "answer", "request", "decide", "objective", "profile", "route",
             "worker")
STRUCTURE_CMDS = ("list", "create", "link", "unlink", "position", "settings", "grant", "report", "decisions", "export",
                  "import")
GRANT_DAYS = 30


class _Refused(Exception):
    pass


def _configure(p) -> None:
    sub = p.add_subparsers(dest="enterprise_cmd", required=True)

    def who(s) -> None:
        s.add_argument("--as", dest="as_pos", default="", metavar="POSITION",
                       help="the owner acts as this position (agents act as their own)")
        s.add_argument("--enterprise", default="", metavar="SLUG", help="when several enterprises exist")
        s.add_argument("--json", action="store_true")

    s = sub.add_parser("list", help="list the enterprises")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("create", help="create an enterprise")
    s.add_argument("slug")
    s.add_argument("--name", default="")
    s.add_argument("--emoji", default="")
    s.add_argument("--project", action="append", default=[], help="a project to link (repeatable)")
    s.add_argument("--json", action="store_true")
    for name in ("link", "unlink"):
        s = sub.add_parser(name, help=f"{name} projects")
        s.add_argument("slug")
        s.add_argument("projects", nargs="+")
        s.add_argument("--vacate", action="store_true", help="vacate the positions held by agents of an unlinked project")
    s = sub.add_parser("show", help="the chart as a tree")
    s.add_argument("slug", nargs="?", default="")
    who(s)
    pos = sub.add_parser("position", help="add, move, seat, vacate or remove a position").add_subparsers(
        dest="position_cmd", required=True)
    s = pos.add_parser("add")
    s.add_argument("slug")
    s.add_argument("id")
    s.add_argument("--title", default=None)
    s.add_argument("--reports-to", default=None)
    s.add_argument("--agent", default=None)
    s.add_argument("--department", default=None)
    s.add_argument("--job", default=None)
    s.add_argument("--job-file", default=None)
    s.add_argument("--json", action="store_true")
    for name in ("move", "seat", "vacate", "remove"):
        s = pos.add_parser(name)
        s.add_argument("slug")
        s.add_argument("id")
        s.add_argument("--json", action="store_true")
        if name == "move":
            s.add_argument("--reports-to", required=True, help="a position id, or `owner` for the top")
        if name == "seat":
            s.add_argument("--agent", required=True)
        if name == "remove":
            s.add_argument("--reparent-to", default=None)
    s = sub.add_parser("settings", help="change a setting")
    s.add_argument("slug")
    s.add_argument("pairs", nargs="+", metavar="KEY=VALUE")
    s.add_argument("--department", default="")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("grant", help="delegated approval")
    s.add_argument("slug")
    s.add_argument("position", nargs="?", default="")
    s.add_argument("--category", default="")
    s.add_argument("--ceiling", type=float, default=None)
    s.add_argument("--until", default="", help="YYYY-MM-DD (30 days at most)")
    s.add_argument("--revoke", default="", metavar="ID")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("report", help="print the last report")
    s.add_argument("slug")
    k = s.add_mutually_exclusive_group()
    k.add_argument("--daily", action="store_true")
    k.add_argument("--weekly", action="store_true")
    k.add_argument("--monthly", action="store_true")
    s.add_argument("--now", action="store_true", help="build one now")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("decisions", help="the decision log")
    s.add_argument("slug")
    s.add_argument("--since", default="", help="YYYY-MM-DD")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("export", help="the enterprise as a zip")
    s.add_argument("slug")
    s.add_argument("-o", "--output", default="")
    s = sub.add_parser("import", help="create an enterprise from a zip")
    s.add_argument("file")
    s.add_argument("--json", action="store_true")
    # turn commands
    s = sub.add_parser("assign", help="a task for a direct report")
    s.add_argument("position")
    s.add_argument("text", nargs="+")
    s.add_argument("--due", default=None)
    s.add_argument("--parent", default=None)
    s.add_argument("--task", default=None, help="send this task back (one more hop)")
    who(s)
    for name in ("done", "block"):
        s = sub.add_parser(name, help="hand in a task" if name == "done" else "report a blocker")
        s.add_argument("task")
        s.add_argument("text", nargs="+")
        who(s)
    s = sub.add_parser("escalate", help="ask one level up")
    s.add_argument("text", nargs="+")
    s.add_argument("--task", default=None)
    who(s)
    s = sub.add_parser("answer", help="answer an escalation")
    s.add_argument("id")
    s.add_argument("text", nargs="+")
    who(s)
    s = sub.add_parser("request", help="an organizational request")
    s.add_argument("category")
    s.add_argument("text", nargs="+")
    s.add_argument("--amount", type=float, default=None)
    s.add_argument("--position", default=None, help="edit_job / reseat: the position concerned")
    s.add_argument("--job", default=None, help="edit_job: the new job description")
    s.add_argument("--agent", default=None, help="reseat: the agent to seat")
    who(s)
    s = sub.add_parser("decide", help="decide a request")
    s.add_argument("id")
    s.add_argument("decision", choices=("allow", "deny"))
    s.add_argument("reason", nargs="*")
    who(s)
    s = sub.add_parser("objective", help="objectives").add_subparsers(dest="objective_cmd", required=True)
    o = s.add_parser("set", help="set the value of an objective")
    o.add_argument("id")
    o.add_argument("value", type=float)
    who(o)
    s = sub.add_parser("profile", help="the company profile")
    s.add_argument("--section", default="")
    who(s)
    s = sub.add_parser("route", help="the front desk passes a request to a department's lead")
    s.add_argument("department")
    s.add_argument("text", nargs="+")
    who(s)
    w = sub.add_parser("worker", help="temporary workers of a position").add_subparsers(dest="worker_cmd", required=True)
    o = w.add_parser("start", help="start a worker for a task")
    o.add_argument("text", nargs="+")
    o.add_argument("--for", dest="for_task", default="", metavar="TASK", help="the task the worker helps with")
    who(o)
    o = w.add_parser("list", help="the workers")
    who(o)
    o = w.add_parser("stop", help="stop a worker (the owner)")
    o.add_argument("id")
    who(o)


# ---- helpers ---------------------------------------------------------------------------------------------
def _out(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _module(name: str, func: str):
    """A function of a sibling module, imported when used; a missing one is a clear error, not a crash."""
    try:
        fn = getattr(importlib.import_module(f"maxxing.{name}"), func)
    except (ImportError, AttributeError):
        raise _Refused(f"`maxxing enterprise` cannot do this here: maxxing.{name}.{func} is not available in this "
                       "version") from None
    return fn


def _turn() -> dict:
    from . import agent_guard
    return agent_guard.agent_turn()


def _slug(a, turn: dict | None = None) -> str:
    """The enterprise of a turn command: the caller's seat, else --enterprise, else the only one."""
    from . import enterprises
    want = getattr(a, "enterprise", "") or getattr(a, "slug", "") or ""
    if turn is not None and turn["path"]:
        seat = enterprises.seat_of(turn["path"])
        if not seat:
            raise _Refused("This agent holds no position in an enterprise: nothing to do here.")
        if want and want != seat[0]:
            raise _Refused(f"This agent works in the enterprise {seat[0]!r}, not {want!r}.")
        return seat[0]
    if want:
        return want
    found = enterprises.names()
    if len(found) == 1:
        return found[0]
    raise _Refused("Several enterprises exist: pass --enterprise SLUG (" + ", ".join(found) + ")" if found
                   else "There is no enterprise yet (`maxxing enterprise create SLUG`).")


def _actor(a) -> tuple[str, str, dict]:
    """(enterprise slug, position of the caller ("" = the owner without --as), turn). An agent acts for its own
    position only; `--as` is the owner's."""
    from . import enterprises
    turn = _turn()
    slug = _slug(a, turn)
    asked = getattr(a, "as_pos", "") or ""
    if turn["path"]:
        if asked:
            raise _Refused("`--as` is for the owner: an agent acts as its own position.")
        seat = enterprises.seat_of(turn["path"])
        if seat is None:
            raise _Refused("This agent no longer holds a position.")
        return seat[0], seat[1], turn
    if asked and not enterprises.position(slug, asked):
        raise _Refused(f"Position {asked!r} not found in {slug!r} (see `maxxing enterprise show {slug}`).")
    return slug, asked, turn


def _need_pos(pos: str, what: str) -> str:
    if not pos:
        raise _Refused(f"{what} acts as a position: add --as POSITION.")
    return pos


def _say(a, obj, text: str) -> int:
    if getattr(a, "json", False):
        _out(obj)
    else:
        print(text)
    return 0


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _nest(pairs: list[str]) -> dict:
    out: dict = {}
    for p in pairs:
        key, eq, raw = p.partition("=")
        if not eq or not key.strip():
            raise _Refused(f"{p!r}: expected KEY=VALUE")
        node = out
        parts = key.strip().split(".")
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        node[parts[-1]] = _parse_value(raw)
    return out


def _day_end(day: str) -> float:
    """The end of YYYY-MM-DD in the configured time zone, as an epoch."""
    from datetime import datetime, time as dtime
    from zoneinfo import ZoneInfo
    from . import config
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        raise _Refused("--until: a date like 2026-12-05") from None
    try:
        zone = ZoneInfo(config.load_config().get("timezone") or "UTC")
    except Exception:  # noqa: BLE001 - unknown zone name
        zone = ZoneInfo("UTC")
    return datetime.combine(d, dtime(23, 59, 59), zone).timestamp()


# ---- structure ---------------------------------------------------------------------------------------------
def _list(a) -> int:
    from . import enterprises
    rows = enterprises.list_all()
    if a.json:
        _out(rows)
        return 0
    for r in rows:
        print(f"{r['id']}  {r['name']}  {r['positions']} position(s), {r['vacant']} vacant  "
              f"projects: {', '.join(r['projects']) or '-'}")
    return 0


def _create(a) -> int:
    from . import enterprises
    e = enterprises.create(a.slug, {"name": a.name, "emoji": a.emoji, "projects": a.project})
    return _say(a, e, f"enterprise {a.slug} created")


def _link(a) -> int:
    from . import enterprises
    cur = enterprises.load(a.slug)["projects"]
    new = [p for p in cur if p not in a.projects] if a.enterprise_cmd == "unlink" else cur + [
        p for p in a.projects if p not in cur]
    if new == cur:
        print("nothing to change: the projects are already " + ("unlinked" if a.enterprise_cmd == "unlink" else "linked"),
              file=sys.stderr)
        return 1
    enterprises.set_projects(a.slug, new, vacate=a.vacate)
    print(f"{a.slug}: projects {', '.join(new) or '-'}")
    return 0


def _position(a) -> int:
    from . import enterprises
    c, slug, pid = a.position_cmd, a.slug, a.id
    if c == "add":
        f: dict = {"id": pid}
        for k, v in (("title", a.title), ("reports_to", a.reports_to), ("agent", a.agent), ("department", a.department),
                     ("job", a.job)):
            if v is not None:
                f[k] = v
        if a.agent:
            from . import cmd_agents
            try:
                f["agent"] = cmd_agents.resolve(a.agent)
            except ValueError as e:
                raise _Refused(str(e)) from None
        if a.job_file:
            try:
                with open(a.job_file, encoding="utf-8") as fh:
                    f["job"] = fh.read()
            except OSError as e:
                raise _Refused(f"Cannot read {a.job_file}: {e}") from None
        enterprises.add_position(slug, f)
        return _say(a, {"position": pid}, f"position {pid} added to {slug}")
    if c == "remove":
        enterprises.remove_position(slug, pid, a.reparent_to)
        return _say(a, {"removed": pid}, f"position {pid} removed")
    rev = enterprises.load(slug)["rev"]
    if c == "move":
        enterprises.update_position(slug, pid, {"reports_to": a.reports_to}, rev=rev)
        text = f"position {pid} now reports to {a.reports_to}"
    elif c == "seat":
        from . import cmd_agents
        try:
            path = cmd_agents.resolve(a.agent)
        except ValueError as e:
            raise _Refused(str(e)) from None
        enterprises.update_position(slug, pid, {"agent": path}, rev=rev)
        text = f"position {pid} is held by {path}"
    else:
        enterprises.update_position(slug, pid, {"agent": None}, rev=rev)
        text = f"position {pid} is vacant"
    return _say(a, {"position": pid}, text)


def _settings(a) -> int:
    from . import enterprises
    patch = _nest(a.pairs)
    if a.department:
        deps = enterprises.load(a.slug)["departments"]
        dep = deps.get(a.department) or {"name": a.department}
        for k in ("name", "notes"):
            if k in patch:
                dep[k] = patch.pop(k)
        if patch:
            dep["settings"] = enterprises._merge(dep.get("settings") or {}, patch)
        deps[a.department] = dep
        e = enterprises.update(a.slug, {"departments": deps})
    else:
        fields = {k: patch.pop(k) for k in ("name", "emoji", "top", "envelope") if k in patch}
        if patch:
            fields["settings"] = patch
        e = enterprises.update(a.slug, fields)
    return _say(a, e, f"{a.slug}: settings updated")


def _grant(a) -> int:
    from . import enterprises
    import uuid
    with enterprises._lock:
        d = enterprises.load(a.slug)
        grants = list(d["grants"])
        if a.revoke:
            left = [g for g in grants if g["id"] != a.revoke]
            if len(left) == len(grants):
                raise _Refused(f"Grant {a.revoke!r} not found")
            enterprises.update(a.slug, {"grants": left})        # the model logs each grant made or revoked
            return _say(a, {"revoked": a.revoke}, f"grant {a.revoke} revoked")
        if not (a.position and a.category and a.ceiling is not None and a.until):
            raise _Refused("grant needs POSITION --category C --ceiling N --until DATE")
        if not enterprises.position(a.slug, a.position):
            raise _Refused(f"Position {a.position!r} not found")
        try:
            cats = importlib.import_module("maxxing.enterprise_policy").CATEGORIES
        except (ImportError, AttributeError):
            cats = None
        if cats and a.category not in cats:
            raise _Refused(f"Unknown category {a.category!r}: " + ", ".join(sorted(cats)))
        until = _day_end(a.until)
        if until <= time.time():
            raise _Refused("--until is in the past")
        if until > time.time() + GRANT_DAYS * 86400:
            raise _Refused(f"A grant lasts {GRANT_DAYS} days at most")
        g = {"id": "g_" + uuid.uuid4().hex[:6], "position": a.position, "category": a.category,
             "ceiling": a.ceiling, "until": until}
        enterprises.update(a.slug, {"grants": grants + [g]})
    return _say(a, g, f"grant {g['id']}: {a.position} decides {a.category} up to {a.ceiling:g} until {a.until}")


def _report(a) -> int:
    from . import enterprises
    enterprises.load(a.slug)
    kind = "weekly" if a.weekly else "monthly" if a.monthly else "daily"
    if a.now:
        r = _module("enterprise_reports", "build")(a.slug, kind)
        if not r:
            print("nothing to report yet", file=sys.stderr)
            return 1
        if a.json:
            _out(r)
        else:
            print(r.get("text") or r.get("name") or "report built")
        return 0
    items = [x for x in _module("enterprise_reports", "reports")(a.slug) if x.get("kind") == kind]
    if not items:
        print(f"no {kind} report yet (`--now` builds one)", file=sys.stderr)
        return 1
    last = max(items, key=lambda x: (x.get("date") or "", x.get("name") or ""))
    r = _module("enterprise_reports", "report")(a.slug, last["name"])
    if a.json:
        _out(r)
    else:
        print(r.get("text", ""))
    return 0


def _decisions(a) -> int:
    from . import enterprises
    from .sessions import store
    enterprises.load(a.slug)
    out: list[dict] = []
    before = None
    limit = max(1, min(a.limit, 500))
    for _ in range(20):
        items, before = enterprises.decisions(a.slug, before, 200)
        for it in items:
            if a.since and store.day_of(it["at"]) < a.since:
                before = None
                break
            out.append(it)
        if before is None or len(out) >= limit:
            break
    out = out[:limit]
    if a.json:
        _out(out)
        return 0
    for it in out:
        who = it.get("position") or it.get("by") or ""
        print(f"{store.day_of(it['at'])} {time.strftime('%H:%M', time.localtime(it['at']))}  {it['kind']:<10} {who:<14} "
              f"{it['text']}")
    return 0 if out else 1


def _export(a) -> int:
    data = _module("enterprise_io", "export_zip")(a.slug)
    if a.output:
        try:
            with open(a.output, "wb") as fh:
                fh.write(data)
        except OSError as e:
            raise _Refused(f"Cannot write {a.output}: {e}") from None
        print(f"written {a.output}")
    else:
        sys.stdout.buffer.write(data)
    return 0


def _import(a) -> int:
    try:
        with open(a.file, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise _Refused(f"Cannot read {a.file}: {e}") from None
    r = _module("enterprise_io", "import_zip")(data)
    return _say(a, r, f"enterprise {r.get('id', '')} imported")


# ---- reading: show, profile -------------------------------------------------------------------------------
def _tree(e: dict, shown: set[str] | None) -> list[str]:
    pos = [p for p in e["positions"] if shown is None or p["id"] in shown]
    ids = {p["id"] for p in pos}
    kids: dict[str, list[dict]] = {}
    for p in pos:
        kids.setdefault(p["reports_to"] if p["reports_to"] in ids else "", []).append(p)
    lines = [f"{e.get('emoji', '')} {e['name']} ({e['id']})".strip()]

    def walk(parent: str, depth: int) -> None:
        for p in kids.get(parent, []):
            occ = p.get("occupant")
            who = (occ or {}).get("display_name") or (occ or {}).get("path") or "vacant"
            extra = f", {p['inbox']} waiting" if p.get("inbox") else ""
            extra += f", {p['open_tasks']} open" if p.get("open_tasks") else ""
            lines.append(f"{'  ' * (depth + 1)}- {p['title']} ({p['id']}) [{p.get('state', '')}] {who}{extra}")
            walk(p["id"], depth + 1)

    walk("", 0)
    return lines


def _show(a) -> int:
    from . import agent_guard, enterprises
    turn = _turn()
    slug = _slug(a, turn)
    own = agent_guard.sandboxed_turn()
    shown = None
    if turn["path"] and own:                         # a sandboxed turn: its own position, its lead, its reports
        pid = (enterprises.seat_of(turn["path"]) or ("", ""))[1]
        shown = {pid, *enterprises.reports_of(slug, pid)} | ({enterprises.lead_of(slug, pid)} - {None})
    e = enterprises.get(slug)
    if shown is not None:
        e = {"id": e["id"], "name": e["name"], "emoji": e["emoji"], "top": e["top"],
             "positions": [p for p in e["positions"] if p["id"] in shown]}
    if a.json:
        _out(e)
    else:
        print("\n".join(_tree(e, shown)))
    return 0


def _profile(a) -> int:
    from . import enterprise_knowledge
    turn = _turn()
    slug = _slug(a, turn)
    sec = a.section.strip()
    if sec and sec not in enterprise_knowledge.PROFILE_SECTIONS:
        raise _Refused("--section: one of " + ", ".join(enterprise_knowledge.PROFILE_SECTIONS))
    p = enterprise_knowledge.profile(slug)
    _out(p.get(sec) if sec else p)
    return 0


# ---- from an agent turn -----------------------------------------------------------------------------------------
def _text(a) -> str:
    t = " ".join(a.text).strip()
    if not t:
        raise _Refused("The text is empty.")
    return t


def _turn_cmd(a) -> int:
    c = a.enterprise_cmd
    if c == "profile":
        return _profile(a)
    slug, pos, turn = _actor(a)
    sess, outside = turn["session"], turn["outside"]
    if c == "assign":
        t = _module("enterprise_flow", "assign")(slug, pos or None, a.position, _text(a), due=a.due, parent=a.parent,
                                                 task=a.task, session=sess, outside=outside)
        return _say(a, t, f"assigned {t.get('id', '')} to {a.position}".replace("  ", " "))
    if c in ("done", "block"):
        fn = _module("enterprise_flow", c)
        t = fn(slug, _need_pos(pos, f"`{c}`"), a.task, _text(a), session=sess)
        return _say(a, t, f"{a.task}: {'handed in' if c == 'done' else 'marked blocked'}")
    if c == "escalate":
        r = _module("enterprise_flow", "escalate")(slug, _need_pos(pos, "`escalate`"), _text(a), task=a.task,
                                                   session=sess, outside=outside)
        return _say(a, r, f"escalated {r.get('id', '')}".strip())
    if c == "answer":
        r = _module("enterprise_flow", "answer")(slug, a.id, _text(a), by=pos or None,
                                                           outside=outside)
        return _say(a, r, f"{a.id}: answered")
    if c == "request":
        payload = {k: v for k, v in (("position", a.position), ("job", a.job), ("agent", a.agent)) if v} or None
        if payload and payload.get("agent"):
            from . import cmd_agents
            try:
                payload["agent"] = cmd_agents.resolve(payload["agent"])
            except ValueError as e:
                raise _Refused(str(e)) from None
        r = _module("enterprise_policy", "request")(slug, _need_pos(pos, "`request`"), a.category, _text(a),
                                                    amount=a.amount, session=sess, outside=outside, payload=payload)
        return _say(a, r, f"request {r.get('id', '')} ({r.get('status', 'sent')})".replace("  ", " "))
    if c == "route":
        r = _module("enterprise_desk", "route")(slug, _need_pos(pos, "`route`"), a.department, _text(a), session=sess)
        return _say(a, r, f"routed: task {r.get('id', '')}".strip())
    if c == "worker":
        return _worker(a, slug, pos, turn)
    if c == "decide":
        r = _module("enterprise_policy", "decide")(slug, a.id, a.decision, reason=" ".join(a.reason).strip(),
                                                   by=pos or None, outside=outside)
        return _say(a, r, f"{a.id}: {a.decision}")
    return _objective(a, slug, pos)


def _worker(a, slug: str, pos: str, turn: dict) -> int:
    c = a.worker_cmd
    if c == "stop":
        if turn["path"]:
            raise _Refused("`maxxing enterprise worker stop` is the owner's: not allowed in an agent turn.")
        w = _module("enterprise_workers", "stop")(slug, a.id)
        return _say(a, w, f"worker {a.id} stopped")
    if c == "list":
        rows = _module("enterprise_workers", "workers")(slug, pos or None)
        if getattr(a, "json", False):
            _out(rows)
        else:
            for w in rows:
                print(f"{w['id']}  {w['status']:<8} {w['position']}  {w['text'][:80]}")
        return 0 if rows else 1
    r = _module("enterprise_workers", "start")(slug, _need_pos(pos, "`worker start`"), " ".join(a.text),
                                               task=a.for_task, session=turn["session"], outside=turn["outside"])
    if r["status"] == "started":
        return _say(a, r, f"worker {r['worker']['id']} started")
    return _say(a, r, f"request {r['request']['id']} is waiting for a decision: the worker starts once it is allowed")


def _objective(a, slug: str, pos: str) -> int:
    from . import enterprises
    with enterprises._lock:
        objs = enterprises.load(slug)["objectives"]
        o = next((x for x in objs if x["id"] == a.id), None)
        if not o:
            raise _Refused(f"Objective {a.id!r} not found")
        if pos and o["owner"] != pos:
            raise _Refused(f"Only the owner position of the objective ({o['owner'] or 'none'}) sets its value.")
        o["value"] = a.value
        enterprises.update(slug, {"objectives": objs})
        enterprises.log(slug, "objective", f"{o['text'] or o['id']}: {a.value:g}", by=pos or "owner", position=pos)
    return _say(a, o, f"objective {a.id} = {a.value:g}")


# ---- entry -----------------------------------------------------------------------------------------------------
def _handler(a) -> int:
    from . import agents, enterprises
    c = a.enterprise_cmd
    try:
        if not enterprises.feature_on():
            raise _Refused("Enterprises are off (Settings -> Features, needs Agents).")
        if c in STRUCTURE_CMDS:
            from . import agent_guard
            if _turn()["path"] and c in agent_guard.ENTERPRISE_OWNER_ONLY:
                raise _Refused(f"`maxxing enterprise {c}` is not allowed in an agent turn.")
            return {"list": _list, "create": _create, "link": _link, "unlink": _link, "position": _position,
                    "settings": _settings, "grant": _grant, "report": _report, "decisions": _decisions,
                    "export": _export, "import": _import}[c](a)
        if c == "show":
            return _show(a)
        return _turn_cmd(a)
    except _Refused as e:
        print(e, file=sys.stderr)
        return 2
    except (enterprises.EnterpriseError, agents.AgentError) as e:
        print(e.message, file=sys.stderr)
        return 2


cli.register("enterprise", "enterprise: org charts of agents above projects (positions, delegation, requests)",
             _configure, _handler)
