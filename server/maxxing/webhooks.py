"""Webhooks and events: automations without AI (Settings -> Automate -> Webhooks / Events).

A hook = one trigger + one action, made from the pages' form or by Harness (`maxxing webhooks add`), shown on two pages:
  trigger "in"     another service calls the hook's URL  (/api/hooks/<token>, GET or POST): page Webhooks
  trigger "event"  something happened in Harness: a feed event, the end of an automatic agent run, the end of a
                   cron run                                                                   : page Events
  action  "shell"  run a command (the request is handed over as files and variables, never in the command)
          "call"   call a URL (relay the request, or a JSON / text body made from a template)
          "store"  add the payload to the hook's own table (SQLite), read by the page, the CLI and widgets
          "notify" post a notification (the feed)
With AI, it is an agent instead (agents.py): nothing here starts Claude.

Storage (state_dir("webhooks")):
  hooks.json            {"version": 1, "hooks": [hook]}       - written under an flock (the CLI writes it too)
  calls/<id>.jsonl      the last KEEP_CALLS calls of a hook   - one record per line, rewritten under the flock
  calls/<id>/<call>/    request.json, body, files/, stdout, response(.type), result.json
  data/<id>.db          rows of a "store" hook
  spool/*.json          events emitted by other processes (cron runs, agent turns), consumed by the server loop
  feed-pos.json         the last feed event read by the "feed" triggers
Secrets (secrets.json "webhooks"): {id: {token, secret, sign}} - never in hooks.json nor in an API answer.

The URL token is the permission. A Stripe / Shopify / GitHub hook refuses every call until its signing secret is
set (as the feed's webhooks: feedhooks.py, whose checks are reused here); a generic hook checks an HMAC when it has
a secret, a phone hook a `Bearer` key. The calls of a hook run one at a time by default (`queue.parallel`), at most
`queue.max_waiting` wait (then 503). A call is recorded before it runs, so a restart resumes it.
"""
from __future__ import annotations

import codecs
import contextlib
import datetime as dt
import fcntl
import fnmatch
import hashlib
import hmac
import json
import logging
import os
import re
import secrets as _secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs

from . import config

log = logging.getLogger("maxxing.webhooks")

SOURCES = ("stripe", "shopify", "github", "generic", "phone")
SIGNED = ("stripe", "shopify", "github")        # always signed by the service: refused until the secret is set
TRIGGERS = ("in", "event")
EVENTS = ("feed", "agent", "cron")
ACTIONS = ("shell", "call", "store", "notify")
METHODS = ("GET", "POST")
CALL_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
REPORTS = ("never", "fail", "always")
WHEN = ("any", "ok", "fail")
LEVELS = ("info", "success", "warning", "error")
STATUSES = ("queued", "running", "ok", "failed", "ignored")
MB = 1024 * 1024
MAX_MB = 50
DEFAULT_MB = 1
PHONE_MB = 20
WAIT_S = 30.0                    # reply "wait": the caller gets the result within this, else 504 (the run goes on)
SYNC_MAX = 4                     # callers waiting at once, all hooks together
MAX_PARALLEL = 4
DEFAULT_WAITING = 50
MAX_WAITING = 500
KEEP_CALLS = 50
SHELL_TIMEOUT = 300
MAX_TIMEOUT = 3600
CALL_TIMEOUT = 15
MAX_RETRIES = 5
OUTPUT_TAIL = 4096
STDOUT_MAX = 1 * MB              # stdout kept for the reply of a "wait" hook
SHOW_BODY = 64 * 1024            # the body shown by the page / `calls --body`
DEFAULT_KEEP = 100_000           # rows of a store hook
MAX_KEEP = 1_000_000
MAX_HOPS = 3                     # feed events posted by a hook (and agents) this deep do not start hooks again
RATE = 120                       # calls per hook per minute
NAME_MAX, DESC_MAX = 60, 200
FILES_MAX = 20
SPOOL_MAX = 1000                 # events waiting in the spool (a stopped server): older ones dropped
RESULT_WAIT_S = 3.0
_REDACT = re.compile(r"authorization|cookie|signature|hmac|secret|token|api[-_]?key|x-harness-key", re.I)
_COL = re.compile(r"^[A-Za-z_][A-Za-z0-9_ -]{0,39}$")
_PATH = re.compile(r"^[A-Za-z0-9_.:\[\]-]{1,120}$")
_TPL = re.compile(r"\{\{\s*([A-Za-z0-9_.:\[\]-]+)\s*\}\}")
HID_RE = re.compile(r"^w_[0-9a-f]{8}$")
CID_RE = re.compile(r"^[0-9a-f]{10,16}$")


class WebhookError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---- files and locks -----------------------------------------------------------------------
_tlock = threading.RLock()


def _dir(*parts: str) -> Path:
    return config.state_dir("webhooks", *parts)


def hooks_path() -> Path:
    return _dir() / "hooks.json"


