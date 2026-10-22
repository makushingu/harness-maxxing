"""Fixtures shared by the organisation tests (tasks, crons, settings, secrets, system, docs,
dashboard, extensions). Import them explicitly in a test module:

    from _org_helpers import org, client  # noqa: F401

`org`    isolated state dir + workspace + crontab file (never the real system).
`client` TestClient on an app limited to the auth + organisation routers, signed in, with the
         CSRF header set.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maxxing import config, security  # noqa: E402

ORG_ROUTERS = ["auth", "tasks", "crons", "settings", "secrets", "system", "docs", "dashboard", "extensions", "git", "infra", "mcp"]
PASSWORD = "correct-horse"


def _reset_caches() -> None:
    from maxxing import extensions, health
    from maxxing.api import tasks
    tasks._cache.update(sig=None, data=None)
    tasks._synced.update(key=None)
    health._cache.update(at=0.0, data=None)
    health._usage.update(at=0.0, data=None)
    with extensions._lock:
        extensions._registry.clear()
        extensions._cards.clear()
        extensions._scanned = False
        extensions._last_sig = ()
    security._fails.clear()


@pytest.fixture
def org(tmp_path, monkeypatch):
    state, ws = tmp_path / "state", tmp_path / "ws"
    state.mkdir()
    ws.mkdir()
    monkeypatch.setattr(config, "STATE", state)
    monkeypatch.setenv("MAXXING_STATE", str(state))
    monkeypatch.setenv("MAXXING_CRONTAB_FILE", str(tmp_path / "crontab"))
    monkeypatch.setenv("MAXXING_SPAWN", "direct")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config.update_config(workspace=str(ws), files_root=str(tmp_path))
    _reset_caches()
    yield SimpleNamespace(tmp=tmp_path, state=state, ws=ws, crontab=tmp_path / "crontab")
    _reset_caches()


@pytest.fixture
def client(org, monkeypatch):
    from fastapi.testclient import TestClient
    from maxxing import app as app_module
    monkeypatch.setattr(app_module, "ROUTERS", ORG_ROUTERS)
    security.set_password(PASSWORD)
    with TestClient(app_module.create_app()) as c:
        r = c.post("/api/auth/login", json={"password": PASSWORD}, headers={"X-Maxxing": "1"})
        assert r.status_code == 200, r.text
        c.headers["X-Maxxing"] = "1"
        yield c
