---
section: Using Harness Maxxing
---
# Webhooks

**Settings -> Automate -> Webhooks** gives your server addresses (URLs) that other services call: Stripe after a
sale, GitHub after a push, a form on Tally or Typeform, n8n, Make, Zapier, IFTTT, UptimeRobot, or a Shortcut on your
phone. Each webhook does **one thing** when it is called, by itself, at once:

| Action | For example |
|---|---|
| **Run a command** | update a site after a push, restart a service when a monitor says it is down, turn a form into a task |
| **Call a URL** | relay the request to n8n and give its answer back, post to Discord or Slack |
| **Store the data** | keep every sale in a table, export it as CSV, show it in a dashboard widget |
| **Post a notification** | a line in your [notifications](feed) (and on Telegram, by its rule) |

**Without AI.** A webhook never starts Claude: it costs nothing and does the same thing every time. When the work
needs judgement (read an order, decide, write an answer), use an [agent](agents): agents have their own webhook
trigger. Something that must happen at set times is a [cron job](crons); something that must happen when something
happens *inside* Harness (a notification, an agent or a cron job that ends) is an [event](events).

## Make one

**New webhook** at the top of the page opens a short form, as for a cron job:

- **Name**, and the sentence shown in the list (optional);
- **Who calls**: Stripe, Shopify, GitHub, another service (JSON or a form: Zapier, n8n, Make, Tally...) or your
  phone (an iPhone Shortcut, Tasker, an NFC tag);
- the **signing secret** (or, for the phone, an access key). Stripe gives it only once the URL is added there:
  leave it empty and add it after, from the webhook's **⋯** menu;
- **Then**: run a script, call a URL, keep the data in a table, or post a notification;
- **Send the result back to the caller** (another service or the phone, with a script or a URL): the caller waits up
  to 30 seconds and gets the output;
- the **Telegram report**: never, on failure, always.

**Create** shows the URL and where to paste it in the service. **Edit** on an open webhook opens the same form; what
the form does not show (filters, headers, stored columns, a reply template) is kept as it is.

For those options, or to have the script written for you, ask Harness in any session: it creates the webhook, tests
it and tells you where to paste the URL. For example:

- *"When I push to main on GitHub, update the blog on this server."*
- *"Keep every Stripe sale with its amount and e-mail, and show this month's sales on my dashboard."*
- *"An iPhone Shortcut that sends a photo to the server and gives me back a link I can share."*
- *"Each Tally answer of my contact form becomes a task."*
- *"When UptimeRobot says the shop is down, restart it."*
- *"Pass the calls of this URL to my n8n workflow and send back what n8n answers."*

Each webhook has a sentence that says what it does ("When GitHub gets a push on main, update the blog");
**Fix with Harness** appears on a webhook whose last call failed and opens a session about it.

## What you see on the page

Each row: the service's icon, the name, its sentence, its state (OK, Failed, Waiting, Off), the last call and a
switch to turn it off and on. Open a row to see:

- **The URL** and **Copy**, to paste in the service;
- **The last calls** (the last 50 are kept): time, a summary (*Sale: 49.00 EUR*, *push on main*), the result, how
  long it took; open one to read what was received and what the command printed; **Replay** runs it again with the
  same request (after you fixed the script, for example). A call that a filter left out shows as *Ignored*;
- **The data** of a webhook that stores it: the last rows, a 7-day count, **Download CSV**;
- **Send a test**: a realistic example of what the service sends (a Stripe sale, a GitHub push...), so you see the
  webhook work before the service calls it. A test really runs the action: a test of a stored webhook adds a sample
  row, a test of a webhook that calls a URL calls it;
- the **⋯** menu: **New URL** (the old one stops working at once; paste the new one in the service), **Secret**,
  **Delete** (its calls and data too).

The same list also shows the **notification webhooks** (*Posts each event to the notifications feed*: Stripe,
Shopify, GitHub, JSON) and the webhooks of **agents** (badge *Agent*, *Starts the agent ...*, **Manage in the
agent**). Open one: its URL, where to paste it in the service, **Send a test**, **New URL**, **Secret**,
**Delete** (an agent's webhook is removed from the agent). Their events are in the notifications feed.

## The URL and the secrets

- Services on the Internet can call your server only when it has a **domain with HTTPS** (domain mode, see
  [Installation](installation)). With Tailscale only, they cannot reach it; a phone on your tailnet can.
- **The URL is the key.** Anyone who knows it can call the webhook: paste it only in the service, never in a public
  place. If it leaks, **New URL**.
- **Signing secret.** Stripe, Shopify and GitHub sign what they send: their webhooks **refuse every call until you
  give the secret** (Harness asks for it; with Stripe you get it once the URL is added there). Other services: a
  webhook with a secret accepts only requests signed with the header `X-Signature: sha256=<hex HMAC-SHA256 of the
  body>`. Secrets are kept with your server's keys, never shown on the page.
- **Keys of other services** used when calling a URL (a token for ntfy, an API key) come from Settings -> Keys;
  Harness never writes them in the webhook.

## Your phone: send something, get an answer

A **phone** webhook takes GET and POST, files (photos, up to 20 MB by default) and form fields, and checks a key you
choose, sent as the header `Authorization: Bearer <key>`. With **wait for the result**, the phone gets the answer of
the command (a link, a text, a picture) instead of a plain "OK". On an iPhone, in the Shortcuts app:

1. Add **Receive images from the Share Sheet** (or **Select Photos**).
2. Add **Get Contents of URL**: the webhook's URL, Method **POST**, a header `Authorization` = `Bearer <your key>`,
   Request Body **Form** with a field of type **File** named `file` = the Shortcut input.
3. Add **Copy to Clipboard** (or **Show Result**): the answer of the server.

Share a photo to the Shortcut: the link comes back in a second. On Android, Tasker's **HTTP Request** does the same; an
NFC tag can start the Shortcut or the task. Harness gives you the exact steps for your webhook.

## Good to know

- **Limits**: a body of 1 MB by default (up to 50 MB per webhook, 20 MB for a phone), 20 files, 120 calls a minute per
  webhook (then `429`). Calls run one at a time by default; when 50 are already waiting, the service gets `503`
  with *Retry-After* and sends it again later. A caller that waits for the result waits 30 seconds at most (then
  `504`; the work goes on), and 4 callers can wait at once.
- **Nothing is lost**: a call is written down before it runs; if the server restarts, it is resumed. A delivery that a
  signing service sends twice runs once.
- **Failures** show in your notifications (source *Webhooks*) with a link to the webhook, and on Telegram (as for
  cron jobs: only failures by default).
- **Safety**: what a service sends is data, never orders. The command gets the request as files, never pasted in its
  command line, so a crafted request cannot run anything. The command runs with the rights of your server: Harness
  keeps it to what you asked for. **Agents cannot create or change webhooks.**
- From a terminal: `maxxing webhooks` (see [Command line](cli-reference#webhooks-and-events)).
