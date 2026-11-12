"""Enterprise policy: organizational requests (who decides what), grants, spending / key / domain envelopes,
who may write to whom, trust along the chain. See docs/dev/API.md#enterprises and INTERNALS.md.

Requests live in `<state>/enterprises/<slug>/requests.json` (`{"items": [...]}`, written under the enterprises lock).
Nothing here grants anything: an allowed request only says yes, a key, a domain or a folder still needs the owner's
agent card. Every lookup (`decider`, `can_send`, `over_ceiling`, `cap`) never raises and does nothing while the
Enterprises feature is off."""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import re
import secrets
import time
from typing import Any

from . import agents, config, enterprises
from .enterprises import EnterpriseError

log = logging.getLogger("maxxing.enterprise_policy")

PROFILES = ("careful", "balanced", "autonomous")
GRANT_MAX_S = 30 * 86400 + 3600                     # a grant lasts 30 days at most (an hour of slack)
KEEP = 500                                          # requests kept per enterprise (the oldest answered go first)


def _row(label: str, careful: str, balanced: str, autonomous: str, enforced: str = "server") -> dict:
    return {"label": label, "careful": careful, "balanced": balanced, "autonomous": autonomous, "enforced": enforced}


# The rows of the matrix (spec 7.1): who decides per autonomy profile; "free" = allowed and logged, "lead" = the
# requester's lead (or a grantee), "owner" = the owner. A row that is "owner" in autonomous is never delegable.
CATEGORIES: dict[str, dict] = {
    "assign_own": _row("Assign to a direct report, read the profile, write in one's department", "free", "free", "free"),
    "deliver_cross": _row("Deliver into another department's folder", "owner", "lead", "lead"),
    "assign_cross": _row("Assign across departments", "owner", "lead", "lead"),
    "edit_job": _row("Edit a report's job description", "owner", "lead", "lead"),
    "worker": _row("Create a worker from an approved template", "owner", "lead", "lead"),
    "profile_edit": _row("Edit the company profile (not prices or terms)", "owner", "lead", "lead"),
    "spending": _row("Declared spending up to the department's threshold", "owner", "lead", "lead", "declared"),
    "raise_budget": _row("Raise a report's daily budget inside the envelope", "owner", "owner", "lead"),
    "reseat": _row("Re-seat an agent on a vacant position of one's team", "owner", "owner", "lead"),
    "profile_terms": _row("Edit prices or terms in the profile", "owner", "owner", "owner"),
    "desk_live": _row("Put the front desk live", "owner", "owner", "owner"),
    "hire_remove": _row("Hire or remove a permanent agent, change keys, domains, sandbox, folders", "owner", "owner", "owner"),
    "spending_high": _row("Declared spending above the threshold", "owner", "owner", "owner", "declared"),
    "recurring": _row("Any new recurring cost", "owner", "owner", "owner", "declared"),
    "publish": _row("Publish publicly, write to a customer, anything irreversible", "owner", "owner", "owner", "role"),
}
NEEDS_GRANT = ("deliver_cross", "hire_remove", "worker", "reseat")          # categories that usually need a grant
GRANT_NOTE = ("Allowing a request grants nothing: a key, a domain or a folder it needs still comes from the "
              "owner's card of the agent.")
_NEEDS_RE = re.compile(r"\b(keys?|domains?|folders?|sandbox|secret|token|password)\b", re.I)


def _now(now: float | None = None) -> float:
    return time.time() if now is None else float(now)


def _owner_by(by: Any) -> bool:
    return by is None or by == "" or by == "owner"


# ---- requests: storage -------------------------------------------------------------------------------------
def _file(slug: str):
    return enterprises.state(slug) / "requests.json"


