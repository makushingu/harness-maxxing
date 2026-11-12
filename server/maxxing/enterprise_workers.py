"""Enterprise workers: temporary agents of a position, made from the worker template the owner approved.

`settings.workers` is `discreet` (Claude Code sub-agents inside the turn: nothing to do here), `visible` (this
module) or `off` (agents.run_settings forbids the sub-agent tool). A visible worker is a Protected agent (sandbox, no
key, no domain, no trigger, never more writable folders than its position's occupant) in the occupant's topic, named
`<position>-w<n>`, with the budget of the template. It is made after a policy request of the category `worker` is
allowed, at most `limits.workers_live` at a time, and goes to the Trash when its run ended and its task is done, or
after 24 h. State: `<state>/enterprises/<slug>/workers.json` `{seq, items, pending}`. See docs/dev/INTERNALS.md."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from . import agents, config, enterprises
from .enterprises import EnterpriseError

log = logging.getLogger("maxxing.enterprise_workers")

TTL_S = 24 * 3600                                   # a worker never outlives a day
KEEP = 100                                          # finished workers remembered per enterprise
PENDING_MAX = 5                                     # requests waiting for a decision, per position
RESULT_MAX = 1500                                   # characters of a worker's result handed to its position
TASK_MAX = 2000
DEFAULT_USD = 1.0                                   # a template without budget would give an unlimited agent


def _file(slug: str):
    return enterprises.state(slug) / "workers.json"


def _read(slug: str) -> dict:
    d = config.read_json(_file(slug), {})
    d = d if isinstance(d, dict) else {}
    return {"seq": d.get("seq") if isinstance(d.get("seq"), dict) else {},
            "items": [i for i in d.get("items") or [] if isinstance(i, dict)],
            "pending": [i for i in d.get("pending") or [] if isinstance(i, dict)]}


def _write(slug: str, d: dict) -> None:
    done = [i for i in d["items"] if i.get("status") not in ("live", "starting")]
    live = [i for i in d["items"] if i.get("status") in ("live", "starting")]
    d["items"] = done[-KEEP:] + live
    config.write_json(_file(slug), d)


def _live(d: dict, pos: str | None = None) -> list[dict]:
    return [i for i in d["items"] if i.get("status") in ("live", "starting") and (pos is None or i.get("position") == pos)]


def _public(i: dict) -> dict:
    return {"id": i["id"], "agent": i["agent"], "position": i["position"], "text": i.get("text", ""),
            "task": i.get("task", ""), "status": "live" if i.get("status") == "starting" else i.get("status", "live"),
            "created": i.get("created"), "expires": (i.get("created") or 0) + TTL_S, "ended": i.get("ended"),
            "session": i.get("session", ""), "result": i.get("result", "")}


def workers(slug: str, pos: str | None = None) -> list[dict]:
    """The workers of the enterprise (of one position), newest first; the finished ones stay listed a while."""
    enterprises.load(slug)
    items = _read(slug)["items"]
    return [_public(i) for i in sorted(items, key=lambda i: i.get("created") or 0, reverse=True)
            if pos is None or i.get("position") == pos]


def _sid(r: dict) -> str:
    s = r.get("session")
    return str(s.get("id") or "") if isinstance(s, dict) else str(s or "")


_WORKER_PATH = re.compile(r"/agents/[a-z0-9-]+-w\d+\Z")


def _today(t: float | None) -> bool:
    return bool(t) and time.strftime("%Y-%m-%d", time.localtime(t)) == time.strftime("%Y-%m-%d")


def seat_of_worker(path: str) -> tuple[str, str] | None:
    """(enterprise, position) of a worker agent: live, or ended today (its spending still counts today), else None."""
    if not isinstance(path, str) or not _WORKER_PATH.search(path):
        return None
    for slug in enterprises.names():
        for i in _read(slug)["items"]:
            if i.get("agent") == path and (i.get("status") in ("live", "starting") or _today(i.get("ended"))):
                return slug, str(i.get("position") or "")
    return None


def cost_today(slug: str, pos: str | None = None) -> float:
    """USD spent today by the workers of the enterprise (of one position): live ones read now, ended ones as recorded."""
    total = 0.0
    for i in _read(slug)["items"]:
        if pos is not None and i.get("position") != pos:
            continue
        if i.get("status") in ("live", "starting"):
            try:
                total += agents.day_cost(i["agent"]) if agents.exists(i["agent"]) else 0.0
            except Exception:  # noqa: BLE001 - a cost that cannot be read counts as nothing
                pass
        elif _today(i.get("ended")):
            total += float(i.get("cost") or 0)
    return total


def remap(old_prefix: str, new_prefix: str) -> None:
    """A project or topic was renamed: the workers' agent paths follow."""
    for slug in enterprises.names():
        with enterprises._lock:
            d = _read(slug)
            hit = False
            for i in d["items"]:
                a = i.get("agent")
                if isinstance(a, str) and (a == old_prefix or a.startswith(old_prefix + "/")):
                    i["agent"] = new_prefix + a[len(old_prefix):]
                    hit = True
            if hit:
                _write(slug, d)


