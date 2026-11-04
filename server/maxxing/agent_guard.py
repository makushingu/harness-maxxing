"""Walls around an agent's turns, built on what Claude Code provides.

    sandbox    Claude Code's sandbox (`settings.sandbox`, bubblewrap + socat on Linux): shell commands can only write
               in the agent folder (+ `writable` folders of the topic), cannot read the server's secrets, and reach
               only the `domains` of the agent. Read/Edit/Write are not shell commands: the same secrets get
               `permissions.deny` rules (they hold in every mode). Claude Code ignores the domain list in bypass
               mode, so a sandboxed turn never runs in bypass (bypass -> acceptEdits).
    maxxing    the `maxxing` CLI cannot work inside the sandbox (the server state is hidden): it is an excluded
               command, run outside, and in a sandboxed agent turn it only accepts a short list of sub-commands
               (`check_cli`), found from the turn's cgroup (systemd unit maxxing-<sid8>), not from an environment
               variable the turn could change.
    rules      fixed rules of the agent ({tool, match, reason}): a PreToolUse hook (`python -m maxxing.agent_guard
               hook <agent path>`) refuses a matching tool call and tells Claude why.

Ubuntu 24.04+ restricts user namespaces (kernel.apparmor_restrict_unprivileged_userns=1): bubblewrap needs an
AppArmor profile allowing them (`APPARMOR_PROFILE`), or every sandboxed command fails. `available()` checks it all;
`maxxing agents sandbox-setup` installs what is missing. Imports stay light (the session runner reads this).
"""
from __future__ import annotations

import json
import os
import pwd
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

from . import config

APPARMOR_FILE = Path("/etc/apparmor.d/bwrap-maxxing")
APPARMOR_PROFILE = """# Harness Maxxing: lets bubblewrap (Claude Code sandbox of agents) create user namespaces on Ubuntu 24.04+
abi <abi/4.0>,
include <tunables/global>
profile bwrap-maxxing /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap-maxxing>
}
"""
USERNS_SYSCTL = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
APPARMOR_PROFILES = Path("/sys/kernel/security/apparmor/profiles")

# `maxxing` sub-commands a sandboxed agent turn may run (anything else is refused): its own work, nothing that
# changes the server (a cron or an MCP server would run outside the sandbox).
CLI_ALLOWED = {
    "feed": {"post", "list"},
    "agents": {"send", "show", "list", "templates"},
    "keys": {"get", "list"},          # filtered by the agent's `keys` (cmd_keys)
    "status": None,                   # None = any
}


# ---- availability ----------------------------------------------------------------------------------
_avail: tuple[float, dict] | None = None


def available(fresh: bool = False) -> dict:
    """{ok, missing: [...]} - what the sandbox needs on this server (cached 60 s)."""
    global _avail
    if _avail and not fresh and time.time() - _avail[0] < 60:
        return _avail[1]
    if os.environ.get("MAXXING_SANDBOX_CHECK") == "0":   # tests
        return {"ok": True, "missing": []}
    missing = [b for b in ("bwrap", "socat") if not shutil.which(b)]
    if sys.platform != "linux":
        missing.append("linux")
    elif _userns_restricted() and not _bwrap_profile_loaded():
        missing.append("apparmor")
    out = {"ok": not missing, "missing": missing}
    _avail = (time.time(), out)
    return out


def _userns_restricted() -> bool:
    try:
        return USERNS_SYSCTL.read_text().strip() == "1"
    except OSError:
        return False


def _bwrap_profile_loaded() -> bool:
    try:
        return any("bwrap" in ln for ln in APPARMOR_PROFILES.read_text().splitlines())
    except OSError:
        return APPARMOR_FILE.is_file()             # profiles list unreadable (not root): trust the file


def setup() -> list[str]:
    """Install what the sandbox needs (root): bubblewrap + socat (apt), the AppArmor profile. Returns what was done."""
    import subprocess
    done: list[str] = []
    pkgs = [p for p, b in (("bubblewrap", "bwrap"), ("socat", "socat")) if not shutil.which(b)]
    if pkgs:
        if not shutil.which("apt-get"):
            raise RuntimeError(f"install {' and '.join(pkgs)} with the package manager of this system")
        env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
        subprocess.run(["apt-get", "install", "-y", "-q", *pkgs], check=True, env=env, stdout=subprocess.DEVNULL)
        done.append("installed " + ", ".join(pkgs))
    if _userns_restricted() and not _bwrap_profile_loaded():
        APPARMOR_FILE.write_text(APPARMOR_PROFILE)
        subprocess.run(["apparmor_parser", "-r", str(APPARMOR_FILE)], check=True)
        done.append(f"AppArmor profile {APPARMOR_FILE}")
    available(fresh=True)
    return done


# ---- settings of a sandboxed turn ------------------------------------------------------------------
def secret_paths() -> list[str]:
    """What a sandboxed agent never reads: the server state (vault, config), SSH keys, Claude and other CLI logins."""
    home = Path(os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir)
    paths = [config.STATE, home / ".ssh", home / ".claude" / ".credentials.json", home / ".claude.json",
             config.claude_dir() / ".credentials.json", home / ".git-credentials", home / ".netrc",
             home / ".config" / "gh", home / ".aws", home / ".docker" / "config.json", home / ".config" / "rclone"]
    out: list[str] = []
    for p in paths:
        s = str(p)
        if s not in out:
            out.append(s)
    return out


