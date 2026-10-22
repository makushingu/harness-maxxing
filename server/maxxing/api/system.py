"""System page: health, services, logs, version/update and the experimental usage probe.
See docs/dev/API.md#system and maxxing/health.py."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
import threading
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import __version__, bus, config, health
from ..security import require_auth

log = logging.getLogger("maxxing.license")
router = APIRouter(prefix="/api", tags=["system"], dependencies=[Depends(require_auth)])

_TRANSIENT_UNIT = re.compile(r"^maxxing-[a-z0-9-]{1,64}$")     # session turns, cron runs, update


def _err(status: int, code: str, msg: str) -> HTTPException:
    return HTTPException(status, detail={"error": code, "message": msg})


@router.get("/system/health")
async def get_health(force: bool = False):
    return await asyncio.to_thread(health.collect, force)


@router.get("/system/services")
async def get_services():
    return await asyncio.to_thread(health.services)


def _service_action(name: str, action: str) -> None:
    if name == health.SELF_UNIT:
        if action == "stop":
            raise _err(400, "refused", "Stopping Harness Maxxing from its own UI would lock you out")
        # restart (or start) ourselves: deferred so this response can be sent first
        r = subprocess.run(["systemd-run", "--collect", "--quiet", "--on-active=2",
                            "--timer-property=AccuracySec=100ms", "systemctl", "restart", health.SELF_UNIT],
                           capture_output=True, text=True, timeout=15)
    else:
        r = subprocess.run(["systemctl", action, name], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise _err(502, "systemctl_failed", (r.stderr or r.stdout).strip()[:300] or f"exit code {r.returncode}")


@router.post("/system/services/{name}/{action}")
async def service_action(name: str, action: Literal["start", "stop", "restart"]):
    if name not in health.service_names():
        raise _err(404, "unknown_service", f"{name} is not a managed service")
    try:
        await asyncio.to_thread(_service_action, name, action)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise _err(502, "systemctl_failed", str(e)) from None
    health.invalidate_cache()
    health.invalidate_services()
    bus.invalidate("health")
    return {"ok": True}


def _logs(unit: str, lines: int) -> list[str]:
    r = subprocess.run(["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"],
                       capture_output=True, text=True, timeout=20)
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


@router.get("/system/logs")
async def logs(unit: str = health.SELF_UNIT, lines: int = Query(200, ge=1, le=5000)):
    if unit not in health.service_names() and not _TRANSIENT_UNIT.match(unit):
        raise _err(400, "unit_not_allowed", f"logs of {unit} are not available here")
    try:
        return {"lines": await asyncio.to_thread(_logs, unit, lines)}
    except (OSError, subprocess.TimeoutExpired) as e:
        raise _err(502, "journalctl_failed", str(e)) from None


# ---- version / update -----------------------------------------------------------------------
REMOTE_TTL = 600
_ver: dict[str, Any] = {"at": 0.0, "latest": None, "behind": None, "busy": False}
_ver_lock = threading.Lock()


def _git(*args: str, timeout: float = 10, auth: bool = False) -> str | None:
    from ..cmd_core import git_auth_env
    tok = config.get_secret("github_update_token") if auth else None   # private repository: same token as `maxxing update`
    env = git_auth_env(tok, {**os.environ, "GIT_ASKPASS": "true"})
    cmd = ["git"]
    try:
        r = subprocess.run([*cmd, "-C", str(config.CODE), *args], capture_output=True, text=True,
                           timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _refresh_remote() -> None:
    """Fetch origin (thread) -> latest commit and how many commits we are behind."""
    try:
        latest = behind = None
        from .. import license
        if license.enabled():                          # licensed install: ask the license server
            try:
                f = license.fetch_latest()
                info = license.status()
                latest = info.get("latest")
                b = _git("rev-list", "--count", "HEAD..refs/remotes/origin/main")
                behind = int(b) if b and b.isdigit() else (1 if f.get("version") else 0)
            except license.LicenseError:
                pass
            with _ver_lock:
                _ver.update(latest=latest, behind=behind)
            return
        if _git("fetch", "--quiet", "origin", timeout=30, auth=True) is not None:
            latest = _git("rev-parse", "--short", "FETCH_HEAD")
            b = _git("rev-list", "--count", "HEAD..FETCH_HEAD")
            behind = int(b) if b and b.isdigit() else None
        else:
            line = _git("ls-remote", "origin", "HEAD", timeout=20, auth=True)
            latest = line.split()[0][:7] if line else None
        with _ver_lock:
            _ver.update(latest=latest, behind=behind)
    finally:
        with _ver_lock:
            _ver.update(at=time.time(), busy=False)


LOCAL_TTL = 30
_local: dict[str, Any] = {"at": 0.0, "sig": None, "commit": None, "custom": None}


def _git_sig() -> tuple:
    """Cheap fingerprint of the code clone: HEAD, the branch ref, packed refs, the index. A commit,
    checkout, rebase or `maxxing custom save` (another process) changes it."""
    g = config.CODE / ".git"
    paths = [g / "HEAD", g / "packed-refs", g / "index"]
    try:
        head = (g / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            paths.append(g / head[5:])
    except OSError:
        pass
    sig = []
    for p in paths:
        try:
            st = p.stat()
            sig.append((st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append(None)
    return (str(config.CODE), *sig)


def invalidate_version() -> None:
    """Drop the cached commit / customizations (after an update or a customization saved here)."""
    with _ver_lock:
        _local.update(at=0.0, sig=None)


def _local_info(refresh: bool) -> tuple[str | None, dict]:
    """(HEAD commit, customizations card) - cached LOCAL_TTL s and while the clone is unchanged
    (uncommitted edits are seen within LOCAL_TTL)."""
    sig = _git_sig()
    with _ver_lock:
        if not refresh and _local["sig"] == sig and time.time() - _local["at"] < LOCAL_TTL:
            return _local["commit"], dict(_local["custom"])
    commit = _git("rev-parse", "--short", "HEAD", timeout=5)
    from .. import customs
    try:
        cs = customs.list_customs() if customs.is_git() else []
        dirty = customs.dirty_files() if customs.is_git() else []
        custom = {"count": len(cs), "titles": [c["title"] for c in cs][:20], "dirty": len(dirty)}
    except Exception:  # noqa: BLE001 - never break the version card
        custom = {"count": 0, "titles": [], "dirty": 0}
    with _ver_lock:
        _local.update(at=time.time(), sig=_git_sig(), commit=commit, custom=custom)   # after git status refreshed the index
    return commit, dict(custom)


def version_info(refresh: bool = False) -> dict:
    """refresh=True: check the remote now (waits for it) instead of every REMOTE_TTL seconds."""
    run_now = False
    with _ver_lock:
        stale = refresh or time.time() - _ver["at"] > REMOTE_TTL
        if stale and not _ver["busy"]:
            _ver["busy"] = True
            run_now = refresh
            if not refresh:
                threading.Thread(target=_refresh_remote, daemon=True, name="maxxing-version").start()
    if run_now:
        _refresh_remote()
    commit, custom = _local_info(refresh)
    from .. import customs
    try:
        custom["rebase"] = customs.rebase_in_progress() if customs.is_git() else False
        pend = customs.pending() if customs.is_git() else None
    except Exception:  # noqa: BLE001
        custom["rebase"], pend = False, None
    with _ver_lock:
        from .. import license
        lic = license.status()
        lic = {k: lic.get(k) for k in ("enabled", "key_hint", "email", "kind", "updates_until", "expires_at", "channel", "latest", "message", "max_servers")}
        out = {"version": __version__, "commit": commit, "latest_commit": _ver["latest"], "behind": _ver["behind"], "license": lic,
               "checking": _ver["busy"], "checked_at": _ver["at"] or None, "custom": custom, "pending": pend}
    from .. import smartupdate
    rep = smartupdate.last_report()
    out["report"] = {k: rep.get(k) for k in ("at", "version", "ok", "problems")} if rep else None
    after = smartupdate.after_info()
    out["after"] = after
    from .. import auto_update
    out["auto_update"] = auto_update.public()
    return out


@router.get("/system/version")
async def version(refresh: bool = False):
    return await asyncio.to_thread(version_info, refresh)


def _spawn_update(smart: bool = True) -> None:
    """Start `maxxing update` apart from the server (it restarts it). `smart`: the Update button also opens the
    Harness session that applies the upgrade notes; the automatic update does not (nobody is there)."""
    from ..crons import maxxing_bin
    extra = ["--smart"] if smart else []
    if os.environ.get("MAXXING_SPAWN") == "direct":
        subprocess.Popen([sys.executable, "-m", "maxxing", "update", *extra], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return
    r = subprocess.run(["systemd-run", "--collect", "--quiet", "--unit", "maxxing-update", maxxing_bin(), "update", *extra],
                       capture_output=True, text=True, timeout=15)
    invalidate_version()
    if r.returncode != 0:
        if "already" in r.stderr.lower() or "exists" in r.stderr.lower():
            raise _err(409, "update_running", "An update is already running")
        raise _err(502, "spawn_failed", r.stderr.strip()[:300])


class AutoUpdateIn(BaseModel):
    enabled: bool


@router.put("/system/auto-update")
async def set_auto_update(body: AutoUpdateIn):
    """Settings -> Updates: update by itself while nobody is on the interface and nothing runs."""
    config.update_config(auto_update=body.enabled)
    return {"ok": True, "enabled": body.enabled}


@router.post("/system/update")
async def update():
    try:
        await asyncio.to_thread(_spawn_update)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise _err(502, "spawn_failed", str(e)) from None
    return {"ok": True}


# ---- smart update: preflight before, Harness during, verification after ----------------------------
@router.get("/system/update/preflight")
async def update_preflight(refresh: bool = False):
    """What the next update does to this server (simulated on a throw-away copy). Cached until the code, the
    target or the unsaved changes change; refresh=True fetches the latest version first."""
    from .. import smartupdate
    if not refresh:
        cached = await asyncio.to_thread(smartupdate.cached_preflight)
        if cached:
            return cached
    rep = await asyncio.to_thread(smartupdate.preflight, None, refresh)
    if not rep.get("ok"):
        raise _err(502, "preflight_failed", rep.get("error") or "preflight failed")
    return rep


@router.post("/system/update/assist")
async def update_assist():
    """Open the Harness session that adapts this server's changes, then updates -> {session}."""
    from .. import smartupdate
    from ..sessions.service import SessionError
    try:
        s = await asyncio.to_thread(smartupdate.start_assist)
    except SessionError as e:
        raise _err(e.status, e.code, e.message) from None
    return {"session": s}