def retire_all(slug: str, why: str = "stopped") -> int:
    """Retire every live worker of the enterprise (enterprise deleted, feature switched off) -> how many went."""
    n = 0
    for item in _live(_read(slug)):
        try:
            n += bool(_retire(slug, item, why))
        except Exception:  # noqa: BLE001 - the others go anyway
            log.exception("worker %s not retired", item.get("id"))
    return n


def _limit(slug: str, pos: str) -> int:
    try:
        return int((enterprises.setting(slug, "limits", pos) or {}).get("workers_live"))
    except (TypeError, ValueError):
        return 5


# ---- starting ------------------------------------------------------------------------------------------------
def start(slug: str, pos: str, text: str, *, task: str = "", session: str = "", outside: bool = False) -> dict:
    """An occupant asks for a worker. -> {status: started, worker} when the request was allowed at once, else
    {status: pending, request} (a lead or the owner decides; `tick` makes the worker then)."""
    if not enterprises.feature_on():
        raise EnterpriseError(404, "feature_off", "Enterprises are off (Settings -> Features, needs Agents)")
    enterprises.load(slug)
    p = enterprises.position(slug, pos)
    if not p:
        raise EnterpriseError(400, "bad_position", f"Position {pos!r} not found")
    text = " ".join(str(text or "").split())[:TASK_MAX]
    if not text:
        raise EnterpriseError(400, "invalid", "Say what the worker does")
    mode = enterprises.setting(slug, "workers", pos)
    if mode == "off":
        raise EnterpriseError(409, "workers_off", "Workers are off in this enterprise")
    if mode != "visible":
        raise EnterpriseError(409, "workers_discreet", "Workers are discreet here: use your Claude Code sub-agents")
    if not p.get("agent") or not agents.exists(p["agent"]):
        raise EnterpriseError(409, "vacant", f"The position {pos!r} has no occupant")
    if not p.get("worker_template"):
        raise EnterpriseError(409, "no_template", "The owner has not approved a worker template for this position")
    data = _read(slug)
    if len(_live(data)) >= _limit(slug, pos):
        raise EnterpriseError(409, "too_many_workers", f"At most {_limit(slug, pos)} workers at a time")
    if sum(1 for x in data["pending"] if x.get("position") == pos) >= PENDING_MAX:
        raise EnterpriseError(409, "too_many_pending", "Too many worker requests are waiting for a decision")
    from . import enterprise_policy
    req = enterprise_policy.request(slug, pos, "worker", f"Worker: {text}", session=session, outside=outside)
    ctx = {"position": pos, "text": text, "task": str(task or "")[:40], "session": session, "outside": bool(outside)}
    if req.get("status") == "allowed":
        return {"status": "started", "worker": spawn(slug, **ctx), "request": req}
    with enterprises._lock:
        data = _read(slug)
        data["pending"].append({**ctx, "request": req["id"], "at": time.time()})
        _write(slug, data)
    return {"status": "pending", "request": req}


