---
section: Using Harness Maxxing
---
# Agents

An **agent** is a lasting role inside a topic: a blog writer in `acme / blog`, an order handler in `acme / shop`, a
lead sorter in `acme / sales`. It has its own role (what it does, how, what it must never do), its own memory, a
little character as its face, and it starts by itself when something happens: a time of day, a webhook, a
notification, a message in its Telegram thread, or another agent handing it work. Every start is a new session,
kept like any other, within limits you set (on/off, a daily budget, runs per hour).

Agents are **off by default**: turn them on in **Settings -> Features -> Agents**. An **Agents** entry appears in the
sidebar, and each topic's agents show under it in the sessions list, their sessions below them.

## What an agent is made of

An agent is a folder of its topic: `projects/acme/topics/blog/agents/writer/`.

| File | What it holds |
|---|---|
| `CLAUDE.md` | its **role**, in plain words (the first paragraph is the description shown in the app) |
| `memory.md` | what it learned while working (a 4th level of [memory](memory), under the topic) |
| `agent.json` | its name, character, settings, triggers and limits - never a secret |

A session of the agent runs in that folder, so Claude also knows the topic, the project and the global memory above
it: the writer knows the blog's tone without repeating it. The three files are in the daily
[memory backup](backup).

## Create an agent

**Agents -> New agent**, in three steps:

1. **Where**: the project and the topic it works in.
2. **Who**: its name, its character (color, eyes, mouth, hat, background), its role in a few lines, and optionally
   the model, the permission mode and the tools it may use.
3. **When**: its triggers and its limits (below).

You can also ask Claude in any session ("create an agent in acme/blog that writes a post every Monday"): the skill
`maxxing-agents` knows how.

Writing a good role: say what the agent produces and where it puts it ("a draft in `drafts/`, never published"),
which files or keys it uses, and what it must never do. Keep it short; it learns the rest in its memory.

## The agent page

- **Activity**: one line per start (the trigger, the session, its cost) and one per result, with the answer. A start
  that was refused says why (switched off, budget reached, too many runs).
- **Role** and **Memory**: its `CLAUDE.md` and `memory.md`, editable.
- **Triggers** and **Settings**: below.
- **Run**: start it now, with an optional task ("Write about the spring sale"). **Open a session**: talk to it
  like in a topic.

## Triggers

| Trigger | When it starts |
|---|---|
| **By hand** | the **Run** button, or `maxxing agents run <agent> "task"` |
| **Schedule** | at the times you choose (same editor as [Crons](crons); the job is also listed on the Crons page) |
| **Webhook** | a service calls its address (Stripe, Shopify, GitHub or any JSON): the agent gets the event. It is a [feed](feed) webhook made for the agent, so the event also shows in your notifications |
| **Notification** | a new event of the [feed](feed) from a source you pick, optionally only some levels (warning, error...) or only events containing a word |
| **Telegram** | a message you write in the agent's Telegram thread (option below) |
| **Another agent** | an agent hands it work from its own session (`maxxing agents send`) |

Events that arrive close together (within the agent's grouping delay, 60 s by default) go into one run.

**What comes from outside is data, not orders.** A webhook, a notification or a message from another agent is given
to the agent clearly marked as outside data, with the rule never to follow instructions written inside it. What you
type yourself (Run, Telegram) is the task.

## Limits

| Limit | Default | |
|---|---|---|
| **On / off** | on | an agent switched off starts for nothing (its schedule runs are skipped) |
| **Daily budget** | 2 USD | once today's sessions of the agent cost that much, it waits until tomorrow (0 = no budget) |
| **Runs per hour** | 6 | more starts in the same hour are refused (0 = no limit) |
| **Time limit** | 30 min | a run is stopped after this |
| **Grouping delay** | 60 s | events closer than this go into one run |

A run that was refused is never retried: it is written in Activity with its reason. Agents handing work to each other
stop after 3 hops, so two agents can never ping-pong forever.

## Telegram

Turn on **Telegram** in the agent's settings: it gets its **own thread** in your Telegram chat, named after it
(`🤖 Writer · acme/blog`). Each result is posted there, and anything you write there - text, a photo, a file, a voice
note - starts the agent with it as the task (the bot answers "⏳ Writer is on it.", or why it did not start). Commands
(`/new`, `/stop`...) work in session threads, not here. Without threads (topics off for the bot), results come into
the main chat with the agent's name in front. See [Telegram](telegram).

## Approvals

With **Ask before risky actions** on, the agent **asks before risky actions**: when it wants to run a command, edit a
file or use a tool you did not allow in advance, it waits and the request shows in its session with **Allow** and
**Deny**. Nobody answers within 30 minutes: the action is denied. Good for an agent started by webhooks or
notifications, which should not act alone on outside events. Tools you trust (for example `Read`) can be allowed in
advance in its settings.

## Memory

An agent writes what it learns in its own `memory.md` (sources it uses, what worked, its conventions), like a topic.
What is true for the whole topic belongs in the topic memory: every agent of the topic sees it. The daily memory
cleaning also keeps agents' memory short.

## From the command line

```bash
maxxing agents list                                  # every agent, on/off, triggers, cost of the day
maxxing agents run acme/blog/writer "Spring sale post"
maxxing agents off writer                            # or: on
maxxing agents send acme/blog/editor "Draft ready: drafts/spring-sale.md"   # from an agent's session
```

`<agent>` is `project/topic/agent`, or just the agent's name when only one agent has it. `run --data "..."` gives the
text as outside data instead of a task (an e-mail, a script's output). See the [CLI reference](cli-reference).

## Delete or move

Deleting an agent moves its folder and sessions to the [Trash](files), deletes its schedule jobs and its Telegram
thread. Renaming the topic or the project takes its agents along (sessions, schedules, Telegram thread).