@router.get("/system/update/report")
async def update_report():
    from .. import smartupdate
    return {"report": await asyncio.to_thread(smartupdate.last_report)}


@router.post("/system/update/verify")
async def update_verify():
    from .. import smartupdate
    return {"report": await asyncio.to_thread(smartupdate.verify)}


@router.post("/system/update/fix")
async def update_fix():
    """Open a Harness session that fixes what the last verification found broken -> {session}."""
    from .. import smartupdate
    from ..sessions import service
    rep = await asyncio.to_thread(smartupdate.last_report)
    if not rep or rep.get("ok"):
        raise _err(409, "nothing_to_fix", "The last verification found nothing broken")
    try:
        s = await asyncio.to_thread(service.create_session, smartupdate.update_topic_path(),
                                    smartupdate.fix_prompt(rep), f"Fix after the update to {rep.get('version')}")
    except service.SessionError as e:
        raise _err(e.status, e.code, e.message) from None
    return {"session": s}


@router.get("/system/changelog")
def changelog(limit: int = Query(10, ge=1, le=500)):
    from .. import changelog as cl
    return cl.entries(limit)


@router.get("/usage")
async def usage(force: bool = False):
    return await asyncio.to_thread(health.usage, force)


# ---- license: daily ping (version + service up + a few health codes) -------------------------
_ping_task: asyncio.Task | None = None


