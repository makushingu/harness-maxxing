"""MCP servers loaded per turn, only when the session needs them (config `mcp_auto`).  STDLIB ONLY.

Every MCP server and claude.ai connector costs prompt tokens on every model call (tool names, server instructions)
and time at each turn start (connections). With `mcp_auto` on, the runner gives each turn only:

  - the servers this TOPIC used (a `mcp__<server>__<tool>` call seen in a turn's stream; kept USED_KEEP_S);
  - the servers loaded for this session (`mcp_loaded` in its meta, written by `maxxing mcp load NAME`);
  - the servers named in the message (the whole name, or a word of it no other server has, 4+ letters);
  - every project / local-scope server of the topic's folder (scoped there on purpose);
  - harness-pc, unchanged (pcbridge.mcp_config_args, its own --mcp-config file).

With `--strict-mcp-config --mcp-config <state>/mcp-auto/sessions/<sid>.json` (0600, rewritten only when it changes;
secrets stay in the file, never on the command line). Strict mode also drops the claude.ai connectors: when the turn
needs one, nothing is restricted (everything loads, as without `mcp_auto`). The servers left out are listed in the
turn's system prompt with `maxxing mcp load NAME`; the runner then continues the turn by itself (runner._mcp_after).

Claude Code writes a server's name in its tool names with every character outside [A-Za-z0-9_-] as "_"
("claude.ai Google Drive" -> mcp__claude_ai_Google_Drive__search): names are compared in that form (`norm`).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

from . import config

USED_KEEP_S = 60 * 86400                        # a server unused by a topic for 60 days is no longer loaded there
CONNECTOR_PREFIX = "claude.ai "
PC_NAME = "harness-pc"                          # pcbridge.MCP_NAME (not imported: pcbridge is not stdlib-only)
WORD_MIN = 4
# words of a server name that say nothing about which service it is
STOP_WORDS = {"mcp", "server", "servers", "api", "apps", "the", "and", "for", "with", "claude", "http", "https",
              "local", "remote", "tool", "tools", "data", "docs", "online", "www", "com", "net", "org"}
TEXT_MAX = 20000                                # characters of a message searched for server names
LOADED_MAX = 50
CONTINUE_MAX = 2                                # automatic continuations in a row (a server asked turn after turn)
CONTINUE_TEXT = ("[Harness: the MCP server{s} {names} {verb} now loaded. Continue where you stopped.]")
HINT = ("MCP servers NOT loaded in this turn (Harness loads only the ones this topic uses, to save tokens): {items}. "
        "If you need one, run `maxxing mcp load \"<name>\"` (it is loaded from your next turn on) and end your turn "
        "saying so; Harness continues automatically.")


def norm(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(name)).lower()


def tool_server(tool: str) -> str | None:
    """`mcp__<server>__<tool>` -> the server's name in tool form (lower case), else None."""
    if not isinstance(tool, str) or not tool.startswith("mcp__"):
        return None
    srv = tool[5:].split("__", 1)[0]
    return srv.lower() or None


def _dir() -> Path:
    return config.STATE / "mcp-auto"