@contextlib.contextmanager
def _locked() -> Iterator[None]:
    """One writer at a time, across the server and the CLI."""
    with _tlock:
        with open(_dir() / ".lock", "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def _load() -> list[dict]:
    data = config.read_json(hooks_path(), {}) or {}
    hooks = data.get("hooks") if isinstance(data, dict) else None
    return [h for h in hooks if isinstance(h, dict) and HID_RE.match(str(h.get("id") or ""))] if isinstance(hooks, list) else []


def _save(hooks: list[dict]) -> None:
    config.write_json(hooks_path(), {"version": 1, "hooks": hooks})


def _store() -> dict:
    v = config.load_secrets().get("webhooks")
    return v if isinstance(v, dict) else {}


def _save_store(store: dict) -> None:
    config.set_secret("webhooks", store or None)


def _now() -> float:
    return time.time()


# ---- validation ----------------------------------------------------------------------------
def _bad(code: str, message: str) -> WebhookError:
    return WebhookError(400, code, message)


def _text(v: Any, n: int, what: str, required: bool = False) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise _bad("invalid", f"{what}: text expected")
    v = v.strip()
    if required and not v:
        raise _bad("invalid", f"{what} is required")
    if len(v) > n:
        raise _bad("invalid", f"{what}: {n} characters at most")
    return v


def _int(v: Any, lo: int, hi: int, default: int, what: str) -> int:
    if v is None or v == "":
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise _bad("invalid", f"{what}: a number expected")
    try:
        n = int(v)
    except (TypeError, ValueError, OverflowError):
        raise _bad("invalid", f"{what}: a number expected") from None
    if not lo <= n <= hi:
        raise _bad("invalid", f"{what}: between {lo} and {hi}")
    return n


def _choice(v: Any, choices: tuple, default: str, what: str) -> str:
    if v in (None, ""):
        return default
    if v not in choices:
        raise _bad("invalid", f"{what}: one of {', '.join(choices)}")
    return v


def _strs(v: Any, n: int, each: int, what: str) -> list[str]:
    if v in (None, ""):
        return []
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or len(v) > n:
        raise _bad("invalid", f"{what}: a list of {n} at most")
    return [_text(x, each, what, required=True) for x in v]


def _clean_trigger(t: Any) -> dict:
    if not isinstance(t, dict):
        raise _bad("invalid", "trigger: an object expected")
    kind = _choice(t.get("kind"), TRIGGERS, "", "trigger.kind")
    if not kind:
        raise _bad("invalid", "trigger.kind: in or event")
    if kind == "in":
        source = _choice(t.get("source"), SOURCES, "generic", "trigger.source")
        methods = [m.upper() for m in _strs(t.get("methods"), 2, 4, "trigger.methods")] or \
            (["GET", "POST"] if source == "phone" else ["POST"])
        if any(m not in METHODS for m in methods):
            raise _bad("invalid", "trigger.methods: GET and/or POST")
        if source in SIGNED and methods != ["POST"]:
            raise _bad("invalid", f"{source} only sends POST")
        flt = t.get("filter") or {}
        if not isinstance(flt, dict):
            raise _bad("invalid", "trigger.filter: an object expected")
        out = {"kind": "in", "source": source, "methods": sorted(set(methods)),
               "max_mb": _int(t.get("max_mb"), 1, MAX_MB, PHONE_MB if source == "phone" else DEFAULT_MB, "trigger.max_mb"),
               "reply": _choice(t.get("reply"), ("now", "wait"), "now", "trigger.reply"),
               "filter": {k: v for k, v in {"events": _strs(flt.get("events"), 20, 80, "trigger.filter.events"),
                                            "branch": _text(flt.get("branch"), 100, "trigger.filter.branch")}.items() if v}}
        return out
    on = _choice(t.get("on"), EVENTS, "", "trigger.on")
    if not on:
        raise _bad("invalid", "trigger.on: feed, agent or cron")
    out = {"kind": "event", "on": on, "when": _choice(t.get("when"), WHEN, "any", "trigger.when")}
    if on == "feed":
        out["source"] = _text(t.get("source"), 40, "trigger.source").lower()
        out["levels"] = _strs(t.get("levels"), 4, 10, "trigger.levels")
        if any(x not in LEVELS for x in out["levels"]):
            raise _bad("invalid", f"trigger.levels: {', '.join(LEVELS)}")
        out["contains"] = _text(t.get("contains"), 100, "trigger.contains")
        out.pop("when")
    elif on == "agent":
        out["agent"] = _text(t.get("agent"), 300, "trigger.agent").strip("/")
    else:
        out["cron"] = _text(t.get("cron"), 64, "trigger.cron")
    return out


def _clean_headers(v: Any) -> dict:
    if v in (None, ""):
        return {}
    if not isinstance(v, dict) or len(v) > 20:
        raise _bad("invalid", "action.headers: an object of 20 headers at most")
    out = {}
    for k, val in v.items():
        if not isinstance(k, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,60}", k):
            raise _bad("invalid", f"action.headers: bad header name {k!r}")
        val = _text(val, 2000, f"action.headers.{k}")
        if re.search(r"[\r\n]", val):
            raise _bad("invalid", f"action.headers.{k}: one line")
        out[k] = val
    return out


def _clean_action(a: Any, trigger: dict) -> dict:
    if not isinstance(a, dict):
        raise _bad("invalid", "action: an object expected")
    kind = _choice(a.get("kind"), ACTIONS, "", "action.kind")
    if not kind:
        raise _bad("invalid", "action.kind: shell, call, store or notify")
    if kind == "shell":
        cmd = _text(a.get("command"), 4000, "action.command", required=True)
        if "\n" in cmd:
            raise _bad("invalid", "action.command: one line (put longer work in a script file)")
        cwd = _text(a.get("cwd"), 500, "action.cwd")
        if cwd and not cwd.startswith("/"):
            raise _bad("invalid", "action.cwd: an absolute path")
        return {"kind": "shell", "command": cmd, "cwd": cwd,
                "timeout_s": _int(a.get("timeout_s"), 1, MAX_TIMEOUT, SHELL_TIMEOUT, "action.timeout_s")}
    if kind == "call":
        url = _text(a.get("url"), 2000, "action.url", required=True)
        bare = re.sub(r"\{\{\s*key:[A-Za-z0-9_]+\s*\}\}", "", url)
        whole_key = re.fullmatch(r"\{\{\s*key:[A-Za-z0-9_]+\s*\}\}", url) is not None
        if "{{" in bare or re.search(r"\s", url) or not (whole_key or re.match(r"^https?://[^\s/?#{}]+", url)):
            raise _bad("invalid", "action.url: an http(s) address; only {{key:NAME}} (a vault key) may be in it")
        body = a.get("body")
        default = "raw" if trigger["kind"] == "in" else "json"
        body = default if body in (None, "") else body
        if not isinstance(body, str) or len(body) > 10000:
            raise _bad("invalid", "action.body: raw, json or a template (10000 characters at most)")
        if body == "raw" and trigger["kind"] != "in":
            body = "json"
        return {"kind": "call", "url": url, "method": _choice((a.get("method") or "POST").upper(), CALL_METHODS, "POST", "action.method"),
                "headers": _clean_headers(a.get("headers")), "body": body, "sign": bool(a.get("sign")),
                "retries": _int(a.get("retries"), 0, MAX_RETRIES, 2, "action.retries"),
                "timeout_s": _int(a.get("timeout_s"), 1, 60, CALL_TIMEOUT, "action.timeout_s")}
    if kind == "store":
        fields = a.get("fields") or {}
        if not isinstance(fields, dict) or len(fields) > 20:
            raise _bad("invalid", "action.fields: an object of 20 columns at most")
        for k, p in fields.items():
            if not isinstance(k, str) or not _COL.match(k) or not isinstance(p, str) or not _PATH.match(p):
                raise _bad("invalid", f"action.fields: bad column {k!r} (path like data.object.amount)")
        return {"kind": "store", "fields": dict(fields), "keep": _int(a.get("keep"), 1, MAX_KEEP, DEFAULT_KEEP, "action.keep")}
    return {"kind": "notify", "level": _choice(a.get("level"), LEVELS, "", "action.level"),
            "title": _text(a.get("title"), 300, "action.title"), "body": _text(a.get("body"), 2000, "action.body"),
            "url": _text(a.get("url"), 500, "action.url")}


def _clean(spec: dict, old: dict | None = None) -> dict:
    if not isinstance(spec, dict):
        raise _bad("invalid", "a JSON object expected")
    cur = {**(old or {}), **{k: v for k, v in spec.items() if v is not None}}
    trigger = _clean_trigger(cur.get("trigger"))
    action = _clean_action(cur.get("action"), trigger)
    if trigger.get("reply") == "wait" and action["kind"] == "notify":
        trigger["reply"] = "now"
    q = cur.get("queue") or {}
    if not isinstance(q, dict):
        raise _bad("invalid", "queue: an object expected")
    enabled = cur.get("enabled", True)
    if not isinstance(enabled, bool):
        raise _bad("invalid", "enabled: true or false")
    return {"id": (old or {}).get("id") or "", "name": _text(cur.get("name"), NAME_MAX, "name", required=True),
            "description": _text(cur.get("description"), DESC_MAX, "description"), "enabled": enabled,
            "created": (old or {}).get("created") or _now(), "updated": _now(), "owner": (old or {}).get("owner"),
            "trigger": trigger, "action": action,
            "queue": {"parallel": _int(q.get("parallel"), 1, MAX_PARALLEL, 1, "queue.parallel"),
                      "max_waiting": _int(q.get("max_waiting"), 0, MAX_WAITING, DEFAULT_WAITING, "queue.max_waiting")},
            "report": _choice(cur.get("report"), REPORTS, "fail", "report")}


def _check_secret(secret: str | None) -> str:
    s = (secret or "").strip()
    if len(s) > 500 or re.search(r"[\x00-\x1f\x7f]", s):
        raise _bad("bad_secret", "The secret: one line, 500 characters at most")
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        raise _bad("bad_secret", "The secret contains an invalid character") from None
    return s


# ---- management ----------------------------------------------------------------------------
def hook_url(token: str) -> str:
    base = (config.load_config().get("public_url") or "").rstrip("/")
    return f"{base}/api/hooks/{token}" if token else ""


def _find(hooks: list[dict], hid: str) -> dict:
    h = next((h for h in hooks if h["id"] == hid), None)
    if h is None:
        raise WebhookError(404, "not_found", f"No webhook {hid}")
    return h


def get(hid: str) -> dict:
    return _find(_load(), hid)


def public(h: dict, store: dict | None = None, stats: bool = True) -> dict:
    s = (store if store is not None else _store()).get(h["id"]) or {}
    out = {**h, "url": hook_url(s.get("token", "")) if h["trigger"]["kind"] == "in" else "",
           "has_secret": bool(s.get("secret")), "has_sign": bool(s.get("sign"))}
    if stats:
        recs = _records(h["id"])
        last = next((r for r in reversed(recs) if r.get("status") != "ignored"), recs[-1] if recs else None)
        day = _now() - 86400
        out["last_call"] = _short(last) if last else None
        out["calls_24h"] = sum(1 for r in recs if r.get("at", 0) >= day and r.get("status") != "ignored")
        out["waiting"] = sum(1 for r in recs if r.get("status") == "queued")
        out["needs_secret"] = h["trigger"]["kind"] == "in" and h["trigger"]["source"] in SIGNED and not s.get("secret")
        if h["action"]["kind"] == "store":
            out["data"] = data_stats(h["id"])
    return out


def list_hooks(stats: bool = True) -> list[dict]:
    store = _store()
    return [public(h, store, stats) for h in _load()]


def create(spec: dict, secret: str | None = None) -> dict:
    secret = _check_secret(secret)
    with _locked():
        hooks = _load()
        h = _clean(spec)
        if any(x["name"].lower() == h["name"].lower() for x in hooks):
            raise WebhookError(409, "exists", f"A webhook named {h['name']!r} already exists")
        h["id"] = "w_" + _secrets.token_hex(4)
        store = _store()
        s: dict = {}
        if h["trigger"]["kind"] == "in":
            s["token"] = _secrets.token_urlsafe(24)
            if secret:
                s["secret"] = secret
        if h["action"]["kind"] == "call" and h["action"].get("sign"):
            s["sign"] = _secrets.token_hex(24)
        store[h["id"]] = s
        _save_store(store)
        _save(hooks + [h])
    _changed()
    return public(h)


def update(hid: str, spec: dict) -> dict:
    spec = {k: v for k, v in (spec or {}).items() if k not in ("id", "created", "owner", "updated")}
    with _locked():
        hooks = _load()
        old = _find(hooks, hid)
        if old.get("owner"):
            raise WebhookError(409, "owned", "This webhook belongs to an agent: change it from the agent")
        h = _clean(spec, old)
        if h["name"].lower() != old["name"].lower() and any(x["name"].lower() == h["name"].lower() for x in hooks):
            raise WebhookError(409, "exists", f"A webhook named {h['name']!r} already exists")
        store = _store()
        s = store.setdefault(hid, {})
        if h["trigger"]["kind"] == "in" and not s.get("token"):
            s["token"] = _secrets.token_urlsafe(24)
        if h["trigger"]["kind"] != "in":
            s.pop("token", None)
            s.pop("secret", None)
        if h["action"]["kind"] == "call" and h["action"].get("sign") and not s.get("sign"):
            s["sign"] = _secrets.token_hex(24)
        _save_store(store)
        _save([h if x["id"] == hid else x for x in hooks])
    _changed()
    return public(h)


def set_enabled(hid: str, on: bool) -> dict:
    with _locked():
        hooks = _load()
        h = _find(hooks, hid)
        h["enabled"], h["updated"] = bool(on), _now()
        _save(hooks)
    _changed()
    return public(h)


def set_description(hid: str, description: str) -> dict:
    with _locked():
        hooks = _load()
        h = _find(hooks, hid)
        h["description"], h["updated"] = _text(description, DESC_MAX, "description"), _now()
        _save(hooks)
    _changed()
    return public(h)


def rotate(hid: str) -> dict:
    with _locked():
        h = _find(_load(), hid)
        if h["trigger"]["kind"] != "in":
            raise _bad("no_url", "Only a webhook called from outside has a URL")
        store = _store()
        store.setdefault(hid, {})["token"] = _secrets.token_urlsafe(24)
        _save_store(store)
    _changed()
    return public(h)


def set_secret(hid: str, secret: str | None) -> dict:
    secret = _check_secret(secret)
    with _locked():
        h = _find(_load(), hid)
        if h["trigger"]["kind"] != "in":
            raise _bad("no_url", "Only a webhook called from outside has a secret")
        store = _store()
        s = store.setdefault(hid, {})
        if secret:
            s["secret"] = secret
        else:
            s.pop("secret", None)
        _save_store(store)
    _changed()
    return public(h)


def sign_secret(hid: str) -> str:
    get(hid)
    return str((_store().get(hid) or {}).get("sign") or "")


def remove(hid: str) -> None:
    with _locked():
        hooks = _load()
        _find(hooks, hid)
        store = _store()
        store.pop(hid, None)
        _save_store(store)
        _save([h for h in hooks if h["id"] != hid])
    with contextlib.suppress(OSError):
        (_dir("calls") / f"{hid}.jsonl").unlink()
    shutil.rmtree(_dir("calls") / hid, ignore_errors=True)
    with contextlib.suppress(OSError):
        (_dir("data") / f"{hid}.db").unlink()
    for ext in ("-wal", "-shm"):
        with contextlib.suppress(OSError):
            (_dir("data") / f"{hid}.db{ext}").unlink()
    _changed()


def by_token(token: str) -> tuple[dict, dict] | None:
    if not token or len(token) > 100:
        return None
    from .feedhooks import _same
    for hid, s in _store().items():
        if isinstance(s, dict) and s.get("token") and _same(str(s["token"]), token):
            with contextlib.suppress(WebhookError):
                return get(hid), s
    return None


def cap_for_token(token: str) -> int | None:
    """The body cap of a hook's URL (bodylimit.py), None when the token is not one of ours."""
    found = by_token(token)
    return found[0]["trigger"]["max_mb"] * MB if found else None


def _changed() -> None:
    with contextlib.suppress(Exception):
        from . import bus
        bus.invalidate("webhooks")


# ---- sentences -----------------------------------------------------------------------------
def describe(h: dict) -> str:
    """The English sentence of a hook without a description (the UI makes its own, in the user's language)."""
    if h.get("description"):
        return h["description"]
    t, a = h["trigger"], h["action"]
    if t["kind"] == "in":
        when = {"stripe": "When Stripe calls", "shopify": "When Shopify calls", "github": "When GitHub calls",
                "phone": "When the phone calls"}.get(t["source"], "When its URL is called")
    elif t["on"] == "feed":
        when = f"On a notification{' from ' + t['source'] if t.get('source') else ''}"
    elif t["on"] == "agent":
        when = f"When {'agent ' + t['agent'] if t.get('agent') else 'an agent'} finishes"
    else:
        ends = {"ok": "succeeds", "fail": "fails"}.get(t.get("when") or "any", "ends")
        when = f"When {'cron ' + t['cron'] if t.get('cron') else 'a cron job'} {ends}"
    if t["kind"] == "event" and t["on"] == "agent" and t.get("when") in ("ok", "fail"):
        when = when.replace("finishes", "succeeds" if t["when"] == "ok" else "fails")
    do = {"shell": f"run {a.get('command', '')[:60]}", "call": f"call {re.sub(r'^https?://', '', a.get('url', ''))[:50]}",
          "store": "store the data", "notify": "post a notification"}[a["kind"]]
    return f"{when}, {do}"


# ---- call records --------------------------------------------------------------------------
def _calls_file(hid: str) -> Path:
    return _dir("calls") / f"{hid}.jsonl"


def call_dir(hid: str, cid: str) -> Path:
    return _dir("calls", hid) / cid


def _records(hid: str) -> list[dict]:
    try:
        lines = _calls_file(hid).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        with contextlib.suppress(ValueError):
            r = json.loads(line)
            if isinstance(r, dict) and r.get("id"):
                out.append(r)
    return out


def _write_records(hid: str, recs: list[dict]) -> None:
    p = _calls_file(hid)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    os.replace(tmp, p)


def _new_cid() -> str:
    return f"{int(_now() * 1000):x}{_secrets.token_hex(2)}"


def _add_record(hid: str, rec: dict) -> None:
    with _locked():
        recs = _records(hid) + [rec]
        drop = []
        while len(recs) > KEEP_CALLS:
            i = next((i for i, r in enumerate(recs) if r.get("status") not in ("queued", "running")), None)
            if i is None:
                break
            drop.append(recs.pop(i))
        _write_records(hid, recs)
    for r in drop:
        shutil.rmtree(call_dir(hid, r["id"]), ignore_errors=True)


def _update_record(hid: str, cid: str, **fields: Any) -> dict | None:
    with _locked():
        recs = _records(hid)
        rec = next((r for r in recs if r["id"] == cid), None)
        if rec is None:
            return None
        rec.update(fields)
        _write_records(hid, recs)
    return rec


def _short(r: dict) -> dict:
    return {k: r.get(k) for k in ("id", "at", "trigger", "event", "summary", "status", "http", "exit", "duration_s", "error")
            if r.get(k) is not None}


def calls(hid: str, limit: int = KEEP_CALLS) -> list[dict]:
    get(hid)
    return list(reversed(_records(hid)))[:limit]


def call(hid: str, cid: str, body: bool = True) -> dict:
    get(hid)
    if not CID_RE.match(cid or ""):
        raise WebhookError(404, "not_found", "No such call")
    rec = next((r for r in _records(hid) if r["id"] == cid), None)
    if rec is None:
        raise WebhookError(404, "not_found", "No such call")
    out = dict(rec)
    d = call_dir(hid, cid)
    req = config.read_json(d / "request.json", {}) or {}
    out["request"] = {k: req.get(k) for k in ("method", "content_type", "headers", "query", "event", "files", "size")}
    if body:
        raw = _read_bytes(d / "body", SHOW_BODY)
        out["body"] = raw.decode("utf-8", "replace") if _is_text(raw) else f"[{req.get('size', len(raw))} bytes of binary data]"
        out["body_truncated"] = (req.get("size") or 0) > SHOW_BODY
    return out


def _read_bytes(p: Path, n: int | None = None) -> bytes:
    try:
        with open(p, "rb") as f:
            return f.read(n) if n else f.read()
    except OSError:
        return b""


def _is_text(b: bytes) -> bool:
    head = b[:4096]
    if b"\x00" in head:
        return False
    try:
        codecs.getincrementaldecoder("utf-8")().decode(head, final=len(b) <= 4096)   # a cut last character is fine
        return True
    except UnicodeDecodeError:
        return False


# ---- requests ------------------------------------------------------------------------------
def _redact(headers: dict) -> dict:
    return {k: ("***" if _REDACT.search(k) else str(v)[:500]) for k, v in headers.items()}


def _flat(d: dict[str, list[str]]) -> dict:
    return {k: v[0] if len(v) == 1 else v for k, v in d.items()}


def parse_payload(method: str, content_type: str, body: bytes, query: dict, fields: dict | None) -> Any:
    ct = (content_type or "").split(";")[0].strip().lower()
    if method == "GET" or (not body and fields is None):
        return dict(query)
    if fields is not None:
        return dict(fields)
    if ct.endswith("json") or (not ct and body[:1] in (b"{", b"[")):
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise _bad("bad_json", "The body is not valid JSON") from None
    if ct == "application/x-www-form-urlencoded":
        try:
            return _flat(parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=500))
        except (UnicodeDecodeError, ValueError):
            raise _bad("bad_form", "The form cannot be read") from None
    if _is_text(body[:SHOW_BODY]) or not body:
        return {"text": body.decode("utf-8", "replace")}
    return {}


