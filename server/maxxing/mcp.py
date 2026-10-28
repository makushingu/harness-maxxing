"""MCP servers of Claude Code, seen and managed from Settings -> MCP.

Claude Code keeps them in three places, all read here:
  user     `<claude_dir>/.claude.json` "mcpServers"                      -> every session
  local    `<claude_dir>/.claude.json` "projects"[<folder>]."mcpServers" -> sessions of that folder (a topic)
  project  `<folder>/.mcp.json` "mcpServers"                             -> that folder, once approved
Changes go through the real CLI (`claude mcp add-json | remove`, run in the topic folder with the turns'
environment), so Claude Code's own locking and validation apply. Only two edits are made by hand: moving a
renamed topic's entry (`on_workspace_change`) and dropping a server whose folder no longer exists.

Secrets: headers / env values are meant to be `${VAULT_KEY}` references (Claude Code expands them from the
environment, and vault keys flagged `expose` are in the environment of every turn); `add` exposes the keys it
references. A header / env value that is anything else than references (an optional auth scheme such as
`Bearer ${KEY}` aside), the user:password and the query values of an address are never sent to the UI (shown as
"•••", `literal_secret`) and are blanked in the backup export. Only a few harmless headers (Content-Type...) show.

Status: `check()` runs `claude mcp list` once per folder (it contacts every server) in a background thread;
states: connected | needs_auth | failed | pending (a .mcp.json server not approved) | unknown.
OAuth: `login_start(id)` runs `claude mcp login --no-browser <name>` in a pseudo-terminal (the CLI refuses a
plain pipe), returns the authorization URL; the user authorises, lands on a page that does not open
(http://localhost:<port>/callback?...), pastes its address: `login_finish(login, url)` types it into the CLI.
"""
from __future__ import annotations

import json
import os
import pty
import re
import select
import shlex
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Any

from . import config

NAME_RE = re.compile(r"\A[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")   # never starts with '-' (a CLI option)
# the default stops at the next "$": linear on "${A:-" repeated without "}" (was quadratic, the API froze)
REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}$]*)?\}")
ANSI_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[=>]")
URL_RE = re.compile(r"https?://[^\s\x07\x1b'\"<>]+")
CLI_TIMEOUT = 60
LOGIN_TTL = 15 * 60
GC_EVERY = 30                                       # s between two sweeps of abandoned OAuth logins
# Marks of `claude mcp list` (they changed between versions: ✓ then ✔); the words decide when the mark is unknown.
STATES = {"✓": "connected", "✔": "connected", "!": "needs_auth", "⚠": "needs_auth", "✗": "failed", "✘": "failed",
          "✖": "failed", "⏸": "pending"}
WORDS = (("connected", "connected"), ("auth", "needs_auth"), ("fail", "failed"), ("error", "failed"),
         ("pending", "pending"), ("approv", "pending"))


class McpError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---- reading ---------------------------------------------------------------------------------
def _cfg_path() -> Path:
    """Same file as the turns: inside Harness' own Claude Code folder (CLAUDE_CONFIG_DIR) when set, else ~/.claude.json."""
    from .sessions import spawn
    env = spawn.claude_env()
    own = env.get("CLAUDE_CONFIG_DIR")
    return Path(own) / ".claude.json" if own else Path(env["HOME"]) / ".claude.json"


def _dict(x: Any) -> dict:
    """Hand-edited files may hold anything where a mapping is expected (`"mcpServers": "x"`): read it as empty."""
    return x if isinstance(x, dict) else {}


def _list(x: Any) -> list:
    return x if isinstance(x, list) else []


# (path, mtime_ns, size, inode) -> parsed .claude.json: the file grows with every folder Claude Code opened
# (megabytes), and the MCP page re-reads it on each refresh
_cfg_cache: dict[str, Any] = {"key": None, "data": {}}


def _read_cfg(fresh: bool = False) -> dict:
    """Parsed .claude.json. Shared with the next callers unless `fresh`: read-only, a writer asks for `fresh`."""
    p = _cfg_path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size, st.st_ino)
        if not fresh and _cfg_cache["key"] == key:
            return _cfg_cache["data"]
        d = json.loads(p.read_text(encoding="utf-8"))
        d = d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}
    if not fresh:
        _cfg_cache.update(key=key, data=d)
    return d


def _ws() -> Path:
    return config.workspace()


