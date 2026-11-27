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


def test_a_second_restore_keeps_held_code_off(ws, mx_state):
    """GHSA-r5wh-pw6w-8xmc: restoring the same data twice leaves the held job and the held extension off."""
    import pytest
    from maxxing import config
    crons = pytest.importorskip("maxxing.crons")
    jobs = {"jobs": [{"id": "j1", "name": "Pushed", "schedule": "0 1 * * *", "kind": "shell", "command": "id",
                      "enabled": True}]}
    files = {f"{backup.META_DIR}/crons/jobs.json": json.dumps(jobs).encode(),
             "extensions/probe/api.py": b"def card(ctx):\n    return {'blocks': []}\n",
             f"{backup.META_DIR}/config.json": json.dumps({"extensions": {"disabled": []}}).encode()}
    _in_use()
    first = backup._apply(dict(files))
    assert first["held"]["crons"] == ["Pushed"] and first["held"]["extensions"] == ["probe"]
    backup._apply(dict(files))
    assert not crons.list_jobs()[0]["enabled"]
    assert "probe" in config.load_config()["extensions"]["disabled"]


def test_restore_on_a_server_in_use_keeps_the_members_of_its_groups(ws, mx_state):
    """A group of this server keeps its members, its trust setting and its limits; a group new here comes back
    without trust between its members."""
    _in_use()
    mine, new = (f"projects/acme/groups/{n}/group.json" for n in ("team", "other"))
    local = {"name": "team", "members": [{"path": "projects/acme/topics/blog/agents/a"}], "trust_members": False,
             "limits": {"turns": 5}}
    (ws / mine).parent.mkdir(parents=True)
    (ws / mine).write_text(json.dumps(local))
    pushed = {"name": "team 2", "members": [{"path": "projects/acme/topics/blog/agents/a"},
                                            {"path": "projects/acme/topics/blog/agents/spy"}],
              "trust_members": True, "limits": {"turns": 9999}}
    r = backup._apply({mine: json.dumps(pushed).encode(), new: json.dumps(pushed).encode()})
    a, b = (json.loads((ws / rel).read_text()) for rel in (mine, new))
    assert a["name"] == "team 2" and a["members"] == local["members"] and a["trust_members"] is False
    assert a["limits"] == {"turns": 5}
    assert b["trust_members"] is False and "limits" not in b
    assert {mine, new} <= set(r["held"]["rules"])
