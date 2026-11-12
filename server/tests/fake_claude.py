#!/usr/bin/env python3
"""Fake `claude` CLI for tests: same flags as the runner uses, realistic stream-json output.

Event shapes are modelled on real Claude Code 2.x logs (system/init, assistant thinking/text/
tool_use, user tool_result, rate_limit_event, result with usage + modelUsage).

Behaviour is driven by the prompt (read from stdin, or a positional argument):
  SLOW          long turn (~30 s) - for stop / queue tests
  AGENTS        two background sub-agents and a background command (task_* lines), FAKE_CLAUDE_AGENTS_S long
  FAIL          prints an error, exits 1 (after init)
  RESUME_FAIL   with --resume: fails like the real CLI when the thread is gone
  PAUSE         short turn (~1.5 s) - for queue tests
  NOTOOL        no tool call
  ORPHAN        leaves a background program holding stdout open (30 s)
  CHATTY        leaves a background program writing to stdout every 0.1 s (30 s)
  HUGE          a 3 MB tool result, an image result and a 100 kB Write input (log clipping tests)
  AUTH_EXPIRED  (or env FAKE_CLAUDE_AUTH_EXPIRED=1) fails like an expired OAuth sign-in
  BIGCTX        the last answer reports a 150k-token context (automatic compaction tests)
  MCPUSE:<srv>  calls the tool mcp__<srv>__ping (MCP auto-loading tests)
  MCPLOAD       runs `maxxing mcp load $FAKE_CLAUDE_MCPLOAD` (python -m maxxing) like a turn asking for a server
  APPROVE       asks the --permission-prompt-tool MCP server about a Bash call (approval tests)
  ASKNET        (stream-json input) asks the host on the control channel to reach example.org (`can_use_tool`
                SandboxNetworkAccess, like the sandbox) and writes the answer to $FAKE_CLAUDE_DIR/asknet.txt
  REPLY_AS x: t answers t when the turn runs in a folder named x (agent groups; the last such line wins)
  MCPINIT       the init event lists the user server Facebook-ads and the connector "claude.ai Google Drive"
  NORESULT      exits right after the init line (no result), stdin still open
  WAITMSG       (stream-json input) waits up to $FAKE_CLAUDE_WAITMSG_S s (default 10) for a user message written
                to stdin during the turn and folds it into the SAME turn ("Read mid-turn: <text>"), like Claude
                Code reading a message queued while it works at its next step; a message after it is a new turn
  BGTASK:<name> starts a background command (task_started / background_tasks_changed) that ends after
                $FAKE_CLAUDE_BG_S s (default 3): writes $FAKE_CLAUDE_DIR/bg-<name>.done, task_notification, then a
                turn by itself ("Background task <name> finished.") - like Claude Code
With `--input-format stream-json`, stdin is read line by line like the real CLI: each user message is a turn,
`{"type":"control_request","request":{"subtype":"interrupt"}}` cuts the running turn short (SLOW / PAUSE stop,
result `error_during_execution`; background tasks keep running), and the process exits once stdin is closed and
no background task is left.
A `--system-prompt` that names chat sessions (short titles) gets $FAKE_CLAUDE_TITLE (default "Fake short
title") as its `-p --output-format json` answer; FAIL / AUTH_EXPIRED in the message still fail.
Threads are remembered in $FAKE_CLAUDE_DIR (default /tmp/fake-claude-<uid>): --resume of an
unknown id fails ("No conversation found…"), --session-id of a known id fails ("already in use").
Every call is appended to $FAKE_CLAUDE_DIR/calls.jsonl (argv, prompt, cwd, a few env vars).
`claude mcp list|add-json|remove|login` edit $CLAUDE_CONFIG_DIR/.claude.json like the real CLI; an http server
without headers "needs authentication" until `mcp login` gets a redirect URL containing `code=`.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path

VERSION = "2.1.0 (Claude Code)"
DEFAULT_MODEL = "claude-sonnet-5-5"
DELAY = float(os.environ.get("FAKE_CLAUDE_DELAY", "0.05"))
STORE = Path(os.environ.get("FAKE_CLAUDE_DIR") or f"/tmp/fake-claude-{os.getuid()}")


def parse(argv: list[str]) -> dict:
    o: dict = {"print": False, "format": "text", "verbose": False, "model": None, "session_id": None,
               "resume": None, "permission_mode": None, "skip": False, "version": False, "prompt": None,
               "input": "text"}
    it = iter(argv)
    with_value = {"--output-format": "format", "--model": "model", "--session-id": "session_id",
                  "--resume": "resume", "--permission-mode": "permission_mode", "-r": "resume",
                  "--input-format": "input", "--settings": "settings", "--tools": "tools",
                  "--system-prompt": "system_prompt", "--append-system-prompt": "append_system_prompt",
                  "--mcp-config": "mcp_config", "--permission-prompt-tool": "permission_prompt_tool",
                  "--max-budget-usd": "max_budget"}
    for a in it:
        if a in ("-p", "--print"):
            o["print"] = True
        elif a == "--verbose":
            o["verbose"] = True
        elif a == "--dangerously-skip-permissions":
            o["skip"] = True
        elif a in ("--version", "-v"):
            o["version"] = True
        elif a in with_value:
            o[with_value[a]] = next(it, None)
        elif not a.startswith("-"):
            o["prompt"] = a
    return o


def _agents(sid: str, model: str, seconds: float) -> None:
    """Claude Code's task_* lines: started, "launched" result at once, progress while they work, then the end."""
    jobs = [("a1", "Agent", "local_agent", "Review the server changes", {"subagent_type": "general-purpose"}),
            ("a2", "Agent", "local_agent", "Write the release notes", {"subagent_type": "general-purpose"}),
            ("b1", "Bash", "local_bash", "npm run build", {})]
    for tid, tool, kind, desc, extra in jobs:
        use = f"toolu_{tid}"
        inp = {"description": desc, "prompt": desc + ".", "run_in_background": True} if tool == "Agent" else \
            {"command": desc, "description": desc, "run_in_background": True}
        emit(msg(sid, model, [{"type": "tool_use", "id": use, "name": tool, "input": inp}]))
        emit({"type": "system", "subtype": "task_started", "task_id": tid, "tool_use_id": use, "task_type": kind,
              "description": desc, "is_backgrounded": True, "session_id": sid, **extra})
        emit({"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": use, "type": "tool_result", "content": "Async agent launched successfully." if tool == "Agent"
             else "Command running in background."}]}, "parent_tool_use_id": None, "session_id": sid})
    steps = max(1, int(seconds / 0.5))
    for i in range(1, steps + 1):
        time.sleep(seconds / steps)
        for tid in ("a1", "a2"):
            emit({"type": "system", "subtype": "task_progress", "task_id": tid, "tool_use_id": f"toolu_{tid}",
                  "description": f"Running pytest -q tests/test_step_{i}.py", "last_tool_name": "Bash",
                  "subagent_type": "general-purpose", "session_id": sid,
                  "usage": {"total_tokens": 4000 * i, "tool_uses": i, "duration_ms": int(i * 500)}})
    for tid, summary in (("b1", "npm run build"), ("a2", "Release notes written."), ("a1", "**Review done.** No bug found.")):
        emit({"type": "system", "subtype": "task_notification", "task_id": tid, "tool_use_id": f"toolu_{tid}",
              "status": "completed", "summary": summary, "session_id": sid})


