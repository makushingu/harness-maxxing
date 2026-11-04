"""The 3rd path level (projects/<p>/topics/<t>/agents/<a>) outside the agents module: MCP, Telegram labels,
search, import, stats."""
from __future__ import annotations

import io
import json
import zipfile

from maxxing import mcp, search
from maxxing.telegram import gateway

A = "projects/acme/topics/blog/agents/writer"


def _agent(client) -> None:
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": "writer",
                                         "display_name": "Writer", "description": "Writes cold brew posts."})
    assert r.status_code == 200, r.text


def test_telegram_labels():
    assert gateway.topic_label(A) == "acme / blog / 🤖 writer"
    assert gateway.topic_name(A) == "acme/blog/🤖writer"
    assert gateway.topic_name("projects/acme/topics/blog") == "acme/blog"


def test_mcp_sees_the_agent_folder(client, topic, mx):
    _agent(client)
    d = mx["ws"] / A
    (d / ".mcp.json").write_text(json.dumps({"mcpServers": {"docs": {"type": "http", "url": "https://mcp.example.com/mcp"}}}))
    s = next(x for x in mcp.servers() if x["name"] == "docs")
    assert s["scope"] == "project" and s["where"]["rel"] == A
    assert (s["where"]["project"], s["where"]["topic"], s["where"]["agent"]) == ("acme", "blog", "writer")
    assert mcp.where_of(str(mx["ws"] / "projects/acme/topics/blog"))["agent"] is None


def test_search_indexes_agent_memory_as_memory(client, topic, mx):
    _agent(client)
    (mx["ws"] / A / "memory.md").write_text("- Readers love zanzibarcoffee\n")
    (mx["ws"] / A / "notes.txt").write_text("zanzibarcoffee draft\n")
    search.refresh(full=True)
    hits = search.search("zanzibarcoffee")["results"]
    mem = [h for h in hits if h["kind"] == "memory"]
    assert mem and mem[0]["path"].endswith(A + "/memory.md")
    assert mem[0]["title"] == "memory.md · agent writer (acme/blog)"
    assert any(h["kind"] == "file" and h["path"].endswith(A + "/notes.txt") for h in hits)
    base = str(mx["ws"])
    mem_dirs, buckets = search._layout(base)
    assert str(mx["ws"] / A) in mem_dirs
    tb = dict(buckets)[str(mx["ws"] / "projects/acme/topics/blog")]
    assert str(mx["ws"] / "projects/acme/topics/blog/agents") in tb       # not in the topic's budget


def test_import_never_plants_an_agent(client, mx):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("projects/acme/topics/blog/memory.md", "- fine\n")
        z.writestr("projects/acme/topics/blog/agents/evil/agent.json", '{"permission_mode": "bypass"}')
        z.writestr("projects/acme/topics/blog/agents/evil/CLAUDE.md", "# Agent evil\n")
    p = client.post("/api/import/upload", files={"file": ("export.zip", buf.getvalue(), "application/zip")}).json()
    assert {s["file"] for s in p["skipped"] if s["reason"].startswith("agent folder")} == {
        "projects/acme/topics/blog/agents/evil/agent.json", "projects/acme/topics/blog/agents/evil/CLAUDE.md"}
    assert client.post(f"/api/import/{p['id']}/apply").status_code == 200
    assert (mx["ws"] / "projects/acme/topics/blog/memory.md").exists()
    assert not (mx["ws"] / "projects/acme/topics/blog/agents").exists()


def test_stats_label_an_agent_row(client, topic):
    from maxxing import stats
    _agent(client)
    r = client.post("/api/sessions", json={"path": A, "message": "NOTOOL hello"})
    assert r.status_code == 200, r.text
    from conftest import wait_idle
    wait_idle(client, r.json()["id"])
    rows = {t["path"]: t for t in stats.compute()["topics"]}
    assert rows[A]["label"] == "acme / blog / Writer" and rows[A]["agent"] == "Writer"
