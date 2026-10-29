"""Server speed fundamentals: cached secrets / workspace files / session ids, inotify wake-ups of the session streams
and of the turn-end watcher (with the polling fallback), the watcher stamp, lock file pruning, log clipping of
thinking signatures, the nightly upkeep, the feed watcher connection and search.db reclaim."""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import sqlite3
import threading
import time

from maxxing import config, feed, search, security, workspace
from maxxing.api import sessions as sessions_api
from maxxing.sessions import clip, maintenance, service, store, wake


class _Req:
    def __init__(self, cookie: str):
        self.cookies = {security.COOKIE: cookie}

    async def is_disconnected(self) -> bool:
        return False


# ---- secrets.json ----------------------------------------------------------------------------
def test_secrets_are_cached_but_copied_and_follow_every_write(mx):
    config.set_secret("a", "1")
    s = config.load_secrets()
    s["a"] = "changed by a caller"
    s["nested"] = {"x": 1}
    assert config.load_secrets() == {"a": "1"}                         # the cache is never handed out
    config.set_secret("b", "2")
    assert config.load_secrets() == {"a": "1", "b": "2"}
    # another process (the CLI) rewrites the file: atomic rename, new inode
    p = config.secrets_path()
    tmp = p.with_name("other.tmp")
    tmp.write_text(json.dumps({"a": "from the cli"}))
    os.replace(tmp, p)
    assert config.load_secrets() == {"a": "from the cli"}
    p.unlink()
    assert config.load_secrets() == {}


def test_cookie_check_does_not_parse_secrets_each_time(mx, monkeypatch):
    security.set_password("correct horse battery")
    cookie = security.make_cookie()
    assert security.cookie_valid(cookie)
    calls = {"n": 0}
    real = config._document

    def counting(path):
        calls["n"] += 1
        return real(path)
    monkeypatch.setattr(config, "_document", counting)
    for _ in range(50):
        assert security.cookie_valid(cookie)
    assert calls["n"] == 0
    security.revoke_cookie(cookie)                                     # a write: seen at once
    assert not security.cookie_valid(cookie)


# ---- workspace files ---------------------------------------------------------------------------
def test_workspace_descriptions_and_settings_are_cached_until_they_change(mx, monkeypatch):
    workspace.create_project("acme", "first")
    workspace.create_topic("acme", "blog", "the blog")
    monkeypatch.setattr(workspace, "RACY_S", 0.0)
    workspace._files.clear()
    reads = {"n": 0}
    real = workspace._parse_description

    def counting(f):
        reads["n"] += 1
        return real(f)
    monkeypatch.setattr(workspace, "_parse_description", counting)
    assert workspace.list_topics()[0]["description"] == "the blog"
    workspace.tree()
    n = reads["n"]
    workspace.tree()
    workspace.list_topics()
    assert reads["n"] == n                                             # nothing changed: nothing parsed again
    workspace.update_topic("acme", "blog", description="new words", permission_mode="acceptEdits")
    t = workspace.get_topic("acme", "blog")
    assert t["description"] == "new words" and t["permission_mode"] == "acceptEdits"
    meta = workspace._folder_meta(workspace.project_dir("acme") / "topics" / "blog")
    meta["permission_mode"] = "default"                                 # a caller's copy
    assert workspace.topic_permission_mode("projects/acme/topics/blog") == "acceptEdits"


# ---- session ids and lock files ----------------------------------------------------------------
def test_session_ids_are_kept_and_follow_the_folder(mx, monkeypatch):
    a = store.create(store.new_meta("", "a"))["id"]
    assert store.list_ids() == [a]
    monkeypatch.setattr(store, "IDS_RACY_S", 0.0)
    listed = {"n": 0}
    real = os.scandir

    def counting(p):
        listed["n"] += 1
        return real(p)
    monkeypatch.setattr(store.os, "scandir", counting)
    store.list_ids()
    n = listed["n"]
    for _ in range(20):
        assert store.list_ids() == [a]
    assert listed["n"] == n                                            # the folder did not change: not listed again
    b = store.new_meta("", "b")                                        # written by another process (trash restore)
    (store.sessions_dir() / f"{b['id']}.json").write_text(json.dumps(b))
    assert sorted(store.list_ids()) == sorted([a, b["id"]])
    store.remove(a)
    assert store.list_ids() == [b["id"]]


def _old(path, age: float = 7200) -> None:
    t = time.time() - age
    os.utime(path, (t, t))


