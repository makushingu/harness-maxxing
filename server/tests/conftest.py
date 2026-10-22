"""Shared fixtures: isolated state dir + workspace + files root, fake `claude`, direct spawn,
and a signed-in TestClient. Nothing here touches the real system."""
from __future__ import annotations

import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterator

import pytest

# before importing maxxing: never the real state dir (each test then gets its own, see `mx`)
os.environ.setdefault("MAXXING_STATE", os.path.join(tempfile.gettempdir(), "mx-test-boot-state"))
os.environ["MAXXING_SPAWN"] = "direct"
os.environ["MAXXING_SYSTEM_TZ"] = "0"                # never switch the real system clock
os.environ.setdefault("MAXXING_AUTH_CHECK", "0")     # no background `claude -p` check (tests opt in)
os.environ["MAXXING_CLAUDE_UPDATE"] = "0"          # no background `claude update` (tests call tick())
os.environ["MAXXING_LICENSE_PING"] = "0"           # no call to the cloud (registration heartbeat) from the test servers
os.environ["MAXXING_SHORT_TITLES"] = "0"           # no background title call (tests/test_titles.py opts in)
# run from a Claude session started by Harness: its turn variables would pass through to the fake `claude`
for _var in ("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"):
    os.environ.pop(_var, None)

from fastapi.testclient import TestClient  # noqa: E402

from maxxing import config, security  # noqa: E402


@pytest.fixture(autouse=True)
def _never_the_real_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test, even without `mx`: root's crontab and the default workspace (/root/maxxing) stay
    untouched - a test creating a cron or saving a customization writes into tmp_path instead."""
    monkeypatch.setenv("MAXXING_CRONTAB_FILE", str(tmp_path / "crontab"))
    monkeypatch.setitem(config.DEFAULT_CONFIG, "workspace", str(tmp_path / "default-workspace"))

@pytest.fixture(autouse=True)
def _never_the_real_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`maxxing deps` / uninstall write commands to /usr/local/bin, remove Claude Code from root's home, a fail2ban
    jail, a swap line of /etc/fstab...: in tests every one of those paths is under tmp_path."""
    from maxxing import cmd_core, deps
    fake = tmp_path / "_system"
    monkeypatch.setattr(deps, "LINK_DIR", fake / "usr-local-bin")
    monkeypatch.setattr(deps, "root_home", lambda: fake / "root-home")
    monkeypatch.setattr(cmd_core, "F2B_JAIL", fake / "fail2ban" / "harness-maxxing.local")
    monkeypatch.setattr(cmd_core, "CADDY_ADMIN_DROPIN", fake / "caddy.service.d" / "harness-maxxing-admin.conf")
    monkeypatch.setattr(cmd_core, "FSTAB", fake / "fstab")


@pytest.fixture(autouse=True)
def _fresh_caches() -> Iterator[None]:
    """Short-lived in-process caches (services, trash size, version) never leak between tests."""
    from maxxing import health, trash, widgets
    from maxxing.api import system as system_api
    drops = (health.invalidate_services, trash.invalidate_sizes, system_api.invalidate_version, widgets.invalidate_cards)
    for drop in drops:
        drop()
    yield
    for drop in drops:
        drop()


FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"


@pytest.fixture
def mx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Fresh state/workspace/files_root for one test; returns their paths."""
    state, ws, files = tmp_path / "state", tmp_path / "ws", tmp_path / "files"
    for d in (state, ws, files):
        d.mkdir()
    FAKE_CLAUDE.chmod(FAKE_CLAUDE.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setattr(config, "STATE", state)
    monkeypatch.setenv("MAXXING_STATE", str(state))
    monkeypatch.setenv("MAXXING_SPAWN", "direct")
    monkeypatch.setenv("MAXXING_CLAUDE_BIN", str(FAKE_CLAUDE))
    monkeypatch.setenv("FAKE_CLAUDE_DIR", str(tmp_path / "fake-claude"))
    monkeypatch.setenv("FAKE_CLAUDE_DELAY", "0.02")
    # upload_min_free_mb 0: tmp_path often sits on a small tmpfs; tests/test_uploads.py covers the reserve
    config.save_config({"workspace": str(ws), "files_root": str(files), "upload_min_free_mb": 0})
    return {"state": state, "ws": ws, "files": files, "tmp": tmp_path, "fake_dir": tmp_path / "fake-claude"}


@pytest.fixture
def client(mx: dict) -> Iterator[TestClient]:
    """Signed-in client (cookie + CSRF header), app lifespan running (session watcher)."""
    from maxxing.app import create_app
    security.set_password("correct horse battery")
    with TestClient(create_app()) as c:
        c.cookies.set(security.COOKIE, security.make_cookie())
        c.headers["X-Maxxing"] = "1"
        yield c
        _stop_all(c)


def _stop_all(c: TestClient) -> None:
    try:
        for s in c.get("/api/sessions").json():
            if s["state"] == "running":
                c.post(f"/api/sessions/{s['id']}/stop")
    except Exception:
        pass


@pytest.fixture
def topic(client: TestClient) -> str:
    """Creates project `acme` with topic `blog`; returns the topic path."""
    assert client.post("/api/workspace/projects", json={"name": "acme"}).status_code == 200
    r = client.post("/api/workspace/projects/acme/topics", json={"name": "blog", "description": "The blog"})
    assert r.status_code == 200, r.text
    return r.json()["path"]


def wait_for(pred: Callable[[], object], timeout: float = 20.0, every: float = 0.1) -> object:
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(every)
    raise AssertionError("condition not met in time")


def wait_idle(client: TestClient, sid: str, timeout: float = 20.0) -> dict:
    def done():
        s = client.get(f"/api/sessions/{sid}").json()
        return s if s["state"] != "running" and s["queue"] == 0 else None
    return wait_for(done, timeout)  # type: ignore[return-value]


def all_events(client: TestClient, sid: str) -> list[dict]:
    out, frm = [], 0
    while True:
        r = client.get(f"/api/sessions/{sid}/events", params={"from": frm}).json()
        out += r["events"]
        if r["next"] == frm or not r.get("more"):
            return out
        frm = r["next"]

