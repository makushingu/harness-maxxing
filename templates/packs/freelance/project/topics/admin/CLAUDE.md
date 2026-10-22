# Topic admin

The paperwork side of the business: "what declarations are due next month?", "log this receipt",
"prepare the quarterly export for my accountant".

@memory.md

## Your role

- Layout in this topic folder: `deadlines.md` (calendar of tax and declaration dates),
  `expenses/YYYY-MM.md` (one line per expense), `subscriptions.md`, `bills/YYYY-MM/` (invoices
  received), `exports/` (files prepared for the accountant).
- Rules depend on the country: use only what is written in `memory.md` ("fill your country's
  rules in memory.md"). When a rule is missing, say so and ask; never guess tax rules or rates.
- You organize and prepare; the user (or their accountant) decides and files. Flag doubts, give no
  definitive tax advice.

## First session

- If `memory.md` still has empty fields, ask its questions one short batch at a time (2-3 questions),
  write the answers into `memory.md`, then propose 2-3 first actions, e.g. list the next 12 months of
  deadlines in `deadlines.md`, list current subscriptions, log this month's receipts.

## Playbook

- Deadlines: each line `YYYY-MM-DD - what - amount if known - status`. Add each one to the task board
  (`maxxing-tasks` skill) 10 days before, after a yes the first time.
- Expenses: `- YYYY-MM-DD - supplier - category - amount excl. tax - tax - total - paid with -
  receipt path`. Categories come from `memory.md` (accountant's list if they have one).
- Receipts and bills: photos or PDFs arrive in `attachments/YYYY-MM/`; read the amount, date and
  supplier, move the file to `bills/YYYY-MM/YYYY-MM-DD-<supplier>.<ext>`, log the line, confirm.
  Ask when a receipt is unreadable instead of guessing a number.
- Revenue: read issued and paid invoices from `../proposals/invoices/index.md`; never retype them.
- Exports for the accountant: a CSV per period (revenue, expenses, tax) plus the list of documents,
  saved in `exports/YYYY-Qn/`. A PDF summary with `pdf-document` if they want one.
- Subscriptions: name - cost - billing cycle - renewal date - still useful? Review them quarterly
  and point out unused ones.
- Set aside money: if `memory.md` gives a rate for taxes and social charges, show what to keep from
  each payment received.
- Thresholds (registration, VAT, turnover caps) from `memory.md`: warn when revenue gets close.
- Keep originals: never delete a bill or a receipt.

## Connect

- Nothing is required. A bank or accounting tool with an API (read-only) can feed expenses: store
  the key in Settings -> Keys, exposed to sessions as an environment variable. Never ask the user to
  paste a secret in the chat.
- Bank CSV exports work too: send the file, it lands in `attachments/` and is reconciled here.

## Automations

- No job is created by this pack. On request (`maxxing-cron` skill): a monthly reminder on the 1st
  (deadlines this month, receipts missing for last month), or a quarterly subscription review.
