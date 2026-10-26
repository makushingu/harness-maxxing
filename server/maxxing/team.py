"""Team: plain chats between people (direct messages and groups), next to the sessions. See docs/dev/INTERNALS.md#maxxing.team.

Config `team_page` (off by default). The chats live in `<state>/team/team.json` and are also sent to the other
members' servers by `teampeer` (connections, signing, delivery); their events come back through `apply_remote()`. Nothing written in a chat ever reaches Claude by itself:
the user clicks "Summarize" (one `claude -p` call without tools on the messages shown) or "Send to a session" on a
message (the text goes to a session as a normal web message, quoted and labelled with its author).

Document: {"me": "me", "chats": [{id, kind: dm|group, name,
emoji, members: [ids], created, read_at, remote, admin, messages: [Message]}]}; Message = {id, author, at, text,
kind: text|summary|poll, reply_to?, files?: [{path, name, size, mime, fid?, pending?, failed?}], poll?: {question,
multi, options: [{id, label, votes: [ids]}]}, sent?: [{session, title, at}], reactions?: {emoji: [ids]}, pending?:
[ids not delivered yet], recv?: when it reached this server (messages of others: unread counts on it, not
on the sender's clock)}. People's ids are `teampeer.pid(address)` (the contacts: `teampeer.people()`).
"""
from __future__ import annotations

import json
import os
import re
import mimetypes
import secrets
import subprocess
import threading
import time
from pathlib import Path

import hashlib

from . import bus, config, teampeer

ME = "me"
TEXT_MAX = 8000
SUMMARY_MODEL = "claude-sonnet-5-5"
SUMMARY_TIMEOUT_S = 120
SUMMARY_MESSAGES = 200         # at most this many messages are summarized
FILES_MAX = 10                  # files per message
COLORS = ("clay", "blue", "violet", "green", "amber", "rose", "teal", "zinc")
_ID = re.compile(r"^[a-z]_[0-9a-f]{8,32}$")         # message and poll option ids (the same on every server)
REACTIONS = ("👍", "❤️", "😂", "🎉", "🤔", "👀")

_lock = threading.RLock()
_slots = threading.BoundedSemaphore(4)          # files of the others: 4 downloads at a time
_queued = [0]                                   # downloads started or waiting (at most QUEUE_MAX, the others fail)
QUEUE_MAX = 100


class TeamError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _path() -> Path:
    return config.state_dir("team") / "team.json"


def _load() -> dict:
    doc = config.read_json(_path(), None)
    if not isinstance(doc, dict):
        doc = {"me": ME, "chats": []}
    doc.setdefault("chats", [])
    return doc


def _save(doc: dict) -> None:
    config.write_json(_path(), doc)
    bus.invalidate("team")


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def _me() -> dict:
    from .api.settings import profile
    p = profile()
    lang = config.load_config().get("language") or "en"
    return {"name": p["name"] or ("Moi" if lang == "fr" else "Me"), "emoji": p["emoji"], "color": p["color"] or "blue",
            "server": "", "status": "online"}


def _chat(doc: dict, cid: str) -> dict:
    for c in doc["chats"]:
        if c["id"] == cid:
            return c
    raise TeamError(404, "not_found", "Chat not found")


def _message(chat: dict, mid: str) -> dict:
    for m in chat["messages"]:
        if m["id"] == mid:
            return m
    raise TeamError(404, "not_found", "Message not found")


def _summary(chat: dict, doc: dict) -> dict:
    msgs = chat["messages"]
    last = msgs[-1] if msgs else None
    read_at = chat.get("read_at", 0)
    unread = sum(1 for m in msgs if m["author"] != ME and m.get("recv", m["at"]) > read_at)
    return {k: v for k, v in chat.items() if k != "messages"} | {
        "last": ({"author": last["author"], "at": last["at"], "kind": last.get("kind", "text"),
                  "text": (last.get("poll") or {}).get("question") or last["text"][:140]
                  or ", ".join(f["name"] for f in last.get("files") or []),
                  "files": len(last.get("files") or [])} if last else None),
        "unread": unread,
        "updated": last["at"] if last else chat.get("created", 0),
    }


