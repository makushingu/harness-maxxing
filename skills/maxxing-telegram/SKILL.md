---
name: maxxing-telegram
description: Explain, configure or troubleshoot the Harness Maxxing Telegram bridge - creating the bot with BotFather, linking the chat, the three modes (Simple = one chat where a reply continues a session; one thread per session; threads + web mirror), starting sessions from the phone, sending messages and files, alerts (server problems, sign-ins, jobs, agents). Use when the user mentions Telegram, the bot, threads, too many threads, or phone notifications.
---

# Telegram bridge

Harness Maxxing has a built-in Telegram gateway (no separate bot program): one bot, one linked private chat.
Three modes (Settings -> Telegram -> Mode, or `maxxing telegram mode [simple|threads|mirror]`):

- **simple** (default of new installs): ONE chat. A message that replies to nothing -> the bot asks the topic
  (buttons; "↩ Continue" = the last session written to from Telegram, < 2 h; default topic after 5 min) -> the
  session runs without a thread; its live status and answer are replies to the message. **Replying** to any message
  of a session (answer, own message, bell, `/sessions` card) continues it. `/stop`, `/close`, `/model`, `/status`
  act on the session replied to, else the last one. Alerts land in the same chat.
- **threads**: one thread per open session (`<project>/<topic> · <title>`, not archived, not a cron, active in the
  last `thread_days` days, max 50) + "Crons", "Alerts", "Notifications". A thread IS the session. Archive / `/close`
  -> thread deleted; main chat message or a thread the user creates -> topic question -> that thread is the session's.
  Sync automatic (session changes + every 10 min); **Sync threads** forces it.
- **mirror**: threads + turns made in the web UI copied into the thread ("🖥 …" + answer), silently unless the bell.

Installs that had threads before the modes existed keep `threads` (or `mirror`). Switching to simple deletes the
session threads and Crons / Alerts / Notifications from Telegram (sessions stay; agents keep their threads). A
chat that refuses threads (Threaded Mode off) works as simple. Agents with the `telegram` option always have their
own thread (results, reply = continue that run, approvals).

Alerts (main chat in simple, else "Alerts"/"Crons"): dashboard health problems (once, **Seen** button, edited
"Resolved"; setting *Server alerts* = `notify_system`), update / vulnerability problems, sign-in alerts and
two-step sign-in, failed jobs (per-job notify policy; `notify_crons`), agents' approvals (Allow / Deny), the feed
when its Telegram option is on.

## Configure (prefer the UI wizard: Settings -> Telegram)
1. In Telegram, open **@BotFather** -> `/newbot` -> choose a name and a username ending in `bot`
   -> copy the token (`123456:ABC…`). Optional: `/mybots` -> the bot -> Bot Settings -> **Threaded Mode** on
   (needed only for agents' own threads and the threads modes; simple works without it).
2. Settings -> Telegram -> paste the token -> **Verify token** (the server calls `getMe`, refuses a bot
   with a webhook - **Remove the webhook** button - or one another program is polling: 409).
3. **Link my Telegram** -> open the `t.me/<bot>?start=<code>` link on the phone (or scan the QR) ->
   Start. The code is valid 15 min (countdown, then **New link**) and survives leaving the page. Only
   this chat (and its user) will be accepted from then on. In a threads mode, threads are created right after linking.
4. Setup is done once the chat is linked. In a threads mode with Threaded Mode off, a notice with **Retry** shows in
   Settings -> Telegram (not an error).
5. Settings: mode, cron reports, server alerts, sign-in alerts, reply mode `final` (only the final answer)
   or `progress` (tool steps too). **Send a test message** (also checks the poller and the webhook).
   **Change bot** (new token, any stage), **Link another chat**, **Disconnect Telegram** (forgets all).

A token must never be pasted in a session or written in memory; the wizard stores it in
`secrets.json`. If the user pastes a token in the chat, use it only through the UI and remind them
it is now in the conversation log (rotate with BotFather `/revoke` if needed).

## Use
- Simple: write, pick the topic, reply to go on. Threads: write in a session's thread -> Claude answers there.
  Photos, documents and voice notes (transcribed) are saved as attachments of the topic and passed to Claude.
- Commands: `/new [title]` (asks the topic; as a reply / in a thread: same topic), `/stop`, `/close` (archive; its
  thread deleted), `/model <id>`, `/sessions` (simple: recent sessions -> a card to reply to; threads: open ones),
  `/status`, `/help`.
- The session's bell (Notify): a turn that did not come from Telegram rings a short "finished" message - in its
  thread, else in the main chat (reply to it to continue). A session started on the phone rings for web turns.

## Check / troubleshoot
```bash
maxxing telegram status        # configured, bot, chat, mode, poller running + last answer from Telegram, pending link, errors, threads
maxxing telegram mode          # show the mode; `maxxing telegram mode simple` changes it
maxxing telegram test          # sends a test message + checks poller and webhook (exit 1 on a problem)
maxxing doctor                 # warns: poller stopped / no getUpdates for 5 min, token rejected, sync failed
journalctl -u claude-maxxing -n 100 --no-pager | grep -i telegram
```
`poll_error` (the poller: 401 `token_rejected`, 409 `conflict`, `unreachable`) and `sync_error` (thread sync)
are kept apart; `topics_notice` = Threaded Mode off (info). State file: `state_dir('telegram')/state.json`
(`last_poll_ok`, `poller_pid` written by the server's poller).

| Problem | Fix |
|---|---|
| Token rejected (401) | revoked or replaced in BotFather -> Settings -> Telegram shows the token field: paste the new token (same bot keeps the chat and threads) |
| Webhook set ("This bot sends its messages to a webhook") | another program (n8n, Make…) uses the bot -> **Remove the webhook** in the wizard, or a dedicated bot |
| 409 Conflict ("Another program … is already using this bot") | n8n, Hermes, OpenClaw, a second server… polls the same bot -> stop it or create a new bot |
| "This link expired or is not valid" in Telegram | code older than 15 min, or Start pressed before the link existed (such old messages are ignored) -> **New link**, open it |
| Messages ignored | sent from another chat/user than the linked one -> **Link another chat** in Settings |
| "Too many threads" | mode simple: Settings -> Telegram -> Mode -> Simple, or `maxxing telegram mode simple` |
| No threads / everything in one chat | that is the simple mode; in a threads mode: Threaded Mode off in BotFather -> turn it on, then **Retry** |
| A session's thread disappeared | the session was archived (`/close`, deleted thread) or is idle longer than `thread_days`; un-archive it or write in it from the web UI |
| "Crons" or "Alerts" thread deleted | **Sync threads** recreates it |
| No cron reports | Telegram setting `notify_crons` off, or the job's notify policy is `never` |

Never call `getUpdates` yourself against the configured bot: it would steal updates from the gateway.