def _read(slug: str) -> list[dict]:
    try:
        raw = json.loads((enterprises._peek(slug) / "requests.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else None
    return [x for x in items if isinstance(x, dict) and x.get("id")] if isinstance(items, list) else []


def _write(slug: str, items: list[dict]) -> None:
    if len(items) > KEEP:
        done = [x for x in items if x.get("status") != "pending"]
        drop = {x["id"] for x in done[: len(items) - KEEP]}
        items = [x for x in items if x["id"] not in drop]
    config.write_json(_file(slug), {"items": items})


def _public(r: dict) -> dict:
    keys = ("id", "category", "position", "text", "amount", "status", "decider", "at", "outside", "deadline",
            "decided_by", "decided_at", "reason", "level")
    return {k: r.get(k) for k in keys}


def requests(slug: str, pending_only: bool = False) -> list[dict]:
    """The enterprise's organizational requests, newest first (pending_only: those waiting for a decision)."""
    enterprises.load(slug)
    items = _read(slug)
    if pending_only:
        items = [x for x in items if x.get("status") == "pending"]
    return [_public(x) for x in sorted(items, key=lambda x: -float(x.get("at") or 0))]


# ---- who decides ----------------------------------------------------------------------------------------------
def _data(slug: str) -> dict:
    return enterprises._index()["by"].get(slug) or {}


def _until(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.strip():
        try:
            d = dt.datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if len(v.strip()) <= 10:
            d = d + dt.timedelta(days=1)                # a bare date lasts to the end of that day
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.timestamp()
    return None


def threshold(slug: str, pos: str) -> float | None:
    """The declared-spending limit a lead may decide: the setting `spending_threshold` when there is one, else the
    department envelope's usd per day, else the enterprise envelope's (None: no limit known, the owner decides)."""
    v = enterprises.setting(slug, "spending_threshold", pos)
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return float(v)
    d = _data(slug)
    dept = (d.get("departments") or {}).get(enterprises.department_of(slug, pos)) or {}
    for env in ((dept.get("envelope") or {}), (d.get("envelope") or {})):
        if (env.get("usd_per_day") or 0) > 0:
            return float(env["usd_per_day"])
    return None


def _grant(slug: str, pos: str, category: str, amount: float | None, now: float) -> str | None:
    """The position that may decide this request through a grant (owner-made, 30 days at most, only rows a lead
    decides in autonomous, within its ceiling, over its own subtree), nearest lead first."""
    row = CATEGORIES.get(category)
    if not row or row["autonomous"] != "lead":
        return None
    chain = enterprises.ancestors(slug, pos)
    best: tuple[int, str] | None = None
    for g in _data(slug).get("grants") or []:
        who = g.get("position")
        if g.get("category") != category or who not in chain:
            continue
        end = _until(g.get("until"))
        if end is None or end <= now or end > now + GRANT_MAX_S:
            continue
        if category == "spending":
            cap = g.get("ceiling") if isinstance(g.get("ceiling"), (int, float)) else threshold(slug, pos)
            if amount is None or cap is None or amount > cap:
                continue
        elif isinstance(g.get("ceiling"), (int, float)) and amount is not None and amount > g["ceiling"]:
            continue
        rank = chain.index(who)
        if best is None or rank < best[0]:
            best = (rank, who)
    return best[1] if best else None


def _route(slug: str, pos: str, category: str, amount: float | None, outside: bool,
           now: float | None = None) -> tuple[str, str]:
    """(kind, who): free | lead | owner, and the deciding position for a lead. Structure only: it does not look at
    whether the lead is running (request() skips the ones that are not)."""
    if outside or category not in CATEGORIES:
        return "owner", ""                                   # invariant 1; an unknown category is never delegated
    if category == "spending" and amount is None:
        return "owner", ""                                   # undeclared spending
    granted = _grant(slug, pos, category, amount, _now(now))
    if granted:
        return "lead", granted
    if category == "spending":
        limit = threshold(slug, pos)
        if limit is None or amount > limit:
            category = "spending_high"
    profile = enterprises.setting(slug, "autonomy", pos)
    row = CATEGORIES[category][profile if profile in PROFILES else "balanced"]
    if row == "lead":
        lead = enterprises.lead_of(slug, pos)
        return ("lead", lead) if lead else ("owner", "")     # the top of the chart reports to the owner
    return row, ""


def decider(slug: str, pos: str, category: str, *, amount: float | None = None, outside: bool = False) -> str:
    """Who decides a request of this category from this position: "free", "lead" or "owner"."""
    return _route(slug, pos, category, amount, outside)[0]


def _ready(slug: str, pos: str) -> bool:
    """The position's occupant exists and is switched on (a lead that cannot decide is skipped)."""
    p = enterprises.position(slug, pos)
    path = p["agent"] if p else None
    if not path or not agents.exists(path):
        return False
    try:
        return bool(agents.load(path)["enabled"])
    except Exception:  # noqa: BLE001
        return False


def _pick(slug: str, pos: str, after: str | None = None) -> str:
    """The next lead above `pos` (past `after`) that can decide, else "owner"."""
    chain = enterprises.ancestors(slug, pos)
    if after in chain:
        chain = chain[chain.index(after) + 1:]
    elif after and after != "owner":
        chain = []
    for p in chain:
        if _ready(slug, p):
            return p
        enterprises.log(slug, "request_skipped", f"{p} cannot decide (vacant or switched off): skipped", position=pos)
    return "owner"


# ---- delivery and owner notification (the other modules by their contract names) -----------------------------
def _title(slug: str, pos: str) -> str:
    p = enterprises.position(slug, pos)
    return p["title"] if p else pos


def _deliver(slug: str, pos: str, kind: str, text: str, *, sender: str = "", outside: bool = False,
             session: str = "") -> None:
    try:
        from . import enterprise_flow
        fn = enterprise_flow.deliver
    except (ImportError, AttributeError):
        fn = None
    try:
        if fn is not None:
            fn(slug, pos, kind, text, sender=sender, outside=outside, session=session)
            return
        d = enterprises.state(slug) / "inbox"
        d.mkdir(parents=True, exist_ok=True)
        line = {"id": secrets.token_hex(4), "kind": kind, "from": sender, "text": text, "task": "", "at": time.time(),
                "outside": bool(outside)}
        with enterprises._lock:
            fd = os.open(d / f"{pos}.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - a delivery that failed must not undo the decision
        log.exception("enterprise %s: delivery to %s failed", slug, pos)


def _notify(slug: str, r: dict) -> None:
    """The Allow / Deny / Open card of a request that waits for the owner."""
    ref = f"enterprise:{slug}:{r['id']}"
    name = _title(slug, r["position"])
    title = f"{name} asks: {CATEGORIES.get(r['category'], {}).get('label', r['category'])}"
    body = r["text"] + (f"\nAmount: {r['amount']:g} USD" if isinstance(r.get("amount"), (int, float)) else "")
    actions = [{"id": "allow", "label": "Allow", "style": "primary"}, {"id": "deny", "label": "Deny", "style": "danger"},
               {"id": "open", "label": "Open", "style": "link"}]
    url = f"/enterprises/{slug}"
    try:
        from . import enterprise_reports
        enterprise_reports.notify_owner(slug, title, body, level="warning", url=url, ref=ref, actions=actions,
                                        dedupe=ref)
        return
    except (ImportError, AttributeError):
        pass
    except Exception:  # noqa: BLE001
        log.exception("enterprise %s: owner notification failed", slug)
    try:
        from . import feed
        feed.post(title, body, "warning", "enterprises", url, dedupe=ref, ref=ref, actions=actions)
    except Exception:  # noqa: BLE001
        log.exception("enterprise %s: feed post failed", slug)


def _hand_to(slug: str, r: dict, who: str) -> None:
    """Hand a pending request to its decider: the lead's inbox, or the owner's card."""
    if who == "owner":
        _notify(slug, r)
        return
    out = " [from outside text]" if r.get("outside") else ""
    _deliver(slug, who, "request",
             f"Request {r['id']} from {_title(slug, r['position'])} ({r['category']}){out}: {r['text']}"
             + (f" Amount: {r['amount']:g} USD." if isinstance(r.get("amount"), (int, float)) else "")
             + f" Decide with: maxxing enterprise decide {r['id']} allow|deny \"<reason>\"",
             sender=r["position"], outside=bool(r.get("outside")), session=r.get("session") or "")


# ---- request / decide ------------------------------------------------------------------------------------------
def request(slug: str, pos: str, category: str, text: str, *, amount: float | None = None, session: str = "",
            outside: bool = False, payload: dict | None = None) -> dict:
    """An occupant asks for something the matrix governs. free: allowed and logged; lead: delivered to the lead's
    inbox with a deadline; owner: an Allow / Deny card. -> the request."""
    if not enterprises.feature_on():
        raise EnterpriseError(404, "feature_off", "Enterprises are off (Settings -> Features, needs Agents)")
    enterprises.load(slug)
    if not enterprises.position(slug, pos):
        raise EnterpriseError(400, "bad_position", f"Position {pos!r} not found")
    if category not in CATEGORIES:
        raise EnterpriseError(400, "bad_category", "Category: " + ", ".join(CATEGORIES))
    text = " ".join(str(text or "").split())[:enterprises.TEXT_MAX]
    if not text:
        raise EnterpriseError(400, "invalid", "Say what is asked")
    if amount is not None:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount != amount or not 0 <= amount <= 1e9:
            raise EnterpriseError(400, "invalid", "amount: a number of USD")
        amount = round(float(amount), 2)
    now = time.time()
    kind, who = _route(slug, pos, category, amount, outside, now)
    if kind == "lead" and not _ready(slug, who):
        enterprises.log(slug, "request_skipped", f"{who} cannot decide (vacant or switched off): skipped", position=pos)
        who = _pick(slug, pos, after=who)
        kind = "owner" if who == "owner" else "lead"
    r: dict[str, Any] = {"id": secrets.token_hex(4), "category": category, "position": pos, "text": text,
                         "amount": amount, "status": "pending", "decider": who or kind, "at": now,
                         "outside": bool(outside), "session": str(session or "")[:64], "deadline": None,
                         "decided_by": "", "decided_at": None, "reason": "", "level": 0,
                         "payload": payload if isinstance(payload, dict) and len(json.dumps(payload, default=str)) < 20000 else None}
    if kind == "free":
        r.update(status="allowed", decider="free", decided_by="policy", decided_at=now)
    elif kind == "lead":
        r["deadline"] = now + int(enterprises.setting(slug, "escalation_timeout_h", pos) or 4) * 3600
    with enterprises._lock:
        items = _read(slug)
        items.append(r)
        _write(slug, items)
    if kind == "free":
        enterprises.log(slug, "request_allowed", f"{category}: {text}", by="policy", position=pos, session=r["session"])
    else:
        enterprises.log(slug, "request", f"{category} -> {r['decider']}: {text}", by=pos, position=pos,
                        session=r["session"])
        _hand_to(slug, r, r["decider"])
    enterprises.invalidate(slug)
    return _public(r)


def _needs_note(r: dict) -> str:
    return GRANT_NOTE if r["category"] in NEEDS_GRANT or _NEEDS_RE.search(r["text"]) else ""


def decide(slug: str, req_id: str, decision: str, *, reason: str = "", by: str | None = None, via: str = "") -> dict:
    """Allow or deny a pending request. by None = the owner; else the position that decides it (the request's
    current decider, never the requester, only for a request of its own subtree). via: where the owner clicked."""
    if decision not in ("allow", "deny"):
        raise EnterpriseError(400, "invalid", "decision: allow or deny")
    reason = " ".join(str(reason or "").split())[:300]
    enterprises.load(slug)
    owner = _owner_by(by)
    with enterprises._lock:
        items = _read(slug)
        r = next((x for x in items if x["id"] == req_id), None)
        if r is None:
            raise EnterpriseError(404, "not_found", f"Request {req_id!r} not found")
        if r["status"] != "pending":
            raise EnterpriseError(409, "not_pending", "This request is already decided")
        if not owner:
            if by == r["position"]:
                raise EnterpriseError(403, "self_decision", "Nobody decides their own request")
            if by not in enterprises.ancestors(slug, r["position"]):
                raise EnterpriseError(403, "not_in_subtree", "A lead decides only for its own subtree")
            if r["decider"] != by:
                raise EnterpriseError(403, "not_decider", f"This request is waiting for {r['decider']}")
        now = time.time()
        r.update(status="allowed" if decision == "allow" else "denied", decided_by="owner" if owner else by,
                 decided_at=now, reason=reason)
        _write(slug, items)
    who = "the owner" if owner else _title(slug, by)
    word = "allowed" if decision == "allow" else "denied"
    note = _needs_note(r) if decision == "allow" else ""
    _deliver(slug, r["position"], "decision",
             f"Your request {r['id']} ({r['category']}) was {word} by {who}." + (f" {reason}" if reason else "")
             + (f" {note}" if note else ""), sender="" if owner else by, outside=bool(r.get("outside")),
             session=r.get("session") or "")
    enterprises.log(slug, f"request_{word}", f"{r['category']}: {r['text']}" + (f" ({reason})" if reason else ""),
                    by="owner" if owner else by, position=r["position"], session=r.get("session") or "")
    with contextlib.suppress(Exception):
        from . import feed
        how = ("Allowed" if decision == "allow" else "Denied") + (" on Telegram" if via == "telegram" else "")
        feed.resolve(f"enterprise:{slug}:{r['id']}", how, read=True, level="info" if decision == "allow" else "warning")
    enterprises.invalidate(slug)
    if decision == "allow":
        _run_payload(slug, r)
    return _public(r)


def _run_payload(slug: str, r: dict) -> None:
    """An allowed cross-department assignment is carried out now (the flow module does not re-run it)."""
    p = r.get("payload")
    if r.get("category") != "assign_cross" or not isinstance(p, dict) or not p.get("to_pos"):
        return
    try:
        from . import enterprise_flow
        enterprise_flow.assign(slug, r["position"], p["to_pos"], p.get("deliverable") or r["text"], due=p.get("due"),
                               parent=p.get("parent"), session=r.get("session") or "", outside=bool(r.get("outside")),
                               approved=True)
    except Exception:  # noqa: BLE001 - the decision stands; the log says why nothing was assigned
        log.exception("enterprise %s: allowed assignment failed", slug)
        enterprises.log(slug, "request_failed", f"The allowed assignment {r['id']} could not be made", by="policy",
                        position=r["position"])


def feed_action(rid: str, action: str, by: str, ev: dict) -> None:
    """A button of the request's feed event (web or Telegram); the value is `<slug>:<request id>`."""
    from . import feed
    slug, _, req = rid.partition(":")
    if action in ("allow", "deny"):
        try:
            if slug != "esc" and any(x["id"] == req for x in _read(slug)):
                decide(slug, req, action, by=None, via=by)
                return
        except EnterpriseError as e:
            raise feed.FeedError(e.status, e.code, e.message) from None
        try:                                            # not a request: another card of the enterprise (escalation)
            from . import enterprise_flow
            fn = getattr(enterprise_flow, "feed_action", None)
        except ImportError:
            fn = None
        if fn:
            fn(rid, action, by, ev)
            return
        raise feed.FeedError(404, "not_found", "This request no longer exists")


# ---- tick: deadlines climb, expired grants go -------------------------------------------------------------------
def _climb(slug: str, now: float) -> None:
    moved: list[tuple[dict, str]] = []
    with enterprises._lock:
        items = _read(slug)
        for r in items:
            if r.get("status") != "pending" or r.get("decider") in ("owner", "free") or not r.get("deadline"):
                continue
            if r["deadline"] > now:
                continue
            nxt = _pick(slug, r["position"], after=r["decider"])
            enterprises.log(slug, "request_climbed", f"{r['category']}: no answer from {r['decider']}, to {nxt}",
                            by="policy", position=r["position"])
            r["decider"], r["level"] = nxt, int(r.get("level") or 0) + 1
            r["deadline"] = None if nxt == "owner" else now + int(
                enterprises.setting(slug, "escalation_timeout_h", r["position"]) or 4) * 3600
            moved.append((dict(r), nxt))
        if moved:
            _write(slug, items)
    for r, who in moved:
        _hand_to(slug, r, who)
    if moved:
        enterprises.invalidate(slug)


def _drop_grants(slug: str, now: float) -> None:
    gone = [g for g in _data(slug).get("grants") or [] if (_until(g.get("until")) or 0) <= now]
    if not gone:
        return
    ids = {g["id"] for g in gone}

    def edit(d: dict) -> list[str]:
        d["grants"] = [g for g in d["grants"] if g["id"] not in ids]
        return sorted(ids)
    enterprises._apply(slug, edit)
    for g in gone:
        enterprises.log(slug, "grant_expired", f"The grant {g['id']} ({g['category']} for {g['position']}) ended",
                        by="policy", position=str(g.get("position") or ""))


def tick(now: float | None = None) -> None:
    """Called every minute by the enterprise loop: requests past their deadline climb, ended grants are dropped."""
    if not enterprises.feature_on():
        return
    t = _now(now)
    for slug in enterprises.names():
        for fn in (_climb, _drop_grants):
            try:
                fn(slug, t)
            except Exception:  # noqa: BLE001 - one enterprise must not stop the others
                log.exception("enterprise %s: policy tick (%s)", slug, fn.__name__)


# ---- envelopes: budget -------------------------------------------------------------------------------------------
def _levels(path: str) -> tuple[str, list[tuple[str, str, float, list[str]]]]:
    """(slug, [(id, label, usd per day, member agent paths)]) of the envelopes with a budget that apply to the agent."""
    seat = enterprises.seat_of(path)
    d = _data(seat[0]) if seat else {}
    if not seat or not d:
        return "", []
    slug, pos = seat
    out = []
    dept = enterprises.department_of(slug, pos)
    env = ((d.get("departments") or {}).get(dept) or {}).get("envelope") or {}
    if dept and (env.get("usd_per_day") or 0) > 0:
        members = [p["agent"] for p in d["positions"] if p["department"] == dept and p["agent"]]
        out.append((f"department:{dept}", f"The department {(d['departments'][dept].get('name') or dept)}",
                    float(env["usd_per_day"]), members))
    top = d.get("envelope") or {}
    if (top.get("usd_per_day") or 0) > 0:
        out.append(("enterprise", f"The enterprise {d.get('name') or slug}", float(top["usd_per_day"]),
                    [p["agent"] for p in d["positions"] if p["agent"]]))
    return slug, out


def _usage(members: list[str], session: str | None = None) -> tuple[float, float]:
    """(spent today, held by runs in progress) over the distinct existing agents."""
    spent = held = 0.0
    for m in dict.fromkeys(members):
        if not agents.exists(m):
            continue
        spent += agents.day_cost(m)
        held += agents._held(agents._read_state(m), but=session)
    return spent, held


def has_ceiling(path: str) -> bool:
    try:
        return bool(enterprises.seat_of(path)) and enterprises.feature_on() and bool(_levels(path)[1])
    except Exception:  # noqa: BLE001
        return False


_told: set[tuple] = set()


def _tell(slug: str, key: str, label: str, usd: float) -> None:
    """One owner notification per envelope per day."""
    from .sessions import store
    day = store.day_of(time.time())
    if (slug, key, day) in _told:
        return
    _told.add((slug, key, day))
    if len(_told) > 500:
        _told.clear()
    ref = f"envelope:{slug}:{key}:{day}"
    title, body = f"{label} reached its daily budget", f"{usd:g} USD spent today: its agents wait until tomorrow."
    try:
        from . import enterprise_reports
        enterprise_reports.notify_owner(slug, title, body, level="warning", url=f"/enterprises/{slug}", dedupe=ref)
        return
    except (ImportError, AttributeError):
        pass
    except Exception:  # noqa: BLE001
        log.exception("enterprise %s: envelope notification failed", slug)
    with contextlib.suppress(Exception):
        from . import feed
        feed.post(title, body, "warning", "enterprises", f"/enterprises/{slug}", dedupe=ref)


def over_ceiling(path: str) -> str | None:
    """The refusal text once the agent's department or enterprise has spent its daily envelope (None: room left)."""
    try:
        if not enterprises.seat_of(path) or not enterprises.feature_on():
            return None
        slug, levels = _levels(path)
        for key, label, usd, members in levels:
            if _usage(members)[0] >= usd:
                _tell(slug, key, label, usd)
                return f"{label} reached its daily budget ({usd:g} USD): runs resume tomorrow."
    except Exception:  # noqa: BLE001
        log.exception("envelope check failed (%s)", path)
    return None


def ceiling_held(path: str) -> bool:
    """True when what is left of an envelope is all held by runs in progress (the delivery waits: busy)."""
    try:
        if not enterprises.seat_of(path) or not enterprises.feature_on():
            return False
        for _key, _label, usd, members in _levels(path)[1]:
            spent, held = _usage(members)
            if held and spent + held >= usd - 0.01:
                return True
    except Exception:  # noqa: BLE001
        log.exception("envelope check failed (%s)", path)
    return False


def cap(path: str, left: float, session: str | None = None) -> float:
    """The per-run budget `left` lowered to what its department and enterprise envelopes still have."""
    try:
        if not enterprises.seat_of(path) or not enterprises.feature_on():
            return left
        for _key, _label, usd, members in _levels(path)[1]:
            spent, held = _usage(members, session)
            left = min(left, max(usd - spent - held, 0.01))
    except Exception:  # noqa: BLE001
        log.exception("envelope cap failed (%s)", path)
    return left


# ---- envelopes: keys and domains -------------------------------------------------------------------------------
def _lists(slug: str, pos: str, field: str) -> list[tuple[str, list[str]]]:
    """The keys / domains lists (not null) that bind the position: its department's, then the enterprise's."""
    d = _data(slug)
    dept = enterprises.department_of(slug, pos)
    out = []
    de = (d.get("departments") or {}).get(dept) or {}
    if dept and isinstance(de.get("envelope", {}).get(field), list):
        out.append((f"department {de.get('name') or dept}", de["envelope"][field]))
    if isinstance((d.get("envelope") or {}).get(field), list):
        out.append((f"enterprise {d.get('name') or slug}", d["envelope"][field]))
    return out


def _within(field: str, item: str, allowed: list[str]) -> bool:
    if field == "keys":
        return item in allowed
    d = item.lower()
    for e in (str(x).lower().removeprefix("https://").removeprefix("http://").rstrip("/") for x in allowed):
        if d == e or (e.startswith("*.") and not d.startswith("*.") and (d == e[2:] or d.endswith(e[1:]))):
            return True
        if e.startswith("*.") and d.startswith("*.") and (d == e or d[2:].endswith(e[1:])):
            return True
    return False


def _outside(field: str, items: list[str], allowed: list[str]) -> list[str]:
    return [x for x in items if not _within(field, x, allowed)]


def check_envelope(path: str, fields: dict) -> None:
    """Refuses widening an agent's keys or domains beyond its department's / enterprise's lists: 400 exceeds_envelope.
    Only what is added counts (an agent already over its envelope is flagged by over_envelope, never edited)."""
    seat = enterprises.seat_of(path)
    if not seat or not enterprises.feature_on():
        return
    cur = None
    for field, clean in (("keys", agents._clean_keys), ("domains", agents._clean_domains)):
        if not isinstance(fields.get(field), list):
            continue
        lists = _lists(seat[0], seat[1], field)
        if not lists:
            continue
        if cur is None:
            cur = agents.load(path)
        added = [x for x in clean(fields[field]) if x not in cur[field]]
        for scope, allowed in lists:
            bad = _outside(field, added, allowed)
            if bad:
                raise agents.AgentError(400, "exceeds_envelope",
                                        f"The {field} {', '.join(bad)} are outside the {scope} envelope "
                                        f"({', '.join(allowed) or 'none'}): widen the envelope first.")


def over_envelope(slug: str) -> list[dict]:
    """The occupants whose keys or domains exceed their envelope: [{position, what}] (flags for the chart)."""
    out: list[dict] = []
    for p in _data(slug).get("positions") or []:
        path = p.get("agent")
        if not path or not agents.exists(path):
            continue
        try:
            a = agents.load(path)
        except Exception:  # noqa: BLE001
            continue
        for field in ("keys", "domains"):
            bad: list[str] = []
            for _scope, allowed in _lists(slug, p["id"], field):
                bad += [x for x in _outside(field, a.get(field) or [], allowed) if x not in bad]
            if bad:
                out.append({"position": p["id"], "what": f"{field}: {', '.join(bad)}"})
    return out


# ---- communication and trust --------------------------------------------------------------------------------------
def can_send(from_path: str, to_path: str) -> str | None:
    """None when `maxxing agents send` may go through; else the refusal text (who to go through). Only when both
    agents sit in the same enterprise and the feature is on."""
    try:
        a, b = enterprises.seat_of(from_path), enterprises.seat_of(to_path)
        if not a or not b or a[0] != b[0] or a[1] == b[1] or not enterprises.feature_on():
            return None
        slug, src, dst = a[0], a[1], b[1]
        mode = enterprises.setting(slug, "communication", src) or "leads"
        up = enterprises.lead_of(slug, src)
        if dst == up or dst in enterprises.reports_of(slug, src):
            return None
        if mode in ("leads", "open") and enterprises.reports_of(slug, src) and enterprises.reports_of(slug, dst):
            return None
        if mode == "open" and any({src, dst} == set(p) for p in enterprises.setting(slug, "allow", src) or []):
            return None
        via = (f"your lead, {_title(slug, up)}" if up else "one of your reports" if enterprises.reports_of(slug, src)
               else "the owner")
        return (f"The enterprise's communication is {mode}: {_title(slug, src)} cannot write directly to "
                f"{_title(slug, dst)}. Go through {via}.")
    except Exception:  # noqa: BLE001 - a lookup never stops a send
        log.exception("can_send failed")
        return None


def trusted_delivery(slug: str, outside: bool) -> bool:
    """A delivery along the chain is given as a task from the lead (not as outside text) when Trust along the chain
    is on and nothing in its chain came from outside."""
    return bool(enterprises.setting(slug, "trust_chain")) and not outside
