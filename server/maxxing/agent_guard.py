"""Walls around an agent's turns, built on what Claude Code provides.

    sandbox    Claude Code's sandbox (`settings.sandbox`, bubblewrap + socat on Linux): shell commands can only write
               in the agent folder (+ `writable` folders of the topic), cannot read the server's secrets nor the
               home folder (but for the workspace, git's settings and the tools: `home_wall`, `read_back`), and reach
               only the `domains` of the agent. Read/Edit/Write are not shell commands: the same secrets get
               `permissions.deny` rules (they hold in every mode). Claude Code ignores the domain list in bypass
               mode, so a sandboxed turn never runs in bypass (bypass -> acceptEdits).
    maxxing    the `maxxing` CLI cannot work inside the sandbox (the server state is hidden): it is an excluded
               command, run outside, and in a sandboxed agent turn it only accepts a short list of sub-commands
               (`check_cli`), found from the turn's cgroup (systemd unit maxxing-<sid8>), not from an environment
               variable the turn could change.
    rules      fixed rules of the agent ({tool, match, reason}): a PreToolUse hook (`python -I ... agent_guard
               hook <agent path>`, `hook_command`) refuses a matching tool call and tells Claude why.

Ubuntu 24.04+ restricts user namespaces (kernel.apparmor_restrict_unprivileged_userns=1): bubblewrap needs an
AppArmor profile allowing them (`APPARMOR_PROFILE`), or every sandboxed command fails. `available()` checks it all;
`maxxing agents sandbox-setup` installs what is missing; the first sandboxed agent loads the profile (`ensure_profile`). Imports stay light (the session runner reads this).
"""
from __future__ import annotations

import json
import logging
import os
import pwd
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

from . import config

