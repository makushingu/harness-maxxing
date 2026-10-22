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
- Sync = automatic (a few seconds after a session change + every 10 minutes); "Sync threads" in
  Settings forces it. No cron needed.

## Configure (prefer the UI wizard: Settings -> Telegram)
1. In Telegram, open **@BotFather** -> `/newbot` -> choose a name and a username ending in `bot`
   -> copy the token (`123456:ABC…`). Enable topics for the bot's private chat in BotFather
   (Bot Settings -> threads / topics) so each open session gets its own thread.
2. Settings -> Telegram -> paste the token (the server calls `getMe` to check it).
3. Click **Link** -> open the `t.me/<bot>?start=<code>` link on the phone -> press Start. Only this
   chat (and its user) will be accepted from then on.
4. Click **Sync threads** (afterwards automatic).
5. Settings: cron reports on/off, sign-in alerts on/off, reply mode `final` (only the final answer)
   or `progress` (tool steps too). **Send test**.

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
maxxing telegram status        # configured, bot, chat, threads, last_error
maxxing telegram test          # sends a test message
journalctl -u claude-maxxing -n 100 --no-pager | grep -i telegram
```
| Problem | Fix |
|---|---|
| `Unauthorized` / 401 | token revoked or mistyped -> new token from BotFather, paste it again |
| `Conflict: terminated by other getUpdates` | another program polls the same bot (old bot, second server) -> stop it or create a new bot |
| Messages ignored | sent from another chat/user than the linked one -> re-link from Settings |
| No threads / everything in one chat | topics not enabled for the bot in BotFather, or threads not synced -> enable, then "Sync threads" |
| A session's thread disappeared | the session was archived (`/close`, deleted thread) or is idle longer than `thread_days`; un-archive it or write in it from the web UI |
| "Crons" or "Alerts" thread deleted | "Sync threads" recreates it |
| No cron reports | Telegram setting `notify_crons` off, or the job's notify policy is `never` |

Never call `getUpdates` yourself against the configured bot: it would steal updates from the gateway.
