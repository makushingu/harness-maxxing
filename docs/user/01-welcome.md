---
section: Getting started
---
# Welcome to Harness Maxxing

Harness Maxxing is a self-hosted control room for **Claude Code** on your own server. It lets you
run many persistent Claude conversations organised by project and topic, from a browser or from
Telegram, together with the files, tasks, scheduled jobs and memory that make them useful.

Everything runs on your server, with your own Claude account or API key. Nothing else leaves it except
an anonymous daily counter (version, system, health codes; no name, no IP, no content), which you can turn off
in Settings → Profile - see [License](license#saying-hello-optional).

## Concepts

| Concept | What it is |
|---|---|
| **Workspace** | The folder Claude works in (default `/root/maxxing`). It holds your projects, the task board and your extensions. |
| **Project** | A folder `projects/<project>/` for one area of work: a client, a product, a website. |
| **Topic** | A sub-folder `projects/<project>/topics/<topic>/`: one stream of work inside a project (for example `acme / blog`). Every session runs inside a topic. |
| **Session** | One Claude conversation. A topic can have many sessions; each one keeps its history and can be resumed weeks later. |
| **Memory** | Plain markdown files: `CLAUDE.md` (instructions) and `memory.md` (what was learned) at three levels: workspace, project, topic. Claude loads them automatically. |
| **Skills** | Instructions Claude Code loads when they are relevant. Harness Maxxing ships skills to set itself up, diagnose problems, write extensions and keep memory tidy. |
| **Cron (job)** | A shell command or a Harness prompt run on a schedule, with history and Telegram reports. |

A session started in `projects/acme/topics/blog/` automatically knows the global memory, the
`acme` project memory and the `blog` topic memory. You never have to re-explain the context.

## Default projects

A new workspace is not empty: it explains and maintains itself.

| Project | Topics | What for |
|---|---|---|
| `general` | `inbox` | quick questions and one-off tasks |
| `system` | `help`, `update`, `server`, `tasks`, `accounts`, `extensions` | Harness Maxxing itself: ask how to do something, update the product, look after the server, manage tasks, keep an inventory of your subscriptions, build extensions. See [The system project](system-project). |
| `tutorial` | `1-first-steps`, `2-files-and-memory`, `3-tasks-and-crons`, `4-telegram-and-voice` | four interactive 5-minute lessons: open a lesson, start a session and say "hi". Delete the project when you are done; updates never bring it back. |

These are ordinary projects: rename, extend or delete them. Updates only add files that are
missing and never re-create a project or topic you deleted.

## What you can do

- **Sessions**: several conversations side by side, live streaming, attachments, message queue
  (steer, edit, or ask a side question without interrupting), plan mode (validate before any change),
  HUD mode, model choice per session, stop, compact, hand off, archive, full-text search, move a
  session to another topic.
- **Sessions list**: three layouts (tree, one level at a time, sessions only), favorites and recent
  sessions on top, an emoji per project.
- **Files**: browse, edit, and preview almost anything in one viewer (pictures, videos, PDF, CSV as a
  table, HTML pages, archives, fonts), with ← / → through the files of a conversation or a folder.
- **Infra** (Settings -> Features): every site, database, bucket, domain and server, here and at Cloudflare /
  Hostinger, with its status; a Hostinger VPS connects in one click; ask Claude to put a site online or create a
  database, it is done the standard way.
- **Tasks**: a kanban board stored in `tasks.json`, which Claude can read and update.
- **Crons**: scheduled shell commands or Harness prompts, with history and Telegram reports.
- **Telegram**: talk to the same sessions from your phone, one thread per open session.
- **Backup**: your memory pushed every day to a private GitHub repository.
- **Dashboard and extensions**: built-in widgets plus your own widgets and pages.
- **Starter projects**: ready-made projects for an online store, an affiliate site, a content creator, apps, a
  second brain or a freelance business - their topics already know the job (Settings -> Starter pack).
- **Notifications**: a feed next to the widgets (and a Telegram thread if you want) for cron jobs, sales,
  orders, deployments and your scripts - Stripe, Shopify, GitHub or any webhook, or `maxxing feed post`.
- **Your look**: light or dark, six accent colors (the logo follows), a neutral or tinted background,
  23 interface fonts and 11 code fonts.
- **Customize and import**: change the product's code and keep your changes across updates; import
  your memory and skills from another agent.

## Where to go next

1. [Installation](installation) if the server is not installed yet.
2. [Onboarding](onboarding) for the first sign-in.
3. The topic `system/tutorial` (Sessions page) to learn by doing, in four 5-minute lessons.
4. [Sessions](sessions) to start working.
