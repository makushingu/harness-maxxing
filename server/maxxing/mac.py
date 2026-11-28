"""macOS: what the server reads from /proc and asks systemd on Linux, the Mac way. There Harness Maxxing is always
installed by a normal user (config.user_mode()), its service is a launchd agent of that user
(~/Library/LaunchAgents/com.harness-maxxing.server.plist, written by install.sh), turns and jobs are plain
processes, and there is no sandbox mode (bubblewrap is Linux only)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

LABEL = "com.harness-maxxing.server"


def is_mac() -> bool:
    return sys.platform == "darwin"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_path() -> Path:
    """Where launchd writes what the server prints (no journal on a Mac)."""
    from . import config
    return config.state_dir("logs") / "server.log"


def _out(cmd: list[str], timeout: float = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def target() -> str:
    return f"gui/{os.getuid()}/{LABEL}"


# ---- the service (launchd) ------------------------------------------------------------------
def service_info() -> dict[str, str]:
    """The agent as `systemctl show` would tell it: LoadState, ActiveState, UnitFileState, pid."""
    code, out = _out(["launchctl", "print", target()])
    if code != 0:
        return {"LoadState": "loaded" if plist_path().exists() else "not-found", "ActiveState": "inactive",
                "UnitFileState": "disabled", "Id": LABEL, "Description": "Harness Maxxing"}
    m = re.search(r"^\s*state = (\S+)", out, re.M)
    pid = re.search(r"^\s*pid = (\d+)", out, re.M)
    return {"LoadState": "loaded", "ActiveState": "active" if m and m.group(1) == "running" else "inactive",
            "UnitFileState": "enabled", "Id": LABEL, "Description": "Harness Maxxing", "pid": pid.group(1) if pid else ""}


def service(action: str) -> tuple[int, str]:
    """restart | start | stop | is-active | is-enabled | disable, with systemctl's exit codes and words."""
    domain = f"gui/{os.getuid()}"
    if action in ("is-active", "is-enabled"):
        info = service_info()
        if action == "is-enabled":
            return (0, "enabled") if info["LoadState"] == "loaded" and plist_path().exists() else (1, "disabled")
        return (0, "active") if info["ActiveState"] == "active" else (3, "inactive")
    if action in ("restart", "start", "try-restart"):
        if _out(["launchctl", "print", target()])[0] != 0:               # not loaded yet (or stopped by `stop`)
            if not plist_path().exists():
                return 5, f"{plist_path()} is missing: run the installer again"
            code, out = _out(["launchctl", "bootstrap", domain, str(plist_path())], timeout=30)
            if code != 0:
                return code, out
        return _out(["launchctl", "kickstart", *(["-k"] if action != "start" else []), target()], timeout=60)
    if action in ("stop", "disable"):
        code, out = _out(["launchctl", "bootout", target()], timeout=60)
        return (0, "") if code == 0 or "No such process" in out or "Could not find" in out else (code, out)
    if action == "daemon-reload":
        return 0, ""
    return 1, f"launchd has no '{action}'"


def restart_later(delay: float = 2.0) -> None:
    """Restart the service once the answer of the request that asked for it is sent."""
    subprocess.Popen(["/bin/sh", "-c", f"sleep {delay}; launchctl kickstart -k {target()}"],     # noqa: S602
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def log_tail(lines: int) -> list[str]:
    try:
        with open(log_path(), "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 400 * max(1, lines)))
            return f.read().decode("utf-8", "replace").splitlines()[-lines:]
    except OSError:
        return []


# ---- what /proc says on Linux ---------------------------------------------------------------
def _sysctl(name: str) -> str:
    code, out = _out(["sysctl", "-n", name], timeout=5)
    return out.strip() if code == 0 else ""


def meminfo() -> dict[str, int]:
    """{total, avail} in bytes: free + inactive + purgeable + speculative pages count as available."""
    try:
        total = int(_sysctl("hw.memsize") or 0)
    except ValueError:
        total = 0
    code, out = _out(["vm_stat"], timeout=5)
    page = int(m.group(1)) if (m := re.search(r"page size of (\d+) bytes", out)) else 4096
    pages = {k.strip(): int(v) for k, v in re.findall(r"^(Pages [a-z ]+):\s+(\d+)\.", out, re.M)}
    avail = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages purgeable", "Pages speculative")) * page
    return {"total": total, "avail": min(avail, total) if total else avail}


def swap_total() -> int:
    """Bytes of swap in use by the system (macOS grows it by itself: never a missing swap)."""
    m = re.search(r"total = ([\d.]+)M", _sysctl("vm.swapusage"))
    return int(float(m.group(1)) * 1024 * 1024) if m else 0


def uptime_s() -> float:
    m = re.search(r"sec = (\d+)", _sysctl("kern.boottime"))
    return max(0.0, time.time() - int(m.group(1))) if m else 0.0


def cpu_pct() -> float | None:
    """Processor use now, 0-100: the sum of every process's share over the number of cores."""
    code, out = _out(["ps", "-A", "-o", "%cpu="], timeout=5)
    if code != 0:
        return None
    total = 0.0
    for v in out.split():
        try:
            total += float(v.replace(",", "."))
        except ValueError:
            continue
    return round(min(100.0, total / (os.cpu_count() or 1)), 1)


def proc_start(pid: int | str) -> str | None:
    """When a process started (who it is, not just its number); None when there is no such process."""
    code, out = _out(["ps", "-o", "lstart=", "-p", str(pid)], timeout=5)
    return out.strip() or None if code == 0 else None


def listen_addrs(port: int) -> list[str]:
    """Addresses listening on TCP `port`."""
    code, out = _out(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fn"], timeout=10)
    found = []
    for line in out.splitlines():
        if line.startswith("n") and ":" in line:
            host = line[1:].rsplit(":", 1)[0].strip("[]")
            found.append("0.0.0.0" if host == "*" else host)
    return sorted(set(found))


def process_paths() -> set[str]:
    """Every absolute path on a running command line (what a process may be working from)."""
    code, out = _out(["ps", "-axww", "-o", "command="], timeout=10)
    return {w for line in out.splitlines() for w in line.split() if w.startswith("/")}
