"""CPU priorities and who uses the processor.  STDLIB ONLY (imported by sessions/spawn.py).

Linux shares a full processor equally between systemd units: a video render at 99 % gets as much as the web server
(the UI) or a Claude turn. With config `cpu_priorities` (default on, Settings -> System) three slices give weights -
never caps or reservations: they only matter while the processor is full.

  live        maxxing-live.slice    the server unit (claude-maxxing), a browser being watched      CPUWeight 1000
  normal      maxxing-turns.slice   the turns of sessions and agents (maxxing-<sid8>)              CPUWeight  100
  background  maxxing-jobs.slice    scheduled jobs, `maxxing heavy <command>`                      CPUWeight   30

(IOWeight follows CPUWeight.) The dash makes the three slices children of `maxxing.slice`, a sibling of system.slice:
inside it the server goes first; against the rest of the machine (Docker, other services) the whole of Harness keeps
its equal share. The files are written by `maxxing init` (cmd_core.ensure_cpu_slices); `set_level()` moves a running
unit at runtime. `snapshot()` = CPU pressure (/proc/pressure/cpu) + the units that use the processor most.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import config

LIVE, NORMAL, BACKGROUND = "live", "normal", "background"
SLICES = {LIVE: "maxxing-live.slice", NORMAL: "maxxing-turns.slice", BACKGROUND: "maxxing-jobs.slice"}
WEIGHTS = {LIVE: 1000, NORMAL: 100, BACKGROUND: 30}
EQUAL = 100                                   # systemd's default weight: the setting off
SLICE_DESC = {LIVE: "Harness Maxxing - what the user watches (web server)",
              NORMAL: "Harness Maxxing - turns of sessions and agents",
              BACKGROUND: "Harness Maxxing scheduled jobs"}
SLICE_DIR = Path("/etc/systemd/system")       # monkeypatched in tests (never /etc there)
SYSTEMD_DIR = Path("/run/systemd/system")     # present when systemd is PID 1
CGROUP_ROOT = Path("/sys/fs/cgroup")
PRESSURE_PATH = Path("/proc/pressure/cpu")
WAITING_PCT = 20.0                            # `some avg10` from which the UI says "waiting"
ALERT_PCT, ALERT_S = 40.0, 600                # `some avg60` held this long -> a health problem
CACHE_S = 3.0
FORCE_S = 0.5                                 # ?force=true still reuses a snapshot this fresh
TOP_N = 6


def enabled(cfg: dict | None = None) -> bool:
    return (cfg if cfg is not None else config.load_config()).get("cpu_priorities", True) is not False


def weight(level: str, cfg: dict | None = None) -> int:
    return WEIGHTS[level] if enabled(cfg) else EQUAL


def systemd_ok() -> bool:
    """Can units be changed here? (root, systemd as PID 1, not in tests/dev MAXXING_SPAWN=direct)."""
    return (os.environ.get("MAXXING_SPAWN") != "direct" and SYSTEMD_DIR.is_dir() and hasattr(os, "geteuid")
            and os.geteuid() == 0 and shutil.which("systemctl") is not None)


def slice_text(level: str, cfg: dict | None = None, extra: str = "") -> str:
    """The unit file of a level's slice (the jobs slice adds its MemoryMax through `extra`)."""
    w = weight(level, cfg)
    head = ("# Harness Maxxing - every scheduled job unit runs in this slice (config `jobs_memory_max`, then `maxxing init`)\n"
            if level == BACKGROUND else
            "# Harness Maxxing - CPU priorities (config `cpu_priorities`, Settings -> System; written by `maxxing init`)\n")
    return (head + f"[Unit]\nDescription={SLICE_DESC[level]}\n\n[Slice]\n" + extra
            + f"CPUWeight={w}\nIOWeight={w}\n")


