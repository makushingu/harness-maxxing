"""Recall: `maxxing search` (cmd_search.py), the archive of memory compaction, the sentence every session gets."""
from __future__ import annotations

import argparse
import json

from maxxing import cmd_search, config, search
from maxxing.sessions import spawn, store

T = "projects/acme/topics/blog"


def _session(path: str, title: str, texts: list[str]) -> str:
    m = store.new_meta(path, title)
    store.create(m)
    with open(store.log_path(m["id"]), "a") as f:
        for text in texts:
            f.write(json.dumps({"type": "mx_user", "text": text, "attachments": [], "source": "web", "at": 1.0}) + "\n")
    return m["id"]


def _run(capsys, *argv: str) -> str:
    p = argparse.ArgumentParser()
    cmd_search._configure(p)
    assert cmd_search._handler(p.parse_args(list(argv))) == 0
    return capsys.readouterr().out


def test_search_finds_a_past_session_and_the_archive(client, mx, capsys, monkeypatch):
    d = config.workspace() / T
    d.mkdir(parents=True)
    (d / "memory-archive.md").write_text("## Archived 2026-11-01\n- The staging database listens on port 5433\n")
    sid = _session(T, "Deploy day", ["The production bucket is named acme-prod-media, never acme-media"])
    other = _session("projects/acme/topics/shop", "Shop", ["The bucket of the shop is shop-assets"])
    out = _run(capsys, "production", "bucket")
    assert "Deploy day" in out and f"id={sid[:8]}" in out and "--session" in out
    assert "port 5433" in _run(capsys, "staging", "database", "port")               # what compaction took out
    out = _run(capsys, "bucket", "--in", T)
    assert "Deploy day" in out and "Shop" not in out and other[:8] not in out
    assert "acme-prod-media" in _run(capsys, "bucket", "--session", sid[:8])
    rows = json.loads(_run(capsys, "production", "bucket", "--json"))
    assert rows and rows[0]["kind"] == "session"
    monkeypatch.setenv("MAXXING_SESSION", sid)                                      # never the session that asks
    assert "Deploy day" not in _run(capsys, "production", "bucket")


def test_one_word_too_many_still_finds(client, mx, capsys):
    _session(T, "Invoices", ["Invoices are sent on the 5th of each month by the billing script"])
    out = _run(capsys, "invoices", "sent", "quarterly")
    assert "closest results" in out and "Invoices" in out
    assert "nothing found" in _run(capsys, "zzzunknownword")
    assert search.fts_query_any("the and for") is None                              # only common words: no query


def test_every_session_is_told_to_search():
    for cfg in ({}, {"background_agents": True}):
        argv = spawn.agents_args(cfg, "HINT")
        assert argv[0] == "--append-system-prompt" and "maxxing search" in argv[1] and argv[1].endswith("HINT")


def test_search_in_a_folder_finds_its_memory_files(client, mx, capsys):
    d = config.workspace() / "projects/a"
    d.mkdir(parents=True)
    (d / "memory.md").write_text("- The zorglubfact lives here\n")
    assert "zorglubfact" in _run(capsys, "zorglubfact", "--in", "projects/a")
    assert "zorglubfact" in _run(capsys, "zorglubfact", "--in", str(d))

