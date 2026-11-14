"""The systemd unit that runs one browser, and what this server needs for it (`available`, `setup`).

`maxxing-br-<hash>`: user `maxxing-browser`, PrivateNetwork (its own empty network: no access to this server's
ports, the local network or UDP), ProtectSystem=strict, ProtectHome, PrivateTmp, NoNewPrivileges, a memory cap. It
sees only what is mounted: Chromium (read-only), its profile, its run folder (proxy.sock, cdp.sock), the Chromium
policy, the host script (host.sh) and, when downloads are on, the owner's downloads folder.

Ubuntu 24.04+ restricts user namespaces: Chromium's own sandbox needs an AppArmor profile (`APPARMOR_FILE`), which
`setup()` writes and loads. MAXXING_BROWSER_LAUNCH=direct runs host.sh without a unit (tests).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pwd
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .. import config, cpu

log = logging.getLogger("maxxing.browser")

USER = "maxxing-browser"
UNIT_PREFIX = "maxxing-br-"
CDM_VERSION = "1.11.0"                # chrome-devtools-mcp (npm checks the tarball against the registry's hash)
APPARMOR_FILE = Path("/etc/apparmor.d/chromium-maxxing")
APPARMOR_NAME = "chromium-maxxing"
USERNS_SYSCTL = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
APPARMOR_PROFILES = Path("/sys/kernel/security/apparmor/profiles")
HOST_SH = Path(__file__).with_name("host.sh")
POLICY_DIRS = ("/etc/opt/chrome_for_testing/policies/managed", "/etc/chromium/policies/managed",
               "/etc/opt/chrome/policies/managed")
MEMORY_MAX = "1536M"
MEMORY_MAX_BYTES = 1536 * 1024 * 1024
READY_TIMEOUT = 30.0
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"


def apparmor_profile(chrome: Path | None) -> str:
    """The profile: the unit's mount point and the real path of every Chromium revision in the same folder."""
    base = str(chrome.parent.parent.parent).lstrip("/") if chrome else "var/lib/claude-maxxing/tools/browsers"
    where = "/{opt/mxchrome,%s/chromium-*/chrome-linux64,%s/chromium-*/chrome-linux}/chrome" % (base, base)
    return f"""# Harness Maxxing: lets the Chromium of the Harness Browser create user namespaces (its sandbox) on Ubuntu 24.04+
abi <abi/4.0>,
include <tunables/global>
profile {APPARMOR_NAME} {where} flags=(unconfined) {{
  userns,
  include if exists <local/{APPARMOR_NAME}>
}}
"""


# ---- what this server needs ----------------------------------------------------------------------------------------
_avail: tuple[float, dict] | None = None


def cdm_dir() -> Path:
    return config.STATE / "tools" / f"chrome-devtools-mcp-{CDM_VERSION}"


def cdm_entry() -> Path:
    return cdm_dir() / "node_modules" / "chrome-devtools-mcp" / "build" / "src" / "bin" / "chrome-devtools-mcp.js"


def chrome_bin() -> Path | None:
    if os.environ.get("MAXXING_BROWSER_CHROME"):
        return Path(os.environ["MAXXING_BROWSER_CHROME"])
    from .. import deps
    return deps.chromium_bin()


def node_bin() -> str | None:
    from .. import deps
    p = deps.node_bin()
    return str(p) if p else shutil.which("node")


def user_ids() -> tuple[int, int] | None:
    try:
        u = pwd.getpwnam(USER)
        return u.pw_uid, u.pw_gid
    except KeyError:
        return None


def _userns_restricted() -> bool:
    try:
        return USERNS_SYSCTL.read_text().strip() == "1"
    except OSError:
        return False


def _profile_loaded() -> bool:
    try:
        return any(ln.startswith(APPARMOR_NAME + " ") for ln in APPARMOR_PROFILES.read_text().splitlines())
    except OSError:
        return APPARMOR_FILE.is_file()


def available(fresh: bool = False) -> dict:
    """{ok, missing: [...]}: what the browser needs on this server (cached 60 s). missing items: linux, systemd,
    socat, chromium, node, user, apparmor, tools (chrome-devtools-mcp)."""
    global _avail
    if _avail and not fresh and time.time() - _avail[0] < 60:
        return _avail[1]
    if os.environ.get("MAXXING_BROWSER_CHECK") == "0":
        return {"ok": True, "missing": []}
    missing: list[str] = []
    if sys.platform != "linux":
        missing.append("linux")
    if not shutil.which("systemd-run") and os.environ.get("MAXXING_BROWSER_LAUNCH") != "direct":
        missing.append("systemd")
    if not shutil.which("socat"):
        missing.append("socat")
    if not chrome_bin():
        missing.append("chromium")
    if not node_bin():
        missing.append("node")
    if not user_ids():
        missing.append("user")
    if _userns_restricted() and not _profile_loaded():
        missing.append("apparmor")
    if not cdm_entry().is_file():
        missing.append("tools")
    out = {"ok": not missing, "missing": missing}
    _avail = (time.time(), out)
    return out


