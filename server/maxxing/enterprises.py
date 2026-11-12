"""Enterprises: an org chart of agents above projects. See docs/dev/API.md#enterprises and INTERNALS.md.

Workspace `<workspace>/enterprises/<slug>/{CLAUDE.md, enterprise.json, profile.json, files/}`, state
`<state>/enterprises/<slug>/{decisions.jsonl, inbox/<pos>.jsonl, ...}`. Every write of enterprise.json is a
read-modify-write under `_lock` that bumps `rev`. Lock order: this lock, then the agents lock, never the reverse;
`agents.fire` is never called while holding it. The lookups (`seat_of`, `position`, ...) read a cache keyed on the
files' stats and never raise; they do not look at the feature switches (the hooks must keep the chart consistent
while the feature is off): callers gate with `feature_on()`."""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from . import agents, config

logger = logging.getLogger("maxxing.enterprises")

_lock = config.ProcessLock("enterprises")

FILE = "enterprise.json"
PROFILE_FILE = "profile.json"
SLUG_RE = agents.SLUG_RE
RESERVED = ("templates", "import", "esc")           # names of routes next to /{e}; `esc` is the escalation card prefix
RESERVED_POS = ("owner", "server", "policy", "visitor", "free", "esc", "none")   # words written in `by`: never a position id
DEPT_SETTINGS = ("communication", "allow", "workers", "autonomy", "escalation_timeout_h", "spending_threshold")
MAX_ENTERPRISES = 20
MAX_POSITIONS = 200
DEPTH_MAX = 6
REPORTS_MAX = 12
NAME_MAX, TITLE_MAX, JOB_MAX, NOTES_MAX, TEXT_MAX = 80, 120, 2000, 2000, 600
DECISIONS_KEEP = 5000
SAVED_STATE = ".state"                              # <trashed enterprise folder>/.state: its state folder
SAVED_LINKS = ".enterprise-links.json"              # <trashed project / topic folder>: what the chart held of it
TOPIC_RE = re.compile(r"^projects/([a-z0-9][a-z0-9-]{0,47})/topics/([a-z0-9][a-z0-9-]{0,47})\Z")


class EnterpriseError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def feature_on() -> bool:
    return agents.feature_on() and bool(config.load_config().get("enterprises_page", False))


# ---- paths ---------------------------------------------------------------------------------------------
def _root() -> Path:
    return config.workspace() / "enterprises"


def folder(slug: str) -> Path:
    return _root() / slug


def state(slug: str) -> Path:
    return config.state_dir("enterprises", slug)


def _peek(slug: str) -> Path:
    """The state folder without creating it."""
    return config.state_dir("enterprises") / slug


def _slug_ok(v: Any) -> bool:
    return isinstance(v, str) and bool(SLUG_RE.match(v))


# ---- cleaning ------------------------------------------------------------------------------------------
def _text(v: Any, n: int) -> str:
    return agents._utf8(str(v if v is not None else "")).strip()[:n]


