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
- **The conversation**, on the left: talk to it like in any session (text, files, voice). It answers short and says
  what it launched, with a link to the session: open it and type in it to take over at any time.
- **Work**, on the right (the list icon on a phone): everything Jarvis handed over. **Waiting for you** (the session
  asks a question), **In progress**, **Answered**. **Open** goes to the session, **Done** closes the entry.
- **New conversation** starts afresh; the work in progress still reports into the new one.

## How the work comes back
Each session Jarvis starts or writes to is on its work board. When one of its turns ends, its answer comes back into
Jarvis's conversation by itself, and Jarvis tells you what matters and decides the next step. If you take over a
session yourself, its answers are not reported (you read them there).

## Morning brief and night pass
- **Morning brief** (08:00 by default): what waits for you, the work in progress, today's tasks and 2-3 proposals.
  With **New conversation each morning** (on by default), each day starts a new conversation with the brief.
- **Night pass** (03:30 by default): Jarvis reads what changed in your projects, sessions, tasks and notifications
  and rewrites its own memory, so the next conversation knows where everything is. It changes nothing else.
Both times are in Jarvis's settings (gear icon); **Brief now** and **Night pass now** run them at once.

## Settings (gear icon)
- **Full rights** (on): Jarvis and the sessions it starts work without permission prompts.
- **Ask me first** (on): before publishing, paying, deleting or writing to someone, it says what it will do and waits
  for your yes. Off: it acts and tells you after.
- **New conversation each morning**: off = one long conversation (compacted when it gets long).
- **Show internals**: Jarvis lives in a project of its own (`jarvis`), hidden from the tree, the session lists and
  the search. Turn this on to see it, its past conversations and night passes.

## From the command line
`maxxing jarvis status | say "..." | new | work [--all] | work close N | digest | brief | dream | set KEY VALUE`, and
`maxxing topics list | new <project>/<topic>`. Any session can also hand work to another and get its answers back:
`maxxing sessions new <project>/<topic> "..." --report-to me`.
