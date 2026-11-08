---
section: Connectivity
---
# Telegram

Talk to your sessions from your phone. Harness Maxxing includes its own Telegram gateway: no extra
program to install. One bot, linked to **your** private chat only.

## Modes (Settings -> Telegram -> Mode)

| Mode | What you get |
|---|---|
| **Simple** (default) | **one chat to follow.** Write a message: the bot asks in which topic (or offers **↩ Continue** the last session you wrote to), the session runs, its live status and its answer come **as replies to your message**. **Reply** to any message of a session (its answer, your own message, its bell) to continue it. The alerts land in the same chat. Every session is also in the web UI, as usual |
| **One thread per session** | the Telegram chat mirrors the Sessions page: one thread per open session, plus *Crons*, *Alerts* and *Notifications* threads (see [Threads: one per open session](#threads-one-per-open-session)) |
| **Threads + web conversations** | the same, and what you write in the web UI and Claude's answers are copied into the session's thread, silently |

In every mode, an [agent](agents) with the Telegram option keeps **its own thread** (its results, a reply there
goes on with that result, its approval requests). The alerts are, in the main chat (Simple) or in *Alerts*:

- the [notifications you can act on](feed): an agent's request (**Allow** / **Deny**, always sent and loud), a failed
  run, an agent at its budget or its runs per hour, and the server's problems (disk almost full, a service down,
  Claude signed out, a backup that failed or is old; Settings -> Notifications -> *Server problems in the
  notifications*), with their buttons; once handled, the message says how it ended. A request too long for one
  message ends with *…(cut, open it to see all)* and keeps only **Refuse** / **Open**: send or allow it from Harness. In
  the agent's thread when it has the Telegram option;
- **server alerts** (Settings -> Telegram -> *Server alerts*, on by default): an update that failed or was rolled
  back, an update available, a known vulnerability, Claude Code that could not update;
- **sign-in alerts** and the [two-step sign-in](#two-step-sign-in) requests;
- **job reports** (*Cron reports*): per job, failures only (default) or every run; failures ring;
- the [notifications feed](feed) when its Telegram option is on (sales, orders, your scripts…, with an *Ask
  Harness* button).

Changing from a threads mode to **Simple** asks first, then deletes the session threads and the *Crons*,
*Alerts*, *Notifications* threads from Telegram (with their messages; the sessions stay in the web UI; agents keep
their threads). Going back to threads creates them again. From a shell: `maxxing telegram mode [simple|threads|mirror]`.
An installation that already had threads before this setting existed keeps them (mode *One thread per session*).
If Telegram refuses threads in your chat (Threaded Mode off in @BotFather), the chat works as Simple whatever the
mode.

## Setup (Settings -> Telegram)

1. In Telegram, open **@BotFather**, send `/newbot`, choose a name and a username ending in `bot`.
   Copy the token it gives you (`123456789:AA...`).
2. Optional: in BotFather, send `/mybots`, pick your bot, then **Bot Settings -> Threaded Mode -> turn it on**.
   The Simple mode does not need it; agents' own threads and the threads modes do (without it everything goes to
   the main chat, and in a threads mode Settings -> Telegram shows a notice with a **Retry** button).
3. Paste the token in Settings -> Telegram and press **Verify token**. The server checks it, and checks
   that no other program uses the bot (a webhook, or another program reading its messages).
4. Click **Link my Telegram**, open the `t.me/<bot>?start=<code>` link on your phone (or scan the QR code)
   and press **Start**. The code is valid 15 minutes (the countdown shows under it; then **New link**).
   You can leave the page: the code is still there when you come back. From then on, messages from any
   other chat are ignored.
5. Setup is done as soon as the chat is linked. In a threads mode the threads are created right after linking
   (and kept in sync automatically: see below).
6. Choose the mode and the options: cron reports, server alerts, sign-in alerts, [two-step sign-in](#two-step-sign-in), reply mode (*live progress*, the default = one
   status message updated while Claude works with its task list and each step, folded into a summary
   at the end; *final answer* = only the answer). Press **Send a test message**: it sends a message
   and checks that the server receives messages too (poller running, last answer from Telegram, no webhook).

At every stage, **Change bot** takes the token of another bot (or a new token of the same bot) - nothing
changes until it is verified - and, once linked, **Link another chat** replaces the linked chat.

Cron reports arrive in *Crons* (the main chat in Simple): a Claude job's answer is shown from its beginning, formatted like a normal reply
(bold, lists, code; tables become one bullet per row), split over several messages and cut after about 12,000
characters (the whole answer stays on the Crons page). A command job shows the end of its output, where errors
are. Successful reports arrive silently; failures ring.

## Threads: one per open session

(Modes *One thread per session* and *Threads + web conversations*.)

| You do | Telegram |
|---|---|
| Open or start a session in the web UI | its thread appears (a few seconds later; a new session waits for its short title, up to a minute, so the thread is named once) |
| Rename a session | its thread is renamed |
| **Archive** a session (session menu -> Archive), or send `/close` in its thread | its thread is deleted - the conversation stays in the web UI (Archived) |
| Un-archive it | the thread comes back (new, empty) |
| Write in the **main chat** | the bot asks *where* (topic buttons); the session is created there with its own thread and your message goes to it (and the ones you write while it is being created). No answer within 5 minutes: `general/inbox`. A server restart meanwhile keeps the question and your messages |
| Create a thread yourself | same question; that thread becomes the session's thread |
| **Close** a thread in Telegram (not delete) | nothing changes: the next message for it reopens the same thread (no duplicate) |
| Delete a thread by hand in Telegram | the session stays open (Telegram does not tell bots) and gets a new thread the next time it is used - e.g. you write in it from the web UI. To really close it: `/close` |
| Write in a session from the **web UI** | mode *Threads + web conversations*: your message ("🖥 …") and Claude's answer are copied into its thread, silently; the session's **bell** makes its answers ring on the phone |
| Reply in the **main chat** to a message of a session (its bell, for instance) | it goes to that session |

A thread is named `<project>/<topic> · <session title>`, with the project's emoji in front when it has one (project
**…** menu in Sessions -> *Set an emoji…*), e.g. `🛒 acme/blog · Launch plan`. Changing only the emoji does not rename
existing threads (each rename posts a notice in the chat); new threads get it.

