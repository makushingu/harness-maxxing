"""A tiny IMAP4rev1 server for the tests (plain text, LOGIN / AUTHENTICATE PLAIN): folders in memory, every command
line it receives kept in `commands` - the tests go through the real mail/imap.py without a mail server.

    srv = FakeIMAP(user="me@example.com", password="pw").start()
    srv.add("INBOX", raw_bytes, flags=("\\Seen",))     -> uid
    ... srv.port, srv.commands, srv.folders["INBOX"].messages -> {uid: {"raw", "flags", "date"}}
    srv.uidvalidity("INBOX", 7)                        renumber the folder (a server that rebuilt its index)
    srv.stop()

Enough of the protocol for imap.py: CAPABILITY, LOGIN, AUTHENTICATE PLAIN, LIST, STATUS, SELECT / EXAMINE, UID SEARCH
(ALL, UNSEEN, SEEN, FLAGGED, UID set, TEXT, FROM, SUBJECT, OR, NOT, lists, CHARSET + literal), UID FETCH (UID FLAGS
INTERNALDATE RFC822.SIZE BODY.PEEK[...]), UID STORE, UID COPY / MOVE / EXPUNGE, EXPUNGE, APPEND (APPENDUID),
CREATE, DELETE, RENAME, NOOP, CLOSE, LOGOUT.
"""
from __future__ import annotations

import base64
import email
import email.policy
import re
import socketserver
import threading
import time


class Folder:
    def __init__(self, name: str, special: str = ""):
        self.name, self.special = name, special
        self.validity = 1
        self.next_uid = 1
        self.messages: dict[int, dict] = {}


