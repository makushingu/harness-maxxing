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

## Alerts: events with buttons

Some events wait for you and carry buttons:

- an agent waiting for your OK: **Allow** / **Deny** in one click (the same answer as in its thread or its run);
  when the notification can only show part of the request (a long command, the content of a file), it has **Open** and
  **Deny** only: open the request to read all of it before you allow it (also on Telegram);
- a server problem: **Seen** (the same as *Seen* in the server health card);
- an agent that needs a look (failed run, daily budget reached...): **Open**.

Once handled, or when the cause goes away (the request was answered elsewhere, the problem is fixed, the agent
runs again), the event says how it ended (*Allowed*, *Denied*, *No answer in time*, *Fixed*...) and its buttons go.
Clicking twice, or on the web and then on Telegram, gives the same answer. Reading an alert on the web (Seen, Open,
**Mark all read**) also removes its Seen button on Telegram. The **To handle** filter of the `/feed`
page (and the *to handle* count of the dashboard panel) shows only the alerts still waiting.

## What arrives by itself

| Source | Events |
|---|---|
| **Cron jobs** | every run: failures one by one (with the error), successes folded into one row |
| **Harness Maxxing** | an update is available, an update needs attention (customizations, roll-back) |
| **Sign-ins** | sign-ins (folded), several wrong passwords |
| **Agents** | an agent waits for your OK (Allow / Deny), a run failed (repeats folded), its daily budget or its runs per hour are reached, its sandbox cannot run, a trigger lost its webhook (Agents page on only) |
| **Server health** | each new problem of the health card (disk, services, Claude sign-in, backup, failed sign-ins), with *Seen*; ends as *Fixed*. On for new installs; turn it on in Settings -> Notifications -> **Server problems in the notifications** |

Agents never start on the source *Agents* (an agent would start itself again).

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
  and GitHub, a signed event replayed by someone who captured it also appears only once (even one that was ignored
  or that you deleted, for 30 days). A signed *Generic JSON* body identical to one received in the last 24 hours is
  a duplicate too: to send the same alert again within the day, put a time or an `id` in it. Up to 120 deliveries
  per minute per source.

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
An agent waiting for your OK always reaches Telegram, with its Allow / Deny buttons.

## Good to know

- Events are kept 30 days. They live on your server (`/var/lib/claude-maxxing/feed.db`).
- A webhook's content comes from outside: *Ask Harness* treats it as data, never as instructions, and opens the
  session in plan mode (Claude explains, it changes nothing until you approve a plan).
