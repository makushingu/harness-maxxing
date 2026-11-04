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


def test_an_edit_landing_while_the_server_writes_is_kept(client, mx, monkeypatch):
    """The signature was checked before the dump and the fsync (71 ms for 5000 tasks): a rename by Claude in that
    window was replaced by the server's copy. Now it is checked again right before the server's rename."""
    t = client.post("/api/tasks", json={"title": "ui"}).json()
    real, calls = tasks_api.config._atomic_write, []

    def claude_renames_during_the_dump(path, data, mode=None, before_replace=None):
        def edit_then_check():
            if not calls:
                _edit_on_disk("added by Claude")
            calls.append(1)
            if before_replace:
                before_replace()
        real(path, data, mode, edit_then_check)

    monkeypatch.setattr(tasks_api.config, "_atomic_write", claude_renames_during_the_dump)
    r = client.patch(f"/api/tasks/{t['id']}", json={"title": "ui 2"})
    monkeypatch.setattr(tasks_api.config, "_atomic_write", real)
    assert r.status_code == 200, r.text
    assert len(calls) == 2                                          # applied again on the fresh file
    titles = {x["title"] for x in client.get("/api/tasks").json()["tasks"]}
    assert titles == {"added by Claude", "ui 2"}


def test_a_server_write_keeps_hand_written_projects_and_values(client, mx):
    """A project without an id was dropped by the next UI action, and values the reader does not understand
    ("in_progress", a due date with a time, labels as text) were reset to their defaults on disk."""
    (mx["ws"] / "tasks.json").write_text(json.dumps({"version": 1, "projects": [{"name": "Personal", "color": "blue"}], "tasks": [
        {"id": "t_1", "title": "hand", "status": "in_progress", "due": "2026-11-05T10:00", "labels": "urgent", "priority": "high"},
    ]}))
    listed = client.get("/api/tasks").json()
    pid = listed["projects"][0]["id"]
    assert pid.startswith("p_") and listed["tasks"][0]["status"] == "todo"
    assert client.get("/api/tasks").json()["projects"][0]["id"] == pid      # stable until saved
    assert client.post("/api/tasks", json={"title": "ui", "project_id": pid}).status_code == 200
    d = json.loads((mx["ws"] / "tasks.json").read_text())
    assert [p["name"] for p in d["projects"]] == ["Personal"] and d["projects"][0]["id"] == pid
    hand = next(x for x in d["tasks"] if x["id"] == "t_1")
    assert (hand["status"], hand["due"], hand["labels"], hand["priority"]) == ("in_progress", "2026-11-05T10:00", "urgent", "high")
    # a field the API changes is written normalised
    client.patch("/api/tasks/t_1", json={"status": "doing", "labels": ["a"]})
    hand = next(x for x in json.loads((mx["ws"] / "tasks.json").read_text())["tasks"] if x["id"] == "t_1")
    assert (hand["status"], hand["labels"], hand["due"]) == ("doing", ["a"], "2026-11-05T10:00")


def test_an_impossible_due_date_written_by_hand_is_no_date(client, mx):
    """"2026-13-01" matched the YYYY-MM-DD pattern and crashed every page that formats the date."""
    (mx["ws"] / "tasks.json").write_text(json.dumps({"version": 1, "projects": [], "tasks": [
        {"id": "t_1", "title": "a", "due": "2026-13-01"}, {"id": "t_2", "title": "b", "due": "2026-02-30"},
        {"id": "t_3", "title": "c", "due": "2026-02-28"}]}))
    due = {t["id"]: t["due"] for t in client.get("/api/tasks").json()["tasks"]}
    assert due == {"t_1": None, "t_2": None, "t_3": "2026-02-28"}


def test_a_card_dropped_between_two_equal_orders_lands_there(client, mx):
    """Hand-written tasks all have order 0: the old midpoint (0 + 0.0005) sent the card to the end of the run."""
    (mx["ws"] / "tasks.json").write_text(json.dumps({"version": 1, "projects": [], "tasks": [
        {"id": f"t_{c}", "title": c, "created": i} for i, c in enumerate("ABCD")]}))
    r = client.patch("/api/tasks/t_D", json={"status": "todo", "order": 0.0005, "prev_id": "t_A", "next_id": "t_B"})
    assert r.status_code == 200, r.text
    tasks = sorted(client.get("/api/tasks").json()["tasks"], key=lambda t: (t["order"], t["created"]))
    assert "".join(t["title"] for t in tasks) == "ADBC"
    # room left: only the dropped card moves
    r = client.patch("/api/tasks/t_C", json={"status": "todo", "prev_id": "t_A", "next_id": "t_D"}).json()
    assert 1.0 < r["order"] < 2.0


def test_a_status_change_without_order_puts_the_task_on_top_of_done(client, mx):
    """The task sheet changes only the status: the task kept its old order and could sink past Done's first page."""
    ids = [client.post("/api/tasks", json={"title": f"d{i}", "status": "done"}).json()["id"] for i in range(3)]
    t = client.post("/api/tasks", json={"title": "todo"}).json()
    for _ in range(5):
        client.post("/api/tasks", json={"title": "more"})
    moved = client.patch(f"/api/tasks/{t['id']}", json={"status": "done"}).json()
    done = [x for x in client.get("/api/tasks").json()["tasks"] if x["status"] == "done"]
    assert moved["order"] < min(x["order"] for x in done if x["id"] in ids)
    back = client.patch(f"/api/tasks/{t['id']}", json={"status": "todo"}).json()
    todo = [x for x in client.get("/api/tasks").json()["tasks"] if x["status"] == "todo" and x["id"] != t["id"]]
    assert back["order"] > max(x["order"] for x in todo)
