"""Short session titles: background model call, renamed titles kept, local fallback, the switch."""
from __future__ import annotations

import json

import pytest

from conftest import wait_for, wait_idle
from maxxing import config
from maxxing.sessions import titles

MSG = "Tu vas me créer une session d'automatisation de E-ink"


@pytest.fixture
def on(monkeypatch):
    """Short titles by the model (the option of Settings -> Claude)."""
    monkeypatch.delenv("MAXXING_SHORT_TITLES", raising=False)
    config.update_config(short_titles_model=True)


@pytest.fixture
def local(monkeypatch):
    """Short titles as installed: made locally, no model call."""
    monkeypatch.delenv("MAXXING_SHORT_TITLES", raising=False)


def _title(client, sid):
    return client.get(f"/api/sessions/{sid}").json()["title"]


def _title_calls(mx):
    f = mx["fake_dir"] / "calls.jsonl"
    calls = [json.loads(ln) for ln in f.read_text().splitlines()] if f.exists() else []
    return [c for c in calls if "--system-prompt" in c["argv"]]


def test_title_from_the_model(client, mx, on, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_TITLE", '"Automatisation E-ink."')
    s = client.post("/api/sessions", json={"message": MSG}).json()
    assert s["title"] == MSG                                  # provisional at once
    wait_for(lambda: _title(client, s["id"]) == "Automatisation E-ink")
    wait_idle(client, s["id"])
    assert _title(client, s["id"]) == "Automatisation E-ink"   # the end of the turn keeps it
    [call] = _title_calls(mx)
    argv = call["argv"]
    assert argv[argv.index("--model") + 1] == titles.MODEL and argv[argv.index("--tools") + 1] == ""
    assert "--no-session-persistence" in argv and call["prompt"] == MSG
    assert call["cwd"] == str(config.STATE / "claude-titles")


def test_default_titles_are_made_locally(client, mx, local):
    """By default no call is made (it would count in the Claude plan): the first message is shortened here."""
    assert client.get("/api/claude/status").json()["short_titles_model"] is False
    s = client.post("/api/sessions", json={"message": MSG}).json()
    wait_for(lambda: _title(client, s["id"]) == titles.heuristic(MSG))
    wait_idle(client, s["id"])
    assert _title_calls(mx) == []


def test_only_the_start_of_a_long_message_is_sent(client, mx, on):
    s = client.post("/api/sessions", json={"message": "word " * 600}).json()
    wait_for(lambda: _title(client, s["id"]) == "Fake short title")
    assert len(_title_calls(mx)[0]["prompt"]) <= titles.MESSAGE_CHARS


def test_explicit_title_and_empty_message_untouched(client, mx, on):
    a = client.post("/api/sessions", json={"message": MSG, "title": "Given"}).json()
    b = client.post("/api/sessions", json={}).json()
    wait_idle(client, a["id"])
    assert _title(client, a["id"]) == "Given" and _title(client, b["id"]).startswith("Session ")
    assert _title_calls(mx) == []


def test_telegram_title_made_from_the_message(client, mx, on):
    from maxxing.sessions import service
    s = service.create_session("", source="telegram", title="Write a plan for the launch", auto_title=True)
    assert _title_calls(mx) == []                             # nothing to name yet
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "Write a plan for the launch"})
    wait_for(lambda: _title(client, s["id"]) == "Fake short title")
    wait_idle(client, s["id"])
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": "and another thing"})
    wait_idle(client, s["id"])
    assert len(_title_calls(mx)) == 1                         # only the first message
    t = service.create_session("", source="telegram", title="Telegram")        # a given title: kept
    client.post(f"/api/sessions/{t['id']}/messages", json={"text": MSG})
    wait_idle(client, t["id"])
    assert _title(client, t["id"]) == "Telegram"


def test_empty_session_named_on_its_first_message(client, mx, on, monkeypatch):
    s = client.post("/api/sessions", json={}).json()
    assert s["title"].startswith("Session ")
    client.post(f"/api/sessions/{s['id']}/messages", json={"text": MSG})
    wait_for(lambda: _title(client, s["id"]) == "Fake short title")
    r = client.post("/api/sessions", json={}).json()           # renamed before its first message: kept
    client.patch(f"/api/sessions/{r['id']}", json={"title": "Mine"})
    client.post(f"/api/sessions/{r['id']}/messages", json={"text": MSG})
    wait_idle(client, r["id"])
    assert _title(client, r["id"]) == "Mine" and len(_title_calls(mx)) == 1
    config.update_config(short_titles=False)                   # off: "Session N" stays, as before
    o = client.post("/api/sessions", json={}).json()
    client.post(f"/api/sessions/{o['id']}/messages", json={"text": MSG})
    wait_idle(client, o["id"])
    assert _title(client, o["id"]) == o["title"] and o["title"].startswith("Session ")


def test_renamed_title_is_kept(client, mx, monkeypatch):
    s = client.post("/api/sessions", json={"message": MSG}).json()     # switch off by env: nothing scheduled
    wait_idle(client, s["id"])
    client.patch(f"/api/sessions/{s['id']}", json={"title": "Mine"})
    assert titles.refine(s["id"], MSG, MSG) is None
    assert _title(client, s["id"]) == "Mine"
    assert titles.refine("0" * 36, MSG, MSG) is None                    # a deleted session: nothing raised


def test_failed_call_falls_back_to_the_heuristic(client, mx, on, monkeypatch):
    msg = "Can you please FAIL to fix the login bug on the blog. Thanks"
    s = client.post("/api/sessions", json={"message": msg}).json()
    wait_for(lambda: _title(client, s["id"]) == "FAIL to fix the login bug on the blog")
    monkeypatch.setenv("FAKE_CLAUDE_TITLE", "")                         # an empty answer is not a title
    s = client.post("/api/sessions", json={"message": MSG}).json()
    wait_for(lambda: _title(client, s["id"]) == "Créer une session d'automatisation")


def test_switch_off_keeps_the_old_title(client, mx, on):
    st = client.get("/api/claude/status").json()
    assert st["short_titles"] is True
    assert client.put("/api/claude/settings", json={"short_titles": False}).json() == {"ok": True}
    assert client.get("/api/claude/status").json()["short_titles"] is False
    s = client.post("/api/sessions", json={"message": MSG}).json()
    wait_idle(client, s["id"])
    assert _title(client, s["id"]) == MSG and _title_calls(mx) == []


@pytest.mark.parametrize("message, title", [
    (MSG, "Créer une session d'automatisation"),
    ("Peux-tu corriger le menu du blog ?", "Corriger le menu du blog"),
    ("Salut, j'aimerais que tu m'aides à écrire la page d'accueil", "Écrire la page d'accueil"),
    ("Please can you write a migration script for the acme database", "Write a migration script for the acme"),
    ("I want you to review the pricing page. Then deploy.", "Review the pricing page"),
    ("hello", "Hello"),
    ("   ", ""),
    ("Supercalifragilisticexpialidocious" * 3, ("Supercalifragilisticexpialidocious" * 3)[:40]),
])
def test_heuristic(message, title):
    assert titles.heuristic(message) == title


def test_clean():
    assert titles.clean("Title: **Blog redesign**\n") == "Blog redesign"
    assert titles.clean("« Refonte du blog »") == "Refonte du blog"
    assert titles.clean("") is None and titles.clean("x" * 61) is None
    assert titles.clean("Sure! Here is a long answer with many many words in it") is None
