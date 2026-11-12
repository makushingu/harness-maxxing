---
section: Using Harness Maxxing
---
# Enterprises

An **enterprise** puts several of your [agents](agents) in one **org chart**, above your projects. The boxes of the
chart are **positions** (a head of marketing, a writer, customer care); each position has a **lead** it reports to, and
at most one agent sitting in it. Work goes **down** the chart (a lead hands a task to a report), results and blockers
go **up** (a hand-in, an escalation), and you get one daily digest instead of one message per agent.

One agent, or a [group](agent-groups), is enough for most work. An enterprise helps when you have **many agents over
several projects** and you have become their dispatcher: you want one place that shows who does what and what it
costs, decisions taken at the right level, and only what really needs you.

- **Marketing agency**: a director, a content lead with a writer, a social media manager.
- **Online shop**: a shop manager, order handling, customer care, a front desk that answers customers.
- **Content studio**, **research and watch**: ready-made charts, below.

Nothing existing changes. An agent keeps its role, its limits, its sandbox and its keys; the enterprise **never grants
anything**, it only narrows (a shared budget, key and domain lists), routes (who hears about what) and keeps a record.
An agent outside any enterprise works exactly as before.

## Switch it on

**Settings -> Features -> Enterprises**. It needs **Agents** to be on, and it is off by default. While it is off, no
enterprise code runs: no note in agents' turns, no ceiling, no routing (your files stay, delegated tasks stay plain
tasks). Switching Agents off pauses everything the same way: deliveries wait, nothing is lost.

## Create an enterprise

On the **Enterprises** page, **New enterprise**:

1. Give it a **name** (and an emoji). Its folder is `enterprises/<name>` in your workspace.
2. Tick the **projects** it covers. A project belongs to **at most one** enterprise.
3. Optionally **start from a template**: *Marketing agency*, *E-commerce*, *Content studio* or *Research and watch*.
   A template is a chart of **vacant** positions with job descriptions, departments and sensible settings; you change
   whatever you like afterwards.

**With Claude**: **Build me a company** (or ask in any session: "build me a company of agents for acme"). Claude asks
five short questions (what the company does, which projects, goals for the next months, a budget in USD a day, how
autonomous it may be), proposes a chart as a short tree and **waits for your OK** and your edits. Only then does it
create the enterprise and its positions, all vacant. It never creates an agent without your explicit yes.

Limits: 20 enterprises, 200 positions each, 6 levels deep (4 by default, the setting **Levels in the chart**) and 12
reports per lead (8 by default).

## The org chart

The **Org chart** tab is the home of an enterprise: a tree of cards, one per position, with the occupant's face, the
title, a state and the cost of the day. States: **Working**, **Waiting for you**, **To read**, **Failed**, **Off**,
**Ready**, **Vacant** and **Blocked** (a task stopped, or a daily budget reached).

- **Open a position**: click its card. Its occupant's conversation opens on the right (the same conversation as on its
  agent page); a second tab shows its job description, **Inbox & tasks** and what it asked you.
- **Add position**: a box exists on its own; an agent can be seated now or later. Choose its title, its lead
  (**Reports to**, or **The top of the chart**), its department and its **job description**.
- **Vacant** positions show **Hire**: it creates a **new agent** in a topic of a linked project (you choose the topic)
  and seats it. The agent sets itself up in its conversation from the job description, like any new agent. Or
  **Seat an agent** that already exists in a linked project. An agent holds at most one position.
- **Vacate** empties a position without touching the agent. Deleting an agent vacates its position; restoring it from
  the Trash does not re-seat it by itself.
- **Change lead**, or **drag** a card onto another one (computer). The chart refuses a cycle, too many levels or too
  many reports under one lead. If the chart changed in the meantime it reloads and you try again.
- **Remove position**: its reports move to its lead (or where you choose); its agent is not touched.
- **Top**: in the settings you choose who stands at the top, **You** or one position (a Director) that reports to you.