def where_of(folder: str | None) -> dict:
    """{label, rel, project, topic, exists} of the folder a server belongs to (None = every session)."""
    if folder is None:
        return {"rel": None, "project": None, "topic": None, "exists": True, "path": None}
    p = Path(folder)
    out = {"rel": None, "project": None, "topic": None, "exists": p.is_dir(), "path": folder}
    try:
        rel = p.relative_to(_ws()).as_posix()
    except ValueError:
        return out
    out["rel"] = rel
    m = re.match(r"^projects/([^/]+)(?:/topics/([^/]+))?$", rel)
    if m:
        out["project"], out["topic"] = m.group(1), m.group(2)
    return out


def _kind(cfg: dict) -> str:
    t = str(cfg.get("type") or ("stdio" if cfg.get("command") else "http"))
    return t if t in ("stdio", "http", "sse", "ws") else t


SECRET_RE = re.compile(r"[A-Za-z0-9_\-]{20,}")


def _has_literal(v: str) -> bool:
    """A value carries a literal secret: once ${KEY} references are removed, a run of 20+ letters/digits/-/_
    mixing letters and digits is left (a token), unlike `Bearer ${KEY}`, `application/json` or a package name."""
    rest = REF_RE.sub("", str(v))
    return any(re.search(r"[A-Za-z]", t) and re.search(r"\d", t) for t in SECRET_RE.findall(rest))


MASK = "•••"
# Headers whose value is never a secret; any other header / env value is masked unless it is only references.
PLAIN_HEADERS = {"accept", "accept-encoding", "accept-language", "cache-control", "content-type",
                 "mcp-protocol-version", "user-agent"}
# What may be left of a value once its ${KEY} references are removed: an auth scheme and separators.
REFS_ONLY_RE = re.compile(r"\A\s*(?:(?:bearer|basic|token|bot|digest|apikey|api-key|key)\s+)?[\s:;,./_-]*\Z", re.I)


def _only_refs(v: Any) -> bool:
    """`${KEY}`, `Bearer ${KEY}`, `${USER}:${PASS}` or empty: nothing secret written in clear."""
    return bool(REFS_ONLY_RE.match(REF_RE.sub("", str(v))))


def _masked(d: Any, mask: str = MASK, plain: frozenset | set = frozenset()) -> tuple[dict, bool]:
    """Every value that is not only references -> `mask` (keys in `plain`, lower case, are kept)."""
    out, hid = {}, False
    for k, v in _dict(d).items():
        secret = str(k).strip().lower() not in plain and not _only_refs(v)
        out[str(k)] = mask if secret else str(v)
        hid = hid or secret
    return out, hid


# A path segment of 24+ letters / digits with no separator is a token even without digits (`/mcp/<key>`).
TOKEN_SEGMENT_RE = re.compile(r"\A[A-Za-z0-9]{24,}\Z")


def _url_masked(url: str, mask: str = MASK) -> str:
    """user:password and query / fragment values -> `mask` (an empty mask drops the user:password); a token in
    the path (a run of letters and digits, or one long unbroken segment) masks the whole address."""
    try:
        u = urlsplit(url)
    except ValueError:
        return mask
    netloc = u.netloc
    if "@" in netloc:
        userinfo, host = netloc.rsplit("@", 1)
        if not _only_refs(userinfo):
            netloc = f"{mask}@{host}" if mask else host

    def values(q: str) -> str:
        parts = []
        for part in q.split("&"):
            k, eq, v = part.partition("=")
            parts.append(f"{k}{eq}{mask}" if eq and not _only_refs(v) else part)
        return "&".join(parts)
    frag = u.fragment if _only_refs(u.fragment) else mask
    if _has_literal(netloc.rsplit("@", 1)[-1] + u.path) or any(TOKEN_SEGMENT_RE.match(s) for s in u.path.split("/")):
        return mask
    return urlunsplit((u.scheme, netloc, u.path, values(u.query) if u.query else "", frag))


SECRET_NAME_RE = re.compile(r"key|token|secret|pass|auth|cred|cookie|session|bearer|signature|private", re.I)
# the scheme starts a word and is short: on a long run of letters with no "://" each try stops quickly (linear)
USERINFO_RE = re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]{0,31}://([^/\s@]+)@")
SECRET_FLAG_RE = re.compile(r"(?:key|token|secret|pass|password|auth|credentials?|cookie|bearer)\Z", re.I)
HEADER_ARG_RE = re.compile(r"\A\s*([A-Za-z0-9-]+)\s*:(.*)\Z", re.S)


def _has_userinfo(v: str) -> bool:
    """`postgres://user:password@host`: a login written in clear in an address."""
    return any(not _only_refs(m.group(1)) for m in USERINFO_RE.finditer(str(v)))