EMIT_LOCK = threading.Lock()
INTERRUPT = threading.Event()
CONTROL: queue.Queue = queue.Queue()                   # the host's control_response lines (ASKNET)
EVENTS: queue.Queue = queue.Queue()                    # ("user", text, images) / ("bgdone", name) / ("eof",)
BG: dict[str, str] = {}                                # background tasks running: task id -> description
BG_LOCK = threading.Lock()
MIDTURN = threading.Event()                            # a WAITMSG turn takes the next user message itself
MID: queue.Queue = queue.Queue()


def emit(ev: dict) -> None:
    with EMIT_LOCK:
        sys.stdout.write(json.dumps(ev) + "\n")
        sys.stdout.flush()
    time.sleep(DELAY)


def _user_text(line: str) -> tuple[str, int] | None:
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    if not isinstance(ev, dict) or ev.get("type") != "user":
        return None
    content = ev["message"]["content"]
    if isinstance(content, str):
        return content, 0
    return ("".join(b.get("text", "") for b in content if b.get("type") == "text"),
            sum(1 for b in content if b.get("type") == "image"))


def _stdin_reader() -> None:
    for line in sys.stdin:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "control_response":
            CONTROL.put(ev)
            continue
        if isinstance(ev, dict) and ev.get("type") == "control_request":
            if (ev.get("request") or {}).get("subtype") == "interrupt":
                INTERRUPT.set()
            emit({"type": "control_response", "response": {"subtype": "success", "request_id": ev.get("request_id")}})
            continue
        got = _user_text(line)
        if got and MIDTURN.is_set():
            MIDTURN.clear()
            MID.put(got)
        elif got:
            EVENTS.put(("user", *got))
    EVENTS.put(("eof",))


