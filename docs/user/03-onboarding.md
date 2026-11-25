---
section: Getting started
---
# Onboarding

The first visit happens through the **one-time setup link** printed by the installer
(`https://ui.example.com/setup?token=...`). Whoever has the link can claim the instance, so keep
it private. Lost it? Run `maxxing setup-link` on the server.

The setup link first asks for the UI password (8 characters minimum, stored hashed with scrypt).
Then the wizard has nine steps. You can leave and come back: it resumes where you stopped, and
every step also exists in Settings.

1. **Language & time zone** – English or French, and the time zone used by scheduled jobs.
2. **About you** (all optional) – your pseudo, an email for security alerts (and the product news if you want),
   and, only for companies that have one, an **Enterprise license key**. The anonymous installation counter is on by
   default and is turned off in Settings → Profile. See [License](license).
3. **Claude connection** – the wizard detects whether Claude Code is signed in. Otherwise:
   - run `claude setup-token` on any machine with a browser and paste the long-lived token, or
   - paste an Anthropic API key (pay-as-you-go).
   A real one-line test call confirms it works.
4. **Import** (optional) – coming from another agent (Hermes, Claude Code, OpenClaw…)? Copy the
   prompt into it, drop the zip it makes: your projects, topics, memory and skills arrive, and
   Claude finishes the job (tasks, scheduled jobs, keys to add). See [Import](import).
5. **First project & topic** – a starter project `general` with a topic `inbox` already exists;
   create your own (for example `acme` / `blog`).
6. **Your pages** (optional) – *What will you use?* Sessions, Files and Notifications are always there; switch on
   the other pages you need now (Agents is on already; Tasks, Team, E-mail, Infra, Git are off). The same rows
   as Settings → Features, where you change them any time. See [Settings](settings-and-keys#features).
7. **Telegram** (optional) – connect a bot to talk to your sessions from the phone. See
   [Telegram](telegram).
8. **Memory backup** (optional, recommended) – a private GitHub repository receiving your memory
   every day. See [Backup](backup).
9. **Ready** – then the **getting started guide** is proposed (below), and **Tell me when a session finishes** (a browser notification when
   Claude is done and the tab is not in front; also in Settings → Features).

## The getting started guide

Proposed once after the wizard (and once after the update that brought it), and always in Help (**?** at the bottom
left of the sidebar) -> **Getting started guide**, the palette (⌘K) and Settings -> General. An address ending in
`?guide` opens it too.

It speaks the language of Harness (Settings -> General), examples included.

1. **Your level**: *Beginner* (step by step, simple examples) or *Intermediate* (what Harness adds, examples that go
   further).
2. **The tour**: *Full* (about 5 minutes: sessions, Zones and Tabs, memory, agents on their page and in the
   sessions, scheduled jobs, tasks, phone, code, sites, e-mail, Team, files, backup, the pages to switch on, server
   health) or *Partial* (about 2 minutes): the essentials plus only the uses you tick - the recommended ones are
   ticked already (from what is set up here). **Close** if you do not need it.

Each step lights up the part of the screen it explains, with a one-line explanation and a tip. On the steps where
you do something, **Opus writes for you, as you go**, one example (two for *Intermediate*: a simple one, then a more
ambitious one) about your own projects - what you imported from another agent, or your sessions and agents if you
already use Harness - each one following on from what you did at the step before. The examples are written when
you get near the step (a few seconds each, on your Claude plan); if Opus cannot write one, the step keeps its
explanation.

**Try it** opens a new session with the example in its message box: read it, change it, send it - nothing is sent
by itself. The guide then waits in a small pill on the right edge of the screen (**Continue**). A step about a page that is
off (Agents, Tasks, Git...) switches it on in one click. **Esc** or **Pause** puts the guide aside; it picks up where
you left off, on any of your devices, from Help -> Getting started guide (**Resume** or **Start again**).

## After the wizard: the tutorial

The workspace comes with the topic `system/tutorial`: four lessons of about 5 minutes (sessions and files,
memory, tasks and scheduled jobs, Telegram and voice) in one topic. Start a session there and say "hi": Claude
guides you one exercise at a time, checks your result and remembers where you stopped. When you are done, it
offers to delete the topic (it goes to the Trash); updates never re-create it. Servers installed before 2.0.0a33
have the former `tutorial` project, one topic per lesson.

The onboarding step **Your projects** also offers the [starter projects](starter-projects) (install all, choose,
or none).

For questions later, use the topic `system/help` (see [The system project](system-project)).

## Setting up from the terminal instead

Open a terminal on the server and run:

```bash
cd /root/maxxing && claude
```
then say **"set up Harness Maxxing"**. The `maxxing-setup` skill runs `maxxing doctor`, fixes what
it can, and walks you through the same steps.