def event_name(source: str, payload: Any, headers: dict) -> tuple[str, str]:
    """-> (event, branch) of an incoming call."""
    low = {k.lower(): v for k, v in headers.items()}
    p = payload if isinstance(payload, dict) else {}
    if source == "stripe":
        return str(p.get("type") or ""), ""
    if source == "shopify":
        return str(low.get("x-shopify-topic") or ""), ""
    if source == "github":
        ev = str(low.get("x-github-event") or "")
        ref = str(p.get("ref") or "")
        return ev, ref.split("/", 2)[2] if ref.startswith("refs/heads/") else ""
    ev = p.get("event") or p.get("type") or ""
    return (str(ev) if isinstance(ev, (str, int, float)) else ""), ""


def _passes(flt: dict, event: str, branch: str) -> bool:
    evs = flt.get("events") or []
    if evs and not any(fnmatch.fnmatchcase(event, e) for e in evs):
        return False
    if flt.get("branch") and branch and not fnmatch.fnmatchcase(branch, flt["branch"]):
        return False
    if flt.get("branch") and not branch and event == "push":
        return False                                  # a tag push
    return True


def _summary(source: str, event: str, payload: Any, method: str) -> str:
    p = payload if isinstance(payload, dict) else {}
    with contextlib.suppress(Exception):
        if source in ("stripe", "shopify", "github"):
            from .feedhooks import PARSERS
            ev = PARSERS[source](p, {"x-shopify-topic": event, "x-github-event": event})
            if ev and ev[0]:
                return str(ev[0])[:120]
    if event:
        return event[:120]
    for k in ("title", "text", "message", "name"):
        if isinstance(p.get(k), str) and p[k].strip():
            return p[k].strip().splitlines()[0][:120]
    return f"{method} call"