def setup(log_line=print) -> list[str]:
    """Install what is missing (root): socat, the user, the AppArmor profile, Chromium, chrome-devtools-mcp."""
    done: list[str] = []
    if os.geteuid() != 0:
        raise RuntimeError("run it as root (sudo maxxing browser setup)")
    if not shutil.which("socat"):
        if not shutil.which("apt-get"):
            raise RuntimeError("install socat with the package manager of this system")
        subprocess.run(["apt-get", "install", "-y", "-q", "socat"], check=True, stdout=subprocess.DEVNULL,
                       env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
        done.append("installed socat")
    if not user_ids():
        subprocess.run(["useradd", "--system", "--no-create-home", "--home-dir", "/nonexistent",
                        "--shell", "/usr/sbin/nologin", USER], check=True)
        done.append(f"system user {USER}")
    chrome = chrome_bin()
    if not chrome:
        log_line("Installing Chromium (a few minutes)...")
        from .. import deps
        deps.update(["chromium"], log=log_line)
        chrome = chrome_bin()
        if not chrome:
            raise RuntimeError("Chromium is missing: run `maxxing deps update chromium`")
        done.append("Chromium")
    if _userns_restricted() and not _profile_loaded():
        APPARMOR_FILE.write_text(apparmor_profile(chrome))
        subprocess.run(["apparmor_parser", "-r", str(APPARMOR_FILE)], check=True)
        done.append(f"AppArmor profile {APPARMOR_FILE}")
    if not cdm_entry().is_file():
        node = node_bin()
        npm = str(Path(node).with_name("npm")) if node and Path(node).with_name("npm").exists() else shutil.which("npm")
        if not npm:
            raise RuntimeError("npm is missing (Node.js): run `maxxing deps update node`")
        d = cdm_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "package.json").write_text('{"private": true}\n')
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "HTTPS_PROXY", "HTTP_PROXY",
                                                             "NO_PROXY", "npm_config_cache")}
        env["PATH"] = f"{Path(npm).parent}:{env.get('PATH', '/usr/bin:/bin')}"
        subprocess.run([npm, "install", "--silent", "--no-audit", "--no-fund", "--ignore-scripts",
                        f"chrome-devtools-mcp@{CDM_VERSION}"], cwd=str(d), check=True, env=env, timeout=600)
        done.append(f"chrome-devtools-mcp {CDM_VERSION}")
    available(fresh=True)
    return done


# ---- one browser unit --------------------------------------------------------------------------------------------
def unit_prefix() -> str:
    """maxxing-br-<this install>-: two installs (or a test server) on one machine never stop each other's browsers."""
    import hashlib
    return UNIT_PREFIX + hashlib.sha256(str(config.state_dir().resolve()).encode()).hexdigest()[:6] + "-"


def unit_name(slug: str) -> str:
    """The unit of a profile (slug = its id)."""
    return unit_prefix() + slug


def chrome_major(chrome: Path) -> str:
    try:
        out = subprocess.run([str(chrome), "--version"], capture_output=True, text=True, timeout=20).stdout
        return out.split()[-1].split(".")[0] if out.strip() else "140"
    except (OSError, subprocess.SubprocessError, IndexError):
        return "140"


_major: dict[str, str] = {}


LOCALES = {"en": "en-US", "fr": "fr-FR", "es": "es-ES", "de": "de-DE", "it": "it-IT", "pt": "pt-PT", "nl": "nl-NL",
           "ja": "ja-JP", "zh": "zh-CN", "ko": "ko-KR", "ru": "ru-RU", "pl": "pl-PL"}


def locale() -> tuple[str, str]:
    """(the browser's language, Accept-Language) from the interface's language: sites answer in the user's language."""
    lang = str(config.load_config().get("language") or "en").split("-")[0].lower()
    loc = LOCALES.get(lang, "en-US")
    base = loc.split("-")[0]
    return loc, ",".join(dict.fromkeys([loc, base, "en-US", "en"]))


