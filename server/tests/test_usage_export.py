"""Usage per agent (Settings -> Usage, the agent page) and the usage export (CSV / JSON)."""
from __future__ import annotations

import csv
import io

from maxxing import stats
from maxxing.sessions import store

A = "projects/acme/topics/blog/agents/writer"


def _agent(client) -> None:
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": "writer",
                                         "display_name": "Writer", "description": "Writes cold brew posts."})
    assert r.status_code == 200, r.text


def _session(path: str, title: str, tokens: int, cost: float, at: float = 1_700_000_000) -> str:
    m = store.new_meta(path, title)
    store.create(m)
    with store.edit(m["id"]) as cur:
        store.add_usage(cur, {"input_tokens": tokens, "output_tokens": 0}, cost, at)
        cur["cost_usd"], cur["turns"] = cost, 1
    return m["id"]


def test_an_agent_has_its_own_row_and_days(client, topic):
    _agent(client)
    _session(A, "run 1", 100, 0.25)
    _session(A, "run 2", 50, 0.5, 1_700_000_000 + 86400)
    _session("projects/acme/topics/blog", "mine", 7, 0.01)
    r = client.get("/api/stats/tokens?force=1").json()
    assert [a["path"] for a in r["agents"]] == [A]
    a = r["agents"][0]
    assert a["name"] == "Writer" and a["label"] == "acme / blog / Writer"
    assert a["total"] == 150 and a["turns"] == 2 and a["sessions"] == 2 and a["cost_usd"] == 0.75
    assert [d["tokens"] for d in a["days"]] == [100, 50] and a["days"][0]["date"] < a["days"][1]["date"]
    # the topic's own sessions are not the agent's
    assert next(t for t in r["topics"] if t["path"] == "projects/acme/topics/blog")["total"] == 7


def test_export_csv_and_json(client, topic):
    _agent(client)
    _session(A, "run", 100, 0.25)
    sid = _session("projects/acme/topics/blog", "=HYPERLINK(\"http://x\")", 7, 0.01)
    r = client.get("/api/stats/export?group=agents")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "harness-usage-agents.csv" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows == [{"path": A, "agent": "Writer", "label": "acme / blog / Writer", "total": "100", "input": "100",
                     "output": "0", "cache_read": "0", "cache_write": "0", "cost_usd": "0.25", "turns": "1", "sessions": "1"}]
    # a title a spreadsheet would run as a formula is neutralised
    rows = {x["id"]: x for x in csv.DictReader(io.StringIO(client.get("/api/stats/export?group=sessions").text))}
    assert rows[sid]["title"].startswith("'=HYPERLINK") and rows[sid]["total"] == "7"
    j = client.get("/api/stats/export?group=projects&format=json").json()
    assert j["group"] == "projects" and j["columns"][0] == "project"
    assert j["rows"][0]["project"] == "acme" and j["rows"][0]["total"] == 107 and j["rows"][0]["sessions"] == 2
    d = client.get("/api/stats/export?group=days&format=json").json()["rows"]
    assert d and set(d[0]) == {"date", "tokens", "cost_usd"} and d[0]["tokens"] == 107


def test_export_keeps_every_session_and_refuses_unknown_values(client, mx):
    for i in range(103):
        _session("", f"s{i}", 1, 0.0)
    assert len(client.get("/api/stats/tokens?force=1").json()["sessions"]) == 100
    assert len(stats.export_rows("sessions")[1]) == 103
    assert client.get("/api/stats/export?group=nope").json()["error"] == "bad_group"
    assert client.get("/api/stats/export?format=xml").json()["error"] == "bad_format"


def test_export_needs_a_session_cookie(mx):
    from fastapi.testclient import TestClient
    from maxxing.app import create_app
    with TestClient(create_app()) as anon:
        assert anon.get("/api/stats/export").status_code == 401