def _check_auth(h: dict, s: dict, headers: dict, query: dict, body: bytes) -> tuple[int, dict] | None:
    src = h["trigger"]["source"]
    secret = str(s.get("secret") or "")
    low = {k.lower(): v for k, v in headers.items()}
    from . import feed, feedhooks
    if src in SIGNED and not secret:
        feed.system(f"Webhook {h['name']} refused: no signing secret",
                    f"Give it the {src.capitalize()} signing secret (ask Harness, or `maxxing webhooks secret {h['id']}`); "
                    "calls are refused until then.", "warning", "security", f"/settings/webhooks?hook={h['id']}",
                    group=f"wh-secret-{h['id']}")
        return 401, {"error": "secret_required"}
    if not secret:
        return None
    if src == "phone":
        got = str(low.get("authorization") or "")
        got = got[7:].strip() if got.lower().startswith("bearer ") else str(low.get("x-harness-key") or query.get("key") or "")
        return None if got and feedhooks._same(got, secret) else (401, {"error": "bad_key"})
    return None if feedhooks.verify(src, secret, headers, body) else (401, {"error": "bad_signature"})


_hits: dict[str, deque] = {}


def _limited(hid: str) -> bool:
    q = _hits.setdefault(hid, deque())
    now = _now()
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= RATE:
        return True
    q.append(now)
    return False


def receive(token: str, method: str, headers: dict, query: dict, body: bytes,
            fields: dict | None = None, files: list[tuple[str, str, bytes]] | None = None) -> dict:
    """An incoming call -> {status, json, hook?, call?, wait?}. `wait`: the API waits for the call (reply "wait")."""
    found = by_token(token)
    if found is None:
        return {"status": 404, "json": {"error": "not_found"}}
    h, s = found
    t = h["trigger"]
    if not h["enabled"]:
        return {"status": 503, "json": {"error": "disabled"}, "retry_after": 3600}
    if method not in t["methods"]:
        return {"status": 405, "json": {"error": "method_not_allowed", "allowed": t["methods"]}}
    if len(body) > t["max_mb"] * MB:
        return {"status": 413, "json": {"error": "too_big"}}
    if not s.get("secret") and _limited(h["id"]):
        return {"status": 429, "json": {"error": "rate_limited"}, "retry_after": 60}
    bad = _check_auth(h, s, headers, query, body)
    if bad:
        return {"status": bad[0], "json": bad[1]}
    if t["source"] == "phone" and s.get("secret"):       # the access key of ?key= is not data: never stored nor passed on
        query = {k: v for k, v in query.items() if k != "key"}
    if s.get("secret") and _limited(h["id"]):
        return {"status": 429, "json": {"error": "rate_limited"}, "retry_after": 60}
    from . import feed, feedhooks
    low = {k.lower(): v for k, v in headers.items()}
    claim = None
    if s.get("secret") and t["source"] in ("shopify", "github", "generic") and body:
        claim = feedhooks._replay_key(t["source"], low, body)
        if not feed.claim_delivery(f"wh:{h['id']}", claim, feedhooks.REPLAY_KEEP_S.get(t["source"], feedhooks.DEFAULT_REPLAY_S)):
            return {"status": 200, "json": {"ok": True, "duplicate": True}}
    try:
        try:
            payload = parse_payload(method, str(low.get("content-type") or ""), body, query, fields)
        except WebhookError as e:
            if t["source"] in SIGNED or e.code != "bad_json":
                raise
            payload = {"text": body.decode("utf-8", "replace")}
        event, branch = event_name(t["source"], payload, headers)
        ignored = not _passes(t.get("filter") or {}, event, branch)
        if not ignored and not dispatcher.has_room(h):
            if claim:
                feed.release_delivery(f"wh:{h['id']}", claim)
            return {"status": 503, "json": {"error": "busy", "message": "Too many calls waiting"}, "retry_after": 30}
        wait = t["reply"] == "wait" and not ignored
        if wait and not dispatcher.sync_slot():
            if claim:
                feed.release_delivery(f"wh:{h['id']}", claim)
            return {"status": 503, "json": {"error": "busy", "message": "Too many callers waiting"}, "retry_after": 10}
        try:
            cid = _new_cid()
            _save_request(h["id"], cid, method=method, headers=headers, query=query, body=body, files=files or [],
                          payload=payload, event=event)
            rec = {"id": cid, "at": _now(), "trigger": "in", "event": event,
                   "summary": _summary(t["source"], event, payload, method), "status": "ignored" if ignored else "queued"}
            _add_record(h["id"], rec)
            _changed()
            if ignored:
                return {"status": 200, "json": {"ok": True, "ignored": True, "call": cid}}
            dispatcher.submit(h["id"], cid, wait=wait)
        except BaseException:
            if wait:
                dispatcher.sync_release()
            raise
        if wait:
            return {"status": 202, "json": {"ok": True, "call": cid}, "hook": h["id"], "call": cid, "wait": True}
        return {"status": 202, "json": {"ok": True, "call": cid}}
    except WebhookError as e:
        if claim:
            feed.release_delivery(f"wh:{h['id']}", claim)
        return {"status": e.status, "json": {"error": e.code, "message": e.message}}
    except BaseException:
        if claim:   # storage failed (disk full...): free the delivery so the sender's retry is not taken for a duplicate
            feed.release_delivery(f"wh:{h['id']}", claim)
        raise