log = logging.getLogger("maxxing.agent_guard")

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
CLI_ALLOWED = {                        # show/list/feed list are narrowed further (cmd_agents, cmd_feed)
    "feed": {"post", "list"},
    "agents": {"send", "show", "list", "templates"},
    "keys": {"get", "list"},          # filtered by the agent's `keys` (cmd_keys)
    # filtered by the agent's `mail` (cmd_mail.Guard): its mailboxes, rights and senders
    "mail": {"accounts", "folders", "list", "read", "attachment", "write", "move", "mkdir", "refresh", "outbox",
             "archive", "trash", "junk", "inbox", "seen", "unseen", "flag", "unflag"},
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
    if load_profile():
        done.append(f"AppArmor profile {APPARMOR_FILE}")
    available(fresh=True)
    return done


def load_profile() -> bool:
    """Load the AppArmor profile when the kernel restricts user namespaces and it is missing (root). It lets
    /usr/bin/bwrap create them for every local user, so it is loaded only once agents are sandboxed: by
    `sandbox-setup` or the first sandboxed agent (`ensure_profile`), never by the installer. True = loaded now."""
    import subprocess
    if not _userns_restricted() or _bwrap_profile_loaded():
        return False
    APPARMOR_FILE.write_text(APPARMOR_PROFILE)
    subprocess.run(["apparmor_parser", "-r", str(APPARMOR_FILE)], check=True)
    return True


def ensure_profile() -> None:
    """Best effort, when a sandboxed agent is created or sandboxed: the profile its runs need (else they stop and the
    agent page points at `maxxing agents sandbox-setup`)."""
    if os.environ.get("MAXXING_SANDBOX_CHECK") == "0" or sys.platform != "linux" or os.geteuid() != 0:
        return
    try:
        if load_profile():
            available(fresh=True)
    except Exception:                               # noqa: BLE001 - no apparmor_parser, read-only /etc...
        pass


# ---- settings of a sandboxed turn ------------------------------------------------------------------
def secret_paths() -> list[str]:
    """What a sandboxed agent never reads: the server state (vault, config), SSH keys, Claude and other CLI logins,
    the Claude transcripts of every session."""
    home = Path(os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir)
    paths = [config.STATE, home / ".ssh", home / ".claude" / ".credentials.json", home / ".claude.json",
             config.claude_dir() / ".credentials.json", home / ".git-credentials", home / ".netrc",
             home / ".config" / "gh", home / ".aws", home / ".docker" / "config.json", home / ".config" / "rclone"]
    paths += [config.claude_dir() / "projects", home / ".claude" / "projects", config.claude_dir() / "history.jsonl",
              home / ".config", home / ".local" / "share"]       # transcripts of every session; other tools' logins
    paths += [config.claude_dir() / "file-history", home / ".claude" / "file-history"]   # copies of edited files
    paths += [home / f for f in HOME_SECRETS]
    ws = config.workspace()
    paths += [ws / "infra.json", ws / "team"]       # where every site / server is; the Team chats and their files
    paths += [Path(p) for p in SYSTEM_SECRETS if os.path.lexists(p)]
    out: list[str] = []
    for p in paths:
        s = str(p)
        if s not in out:
            out.append(s)
    return out


# logins and histories in the home folder (the sandbox hides the whole home anyway: these also hold for Read/Edit)
HOME_SECRETS = (".bash_history", ".zsh_history", ".python_history", ".psql_history", ".mysql_history", ".lesshst",
                ".viminfo", ".npmrc", ".pypirc", ".pgpass", ".my.cnf", ".gnupg", ".kube", ".cloudflared", ".wrangler",
                ".terraform.d", ".azure", ".oci", ".gcloud", ".vault-token")
# the server's own secrets outside the home folder (only those that exist: the sandbox would mount the others):
# password hashes, SSH host keys, TLS keys and certificates, the web server's data, databases, logs, other users
SYSTEM_SECRETS = ("/etc/shadow", "/etc/shadow-", "/etc/gshadow", "/etc/gshadow-", "/etc/ssh", "/etc/letsencrypt",
                  "/etc/ssl/private", "/etc/caddy", "/var/lib/caddy", "/etc/credstore", "/etc/credstore.encrypted",
                  "/run/credentials", "/etc/garage.toml", "/var/lib/garage", "/var/lib/postgresql", "/var/lib/mysql",
                  "/etc/mysql/debian.cnf", "/var/backups", "/var/log", "/home")
# under the denied ~/.local/share: Claude Code itself (its sandbox helper), the interpreters and tools its commands
# run (the product's venv python is uv's)
READ_BACK = ("claude", "uv/python", "uv/tools", "pnpm", "fnm", "mise/installs")
# the home folder is hidden from a sandboxed command (`home_wall`), but for what its commands need: the workspace
# (narrowed by private_paths), git's settings, tools installed in the home folder, package caches
HOME_BACK = (".gitconfig", ".local/bin", ".local/lib", ".nvm", ".bun", ".cargo", ".rustup", ".deno", ".pyenv", "go",
             ".npm", ".cache/uv", ".cache/pip", ".cache/ms-playwright", ".cache/pnpm", ".cache/yarn", ".cache/deno",
             ".cache/go-build")
CLAUDE_BACK = ("skills", "shell-snapshots", "session-env", ".cc-writes")   # in Claude Code's folder
# the shell's own settings (bash reads them in every command: denied, each one starts with "Permission denied"),
# unless one sets something that looks like a secret (`export API_TOKEN=...`: those belong in the Keys vault)
SHELL_RC = (".bashrc", ".bash_profile", ".bash_login", ".profile", ".bash_aliases", ".bash_logout", ".zshrc",
            ".zshenv", ".zprofile", ".inputrc")
# a name with one of these anywhere (PGPASSWORD, github_token), or one of SECRET_PARTS as a whole `_` part (NPM_KEY)
SECRET_WORDS = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "APIKEY", "CREDENTIAL")
SECRET_PARTS = {"KEY", "PASS", "PWD", "AUTH", "PAT", "DSN"}
# `NAME=value` (export, readonly, declare -x...), fish's `set -x NAME value`, a URL with a password (DATABASE_URL)
SECRET_SET = re.compile(r"^[ \t]*(?:(?:export|readonly|local|declare[ \t]+-\w+|typeset[ \t]+-\w+)[ \t]+)*(\w+)=\S"
                        r"|^[ \t]*set[ \t]+-\w+[ \t]+(\w+)[ \t]+\S|(://)[^/\s:@]{1,256}:[^@\s/]{1,256}@", re.M)