def _tasks_changed(sid: str) -> None:
    emit({"type": "system", "subtype": "background_tasks_changed", "session_id": sid,
          "tasks": [{"task_id": t, "task_type": "local_bash", "description": d} for t, d in list(BG.items())]})


def _bg_task(sid: str, model: str, name: str) -> None:
    tid, use = f"bg_{name}", f"toolu_bg_{name}"
    cmd = f"sleep; touch bg-{name}.done"
    emit(msg(sid, model, [{"type": "tool_use", "id": use, "name": "Bash",
                           "input": {"command": cmd, "description": cmd, "run_in_background": True}}]))
    BG[tid] = cmd
    _tasks_changed(sid)
    emit({"type": "system", "subtype": "task_started", "task_id": tid, "tool_use_id": use, "task_type": "local_bash",
          "description": cmd, "is_backgrounded": True, "session_id": sid})
    emit({"type": "user", "message": {"role": "user", "content": [
        {"tool_use_id": use, "type": "tool_result", "content": f"Command running in background with ID: {tid}."}]},
        "parent_tool_use_id": None, "session_id": sid})

    def run() -> None:
        time.sleep(float(os.environ.get("FAKE_CLAUDE_BG_S", "3")))
        (STORE / f"bg-{name}.done").write_text("ok")
        with BG_LOCK:                                    # the turn it starts waits for these lines
            EVENTS.put(("bgdone", name))
            BG.pop(tid, None)
            emit({"type": "system", "subtype": "task_notification", "task_id": tid, "tool_use_id": use,
                  "status": "completed", "summary": cmd, "session_id": sid})
            _tasks_changed(sid)
    threading.Thread(target=run, daemon=True).start()


def _interrupted(sid: str, model: str, t0: float) -> None:
    r = result(sid, model, "", ok=False, t0=t0)
    emit(r)


def usage(inp: int = 3, out: int = 12, cr: int = 1200, cw: int = 300) -> dict:
    return {"input_tokens": inp, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr,
            "output_tokens": out, "service_tier": "standard"}


def msg(sid: str, model: str, content: list) -> dict:
    return {"type": "assistant", "message": {"model": model, "id": "msg_" + uuid.uuid4().hex[:20],
            "type": "message", "role": "assistant", "content": content, "stop_reason": None,
            "usage": usage()}, "parent_tool_use_id": None, "session_id": sid,
            "uuid": str(uuid.uuid4()), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}


def result(sid: str, model: str, text: str, ok: bool = True, errors: list | None = None, t0: float = 0,
           keep: bool = True) -> dict:
    # Like the real CLI, total_cost_usd is the running total of the thread (0.0123 per turn); a fork (side
    # question) starts from it without adding to it.
    f = STORE / f"{sid}.cost"
    try:
        before = float(f.read_text())
    except (OSError, ValueError):
        before = 0.0
    cost = round(before + 0.0123, 6) if ok else before
    if ok and keep:
        STORE.mkdir(parents=True, exist_ok=True)
        f.write_text(str(cost))
    r = {"type": "result", "subtype": "success" if ok else "error_during_execution", "is_error": not ok,
         "duration_ms": int((time.time() - t0) * 1000) if t0 else 0, "duration_api_ms": 900, "num_turns": 2,
         "result": text, "stop_reason": "end_turn", "session_id": sid, "total_cost_usd": cost,
         "usage": usage(10, 40, 2400, 600),
         "modelUsage": {model: {"inputTokens": 10, "outputTokens": 40, "cacheReadInputTokens": 2400,
                                "cacheCreationInputTokens": 600, "costUSD": cost,
                                "contextWindow": 1000000}} if ok else {},
         "permission_denials": [], "uuid": str(uuid.uuid4())}
    if errors:
        r["errors"] = errors
    return r


