"""Request body caps before authentication (audit F01): nothing of an anonymous body is read, signed-in bodies are
capped per route, chunked bodies are counted while they stream."""
from __future__ import annotations

import asyncio
import json

import pytest

from maxxing import bodylimit, security

MB = 1024 * 1024


def _call(app, method: str, path: str, *, length: int | None, chunks: list[bytes] | None = None,
          headers: dict[str, str] | None = None, cookie: str | None = None) -> tuple[int, int, dict]:
    """Drive the ASGI app by hand -> (status, bytes handed to the app by receive(), JSON body)."""
    hdrs = [(b"content-type", b"application/json")]
    if length is not None:
        hdrs.append((b"content-length", str(length).encode()))
    for k, v in (headers or {}).items():
        hdrs.append((k.lower().encode(), v.encode()))
    if cookie:
        hdrs.append((b"cookie", f"{security.COOKIE}={cookie}".encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "path": path,
             "raw_path": path.encode(), "query_string": b"", "headers": hdrs, "scheme": "http",
             "server": ("testserver", 80), "client": ("127.0.0.1", 5000), "root_path": ""}
    body = list(chunks if chunks is not None else [b"x" * (length or 0)])
    read = 0
    out: dict = {"status": 0, "body": b""}

    async def receive():
        nonlocal read
        if not body:
            return {"type": "http.disconnect"}
        chunk = body.pop(0)
        read += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": bool(body)}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"")

    asyncio.run(app(scope, receive, send))
    try:
        data = json.loads(out["body"] or b"{}")
    except ValueError:
        data = {}
    return out["status"], read, data


@pytest.fixture
def app(mx):
    from maxxing.app import create_app
    security.set_password("correct horse battery")
    return create_app()


def test_anonymous_json_refused_before_a_byte_is_read(app):
    st, read, data = _call(app, "POST", "/api/sessions", length=2 * MB, headers={"X-Maxxing": "1"})
    assert (st, read, data["error"]) == (401, 0, "auth_required")
    st, read, data = _call(app, "PUT", "/api/files/write", length=2 * MB, headers={"X-Maxxing": "1"})
    assert (st, read) == (401, 0)


def test_login_body_capped_and_csrf_checked_before_reading(app):
    st, read, data = _call(app, "POST", "/api/auth/login", length=2 * MB, headers={"X-Maxxing": "1"})
    assert (st, read, data["error"]) == (413, 0, "too_large")
    st, read, data = _call(app, "POST", "/api/auth/login", length=20, headers={})
    assert (st, read, data["error"]) == (403, 0, "csrf")


def test_chunked_anonymous_body_aborted_while_streaming(app):
    chunks = [b"x" * 16384] * 128                                   # 2 MB, no Content-Length
    st, read, data = _call(app, "POST", "/api/auth/login", length=None, chunks=chunks, headers={"X-Maxxing": "1"})
    assert st == 413 and data["error"] == "too_large"
    assert read <= bodylimit.PUBLIC_MAX + 16384                     # stopped at the cap, not at the end


def test_signed_in_caps_per_route(app):
    cookie = security.make_cookie()
    h = {"X-Maxxing": "1"}
    st, read, _ = _call(app, "PATCH", "/api/tasks/t_x", length=2 * MB, headers=h, cookie=cookie)
    assert (st, read) == (413, 0)                                   # default 1 MB
    chunks = [b"x" * 65536] * 32
    st, read, _ = _call(app, "POST", "/api/tasks", length=None, chunks=chunks, headers=h, cookie=cookie)
    assert st == 413 and read <= bodylimit.DEFAULT_MAX + 65536
    assert bodylimit.cap_for("PUT", "/api/files/write", True) == 16 * MB
    assert bodylimit.cap_for("POST", "/api/sessions/abc/messages", True) == 8 * MB
    assert bodylimit.cap_for("POST", "/api/ext/x/y", True) == 5 * MB
    assert bodylimit.cap_for("POST", "/api/sessions/abc/messages", False) == bodylimit.PUBLIC_MAX


def test_editor_saves_a_large_file(client, mx):
    p = mx["files"] / "big.txt"
    content = "\\" * (2 * MB)                                       # JSON-escaped: 4 MB on the wire
    r = client.put("/api/files/write", json={"path": str(p), "content": content})
    assert r.status_code == 200, r.text
    assert p.stat().st_size == 2 * MB
    r = client.post("/api/sessions", json={"path": "", "message": "y" * (3 * MB)})
    assert r.status_code != 413


def test_webhooks_keep_their_own_cap(client):
    client.cookies.clear()
    r = client.post("/api/hooks/nope", content=b"x" * 100)
    assert r.status_code == 404                                    # public: token checked by the route
