"""Memory review (memory_review.py): proposals from an agent's run and from the repeated sessions of a topic, as
notifications with Accept / Refuse. Nothing is written before the owner accepts."""
from __future__ import annotations

import time

import pytest

from maxxing import config, feed, memory_review as mr
from maxxing.sessions import store

T = "projects/acme/topics/blog"
A = T + "/agents/writer"


def _agent(client) -> None:
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    r = client.post("/api/agents", json={"topic_path": T, "name": "writer", "description": "Writes.", "sandbox": False})
    assert r.status_code == 200, r.text


def _session(path: str, source: str = "web", ago: float = 0.0) -> dict:
    m = store.new_meta(path, "s", source=source)
    m["created"] = time.time() - ago
    return store.create(m)


@pytest.fixture
def model(monkeypatch):
    """The model's answers, in order (the last one repeats); `.asked` = the payloads it got."""
    box = type("Box", (), {"answers": [{}], "asked": []})()

    def ask(system, payload, model):
        box.asked.append(payload)
        return box.answers[min(len(box.asked), len(box.answers)) - 1], 0.001, ""
    monkeypatch.setattr(mr, "_ask", ask)
    monkeypatch.setattr(mr, "transcript", lambda sid, actions=False: "[OWNER] Run your routine.\n\n[DID] Bash: sh report.sh")
    return box


def _bullet(text="Run report.sh with --cached: same figures, 12 s faster.", **kw) -> dict:
    return {"proposals": [{"level": "agent", "action": "add", "text": text, "old": "", "why": "tool hint", **kw}]}


def _events() -> list[dict]:
    return [e for e in feed.list_events(limit=50)["events"] if (e.get("ref") or "").startswith("memory:")]


def test_a_run_proposes_and_accept_writes_the_agents_memory(client, topic, model):
    _agent(client)
    model.answers = [_bullet()]
    s = _session(A, "agent")
    new = mr.after_run(s)
    assert len(new) == 1 and new[0]["state"] == "new"
    mem = config.workspace() / A / "memory.md"
    assert "--cached" not in (mem.read_text() if mem.exists() else "")       # nothing written before the click
    ev = _events()[0]
    assert ev["source"] == "agents" and ev["agent"] == A and {a["id"] for a in ev["actions"]} == {"accept", "refuse"}
    assert "--cached" in ev["body"]
    r = client.post(f"/api/feed/{ev['id']}/act/accept")
    assert r.status_code == 200, r.text
    assert "- Run report.sh with --cached" in mem.read_text()
    done = feed.get(ev["id"])
    assert done["resolved"] and done["resolution"] == "Added"
    assert client.post(f"/api/feed/{ev['id']}/act/accept").status_code == 200  # a second click changes nothing
    assert mem.read_text().count("--cached") == 1


def test_refuse_writes_nothing_and_the_next_review_is_told(client, topic, model):
    _agent(client)
    model.answers = [_bullet(), {"proposals": []}]
    mr.after_run(_session(A, "agent"))
    ev = _events()[0]
    assert client.post(f"/api/feed/{ev['id']}/act/refuse").status_code == 200
    assert feed.get(ev["id"])["resolution"] == "Rejected"
    mem = config.workspace() / A / "memory.md"
    assert "--cached" not in (mem.read_text() if mem.exists() else "")
    assert mr.after_run(_session(A, "agent")) == []
    assert "ALREADY PROPOSED" in model.asked[1] and "--cached" in model.asked[1]


def test_one_lesson_a_run_and_no_review_while_three_wait(client, topic, model):
    _agent(client)
    two = _bullet()
    two["proposals"].append({"level": "agent", "action": "add", "text": "Second lesson.", "old": "", "why": ""})
    model.answers = [two, _bullet("B."), _bullet("C."), _bullet("D.")]
    for _ in range(4):
        mr.after_run(_session(A, "agent"))
    assert len(_events()) == 3 and len(model.asked) == 3                      # the fourth run was not read
    assert [x["state"] for x in mr.load()].count("new") == 3


def test_not_for_a_session_of_the_owner_nor_when_off_nor_another_level(client, topic, model):
    _agent(client)
    model.answers = [_bullet(level="global")]                               
    assert mr.after_run(_session(T)) == [] and not model.asked                # a topic session: not this path
    config.save_config({**config.load_config(), "memory_review": False})
    assert mr.after_run(_session(A, "agent")) == [] and not model.asked
    assert mr.daily(force=True) == []
    config.save_config({**config.load_config(), "memory_review": True})
    model.answers = [{"proposals": [{"level": "nowhere", "action": "add", "text": "x"},
                                    {"level": "agent", "action": "run", "text": "x"}, "junk"]}]
    assert mr.after_run(_session(A, "agent")) == [] and not _events()


SKILL = {"skills": [{"name": "New Product Sheet!", "description": 'Creates a "fiche".', "sessions": 3,
                     "steps": ["Create fiches/<slug>.md (asked by the owner).", "Run tools/check.sh."]}],
         "rules": [{"text": "Weights are written without a unit.", "sessions": 2}]}


def test_daily_proposes_a_skill_and_a_rule_for_a_busy_topic(client, topic, model):
    for n in range(3):
        _session(T, ago=3600 * (n + 1))
    _session(T, "agent", ago=10)                                              # runs and old sessions do not count
    model.answers = [SKILL]
    new = mr.daily()
    assert [x["level"] for x in new] == ["skill", "topic"]
    evs = {e["title"]: e for e in _events()}
    sk = next(e for t, e in evs.items() if t.startswith("Skill proposed for acme / blog: new-product-sheet"))
    assert sk["source"] == "sessions" and "1. Create fiches/<slug>.md" in sk["body"]
    f = config.workspace() / T / ".claude" / "skills" / "new-product-sheet" / "SKILL.md"
    assert not f.exists()
    assert client.post(f"/api/feed/{sk['id']}/act/accept").status_code == 200
    txt = f.read_text()
    assert txt.startswith("---\nname: new-product-sheet\ndescription: \"Creates a 'fiche'.\"\n---") and "accepted by the owner" in txt
    rule = next(e for t, e in evs.items() if t.startswith("Memory of acme / blog"))
    assert client.post(f"/api/feed/{rule['id']}/act/accept").status_code == 200
    assert "- Weights are written without a unit." in (config.workspace() / T / "memory.md").read_text()
    # the same day, then another day without a new session: the topic is not read again
    assert mr.daily() == [] and mr.daily(force=True) == [] and len(model.asked) == 1
    _session(T)
    model.answers = [{"skills": [], "rules": []}]
    assert mr.daily(force=True) == [] and len(model.asked) == 2
    assert "SKILLS THIS FOLDER ALREADY HAS" in model.asked[1] and "new-product-sheet" in model.asked[1]


def test_daily_leaves_a_topic_with_two_sessions_alone(client, topic, model):
    _session(T)
    _session(T, ago=60)
    for n in range(3):
        _session(T, ago=86400 * 20 + n)                                       # older than the window
    model.answers = [SKILL]
    assert mr.daily() == [] and not model.asked


def test_cli_lists_and_applies(client, topic, model, capsys):
    from maxxing import cli
    _agent(client)
    model.answers = [_bullet()]
    pid = mr.after_run(_session(A, "agent"))[0]["id"]
    assert cli.main(["memory-review", "list"]) == 0 and pid in capsys.readouterr().out
    assert cli.main(["memory-review", "apply", pid]) == 0 and "added" in capsys.readouterr().out
    assert cli.main(["memory-review", "list"]) == 0 and "nothing waits" in capsys.readouterr().out
