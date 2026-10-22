---
section: Using Harness Maxxing
---
# Tasks

The **Tasks** page shows your tasks by project, as a kanban board (To do / Doing / Done), a week, a
calendar or a list. It is stored in a plain JSON file in your workspace, `tasks.json`, so Claude can read
and update it too.

## Projects

Every project of your workspace (the ones in **Sessions**) is also a task project: it appears by itself when
you create the project, follows it when you rename it, and when you delete the project its tasks are kept in
a free project of the same name. You can add free projects too (Personal, Admin...), and a task does not
need a project.

The column on the left (a row of chips on a phone) picks what you see:
- **Overview**: one card per project with its open tasks, progress, overdue and urgent tasks and the next
  due date; projects that need attention come first. Click a card to open the project.
- **All tasks**, **No project**, or one project: its header shows its progress and a **Sessions** button
  that opens the project in Sessions. Quick add files new tasks in the project you are looking at.
- Hide a project you do not use for tasks with its **⋯** menu (the `system` project is hidden at first);
  **N hidden projects** at the bottom shows them again. **Projects** (the gear icon, at the end of the chips on a
  phone) renames them and changes their color.

A link to one project: `/tasks?project=<workspace project name>`.

## Views

- **Board**: drag cards between columns and to reorder them. In **All tasks**, **By project** shows one
  board row per project (fold a row with its arrow).
- **Week**: open tasks in columns by due date: overdue, today, the next six days, later, no date. Drag a
  card onto a day (or onto **No date**) to change its due date; **Add a task** under a day creates it for
  that day.
- **Calendar**: the month, with each task on its due date. Click a day to list its tasks below the
  grid and add one for that day; on a computer, drag a task to another day.
- **List**: grouped by due date, by project or (inside a project) by topic, sortable.

## Using the board

- Create a task with a title; add notes (markdown), priority (none, low, medium, urgent), due
  date, labels, a task project (with a color) and optionally a linked workspace topic.
- **Several at once**: Ctrl/⌘ + click cards (or click the round box in their corner, or the one
  next to a column / group title) to select them. A bar appears at the bottom: change their
  status, priority, due date, project or labels in one go, or delete them. Dragging a selected
  card moves the whole selection to the other column. **Esc** clears the selection; **Select all** in the bar
  (or Ctrl/⌘ + A once a task is selected) selects every visible task.
- Filter by label, priority or due date; "today" shows overdue and due-today tasks.
- The dashboard widget **Tasks** summarizes what is in progress and due.

## Asking Claude

In any session: "add a task to call the accountant on Friday", "what is due this week?", "close
the launch tasks". The `maxxing-tasks` skill knows the file format and writes it safely. The page
refreshes by itself within seconds.

When Claude changes the file while you edit a task on the page, both changes are kept: yours is applied
on top of the file as Claude left it.

## File format

```json
{
  "version": 1,
  "projects": [{"id": "p_ab12", "name": "acme", "color": "#6366f1", "workspace": "acme"}],
  "tasks": [{
    "id": "t_9f3c2a", "title": "Write the launch post", "notes": "",
    "status": "todo", "priority": 2, "due": "2026-05-04",
    "project_id": "p_ab12", "topic_path": "projects/acme/topics/blog", "labels": ["writing"],
    "created": 1767225600.0, "updated": 1767225600.0, "done_at": null, "order": 1000.0
  }]
}
```

- `status`: `todo`, `doing`, `done`; `priority`: 0–3; `due`: `YYYY-MM-DD` or `null`.
- A project with `workspace` follows that workspace project; `hidden: true` leaves it out of the projects
  column.
- Unknown fields are preserved, so you can add your own.
- A field of the wrong type (a list of notes, a number as a title) is read as text instead of breaking
  the page or the search.
- If the file is not valid JSON, the page shows an error and never overwrites it: fix the file
  (or ask Claude to) and reload.
