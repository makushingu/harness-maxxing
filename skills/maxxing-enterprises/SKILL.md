---
name: maxxing-enterprises
description: Set up and work inside a Harness Maxxing enterprise - an org chart of agents above projects (positions, leads, departments), with delegated tasks, escalations, requests the lead or the owner decides, and a company profile. Use when the user wants "a company of agents", a team with a head of marketing and a writer, to hand work down or up a chart, to ask what an agent's position is, or when an agent holds a position and must delegate, hand in work, escalate or ask for an approval.
---

# Enterprises

An enterprise is a folder `{{WORKSPACE}}/enterprises/<slug>/` (`CLAUDE.md`, `enterprise.json`, `profile.json`, `files/`) with
linked projects and a chart of **positions**. A position has a title, a lead (`reports_to`, empty = the owner), a department, a
job description and at most one occupant: an existing agent of a linked project. Settings -> Features -> Enterprises must be on
(it needs Agents). Everything below is `maxxing enterprise ...`; the Enterprises page shows the same data.

## The owner (a session): build the chart
```
maxxing enterprise create acme-group --name "Acme Group" --project acme
maxxing enterprise position add acme-group lead --title "Head of marketing" --agent acme/blog/lead --department marketing
maxxing enterprise position add acme-group writer --title "Articles" --reports-to lead --agent acme/blog/writer --job-file job.md
maxxing enterprise position move|seat|vacate|remove acme-group writer [--reports-to P] [--agent A] [--reparent-to P]
maxxing enterprise link|unlink acme-group acme-shop [--vacate]
maxxing enterprise settings acme-group autonomy=balanced digest.enabled=true      # KEY=VALUE, dotted for nested
maxxing enterprise settings acme-group --department marketing notes="Friendly tone"  # a department's notes or override
maxxing enterprise grant acme-group lead --category spending --ceiling 50 --until 2026-12-05   # 30 days at most
maxxing enterprise show acme-group [--json] ; list ; decisions acme-group [--since D] ; report acme-group --weekly [--now]
maxxing enterprise export acme-group -o acme-group.zip ; maxxing enterprise import acme-group.zip
```
Create the agents first (skill `maxxing-agents`), then seat them. Ask only what is missing (names, who leads whom). The
structure is the owner's: an agent never runs these (refused in an agent turn): it says what should change in its answer.
The enterprise `CLAUDE.md` and the company profile are edited on the page (or by writing the files).

## An agent holding a position
Its system note says which position it holds, its lead and its reports, with the enterprise `CLAUDE.md`, the department notes
and its job description (3,000 characters at most). It acts **as its own position**, never for another one. Run each command
alone on its line (no pipe, `;`, `&&`):

| To | Command |
|---|---|
| give work to a direct report | `maxxing enterprise assign writer "Three articles on the spring kit" --due 2026-12-01 [--parent T]` |
| send a task back with notes | `maxxing enterprise assign writer "Shorter intro" --task t_9f3c2a` |
| hand in a task (goes to the requester) | `maxxing enterprise done t_9f3c2a "Drafts in files/marketing/spring/"` |
| report a blocker | `maxxing enterprise block t_9f3c2a "Waiting for the product photos"` |
| ask one level up (what you tried, the options, your recommendation) | `maxxing enterprise escalate "Need a decision on the ad budget: A or B, I recommend A" [--task T]` |
| answer an escalation of a report | `maxxing enterprise answer e_41c0 "Go with A, 30 USD at most"` |
| ask for something (spending, a purchase, a job change...) | `maxxing enterprise request spending "Boost the spring post" --amount 20` |
| decide a request of your team | `maxxing enterprise decide r_88d2 allow "Within this month's plan"` |
| set an objective you own | `maxxing enterprise objective set o_12 7` |
| read the company profile (prices, hours, terms, FAQ) | `maxxing enterprise profile [--section products\|hours\|terms\|contact\|faq]` |
| see your place in the chart | `maxxing enterprise show` |

Rules that hold whatever the settings: assign only to **direct reports**; hand-ins go up to the requester, never to the owner;
nobody decides their own request; a request born from a run started from outside (a webhook, a mail, a feed event) is always
decided by the owner. Never quote a price or a term that is not in the profile: read it, or escalate. An agent without a
position gets "holds no position": ask the owner to seat it.

The owner can run the same commands with `--as POSITION` (and `--enterprise SLUG` when several exist), for instance to test a
flow: `maxxing enterprise assign writer "Test" --as lead`. Exit codes: 0 done, 1 nothing done, 2 error or refusal (stderr).

## Build me a company
When the owner asks for "a company of agents" without a chart, ask these five questions (all at once, short), then wait:
1. **Activity**: what does the company do? 2. **Projects**: which existing projects does it cover (`maxxing projects` / the workspace)?
3. **Goals**: what should it achieve in the next months? 4. **Budget**: how many USD a day at most? 5. **Autonomy**: `careful`
(ask before most things), `balanced` or `autonomous`.

Then propose a chart as a short tree (position, lead, department, one-line job; 3 to 8 positions, at most 3 levels), for example:
```
Head of marketing (marketing)
  Writer: articles for the blog
  Social media: weekly posts
```
The New enterprise dialog also offers ready-made charts (Marketing agency, E-commerce, Content studio, Research and watch);
the commands below build any chart. **Wait for the
owner's OK and apply their edits.** Only then run, one per line:
```
maxxing enterprise create acme-group --name "Acme Group" --project acme
maxxing enterprise position add acme-group lead --title "Head of marketing" --department marketing --job "..."
maxxing enterprise position add acme-group writer --title "Writer" --reports-to lead --job "..."
maxxing enterprise settings acme-group autonomy=balanced envelope.usd_per_day=10 digest.enabled=true
```
Positions start **vacant**. Offer to hire each one (the Hire button of the chart, or the skill `maxxing-agents` to create the
agent, then `position seat`), and **never create an agent without the owner's explicit yes**. To start from a file,
`maxxing enterprise import FILE.zip` creates a new enterprise with vacant positions; its agent files are in
`files/imported-agents/` to hire from. Never put keys or secrets in a job description.
