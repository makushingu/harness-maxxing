"""Nightly upkeep of the session files, in a background thread of the server.

Every night at RUN_AT (server local time):
- the logs written since the last pass are compacted like `maxxing sessions compact-logs` (logs written before the
  runner clipped at write time, thinking signatures; a running session is skipped and retried the next night);
- the `.lock` / `.run` files of sessions idle for an hour are removed (store.prune_locks).
State: <state>/sessions-maintenance.json {at, retry: [ids]} (when the last pass started, sessions skipped).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta

from .. import config
from . import store

log = logging.getLogger("maxxing.sessions.maintenance")

RUN_AT = (4, 30)              # local time of the nightly pass
_started = False


def _state_path():
    return config.STATE / "sessions-maintenance.json"


def run() -> dict:
    """One pass -> {compacted, saved (bytes), running, locks}."""
    from . import service
    st = config.read_json(_state_path(), {}) or {}
    since = float(st.get("at") or 0) if isinstance(st, dict) else 0.0
    retry = set(st.get("retry") or []) if isinstance(st, dict) else set()
    t0 = time.time()
    out = {"compacted": 0, "saved": 0, "running": 0, "locks": 0}
    skipped: list[str] = []
    for sid in sorted(store.list_ids()):
        try:
            if os.stat(store.log_path(sid)).st_mtime < since and sid not in retry:
                continue                                # untouched since the last pass: already compact
        except (OSError, KeyError):
            continue
        try:
            r = service.compact_log(sid)
        except Exception:                               # one bad log never stops the others
            log.exception("compacting the log of %s failed", sid)
            continue
        if r["status"] == "running":
            out["running"] += 1
            skipped.append(sid)
        elif r["status"] == "compacted":
            out["compacted"] += 1
            out["saved"] += r["before"] - r["after"]
    out["locks"] = store.prune_locks()
    try:
        config.write_json(_state_path(), {"at": t0, "retry": skipped})
    except OSError:
        log.warning("cannot write %s", _state_path(), exc_info=True)
    return out


def _seconds_to_next(now: datetime) -> float:
    nxt = now.replace(hour=RUN_AT[0], minute=RUN_AT[1], second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def start_background() -> None:
    """Once per process: the nightly pass."""
    global _started
    if _started or os.environ.get("MAXXING_SESSION_MAINTENANCE") == "0":
        return
    _started = True

    def loop() -> None:
        while True:
            time.sleep(_seconds_to_next(datetime.now()))
            try:
                res = run()
                if res["compacted"] or res["locks"]:
                    log.info("session files upkeep: %s", res)
            except Exception:
                log.exception("session files upkeep failed")
            time.sleep(60)                              # never twice in the same minute
    threading.Thread(target=loop, name="session-upkeep", daemon=True).start()
