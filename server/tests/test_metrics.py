"""GET /metrics (Prometheus text format): off by default, bearer token, what the Usage page counts."""
from __future__ import annotations

import re

from maxxing import config, metrics
from maxxing.sessions import store

A = "projects/acme/topics/blog/agents/writer"
LINE = re.compile(r'^[a-z_][a-z0-9_]*(\{[a-z_]+="(?:[^"\\\n]|\\.)*"(,[a-z_]+="(?:[^"\\\n]|\\.)*")*\})? -?[0-9.e+-]+$')


def _session(path: str, tokens: int, cost: float, state: str = "idle") -> None:
    m = store.new_meta(path, "t")
    store.create(m)
    with store.edit(m["id"]) as cur:
        store.add_usage(cur, {"input_tokens": tokens, "output_tokens": 1}, cost, 1_700_000_000)
        cur["cost_usd"], cur["turns"], cur["state"] = cost, 1, state


def test_off_by_default_then_token_only(client, mx):
    assert client.get("/metrics").status_code == 404
    assert client.get("/api/system/metrics").json() == {"enabled": False, "has_token": False, "url": "/metrics"}
    r = client.put("/api/system/metrics", json={"enabled": True}, headers={"X-Maxxing": "1"}).json()
    tok = r["token"]
    assert r["enabled"] and r["has_token"] and tok.startswith("hmx_") and len(tok) > 40
    assert tok not in config.config_path().read_text()                    # the token lives with the secrets
    # the signed-in cookie is not a permission here, a wrong or missing token neither
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Basic " + tok}).status_code == 401
    ok = client.get("/metrics", headers={"Authorization": "Bearer " + tok})
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("text/plain; version=0.0.4")
    # switching on again keeps the token (shown once); a new one replaces it
    assert client.put("/api/system/metrics", json={"enabled": True}, headers={"X-Maxxing": "1"}).json()["token"] is None
    new = client.post("/api/system/metrics/token", headers={"X-Maxxing": "1"}).json()["token"]
    assert new != tok and client.get("/metrics", headers={"Authorization": "Bearer " + tok}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer " + new}).status_code == 200
    client.put("/api/system/metrics", json={"enabled": False}, headers={"X-Maxxing": "1"})
    assert client.get("/metrics", headers={"Authorization": "Bearer " + new}).status_code == 404


def test_switch_needs_a_session(mx):
    from fastapi.testclient import TestClient
    from maxxing.app import create_app
    with TestClient(create_app()) as anon:
        assert anon.get("/api/system/metrics").status_code == 401
        assert anon.put("/api/system/metrics", json={"enabled": True}, headers={"X-Maxxing": "1"}).status_code == 401
        assert anon.post("/api/system/metrics/token", headers={"X-Maxxing": "1"}).status_code == 401
    assert not metrics.enabled() and not metrics.has_token()


def test_page_is_valid_and_counts_what_usage_counts(client, topic):
    assert client.put("/api/settings", json={"agents_page": True, "daily_budget_usd": 5}).status_code == 200
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": "writer",
                                         "display_name": 'Wri"ter\\', "description": "Writes."})
    assert r.status_code == 200, r.text
    _session(A, 100, 0.25)
    _session("projects/acme/topics/blog", 10, 0.5, state="running")
    from maxxing import stats
    stats.invalidate()
    text = metrics.render()
    body = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert body and all(LINE.match(ln) for ln in body), [ln for ln in body if not LINE.match(ln)]
    # every sample has its HELP and TYPE, once
    names = {ln.split("{")[0].split(" ")[0] for ln in body}
    assert names == {ln.split()[2] for ln in text.splitlines() if ln.startswith("# TYPE")}
    assert text.count("# TYPE harness_usage_tokens gauge") == 1
    v = {ln.rsplit(" ", 1)[0]: float(ln.rsplit(" ", 1)[1]) for ln in body}
    assert v['harness_usage_tokens{kind="input"}'] == 110 and v['harness_usage_tokens{kind="output"}'] == 2
    assert v["harness_usage_cost_usd"] == 0.75 and v["harness_usage_turns"] == 2
    assert v["harness_sessions"] == 2 and v["harness_sessions_running"] == 1
    assert v['harness_project_tokens{project="acme"}'] == 112
    assert v['harness_agent_tokens{agent="Wri\\"ter\\\\",path="%s"}' % A] == 101          # label escaped
    assert v["harness_budget_usd_per_day"] == 5 and v["harness_budget_reached"] == 0
    assert v["harness_metrics_parts_failed"] == 0 and 'harness_build_info{version="' in text
    assert "harness_disk_free_bytes" in v and "harness_health_ok" in v
    # no session title or id in the page
    assert not any(sid in text for sid in store.list_ids())


def test_a_broken_part_is_left_out_not_fatal(client, mx, monkeypatch):
    from maxxing import crons
    monkeypatch.setattr(crons, "list_jobs", lambda: 1 / 0)
    text = metrics.render()
    assert "harness_metrics_parts_failed 1" in text and "harness_usage_turns" in text and "harness_cron_jobs" not in text
