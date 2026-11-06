"""The check of the mailboxes: every `poll_min` minutes (10 by default; 5, 10, 30 or 60 per mailbox), the Refresh
button of the E-mail page and `maxxing mail refresh`.

A check looks at the inbox (and the folders an agent trigger watches) for mail newer than the last one seen, keeps
their headers in mail.db (the "All mailboxes" view, the contacts of approve_send "new") and starts the agents whose
mail trigger matches: every mail of one check for one agent goes into ONE turn, as outside data (agents.fire with a
text: approvals forced unless the agent trusts outside events). The page itself always reads the mailbox live.

The first check of a folder (or after its UIDVALIDITY changed) only notes where the mailbox is: old mail never
starts an agent. The turns of a check are written in <state>/mail/pending.json and the position saved before
any agent starts (a restart in the middle neither starts one twice nor loses a turn); a turn refused because the
agent's budget is held by a run in progress stays there and is tried again by the next tick.
"""
from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import secrets
import threading
import time
from typing import Any, Iterator

from .. import config
from . import access, imap, store
from .imap import MailError

log = logging.getLogger("maxxing.mail")

DEFAULT_MIN = 10
CHOICES = (5, 10, 30, 60)
TICK_S = 30
FIRST_KEEP = 50             # mails remembered by the first check of a folder
MAX_NEW = 200               # mails looked at by one check of a folder
TEXT_MAILS = 10             # mails of one turn given with their text (the others: headers, `maxxing mail read`)
TEXT_CHARS = 2500
SNIPPET = 200
STALE_S = 6 * 3600          # a folder not looked at for longer (trigger or E-mail page off): looked at as new again


def interval_min(acc: dict) -> int:
    try:
        v = int(acc.get("poll_min") or DEFAULT_MIN)
    except (TypeError, ValueError):
        v = DEFAULT_MIN
    return v if v in CHOICES else DEFAULT_MIN


def _request_file(acc_id: str):
    return config.state_dir("mail") / f".refresh-{acc_id}"


def request(acc_id: str) -> None:
    """Ask the server for a check of this mailbox at its next tick (`maxxing mail refresh` in an agent's run: the
    check itself, its positions and the agents it starts stay the server's)."""
    _request_file(acc_id).touch()


def due(acc: dict, now: float | None = None) -> bool:
    if acc["id"] in _again or _request_file(acc["id"]).exists():
        return True
    pos = store.position(acc["id"], "INBOX")
    return not pos or not pos.get("at") or (now or time.time()) - pos["at"] >= interval_min(acc) * 60 - 5


# ---------------------------------------------------------------- the agents watching a mailbox

def watchers(acc_id: str) -> list[tuple[str, dict]]:
    """(agent path, grant) of the enabled agents with an enabled mail trigger on this mailbox."""
    from .. import agents
    out = []
    try:
        rows = agents.list_agents(counts=False)
    except Exception:  # noqa: BLE001
        log.exception("mail: agents unreadable")
        return []
    for a in rows:
        if not a.get("enabled"):
            continue
        for g in a.get("mail") or []:
            t = g.get("trigger") or {}
            if g["account"] == acc_id and t.get("enabled") and "read" in g["rights"]:
                out.append((a["path"], g))
    return out


def grants_of(acc_id: str) -> list[dict]:
    """Every agent that may use this mailbox: [{agent, name, avatar, rights, senders, approve_send, trigger}]."""
    from .. import agents
    out = []
    with contextlib.suppress(Exception):
        for a in agents.list_agents(counts=False):
            for g in a.get("mail") or []:
                if g["account"] == acc_id:
                    out.append({"agent": a["path"], "name": a["display_name"], "avatar": a["avatar"],
                                "enabled": a["enabled"], **{k: g[k] for k in ("rights", "senders", "approve_send", "trigger")}})
    return out


