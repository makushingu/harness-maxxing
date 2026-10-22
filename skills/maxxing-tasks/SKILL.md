---
name: maxxing-tasks
description: Read or edit the Harness Maxxing task board (<workspace>/tasks.json) safely - add, update, move, complete or list tasks and task projects. Use when the user talks about their tasks, to-do list, kanban, what is due today, or asks to add/close a task.
---

# Tasks (tasks.json)

The Tasks page of the UI reads `<workspace>/tasks.json` (workspace from `maxxing status`, here
`{{WORKSPACE}}/tasks.json`). The server re-reads the file when it changes, so your edits show up
in the UI within seconds.

## Schema
```json
{
  "version": 1,
  "projects": [{"id": "p_ab12", "name": "acme", "color": "#6366f1", "workspace": "acme"}],
  "tasks": [{
    "id": "t_9f3c2a", "title": "Write the launch post", "notes": "markdown",
    "status": "todo", "priority": 2, "due": "2026-05-04",
    "project_id": "p_ab12", "topic_path": "projects/acme/topics/blog", "labels": ["writing"],
    "created": 1767225600.0, "updated": 1767225600.0, "done_at": null, "order": 1000.0
  }]
}
```
- `status`: `todo` | `doing` | `done`. `priority`: 0 (none) … 3 (urgent). `due`: `YYYY-MM-DD` or null.
- `project_id` refers to `projects[].id`. Every workspace project has its task project, linked by
  `"workspace": "<project folder name>"` (created by Harness, renamed with the project): to file a task under
  workspace project `acme`, use the id of the project whose `workspace` is `acme`. Projects without `workspace`
  are free projects (e.g. "Personal"); a task may also have no project. `hidden: true` = left out of the
  page's projects bar. Never delete a linked project.
- `topic_path` optionally links a workspace topic (`projects/acme/topics/blog`); a task with a `topic_path`
  and no `project_id` is attached to that project's task project automatically.
- `order`: float, sort order inside a column (to insert between two tasks use the mean of their orders).
- Timestamps are Unix seconds (float). Set `done_at` when moving to `done`, null otherwise.
- Ids: `t_` + 6 hex chars for tasks, `p_` + 4 hex for projects; must be unique.

## Safe editing (always)
1. Read the whole file; if it is not valid JSON, **stop** and tell the user (the UI refuses to
   overwrite a corrupt file too).
2. Change only what is needed; **keep unknown fields** at every level.
3. Update `updated` on every changed task.
4. Write atomically: write `tasks.json.tmp` in the same folder, then rename over `tasks.json`.
Python snippet:
```python
import json, os, secrets, time
p = "{{WORKSPACE}}/tasks.json"
d = json.load(open(p))
now = time.time()
d["tasks"].append({"id": "t_" + secrets.token_hex(3), "title": "Call the accountant", "notes": "",
                   "status": "todo", "priority": 1, "due": None, "project_id": None,
                   "topic_path": None, "labels": [], "created": now, "updated": now,
                   "done_at": None, "order": max([t.get("order", 0) for t in d["tasks"]] + [0]) + 1000})
tmp = p + ".tmp"; json.dump(d, open(tmp, "w"), indent=2, ensure_ascii=False); os.replace(tmp, p)
```

## Answering questions
"What is due today?" -> tasks with `status != done` and `due <= today` (in the configured time zone,
`maxxing status`/config), overdue first, then by priority. Quote titles, keep it short.
