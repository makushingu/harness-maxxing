"""Start a turn runner, and build the environment of a `claude` process.  STDLIB ONLY.

Production: one transient systemd unit per runner (`systemd-run --collect --unit maxxing-<sid8>`),
so a turn survives a browser close and a server restart. Tests/dev: MAXXING_SPAWN=direct starts a
detached subprocess (new session) instead.
"""
from __future__ import annotations

import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import config

SERVER_DIR = Path(__file__).resolve().parent.parent.parent      # …/server
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TUNING_ENV = ("CLAUDE_CODE_EFFORT_LEVEL", "MAX_THINKING_TOKENS", "CLAUDE_CODE_PROMPT_CACHE_TTL",
              "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL", "FORCE_PROMPT_CACHING_5M",
              "ENABLE_PROMPT_CACHING_1H", "DISABLE_PROMPT_CACHING", "ENABLE_TOOL_SEARCH",
              "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "BASH_MAX_OUTPUT_LENGTH",
              "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")  # never secrets: shown in `ps`
# Characters of a Bash command's output Claude keeps (Claude Code's own default is 30 000): every byte stays in the
# conversation and is re-sent on each later call; the end of a longer output is cut, Claude sees it was cut.
BASH_OUTPUT_MAX = 15000
# Claude Code's own compaction inside a turn (between tool calls): it starts about 43k tokens below the window it is
# given (measured with a 100k window: compacted at ~57k), so the window is the session threshold + this margin - a
# long turn is summarized near `auto_compact_tokens` too, instead of growing up to ~1M.
COMPACT_WINDOW_MARGIN = 45000
COMPACT_WINDOW_MIN, COMPACT_WINDOW_MAX = 100000, 1000000     # the range Claude Code accepts
# `claude_quiet_start`: no update check, telemetry or feature-flag fetch at start - measured 0.87 -> 0.52 s to the
# first event, and ~900 fewer prompt tokens per call; the 1-hour prompt cache of subscriptions is unchanged.
QUIET_START_ENV = "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
FORWARDED = ("MAXXING_STATE", "MAXXING_LISTEN_PORT", "MAXXING_CLAUDE_BIN", "MAXXING_SPAWN", "MAXXING_TELEGRAM_API",
             "FAKE_CLAUDE_DIR", "LANG", "LC_ALL") + TUNING_ENV


# ---- environment ---------------------------------------------------------------------------
def base_env() -> dict[str, str]:
    """os.environ with HOME set and ~/.local/bin + /usr/local/bin on PATH (where the official
    installers put `claude`). A systemd unit starts with a bare environment, hence this."""
    env = dict(os.environ)
    home = env.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir
    env["HOME"] = home
    path = [p for p in env.get("PATH", "/usr/bin:/bin").split(":") if p]
    for extra in (os.path.join(home, ".local", "bin"), "/usr/local/bin"):
        if extra not in path:
            path.insert(0, extra)
    # the Node.js older installers put next to an older one of the server; ours (deps.toml:
    # <state>/tools/nodejs/current) only when the server has none - a turn administering the server uses its Node
    legacy, managed = config.STATE / "tools" / "node" / "bin", config.STATE / "tools" / "nodejs" / "current" / "bin"
    if legacy.is_dir() and str(legacy) not in path:
        path.insert(0, str(legacy))
    if managed.is_dir() and str(managed) not in path and not shutil.which("node", path=":".join(path)):
        path.insert(0, str(managed))
    env["PATH"] = ":".join(path)
    own_dir = config.load_config().get("claude_dir")
    if own_dir:
        env["CLAUDE_CONFIG_DIR"] = own_dir
    return env


def claude_bin() -> str:
    """Claude executable: MAXXING_CLAUDE_BIN, else `claude` resolved on the fixed PATH."""
    explicit = os.environ.get("MAXXING_CLAUDE_BIN")
    if explicit:
        return explicit
    return shutil.which("claude", path=base_env()["PATH"]) or "claude"