def _save_request(hid: str, cid: str, *, method: str, headers: dict, query: dict, body: bytes,
                  files: list[tuple[str, str, bytes]], payload: Any, event: str, extra: dict | None = None) -> None:
    d = call_dir(hid, cid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "body").write_bytes(body)
    saved = []
    if files:
        fd = d / "files"
        fd.mkdir(exist_ok=True)
        for i, (field, name, data) in enumerate(files[:FILES_MAX]):
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.basename(name or "") or f"file{i + 1}").lstrip(".")[:100] or f"file{i + 1}"
            if (fd / safe).exists():
                safe = f"{i + 1}-{safe}"
            (fd / safe).write_bytes(data)
            saved.append({"field": field, "name": safe, "path": str(fd / safe), "size": len(data)})
    low = {k.lower(): v for k, v in headers.items()}
    config.write_json(d / "request.json", {
        "method": method, "content_type": str(low.get("content-type") or ""), "headers": _redact(headers),
        "query": query, "event": event, "files": saved, "size": len(body), **(extra or {})})
    config.write_json(d / "payload.json", payload if payload is not None else {})


# ---- events (feed, agents, crons) ----------------------------------------------------------
def _event_hooks(on: str) -> list[dict]:
    return [h for h in _load() if h["enabled"] and h["trigger"]["kind"] == "event" and h["trigger"]["on"] == on]


def emit(kind: str, data: dict) -> None:
    """Another process (a cron run, an agent turn) tells the server loop that something ended. Never raises."""
    try:
        if kind not in ("agent", "cron") or not _event_hooks(kind):
            return
        sp = _dir("spool")
        if sum(1 for _ in sp.glob("*.json")) >= SPOOL_MAX:
            return
        p = sp / f"{int(_now() * 1000):013d}-{_secrets.token_hex(3)}.json"
        config.write_json(p, {"kind": kind, "at": _now(), "data": data})
    except Exception:  # noqa: BLE001
        log.exception("webhooks: cannot record the %s event", kind)


def _fire_event(h: dict, event: str, data: dict, summary: str) -> str | None:
    if not dispatcher.has_room(h):
        log.warning("webhook %s: queue full, event dropped", h["id"])
        return None
    cid = _new_cid()
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    _save_request(h["id"], cid, method="EVENT", headers={"Content-Type": "application/json"}, query={}, body=body,
                  files=[], payload=data, event=event)
    _add_record(h["id"], {"id": cid, "at": _now(), "trigger": "event", "event": event, "summary": summary[:120],
                          "status": "queued"})
    dispatcher.submit(h["id"], cid)
    return cid


def _when_ok(t: dict, ok: bool) -> bool:
    w = t.get("when") or "any"
    return w == "any" or (w == "ok") == bool(ok)


def process_spool() -> int:
    n = 0
    for p in sorted(_dir("spool").glob("*.json"))[:200]:
        item = config.read_json(p, None)
        with contextlib.suppress(OSError):
            p.unlink()
        if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
            continue
        kind, data = item.get("kind"), item["data"]
        for h in _event_hooks(str(kind)):
            t = h["trigger"]
            if not _when_ok(t, bool(data.get("ok"))):
                continue
            if kind == "agent":
                want = t.get("agent") or ""
                if want and data.get("agent") != want and not str(data.get("agent", "")).startswith(want + "/"):
                    continue
                if _fire_event(h, f"agent:{data.get('agent')}", data,
                               f"{data.get('agent', 'agent')}: {'done' if data.get('ok') else 'failed'}"):
                    n += 1
            elif kind == "cron":
                want = t.get("cron") or ""
                if want and want not in (data.get("cron"), data.get("name")):
                    continue
                if _fire_event(h, f"cron:{data.get('cron')}", data,
                               f"{data.get('name', 'cron')}: {'ok' if data.get('ok') else 'failed'}"):
                    n += 1
    return n


def _feed_pos_path() -> Path:
    return _dir() / "feed-pos.json"


def scan_feed() -> int:
    """Hand the feed events posted since the last scan to the matching "feed" event hooks."""
    from . import feed
    hooks = _event_hooks("feed")
    top = feed.max_id()
    pos = config.read_json(_feed_pos_path(), {}) or {}
    last = pos.get("last_id")
    if not hooks or not isinstance(last, int) or top < last:
        if last != top:
            config.write_json(_feed_pos_path(), {"last_id": top})
        return 0
    if top == last:
        return 0
    events = feed.events_after(last, 200)
    n = 0
    for ev in events:
        if ev.get("source") == "webhooks" or int(ev.get("hops") or 0) >= MAX_HOPS:
            continue
        text = f"{ev.get('title', '')}\n{ev.get('body', '')}".lower()
        for h in hooks:
            t = h["trigger"]
            if t.get("source") and ev.get("source") != t["source"]:
                continue
            if t.get("levels") and ev.get("level") not in t["levels"]:
                continue
            if t.get("contains") and t["contains"].lower() not in text:
                continue
            if h["action"]["kind"] == "notify" and ev.get("source") == _notify_source(h):
                continue                              # its own notifications
            data = {k: ev.get(k) for k in ("id", "title", "body", "level", "source", "url", "at", "hops")}
            if _fire_event(h, f"feed:{ev.get('source')}", data, str(ev.get("title") or "notification")):
                n += 1
    config.write_json(_feed_pos_path(), {"last_id": max([last] + [int(e["id"]) for e in events])})
    return n


# ---- templates -----------------------------------------------------------------------------
def _lookup(ctx: Any, path: str) -> Any:
    cur = ctx
    for part in re.split(r"\.|\[(\d+)\]", path):
        if part in (None, ""):
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def render(tpl: str, ctx: dict, json_mode: bool = False, keys: bool = False) -> str:
    """{{path}} -> its value (text; JSON for objects); `json_mode`: values are escaped for a JSON string;
    `keys`: {{key:NAME}} -> the vault key NAME (headers only)."""
    def one(m: re.Match) -> str:
        name = m.group(1)
        if name.startswith("key:"):
            if not keys:
                return ""
            from . import vault
            return vault.get(name[4:]) or ""
        v = _lookup(ctx, name)
        if v is None:
            s = ""
        elif isinstance(v, (dict, list)):
            s = json.dumps(v, ensure_ascii=False)
        elif isinstance(v, bool):
            s = "true" if v else "false"
        else:
            s = str(v)
        return json.dumps(s, ensure_ascii=False)[1:-1] if json_mode else s
    return _TPL.sub(one, tpl)


def _context(h: dict, cid: str) -> tuple[dict, dict, bytes]:
    d = call_dir(h["id"], cid)
    req = config.read_json(d / "request.json", {}) or {}
    payload = config.read_json(d / "payload.json", {})
    return _ctx(payload, req.get("event", ""), req.get("query") or {}, h["name"], cid), req, _read_bytes(d / "body")


def _ctx(payload: Any, event: str = "", query: dict | None = None, hook: str = "", cid: str = "") -> dict:
    """What a {{path}} reads: the payload's own keys first ({{data.object.amount}} of a Stripe event), then
    `payload` (all of it), `event`, `query`, `hook`, `call` when the payload has no key of that name."""
    ctx: dict = {"payload": payload, "event": event, "query": query or {}, "hook": hook, "call": cid}
    if isinstance(payload, dict):
        ctx.update(payload)
    return ctx


# ---- execution -----------------------------------------------------------------------------
def execute(hid: str, cid: str, units: bool = True) -> dict | None:
    """Run the action of one recorded call; -> its final record. `units`: a shell action runs in a systemd unit
    when available (the server), else inline (tests, the CLI)."""
    try:
        h = get(hid)
    except WebhookError:
        return None
    rec = _update_record(hid, cid, status="running", started=_now())
    if rec is None:
        return None
    start = _now()
    a = h["action"]
    try:
        if a["kind"] == "shell":
            res = _shell(h, cid, units)
        elif a["kind"] == "call":
            res = _call(h, cid)
        elif a["kind"] == "store":
            res = _store_row(h, cid)
        else:
            res = _notify(h, cid)
    except Exception as e:  # noqa: BLE001
        log.exception("webhook %s: call %s", hid, cid)
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    fields = {"status": "ok" if res.get("ok") else "failed", "duration_s": round(_now() - start, 3),
              "ended": _now(), **{k: v for k, v in res.items() if k != "ok"}}
    rec = _update_record(hid, cid, **fields)
    _changed()
    if rec:
        _report(h, rec)
    return rec


