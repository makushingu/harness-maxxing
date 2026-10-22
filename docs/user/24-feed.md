---
section: Using Harness Maxxing
---
# Notifications

The notifications feed collects what happens around you - cron jobs, sales, orders, deployments,
important e-mails, any script's result - in one place instead of chat messages.

## Where you see it

- **Dashboard**: a panel next to the widgets (wide screens). The bell in the header shows the unread
  count and hides / shows the panel; on a phone it opens the list.
- **See all** (page `/feed`): the last 30 days, filters per source, *Unread only*, *Mark all as read*.
- **Telegram** (optional): the bot posts in the thread **Notifications** by itself - no Claude, instant.
  Under each message, **Ask Harness** opens a session about it, and **Open** follows its link.

Click an event to mark it read and open its link (the cron job's history, the Stripe payment, the
GitHub run…). Its **…** menu marks it read or deletes it. Repeated routine events fold into one row
(*Cron jobs succeeded ×12*) until you read it.

## What arrives by itself

| Source | Events |
|---|---|
| **Cron jobs** | every run: failures one by one (with the error), successes folded into one row |
| **Harness Maxxing** | an update is available, an update needs attention (customizations, roll-back) |
| **Sign-ins** | sign-ins (folded), several wrong passwords |

## Connect a service (webhooks)

Settings -> **Notifications** -> **Add a webhook**, choose the service, give it a name, paste its
signing secret if you have it, **Create**: copy the URL into the service. The dialog says where.

| Service | What you get |
|---|---|
| **Stripe** | sales (*Sale: 49.00 EUR*), payments, refunds, failed payments, disputes, subscriptions |
| **Shopify** | new / paid / cancelled orders, refunds, stock updates (out of stock as a warning) |
| **GitHub** | pushes, pull requests, issues, failed / passed workflows, releases |
| **Generic JSON** | anything: POST `{"title", "body", "level", "url", "id"}` |

- Webhooks need the server **reachable from the Internet with HTTPS** (domain mode). With Tailscale only,
  use a script (below).
- Set the **signing secret** the service gives you. Stripe, Shopify and GitHub sources **refuse every event
  until the secret is set** (a warning appears in the feed); with Stripe you get the secret only after adding
  the URL there, so create the source, add the URL in Stripe, then paste the secret. A *Generic JSON* source
  works without a secret, but then anyone who learns the URL could send fake events. The source's **…** menu: *Send a test event*, *Set the signing secret*, *New URL* (the old one
  stops working), *Delete*.
- A delivery sent twice (services retry) appears once, even when both copies arrive at the same moment. For Shopify
  and GitHub, a signed event replayed by someone who captured it also appears only once. Up to 120 deliveries per minute per source.

## From any script

```bash
maxxing feed post "Invoice from ACME: 39 EUR due Friday" --source mail --level warning \
  --body "From billing@acme.example" --dedupe "msg-1234"
```

`--level` info | success | warning | error · `--source` short name · `--url` link · `--dedupe KEY`
(the same key twice is ignored) · `--group KEY` (fold repeats) · `--quiet` (never to Telegram).
`maxxing feed list`, `maxxing feed read-all`. Run the script with a cron job.

Just ask Claude: *"notify me when an e-mail from my accountant arrives"*, *"tell me when the site is
down"*, *"connect my Shopify orders"* - it writes the script and the job, or sets up the webhook.

## What goes to Telegram

Settings -> Notifications -> **Sources**, per source:

| Rule | Effect |
|---|---|
| **Auto (by level)** (default) | errors ring, warnings are silent, info / success stay in the dashboard |
| **Not in Telegram** | dashboard only |
| **Telegram, silent** | posted without a sound |
| **Telegram, rings** | posted with a sound (e.g. your sales) |

Cron jobs, updates and sign-ins already report in their own threads (*Crons*, *Alerts*): they are not
repeated in *Notifications* unless you choose so. The switch at the top turns the Telegram thread off.

## Good to know

- Events are kept 30 days. They live on your server (`/var/lib/claude-maxxing/feed.db`).
- A webhook's content comes from outside: *Ask Harness* treats it as data, never as instructions, and opens the
  session in plan mode (Claude explains, it changes nothing until you approve a plan).