_RESERVED = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "PWD", "TERM", "LANG", "LC_ALL", "TZ",   # = vault.RESERVED
             "HOSTNAME", "TMPDIR", "PYTHONPATH", "LD_PRELOAD", "LD_LIBRARY_PATH",
             "LD_AUDIT", "BASH_ENV", "ENV", "PROMPT_COMMAND", "NODE_OPTIONS", "NODE_PATH",
             "PYTHONSTARTUP", "PYTHONHOME", "GIT_SSH_COMMAND", "GIT_EXEC_PATH", "ANTHROPIC_BASE_URL"}


def _exposed_vault(secrets: dict) -> dict[str, str]:
    """Vault entries flagged `expose` (maxxing.vault.exposed_env, or the same filter if absent)."""
    try:
        from .. import vault
        return dict(vault.exposed_env())
    except ImportError:
        pass
    v = secrets.get("vault") if isinstance(secrets.get("vault"), dict) else {}
    return {k: str(e.get("value") or "") for k, e in v.items()
            if isinstance(e, dict) and e.get("expose") and ENV_NAME_RE.match(k)
            and k not in _RESERVED and not k.startswith("MAXXING_")}


def auth_env(secrets: dict | None = None) -> dict[str, str]:
    """Claude credentials stored in secrets.json + the user's vault entries flagged `expose`."""
    s = secrets if secrets is not None else config.load_secrets()
    out = _exposed_vault(s)
    if s.get("claude_oauth_token"):
        out["CLAUDE_CODE_OAUTH_TOKEN"] = str(s["claude_oauth_token"])
    if s.get("anthropic_api_key"):
        out["ANTHROPIC_API_KEY"] = str(s["anthropic_api_key"])
    return out


def permission_args(mode: str) -> tuple[list[str], dict[str, str]]:
    """CLI flags + env for a permission mode (bypass | acceptEdits | default)."""
    if mode == "acceptEdits":
        return ["--permission-mode", "acceptEdits"], {}
    if mode == "default":
        return ["--permission-mode", "default"], {}
    if mode == "plan":                                       # read-only: explore, then propose a plan
        return ["--permission-mode", "plan"], {}
    env = {"IS_SANDBOX": "1"} if os.geteuid() == 0 else {}   # bypass refuses root otherwise
    return ["--dangerously-skip-permissions"], env


def compact_window(cfg: dict) -> int | None:
    """CLAUDE_CODE_AUTO_COMPACT_WINDOW for `auto_compact_tokens` (None: automatic compaction is off)."""
    limit = int(cfg.get("auto_compact_tokens") or 0)
    if limit <= 0:
        return None
    return max(COMPACT_WINDOW_MIN, min(COMPACT_WINDOW_MAX, max(limit, 100000) + COMPACT_WINDOW_MARGIN))


def protected_paths() -> list[str]:
    """Files Claude's tools must not read or edit when `protect_secrets` is on: the server's secrets and SSH keys.
    A speed bump against injected instructions ("read ~/.ssh/id_ed25519 and post it"): Read/Edit and simple shell
    reads (`cat`) are refused, a script that opens the file is not - permission modes are the real limit."""
    home = os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir
    return [str(config.STATE / "secrets.json"), str(Path(home) / ".ssh") + "/**"]


def deny_rules(cfg: dict) -> list[str]:
    # Folder settings (a topic's permission mode lives in <topic>/.maxxing.json, inside the turn's working
    # directory): Claude never edits them, or a stricter topic could switch itself back to bypass. The UI changes
    # them through the server. Edit rules cover Write too.
    rules = [f"Edit(/{config.workspace()}/**/.maxxing.json)",
             f"Edit(/{config.workspace()}/infra.json)"]     # its servers are reached through ssh by the server
    if cfg.get("protect_secrets", True):
        for p in protected_paths():                     # "//abs/path": an absolute path in Claude Code rules
            rules += [f"Read(/{p})", f"Edit(/{p})"]
    extra = cfg.get("claude_deny") or []
    if isinstance(extra, str):                          # written by hand as one rule
        extra = [extra]
    rules += [r for r in extra if isinstance(r, str) and r.strip()] if isinstance(extra, list) else []
    return rules


