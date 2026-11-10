"""Approval MCP server - asks the user before a tool runs.  STDLIB ONLY, runs as a plain script.

    python /path/to/maxxing/approval_mcp.py          (started by Claude Code from the turn's --mcp-config)

A turn of an agent with `approvals: true` runs `claude -p --permission-mode default
--permission-prompt-tool mcp__maxxing-approval__approve`: when a tool is not pre-allowed, Claude Code calls our
`approve` tool with {tool_name, input, tool_use_id} and waits. We write a pending request

    <state>/approvals/<id>.json   {id, session, agent_path, tool, input (clipped), at, status: "pending", expires,
                                   clipped (true when the input shown is not all of it: Allow is refused)}

and poll it every POLL_S until the server (maxxing.approvals, the user's Allow / Deny) sets `status` to "allow" or
"deny", or until the timeout (MAXXING_APPROVAL_TIMEOUT, seconds) -> status "timeout" and a deny. The answer is the
text block Claude Code expects: {"behavior": "allow", "updatedInput": <original input>} or
{"behavior": "deny", "message": "..."}. When Claude Code goes away (stdin closed: the turn was stopped), the
requests still waiting are marked "expired".

Framing: JSON-RPC 2.0, one message per line on stdin / stdout (MCP stdio transport). Environment (set by the
runner in the MCP config): MAXXING_APPROVAL_DIR, MAXXING_SESSION, MAXXING_AGENT_PATH, MAXXING_APPROVAL_TIMEOUT.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from typing import Any

SERVER_NAME = "maxxing-approval"
TOOL_NAME = "approve"
PROMPT_TOOL = f"mcp__{SERVER_NAME}__{TOOL_NAME}"   # the --permission-prompt-tool value
POLL_S = 0.5
DEFAULT_TIMEOUT_S = 1800.0
STR_MAX = 4000            # characters kept of each string of the tool input (display only)
INPUT_MAX = 20000         # characters of the whole clipped input
DECIDED = ("allow", "deny", "timeout", "expired")
PROTOCOL = "2025-06-18"

_out_lock = threading.Lock()
_mine: set[str] = set()   # ids of the requests this process is waiting for
_mine_lock = threading.Lock()


# ---- request files (also used by the runner and the server) ------------------------------------------
def write_atomic(f: Path, data: dict) -> None:
    tmp = f.with_name(f".{f.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)                             # ASCII: a lone surrogate in a tool input is stored too
        os.replace(tmp, f)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read(f: Path) -> dict | None:
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError, RecursionError):      # RecursionError: JSON nested too deep
        return None
    return d if isinstance(d, dict) else None


def clip(v: Any, budget: list[int] | None = None, depth: int = 0) -> Any:
    """The tool input for display: long strings cut, deep or huge structures summarised."""
    budget = budget if budget is not None else [INPUT_MAX]
    if budget[0] <= 0:
        return "..."
    if isinstance(v, str):
        s = v if len(v) <= STR_MAX else v[:STR_MAX] + f"... [{len(v) - STR_MAX} more characters]"
        s = s[:max(budget[0], 3)]
        budget[0] -= len(s)
        return s
    if isinstance(v, (int, float, bool)) or v is None:
        budget[0] -= 8
        return v
    if depth >= 6:
        return "..."
    if isinstance(v, dict):
        return {str(k)[:200]: clip(x, budget, depth + 1) for k, x in list(v.items())[:100]}
    if isinstance(v, (list, tuple)):
        return [clip(x, budget, depth + 1) for x in list(v)[:100]]
    return str(v)[:200]


def expire(folder: Path, session: str | None = None, ids: set[str] | None = None, reason: str = "expired") -> int:
    """Marks the pending requests of a session (or the given ids) as `reason`. Returns how many changed."""
    n = 0
    try:
        files = list(folder.glob("*.json"))
    except OSError:
        return 0
    for f in files:
        d = read(f)
        if not d or d.get("status") != "pending":
            continue
        if session is not None and ids is None and d.get("kind") == "agent_change":
            continue                    # a settings change waits for the owner after the turn (agents.request_change)
        if (ids is not None and d.get("id") not in ids) or (session is not None and d.get("session") != session):
            continue
        d.update(status=reason, decided_at=time.time())
        try:
            write_atomic(f, d)
            n += 1
        except OSError:
            pass
    return n


# ---- the tool -------------------------------------------------------------------------------------
@contextlib.contextmanager
def _state_lock(folder: Path, wait: float = 5.0):
    """The flock of the server's `config.ProcessLock("approvals")` (<state>/.approvals.lock, next to the folder),
    at most `wait` seconds (then without it)."""
    try:
        fd = os.open(folder.parent / ".approvals.lock", os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        yield
        return
    try:
        end = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    break
                time.sleep(0.02)
            except OSError:
                break
        yield
    finally:
        os.close(fd)                                # closing drops the flock


def _folder() -> Path:
    d = Path(os.environ.get("MAXXING_APPROVAL_DIR") or "approvals")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("MAXXING_APPROVAL_TIMEOUT") or DEFAULT_TIMEOUT_S))
    except ValueError:
        return DEFAULT_TIMEOUT_S


def ask(args: dict, poll_s: float = POLL_S, ctx: dict | None = None) -> dict:
    """One permission prompt: write the request, wait for the answer, return Claude Code's expected object.
    ctx: {folder, session, agent_path, timeout} when the caller is not this MCP server (the runner answering Claude
    Code's own `can_use_tool` requests), else the environment."""
    tool = str(args.get("tool_name") or "")[:200] or "?"
    tool_input = args.get("input") if isinstance(args.get("input"), dict) else {}
    if ctx:
        folder, timeout = Path(ctx["folder"]), float(ctx["timeout"])
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    else:
        folder, timeout = _folder(), _timeout()
    rid = secrets.token_hex(8)
    now = time.time()
    req = {"id": rid, "session": (ctx or {}).get("session") or os.environ.get("MAXXING_SESSION") or "",
           "agent_path": (ctx or {}).get("agent_path") if ctx else os.environ.get("MAXXING_AGENT_PATH") or "",
           "tool": tool, "input": clip(tool_input),
           "tool_use_id": str(args.get("tool_use_id") or "")[:200], "at": now, "expires": now + timeout,
           "status": "pending"}
    if req["input"] != tool_input:          # what Allow would run is not all shown: it can only be denied
        req["clipped"] = True
    f = folder / f"{rid}.json"
    with _mine_lock:
        _mine.add(rid)
    try:
        write_atomic(f, req)
        while True:
            time.sleep(poll_s)
            d = read(f) or {}
            st = d.get("status")
            if st == "allow":
                return {"behavior": "allow", "updatedInput": tool_input}
            if st == "deny":
                msg = str(d.get("message") or "").strip()
                return {"behavior": "deny", "message": ("The user denied this action" + (f": {msg}" if msg else "."))[:2000]}
            if st in ("timeout", "expired") or not d:
                return {"behavior": "deny", "message": "No answer in time: the action was not allowed."}
            if time.time() >= now + timeout:
                with _state_lock(folder):              # the server's lock (approvals.decide): one answer wins
                    cur = read(f) or {}
                    if cur.get("status") == "pending":     # the user did not answer meanwhile
                        write_atomic(f, {**cur, "status": "timeout", "decided_at": time.time()})
                        return {"behavior": "deny", "message": "No answer in time: the action was not allowed."}
                # answered at the last second: the next poll returns that answer
    finally:
        with _mine_lock:
            _mine.discard(rid)


# ---- JSON-RPC over stdio ----------------------------------------------------------------------------
def _send(msg: dict) -> None:
    line = json.dumps(msg, ensure_ascii=False)
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


TOOLS = [{
    "name": TOOL_NAME,
    "description": "Internal to Harness: asks the user to allow a tool call. Never call it yourself.",
    "inputSchema": {"type": "object", "properties": {
        "tool_name": {"type": "string"}, "input": {"type": "object"}, "tool_use_id": {"type": "string"}},
        "required": ["tool_name", "input"]},
}]


def _call(mid: Any, params: dict) -> None:
    try:
        if params.get("name") != TOOL_NAME:
            _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unknown tool"}})
            return
        out = ask(params.get("arguments") if isinstance(params.get("arguments"), dict) else {})
    except Exception as e:  # noqa: BLE001 - never leave Claude Code waiting
        out = {"behavior": "deny", "message": f"Approval failed: {type(e).__name__}"}
    _send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(out)}]}})


def handle(msg: Any) -> dict | None:
    """Answer to one message (None: notification, or tools/call answered later by its own thread)."""
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        return None                                     # notifications (initialized, cancelled...)
    if method == "initialize":
        p = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": p.get("protocolVersion") or PROTOCOL, "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": "1"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        threading.Thread(target=_call, args=(mid, params), daemon=True).start()
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (ValueError, RecursionError):            # RecursionError: JSON nested too deep (the loop went down)
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        out = handle(msg)
        if out is not None:
            _send(out)
    with _mine_lock:                                    # Claude Code went away: nobody can use an answer
        ids = set(_mine)
    if ids:
        expire(_folder(), ids=ids)
    return 0


if __name__ == "__main__":
    sys.exit(main())