def spawn(slug: str, position: str, text: str, task: str = "", session: str = "", outside: bool = False) -> dict:
    """Make the agent and give it its task (the request was allowed). -> the worker."""
    p = enterprises.position(slug, position)
    occ = p.get("agent") if p else None
    tpl = (p or {}).get("worker_template")
    if not p or not occ or not agents.exists(occ) or not tpl:
        raise EnterpriseError(409, "no_template", "The position has no occupant or no worker template any more")
    topic = agents.topic_of(occ)
    with enterprises._lock:
        data = _read(slug)
        if len(_live(data)) >= _limit(slug, position):
            raise EnterpriseError(409, "too_many_workers", f"At most {_limit(slug, position)} workers at a time")
        n = int(data["seq"].get(position) or 0)
        while True:
            n += 1
            name = f"{position[:40]}-w{n}"
            if not agents.exists(f"{topic}/agents/{name}"):
                break
        data["seq"][position] = n
        item = {"id": name, "agent": f"{topic}/agents/{name}", "position": position, "text": text, "task": task,
                "session": "", "created": time.time(), "status": "starting", "outside": bool(outside), "creator": session}
        data["items"].append(item)
        _write(slug, data)
    role = (tpl.get("role") or p["title"]).strip()
    o = agents.load(occ)
    try:
        agents.create(topic, name, {
            "description": f"{role}\n\nA temporary worker of {p['title']} ({position}). Its result is handed to that position.",
            "name": f"{p['title']} worker {n}", "enabled": True, "sandbox": True, "keys": [], "domains": [],
            "writable": list(o["writable"]), "triggers": [], "silent": True,
            # never wider than its creator: its rules, forbidden tools, approvals and mode follow; no mail
            "rules": list(o["rules"]), "disallowed_tools": list(o["disallowed_tools"]), "approvals": o["approvals"],
            "permission_mode": o["permission_mode"],
            "model": tpl.get("model") or "", "limits": {"usd_per_day": float(tpl.get("usd_per_day") or 0) or DEFAULT_USD}})
    except agents.AgentError as e:
        _drop(slug, name)
        raise EnterpriseError(e.status, e.code, e.message) from None
    except Exception:
        _drop(slug, name)
        raise
    with enterprises._lock:
        data = _read(slug)
        for i in data["items"]:
            if i["id"] == name:
                i["status"] = "live"
        _write(slug, data)
    enterprises.log(slug, "worker", f"Worker {name} made for {position}: {text}", by=position, position=position,
                    session=session)
    try:
        agents.post(occ, "note", f"Worker {name} started: {text[:300]}", enterprise=slug)
    except Exception:  # noqa: BLE001 - a note is a nicety
        log.exception("worker note")
    _fire(slug, item)
    enterprises.invalidate(slug)
    return _public(next(i for i in _read(slug)["items"] if i["id"] == name))


def _drop(slug: str, name: str) -> None:
    with enterprises._lock:
        data = _read(slug)
        data["items"] = [i for i in data["items"] if i["id"] != name]
        _write(slug, data)


def _fire(slug: str, item: dict) -> bool:
    """Hand the task to the worker (never under the lock) -> True when its run started."""
    head = (f"You are a temporary worker of the position {item['position']!r}. Do the task below and answer with its "
            "result only: your answer is handed to that position.")
    from . import enterprise_policy
    outside = bool(item.get("outside")) or not enterprise_policy.trusted_delivery(slug, bool(item.get("outside")))
    try:
        if outside:                           # an outside task, or no trust along the chain: data, never orders
            r = agents.fire(item["agent"], trigger=f"enterprise-worker:{slug}:{item['position']}", prompt=head,
                            text=item["text"], source=f"worker of {item['position']}", depth=0)
        else:
            r = agents.fire(item["agent"], trigger=f"enterprise-worker:{slug}:{item['position']}",
                            prompt=f"{head}\n\nTask: {item['text']}", source=f"worker of {item['position']}", depth=0)
    except Exception:  # noqa: BLE001 - tried again by the tick
        log.exception("worker %s not started", item["id"])
        return False
    if not r.get("started"):
        return False
    sid = _sid(r)
    with enterprises._lock:
        data = _read(slug)
        for i in data["items"]:
            if i["id"] == item["id"]:
                i["session"] = sid
        _write(slug, data)
    item["session"] = sid
    return True


# ---- ending --------------------------------------------------------------------------------------------------
def _result(path: str, sid: str) -> dict | None:
    """The result message of the worker's run `sid`, None while it runs (or never started)."""
    if not sid:
        return None
    try:
        return next((m for m in reversed(agents.thread(path, 200)) if m.get("kind") == "result" and m.get("session") == sid), None)
    except Exception:  # noqa: BLE001
        return None


def _task_done(task: str) -> bool:
    if not task:
        return True
    try:
        from .api import tasks
        t = tasks.get_task(task)
    except Exception:  # noqa: BLE001 - an unreadable task list never keeps a worker for a day
        return True
    return t is None or t.get("status") == "done"