def _secret_args(args: Any) -> list[bool]:
    """Which command-line arguments carry a literal secret: a token, a login in an address, `--api-key=value`
    or `Authorization: value` with a secret-looking name, the value after `--token` / `--api-key`, or a non-plain
    header after `-H` / `--header`."""
    out, after = [], ""
    for a in map(str, _list(args)):
        name, eq, value = a.partition("=")
        header = HEADER_ARG_RE.match(a)
        if _has_literal(a) or _has_userinfo(a):
            secret = True
        elif after == "header":
            secret = not (header and header.group(1).lower() in PLAIN_HEADERS) and not _only_refs(a)
        elif after == "value":
            secret = not _only_refs(a)
        elif a.startswith("-") and eq:
            secret = bool(SECRET_NAME_RE.search(name)) and not _only_refs(value)
        elif header and not a.startswith("-"):
            secret = bool(SECRET_NAME_RE.search(header.group(1))) and not _only_refs(header.group(2))
        else:
            secret = False
        out.append(secret)
        flag = a.startswith("-") and not eq
        value_flag = flag and not a.lower().startswith("--no-") and SECRET_FLAG_RE.search(a)
        after = "header" if a in ("-H", "--header") else "value" if value_flag else ""
    return out


def _blank_secrets(d: Any) -> dict:
    """Backup export: a value written in clear is blanked when it looks like a secret (a token-like string, a login
    in an address such as `postgres://user:password@host`, or a name such as API_KEY / Authorization); plain settings (LOG_LEVEL=debug, Content-Type) are kept so a restore
    works as is. The UI masks more (`_masked`)."""
    out = {}
    for k, v in _dict(d).items():
        secret = not _only_refs(v) and (_has_literal(str(v)) or _has_userinfo(str(v))
                                        or bool(SECRET_NAME_RE.search(str(k))))
        out[str(k)] = "" if secret else str(v)
    return out


def _refs(cfg: dict) -> set[str]:
    vals = [*_dict(cfg.get("headers")).values(), *_dict(cfg.get("env")).values(), *_list(cfg.get("args")),
            cfg.get("url") or ""]
    return {m.group(1) for v in vals for m in REF_RE.finditer(str(v))}


def _public(cfg: dict) -> dict:
    headers, lh = _masked(cfg.get("headers"), plain=PLAIN_HEADERS)
    env, le = _masked(cfg.get("env"))
    args = [MASK if hid else str(a) for a, hid in zip(_list(cfg.get("args")), _secret_args(cfg.get("args")))]
    url = cfg.get("url")
    shown = _url_masked(str(url)) if url else url
    return {"type": _kind(cfg), "url": shown, "command": cfg.get("command"),
            "args": args, "headers": headers, "env": env,
            "literal_secret": lh or le or MASK in args or shown != url,
            "keys": sorted(_refs(cfg))}


def _id(scope: str, folder: str | None, name: str) -> str:
    return f"{scope}|{folder or ''}|{name}"


def _file_name(name: str) -> bool:
    """A name written by hand in a .mcp.json ("my server", accents): listed, so it can be removed too (it is only
    ever passed to the CLI after "--")."""
    return 0 < len(name) <= 200 and name.isprintable() and not name.startswith("-")


def parse_id(sid: str) -> tuple[str, str | None, str]:
    try:
        scope, folder, name = sid.split("|", 2)
    except ValueError:
        raise McpError(400, "bad_id", "unknown MCP server id") from None
    if scope not in ("user", "local", "project") or not (NAME_RE.match(name) or scope == "project" and _file_name(name)):
        raise McpError(400, "bad_id", "unknown MCP server id")
    if scope == "project":                               # its .mcp.json is rewritten: a folder of the workspace only
        try:
            Path(folder).resolve().relative_to(_ws().resolve())
        except (ValueError, OSError):
            folder = ""
        if not folder or not Path(folder).is_absolute():
            raise McpError(400, "bad_id", "unknown MCP server id")
    return scope, (folder or None), name


def _project_files() -> list[Path]:
    root = _ws() / "projects"
    if not root.is_dir():
        return []
    return sorted([*root.glob("*/.mcp.json"), *root.glob("*/topics/*/.mcp.json")])


