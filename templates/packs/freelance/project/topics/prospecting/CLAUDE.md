# Topic prospecting

Find and approach new clients: "find 10 agencies in Lyon that could need a copywriter", "research
example.com before my call", "draft a first message to their marketing lead".

@memory.md

## Your role

- Pipeline: `pipeline.md` in this topic folder, one table or list per stage:
  `target` -> `researched` -> `contacted` -> `replied` -> `call` -> `proposal` -> `won` / `lost`.
- One file per prospect: `prospects/<company>.md` (lowercase with dashes), same slug as `clients`.
- Research with public sources only (the `web-scraping` skill for websites, news, job posts), and
  write down where each fact comes from.
- Write personalized messages as drafts only. Nothing is sent by Claude; each message goes out only
  after the user's explicit yes, by the user or with their confirmation.
- Won prospects move to `../clients/<company>.md` (status `active`), with the history copied over.

## First session

- If `memory.md` still has empty fields, ask its questions one short batch at a time (2-3 questions),
  write the answers into `memory.md`, then propose 2-3 first actions, e.g. write the ideal client
  profile, build a first list of 10 targets, draft one message template to adapt.

## Playbook

- Ideal client profile (in `memory.md`): sector, size, location, budget signals, triggers (new
  funding, hiring, a rebrand, a slow website), who decides. Every target is checked against it.
- Prospect file: `# Company`, `- Site / sector / size / location`, `## Why them` (the trigger),
  `## People` (name, role, public profile link), `## Findings` (dated, with sources),
  `## Angle` (the one problem you can solve), `## Touches` (dated), `Next step:`.
- Research in 10 minutes: their site (services, clients, tone), recent news or posts, job offers,
  one concrete weakness or opportunity related to the user's service. No guessing about people.
- Message: 4-6 lines, about them not you: specific observation, why it matters, one relevant proof
  (case or result), one small ask (a 15-minute call, a question). No attachments in a first message.
- Follow-up sequence: up to 2 follow-ups, 4-7 days apart, each adding something new; then stop and
  mark `lost (no reply)` with a date to retry in 6 months.
- Volume: agree on a weekly target in `memory.md` (e.g. 10 researched, 5 contacted) and report
  against it when asked.
- Respect privacy and anti-spam rules where the user works: business contacts only, an easy way to
  opt out, no bought lists. Note the local rules in `memory.md`.
- Track the results: reply rate per angle and channel, to keep what works.

## Connect

- `web-scraping` (installed) reads public pages. Sites that need a login or paid data services
  (company databases, enrichment tools): store the key in Settings -> Keys, exposed to sessions as
  an environment variable. Never ask the user to paste a secret in the chat.
- Do not automate actions on social networks; prepare drafts the user posts or sends.

## Automations

- No job is created by this pack. On request (`maxxing-cron` skill): a Monday "pipeline review"
  (stage counts, follow-ups due, stale prospects), or a weekly batch of new targets to research.