def test_prune_locks_removes_only_unused_lock_files(mx):
    d = store.sessions_dir()
    gone = "00000000-0000-4000-8000-000000000001"                     # session deleted, files left behind
    for ext in (".lock", ".run"):
        (d / f"{gone}{ext}").touch()
        _old(d / f"{gone}{ext}")
    idle = store.new_meta("", "idle")
    idle.update(updated=time.time() - 7200, finished_at=time.time() - 7200)
    store.create(idle)
    fd = store.hold_run_lock(idle["id"])                               # a run lock held: kept
    os.close(fd)
    running = store.new_meta("", "running")
    running.update(state="running", updated=time.time() - 7200)
    store.create(running)
    busy = store.new_meta("", "busy")                                 # idle, but its lock is held right now
    busy.update(updated=time.time() - 7200)
    store.create(busy)
    for sid in (idle["id"], running["id"], busy["id"]):
        (d / f"{sid}.run").touch()
        for ext in (".lock", ".run"):
            _old(d / f"{sid}{ext}")
    held = os.open(d / f"{busy['id']}.run", os.O_RDWR)
    fcntl.flock(held, fcntl.LOCK_EX)
    try:
        assert store.prune_locks() == 5                                # gone x2, idle x2, busy's .lock
    finally:
        os.close(held)
    left = sorted(p.name for p in d.iterdir() if p.suffix in (".lock", ".run"))
    assert left == sorted([f"{running['id']}.lock", f"{running['id']}.run", f"{busy['id']}.run"])
    assert not store.runner_alive(idle["id"], {})                      # no file: nobody holds it (none created)
    assert not (d / f"{idle['id']}.run").exists()
    store.update(idle["id"], title="still editable")                   # the lock file comes back when needed
    assert store.read(idle["id"])["title"] == "still editable"


def test_a_waiter_on_a_pruned_lock_file_locks_the_new_one(mx):
    meta = store.new_meta("", "s")
    meta.update(updated=time.time() - 7200)
    store.create(meta)
    sid, d = meta["id"], store.sessions_dir()
    path = d / f"{sid}.lock"
    _old(path)
    # a pruner holds the old file while an edit waits on it, then removes it
    fd = os.open(path, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    got: list[int] = []

    def editor():
        with store.edit(sid) as m:
            got.append(os.stat(path).st_ino)
            m["title"] = "edited"
    t = threading.Thread(target=editor)
    t.start()
    time.sleep(0.2)
    old_ino = os.fstat(fd).st_ino
    path.unlink()
    os.close(fd)
    t.join(5)
    assert got and store.read(sid)["title"] == "edited"
    assert path.exists()                                               # the edit used a fresh lock file
    assert got[0] == os.stat(path).st_ino != old_ino


# ---- inotify wake-ups ----------------------------------------------------------------------------
def _stream_session(mx_running: bool = False) -> tuple[str, str]:
    security.set_password("correct horse battery")
    cookie = security.make_cookie()
    meta = store.new_meta("", "Stream")
    store.create(meta)
    store.log_path(meta["id"]).write_text("")
    return meta["id"], cookie


async def _first_events(gen, timeout: float) -> float | None:
    """Seconds until the first `events` frame (None if none came within timeout)."""
    t0 = time.monotonic()

    async def go():
        async for f in gen:
            if f.startswith("event: events"):
                return time.monotonic() - t0
    try:
        return await asyncio.wait_for(go(), timeout)
    except asyncio.TimeoutError:
        return None


def _append(sid: str, text: str) -> None:
    with open(store.log_path(sid), "a") as f:
        f.write(json.dumps({"type": "mx_user", "text": text, "attachments": [], "at": time.time()}) + "\n")


def test_stream_is_woken_by_inotify(mx, monkeypatch):
    sid, cookie = _stream_session()
    monkeypatch.setattr(sessions_api, "POLL_IDLE_S", 5.0)              # polling alone would take 5 s
    monkeypatch.setattr(sessions_api, "WAKE_RUNNING_S", 5.0)

    async def run():
        assert wake.start()
        for _ in range(100):
            if wake.active():
                break
            await asyncio.sleep(0.02)
        assert wake.active()
        gen = sessions_api._sse(sid, 0, _Req(cookie))
        await gen.__anext__()                                          # retry:
        await gen.__anext__()                                          # the first state frame
        asyncio.get_running_loop().call_later(0.3, _append, sid, "hello")
        took = await _first_events(gen, 3.0)
        await gen.aclose()
        wake.stop()
        return took
    took = asyncio.run(run())
    assert took is not None and took < 0.3 + 0.5, took


def test_stream_polls_when_inotify_is_off(mx, monkeypatch):
    sid, cookie = _stream_session()
    monkeypatch.setattr(wake, "ENABLED", False)
    monkeypatch.setattr(sessions_api, "POLL_IDLE_S", 0.2)

    async def run():
        assert not wake.start() and wake.mark(sid) is None
        gen = sessions_api._sse(sid, 0, _Req(cookie))
        await gen.__anext__()
        await gen.__anext__()
        asyncio.get_running_loop().call_later(0.2, _append, sid, "hello")
        took = await _first_events(gen, 3.0)
        await gen.aclose()
        return took
    took = asyncio.run(run())
    assert took is not None and took < 1.5, took


def test_turn_end_watcher_is_woken_by_inotify(mx, monkeypatch):
    meta = store.new_meta("", "turns")
    store.create(meta)
    sid = meta["id"]
    ended: list[float] = []
    service.on_turn_end(lambda s, r: ended.append(time.monotonic()))

    async def run():
        service.start_watcher(interval=5.0)                            # polling alone: 5 s
        for _ in range(100):
            if wake.active() and sid in service._known:
                break
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.2)
        t0 = time.monotonic()
        await asyncio.to_thread(store.update, sid, turns=1, finished_at=time.time())
        for _ in range(150):
            if ended:
                break
            await asyncio.sleep(0.02)
        await service.stop_watcher()
        return ended[0] - t0 if ended else None
    try:
        took = asyncio.run(run())
    finally:
        service._turn_cbs.pop()
    assert took is not None and took < 0.5, took