def _int(v: Any, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        raise ValueError("number expected")
    if not lo <= v <= hi:
        raise ValueError("out of range")
    return int(v)


def _usd(v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not 0 <= v <= 100000:
        raise ValueError("amount expected")
    return round(float(v), 2)


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise ValueError("boolean expected")
    return v


def _enum(*vals: str) -> Callable[[Any], str]:
    def check(v: Any) -> str:
        if v not in vals:
            raise ValueError("one of " + ", ".join(vals))
        return v
    return check


def _slugs(v: Any, limit: int = 200) -> list[str]:
    if not isinstance(v, list) or len(v) > limit or not all(_slug_ok(x) for x in v):
        raise ValueError("list of ids expected")
    return list(dict.fromkeys(v))


def _pairs(v: Any) -> list[list[str]]:
    if not isinstance(v, list) or len(v) > 200:
        raise ValueError("list of pairs expected")
    out = []
    for p in v:
        if not (isinstance(p, (list, tuple)) and len(p) == 2 and all(_slug_ok(x) for x in p)):
            raise ValueError("pair of ids expected")
        out.append([p[0], p[1]])
    return out


def _group(spec: dict[str, Callable[[Any], Any]], default: dict) -> Callable[[Any], dict]:
    """A nested settings object: every key checked, the missing ones at their default."""
    def check(v: Any) -> dict:
        if not isinstance(v, dict):
            raise ValueError("object expected")
        out = copy.deepcopy(default)
        for k, f in spec.items():
            if k in v:
                out[k] = f(v[k])
        for k, x in v.items():
            if k not in spec:
                out[k] = x
        return out
    return check


def _token(v: Any) -> str:
    """The public chat link's token: empty or 20-64 URL-safe characters (the server makes it)."""
    if v == "" or (isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{20,64}", v)):
        return v
    raise ValueError("token")


DEFAULT_SETTINGS: dict[str, Any] = {
    "communication": "leads", "allow": [], "workers": "discreet", "autonomy": "balanced", "trust_chain": False,
    "escalation_timeout_h": 4,
    "digest": {"enabled": False, "hour": 8, "per_lead": False, "titles_only": False},
    "weekly": False, "monthly": False,
    "desk": {"enabled": False, "label": "", "retention_days": 30,
             "public": {"enabled": False, "token": "", "rate_per_hour": 20, "max_chars": 1000}},
    "limits": {"depth": 4, "reports": 8, "workers_live": 5, "hops_per_task": 6},
}
_CHECKS: dict[str, Callable[[Any], Any]] = {
    "communication": _enum("strict", "leads", "open"), "allow": _pairs, "workers": _enum("discreet", "visible", "off"),
    "autonomy": _enum("careful", "balanced", "autonomous"), "trust_chain": _bool,
    "escalation_timeout_h": lambda v: _int(v, 1, 72),
    "digest": _group({"enabled": _bool, "hour": lambda v: _int(v, 0, 23), "per_lead": _bool, "titles_only": _bool},
                     DEFAULT_SETTINGS["digest"]),
    "weekly": _bool, "monthly": _bool,
    "desk": _group({"enabled": _bool, "label": lambda v: _text(v, 60), "retention_days": lambda v: _int(v, 1, 365),
                    "public": _group({"enabled": _bool, "token": _token, "rate_per_hour": lambda v: _int(v, 1, 600),
                                      "max_chars": lambda v: _int(v, 50, 4000)},
                                     DEFAULT_SETTINGS["desk"]["public"])}, DEFAULT_SETTINGS["desk"]),
    "limits": _group({"depth": lambda v: _int(v, 1, DEPTH_MAX), "reports": lambda v: _int(v, 1, REPORTS_MAX),
                      "workers_live": lambda v: _int(v, 0, 50), "hops_per_task": lambda v: _int(v, 1, 20)},
                     DEFAULT_SETTINGS["limits"]),
}


def _settings(src: Any, strict: bool = False, partial: bool = False) -> dict:
    """The settings with defaults (partial: only the keys given, a department's overrides). strict: a bad value is a
    400 `invalid`, else it falls back to its default. Unknown keys are kept."""
    s = src if isinstance(src, dict) else {}
    out: dict[str, Any] = {}
    for k, check in _CHECKS.items():
        if k in s:
            try:
                out[k] = check(s[k])
                continue
            except (ValueError, TypeError):
                if strict:
                    raise EnterpriseError(400, "invalid", f"Invalid value for the setting {k!r}") from None
        if not partial:
            out[k] = copy.deepcopy(DEFAULT_SETTINGS[k])
    for k, v in s.items():
        if k not in _CHECKS:
            out[k] = v
    return out


def _merge(base: dict, patch: dict) -> dict:
    """patch over base, nested objects merged all the way down (desk.public.enabled keeps the token)."""
    out = copy.deepcopy(base)
    for k, v in patch.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _names(v: Any) -> list[str] | None:
    if v is None:
        return None
    if not isinstance(v, list) or len(v) > 100 or not all(isinstance(x, str) and 0 < len(x) <= 120 for x in v):
        raise ValueError("list of names or null expected")
    return list(dict.fromkeys(v))


def _envelope(src: Any, strict: bool = False) -> dict:
    """{usd_per_day (0 = no ceiling), keys (null = no limit), domains (null = no limit)}."""
    s = src if isinstance(src, dict) else {}
    out: dict[str, Any] = {"usd_per_day": 0, "keys": None, "domains": None}
    for k, f in (("usd_per_day", _usd), ("keys", _names), ("domains", _names)):
        if k in s:
            try:
                out[k] = f(s[k])
            except (ValueError, TypeError):
                if strict:
                    raise EnterpriseError(400, "invalid", f"Invalid envelope value for {k!r}") from None
    for k, v in s.items():
        if k not in out:
            out[k] = v
    return out


def _departments(src: Any, strict: bool = False) -> dict:
    if not isinstance(src, dict) or len(src) > 50:
        if strict:
            raise EnterpriseError(400, "invalid", "departments: an object of at most 50 departments")
        return {}
    out = {}
    for did, v in src.items():
        if not _slug_ok(did):
            if strict:
                raise EnterpriseError(400, "invalid", f"Invalid department id {did!r}")
            continue
        v = v if isinstance(v, dict) else {}
        over = v.get("settings") if isinstance(v.get("settings"), dict) else {}
        bad = [k for k in over if k not in DEPT_SETTINGS]
        if bad and strict:
            raise EnterpriseError(400, "invalid", f"A department overrides only: {', '.join(DEPT_SETTINGS)} (not {', '.join(bad)})")
        d = {"name": _text(v.get("name"), NAME_MAX) or did, "envelope": _envelope(v.get("envelope"), strict),
             "settings": _settings({k: x for k, x in over.items() if k in DEPT_SETTINGS}, strict, partial=True),
             "notes": _text(v.get("notes"), NOTES_MAX)}
        for k, x in v.items():
            if k not in d:
                d[k] = x
        out[did] = d
    return out


def _num_or_none(v: Any) -> float | None:
    return None if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v else v


def _objectives(src: Any) -> list[dict]:
    out = []
    for o in (src if isinstance(src, list) else [])[:200]:
        if not isinstance(o, dict) or not _text(o.get("id"), 48):
            continue
        d = {"id": _text(o["id"], 48), "text": _text(o.get("text"), 300), "target": _num_or_none(o.get("target")),
             "unit": _text(o.get("unit"), 20), "value": _num_or_none(o.get("value")),
             "owner": _text(o.get("owner"), 48), "parent": _text(o.get("parent"), 48)}
        out.append({**{k: v for k, v in o.items() if k not in d}, **d})
    return out


def _grants(src: Any) -> list[dict]:
    out = []
    for g in (src if isinstance(src, list) else [])[:200]:
        if not isinstance(g, dict) or not _text(g.get("id"), 48):
            continue
        d = {"id": _text(g["id"], 48), "position": _text(g.get("position"), 48), "category": _text(g.get("category"), 40),
             "ceiling": _num_or_none(g.get("ceiling")), "until": g.get("until") if isinstance(g.get("until"), (int, float, str)) else None}
        out.append({**{k: v for k, v in g.items() if k not in d}, **d})
    return out


GRANT_DAYS = 30


def _check_grants(d: dict, src: Any) -> list[dict]:
    """The grants as written by the owner. A new or changed one is checked like `maxxing enterprise grant`: the position
    exists, the category is known, `until` is in the future and within 30 days, the ceiling is a number (400 invalid)."""
    from . import enterprise_policy
    if not isinstance(src, list):
        raise EnterpriseError(400, "invalid", "grants: a list")
    out = _grants(src)
    if len(out) != len(src):
        raise EnterpriseError(400, "invalid", "grants: each needs an id")
    old = {g["id"]: g for g in d["grants"]}
    now = time.time()
    for g, raw in zip(out, src):
        if old.get(g["id"]) == g:
            continue                                    # untouched (maybe ended: the tick drops it)
        if not any(p["id"] == g["position"] for p in d["positions"]):
            raise EnterpriseError(400, "bad_position", f"Grant {g['id']}: the position {g['position']!r} does not exist")
        if g["category"] not in enterprise_policy.CATEGORIES:
            raise EnterpriseError(400, "invalid", f"Grant {g['id']}: unknown category {g['category']!r}")
        end = enterprise_policy._until(g.get("until"))
        if end is None or end <= now or end > now + GRANT_DAYS * 86400 + 3600:
            raise EnterpriseError(400, "invalid", f"Grant {g['id']}: `until` must be within {GRANT_DAYS} days from now")
        if raw.get("ceiling") is not None and g["ceiling"] is None:
            raise EnterpriseError(400, "invalid", f"Grant {g['id']}: the ceiling is a number")
    return out


def _worker(v: Any) -> dict | None:
    if not isinstance(v, dict):
        return None
    out = {"role": _text(v.get("role"), JOB_MAX), "model": _text(v.get("model"), 80)}
    try:
        out["usd_per_day"] = _usd(v.get("usd_per_day", 0))
    except ValueError:
        out["usd_per_day"] = 0
    return out


def _position(p: Any) -> dict | None:
    if not isinstance(p, dict) or not _slug_ok(p.get("id")) or p["id"] in RESERVED_POS:
        return None
    rt = p.get("reports_to")
    dept = p.get("department")
    out: dict[str, Any] = {
        "id": p["id"], "title": _text(p.get("title"), TITLE_MAX) or p["id"], "reports_to": rt if _slug_ok(rt) else None,
        "department": dept if _slug_ok(dept) else "",
        "agent": p["agent"].strip("/") if isinstance(p.get("agent"), str) and p["agent"].strip("/") else None,
        "job": _text(p.get("job"), JOB_MAX), "desk": p.get("desk") is True}
    w = _worker(p.get("worker_template"))
    if w:
        out["worker_template"] = w
    for k, v in p.items():
        if k not in out and k != "worker_template":
            out[k] = v
    return out


def clean(data: Any) -> dict:
    """enterprise.json with defaults for every field; unknown keys of a newer version are kept."""
    d = data if isinstance(data, dict) else {}
    positions: list[dict] = []
    seen: set[str] = set()
    for raw in (d.get("positions") if isinstance(d.get("positions"), list) else [])[:MAX_POSITIONS]:
        p = _position(raw)
        if p and p["id"] not in seen:
            seen.add(p["id"])
            positions.append(p)
    for p in positions:
        if p["reports_to"] not in seen or p["reports_to"] == p["id"]:
            p["reports_to"] = None
    roots = {p["id"] for p in positions if p["reports_to"] is None}
    top = d.get("top")
    try:
        rev = max(0, int(d.get("rev") or 0))
    except (TypeError, ValueError):
        rev = 0
    projects = d.get("projects")
    out = {"version": 1, "rev": rev, "name": _text(d.get("name"), NAME_MAX), "emoji": _text(d.get("emoji"), 8),
           "projects": [x for x in dict.fromkeys(projects) if _slug_ok(x)][:100] if isinstance(projects, list) else [],
           "top": top if isinstance(top, str) and top in roots else "owner", "settings": _settings(d.get("settings")),
           "envelope": _envelope(d.get("envelope")), "departments": _departments(d.get("departments")),
           "positions": positions, "objectives": _objectives(d.get("objectives")), "grants": _grants(d.get("grants"))}
    for k, v in d.items():
        if k not in out:
            out[k] = v
    return out


# ---- reading -------------------------------------------------------------------------------------------
def _read(slug: str) -> tuple[dict, str]:
    """(cleaned data, "ok" | "broken" | "missing"); a file that cannot be read is `broken` (never written over)."""
    f = folder(slug) / FILE
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return clean({}), "missing"
    except (OSError, ValueError):
        return {**clean({}), "broken": True}, "broken"
    if not isinstance(raw, dict):
        return {**clean({}), "broken": True}, "broken"
    return clean(raw), "ok"


def load(slug: str) -> dict:
    """The enterprise's file, cleaned; `broken: True` when it cannot be read. 404 when there is none."""
    if not _slug_ok(slug):
        raise EnterpriseError(404, "not_found", f"Enterprise {slug!r} not found")
    d, kind = _read(slug)
    if kind == "missing":
        raise EnterpriseError(404, "not_found", f"Enterprise {slug!r} not found")
    return d


def names() -> list[str]:
    try:
        return sorted(e.name for e in os.scandir(_root()) if e.is_dir() and SLUG_RE.match(e.name)
                      and (Path(e.path) / FILE).exists())
    except OSError:
        return []


def _load_ok(slug: str) -> dict:
    d = load(slug)
    if d.get("broken"):
        raise EnterpriseError(409, "broken", "enterprise.json cannot be read: fix the file first (it is not overwritten)")
    return d


# ---- lookups: cached on the files' stats, never raise ----------------------------------------------------
_idx: dict[str, Any] = {"sig": None, "data": None}


def _signature() -> tuple:
    root = _root()
    sig: list = []
    for n in names():
        try:
            st = os.stat(root / n / FILE)
            sig.append((n, st.st_ino, st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    return (str(root), tuple(sig))


def _index() -> dict:
    """{"by": {slug: data}, "seats": {agent path: (slug, pos)}, "projects": {project: slug}} of the readable enterprises."""
    try:
        sig = _signature()
        if _idx["sig"] == sig and _idx["data"] is not None:
            return _idx["data"]
        by, seats, projects = {}, {}, {}
        for n in sorted(x[0] for x in sig[1]):
            d, kind = _read(n)
            if kind != "ok":
                continue
            by[n] = d
            for p in d["positions"]:
                if p["agent"]:
                    seats.setdefault(p["agent"], (n, p["id"]))
            for pr in d["projects"]:
                projects.setdefault(pr, n)
        data = {"by": by, "seats": seats, "projects": projects}
        _idx.update(sig=sig, data=data)
        return data
    except Exception:  # noqa: BLE001 - a lookup never raises
        logger.exception("enterprise index failed")
        return {"by": {}, "seats": {}, "projects": {}}


def seat_of(agent_path: str) -> tuple[str, str] | None:
    return _index()["seats"].get(agent_path)


def enterprise_of_project(project: str) -> str | None:
    return _index()["projects"].get(project)


def position(slug: str, pos: str) -> dict | None:
    d = _index()["by"].get(slug)
    p = next((p for p in d["positions"] if p["id"] == pos), None) if d else None
    return copy.deepcopy(p) if p else None


def lead_of(slug: str, pos: str) -> str | None:
    p = position(slug, pos)
    return p["reports_to"] if p else None


def reports_of(slug: str, pos: str) -> list[str]:
    d = _index()["by"].get(slug)
    return [p["id"] for p in d["positions"] if p["reports_to"] == pos] if d else []


def subtree(slug: str, pos: str) -> list[str]:
    """Every position under `pos` (not `pos` itself), nearest first."""
    out: list[str] = []
    todo = reports_of(slug, pos)
    while todo and len(out) <= MAX_POSITIONS:
        p = todo.pop(0)
        if p not in out and p != pos:
            out.append(p)
            todo += reports_of(slug, p)
    return out


def ancestors(slug: str, pos: str) -> list[str]:
    """The leads above `pos`, nearest first."""
    out: list[str] = []
    cur = lead_of(slug, pos)
    while cur and cur not in out and cur != pos and len(out) <= MAX_POSITIONS:
        out.append(cur)
        cur = lead_of(slug, cur)
    return out


def department_of(slug: str, pos: str) -> str:
    p = position(slug, pos)
    return p["department"] if p else ""


def setting(slug: str, name: str, pos: str | None = None) -> Any:
    """An enterprise setting, with the override of the position's department when it has one."""
    d = _index()["by"].get(slug)
    if not d:
        return None
    if pos:
        dept = department_of(slug, pos)
        over = (d["departments"].get(dept) or {}).get("settings") or {}
        if name in over:
            return copy.deepcopy(over[name])
    return copy.deepcopy(d["settings"].get(name))


# ---- bus, decision log -----------------------------------------------------------------------------------
def invalidate(slug: str | None = None) -> None:
    from . import bus
    bus.invalidate("enterprises", *([f"enterprises:{slug}"] if slug else []))


_last_at = 0.0


def log(slug: str, kind: str, text: str, *, by: str = "owner", position: str = "", task: str = "",
        session: str = "", **extra: Any) -> None:
    """One line of the decision log (text capped at 600). Never raises."""
    try:
        global _last_at
        with _lock:
            _last_at = max(round(time.time(), 6), round(_last_at + 0.000001, 6))   # unique: the paging key
        line = {"at": _last_at, "kind": str(kind)[:40], "by": str(by)[:200], "position": str(position)[:48],
                "text": _text(text, TEXT_MAX), "task": str(task)[:40], "session": str(session)[:64], **extra}
        f = state(slug) / "decisions.jsonl"
        with _lock:
            fd = os.open(f, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
            if f.stat().st_size > 2_000_000:
                _trim(f)
    except Exception:  # noqa: BLE001
        logger.exception("decision not logged (%s)", slug)


def _trim(f: Path) -> None:
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[-DECISIONS_KEEP:]
    tmp = f.with_suffix(".tmp")
    tmp.write_text("".join(x + "\n" for x in lines), encoding="utf-8")
    tmp.replace(f)


def decisions(slug: str, before: float | None = None, limit: int = 50) -> tuple[list[dict], float | None]:
    """The log, newest first: (items, next) - `next` is the `before` of the next page, None at the end."""
    limit = max(1, min(200, int(limit or 50)))
    try:
        lines = (_peek(slug) / "decisions.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return [], None
    items: list[dict] = []
    for ln in reversed(lines):
        try:
            m = json.loads(ln)
        except ValueError:
            continue
        if isinstance(m, dict) and (before is None or float(m.get("at") or 0) < before):
            items.append(m)
            if len(items) > limit:
                break
    more = len(items) > limit
    items = items[:limit]
    return items, (float(items[-1].get("at") or 0) if more and items else None)


# ---- the chart's checks ----------------------------------------------------------------------------------
def _check_tree(d: dict) -> None:
    """Cycles, depth and reports per lead of the whole tree (400 cycle / too_deep / too_many_reports)."""
    pos = {p["id"]: p for p in d["positions"]}
    lim = d["settings"]["limits"]
    kids: dict[str, int] = {}
    for p in d["positions"]:
        rt = p["reports_to"]
        if rt is not None and rt not in pos:
            raise EnterpriseError(400, "bad_position", f"{p['id']!r} reports to {rt!r}, which does not exist")
        if rt is not None:
            kids[rt] = kids.get(rt, 0) + 1
    for p in d["positions"]:
        depth, cur, seen = 1, p, {p["id"]}
        while cur["reports_to"] is not None:
            cur = pos[cur["reports_to"]]
            if cur["id"] in seen:
                raise EnterpriseError(400, "cycle", f"{p['id']!r} would end up above itself")
            seen.add(cur["id"])
            depth += 1
        if depth > lim["depth"]:
            raise EnterpriseError(400, "too_deep", f"The chart is at most {lim['depth']} levels deep")
    for lead, n in kids.items():
        if n > lim["reports"]:
            raise EnterpriseError(400, "too_many_reports", f"{lead!r} has more than {lim['reports']} reports")


def _check_agent(d: dict, slug: str, path: Any, pos: str) -> str:
    ap = agents.parse(path) if isinstance(path, str) else None
    if not ap or ap[0] not in d["projects"] or not agents.exists(path):
        raise EnterpriseError(400, "bad_agent", f"{path!r} is not an agent of a project of this enterprise")
    seat = seat_of(path)
    if seat and seat != (slug, pos):
        raise EnterpriseError(409, "agent_seated", f"{path!r} already holds the position {seat[1]!r} ({seat[0]})")
    return path


def _apply(slug: str, fn: Callable[[dict], Any], note: Callable[[dict, Any], str] | None = None) -> tuple[dict, Any]:
    """Read-modify-write of enterprise.json under the lock: fn(d) edits the cleaned data, the tree is checked, `rev`
    goes up. -> (data written, what fn returned)."""
    with _lock:
        d = _load_ok(slug)
        res = fn(d)
        _check_tree(d)
        d["rev"] = int(d.get("rev") or 0) + 1
        config.write_json(folder(slug) / FILE, d)
        if note:
            log(slug, "structure", note(d, res))
    invalidate(slug)
    return d, res


# ---- create / update / delete ----------------------------------------------------------------------------
def list_templates() -> list[dict]:
    from . import enterprise_templates
    return enterprise_templates.listing()


def _check_projects(projects: Any, slug: str) -> list[str]:
    if not isinstance(projects, list) or not all(_slug_ok(p) for p in projects):
        raise EnterpriseError(400, "bad_project", "projects: a list of project names")
    projects = list(dict.fromkeys(projects))
    for p in projects:
        if not (config.workspace() / "projects" / p).is_dir():
            raise EnterpriseError(400, "bad_project", f"Project {p!r} not found")
        other = enterprise_of_project(p)
        if other and other != slug:
            raise EnterpriseError(409, "project_linked", f"Project {p!r} belongs to the enterprise {other!r}")
    return projects


def create(slug: str, fields: dict | None = None) -> dict:
    f = dict(fields or {})
    if not _slug_ok(slug) or slug in RESERVED:
        raise EnterpriseError(400, "invalid_name",
                              "Use 1-48 lowercase letters, digits or dashes (starting with a letter or digit)")
    tpl = None
    if f.get("template"):
        from . import enterprise_templates
        tpl = enterprise_templates.get(str(f["template"]))
        if not tpl:
            raise EnterpriseError(400, "bad_template", f"Unknown template {f['template']!r}")
    name = _text(f.get("name"), NAME_MAX) or (tpl["name"] if tpl else slug)
    with _lock:
        if folder(slug).exists():
            raise EnterpriseError(409, "exists", f"Enterprise {slug!r} already exists")
        if len(names()) >= MAX_ENTERPRISES:
            raise EnterpriseError(400, "too_many", f"At most {MAX_ENTERPRISES} enterprises")
        projects = _check_projects(f.get("projects") or [], slug)
        data = clean({"name": name, "emoji": f.get("emoji") or "", "projects": projects, "rev": 1,
                      **({k: tpl[k] for k in ("positions", "departments", "settings")} if tpl else {})})
        try:
            folder(slug).mkdir(parents=True)
        except FileExistsError:
            raise EnterpriseError(409, "exists", f"Enterprise {slug!r} already exists") from None
        try:
            mission = f"{tpl['mission']}\n\n" if tpl else ""    # a template's positions stay vacant
            (folder(slug) / "CLAUDE.md").write_text(f"# Enterprise {name}\n\n{mission}", encoding="utf-8")
            (folder(slug) / "files").mkdir(exist_ok=True)
            shutil.rmtree(_peek(slug), ignore_errors=True)  # left by an older enterprise of that name
            config.write_json(folder(slug) / FILE, data)
        except BaseException:                           # a half-made folder would keep the name taken
            shutil.rmtree(folder(slug), ignore_errors=True)
            raise
        log(slug, "structure", f"Enterprise created ({', '.join(projects) or 'no project'})")
    invalidate(slug)
    return get(slug)


_UPDATABLE = ("name", "emoji", "top", "settings", "envelope", "departments", "objectives", "grants")


def update(slug: str, fields: dict) -> dict:
    f = {k: v for k, v in (fields or {}).items() if k in _UPDATABLE}
    grants_log: list[str] = []

    def edit(d: dict) -> list[str]:
        grants_log.clear()
        if "name" in f:
            name = _text(f["name"], NAME_MAX)
            if not name:
                raise EnterpriseError(400, "invalid", "The name cannot be empty")
            d["name"] = name
        if "emoji" in f:
            d["emoji"] = _text(f["emoji"], 8)
        if "settings" in f:
            if not isinstance(f["settings"], dict):
                raise EnterpriseError(400, "invalid", "settings: an object")
            was_live = bool(d["settings"]["desk"].get("enabled"))
            d["settings"] = _settings(_merge(d["settings"], f["settings"]), strict=True)
            if d["settings"]["desk"]["enabled"] and not was_live:      # the front desk goes live: every occupant protected
                from . import enterprise_desk
                enterprise_desk.check_live(slug, d)
        if "envelope" in f:
            if not isinstance(f["envelope"], dict):
                raise EnterpriseError(400, "invalid", "envelope: an object")
            d["envelope"] = _envelope({**d["envelope"], **f["envelope"]}, strict=True)
        if "departments" in f:
            d["departments"] = _departments(f["departments"], strict=True)
        if "objectives" in f:
            d["objectives"] = _objectives(f["objectives"])
        if "grants" in f:
            old = {g["id"]: g for g in d["grants"]}
            d["grants"] = _check_grants(d, f["grants"])
            new = {g["id"]: g for g in d["grants"]}
            for gid, g in new.items():
                if old.get(gid) != g:
                    grants_log.append(f"Grant {gid} made: {g['category']} for {g['position']}")
            for gid, g in old.items():
                if gid not in new:
                    grants_log.append(f"Grant {gid} revoked: {g['category']} for {g['position']}")
        if "top" in f:
            roots = {p["id"] for p in d["positions"] if p["reports_to"] is None}
            if f["top"] != "owner" and f["top"] not in roots:
                raise EnterpriseError(400, "bad_position", "top: \"owner\" or a position that reports to nobody")
            d["top"] = f["top"]
        return sorted(f)

    _apply(slug, edit, lambda d, keys: "Updated " + ", ".join(keys))
    for line in grants_log:
        log(slug, "grant", line)
    return get(slug)


def objectives_progress(slug: str) -> list[dict]:
    """The objectives with `progress` (percent of the target, None without a target or a value)."""
    return [{**o, "progress": round(100 * o["value"] / o["target"]) if o.get("target") and o.get("value") is not None
             else None} for o in load(slug)["objectives"]]


def delete(slug: str) -> None:
    """The folder goes to the Trash with the enterprise's state (put back by `restored`); agents, topics and
    sessions are untouched."""
    from . import workspace
    if _slug_ok(slug) and (folder(slug) / FILE).exists():
        try:                                         # live workers do not outlive their enterprise (outside the lock)
            from . import enterprise_workers
            enterprise_workers.retire_all(slug)
        except Exception:  # noqa: BLE001 - the delete goes on; a worker left behind is an ordinary agent
            logger.exception("workers of %s not retired", slug)
    with _lock:
        if not _slug_ok(slug) or not (folder(slug) / FILE).exists():
            raise EnterpriseError(404, "not_found", f"Enterprise {slug!r} not found")
        dest = workspace.move_to_trash(folder(slug), label=f"enterprise-{slug}")
        st = _peek(slug)
        if st.is_dir():
            try:
                shutil.move(str(st), str(dest / SAVED_STATE))
            except OSError:
                logger.exception("state of %s not saved in the Trash", slug)
    try:                                             # its Telegram thread goes too (re-created on the next message)
        from .telegram import gateway
        gateway.drop_enterprise_thread(slug, delete=True)
    except Exception:  # noqa: BLE001 - Telegram is optional; the enterprise is already in the Trash
        logger.exception("Telegram thread of %s not dropped", slug)
    invalidate(slug)
    invalidate()


def list_all() -> list[dict]:
    out = []
    for n in names():
        d, kind = _read(n)
        pos = d["positions"]
        out.append({"id": n, "name": d["name"] or n, "emoji": d["emoji"], "projects": d["projects"],
                    "positions": len(pos), "vacant": sum(1 for p in pos if not p["agent"]), "top": d["top"],
                    "broken": kind == "broken"})
    return out


# ---- the chart with every position's state -----------------------------------------------------------------
def _inbox_count(slug: str, pos: str) -> int:
    try:
        with open(_peek(slug) / "inbox" / f"{pos}.jsonl", encoding="utf-8", errors="replace") as fh:
            return sum(1 for ln in fh if ln.strip())
    except OSError:
        return 0


def inbox(slug: str, pos: str) -> list[dict]:
    """The deliveries waiting for a position, oldest first (empty when there is none)."""
    d = load(slug)
    if not any(p["id"] == pos for p in d["positions"]):
        raise EnterpriseError(404, "not_found", f"Position {pos!r} not found")
    items: list[dict] = []
    try:
        with open(_peek(slug) / "inbox" / f"{pos}.jsonl", encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                try:
                    m = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(m, dict):
                    items.append({"id": str(m.get("id") or ""), "kind": str(m.get("kind") or ""),
                                  "from": str(m.get("from") or ""), "text": str(m.get("text") or ""),
                                  "task": str(m.get("task") or ""), "at": m.get("at") or 0,
                                  "outside": bool(m.get("outside"))})
    except OSError:
        pass
    return items


def _open_tasks(slug: str) -> dict[str, int]:
    """position -> its open tasks (tasks.json: `enterprise.id == slug`, `enterprise.owner == pos`, not done)."""
    out: dict[str, int] = {}
    try:
        from .api import tasks as tasks_api
        data = tasks_api.load(copy_=False)
    except Exception:  # noqa: BLE001 - no tasks file, a damaged one, no module: no count
        return out
    for t in data.get("tasks") or []:
        e = t.get("enterprise") if isinstance(t, dict) else None
        if isinstance(e, dict) and e.get("id") == slug and t.get("status") != "done" and e.get("owner"):
            out[e["owner"]] = out.get(e["owner"], 0) + 1
    return out


BLOCKING = ("budget", "envelope", "disabled")        # why of a flow wait that stops the occupant: the box is Blocked


def _waits(slug: str) -> dict:
    """position -> {since, why} of the deliveries that wait (the flow's file; {} when none)."""
    try:
        w = json.loads((_peek(slug) / "flow.json").read_text(encoding="utf-8")).get("waits")
    except (OSError, ValueError, AttributeError):
        return {}
    return w if isinstance(w, dict) else {}


def _state_of(agent: dict | None, st: dict, wait: dict | None = None) -> str:
    if agent is None:
        return "vacant"
    if (st.get("waiting") or 0) > 0:
        return "waiting"
    if isinstance(wait, dict) and wait.get("why") in BLOCKING:
        return "blocked"
    if (st.get("running_now") or 0) > 0:
        return "working"
    if (st.get("thread_unread") or 0) > 0:
        return "unread"
    if not agent["enabled"]:
        return "off"
    last = st.get("last_run")
    if isinstance(last, dict) and last.get("kind") == "result" and last.get("ok") is False:
        return "failed"
    return "idle"


def get(slug: str, with_state: bool = True) -> dict:
    d = load(slug)
    out = {**d, "id": slug, "name": d["name"] or slug, "broken": bool(d.get("broken"))}
    out["cost_today"], out["ceiling_hit"] = 0.0, False
    if d.get("broken"):
        return out
    positions = [dict(p) for p in d["positions"]]
    if with_state:
        by = agents._agent_metas()
        tasks = _open_tasks(slug)
        waits = _waits(slug)
        total, paid = 0.0, set()
        for p in positions:
            path, occupant, st, cost = p["agent"], None, {}, 0.0
            if path and agents.exists(path):
                try:
                    a = agents.load(path)
                    occupant = {"path": path, "display_name": a["name"] or agents.parse(path)[2],
                                "avatar": a["avatar"], "enabled": bool(a["enabled"]), "sandbox": bool(a["sandbox"])}
                    metas = by.get(path, [])
                    st = agents.status(path, metas)
                    cost = float(st.get("cost_today") or 0)
                except Exception:  # noqa: BLE001 - one unreadable agent must not hide the chart
                    logger.exception("position %s/%s: occupant unreadable", slug, p["id"])
                if path not in paid:
                    paid.add(path)
                    total += cost
            state = _state_of(occupant, st, waits.get(p["id"]))
            why = (waits.get(p["id"]) or {}).get("why", "") if state == "blocked" else ""
            p.update(state=state, occupant=occupant, cost_today=round(cost, 4), inbox=_inbox_count(slug, p["id"]),
                     open_tasks=tasks.get(p["id"], 0),
                     blocked_reason="agent missing" if path and occupant is None else why)
        out["cost_today"] = round(total, 4)
        cap = float(d["envelope"].get("usd_per_day") or 0)
        out["ceiling_hit"] = bool(cap and total >= cap)
    out["positions"] = positions
    return out


# ---- projects ---------------------------------------------------------------------------------------------
def _vacate_under(d: dict, projects: set[str]) -> list[str]:
    hit = []
    for p in d["positions"]:
        ap = agents.parse(p["agent"]) if p["agent"] else None
        if ap and ap[0] in projects:
            p["agent"] = None
            hit.append(p["id"])
    return hit


def set_projects(slug: str, projects: list[str], vacate: bool = False) -> dict:
    projects = _check_projects(projects, slug)

    def edit(d: dict) -> list[str]:
        gone = set(d["projects"]) - set(projects)
        held = [p["id"] for p in d["positions"] if p["agent"] and (agents.parse(p["agent"]) or [""])[0] in gone]
        if held and not vacate:
            raise EnterpriseError(409, "occupied", "Positions are held by agents of the project(s) removed: "
                                  + ", ".join(held), positions=held)
        d["projects"] = projects
        return _vacate_under(d, gone)

    _apply(slug, edit, lambda d, vac: "Projects: " + (", ".join(d["projects"]) or "none")
           + (f" ({len(vac)} position(s) vacated)" if vac else ""))
    return get(slug)


# ---- positions --------------------------------------------------------------------------------------------
def _find(d: dict, pos: str) -> dict:
    p = next((p for p in d["positions"] if p["id"] == pos), None)
    if p is None:
        raise EnterpriseError(404, "not_found", f"Position {pos!r} not found")
    return p


def _reports_to(d: dict, v: Any, pos: str) -> str | None:
    if v in (None, "", "owner"):
        return None
    if not _slug_ok(v) or not any(p["id"] == v for p in d["positions"]):
        raise EnterpriseError(400, "bad_position", f"The lead {v!r} does not exist")
    if v == pos:
        raise EnterpriseError(400, "cycle", "A position cannot report to itself")
    return v


def _fields(f: dict) -> dict:
    out: dict[str, Any] = {}
    if "title" in f:
        out["title"] = _text(f["title"], TITLE_MAX)
    if "job" in f:
        out["job"] = _text(f["job"], JOB_MAX)
    if "department" in f:
        dept = f["department"]
        if dept not in (None, "") and not _slug_ok(dept):
            raise EnterpriseError(400, "invalid", "department: an id")
        out["department"] = dept or ""
    if "desk" in f:
        out["desk"] = bool(f["desk"])
    if "worker_template" in f:
        out["worker_template"] = _worker(f["worker_template"])
    return out


def add_position(slug: str, fields: dict) -> dict:
    f = dict(fields or {})
    pid = f.get("id")
    if not _slug_ok(pid):
        raise EnterpriseError(400, "invalid_name",
                              "Use 1-48 lowercase letters, digits or dashes (starting with a letter or digit)")
    if pid in RESERVED_POS:
        raise EnterpriseError(400, "invalid", f"{pid!r} is reserved: pick another id for the position")

    def edit(d: dict) -> dict:
        if any(p["id"] == pid for p in d["positions"]):
            raise EnterpriseError(409, "exists", f"Position {pid!r} already exists")
        if len(d["positions"]) >= MAX_POSITIONS:
            raise EnterpriseError(400, "too_many", f"At most {MAX_POSITIONS} positions")
        extra = _fields(f)
        p = {"id": pid, "title": extra.get("title") or pid, "reports_to": _reports_to(d, f.get("reports_to"), pid),
             "department": extra.get("department", ""), "agent": None, "job": extra.get("job", ""),
             "desk": extra.get("desk", False)}
        if extra.get("worker_template"):
            p["worker_template"] = extra["worker_template"]
        if f.get("agent"):
            p["agent"] = _check_agent(d, slug, f["agent"], pid)
        d["positions"].append(p)
        return p

    _apply(slug, edit, lambda d, p: f"Position {p['id']} added" + (f" under {p['reports_to']}" if p["reports_to"] else "")
           + (f", held by {p['agent']}" if p["agent"] else ""))
    return get(slug)


def update_position(slug: str, pos: str, fields: dict, rev: int | None = None) -> dict:
    f = dict(fields or {})

    def edit(d: dict) -> list[str]:
        p = _find(d, pos)
        notes: list[str] = []
        move = "reports_to" in f and _reports_to(d, f["reports_to"], pos) != p["reports_to"]
        seat = "agent" in f and (f["agent"] or None) != p["agent"]
        if (move or seat) and rev != d["rev"]:
            raise EnterpriseError(409, "stale", "The chart changed since it was drawn: reload it", chart=get(slug))
        p.update(_fields(f))
        if p.get("worker_template") is None:
            p.pop("worker_template", None)
        if move:
            new = _reports_to(d, f["reports_to"], pos)
            if new in subtree_of(d, pos):
                raise EnterpriseError(400, "cycle", f"{new!r} is under {pos!r}")
            if p["id"] == d["top"] and new is not None:
                d["top"] = "owner"
            p["reports_to"] = new
            notes.append(f"moved under {new or 'the top'}")
        if seat:
            p["agent"] = _check_agent(d, slug, f["agent"], pos) if f["agent"] else None
            notes.append(f"held by {p['agent']}" if p["agent"] else "vacated")
        return notes

    _apply(slug, edit, lambda d, n: f"Position {pos}: " + (", ".join(n) or "edited"))
    return get(slug)


def subtree_of(d: dict, pos: str) -> list[str]:
    """subtree() on data not yet written."""
    out: list[str] = []
    todo = [p["id"] for p in d["positions"] if p["reports_to"] == pos]
    while todo:
        x = todo.pop()
        if x not in out:
            out.append(x)
            todo += [p["id"] for p in d["positions"] if p["reports_to"] == x]
    return out


def remove_position(slug: str, pos: str, reparent_to: str | None = None) -> dict:
    def edit(d: dict) -> tuple[int, str]:
        p = _find(d, pos)
        reports = [x for x in d["positions"] if x["reports_to"] == pos]
        new = p["reports_to"]                           # who takes over its requests: the new lead, else its own lead
        if reports:
            if reparent_to is None:
                raise EnterpriseError(409, "has_reports", f"{pos!r} has {len(reports)} report(s): say where they go",
                                      reports=[x["id"] for x in reports])
            new = _reports_to(d, reparent_to, pos)
            if new in subtree_of(d, pos):
                raise EnterpriseError(400, "cycle", f"{new!r} is under {pos!r}")
        for x in reports:
            x["reports_to"] = new
        d["positions"].remove(p)
        if d["top"] == pos:
            d["top"] = "owner"
        return len(reports), new or ""

    _, (_n, heir) = _apply(slug, edit, lambda d, res: f"Position {pos} removed" + (f", {res[0]} report(s) moved" if res[0] else ""))
    try:
        (_peek(slug) / "inbox" / f"{pos}.jsonl").unlink(missing_ok=True)
    except OSError:
        pass
    _reassign_requester(slug, pos, heir)
    return get(slug)


def _reassign_requester(slug: str, pos: str, heir: str) -> None:
    """The open tasks the removed position asked for get its heir (the new lead; "" = the owner) as requester."""
    try:
        from .api import tasks as tasks_api
        todo = [t for t in tasks_api.load(copy_=False).get("tasks") or []
                if isinstance(t.get("enterprise"), dict) and t["enterprise"].get("id") == slug
                and t["enterprise"].get("requester") == pos and t.get("status") != "done"]
        for t in todo:
            tasks_api.update_task(t["id"], {"enterprise": {**t["enterprise"], "requester": heir}})
        if todo:
            log(slug, "structure", f"{len(todo)} open task(s) of {pos} now have {heir or 'the owner'} as requester",
                by="server", position=heir)
    except Exception:  # noqa: BLE001 - the removal stands
        logger.exception("requesters of %s/%s not reassigned", slug, pos)


def hire(slug: str, pos: str, topic: str, name: str | None = None, template: str | None = None) -> str:
    """Create the agent of a vacant position in a topic of a linked project and seat it. -> its path.
    `template` (an agent template id; "" = none; default: the position's `suggested_template`) gives the settings; the role stays the job."""
    d = _load_ok(slug)
    p = _find(d, pos)
    m = TOPIC_RE.match((topic or "").strip("/"))
    if not m or m.group(1) not in d["projects"]:
        raise EnterpriseError(400, "bad_project", "The topic must belong to a project of this enterprise")
    if p["agent"] and agents.exists(p["agent"]):
        raise EnterpriseError(409, "not_vacant", f"The position {pos!r} already has an occupant")
    role = (p["title"] + ("\n\n" + p["job"] if p["job"] else "")).strip()
    fields: dict[str, Any] = {}
    tid = template if template is not None else (p.get("suggested_template") or "")
    if tid:
        from . import agent_templates, vault
        tpl = agent_templates.get(tid, config.load_config().get("language") or "en")
        if tpl is None:
            if template:
                raise EnterpriseError(400, "bad_template", f"No agent template {template!r}")
        else:
            fields = agent_templates.fields(tpl, [x["name"] for x in vault.list_secrets()])
            fields.pop("name", None)
    created = agents.create(topic.strip("/"), name or pos, {**fields, "description": role})
    path = created["path"]
    update_position(slug, pos, {"agent": path}, rev=load(slug)["rev"])
    return path


# ---- hooks of agents / workspace / trash -------------------------------------------------------------------
def _each(fn: Callable[[str, dict], str | None]) -> None:
    """Edit every readable enterprise under the lock; fn(slug, d) returns a log text when it changed d."""
    for slug in names():
        try:
            with _lock:
                d, kind = _read(slug)
                if kind != "ok":
                    continue
                text = fn(slug, d)
                if text is None:
                    continue
                d["rev"] = int(d.get("rev") or 0) + 1
                config.write_json(folder(slug) / FILE, d)
                log(slug, "structure", text)
            invalidate(slug)
        except Exception:  # noqa: BLE001 - a hook never breaks the delete / rename it follows
            logger.exception("enterprise %s not updated", slug)


def agent_gone(path: str) -> None:
    """An agent was deleted: its position is vacated (the box stays)."""
    def fn(slug: str, d: dict) -> str | None:
        hit = [p for p in d["positions"] if p["agent"] == path]
        for p in hit:
            p["agent"] = None
        return f"{path} was deleted: position {', '.join(p['id'] for p in hit)} vacated" if hit else None
    _each(fn)


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _swap(path: str, old: str, new: str) -> str:
    return new + path[len(old):] if _under(path, old) else path


def remap(old_prefix: str, new_prefix: str) -> None:
    """A project or topic was renamed: positions follow their agents; a renamed project follows in `projects`."""
    old_p, new_p = old_prefix.split("/")[1], new_prefix.split("/")[1]
    whole = old_prefix.count("/") == 1

    def fn(slug: str, d: dict) -> str | None:
        n = 0
        for p in d["positions"]:
            if p["agent"] and _under(p["agent"], old_prefix):
                p["agent"] = _swap(p["agent"], old_prefix, new_prefix)
                n += 1
        if whole and old_p in d["projects"]:
            d["projects"] = [new_p if x == old_p else x for x in d["projects"]]
            n += 1
        return f"{old_prefix} renamed to {new_prefix}" if n else None
    _each(fn)
    from . import enterprise_workers; enterprise_workers.remap(old_prefix, new_prefix)  # noqa: E702 - the workers follow too


def deleted_with(prefix: str, dest: Path) -> None:
    """A project or topic went to the Trash (its folder is now `dest`): its agents are vacated, a project is unlinked,
    and what the chart held is kept in the trashed folder for a restore."""
    saved: dict[str, dict] = {}
    whole = prefix.count("/") == 1
    project = prefix.split("/")[1]

    def fn(slug: str, d: dict) -> str | None:
        seats = {p["id"]: p["agent"] for p in d["positions"] if p["agent"] and _under(p["agent"], prefix)}
        linked = whole and project in d["projects"]
        if not seats and not linked:
            return None
        for p in d["positions"]:
            if p["id"] in seats:
                p["agent"] = None
        if linked:
            d["projects"] = [x for x in d["projects"] if x != project]
        saved[slug] = {"project": project if linked else None, "seats": seats}
        return f"{prefix} deleted: " + ("unlinked, " if linked else "") + f"{len(seats)} position(s) vacated"
    _each(fn)
    if saved:
        try:
            config.write_json(dest / SAVED_LINKS, {"prefix": prefix, "links": saved})
        except OSError:
            logger.exception("links of %s not kept in the Trash", prefix)


def restored(dest: Path, old_prefix: str | None = None, new_prefix: str | None = None) -> None:
    """An item came back from the Trash as `dest`: an enterprise folder gets its state back; a project or topic gets
    its link and the seats of its agents back (those still free), under the new name when it changed."""
    try:
        if old_prefix is None:
            _restore_enterprise(dest)
        else:
            _restore_links(dest, old_prefix, new_prefix or old_prefix)
    except Exception:  # noqa: BLE001
        logger.exception("enterprise data of %s not restored", dest)


def _restore_enterprise(dest: Path) -> None:
    slug = dest.name
    saved = dest / SAVED_STATE
    if saved.is_dir():
        target = _peek(slug)
        if target.exists() and any(target.iterdir()):
            shutil.rmtree(saved, ignore_errors=True)
        else:
            shutil.rmtree(target, ignore_errors=True)
            shutil.move(str(saved), str(target))
    with _lock:
        d, kind = _read(slug)
        if kind != "ok":
            return
        taken_projects, taken_seats = set(), set()             # held by the OTHER enterprises (this one is in the index too)
        for other, od in _index()["by"].items():
            if other != slug:
                taken_projects.update(od["projects"])
                taken_seats.update(x["agent"] for x in od["positions"] if x["agent"])
        mine = [p for p in d["projects"] if (config.workspace() / "projects" / p).is_dir() and p not in taken_projects]
        changed = mine != d["projects"]
        d["projects"] = mine
        for p in d["positions"]:
            ap = agents.parse(p["agent"]) if p["agent"] else None
            if p["agent"] and (not ap or ap[0] not in mine or not agents.exists(p["agent"]) or p["agent"] in taken_seats):
                p["agent"], changed = None, True
        if changed:
            d["rev"] = int(d.get("rev") or 0) + 1
            config.write_json(folder(slug) / FILE, d)
            log(slug, "structure", "Restored from the Trash: links and seats that no longer hold were dropped")
    invalidate(slug)
    invalidate()


def _restore_links(dest: Path, old_prefix: str, new_prefix: str) -> None:
    f = dest / SAVED_LINKS
    rec = config.read_json(f, None)
    if not isinstance(rec, dict) or not isinstance(rec.get("links"), dict):
        return
    new_project = new_prefix.split("/")[1]
    for slug, link in rec["links"].items():
        try:
            with _lock:
                d, kind = _read(slug) if _slug_ok(slug) else ({}, "missing")
                if kind != "ok":
                    continue
                text = []
                if link.get("project") and new_project not in d["projects"] and enterprise_of_project(new_project) is None:
                    d["projects"].append(new_project)
                    text.append("project linked again")
                for pid, agent in (link.get("seats") or {}).items():
                    path = _swap(agent, old_prefix, new_prefix)
                    p = next((x for x in d["positions"] if x["id"] == pid), None)
                    ap = agents.parse(path)
                    if p and not p["agent"] and ap and ap[0] in d["projects"] and agents.exists(path) \
                            and not seat_of(path):
                        p["agent"] = path
                        text.append(f"{pid} held again")
                if text:
                    d["rev"] = int(d.get("rev") or 0) + 1
                    config.write_json(folder(slug) / FILE, d)
                    log(slug, "structure", f"{new_prefix} restored from the Trash: " + ", ".join(text))
            invalidate(slug)
        except Exception:  # noqa: BLE001
            logger.exception("links of %s not restored in %s", new_prefix, slug)
    f.unlink(missing_ok=True)
