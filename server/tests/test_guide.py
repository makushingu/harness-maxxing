"""Getting-started guide: progress, the case it sees, the cards Opus writes (faked here)."""
from __future__ import annotations

import re
from pathlib import Path

from maxxing import config, guide

from conftest import wait_for

WEB = Path(__file__).resolve().parents[2] / "web" / "src"


def test_the_ui_and_the_server_know_the_same_steps():
    ids = re.findall(r"\{ id: '([a-z-]+)', part:", (WEB / "guide" / "steps.ts").read_text(encoding="utf-8"))
    assert ids and ids == list(guide.STEPS)
    for lang in ("en", "fr"):
        text = (WEB / "i18n" / f"{lang}.ts").read_text(encoding="utf-8")
        for s in ids:
            for part in ("title", "body", "tip"):
                assert f"'guide.{s}.{part}'" in text, (lang, s, part)


def test_offered_once_then_progress_is_kept(client):
    config.update_config(onboarding_completed=True)
    st = client.get("/api/guide").json()
    assert st["offer"] is True and st["status"] is None and "context" not in st
    ctx = client.get("/api/guide", params={"context": 1}).json()["context"]
    assert ctx["case"] == "new" and "automate" in ctx["recommended"]
    st = client.put("/api/guide", json={"status": "running", "level": "beginner", "mode": "partial", "uses": ["mail", "nope"],
                                         "steps": ["welcome", "first-prompt", "bogus", "final"], "index": 9}).json()
    assert st["offer"] is False and st["uses"] == ["mail"] and st["steps"] == ["welcome", "first-prompt", "final"]
    assert st["index"] == 3                                   # clamped to the plan
    st = client.put("/api/guide", json={"status": "paused", "index": 1, "tried": {"step": "first-prompt", "label": "x", "topic": "t"}}).json()
    assert st["status"] == "paused" and st["tried"]["first-prompt"]["label"] == "x"
    st = client.post("/api/guide/reset").json()
    assert st["steps"] == [] and st["status"] == "dismissed" and st["offer"] is False


def test_import_is_seen(client, mx):
    rep = Path(config.workspace()) / "imports" / "20261125" / "IMPORT_REPORT.md"
    rep.parent.mkdir(parents=True)
    rep.write_text("# Import\nproject blog\n")
    assert client.get("/api/guide", params={"context": 1}).json()["context"]["case"] == "import"


def test_cards_are_written_checked_and_never_twice(client, topic, monkeypatch):
    calls = []

    def fake(step, facts):
        calls.append((step, facts["level"]))
        return {"intro": f"intro {step}", "prompts": [
            {"label": "Ok", "text": "write hello.md", "topic": topic},
            {"label": "Bad", "text": "then git push the repo", "topic": topic},
            {"label": "Elsewhere", "text": "summarize", "topic": "projects/nope/topics/x"},
        ]}
    monkeypatch.setattr(guide, "ask_opus", fake)
    client.put("/api/guide", json={"status": "running", "level": "intermediate", "steps": ["welcome", "nav", "first-prompt"]})
    client.post("/api/guide/cards", json={"steps": ["welcome", "nav", "first-prompt"]})
    st = wait_for(lambda: (s := client.get("/api/guide").json())["cards"].get("first-prompt", {}).get("status") == "ready" and s)
    assert "nav" not in st["cards"]                            # an explanation alone: no Opus call
    assert st["cards"]["welcome"]["prompts"] == []             # the welcome card has an intro only
    p = st["cards"]["first-prompt"]["prompts"]
    assert [x["label"] for x in p] == ["Ok", "Elsewhere"]      # "git push" dropped; unknown topic -> a real one
    from maxxing import workspace
    assert p[1]["topic"] in {t["path"] for t in workspace.list_topics()}
    client.post("/api/guide/cards", json={"steps": ["welcome", "first-prompt"]})
    assert len(calls) == 2                                     # ready cards are not written again
    client.post("/api/guide/cards", json={"steps": ["welcome"], "force": True})
    wait_for(lambda: len(calls) == 3)


def test_a_card_opus_could_not_write_is_failed(client, monkeypatch):
    monkeypatch.setattr(guide, "ask_opus", lambda step, facts: None)
    client.put("/api/guide", json={"status": "running", "steps": ["first-prompt"]})
    client.post("/api/guide/cards", json={"steps": ["first-prompt"]})
    wait_for(lambda: client.get("/api/guide").json()["cards"]["first-prompt"]["status"] == "failed")


def test_a_card_lost_by_a_restart_is_asked_again(client, topic, monkeypatch):
    monkeypatch.setattr(guide, "ask_opus", lambda step, facts: {"intro": "hi", "prompts": [{"label": "a", "text": "b", "topic": topic}]})
    client.put("/api/guide", json={"status": "running", "steps": ["first-prompt", "memory"]})
    guide._save({**guide.load(), "cards": {"first-prompt": {"status": "pending", "at": 1}, "memory": "junk"}})
    st = client.get("/api/guide").json()
    assert st["cards"] == {"first-prompt": {"status": "failed", "at": 1}}   # nobody writes it any more; junk dropped
    client.post("/api/guide/cards", json={"steps": ["first-prompt"]})       # no "force": asked again all the same
    wait_for(lambda: client.get("/api/guide").json()["cards"]["first-prompt"]["status"] == "ready")


def test_a_new_tour_starts_with_fresh_cards(client, topic, monkeypatch):
    gate = __import__("threading").Event()

    def slow(step, facts):
        gate.wait(5)
        return {"intro": "old", "prompts": []}
    monkeypatch.setattr(guide, "ask_opus", slow)
    client.put("/api/guide", json={"status": "running", "steps": ["welcome", "final"], "tried": {"step": "welcome", "label": "x", "topic": topic}})
    guide._save({**guide.load(), "cards": {"final": {"status": "ready", "intro": "old", "prompts": [], "at": 1}}})
    client.post("/api/guide/cards", json={"steps": ["welcome"]})
    client.post("/api/guide/reset")                                         # started again while Opus writes
    gate.set()
    wait_for(lambda: not guide._ACTIVE)
    assert client.get("/api/guide").json()["cards"] == {}                   # the old tour's card is not kept
    guide._save({**guide.load(), "cards": {"final": {"status": "ready", "intro": "old", "prompts": [], "at": 1}}, "tried": {"welcome": {}}})
    st = client.put("/api/guide", json={"status": "running", "steps": ["welcome", "final"], "index": 0}).json()
    assert st["cards"] == {} and st["tried"] == {}                          # a new tour: no intro about the old one
    st = client.put("/api/guide", json={"index": True}).json()
    assert st["index"] == 0                                                 # a boolean is not an index
