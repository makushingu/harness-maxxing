"""JSON API responses are gzipped for direct clients, left to the proxy when there is one."""
from __future__ import annotations

import json


def _many_sessions(client, topic: str, n: int = 12) -> None:
    for i in range(n):
        assert client.post("/api/sessions", json={"path": topic, "title": f"Session {i} " + "x" * 80}).status_code == 200


def test_large_json_is_gzipped(client, topic):
    _many_sessions(client, topic)
    r = client.get("/api/sessions", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in r.headers["vary"]
    assert len(r.json()) == 12                                 # httpx decodes it


def test_same_body_without_gzip_and_behind_a_proxy(client, topic):
    _many_sessions(client, topic)
    plain = client.get("/api/sessions", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in plain.headers
    proxied = client.get("/api/sessions", headers={"Accept-Encoding": "gzip", "X-Forwarded-For": "203.0.113.9"})
    assert "content-encoding" not in proxied.headers          # Caddy (or the user's proxy) compresses
    assert json.loads(plain.content) == json.loads(proxied.content)
    zipped = client.get("/api/sessions", headers={"Accept-Encoding": "gzip"})
    assert zipped.headers["content-encoding"] == "gzip" and zipped.content == plain.content   # same bytes once decoded


def test_small_and_non_json_untouched(client):
    r = client.get("/api/settings", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and "content-encoding" not in r.headers   # < 1 kB
    r = client.get("/api/sessions/nope/events", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 404
