from __future__ import annotations

import json

from maxxing import changelog, config, memory, stats
from maxxing.sessions import store


def _session(path: str, title: str, *, tokens: bool = True, results: list[dict] | None = None) -> str:
    m = store.new_meta(path, title)
    if not tokens:
        m.pop("tokens")
    store.create(m)
    with open(store.log_path(m["id"]), "a") as f:
        for u in results or []:
            f.write(json.dumps({"type": "result", "total_cost_usd": 0.01, "usage": u}) + "\n")
    return m["id"]


def test_add_usage_and_stats(client, mx):
    a = _session("projects/acme/topics/blog", "A")
    with store.edit(a) as m:
        store.add_usage(m, {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100,
                            "cache_creation_input_tokens": 1}, 0.5, 1_700_000_000)
        m["cost_usd"], m["turns"] = 0.5, 1
    # an older session without counters: backfilled from its log
    b = _session("projects/acme/topics/shop", "B", tokens=False,
                 results=[{"input_tokens": 1, "output_tokens": 2}, {"input_tokens": 3, "output_tokens": 4}])
    _session("", "Root")
    r = client.get("/api/stats/tokens?force=1").json()
    assert r["totals"]["input"] == 14 and r["totals"]["output"] == 11 and r["totals"]["total"] == 126
    assert r["totals"]["sessions"] == 3
    acme = next(p for p in r["projects"] if p["name"] == "acme")
    assert acme["total"] == 126 and acme["sessions"] == 2
    assert [t["path"] for t in r["topics"]][:2] == ["projects/acme/topics/blog", "projects/acme/topics/shop"]
    assert r["sessions"][0]["id"] == a and r["sessions"][0]["cost_usd"] == 0.5
    assert r["days"] and r["days"][0]["tokens"] == 116
    assert store.read(b)["tokens"] == {"input": 4, "output": 6, "cache_read": 0, "cache_write": 0}
    assert stats.tokens()["at"] == r["at"]                     # cached


def test_memory_files_limit_and_settings(client, mx):
    ws = config.workspace()
    (ws / "memory.md").write_text("# Global\n" + "- x\n" * 10)
    t = ws / "projects" / "acme" / "topics" / "blog"
    t.mkdir(parents=True)
    (t / "memory.md").write_text("line\n" * 250)
    r = client.get("/api/memory").json()
    assert r["max_lines"] == 200
    by = {f["path"]: f for f in r["files"]}
    assert by["memory.md"]["lines"] == 11 and not by["memory.md"]["over"]
    assert by["projects/acme/topics/blog/memory.md"]["over"] and by["projects/acme/topics/blog/memory.md"]["level"] == "topic"

    assert client.put("/api/settings", json={"memory_max_lines": 10}).status_code == 400
    assert client.put("/api/settings", json={"memory_max_lines": 0}).json()["memory_max_lines"] == 0
    assert not any(f["over"] for f in client.get("/api/memory").json()["files"])
    assert "No line limit" in memory.compact_prompt(0) and "at most 300 lines" in memory.compact_prompt(300)


def test_changelog_parse():
    assert changelog.normalize("2.0.0-alpha.6") == changelog.normalize("2.0.0a6") == "2.0.0a6"
    assert changelog.normalize("v2.1.0") == "2.1.0"
    e = changelog.parse("# Changelog\n\nintro\n\n## 2.0.0-alpha.6 - unreleased\n\n- **A**: b\n\n## 2.0.0-alpha.5\n\n- c\n")
    assert [x["version"] for x in e] == ["2.0.0-alpha.6", "2.0.0-alpha.5"]
    assert e[0]["label"] == "unreleased" and e[0]["body"] == "- **A**: b" and e[1]["label"] == ""


def test_changelog_endpoint(client):
    r = client.get("/api/system/changelog?limit=2").json()
    assert r["version"] and 1 <= len(r["entries"]) <= 2 and r["entries"][0]["body"]


def test_context_window_backfilled_from_log(client, mx):
    from maxxing.sessions import service
    m = store.new_meta("", "Old")
    m["turns"] = 1
    store.create(m)
    with open(store.log_path(m["id"]), "a") as f:
        f.write(json.dumps({"type": "result", "usage": {}, "modelUsage": {
            "claude-x": {"costUSD": 0.1, "contextWindow": 1000000},
            "claude-haiku": {"costUSD": 0.01, "contextWindow": 200000}}}) + "\n")
    assert service.get_session(m["id"])["context_window"] == 1000000
    assert store.read(m["id"])["context_window"] == 1000000
    assert store.context_window_of({"modelUsage": {"a": {"contextWindow": 200000}}}, "a") == 200000
    assert store.context_window_of({}) is None


def test_known_windows_per_model(client, mx):
    from maxxing.sessions import service
    store.record_windows({"modelUsage": {"claude-a": {"contextWindow": 1000000}, "claude-b": {"contextWindow": 200000}, "x": "bad"}})
    store.record_windows({"modelUsage": {"claude-b": {"contextWindow": 400000}}})
    assert store.known_windows() == {"claude-a": 1000000, "claude-b": 400000}
    service._models_cache = (0, [])
    by = {m["id"]: m for m in service.models()}
    assert all("context_window" in m for m in by.values())


