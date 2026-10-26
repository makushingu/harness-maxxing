"""Core CLI sub-commands: init, doctor, update, status, uninstall.

  maxxing init        create/refresh state dir, config, workspace, shipped skills, default jobs
  maxxing doctor      check the installation (human or --json output, exit code 0/1)
  maxxing update      git pull (ff-only) + uv sync + init + service restart + changelog
  maxxing status      one-screen summary
  maxxing uninstall   remove service, Caddy site, crontab block, CLI link (+ --purge)

Every call to the system (systemctl, caddy, crontab, git, uv) goes through `run()` so tests can
monkeypatch it; system paths are module constants for the same reason.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from . import __version__, cli, config

SERVICE = "claude-maxxing"
UNIT_PATH = Path("/etc/systemd/system/claude-maxxing.service")
JOBS_SLICE_PATH = Path("/etc/systemd/system/maxxing-jobs.slice")
SYSTEMD_DIR = Path("/run/systemd/system")          # present when systemd is PID 1
CADDYFILE = Path("/etc/caddy/Caddyfile")
CADDY_SITE = Path("/etc/caddy/claude-maxxing.caddy")
BIN_LINK = Path("/usr/local/bin/maxxing")
PRODUCT_SKILLS_EXTRA = ("memory", "memory-compaction", "video-motion-design", "pdf-document", "image-edit",
                        "seo-audit", "web-scraping")                     # + every skill named maxxing-*
UPDATE_TOKEN = "github_update_token"
STDIN_SECRETS = (UPDATE_TOKEN, "claude_oauth_token", "anthropic_api_key")
COMPACTION_JOB = {
    "name": "Memory compaction",
    "schedule": "0 5 * * *",
    "kind": "claude",
    "topic_path": "",
    "prompt": ("Use the memory-compaction skill: review every memory.md of the workspace and compact "
               "only the files that need it. End with a one-line report per file changed "
               "(or 'nothing to compact')."),
    "model": "",
    "reuse_session": False,
    "enabled": False,               # turned on at the end of the onboarding, once Claude is signed in
    "notify": "failure",
    "timeout_s": 1800,
}
ENABLE_AFTER_ONBOARDING = ("memory-compaction",)   # default jobs created off until Claude is signed in

# systemd sandboxing of the server process (drop-in next to the unit; install.sh writes the same text).
# Only options that cannot break the product: the server runs as root, starts turns and updates with
# systemd-run (PID 1 creates those units, outside this sandbox), edits root's crontab, runs git/uv/ffmpeg/
# pdftoppm/claude, writes the workspace, /tmp and /etc/caddy. Hence NO ProtectSystem/ProtectHome/PrivateTmp
# (writes, shared /tmp), NO RestrictNamespaces (Claude Code's sandbox), NO MemoryDenyWriteExecute (Node JIT),
# NO UMask=0077 (files created for Caddy or other web servers must stay readable).
HARDENING_NAME = "10-hardening.conf"
HARDENING = """# Harness Maxxing - sandboxing of the server process (`maxxing harden --undo` removes it)
[Service]
NoNewPrivileges=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
LockPersonality=yes
SystemCallArchitectures=native
TasksMax=2048
"""

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
_SYM = {OK: "✔", WARN: "!", FAIL: "✘", INFO: "–"}
_COL = {OK: "32", WARN: "33", FAIL: "31", INFO: "2"}


# ---- system helpers (monkeypatched in tests) -----------------------------------------------
def run(cmd: list[str], timeout: float = 60, cwd: str | Path | None = None,
        input: str | None = None, env: dict | None = None) -> tuple[int, str]:
    """Run a command -> (exit code, stdout+stderr). 127 = not found, 124 = timeout."""
    try:
        p = subprocess.run(cmd, cwd=cwd, input=input, env=env, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]}: timed out after {timeout:.0f}s"


def systemctl(*args: str, timeout: float = 60) -> tuple[int, str]:
    if not Path("/run/systemd/system").is_dir():
        return 127, "systemd is not running"
    return run(["systemctl", *args], timeout=timeout)


def http_get(url: str, timeout: float = 6) -> tuple[int, str]:
    """-> (status, body[:500]); status 0 = connection error (body = reason)."""
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"maxxing-doctor/{__version__}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(500).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:  # noqa: BLE001 - any network failure is a diagnosis, not a crash
        return 0, str(getattr(e, "reason", e))


def http_headers(url: str, timeout: float = 6) -> dict[str, str]:
    """Response headers of GET url (lower-case names), {} on any failure."""
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"maxxing-doctor/{__version__}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return {k.lower(): v for k, v in (e.headers or {}).items()}
    except Exception:  # noqa: BLE001
        return {}


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def _tty() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def line(level: str, text: str, hint: str = "") -> None:
    sym = _SYM[level]
    if _tty():
        sym = f"\033[{_COL[level]}m{sym}\033[0m"
    print(f"  {sym} {text}")
    if hint:
        print(f"      -> {hint}")


def _optional(module: str):
    """Import a sibling module owned by another domain; None if it does not exist (yet)."""
    import importlib
    try:
        return importlib.import_module(f"maxxing.{module}")
    except ModuleNotFoundError as e:
        if e.name and e.name.startswith("maxxing"):
            return None
        raise
    except Exception:   # noqa: BLE001 - a broken optional module must not break the CLI
        return None


def _install_file() -> Path:
    return config.STATE / "install.json"


def _install_state() -> dict:
    return config.read_json(_install_file(), {}) or {}


def _save_install_state(**kw: Any) -> None:
    st = _install_state()
    st.update(kw)
    config.write_json(_install_file(), st)


# ---- product skills ------------------------------------------------------------------------
def product_skill_names() -> list[str]:
    d = config.SKILLS_DIR
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir()
                  if (p / "SKILL.md").is_file()
                  and (p.name.startswith("maxxing-") or p.name in PRODUCT_SKILLS_EXTRA))


def skills_target() -> Path:
    return config.claude_dir() / "skills"


def _skill_vars() -> dict[str, str]:
    return template_vars(config.workspace())


def _render_skill_tree(dst: Path, variables: dict[str, str]) -> None:
    """Render the text files of an installed skill copy like the workspace templates ({{CODE_DIR}}, {{WORKSPACE}},
    {{STATE_DIR}}, {{VERSION}}): Claude reads the paths of this install, not the defaults."""
    for f in dst.rglob("*"):
        if f.is_file() and not f.is_symlink() and f.suffix in RENDERED_SUFFIXES:
            text = f.read_text(encoding="utf-8")
            rendered = render_template(text, variables)
            if rendered != text:
                f.write_text(rendered, encoding="utf-8")


def install_skills() -> dict:
    """Copy product skills to ~/.claude/skills (overwrite them only, text files rendered), drop obsolete ones."""
    dst_root = skills_target()
    dst_root.mkdir(parents=True, exist_ok=True)
    names = product_skill_names()
    previous = set(_install_state().get("skills", []))
    installed, removed, backed_up = [], [], []
    variables = _skill_vars()
    for n in names:
        dst = dst_root / n
        if dst.exists() and n not in previous:
            # a skill with the same name that we did not install: keep a copy, never lose user work
            bak = config.state_dir("trash", "skills") / f"{n}-{int(time.time())}"
            shutil.move(str(dst), str(bak))
            backed_up.append(str(bak))
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        elif dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(config.SKILLS_DIR / n, dst)
        _render_skill_tree(dst, variables)
        installed.append(n)
    for n in sorted(previous - set(names)):
        dst = dst_root / n
        if n.startswith("maxxing-") or n in PRODUCT_SKILLS_EXTRA:
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst, ignore_errors=True)
                removed.append(n)
    _save_install_state(skills=installed)
    return {"installed": installed, "removed": removed, "backed_up": backed_up}


def skills_status() -> list[dict]:
    out = []
    variables = _skill_vars()
    for n in product_skill_names():
        src, dst = config.SKILLS_DIR / n / "SKILL.md", skills_target() / n / "SKILL.md"
        state = "missing" if not dst.is_file() else (
            "ok" if dst.read_text(encoding="utf-8", errors="replace")
            == render_template(src.read_text(encoding="utf-8", errors="replace"), variables) else "outdated")
        out.append({"name": n, "state": state})
    return out


# ---- workspace -----------------------------------------------------------------------------
RENDERED_SUFFIXES = (".md", ".json", ".txt")


def template_vars(ws: Path) -> dict[str, str]:
    return {"{{CODE_DIR}}": str(config.CODE), "{{WORKSPACE}}": str(ws), "{{STATE_DIR}}": str(config.STATE),
            "{{VERSION}}": __version__}


def render_template(text: str, variables: dict[str, str]) -> str:
    for k, v in variables.items():
        text = text.replace(k, v)
    return text


def _seed_unit(rel: Path) -> str | None:
    """'projects/<p>', 'projects/<p>/topics/<t>' or 'extensions/<id>' owning a template path (None = workspace level)."""
    parts = rel.parts
    if len(parts) >= 4 and parts[0] == "projects" and parts[2] == "topics":
        return "/".join(parts[:4])
    if len(parts) >= 2 and parts[0] in ("projects", "extensions") and not (len(parts) == 2 and "." in parts[1]):
        return "/".join(parts[:2])          # a project, or a default extension (extensions/README.md is not one)
    return None


def copy_templates(ws: Path) -> list[str]:
    """Copy templates/workspace into ws - only files that do not exist yet.

    Text files are rendered ({{CODE_DIR}}, {{WORKSPACE}}, {{STATE_DIR}}, {{VERSION}}). Default projects and topics
    are seeded once: one the user deleted or renamed (folder gone after it was seeded) is never
    re-created by a later init / update. Seeded units are recorded in install.json (`seeded`)."""
    src_root = config.TEMPLATES_DIR / "workspace"
    created: list[str] = []
    ws.mkdir(parents=True, exist_ok=True)
    if not src_root.is_dir():
        return created
    state = _install_state()
    seeded = set(state.get("seeded", []))
    if "seeded" not in state and state.get("initialized"):
        seeded |= {"projects/general", "projects/general/topics/inbox"}   # installed before 2.0.0a2
    variables = template_vars(ws)
    # Workspaces made before 2.0.0a33 keep their layout (system/update, server, tasks... and the tutorial project):
    # the 2.0.0a33 system topics are not added next to them (Settings -> Projects adds the starter packs).
    if (ws / "projects/system/topics/update").is_dir() or (ws / "projects/tutorial").is_dir():
        seeded |= {"projects/system/topics/tutorial", "projects/system/topics/harness"}
        skip_new = {"projects/system/topics/tutorial", "projects/system/topics/harness"}
    else:
        skip_new = set()
    units: set[str] = set()
    for src in sorted(src_root.rglob("*")):
        rel = src.relative_to(src_root)
        unit = _seed_unit(rel)
        if unit:
            parent = _seed_unit(Path(unit).parent.parent) if "/topics/" in unit else None
            if unit in skip_new and not (ws / unit).is_dir():
                continue
            if (unit in seeded and not (ws / unit).is_dir()) or \
               (parent and parent in seeded and not (ws / parent).is_dir()):
                continue                                  # removed by the user: leave it gone
            units.add(unit)
        dst = ws / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        elif not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix in RENDERED_SUFFIXES:
                dst.write_text(render_template(src.read_text(encoding="utf-8"), variables), encoding="utf-8")
                shutil.copymode(src, dst)
            else:
                shutil.copy2(src, dst)
            created.append(str(rel))
    if units - seeded:
        _save_install_state(seeded=sorted(seeded | units))
    return created


def claude_settings_defaults() -> bool:
    """~/.claude/settings.json: keep transcripts ~10 years (sessions are resumed for months)."""
    p = config.claude_dir() / "settings.json"
    data = config.read_json(p, {})
    if not isinstance(data, dict):
        return False
    if "cleanupPeriodDays" in data:
        return False
    data["cleanupPeriodDays"] = 3650
    config.write_json(p, data)
    return True


def detect_timezone() -> str:
    """System time zone (the one the cron daemon uses): timedatectl, /etc/timezone, else UTC."""
    code, out = run(["timedatectl", "show", "-p", "Timezone", "--value"], timeout=5)
    tz = out.strip().splitlines()[0].strip() if code == 0 and out.strip() else ""
    if not tz:
        try:
            tz = Path("/etc/timezone").read_text().strip()
        except OSError:
            tz = ""
    return tz or "UTC"


def _is_public_bind(ip: str) -> bool:
    if ip in ("0.0.0.0", "::", "", "*"):
        return True
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False        # host name: cannot judge here
    if a.is_loopback or a.is_link_local or a.is_private:
        return False
    if a.version == 4 and a in ipaddress.ip_network("100.64.0.0/10"):   # Tailscale / CGNAT
        return False
    return True


def update_topic() -> str:
    """The topic that handles updates: `system/harness` since 2.0.0a33, `system/update` on older workspaces."""
    try:
        ws = config.workspace()
        if (ws / "projects/system/topics/update").is_dir() and not (ws / "projects/system/topics/harness").is_dir():
            return "system/update"
    except Exception:  # noqa: BLE001
        pass
    return "system/harness"


# ---- default managed jobs ------------------------------------------------------------------
def default_jobs() -> list[tuple[str, dict]]:
    """(key, job) created once by init. Shell commands use the absolute `maxxing` path."""
    crons = _optional("crons")
    mx = crons.maxxing_bin() if crons is not None else "maxxing"
    can_update = update_source() is not None       # no git remote (and no license): the weekly check could only fail
    return [
        ("memory-compaction", dict(COMPACTION_JOB)),
        ("check-updates", {
            "name": "Check for updates", "schedule": "0 9 * * 1", "kind": "shell",
            "command": f"{mx} update --check --notify", "enabled": can_update, "notify": "failure",
            "timeout_s": 300}),
        ("morning-tasks", {
            "name": "Morning tasks", "schedule": "0 8 * * *", "kind": "claude",
            "topic_path": "projects/general/topics/inbox",
            "prompt": ("Use the maxxing-tasks skill to read tasks.json. Reply with a short morning brief: "
                       "overdue tasks, then tasks due today, one line each (title, due date, priority), "
                       "most urgent first, then the number of tasks in progress. If nothing is due, say "
                       "so in one line. Do not change any task."),
            "model": "", "reuse_session": False, "enabled": False, "notify": "always", "timeout_s": 600}),
    ] + _deps_jobs(mx)


def _deps_jobs(mx: str) -> list[tuple[str, dict]]:
    deps = _optional("deps")
    return deps.default_jobs(mx) if deps is not None else []


OFF_ON_EXISTING_INSTALLS = {"deps-clean", "deps-check"}   # 2.0.0a70 weekly jobs: on for new installs only


def ensure_default_crons() -> str:
    """Create the default jobs once each (never re-created after the user deleted them)."""
    crons = _optional("crons")
    if crons is None:
        return "crons module not available - skipped"
    done = set(_install_state().get("default_crons", []))
    existing_install = bool(done)                  # jobs added by a later version arrive off there (no silent change)
    lister = getattr(crons, "list_jobs", None)
    creator = getattr(crons, "create_job", None) or getattr(crons, "create", None)
    if creator is None:
        return "crons module has no create_job() - skipped"
    todo = [(k, j) for k, j in default_jobs() if k not in done]
    if not todo:
        return "default jobs already created"
    made, problems = [], []
    try:
        existing = lister() if lister else []
        if isinstance(existing, dict):
            existing = existing.get("jobs", [])
        names = {j.get("name") for j in existing or []}
    except Exception as e:  # noqa: BLE001
        return f"could not create the default jobs: {e}"
    pending = list(_install_state().get("enable_after_onboarding", []))
    for key, job in todo:
        try:
            if job["name"] not in names:
                if existing_install and key in OFF_ON_EXISTING_INSTALLS:
                    job = {**job, "enabled": False}
                created = creator(dict(job))
                made.append(job["name"] + ("" if job.get("enabled", True) else " (disabled)"))
                if key in ENABLE_AFTER_ONBOARDING and isinstance(created, dict) and created.get("id"):
                    pending.append(created["id"])
            done.add(key)
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", "") == "invalid_topic":
                done.add(key)                  # its topic was deleted by the user: do not insist
            problems.append(f"{job['name']}: {e}")
    _save_install_state(default_crons=sorted(done), enable_after_onboarding=pending)
    msg = ("created " + ", ".join(made)) if made else "default jobs ready"
    return msg + (f" - problems: {'; '.join(problems)}" if problems else "")


def enable_pending_jobs() -> list[str]:
    """End of the onboarding with Claude signed in: turn on the default jobs created off for that reason (Memory
    compaction), once. A job the user changed meanwhile is left as it is; existing installs have no pending job."""
    pending = _install_state().get("enable_after_onboarding") or []
    if not pending:
        return []
    crons = _optional("crons")
    if crons is None:
        return []
    turned_on = []
    for cid in pending:
        try:
            job = crons.get_job(cid)
            if job and not job.get("enabled") and job.get("created") == job.get("updated"):
                crons.update_job(cid, {"enabled": True})
                turned_on.append(cid)
        except Exception:  # noqa: BLE001 - never break the onboarding
            pass
    _save_install_state(enable_after_onboarding=[])
    return turned_on


# ---- jobs slice ----------------------------------------------------------------------------
_SLICE_MEMORY_RE = re.compile(r"^\d+(\.\d+)?[%KMGT]?$")


def jobs_slice_text(cfg: dict | None = None) -> str:
    cap = str((cfg if cfg is not None else config.load_config()).get("jobs_memory_max") or "").strip()
    limit = f"MemoryMax={cap}\n" if cap and cap.lower() != "infinity" and _SLICE_MEMORY_RE.match(cap) else ""
    return ("# Harness Maxxing - every scheduled job unit runs in this slice (config `jobs_memory_max`, then `maxxing init`)\n"
            "[Unit]\nDescription=Harness Maxxing scheduled jobs\n\n[Slice]\n" + limit)


def ensure_jobs_slice() -> str:
    """Write /etc/systemd/system/maxxing-jobs.slice (the memory budget shared by the jobs running at once) when it
    changed, then daemon-reload. Skipped without systemd and in tests/dev (MAXXING_SPAWN=direct)."""
    if os.environ.get("MAXXING_SPAWN") == "direct" or not SYSTEMD_DIR.is_dir():
        return "skipped (no systemd)"
    text = jobs_slice_text()
    try:
        if JOBS_SLICE_PATH.is_file() and JOBS_SLICE_PATH.read_text() == text:
            return "unchanged"
        JOBS_SLICE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = JOBS_SLICE_PATH.with_name(JOBS_SLICE_PATH.name + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, JOBS_SLICE_PATH)
    except OSError as e:
        return f"not written: {e}"
    systemctl("daemon-reload")
    return "written"


# ---- init ----------------------------------------------------------------------------------
def _cfg_raw() -> dict:
    raw = config.read_json(config.config_path(), {})
    return raw if isinstance(raw, dict) else {}


def do_init(a: argparse.Namespace) -> dict:
    report: dict[str, Any] = {}
    st = config.STATE
    st.mkdir(parents=True, exist_ok=True)
    os.chmod(st, 0o700)

    raw = _cfg_raw()
    flags = {"workspace": a.workspace, "files_root": a.files_root, "port": a.port, "bind": a.bind,
             "public_url": a.public_url, "timezone": a.timezone, "language": a.language,
             "system_clock": a.system_clock, "claude_dir": getattr(a, "claude_dir", None)}
    if a.bind is not None and _is_public_bind(a.bind) and not _is_hostname(a.bind):
        raise SystemExit(f"Refusing to bind {a.bind!r}: use 127.0.0.1 (behind Caddy) or the Tailscale IP.")
    for k, v in flags.items():
        if v is not None:
            raw[k] = str(Path(v).expanduser().resolve()) if k in ("workspace", "files_root", "claude_dir") and v else v
    if a.public_url is not None:
        raw["public_url"] = a.public_url.rstrip("/")
    raw.setdefault("workspace", config.DEFAULT_CONFIG["workspace"])
    if "files_root" not in raw:
        ws = Path(raw["workspace"])
        h = home()
        raw["files_root"] = str(h) if h == ws or h in ws.parents else str(ws)
    for k in ("bind", "port", "language"):
        raw.setdefault(k, config.DEFAULT_CONFIG[k])
    raw.setdefault("timezone", detect_timezone())
    raw.setdefault("public_url", "")
    before_a70 = bool(_install_state().get("default_crons"))   # an install that already had its default jobs
    if "cron_keep_background" not in raw:         # written once: installed before 2.0.0a70 = background programs of
        raw["cron_keep_background"] = before_a70  # jobs keep living, as they did
    if "unit_hardening" not in raw:               # same: the turn / job unit protections are new there, so off
        raw["unit_hardening"] = not before_a70
    from . import register                        # once (2.0.0a94): anonymous counter on unless the user was asked
    register.migrate(raw)
    config.write_json(config.config_path(), raw)
    for sub in ("sessions", "crons", "telegram", "backup", "trash", "logs"):
        config.state_dir(sub)
    report["config"] = {k: raw[k] for k in ("workspace", "files_root", "bind", "port", "public_url",
                                             "timezone", "language")}

    if a.secret_from_stdin:
        if a.secret_from_stdin not in STDIN_SECRETS:
            raise SystemExit(f"--secret-from-stdin accepts: {', '.join(STDIN_SECRETS)}")
        val = sys.stdin.read().strip()
        config.set_secret(a.secret_from_stdin, val or None)
        report["secret"] = f"{a.secret_from_stdin} {'stored' if val else 'removed'}"
    if config.secrets_path().exists():
        os.chmod(config.secrets_path(), 0o600)

    ws = Path(raw["workspace"])
    report["workspace_created"] = copy_templates(ws)
    report["skills"] = install_skills()
    report["claude_settings"] = "cleanupPeriodDays set to 3650" if claude_settings_defaults() else "unchanged"
    report["crons"] = "skipped (--no-crons)" if a.no_crons else ensure_default_crons()
    report["jobs_slice"] = ensure_jobs_slice()
    report["service_memory"] = ensure_service_memory()
    cr = _optional("crons")
    try:
        # lines are guarded or not depending on the clock mode; older lines get `--detach` (job units)
        cr and cr.sync_crontab()
    except Exception:  # noqa: BLE001
        pass
    _save_install_state(version=__version__, code_dir=str(config.CODE), initialized=time.time())
    from . import security
    if not security.password_is_set():
        report["setup_link"] = f"{cli._base(config.load_config())}/setup?token={security.ensure_setup_token()}"
    return report


def _is_hostname(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return False
    except ValueError:
        return s not in ("", "*")


def cmd_init(a) -> int:
    r = do_init(a)
    if a.json:
        print(json.dumps(r, indent=2))
        return 0
    if a.quiet:
        return 0
    c = r["config"]
    print(f"Harness Maxxing {__version__} - init")
    line(OK, f"state      {config.STATE}")
    line(OK, f"config     bind {c['bind']}:{c['port']}  tz {c['timezone']}  lang {c['language']}"
             + (f"  url {c['public_url']}" if c["public_url"] else ""))
    n = len(r["workspace_created"])
    line(OK, f"workspace  {c['workspace']}" + (f" ({n} file(s) created)" if n else " (unchanged)"))
    sk = r["skills"]
    line(OK, f"skills     {len(sk['installed'])} installed in {skills_target()}"
             + (f", removed {', '.join(sk['removed'])}" if sk["removed"] else ""))
    for b in sk["backed_up"]:
        line(WARN, f"an existing skill was replaced; previous copy kept in {b}")
    line(OK, f"claude     {r['claude_settings']}")
    line(INFO if "skipped" in r["crons"] or "not" in r["crons"] else OK, f"jobs       {r['crons']}")
    if r.get("secret"):
        line(OK, f"secret     {r['secret']}")
    if r.get("setup_link"):
        print(f"\nFirst sign-in (one-time link, valid 1 h - `maxxing setup-link` for a fresh one):\n  {r['setup_link']}")
    return 0


def _cfg_init(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workspace", help="workspace folder (default /root/maxxing)")
    p.add_argument("--files-root", help="root folder shown in the Files page (default: home)")
    p.add_argument("--port", type=int, help="HTTP port (default 8787)")
    p.add_argument("--bind", help="listen address: 127.0.0.1 or the Tailscale IP (never 0.0.0.0)")
    p.add_argument("--public-url", help="public URL, e.g. https://ui.example.com ('' to clear)")
    p.add_argument("--timezone", help="IANA time zone, e.g. Europe/Paris (default: system)")
    p.add_argument("--language", choices=["en", "fr"], help="UI language")
    p.add_argument("--system-clock", choices=["follow", "keep"],
                   help="follow: the system zone follows the configured one; keep: never touch it (shared server)")
    p.add_argument("--claude-dir", help="Claude Code folder for Harness Maxxing (default ~/.claude): another one keeps "
                                        "it apart from a Claude Code already used here ('' = ~/.claude)")
    p.add_argument("--secret-from-stdin", metavar="NAME",
                   help=f"store a secret read from stdin ({', '.join(STDIN_SECRETS)})")
    p.add_argument("--no-crons", action="store_true", help="do not create the default jobs")
    p.add_argument("--quiet", action="store_true", help="no output")
    p.add_argument("--json", action="store_true", help="JSON report")


# ---- doctor --------------------------------------------------------------------------------
Check = dict


def _c(cid: str, level: str, title: str, detail: str = "", fix: str = "") -> Check:
    return {"id": cid, "level": level, "title": title, "detail": detail, "fix": fix}


def claude_bin() -> str | None:
    env = os.environ.get("MAXXING_CLAUDE_BIN")
    if env:
        return env
    found = shutil.which("claude")
    if found:
        return found
    for p in (home() / ".local" / "bin" / "claude", Path("/usr/local/bin/claude")):
        if p.exists():
            return str(p)
    return None


def uv_bin() -> str | None:
    if Path("/usr/local/bin/uv").exists():            # the pinned one (deps.toml) before any other on PATH
        return "/usr/local/bin/uv"
    found = shutil.which("uv")
    if found:
        return found
    for p in (home() / ".local" / "bin" / "uv",):
        if p.exists():
            return str(p)
    return None


def claude_auth() -> tuple[str | None, str]:
    """-> (method, detail). method None = not signed in."""
    if config.get_secret("claude_oauth_token"):
        return "oauth_token", "long-lived token stored in Harness Maxxing"
    if config.get_secret("anthropic_api_key"):
        return "api_key", "API key stored in Harness Maxxing"
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "oauth_token", "CLAUDE_CODE_OAUTH_TOKEN in the environment"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api_key", "ANTHROPIC_API_KEY in the environment"
    cred = config.claude_dir() / ".credentials.json"
    if cred.is_file():
        return "credentials", f"Claude CLI sign-in ({cred})"
    return None, "no token, API key or CLI sign-in found"


def _listen_addrs(port: int) -> list[str]:
    """Addresses listening on TCP `port` (from /proc/net/tcp*)."""
    out = []
    for fn, v6 in (("/proc/net/tcp", False), ("/proc/net/tcp6", True)):
        try:
            rows = Path(fn).read_text().splitlines()[1:]
        except OSError:
            continue
        for r in rows:
            f = r.split()
            if len(f) < 4 or f[3] != "0A":
                continue
            addr, prt = f[1].split(":")
            if int(prt, 16) != port:
                continue
            raw = bytes.fromhex(addr)
            if v6:
                raw = b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
                out.append(str(ipaddress.IPv6Address(raw)))
            else:
                out.append(str(ipaddress.IPv4Address(raw[::-1])))
    return out


def _crontab_text() -> str | None:
    f = os.environ.get("MAXXING_CRONTAB_FILE")
    if f:
        try:
            return Path(f).read_text()
        except OSError:
            return ""
    code, out = run(["crontab", "-l"], timeout=10)
    if code == 127:
        return None
    return out if code == 0 else ""


def git_auth_env(token: str | None, env: dict | None = None) -> dict:
    """Git environment with the update token passed through GIT_CONFIG_* variables - never in the
    command line, where `ps` would show it to every user of the server (same as backup.py)."""
    out = dict(os.environ if env is None else env)
    out["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        out.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.extraHeader", GIT_CONFIG_VALUE_0=auth_header(token))
    return out


def _git(*args: str, timeout: float = 30, token: str | None = None) -> tuple[int, str]:
    return run(["git", "-C", str(config.CODE), *args], timeout=timeout, env=git_auth_env(token))


def auth_header(token: str) -> str:
    b = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"Authorization: Basic {b}"


def _current_branch() -> str:
    code, out = _git("rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if code == 0 else "main"


PYTHON_MIN = (3, 11)        # tomllib (depcheck, claude_update); same floor as requires-python in pyproject.toml


def check_python() -> Check:
    v = sys.version_info
    lvl = OK if v >= PYTHON_MIN else FAIL
    return _c("python", lvl, f"Python {v.major}.{v.minor}.{v.micro}", sys.executable,
              "" if lvl == OK else "re-run install.sh (uv installs a recent Python)")


def check_uv() -> Check:
    b = uv_bin()
    if not b:
        return _c("uv", WARN, "uv not found", "needed by `maxxing update`",
                  f"bash {config.CODE}/install.sh (installs a pinned, checksum-verified uv)")
    code, out = run([b, "--version"], timeout=10)
    return _c("uv", OK if code == 0 else WARN, out.strip() or "uv", b)


def check_claude_cli() -> Check:
    b = claude_bin()
    if not b:
        return _c("claude_cli", FAIL, "Claude Code CLI not installed", "",
                  "maxxing deps update claude  (the pinned build, checked by its sha256)")
    code, out = run([b, "--version"], timeout=20)
    if code != 0:
        return _c("claude_cli", FAIL, "Claude Code CLI does not start", out.strip()[:200], f"run `{b} --version`")
    return _c("claude_cli", OK, f"Claude Code {out.strip().splitlines()[0] if out.strip() else ''}".strip(), b)


def check_claude_version(fetch: bool = True) -> Check | None:
    """Claude Code behind its latest release (its own auto-update may be off): updates carry security fixes."""
    b = claude_bin()
    if not b or not fetch:
        return None
    from . import depcheck
    code, out = run([b, "--version"], timeout=20)
    installed = (re.findall(r"\d+\.\d+\.\d+", out) or [""])[0] if code == 0 else ""
    latest = depcheck.claude_latest()
    if not installed or not latest:
        return None
    n = depcheck.claude_behind(installed, latest)
    if not n:
        return _c("claude_version", OK, f"Claude Code {installed} is the latest release")
    from . import claude_update
    if claude_update.enabled():
        last = claude_update.load().get("last") or {}
        why = (f"the automatic update failed: {last.get('error')}" if last.get("ok") is False and last.get("to") == latest
               else "the server updates it by itself when nothing has run for 10 min (Settings -> Claude)")
    else:
        why = "releases carry fixes, security ones included; automatic update is off (Settings -> Claude)"
    return _c("claude_version", INFO, f"Claude Code {installed}, {latest} available ({n} release(s) behind)",
              why[:300], f"{b} update   (then maxxing doctor --live)")


def check_skill_listing(cfg: dict) -> Check | None:
    """Every skill's name + description is in every prompt; past Claude Code's budget, descriptions are dropped."""
    from . import depcheck
    roots = [Path(str(cfg.get("workspace") or "/root/maxxing")) / ".claude" / "skills", skills_target()]
    st = depcheck.skill_listing(roots)
    if not st["count"]:
        return None
    title = f"{st['count']} skills listed in every prompt ({st['chars']:,} characters, ~{st['chars'] // 4:,} tokens)"
    if st["chars"] <= depcheck.SKILL_LISTING_BUDGET:
        return _c("skill_listing", OK, title)
    return _c("skill_listing", INFO, title,
              f"over Claude Code's ~{depcheck.SKILL_LISTING_BUDGET:,}-character budget: the descriptions of the least "
              "used skills are dropped, so Claude picks them less reliably",
              "move project-specific skills into projects/<p>/.claude/skills, or hide rare ones from Claude with "
              "\"disable-model-invocation: true\" in their SKILL.md")


def check_deps() -> Check:
    """`maxxing doctor --deps`: known vulnerabilities (OSV) in the installed lockfiles."""
    from . import depcheck
    try:
        r = depcheck.osv_scan()
    except Exception as e:  # noqa: BLE001 - offline / OSV down
        return _c("deps", INFO, "dependency check skipped (OSV not reachable)", str(e)[:120])
    if not r["vulnerable"]:
        return _c("deps", OK, f"no known vulnerability in {r['checked']} installed packages", "osv.dev")
    lines = [f"{v['where']}: {v['name']} {v['version']} ({', '.join(v['ids'])})" for v in r["vulnerable"]]
    return _c("deps", WARN, f"{len(lines)} installed package(s) with a known vulnerability", "; ".join(lines),
              "maxxing update --check (a newer release may fix it), else tell the maintainers")


def check_claude_auth(live: bool = False) -> Check:
    method, detail = claude_auth()
    if not method:
        return _c("claude_auth", FAIL, "Claude is not signed in", detail,
                  "run `claude setup-token` (any machine with a browser) and paste the token in "
                  "Settings -> Claude, or set an API key there")
    if not live:
        from . import claude_auth as ca
        st = ca.status()
        if st["method"] == method and not st["ok"]:
            return _c("claude_auth", FAIL, "Claude sign-in expired", st.get("error") or st["detail"],
                      "run `claude` then /login on the server, or `claude setup-token` and paste the token "
                      "in Settings -> Claude (`maxxing doctor --live` re-tests)")
        when = (f", verified {time.strftime('%Y-%m-%d %H:%M', time.localtime(st['checked_at']))}"
                if st["method"] == method and st.get("checked_at") else ", not verified yet")
        return _c("claude_auth", OK, f"Claude auth: {method}{when}", detail)
    b = claude_bin()
    env = dict(os.environ)
    tok, key = config.get_secret("claude_oauth_token"), config.get_secret("anthropic_api_key")
    if tok:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = tok
    if key:
        env["ANTHROPIC_API_KEY"] = key
    t0 = time.time()
    code, out = run([b or "claude", "-p", "Reply with the single word: ok"], timeout=120, cwd="/tmp", env=env)
    from . import claude_auth as ca
    if code == 0 and "ok" in out.lower():
        ca.record(True, None, "check")
        return _c("claude_auth", OK, f"Claude auth: {method} (live test {time.time() - t0:.1f}s)", detail)
    auth_err = ca.detect(out)
    if auth_err:
        ca.record(False, auth_err, "check")
        return _c("claude_auth", FAIL, "Claude sign-in expired", auth_err,
                  "run `claude` then /login on the server, or `claude setup-token` and paste the token "
                  "in Settings -> Claude")
    return _c("claude_auth", FAIL, f"Claude auth: {method} but the test call failed", out.strip()[-300:],
              "renew the token (`claude setup-token`) or check the API key in Settings -> Claude")


def check_service() -> Check:
    code, out = systemctl("is-active", SERVICE, timeout=10)
    state = out.strip() or "unknown"
    if code == 127:
        return _c("service", WARN, "systemd not available", "the service cannot be checked")
    if not UNIT_PATH.exists() and state != "active":
        return _c("service", WARN, f"service {SERVICE} not installed", "",
                  "run install.sh (or start manually: maxxing serve)")
    if state == "active":
        return _c("service", OK, f"service {SERVICE} active")
    return _c("service", FAIL, f"service {SERVICE} {state}", "",
              f"journalctl -u {SERVICE} -n 50 --no-pager ; systemctl restart {SERVICE}")


def hardening_path() -> Path:
    return UNIT_PATH.with_name(UNIT_PATH.name + ".d") / HARDENING_NAME


SERVICE_MEMORY_NAME = "20-memory.conf"
SERVICE_MEMORY = ("# Harness Maxxing - memory cap of the web server (audit F01; sessions and jobs run in their own units)\n"
                  "[Service]\nMemoryMax=60%\n")


def service_memory_path() -> Path:
    return UNIT_PATH.with_name(UNIT_PATH.name + ".d") / SERVICE_MEMORY_NAME


def ensure_service_memory() -> str:
    """A web service unit written before 2.0.0a70 has no MemoryMax: a drop-in adds one (every `maxxing init`, so
    every update; install.sh now writes it in the unit itself, sized from the RAM)."""
    if os.environ.get("MAXXING_SPAWN") == "direct" or not SYSTEMD_DIR.is_dir() or not UNIT_PATH.is_file():
        return "skipped"
    try:
        if "MemoryMax=" in UNIT_PATH.read_text():
            return "in the unit"
        p = service_memory_path()
        if p.is_file() and p.read_text() == SERVICE_MEMORY:
            return "unchanged"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(SERVICE_MEMORY)
        os.chmod(p, 0o644)
    except OSError as e:
        return f"not written: {e}"
    systemctl("daemon-reload")
    return "written"


def check_hardening() -> Check | None:
    if not UNIT_PATH.exists():
        return None
    p = hardening_path()
    if not p.is_file():
        return _c("hardening", INFO, "service sandboxing not applied", "installed before 2.0.0a32",
                  "maxxing harden  (restarts the service)")
    if p.read_text(errors="replace") != HARDENING:
        return _c("hardening", INFO, "service sandboxing differs from this version", str(p),
                  "maxxing harden  (restarts the service)")
    return _c("hardening", OK, "service sandboxing applied", str(p))


CADDY_SITE = Path(os.environ.get("MAXXING_CADDY_SITE") or "/etc/caddy/claude-maxxing.caddy")
CADDY_BODY_MB = 2100                     # install.sh: request_body max_size (uploads up to 2 GB + multipart overhead)


def _caddy_max_mb(text: str) -> float | None:
    m = re.search(r"max_size\s+(\d+(?:\.\d+)?)\s*([KMG]i?B)?", text, re.I)
    if not m:
        return None
    unit = (m.group(2) or "B").upper().replace("I", "")
    return float(m.group(1)) * {"B": 1 / 1e6, "KB": 1 / 1e3, "MB": 1, "GB": 1e3}[unit]


def check_caddy_site(cfg: dict) -> Check | None:
    """The Caddy site written by an older installer: X-Frame-Options DENY (replaces the app's SAMEORIGIN, so the
    PDF viewer in Files stays blank) or a body limit below upload_max_mb."""
    try:
        text = CADDY_SITE.read_text(errors="replace")
    except OSError:
        return None
    problems, fixes = [], []
    if re.search(r'X-Frame-Options\s+"?DENY', text, re.I):
        problems.append("X-Frame-Options DENY: PDF previews in Files stay blank")
        fixes.append(f"sed -i 's/X-Frame-Options \"DENY\"/X-Frame-Options \"SAMEORIGIN\"/' {CADDY_SITE}")
    # upload_max_mb 0 = no cap in the app: Caddy's own limit is then the only one (compare with what install.sh writes)
    limit, want = _caddy_max_mb(text), int(cfg.get("upload_max_mb") or 0)
    if limit is not None and limit < (want or CADDY_BODY_MB):
        allows = f"the app allows {want} MB" if want else "the app has no limit"
        problems.append(f"uploads above {limit:g} MB are refused by Caddy ({allows})")
        # a bare byte count (`max_size 524288000`) too, like _caddy_max_mb reads it
        fixes.append(f"sed -i -E 's/max_size [0-9.]+ *([KMG]i?)?B?/max_size {CADDY_BODY_MB}MB/' {CADDY_SITE}")
    if not problems:
        return _c("caddy_site", OK, "Caddy site settings match this version", str(CADDY_SITE))
    # a copy first, and a reload only once the edited config is valid; an invalid edit puts the copy back (an
    # invalid site would stop the next restart)
    backup = f"cp -p {CADDY_SITE} {CADDY_SITE}.bak"
    check = (f"{{ caddy validate --config {CADDYFILE} --adapter caddyfile"
             f" || {{ cp -p {CADDY_SITE}.bak {CADDY_SITE}; false; }}; }}")
    return _c("caddy_site", WARN, "Caddy site from an older installer", "; ".join(problems),
              " && ".join([backup, *fixes, check, "systemctl reload caddy"]))


def check_infra_paths() -> Check | None:
    """Path sites (`maxxing infra site add`) named like a route of this version of the UI would hide that page."""
    try:
        from .infra import caddy
        sites = [x for x in caddy.list_sites() if x["mode"] == "path"]
    except Exception:  # noqa: BLE001
        return None
    if not sites:
        return None
    taken = [x["name"] for x in sites if x["name"] in caddy.reserved()]
    if not taken:
        return _c("infra_paths", OK, f"{len(sites)} site(s) under the Harness address", str(caddy.paths_dir()))
    return _c("infra_paths", WARN, "a site hides a page of Harness",
              ", ".join(f"/{n}/" for n in taken) + " is now used by the app",
              "; ".join(f"move it: maxxing infra site remove {n} && maxxing infra site add <new name> ..." for n in taken))


MEMINFO = Path("/proc/meminfo")
SMALL_RAM_MB = 4096                      # under 4 GiB (a "4 GB" VPS reports ~3.8): no swap = OOM risk (audit 2.2)


def check_memory() -> Check | None:
    """A small server without swap: every running Claude turn takes 200-300 MB, so a few at once (plus the
    service, a build...) can make the kernel kill one."""
    try:
        info = {k: int(v.split()[0]) for k, v in (l.split(":", 1) for l in MEMINFO.read_text().splitlines() if ":" in l)}
    except (OSError, ValueError):
        return None
    ram, swap = info.get("MemTotal", 0) // 1024, info.get("SwapTotal", 0) // 1024
    if not ram:
        return None
    title = f"{ram / 1024:.1f} GB of RAM, {swap / 1024:.1f} GB of swap" if swap else f"{ram / 1024:.1f} GB of RAM, no swap"
    if ram >= SMALL_RAM_MB or swap >= 512:
        return _c("memory", OK, title)
    return _c("memory", WARN, title, "under 4 GB without swap: each running Claude turn uses 200-300 MB, local voice "
              "(Whisper), the browsers and video renders more - several at once can run out of memory",
              "fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && "
              "echo '/swapfile none swap sw 0 0' >> /etc/fstab")


def check_bind(cfg: dict) -> Check:
    bind, port = str(cfg.get("bind")), int(cfg.get("port") or 8787)
    if _is_public_bind(bind) and not _is_hostname(bind):
        return _c("bind", FAIL, f"configured to listen on {bind}:{port} (reachable from the internet)", "",
                  "maxxing init --bind 127.0.0.1 && systemctl restart claude-maxxing (put Caddy or Tailscale in front)")
    live = _listen_addrs(port)
    public = [a for a in live if _is_public_bind(a)]
    if public:
        return _c("bind", FAIL, f"port {port} is listening on {', '.join(public)}",
                  "something listens on a public interface", f"ss -ltnp 'sport = :{port}'")
    return _c("bind", OK, f"listens on {bind}:{port} (not public)",
              ", ".join(live) if live else "nothing listening right now")


def check_http(cfg: dict) -> Check:
    bind = str(cfg.get("bind") or "127.0.0.1")
    host = "127.0.0.1" if bind in ("0.0.0.0", "::", "") else bind
    if ":" in host:
        host = f"[{host}]"
    url = f"http://{host}:{cfg.get('port') or 8787}/api/auth/state"
    status, body = http_get(url, timeout=5)
    if status == 200:
        try:
            v = json.loads(body).get("version", "?")
        except ValueError:
            v = "?"
        return _c("http", OK, f"server answers on {url} (version {v})")
    return _c("http", FAIL, "server does not answer", f"{url}: {status or body}",
              f"systemctl status {SERVICE} ; journalctl -u {SERVICE} -n 50 --no-pager")


def check_public_url(cfg: dict) -> Check:
    url = (cfg.get("public_url") or "").rstrip("/")
    if not url:
        return _c("public_url", INFO, "no public URL (local / SSH tunnel access)", "",
                  "domain access: re-run install.sh with ACCESS=domain DOMAIN=ui.example.com")
    status, body = http_get(url + "/api/auth/state", timeout=10)
    if status == 200:
        h = http_headers(url + "/api/auth/state", timeout=10)
        if "cf-ray" in h or h.get("server", "").lower() == "cloudflare":
            return _c("public_url", WARN, f"{url} reachable, but through the Cloudflare proxy",
                      "the server sees Cloudflare's addresses: sign-in alerts and login throttling cannot see the "
                      "real visitor IP",
                      "Cloudflare -> DNS -> this record -> Proxy status: DNS only (grey cloud)")
        return _c("public_url", OK, f"{url} reachable")
    hint = ("check the DNS A record points to this server, ports 80/443 are open, then "
            "journalctl -u caddy -n 50" if url.startswith("https") else "check Tailscale: tailscale status")
    return _c("public_url", WARN if url.startswith("http://") else FAIL, f"{url} not reachable",
              str(status or body), hint)


def check_caddy(cfg: dict) -> Check | None:
    if not CADDY_SITE.exists() and (config.STATE / "reverse-proxy.conf").exists():
        return _c("caddy", OK, "served by your own web server (no Caddy)", str(config.STATE / "reverse-proxy.conf"))
    if not CADDY_SITE.exists():
        if (cfg.get("public_url") or "").startswith("https://"):
            return _c("caddy", WARN, "public URL is https but no Caddy site for Harness Maxxing",
                      str(CADDY_SITE), "re-run install.sh with ACCESS=domain (or configure your own proxy)")
        return None
    code, out = run(["caddy", "validate", "--config", str(CADDYFILE), "--adapter", "caddyfile"], timeout=30)
    if code == 127:
        return _c("caddy", FAIL, "Caddy site file present but caddy is not installed", "", "re-run install.sh")
    if code != 0:
        return _c("caddy", FAIL, "Caddy configuration invalid", out.strip()[-300:],
                  f"caddy validate --config {CADDYFILE} --adapter caddyfile")
    imported = CADDYFILE.exists() and str(CADDY_SITE) in CADDYFILE.read_text()
    if not imported:
        return _c("caddy", WARN, "Caddy site not imported", f"{CADDYFILE} has no 'import {CADDY_SITE}'",
                  f"echo 'import {CADDY_SITE}' >> {CADDYFILE} && systemctl reload caddy")
    code, out = systemctl("is-active", "caddy", timeout=10)
    if out.strip() != "active":
        return _c("caddy", FAIL, f"Caddy {out.strip() or 'inactive'}", "", "systemctl enable --now caddy")
    return _c("caddy", OK, "Caddy configuration valid and active")


def check_crontab() -> Check | None:
    crons = _optional("crons")
    if crons is None:
        return None
    try:
        jobs = crons.list_jobs() if hasattr(crons, "list_jobs") else []
        if isinstance(jobs, dict):
            jobs = jobs.get("jobs", [])
    except Exception as e:  # noqa: BLE001
        return _c("crontab", WARN, "cannot list scheduled jobs", str(e))
    enabled = [j for j in jobs or [] if j.get("enabled")]
    text = _crontab_text()
    if text is None:
        return _c("crontab", FAIL, "cron is not installed", "", "apt-get install -y cron && systemctl enable --now cron")
    missing = [j.get("name") or j.get("id") for j in enabled if str(j.get("id", "\0")) not in text]
    if missing:
        return _c("crontab", WARN, f"{len(missing)} enabled job(s) missing from the crontab",
                  ", ".join(map(str, missing)), "maxxing cron sync")
    return _c("crontab", OK, f"crontab in sync ({len(enabled)} enabled job(s))")


def check_timezone(cfg: dict) -> Check:
    """cron fires in the SYSTEM zone while next runs are computed in config timezone."""
    want, sys_tz = cfg.get("timezone") or "UTC", detect_timezone()
    if want == sys_tz:
        return _c("timezone", OK, f"time zone {want} (config = system)")
    if cfg.get("system_clock") == "keep":
        return _c("timezone", OK, f"time zone {want}, server clock kept at {sys_tz}",
                  "jobs check their schedule in the configured zone (system_clock = keep)")
    return _c("timezone", WARN, f"config time zone {want} differs from the system zone {sys_tz}",
              "scheduled jobs fire in the system zone, the UI shows times in the config zone",
              f"timedatectl set-timezone {want} && systemctl restart cron "
              f"(or: maxxing init --timezone {sys_tz})")


def check_telegram(cfg: dict) -> Check:
    st = None
    gw = _optional("telegram.gateway")
    if gw is not None and hasattr(gw, "status"):
        try:
            st = gw.status()
        except Exception:  # noqa: BLE001
            st = None
    tg = cfg.get("telegram") or {}
    configured = (st or {}).get("configured", bool(config.get_secret("telegram_token")))
    chat = (st or {}).get("chat") or ({"id": tg.get("chat_id")} if tg.get("chat_id") else None)
    if not configured:
        return _c("telegram", INFO, "Telegram not configured (optional)", "", "Settings -> Telegram")
    if not chat:
        return _c("telegram", WARN, "Telegram bot set but no chat linked", "", "Settings -> Telegram -> Link")
    if not tg.get("user_ids"):
        return _c("telegram", WARN, "Telegram chat linked without its owner: the bot answers nobody",
                  "linked by hand or by a very old version", "Settings -> Telegram -> Link again")
    err = (st or {}).get("last_error")
    two = " · two-step sign-in on" if tg.get("two_factor") else ""
    if err:
        return _c("telegram", WARN, "Telegram linked, last error reported" + two, str(err),
                  "maxxing telegram test" + (" (sign-in blocked? maxxing 2fa off)" if two else ""))
    return _c("telegram", OK, f"Telegram linked (chat {chat.get('title') or chat.get('id')}){two}")


def backup_info(cfg: dict) -> dict:
    """{repo, age_h (last success), last_ok} - from the backup module, else its history file."""
    repo = (cfg.get("backup") or {}).get("repo") or ""
    last = None
    mod = _optional("backup")
    if mod is not None and hasattr(mod, "status"):
        try:
            s = mod.status() or {}
            repo, last = s.get("repo") or repo, s.get("last")
        except Exception:  # noqa: BLE001
            last = None
    if last is None:
        h = _optional("health")
        if h is not None and hasattr(h, "last_backup"):
            last = h.last_backup()
    age = None
    if last and last.get("at"):
        age = (time.time() - float(last["at"])) / 3600
    return {"repo": repo, "age_h": age, "last_ok": (last or {}).get("ok")}


def check_backup(cfg: dict) -> Check:
    b = backup_info(cfg)
    if not b["repo"]:
        return _c("backup", INFO, "memory backup not configured (recommended)", "", "Settings -> Backup")
    if b["age_h"] is None:
        return _c("backup", WARN, f"backup to {b['repo']}: never ran", "", "maxxing backup run")
    if b["last_ok"] is False:
        return _c("backup", WARN, f"backup to {b['repo']}: last run failed ({b['age_h']:.0f} h ago)", "",
                  "maxxing backup run ; see Settings -> Backup for the error")
    lvl = OK if b["age_h"] < 48 else WARN
    return _c("backup", lvl, f"backup to {b['repo']}, last run {b['age_h']:.0f} h ago", "",
              "" if lvl == OK else "maxxing backup run ; check the job in Crons")


def check_voice() -> Check:
    from . import voice
    lvl, title, detail, fix = voice.doctor()
    return _c("voice", lvl, title, detail, fix)


def check_tools() -> Check:
    """Node.js + Remotion (videos) + headless browser (PDF) + Scrapling: optional, never a failure."""
    from . import cmd_video
    st = cmd_video.status()
    if st["remotion"] and st["browser"] and st["scrapling"]:
        return _c("tools", OK, f"tools ready (Node.js {st['node']}, Remotion, Scrapling)", st["tools_dir"])
    missing = ", ".join(x for x, ok in (("Node.js", st["node"]), ("Remotion", st["remotion"]),
                                         ("headless browser", st["browser"]), ("Scrapling", st["scrapling"])) if not ok)
    return _c("tools", WARN, f"tools not ready ({missing})", "",
              "maxxing deps update  (or: bash " + str(config.CODE) + "/install.sh --tools)")


NODE_PARTS = ("bin/node", "bin/npm", "bin/npx", "bin/corepack", "include/node", "lib/node_modules/npm",
              "lib/node_modules/corepack", "share/doc/node")


def node_prefixes() -> list[Path]:
    """Where the installer put Node.js: /usr/local, or <state>/tools/node next to an older system Node."""
    out = [config.STATE / "tools" / "node"]
    try:
        for ln in (config.STATE / "install-manifest").read_text().splitlines():
            if ln.startswith("node "):
                out.append(Path(ln[5:].strip()))
    except OSError:
        pass
    return [p for p in dict.fromkeys(out) if (p / "bin" / "node").exists()]


def foreign_owned(prefix: Path, limit: int = 20) -> list[str]:
    """Files of the Node.js install not owned by root (a release tarball extracted with its owner: that user could
    replace the node binary root runs)."""
    bad: list[str] = []
    for part in NODE_PARTS:
        top = prefix / part
        if not os.path.lexists(top):
            continue
        todo = [top]
        while todo and len(bad) < limit:
            p = todo.pop()
            try:
                st = p.lstat()
            except OSError:
                continue
            if st.st_uid != 0 or st.st_gid != 0:
                bad.append(str(p))
            if p.is_dir() and not p.is_symlink():
                try:
                    todo.extend(p.iterdir())
                except OSError:
                    pass
    return bad


def check_node_owner() -> Check | None:
    bad = [f for pre in node_prefixes() for f in foreign_owned(pre)]
    if not bad:
        return None
    return _c("node_owner", FAIL, "Node.js files are not owned by root (another user could replace them)",
              ", ".join(bad[:3]) + (" ..." if len(bad) > 3 else ""), f"bash {config.CODE}/install.sh --tools  (or chown -R root:root on them)")


def check_managed_deps() -> Check | None:
    """deps.toml: components missing / not at the pinned version, and files another user could replace (FAIL)."""
    deps = _optional("deps")
    if deps is None:
        return check_node_owner()
    rows = deps.status()                                # each component's version is asked once (subprocesses)
    bad = [r for r in deps.verify(versions={r["name"]: r["installed"] for r in rows}) if r["level"] == "fail"]
    if bad:
        return _c("deps_files", FAIL, "external components failed verification",
                  "; ".join(f"{r['name']}: {r['text']}" for r in bad)[:400],
                  "maxxing deps update (re-installs the pinned, checked versions) - or chown -R root:root on them")
    late = [r for r in rows if r["state"] in ("missing", "outdated")]
    if late:
        return _c("deps_files", WARN, f"{len(late)} external component(s) not at the version of this release",
                  ", ".join(f"{r['name']} {r['installed'] or 'missing'} (expected {r['expected'] or '-'})" for r in late),
                  "maxxing deps update")
    return _c("deps_files", OK, f"{sum(r['state'] == 'ok' for r in rows)} external components verified",
              "maxxing deps list")


def _run_ok(cmd: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return False, ""


def check_security() -> Check:
    """Firewall (ufw), fail2ban, automatic security updates: set by the installer; warning only."""
    missing = []
    in_container = _run_ok(["systemd-detect-virt", "-cq"])[0]
    if not in_container:
        ok, out = _run_ok(["ufw", "status"])
        if not ok or "Status: active" not in out:
            missing.append("firewall")
    if not _run_ok(["systemctl", "is-active", "--quiet", "fail2ban"])[0]:
        missing.append("fail2ban")
    if not _run_ok(["systemctl", "is-enabled", "--quiet", "unattended-upgrades"])[0]:
        missing.append("security updates")
    if not missing:
        return _c("security", OK, "firewall, fail2ban and security updates active" if not in_container
                  else "fail2ban and security updates active (firewall: the container's host)")
    return _c("security", WARN, f"server hardening incomplete ({', '.join(missing)})", "",
              f"bash {config.CODE}/install.sh --secure")


def check_state_files() -> Check | None:
    """config.json / secrets.json found damaged: a copy was kept before they were rewritten."""
    copies = [c for c in (config.damaged_copy_of(config.config_path()), config.damaged_copy_of(config.secrets_path())) if c]
    if not copies:
        return None
    return _c("state_files", WARN, "a damaged settings file was replaced - its copy is kept",
              ", ".join(str(c) for c in copies),
              "compare with the current file, restore what is missing (keys: Settings -> Keys), then delete the copy")


def check_disk(cfg: dict) -> Check:
    p = Path(cfg.get("workspace") or "/")
    while not p.exists() and p != p.parent:
        p = p.parent
    du = shutil.disk_usage(p)
    free_gb, pct = du.free / 1e9, 100 * (du.total - du.free) / du.total
    lvl = FAIL if free_gb < 1 else WARN if (free_gb < 5 or pct > 90) else OK
    return _c("disk", lvl, f"disk {pct:.0f}% used, {free_gb:.1f} GB free", str(p),
              "" if lvl == OK else "free space: journalctl --vacuum-size=200M ; apt-get clean ; check ~/.claude/projects")


def check_workspace(cfg: dict) -> Check:
    ws = Path(cfg.get("workspace") or "")
    if not ws.is_dir():
        return _c("workspace", FAIL, f"workspace {ws} missing", "", "maxxing init")
    if not os.access(ws, os.W_OK):
        return _c("workspace", FAIL, f"workspace {ws} not writable", "", f"chown -R root: {ws}")
    if not (ws / "CLAUDE.md").is_file():
        return _c("workspace", WARN, f"workspace {ws} has no CLAUDE.md", "", "maxxing init")
    return _c("workspace", OK, f"workspace {ws}")


def check_skills() -> Check:
    st = skills_status()
    bad = [s["name"] + " (" + s["state"] + ")" for s in st if s["state"] != "ok"]
    if not st:
        return _c("skills", WARN, "no product skills found in the code", str(config.SKILLS_DIR))
    if bad:
        return _c("skills", WARN, f"{len(bad)} skill(s) not up to date", ", ".join(bad), "maxxing init")
    return _c("skills", OK, f"{len(st)} skills installed", str(skills_target()))


def check_web() -> Check:
    if (config.WEB_DIST / "index.html").is_file():
        return _c("web", OK, "web UI build present")
    return _c("web", FAIL, "web UI build missing", str(config.WEB_DIST), "maxxing update (web/dist is shipped in the repo)")


def check_git(fetch: bool = True) -> Check:
    if not (config.CODE / ".git").exists():
        return _c("git", INFO, "install is not a git clone", str(config.CODE))
    branch = _current_branch()
    if fetch:
        _fetch_quiet(branch)
    code, out = _git("rev-list", "--count", f"HEAD..origin/{branch}")
    behind = int(out.strip()) if code == 0 and out.strip().isdigit() else None
    from . import customs
    st = customs.summary(branch)
    n = len(st["customs"])
    detail = f"{config.CODE} ({branch})" + (f", {n} customization(s): see CUSTOMIZATIONS.md" if n else "")
    if st["rebase"]:
        return _c("git", WARN, "customizations are being adapted (rebase in progress)", detail,
                  "finish the rebase then: maxxing update --resume  (or: maxxing update --rollback)")
    p = st["pending"]
    if p:
        what = {"conflict": "customizations conflict with the new version",
                "health": "the last update did not start and was rolled back",
                "dependencies": "the last update failed (dependencies) and was rolled back"}.get(p.get("reason"), "update pending")
        return _c("git", WARN, f"update pending: {what}", detail,
                  f"open the topic {update_topic()} and say: update  (skill maxxing-customize)")
    if st["dirty"]:
        return _c("git", WARN, f"{len(st['dirty'])} unsaved change(s) in the code directory", detail,
                  'maxxing custom save "what it does" --why "why"  (skill maxxing-customize)')
    if behind:
        return _c("git", WARN, f"{behind} update(s) available", detail, "maxxing update")
    return _c("git", OK, ("up to date" if behind == 0 else "version check unavailable")
              + (f" ({n} customization(s))" if n else ""), detail)


def _fetch_quiet(branch: str) -> None:
    from . import license
    if license.enabled() or not valid_branch(branch):  # still on archives: nothing to fetch before the move to git
        return
    _git("fetch", "-q", "origin", "--", branch, timeout=20, token=config.get_secret(UPDATE_TOKEN) or None)


def check_update_signature() -> Check | None:
    if not config.load_config().get("update_verify_signature") or not (config.CODE / ".git").exists():
        return None
    from . import license
    if license.enabled():
        return None                                    # still on archives: checked once it has moved to git
    ref = f"origin/{_current_branch()}"
    target = _rev(ref) or _rev("HEAD")
    ok, detail = verify_target(target) if target else (False, "no commit")
    if ok:
        return _c("update_signature", OK, f"update signatures checked ({detail})")
    return _c("update_signature", WARN, f"update_verify_signature is on but {ref} is not signed by a trusted key",
              detail, "maxxing update will stop until it is: import the maintainer's key (gpg --import) or set "
                      "gpg.ssh.allowedSignersFile; or set update_verify_signature to false in config.json")


def check_license() -> Check:
    from . import license
    st = license.status()
    if not st["enabled"]:                              # no license needed (fair source): git or a local copy
        if update_source() == "git":
            return _c("license", INFO, "updates from the git repository (no license needed)")
        return _c("license", INFO, "no license needed (local copy: updates come from a newer copy)")
    # an install from before 2.0.0a87 (code of a signed archive): moves to the public git repository by itself
    if st.get("move_error"):
        return _c("license", INFO, f"moving to the public git repository: not yet - {st['move_error']}",
                  "tried again by itself every few hours", "maxxing update  (moves it first)")
    return _c("license", INFO, "moving to the public git repository (by itself, a few minutes after the start)",
              "", "maxxing update  (moves it now)")


def _password_set() -> bool:
    """= security.password_is_set(), without importing FastAPI (security does): keeps the CLI fast."""
    return bool(config.get_secret("password_hash"))


def check_setup() -> Check:
    if _password_set():
        return _c("setup", OK, "UI password set")
    return _c("setup", WARN, "first sign-in not done yet", "", "maxxing setup-link  (open the printed link)")


def collect_checks(live: bool = False, fetch: bool = True, deps: bool = False) -> list[Check]:
    cfg = config.load_config()
    steps: list[Callable[[], Check | None]] = [
        check_python, check_uv, check_claude_cli, lambda: check_claude_version(fetch), lambda: check_claude_auth(live),
        lambda: check_skill_listing(cfg), check_setup,
        check_service, check_hardening, lambda: check_caddy_site(cfg), check_infra_paths, lambda: check_bind(cfg), lambda: check_http(cfg), lambda: check_public_url(cfg),
        lambda: check_caddy(cfg), check_crontab, lambda: check_timezone(cfg), lambda: check_telegram(cfg), lambda: check_backup(cfg), check_voice, check_tools, check_managed_deps, check_security, check_state_files,
        lambda: check_disk(cfg), check_memory, lambda: check_workspace(cfg), check_skills, check_web,
        check_license, lambda: check_git(fetch), check_update_signature,
    ] + ([check_deps] if deps else [])
    out = []
    for fn in steps:
        try:
            c = fn()
        except Exception as e:  # noqa: BLE001 - a crashing check is reported, never fatal
            c = _c(getattr(fn, "__name__", "check"), WARN, "check failed to run", repr(e))
        if c:
            out.append(c)
    return out


def cmd_doctor(a) -> int:
    checks = collect_checks(live=a.live, fetch=not a.offline, deps=getattr(a, "deps", False))
    ok = not any(c["level"] == FAIL for c in checks)
    if a.json:
        print(json.dumps({"ok": ok, "version": __version__, "state": str(config.STATE),
                          "checks": checks}, indent=2))
        return 0 if ok else 1
    print(f"Harness Maxxing {__version__} - doctor")
    for c in checks:
        line(c["level"], c["title"] + (f"  ({c['detail']})" if c["detail"] and c["level"] == OK else ""),
             "" if c["level"] == OK else "; ".join(x for x in (c["detail"], c["fix"]) if x))
    n_fail = sum(c["level"] == FAIL for c in checks)
    n_warn = sum(c["level"] == WARN for c in checks)
    print(f"\n{'All good.' if ok and not n_warn else f'{n_fail} problem(s), {n_warn} warning(s).'}")
    return 0 if ok else 1


def _cfg_doctor(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--live", action="store_true", help="also make a real one-line Claude call")
    p.add_argument("--offline", action="store_true", help="do not contact GitHub / npm for updates")
    p.add_argument("--deps", action="store_true", help="also look up known vulnerabilities of the installed "
                                                       "packages (osv.dev)")


# ---- update --------------------------------------------------------------------------------
UPGRADE_DIR = "docs/upgrade"
_VER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-.]?(a|alpha|b|beta|rc)\.?(\d+))?$")


def version_key(v: str) -> tuple | None:
    """Sortable key of '2.0.0', '2.0.0a2', '2.0.0-alpha.2', '2.0.0rc1' (None if not a version)."""
    m = _VER_RE.match(v.strip())
    if not m:
        return None
    pre = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2}.get(m.group(4) or "", 3)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), pre, int(m.group(5) or 0))


def upgrade_notes(old: str, new: str, root: Path | None = None) -> list[Path]:
    """docs/upgrade/<version>.md with old < version <= new, in version order."""
    d = (root or config.CODE) / UPGRADE_DIR
    lo, hi = version_key(old), version_key(new)
    if not d.is_dir() or hi is None:
        return []
    out = []
    for f in d.glob("*.md"):
        k = version_key(f.stem)
        if k is not None and (lo is None or k > lo) and k <= hi:
            out.append((k, f))
    return [f for _, f in sorted(out)]


def _version_in(text: str) -> str | None:
    m = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", text or "")
    return m.group(1) if m else None


def changelog_since(old: str, new: str) -> list[str]:
    code, out = _git("diff", "--unified=0", f"{old}..{new}", "--", "CHANGELOG.md")
    if code != 0:
        return []
    from .changelog import strip_show
    return [strip_show(ln[1:]) for ln in out.splitlines() if ln.startswith("+") and not ln.startswith("+++")]


_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def valid_branch(branch: str) -> bool:
    """The branch names install.sh accepts: never an option of git (`--upload-pack=…` runs a command)."""
    return (bool(_BRANCH_RE.match(branch)) and not branch.startswith(("-", "/")) and not branch.endswith("/")
            and ".." not in branch and "//" not in branch)


def _fetch(branch: str) -> tuple[bool, str]:
    from . import license
    if not valid_branch(branch):
        return False, f"invalid branch name: {branch[:80]!r}"
    if license.enabled():                              # pre-a87 install still on archives: git once it has moved
        err = (license.status().get("move_error") or "").strip()
        return False, ("this server still runs the code of a signed archive and has not moved to the public git "
                       "repository yet" + (f": {err}" if err else "") + " - `maxxing update` moves it first")
    token = config.get_secret(UPDATE_TOKEN) or None
    code, out = _git("fetch", "-q", "origin", "--", branch, timeout=120, token=token)
    if code != 0:
        return False, out.strip()[-300:] + (
            "" if token else " | private repo? store a read token: "
            "printf %s TOKEN | maxxing init --quiet --secret-from-stdin github_update_token")
    return True, ""


def update_source() -> str | None:
    """Where updates come from: "git" (a clone with an `origin` remote), "license" (an install from before 2.0.0a87,
    still on the code of a signed archive: it moves to git first) or None (no check can ever succeed)."""
    from . import license
    if license.enabled():
        return "license"
    if (config.CODE / ".git").exists() and _git("remote", "get-url", "origin")[0] == 0:
        return "git"
    return None


def check_update(branch: str | None = None) -> dict:
    """Fetch and compare without touching the code -> {ok, error?, current, latest, behind,
    available, commit, latest_commit, changelog:[lines], branch}."""
    if not (config.CODE / ".git").exists():
        return {"ok": True, "available": False, "git": False, "current": __version__, "latest": None,
                "behind": None, "changelog": [], "message": f"{config.CODE} is not a git clone"}
    if update_source() is None:
        return {"ok": True, "available": False, "git": False, "current": __version__, "latest": None,
                "behind": None, "changelog": [], "message": "no git remote",
                "hint": "git -C <code dir> remote add origin https://github.com/makushingu/harness-maxxing.git"}
    branch = branch or _current_branch()
    ok, err = _fetch(branch)
    if not ok:
        return {"ok": False, "error": err, "current": __version__}
    remote = f"origin/{branch}"
    _, head = _git("rev-parse", "HEAD")
    code, rhead = _git("rev-parse", remote)
    if code != 0:
        return {"ok": False, "error": f"branch {branch} not found on origin", "current": __version__}
    code, cnt = _git("rev-list", "--count", f"HEAD..{remote}")
    behind = int(cnt.strip()) if code == 0 and cnt.strip().isdigit() else 0
    try:                                              # the code on disk (not the HEAD commit, nor this process)
        local_src = (config.CODE / "server" / "maxxing" / "__init__.py").read_text()
    except OSError:
        local_src = ""
    code, remote_src = _git("show", f"{remote}:server/maxxing/__init__.py")
    current = _version_in(local_src) or __version__
    latest = (_version_in(remote_src) if code == 0 else None) or current
    from . import customs
    return {"ok": True, "git": True, "branch": branch, "current": current, "latest": latest,
            "behind": behind, "available": behind > 0, "commit": head.strip()[:12],
            "latest_commit": rhead.strip()[:12],
            "changelog": changelog_since("HEAD", remote) if behind else [],
            "customs": [{"id": c["id"], "title": c["title"]} for c in customs.list_customs(branch)],
            "pending": customs.pending()}


def notify_update(info: dict) -> bool:
    """Telegram message (Crons thread) about an available update; no-op when not configured."""
    from . import feed
    feed.system(f"Update available: {info['latest']}", f"Installed: {info['current']}. Open the topic {update_topic()} "
                "and say: update.", "info", "system", f"/sessions?path=projects/{update_topic().replace('/', '/topics/')}",
                dedupe=f"update-{info['latest']}")
    url = (config.load_config().get("public_url") or "").rstrip("/")
    text = (f"Harness Maxxing {info['latest']} is available (installed: {info['current']}, "
            f"{info['behind']} new commit(s)).\nOpen the topic {update_topic()}"
            + (f" ({url}/sessions)" if url else "") + " and say: update")
    try:
        from .telegram import gateway
        gateway.notify_cron(text)
        return True
    except Exception:  # noqa: BLE001 - never fail the check because of Telegram
        return False


def cmd_update_check(a) -> int:
    info = check_update(a.branch)
    if a.notify and info.get("ok") and info.get("available"):
        info["notified"] = notify_update(info)
    if a.json:
        print(json.dumps(info, indent=2))
        return 0 if info.get("ok") else 1
    print(f"Harness Maxxing {__version__} - update check")
    if not info.get("ok"):
        line(FAIL, "cannot check for updates", info.get("error", ""))
        return 1
    if not info.get("git"):
        line(INFO, f"updates unavailable ({info['message']})", info.get("hint") or "re-run install.sh to get a git install")
        return 0
    line(OK, f"installed  {info['current']} ({info['commit'][:8]}, branch {info['branch']})")
    if not info["available"]:
        line(OK, "up to date")
        return 0
    line(WARN, f"available  {info['latest']} ({info['behind']} new commit(s), {info['latest_commit'][:8]})",
         f"maxxing update  (or open the topic {update_topic()} and say: update)")
    if info.get("customs"):
        line(INFO, f"{len(info['customs'])} customization(s) will be carried over: "
             + "; ".join(c["title"] for c in info["customs"]), "see CUSTOMIZATIONS.md in the workspace")
    if info["changelog"]:
        print("\nWhat's new:")
        for n in info["changelog"]:
            print("  " + n)
    if a.notify:
        line(OK if info.get("notified") else INFO,
             "Telegram notified" if info.get("notified") else "Telegram not notified")
    return 0


def _rev(ref: str) -> str:
    code, out = _git("rev-parse", "--verify", "-q", ref)
    return out.strip() if code == 0 else ""


def _sync_deps() -> tuple[bool, str]:
    uv = uv_bin()
    if not uv:
        return False, f"uv not found - bash {config.CODE}/install.sh installs it (pinned, checksum-verified)"
    from .voice import sync_extras                    # keep the optional voice dependencies once installed
    env = {**os.environ, "UV_PYTHON_INSTALL_DIR": str(config.STATE / "tools" / "python")}
    code, out = run([uv, "sync", "--frozen", "--no-dev", "--quiet", *sync_extras()], cwd=config.CODE / "server",
                    timeout=600, env=env)
    return code == 0, out.strip()[-500:]


def _healthy(version: str, wait: float = 45) -> bool:
    """The restarted service answers /api/auth/state with the expected version."""
    cfg = config.load_config()
    host = cfg.get("bind") or "127.0.0.1"
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{cfg.get('port') or 8787}/api/auth/state"
    deadline = time.time() + wait
    while time.time() < deadline:
        status, body = http_get(url, timeout=3)
        if status == 200:
            try:
                if json.loads(body).get("version") == version:
                    return True
            except ValueError:
                pass
        time.sleep(1)
    return False


_UPDATE_CTX: dict = {}        # branch + web stash of the running `maxxing update` (put back on a rollback)
PRE_UPDATE_BRANCH = "update/pre-update-branch.json"   # branch that ran at refs/maxxing/pre-update ("" = detached)


def _start_branch() -> str:
    """The branch checked out now, "" on a detached HEAD (a branch under test)."""
    b = _current_branch()
    return "" if b == "HEAD" else b


def _record_start(old: str, start: str) -> None:
    config.write_json(config.STATE / PRE_UPDATE_BRANCH, {"commit": old, "branch": start})


def _recorded_start(old: str) -> str | None:
    """Branch recorded with the rollback point `old` ("" = detached), None when unknown (older version)."""
    try:
        d = json.loads((config.STATE / PRE_UPDATE_BRANCH).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("commit") != old or not isinstance(d.get("branch"), str):
        return None
    return d["branch"]


def _goto_start(start: str | None, old: str) -> None:
    """Check out what ran before (`start` branch, or `old` detached) WITHOUT moving another branch: a reset --hard
    on the branch an update switched to would rewrite it (and a detached start would rewrite main)."""
    from . import customs
    if start == "":
        customs.git("checkout", "-q", "-f", "--detach", old)
    elif start and start != _current_branch():
        customs.git("checkout", "-q", "-f", start)


def _back_to(old: str) -> str:
    """The code directory as it was before the update: the branch it was on, its commit, the uncommitted changes
    (auto-saved on the new branch after a `--branch` switch: carried back as the same customization), the web/ edits
    set aside. -> the commit it ends on (the rollback point, moved when the auto-save was carried back)."""
    from . import customs
    _goto_start(_UPDATE_CTX.get("branch"), old)
    customs.git("reset", "-q", "--hard", old)
    saved = _UPDATE_CTX.pop("saved", None)
    if saved:
        branch, sha = saved
        customs.ensure_identity()
        code, out = customs.git("cherry-pick", "--allow-empty", sha)
        if code == 0:
            old = _rev("HEAD")
            _git("update-ref", customs.PRE_UPDATE_REF, old)
            _record_start(old, _UPDATE_CTX["branch"])
        else:
            customs.git("cherry-pick", "--abort")
            line(WARN, f"the uncommitted changes saved by the update could not be put back - they stay on branch "
                       f"{branch}", f"git -C {config.CODE} show {sha[:8]}")
    _unstash_web()
    return old


def _unstash_web() -> None:
    """The edits of web/ set aside by this update go back in place (or the way to get them back is printed)."""
    from . import customs
    if _UPDATE_CTX.pop("stashed", False):
        code, out = customs.git("stash", "pop", "-q")
        if code != 0:
            line(WARN, "the edits of the web UI set aside could not be put back - they stay in the git stash",
                 f"git -C {config.CODE} stash list  (then: git stash pop)")


def _rollback(old: str, reason: str, restart: bool, **info) -> None:
    """Back to the code that was running before the update (customizations included)."""
    from . import customs
    old = _back_to(old)
    _sync_deps()
    if restart:
        systemctl("restart", SERVICE, timeout=60)
    customs.set_pending(reason=reason, **{"from": old}, **info)
    line(WARN, f"rolled back to {old[:8]} - the previous version keeps running")


def _notify(text: str) -> None:
    from . import feed
    feed.system("Update needs attention", text, "warning", "system", f"/sessions?path=projects/{update_topic().replace('/', '/topics/')}")
    try:
        from .telegram import gateway
        gateway.notify_cron(text)
    except Exception:  # noqa: BLE001 - Telegram is optional
        pass


def cmd_update(a) -> int:
    """Careful update: customizations (local commits) are rebased onto the new version; on a
    conflict nothing changes and Claude adapts them (topic system/harness); a release that does not
    start is rolled back."""
    from . import customs
    if a.check:
        return cmd_update_check(a)
    if a.preflight:
        return cmd_update_preflight(a)
    if a.verify:
        return cmd_update_verify(a)
    if a.notify or a.json:
        print("--notify and --json only apply to --check", file=sys.stderr)
        return 2
    print(f"Harness Maxxing {__version__} - update")
    if not (config.CODE / ".git").exists():
        line(FAIL, f"{config.CODE} is not a git clone - re-run install.sh")
        return 1
    if a.rollback:
        return _update_rollback(a)
    if a.resume:
        if customs.rebase_in_progress() or customs.conflicts():
            line(FAIL, "the rebase is not finished", f"git -C {config.CODE} status  (then: git add <files> && "
                 f"git rebase --continue, or git rebase --abort)")
            return 1
        old = (customs.pending() or {}).get("from") or _rev(customs.PRE_UPDATE_REF) or _rev("HEAD")
        _UPDATE_CTX.clear()
        start = _recorded_start(old)
        if start is not None:                          # a failed resume goes back to the branch that ran
            _UPDATE_CTX["branch"] = start
        line(OK, f"resuming the update from {old[:8]} ({len(customs.list_customs())} customization(s))")
        return _update_finish(a, old)
    if customs.rebase_in_progress():
        line(FAIL, "a rebase is in progress in the code directory (customizations being adapted)",
             "finish it then run: maxxing update --resume   (or abandon: git -C "
             f"{config.CODE} rebase --abort)")
        return 1
    from . import license
    if license.enabled():                              # fair source: an install still on archives moves to git first
        dirty = [f for f in customs.dirty_files() if not f.startswith("web/")]
        if dirty:                                      # the move needs a clean tree: keep them as a customization
            try:
                it = customs.save("Unsaved changes found by the update",
                                  why=f"auto-saved by maxxing update ({', '.join(dirty[:5])}) - "
                                      f"give it a real title and reason (topic {update_topic()})")
                line(WARN, f"{len(dirty)} uncommitted change(s) saved as customization {it['id']}",
                     "Claude: rename it with the real purpose (skill maxxing-customize)")
            except customs.CustomError as e:
                line(FAIL, "uncommitted changes in the code directory cannot be kept", str(e))
                return 1
        r = license.try_move_to_git()
        if r.get("moved"):
            line(OK, f"this server now updates from {license.GIT_URL} (branch {r['branch']}, "
                     f"{r.get('version') or '?'}), customizations kept")
        else:
            line(FAIL, "this server still runs the code of a signed archive and could not move to the public git "
                       f"repository yet: {r.get('error') or '?'}", "fix what is said, then: maxxing update")
            return 1
    branch = a.branch or _current_branch()
    old = _rev("HEAD")                                 # what runs now: a rollback goes back here, on this branch
    _UPDATE_CTX.clear()
    _UPDATE_CTX["branch"] = _start_branch()
    switched = branch != _current_branch()
    ok, err = _fetch(branch)
    if not ok:
        line(FAIL, "git fetch failed", err)
        return 1
    if branch != _current_branch():
        carried = customs.list_customs() if switched else []     # the customizations live on the branch left
        code, out = _git("checkout", "-q", branch)
        if code != 0:
            code, out = _git("checkout", "-q", "-b", branch, "--track", f"origin/{branch}")
        if code != 0:
            line(FAIL, f"cannot switch to branch {branch}", out.strip()[-300:])
            return 1
        have = {c["id"] for c in customs.list_customs(branch)}
        todo = [c for c in carried if c["id"] not in have]
        if todo:                                       # replayed here, then rebased like any customization below
            customs.ensure_identity()
            for c in todo:
                code, out = customs.git("cherry-pick", "--allow-empty", c["commit"])
                if code != 0:
                    customs.git("cherry-pick", "--abort")
                    _back_to(old)
                    line(FAIL, f"customization \"{c['title']}\" cannot be carried to branch {branch}"
                         f" - nothing changed, {__version__} keeps running", out.strip()[-300:])
                    print(f"\nFor Claude (topic {update_topic()}, skill maxxing-customize): adapt it on {branch}"
                          f"\n  cd {config.CODE} && git checkout {branch} && git cherry-pick {c['commit'][:12]}"
                          "\n  # resolve, git add, GIT_EDITOR=true git cherry-pick --continue, then: maxxing update")
                    return 3
            line(OK, f"{len(todo)} customization(s) carried to branch {branch}")
    target = _rev(f"origin/{branch}")
    if config.load_config().get("update_verify_signature") and target and target != old:
        ok, detail = verify_target(target)
        if not ok:
            line(FAIL, f"update stopped: {target[:8]} has no valid signature (update_verify_signature is on)"
                 f" - nothing changed, {__version__} keeps running",
                 f"{detail} | check: git -C {config.CODE} verify-commit {target[:8]} ; import the maintainer's "
                 "key (gpg --import) or set gpg.ssh.allowedSignersFile ; or turn the check off: "
                 "update_verify_signature false in config.json")
            _notify(f"Harness Maxxing update stopped: the new version {target[:8]} is not signed by a trusted "
                    "key (update_verify_signature). Nothing changed.")
            return 1
        line(OK, detail)
    web = [f for f in customs.dirty_files() if f.startswith("web/")]
    if web:                                            # the pre-built UI cannot be a customization: kept aside
        code, out = customs.git("stash", "push", "-u", "-q", "-m",
                                f"maxxing update {time.strftime('%Y-%m-%d %H:%M')}: edits of the web UI", "--", "web/")
        if code != 0:
            line(FAIL, "edits of the pre-built web UI cannot be set aside", out.strip()[-300:])
            return 1
        _UPDATE_CTX["stashed"] = True
        line(WARN, f"{len(web)} edit(s) of the pre-built web UI set aside (git stash) - they cannot be carried over",
             f"Claude: rebuild what they did as an extension (git -C {config.CODE} stash show -p stash@{{0}})")
    dirty = customs.dirty_files()
    if dirty:                                          # never lose a change made in the code directory
        try:
            it = customs.save("Unsaved changes found by the update",
                              why=f"auto-saved by maxxing update ({', '.join(dirty[:5])}) - "
                                  f"give it a real title and reason (topic {update_topic()})")
            line(WARN, f"{len(dirty)} uncommitted change(s) saved as customization {it['id']}",
                 "Claude: rename it with the real purpose (skill maxxing-customize)")
        except customs.CustomError as e:
            line(FAIL, "uncommitted changes in the code directory cannot be kept", str(e))
            _unstash_web()
            return 1
        if not switched:                               # (after a branch switch the save sits on the new branch)
            old = _rev("HEAD")
        else:
            _UPDATE_CTX["saved"] = (branch, _rev("HEAD"))
    _git("update-ref", customs.PRE_UPDATE_REF, old)
    _record_start(old, _UPDATE_CTX["branch"])
    mine = customs.list_customs(branch)
    if old == target or (not mine and _rev("HEAD") == target):
        line(OK, f"code already up to date ({old[:8]})")
    elif not mine:
        code, out = _git("merge", "--ff-only", "-q", f"origin/{branch}")
        if code != 0:
            line(FAIL, "cannot fast-forward", out.strip()[-300:] + f" | inspect: git -C {config.CODE} status")
            return 1
    else:
        customs.ensure_identity()
        code, out = customs.git("rebase", "-q", f"origin/{branch}", timeout=300)
        if code != 0:
            files = customs.conflicts()
            customs.git("rebase", "--abort")
            web_back = bool(_UPDATE_CTX.get("stashed"))
            old = _back_to(old)
            _, remote_src = _git("show", f"origin/{branch}:server/maxxing/__init__.py")
            info = customs.set_pending(reason="conflict", **{"from": old}, target=target,
                                       target_version=_version_in(remote_src) or "",
                                       customs=[c["title"] for c in mine], conflicts=files)
            line(FAIL, f"your customizations conflict with the new version {info['target_version'] or target[:8]}"
                 f" - nothing changed, {__version__} keeps running",
                 "conflicting files: " + (", ".join(files) or "?"))
            print(f"\nFor Claude (topic {update_topic()}, skill maxxing-customize):"
                  f"\n  cd {config.CODE} && "
                  + ('git stash push -u -q -m "maxxing update: edits of the web UI" -- web/ && ' if web_back else "")
                  + (f"git checkout {branch} && " if switched else "") + f"git rebase origin/{branch}"
                  "\n  # adapt each conflicting file so the customization still does what CUSTOMIZATIONS.md says"
                  "\n  git add <files> && GIT_EDITOR=true git rebase --continue      # repeat until done"
                  "\n  maxxing update --resume")
            _notify(f"Harness Maxxing {info['target_version'] or 'update'}: your customizations need to be adapted "
                    f"before updating (nothing changed). Open the topic {update_topic()} and say: update")
            return 3
        line(OK, f"{len(mine)} customization(s) carried over onto the new version")
    return _update_finish(a, old)


def verify_target(target: str) -> tuple[bool, str]:
    """Config `update_verify_signature`: the commit to install must carry a valid signature (`git verify-commit`),
    or a tag pointing at it must (`git verify-tag`). Trust = the keys git knows (gpg keyring, or
    gpg.ssh.allowedSignersFile for SSH signatures). -> (ok, detail)."""
    code, out = _git("verify-commit", target, timeout=30)
    if code == 0:
        return True, f"commit {target[:8]} signature verified"
    detail = out.strip()[-300:]
    _, tags = _git("tag", "--points-at", target)
    for tag in tags.split():
        tcode, tout = _git("verify-tag", tag, timeout=30)
        if tcode == 0:
            return True, f"tag {tag} signature verified"
        detail = tout.strip()[-300:] or detail
    return False, detail or "no signature"


def _update_finish(a, old: str) -> int:
    from . import customs
    new = _rev("HEAD")
    line(OK, f"code {old[:8]} -> {new[:8]}" if old != new else f"code {new[:8]}")
    ok, err = _sync_deps()
    if not ok:
        line(FAIL, "dependency sync failed", err)
        _rollback(old, "dependencies", restart=False, target=new, error=err[-300:])
        return 4
    line(OK, "dependencies synced")
    # run the NEW code's init (this process still has the old modules loaded)
    code, out = run([sys.executable, "-m", "maxxing", "init", "--quiet"], cwd=config.CODE / "server", timeout=300)
    line(OK if code == 0 else WARN, "workspace templates and skills refreshed" if code == 0 else "init reported a problem",
         "" if code == 0 else out.strip()[-300:])
    _deps_core_update()
    try:
        new_version = _version_in((config.CODE / "server" / "maxxing" / "__init__.py").read_text()) or __version__
    except OSError:
        new_version = __version__
    if old != new:
        notes = changelog_since(old, new)
        if notes:
            print("\nWhat's new:")
            for n in notes:
                print("  " + n)
        ups = upgrade_notes(__version__, new_version)
        if ups:
            print(f"\nWorkspace upgrade notes {__version__} -> {new_version} (for Claude, topic {update_topic()}):")
            for f in ups:
                print(f"  {f}")
    if customs.list_customs():
        customs.export()
        line(OK, f"customizations recorded in {customs._workspace() / customs.REGISTRY}")
    if a.no_restart:
        customs.clear_pending()
        _mark_updated(new_version, a)                  # checked when the server next starts
        return 0
    code, out = systemctl("is-enabled", SERVICE, timeout=10)
    if code == 127 or not UNIT_PATH.exists():
        line(INFO, "service not installed - restart `maxxing serve` yourself")
        customs.clear_pending()
        _mark_updated(new_version, a)
        return 0
    code, out = systemctl("restart", SERVICE, timeout=60)
    if code != 0 or not _healthy(new_version):
        line(FAIL, "the new version does not start" if code == 0 else "restart failed", out.strip()[-300:])
        _rollback(old, "health", restart=True, target=new, target_version=new_version)
        _notify(f"Harness Maxxing {new_version} did not start and was rolled back - nothing lost. "
                f"Open the topic {update_topic()} and say: update")
        return 4
    line(OK, f"service {SERVICE} restarted ({new_version} answers)")
    customs.clear_pending()
    _mark_updated(new_version, a)
    _deps_background_update()
    return 0


def _deps_core_update() -> None:
    """Before the restart, with the NEW code: uv and the managed Python of deps.toml (the venv moves onto it when it
    used ~/.local). Never fails the update: a problem is reported and the old ones stay."""
    if os.environ.get("MAXXING_SPAWN") == "direct" or not (config.CODE / "server" / "maxxing" / "deps.toml").exists():
        return
    code, out = run([sys.executable, "-m", "maxxing", "deps", "update", "uv", "python", "--auto", "--quiet"],
                    cwd=config.CODE / "server", timeout=1200)
    line(OK if code == 0 else WARN, "uv and Python at the pinned versions" if code == 0 else "uv / Python not updated",
         "" if code == 0 else out.strip()[-300:])


def _deps_background_update() -> None:
    """After a healthy restart: the other components of deps.toml move to this release's versions in a background
    unit (downloads can take minutes; each is checked, installed next to the old one, then switched)."""
    if os.environ.get("MAXXING_SPAWN") == "direct" or not Path("/run/systemd/system").is_dir():
        line(INFO, "external components: run `maxxing deps update` to move them to this release's versions")
        return
    log = config.STATE / "logs" / "deps-update.log"
    code, out = run(["systemd-run", "--quiet", "--collect", "--unit", f"maxxing-deps-update-{int(time.time())}",
                     "-p", "MemoryMax=2G", "-p", f"StandardOutput=append:{log}", "-p", f"StandardError=append:{log}",
                     "-E", f"MAXXING_STATE={config.STATE}", "-E", f"HOME={home()}",
                     str(BIN_LINK if BIN_LINK.exists() else sys.executable), *([] if BIN_LINK.exists() else ["-m", "maxxing"]),
                     "deps", "update", "--notify"], timeout=30)
    line(OK if code == 0 else WARN, "external components update in the background" if code == 0
         else "could not start the background update of the components", f"log: {log}" if code == 0 else out[-200:])


def _mark_updated(new_version: str, a) -> None:
    """The restarted server verifies extensions and customizations (and, for the Update button, opens the
    upgrade-notes session) - see smartupdate.after_update."""
    from . import smartupdate
    try:
        smartupdate.mark_updated(__version__, new_version, smart=bool(getattr(a, "smart", False)))
    except Exception:  # noqa: BLE001 - never fail an update for this
        pass


def cmd_update_preflight(a) -> int:
    from . import smartupdate
    rep = smartupdate.preflight(a.branch)
    if a.json:
        print(json.dumps(rep, indent=2, default=str))
        return 0 if rep.get("ok") else 1
    print(f"Harness Maxxing {__version__} - update preflight (nothing is changed)")
    if not rep.get("ok"):
        line(FAIL, "cannot check", rep.get("error", ""))
        return 1
    if rep["verdict"] == "up_to_date":
        line(OK, "up to date")
    else:
        line(OK, f"{rep['current']} -> {rep['latest']} ({rep['behind']} new commit(s))")
    labels = {"ok": (OK, "carries over"), "review": (WARN, "carries over, on code that changed - verified after"),
              "included": (INFO, "now included in the new version - can be dropped"),
              "conflict": (FAIL, "conflicts - must be adapted"), "unknown": (WARN, "could not be checked")}
    for c in rep.get("customs", []):
        lvl, txt = labels.get(c["status"], (INFO, c["status"]))
        line(lvl, f"customization {c['id']} \"{c['title']}\": {txt}", ", ".join(c.get("conflicts") or c.get("overlap") or []))
    if rep.get("unsaved"):
        line(WARN if rep.get("unsaved_overlap") else INFO, f"{len(rep['unsaved'])} unsaved change(s): saved as a "
             "customization by the update", ", ".join(rep["unsaved"][:6]))
    if rep.get("web_changes"):
        line(WARN, f"{len(rep['web_changes'])} edit(s) of the pre-built web UI: set aside by the update "
             "(rebuild them as an extension)", ", ".join(rep["web_changes"][:4]))
    for e in rep.get("extensions", []):
        line(FAIL, f"extension {e['id']}: {e['reason']}")
    for n in rep.get("notes", []):
        line(INFO, f"upgrade note {n['version']}: Harness applies it after the update")
    if rep["verdict"] == "simple":
        line(OK, "verdict: simple - `maxxing update` (or the Update button) does it all")
    elif rep["verdict"] == "adapt":
        line(WARN, "verdict: some changes need adapting first",
             f"Settings -> System -> Update with Harness, or the topic {update_topic()}: say \"update\"")
    return 0


def cmd_update_verify(a) -> int:
    from . import smartupdate
    rep = smartupdate.verify()
    if a.json:
        print(json.dumps(rep, indent=2, default=str))
        return 0 if rep["ok"] else 1
    print(f"Harness Maxxing {__version__} - verification")
    for x in rep["extensions"]:
        if x.get("skipped"):
            line(INFO, f"extension {x['id']}: turned off")
        else:
            line(OK if x["ok"] else FAIL, f"extension {x['id']} ({x['type']})", x["error"])
    for x in rep["checks"]:
        line(OK if x["ok"] else FAIL, f"customization {x['id']} \"{x['title']}\": {x['check']}", "" if x["ok"] else x["output"])
    if not rep["checks"]:
        line(INFO, "no customization check recorded", "maxxing custom check ID \"COMMAND\"")
    line(OK if rep["ok"] else FAIL, "everything works" if rep["ok"] else f"{rep['problems']} problem(s)")
    return 0 if rep["ok"] else 1


def _update_rollback(a) -> int:
    from . import customs
    old = _rev(customs.PRE_UPDATE_REF)
    if not old:
        line(FAIL, "no previous version recorded (rollback is available after an update)")
        return 1
    if customs.rebase_in_progress():
        customs.git("rebase", "--abort")
    dirty = customs.dirty_files()
    if dirty:                                          # a reset --hard would destroy them
        line(FAIL, f"{len(dirty)} uncommitted change(s) in {config.CODE} - nothing changed",
             f"put them aside (git -C {config.CODE} stash push -u -m \"before rollback\"), run the rollback again, "
             "then put them back (git stash pop) - a customization saved now would be undone by the rollback: "
             + ", ".join(dirty[:5]))
        return 1
    start = _recorded_start(old)                       # after `--branch X`: back on the branch that ran, X untouched
    _goto_start(start, old)
    customs.git("reset", "-q", "--hard", old)
    ok, err = _sync_deps()
    line(OK if ok else FAIL, f"code back to {old[:8]}" + (f" (branch {start})" if start else ""), "" if ok else err)
    customs.clear_pending()
    if not a.no_restart and UNIT_PATH.exists():
        code, out = systemctl("restart", SERVICE, timeout=60)
        line(OK if code == 0 else FAIL, f"service {SERVICE} restarted" if code == 0 else "restart failed", out.strip())
        return 0 if code == 0 else 1
    return 0 if ok else 1


def _cfg_update(p: argparse.ArgumentParser) -> None:
    p.add_argument("--branch", help="switch to / follow this branch")
    p.add_argument("--check", action="store_true",
                   help="only check: installed vs latest version and the changelog in between (changes nothing)")
    p.add_argument("--notify", action="store_true",
                   help="with --check: send a Telegram message when an update is available")
    p.add_argument("--json", action="store_true", help="with --check: machine-readable output")
    p.add_argument("--no-restart", action="store_true", help="do not restart the service")
    p.add_argument("--resume", action="store_true",
                   help="finish an update after the customizations were adapted (rebase completed by hand)")
    p.add_argument("--rollback", action="store_true", help="go back to the code that ran before the last update")
    p.add_argument("--preflight", action="store_true",
                   help="simulate the update on a throw-away copy: what carries over, conflicts, is now included "
                        "(changes nothing; with --json: machine-readable)")
    p.add_argument("--verify", action="store_true",
                   help="check that every extension loads and every customization check passes")
    p.add_argument("--smart", action="store_true",
                   help="update started from the UI: afterwards the server applies the upgrade notes in a session")


# ---- status --------------------------------------------------------------------------------
def collect_status() -> dict:
    cfg = config.load_config()
    code, out = systemctl("is-active", SERVICE, timeout=10)
    method, _ = claude_auth()
    tg = check_telegram(cfg)
    return {
        "version": __version__,
        "url": cli._base(cfg),
        "service": out.strip() if code != 127 else "no systemd",
        "password_set": _password_set(),
        "claude_auth": method,
        "telegram": tg["title"],
        "backup": backup_info(cfg),
        "workspace": cfg["workspace"],
        "state": str(config.STATE),
        "code": str(config.CODE),
    }


def cmd_status(a) -> int:
    s = collect_status()
    if a.json:
        print(json.dumps(s, indent=2))
        return 0
    b = s["backup"]
    rows = [
        ("Version", s["version"]),
        ("URL", s["url"] + ("" if s["password_set"] else "   (setup not done: maxxing setup-link)")),
        ("Service", s["service"]),
        ("Claude", s["claude_auth"] or "not signed in"),
        ("Telegram", s["telegram"]),
        ("Backup", (f"{b['repo']}" + (f", {b['age_h']:.0f} h ago" if b["age_h"] is not None else ", never ran"))
         if b["repo"] else "not configured"),
        ("Workspace", s["workspace"]),
        ("State", s["state"]),
        ("Code", s["code"]),
    ]
    for k, v in rows:
        print(f"{k:<10} {v}")
    return 0


def _cfg_status(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true")


# ---- uninstall -----------------------------------------------------------------------------
def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        with open("/dev/tty") as tty:
            print(f"{question} [y/N] ", end="", flush=True)
            return tty.readline().strip().lower() in ("y", "yes")
    except OSError:
        return False


def remove_crontab_block() -> str:
    """Remove the managed block (and stray `maxxing cron run` lines); other lines are kept."""
    crons = _optional("crons")
    begin = getattr(crons, "BLOCK_BEGIN", "# >>> claude-maxxing (managed) >>>")
    end = getattr(crons, "BLOCK_END", "# <<< claude-maxxing <<<")
    text = crons.read_crontab() if crons is not None else _crontab_text()
    if not text:
        return "no crontab"
    keep, inside, removed = [], False, 0
    for ln in text.splitlines():
        s = ln.strip()
        if s == begin:
            inside, removed = True, removed + 1
        elif inside:
            removed += 1
            inside = s != end
        elif "maxxing cron run" in ln:
            removed += 1
        else:
            keep.append(ln)
    if not removed:
        return "no managed crontab lines"
    while keep and not keep[-1].strip():
        keep.pop()
    new = "\n".join(keep) + "\n" if keep else ""
    if crons is not None and hasattr(crons, "write_crontab"):
        crons.write_crontab(new)
    elif os.environ.get("MAXXING_CRONTAB_FILE"):
        Path(os.environ["MAXXING_CRONTAB_FILE"]).write_text(new)
    else:
        run(["crontab", "-"], input=new, timeout=10)
    return f"{removed} managed crontab line(s) removed"


def remove_caddy_site() -> str:
    if not CADDY_SITE.exists() and not (CADDYFILE.exists() and str(CADDY_SITE) in CADDYFILE.read_text()):
        return "no Caddy site"
    if CADDYFILE.exists():
        lines = [ln for ln in CADDYFILE.read_text().splitlines() if str(CADDY_SITE) not in ln]
        CADDYFILE.write_text("\n".join(lines).strip("\n") + "\n" if any(x.strip() for x in lines) else "")
    CADDY_SITE.unlink(missing_ok=True)
    code, out = systemctl("is-active", "caddy", timeout=10)
    if out.strip() == "active":
        systemctl("reload", "caddy", timeout=30)
    return "Caddy site removed"


def _is_install_dir(p: Path) -> bool:
    p = p.resolve()
    return (p not in (Path("/"), home().resolve(), Path("/opt"), Path("/root"))
            and (p / "install.sh").is_file() and (p / "server" / "maxxing").is_dir())


def cmd_harden(a) -> int:
    """Write (or with --undo remove) the sandboxing drop-in, reload systemd and restart the service.
    If the service does not come back, the drop-in is removed again and the service restarted."""
    if not UNIT_PATH.exists():
        line(FAIL, f"service {SERVICE} not installed ({UNIT_PATH})")
        return 1
    p = hardening_path()
    before = p.read_text(errors="replace") if p.is_file() else None
    if a.undo:
        if before is None:
            line(OK, "service sandboxing not applied - nothing to remove")
            return 0
        p.unlink()
        line(OK, f"removed {p}")
    else:
        if before == HARDENING:
            line(OK, f"service sandboxing already applied ({p})")
            return 0
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(HARDENING)
        os.chmod(p, 0o644)
        line(OK, f"wrote {p}")
    code, out = systemctl("daemon-reload", timeout=60)
    if code != 0:
        line(FAIL, "systemctl daemon-reload failed", out.strip()[-300:])
        return 1
    if a.no_restart:
        line(INFO, f"takes effect at the next restart: systemctl restart {SERVICE}")
        return 0
    code, out = systemctl("restart", SERVICE, timeout=60)
    if code == 0 and _healthy(__version__):
        line(OK, f"service {SERVICE} restarted")
        return 0
    line(FAIL, "the service does not answer after the restart" if code == 0 else "restart failed",
         out.strip()[-300:])
    if before is None:
        p.unlink(missing_ok=True)
    else:
        p.write_text(before)
    systemctl("daemon-reload", timeout=60)
    systemctl("restart", SERVICE, timeout=60)
    line(WARN, "previous service settings restored", f"journalctl -u {SERVICE} -n 50 --no-pager")
    return 1


def _cfg_harden(p: argparse.ArgumentParser) -> None:
    p.add_argument("--undo", action="store_true", help="remove the sandboxing drop-in")
    p.add_argument("--no-restart", action="store_true", help="do not restart the service")


def cmd_uninstall(a) -> int:
    cfg = config.load_config()
    what = "service, Caddy site, crontab block, CLI link and product skills"
    if a.purge:
        what += f", the code ({config.CODE}) and the state ({config.STATE})"
    if a.purge_workspace:
        what += f", and THE WORKSPACE ({cfg['workspace']})"
    if not _confirm(f"Remove {what}?", a.yes):
        print("Aborted.")
        return 1
    print("Harness Maxxing - uninstall")
    try:
        changed = (config.STATE / "install-manifest").read_text().splitlines()
    except OSError:
        changed = []
    systemctl("disable", "--now", SERVICE, timeout=60)
    systemctl("stop", "maxxing-*", timeout=60)        # running turns (transient units)
    if service_memory_path().is_file():
        service_memory_path().unlink()
    if hardening_path().is_file():
        hardening_path().unlink()
        try:
            hardening_path().parent.rmdir()
        except OSError:
            pass
    if JOBS_SLICE_PATH.is_file():
        JOBS_SLICE_PATH.unlink()
    if UNIT_PATH.exists():
        UNIT_PATH.unlink()
        systemctl("daemon-reload")
    line(OK, f"service {SERVICE} removed")
    line(OK, remove_caddy_site())
    line(OK, remove_crontab_block())
    for n in _install_state().get("skills", []):
        d = skills_target() / n
        if d.is_dir() and not d.is_symlink():
            shutil.rmtree(d, ignore_errors=True)
    line(OK, "product skills removed")
    if BIN_LINK.is_symlink() or (BIN_LINK.is_file() and "claude-maxxing" in BIN_LINK.read_text(errors="ignore")):
        BIN_LINK.unlink()
        line(OK, f"{BIN_LINK} removed")
    _uninstall_components(changed, a.purge)
    if a.purge:
        if _is_install_dir(config.CODE):
            shutil.rmtree(config.CODE, ignore_errors=True)
            line(OK, f"code removed ({config.CODE})")
        else:
            line(WARN, f"{config.CODE} does not look like an install directory - kept")
        if config.STATE.is_dir() and config.STATE.resolve() != Path("/"):
            shutil.rmtree(config.STATE, ignore_errors=True)
            line(OK, f"state removed ({config.STATE})")
    if a.purge_workspace:
        ws = Path(cfg["workspace"]).resolve()
        if ws not in (Path("/"), home().resolve()) and ws.is_dir():
            shutil.rmtree(ws, ignore_errors=True)
            line(OK, f"workspace removed ({ws})")
    else:
        line(INFO, f"workspace kept: {cfg['workspace']}")
    if not a.purge:
        line(INFO, f"code and state kept ({config.CODE}, {config.STATE}) - use --purge to remove them")
    if not a.purge:
        line(INFO, "Claude Code, uv, Node.js and the tools were left installed (--purge removes them)")
    for c in changed:                                  # what install.sh changed on this server
        if c == "ufw enabled":
            line(INFO, "the installer turned the ufw firewall on - `ufw disable` turns it off")
        elif c == "ssh key-only":
            line(INFO, "the installer turned SSH password logins off (kept: safer) - to undo: "
                       "rm /etc/ssh/sshd_config.d/01-harness-maxxing.conf && systemctl reload ssh")
        elif c.startswith("timezone "):
            line(INFO, f"the system time zone was {c[9:]} before - timedatectl set-timezone {c[9:]}")
    return 0


F2B_JAIL = Path("/etc/fail2ban/jail.d/harness-maxxing.local")
CADDY_ADMIN_DROPIN = Path("/etc/systemd/system/caddy.service.d/harness-maxxing-admin.conf")
FSTAB = Path("/etc/fstab")


def _uninstall_components(changed: list[str], purge: bool) -> None:
    """What deps.toml and the install-manifest list: the commands in /usr/local/bin always (they point into the
    state dir), the components themselves with --purge (Caddy only when the installer installed it)."""
    deps = _optional("deps")
    if deps is None:
        return
    for name in ("scrapling", "node"):
        c = deps.get(name)
        for n in c.get("links", []):
            link = deps.LINK_DIR / n
            text = ""
            if link.is_file() and not link.is_symlink():
                with contextlib.suppress(OSError):
                    text = link.read_text(errors="ignore")[:400]
            if (link.is_symlink() and os.readlink(link).startswith(str(config.STATE))) or "Harness Maxxing wrapper" in text:
                link.unlink()
    line(OK, "tool commands removed from /usr/local/bin (scrapling, node...)")
    if F2B_JAIL.is_file():
        F2B_JAIL.unlink()
        systemctl("try-restart", "fail2ban", timeout=60)
        line(OK, f"fail2ban jail removed ({F2B_JAIL})")
    if not purge:
        return
    removed = []
    for name in ("remotion", "chromium", "scrapling", "whisper", "node", "python", "claude", "uv"):
        try:
            if name in ("claude", "uv") and f"{name} installed" not in changed and name not in deps.read_record():
                continue                               # it was here before Harness Maxxing: not ours to remove
            if deps.remove(name, force=True):
                removed.append(name)
        except Exception as e:  # noqa: BLE001 - uninstall goes on
            line(WARN, f"{name} not removed", str(e)[:200])
    if removed:
        line(OK, "removed: " + ", ".join(removed))
    if "caddy installed" in changed:
        c = deps.get("caddy")
        systemctl("disable", "--now", "caddy", timeout=60)
        code, out = run(["apt-get", "purge", "-y", "-qq", c["package"]], timeout=600,
                        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
        for f in [Path(x) for x in c["remove"]] + [CADDY_ADMIN_DROPIN]:
            with contextlib.suppress(OSError):
                f.unlink()
        with contextlib.suppress(OSError):
            CADDY_ADMIN_DROPIN.parent.rmdir()
        systemctl("daemon-reload")
        line(OK if code == 0 else WARN, "Caddy removed (installed by the installer)" if code == 0 else "Caddy not purged",
             "" if code == 0 else out[-200:])
    for c in changed:
        if c.startswith("swapfile "):
            sw = Path(c[9:].strip())
            run(["swapoff", str(sw)], timeout=120)
            with contextlib.suppress(OSError):
                lines = FSTAB.read_text().splitlines()
                keep = [ln for ln in lines if not (ln.split()[:1] == [str(sw)])]
                if keep != lines:
                    FSTAB.write_text("".join(ln + "\n" for ln in keep))
            with contextlib.suppress(OSError):
                sw.unlink()
            line(OK, f"swap file removed ({sw})")
    if Path(deps.get("garage")["path"]).exists():
        line(INFO, "Garage (S3 buckets) kept: it holds your buckets - maxxing deps remove garage removes the program")


def _cfg_uninstall(p: argparse.ArgumentParser) -> None:
    p.add_argument("--purge", action="store_true", help="also remove the code and the state dir")
    p.add_argument("--purge-workspace", action="store_true", help="also remove the workspace (irreversible)")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")


cli.register("init", "create or refresh config, workspace, skills and default jobs", _cfg_init, cmd_init)
cli.register("doctor", "check the installation", _cfg_doctor, cmd_doctor)
cli.register("update", "update the code, dependencies and skills, then restart", _cfg_update, cmd_update)
cli.register("status", "short status summary", _cfg_status, cmd_status)
cli.register("harden", "apply (or --undo) the systemd sandboxing of the service, then restart it",
             _cfg_harden, cmd_harden)
cli.register("uninstall", "remove the service and integrations", _cfg_uninstall, cmd_uninstall)