def record(o: dict, prompt: str, images: int = 0, continued: bool = False) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    with open(STORE / "calls.jsonl", "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt, "images": images, "cwd": os.getcwd(),
                            "env": {k: os.environ.get(k) for k in ("IS_SANDBOX", "CLAUDE_CODE_OAUTH_TOKEN",
                                                                   "ANTHROPIC_API_KEY", "MX_TEST_VAR",
                                                                   "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
                                                                   "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
                                                                   "MAXXING_SESSION")},
                            "at": time.time(), **({"continued": True} if continued else {})}) + "\n")


def reply_for(prompt: str) -> str:
    me = os.path.basename(os.getcwd())                   # REPLY_AS <agent folder>: <text> - agent group tests
    said = [ln.split("REPLY_AS " + me + ":", 1)[1].strip() for ln in prompt.splitlines() if "REPLY_AS " + me + ":" in ln]
    if said:
        return said[-1].replace("AT:", "@")
    if "Summarize this conversation" in prompt:
        return "Summary: the user tested the fake Claude; nothing left to do."
    first = prompt.strip().splitlines()[0] if prompt.strip() else ""
    out = f"Echo: {first[:200]}"
    if "Attached files:" in prompt:
        n = sum(1 for ln in prompt.splitlines() if ln.startswith("- /"))
        out += f" ({n} attachment{'s' if n != 1 else ''} received)"
    return out


def _approve(sid: str, model: str) -> None:
    """APPROVE: asks the --permission-prompt-tool (a stdio MCP server of a --mcp-config file) before a Bash call,
    like Claude Code in permission mode `default`; the decoded answer goes to $FAKE_CLAUDE_DIR/approve.json."""
    import subprocess as _sp
    argv = sys.argv[1:]
    tool = argv[argv.index("--permission-prompt-tool") + 1] if "--permission-prompt-tool" in argv else ""
    answer: dict = {"behavior": "none"}
    parts = tool.split("__")
    spec = None
    for i, a in enumerate(argv[:-1]):
        if a == "--mcp-config" and len(parts) == 3:
            f = Path(argv[i + 1])
            cfg = json.loads(f.read_text()) if f.is_file() else {}
            spec = (cfg.get("mcpServers") or {}).get(parts[1]) or spec
    if spec:
        p = _sp.Popen([spec["command"], *spec.get("args", [])], stdin=_sp.PIPE, stdout=_sp.PIPE, text=True,
                      env={**os.environ, **(spec.get("env") or {})})
        for m in ({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                  {"jsonrpc": "2.0", "method": "notifications/initialized"},
                  {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": parts[2], "arguments": {
                      "tool_name": "Bash", "input": {"command": "git push", "description": "Push"},
                      "tool_use_id": "toolu_fake"}}}):
            p.stdin.write(json.dumps(m) + "\n")
            p.stdin.flush()
        for line in p.stdout:
            r = json.loads(line)
            if r.get("id") == 2:
                answer = json.loads(r["result"]["content"][0]["text"])
                break
        p.stdin.close()
        p.wait(timeout=10)
    (STORE / "approve.json").write_text(json.dumps(answer))
    emit(msg(sid, model, [{"type": "text", "text": f"approval: {answer.get('behavior')}"}]))


def _mcp_cfg() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home()) / ".claude.json"