def servers() -> list[dict]:
    """Every MCP server Claude Code would load in this workspace, with its last known state."""
    d = _read_cfg()
    out: list[dict] = []

    def add(scope: str, folder: str | None, name: str, cfg: Any, **extra) -> None:
        if not isinstance(cfg, dict):
            return
        st = _status.get(_id(scope, folder, name)) or {}
        out.append({"id": _id(scope, folder, name), "name": name, "scope": scope, "where": where_of(folder),
                    **_public(cfg), "state": st.get("state", "unknown"), "detail": st.get("detail"),
                    "checked_at": st.get("at"), **extra})
    for name, cfg in _dict(d.get("mcpServers")).items():
        add("user", None, name, cfg)
    projects = _dict(d.get("projects"))
    for folder, p in projects.items():
        for name, cfg in _dict(_dict(p).get("mcpServers")).items():
            add("local", folder, name, cfg)
    for f in _project_files():
        try:
            servers_ = _dict(_dict(json.loads(f.read_text(encoding="utf-8"))).get("mcpServers"))
        except (OSError, ValueError):
            continue
        folder = str(f.parent)
        p = _dict(projects.get(folder))
        for name, cfg in servers_.items():
            approved = bool(p.get("enableAllProjectMcpServers")) or name in _list(p.get("enabledMcpjsonServers"))
            add("project", folder, name, cfg, approved=approved)
    order = {"user": 0, "local": 1, "project": 2}
    return sorted(out, key=lambda s: (order[s["scope"]], s["where"].get("rel") or "", s["name"].lower()))


# ---- the CLI -----------------------------------------------------------------------------------
def _env() -> dict[str, str]:
    from .sessions import spawn
    return spawn.claude_env()


def _bin() -> str:
    from .sessions import spawn
    return spawn.claude_bin()


def _cwd(folder: str | None) -> str:
    if folder is None:
        return str(_ws())
    if not Path(folder).is_dir():
        raise McpError(404, "folder_missing", f"{folder} no longer exists")
    return folder


