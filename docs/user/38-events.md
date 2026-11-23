---
section: Using Harness Maxxing
---
# Events

**Settings -> Automate -> Events** does one thing when something happens inside Harness, by itself and without AI:

| When | For example |
|---|---|
| **A notification arrives** (any source, or only one: *Stripe*, *Cron jobs*...; only some levels; only those containing a word) | send warnings and errors to Discord, Slack or ntfy; each new sale to a Slack channel |
| **An automatic agent run ends** (one agent, every agent of a project, or all; when it succeeds, fails, or both) | hand the agent's result to an n8n workflow, run a script that publishes what it wrote |
| **A cron job run ends** (one job or all; succeeded, failed, or both) | when the backup job fails, post to ntfy; when the export job succeeds, upload the file |

and the same actions as [webhooks](webhooks): **run a command**, **call a URL**, **store the data**, **post a
notification**. An event is a webhook that nobody outside calls: it has no URL.

Only agent runs that start **by themselves** count (a schedule, a notification, an e-mail, another agent), not your own
messages to an agent. A cron job that is retried counts once, when its last attempt ends.

**Without AI.** When the work needs judgement, an agent's own triggers do it: *Notification* and *After another agent*
(see [Agents](agents#triggers)). An event costs nothing and does the same thing every time.

## Make one

**New event** at the top of the page opens a short form, as for a cron job:

- **Name**, and the sentence shown in the list (optional);
- **When**: a notification arrives (from one source or all, optionally containing a text), an agent finishes, or a
  cron job ends (one or any, on success, failure or always);
- **Then**: post a notification, call a URL (Discord, Slack, ntfy, n8n: the event is sent as JSON), run a script, or
  keep the data in a table;
- the **Telegram report**: never, on failure, always.

**Edit** on an open event opens the same form. For levels, headers or a message made to measure, ask Harness in any
session, for example:

- *"Send my errors and warnings to my Discord channel."*
- *"When a cron job fails, push a notification to my phone with ntfy."*
- *"When the blog writer agent has finished, send its article to my n8n workflow."*
- *"Each new Stripe sale, post it in the #sales Slack channel."*

Harness creates it, sends a test and tells you what it did. For Discord or Slack, it asks you for the channel's
webhook address (Discord: channel -> Edit channel -> Integrations -> Webhooks; Slack: an *Incoming Webhook* of a Slack
app). A token for ntfy or an API key goes in Settings -> Keys: the event reads it from there.

## What you see on the page

The same list as the Webhooks page: each event's sentence (*When a cron job fails, notify ntfy*), its state, the last
time it ran, a switch. Open a row to see the last runs (50 kept) with what was received and what happened,
**Replay**, **Send a test** (a realistic notification, agent result or cron run), **Change with Harness**, **Fix with
Harness** after a failure, and the **⋯** menu (Delete).

## Good to know

- **No loops**: a notification posted by an event cannot start events again without end (3 steps at most), the
  notifications of a failed webhook or event never start one, and an event never reacts to its own notifications.
- Events are checked every few seconds; a run of the same event waits for the previous one (one at a time by default).
- A failure shows in your notifications (source *Webhooks*) and on Telegram (failures only by default).
- What an event passes on (a notification's text, an agent's answer) is data, never orders: the command gets it as
  files, never in its command line. **Agents cannot create or change events.**
- From a terminal: `maxxing webhooks` (the same commands as webhooks, see
  [Command line](cli-reference#webhooks-and-events)).
