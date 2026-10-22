"""Sites on this server, the standard way (`maxxing infra site add|remove|list`, skill `maxxing-infra`).

Two kinds:
- **path site** (default): `https://<Harness address>/<name>/`, no DNS needed. One file per site in
  `/etc/caddy/maxxing-paths/<name>.caddy`, imported inside Harness's own Caddy block (before its reverse_proxy).
  Served with `Content-Security-Policy: sandbox ...` (no allow-same-origin): the page runs in an opaque origin and
  can never use the Harness session or API, so any page can live next to the UI. No localStorage/cookies inside:
  an app with a login or a cart goes on its own host.
- **host site**: `https://<host>/`, one file per site in `/etc/caddy/sites/<name>.caddy`, imported by the Caddyfile.

Each change: keep the old text of every touched file, write, `caddy validate`, reload; any failure puts the old files
back. Paths can be redirected for tests: MAXXING_CADDY_DIR, MAXXING_CADDY_BIN, MAXXING_CADDY_RELOAD.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

from .. import config

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
SANDBOX = "sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-modals allow-downloads"
UI_ROUTES = {"api", "ext", "x", "git", "infra", "tasks", "settings", "sessions", "files", "docs", "feed", "crons", "login",
             "setup", "welcome", "hud", "solo", "abs", "assets", "icons", "stream", "hooks", "health", "index.html"}
HEADER = "# maxxing-site"


class CaddyError(Exception):
    def __init__(self, message: str, code: str = "caddy_error"):
        super().__init__(message)
        self.code = code


def caddy_dir() -> Path:
    return Path(os.environ.get("MAXXING_CADDY_DIR", "/etc/caddy"))


def caddyfile() -> Path:
    return caddy_dir() / "Caddyfile"


def harness_site() -> Path:
    return caddy_dir() / "claude-maxxing.caddy"


def paths_dir() -> Path:
    return caddy_dir() / "maxxing-paths"


def sites_dir() -> Path:
    return caddy_dir() / "sites"


def reserved() -> list[str]:
    """Names a path site cannot take: the UI's routes and the files at the root of the web build."""
    names = set(UI_ROUTES)
    try:
        for e in config.WEB_DIST.iterdir():
            names.add(e.name.split(".")[0] if e.is_file() else e.name)
            names.add(e.name)
    except OSError:
        pass
    return sorted(names)


def _caddy(*args: str, timeout: int = 30) -> tuple[int, str]:
    binary = os.environ.get("MAXXING_CADDY_BIN", "caddy")
    try:
        r = subprocess.run([binary, *args], capture_output=True, text=True, timeout=timeout, errors="replace")
        return r.returncode, (r.stderr or r.stdout)
    except FileNotFoundError:
        raise CaddyError("Caddy is not installed on this server", "no_caddy") from None
    except subprocess.TimeoutExpired:
        return 1, "caddy took too long"


def _reload() -> tuple[int, str]:
    cmd = os.environ.get("MAXXING_CADDY_RELOAD")
    args = shlex.split(cmd) if cmd else ["systemctl", "reload", "caddy"]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=60, errors="replace")
        return r.returncode, r.stderr or r.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def _apply(changes: dict[Path, str | None]) -> None:
    """Write (or delete, value None) the files, validate, reload; put everything back on any failure."""
    before = {p: (p.read_text() if p.exists() else None) for p in changes}
    try:
        for p, text in changes.items():
            if text is None:
                p.unlink(missing_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
        code, out = _caddy("validate", "--config", str(caddyfile()), "--adapter", "caddyfile")
        if code != 0:
            raise CaddyError("Caddy refused the configuration: " + _last_error(out), "invalid_config")
        code, out = _reload()
        if code != 0:
            raise CaddyError("Caddy did not reload: " + _last_error(out), "reload_failed")
    except BaseException:
        for p, text in before.items():
            if text is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(text)
        if any(changes):
            _reload()
        raise


def _last_error(out: str) -> str:
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    err = next((ln for ln in reversed(lines) if "Error" in ln or "error" in ln), lines[-1] if lines else "")
    m = re.search(r'"(?:msg|error)":\s*"([^"]+)"', err)
    return (m.group(1) if m else err)[:300]


def _with_import(text: str, line: str, before_directive: str | None) -> str:
    """`text` with `line` added (once): before the first `before_directive` line, else at the end."""
    if line.strip() in (ln.strip() for ln in text.splitlines()):
        return text
    if before_directive:
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if ln.strip().startswith(before_directive):
                indent = ln[: len(ln) - len(ln.lstrip())]
                lines[i:i] = [f"{indent}# sites under this address (maxxing infra site add)", indent + line.strip()]
                return "\n".join(lines) + "\n"
        raise CaddyError(f"no `{before_directive}` line in {harness_site()}", "unexpected_config")
    return text.rstrip("\n") + f"\n\n{line.strip()}\n"


def _served() -> list[dict]:
    from . import probe
    try:
        return probe.caddy_sites() or []
    except Exception:  # noqa: BLE001
        return []


HARNESS_COOKIE_NAME = r"mx_[A-Za-z0-9_]+"
HARNESS_COOKIE_RE = HARNESS_COOKIE_NAME + r"=[^;]*;?\s*"       # one Harness cookie in a Cookie header (Caddy regex)
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_./-]+$")      # written as is in a Caddy file: no space, quote, newline


