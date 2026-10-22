---
section: Getting started
---
# Onboarding

The first visit happens through the **one-time setup link** printed by the installer
(`https://ui.example.com/setup?token=...`). Whoever has the link can claim the instance, so keep
it private. Lost it? Run `maxxing setup-link` on the server.

The setup link first asks for the UI password (8 characters minimum, stored hashed with scrypt).
Then the wizard has eight steps. You can leave and come back: it resumes where you stopped, and
every step also exists in Settings.

1. **Language & time zone** – English or French, and the time zone used by scheduled jobs.
2. **About you** (all optional) – your pseudo, an email for security alerts (and the product news if you want),
   the anonymous installation counter, and, only for companies that have one, an **Enterprise license key**. See
   [License](license).
3. **Claude connection** – the wizard detects whether Claude Code is signed in. Otherwise:
   - run `claude setup-token` on any machine with a browser and paste the long-lived token, or
   - paste an Anthropic API key (pay-as-you-go).
   A real one-line test call confirms it works.
4. **Import** (optional) – coming from another agent (Hermes, Claude Code, OpenClaw…)? Copy the
   prompt into it, drop the zip it makes: your projects, topics, memory and skills arrive, and
   Claude finishes the job (tasks, scheduled jobs, keys to add). See [Import](import).
5. **First project & topic** – a starter project `general` with a topic `inbox` already exists;
   create your own (for example `acme` / `blog`).
6. **Telegram** (optional) – connect a bot to talk to your sessions from the phone. See
   [Telegram](telegram).
7. **Memory backup** (optional, recommended) – a private GitHub repository receiving your memory
   every day. See [Backup](backup).
8. **Ready** – a short tour of the interface.

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