def _env(h: dict, cid: str, req: dict) -> dict[str, str]:
    from . import crons
    env = crons._job_env({"id": h["id"], "name": h["name"]})
    env.pop("MAXXING_CRON_ID", None)
    env.pop("MAXXING_CRON_NAME", None)
    d = call_dir(h["id"], cid)
    files = req.get("files") or []
    env.update({
        "MAXXING_WEBHOOK_ID": h["id"], "MAXXING_WEBHOOK_NAME": h["name"], "MAXXING_WEBHOOK_CALL": cid,
        "MAXXING_WEBHOOK_TRIGGER": h["trigger"]["kind"] if h["trigger"]["kind"] == "event" else "in",
        "MAXXING_WEBHOOK_EVENT": str(req.get("event") or ""), "MAXXING_WEBHOOK_METHOD": str(req.get("method") or ""),
        "MAXXING_WEBHOOK_BODY": str(d / "body"), "MAXXING_WEBHOOK_PAYLOAD": str(d / "payload.json"),
        "MAXXING_WEBHOOK_HEADERS": str(d / "request.json"),
        "MAXXING_WEBHOOK_QUERY": json.dumps(req.get("query") or {}, ensure_ascii=False)[:8000],
        "MAXXING_WEBHOOK_FILES": str(d / "files") if files else "",
        "MAXXING_RESPONSE_FILE": str(d / "response"),
    })
    return env


def run_shell(hid: str, cid: str) -> int:
    """`maxxing webhooks run <id> <call>`: run a shell action and write result.json (in its unit, or inline)."""
    from . import crons
    h = get(hid)
    a = h["action"]
    d = call_dir(hid, cid)
    req = config.read_json(d / "request.json", {}) or {}
    cwd = Path(a.get("cwd") or "") if a.get("cwd") else config.workspace()
    for name in ("response", "response.type", "stdout", "result.json"):
        with contextlib.suppress(OSError):
            (d / name).unlink()
    start = _now()
    try:
        stdin = open(d / "body", "rb")
    except OSError:
        stdin = subprocess.DEVNULL                      # type: ignore[assignment]
    try:
        proc = subprocess.Popen(["bash", "-lc", a["command"]], stdin=stdin, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=_env(h, cid, req),
                                cwd=str(cwd) if cwd.is_dir() else None, start_new_session=True)
    except OSError as e:
        config.write_json(d / "result.json", {"ok": False, "exit": 127, "error": f"cannot start bash: {e}", "output": ""})
        return 127
    finally:
        if stdin is not subprocess.DEVNULL:
            stdin.close()
    out_tail, err_tail = bytearray(), bytearray()
    kept = [0]

    def pump_out() -> None:
        assert proc.stdout is not None
        with open(d / "stdout", "wb") as f:
            for chunk in iter(lambda: proc.stdout.read1(65536), b""):
                if kept[0] < STDOUT_MAX:
                    part = chunk[:STDOUT_MAX - kept[0]]
                    f.write(part)
                    kept[0] += len(part)
                out_tail.extend(chunk)
                del out_tail[:-OUTPUT_TAIL]

    def pump_err() -> None:
        assert proc.stderr is not None
        for chunk in iter(lambda: proc.stderr.read1(65536), b""):
            err_tail.extend(chunk)
            del err_tail[:-OUTPUT_TAIL]
    readers = [threading.Thread(target=pump_out, daemon=True), threading.Thread(target=pump_err, daemon=True)]
    for r in readers:
        r.start()
    timeout = int(a.get("timeout_s") or SHELL_TIMEOUT)
    timed_out = False
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        crons._kill_group(proc)
        code = 124
    except BaseException:
        crons._kill_group(proc)
        raise
    for r in readers:
        r.join(timeout=2)
    out = bytes(out_tail).decode("utf-8", "replace")
    err = bytes(err_tail).decode("utf-8", "replace")
    text = (out + ("\n" if out and err else "") + err).strip()
    if timed_out:
        text += f"\n[timed out after {timeout} s]"
    res = {"ok": code == 0, "exit": code, "output": text[-OUTPUT_TAIL:], "duration_s": round(_now() - start, 3)}
    if code != 0:
        res["error"] = "timed out" if timed_out else f"exit code {code}"
    config.write_json(d / "result.json", res)
    return code


def _unit(hid: str, cid: str) -> str:
    return f"maxxing-hook-{hid.replace('_', '-')}-{cid}"


def _shell(h: dict, cid: str, units: bool) -> dict:
    from . import crons
    d = call_dir(h["id"], cid)
    if units and crons.units_available():
        cmd = [sys.executable, "-m", "maxxing", "webhooks", "run", h["id"], cid]
        env_args = [f"--setenv={k}={v}" for k, v in os.environ.items() if k.startswith("MAXXING_")]
        try:
            subprocess.run(["systemd-run", "--wait", "--collect", "--quiet", "--unit", _unit(h["id"], cid),
                            "--description", f"Harness Maxxing webhook {h['id']}",
                            *crons.unit_properties({"timeout_s": h["action"].get("timeout_s") or SHELL_TIMEOUT}),
                            *env_args, "--", *cmd],
                           capture_output=True, text=True, timeout=int(h["action"].get("timeout_s") or SHELL_TIMEOUT) + 180)
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"ok": False, "error": f"cannot run the unit: {e}"[:300]}
    else:
        run_shell(h["id"], cid)
    res = config.read_json(d / "result.json", None)
    if not isinstance(res, dict):
        return {"ok": False, "error": "the command left no result (stopped?)"}
    res.pop("duration_s", None)
    return res


def _call(h: dict, cid: str) -> dict:
    import httpx
    a = h["action"]
    ctx, req, raw = _context(h, cid)
    headers = {k: render(v, ctx, keys=True) for k, v in a.get("headers", {}).items()}
    lower = {k.lower() for k in headers}
    body: bytes | None
    if a["method"] == "GET":
        body = None
    elif a["body"] == "raw":
        body = raw
        if "content-type" not in lower and req.get("content_type"):
            headers["Content-Type"] = req["content_type"]
    elif a["body"] == "json":
        body = json.dumps(ctx.get("payload"), ensure_ascii=False).encode("utf-8")
        if "content-type" not in lower:
            headers["Content-Type"] = "application/json"
    else:
        tpl = a["body"]
        is_json = tpl.lstrip()[:1] in ("{", "[")
        body = render(tpl, ctx, json_mode=is_json).encode("utf-8")
        if "content-type" not in lower:
            headers["Content-Type"] = "application/json" if is_json else "text/plain; charset=utf-8"
    if a.get("sign") and body is not None:
        key = sign_secret(h["id"])
        if key:
            headers["X-Harness-Signature"] = "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    headers.setdefault("User-Agent", "Harness-Maxxing-Webhooks")
    url = render(a["url"], {}, keys=True)
    if not re.match(r"^https?://[^\s/?#]+", url):
        return {"ok": False, "error": "the URL (or the vault key holding it) is not an http(s) address"}
    d = call_dir(h["id"], cid)
    attempts, last_err, resp = 0, "", None
    for attempt in range(int(a.get("retries") or 0) + 1):
        attempts = attempt + 1
        if attempt:
            time.sleep(min(30, 2 ** attempt))
        try:
            with httpx.Client(timeout=a.get("timeout_s") or CALL_TIMEOUT, follow_redirects=False) as c:
                resp = c.request(a["method"], url, headers=headers, content=body)
        except httpx.HTTPError as e:
            last_err, resp = f"{type(e).__name__}: {e}"[:300], None
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            last_err = f"HTTP {resp.status_code}"
            continue
        break
    if resp is None:
        return {"ok": False, "error": last_err or "no answer", "attempts": attempts}
    data = resp.content[:STDOUT_MAX]
    (d / "response").write_bytes(data)
    (d / "response.type").write_text(resp.headers.get("content-type", "application/octet-stream")[:200])
    ok = resp.status_code < 400
    snippet = data[:OUTPUT_TAIL].decode("utf-8", "replace") if _is_text(data[:OUTPUT_TAIL]) else f"[{len(data)} bytes]"
    out = {"ok": ok, "http": resp.status_code, "output": snippet, "attempts": attempts}
    if not ok:
        out["error"] = f"HTTP {resp.status_code}"
    return out