Mirrored sessions: the ones you talk to (not those started by scheduled jobs - their reports go to
*Crons*), not archived, active in the last **30 days** (Settings -> Telegram -> *Keep a thread for*:
7, 14, 30 or 90 days), at most 50. An older session simply gets its thread back when it is used
again. The sync runs a few seconds after any change and every 10 minutes; nothing to schedule. If Telegram
refuses to delete a thread for a moment (too many requests, no connection), the next sync deletes it.
Renaming a session renames its thread: Telegram shows a small "topic renamed" line in the thread. To keep the
chat quiet, a new session's thread is renamed at most once in its first two minutes (the last name is applied
after that). Choosing a shorter *Keep a thread for* asks for confirmation and says how many threads (with their
messages) it deletes.

## Using it

- Simple: write in the chat, choose the topic, and reply to the answers to go on. Threads: write in a session's
  thread, Claude answers in that thread. While it works you see "typing…" and,
  for longer tasks, the live status message. A message sent while the session is busy waits its turn and
  gets its own answer (a turn started from the web UI or an automatic summary is never sent as the answer);
  "typing…" stops as soon as the queue is stopped or cleared. A server restart (an update) while Claude works
  does not lose the answer: it still comes in the thread when the turn ends.
- Send photos and files: they are saved in `<topic>/attachments/telegram/YYYY-MM/` and passed to
  Claude with your caption. An album is one message to Claude, and what you send right after it comes after
  it. Audio files (music, recordings sent as files) are files too; only voice notes and round video notes are
  transcribed. A caption is never a command: a photo captioned `/new` is a photo. A file the bot cannot save
  (over 20 MB) is named in a reply, and the other files of the album still go to Claude.