def turn_slice_args(cfg: dict | None = None) -> list[str]:
    """systemd-run options of a turn unit: the turns slice, when the setting is on and its file exists."""
    if not enabled(cfg) or not (SLICE_DIR / SLICES[NORMAL]).is_file():
        return []
    return ["--slice", SLICES[NORMAL]]


def set_level(unit: str, level: str) -> bool:
    """Give a running unit the weight of a level, at runtime (`systemctl set-property --runtime`): e.g. the browser
    the user is watching -> "live", back to "normal" when they look away. A unit cannot change slice while it runs,
    so only its weight moves. No-op (False) when the setting is off, without systemd or not root."""
    if level not in WEIGHTS or not unit or not enabled() or not systemd_ok():
        return False
    w = WEIGHTS[level]
    try:
        r = subprocess.run(["systemctl", "set-property", "--runtime", unit, f"CPUWeight={w}", f"IOWeight={w}"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


# ---- `maxxing heavy` ------------------------------------------------------------------------------
_UNIT_PART = re.compile(r"[^A-Za-z0-9]+")


def heavy_unit(env: dict | None = None, pid: int | None = None) -> str:
    """Scope name of `maxxing heavy`: after the session (MAXXING_SESSION) or the job (MAXXING_CRON_ID) that started
    it, so the CPU view can name it ("Heavy · <session title>")."""
    env = os.environ if env is None else env
    pid = os.getpid() if pid is None else pid
    sid, cid = str(env.get("MAXXING_SESSION") or ""), str(env.get("MAXXING_CRON_ID") or "")
    tag = (f"session-{_UNIT_PART.sub('', sid)[:8]}" if _UNIT_PART.sub("", sid)
           else f"cron-{_UNIT_PART.sub('-', cid).strip('-')[:40]}" if _UNIT_PART.sub("", cid) else "")
    return "-".join(x for x in ("maxxing-heavy", tag, str(pid)) if x) + ".scope"


def heavy_argv(cmd: list[str], env: dict | None = None, systemd: bool | None = None) -> list[str]:
    """The command line that runs `cmd` with the background priority: in a scope of the jobs slice (systemd-run
    --scope: the command stays in the foreground - same terminal, same output, same exit code), else under
    `nice -n 10` + `ionice -c3` (idle I/O)."""
    if systemd is None:
        systemd = systemd_ok() and shutil.which("systemd-run") is not None
    if systemd:
        env = os.environ if env is None else env
        who = env.get("MAXXING_SESSION") or env.get("MAXXING_CRON_NAME") or ""
        return ["systemd-run", "--scope", "--quiet", "--collect", f"--slice={SLICES[BACKGROUND]}",
                f"--unit={heavy_unit(env)}", f"--description=Harness Maxxing heavy work{' - ' + who if who else ''}",
                "--", *cmd]
    out = ["nice", "-n", "10"] if shutil.which("nice") else []
    if shutil.which("ionice"):
        out += ["ionice", "-c3"]
    return out + cmd


# ---- pressure --------------------------------------------------------------------------------------
def parse_pressure(text: str) -> dict | None:
    """`some avg10=1.86 avg60=2.34 avg300=2.74 total=…` -> {"avg10": 1.86, "avg60": 2.34, "avg300": 2.74}: the share
    of time at least one program waited for the processor."""
    for line in (text or "").splitlines():
        parts = line.split()
        if parts and parts[0] == "some":
            vals = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
            try:
                return {k: float(vals[k]) for k in ("avg10", "avg60", "avg300")}
            except (KeyError, ValueError):
                return None
    return None


def pressure() -> dict | None:
    """CPU pressure of the machine, None when the kernel has no PSI (old kernel, `psi=0`)."""
    try:
        return parse_pressure(PRESSURE_PATH.read_text())
    except OSError:
        return None


_watch: dict = {"since": None, "seen": 0.0}


def note_pressure(p: dict | None, now: float | None = None) -> float:
    """Remember since when `some avg60` stays >= ALERT_PCT (the server checks it every health pass); returns how long
    it has been high (0 when not). A gap of more than 5 min without a reading starts again."""
    now = time.time() if now is None else now
    high = bool(p) and p["avg60"] >= ALERT_PCT
    if not high or (_watch["seen"] and now - _watch["seen"] > 300):
        _watch["since"] = now if high else None
    elif _watch["since"] is None:
        _watch["since"] = now
    _watch["seen"] = now
    return now - _watch["since"] if _watch["since"] is not None else 0.0


# ---- who uses the processor ------------------------------------------------------------------------
def _units(root: Path, depth: int = 0) -> list[tuple[str, str, Path]]:
    """(unit, parent slice, cgroup folder) of every service / scope under the slices of `root`."""
    out: list[tuple[str, str, Path]] = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return out
    for e in entries:
        if not e.is_dir(follow_symlinks=False):
            continue
        if e.name.endswith(".slice") and depth < 4:
            out += [(u, s if s != "-" else e.name, p) for u, s, p in _units(Path(e.path), depth + 1)]
        elif e.name.endswith((".service", ".scope")):
            out.append((e.name, "-", Path(e.path)))
    return out


def _usage_usec(p: Path) -> int | None:
    try:
        with open(p / "cpu.stat") as f:
            first = f.readline().split()
        return int(first[1]) if first and first[0] == "usage_usec" else None
    except (OSError, ValueError, IndexError):
        return None


def level_of(slice_name: str) -> str:
    return next((level for level, name in SLICES.items() if name == slice_name), "other")


_SID8 = re.compile(r"^maxxing-([0-9a-f]{8})(?:-\d+)?\.service$")
_HEAVY = re.compile(r"^maxxing-heavy-(?:session-([0-9a-f]{1,8})|cron-(.+?))?-?\d*\.scope$")
_CRON = re.compile(r"^maxxing-cron-(.+)\.service$")
_AGENT = re.compile(r"^projects/[^/]+/topics/[^/]+/agents/([^/]+)/?$")


class _Names:
    """Session titles and job names, looked up once per snapshot."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict | None] | None = None
        self._ids: list[str] | None = None
        self._jobs: dict[str, str] | None = None

    def session(self, sid8: str) -> dict | None:
        if not sid8:
            return None
        key = sid8[:8]
        if self._sessions is None:
            self._sessions = {}
        if key not in self._sessions:
            self._sessions[key] = None
            try:
                from .sessions import store
                if self._ids is None:
                    self._ids = store.list_ids()
                for sid in self._ids:            # only this prefix's metas: not every session's for one name
                    if sid.startswith(key) and (m := store.read_cached(sid)):
                        self._sessions[key] = m
                        break
            except Exception:  # noqa: BLE001 - a name is a nicety
                pass
        return self._sessions[key]

    def job(self, unit_id: str) -> str | None:
        if self._jobs is None:
            self._jobs = {}
            try:
                from . import crons
                for j in crons.list_jobs():
                    self._jobs[crons.unit_name(j["id"]).removeprefix("maxxing-cron-")] = j.get("name") or j["id"]
            except Exception:  # noqa: BLE001
                pass
        return self._jobs.get(unit_id)


def _session_name(m: dict | None, sid8: str) -> tuple[str, str]:
    if not m:
        return "session", sid8
    a = _AGENT.match(str(m.get("path") or ""))
    if a:
        return "agent", a.group(1)
    return "session", str(m.get("title") or "").strip() or sid8


def describe(unit: str, names: _Names | None = None) -> tuple[str, str]:
    """(kind, name) of a unit for the CPU view: harness, session, agent, heavy, job, browser, docker, other."""
    names = names or _Names()
    if unit == "claude-maxxing.service":
        return "harness", "Harness"
    m = _SID8.match(unit)
    if m:
        return _session_name(names.session(m.group(1)), m.group(1))
    m = _HEAVY.match(unit)
    if m:
        if m.group(1):
            return "heavy", _session_name(names.session(m.group(1)), m.group(1))[1]
        if m.group(2):
            return "heavy", names.job(m.group(2)) or m.group(2)
        return "heavy", ""
    m = _CRON.match(unit)
    if m:
        return "job", names.job(m.group(1)) or m.group(1)
    if unit.startswith(("maxxing-br-", "maxxing-pc-")):
        return "browser", ""
    if unit.startswith("docker") or unit in ("containerd.service",):
        return "docker", ""
    return "other", unit.rsplit(".", 1)[0]


KIND_LABEL = {"harness": "Harness", "session": "Session", "agent": "Agent", "heavy": "Heavy", "job": "Job",
              "browser": "Browser", "docker": "Docker"}


def label(kind: str, name: str) -> str:
    """English label ("Session · blog", "Docker"): the health text; the UI translates the kind itself."""
    k = KIND_LABEL.get(kind)
    if not k:
        return name
    return k if not name or name == k else f"{k} · {name}"


_lock = threading.Lock()
_clock, _sleep = time.monotonic, time.sleep          # monkeypatched in tests
_prev: dict = {"t": 0.0, "usage": {}}
_cache: dict = {"at": 0.0, "data": None}


def _sample() -> tuple[float, dict[str, tuple[int, str, str]]]:
    now = _clock()
    out: dict[str, tuple[int, str, str]] = {}
    for unit, sl, p in _units(CGROUP_ROOT):
        u = _usage_usec(p)
        if u is not None:
            out[str(p)] = (u, unit, sl)
    return now, out


def top(n: int = TOP_N) -> list[dict]:
    """The units that used the processor most since the previous call (a 0.5 s sample on the first call or after
    30 s): [{unit, kind, name, label, level, pct}], pct = share of the whole machine (all cores)."""
    t1, cur = _sample()
    if not cur:                         # no readable cgroup (container, cgroup v1): nothing to wait 0.5 s for
        return []
    t0, prev = _prev["t"], _prev["usage"]
    if not prev or t1 - t0 > 30 or t1 - t0 < 0.2:
        _sleep(0.5)
        t0, prev = t1, cur
        t1, cur = _sample()
    _prev.update(t=t1, usage=cur)
    span = (t1 - t0) * 1e6 * (os.cpu_count() or 1)
    rows = []
    for path, (u, unit, sl) in cur.items():
        before = prev.get(path)
        if before is None or span <= 0:
            continue
        pct = 100.0 * max(0, u - before[0]) / span
        if pct >= 0.1:
            rows.append((pct, unit, sl))
    rows.sort(reverse=True)
    names = _Names()
    out: list[dict] = []
    docker: dict | None = None
    for pct, unit, sl in rows:
        kind, name = describe(unit, names)
        if kind == "docker" and docker is not None:              # every container in one row
            docker["pct"] += pct
            continue
        row = {"unit": unit, "kind": kind, "name": name, "label": label(kind, name), "level": level_of(sl), "pct": pct}
        docker = row if kind == "docker" else docker
        out.append(row)
    out.sort(key=lambda r: -r["pct"])
    for r in out:
        r["pct"] = round(min(r["pct"], 100.0), 1)
    return out[:n]


def snapshot(force: bool = False) -> dict:
    """GET /api/system/cpu: {enabled, pressure:{avg10, avg60, avg300}|null, waiting, top:[...], at} (cached CACHE_S).
    Blocking (up to ~0.5 s): call it through asyncio.to_thread."""
    with _lock:
        # force: a fresh sample, but one made under FORCE_S ago is fresh (parallel forced calls queue on this lock and
        # would each wait another 0.5 s sample)
        if _cache["data"] is not None and time.time() - _cache["at"] < (FORCE_S if force else CACHE_S):
            return dict(_cache["data"])
        p = pressure()
        data = {"enabled": enabled(), "pressure": p, "waiting": bool(p and p["avg10"] >= WAITING_PCT),
                "top": top(), "at": time.time()}
        _cache.update(at=time.time(), data=data)
        return dict(data)
