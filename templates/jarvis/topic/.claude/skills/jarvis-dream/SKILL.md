---
name: jarvis-dream
description: "Jarvis's night pass: read what changed since the last pass (maxxing jarvis digest: projects, memory files, sessions, tasks, notifications, work board), consolidate brain/ (summary.md, projects.md, owner.md, tasks.md, journal.md, inbox.md), flag what waits for the owner. Use on a [Night pass] message, or when the owner asks Jarvis to consolidate its memory now."
---

# Night pass: consolidate brain/

Folder: Jarvis's `{{WORKSPACE}}/projects/jarvis/topics/main/brain/` (noted `B/`). Read anywhere; **write only in `B/`**: no project memory, no tasks.json,
no session, agent or cron changes (propose them in the journal). Do not write to the owner (no `sessions send`).

## 1. Collect
`maxxing jarvis digest` (since the last pass; the first pass: `maxxing jarvis digest --since 2400` and read **every**
project memory.md). Then read:
- every file listed under "Memory files changed";
- `B/inbox.md`;
- the owner's own words in the sessions of the digest (their messages are the best source on what they want); a
  session in full only when needed: `{{WORKSPACE}}`'s session is in `maxxing sessions list --json`, its last answer in
  the digest.

## 2. Consolidate (rewrite each file whole, clean, no duplicate)
- **`B/projects.md`**: one section per active project (`## <project>`), 4-8 lines: goal (1 line), state on <date>,
  work in progress (sessions, agents), next steps, blockers, links (sites, folders). Paused or dropped projects
  grouped at the end, one line each. The project's memory is the truth; if the owner said something more recent that
  contradicts it, keep the owner's version and say it in the journal.
- **`B/owner.md`**: § Goals (long term), § Priorities now (in order), § How they decide / like to work, § People
  (role, project, last contact), § Commitments (date, to whom). Only what is true and useful; do not copy the global
  memory.
- **`B/tasks.md`**: late, today, this week, urgent without a date, count per project; tasks that look done according
  to the sessions but are still open (to propose closing).
- **`B/journal.md`**: on top, an entry `## YYYY-MM-DD` (owner's time zone) in 10 lines at most: what moved, what failed
  (jobs, agents, sites), what waits for an answer of the owner, proposals (task to create or close, session to go on
  with, agent to switch off, work to close on the board). Drop entries older than 30 days.
- **`B/inbox.md`**: each note filed in the right file, then removed; keep the title line.
- **`B/summary.md`** (6 KB at most, loaded in every conversation), in this order:
  `# Summary (night pass of YYYY-MM-DD)`, then § Owner's priorities (3-5), § Waiting for the owner (answers,
  decisions, failures to look at), § Projects (1 line each: state + next step, with its topic path), § Open work (from
  the board), § Tasks (counts + the 5 most urgent), § People (1 line each), § Files (pointers to projects.md,
  owner.md, tasks.md, journal.md).

## 3. Finish
- Check: no secret written, `B/summary.md` 6 KB at most (`wc -c`).
- `maxxing jarvis digest --mark` (only once everything is written).
- Final answer: 5 lines at most, what waits for the owner first.
- Something urgent (a site down, an order blocked, a repeated failure): `maxxing feed post "Jarvis: <title>" --body
  "<detail>" --source jarvis --level warning`.