# ---- reading ------------------------------------------------------------------------------------------------
def state() -> dict:
    """People (the user under "me") and the chats, most recent first, without their messages."""
    with _lock:
        doc = _load()
        people = teampeer.people() | {ME: _me()}
        chats = sorted((_summary(c, doc) for c in doc["chats"]), key=lambda c: -c["updated"])
        return {"me": ME, "people": people, "chats": chats, "reactions": list(REACTIONS)}


def messages(cid: str) -> dict:
    with _lock:
        doc = _load()
        chat = _chat(doc, cid)
        return {"chat": _summary(chat, doc), "messages": chat["messages"]}


def mark_read(cid: str) -> None:
    with _lock:
        doc = _load()
        chat = _chat(doc, cid)
        chat["read_at"] = time.time()
        _save(doc)


# ---- writing ------------------------------------------------------------------------------------------------
def _post(cid: str, author: str, text: str, kind: str = "text", **extra) -> dict:
    with _lock:
        doc = _load()
        chat = _chat(doc, cid)
        msg = {"id": _id("m"), "author": author, "at": time.time(), "text": text, "kind": kind} | extra
        chat["messages"].append(msg)
        if author == ME:
            chat["read_at"] = msg["at"]
        _save(doc)
        return msg


def files_dir() -> Path:
    """Files sent in the chats: <workspace>/team/attachments/YYYY-MM/ (inside the files root: the viewer opens them)."""
    d = config.workspace() / "team" / "attachments" / time.strftime("%Y-%m")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clean_files(files: list[dict] | None) -> list[dict]:
    """Only files uploaded to the team folder (an uploaded file's path comes back from the browser)."""
    root = (config.workspace() / "team" / "attachments").resolve()
    out = []
    for f in (files or [])[:FILES_MAX]:
        p = Path(str((f or {}).get("path") or "")).resolve()
        if root not in p.parents or not p.is_file():
            raise TeamError(400, "bad_file", "Unknown file")
        out.append({"path": str(p), "name": p.name, "size": p.stat().st_size,
                    "mime": mimetypes.guess_type(p.name)[0] or "application/octet-stream"})
    return out


def send(cid: str, text: str, reply_to: str | None = None, files: list[dict] | None = None) -> dict:
    text = (text or "").strip()[:TEXT_MAX]
    clean = _clean_files(files)
    if not text and not clean:
        raise TeamError(400, "empty", "Empty message")
    extra = ({"reply_to": reply_to} if reply_to else {}) | ({"files": clean} if clean else {})
    with _lock:
        if _chat(_load(), cid).get("remote"):
            for f in clean:
                f["fid"] = teampeer.share_file(f["path"], cid, f)
    msg = _post(cid, ME, text, **extra)
    _broadcast(cid, msg)
    return msg


def dm_id(a: str, b: str) -> str:
    """The id of the direct chat between two addresses: the same on both servers."""
    return "d_" + hashlib.sha256("|".join(sorted((a, b))).encode()).hexdigest()[:16]


def create_chat(kind: str, members: list[str], name: str = "", emoji: str = "") -> dict:
    peers = {k: v for k, v in teampeer.people().items() if v.get("contact")}
    with _lock:
        doc = _load()
        members = [m for m in dict.fromkeys(members) if m in peers]
        if not members:
            raise TeamError(400, "no_members", "Choose at least one contact")
        if kind == "dm":
            members = members[:1]
            for c in doc["chats"]:
                if c["kind"] == "dm" and c["members"] == members:
                    return _summary(c, doc)
        cid = dm_id(teampeer.own_address(), peers[members[0]]["address"]) if kind == "dm" else "g_" + secrets.token_hex(8)
        chat = {"id": cid, "kind": kind, "name": (name or "").strip()[:60], "emoji": (emoji or "").strip()[:8],
                "members": members, "created": time.time(), "read_at": time.time(), "messages": [],
                "remote": True, "admin": ME if kind == "group" else None}
        doc["chats"].append(chat)
        _save(doc)
    if kind == "group":
        _send_group(chat, peers)
    return _summary(chat, _load())