The **Org** view of the **Office** (the view menu of the Agents page) draws the desks grouped by enterprise and
department; agents outside any enterprise are under *Not in an enterprise*.

## What an occupant knows

At every turn, an occupant reads, from general to specific:

1. the **mission** of the enterprise (its `CLAUDE.md`, edited in the **Profile** tab),
2. the **notes of its department**,
3. its own **job description**,

then its own role and memory as always. These three are added to the turn by the server and cut at **3,000
characters in total** (the editor shows the count): keep them short. Changing the mission once changes it for every
occupant at its next turn. Nothing is written into the agent's folder: unlinking leaves no trace in the agent.

The **company profile** (products and prices, hours, terms, contact, FAQ) is **not** given to every turn. Agents read
it **on demand** (`maxxing enterprise profile`), so a long catalogue costs nothing to an agent that never needs it. It
is what customers may hear: put nothing private in it, every occupant can read it, and an agent must never quote a
price or a term that is not in it.

## Delegation, hand-ins and escalation

| What | How |
|---|---|
| **Delegate** | A lead gives a task to one of its **direct reports** (never further down, never across the chart). It becomes a normal entry of the [Tasks](tasks) file, labelled with the enterprise, and the report receives it. |
| **Hand in** | The report says it is done, with a summary: it goes to the **requester's** inbox, never to you. The lead accepts it or sends it back with notes. |
| **Block** | A report that cannot go on says why; the task shows **Blocked** with the reason. |
| **Escalate** | A position that needs a decision asks **one level up**, saying what it tried, the options and its recommendation. |

Deliveries are not one run per message: they wait in the position's **inbox**, and its occupant runs **once** for
everything waiting, after its usual grouping delay. A delivery that cannot start (agent off, budget or runs per hour
reached, vacant position) **waits** instead of being lost. These runs count in the agent's budget and limits.

**Escalation timeout** (setting, 4 hours by default, 1 to 72): a question nobody answers climbs one level, up to you,
where it becomes a notification you can answer. A vacant, switched-off or out-of-budget lead is skipped at once. An
escalation always reaches you, even from a silent agent. The hand-overs on one task are limited (6 by default); past
that, it goes to you.

## Requests and approvals

An occupant can **ask for something** that the chart must decide: spending, a purchase, a change to a job
description, a worker, a budget raise, a profile edit... Each category is decided by the **requester's lead** or by
**you**, depending on the **autonomy** profile of the enterprise (setting):

| Request | Careful | Balanced | Autonomous |
|---|---|---|---|
| Assign to a direct report, read the profile, write in one's own department | free | free | free |
| Deliver into another department's folder, assign across departments | you | lead | lead |
| Edit a report's job description | you | lead | lead |
| Create a worker from an approved template | you | lead | lead |
| Edit the company profile (not prices or terms) | you | lead | lead |
| Declared spending up to the department's threshold | you | lead | lead |
| Raise a report's daily budget (inside the envelope) | you | you | lead |
| Re-seat an agent on a vacant position of one's team | you | you | lead |
| Edit prices or terms, put the front desk live | you | you | you |
| Hire or remove a permanent agent; change keys, domains, sandbox, folders | you | you | you |
| Spending above the threshold, any new recurring cost | you | you | you |
| Publish publicly, write to a customer, anything irreversible | you | you | you |

Some rows are enforced by the server; the spending rows are **declared** by the agent and the last row relies on the
agent's role and its usual approvals.

A request that reaches you is an **Allow / Deny** card in the **Overview** ("Waiting for you"), in the notifications
and on Telegram. A lead decides in its next run. If nobody answers in time, the request climbs one level, like an
escalation. Everything is written in the **Decisions** tab (the decision log, filterable by kind and position).

Rules no setting can change:

1. A request born in a run **started from outside** (a webhook, a mail, a feed event, the front desk, a forwarded
   Telegram message) is **always decided by you**, and so is everything further down that chain.
