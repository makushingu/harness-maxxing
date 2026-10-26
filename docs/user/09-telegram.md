---
section: Connectivity
---
# Telegram

Talk to your sessions from your phone. Harness Maxxing includes its own Telegram gateway: no extra
program to install.

- One bot, linked to **your** private chat only.
- **One thread per open session** - the Telegram chat mirrors the Sessions page - plus *Crons*
  (job reports), *Alerts* (sign-in alerts, and problems of the server itself: an update that failed or was
  rolled back, an update available, a known vulnerability, Claude Code that could not update; on by default,
  setting `notify_system` of `PUT /api/telegram/settings`) and *Notifications* (the [notifications feed](feed): sales, orders,
  your scripts… per the rules you set, posted by the bot itself, with an *Ask Harness* button). A thread is named `<project>/<topic> · <session title>`, with the project's emoji in front when it has one (project **…** menu in Sessions -> *Set an emoji…*), e.g. `🛒 acme/blog · Launch plan`. Changing the emoji renames the threads.
- A thread is the session itself: what you write on the phone appears in the web UI and you can
  continue there, and the other way round.
- Write in the **main chat** (or create a thread) to start a new session: the bot asks in which topic.

## Setup (Settings -> Telegram)

1. In Telegram, open **@BotFather**, send `/newbot`, choose a name and a username ending in `bot`.
   Copy the token it gives you (`123456789:AA...`).
2. In BotFather, open your bot's settings and **enable topics (threads) for private chats**, so
   each open session gets its own thread. Without it everything works in the main chat (use
   `/topic` to choose which topic it talks to).
3. Paste the token in Settings -> Telegram. The server checks it.
4. Click **Link**, open the `t.me/<bot>?start=<code>` link on your phone and press **Start**. The
   code is valid 15 minutes. From then on, messages from any other chat are ignored.
5. Click **Sync threads** (afterwards it is automatic: see below).
6. Choose the options: cron reports, sign-in alerts, [two-step sign-in](#two-step-sign-in), reply mode (*live progress*, the default = one
   status message updated while Claude works with its task list and each step, folded into a summary
   at the end; *final answer* = only the answer). Press **Send test**.

Cron reports arrive in *Crons*: a Claude job's answer is shown from its beginning, formatted like a normal reply
(bold, lists, code; tables become one bullet per row), split over several messages and cut after about 12,000
characters (the whole answer stays on the Crons page). A command job shows the end of its output, where errors
are. Successful reports arrive silently; failures ring.

## Threads = open sessions

| You do | Telegram |
|---|---|
| Open or start a session in the web UI | its thread appears (a few seconds later) |
| Rename a session | its thread is renamed |
| **Archive** a session (session menu -> Archive), or send `/close` in its thread | its thread is deleted - the conversation stays in the web UI (Archived) |
| Un-archive it | the thread comes back (new, empty) |
| Write in the **main chat** | the bot asks *where* (topic buttons); the session is created there with its own thread and your message goes to it (and the ones you write while it is being created). No answer within 5 minutes: `general/inbox`. A server restart meanwhile keeps the question and your messages |
| Create a thread yourself | same question; that thread becomes the session's thread |
| **Close** a thread in Telegram (not delete) | nothing changes: the next message for it reopens the same thread (no duplicate) |
| Delete a thread by hand in Telegram | the session stays open (Telegram does not tell bots) and gets a new thread the next time it is used - e.g. you write in it from the web UI. To really close it: `/close` |
| Write in a session from the **web UI** | optional (off by default): Settings -> Telegram -> *Show web conversations in Telegram* copies your message ("🖥 …") and Claude's answer into its thread, silently; the session's **bell** makes its answers ring on the phone |

