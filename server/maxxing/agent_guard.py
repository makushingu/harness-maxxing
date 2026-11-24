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

import contextlib
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
DISTRO_FILE = Path("/etc/apparmor.d/bwrap-userns-restrict")     # Ubuntu's own profile over bubblewrap...
DISTRO_OFF = Path("/etc/apparmor.d/disable/bwrap-userns-restrict")
DISTRO_CHILD = "unpriv_bwrap"                                   # ...and the profile of what bwrap starts

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
    """{ok, missing: [...]} - what the sandbox needs on this server (cached 60 s). The binaries being there is not
    enough: a bubblewrap that cannot nest a user namespace (an AppArmor profile over it) fails every command of a
    sandboxed turn, so one is really started (_probe)."""
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
    elif "bwrap" not in missing and not _probe():
        missing.append("apparmor" if _distro_profile_loaded() else "user namespaces")
    out = {"ok": not missing, "missing": missing}
    _avail = (time.time(), out)
    return out


def _userns_restricted() -> bool:
    try:
        return USERNS_SYSCTL.read_text().strip() == "1"
    except OSError:
        return False


def _profiles() -> list[str]:
    return APPARMOR_PROFILES.read_text().splitlines()


def _bwrap_profile_loaded() -> bool:
    try:
        # by its name: a profile of another namespace (":glycin:bwrap") is not over /usr/bin/bwrap
        return any(ln.startswith("bwrap") for ln in _profiles())
    except OSError:
        return APPARMOR_FILE.is_file()             # profiles list unreadable (not root): trust the file


def _distro_profile_loaded() -> bool:
    """The distribution's own profile over bubblewrap (Ubuntu's bwrap-userns-restrict): what bwrap starts runs as
    `unpriv_bwrap`, without capabilities in its user namespace, so Claude Code's sandbox cannot nest its own."""
    try:
        return any(ln.split(" ")[0] == DISTRO_CHILD for ln in _profiles())
    except OSError:
        return False


def _probe() -> bool:
    """What Claude Code's sandbox does first, in small: a user namespace inside bubblewrap's. False = every command
    of a sandboxed turn would fail there. True when it cannot be tried (no `unshare`): the run says it then.
    Tried where the turns run: in a transient unit like theirs (spawn), not in this process - the service's own
    hardening (ProtectKernelTunables) keeps bubblewrap from mounting /proc, which turn units never have."""
    import subprocess
    if not shutil.which("unshare"):
        return True
    cmd = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-user", "--unshare-pid",
           "--die-with-parent", "--", "unshare", "--user", "--map-root-user", "true"]
    if os.environ.get("MAXXING_SPAWN") != "direct" and shutil.which("systemd-run"):
        from .sessions import spawn
        cmd = ["systemd-run", "--wait", "--quiet", "--collect", "--description", "Harness Maxxing sandbox check",
               *spawn.hardening_properties(), "--", *cmd]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


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
    if _distro_profile_loaded() and not _probe() and drop_distro_profile():
        done.append(f"AppArmor profile {DISTRO_FILE} switched off (it kept the sandbox from starting; "
                    f"back: rm {DISTRO_OFF} && apparmor_parser -r {DISTRO_FILE})")
    if load_profile():
        done.append(f"AppArmor profile {APPARMOR_FILE}")
    available(fresh=True)
    return done


def drop_distro_profile() -> bool:
    """Switch the distribution's profile over bubblewrap off (root, `sandbox-setup` only: never by itself), the way
    AppArmor documents it: a link in disable/ and the profile unloaded. True = done now."""
    import subprocess
    if not DISTRO_FILE.is_file():
        return False
    DISTRO_OFF.parent.mkdir(exist_ok=True)
    made = not DISTRO_OFF.exists()
    if made:
        DISTRO_OFF.symlink_to(DISTRO_FILE)
    try:
        subprocess.run([_parser(), "-R", str(DISTRO_FILE)], check=True)
    except (OSError, subprocess.SubprocessError):
        if made:                                    # never half done: off at the next boot but still loaded now
            DISTRO_OFF.unlink(missing_ok=True)
        raise
    return True


def _parser() -> str:
    """apparmor_parser lives in /usr/sbin, which is not on every PATH (a unit, a cron, a sudo without -i)."""
    return (shutil.which("apparmor_parser") or shutil.which("apparmor_parser", path="/usr/sbin:/sbin")
            or "apparmor_parser")