def sets_a_secret(text: str) -> bool:
    """A shell settings file that sets something looking like a secret (those belong in the Keys vault)."""
    for m in SECRET_SET.finditer(text):
        if m[3]:
            return True
        name = (m[1] or m[2]).upper()
        if any(w in name for w in SECRET_WORDS) or SECRET_PARTS & set(name.split("_")):
            return True
    return False


# a link of the home folder into these is a tool, left readable
TOOL_ROOTS = tuple(Path(p) for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/opt", "/snap", "/nix"))
TOOLS = ("node", "npm", "npx", "uv", "python3", "python", "git", "bun", "deno", "pnpm", "go")
ENV_GLOBS = (".env", ".env.*", "*/.env", "*/.env.*", "*/*/.env", "*/*/.env.*")


def private_paths(path: str) -> list[str]:
    """What a sandboxed agent never reads in the workspace: the other projects, the other topics of its project, the
    other agents of its topic, the groups of its project it is not a member of (and the kept folders of deleted
    groups), and the `.env` files of its topic (globs, expanded by Claude Code at sandbox start)."""
    root = config.workspace()
    folder = root / path
    topic = folder.parent.parent
    out: list[str] = []
    for d, keep in ((root / "projects", topic.parent.parent), (topic.parent, topic), (topic / "agents", folder)):
        try:
            out += [str(k) for k in sorted(d.iterdir()) if k.is_dir() and k != keep]
        except OSError:
            pass
    try:
        groups = sorted(topic.parent.parent.joinpath("groups").iterdir())
    except OSError:
        groups = []
    out += [str(g) for g in groups if g.is_dir() and not _member(g, path)]
    return out + [f"{topic}/{g}" for g in ENV_GLOBS]


def _member(group: Path, path: str) -> bool:
    """`path` is a member of the group folder (its group.json, read here: agent_rooms is not imported by the runner)."""
    if group.name.startswith("."):                  # .kept-<name>-<time>: a deleted group's files
        return False
    try:
        d = json.loads((group / "group.json").read_text(encoding="utf-8"))
        return any(isinstance(m, dict) and m.get("path") == path for m in d.get("members") or [])
    except (OSError, ValueError, AttributeError):
        return False


def _home() -> Path:
    return Path(os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir)


def _home_kept() -> set[Path]:
    """What a sandboxed command still reads in the home folder: the workspace (narrowed by private_paths), HOME_BACK,
    the skills and shell snapshots of Claude Code, the install folder of a tool installed in the home folder."""
    home = _home()
    h = home.resolve()
    kept = {home / p for p in HOME_BACK}
    kept.add(config.workspace())
    for n in SHELL_RC:
        rc = home / n
        try:
            if rc.is_file() and not rc.is_symlink() and rc.stat().st_size < 1_000_000 \
                    and not sets_a_secret(rc.read_text(encoding="utf-8", errors="replace")):
                kept.add(rc)
        except OSError:
            pass
    for d in {config.claude_dir(), home / ".claude"}:
        kept |= {d / n for n in CLAUDE_BACK}
    for t in TOOLS:
        w = shutil.which(t)
        p = Path(w).resolve() if w else None
        if not p or h not in p.parents:
            continue
        root = p.parent.parent if p.parent.name == "bin" else p.parent    # ~/.nvm/versions/node/v22, ~/.hermes/node
        kept.add(root if root not in (h, h / ".local") else p.parent)
    out = set()
    for k in kept:
        try:
            out.add(k.resolve())
        except (OSError, RuntimeError):             # a link in a loop: not kept
            pass
    return out


def home_wall() -> list[str]:
    """`denyRead` of a sandboxed command beyond the named secrets: everything in the home folder (SSH keys, scripts,
    notes, other tools' files: a list of names always misses some) but `_home_kept`, entry by entry (a denied home
    with allowRead inside breaks bubblewrap's mounts). A link is denied when it leads out of the home folder (but into
    a tool folder, TOOL_ROOTS); one inside is its target's entry. ~/.local/share stays with secret_paths + READ_BACK."""
    home = _home()
    h = home.resolve()
    ws = config.workspace().resolve()
    if h == Path("/") or ws == h or ws in h.parents:   # a workspace that is the home folder: its own walls only
        return []
    kept = _home_kept()
    out: list[str] = []

    def walk(d: Path, depth: int) -> None:
        try:
            kids = sorted(d.iterdir())
        except OSError:
            return
        for k in kids:
            if k == home / ".local" / "share":
                continue
            try:
                r = k.resolve()
            except (OSError, RuntimeError):         # a link in a loop (Python < 3.13 raises RuntimeError)
                out.append(str(k))
                continue
            if k.is_symlink():                      # inside the home folder: its target is an entry of its own
                if r not in kept and h not in r.parents and r != h and r != Path("/") \
                        and not any(r == t or t in r.parents for t in TOOL_ROOTS):
                    out.append(str(k))
                continue
            if r in kept:
                continue
            if depth < 4 and k.is_dir() and any(r in x.parents for x in kept):
                walk(k, depth + 1)
            else:
                out.append(str(k))
    walk(home, 0)
    return out


def read_back() -> list[str]:
    """`allowRead` inside the denied folders: the tools its commands run."""
    share = _home() / ".local" / "share"
    return [str(share / p) for p in READ_BACK if (share / p).exists()]


def locked_paths(path: str) -> list[str]:
    """What a sandboxed agent never writes even in its own folder: its settings (agent.json: triggers, budget, keys,
    sandbox...), its role (CLAUDE.md), and the Claude Code project files that could widen its rights (.claude/, an
    existing .mcp.json) in its folder and its topic. The owner changes them from the agent page, the CLI or a session."""
    folder = config.workspace() / path
    topic = folder.parent.parent
    out = [str(folder / "agent.json"), str(folder / "CLAUDE.md"), str(folder / ".claude"), str(topic / ".claude")]
    # the owner's uploads (web page, Telegram): read only, so the agent can neither swap a file it was sent nor turn
    # the folder into a link that sends the next upload elsewhere (created here: a missing path would be mounted)
    # (the agent's and its topic's, even when `writable` names them: denyWrite wins over allowWrite)
    for att in (folder / "attachments", topic / "attachments"):
        try:
            if not att.is_symlink():
                att.mkdir(exist_ok=True)
            if att.is_dir() and not att.is_symlink():
                out.append(str(att))
        except OSError:
            pass
    # a missing .mcp.json is not locked: the sandbox would mount a placeholder there for the run, which breaks a
    # `git add -A` in a topic that is a clone; a new one is never trusted in a headless run anyway (its servers need
    # an approval)
    return out + [str(p) for p in (folder / ".mcp.json", topic / ".mcp.json") if p.exists()]


# what an agent never writes in its topic, even with `writable: "."`: the other agents (and new ones), the topic's
# own role and memory (read by every session of the topic), its Claude Code settings, the owner's uploads
# (attachments/: a file swapped there would be read by the owner's sessions, a link would send the next upload away)
TOPIC_LOCKED = ("agents", "CLAUDE.md", "CLAUDE.local.md", "memory.md", ".claude", ".mcp.json", "attachments")


def writable_dirs(path: str, a: dict) -> list[str]:
    """The `writable` folders of a sandboxed agent, as absolute paths. "." (the whole topic) becomes every entry of the
    topic but TOPIC_LOCKED: the sandbox's denyWrite wins over allowWrite, so the topic's `agents/` cannot be denied
    without denying the agent's own folder, and a new folder there would be a new agent. A folder in `agents/` (or one
    holding it through a link) is never writable. A link only leads inside the topic: an entry whose target is
    elsewhere (a git clone's `cfg -> /root/.claude`) is dropped, the sandbox, Write/Edit (--add-dir) and `maxxing mail
    attachment` would write in the target. An absolute entry is the shared folder of a group (agents.turn_args): it
    stays in the project's groups/ folder."""
    topic = (config.workspace() / path).parent.parent
    t, agents_dir = topic.resolve(), (topic / "agents").resolve()
    groups = (topic.parent.parent / "groups").resolve()
    out: list[str] = []
    for w in a.get("writable") or []:
        base = groups if Path(w).is_absolute() else t
        p = (topic / w).resolve()
        if p == t:
            try:
                kids = sorted(topic.iterdir())
            except OSError:
                kids = []
            todo = [(k, k.resolve()) for k in kids if k.name not in TOPIC_LOCKED]
        else:
            todo = [(topic / w, p)]
        for k, q in todo:
            if base not in q.parents:
                log.warning("writable %s of agent %s leads outside its topic (%s): dropped", k, path, q)
                continue
            if q == agents_dir or agents_dir in q.parents or q in agents_dir.parents or q == t:
                continue
            if str(q) not in out:
                out.append(str(q))
    return out


def topic_edit_denied(path: str) -> list[str]:
    """`permissions.deny` for Write/Edit (not sandboxed, --add-dir lets them into the `writable` folders): the other
    agents' folders, any agent's settings / role / Claude Code files (a new agent included), the topic's own files."""
    folder = config.workspace() / path
    topic = folder.parent.parent
    ag = topic / "agents"
    out = [f"Edit(/{ag}/*/{f})" for f in ("agent.json", "CLAUDE.md", ".mcp.json")] + [f"Edit(/{ag}/*/.claude/**)"]
    try:
        out += [f"Edit(/{d}/**)" for d in sorted(ag.iterdir()) if d.is_dir() and d.name != folder.name]
    except OSError:
        pass
    return out + [f"Edit(/{topic / f})" for f in TOPIC_LOCKED[1:5]] + [f"Edit(/{topic / d}/**)" for d in (".claude", "attachments")]


def _overlaps(p: Path, q: Path) -> bool:
    return p == q or q in p.parents or p in q.parents


def media_roots(path: str, a: dict | None = None) -> list[str]:
    """The folders whose files the agent's answers may show on its page (links, thumbnails, players): its own folder
    and its `writable` folders. One that is, holds or sits in a secret or private path is left out (the web page
    never previews it, the files API checks the real path with `within`). Never the whole files root."""
    if a is None:
        from . import agents
        a = agents.load(path)
    folder = config.workspace() / path
    cands = [str(folder)] + writable_dirs(path, a)
    banned = [Path(p) for p in secret_paths() + private_paths(path) if "*" not in p]
    banned += [b.resolve() for b in banned]
    out: list[str] = []
    for c in cands:
        p = Path(c)
        real = p.resolve()
        if real == Path(real.anchor) or any(_overlaps(p, b) or _overlaps(real, b) for b in banned):
            continue
        if c not in out:
            out.append(c)
    return out


def mode(requested: str) -> str:
    """Permission mode of a sandboxed turn: never bypass (Claude Code lets every domain through in bypass)."""
    return requested if requested in ("default", "acceptEdits", "plan") else "acceptEdits"


def settings(path: str, a: dict, approvals: bool = False, manager: bool = False) -> dict:
    """The `--settings` part of an agent turn: sandbox (when on) and the hook of its rules. approvals: the turn asks
    before risky tools (the agent's setting, or forced for an outside event): Claude Code would let every sandboxed
    command through without asking (`autoAllowBashIfSandboxed`), and `maxxing` too if pre-allowed, so neither is.
    manager: the owner's conversation (agents.run_settings): it writes its role (CLAUDE.md), its sandboxed commands,
    `maxxing` and the edits in its folders do not ask, and a command can leave the sandbox once the owner allows it
    (Claude Code's `dangerouslyDisableSandbox`: a normal permission prompt, i.e. an approval)."""
    out: dict = {}
    folder = config.workspace() / path
    if a.get("sandbox"):
        write = [str(folder)] + writable_dirs(path, a)
        secrets = secret_paths() + private_paths(path)
        locked = locked_paths(path)
        if manager:
            locked = [p for p in locked if p != str(folder / "CLAUDE.md")]
        out["sandbox"] = {"enabled": True, "allowUnsandboxedCommands": manager, "failIfUnavailable": True,
                          "autoAllowBashIfSandboxed": manager or not approvals, "excludedCommands": ["maxxing:*"],
                          "filesystem": {"denyRead": secrets + [p for p in home_wall() if p not in secrets], "allowRead": read_back(),
                                         "allowWrite": write,
                                         "denyWrite": locked},
                          "network": {"allowedDomains": list(a.get("domains") or [])}}
        deny = []
        for p in secrets:
            g = p + "/**" if not Path(p).is_file() and not p.endswith((".json", ".jsonl")) and "*" not in p \
                and not Path(p).name.startswith(".env") else p
            deny += [f"Read(/{g})", f"Edit(/{g})"]
        for p in locked:                                # its settings and role: the owner's, never the agent's
            deny.append(f"Edit(/{p + '/**' if p.endswith(('/.claude', '/attachments')) else p})")
        # the manager's own role: not denied (another agent's folder still is, a new one asks: outside its folders)
        deny += [r for r in topic_edit_denied(path) if r not in deny
                 and not (manager and r == f"Edit(/{folder.parent}/*/CLAUDE.md)")]
        # an excluded command still needs a permission to run outside the sandbox (else it runs inside, where the
        # server state is hidden): `maxxing` is allowed, check_cli limits what it does; with approvals it is asked
        out["permissions"] = {"deny": deny,
                              "allow": ([] if approvals and not manager else ["Bash(maxxing:*)"])
                              + [f"WebFetch(domain:{d})" for d in a.get("domains") or []]
                              + ([f"Edit(/{p}/**)" for p in write] if manager else [])}
    if a.get("rules"):
        cmd = hook_command(path)
        out["hooks"] = {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]}
    return out


