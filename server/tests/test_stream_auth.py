"""Open SSE streams follow the sign-in (audit F05): a revoked, expired or rotated cookie closes them before the next
frame is sent."""
from __future__ import annotations

import asyncio
import json

from maxxing import bus, config, security
from maxxing.api import sessions as sessions_api
from maxxing.sessions import store


class _Req:
    def __init__(self, cookie: str):
        self.cookies = {security.COOKIE: cookie}

    async def is_disconnected(self) -> bool:
        return False


async def _rest(gen, timeout: float = 5.0) -> list[str]:
    """Frames until the generator ends (TimeoutError if it never does)."""
    out: list[str] = []

    async def drain():
        async for f in gen:
            out.append(f)
    try:
        await asyncio.wait_for(drain(), timeout)
    except asyncio.TimeoutError:
        out.append("<still open>")
    return out


def test_session_stream_closes_after_sign_out(mx):
    security.set_password("correct horse battery")
    cookie = security.make_cookie()
    meta = store.new_meta("", "Stream")
    store.create(meta)
    log = store.log_path(meta["id"])
    log.write_text(json.dumps({"type": "mx_user", "text": "first", "attachments": [], "at": 1.0}) + "\n")
    size = store.log_size(meta["id"])

    async def run():
        gen = sessions_api._sse(meta["id"], size, _Req(cookie))
        assert (await gen.__anext__()).startswith("retry:")
        security.revoke_cookie(cookie)                                 # sign-out elsewhere
        with open(log, "a") as f:
            f.write(json.dumps({"type": "mx_user", "text": "SECRET next message", "attachments": [], "at": 2.0}) + "\n")
        return await _rest(gen)
    frames = asyncio.run(run())
    assert "<still open>" not in frames
    assert not any("SECRET" in f for f in frames)


def test_session_stream_keeps_a_valid_cookie(mx):
    security.set_password("correct horse battery")
    cookie = security.make_cookie()
    meta = store.new_meta("", "Stream")
    store.create(meta)
    log = store.log_path(meta["id"])
    log.write_text("")

    async def run():
        gen = sessions_api._sse(meta["id"], 0, _Req(cookie))
        await gen.__anext__()
        with open(log, "a") as f:
            f.write(json.dumps({"type": "mx_user", "text": "hello", "attachments": [], "at": 2.0}) + "\n")
        for _ in range(5):
            f = await asyncio.wait_for(gen.__anext__(), 5)
            if "hello" in f:
                await gen.aclose()
                return True
        return False
    assert asyncio.run(run())


def test_global_stream_closes_after_password_change(mx):
    security.set_password("correct horse battery")
    cookie = security.make_cookie()

    async def run():
        bus.bind_loop(asyncio.get_running_loop())
        gen = bus.stream(cookie)
        assert (await gen.__anext__()).startswith("retry:")
        bus.invalidate("tasks")
        first = await asyncio.wait_for(gen.__anext__(), 5)           # still signed in: delivered
        security.set_password("another long password")                # every cookie dies
        bus.invalidate("secret-topic")
        return first, await _rest(gen)
    first, frames = asyncio.run(run())
    assert "tasks" in first
    assert "<still open>" not in frames and not any("secret-topic" in f for f in frames)


def test_stream_auth_rechecks_when_secrets_change(mx):
    security.set_password("correct horse battery")
    cookie = security.make_cookie()
    auth = security.StreamAuth(cookie)
    assert auth.ok() and auth.ok()
    config.set_secret("sessions_not_before", 2 ** 31)                # "sign out every browser"
    assert not auth.ok()
    assert not security.StreamAuth(None).ok()


def test_sse_streams_are_capped_per_sign_in_and_in_total(client, mx, monkeypatch):
    """Audit F01 (stream counter): one sign-in, or all of them together, may hold only so many SSE streams; beyond
    that a clean 429, and a slot comes back however the stream ends (even if its body never started)."""
    import gc
    from maxxing import streamcap
    monkeypatch.setattr(streamcap, "PER_SIGNIN", 3)
    monkeypatch.setattr(streamcap, "TOTAL", 5)
    security.set_password("correct horse battery")
    c1, c2 = security.make_cookie(), security.make_cookie()
    glob = next(r for r in client.app.routes if getattr(r, "path", "") == "/api/stream").endpoint
    meta = store.new_meta("", "Capped")
    store.create(meta)

    async def receive():
        return {"type": "http.disconnect"}

    async def send(_msg):
        pass

    async def end(resp):                                   # the client goes away
        await asyncio.wait_for(resp(scope, receive, send), 5)

    scope = {"type": "http", "method": "GET", "path": "/api/stream", "headers": [], "asgi": {"version": "3.0"}}

    async def run():
        opened = [await glob(_Req(c1)), await sessions_api.stream(meta["id"], _Req(c1), 0),
                  await sessions_api.stream(meta["id"], _Req(c1), 0)]
        assert all(r.status_code == 200 for r in opened)
        over = await glob(_Req(c1))
        assert over.status_code == 429 and json.loads(over.body)["error"] == "too_many_streams"
        assert over.headers["retry-after"]
        assert (await sessions_api.stream(meta["id"], _Req(c1), 0)).status_code == 429    # per sign-in
        opened += [await glob(_Req(c2)), await glob(_Req(c2))]
        assert all(r.status_code == 200 for r in opened[3:])
        assert (await glob(_Req(c2))).status_code == 429                                 # in total
        await end(opened.pop(0))                                                          # slot back
        again = await glob(_Req(c1))
        assert again.status_code == 200
        del again                                                                         # never sent: GC releases
        gc.collect()
        assert streamcap.counts()[0] == 4
        for r in opened:
            await end(r)
        assert streamcap.counts()[0] == 0
    asyncio.run(run())


def test_quiet_running_session_is_polled_less_often(mx, monkeypatch):
    # a running session with nothing new (thinking, a long tool): after QUIET_AFTER_S the stream checks the log every
    # POLL_QUIET_S instead of POLL_RUNNING_S (24 open panes were 240 wake-ups a second)
    security.set_password("correct horse battery")
    cookie = security.make_cookie()
    meta = store.new_meta("", "Quiet")
    store.create(meta)
    store.log_path(meta["id"]).write_text("")
    monkeypatch.setattr(sessions_api, "POLL_RUNNING_S", 0.01)
    monkeypatch.setattr(sessions_api, "POLL_QUIET_S", 0.2, raising=False)
    monkeypatch.setattr(sessions_api, "QUIET_AFTER_S", 0.3, raising=False)
    monkeypatch.setattr(sessions_api, "_read_tick", lambda sid, off, session: ([], off, False, {"id": sid, "state": "running"}))
    probes = {"n": 0}
    real = sessions_api._probe

    def counting(sid):
        probes["n"] += 1
        return real(sid)
    monkeypatch.setattr(sessions_api, "_probe", counting)

    async def run():
        gen = sessions_api._sse(meta["id"], 0, _Req(cookie))
        out = await _rest(gen, 1.5)
        await gen.aclose()
        return out
    out = asyncio.run(run())
    assert out[-1] == "<still open>"
    # ~30 fast ticks in the first 0.3 s, then ~6 quiet ones; without the slow-down ~150
    assert probes["n"] < 60, probes["n"]