def _send_group(chat: dict, peers: dict) -> None:
    """The group to every member, each with a key for every other member (they may not know each other)."""
    me = teampeer.own_address()
    addrs = [peers[m]["address"] for m in chat["members"]]
    pair = {}
    for i, a in enumerate(addrs):
        for b in addrs[i + 1:]:
            pair[(a, b)] = pair[(b, a)] = teampeer.new_pair_key()
    roster = [{"address": me, **teampeer._profile()}] + [
        {"address": peers[m]["address"], "name": peers[m]["name"], "emoji": peers[m]["emoji"], "color": peers[m]["color"]}
        for m in chat["members"]]
    for a in addrs:
        event = {"type": "chat", "chat": chat["id"], "kind": "group", "name": chat["name"], "emoji": chat["emoji"],
                 "admin": me, "members": roster, "keys": {b: pair[(a, b)] for b in addrs if b != a}}
        teampeer.send([a], event)


def _addresses(chat: dict) -> list[str]:
    people = teampeer.people()
    return [people[m]["address"] for m in chat["members"] if m in people]


def _wire(msg: dict) -> dict:
    """A message as sent to the other servers (no local paths)."""
    out = {k: msg[k] for k in ("id", "at", "text", "kind") if k in msg}
    if msg.get("poll"):
        out["poll"] = {"question": msg["poll"]["question"], "multi": msg["poll"].get("multi", False),
                       "options": [{"id": o["id"], "label": o["label"]} for o in msg["poll"]["options"]]}
    if msg.get("summary"):
        out["summary"] = {"count": msg["summary"].get("count", 0)}
    if msg.get("files"):
        out["files"] = [{"id": f["fid"], "name": f["name"], "size": f["size"], "mime": f["mime"]} for f in msg["files"] if f.get("fid")]
    return out


def _broadcast(cid: str, msg: dict | None = None, event: dict | None = None) -> None:
    """A new message of the user (or another event) to every member of a chat with real people."""
    with _lock:
        doc = _load()
        chat = _chat(doc, cid)
        if not chat.get("remote"):
            return
        addrs = _addresses(chat)
        if msg is not None:
            m = _message(chat, msg["id"])
            m["pending"] = [teampeer.pid(a) for a in addrs]
            msg["pending"] = list(m["pending"])      # the caller returns it: the clock shows at once
            _save(doc)
    ev = event or {"type": "message", "message": _wire(msg or {})}
    teampeer.send(addrs, ev | {"chat": cid}, msg["id"] if msg else None)


def delivered(cid: str, mid: str, who: str) -> None:
    with _lock:
        doc = _load()
        try:
            m = _message(_chat(doc, cid), mid)
        except TeamError:
            return
        if who in (m.get("pending") or []):
            m["pending"].remove(who)
            if not m["pending"]:
                m.pop("pending")
            _save(doc)


def is_member(cid: str, who: str) -> bool:
    with _lock:
        try:
            return who in _chat(_load(), cid)["members"]
        except TeamError:
            return False


def react(cid: str, mid: str, emoji: str) -> dict:
    if emoji not in REACTIONS:
        raise TeamError(400, "invalid_emoji", "Unknown reaction")
    with _lock:
        doc = _load()
        msg = _message(_chat(doc, cid), mid)
        who = msg.setdefault("reactions", {}).setdefault(emoji, [])
        who.remove(ME) if ME in who else who.append(ME)
        msg["reactions"] = {e: w for e, w in msg["reactions"].items() if w}
        _save(doc)
    _broadcast(cid, event={"type": "react", "msg": mid, "emoji": emoji, "on": ME in who})
    return msg


def create_poll(cid: str, question: str, options: list[str], multi: bool = False) -> dict:
    """A poll: one choice (round buttons) or several (`multi`, square boxes)."""
    question = (question or "").strip()[:200]
    opts = [o.strip()[:120] for o in options if o and o.strip()][:12]
    if not question or len(opts) < 2:
        raise TeamError(400, "invalid_poll", "A question and at least two options")
    poll = {"question": question, "multi": bool(multi), "options": [{"id": _id("o"), "label": o, "votes": []} for o in opts]}
    msg = _post(cid, ME, question, kind="poll", poll=poll)
    _broadcast(cid, msg)
    return msg