def _cli(args: list[str], folder: str | None, timeout: int = CLI_TIMEOUT) -> str:
    try:
        r = subprocess.run([_bin(), "mcp", *args], cwd=_cwd(folder), env=_env(), capture_output=True, text=True,
                           timeout=timeout, errors="replace", stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise McpError(500, "no_claude", "Claude Code is not installed") from None
    except OSError as e:
        raise McpError(500, "cli_failed", f"cannot start Claude Code: {e}") from None
    except subprocess.TimeoutExpired:
        raise McpError(504, "timeout", f"claude mcp {args[0]} took more than {timeout} s") from None
    out = ANSI_RE.sub("", (r.stdout or "") + (r.stderr or ""))
    if r.returncode != 0:
        msg = next((ln.strip() for ln in reversed(out.splitlines()) if ln.strip()), "claude mcp failed")
        raise McpError(400, "cli_failed", msg[:400])
    return out


# ---- status --------------------------------------------------------------------------------------
_lock = threading.Lock()
_status: dict[str, dict] = {}
_check: dict[str, Any] = {"running": False, "at": None}
LIST_LINE = re.compile(r"^(?P<name>[A-Za-z0-9_.-]{1,64}): (?P<what>.*) - (?P<mark>\S)️?\s+(?P<detail>.*)$")


def parse_list(out: str) -> dict[str, dict]:
    res = {}
    for ln in out.splitlines():
        m = LIST_LINE.match(ln.strip())
        if m:
            detail = m.group("detail").strip()
            state = STATES.get(m.group("mark")) or next((st for w, st in WORDS if w in detail.lower()), "unknown")
            res[m.group("name")] = {"state": state, "detail": detail[:200]}
    return res


def check(wait: bool = False) -> dict:
    """Refresh every server's state in the background (`claude mcp list` per folder). `wait` = synchronous."""
    deadline = time.time() + 300
    while True:
        with _lock:
            if not _check["running"]:
                _check["running"] = True
                break
        if not wait or time.time() > deadline:
            return dict(_check)
        time.sleep(0.1)                              # a check already runs: wait for it, then check again

    def run() -> None:
        try:
            todo: dict[str | None, list[dict]] = {}
            for s in servers():
                folder = s["where"]["path"]
                todo.setdefault(folder, []).append(s)
            for folder, items in sorted(todo.items(), key=lambda kv: kv[0] is not None):
                if folder is not None and not Path(folder).is_dir():
                    for s in items:
                        _status[s["id"]] = {"state": "failed", "detail": "folder no longer exists", "at": time.time()}
                    continue
                try:
                    found = parse_list(_cli(["list"], folder, timeout=120))
                except McpError as e:
                    found = {}
                    for s in items:
                        _status[s["id"]] = {"state": "failed", "detail": e.message, "at": time.time()}
                    continue
                for s in items:
                    if s["name"] in found:
                        _status[s["id"]] = {**found[s["name"]], "at": time.time()}
        finally:
            with _lock:
                _check.update(running=False, at=time.time())
            from . import bus
            bus.invalidate("mcp")
    if wait:
        run()
    else:
        threading.Thread(target=run, name="mcp-check", daemon=True).start()
    return dict(_check)


def overview() -> dict:
    _gc()                                            # abandoned OAuth logins go when the page is (re)loaded
    return {"servers": servers(), "checking": _check["running"], "checked_at": _check["at"],
            "config_file": str(_cfg_path())}


# ---- add / remove ------------------------------------------------------------------------------
def _folder_of(where: str | None) -> str | None:
    """`where` from the UI: None/"" = every session, else a workspace-relative topic or project folder."""
    if not where:
        return None
    if ".." in Path(where).parts or where.startswith("/"):
        raise McpError(400, "bad_where", "where must be a folder of the workspace")
    p = _ws() / where
    if not p.is_dir():
        raise McpError(404, "folder_missing", f"{where} does not exist")
    return str(p)


MAX_VALUE = 8192                                         # one address, argument, header or env value


def build(spec: dict) -> dict:
    """Claude Code server config from the UI form: {type, url | command + args, headers, env}."""
    t = spec.get("type") or ("stdio" if spec.get("command") else "http")
    clean = lambda d: {str(k).strip(): str(v) for k, v in (d or {}).items() if str(k).strip()}  # noqa: E731
    if t in ("http", "sse"):
        url = str(spec.get("url") or "").strip()
        if not re.match(r"^https?://\S+$", url):
            raise McpError(400, "bad_url", "the address must start with https://")
        cfg: dict = {"type": t, "url": url}
        if clean(spec.get("headers")):
            cfg["headers"] = clean(spec.get("headers"))
    elif t == "stdio":
        command = str(spec.get("command") or "").strip()
        if not command:
            raise McpError(400, "bad_command", "a command is required")
        args = spec.get("args")
        try:
            if isinstance(args, str):
                args = shlex.split(args)
            if not isinstance(args, list):
                args = []
            if " " in command and not args:
                command, *args = shlex.split(command)
        except ValueError as e:                            # unbalanced quotes
            raise McpError(400, "bad_command", f"the command cannot be parsed: {e}") from None
        cfg = {"type": "stdio", "command": command, "args": [str(a) for a in args]}
        if clean(spec.get("env")):
            cfg["env"] = clean(spec.get("env"))
    else:
        raise McpError(400, "bad_type", "type must be http, sse or stdio")
    values = [cfg.get("url") or cfg.get("command"), *cfg.get("args", []),
              *[v for d in (cfg.get("headers"), cfg.get("env")) for kv in (d or {}).items() for v in kv]]
    if any(len(v) > MAX_VALUE for v in values) or sum(map(len, values)) > 4 * MAX_VALUE:
        raise McpError(400, "too_long", f"each value is limited to {MAX_VALUE} characters")
    return cfg


def _expose_refs(cfg: dict) -> list[str]:
    """Vault keys referenced as ${KEY}: flagged `expose` so Claude Code finds them in its environment."""
    from . import vault
    exposed = []
    hidden = {r["name"] for r in vault.list_secrets() if not r.get("expose")}
    for n in sorted(_refs(cfg) & hidden):
        try:
            vault.put(n, expose=True)
            exposed.append(n)
        except Exception:                                  # reserved names etc.: Claude Code reports it
            pass
    return exposed


def _redacted(cfg: dict) -> dict:
    """`cfg` without its literal secrets, for the command line (which every local user sees in `ps`)."""
    c = dict(cfg)
    for k in ("headers", "env"):
        if k in c:
            c[k] = {str(n): (str(v) if _only_refs(v) else "") for n, v in _dict(c[k]).items()}
    if "args" in c:
        c["args"] = ["" if hid else a for a, hid in zip(_list(c["args"]), _secret_args(c["args"]))]
    if c.get("url"):
        c["url"] = _url_masked(str(c["url"]), "") or "https://redacted.invalid/"
    return c


def _add_json(scope: str, folder: str | None, name: str, cfg: dict) -> None:
    """`claude mcp add-json` with the secrets left out of its arguments, then the real config written in place
    (.claude.json is private, the process list is not)."""
    shown = _redacted(cfg)
    _cli(["add-json", "-s", scope, "--", name, json.dumps(shown)], folder)
    if shown == cfg:
        return

    done = []

    def put(d: dict) -> bool:
        box = d.get("mcpServers") if folder is None else _dict(_dict(d.get("projects")).get(folder)).get("mcpServers")
        if not isinstance(box, dict) or name not in box:
            return False
        box[name] = cfg
        done.append(True)
        return True
    try:
        _write_cfg(put)
    except Exception:
        done.clear()
    if not done:                         # never leave a server registered with its secrets blanked out
        try:
            _cli(["remove", "-s", scope, "--", name], folder)
        except McpError:
            pass
        raise McpError(500, "not_saved", f"{name}: the CLI added it, but its configuration could not be completed")


def add(name: str, spec: dict, where: str | None) -> dict:
    if not NAME_RE.match(name or ""):
        raise McpError(400, "bad_name", "names use letters, digits, '.', '_' and '-' (64 at most)")
    folder = _folder_of(where)
    cfg = build(spec)
    scope = "user" if folder is None else "local"
    if any(s["name"] == name and s["scope"] == scope and s["where"]["path"] == folder for s in servers()):
        raise McpError(409, "exists", f"{name} already exists there")
    exposed = _expose_refs(cfg)
    try:
        _add_json(scope, folder, name, cfg)
    except BaseException:                                  # no server uses them: hide them again
        from . import vault
        for n in exposed:
            try:
                vault.put(n, expose=False)
            except Exception:
                pass
        raise
    sid = _id(scope, folder, name)
    _status.pop(sid, None)
    check()
    return {"id": sid, "exposed": exposed}


_write_lock = threading.Lock()
CFG_LOCK_WAIT = 10.0                                # s to wait for Claude Code's lock on .claude.json
CFG_LOCK_STALE = 10.0                               # s after which a lock left by a dead writer is taken over


def _cfg_lock(target: Path) -> Path | None:
    """Claude Code's own lock on .claude.json (proper-lockfile: a `<file>.lock` folder next to the real file).
    Returns the folder to remove, or None when it could not be taken in time (the write goes ahead anyway)."""
    lock = target.with_name(target.name + ".lock")
    deadline = time.monotonic() + CFG_LOCK_WAIT
    while True:
        try:
            lock.mkdir()
            return lock
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > CFG_LOCK_STALE:
                    lock.rmdir()
                    continue
            except FileNotFoundError:
                continue                            # released meanwhile: take it
            except OSError:
                pass                                # cannot be taken over (a file, a full folder): wait, give up
        except OSError:
            return None
        if time.monotonic() > deadline:
            return None
        time.sleep(0.05)


def _write_cfg(fn) -> None:
    """Read-modify-write of .claude.json (only for what the CLI cannot do: renamed or deleted folders), under
    Claude Code's lock so a key it writes meanwhile is not lost. A symlinked file (dotfiles) is written through
    the link, which stays a link."""
    target = _cfg_path().resolve()
    with _write_lock:
        lock = _cfg_lock(target)
        try:
            d = _read_cfg(fresh=True)
            if not d or not fn(d):
                return
            # the file holds the Claude account (maybe an API key): the copy is private from its creation, unique
            tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex[:12]}.mx-tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(d, indent=2, ensure_ascii=False))
                os.replace(tmp, target)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
        finally:
            if lock is not None:
                try:
                    lock.rmdir()
                except OSError:
                    pass


