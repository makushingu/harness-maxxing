from __future__ import annotations

import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from maxxing import config


@pytest.fixture
def spa(mx: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, bytes]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>")
    js = b"console.log('hello');" * 100
    (dist / "assets" / "app-abc.js").write_bytes(js)
    (dist / "assets" / "app-abc.js.br").write_bytes(b"BROTLI-TWIN")  # content irrelevant: only routing is tested
    (dist / "assets" / "plain-abc.js").write_bytes(js)
    monkeypatch.setattr(config, "WEB_DIST", dist)
    from maxxing.app import create_app
    with TestClient(create_app()) as c:
        yield c, js


def test_brotli_twin_served_when_accepted(spa):
    c, _ = spa
    r = c.get("/assets/app-abc.js", headers={"Accept-Encoding": "gzip, deflate, br, zstd"})
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "br"
    assert r.headers["content-type"].startswith("text/javascript")
    assert "Accept-Encoding" in r.headers["vary"]
    assert "immutable" in r.headers["cache-control"]


def test_plain_file_when_br_refused_or_missing(spa):
    c, js = spa
    for enc in ("gzip", "br;q=0, gzip"):
        r = c.get("/assets/app-abc.js", headers={"Accept-Encoding": enc})
        assert r.status_code == 200 and "content-encoding" not in r.headers
        assert zlib.crc32(r.content) == zlib.crc32(js)
        assert "Accept-Encoding" in r.headers["vary"]
    r = c.get("/assets/plain-abc.js", headers={"Accept-Encoding": "br"})
    assert r.status_code == 200 and "content-encoding" not in r.headers and r.content == js


def test_app_page_allows_only_its_own_scripts(spa, tmp_path):
    import base64
    import hashlib
    c, _ = spa
    boot = "window.__mx=1"
    (config.WEB_DIST / "index.html").write_text(f"<!doctype html><script>{boot}</script><script type=module src=/assets/app-abc.js></script>")
    csp = c.get("/sessions").headers["content-security-policy"]
    h = base64.b64encode(hashlib.sha256(boot.encode()).digest()).decode()
    assert f"script-src 'self' 'sha256-{h}'" in csp and "frame-ancestors 'self'" in csp
    assert csp.count("sha256-") == 1                  # the external module needs no hash


def test_index_gzipped_without_a_proxy(client):
    r = client.get("/", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip" and "<html" in r.text.lower()
    assert "content-security-policy" in r.headers and r.headers["cache-control"] == "no-store"
    r = client.get("/", headers={"Accept-Encoding": "gzip", "X-Forwarded-For": "1.2.3.4"})
    assert "content-encoding" not in r.headers                      # behind Caddy: its `encode` compresses