def mode(requested: str) -> str:
    """Permission mode of a sandboxed turn: never bypass (Claude Code lets every domain through in bypass)."""
    return requested if requested in ("default", "acceptEdits", "plan") else "acceptEdits"


def settings(path: str, a: dict) -> dict:
    """The `--settings` part of an agent turn: sandbox (when on) and the hook of its rules."""
    out: dict = {}
    folder = config.workspace() / path
    if a.get("sandbox"):
        topic = folder.parent.parent
        write = [str(folder)] + [str((topic / w).resolve()) for w in a.get("writable") or []]
        secrets = secret_paths()
        out["sandbox"] = {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
                          "autoAllowBashIfSandboxed": True, "excludedCommands": ["maxxing"],
                          "filesystem": {"denyRead": secrets, "allowWrite": write},
                          "network": {"allowedDomains": list(a.get("domains") or [])}}
        deny = []
        for p in secrets:
            g = p + "/**" if not Path(p).is_file() and not p.endswith(".json") else p
            deny += [f"Read(/{g})", f"Edit(/{g})"]
        out["permissions"] = {"deny": deny,
                              "allow": [f"WebFetch(domain:{d})" for d in a.get("domains") or []]}
    if a.get("rules"):
        cmd = f"{shlex.quote(sys.executable)} -m maxxing.agent_guard hook {shlex.quote(path)}"
        out["hooks"] = {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}
    return out


def add_dirs(path: str, a: dict) -> list[str]:
    """`--add-dir` for the `writable` folders: acceptEdits then lets Write/Edit work there too."""
    if not a.get("sandbox"):
        return []
    topic = (config.workspace() / path).parent.parent
    out: list[str] = []
    for w in a.get("writable") or []:
        out += ["--add-dir", str((topic / w).resolve())]
    return out


def merge(base: dict, extra: dict) -> dict:
    """Two settings objects in one (`--settings` is given once): lists of `permissions` add up."""
    out = json.loads(json.dumps(base))
    for k, v in extra.items():
        if k == "permissions":
            p = out.setdefault("permissions", {})
            for kk, vv in v.items():
                p[kk] = list(p.get(kk) or []) + [x for x in vv if x not in (p.get(kk) or [])]
        else:
            out[k] = v
    return out


# ---- rules (PreToolUse hook) -----------------------------------------------------------------------
def check_rules(rules: list[dict], tool: str, tool_input: object) -> str | None:
    """The reason a tool call breaks one of the rules, else None."""
    text = json.dumps(tool_input, ensure_ascii=False).lower() if tool_input is not None else ""
    for r in rules:
        if r.get("tool") not in ("*", tool):
            continue
        if str(r.get("match") or "").lower() in text:
            return r.get("reason") or f"Refused by a rule of this agent: {r['tool']} with {r['match']!r}"
    return None


def hook(path: str) -> int:
    """PreToolUse hook: read the call on stdin, answer deny (with the reason) when a rule matches."""
    from . import agents
    try:
        ev = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        rules = agents.load(path)["rules"] if agents.exists(path) else []
    except Exception:                                   # never block a turn because the hook broke
        return 0
    why = check_rules(rules, str(ev.get("tool_name") or ""), ev.get("tool_input"))
    if why:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    return 0


# ---- the maxxing CLI inside a sandboxed turn ---------------------------------------------------------
UNIT_RE = re.compile(r"/maxxing-([0-9a-f]{8})\.service(?:/|$)")


def sandboxed_turn() -> str | None:
    """The agent path when this process belongs to a sandboxed agent turn (its systemd unit), else None."""
    try:
        cg = Path("/proc/self/cgroup").read_text()
    except OSError:
        return None
    m = UNIT_RE.search(cg)
    if not m:
        return None
    return sandboxed_session(m.group(1))


def sandboxed_session(sid8: str) -> str | None:
    """The agent path of session <sid8...> when it runs in a sandboxed agent folder, else None."""
    from . import agents
    from .sessions import store
    for sid in store.list_ids():
        if sid.startswith(sid8):
            p = (store.read(sid) or {}).get("path") or ""
            if agents.exists(p) and agents.load(p)["sandbox"]:
                return p
    return None


def check_cli(argv: list[str]) -> str | None:
    """Why `maxxing <argv>` is refused in a sandboxed agent turn, else None."""
    words = [a for a in argv if not a.startswith("-")]
    if not words:
        return None
    path = sandboxed_turn()
    if not path:
        return None
    cmd, sub = words[0], (words[1] if len(words) > 1 else "")
    allowed = CLI_ALLOWED.get(cmd, set())
    if allowed is None or sub in (allowed or set()):
        return None
    ok = ", ".join(f"maxxing {c} {'|'.join(sorted(s))}" if s else f"maxxing {c}" for c, s in CLI_ALLOWED.items())
    return (f"`maxxing {cmd}{' ' + sub if sub else ''}` is not allowed in a sandboxed agent turn. Allowed: {ok}. "
            "The owner can turn the sandbox off in the agent settings.")


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "hook":
        return hook(argv[2])
    print("usage: python -m maxxing.agent_guard hook <agent path>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