async def _ping_loop() -> None:
    from .. import license
    await asyncio.sleep(60)
    while True:
        try:
            if license.enabled() and license.ping_due():
                await asyncio.to_thread(license.ping, await asyncio.to_thread(license.health_summary))
        except Exception as e:  # noqa: BLE001 - offline or server down: try again later
            log.info("license ping failed: %s", e)
        try:
            from .. import register
            if register.heartbeat_due():
                await asyncio.to_thread(register.heartbeat)
        except Exception as e:  # noqa: BLE001 - offline or server down: try again later
            log.info("register signal failed: %s", e)
        await asyncio.sleep(3600)


_after_task: asyncio.Task | None = None


async def _after_update() -> None:
    """Just updated (marker written by `maxxing update`): verify extensions and customizations, and for the
    Update button open the upgrade-notes session. Waits a little so the server is fully up."""
    from .. import smartupdate
    await asyncio.sleep(float(os.environ.get("MAXXING_AFTER_UPDATE_DELAY", "15")))
    try:
        await asyncio.to_thread(smartupdate.after_update)
    except Exception as e:  # noqa: BLE001
        log.warning("after-update checks failed: %s", e)


async def startup() -> None:
    global _ping_task, _after_task
    if os.environ.get("MAXXING_LICENSE_PING", "1") != "0":
        _ping_task = asyncio.create_task(_ping_loop())
    _after_task = asyncio.create_task(_after_update())
    from .. import auto_update
    auto_update.start(lambda: _spawn_update(smart=False))


async def shutdown() -> None:
    from .. import auto_update
    auto_update.stop()
    if _ping_task:
        _ping_task.cancel()