def _notify_source(h: dict) -> str:
    from . import feed
    try:
        s = feed.clean_source(h["name"])
    except Exception:  # noqa: BLE001
        return "webhooks"
    return "webhooks" if s in feed.BUILTIN or s in feed.PRODUCT_SOURCES else s


def _notify(h: dict, cid: str) -> dict:
    from . import feed
    a = h["action"]
    ctx, req, _ = _context(h, cid)
    title, body, level, url = render(a.get("title") or "", ctx), render(a.get("body") or "", ctx), a.get("level") or "", \
        render(a.get("url") or "", ctx)
    t = h["trigger"]
    if not title and t["kind"] == "in" and t["source"] in ("stripe", "shopify", "github", "generic"):
        from .feedhooks import PARSERS
        hdr = {"x-shopify-topic": req.get("event", ""), "x-github-event": req.get("event", "")}
        ev = PARSERS[t["source"]](ctx["payload"] if isinstance(ctx.get("payload"), dict) else {}, hdr)
        if ev:
            title, body = title or ev[0], body or ev[1]
            level, url = level or ev[2], url or ev[3]
    if not title:
        title = ctx.get("title") if t["kind"] == "event" and isinstance(ctx.get("title"), str) else h["name"]
    hops = int((ctx.get("hops") or 0)) + 1 if t["kind"] == "event" else 0
    ev = feed.post(str(title)[:200], str(body)[:4000], level or "info", _notify_source(h), url, hops=hops)
    return {"ok": True, "output": f"notification {ev['id'] if ev else '(duplicate)'}"}


# ---- store ---------------------------------------------------------------------------------
def _db(hid: str) -> sqlite3.Connection:
    c = sqlite3.connect(_dir("data") / f"{hid}.db", timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE IF NOT EXISTS rows (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, "
              "call TEXT, data TEXT NOT NULL)")
    c.execute("CREATE INDEX IF NOT EXISTS rows_at ON rows(at)")
    return c


def _store_row(h: dict, cid: str) -> dict:
    ctx, _, _ = _context(h, cid)
    data = ctx["payload"]
    with contextlib.closing(_db(h["id"])) as c, c:
        cur = c.execute("INSERT INTO rows(at, call, data) VALUES (?,?,?)",
                        (_now(), cid, json.dumps(data, ensure_ascii=False)))
        rid = cur.lastrowid
        keep = int(h["action"].get("keep") or DEFAULT_KEEP)
        c.execute("DELETE FROM rows WHERE id <= ?", ((rid or 0) - keep,))
    _changed()
    return {"ok": True, "output": f"row {rid}"}


def _row(h: dict, r: tuple) -> dict:
    try:
        data = json.loads(r[3])
    except ValueError:
        data = None
    out = {"id": r[0], "at": r[1], "call": r[2], "data": data}
    fields = h["action"].get("fields") or {}
    if fields:
        ctx = _ctx(data)
        out["fields"] = {k: _lookup(ctx, p) for k, p in fields.items()}
    return out


def data(hid: str, after: int = 0, limit: int = 100) -> list[dict]:
    h = get(hid)
    if h["action"]["kind"] != "store" or not (_dir("data") / f"{hid}.db").exists():
        return []
    limit = max(1, min(int(limit), 1000))
    with contextlib.closing(_db(hid)) as c:
        if after:
            rows = c.execute("SELECT id, at, call, data FROM rows WHERE id > ? ORDER BY id LIMIT ?", (after, limit)).fetchall()
        else:
            rows = list(reversed(c.execute("SELECT id, at, call, data FROM rows ORDER BY id DESC LIMIT ?", (limit,)).fetchall()))
    return [_row(h, r) for r in rows]


def data_stats(hid: str) -> dict:
    p = _dir("data") / f"{hid}.db"
    if not p.exists():
        return {"rows": 0, "today": 0, "days": [0] * 7, "last_id": 0}
    from . import crons
    zone = crons.tz()
    today = dt.datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    starts = [(today - dt.timedelta(days=i)).timestamp() for i in range(6, -1, -1)]
    with contextlib.closing(_db(hid)) as c:
        rows, last = c.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM rows").fetchone()
        days = [c.execute("SELECT COUNT(*) FROM rows WHERE at >= ? AND at < ?",
                          (s, starts[i + 1] if i + 1 < len(starts) else s + 86400)).fetchone()[0]
                for i, s in enumerate(starts)]
    return {"rows": rows, "today": days[-1], "days": days, "last_id": last}


def _scalar_keys(rows: list[dict]) -> list[str]:
    keys: list[str] = []
    for r in rows[-200:]:
        if isinstance(r.get("data"), dict):
            for k, v in r["data"].items():
                if k not in keys and not isinstance(v, (dict, list)) and len(keys) < 30:
                    keys.append(k)
    return keys


def data_csv(hid: str, limit: int = 100_000) -> str:
    import csv
    import io
    h = get(hid)
    rows = _all_rows(hid, limit)
    fields = h["action"].get("fields") or {}
    cols = list(fields) or _scalar_keys(rows)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "at"] + cols)
    for r in rows:
        vals = r.get("fields") if fields else (r.get("data") if isinstance(r.get("data"), dict) else {})
        w.writerow([r["id"], dt.datetime.fromtimestamp(r["at"]).isoformat(timespec="seconds")] +
                   ["" if (vals or {}).get(c) is None else (json.dumps(vals[c], ensure_ascii=False)
                    if isinstance(vals[c], (dict, list)) else vals[c]) for c in cols])
    return buf.getvalue()


def _all_rows(hid: str, limit: int) -> list[dict]:
    h = get(hid)
    if not (_dir("data") / f"{hid}.db").exists():
        return []
    with contextlib.closing(_db(hid)) as c:
        rows = list(reversed(c.execute("SELECT id, at, call, data FROM rows ORDER BY id DESC LIMIT ?", (limit,)).fetchall()))
    return [_row(h, r) for r in rows]


# ---- reports -------------------------------------------------------------------------------
def _report(h: dict, rec: dict) -> None:
    ok = rec.get("status") == "ok"
    if not ok:
        from . import feed
        feed.system(f"Webhook failed: {h['name']}", (rec.get("error") or "") + ("\n\n" + rec["output"][-600:] if rec.get("output") else ""),
                    "error", "webhooks", f"/settings/{'events' if h['trigger']['kind'] == 'event' else 'webhooks'}?hook={h['id']}",
                    group=f"wh-fail-{h['id']}")
    policy = h.get("report") or "fail"
    if policy == "never" or (policy == "fail" and ok):
        return
    header = f"{'OK' if ok else 'FAILED'} - webhook {h['name']} ({rec.get('summary') or rec.get('event') or ''})".strip()
    with contextlib.suppress(Exception):
        from .telegram import gateway
        gateway.notify_cron_report(header, (rec.get("output") or rec.get("error") or "")[-1200:], markdown=False, loud=not ok)


# ---- replay / test -------------------------------------------------------------------------
_SAMPLES: dict[str, tuple[dict, dict]] = {
    "stripe": ({"id": "evt_test", "type": "checkout.session.completed",
                "data": {"object": {"amount_total": 4900, "currency": "eur", "customer_details": {"email": "buyer@example.com"}}}}, {}),
    "shopify": ({"id": 1001, "name": "#1001", "total_price": "49.00", "currency": "EUR", "email": "buyer@example.com"},
                {"X-Shopify-Topic": "orders/create"}),
    "github": ({"ref": "refs/heads/main", "repository": {"full_name": "acme/blog"},
                "head_commit": {"message": "Test commit"}, "commits": [{"message": "Test commit"}]}, {"X-GitHub-Event": "push"}),
    "generic": ({"title": "Test", "body": "If you can read this, the webhook works."}, {}),
    "phone": ({"text": "Test sent from the Webhooks page"}, {}),
    "feed": ({"id": 0, "title": "Test notification", "body": "If you can read this, the event works.", "level": "info",
              "source": "test", "url": ""}, {}),
    "agent": ({"agent": "acme/blog/agents/writer", "ok": True, "text": "Test run of the agent."}, {}),
    "cron": ({"cron": "c_test", "name": "Test job", "ok": True, "exit": 0, "output": "test"}, {}),
}