@contextmanager
def _locked(name: str) -> Iterator[None]:
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(d / f".{name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


# ---- what a topic used ----------------------------------------------------------------------
def _topic_file(path: str) -> Path:
    return _dir() / "topics" / (hashlib.sha1((path or "").encode()).hexdigest()[:20] + ".json")


def used(path: str, now: float | None = None) -> dict[str, float]:
    """{server in tool form: last use} of a topic (workspace-relative folder), the last USED_KEEP_S only."""
    now = time.time() if now is None else now
    d = config.read_json(_topic_file(path), {}) or {}
    u = d.get("used") if isinstance(d, dict) else None
    if not isinstance(u, dict):
        return {}
    return {str(k): float(v) for k, v in u.items() if isinstance(v, (int, float)) and now - v < USED_KEEP_S}


def record_used(path: str, servers: set[str] | list[str], now: float | None = None) -> None:
    servers = {s for s in servers if s and s != norm(PC_NAME)}
    if not servers:
        return
    now = time.time() if now is None else now
    f = _topic_file(path)
    with _locked("topics"):
        u = used(path, now)
        u.update({s: now for s in servers})
        config.write_json(f, {"path": path, "used": u}, mode=0o600)


# ---- claude.ai connectors (only Claude Code knows them: its init event, `claude mcp list`) ----------------
def connectors() -> list[str]:
    d = config.read_json(_dir() / "connectors.json", {}) or {}
    names = d.get("names") if isinstance(d, dict) else None
    return [str(n) for n in names if isinstance(n, str)] if isinstance(names, list) else []


def record_connectors(names: list[str]) -> None:
    """The claude.ai connectors seen (a complete list: a non-strict turn's init, or `claude mcp list`)."""
    names = sorted({str(n) for n in names if isinstance(n, str) and n.startswith(CONNECTOR_PREFIX)})
    if names == connectors():
        return
    with _locked("connectors"):
        config.write_json(_dir() / "connectors.json", {"names": names, "at": time.time()}, mode=0o600)


def connectors_of_init(ev: dict) -> list[str] | None:
    """Connector names of a stream-json init event (read from turns that were not restricted), None when the
    event has no server list."""
    servers = ev.get("mcp_servers")
    if not isinstance(servers, list):
        return None
    return [s["name"] for s in servers if isinstance(s, dict) and isinstance(s.get("name"), str)
            and (s["name"].startswith(CONNECTOR_PREFIX) or s.get("source") == "claudeai")]


# ---- the servers a turn may load ----------------------------------------------------------------
@dataclass
class Server:
    name: str
    scope: str                                  # user | local | project | connector
    cfg: dict

    def hint(self) -> str:
        if self.scope == "connector":
            return f"{self.name} (claude.ai connector)"
        kind = str(self.cfg.get("type") or ("stdio" if self.cfg.get("command") else "http"))
        if self.cfg.get("url"):
            try:
                host = urlsplit(str(self.cfg["url"])).hostname or ""
            except ValueError:
                host = ""
            return f"{self.name} ({kind}{', ' + host if host else ''})"
        cmd = os.path.basename(str(self.cfg.get("command") or ""))
        pkg = next((str(a) for a in self.cfg.get("args") or [] if isinstance(a, str) and a and not a.startswith("-")
                    and re.fullmatch(r"[@A-Za-z0-9_./-]{1,80}", a) and not re.search(r"\d{6}|[A-Za-z0-9]{24}", a)), "")
        return f"{self.name} (local program{': ' + cmd if cmd else ''}{' ' + pkg if pkg else ''})"


def _cfg_file() -> Path:
    from . import mcp                           # its path rule (CLAUDE_CONFIG_DIR of the turns, else ~/.claude.json)
    return mcp._cfg_path()                      # noqa: SLF001


def _d(x: Any) -> dict:
    return x if isinstance(x, dict) else {}


def _l(x: Any) -> list[str]:
    return [v for v in x if isinstance(v, str)] if isinstance(x, list) else []


def candidates(cwd: str, claude_json: dict) -> tuple[list[Server], list[Server]]:
    """(user-scope servers, servers of the folder: local + approved project .mcp.json of cwd and its parents)."""
    projects = _d(claude_json.get("projects"))
    here = _d(projects.get(cwd))
    disabled = set(_l(here.get("disabledMcpServers")))
    users = [Server(n, "user", c) for n, c in _d(claude_json.get("mcpServers")).items()
             if isinstance(c, dict) and n != PC_NAME and n not in disabled]
    folder: dict[str, Server] = {}
    p = Path(cwd)
    for d in [p, *p.parents]:                   # Claude Code reads .mcp.json from the folder and its parents
        f = d / ".mcp.json"
        try:
            if not f.is_file() or f.stat().st_size > (1 << 20):
                continue
            items = _d(_d(json.loads(f.read_text(encoding="utf-8"))).get("mcpServers"))
        except (OSError, ValueError):
            continue
        own = _d(projects.get(str(d)))
        refused = set(_l(here.get("disabledMcpjsonServers")))
        for n, c in items.items():
            ok = any(bool(x.get("enableAllProjectMcpServers")) or n in _l(x.get("enabledMcpjsonServers"))
                     for x in (here, own))
            if isinstance(c, dict) and ok and n not in refused and n not in disabled and n not in folder \
                    and n != PC_NAME:
                folder[n] = Server(n, "project", c)
    for n, c in _d(here.get("mcpServers")).items():        # local scope wins over a .mcp.json of the same name
        if isinstance(c, dict) and n != PC_NAME and n not in disabled:
            folder[n] = Server(n, "local", c)
    return users, list(folder.values())


def _base(name: str) -> str:
    return name[len(CONNECTOR_PREFIX):] if name.lower().startswith(CONNECTOR_PREFIX) else name


def _words(name: str) -> list[str]:
    parts = re.split(r"[^0-9A-Za-z]+|(?<=[a-z])(?=[A-Z])", _base(name))
    return [w.lower() for w in parts if len(w) >= WORD_MIN and w.lower() not in STOP_WORDS]


def mentioned(names: list[str], text: str) -> set[str]:
    """Names (of `names`) a message speaks of: the whole name ("facebook ads", "Facebook-ads"), or one of its
    words that no other server has ("drive" for "claude.ai Google Drive", not "google" when Calendar exists too)."""
    t = (text or "")[:TEXT_MAX].lower()
    if not t:
        return set()
    count: dict[str, int] = {}
    for n in names:
        for w in set(_words(n)):
            count[w] = count.get(w, 0) + 1
    out = set()
    for n in names:
        parts = [re.escape(w) for w in re.split(r"[^0-9A-Za-z]+", _base(n).lower()) if w]
        if parts and re.search(r"(?<![0-9a-z])" + r"[\s_.-]*".join(parts) + r"(?![0-9a-z])", t):
            out.add(n)
            continue
        if any(count.get(w) == 1 and re.search(rf"(?<![0-9a-z]){re.escape(w)}(?![0-9a-z])", t) for w in _words(n)):
            out.add(n)
    return out


@dataclass
class Plan:
    args: list[str]                             # --strict-mcp-config --mcp-config <file>, or [] (load everything)
    hint: str                                   # system prompt paragraph: the servers left out ("" = none)
    loaded: list[str]                           # names given to the turn (strict only)


NO_PLAN = Plan([], "", [])


def plan(sid: str, cfg: dict, meta: dict, cwd: str, text: str) -> Plan:
    """What the turn of `sid` loads. NO_PLAN (= everything, as without `mcp_auto`) when off, when a needed server is
    a claude.ai connector, or when Claude Code's config cannot be read. Never raises."""
    if not cfg.get("mcp_auto"):
        return NO_PLAN
    try:
        return _plan(sid, meta, cwd, text)
    except Exception:                           # noqa: BLE001 - a turn never fails because of this
        return NO_PLAN


def _plan(sid: str, meta: dict, cwd: str, text: str) -> Plan:
    try:
        claude_json = json.loads(_cfg_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return NO_PLAN                          # unreadable (being rewritten?): restricting would drop servers
    if not isinstance(claude_json, dict):
        return NO_PLAN
    users, folder = candidates(cwd, claude_json)
    conns = [Server(n, "connector", {}) for n in connectors()]
    pool = users + conns
    want = set(used(str(meta.get("path") or "")))
    want |= {norm(n) for n in meta.get("mcp_loaded") or [] if isinstance(n, str)}
    want |= {norm(n) for n in mentioned([s.name for s in pool], text)}
    if any(norm(s.name) in want for s in conns):
        return NO_PLAN
    chosen = folder + [s for s in users if norm(s.name) in want]
    left = [s for s in pool if s not in chosen]
    f = _dir() / "sessions" / f"{sid}.json"
    body = json.dumps({"mcpServers": {s.name: s.cfg for s in chosen}}, ensure_ascii=False, sort_keys=True)
    try:
        same = f.read_text(encoding="utf-8") == body
    except OSError:
        same = False
    if not same:
        f.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(f.parent, 0o700)
        tmp = f.with_name(f".{f.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, f)
    hint = HINT.format(items="; ".join(s.hint() for s in left)) if left else ""
    return Plan(["--strict-mcp-config", "--mcp-config", str(f)], hint, [s.name for s in chosen])


def forget_session(sid: str) -> None:
    try:
        (_dir() / "sessions" / f"{sid}.json").unlink()
    except OSError:
        pass


# ---- `maxxing mcp load` ----------------------------------------------------------------------
def known_names(cwd: str | None = None) -> list[str]:
    """Every server a session could load: user scope, the folder's own, the claude.ai connectors."""
    try:
        claude_json = json.loads(_cfg_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        claude_json = {}
    users, folder = candidates(cwd or "/nonexistent", _d(claude_json))
    return [s.name for s in users + folder] + connectors()


def resolve(name: str, names: list[str]) -> str | None:
    """The real name of a server asked as `name`: exact, any case, without/with "claude.ai ", or in tool form."""
    name = (name or "").strip()
    for test in (lambda n: n == name, lambda n: n.lower() == name.lower(),
                 lambda n: _base(n).lower() == _base(name).lower(), lambda n: norm(n) == norm(name)):
        hits = [n for n in names if test(n)]
        if len(hits) == 1:
            return hits[0]
    return None


def continue_item(new: list[str], streak: int) -> dict:
    many = len(new) > 1
    text = CONTINUE_TEXT.format(s="s" if many else "", names=", ".join(new), verb="are" if many else "is")
    return {"text": text, "attachments": [], "source": "system", "kind": "user", "mcp_continue": streak,
            "at": time.time()}