def mcp(args: list[str]) -> int:
    f = _mcp_cfg()
    d = json.loads(f.read_text()) if f.is_file() else {}
    here = os.getcwd()
    authed = STORE / "mcp-authed.json"
    ok = set(json.loads(authed.read_text())) if authed.is_file() else set()
    act = args[0] if args else ""
    if act == "list":
        found = {**(d.get("mcpServers") or {}), **((d.get("projects") or {}).get(here, {}).get("mcpServers") or {})}
        print("Checking MCP server health...\n")
        for name, cfg in found.items():
            what = cfg.get("url") or " ".join([cfg.get("command", "")] + cfg.get("args", []))
            kind = {"http": " (HTTP)", "sse": " (SSE)"}.get(cfg.get("type"), "")
            if cfg.get("type") in ("http", "sse") and not cfg.get("headers") and name not in ok:
                mark = "! Needs authentication"
            elif "fail" in what:
                mark = "✗ Failed to connect"
            else:
                mark = "✓ Connected"
            print(f"{name}: {what}{kind} - {mark}")
        if not found:
            print("No MCP servers configured. Use `claude mcp add` to add a server.")
        return 0
    if act in ("add-json", "remove"):
        scope = args[args.index("-s") + 1] if "-s" in args else "local"
        rest = [a for i, a in enumerate(args[1:], 1) if a not in ("-s", "--") and args[i - 1] != "-s"]
        box = d.setdefault("mcpServers", {}) if scope == "user" else \
            d.setdefault("projects", {}).setdefault(here, {}).setdefault("mcpServers", {})
        if act == "add-json":
            box[rest[0]] = json.loads(rest[1])
            msg = f"Added {rest[0]} to {scope} config"
        elif box.pop(rest[0], None) is None:
            print(f"No MCP server found with name: {rest[0]}", file=sys.stderr)
            return 1
        else:
            msg = f"Removed MCP server {rest[0]} from {scope} config"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, indent=2))
        print(msg)
        return 0
    if act == "login":
        name = args[-1]
        url = f"https://auth.example.com/oauth/authorize?client_id=x&redirect_uri=http%3A%2F%2Flocalhost%3A4321%2Fcallback&name={name}"
        sys.stdout.write(f"Open this link: \x1b]8;;{url}\x07{url[:30]}\x1b]8;;\x07\nOr paste the redirect URL here: ")
        sys.stdout.flush()
        line = sys.stdin.readline()
        time.sleep(float(os.environ.get("FAKE_CLAUDE_LOGIN_DELAY") or 0))
        if "code=" not in line:
            print("\nAuthentication failed: no code", file=sys.stderr)
            return 1
        STORE.mkdir(parents=True, exist_ok=True)
        authed.write_text(json.dumps(sorted(ok | {name})))
        print(f"\nAuthentication successful. Connected to {name}.")
        return 0
    print(f"unknown mcp command {act}", file=sys.stderr)
    return 1


def main() -> int:
    if sys.argv[1:2] == ["mcp"]:
        return mcp(sys.argv[2:])
    o = parse(sys.argv[1:])
    if o["version"]:
        print(VERSION)
        return 0
    images = 0
    if o["input"] == "stream-json" and o["prompt"] is None:   # user messages, one per line; stdin stays open
        got = None
        while got is None:
            line = sys.stdin.readline()
            if not line:
                return 1
            got = _user_text(line)
        prompt, images = got
        threading.Thread(target=_stdin_reader, daemon=True).start()
    else:
        prompt = o["prompt"] if o["prompt"] is not None else (sys.stdin.read() if not sys.stdin.isatty() else "")
        EVENTS.put(("eof",))
    record(o, prompt, images)
    model = o["model"] or DEFAULT_MODEL
    STORE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    if o["resume"]:
        sid = o["resume"]
        if "RESUME_FAIL" in prompt or not (STORE / sid).exists():
            err = f"No conversation found with session ID: {sid}"
            sys.stderr.write(err + "\n")
            if o["format"] == "stream-json":
                emit(result(sid, model, "", ok=False, errors=[err]))
            return 1
    else:
        sid = o["session_id"] or str(uuid.uuid4())
        if o["session_id"] and (STORE / sid).exists():
            sys.stderr.write(f"Error: Session ID {sid} is already in use.\n")
            return 1
        (STORE / sid).write_text(prompt)

    rc = turn(o, sid, model, prompt, t0)
    if rc is not None or o["format"] != "stream-json":
        return rc or 0
    eof = False
    while True:                                          # more messages (stream-json input), tasks ending
        if eof and not BG and EVENTS.empty():
            return 0
        ev = EVENTS.get()
        if ev[0] == "eof":
            eof = True
        elif ev[0] == "user":
            record(o, ev[1], ev[2], continued=True)
            rc = turn(o, sid, model, ev[1], time.time())
        else:
            with BG_LOCK:
                pass
            rc = turn(o, sid, model, f"Background task {ev[1]} finished. NOTOOL", time.time())
        if rc is not None:
            return rc


