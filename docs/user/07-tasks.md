---
section: Using Harness Maxxing
---
# Tasks

The **Tasks** page shows your tasks by project, as a kanban board (To do / Doing / Done), a week, a
calendar or a list. It is stored in a plain JSON file in your workspace, `tasks.json`, so Claude can read
and update it too.

Tasks is optional: switch it on or off in **Settings -> Features -> Tasks**. It is off on a new install and
stays on for installs that already had it. Off hides the **Tasks** entry of the sidebar (and its shortcut) and
the dashboard widget; nothing is deleted: `tasks.json` stays in the workspace, Claude can still read and change it
(skill `maxxing-tasks`), and everything is back as it was when you switch it on again.

## Projects

Every project of your workspace (the ones in **Sessions**) is also a task project: it appears by itself when
you create the project, follows it when you rename it, and when you delete the project its tasks are kept in
a free project of the same name. You can add free projects too (Personal, Admin...), and a task does not
need a project.

The list of projects (in the second bar next to the sidebar on a computer, see
[Sessions](04-sessions.md#layout); under **☰** at the top left on a phone) picks what you see:
- **Overview**: one card per project with its open tasks, progress, overdue and urgent tasks and the next
  due date; projects that need attention come first. Click a card to open the project.
- **All tasks**, **No project**, or one project: its header shows its progress and a **Sessions** button
  that opens the project in Sessions. **New task** files new tasks in the project you are looking at.
- Hide a project you do not use for tasks with its **⋯** menu (the `system` project is hidden at first);
  **N hidden projects** at the bottom shows them again. The gear icon next to **Projects** renames them and changes
  their color.

A link to one project: `/tasks?project=<workspace project name>`.

## Views

At the top right of the page: the view switch, **By project** (board, All tasks), **Filters** and **New task**.

- **Board**: drag cards between columns and to reorder them (a task whose status you change in its sheet goes
  on top of Done, at the bottom of the other columns). In **All tasks**, **By project** shows one
  board row per project (fold a row with its arrow).
- **Week**: open tasks in columns by due date: overdue, today, the next six days, later, no date. Drag a
  card onto a day (or onto **No date**) to change its due date; **Add a task** under a day creates it for
  that day.
- **Calendar**: the month, with each task on its due date. Click a day to list its tasks below the
  grid and add one for that day; on a computer, drag a task to another day.
- **List**: grouped by due date, by project or (inside a project) by topic, sortable: **Group by**, **Sort** and
  **Show done** sit above the list.

## Using the board

- **New task** (or the `N` key) opens a small field: type the title and press Enter (Esc closes it). Shortcuts
  in the title: `#label`, `!` / `!!` / `!!!` for the priority, `@project`, `^date` (`^tomorrow`, `^fri`,
  `^2026-05-04`). Then add notes (markdown), priority (none, low, medium, urgent), due
  date, labels, a task project (with a color) and optionally a linked workspace topic.
- **Several at once**: Ctrl/⌘ + click cards (or click the round box in their corner, or the one
  next to a column / group title) to select them. A bar appears at the bottom: change their
  status, priority, due date, project or labels in one go, or delete them. Dragging a selected
  card moves the whole selection to the other column. **Esc** clears the selection; **Select all** in the bar
  (or Ctrl/⌘ + A once a task is selected) selects every visible task.
- **Filters** filters by label, priority or due date ("today" shows overdue and due-today tasks); the active
  filters show as chips above the tasks, × removes one. To find a task by its words, use **Ctrl/⌘+K**.
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
- A value the page does not understand (`"status": "in_progress"`, `"due": "2026-13-01"`) shows as the
  default (to do, no date) but stays as written in the file until you change that field in the page; a
  project written without an `id` gets one instead of being dropped.
- If the file is not valid JSON, the page shows an error and never overwrites it: fix the file
  (or ask Claude to) and reload.
