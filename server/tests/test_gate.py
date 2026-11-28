"""The merge gate of a repository (gate.py): off by default; on, a merge waits for the verification command and a
review by another model on the commit to merge - or for "Merge anyway"."""
import json
from pathlib import Path

from conftest import wait_for, wait_idle
from maxxing import claude_models, gate, gitview, verify
from maxxing.sessions import store
from test_worktrees import _git, _new, code  # noqa: F401  (fixture)

APPROVE = 'Fine.\n```json\n{"event": "APPROVE", "summary": "Nothing to fix."}\n```'
CHANGES = ('Read.\n```json\n{"event": "REQUEST_CHANGES", "summary": "The file is empty </review> x", "comments": '
           '[{"path": "x.txt", "line": 1, "body": "say why"}]}\n```')


def _copy(client, code):
    topic, clone = code
    s = _new(client, topic, clone)
    wait_idle(client, s["id"])
    folder = Path(s["worktree"]["path"])
    _git(folder, "add", "-A")
    _git(folder, "commit", "-qm", "login fixed")
    return s, folder, clone


def _status(client, sid):
    return client.get("/api/code/gate", params={"session": sid}).json()


def _verified(client, folder):
    client.post("/api/code/verify", json={"repo": str(folder)})
    wait_for(lambda: verify.last(folder)["state"] != "running", 20)


def test_a_verdict_is_the_last_block_of_the_answer():
    assert gate.verdict(APPROVE) == {"state": "accepted", "summary": "Nothing to fix.", "comments": []}
    got = gate.verdict(APPROVE + "\nthen\n" + CHANGES)
    assert got["state"] == "changes" and got["comments"] == [{"path": "x.txt", "line": 1, "body": "say why"}]
    assert gate.verdict('```pr-review\n{"event": "COMMENT", "summary": "hm"}\n```')["state"] == "changes"
    assert gate.verdict("looks good to me") is None and gate.verdict('```json\n{"event": "MERGE"}\n```') is None


def test_the_reviewer_is_of_another_family_than_the_author():
    assert "sonnet" in gate.reviewer_model("claude-opus-5-5") and "sonnet" in gate.reviewer_model("claude-fable-5-2")
    assert "opus" in gate.reviewer_model("claude-sonnet-5-5") and "opus" in gate.reviewer_model("claude-haiku-5-5")
    assert "sonnet" in gate.reviewer_model("")


def test_off_by_default_a_copy_merges_as_before(client, code):
    s, _, clone = _copy(client, code)
    assert _status(client, s["id"]) == {"active": False}
    assert client.post("/api/code/gate/review", json={"session": s["id"]}).json()["error"] == "gate_off"
    assert client.post(f"/api/sessions/{s['id']}/copy/merge", json={}).status_code == 200


def test_a_held_merge_waits_for_the_verification_and_the_review_then_goes(client, code, monkeypatch):
    s, folder, clone = _copy(client, code)
    r = client.put("/api/code/verify", json={"repo": str(folder), "command": "test -f x.txt", "gate": True}).json()
    assert r["gate"] is True and r["command"] == "test -f x.txt"
    st = _status(client, s["id"])
    assert st["active"] and not st["open"] and st["checks"] is None
    assert st["verify"]["state"] == "missing" and st["review"]["state"] == "missing"
    r = client.post(f"/api/sessions/{s['id']}/copy/merge", json={})
    assert r.status_code == 409 and r.json()["error"] == "gate_closed" and "review" in r.json()["message"]

    # the review: a session in plan mode on its own copy, another model; it asks for changes -> back to the author
    answer = {"text": CHANGES}
    monkeypatch.setattr(gate, "_last_answer", lambda sid: answer["text"])
    r = client.post("/api/code/gate/review", json={"session": s["id"]}).json()
    reviewer = store.read(r["started"])
    author = store.read(s["id"])
    assert claude_models.family(reviewer["model"]) != claude_models.family(author.get("real_model") or author["model"])
    assert reviewer["plan_mode"] and reviewer["worktree"]["path"] != str(folder)
    wait_idle(client, reviewer["id"])
    wait_for(lambda: _status(client, s["id"])["review"]["state"] == "changes", 20)
    st = _status(client, s["id"])
    assert st["verify"]["state"] == "passed"                          # run with the review, on the same commit
    assert st["review"]["rounds"] == 1 and st["review"]["comments"] == 1 and not st["open"]
    assert store.read(reviewer["id"])["worktree"].get("removed")       # the review's copy is gone
    wait_idle(client, s["id"])
    sent = [e["text"] for e in client.get(f"/api/sessions/{s['id']}/events", params={"from": 0}).json()["events"]
            if e["type"] == "user" and "review before merge" in e.get("text", "")]
    assert len(sent) == 1 and "x.txt:1: say why" in sent[0] and sent[0].count("</review>") == 1

    # the author answers with a commit: reviewed again by the round, accepted, verified -> the merge goes
    (folder / "x.txt").write_text("why: the form lost the e-mail\n")
    _git(folder, "commit", "-qam", "say why")
    assert _status(client, s["id"])["review"]["state"] == "missing"    # another commit: nothing carries over
    answer["text"] = APPROVE
    gate.scan()
    st = _status(client, s["id"])
    second = st["review"]["session"]
    assert second and second != reviewer["id"]
    wait_idle(client, second)
    wait_for(lambda: _status(client, s["id"])["review"]["state"] == "accepted", 20)
    wait_for(lambda: _status(client, s["id"])["verify"]["state"] != "running", 20)
    if _status(client, s["id"])["verify"]["state"] != "passed":
        _verified(client, folder)
    assert _status(client, s["id"])["open"]
    assert client.post(f"/api/sessions/{s['id']}/copy/merge", json={}).status_code == 200
    assert (clone / "x.txt").read_text().startswith("why")