def hook_command(path: str) -> str:
    """The rules hook, run by Claude Code outside the sandbox from the agent folder (which the agent writes): `-I`
    keeps the folder (and PYTHONPATH) off sys.path, so a `maxxing/` package written there is never imported."""
    boot = (f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r}); "
            "from maxxing.agent_guard import main; sys.exit(main(sys.argv))")
    return f"{shlex.quote(sys.executable)} -I -c {shlex.quote(boot)} hook {shlex.quote(path)}"


def add_dirs(path: str, a: dict) -> list[str]:
    """`--add-dir` for the `writable` folders: acceptEdits then lets Write/Edit work there too."""
    if not a.get("sandbox"):
        return []
    topic = (config.workspace() / path).parent.parent
    dirs = writable_dirs(path, a)
    if "." in (a.get("writable") or []):            # the whole topic: Write/Edit keep to it (topic_edit_denied)
        dirs = [str(topic.resolve())] + [d for d in dirs if not Path(d).is_relative_to(topic.resolve())]
    out: list[str] = []
    for d in dirs:
        out += ["--add-dir", d]
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
UNIT_RE = re.compile(r"/maxxing-([0-9a-f]{8})(?:-\d+)?\.service(?:/|$)")


def turn_meta() -> dict | None:
    """The session of the turn this process belongs to (its systemd unit maxxing-<sid8>), else None."""
    try:
        cg = Path("/proc/self/cgroup").read_text()
    except OSError:
        return None
    m = UNIT_RE.search(cg)
    if not m:
        return None
    from .sessions import store
    for sid in store.list_ids():
        if sid.startswith(m.group(1)):
            return store.read(sid) or {}
    return None


