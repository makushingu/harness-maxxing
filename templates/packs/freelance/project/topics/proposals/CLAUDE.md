# Topic proposals

Quotes, proposals and invoices as clean PDFs: "quote for Example Ltd: website redesign, 6 days",
"invoice the March work for Example Ltd", "which invoices are unpaid?".

@memory.md

## Your role

- Layout in this topic folder: `quotes/Q-YYYY-NNN-<client>.md` + `.html` + `.pdf`,
  `invoices/YYYY-NNN-<client>.html` + `.pdf`, `proposals/<client>-<project>.md`, `invoices/index.md`.
- Seller details, rates, currency, tax and payment terms come from the project `memory.md`; client
  details from `../clients/<client>.md`. Ask for anything missing, never invent it.
- Build each document as HTML, then the PDF with the `pdf-document` skill
  (`maxxing pdf in.html out.pdf`), and show the PDF path. The user reviews before sending.
- Never edit an issued invoice: corrections are a credit note plus a new invoice.

## First session

- If `memory.md` still has empty fields, ask its questions one short batch at a time (2-3 questions),
  write the answers into `memory.md`, then propose 2-3 first actions, e.g. make a template quote,
  import the list of open invoices into `invoices/index.md`, enable the "Unpaid invoices" job.

## Playbook

- Numbering: sequential with no gaps, per the format in `memory.md` (default `YYYY-NNN`, restart
  each year if allowed by local rules). The last number used is kept in `memory.md`; update it.
- Invoice content: seller and client legal details, number, issue date, due date, line items
  (description, quantity, unit price), subtotal, tax rate and amount (or the exemption mention),
  total, payment terms, late fees mention, bank details. Fill in country rules from `memory.md`.
- `invoices/index.md`: one line per invoice: number - client - amount - issued - due - status
  (draft / sent / paid YYYY-MM-DD / late). Update it on every change.
- Quotes: scope in plain words, deliverables, what is not included, timeline, price, validity
  (e.g. 30 days), deposit if any, acceptance line. Offer 2-3 options when the budget is unclear.
- Proposals: client problem in their words, approach, steps, timeline, price, why you, next step.
  Reuse facts from the client file; keep it to 1-2 pages.
- Pricing: start from the rates in `memory.md`; flag scope creep and anything below the floor rate.
- Accepted quote: note it in the client file and propose the invoice schedule (deposit, milestones).
- Unpaid reminders: draft a polite note at due date + 3 days, a firmer one at + 15, a formal one at
  + 30 per the late payment terms. Drafts only; each email is sent only after the user's yes.
- Paid: mark the date in the index; the `admin` topic reads `invoices/index.md` for its exports.

## Connect

- Nothing is required: `pdf-document` is installed with the product.
- Payment or invoicing service (e.g. Stripe): an API key in Settings -> Keys (exposed to sessions as
  an environment variable) lets Claude check paid status. Never ask the user to paste a secret here.

## Automations

- "Unpaid invoices" (Monday 09:00, this topic): lists late and soon-due invoices and the total
  outstanding, drafts and sends nothing. Created disabled, enable it on the Crons page or ask here.
