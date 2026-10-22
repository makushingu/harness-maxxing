---
section: Getting started
---
# Import from another agent

Coming from Hermes, Claude Code, OpenClaw or any other agent? Bring what it knows about you -
projects, topics, memory, skills, to-dos, scheduled jobs - in a few minutes. Onboarding step 3, or
Settings -> **Import** at any time.

## 1. Ask your old agent for a zip

Pick your agent and press **Copy the prompt**, then send it to the old agent. It builds a folder
and zips it (`maxxing import --prompt hermes` prints the same prompt in a terminal):

```
harness-maxxing-export/
  memory.md                                      who you are, preferences, global facts
  projects/<project>/CLAUDE.md, memory.md        what the project is / its facts and decisions
  projects/<project>/topics/<topic>/CLAUDE.md, memory.md, useful files
  skills/<skill>/SKILL.md                        reusable procedures
  tasks.md, crons.md, SECRETS.md                 to-dos, recurring jobs, names of the keys you use
```

The prompt tells it never to write a key or a password - only their names in `SECRETS.md`.

## 2. Drop the zip

You first see a preview: new projects and topics, the ones that already exist (merged), skills,
files kept aside for Claude, and files refused. Press **Import**.

- **Nothing is overwritten.** A memory.md or CLAUDE.md that already has content receives an
  `## Imported (date)` section at the end; any other existing file is kept and the imported copy is
  saved next to it as `<name> (imported).<ext>`; an existing skill is kept and the imported one is
  saved as `<name>-imported`.
- Folder names are turned into valid names (`Coffee Shop` -> `coffee-shop`).
- **Files containing a key or a token are refused** (reported by type, never by value). Add your
  keys in Settings -> Keys.
- Unsafe archives are refused: paths leaving the folder, links, more than 20,000 files or 500 MB
  once unzipped (a 600 MB upload at most).
- Settings are never imported: Claude Code settings (`.claude/settings.json`, `.mcp.json`) and Harness folder
  settings (`.maxxing.json`, which holds a topic's permission mode, and `.order.json`). Set them in the app.
- A file that cannot be placed (a folder of the same name is already there, a file stands where its folder
  should be, or a link in your workspace would carry it outside) is skipped and listed in the report; the rest
  is imported.
- `tasks.md`, `crons.md`, `SECRETS.md` and anything outside `projects/` and `skills/` are kept in
  `imports/<date>/` with an `IMPORT_REPORT.md`.

## 3. Let Harness finish

**Let Harness finish the import** opens a session (in `general/inbox`) where Claude reads the report,
tidies the imported memory, creates your tasks, proposes your recurring jobs (and asks before
creating them) and lists the keys to add. During the onboarding it starts by itself.

## From the terminal

```bash
maxxing import --prompt openclaw          # the prompt for your old agent
maxxing import export.zip --dry-run       # what would be imported
maxxing import export.zip                 # import (same rules as the UI)
```