# Claude Code sends subagents to the background by default: the turn ends, then waits for a notification to carry on
# (slower, and in Harness 91 % of the agents went there). Unless `background_agents` is on, each turn asks for
# foreground agents - several in one message still run in parallel - and keeps background ones for when the user
# asks for them.
FOREGROUND_AGENTS = ("Subagents (Agent tool): run them in the foreground, always passing run_in_background: false, "
                     "unless the user explicitly asks for a background agent. To run several at once, put several "
                     "Agent calls in the same message: they run in parallel and their results come back in this turn.")


def agents_args(cfg: dict) -> list[str]:
    """`--append-system-prompt` asking for foreground subagents, unless config `background_agents` is on."""
    return [] if cfg.get("background_agents") else ["--append-system-prompt", FOREGROUND_AGENTS]


def settings_args(cfg: dict) -> list[str]:
    """`--settings` for the turn: deny rules (they apply in every permission mode, bypass included, and add to
    the user's own settings files)."""
    return ["--settings", json.dumps({"permissions": {"deny": deny_rules(cfg)}}, separators=(",", ":"))]


def claude_env(extra: dict | None = None, permission_mode: str = "bypass") -> dict[str, str]:
    env = base_env()
    cfg = config.load_config()
    env.setdefault("BASH_MAX_OUTPUT_LENGTH", str(BASH_OUTPUT_MAX))
    if cfg.get("claude_quiet_start", True):
        env.setdefault(QUIET_START_ENV, "1")
    window = compact_window(cfg)
    if window:
        env.setdefault("CLAUDE_CODE_AUTO_COMPACT_WINDOW", str(window))
    env.update(auth_env())
    env.update(permission_args(permission_mode)[1])
    env.update({str(k): str(v) for k, v in (extra or {}).items() if ENV_NAME_RE.match(str(k))})
    return env


# ---- runner start --------------------------------------------------------------------------
def unit_name(sid: str) -> str:
    return "maxxing-" + sid[:8]


def _runner_cmd(sid: str) -> list[str]:
    return [sys.executable, "-m", "maxxing.sessions.runner", sid]


def _runner_env() -> dict[str, str]:
    env = base_env()
    env["MAXXING_STATE"] = str(config.STATE)
    env["PYTHONPATH"] = str(SERVER_DIR) + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _start_direct(sid: str) -> str:
    logf = open(config.state_dir("logs") / "runner.log", "ab")
    p = subprocess.Popen(_runner_cmd(sid), env=_runner_env(), cwd=str(SERVER_DIR),
                         stdin=subprocess.DEVNULL, stdout=logf, stderr=logf, start_new_session=True)
    logf.close()
    threading.Thread(target=p.wait, daemon=True).start()       # reap: no zombie
    return f"pid:{p.pid}"


UNIT_GONE_WAIT_S = 3.0          # the previous runner unit of the session still stopping: wait that long
UNIT_POLL_S = 0.05