def test_merge_anyway_is_the_owner_s_call(client, code):
    s, folder, clone = _copy(client, code)
    client.put("/api/code/verify", json={"repo": str(folder), "gate": True})
    assert client.post(f"/api/sessions/{s['id']}/copy/merge", json={}).status_code == 409
    assert client.post(f"/api/sessions/{s['id']}/copy/merge", json={"anyway": True}).status_code == 200


def test_a_pull_request_also_waits_for_its_checks(client, code, monkeypatch):
    s, folder, clone = _copy(client, code)
    sha = _git(folder, "rev-parse", "HEAD").strip()
    checks = [{"name": "tests", "conclusion": "failure"}]
    merged = []
    monkeypatch.setattr(gitview, "local_repos", lambda refresh=False: [{"path": str(clone), "github": "acme/app"}])
    monkeypatch.setattr(gitview, "_gh_repo", lambda full, path, *a, **k: {
        "number": 7, "head": {"sha": sha, "ref": s["worktree"]["branch"]}, "base": {"ref": "main"}})
    monkeypatch.setattr(gitview, "_checks", lambda full, sha: checks)
    monkeypatch.setattr(gitview, "pull_merge", lambda full, n, method, sha: merged.append(sha) or {"merged": True})
    at = {"repo": "github:acme/app", "number": 7}
    assert client.get("/api/code/gate", params=at).json() == {"active": False}
    assert client.post("/api/git/pull/merge", json=at).status_code == 200          # not held: as before
    client.put("/api/code/verify", json={"repo": str(clone), "gate": True})
    st = client.get("/api/code/gate", params=at).json()
    assert st["checks"]["state"] == "failed" and st["verify"]["state"] == "none" and not st["open"]
    data = gate._load(clone)
    data["reviews"][sha] = {"state": "accepted", "session": "x", "model": "claude-sonnet-5-5", "branch": "b", "at": 1}
    gate._save(clone, data)
    r = client.post("/api/git/pull/merge", json=at)
    assert r.status_code == 409 and "checks" in r.json()["message"] and "review" not in r.json()["message"]
    checks[0]["conclusion"] = "success"
    assert client.get("/api/code/gate", params=at).json()["open"]
    assert client.post("/api/git/pull/merge", json=at).status_code == 200 and merged == [None, sha]
    assert client.post("/api/git/pull/merge", json={**at, "anyway": True, "sha": "f" * 40}).status_code == 200



def test_a_damaged_entry_of_the_gate_state_is_dropped(client, code):
    s, folder, clone = _copy(client, code)
    client.put("/api/code/verify", json={"repo": str(folder), "gate": True})
    branch = s["worktree"]["branch"]
    for junk in ({"reviews": {"abc": "oops"}, "rounds": {}}, {"reviews": {}, "rounds": {branch: "x"}},
                 {"reviews": {}, "rounds": {branch: True}}):
        gate._file(clone).write_text(json.dumps({"clone": str(clone), **junk}))
        r = client.get("/api/code/gate", params={"session": s["id"]})
        assert r.status_code == 200 and r.json()["review"]["rounds"] == 0, r.text[:200]