def vote(cid: str, mid: str, option: str) -> dict:
    """Toggle the user's vote on an option (one choice: the other votes of the user go)."""
    with _lock:
        doc = _load()
        msg = _message(_chat(doc, cid), mid)
        poll = msg.get("poll") or {}
        opt = next((o for o in poll.get("options", []) if o["id"] == option), None)
        if opt is None:
            raise TeamError(404, "not_found", "Option not found")
        if ME in opt["votes"]:
            opt["votes"].remove(ME)
        else:
            if not poll.get("multi"):
                for o in poll["options"]:
                    if ME in o["votes"]:
                        o["votes"].remove(ME)
            opt["votes"].append(ME)
        _save(doc)
    _broadcast(cid, event={"type": "vote", "msg": mid, "options": [o["id"] for o in poll["options"] if ME in o["votes"]]})
    return msg


def mark_sent(cid: str, mid: str, session: str, title: str) -> dict:
    with _lock:
        doc = _load()
        msg = _message(_chat(doc, cid), mid)
        msg.setdefault("sent", []).append({"session": session, "title": title[:120], "at": time.time()})
        _save(doc)
        return msg


def _post_shared(cid: str, text: str, **extra) -> dict:
    msg = _post(cid, ME, text, **extra)
    _broadcast(cid, msg)
    return msg


# ---- summary (one claude -p call, no tools) -----------------------------------------------------------------
SUMMARY_PROMPT = (
    "You summarize a chat between humans (friends or colleagues working together, each with their own AI assistant). "
    "Write everything in the language of the chat, section titles included. Markdown, short: a one-line gist, then "
    "only the sections that have content among Decided, Ideas, To do (with who, when someone took it) and Open "
    "questions - each title in bold, translated. "
    "Bullets of one line. No preamble, no closing sentence, never invent anything that was not said.")


def _transcript(doc: dict, msgs: list[dict]) -> str:
    people = teampeer.people() | {ME: _me()}
    lines = []
    for m in msgs:
        who = (people.get(m["author"]) or {}).get("name") or m["author"]
        if m.get("kind") == "poll":
            p = m["poll"]
            opts = "; ".join(f"{o['label']} ({', '.join((people.get(v) or {}).get('name') or v for v in o['votes']) or 'no vote'})"
                             for o in p["options"])
            lines.append(f"{who} [poll] {p['question']}: {opts}")
        elif m.get("kind") == "summary":
            continue
        else:
            names = ", ".join(f["name"] for f in m.get("files") or [])
            lines.append(f"{who}: {m['text']}" + (f" [files: {names}]" if names else ""))
    return "\n".join(lines)


def summarize(cid: str, ids: list[str] | None = None, since: float | None = None) -> dict:
    """Summarize the chosen messages (`ids`), else those after `since` (default: after the last summary); the
    summary is posted as a message of the user."""
    from .sessions import spawn
    with _lock:
        doc = _load()
        chat = _chat(doc, cid)
        msgs = [m for m in chat["messages"] if m.get("kind") != "summary"]
        if ids:
            want = set(ids)
            part = [m for m in msgs if m["id"] in want]
        else:
            if since is None:
                since = next((m["at"] for m in reversed(chat["messages"]) if m.get("kind") == "summary"), 0)
            part = [m for m in msgs if m["at"] > since]
        part = part[-SUMMARY_MESSAGES:]
        if len(part) < 2:
            raise TeamError(409, "nothing_new", "Choose at least two messages to summarize")
        text = _transcript(doc, part)
    cmd = [spawn.claude_bin(), "-p", "--output-format", "json", "--model", SUMMARY_MODEL, "--tools", "",
           "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands", "--system-prompt", SUMMARY_PROMPT]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=SUMMARY_TIMEOUT_S,
                           cwd=config.state_dir("claude-titles"), env=spawn.claude_env(None, "default"))
    except subprocess.TimeoutExpired:
        raise TeamError(504, "timeout", f"No summary after {SUMMARY_TIMEOUT_S} s") from None
    except OSError as e:
        raise TeamError(500, "spawn_failed", f"Claude could not start: {e}") from None
    try:
        data = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except ValueError:
        data = {}
    out = str((data or {}).get("result") or "").strip() if isinstance(data, dict) else ""
    if r.returncode != 0 or not out or (isinstance(data, dict) and data.get("is_error")):
        raise TeamError(502, "summary_failed", out or (r.stderr or "").strip()[-300:] or f"exit code {r.returncode}")
    return _post_shared(cid, out, kind="summary",
                 summary={"from": part[0]["at"], "to": part[-1]["at"], "count": len(part),
                          "cost_usd": round(float(data.get("total_cost_usd") or 0), 4),
                          "duration_ms": int(data.get("duration_ms") or (time.time() - t0) * 1000)})


