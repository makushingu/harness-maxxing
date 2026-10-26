---
name: maxxing-telegram
description: Explain, configure or troubleshoot the Harness Maxxing Telegram bridge - creating the bot with BotFather, linking the chat, one thread per open session, starting sessions from the phone, sending messages and files, cron reports and sign-in alerts. Use when the user mentions Telegram, the bot, threads, or phone notifications.
---

# Telegram bridge

Harness Maxxing has a built-in Telegram gateway (no separate bot program). One bot, one linked
private chat that **mirrors the Sessions page: one thread per open session** (named
`<topic> · <title>`), plus "Crons" (job reports) and "Alerts" (sign-in alerts). A thread IS the
session: continue it from the web UI or the phone. Open sessions = not archived, not started by a
cron, active in the last `thread_days` days (Settings -> Telegram, default 30), at most 50.

- Archive a session, or `/close` in its thread -> the thread is deleted (data kept); un-archive ->
  new thread.
- The user deletes a thread by hand -> Telegram tells bots nothing; the session stays open and gets
  a new thread the next time it is used. To close it for real: `/close`.
- Mirror (`mirror_web`, off by default, Settings -> Telegram): turns made in the web UI are copied
  into the thread (the user message "🖥 …" + the answer), silently unless the session's bell is on.
- Main chat message, or a thread the user creates -> the bot asks which topic (buttons, default
  `general/inbox` after 5 min) -> new session there, that thread becomes its thread.
- Sync = automatic (a few seconds after a session change + every 10 minutes); **Sync threads**
  (Settings -> Telegram -> Threads) forces it. No cron needed.

## Configure (prefer the UI wizard: Settings -> Telegram)
1. In Telegram, open **@BotFather** -> `/newbot` -> choose a name and a username ending in `bot`
   -> copy the token (`123456:ABC…`). Then `/mybots` -> the bot -> Bot Settings -> **Threaded Mode**
   on, so each open session gets its own thread (optional: without it everything works in the main chat).
2. Settings -> Telegram -> paste the token -> **Verify token** (the server calls `getMe`, refuses a bot
   with a webhook - **Remove the webhook** button - or one another program is polling: 409).
3. **Link my Telegram** -> open the `t.me/<bot>?start=<code>` link on the phone (or scan the QR) ->
   Start. The code is valid 15 min (countdown, then **New link**) and survives leaving the page. Only
   this chat (and its user) will be accepted from then on. Threads are created right after linking.
4. Setup is done once the chat is linked. If Threaded Mode is off, a notice with **Retry** shows in
   Settings -> Telegram (not an error).
5. Settings: cron reports on/off, sign-in alerts on/off, reply mode `final` (only the final answer)
   or `progress` (tool steps too). **Send a test message** (also checks the poller and the webhook).
   **Change bot** (new token, any stage), **Link another chat**, **Disconnect Telegram** (forgets all).

A token must never be pasted in a session or written in memory; the wizard stores it in
`secrets.json`. If the user pastes a token in the chat, use it only through the UI and remind them
it is now in the conversation log (rotate with BotFather `/revoke` if needed).

## Use
- Write in a session's thread -> Claude answers there. Photos and documents are saved as attachments
  of the topic and passed to Claude.
- Commands: `/new [title]` (sibling session in the same topic, own thread), `/stop` (stop the
  running turn), `/close` (archive + delete the thread), `/model <id>`, `/sessions` (list the open
  sessions), `/status`.
- The session's bell (Notify): a short "finished" message in its thread when a turn ends (mirror on:
  the mirrored answers ring instead).

## Check / troubleshoot
```bash
maxxing telegram status        # configured, bot, chat, poller running + last answer from Telegram, pending link, poll error, sync error, threads
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
| No threads / everything in one chat | Threaded Mode off for the bot in BotFather -> turn it on, then **Retry** in Settings -> Telegram |
| A session's thread disappeared | the session was archived (`/close`, deleted thread) or is idle longer than `thread_days`; un-archive it or write in it from the web UI |
| "Crons" or "Alerts" thread deleted | **Sync threads** recreates it |
| No cron reports | Telegram setting `notify_crons` off, or the job's notify policy is `never` |

Never call `getUpdates` yourself against the configured bot: it would steal updates from the gateway.
