"""The package manager of this system: apt (Debian, Ubuntu), dnf (Fedora and its family) or pacman (Arch and its
family). The few places of the server that install a system package, or tell the user how to, go through here; the
installer has its own copy of the names (install.sh, `pkg_names`)."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# the names that differ from Debian's
NAMES = {
    "dnf": {"cron": "cronie", "ffmpeg": "ffmpeg-free", "postgresql": "postgresql-server"},
    "pacman": {"cron": "cronie"},
}
CACHES = {"apt": ("/var/cache/apt/archives", "*.deb"), "dnf": ("/var/cache/libdnf5", "*.rpm"),
          "pacman": ("/var/cache/pacman/pkg", "*.pkg.tar*")}
UNIT_DIRS = ("/usr/lib/systemd/system", "/lib/systemd/system", "/etc/systemd/system")


def manager() -> str:
    """"apt", "dnf", "pacman", or "" (none of them here)."""
    for name, binary in (("apt", "apt-get"), ("dnf", "dnf"), ("pacman", "pacman")):
        if shutil.which(binary):
            return name
    return ""


def name(pkg: str) -> str:
    return NAMES.get(manager(), {}).get(pkg, pkg)


def install_cmd(*pkgs: str) -> list[str]:
    m = manager()
    names = [name(p) for p in pkgs]
    if m == "dnf":
        return ["dnf", "install", "-y", "-q", *names]
    if m == "pacman":
        return ["pacman", "-S", "--needed", "--noconfirm", *names]
    return ["apt-get", "install", "-y", "-q", *names]


def hint(*pkgs: str) -> str:
    """The command a person types to install these packages (doctor fixes, error messages)."""
    cmd = install_cmd(*pkgs)
    return " ".join(c for c in cmd if c not in ("-q", "--noconfirm"))


def install(*pkgs: str, timeout: int = 900) -> tuple[int, str]:
    """Install system packages (root) -> (exit code, output). apt: one retry after refreshing its lists."""
    m = manager()
    if not m:
        return 127, "no package manager found (apt-get, dnf or pacman)"
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}

    def go(cmd: list[str], t: int) -> tuple[int, str]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=t, env=env)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, str(e)

    code, out = go(install_cmd(*pkgs), timeout)
    if code != 0 and m == "apt":
        go(["apt-get", "update", "-q"], 300)
        code, out = go(install_cmd(*pkgs), timeout)
    return code, out


def purge_cmd(pkg: str) -> list[str]:
    m = manager()
    if m == "dnf":
        return ["dnf", "remove", "-y", "-q", pkg]
    if m == "pacman":
        return ["pacman", "-Rns", "--noconfirm", pkg]
    return ["apt-get", "purge", "-y", "-qq", pkg]


def clean_cmd() -> list[str]:
    """Empty the cache of downloaded packages."""
    m = manager()
    if m == "dnf":
        return ["dnf", "clean", "packages"]
    if m == "pacman":
        return ["pacman", "-Scc", "--noconfirm"]
    return ["apt-get", "clean"]


def cache() -> tuple[Path, str]:
    """(folder, pattern) of the downloaded packages."""
    folder, pattern = CACHES.get(manager() or "apt", CACHES["apt"])
    return Path(folder), pattern


def cron_service() -> str:
    """The unit of the cron daemon: `cron` (Debian, Ubuntu), `crond` (Fedora), `cronie` (Arch)."""
    for unit in ("cron", "crond", "cronie"):
        if any(os.path.exists(f"{d}/{unit}.service") for d in UNIT_DIRS):
            return unit
    return "cron"