# ---- events from the other servers ---------------------------------------------------------------------------
def _safe_name(name: str) -> str:
    name = Path(str(name or "file")).name.strip().replace("\x00", "")[:120]
    return name if name and name not in (".", "..") else "file"


def _remote_message(frm_pid: str, raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    kind = raw.get("kind") if raw.get("kind") in ("text", "summary", "poll") else "text"
    now = time.time()
    try:
        at = min(float(raw.get("at") or now), now)
    except (TypeError, ValueError):
        at = now
    mid = str(raw.get("id") or "")
    if not _ID.match(mid):
        raise TeamError(400, "bad_id", "Bad message id")
    msg = {"id": mid, "author": frm_pid, "at": at, "recv": now,
           "text": str(raw.get("text") or "")[:TEXT_MAX * 2 if kind == "summary" else TEXT_MAX], "kind": kind}
    if kind == "poll":
        p = raw.get("poll") if isinstance(raw.get("poll"), dict) else {}
        opts = [o for o in (p.get("options") or []) if isinstance(o, dict)][:12]
        if len(opts) < 2:
            raise TeamError(400, "invalid_poll", "Bad poll")
        msg["poll"] = {"question": str(p.get("question") or msg["text"])[:200], "multi": bool(p.get("multi")),
                       "options": [{"id": str(o.get("id"))[:40], "label": str(o.get("label") or "")[:120], "votes": []}
                                   for o in opts if _ID.match(str(o.get("id")))]}
    if kind == "summary":
        msg["summary"] = {"count": int((raw.get("summary") or {}).get("count") or 0), "from": at, "to": at}
    files = []
    for f in (raw.get("files") or [])[:FILES_MAX]:
        if isinstance(f, dict) and f.get("id"):
            name = _safe_name(f.get("name"))
            try:
                size = max(int(f.get("size") or 0), 0)
            except (TypeError, ValueError):
                size = 0
            files.append({"path": "", "name": name, "size": size,
                          "mime": mimetypes.guess_type(name)[0] or "application/octet-stream",
                          "fid": str(f["id"])[:40], "pending": True})
    if files:
        msg["files"] = files
    if not msg["text"] and not files and kind == "text":
        raise TeamError(400, "empty", "Empty message")
    return msg


def apply_remote(frm: str, contact: bool, event: dict) -> None:
    """A verified event of another server (teampeer.receive). Only what the sender may do in that chat."""
    who = teampeer.pid(frm)
    kind, cid = event.get("type"), str(event.get("chat") or "")[:40]
    me = teampeer.own_address()
    fetch: list[tuple[str, dict]] = []
    with _lock:
        doc = _load()
        chat = next((c for c in doc["chats"] if c["id"] == cid), None)
        if kind == "chat":
            if not contact or not cid.startswith("g_") or (chat and chat.get("admin") != who):
                raise TeamError(403, "forbidden", "Only a contact may add you to a group, only its creator may change it")
            roster = [m for m in (event.get("members") or []) if isinstance(m, dict)][:50]
            members = []
            for m in roster:
                try:
                    addr = teampeer.normalize(str(m.get("address")))
                except teampeer.PeerError:
                    continue
                if addr == me:
                    continue
                if addr != frm:
                    key = (event.get("keys") or {}).get(addr)
                    if not isinstance(key, str):
                        continue
                    teampeer.add_group_peer(addr, cid, key, m)
                members.append(teampeer.pid(addr))
            doc = _load()
            chat = next((c for c in doc["chats"] if c["id"] == cid), None)
            if chat is None:
                chat = {"id": cid, "kind": "group", "created": time.time(), "read_at": 0, "messages": [], "remote": True, "admin": who}
                doc["chats"].append(chat)
            chat |= {"name": str(event.get("name") or "")[:60], "emoji": str(event.get("emoji") or "")[:8], "members": members}
            _save(doc)
            return
        if chat is None:
            if kind == "message" and contact and cid == dm_id(me, frm):
                chat = {"id": cid, "kind": "dm", "name": "", "emoji": "", "members": [who], "created": time.time(),
                        "read_at": 0, "messages": [], "remote": True, "admin": None}
                doc["chats"].append(chat)
            else:
                raise TeamError(404, "not_found", "Unknown chat")
        if not chat.get("remote") or who not in chat["members"]:
            raise TeamError(403, "forbidden", "Not a member of this chat")
        if kind == "message":
            msg = _remote_message(who, event.get("message"))
            if any(m["id"] == msg["id"] for m in chat["messages"]):
                return
            chat["messages"].append(msg)
            chat["messages"].sort(key=lambda m: m["at"])
            fetch = [(msg["id"], f) for f in msg.get("files") or []]
        elif kind == "vote":
            msg = _message(chat, str(event.get("msg"))[:40])
            chosen = {str(x) for x in (event.get("options") or [])[:12]}
            poll = msg.get("poll") or {"options": []}
            if not poll.get("multi") and len(chosen) > 1:
                chosen = set(list(chosen)[:1])
            for o in poll["options"]:
                if who in o["votes"]:
                    o["votes"].remove(who)
                if o["id"] in chosen:
                    o["votes"].append(who)
        elif kind == "react":
            emoji = event.get("emoji")
            if emoji not in REACTIONS:
                raise TeamError(400, "invalid_emoji", "Unknown reaction")
            msg = _message(chat, str(event.get("msg"))[:40])
            who_list = msg.setdefault("reactions", {}).setdefault(emoji, [])
            if event.get("on") and who not in who_list:
                who_list.append(who)
            if not event.get("on") and who in who_list:
                who_list.remove(who)
            msg["reactions"] = {e: w for e, w in msg["reactions"].items() if w}
        else:
            raise TeamError(400, "unknown_event", "Unknown event")
        _save(doc)
    for mid, f in fetch:
        threading.Thread(target=_fetch, args=(frm, cid, mid, f), daemon=True).start()


def _fetch(frm: str, cid: str, mid: str, f: dict) -> None:
    from .api.sessions import reserve_path
    from .uploads import free_bytes, limits
    max_b, reserve = limits()
    d = files_dir()
    ok = False
    dest = None
    with _lock:
        _queued[0] += 1
        room = _queued[0] <= QUEUE_MAX
    try:
        if room and (not max_b or f["size"] <= max_b) and free_bytes(d) - f["size"] >= reserve:
            with _slots:
                dest, fd = reserve_path(d, f["name"])  # the name is taken at once: two "image.png" never collide
                os.close(fd)
                ok = teampeer.fetch_file(frm, f["fid"], dest, max_b, cid, reserve)
                if not ok:
                    dest.unlink(missing_ok=True)
    finally:
        with _lock:
            _queued[0] -= 1
    with _lock:
        doc = _load()
        try:
            msg = _message(_chat(doc, cid), mid)
        except TeamError:
            return
        for x in msg.get("files") or []:
            if x.get("fid") == f["fid"]:
                x.pop("pending", None)
                if ok:
                    x["path"], x["size"] = str(dest), dest.stat().st_size
                else:
                    x["failed"] = True
        _save(doc)