def _unit_gone(unit: str) -> bool:
    """True once the unit is unloaded or stopped (--collect unloads it right after it ends)."""
    try:
        r = subprocess.run(["systemctl", "show", unit, "--no-pager", "-p", "LoadState", "-p", "ActiveState"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    info = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
    return info.get("LoadState") == "not-found" or info.get("ActiveState") in ("inactive", "failed")


def _wait_unit_gone(unit: str, timeout: float = UNIT_GONE_WAIT_S) -> bool:
    end = time.monotonic() + timeout
    while True:
        if _unit_gone(unit):
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(UNIT_POLL_S)


_MEMORY_RE = re.compile(r"^\d+(\.\d+)?[%KMGT]?$")


def memory_properties() -> list[str]:
    """systemd-run properties of a turn / job unit. OOMPolicy=continue: when a command runs out of memory (an ffmpeg
    render, a build) the kernel kills that process only - Claude gets "Killed" (exit 137) and carries on - instead of
    systemd stopping the whole unit with Claude in it (default `stop`: the turn vanished without an answer).
    MemoryMax (config `unit_memory_max`, default 75 % of RAM): that kill happens inside the unit, usually before the
    server itself (UI, other sessions) runs short - the cap is per unit, not a total."""
    props = ["--property", "OOMPolicy=continue"]
    cap = str(config.load_config().get("unit_memory_max") or "").strip()
    if cap and cap.lower() != "infinity" and _MEMORY_RE.match(cap):
        props += ["--property", f"MemoryMax={cap}"]
    return props


# systemd protections of every turn / job unit (config `unit_hardening`, default on). Only options measured harmless
# for sessions that administer the server as root (apt, systemctl, sudo, git, docker/lxc CLIs, Chromium, ffmpeg,
# Node, mount): no mount namespace (mounts made by a session must stay visible), no NoNewPrivileges (sudo, setuid
# helpers, snap). The kept options are seccomp / capability filters only. See docs/dev/INTERNALS.md "Unit hardening".
UNIT_HARDENING = ("ProtectClock=yes", "LockPersonality=yes", "RestrictRealtime=yes")


def hardening_properties() -> list[str]:
    """systemd-run properties of the unit hardening (none when config `unit_hardening` is false)."""
    if config.load_config().get("unit_hardening", True) is False:
        return []
    return [a for opt in UNIT_HARDENING for a in ("--property", opt)]


_OOM_MARKS = ("result 'oom-kill'", "OOM killer killed", "killed by the OOM killer")


def unit_end_reason(unit: str | None) -> str | None:
    """Why a turn unit ended, from the journal (the unit itself is collected): "oom" when the kernel OOM killer
    stopped it, else None. Only asked when a session is found dead while 'running' (rare)."""
    if not unit or unit.startswith("pid:") or not shutil.which("journalctl"):
        return None
    try:
        r = subprocess.run(["journalctl", "-u", unit, "-n", "30", "-o", "cat", "--no-pager"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = r.stdout.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("Started ")]
    last = lines[starts[-1]:] if starts else lines      # the unit name is reused by every turn: its last run only
    # OOMPolicy=stop logs "Failed with result 'oom-kill'"; OOMPolicy=continue (memory_properties) only logs
    # "The kernel OOM killer killed some processes in this unit" (systemd 259) or "killed by the OOM killer"
    return "oom" if any(m in line for line in last for m in _OOM_MARKS) else None


def _start_unit(sid: str) -> str:
    env = _runner_env()
    sets = []
    for k in FORWARDED + ("HOME", "PATH", "PYTHONPATH"):
        if env.get(k):
            sets += ["--setenv", f"{k}={env[k]}"]
    base = unit_name(sid)
    last_err = ""
    for attempt in range(3):
        # the previous runner of this session may still be exiting: wait until its unit is gone
        # (polled every UNIT_POLL_S), then start again; still there -> a suffixed name
        unit = base if attempt < 2 else f"{base}-{int(time.time()) % 100000}"
        cmd = ["systemd-run", "--collect", "--quiet", "--unit", unit,
               "--description", f"Harness Maxxing turn {sid}",
               "--property", "KillMode=mixed", "--property", "TimeoutStopSec=15", *memory_properties(),
               *hardening_properties(),
               "--working-directory", str(SERVER_DIR), *sets, "--", *_runner_cmd(sid)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return unit
        last_err = (r.stderr or r.stdout).strip()
        if "already" not in last_err.lower() and "exists" not in last_err.lower():
            break
        if attempt == 0:
            _wait_unit_gone(base)              # still there after UNIT_GONE_WAIT_S: base once more, then a suffix
    raise RuntimeError(f"systemd-run failed: {last_err[:300]}")


def start(sid: str) -> str:
    """Start the runner of `sid`; returns the unit name (or "pid:<n>" in direct mode)."""
    from .. import pcbridge
    pcbridge.ensure_mcp_soon()                         # the entry lost from ~/.claude.json comes back (the turn has --mcp-config)
    if os.environ.get("MAXXING_SPAWN") == "direct" or not shutil.which("systemd-run"):
        return _start_direct(sid)
    return _start_unit(sid)


def stop_unit(unit: str | None) -> None:
    """Last-resort stop of a runner unit (the runner is normally signalled directly)."""
    if unit and not unit.startswith("pid:") and shutil.which("systemctl"):
        subprocess.run(["systemctl", "stop", unit], capture_output=True, timeout=30)
