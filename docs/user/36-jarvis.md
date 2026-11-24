---
section: Using Harness Maxxing
---
# Jarvis

Jarvis is one assistant you talk to, and it runs Harness for you. You say what you want ("write the next article of
the blog", "start a newsletter", "where are we?"), and Jarvis does the rest: it picks the right project and topic (or
creates them), hands the work to a session there, gets the result back when the session is done and tells you, in
the same conversation. You never have to think about projects, topics, sessions or commands.

Turn it on in **Settings -> Features -> Jarvis**. It then sits at the top of the sidebar.

## The page
- **The conversation**, on the left: talk to it like in any session (text, files, voice), without a session's title,
  place or options: Jarvis is not one of your sessions. It answers short and says what it launched, with a link to
  the session: open it and type in it to take over at any time.
- **Work**, on the right (the list icon on a phone): everything Jarvis handed over. **Waiting for you** (the session
  asks a question), **In progress**, **Answered**. **Open** goes to the session, **Done** closes the entry. On a computer, the list icon hides or shows it and its left edge
  can be dragged to make it wider (double-click: back to the default).
- **New conversation** (gear menu) starts again with an empty context, so its turns cost less; Jarvis keeps what
  matters in its memory, and the work in progress still reports into the new one. With **New conversation each
  morning** this happens by itself every day.

## How the work comes back
Each session Jarvis starts or writes to is on its work board, and is asked to end with a short report (anything
long goes to a file it names). When one of its turns ends, its answer comes back into
Jarvis's conversation by itself, and Jarvis tells you what matters and decides the next step. If you take over a
session yourself, its answers are not reported (you read them there). These hand-offs stay out of your way: in the
session, Jarvis's instructions are a small folded card, and in Jarvis's conversation each report is one too
(**Report #N**, with *answered*, *asks you* in orange or *failed*), like the morning brief its backstage agent
prepared; click one to read it.

Jarvis keeps its own turns short: anything longer than a quick lookup (analysing data, a script, writing in a project)
goes to a session, so it answers you within a minute while the sessions work side by side. It follows a piece of work
on its own for up to 8 rounds (report, next step, report...); past that it asks you. Reports that arrive while it is
busy are read together in one turn, at a lighter effort than your messages (same model; `maxxing jarvis set
report_effort high`, or `""` for the same effort as your messages).

## Morning brief and night pass
- **Morning brief** (08:00 by default): what waits for you, the work in progress, today's tasks and 2-3 proposals.
  With **New conversation each morning** (on by default), each day starts a new conversation with the brief.
- **Night pass** (03:30 by default): Jarvis reads what changed in your projects, sessions, tasks and notifications
  and rewrites its own memory, so the next conversation knows where everything is. It changes nothing else.
A brief that fails (Claude signed out, a crash) is tried again every 15 minutes, three times; then a notification
tells you there is no brief today. Switching Jarvis on starts neither the brief nor the night pass at once: the first
ones come at their next time.
Both are done by Jarvis's **backstage agent** (on Sonnet): it does the reading, and the brief it prepares comes into
the conversation, where Jarvis gives it to you. It is hidden like the rest of Jarvis's internals: **Show internals**
shows it on the Agents page with its runs and their cost. Both times are in Jarvis's settings (gear icon); **Brief
now** and **Night pass now** run them at once.

## What it costs
Jarvis uses your Claude plan like any session, a bit more: one turn per message you send, one per answer that comes
back from a session it launched, the morning brief, and the night pass. The night pass runs on Sonnet and is skipped
when nothing of yours changed since the last one (scheduled jobs and agents alone do not count); a new conversation each day keeps each turn small. To spend less, clear the
brief or night pass time in its settings.

## Continued sessions, archived sessions
- **New work on the same subject continues a session you already have.** Before starting a session, Jarvis looks at
  the sessions of the topic the work belongs to (active in the last 30 days). One on the same subject, or the work
  follows up what it did: the work goes there, with its context, and Jarvis tells you which one. Never a session of
  another topic, never one that is running, one you wrote in during the last 30 minutes (you may be working there) or
  one whose context is almost full. Unsure: a new session.
- **Finished work is put away.** When Jarvis marks a piece of work done, the session it started for it goes to the
  Archives - unless you wrote in it, then it stays where it is. Sessions Jarvis only continued (yours, an agent's) are
  never archived. Its line on the work board says "archived"; the link still opens it, and it comes back by itself
  when Jarvis (or you) writes in it again.

## Settings (gear icon: a window, from the bottom on a phone)
- **Full rights** (on): Jarvis and the sessions it starts work without permission prompts.
- **Ask me first** (on): before publishing, paying, deleting or writing to someone, it says what it will do and waits
  for your yes. Off: it acts and tells you after.
- **Continue existing sessions** (on): new work on the same subject goes to a recent session of the topic. When
  Jarvis still starts a new one there, its card on the work board says why.
- **Archive finished sessions** (on): once work is done, the sessions Jarvis started and you never wrote in go to
  the Archives.
- **New conversation each morning**: off = one long conversation (compacted when it gets long).
- **Summarize its conversation at** (150k by default): past this context, its conversation is summarized and goes
  on from the summary, like any session but sooner, so each turn stays cheap. **As every session** uses the
  threshold of Settings -> Claude. The gauge next to the model shows how far it is.
- **On Telegram** (when Telegram is connected): **The brief, questions and failures** (default), **Every answer** or
  **Nothing**. Its message comes whole, signed Jarvis; reply to it on Telegram to answer Jarvis.
- **Show internals**: Jarvis lives in a project of its own (`jarvis`), hidden from the tree, the session lists and
  the search. Turn this on to see it, its past conversations and night passes.

## From the command line
`maxxing jarvis status | say "..." | new | work [--all] | work close N | digest | brief | dream | set KEY VALUE`, and
`maxxing topics list | new <project>/<topic>`. Any session can also hand work to another and get its answers back:
`maxxing sessions new <project>/<topic> "..." --report-to me`. From any session, `@Jarvis` in a message (or
`maxxing sessions send jarvis "..."`) writes into its conversation of the moment, never into an older one.
