---
section: Using Harness Maxxing
---
# Starter projects

Starter projects (packs) are ready-made projects for a kind of work. Each topic already knows the job - a
playbook: good practices, what to connect, the usual scheduled jobs, the common mistakes - and asks you a few
questions at its first session (your shop, your stack, your clients...). There is no fake data: the answers you
give are written into the topic's `memory.md`, so the project becomes yours from the first exchange.

| Pack | Project | Topics | Scheduled jobs (created disabled) |
|---|---|---|---|
| 🛒 Online store | `ecommerce` | `code`, `orders`, `ads`, `social` | Orders report, Ads review |
| 🤝 Affiliate site | `affiliate` | `website`, `blog`, `affiliation`, `google` | Broken affiliate links, SEO report |
| 🎬 Content creator | `creator` | `scripts`, `video`, `stats` | Weekly stats review |
| 🧩 Apps | `apps` | `template`, `hosting`, `app-1`, `app-2`, `app-3` | Uptime check |
| 🧠 Second brain | `second-brain` | `journal`, `knowledge`, `reading`, `ideas` | Weekly journal review, Ideas triage |
| 💼 Freelance business | `freelance` | `clients`, `proposals`, `prospecting`, `admin` | Follow-ups due, Unpaid invoices |

## Adding a pack

- **At the first sign-in**: the onboarding step "Your projects" offers **Install all**, **Choose** (tick the
  cards) or **None**. You can also create your own project there.
- **Any time later**: **Settings -> Starter pack**, then **Add** on a card.
- **By asking**: in `system/harness`, say "add the freelance pack".
- **From the server**: `maxxing packs list`, then `maxxing packs add freelance` (several ids at once work).

Add a pack as many times as you like: each time it is a **new project** - `ecommerce`, then `ecommerce-2` for a
second store, and so on (rename it from the Sessions page). Nothing existing is ever touched. The pack's
scheduled jobs are created **disabled** (named "Orders report (ecommerce-2)" for a second copy): enable them on
the Crons page, or ask in the topic ("enable the orders report").

## Putting back the default projects

The first card, **Default projects**, is what a new install starts with: `general/inbox` and `system`
(tutorial, help, harness). **Put back** re-creates the ones you deleted, and any missing file, without
overwriting your edits. From the server: `maxxing packs add basics`.

## Making it yours

Rename a project or a topic, delete the topics you do not need, or add new ones from the Sessions page: a pack
is only a starting point. The playbook lives in each topic's `CLAUDE.md` (edit it to change how Claude works
there); what Claude learns goes to `memory.md`.
