---
section: Using Harness Maxxing
---
# Memory

Claude has no memory between conversations – except what is written in files. Harness Maxxing
organises that memory in plain markdown files that Claude Code loads automatically.

## Three levels

```
/root/maxxing/
  CLAUDE.md  memory.md                         workspace (global)
  projects/acme/
    CLAUDE.md  memory.md                       project acme
    topics/blog/
      CLAUDE.md  memory.md                     topic acme / blog
```

Claude Code loads every `CLAUDE.md` from the session folder up to the workspace root, and each
`CLAUDE.md` contains the line `@memory.md`, which imports its memory file. A session in
`projects/acme/topics/blog/` therefore reads all six files.

| File | Contains | Who writes it |
|---|---|---|
| `CLAUDE.md` | stable instructions: what the project/topic is, how to work on it. The first paragraph under the title is the description shown in the UI. | you (or Claude when you ask) |
| `memory.md` | what was learned: decisions, preferences, state of the work, useful paths and URLs | Claude, through the `memory` skill |

## What goes where

- **Topic memory** (most common): the state of this work stream, its decisions and conventions.
- **Project memory**: what is true for every topic of the project.
- **Global memory**: your preferences and rules valid everywhere (language, tone, "never push
  without asking"...). Keep it short – it is loaded in every session.

Not in memory: chit-chat, one-off questions, step-by-step logs, and **never secrets** (put them in
Settings -> Keys and mention only the key name).

## The memory skills

- **`memory`** – at the end of a significant exchange Claude records durable facts in the right
  file: short dated bullets, replacing outdated facts instead of piling them up. You can also ask
  explicitly: "remember that ...".
- **`memory-compaction`** – keeps files short and consistent. A scheduled job "Memory compaction"
  runs it every day at 05:00 (see Crons; it starts once the onboarding is finished with Claude signed in). It acts on files longer than the **line limit**
  (Settings -> **Memory**, 200 lines by default) or redundant, contradictory or outdated: it merges
  duplicates, summarizes old history and reorders each file (rules and preferences, current
  state, decisions, references, context). It only edits `memory.md` files.

## Second brain cleaner (Settings -> Memory)

- **Maximum length per file**: the line limit above (or *No limit*).
- **Clean now**: starts the compaction immediately, in a session at the workspace root that you
  can watch.
- The list shows every `memory.md` with its line count; files over the limit are in red.
- From a shell: `maxxing memory` prints the same list.

## Editing memory yourself

Memory files are ordinary files: open them in **Files**, edit, save. Changes apply to the next
turn of every session in that scope.

## Backup

Memory is the most valuable thing on the server. Enable the [Backup](backup) to push it to a
private GitHub repository every day, with history.
