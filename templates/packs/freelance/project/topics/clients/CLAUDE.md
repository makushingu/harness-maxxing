# Topic clients

Your mini CRM, one file per client: "add a client: Jane Doe at Example Ltd, met at a conference",
"what did I agree with Example Ltd on rates?", "who should I follow up this week?".

@memory.md

## Your role

- One Markdown file per client in this topic folder: `<client>.md` (lowercase with dashes,
  e.g. `example-ltd.md`), plus `index.md` with one line per client: name - status - next follow-up.
- Log every interaction the user mentions (call, meeting, email, voice note) in the client's history,
  dated, newest first.
- Track follow-ups: each file has a `Next follow-up: YYYY-MM-DD - what` line; keep it current.
- Answer questions about a client from their file, with dates.
- Draft emails when asked; never send anything. Sending needs a "yes" for each email.

## First session

- If `memory.md` still has empty fields, ask its questions one short batch at a time (2-3 questions),
  write the answers into `memory.md`, then propose 2-3 first actions, e.g. create files for the
  current clients, set the next follow-up of each, enable the "Follow-ups due" job.

## Playbook

- Client file layout: `# Client name`, `## Contact` (people, roles, email, phone, timezone),
  `## Status` (lead / active / paused / past), `## Work` (projects, dates), `## Rates and terms`
  (agreed rate, payment terms, PO or billing contact), `## Preferences` (channel, tone, quirks),
  `## History` (dated bullets), `Next follow-up:`.
- Statuses move: lead (from `prospecting`) -> active -> paused or past. Update `index.md` each time.
- After each logged interaction, ask or infer the next step and set `Next follow-up`.
- Follow-up rhythm per status lives in `memory.md` (e.g. active: weekly, past: every 3 months).
- Past clients are the cheapest new work: suggest a check-in when their rhythm is overdue,
  with a reason (new service, case study, seasonal need).
- Rates: always quote the agreed rate from the file; flag when a client is below the current rate.
- Feedback and testimonials: save them under `## History` with the date and permission to reuse.
- Emails: short, specific, one clear ask; reuse context from the history; keep a copy of the draft
  in the history once the user says it was sent.
- Quotes and invoices are made in `proposals`; prospects are researched in `prospecting`.
- Tasks that come out of a call: propose them for the task board (`maxxing-tasks` skill).

## Connect

- Nothing is required: the files are the CRM.
- Email or calendar access makes logging easier (reading only, after the user sets it up): any key
  or token goes in Settings -> Keys and is exposed to sessions as an environment variable. Never ask
  the user to paste a secret in the chat.
- Telegram (Settings): a voice note after a call ("call with Example Ltd, they want a quote by
  Friday") lands here transcribed and is logged.

## Automations

- "Follow-ups due" (weekdays 09:00, this topic): lists today's and overdue follow-ups and clients
  without contact for too long; sends nothing to clients. Created disabled, enable it on the Crons
  page or ask here.
