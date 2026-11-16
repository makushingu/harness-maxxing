"""A voice call on an agent's page: what is said goes to its conversation like a typed message, with the call's
language, so its turn is told it is on the phone (runner.CALL_PREFACE); the next sentence goes on in the same
conversation (fake claude)."""
from __future__ import annotations

from conftest import wait_idle
from test_agents import _calls, _create, _on

RUN = "/api/agents/acme/blog/writer/run"


def test_a_sentence_said_on_a_call_reaches_the_agent_as_said_on_the_phone(client, topic):
    _on(client)
    _create(client, sandbox=False)
    r = client.post(RUN, json={"text": "Vérifie le blog", "call": "fr"})
    assert r.status_code == 200 and r.json()["started"], r.text
    sid = r.json()["session"]["id"]
    wait_idle(client, sid)
    prompt = _calls()[-1]["prompt"]
    assert "on a voice call" in prompt and "language: fr" in prompt and "Vérifie le blog" in prompt
    r = client.post(RUN, json={"text": "Et la boutique", "call": "fr"}).json()
    assert r["continued"] and r["session"]["id"] == sid
    wait_idle(client, sid)
    assert "on a voice call" in _calls()[-1]["prompt"]
    # typed in the box: no call
    client.post(RUN, json={"text": "Merci"})
    wait_idle(client, sid)
    assert "on a voice call" not in _calls()[-1]["prompt"]


def test_a_call_language_is_checked(client, topic):
    _on(client)
    _create(client, sandbox=False)
    assert client.post(RUN, json={"text": "hello", "call": "not a language"}).status_code == 422