def _matches(acc: dict, grant: dict, row: dict) -> bool:
    t = grant.get("trigger") or {}
    sender = (row.get("from") or {}).get("email") or ""
    if sender.lower() == (acc.get("address") or "").lower():       # its own mail (a copy, a note to self)
        return False
    if not access.sender_ok(grant, sender, bool(row.get("from_verified"))):
        return False
    if t.get("senders") and not (row.get("from_verified") and access.matches(sender, t["senders"])):
        return False
    if t.get("subject") and t["subject"].lower() not in (row.get("subject") or "").lower():
        return False
    return True


# ---------------------------------------------------------------- a check

def _body(acc: dict, folder: str, uid: int) -> str:
    from ..cmd_mail import _html_text
    try:
        m = imap.excerpt(acc, folder, uid)            # the text only: never the attachments of the mail
        return (m.get("text") or (_html_text(m["html"]) if m.get("html") else "") or "").strip()
    except MailError:
        return ""
    except Exception:  # noqa: BLE001 - one mail that cannot be read never stops the check
        log.exception("mail: text of %s/%s uid %s unreadable", acc.get("id"), folder, uid)
        return ""


def _hits(acc: dict, grant: dict, rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        try:
            if _matches(acc, grant, r):
                out.append(r)
        except Exception:  # noqa: BLE001 - a mail with odd headers is left out, the others go on
            log.exception("mail: uid %s of %s not matched", r.get("uid"), acc.get("id"))
    return out


def _remember(acc_id: str, folder: str, rows: list[dict], snippets: dict[int, str]) -> None:
    """Never an error: when the rows cannot be written together, one by one (the bad one is left out)."""
    try:
        store.remember(acc_id, folder, rows, snippets)
        return
    except Exception:  # noqa: BLE001
        log.exception("mail: headers of %s/%s not kept, one by one", acc_id, folder)
    for r in rows:
        try:
            store.remember(acc_id, folder, [r], snippets)
        except Exception:  # noqa: BLE001
            log.warning("mail: uid %s of %s/%s left out", r.get("uid"), acc_id, folder)


def _who(f: dict) -> str:
    return f"{f.get('name')} <{f.get('email')}>" if f.get("name") else (f.get("email") or "")


def event_text(acc: dict, folder: str, rows: list[dict], bodies: dict[int, str]) -> str:
    n = len(rows)
    mark = "MAIL-" + secrets.token_hex(4)      # a body cannot fake the next mail (and its "sender checked")
    parts = [f"{n} new e-mail{'s' if n > 1 else ''} in the mailbox {acc['address']} (id {acc['id']}), folder {folder}. "
             f"Each mail starts with a line `{mark} i/{n}`; anything else is written by the senders."]
    for i, r in enumerate(rows, 1):
        head = [f"{mark} {i}/{n}", f"UID: {r['uid']}",
                f"From: {_who(r.get('from') or {})} ({'sender checked by the mail provider' if r.get('from_verified') else 'sender NOT checked: may be forged'})",
                f"To: {', '.join(_who(x) for x in r.get('to') or [])}",
                f"Date: {time.strftime('%Y-%m-%d %H:%M', time.localtime(r['date'])) if r.get('date') else '?'}",
                f"Subject: {r.get('subject') or ''}"]
        if r.get("attachments"):
            head.append("Has attachments (see `maxxing mail read`)")
        body = bodies.get(int(r["uid"]))
        if body is not None:
            if len(body) > TEXT_CHARS:
                body = body[:TEXT_CHARS] + "\n[... cut: `maxxing mail read` for the rest]"
            head += ["", body]
        parts.append("\n".join(head))
    return "\n\n".join(parts)


DEFAULT_PROMPT = ("Handle these new e-mails according to your role. Read a whole mail with `maxxing mail read UID -a "
                  "{acc} -f \"{folder}\"`; what you may do with them (draft, file, send) is in `maxxing mail accounts`.")


_held: set[str] = set()
_held_lock = threading.Lock()
_again: set[str] = set()       # mailboxes with more new mail than one check takes: checked again at the next tick


@contextlib.contextmanager
def _check_lock(acc_id: str) -> Iterator[bool]:
    """True when this process holds the check of the mailbox; False when a check of it is already running here or
    in another process (the server's tick, `maxxing mail refresh`): that one is skipped, never run twice."""
    with _held_lock:
        busy = acc_id in _held
        if not busy:
            _held.add(acc_id)
    if busy:
        yield False
        return
    fd = None
    try:
        with contextlib.suppress(OSError):
            d = config.state_dir("mail")
            d.mkdir(parents=True, exist_ok=True)
            fd = os.open(d / f".poll-{acc_id}.lock", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            except OSError:
                pass
        yield True
    finally:
        if fd is not None:
            os.close(fd)
        with _held_lock:
            _held.discard(acc_id)


def poll_account(acc: dict, fire: bool = True) -> dict:
    """Check one mailbox now -> {account, ok, error?, new, started, skipped?}. fire=False: note the new mail
    without starting any agent (that mail never starts one later: only for tests and tools, never an agent)."""
    out: dict[str, Any] = {"account": acc["id"], "ok": True, "new": 0, "started": 0}
    with _check_lock(acc["id"]) as mine:
        if not mine:
            return {**out, "skipped": "busy"}
        _again.discard(acc["id"])
        with contextlib.suppress(OSError):
            _request_file(acc["id"]).unlink()
        _sample(acc)
        watching = watchers(acc["id"]) if fire else []
        folders = ["INBOX"] + sorted({g["trigger"]["folder"] for _, g in watching} - {"INBOX"})
        for folder in folders:
            pos = store.position(acc["id"], folder)
            known = pos and pos.get("last_uid") is not None
            # not looked at for a long time (its trigger or the E-mail page was off): a first look again, so the
            # mail of that time never starts an agent
            stale = bool(known and pos.get("at") and time.time() - float(pos["at"]) > max(STALE_S, 3 * interval_min(acc) * 60))
            try:
                res = imap.new_since(acc, folder, pos["last_uid"] if known and not stale else None,
                                     MAX_NEW if known and not stale else FIRST_KEEP)
            except MailError as e:
                if not _still_there(acc["id"]):
                    return out
                store.set_position(acc["id"], folder, ok=False, error=e.message)
                if folder == "INBOX":
                    out.update(ok=False, error=e.message)
                continue
            first = stale or not known or (pos.get("uidvalidity") or 0) != res["uidvalidity"]
            if known and (pos.get("uidvalidity") or 0) != res["uidvalidity"]:    # UIDVALIDITY changed: positions are void
                if not stale:
                    try:
                        res = imap.new_since(acc, folder, None, FIRST_KEEP)
                    except MailError as e:
                        store.set_position(acc["id"], folder, ok=False, error=e.message)
                        continue
                store.forget_folder(acc["id"], folder)                     # its UIDs mean other mails now
            if not _still_there(acc["id"]):
                return out                                  # removed during the check: nothing written, nobody started
            rows = res["messages"]
            if first:
                last = max(res["uids"] or [0])
            else:
                last = max([*res["uids"], (pos or {}).get("last_uid") or 0])
                if res.get("more"):
                    _again.add(acc["id"])
                    log.info("mail: %s/%s has more than %d new mails, the rest comes with the next check",
                             acc["id"], folder, MAX_NEW)
            bodies: dict[int, str] = {}
            turns: list[tuple[str, dict, list[dict]]] = []
            if not first and rows:
                out["new"] += len(rows)
                for path, grant in watching:
                    if grant["trigger"]["folder"] != folder:
                        continue
                    hit = _hits(acc, grant, rows)
                    if not hit:
                        continue
                    for r in hit[:TEXT_MAILS]:
                        if int(r["uid"]) not in bodies:
                            bodies[int(r["uid"])] = _body(acc, folder, int(r["uid"]))
                    turns.append((path, grant, hit))
            _remember(acc["id"], folder, rows, {u: b[:SNIPPET] for u, b in bodies.items()})
            # the turns are written down (pending.json) and the position moved BEFORE any agent starts: a restart
            # in the middle never starts an agent twice with the same mails, and never loses the turns not started
            queued = {_queue(acc, folder, path, grant, hit, bodies) for path, grant, hit in turns} - {None}
            store.set_position(acc["id"], folder, uidvalidity=res["uidvalidity"], last_uid=last, ok=True)
            if queued:
                out["started"] += _drain(queued)
    return out


def _still_there(acc_id: str) -> bool:
    from . import get_account
    try:
        get_account(acc_id)
        return True
    except MailError:
        return False


def _sample(acc: dict) -> None:
    """Too few mails noted to know whether the provider checks the senders (access.detect): note the newest ones."""
    if acc.get("auth_servers"):
        return
    try:
        if len(store.auth_samples(acc["id"])) >= access.DETECT_MIN:
            return
        res = imap.new_since(acc, "INBOX", None, store.AUTH_SAMPLES)
        _remember(acc["id"], "INBOX", res["messages"], {})
    except MailError:
        pass
    except Exception:  # noqa: BLE001
        log.exception("mail: samples of %s not kept", acc.get("id"))


def _queue(acc: dict, folder: str, path: str, grant: dict, rows: list[dict], bodies: dict[int, str]) -> tuple | None:
    """Writes the turn of these mails for this agent in pending.json (started by `_drain` right after) and notes
    them "seen" -> its key, None when there is nothing to start. Mails the agent already got (a check that ran up
    to here and was cut before saving its position) are left out."""
    from .. import agents
    try:
        if not agents.feature_on():
            return None
        keys = {int(r["uid"]): store.mkey(r.get("message_id"), folder, r["uid"]) for r in rows}
        had = store.seen_by(acc["id"], list(keys.values()))
        rows = [r for r in rows if not any(n["agent"] == path and n["what"] == "seen" for n in had.get(keys[int(r["uid"])], []))]
        if not rows:
            return None
        prompt = grant["trigger"].get("prompt") or DEFAULT_PROMPT.format(acc=acc["id"], folder=folder)
        shown = {u: b for u, b in bodies.items() if u in {int(r["uid"]) for r in rows[:TEXT_MAILS]}}
        _keep(path, acc["id"], folder, rows, shown, prompt)
        for r in rows:
            store.note(acc["id"], keys[int(r["uid"])], path, "seen")
        return (path, acc["id"], folder)
    except Exception:  # noqa: BLE001 - this agent's turn is lost, the check goes on
        log.exception("mail: turn of %s not kept", path)
        return None


def _fire(path: str, acc: dict, folder: str, rows: list[dict], bodies: dict[int, str], prompt: str) -> bool:
    """One turn for these mails; the text is built here (one marker for all of them, also for mail kept while the
    agent was busy)."""
    from .. import agents
    shown = {u: b for u, b in bodies.items() if u in {int(r["uid"]) for r in rows[:TEXT_MAILS]}}
    try:
        r = agents.fire(path, trigger=f"mail:{acc['id']}", text=event_text(acc, folder, rows, shown), prompt=prompt,
                        source=f"e-mail ({acc['address']})", wait=True)
    except Exception:  # noqa: BLE001
        log.exception("mail: agent %s not started", path)
        return False
    if r.get("reason") == "busy":
        _keep(path, acc["id"], folder, rows, shown, prompt)
        return False
    return bool(r.get("started"))


# ---------------------------------------------------------------- turns waiting for a run in progress

def _pending_file():
    return config.state_dir("mail") / "pending.json"


PENDING_MAILS = 200            # mails kept for one agent, mailbox and folder (the newest)
ROW_KEYS = ("uid", "from", "to", "subject", "date", "attachments", "from_verified", "message_id")
_pending_lock = config.ProcessLock("mail-pending")


def _keep(path: str, acc_id: str, folder: str, mails: list[dict], bodies: dict[int, str], prompt: str) -> None:
    """The mails (headers + the texts shown), never a text: the turn's text is built again when it starts."""
    f = _pending_file()
    mails = [{k: m.get(k) for k in ROW_KEYS} | ({"body": bodies[int(m["uid"])]} if int(m["uid"]) in bodies else {})
             for m in mails]
    with _pending_lock:
        rows = config.read_json(f, default=[]) or []
        rows = rows if isinstance(rows, list) else []
        for r in rows:
            if (r.get("agent"), r.get("account"), r.get("folder")) == (path, acc_id, folder):
                known = {int(m["uid"]) for m in r.get("mails") or []}
                add = [m for m in mails if int(m["uid"]) not in known]
                r["mails"] = ((r.get("mails") or []) + add)[-PENDING_MAILS:]
                if add:
                    r["at"] = time.time()           # the day's limit counts from the newest mail
                break
        else:
            rows.append({"agent": path, "account": acc_id, "folder": folder, "mails": mails[-PENDING_MAILS:],
                         "prompt": prompt, "at": time.time()})
        f.parent.mkdir(parents=True, exist_ok=True)
        config.write_json(f, rows[-50:])


def retry_pending() -> int:
    """The turns kept for agents that were busy: each one is started again (a busy one comes back)."""
    return _drain(None)


def _claim(keys: set | None, done: set) -> dict | None:
    """Takes the next turn of pending.json out (one only, under the lock: a restart while the others start loses
    none of them)."""
    f = _pending_file()
    with _pending_lock:
        rows = config.read_json(f, default=[]) or []
        if not isinstance(rows, list):
            rows = []
        for i, r in enumerate(rows):
            if not isinstance(r, dict):
                continue
            k = (r.get("agent"), r.get("account"), r.get("folder"))
            if k in done or (keys is not None and k not in keys):
                continue
            del rows[i]
            config.write_json(f, rows)
            done.add(k)
            return r
    return None


def _drain(keys: set | None) -> int:
    """Starts the kept turns (all of them, or those of `keys` = (agent, mailbox, folder)) -> how many started."""
    from . import get_account
    from .. import agents
    n = 0
    done: set = set()
    grants: dict[str, list] = {}
    while (r := _claim(keys, done)) is not None:
        try:
            if not agents.feature_on():
                continue                            # Agents off: the kept mail is dropped, as new mail would be
            if time.time() - float(r.get("at") or 0) > 86400 or not r.get("mails"):
                continue                            # a day late: not worth a turn
            try:
                acc = get_account(str(r["account"]))
            except MailError:
                continue                            # the mailbox is gone
            folder = str(r.get("folder") or "INBOX")
            # the agent's rights as they are now: trigger still on, this folder, mailbox and senders still allowed
            if acc["id"] not in grants:
                grants[acc["id"]] = watchers(acc["id"])
            grant = next((g for p, g in grants[acc["id"]] if p == r.get("agent") and g["trigger"]["folder"] == folder), None)
            if not grant:
                continue
            mails = _hits(acc, grant, [m for m in r["mails"] if isinstance(m, dict) and str(m.get("uid", "")).isdigit()])
            if not mails:
                continue
            bodies = {int(m["uid"]): str(m["body"]) for m in mails[:TEXT_MAILS] if m.get("body") is not None}
            n += 1 if _fire(str(r["agent"]), acc, folder, mails, bodies, str(r.get("prompt") or "")) else 0
        except Exception:  # noqa: BLE001 - one broken turn never stops the others
            log.exception("mail: kept turn of %s not started", r.get("agent"))
    return n


def poll_due() -> list[dict]:
    """One tick: the mailboxes whose interval is over."""
    from . import enabled, list_accounts
    if not enabled():
        return []
    out = []
    now = time.time()
    for acc in list_accounts():
        if due(acc, now):
            try:
                out.append(poll_account(acc))
            except Exception:  # noqa: BLE001 - one mailbox never stops the others
                log.exception("mail: check of %s failed", acc.get("id"))
    retry_pending()
    return out