class FakeIMAP:
    def __init__(self, user: str = "", password: str = "", caps: str = "IMAP4rev1 AUTH=PLAIN UIDPLUS MOVE"):
        self.user, self.password, self.caps = user, password, caps
        self.commands: list[str] = []
        self.folders: dict[str, Folder] = {}
        for name, special in (("INBOX", ""), ("Drafts", "\\Drafts"), ("Sent", "\\Sent"), ("Trash", "\\Trash"),
                              ("Archive", "\\Archive"), ("Junk", "\\Junk")):
            self.folders[name] = Folder(name, special)
        self.lock = threading.Lock()
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def send(self, line: str | bytes) -> None:
                self.wfile.write((line.encode() if isinstance(line, str) else line) + b"\r\n")

            def read_command(self) -> tuple[str, list] | None:
                """One command: its text (literals as {N}) and the tokens (a literal is a bytes token)."""
                text, chunks = "", []
                while True:
                    raw = self.rfile.readline()
                    if not raw:
                        return None
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    text += line
                    if line.endswith("}") and "{" in line:
                        n = int(line[line.rindex("{") + 1:-1].rstrip("+"))
                        chunks.append(line[:line.rindex("{")])
                        if not line[:-1].endswith("+"):
                            self.send("+ go ahead")
                        chunks.append(self.rfile.read(n))
                        continue
                    chunks.append(line)
                    break
                outer.commands.append(text)
                tokens: list = []
                for c in chunks:
                    tokens += [c] if isinstance(c, bytes) else _tokens(c)
                return text, tokens

            def handle(self) -> None:
                self.send("* OK fake IMAP ready")
                state = {"authed": False, "folder": None, "readonly": True}
                while True:
                    got = self.read_command()
                    if got is None:
                        return
                    _, tok = got
                    if len(tok) < 2:
                        self.send("* BAD empty")
                        continue
                    tag, cmd, args = tok[0], str(tok[1]).upper(), tok[2:]
                    try:
                        with outer.lock:
                            done = outer._do(self, state, tag, cmd, args)
                    except Exception as e:  # noqa: BLE001
                        self.send(f"{tag} BAD {e}")
                        continue
                    if done == "logout":
                        return

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]

    # ------------------------------------------------------------ setup helpers

    def start(self) -> "FakeIMAP":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def add(self, folder: str, raw: bytes, flags: tuple[str, ...] = (), date: float | None = None) -> int:
        with self.lock:
            f = self.folders[folder]
            uid = f.next_uid
            f.next_uid += 1
            f.messages[uid] = {"raw": raw, "flags": set(flags), "date": date or time.time()}
            return uid

    def uidvalidity(self, folder: str, value: int) -> None:
        with self.lock:
            f = self.folders[folder]
            f.validity = value
            msgs = sorted(f.messages.values(), key=lambda m: m["date"])
            f.messages = {i + 1: m for i, m in enumerate(msgs)}
            f.next_uid = len(msgs) + 1

    def sent(self, verb: str) -> list[str]:
        """The command lines whose command (after the tag, and UID) is `verb`."""
        out = []
        for c in self.commands:
            parts = c.split()
            words = [p.upper() for p in parts[1:3]]
            if words[:1] == [verb] or words == ["UID", verb]:
                out.append(c)
        return out

    # ------------------------------------------------------------ commands

    def _do(self, h, state: dict, tag: str, cmd: str, args: list):
        ok = lambda text="done": h.send(f"{tag} OK {text}")  # noqa: E731
        if cmd == "CAPABILITY":
            h.send(f"* CAPABILITY {self.caps}")
            return ok()
        if cmd == "LOGIN":
            if (_s(args[0]), _s(args[1])) != (self.user, self.password):
                return h.send(f"{tag} NO [AUTHENTICATIONFAILED] wrong password")
            state["authed"] = True
            return ok()
        if cmd == "AUTHENTICATE":
            h.send("+ ")
            line = h.rfile.readline().strip()
            _, user, pw = base64.b64decode(line).decode().split("\0")
            if (user, pw) != (self.user, self.password):
                return h.send(f"{tag} NO [AUTHENTICATIONFAILED] wrong password")
            state["authed"] = True
            return ok()
        if cmd == "LOGOUT":
            h.send("* BYE")
            ok()
            return "logout"
        if cmd == "NOOP":
            return ok()
        if not state["authed"]:
            return h.send(f"{tag} NO sign in first")
        if cmd == "LIST":
            for f in self.folders.values():
                flags = " ".join(x for x in ("\\HasNoChildren", f.special) if x)
                h.send(f'* LIST ({flags}) "/" "{f.name}"')
            return ok()
        if cmd == "STATUS":
            f = self._folder(args[0])
            unseen = sum(1 for m in f.messages.values() if "\\Seen" not in m["flags"])
            h.send(f'* STATUS "{f.name}" (MESSAGES {len(f.messages)} UNSEEN {unseen})')
            return ok()
        if cmd in ("SELECT", "EXAMINE"):
            f = self._folder(args[0])
            state["folder"], state["readonly"] = f.name, cmd == "EXAMINE"
            h.send(f"* {len(f.messages)} EXISTS")
            h.send(f"* OK [UIDVALIDITY {f.validity}] UIDs valid")
            h.send(f"* OK [UIDNEXT {f.next_uid}] next")
            return ok("[READ-ONLY] done" if state["readonly"] else "[READ-WRITE] done")
        if cmd == "CREATE":
            name = _s(args[0])
            self.folders.setdefault(name, Folder(name))
            return ok()
        if cmd == "DELETE":
            self.folders.pop(_s(args[0]), None)
            return ok()
        if cmd == "RENAME":
            f = self.folders.pop(_s(args[0]))
            f.name = _s(args[1])
            self.folders[f.name] = f
            return ok()
        if cmd == "APPEND":
            f = self._folder(args[0])
            flags = args[1] if len(args) > 2 and isinstance(args[1], list) else []
            raw = next(a for a in args if isinstance(a, bytes))
            uid = f.next_uid
            f.next_uid += 1
            f.messages[uid] = {"raw": raw, "flags": set(map(str, flags)), "date": time.time()}
            return ok(f"[APPENDUID {f.validity} {uid}] appended")
        if cmd == "CLOSE":
            state["folder"] = None
            return ok()
        f = self.folders.get(state["folder"] or "")
        if f is None:
            return h.send(f"{tag} NO select a folder first")
        if cmd == "EXPUNGE":
            for u in [u for u, m in f.messages.items() if "\\Deleted" in m["flags"]]:
                del f.messages[u]
            return ok()
        if cmd != "UID":
            return h.send(f"{tag} BAD unknown command {cmd}")
        sub, rest = str(args[0]).upper(), args[1:]
        uids = sorted(f.messages)
        if sub == "SEARCH":
            if rest and str(rest[0]).upper() == "CHARSET":
                rest = rest[2:]
            hit = [u for u in uids if _match(f.messages[u], u, list(rest), uids)]
            h.send("* SEARCH" + "".join(f" {u}" for u in hit))
            return ok()
        sel = [u for u in _set(str(rest[0]), uids) if u in f.messages]
        if sub == "FETCH":
            items = " ".join(str(x) for x in _flat(rest[1:])).upper()
            for u in sel:
                m = f.messages[u]
                seq = uids.index(u) + 1
                head = f"UID {u} FLAGS ({' '.join(sorted(m['flags']))})"
                if "INTERNALDATE" in items:
                    head += f' INTERNALDATE "{time.strftime("%d-%b-%Y %H:%M:%S +0000", time.gmtime(m["date"]))}"'
                if "RFC822.SIZE" in items:
                    head += f" RFC822.SIZE {len(m['raw'])}"
                if "BODY.PEEK[HEADER" in items or "BODY[HEADER" in items:
                    part = m["raw"].split(b"\r\n\r\n", 1)[0] if b"\r\n\r\n" in m["raw"] else m["raw"].split(b"\n\n", 1)[0]
                    part += b"\r\n\r\n"
                    h.wfile.write(f"* {seq} FETCH ({head} BODY[HEADER.FIELDS (X)] {{{len(part)}}}\r\n".encode() + part + b")\r\n")
                elif "BODY.PEEK[]" in items or "BODY[]" in items:
                    cut = re.search(r"BODY(?:\.PEEK)?\[\]<0\.(\d+)>", items)       # a partial fetch: its first N bytes
                    raw = m["raw"][:int(cut.group(1))] if cut else m["raw"]
                    name = "BODY[]<0>" if cut else "BODY[]"
                    h.wfile.write(f"* {seq} FETCH ({head} {name} {{{len(raw)}}}\r\n".encode() + raw + b")\r\n")
                    if "BODY[]" in items and "PEEK" not in items:
                        m["flags"].add("\\Seen")
                else:
                    h.send(f"* {seq} FETCH ({head})")
            return ok()
        if sub == "STORE":
            if state["readonly"]:
                return h.send(f"{tag} NO read-only folder")
            how, flags = str(rest[1]).upper(), {str(x) for x in _flat(rest[2:])}
            for u in sel:
                fl = f.messages[u]["flags"]
                if how.startswith("+"):
                    fl |= flags
                elif how.startswith("-"):
                    fl -= flags
                else:
                    fl.clear()
                    fl |= flags
            return ok()
        if sub in ("COPY", "MOVE"):
            dest = self._folder(rest[1])
            for u in sel:
                m = f.messages[u]
                dest.messages[dest.next_uid] = {**m, "flags": set(m["flags"])}
                dest.next_uid += 1
                if sub == "MOVE":
                    del f.messages[u]
            return ok()
        if sub == "EXPUNGE":
            for u in sel:
                if "\\Deleted" in f.messages[u]["flags"]:
                    del f.messages[u]
            return ok()
        return h.send(f"{tag} BAD unknown UID command {sub}")

    def _folder(self, name) -> Folder:
        n = _s(name)
        n = "INBOX" if n.upper() == "INBOX" else n
        if n not in self.folders:
            raise KeyError(f"no folder {n}")
        return self.folders[n]