def _retire(slug: str, item: dict, why: str) -> bool:
    """The worker goes to the Trash (its running session stopped first) -> False when it could not go yet."""
    path = item["agent"]
    res = _result(path, item.get("session", ""))
    try:
        spent = agents.day_cost(path) if agents.exists(path) else float(item.get("cost") or 0)
    except Exception:  # noqa: BLE001
        spent = float(item.get("cost") or 0)
    if agents.exists(path):
        try:
            from .sessions import service
            for s in agents.status(path).get("running_sessions") or []:
                if s.get("id"):
                    service.stop(s["id"])
            agents.delete(path)
        except agents.AgentError as e:
            if e.status != 404:
                log.warning("worker %s not removed yet: %s", item["id"], e.message)
                return False
        except Exception:  # noqa: BLE001
            log.exception("worker %s not removed", item["id"])
            return False
    text = str((res or {}).get("text") or "").strip()[:RESULT_MAX]
    with enterprises._lock:
        data = _read(slug)
        for i in data["items"]:
            if i["id"] == item["id"]:
                i.update(status=why, ended=time.time(), result=text, cost=round(spent, 4))
        _write(slug, data)
    enterprises.log(slug, "worker", f"Worker {item['id']} {why}", by="server", position=item["position"])
    if why != "stopped" and enterprises.position(slug, item["position"]):
        try:
            from . import enterprise_flow
            enterprise_flow.deliver(slug, item["position"], "handin",
                                    f"Worker {item['id']} {'finished' if why == 'done' else 'was removed after 24 h'}: "
                                    f"{text or 'no result'}", task=item.get("task", ""), outside=bool(item.get("outside")))
        except Exception:  # noqa: BLE001 - the worker is gone either way
            log.exception("worker result not delivered")
    enterprises.invalidate(slug)
    return True


def stop(slug: str, wid: str) -> dict:
    """The owner stops a live worker (it goes to the Trash). -> the worker."""
    enterprises.load(slug)
    item = next((i for i in _read(slug)["items"] if i["id"] == wid), None)
    if item is None:
        raise EnterpriseError(404, "not_found", f"Worker {wid!r} not found")
    if item.get("status") not in ("live", "starting"):
        raise EnterpriseError(409, "not_live", "This worker is already gone")
    if not _retire(slug, item, "stopped"):
        raise EnterpriseError(409, "busy", "The worker could not be removed now: try again")
    return _public(next(i for i in _read(slug)["items"] if i["id"] == wid))



# ---- tick ----------------------------------------------------------------------------------------------------
def tick(now: float | None = None) -> None:
    now = time.time() if now is None else float(now)
    on = enterprises.feature_on()
    for slug in enterprises.names():
        try:
            if not _file(slug).exists():
                continue
            if on:
                _tick_one(slug, now)
            else:                                           # switched off: only the retirement goes on
                retire_all(slug)
        except Exception:  # noqa: BLE001 - one enterprise never stops the others
            log.exception("workers of %s", slug)


def _tick_one(slug: str, now: float) -> None:
    if enterprises.load(slug).get("broken"):
        return
    data = _read(slug)
    if data["pending"]:
        _pending(slug, data)
        data = _read(slug)
    for item in _live(data):
        if item.get("status") == "starting" and now - float(item.get("created") or 0) > 300:
            _drop(slug, item["id"])                         # a crash between the record and the agent
            continue
        path = item["agent"]
        if not agents.exists(path):
            with enterprises._lock:
                d = _read(slug)
                for i in d["items"]:
                    if i["id"] == item["id"]:
                        i.update(status="stopped", ended=now)
                _write(slug, d)
            continue
        if now - float(item.get("created") or 0) >= TTL_S:
            _retire(slug, item, "expired")
        elif not item.get("session"):
            _fire(slug, item)                               # the first try was refused (budget, busy): again
        elif _result(path, item["session"]) is not None and _task_done(item.get("task", "")):
            _retire(slug, item, "done")


def _pending(slug: str, data: dict) -> None:
    from . import enterprise_policy
    status = {r["id"]: r for r in enterprise_policy.requests(slug)}
    keep, go = [], []
    for w in data["pending"]:
        st = (status.get(w.get("request")) or {}).get("status")
        if st == "allowed":
            go.append(w)
        elif st == "pending":
            keep.append(w)                                  # denied, expired or forgotten: dropped
    with enterprises._lock:
        d = _read(slug)
        d["pending"] = keep
        _write(slug, d)
    for w in go:
        try:
            spawn(slug, w["position"], w.get("text", ""), w.get("task", ""), w.get("session", ""), bool(w.get("outside")))
        except EnterpriseError as e:
            enterprises.log(slug, "worker", f"Worker for {w['position']} not made: {e.message}", by="server",
                            position=w["position"])