Mirrored sessions: the ones you talk to (not those started by scheduled jobs - their reports go to
*Crons*), not archived, active in the last **30 days** (Settings -> Telegram -> *Keep a thread for*:
7, 14, 30 or 90 days), at most 50. An older session simply gets its thread back when it is used
again. The sync runs a few seconds after any change and every 10 minutes; nothing to schedule. If Telegram
refuses to delete a thread for a moment (too many requests, no connection), the next sync deletes it.
Renaming a session renames its thread: Telegram shows a small "topic renamed" line in the thread.

## Using it

- Write in a session's thread: Claude answers in that thread. While it works you see "typing…" and,
  for longer tasks, the live status message. A message sent while the session is busy waits its turn and
  gets its own answer (a turn started from the web UI or an automatic summary is never sent as the answer);
  "typing…" stops as soon as the queue is stopped or cleared.
- Send photos and files: they are saved in `<topic>/attachments/telegram/YYYY-MM/` and passed to
  Claude with your caption.
- Commands:

| Command | Effect |
|---|---|
| `/new [title]` | new session in the same topic, with its own thread (in the main chat: asks the topic) |
| `/sessions` | list the open sessions |
| `/stop` | stop the running turn |
| `/close` | close this session: archived (kept in the web UI) and its thread deleted |
| `/model [id]` | show or change the model of the session |
| `/status` | state, model, cost, queue, link to the web UI |
| `/topic` | (main chat, threads off) choose the topic |
| `/help` | list the commands |

- The **bell** of a session (web UI, next to its title): with the mirror off (default) it posts a short
  "finished" message in the session's thread when a turn ends; with the mirror on it makes the
  mirrored answers ring.

## Two-step sign-in

Settings -> Telegram (or Settings -> Security) -> **Two-step sign-in**: after the right password, a browser
that is not trusted yet waits for your approval in Telegram. The *Alerts* thread gets a message with the IP,
the browser, a 6-digit code and two buttons:

- **Allow**: the sign-in page opens by itself;
- **Deny**: the sign-in is refused - and since the right password was typed, change it (Settings -> Security).

When the buttons do not answer, type the code of the message on the sign-in page. A request expires after
2 minutes; 5 wrong codes cancel it, and after 20 wrong codes in an hour on the whole server codes are paused for
the hour (the **Allow** button still works) - someone who knows the password cannot try codes from many
addresses. A sign-in page opened again replaces its previous request. **Trust this browser for 30 days** (ticked
by default) skips the second step on that browser; **Forget trusted browsers** makes every other browser ask again
(changing the password does it too). Changing the password, forgetting browsers or turning two-step sign-in off
also cancels every request still waiting, even one you allowed by mistake.

Turning it on sends a first request: it is only switched on once you approved it, so a bot that does not
answer cannot lock you out. Unlinking Telegram turns it off.

**Telegram does not answer** (bot deleted, Telegram down, phone lost): on the server, over SSH,

```bash
maxxing 2fa off             # password only again (every trusted browser is forgotten)
maxxing 2fa status          # on / off
```

## Troubleshooting

```bash
maxxing telegram status     # bot, chat, threads, settings, last error
maxxing telegram test       # sends a test message
```

| Problem | Fix |
|---|---|
| Token rejected | revoked or mistyped: get a new one from BotFather (`/token`) and paste it again |
| "Conflict: terminated by other getUpdates" | another program (an old bot, another server) uses the same bot: stop it or create a new bot |
| Nothing answers | the message comes from another chat than the linked one: re-link |
| Everything lands in one chat | topics not enabled for the bot in BotFather; enable, then Sync threads |
| A session vanished from Telegram | archived (in the web UI: Sessions tree -> topic -> Archived), or idle longer than *Keep a thread for* - it comes back when you use it |
| A special thread (Crons, Alerts) was deleted | Sync threads recreates it |
| Two-step sign-in: no message, you cannot sign in | on the server: `maxxing 2fa off`, then sign in with the password |

To disconnect: Settings -> Telegram -> **Unlink** (forgets the token and the chat).