def _block(name: str, root: str | None, port: int | None, upstream_host: str | None, keep_prefix: bool, sandbox: bool) -> str:
    inner = []
    if sandbox:
        inner += [f'header Content-Security-Policy "{SANDBOX}"', 'header Access-Control-Allow-Origin "*"']
    if root:
        # dotfiles (.env, .git/config with a token in a remote URL) are never served
        inner += [f"root * {root}", "file_server {\n\t\thide .*\n\t}"]
    else:
        opts = [f"header_up Host {upstream_host}"] if upstream_host else []
        if sandbox:
            # a path site shares the Harness origin: its app never sees the Harness cookies (mx_session, mx_device)
            # and cannot set one; its own cookies (a login of the app) still work
            opts += [f'header_up Cookie "{HARNESS_COOKIE_RE}" ""', f'header_down Set-Cookie "^{HARNESS_COOKIE_NAME}=.*$" ""']
        up = f"reverse_proxy 127.0.0.1:{port}"
        inner.append(up + (" {\n" + "".join(f"\t\t{o}\n" for o in opts) + "\t}" if opts else ""))
    return "\n".join("\t" + ln for ln in inner)


def add_site(name: str, root: str | None = None, port: int | None = None, host: str | None = None,
             project: str | None = None, keep_prefix: bool = False, upstream_host: str | None = None,
             kind: str = "site") -> dict:
    """Create a path site (no host) or a host site. Returns {name, url, file, mode}."""
    if not NAME_RE.match(name or ""):
        raise CaddyError("names use a-z, 0-9 and -, start with a letter or digit (max 63)", "invalid_name")
    if bool(root) == bool(port):
        raise CaddyError("give either a folder (--dir) or a local port (--port)", "invalid_target")
    if root:
        rp = Path(root).expanduser().resolve()
        if not rp.is_dir():
            raise CaddyError(f"{root} is not a folder", "invalid_dir")
        home = Path(os.environ.get("HOME") or "/root")
        never = [config.STATE, config.CODE, home / ".ssh", Path("/etc")]
        if (str(rp) in ("/", "/root", str(home), str(config.workspace()), "/home")
                or any(rp == n or rp.is_relative_to(n) for n in never)
                or any(part.startswith(".") for part in rp.parts[1:]) or rp.name == ".ssh"):
            raise CaddyError(f"{rp} cannot be published (system, secret or workspace root folder)", "invalid_dir")
        if not SAFE_PATH_RE.match(str(rp)):
            raise CaddyError("the folder path may only use letters, digits, '.', '_', '-' and '/'", "invalid_dir")
        root = str(rp)
    if port is not None and not 1 <= int(port) <= 65535:
        raise CaddyError("invalid port", "invalid_target")
    if (paths_dir() / f"{name}.caddy").exists() or (sites_dir() / f"{name}.caddy").exists():
        raise CaddyError(f"a site named {name} already exists (maxxing infra site remove {name} first)", "exists")
    if project and not SAFE_PATH_RE.match(project):
        raise CaddyError("the project may only use letters, digits, '.', '_', '-' and '/'", "invalid_project")
    cfg = config.load_config()
    from .build import harness_host
    hh = harness_host(cfg.get("public_url"))
    meta = f"{HEADER} name={name} kind={kind}" + (f" project={project}" if project else "")
    if not host:
        if name in reserved():
            raise CaddyError(f"/{name} is used by Harness itself: pick another name", "reserved_name")
        if not harness_site().exists() or not hh:
            raise CaddyError("path sites need Harness served by Caddy on a domain (Settings -> General -> address); "
                             "give the site its own host with --host instead", "no_harness_site")
        if any(s.get("host") == hh and (s.get("path") or "").rstrip("/") == f"/{name}" for s in _served()):
            raise CaddyError(f"https://{hh}/{name} is already served by another part of the Caddy configuration", "taken")
        f = paths_dir() / f"{name}.caddy"
        directive = "handle" if keep_prefix and port else "handle_path"
        text = (f"{meta}\n# written by `maxxing infra site add` - remove with `maxxing infra site remove {name}`\n"
                f"redir /{name} /{name}/ 308\n{directive} /{name}/* {{\n"
                f"{_block(name, root, port, upstream_host, keep_prefix, True)}\n}}\n")
        imp = f"import {paths_dir()}/*.caddy"
        changes = {f: text, harness_site(): _with_import(harness_site().read_text(), imp, "reverse_proxy")}
        url = f"https://{hh}/{name}/"
        mode = "path"
        rid = f"site:local:{hh}/{name}"
    else:
        host = host.lower().strip().rstrip(".")
        if not HOST_RE.match(host):
            raise CaddyError(f"{host} is not a valid host name", "invalid_host")
        if host == hh:
            raise CaddyError("that is the address of Harness itself: use a path site (no --host)", "taken")
        if any(s.get("host") == host for s in _served()):
            raise CaddyError(f"{host} is already served by the Caddy configuration", "taken")
        f = sites_dir() / f"{name}.caddy"
        text = (f"{meta}\n# written by `maxxing infra site add` - remove with `maxxing infra site remove {name}`\n"
                f"{host} {{\n\tencode zstd gzip\n{_block(name, root, port, upstream_host, False, False)}\n}}\n")
        imp = f"import {sites_dir()}/*.caddy"
        cf_text = caddyfile().read_text() if caddyfile().exists() else ""
        changes = {f: text, caddyfile(): _with_import(cf_text, imp, None)}
        url = f"https://{host}/"
        mode = "host"
        rid = f"site:local:{host}"
    _apply(changes)
    from . import registry
    registry.declare(rid, kind="site", name=url.split("://", 1)[1].rstrip("/"), server="local", project=project,
                     urls=[url], recipe={"mode": mode, "file": str(f), "dir": root, "port": port, "name": name, "type": kind})
    return {"name": name, "url": url, "file": str(f), "mode": mode, "id": rid}


def list_sites() -> list[dict]:
    out = []
    for mode, d in (("path", paths_dir()), ("host", sites_dir())):
        for f in sorted(d.glob("*.caddy")) if d.is_dir() else []:
            first = f.read_text(errors="replace").splitlines()[:1]
            meta = dict(kv.split("=", 1) for kv in (first[0].split()[2:] if first and first[0].startswith(HEADER) else []) if "=" in kv)
            out.append({"name": f.stem, "mode": mode, "file": str(f), **meta})
    return out


def remove_site(name: str) -> dict:
    f = next((d / f"{name}.caddy" for d in (paths_dir(), sites_dir()) if (d / f"{name}.caddy").exists()), None)
    if not NAME_RE.match(name or "") or f is None:
        raise CaddyError(f"no site named {name} (see maxxing infra site list)", "not_found")
    keep = config.state_dir("infra", "removed") / f"{name}.caddy"
    keep.write_text(f.read_text())
    _apply({f: None})
    from . import registry
    for rid, r in registry.resources().items():
        if (r.get("recipe") or {}).get("file") == str(f):
            registry.forget(rid)
    return {"name": name, "removed": str(f), "kept_copy": str(keep)}