# ---------------------------------------------------------------- parsing

def _tokens(s: str) -> list:
    """Atoms, quoted strings (str), lists (list); an atom keeps its [...] whole (BODY.PEEK[HEADER.FIELDS (A B)])."""
    out: list = []
    stack: list[list] = [out]
    i = 0
    while i < len(s):
        c = s[i]
        if c == " ":
            i += 1
        elif c == '"':
            j, buf = i + 1, ""
            while s[j] != '"':
                if s[j] == "\\":
                    j += 1
                buf += s[j]
                j += 1
            stack[-1].append(Quoted(buf))
            i = j + 1
        elif c == "(":
            new: list = []
            stack[-1].append(new)
            stack.append(new)
            i += 1
        elif c == ")":
            stack.pop()
            i += 1
        else:
            j, depth = i, 0
            while j < len(s) and (depth or s[j] not in ' ()"'):
                depth += s[j] == "["
                depth -= s[j] == "]"
                j += 1
            stack[-1].append(s[i:j])
            i = j
    return out


class Quoted(str):
    pass


def _s(x) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def _flat(x) -> list:
    out = []
    for y in x:
        out += _flat(y) if isinstance(y, list) else [y]
    return out


def _set(spec: str, uids: list[int]) -> list[int]:
    top = max(uids) if uids else 0
    out: list[int] = []
    for part in spec.split(","):
        a, _, b = part.partition(":")
        lo = top if a == "*" else int(a)
        hi = lo if not b else (top if b == "*" else int(b))
        lo, hi = min(lo, hi), max(lo, hi)
        out += [u for u in uids if lo <= u <= hi] or ([top] if b == "*" and top else [])
    return sorted(set(out))


def _text(m: dict) -> str:
    return m["raw"].decode("utf-8", "replace").lower()


def _header(m: dict, name: str) -> str:
    msg = email.message_from_bytes(m["raw"], policy=email.policy.default)
    return str(msg.get(name) or "").lower()


def _match(m: dict, uid: int, crit: list, uids: list[int]) -> bool:
    """Every criterion of the list holds (consumed from the front)."""
    while crit:
        if not _one(m, uid, crit, uids):
            return False
    return True


def _one(m: dict, uid: int, crit: list, uids: list[int]) -> bool:
    c = crit.pop(0)
    if isinstance(c, list):
        return _match(m, uid, list(c), uids)
    word = _s(c).upper() if not isinstance(c, Quoted) else ""
    if word == "ALL":
        return True
    if word in ("UNSEEN", "SEEN", "FLAGGED", "DELETED", "UNDELETED"):
        flag = {"UNSEEN": "\\Seen", "SEEN": "\\Seen", "FLAGGED": "\\Flagged", "DELETED": "\\Deleted",
                "UNDELETED": "\\Deleted"}[word]
        return (flag in m["flags"]) != (word in ("UNSEEN", "UNDELETED"))
    if word == "UID":
        return uid in _set(_s(crit.pop(0)), uids)
    if word == "NOT":
        return not _one(m, uid, crit, uids)
    if word == "OR":
        a = _one(m, uid, crit, uids)
        b = _one(m, uid, crit, uids)
        return a or b
    if word in ("TEXT", "BODY"):
        return _s(crit.pop(0)).lower() in _text(m)
    if word == "HEADER":
        name = _s(crit.pop(0))
        return _s(crit.pop(0)).lower() in _header(m, name)
    if word in ("FROM", "TO", "SUBJECT"):
        return _s(crit.pop(0)).lower() in _header(m, word)
    raise ValueError(f"unknown search key {c!r}")