def agent_turn() -> dict:
    """The agent run this process belongs to -> {path, depth} (path "" when none). In a turn's unit it comes from the
    session the server wrote (the run's MAXXING_AGENT*), never from this process's environment, which the turn can
    change (`env -u MAXXING_AGENT ...`); outside a unit (direct spawn, the owner's shell) the environment is all
    there is. `tampered`: an agent turn whose environment says something else (refused by check_cli)."""
    meta = turn_meta()
    env = os.environ if meta is None else (meta.get("env") or {})
    path = (env.get("MAXXING_AGENT") or "").strip()
    try:
        depth = max(0, int(env.get("MAXXING_AGENT_DEPTH") or 0))
    except ValueError:
        depth = 0
    from . import agents
    manager = bool(path) and agents.manager_turn(meta if meta is not None else {"env": dict(os.environ)})
    tampered = bool(meta is not None and path and (
        (os.environ.get("MAXXING_AGENT") or "").strip() != path
        or (os.environ.get("MAXXING_AGENT_DEPTH") or "0").strip() != str(env.get("MAXXING_AGENT_DEPTH") or "0")))
    return {"path": path, "depth": depth, "tampered": tampered, "manager": manager,
            "session": str((meta or {}).get("id") or (os.environ.get("MAXXING_SESSION") if meta is None else "") or "")}


