---
section: Using Harness Maxxing
---
# The system project

Every workspace comes with a project `system` dedicated to Harness Maxxing itself. Each topic has
instructions telling Claude exactly how to behave there: open the topic, start a session and ask
in your own words.

| Topic | Say for example | What Claude does |
|---|---|---|
| `tutorial` | "hi", "lesson 3" | four 5-minute hands-on lessons (first steps, files and memory, tasks and crons, Telegram and voice); remembers where you stopped, and at the end offers to delete the topic (it goes to the Trash for 30 days) |
| `help` | "how do I schedule a job?", "how is the server doing?" | answers from the documentation of the version installed on your server (these pages), then offers to do it for you; looks after the server: health (`maxxing doctor`, `maxxing status`), disk, services, logs, security updates, firewall, and asks before anything destructive or a reboot |
| `harness` | "update", "make a widget showing my site's visitors", "add the freelance pack" | runs `maxxing update --check`, explains the changes in plain language, updates after your yes, then applies the workspace upgrade notes of the new version and records it; writes dashboard widgets and pages in `<workspace>/extensions/`; adds starter packs (`maxxing packs add <id>`) |

Tasks and subscriptions are handled in **`general/inbox`** (or any session): "add a task for
Friday", "what is due this week?" read and edit the task board (`tasks.json`); "I just subscribed
to X for 12 €/month", "what renews soon?" keep `accounts.md` in that topic (service, plan, cost,
renewal date, login email, notes) and list renewals in the next 30 days. **Never** passwords or
keys: those go to Settings -> Keys.

## Starter packs

Ready-made projects with their topics and instructions: `ecommerce`, `affiliate`, `creator`,
`apps`, `second-brain`, `freelance`. Add one from Settings -> Starter pack or by asking in
`system/harness`. An existing project is never overwritten: only missing files are added.

## Jobs linked to these topics

| Job | Default | What it does |
|---|---|---|
| Check for updates | on, Mondays 09:00 | `maxxing update --check --notify`: a Telegram message when a new version exists ("open system/harness and say: update"). Never updates by itself |
| Morning tasks | off | daily 08:00 in `general/inbox`: overdue and today's tasks on Telegram |
| Renewal reminder | not created | ask in `general/inbox` ("remind me of my renewals"): Claude creates it, Mondays 09:30, renewals in the next 30 days on Telegram |

Turn them on, change the hour or delete them on the Crons page. A deleted default job is never
re-created.

## Updates and your workspace

Updates replace the product code but never edit your files, and keep your changes to the product
itself ([customizations](customizing)): when they conflict with a new version, nothing changes
until Claude has adapted them in `system/harness`. When a version needs a change in your
workspace (for example a new section in the root `CLAUDE.md`), it ships *upgrade notes* for Claude
in `<code>/docs/upgrade/<version>.md`. In the topic `system/harness`, Claude applies the notes of
every version you skipped, checking first and asking before touching anything you wrote, and keeps
track of the last version applied in that topic's `memory.md`.

## Customising

The `system` project is an ordinary project: edit the topics' `CLAUDE.md` to change how Claude
behaves, add your own topics, or delete what you do not need (it is not re-created by updates).