def _prepare_copy(hid: str, src: str) -> str:
    h = get(hid)
    s = call_dir(hid, src)
    if not s.is_dir():
        raise WebhookError(404, "not_found", "That call is no longer kept")
    old = next((r for r in _records(hid) if r["id"] == src), {})
    cid = _new_cid()
    d = call_dir(hid, cid)
    d.mkdir(parents=True, exist_ok=True)
    for name in ("body", "payload.json"):
        if (s / name).exists():
            shutil.copy2(s / name, d / name)
    req = config.read_json(s / "request.json", {}) or {}
    if (s / "files").is_dir():
        shutil.copytree(s / "files", d / "files")
        for f in req.get("files") or []:
            f["path"] = str(d / "files" / f["name"])
    config.write_json(d / "request.json", req)
    _add_record(hid, {"id": cid, "at": _now(), "trigger": "replay", "event": old.get("event") or req.get("event", ""),
                      "summary": old.get("summary") or h["name"], "status": "queued", "of": src})
    return cid


def _prepare_test(hid: str) -> str:
    h = get(hid)
    t = h["trigger"]
    key = t["source"] if t["kind"] == "in" else t["on"]
    payload, headers = _SAMPLES[key]
    body = json.dumps(payload).encode()
    event, _ = event_name(t["source"], payload, headers) if t["kind"] == "in" else (f"{key}:test", "")
    cid = _new_cid()
    _save_request(hid, cid, method="POST" if t["kind"] == "in" else "EVENT",
                  headers={"Content-Type": "application/json", **headers}, query={}, body=body, files=[],
                  payload=payload, event=event, extra={"test": True})
    _add_record(hid, {"id": cid, "at": _now(), "trigger": "test", "event": event,
                      "summary": _summary(t.get("source", ""), event, payload, "POST") if t["kind"] == "in" else payload.get("title") or key,
                      "status": "queued"})
    return cid


def replay(hid: str, cid: str, inline: bool = False) -> dict:
    new = _prepare_copy(hid, cid)
    return _go(hid, new, inline)


def test(hid: str, inline: bool = False) -> dict:
    new = _prepare_test(hid)
    return _go(hid, new, inline)


def _go(hid: str, cid: str, inline: bool) -> dict:
    _changed()
    if inline:
        return execute(hid, cid, units=False) or {}
    dispatcher.submit(hid, cid)
    return {"id": cid, "status": "queued"}


# ---- dispatcher (server) -------------------------------------------------------------------
class Dispatcher:
    """Per hook: `parallel` calls at a time, the others wait in order. Lives in the server process."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running: dict[str, int] = {}
        self.waiting: dict[str, deque] = {}
        self.done: dict[str, threading.Event] = {}
        self.sync = 0

    def has_room(self, h: dict) -> bool:
        with self.lock:
            busy = self.running.get(h["id"], 0) >= h["queue"]["parallel"]
            return not busy or len(self.waiting.get(h["id"], ())) < h["queue"]["max_waiting"]

    def sync_slot(self) -> bool:
        with self.lock:
            if self.sync >= SYNC_MAX:
                return False
            self.sync += 1
            return True

    def sync_release(self) -> None:
        with self.lock:
            self.sync = max(0, self.sync - 1)

    def submit(self, hid: str, cid: str, wait: bool = False) -> None:
        try:
            parallel = get(hid)["queue"]["parallel"]
        except WebhookError:
            return
        with self.lock:
            if wait:
                self.done[cid] = threading.Event()
            if self.running.get(hid, 0) < parallel:
                self.running[hid] = self.running.get(hid, 0) + 1
                start = True
            else:
                self.waiting.setdefault(hid, deque()).append(cid)
                start = False
        if start:
            threading.Thread(target=self._work, args=(hid, cid), name=f"webhook-{hid}", daemon=True).start()

    def _work(self, hid: str, cid: str) -> None:
        while cid:
            try:
                execute(hid, cid)
            except Exception:  # noqa: BLE001
                log.exception("webhook %s: call %s", hid, cid)
                with contextlib.suppress(Exception):
                    _update_record(hid, cid, status="failed", error="internal error")
            with self.lock:
                ev = self.done.pop(cid, None)
                q = self.waiting.get(hid)
                cid = q.popleft() if q else ""
                if not cid:
                    self.running[hid] = max(0, self.running.get(hid, 1) - 1)
            if ev:
                ev.set()

    def wait(self, cid: str, timeout: float) -> bool:
        with self.lock:
            ev = self.done.get(cid)
        if ev is None:
            return True
        ok = ev.wait(timeout)
        if not ok:
            with self.lock:
                self.done.pop(cid, None)
        return ok

    def idle(self) -> bool:
        with self.lock:
            return not any(self.running.values()) and not any(self.waiting.values())


dispatcher = Dispatcher()


def reply_of(hid: str, cid: str) -> tuple[int, bytes, str]:
    """The answer to a caller that waited: (status, body, content type)."""
    rec = next((r for r in _records(hid) if r["id"] == cid), None) or {}
    d = call_dir(hid, cid)
    h = get(hid)
    if rec.get("status") not in ("ok", "failed"):
        return 504, json.dumps({"ok": False, "error": "timeout", "call": cid}).encode(), "application/json"
    kind = h["action"]["kind"]
    if kind == "call" and (d / "response").exists():
        ctype = (d / "response.type").read_text()[:200] if (d / "response.type").exists() else "application/octet-stream"
        status = int(rec.get("http") or (200 if rec.get("status") == "ok" else 502))
        return (status if 200 <= status < 600 else 502), _read_bytes(d / "response"), ctype
    if rec.get("status") != "ok":
        return 502, json.dumps({"ok": False, "error": "failed", "call": cid, "exit": rec.get("exit")}).encode(), "application/json"
    if kind == "shell":
        resp = d / "response"
        data = _read_bytes(resp) if resp.exists() else _read_bytes(d / "stdout")
        ctype = (d / "response.type").read_text().strip()[:200] if (d / "response.type").exists() else _sniff(data)
        if not data:
            return 200, json.dumps({"ok": True, "call": cid}).encode(), "application/json"
        return 200, data, ctype
    return 200, json.dumps({"ok": True, "call": cid, "output": rec.get("output", "")}).encode(), "application/json"


def _sniff(data: bytes) -> str:
    head = data[:16]
    for magic, ctype in ((b"\x89PNG", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF8", "image/gif"),
                         (b"%PDF", "application/pdf")):
        if head.startswith(magic):
            return ctype
    if head[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    s = data.strip()
    if s[:1] in (b"{", b"["):
        with contextlib.suppress(ValueError, UnicodeDecodeError):
            json.loads(s.decode("utf-8"))
            return "application/json"
    return "text/plain; charset=utf-8" if _is_text(data) else "application/octet-stream"


def recover() -> int:
    """At start: queued calls go back to the queue; a call left running finishes from its result, or fails."""
    from . import crons
    n = 0
    for h in _load():
        for r in _records(h["id"]):
            if r.get("status") == "queued":
                dispatcher.submit(h["id"], r["id"])
                n += 1
            elif r.get("status") == "running":
                d = call_dir(h["id"], r["id"])
                res = config.read_json(d / "result.json", None)
                if h["action"]["kind"] == "shell" and not isinstance(res, dict) and crons.units_available() and _unit_active(h["id"], r["id"]):
                    threading.Thread(target=_finish_later, args=(h["id"], r["id"]), daemon=True).start()
                    continue
                if isinstance(res, dict) and h["action"]["kind"] == "shell":
                    _update_record(h["id"], r["id"], status="ok" if res.get("ok") else "failed",
                                   **{k: v for k, v in res.items() if k in ("exit", "output", "error")})
                else:
                    _update_record(h["id"], r["id"], status="failed", error="interrupted (the server restarted)")
                n += 1
    return n


def _unit_active(hid: str, cid: str) -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", "--quiet", _unit(hid, cid) + ".service"], timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _finish_later(hid: str, cid: str) -> None:
    while _unit_active(hid, cid):
        time.sleep(5)
    res = config.read_json(call_dir(hid, cid) / "result.json", None)
    if isinstance(res, dict):
        _update_record(hid, cid, status="ok" if res.get("ok") else "failed",
                       **{k: v for k, v in res.items() if k in ("exit", "output", "error")})
    else:
        _update_record(hid, cid, status="failed", error="interrupted")
    _changed()


def counts() -> dict:
    hooks = _load()
    return {"webhooks": sum(1 for h in hooks if h["trigger"]["kind"] == "in"),
            "events": sum(1 for h in hooks if h["trigger"]["kind"] == "event")}