def sandboxed_turn() -> str | None:
    """The agent path when this process belongs to a sandboxed agent turn (its systemd unit), else None."""
    meta = turn_meta()
    p = (meta or {}).get("path") or ""
    return p if p and _sandboxed(p) else None


def _sandboxed(p: str) -> bool:
    from . import agents
    return agents.exists(p) and agents.load(p)["sandbox"]


def sandboxed_session(sid8: str) -> str | None:
    """The agent path of session <sid8...> when it runs in a sandboxed agent folder, else None."""
    from .sessions import store
    for sid in store.list_ids():
        if sid.startswith(sid8):
            p = (store.read(sid) or {}).get("path") or ""
            if _sandboxed(p):
                return p
    return None


# changing an agent (any agent) is the owner's: refused in every agent turn, sandboxed or not
AGENT_OWNER_ONLY = {"create", "cron", "webhook", "watch", "on", "off", "set", "import", "sandbox-setup", "group"}
# ...but the owner's conversation with an agent (its manager) runs these on that agent itself
AGENT_MANAGER = {"cron", "webhook", "watch", "on", "off", "set", "show"}


def _manages(turn: dict, words: list[str]) -> bool:
    """`maxxing agents <sub> <agent>` run by the manager of that very agent."""
    if not (turn.get("manager") and len(words) > 2 and words[0] == "agents" and words[1] in AGENT_MANAGER):
        return False
    from . import cmd_agents
    try:
        return cmd_agents.resolve(words[2]) == turn["path"]
    except (ValueError, SystemExit):
        return False