2. The approvals of tool calls and the requests of safety settings (sandbox, keys, domains, folders, budget) stay
   yours: a lead **never** answers them, and an agent never changes itself.
3. Nobody decides their own request, and a lead only decides for its own team.
4. **Allowing a request grants nothing.** If it needs a key, a domain or a folder, you still get the usual card of
   the agent.

**Delegated approval**: you can let a lead decide a category up to a ceiling until a date ("until Friday, the head of
marketing decides spending up to 50 USD"), 30 days at most, revocable. It never covers the rows where you always
decide. See [the command line](#from-the-command-line).

## Envelopes: budget, keys and domains

The **envelope** of the enterprise (settings) and of each **department** caps what its agents may use together:

- **Budget per day (USD)**: the sum of what its agents spend in a day, digests included. A position has no budget of
  its own: it is its occupant's daily budget.
- **Keys** and **Domains**: a list of key names / sites. Empty means no narrowing.

An envelope **only narrows**: it never gives an agent anything it did not have. A run is limited to the smallest of
what is left for the agent, its department and the enterprise. When the budget of a department or of the enterprise is
**reached**, new runs do not start (the delivery waits, the task shows *Blocked* with the reason) and you get **one**
notification for that envelope that day, not one per agent. While runs share the last of an envelope, one may find it
fully held: it waits and starts when room is back. A key or a domain that an agent holds beyond a narrowed list is
flagged in the chart; the server never edits an agent itself, you remove it. Widening an agent beyond its envelope is
refused.

**Departments** (settings): a branch of the chart with its own envelope and notes, and overrides of some settings
(shown as *Same as the enterprise* when not overridden).

## Who may talk to whom

The **Communication** setting decides how agents of the enterprise may write to each other:

- **Strict**: an agent writes only to its lead and its reports.
- **Leads** (default): leads can also write to each other.
- **Open**: also the **pairs you list** (one per line, two position ids).

A refused message says who to go through. Agents outside the enterprise, and [groups](agent-groups), are not affected.

## Trust along the chain

Normally a message from another agent is **outside text**: the receiving run asks before every risky action (unless
the agent trusts outside events). Inside a chart this would send you a card for almost every delegated step.
**Trust along the chain** (setting, **off by default**) changes that: a task whose **whole chain is clean** (it
started from your words or a schedule, and no run in the chain was started from outside) reaches the receiver as an
order from its lead. One outside-started run **anywhere** in the chain keeps everything after it outside text, and the
mark is set by the server, never by an agent. Hand-ins going up are always information for the lead, never orders.
Leave it off if you do not need it: it relaxes a safety default.

## The digest, reports and the Overview

- **Daily digest**: once a day (setting: hour, 8 by default), one short message on what happened, per department: done,
  next, blocked. The server collects the facts without Claude; **one** short call writes the text, charged to the
  enterprise. Nothing new means no call and no message; budget reached means the raw list is sent. Options: **One per
  lead** (each lead also gets its team's digest) and **Titles only** (one line per item).
- **Weekly report** (Monday morning) and **Monthly report** (the 1st): objectives, blocked work, cost per department.
  Switch them on in the settings.
- **Reports** tab: all of them, newest first, **Build now** to make one at once.
- **Overview** tab: what waits for you (requests to allow or deny, escalations to answer), the **cost of the day** per
  department against its ceiling, tasks open, late and blocked, objectives and the latest digest.

With [Telegram](telegram) linked, each enterprise gets **its own thread** (named after it, with a building emoji): the
digest, the cards that need you, and the answers you give there. Without topics, they arrive in the main chat with the
enterprise's emoji in front.

## Workers

A position may need short-lived helpers ("resize these 12 visuals"). The **Workers** setting:

- **Discreet** (default): helpers live inside the agent's turn (Claude Code sub-agents). Nothing to manage.
- **Visible**: **temporary agents** you can see in the chart. You approve once a **worker template** per position
  (role, model, daily budget). A worker is always protected (sandbox, no key, no domain, no trigger), at most 5 live at
  a time, and goes to the Trash when its task is done or after 24 hours. You can stop one at any time.
- **Off**: no helpers.

## Front desk

The **front desk** is a position that answers people **outside** the company on a **public chat link**.

- It is always labelled **"AI assistant of <name>"**; you can add a label of your own, never remove the AI mention.
- It has no key, no domain, no folder and no tool but two: read the profile, and **route** a request to the right
  department. It routes, it does not solve: a refund request becomes a task for customer care, **marked as coming from
  outside**, so everything it triggers asks you first.
- **Going live is your decision**, and **needs every occupant of the chart to be protected** (sandboxed, so they cannot
  read what they should not): the chart lists those who are not. The public link is an entry point without a session,
  so it ships **off**, with its own **rate limit** per visitor (20 messages an hour by default), a size limit per
  message (1,000 characters) and the agent's own limits. Regenerate the link to cancel the old one.
- **Retention**: conversations are kept 30 days by default (1 to 365) and you can delete any of them. They are never
  exported. Other positions receive summaries and themes only; **full conversations** can be given to chosen positions
  (customer care).

**Weekly insights**: once a week, one short call over the desk's conversations produces the questions most asked,
rising topics, pain points and what the profile could not answer. Unanswered questions come as **suggested FAQ
entries** in the Profile tab (accept with an answer, or dismiss), and the relevant leads get a task, marked as coming
from outside.

## Objectives

An objective is a sentence with an optional target and unit, a current value and an **owner position**; it can sit
under a parent objective (enterprise, department, position). Only its owner position updates the value; the weekly
report shows progress. Nothing is measured automatically.

## Export and import

**Export** downloads the enterprise as a zip: chart, job descriptions, departments, settings, mission, profile and
shared files. It holds **no** grant, **no** agent path, **no** key or domain list and no front desk conversation.
**Import** creates a **new** enterprise from a zip (a free name is chosen if needed), with **vacant** positions and no
linked project: link your projects, then hire or seat the agents. Files that could not be kept are listed. Agent
definitions found in the zip are kept in `files/imported-agents/` to hire from.

## Unlink or delete

- **Unlink a project**: refused while agents of that project hold positions, unless you choose **Unlink and vacate**
  (the positions become vacant; the agents, their runs and their sessions are not touched). Open tasks stay in Tasks as
  plain tasks.
- **Delete enterprise** (settings, danger zone): the folder goes to the **Trash** with its state. Agents, topics,
  sessions and files are untouched.
- A chart file that cannot be read (hand edit) shows **This enterprise has a problem**; nothing is saved over it until
  you fix the JSON, and agents keep running as plain agents.

## From the command line

`maxxing enterprise ...` does everything the page does (see the [CLI reference](cli-reference)). The structure
commands are **yours**: an agent never changes the chart, its settings or its grants.

| Who | Commands |
|---|---|
| You | `create`, `link`, `unlink`, `position add\|move\|seat\|vacate\|remove`, `settings`, `grant`, `report`, `decisions`, `export`, `import` |
| An agent, as its own position | `show`, `profile`, `assign`, `done`, `block`, `escalate`, `answer`, `request`, `decide`, `objective set`, `worker`, and `route` (front desk) |

You can run the agent commands too, with `--as POSITION`, to test a flow. The `maxxing-enterprises` skill lets Claude
set a chart up from a conversation.

## Safety in short

- The enterprise only **narrows and routes**; it grants nothing. Keys, domains, folders and sandbox stay yours.
- The server enforces ceilings, cycles, depth, hand-over limits and who may run which command; a prompt never does.
- Tool approvals and safety requests are always yours. Anything born from outside text is decided by you.
- Agents delegate only to their direct reports and never edit the chart or each other.
- The front desk is off by default, labelled as AI, protected, rate limited, and its tasks are marked as outside.
- Switch **Enterprises** off in Settings -> Features at any time: no enterprise code runs, your files stay.