def timezone() -> str:
    """The Harness time zone (Settings): pages see the user's time, not the server's (a phone exit far from the
    server with the server's clock looks like a robot)."""
    tz = str(config.load_config().get("timezone") or "UTC")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
        return tz
    except Exception:  # noqa: BLE001
        return "UTC"


def chrome_args(chrome: Path, width: int = 1280, height: int = 800) -> list[str]:
    major = _major.get(str(chrome))
    if major is None:
        major = _major[str(chrome)] = chrome_major(chrome)
    return ["--headless=new", "--user-data-dir=/mxprofile" if not _direct() else f"--user-data-dir={{profile}}",
            "--disable-gpu", "--disable-extensions", "--disable-background-networking", "--disable-component-update",
            "--disable-sync", "--disable-default-apps", "--no-first-run", "--no-default-browser-check",
            "--disable-features=AutofillServerCommunication,MediaRouter,OptimizationHints,Translate",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp", "--renderer-process-limit=2",
            "--password-store=basic", "--mute-audio", "--disable-smooth-scrolling", "--autoplay-policy=user-gesture-required",
            f"--window-size={width},{height}", f"--user-agent={UA.format(v=major)}",
            f"--lang={locale()[0]}", f"--accept-lang={locale()[1]}", "about:blank"]


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _direct() -> bool:
    return os.environ.get("MAXXING_BROWSER_LAUNCH") == "direct"


def prepare_dirs(profile: Path, run: Path, downloads: Path | None) -> None:
    ids = user_ids()
    for d, mode in ((profile, 0o700), (run, 0o750)):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, mode)
        if ids and not _direct():
            os.chown(d, ids[0], ids[1])
    if downloads is not None:
        downloads.mkdir(parents=True, exist_ok=True)
        if ids and not _direct():
            os.chown(downloads, ids[0], ids[1])
    for f in ("cdp.sock", "proxy.sock"):
        (run / f).unlink(missing_ok=True)
    shutil.rmtree(run / "uploads", ignore_errors=True)   # files given to pages last time


async def start(slug: str, profile: Path, run: Path, policy: dict, downloads: Path | None) -> asyncio.subprocess.Process | None:
    """Start the unit (or, direct mode, the host script). The caller then waits for `ready()`."""
    chrome = chrome_bin()
    if not chrome:
        raise RuntimeError("Chromium is not installed (maxxing browser setup)")
    config.write_json(run / "policy.json", policy, mode=0o644)
    args = chrome_args(chrome)
    if _direct():
        env = {**{k: v for k, v in os.environ.items() if k in ("PATH", "LANG")}, "TZ": timezone(), "HOME": str(run),
               "MX_RUN": str(run), "MX_CHROME": str(chrome), "MX_PROXY_PORT": str(_free_port()),
               "MX_CDP_PORT": str(_free_port())}
        args = [a.replace("{profile}", str(profile)) for a in args]
        return await asyncio.create_subprocess_exec("/bin/sh", str(HOST_SH), *args, env=env,
                                                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                                                    start_new_session=True)
    props = [f"User={USER}", f"Group={USER}", "PrivateNetwork=yes", "ProtectSystem=strict", "ProtectHome=yes",
             "PrivateTmp=yes", "PrivateIPC=yes", "NoNewPrivileges=yes", f"MemoryMax={MEMORY_MAX}", "TasksMax=512",
             "CPUWeight=30", "IOWeight=30", "ProtectKernelTunables=yes", "ProtectKernelModules=yes", "ProtectControlGroups=yes",
             "RestrictSUIDSGID=yes", "LockPersonality=yes", "UMask=0077",
             f"BindReadOnlyPaths={chrome.parent}:/opt/mxchrome", f"BindPaths={profile}:/mxprofile",
             f"BindPaths={run}:/mxrun", f"BindReadOnlyPaths={HOST_SH.resolve()}:/mxhost.sh",
             "Environment=HOME=/tmp", f"Environment=LANG={locale()[0].replace('-', '_')}.UTF-8",
             f"Environment=LANGUAGE={locale()[0].replace('-', '_')}", f"Environment=TZ={timezone()}"]
    props += [f"BindReadOnlyPaths={run / 'policy.json'}:{d}/harness.json" for d in POLICY_DIRS]
    if downloads is not None:
        props.append(f"BindPaths={downloads}:/mxdownloads")
    # in the turns' slice (CPU priorities on): its weight then counts against turns, never against the web server
    cmd = ["systemd-run", "--quiet", "--collect", "--unit", unit_name(slug), *cpu.turn_slice_args(), "--description",
           f"Harness Maxxing: Harness Browser ({slug})"]
    for p in props:
        cmd += ["-p", p]
    cmd += ["/bin/sh", "/mxhost.sh", *args]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, err = await asyncio.wait_for(proc.communicate(), 30)
    if proc.returncode != 0:
        raise RuntimeError("the browser did not start: " + (err or b"").decode(errors="replace")[-300:].strip())
    return None