def test_models_learn_windows_from_logs(client, mx):
    from maxxing.sessions import service
    sid = _session("", "W")
    with open(store.log_path(sid), "a") as f:
        f.write(json.dumps({"type": "assistant", "message": {"model": "claude-zeta-9"}}) + "\n")
        f.write(json.dumps({"type": "result", "modelUsage": {"claude-zeta-9": {"costUSD": 1, "contextWindow": 1000000}}}) + "\n")
    service._models_cache = (0, [])
    assert next(m for m in service.models() if m["id"] == "claude-zeta-9")["context_window"] == 1000000


def test_models_scan_only_new_bytes(client, mx, monkeypatch):
    from maxxing.sessions import service
    sid = _session("", "Inc")
    log = store.log_path(sid)
    with open(log, "a") as f:
        f.write(json.dumps({"type": "assistant", "message": {"model": "claude-eta-1"}}) + "\n")
    service._models_cache = (0, [])
    assert "claude-eta-1" in {m["id"] for m in service.models()}
    reads = []
    real = open
    monkeypatch.setattr("builtins.open", lambda f, *a, **k: (reads.append(str(f)), real(f, *a, **k))[1])
    service._models_cache = (0, [])
    assert "claude-eta-1" in {m["id"] for m in service.models()}      # remembered, log not reopened
    assert str(log) not in reads
    monkeypatch.setattr("builtins.open", real)
    with open(log, "a") as f:
        f.write(json.dumps({"type": "assistant", "message": {"model": "claude-eta-2"}}) + "\n")
    service._models_cache = (0, [])
    assert {"claude-eta-1", "claude-eta-2"} <= {m["id"] for m in service.models()}
    log.write_text(json.dumps({"type": "assistant", "message": {"model": "claude-eta-3"}}) + "\n")   # rewritten, shorter
    service._models_cache = (0, [])
    ids = {m["id"] for m in service.models()}
    assert "claude-eta-3" in ids and "claude-eta-2" not in ids


def test_stats_do_not_reparse_unchanged_sessions(client, mx, monkeypatch):
    ids = [_session("projects/acme/topics/blog", f"S{i}") for i in range(5)]
    assert client.get("/api/stats/tokens?force=1").json()["totals"]["sessions"] == 5
    loads = {"n": 0}
    real = store.read

    def counting(sid):
        import sys
        f = sys._getframe(1)
        callers = {f.f_code.co_filename, f.f_back.f_code.co_filename if f.f_back else ""}
        if any(c.endswith("stats.py") for c in callers):        # only the stats' own reads (other threads may run)
            loads["n"] += 1
        return real(sid)
    monkeypatch.setattr(store, "read", counting)
    assert client.get("/api/stats/tokens?force=1").json()["totals"]["sessions"] == 5
    assert loads["n"] == 0                                      # every meta came from the cache
    with store.edit(ids[0]) as m:
        m["title"] = "renamed"
    loads["n"] = 0
    r = client.get("/api/stats/tokens?force=1").json()
    assert loads["n"] <= 2 and any(s["title"] == "renamed" for s in r["sessions"])


def test_stats_survive_non_numeric_meta_values(client, mx):
    bad = _session("projects/acme/topics/blog", "Bad")
    with store.edit(bad) as m:
        m["tokens"] = {"input": "abc", "output": 5}
        m["cost_usd"], m["turns"] = "1,5", "x"
        m["days"] = {"2026-10-19": {"tokens": "n/a", "cost": float("nan")}}
    _session("projects/acme/topics/shop", "Good")
    r = client.get("/api/stats/tokens?force=1")
    assert r.status_code == 200
    t = r.json()["totals"]
    assert t["sessions"] == 2 and t["input"] == 0 and t["output"] == 5 and t["cost_usd"] == 0.0


def test_stats_survive_badly_typed_meta_fields(client, mx):
    """One hand-edited meta (days as a list, path as a number, NaN latency / title / date) must not break the page."""
    cases = [{"days": [1, 2]}, {"days": "x"}, {"path": 5}, {"path": ["a"]}, {"latency": 5},
             {"latency": [[float("nan"), 1]]}, {"latency": [[float("inf"), float("inf")]]}, {"latency": [[True, 1]]},
             {"title": float("nan")}, {"title": [1]}, {"updated": float("nan")}, {"updated": [1]}]
    for over in cases:
        with store.edit(_session("projects/acme/topics/blog", "Bad")) as m:
            m.update(over)
    _session("projects/acme/topics/shop", "Good")
    r = client.get("/api/stats/tokens?force=1")
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    assert d["totals"]["sessions"] == len(cases) + 1 and d["latency"]["turns"] == 0
    assert all(isinstance(s["title"], str) and isinstance(s["path"], str) for s in d["sessions"])
