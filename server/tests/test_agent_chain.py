""""agent" triggers: an agent starts on the result of another agent's automatic run (agents.chain_after)."""
from __future__ import annotations

import threading

from conftest import wait_for, wait_idle
from maxxing import agents, config, feed

W = "projects/acme/topics/blog/agents/writer"
R = "projects/acme/topics/blog/agents/reviewer"


def _setup(client, on: str = "ok", match: str = "", debounce_s: int = 0) -> str:
    assert client.put("/api/settings", json={"agents_page": True}).status_code == 200
    for name in ("writer", "reviewer"):
        r = client.post("/api/agents", json={"topic_path": "projects/acme/topics/blog", "name": name,
                                             "description": f"The {name}."})
        assert r.status_code == 200, r.text
    r = client.patch("/api/agents/acme/blog/reviewer", json={
        "limits": {"debounce_s": debounce_s},
        "triggers": [{"kind": "agent", "agent": W, "on": on, "match": match, "prompt": "NOTOOL review it"}]})
    assert r.status_code == 200, r.text
    t = r.json()["triggers"][0]
    assert t["kind"] == "agent" and t["agent"] == W and t["on"] == on
    return t["id"]


def _run_writer(client, text: str = "NOTOOL write the post") -> str:
    run = agents.fire(W, trigger="cron:c_1", prompt=text, source="cron")
    assert run["started"]
    wait_idle(client, run["session"]["id"])
    return run["session"]["id"]


def test_validation(client, topic):
    _setup(client)
    bad = [{"kind": "agent", "agent": "nope"}, {"kind": "agent", "agent": R},
           {"kind": "agent", "agent": W, "on": "maybe"}]
    for t in bad:
        r = client.patch("/api/agents/acme/blog/reviewer", json={"triggers": [t]})
        assert r.status_code in (400, 422), (t, r.text)
    r = client.patch("/api/agents/acme/blog/reviewer",
                     json={"triggers": [{"kind": "agent", "agent": "projects/acme/topics/blog/agents/ghost"}]})
    assert r.status_code == 404
    # its agent deleted: the trigger stays, the other settings can still be changed
    assert client.delete("/api/agents/acme/blog/writer").status_code == 200
    r = client.patch("/api/agents/acme/blog/reviewer", json={"description": "Still here."})
    assert r.status_code == 200, r.text
    assert r.json()["triggers"][0]["agent"] == W


def test_an_automatic_run_starts_the_next_agent(client, topic):
    tid = _setup(client)
    _run_writer(client)                                  # the end of its turn is handled in the background
    run = wait_for(lambda: agents.flush_due() * 0 or next((m for m in agents.thread(R) if m.get("kind") == "run"),
                                                          None))
    assert run["trigger"] == f"after:{tid}" and run["source"] == "agent writer"
    meta = agents.get(R)
    assert meta["trigger_stats"][tid]["events"] == 1
    from maxxing.sessions import store
    env = store.read(run["session"])["env"]
    assert env["MAXXING_AGENT_DEPTH"] == "1" and env["MAXXING_AGENT_OUTSIDE"] == "1"   # its result is data


def test_filters_on_end_and_words(client, topic, monkeypatch):
    _setup(client, on="error", match="refund")
    fired = []
    monkeypatch.setattr(agents, "fire", lambda path, **k: fired.append((path, k)) or {"started": True})
    assert agents.chain_after(W, "a refund was made", ok=True) == 0          # ok, not error
    assert agents.chain_after(W, "nothing to see", ok=False) == 0            # no word
    assert agents.chain_after(W, "the REFUND failed", ok=False, depth=1) == 1
    assert agents.chain_after(R, "a refund", ok=False) == 0                   # another agent's run
    assert agents.flush_due() == 1
    path, k = fired[0]
    assert path == R and k["depth"] == 2 and "FAILED" in k["text"] and "the REFUND failed" in k["text"]
    assert k["prompt"] == "NOTOOL review it"