def in_the_sandbox() -> bool:
    """This `maxxing` runs inside an agent turn's sandbox: a command line with a pipe, `;`, `&&`... is sandboxed as a
    whole (only a plain `maxxing …` is excluded), and there the server state is hidden: what it writes would vanish."""
    if not os.environ.get("MAXXING_AGENT"):
        return False
    try:
        if not UNIT_RE.search(Path("/proc/self/cgroup").read_text()):
            return False
    except OSError:
        return False
    return not (config.STATE / "config.json").exists()


def check_cli(argv: list[str]) -> str | None:
    """Why `maxxing <argv>` is refused in an agent turn, else None."""
    words = [a for a in argv if not a.startswith("-")]
    if not words or "-h" in argv or "--help" in argv:   # help changes nothing (argparse prints it and exits)
        return None
    if in_the_sandbox():
        return ("Run `maxxing` alone on its command line (no pipe, `;`, `&&`, `$(...)` nor redirection): only then "
                "it runs outside the sandbox and reaches the server. Nothing was done.")
    turn = agent_turn()
    if turn["tampered"]:
        return ("Refused: the MAXXING_AGENT* variables of this agent turn were changed. Run `maxxing` with the "
                "environment the run was started with.")
    if _manages(turn, words):
        return None
    if turn["path"] and words[0] == "agents" and len(words) > 1 and words[1] in AGENT_OWNER_ONLY:
        return (f"`maxxing agents {words[1]}` is not allowed in an agent turn: an agent never changes agents (its own "
                "triggers, settings or role included). Say what should change in your answer; the owner applies it "
                "from the agent page or a session.")
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