def _write_mcp_json(f: Path, data: dict) -> None:
    """Rewrite a .mcp.json atomically (a failed write leaves the old file whole); a value that cannot be written
    as UTF-8 (a lone surrogate) is escaped instead of losing the file."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        raw = (json.dumps(data, indent=2) + "\n").encode("ascii")
    target = f.resolve()                                 # a symlinked file is written through the link
    tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex[:12]}.mx-tmp")
    try:
        mode = target.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def remove(sid: str) -> None:
    scope, folder, name = parse_id(sid)
    if scope == "project":
        f = Path(folder or "") / ".mcp.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data.get("mcpServers", {}).pop(name)
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            raise McpError(404, "not_found", f"no {name} in {f}") from None
        _write_mcp_json(f, data)
    elif folder is not None and not Path(folder).is_dir():
        def drop(d: dict) -> bool:
            p = _dict(_dict(d.get("projects")).get(folder))
            return _dict(p.get("mcpServers")).pop(name, None) is not None
        _write_cfg(drop)
    else:
        _cli(["remove", "-s", scope, "--", name], folder)
    _status.pop(sid, None)


def on_workspace_change(change: dict) -> None:
    """A renamed project / topic keeps its MCP servers: move its .claude.json entry (and the ones below it)."""
    if change.get("action") != "renamed" or not change.get("old_path") or not change.get("path"):
        return
    old, new = str(_ws() / change["old_path"]), str(_ws() / change["path"])

    def move(d: dict) -> bool:
        projects = d.get("projects")
        if not isinstance(projects, dict):
            return False
        moved = False
        for key in [k for k in projects if k == old or k.startswith(old + "/")]:
            target = new + key[len(old):]
            if target not in projects:
                projects[target] = projects.pop(key)
                moved = True
        return moved
    try:
        _write_cfg(move)
    except OSError:
        pass


# ---- backup ------------------------------------------------------------------------------------
def export() -> list[dict]:
    """user + local servers for the memory backup: folders relative to the workspace, literal secrets blanked."""
    d = _read_cfg()
    out = []

    def item(name: str, cfg: dict, rel: str | None) -> dict:
        c = dict(cfg)
        for k in ("headers", "env"):
            if k in c:
                c[k] = _blank_secrets(c[k])
        if "args" in c:
            c["args"] = ["" if hid else a for a, hid in zip(_list(c["args"]), _secret_args(c["args"]))]
        if c.get("url"):
            c["url"] = _url_masked(str(c["url"]), "")
        return {"name": name, "where": rel, "config": c}
    for name, cfg in _dict(d.get("mcpServers")).items():
        if isinstance(cfg, dict):
            out.append(item(name, cfg, None))
    for folder, p in _dict(d.get("projects")).items():
        rel = where_of(folder)["rel"]
        if rel is None or not isinstance(p, dict):
            continue
        for name, cfg in _dict(p.get("mcpServers")).items():
            if isinstance(cfg, dict):
                out.append(item(name, cfg, rel))
    return out


def restore(items: list) -> int:
    """Add back the servers of a backup that are missing here. Returns how many were added."""
    have = {(s["name"], s["where"]["rel"]) for s in servers() if s["scope"] in ("user", "local")}
    n = 0
    for it in items if isinstance(items, list) else []:
        try:
            name, rel, cfg = it["name"], it.get("where"), it["config"]
            if (name, rel) in have or not NAME_RE.match(name) or not isinstance(cfg, dict):
                continue
            folder = _folder_of(rel)
            _add_json("user" if folder is None else "local", folder, name, cfg)
            n += 1
        except (McpError, KeyError, TypeError, ValueError):
            continue
    return n


# ---- OAuth login in a pseudo-terminal ----------------------------------------------------------
class _Login:
    """One `claude mcp login` on a pty. The fd number is freed only once the reader thread is gone: a number
    closed under a running select()/read() is reused by the next open() of any component, whose data it would eat."""

    def __init__(self, sid: str, proc: subprocess.Popen, fd: int):
        self.sid, self.proc, self.fd = sid, proc, fd
        self.buf = ""
        self.started = time.time()
        self.finishing = False
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.reader = threading.Thread(target=self._read, name="mcp-login", daemon=True)
        self.reader.start()

    def _read(self) -> None:
        while not self.closed.is_set():
            try:
                r, _, _ = select.select([self.fd], [], [], 0.2)
                if self.closed.is_set():
                    break
                if r:
                    data = os.read(self.fd, 4096)
                    if not data:
                        break
                    with self.lock:
                        self.buf += data.decode("utf-8", "replace")
                elif self.proc.poll() is not None:
                    break
            except (OSError, ValueError):
                break

    def text(self) -> str:
        with self.lock:
            raw = self.buf
        # OSC 8 hyperlinks carry the URL inside the escape: keep it as plain text before stripping
        raw = re.sub(r"\x1b\]8;[^;]*;([^\x07\x1b]*)(?:\x07|\x1b\\)", r" \1 ", raw)
        return ANSI_RE.sub("", raw).replace("\r", "")

    def url(self) -> str | None:
        urls = [u.rstrip(".,)") for u in URL_RE.findall(self.text())]
        urls = [u for u in urls if not u.startswith(("http://localhost", "http://127.0.0.1"))]
        return next((u for u in urls if "authorize" in u or "oauth" in u), urls[0] if urls else None)

    def write(self, data: bytes) -> None:
        with self.lock:                                  # close() cannot free the fd in the middle
            if self.closed.is_set():
                raise McpError(404, "login_expired", "this connection attempt expired: start again")
            os.write(self.fd, data)

    def close(self) -> None:
        """Idempotent: stop the CLI (its whole process group), wait for the reader, then free the fd."""
        with self.lock:
            if self.closed.is_set():
                return                                   # closed once: the number may belong to someone else now
            self.closed.set()
        try:
            if self.proc.poll() is None:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)         # started in its own session: children go too
                except OSError:
                    self.proc.kill()
            self.proc.wait(timeout=5)
        except Exception:                                # noqa: BLE001
            pass
        if self.reader is not threading.current_thread():
            self.reader.join(timeout=5)
        if self.reader.is_alive():                       # never seen: leak the fd rather than free it under a read
            return
        try:
            os.close(self.fd)
        except OSError:
            pass


_logins: dict[str, _Login] = {}
_logins_lock = threading.Lock()
_reaper: dict[str, Any] = {"thread": None}


def _gc() -> None:
    """Close the logins nobody finished nor cancelled (a tab closed): each one keeps a claude process alive."""
    now = time.time()
    with _logins_lock:
        old = [k for k, lg in _logins.items() if not lg.finishing and
               (now - lg.started > LOGIN_TTL or (lg.proc.poll() is not None and now - lg.started > 120))]
        gone = [_logins.pop(k) for k in old]
    for lg in gone:
        lg.close()


def _reap() -> None:
    while True:
        time.sleep(GC_EVERY)
        _gc()
        with _logins_lock:
            if not _logins:
                _reaper["thread"] = None
                return


def _register(key: str, lg: _Login) -> None:
    """Keep the login; an older one for the same server (the user clicked Connect again) is replaced."""
    with _logins_lock:
        gone = [_logins.pop(k) for k, o in list(_logins.items()) if o.sid == lg.sid]
        _logins[key] = lg
        if _reaper["thread"] is None:
            _reaper["thread"] = threading.Thread(target=_reap, name="mcp-login-gc", daemon=True)
            _reaper["thread"].start()
    for o in gone:
        o.close()


def _drop_logins_of(sid: str) -> None:
    with _logins_lock:
        gone = [_logins.pop(k) for k, o in list(_logins.items()) if o.sid == sid and not o.finishing]
    for o in gone:
        o.close()


def login_start(sid: str, wait: float = 30.0) -> dict:
    scope, folder, name = parse_id(sid)
    _gc()
    cwd = _cwd(folder)                                   # before the pty: a missing folder leaks nothing
    _drop_logins_of(sid)                                 # one CLI per server (they would race on the callback)
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen([_bin(), "mcp", "login", "--no-browser", "--", name], cwd=cwd, env=_env(),
                                stdin=slave, stdout=slave, stderr=slave, close_fds=True, start_new_session=True)
    except BaseException as e:
        os.close(master)
        if isinstance(e, FileNotFoundError):
            raise McpError(500, "no_claude", "Claude Code is not installed") from None
        if isinstance(e, OSError):
            raise McpError(500, "cli_failed", f"cannot start Claude Code: {e}") from None
        raise
    finally:
        os.close(slave)
    lg = _Login(sid, proc, master)
    deadline = time.time() + wait
    while time.time() < deadline:
        u = lg.url()
        if u:
            key = uuid.uuid4().hex
            _register(key, lg)
            return {"login": key, "url": u}
        if proc.poll() is not None:
            break
        time.sleep(0.2)
    out = lg.text().strip().splitlines()
    lg.close()
    msg = next((ln.strip() for ln in reversed(out) if ln.strip()), "no authorization address")
    raise McpError(400, "no_login_url", msg[:300])


def login_finish(key: str, redirect: str, wait: float = 60.0) -> dict:
    _gc()
    redirect = (redirect or "").strip()
    with _logins_lock:
        lg = _logins.get(key)
        if lg is None or lg.closed.is_set():
            raise McpError(404, "login_expired", "this connection attempt expired: start again")
        if not re.match(r"^https?://\S+$", redirect):
            raise McpError(400, "bad_redirect", "paste the full address of the page you landed on")
        if lg.finishing:
            raise McpError(409, "busy", "this connection is already being finished")
        lg.finishing = True
    try:
        before = len(lg.text())
        lg.write((redirect + "\r").encode())
        deadline = time.time() + wait
        while time.time() < deadline and lg.proc.poll() is None and not lg.closed.is_set():
            time.sleep(0.2)
        cancelled = lg.closed.is_set()
        tail = lg.text()[before:].strip().splitlines()
        code = lg.proc.poll()
    finally:
        with _logins_lock:
            if _logins.get(key) is lg:
                _logins.pop(key)
        lg.close()
    if cancelled:
        raise McpError(404, "login_expired", "this connection attempt was cancelled")
    msg = next((ln.strip() for ln in reversed(tail) if ln.strip() and redirect[:30] not in ln), "")
    if code is None:
        raise McpError(504, "timeout", "Claude Code did not finish the connection")
    if code != 0:
        raise McpError(400, "login_failed", msg[:300] or "the connection failed")
    _status[lg.sid] = {"state": "connected", "detail": "", "at": time.time()}
    from . import bus
    bus.invalidate("mcp")
    return {"ok": True, "message": msg[:300]}


def login_cancel(key: str) -> None:
    with _logins_lock:
        lg = _logins.pop(key, None)
    if lg:
        lg.close()