def test_the_owner_conversation_never_starts_the_next_agent(client, topic, monkeypatch):
    _setup(client)
    seen = []
    real = agents.chain_after
    monkeypatch.setattr(agents, "chain_after", lambda *a, **k: seen.append(a) or real(*a, **k))
    r = client.post("/api/agents/acme/blog/writer/run", json={"text": "NOTOOL hello"})
    assert r.status_code == 200, r.text
    wait_idle(client, r.json()["session"]["id"])
    assert seen == [] and not agents.debouncer.pending


def test_chains_stop_at_the_depth_limit(client, topic):
    _setup(client)
    agents.chain_after(W, "done", ok=True, depth=agents.MAX_DEPTH)
    assert agents.flush_due() == 1
    skip = wait_for(lambda: next((m for m in agents.thread(R) if m.get("kind") == "skip"), None))
    assert skip["reason"] == "depth"


def test_a_waiting_result_survives_a_restart(client, topic, monkeypatch):
    _setup(client, debounce_s=60)
    agents.scan_feed()                                   # the feed position exists (the server's first scan)
    assert agents.chain_after(W, "post 3 written", ok=True) == 1
    agents.debouncer.pending.clear()                     # the server restarts
    agents._feed_loaded.clear()
    agents.scan_feed()
    (p,) = agents.debouncer.pending.values()
    assert p["fire_as"].startswith("after:t_")
    p["due"] = 0
    fired = []
    monkeypatch.setattr(agents, "fire", lambda path, **k: fired.append(k) or {"started": True})
    assert agents.flush_due() == 1 and fired[0]["trigger"] == p["fire_as"]


def test_a_chained_result_does_not_move_the_feed_position_back(client, topic, monkeypatch):
    """chain_after (end of a turn, worker thread) and scan_feed (agents loop) both write _feed.json: a position read
    before scan_feed saved a newer one is never written back (the events would be handed out again)."""
    _setup(client)
    monkeypatch.setattr(agents, "fire", lambda path, **k: {"started": True})
    agents.scan_feed()                                  # first scan: the position starts now
    for i in range(3):
        feed.post(f"event {i}", "body", source="custom", notify=False)
    top = feed.max_id()
    real, inside, go = agents.debouncer.dump, threading.Event(), threading.Event()

    def slow_dump():                                    # chain_after stops just before it writes
        if threading.current_thread().name == "chain":
            inside.set()
            go.wait(5)
        return real()

    monkeypatch.setattr(agents.debouncer, "dump", slow_dump)
    chain = threading.Thread(target=agents.chain_after, args=(W, "the post is out", True), name="chain")
    chain.start()
    assert inside.wait(5)
    scan = threading.Thread(target=agents.scan_feed)    # the agents loop meanwhile saves `top`
    scan.start()
    scan.join(0.5)
    go.set()
    chain.join(5)
    scan.join(5)
    assert config.read_json(agents._feed_state())["last_id"] == top


def test_the_trigger_follows_a_topic_rename(client, topic):
    _setup(client)
    assert client.patch("/api/workspace/projects/acme/topics/blog", json={"name": "news"}).status_code == 200
    a = agents.get("projects/acme/topics/news/agents/reviewer")
    assert a["triggers"][0]["agent"] == "projects/acme/topics/news/agents/writer"


def test_test_button_uses_the_last_result(client, topic, monkeypatch):
    tid = _setup(client)
    _run_writer(client)
    wait_for(lambda: any(m.get("kind") == "result" for m in agents.thread(W)))
    fired = []
    monkeypatch.setattr(agents, "fire", lambda path, **k: fired.append(k) or {"started": True})
    r = client.post(f"/api/agents/acme/blog/reviewer/triggers/{tid}/test")
    assert r.status_code == 200, r.text
    assert fired[0]["trigger"] == f"after:{tid}" and "Result of a run of the agent" in fired[0]["text"]


def test_cli_after(client, topic, capsys):
    _setup(client)
    from maxxing import cli
    assert cli.main(["agents", "after", "writer", "reviewer", "--on", "any", "--match", "draft"]) == 0, \
        capsys.readouterr().err
    t = agents.get(W)["triggers"][0]
    assert t == {**t, "kind": "agent", "agent": R, "on": "any", "match": "draft"}