def turn(o: dict, sid: str, model: str, prompt: str, t0: float) -> int | None:
    """One turn; an exit code when the process ends with it, None when it can take more."""
    INTERRUPT.clear()
    text = reply_for(prompt)
    if "AUTH_EXPIRED" in prompt or os.environ.get("FAKE_CLAUDE_AUTH_EXPIRED") == "1":
        err = "OAuth session expired and could not be refreshed. Please run /login."
        if o["format"] == "stream-json":
            emit({"type": "system", "subtype": "init", "cwd": os.getcwd(), "session_id": sid, "tools": [],
                  "model": model, "apiKeySource": "none", "uuid": str(uuid.uuid4())})
            emit(msg(sid, "<synthetic>", [{"type": "text", "text": err}]))
            emit(result(sid, model, err, ok=False))
        else:
            print(json.dumps(result(sid, model, err, ok=False)) if o["format"] == "json" else err)
        return 1
    if o["format"] == "json":
        if "FAIL" in prompt:
            print(json.dumps(result(sid, model, "Simulated failure", ok=False)))
            return 1
        if "name chat sessions" in (o.get("system_prompt") or ""):
            print(json.dumps(result(sid, model, os.environ.get("FAKE_CLAUDE_TITLE", "Fake short title"), t0=t0,
                                    keep=False)))
            return 0
        # a side question (fork, nothing saved) answers like a turn would
        print(json.dumps(result(sid, model, text if "--fork-session" in sys.argv else "ok", t0=t0,
                                keep="--fork-session" not in sys.argv)))
        return 0
    if o["format"] != "stream-json":
        print(text)
        return 0

    emit({"type": "system", "subtype": "init", "cwd": os.getcwd(), "session_id": sid,
          "tools": ["Task", "Bash", "Read", "Edit", "Write", "Grep", "Glob"],
          "mcp_servers": [{"name": "Facebook-ads", "status": "connected", "source": "user"},
                          {"name": "claude.ai Google Drive", "status": "connected", "source": "claudeai"}]
          if "MCPINIT" in prompt else [],
          "model": model, "permissionMode": "bypassPermissions" if o["skip"] else (o["permission_mode"] or "default"),
          "apiKeySource": "none", "claude_code_version": VERSION.split()[0], "uuid": str(uuid.uuid4())})
    if "NORESULT" in prompt:                           # crashes mid-turn: no result line
        return 0
    if "HALFTURN" in prompt:                           # killed mid-turn after some work: tokens spent, no result
        emit(msg(sid, model, [{"type": "text", "text": "Working..."}]))
        return 0
    emit({"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 40, "session_id": sid})
    emit(msg(sid, model, [{"type": "thinking", "thinking": "", "signature": "c2lnbmF0dXJl"}]))
    if "FAIL" in prompt and "RESUME_FAIL" not in prompt:
        sys.stderr.write("API Error: simulated failure\n")
        emit(result(sid, model, "API Error: simulated failure", ok=False, errors=["simulated failure"], t0=t0))
        return 1
    if "OVERBUDGET" in prompt:                         # `--max-budget-usd` reached: Claude Code stops the turn
        r = result(sid, model, "", ok=False, errors=["Reached maximum budget ($0.01)"], t0=t0)
        r["subtype"] = "error_max_budget_usd"
        emit(r)
        return 1
    for name in __import__("re").findall(r"BGTASK:([A-Za-z0-9_-]+)", prompt):
        _bg_task(sid, model, name)
    if "SLOW" in prompt:
        emit(msg(sid, model, [{"type": "text", "text": "Starting a long task."}]))
        for i in range(300):
            if INTERRUPT.wait(0.1):
                _interrupted(sid, model, t0)
                return None
            if i % 50 == 0:
                emit({"type": "tool_progress", "tool_use_id": "toolu_slow", "tool_name": "Bash",
                      "elapsed_time_seconds": i // 10, "session_id": sid})
    if "AGENTS" in prompt:                               # two background sub-agents and a background command
        _agents(sid, model, float(os.environ.get("FAKE_CLAUDE_AGENTS_S", "1.5")))
    if "PAUSE" in prompt and INTERRUPT.wait(1.5):
        _interrupted(sid, model, t0)
        return None
    if "ORPHAN" in prompt:                               # a background program that keeps our stdout open
        import subprocess as _sp
        _sp.Popen(["sleep", "30"], stdout=sys.stdout, start_new_session=True)
    if "CHATTY" in prompt:                               # ... and one that keeps writing to it (a dev server's logs)
        import subprocess as _sp
        _sp.Popen(["sh", "-c", "for i in $(seq 300); do echo log $i; sleep 0.1; done"], stdout=sys.stdout,
                  start_new_session=True)
    if "HUGE" in prompt:
        wid, rid, iid = ("toolu_" + uuid.uuid4().hex[:20] for _ in range(3))
        emit(msg(sid, model, [{"type": "tool_use", "id": wid, "name": "Write",
                               "input": {"file_path": os.getcwd() + "/big.txt", "content": "w" * 100_000}}]))
        emit({"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": wid, "type": "tool_result", "content": "File written"}]},
            "parent_tool_use_id": None, "session_id": sid, "uuid": str(uuid.uuid4())})
        emit(msg(sid, model, [{"type": "tool_use", "id": rid, "name": "Read",
                               "input": {"file_path": os.getcwd() + "/huge.log"}}]))
        emit({"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": rid, "type": "tool_result", "content": "x" * 3_000_000}]},
            "parent_tool_use_id": None, "session_id": sid, "uuid": str(uuid.uuid4()),
            "tool_use_result": {"stdout": "x" * 3_000_000, "stderr": ""}})
        emit(msg(sid, model, [{"type": "tool_use", "id": iid, "name": "Read",
                               "input": {"file_path": os.getcwd() + "/shot.png"}}]))
        emit({"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": iid, "type": "tool_result", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "A" * 500_000}}]}]},
            "parent_tool_use_id": None, "session_id": sid, "uuid": str(uuid.uuid4())})
    if "APPROVE" in prompt:
        _approve(sid, model)
    if "WAITMSG" in prompt and o["input"] == "stream-json":
        MIDTURN.set()
        emit(msg(sid, model, [{"type": "text", "text": "Waiting for a message."}]))
        try:
            mid = MID.get(timeout=float(os.environ.get("FAKE_CLAUDE_WAITMSG_S", "10")))
            record(o, mid[0], mid[1], continued=True)
            emit(msg(sid, model, [{"type": "text", "text": "Read mid-turn: " + mid[0]}]))
        except queue.Empty:
            pass
        MIDTURN.clear()
    if "ASKNET" in prompt:
        rid = "req-" + uuid.uuid4().hex[:8]
        emit({"type": "control_request", "request_id": rid, "request": {
            "subtype": "can_use_tool", "tool_name": "SandboxNetworkAccess", "input": {"host": "example.org"},
            "tool_use_id": "toolu_net", "description": "Allow network connection to example.org?"}})
        try:
            got = CONTROL.get(timeout=float(os.environ.get("FAKE_CLAUDE_ASK_S", "20")))
            r = got["response"]
            answer = r["response"]["behavior"] if r.get("request_id") == rid else "wrong id"
        except queue.Empty:
            answer = "no answer"
        with open(STORE / "asknet.txt", "a") as f:
            f.write(answer + "\n")
    import re as _re
    for srv in _re.findall(r"MCPUSE:([A-Za-z0-9_-]+)", prompt):
        uid = "toolu_" + uuid.uuid4().hex[:20]
        emit(msg(sid, model, [{"type": "tool_use", "id": uid, "name": f"mcp__{srv}__ping", "input": {}}]))
        emit({"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": uid, "type": "tool_result", "content": "pong"}]}, "parent_tool_use_id": None,
            "session_id": sid, "uuid": str(uuid.uuid4())})
    for srv in ([os.environ.get("FAKE_CLAUDE_MCPLOAD", "")] if "MCPLOAD" in prompt else []):
        import subprocess as _sp
        r = _sp.run([sys.executable, "-m", "maxxing", "mcp", "load", srv], capture_output=True, text=True,
                    timeout=60)
        with open(STORE / "mcp-load.txt", "a") as f:
            f.write(f"{r.returncode} {r.stdout.strip()} {r.stderr.strip()}\n")
    if "NOTOOL" not in prompt:
        tid = "toolu_" + uuid.uuid4().hex[:20]
        emit(msg(sid, model, [{"type": "text", "text": "Let me look at the folder."}]))
        emit(msg(sid, model, [{"type": "tool_use", "id": tid, "name": "Bash",
                               "input": {"command": "ls -la", "description": "List files"}}]))
        emit({"type": "user", "message": {"role": "user", "content": [
            {"tool_use_id": tid, "type": "tool_result", "content": "total 8\nCLAUDE.md\nmemory.md",
             "is_error": False}]}, "parent_tool_use_id": None, "session_id": sid,
            "uuid": str(uuid.uuid4()), "tool_use_result": {"stdout": "total 8", "stderr": ""}})
    last = msg(sid, model, [{"type": "text", "text": text}])
    if "BIGCTX" in prompt:
        last["message"]["usage"] = usage(3, 12, 150_000, 300)
    emit(last)
    emit({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "rateLimitType": "five_hour"},
          "session_id": sid})
    emit(result(sid, model, text, t0=t0))
    return None


if __name__ == "__main__":
    sys.exit(main())