def load_profile() -> bool:
    """Load the AppArmor profile when the kernel restricts user namespaces and it is missing (root). It lets
    /usr/bin/bwrap create them for every local user, so it is loaded only once agents are sandboxed: by
    `sandbox-setup` or the first sandboxed agent (`ensure_profile`), never by the installer. True = loaded now."""
    import subprocess
    if not _userns_restricted() or _bwrap_profile_loaded():
        return False
    APPARMOR_FILE.write_text(APPARMOR_PROFILE)
    subprocess.run([_parser(), "-r", str(APPARMOR_FILE)], check=True)
    return True


def ensure_profile() -> None:
    """Best effort, when a sandboxed agent is created or sandboxed: the profile its runs need (else they stop and the
    agent page points at `maxxing agents sandbox-setup`)."""
    if os.environ.get("MAXXING_SANDBOX_CHECK") == "0" or sys.platform != "linux" or os.geteuid() != 0:
        return
    with contextlib.suppress(Exception):            # no apparmor_parser, read-only /etc...
        if load_profile():
            available(fresh=True)


# ---- settings of a sandboxed turn ------------------------------------------------------------------
def secret_paths() -> list[str]:
    """What a sandboxed agent never reads: the server state (vault, config), SSH keys, Claude and other CLI logins,
    the Claude transcripts of every session."""
    home = _home()
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
    return list(dict.fromkeys(map(str, paths)))


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
# `NAME=value` anywhere on a line (export, readonly, declare -x..., after `;`, `&&`, `then`, or as a second assignment),
# fish's `set -x NAME value`, a URL with a password (DATABASE_URL)
SECRET_SET = re.compile(r"(?:^|[ \t;&|(`{])(?:(?:export|readonly|local|declare[ \t]+-\w+|typeset[ \t]+-\w+)[ \t]+)*(\w+)=\S"
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
    # the topic's .maxxing.json (permission mode and "Always allow" rules of its sessions, inherited by its agents):
    # only when it exists, like .mcp.json (a new file at the topic's root is never writable)
    return out + [str(p) for p in (folder / ".mcp.json", topic / ".mcp.json", topic / ".maxxing.json") if p.exists()]


# what an agent never writes in its topic, even with `writable: "."`: the other agents (and new ones), the topic's
# own role and memory (read by every session of the topic), its Claude Code settings, the owner's uploads
# (attachments/: a file swapped there would be read by the owner's sessions, a link would send the next upload away),
# its .maxxing.json (the permission mode and "Always allow" rules of the owner's sessions there)
TOPIC_LOCKED = ("agents", "CLAUDE.md", "CLAUDE.local.md", "memory.md", ".claude", ".mcp.json", "attachments",
                ".maxxing.json")


def writable_dirs(path: str, a: dict) -> list[str]:
    """The `writable` folders of a sandboxed agent, as absolute paths. "." (the whole topic) becomes every entry of the
    topic but TOPIC_LOCKED: the sandbox's denyWrite wins over allowWrite, so the topic's `agents/` cannot be denied
    without denying the agent's own folder, and a new folder there would be a new agent. A folder in `agents/` (or one
    holding it through a link) is never writable, nor a TOPIC_LOCKED entry (named, or reached through a link). A link
    only leads inside the topic: an entry whose target is
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
            if _overlaps(q, agents_dir) or q == t:
                continue
            if t in q.parents and q.relative_to(t).parts[0] in TOPIC_LOCKED:   # `notes -> memory.md`: still locked
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
    # the topic's .mcp.json even while missing: unlike the sandbox mount (locked_paths), a deny rule needs no
    # placeholder, and a new one would bring its servers into every session of the topic
    return out + [f"Edit(/{topic / f})" for f in (*TOPIC_LOCKED[1:6], ".maxxing.json")] + \
        [f"Edit(/{topic / d}/**)" for d in (".claude", "attachments")]


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


def settings(path: str, a: dict, approvals: bool = False, chat: bool = False) -> dict:
    """The `--settings` part of an agent turn: sandbox (when on) and the hook of its rules. approvals: the turn asks
    before risky tools (the agent's setting, or forced for an outside event): Claude Code would let every sandboxed
    command through without asking (`autoAllowBashIfSandboxed`), and `maxxing` too if pre-allowed, so neither is.
    The owner's conversation with the agent is never sandboxed (chat_settings); chat: that conversation, which the
    walls of an agent in acceptEdits / default without sandbox do not apply to either."""
    out: dict = {}
    folder = config.workspace() / path
    if a.get("sandbox"):
        write = [str(folder)] + writable_dirs(path, a)
        secrets = secret_paths() + private_paths(path)
        locked = locked_paths(path)
        out["sandbox"] = {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True,
                          "autoAllowBashIfSandboxed": not approvals, "excludedCommands": ["maxxing:*"],
                          "filesystem": {"denyRead": secrets + [p for p in home_wall() if p not in secrets], "allowRead": read_back(),
                                         "allowWrite": write,
                                         "denyWrite": locked},
                          "network": {"allowedDomains": list(a.get("domains") or [])}}
        deny = _deny_secrets(secrets) + [_deny_edit(p) for p in locked]   # its settings and role: the owner's
        deny += [r for r in topic_edit_denied(path) if r not in deny]
        # an excluded command still needs a permission to run outside the sandbox (else it runs inside, where the
        # server state is hidden): `maxxing` is allowed, check_cli limits what it does; with approvals it is asked
        out["permissions"] = {"deny": deny,
                              "allow": ([] if approvals else ["Bash(maxxing:*)"])
                              + [f"WebFetch(domain:{d})" for d in a.get("domains") or []]
                              + topic_read(path)}
    elif not chat and a.get("permission_mode") in ("acceptEdits", "default"):
        # no sandbox, and not free (bypass): Write/Edit reach its `writable` folders (--add-dir), so the files that
        # are the owner's keep off them as in the sandbox; the topic is read without asking, its .env files excepted
        topic = folder.parent.parent
        deny = [f"Read(/{topic}/{g})" for g in ENV_GLOBS]
        if a.get("writable"):
            deny += topic_edit_denied(path)
        out["permissions"] = {"deny": deny, "allow": topic_read(path) + ([] if approvals else list(FREE_CLI))}
    if a.get("rules"):
        out["hooks"] = {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": hook_command(path)}]}]}
    return out


def _deny_secrets(paths: list[str]) -> list[str]:
    """Read and Edit deny rules of secret / private paths (a folder: all it holds)."""
    out: list[str] = []
    for p in paths:
        g = p + "/**" if not Path(p).is_file() and not p.endswith((".json", ".jsonl")) and "*" not in p \
            and not Path(p).name.startswith(".env") else p
        out += [f"Read(/{g})", f"Edit(/{g})"]
    return out


def _deny_edit(p: str) -> str:
    return f"Edit(/{p + '/**' if p.endswith(('/.claude', '/attachments')) else p})"


def chat_settings(path: str, a: dict) -> dict:
    """The `--settings` of the owner's conversation with a sandboxed agent: no sandbox, no approvals (the owner is
    talking), but the files tools still keep off its secrets and its settings (a safety change goes through
    `maxxing agents set`, which asks the owner); its role (CLAUDE.md) is its own to write; its rules hook stays."""
    out = settings(path, {**a, "sandbox": False}, chat=True)
    folder = config.workspace() / path
    deny = _deny_secrets(secret_paths() + private_paths(path))
    deny += [_deny_edit(p) for p in locked_paths(path) if p != str(folder / "CLAUDE.md")]
    out["permissions"] = {"deny": deny}
    return out


# Without a sandbox and without bypass (acceptEdits, default), a command asks, i.e. is refused when nobody answers:
# these `maxxing` ones are let through, so the agent can still hand work over and post to the feed (check_cli says
# which of them an agent turn may run, and on whom).
FREE_CLI = ("Bash(maxxing agents:*)", "Bash(maxxing feed:*)")


def topic_read(path: str) -> list[str]:
    """`permissions.allow`: the files tools read the agent's topic without asking (its work is there; the deny rules
    of the secrets and private paths still win). Else a turn that is not in bypass is refused each file outside its
    own folder, and one started by outside text asks for every one of them."""
    return [f"Read(/{(config.workspace() / path).parent.parent}/**)"]


def hook_command(path: str) -> str:
    """The rules hook, run by Claude Code outside the sandbox from the agent folder (which the agent writes): `-I`
    keeps the folder (and PYTHONPATH) off sys.path, so a `maxxing/` package written there is never imported."""
    boot = (f"import sys; sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r}); "
            "from maxxing.agent_guard import main; sys.exit(main(sys.argv))")
    return f"{shlex.quote(sys.executable)} -I -c {shlex.quote(boot)} hook {shlex.quote(path)}"


def add_dirs(path: str, a: dict) -> list[str]:
    """`--add-dir` for the `writable` folders: acceptEdits then lets Write/Edit work there too (with or without the
    sandbox: without it and without bypass, they are the only way the agent writes in its topic)."""
    topic = (config.workspace() / path).parent.parent
    dirs = writable_dirs(path, a)
    if "." in (a.get("writable") or []):            # the whole topic: Write/Edit keep to it (topic_edit_denied)
        dirs = [str(topic.resolve())] + [d for d in dirs if not Path(d).is_relative_to(topic.resolve())]
    return [x for d in dirs for x in ("--add-dir", d)]


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
        if r.get("tool") in ("*", tool) and str(r.get("match") or "").lower() in text:
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
    if why := check_rules(rules, str(ev.get("tool_name") or ""), ev.get("tool_input")):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": why}}))
    return 0


# ---- the maxxing CLI inside a sandboxed turn ---------------------------------------------------------
UNIT_RE = re.compile(r"/maxxing-([0-9a-f]{8})(?:-\d+)?\.service(?:/|$)")


def _unit() -> re.Match | None:
    """This process's systemd unit maxxing-<sid8> (a turn's), else None."""
    try:
        return UNIT_RE.search(Path("/proc/self/cgroup").read_text())
    except OSError:
        return None


def turn_meta() -> dict | None:
    """The session of the turn this process belongs to (its systemd unit maxxing-<sid8>), else None."""
    if not (m := _unit()):
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
    try:                                    # a session's turn started by a send (maxxing sessions send): its hops
        depth = max(depth, int((meta or {}).get("turn_hops") or 0))
    except (TypeError, ValueError):
        pass
    from . import agents
    manager = bool(path) and agents.manager_turn(meta if meta is not None else {"env": dict(os.environ)})
    tampered = bool(meta is not None and path and (
        (os.environ.get("MAXXING_AGENT") or "").strip() != path
        or (os.environ.get("MAXXING_AGENT_DEPTH") or "0").strip() != str(env.get("MAXXING_AGENT_DEPTH") or "0")))
    return {"path": path, "depth": depth, "tampered": tampered, "manager": manager,
            "session": str((meta or {}).get("id") or (os.environ.get("MAXXING_SESSION") if meta is None else "") or "")}


def sandboxed_turn() -> str | None:
    """The agent path when this process belongs to a sandboxed agent turn (its systemd unit), else None. The owner's
    conversation with that agent is not one: it runs outside the sandbox (agents.run_settings)."""
    meta = turn_meta()
    p = (meta or {}).get("path") or ""
    from . import agents
    return p if p and _sandboxed(p) and not agents.manager_turn(meta) else None


def _sandboxed(p: str) -> bool:
    from . import agents
    return agents.exists(p) and agents.load(p)["sandbox"]


# changing an agent (any agent) is the owner's: refused in every agent turn, sandboxed or not
AGENT_OWNER_ONLY = {"create", "cron", "webhook", "watch", "after", "on", "off", "silent", "loud", "set", "import", "sandbox-setup", "group"}
# ...but the owner's conversation with an agent (its manager) runs these on that agent itself
AGENT_MANAGER = {"cron", "webhook", "watch", "after", "on", "off", "silent", "loud", "set", "show", "run"}


# ...and so is what starts something with the owner's rights outside the agent's guards (a session of any topic,
# a scheduled job now): an agent hands work to another agent (`maxxing agents send`), which keeps its own
OWNER_ONLY = {"sessions": {"new", "send"}, "cron": {"run", "restore"}}


def _manages(turn: dict, words: list[str], argv: list[str]) -> bool:
    """`maxxing agents <sub> <agent>` run by the manager of that very agent. The target is read by the command's own
    parser (an option value such as `--name writer` is not the agent)."""
    if not (turn.get("manager") and len(words) > 2 and words[0] == "agents" and words[1] in AGENT_MANAGER):
        return False
    import argparse
    import io
    from . import cmd_agents
    p = argparse.ArgumentParser(prog="maxxing agents", add_help=False)
    cmd_agents._configure(p)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            ns, _ = p.parse_known_args(argv[argv.index("agents") + 1:])
        return ns.agents_cmd in AGENT_MANAGER and cmd_agents.resolve(ns.agent) == turn["path"]
    except (ValueError, SystemExit, AttributeError):
        return False


def in_the_sandbox() -> bool:
    """This `maxxing` runs inside an agent turn's sandbox: a command line with a pipe, `;`, `&&`... is sandboxed as a
    whole (only a plain `maxxing …` is excluded), and there the server state is hidden: what it writes would vanish."""
    return bool(os.environ.get("MAXXING_AGENT") and _unit()) and not (config.STATE / "config.json").exists()


BROWSER_OWNER_ONLY = {"set", "profile", "forget", "setup", "settings", "enable", "disable"}
DEVICES_OWNER_ONLY = {"add", "confirm", "remove", "rename", "access", "mode", "screen", "enable", "disable"}
WEBHOOKS_OWNER_ONLY = frozenset({"add", "edit", "remove", "on", "off", "rotate", "secret", "replay", "test", "run",
                                 "describe"})
OWNER_SUBS = {      # command -> (sub-commands of the owner only in any agent turn, why)
    "agents": (AGENT_OWNER_ONLY, "an agent never changes agents (its own triggers, settings or role included). Say "
                                 "what should change in your answer; the owner applies it from the agent page or a "
                                 "session."),
    "browser": (BROWSER_OWNER_ONLY, "its browser settings belong to the owner. Say what should change in your answer "
                                    "(the owner's conversation asks for its browser with `maxxing agents set <itself> "
                                    "browser.enabled=true`: a request the owner allows)."),
    "devices": (DEVICES_OWNER_ONLY, "the person's devices belong to the owner. Say what should change in your answer "
                                    "(the owner's conversation asks for a device with `maxxing agents set <itself> "
                                    "devices='[\"<id>\"]'`: a request the owner allows)."),
    "themes": (frozenset({"install", "verify", "remove"}), "themes change the owner's interface. Say which theme to install in "
                                                 "your answer."),
    "webhooks": (WEBHOOKS_OWNER_ONLY, "webhooks and events run commands and calls with the owner's rights, without "
                                      "an agent's budget or guards. Say what should be done in your answer."),
}


def check_cli(argv: list[str]) -> str | None:
    """Why `maxxing <argv>` is refused in an agent turn, else None."""
    words = [a for a in argv if not a.startswith("-")]
    head = argv[:argv.index("--")] if "--" in argv else argv    # after `--`, a "-h" is a value, not help
    if words and words[0] == "heavy" and len(words) > 1:        # its command takes the rest (REMAINDER): a "-h"
        head = head[:argv.index(words[1])]                      # after it is the command's, argparse prints nothing
    if not words or "-h" in head or "--help" in head:   # help changes nothing (argparse prints it and exits)
        return None
    if in_the_sandbox():
        return ("Run `maxxing` alone on its command line (no pipe, `;`, `&&`, `$(...)` nor redirection): only then "
                "it runs outside the sandbox and reaches the server. Nothing was done.")
    turn = agent_turn()
    if turn["tampered"]:
        return ("Refused: the MAXXING_AGENT* variables of this agent turn were changed. Run `maxxing` with the "
                "environment the run was started with.")
    if _manages(turn, words, argv):
        return None
    cmd, sub = words[0], (words[1] if len(words) > 1 else "")
    subs, why = OWNER_SUBS.get(cmd, ((), ""))
    if turn["path"] and sub in subs:
        return f"`maxxing {cmd} {sub}` is not allowed in an agent turn: {why}"
    if turn["path"] and not turn.get("manager") and sub in OWNER_ONLY.get(cmd, ()):
        return (f"`maxxing {cmd} {sub}` is not allowed in an agent run: it would start work with the owner's rights, "
                "outside this agent's budget and guards. Hand it to another agent (`maxxing agents send`) or say "
                "what should be done in your answer.")
    path = sandboxed_turn()
    if not path:
        return None
    allowed = CLI_ALLOWED.get(cmd, set())
    if allowed is None or sub in allowed:
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
