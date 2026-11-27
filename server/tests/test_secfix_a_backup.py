"""Regression test of the security review of 2026-11-24: a restore on a server in use (backup.py)."""
from __future__ import annotations

import json

from test_backup import _in_use, mx_state, ws  # noqa: F401
from maxxing import backup


def test_restore_on_a_server_in_use_keeps_its_own_backup_list(ws, mx_state):
    """The list of what the next backups send out is not taken from the repository; a new server takes it."""
    mine = list(backup._settings()["include"])
    blob = {f"{backup.META_DIR}/config.json": json.dumps({"backup": {"schedule": "0 5 * * *",
                                                                      "include": ["**/*"]}}).encode()}
    backup._apply(dict(blob))                        # a new server: all of it
    assert backup._settings()["include"] == ["**/*"]
    backup.update_settings(include=mine)
    _in_use()
    backup._apply(dict(blob))
    assert backup._settings()["include"] == mine and backup._settings()["schedule"] == "0 5 * * *"
