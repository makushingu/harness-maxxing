"""tasks.json is shared with Claude: an odd hand-written task or an edit made during a request must not break or be lost."""
from __future__ import annotations

import json
import math

from maxxing import search
from maxxing.api import tasks as tasks_api


def test_a_hand_written_task_with_odd_fields_keeps_the_search_working(client, mx):
    """Notes written as a list (or a number as a title) made the search index refresh fail and roll back every
    time, so no file, memory or task was found any more."""
    (mx["ws"] / "notes.md").write_text("zanzibarquux\n")
    (mx["ws"] / "tasks.json").write_text(json.dumps({"version": 1, "projects": [], "tasks": [
        {"id": "t_1", "title": "x", "notes": ["a", "b"]},
        {"id": "t_2", "title": 42, "notes": {"k": "v"}, "topic_path": ["p"], "updated": "yesterday"},
    ]}))
    search.refresh(full=True, deep=True)
    assert search.search("zanzibarquux")["results"], "the refresh was rolled back: nothing is indexed any more"
    tasks = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert tasks["t_1"]["notes"] == '["a", "b"]'
    assert tasks["t_2"]["title"] == "42" and tasks["t_2"]["topic_path"] == '["p"]'
    assert isinstance(tasks["t_2"]["updated"], float)


def _edit_on_disk(title: str) -> None:
    d = json.loads(tasks_api.tasks_path().read_text())
    d["tasks"].append({"id": f"t_{len(d['tasks'])}x", "title": title})
    tasks_api.tasks_path().write_text(json.dumps(d))


def test_an_edit_made_by_claude_during_a_request_is_kept(client, mx, monkeypatch):
    """Claude writes tasks.json while the server is between reading and writing it for the UI: the server used to
    write its stale copy back and Claude's task vanished. Now the UI change is applied on top of the new file."""
    t = client.post("/api/tasks", json={"title": "ui"}).json()
    real, calls = tasks_api._apply, []

    def claude_edits_meanwhile(task, body, data, fields):
        if not calls:
            _edit_on_disk("added by Claude")
        calls.append(1)
        real(task, body, data, fields)

    monkeypatch.setattr(tasks_api, "_apply", claude_edits_meanwhile)
    r = client.patch(f"/api/tasks/{t['id']}", json={"title": "ui 2"})
    monkeypatch.setattr(tasks_api, "_apply", real)
    assert r.status_code == 200, r.text
    tasks = {x["title"]: x for x in client.get("/api/tasks").json()["tasks"]}
    assert "added by Claude" in tasks and "ui 2" in tasks and "ui" not in tasks
    assert len(calls) == 2                                          # applied again on the fresh file


def test_a_file_that_keeps_changing_is_a_conflict_not_a_lost_update(client, mx, monkeypatch):
    t = client.post("/api/tasks", json={"title": "ui"}).json()
    real = tasks_api._apply

    def always_edited(task, body, data, fields):
        _edit_on_disk("Claude again")
        real(task, body, data, fields)

    monkeypatch.setattr(tasks_api, "_apply", always_edited)
    r = client.patch(f"/api/tasks/{t['id']}", json={"title": "ui 2"})
    monkeypatch.setattr(tasks_api, "_apply", real)
    assert r.status_code == 409 and r.json()["error"] == "conflict", r.text
    titles = [x["title"] for x in client.get("/api/tasks").json()["tasks"]]
    assert titles.count("Claude again") == 3 and "ui" in titles


def test_text_timestamps_of_a_hand_written_task_are_read_not_dropped():
    assert tasks_api._num("1767225600", None) == 1767225600.0
    assert tasks_api._num("2026-10-01T00:00:00+00:00", None) == 1790812800.0
    assert tasks_api._num("2026-10-01", None) is not None
    assert tasks_api._num("soon", 5) == 5 and tasks_api._num(True, 5) == 5


def test_a_huge_priority_does_not_break_the_task_page(client, mx):
    """"priority": 1e999 is read as infinity: int() raised OverflowError and every GET /api/tasks answered 500."""
    (mx["ws"] / "tasks.json").write_text('{"version": 1, "projects": [], "tasks": [{"id": "t_1", "title": "x", "priority": 1e999}]}')
    r = client.get("/api/tasks")
    assert r.status_code == 200 and r.json()["tasks"][0]["priority"] == 0


def test_infinite_order_or_dates_do_not_break_the_task_page(client, mx):
    """An infinite or NaN order / created passed load() but the JSON answer failed (500)."""
    (mx["ws"] / "tasks.json").write_text('{"version": 1, "projects": [], "tasks": ['
                                         '{"id": "t_1", "title": "x", "order": 1e999, "created": "1e999"},'
                                         '{"id": "t_2", "title": "y", "order": NaN, "updated": -1e999, "done_at": "nan"},'
                                         '{"id": "t_3", "title": "z", "created": 1' + "0" * 400 + '}]}')
    r = client.get("/api/tasks")
    assert r.status_code == 200
    tasks = {t["id"]: t for t in r.json()["tasks"]}
    assert tasks["t_1"]["order"] == 0 and tasks["t_2"]["order"] == 0 and tasks["t_2"]["done_at"] is None
    assert all(math.isfinite(t[k]) for t in tasks.values() for k in ("created", "updated"))


def test_a_project_whose_workspace_is_not_text_does_not_break_the_task_page(client, mx):
    """_sync() keys a dict by "workspace": a list raised TypeError (unhashable) on every GET /api/tasks."""
    (mx["ws"] / "tasks.json").write_text(json.dumps({"version": 1, "tasks": [], "projects": [
        {"id": "p_1", "name": "a", "workspace": ["a"]}, {"id": "p_2", "name": "b", "workspace": {"k": 1}}]}))
    r = client.get("/api/tasks")
    assert r.status_code == 200
    assert not any(isinstance(p.get("workspace"), (list, dict)) for p in r.json()["projects"])


def test_reading_the_tasks_does_not_copy_the_whole_file(client, mx, monkeypatch):
    """GET /api/tasks deep-copied the cached tasks.json twice (sync_workspace, then the read) and the dashboard
    widget once: ~290 ms per list with 5000 tasks. Reads now share the cache; only writers get a copy."""
    (mx["ws"] / "tasks.json").write_text(json.dumps({"version": 1, "projects": [], "tasks": [
        {"id": f"t_{i}", "title": f"task {i}", "labels": ["a"]} for i in range(50)]}))
    assert client.get("/api/tasks").status_code == 200        # warm the cache and the workspace sync
    copies = []
    real = tasks_api.copy.deepcopy
    monkeypatch.setattr(tasks_api.copy, "deepcopy", lambda x, *a: copies.append(1) or real(x, *a))
    assert len(client.get("/api/tasks").json()["tasks"]) == 50
    assert tasks_api.summary()["open"] == 50
    assert copies == []
    r = client.patch("/api/tasks/t_1", json={"title": "renamed"})  # writers still work on their own copy
    assert r.status_code == 200 and copies
    tasks = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert tasks["t_1"]["title"] == "renamed" and tasks["t_2"]["title"] == "task 2"