- Replies, quotes and forwards keep their context: replying to a message (or quoting part of it) sends
  Claude the quoted part in front of your text (not when you simply reply to Claude's own answer to go on), a
  forwarded message says where it comes from, and links hidden behind a word are passed as "word (link)".
- A very long text that Telegram splits into several messages (over 4,096 characters) is put back together
  and sent as one message.
- Editing a message you already sent does nothing: the bot says so once - send a new message instead.
- The bot answers in the language of the web UI (English or French), and the command menu is
  translated. While linking, it uses the language of your Telegram app.
- Commands:

| Command | Effect |
|---|---|
| `/new [title]` | new session: asks the topic (in a session's thread, or as a reply to one of its messages: same topic) |
| `/sessions` | Simple: the recent sessions as buttons - tap one, then reply to the message that comes to continue it. Threads: list the open sessions |
| `/stop` | stop the running turn |
| `/close` | archive the session (kept in the web UI; its thread, if any, deleted) |
| `/model [id]` | show or change the model of the session (an id, a name such as `Sonnet 5.5`, or `opus` / `sonnet` / `haiku` for the newest of that family; an unknown name lists the choices) |
| `/status` | state, model, cost, queue, link to the web UI |
| `/help` | list the commands |

  In Simple, `/stop`, `/close`, `/model` and `/status` act on the session of the message you reply to, else on the
  last session you wrote to (its title is in the answer).

- The **bell** of a session (web UI, next to its title): when a turn that did not come from Telegram ends (you
  worked in the web UI, for instance), a short "✅ title - preview" message rings on the phone: in the session's
  thread, else in the main chat, where replying to it continues the session. A session started on the phone and
  continued in the web UI rings too. In *Threads + web conversations* it makes the copied answers ring.

## Two-step sign-in

Settings -> Telegram (or Settings -> Security) -> **Two-step sign-in**: after the right password, a browser
that is not trusted yet waits for your approval in Telegram. The *Alerts* thread (the main chat in Simple) gets a message with the IP,
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
answer cannot lock you out. Turning it off from the web UI asks for the current password and posts a notice in
the *Alerts* thread and the notifications feed; unlinking Telegram or changing the bot turns it off too, so they
ask for the current password as well, with the same notice.

**Telegram does not answer** (bot deleted, Telegram down, phone lost): on the server, over SSH,

```bash
maxxing 2fa off             # password only again (every trusted browser is forgotten)
maxxing 2fa status          # on / off
```

## Troubleshooting

```bash
maxxing telegram status     # bot, chat, mode, poller (running, last answer from Telegram), pending link, errors, threads
maxxing telegram mode       # the mode; `maxxing telegram mode simple` changes it
maxxing telegram test       # sends a test message and checks the receiving side (poller, webhook)
```

Settings -> Telegram shows the same: **Gateway** (running / stopped), **Last answer from Telegram**,
*Receiving messages* errors (the poller) apart from *Thread sync* errors.

| Problem | Fix |
|---|---|
| "Telegram rejected the bot token" | the token was revoked or replaced in BotFather (`/revoke`, `/token`): Settings -> Telegram shows the token field right away - paste the new token. Same bot: the chat and the threads are kept |
| "This bot sends its messages to a webhook" | another program (n8n, Make, an old script…) receives the bot's messages through a webhook: press **Remove the webhook** (that program stops receiving them) or create a dedicated bot |
| "Another program (n8n, Hermes, OpenClaw…) is already using this bot" | Telegram gives a bot's messages to one program only (error 409 Conflict): stop the other program, or create a bot dedicated to Harness Maxxing |
| "This link expired or is not valid" in Telegram | the code is older than 15 minutes, or Start was pressed before the link was created: Settings -> Telegram -> **New link**, then open that link (or scan its QR code). A Start pressed before the link exists is ignored |
| Nothing answers | the message comes from another chat than the linked one: **Link another chat** |
| Too many threads | Settings -> Telegram -> Mode -> **Simple**: one chat, the threads are deleted |
| Everything lands in one chat ("Threads are disabled for this bot") | that is the Simple mode; in a threads mode, Threaded Mode is off for the bot: in BotFather `/mybots` -> your bot -> Bot Settings -> Threaded Mode, then **Retry** in Settings -> Telegram. Not an error: the main chat works meanwhile |
| A session vanished from Telegram | archived (in the web UI: Sessions tree -> topic -> Archived), or idle longer than *Keep a thread for* - it comes back when you use it |
| A special thread (Crons, Alerts) was deleted | **Sync threads** (Settings -> Telegram -> Threads) recreates it |
| Two-step sign-in: no message, you cannot sign in | on the server: `maxxing 2fa off`, then sign in with the password |

`maxxing doctor` warns when the bot is configured but the server is not reading its messages (poller
stopped, or no answer from Telegram for 5 minutes), when the token was rejected, or when the last thread
sync failed. Threads being off is shown as a note, not a warning.

To disconnect: Settings -> Telegram -> **Disconnect Telegram** (forgets the token, the chat and the threads).