def set_level(slug: str, level: str, proc: asyncio.subprocess.Process | None = None) -> None:
    """CPU / disk priority of a profile's unit (cpu.py, Settings -> System -> CPU priorities): `live` while someone
    watches it or Claude acts in it, `background` while it waits. Weights only matter when the processor is full."""
    if proc is not None or _direct():
        return
    cpu.set_level(unit_name(slug), level)


async def http_get(sock: Path, path: str, timeout: float = 5.0) -> dict:
    """GET over the DevTools unix socket (json/version, json/list)."""
    r, w = await asyncio.wait_for(asyncio.open_unix_connection(str(sock)), timeout)
    try:
        w.write(f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode())
        await w.drain()
        head = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), timeout)     # Chromium keeps the connection open
        size = 0
        for line in head.decode("latin-1").split("\r\n"):
            if line.lower().startswith("content-length:"):
                size = int(line.split(":", 1)[1].strip() or 0)
        body = await asyncio.wait_for(r.readexactly(min(size, 1 << 20)), timeout) if size else b""
    finally:
        w.close()
    return json.loads(body or b"{}")


async def ready(run: Path, proc: asyncio.subprocess.Process | None, slug: str) -> str:
    """Wait until DevTools answers; the browser websocket path (/devtools/browser/<id>)."""
    sock = run / "cdp.sock"
    deadline = time.monotonic() + READY_TIMEOUT
    last = ""
    while time.monotonic() < deadline:
        if proc is not None and proc.returncode is not None:
            raise RuntimeError("the browser stopped at once")
        if proc is None and not await unit_active(slug):
            raise RuntimeError("the browser stopped at once (see `journalctl -u " + unit_name(slug) + "`)")
        if sock.exists():
            try:
                v = await http_get(sock, "/json/version", 3)
                url = str(v.get("webSocketDebuggerUrl") or "")
                if "/devtools/" in url:
                    return "/devtools/" + url.split("/devtools/", 1)[1]
            except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
                last = str(e) or type(e).__name__
        await asyncio.sleep(0.25)
    raise RuntimeError("the browser did not answer in time" + (f" ({last})" if last else ""))


def memory_current(slug: str, proc: asyncio.subprocess.Process | None = None) -> int:
    """Bytes the browser uses now (its unit's cgroup; 0 when unknown, e.g. the direct mode of the tests)."""
    if proc is not None or _direct():
        return 0
    try:
        out = subprocess.run(["systemctl", "show", unit_name(slug), "-p", "MemoryCurrent", "--value"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return int(out) if out.isdigit() else 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def server_memory() -> tuple[int, int]:
    """(used, total) bytes of this server's memory (MemTotal - MemAvailable)."""
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            if k in ("MemTotal", "MemAvailable"):
                info[k] = int(v.split()[0]) * 1024
        return info["MemTotal"] - info["MemAvailable"], info["MemTotal"]
    except (OSError, KeyError, ValueError, IndexError):
        return 0, 0


async def unit_active(slug: str) -> bool:
    proc = await asyncio.create_subprocess_exec("systemctl", "is-active", "--quiet", unit_name(slug))
    return await proc.wait() == 0


async def stop(slug: str, proc: asyncio.subprocess.Process | None) -> None:
    if proc is not None:
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, 15)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                try:
                    os.killpg(proc.pid, 9)
                except (ProcessLookupError, PermissionError):
                    pass
        return
    p = await asyncio.create_subprocess_exec("systemctl", "stop", unit_name(slug),
                                             stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(p.wait(), 20)
    except asyncio.TimeoutError:
        pass


def stop_all_units() -> None:
    """At server start: browsers of a previous run lost their proxy and tools - stop them (blocking)."""
    if _direct() or not shutil.which("systemctl"):
        return
    try:
        prefix = unit_prefix()
        out = subprocess.run(["systemctl", "list-units", "--plain", "--no-legend", f"{prefix}*"],
                             capture_output=True, text=True, timeout=20).stdout
        names = [ln.split()[0] for ln in out.splitlines() if ln.strip().startswith(prefix)]
        if names:
            subprocess.run(["systemctl", "stop", *names], timeout=60, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        log.exception("stopping the browsers of a previous run failed")
