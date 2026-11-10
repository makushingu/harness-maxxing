"""Doctor checks: installed packages vs OSV, Claude Code behind its latest release, skill listing size."""
from __future__ import annotations

import json

from maxxing import cmd_core, depcheck


def test_lockfile_readers(tmp_path):
    uv = tmp_path / "uv.lock"
    uv.write_text('version = 1\n[[package]]\nname = "fastapi"\nversion = "0.143.0"\nsource = { registry = "https://pypi.org/simple" }\n'
                  '[[package]]\nname = "claude-maxxing"\nversion = "2.0.0a33"\nsource = { editable = "." }\n')
    assert depcheck.python_packages(uv) == [("fastapi", "0.143.0")]
    npm = tmp_path / "package-lock.json"
    npm.write_text(json.dumps({"packages": {"": {"name": "web"}, "node_modules/katex": {"version": "0.18.10"},
                                            "node_modules/a/node_modules/@scope/b": {"version": "1.0.0"},
                                            "node_modules/local": {"link": True, "version": "0.0.0"}}}))
    assert depcheck.npm_packages(npm) == [("@scope/b", "1.0.0"), ("katex", "0.18.10")]
    assert depcheck.npm_packages(tmp_path / "missing.json") == []


def test_osv_scan_and_doctor(monkeypatch, tmp_path):
    npm = tmp_path / "package-lock.json"
    npm.write_text(json.dumps({"packages": {"node_modules/katex": {"version": "0.16.47"},
                                            "node_modules/react": {"version": "19.3.1"}}}))
    monkeypatch.setattr(depcheck, "lockfiles", lambda: [("web", "npm", npm)])
    sent = []

    def post(url, body, timeout=30):
        sent.append(body)
        return {"results": [{"vulns": [{"id": "GHSA-238p-pmpm-9mq7"}]} if q["package"]["name"] == "katex" else {}
                            for q in body["queries"]]}
    monkeypatch.setattr(depcheck, "_post_json", post)
    r = depcheck.osv_scan()
    assert r["checked"] == 2 and r["vulnerable"] == [{"where": "web", "ecosystem": "npm", "name": "katex",
                                                      "version": "0.16.47", "ids": ["GHSA-238p-pmpm-9mq7"]}]
    c = cmd_core.check_deps()
    assert c["level"] == "warn" and "katex 0.16.47" in c["detail"]
    monkeypatch.setattr(depcheck, "_post_json", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    assert cmd_core.check_deps()["level"] == "info"


def test_claude_behind():
    assert depcheck.claude_behind("2.1.296", "2.1.302") == 6
    assert depcheck.claude_behind("2.1.302", "2.1.302") == 0
    assert depcheck.claude_behind("2.1.302", "2.1.296") == 0
    assert depcheck.claude_behind("2.1.296", "2.2.3") == 3
    assert depcheck.claude_behind("2.1.296", None) == 0


def test_skill_listing(tmp_path, monkeypatch):
    for i in range(3):
        d = tmp_path / "skills" / f"s{i}"
        d.mkdir(parents=True)
        d.joinpath("SKILL.md").write_text(f"---\nname: s{i}\ndescription: {'x' * 4000}\n  more words\nlicense: MIT\n---\nbody\n")
    st = depcheck.skill_listing([tmp_path / "skills", tmp_path / "none"])
    assert st["count"] == 3 and st["chars"] == 3 * (2 + 4000 + 11)
    monkeypatch.setattr(cmd_core, "skills_target", lambda: tmp_path / "none")
    c = cmd_core.check_skill_listing({"workspace": str(tmp_path / "ws")})
    assert c is None                                                   # no skills in the workspace
    (tmp_path / "ws" / ".claude").mkdir(parents=True)
    (tmp_path / "ws" / ".claude" / "skills").symlink_to(tmp_path / "skills")
    c = cmd_core.check_skill_listing({"workspace": str(tmp_path / "ws")})
    assert c["level"] == "info" and "3 skills" in c["title"] and "disable-model-invocation" in c["fix"]


def test_memory_check(tmp_path, monkeypatch):
    mi = tmp_path / "meminfo"
    monkeypatch.setattr(cmd_core, "MEMINFO", mi)
    mi.write_text("MemTotal:        2014000 kB\nSwapTotal:             0 kB\n")
    c = cmd_core.check_memory()
    assert c["level"] == "warn" and "no swap" in c["title"] and "mkswap" in c["fix"]
    mi.write_text("MemTotal:        2014000 kB\nSwapTotal:       2097148 kB\n")
    assert cmd_core.check_memory()["level"] == "ok"
    mi.write_text("MemTotal:        8000000 kB\nSwapTotal:             0 kB\n")
    assert cmd_core.check_memory()["level"] == "ok"
    mi.write_text("MemTotal:        3960000 kB\nSwapTotal:             0 kB\n")      # a "4 GB" VPS, no swap (audit 2.2)
    assert cmd_core.check_memory()["level"] == "warn"
    mi.write_text("MemTotal:        4194304 kB\nSwapTotal:             0 kB\n")
    assert cmd_core.check_memory()["level"] == "ok"


def test_answers_are_capped_in_size_and_time(monkeypatch):
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import pytest

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            try:
                if self.path == "/big":
                    for _ in range(40):
                        self.wfile.write(b" " * (1 << 16))
                else:                                   # one byte every 0.1 s, forever
                    for _ in range(600):
                        self.wfile.write(b" ")
                        self.wfile.flush()
                        time.sleep(0.1)
            except OSError:
                pass

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    monkeypatch.setattr(depcheck, "ANSWER_MAX", 1 << 20)
    try:
        with pytest.raises(ValueError):
            depcheck._get_json(base + "/big", 2)
        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            depcheck._get_json(base + "/drip", 0.5)
        assert time.monotonic() - t0 < 5
    finally:
        srv.shutdown()
        srv.server_close()