# ---- session-watcher.json -------------------------------------------------------------------------
def test_watcher_stamp_is_written_only_when_something_changed(mx, monkeypatch):
    monkeypatch.setattr(service, "PASS_STAMP_S", 0.0)
    monkeypatch.setattr(wake, "ENABLED", False)
    meta = store.new_meta("", "stamp")
    store.create(meta)
    p = config.STATE / "session-watcher.json"

    async def run():
        service.start_watcher(interval=0.05)
        for _ in range(100):
            if p.exists():
                break
            await asyncio.sleep(0.02)
        first = p.stat().st_mtime_ns
        await asyncio.sleep(0.5)                                       # ~10 quiet passes
        quiet = p.stat().st_mtime_ns
        await asyncio.to_thread(store.update, meta["id"], title="renamed")
        await asyncio.sleep(0.5)
        changed = p.stat().st_mtime_ns
        await service.stop_watcher()
        return first, quiet, changed
    first, quiet, changed = asyncio.run(run())
    assert quiet == first
    assert changed > quiet
    raw = p.read_text()
    assert "\n" not in raw and json.loads(raw)["at"] > 0               # compact, no indent


# ---- log clipping ------------------------------------------------------------------------------
def _thinking_line(sig: str = "S" * 600) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": "let me think", "signature": sig},
        {"type": "redacted_thinking", "data": "D" * 300},
        {"type": "tool_use", "name": "Write", "input": {"file_path": "/x", "content": "y" * (clip.INPUT_MAX + 50)}},
    ]}}


def test_thinking_signatures_are_dropped_at_write_time(mx):
    ev = _thinking_line()
    assert clip.clip_event(ev)
    blocks = ev["message"]["content"]
    assert blocks[0] == {"type": "thinking", "thinking": "let me think"}   # the text the UI shows is kept
    assert "data" not in blocks[1]
    assert blocks[2]["input"]["content"].endswith("characters in total]") and blocks[2]["mx_clipped"]
    small = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": "short", "signature": "abc"}]}})
    assert len(small) < clip.RESULT_MAX and "signature" not in clip.clip_line(small)


def test_nightly_upkeep_compacts_changed_logs_and_prunes_locks(mx):
    meta = store.new_meta("", "old log")
    meta.update(updated=time.time() - 7200, finished_at=time.time() - 7200)
    store.create(meta)
    sid = meta["id"]
    lines = [json.dumps({"type": "assistant", "message": {"content": [
        {"type": "thinking", "thinking": f"step {i}", "signature": "S" * 500}]}}) for i in range(20)]
    store.log_path(sid).write_text("\n".join(lines) + "\n")
    before = store.log_size(sid)
    _old(store.sessions_dir() / f"{sid}.lock")
    res = maintenance.run()
    assert res["compacted"] == 1 and res["saved"] > 0 and store.log_size(sid) < before / 3
    assert "signature" not in store.log_path(sid).read_text()
    assert not (store.sessions_dir() / f"{sid}.lock").exists()
    assert maintenance.run()["compacted"] == 0                          # unchanged since: not read again
    events = service.read_events(sid, 0)[0]
    assert [e["text"] for e in events if e.get("type") == "thinking"][:2] == ["step 0", "step 1"]


# ---- feed watcher and search.db --------------------------------------------------------------------
def test_feed_watcher_reuses_one_connection(mx, monkeypatch):
    feed.post("one", source="custom")
    first = feed.watch_id()
    opened = {"n": 0}
    real = sqlite3.connect

    def counting(*a, **kw):
        opened["n"] += 1
        return real(*a, **kw)
    monkeypatch.setattr(feed.sqlite3, "connect", counting)
    for _ in range(5):
        assert feed.watch_id() == first
    feed.post("two", source="custom")
    opened["n"] = 0
    second = feed.watch_id()
    assert second != first and second == feed.last_id()
    assert feed.watch_id() == second


def test_search_db_free_pages_are_reclaimed(mx, monkeypatch):
    monkeypatch.setattr(search, "VACUUM_MIN_BYTES", 0)
    con = search._db()
    with search._lock:
        con.executemany("INSERT INTO items(src, kind, ref, body) VALUES ('x', 'file', 'r', ?)",
                        [("word " * 2000,) for _ in range(300)])
        con.commit()
        con.execute("DELETE FROM items WHERE src='x'")
        con.commit()
        search.checkpoint(con)
    free = con.execute("PRAGMA freelist_count").fetchone()[0]
    assert free > 0
    assert search.reclaim(con)
    assert con.execute("PRAGMA freelist_count").fetchone()[0] < free / 4
    assert not search.reclaim(con)                                     # at most once a day
