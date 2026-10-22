# Project freelance

Your freelance business in one place: "who do I need to follow up this week?", "make a quote for
Example Ltd: 5 days of design", "what taxes are due next month?".

## Topics

- `clients`: one file per client (contact, history, rates, preferences), follow-ups, mini CRM.
- `proposals`: quotes, proposals and invoices as PDF, numbering, payment terms, unpaid reminders.
- `prospecting`: target list, research on prospects, personalized message drafts, the pipeline.
- `admin`: accounting exports, tax and declaration deadlines, expenses, subscriptions, bills received.

## Shared conventions

- Your business identity (name, legal details, services, rates, currency, payment terms) lives in
  this project's `memory.md`. Read it before any work; fill it in during the first session of any topic.
- Data is plain Markdown inside each topic folder (`topics/clients/<client>.md`,
  `topics/proposals/invoices/...`). Client slugs are lowercase with dashes (`example-ltd`) and are the
  same in every topic.
- Files sent from the phone or the web arrive in the topic's `attachments/YYYY-MM/`; file or link them.
- Keys and tokens are stored in Settings -> Keys and reach sessions as environment variables. Never
  ask the user to paste a secret in the chat, never write one into a file.
- Never send an email or message on the user's behalf: write drafts. Sending needs an explicit "yes"
  for each email in the current conversation.
- Money: always state currency, tax included or not, and dates. Never change an issued invoice.
- Follow-ups go to the task board (`maxxing-tasks` skill); alerts that matter go to the feed
  (`maxxing-feed` skill, e.g. `maxxing feed post "Invoice 2026-014 is 15 days late" --level warning`).

@memory.md
