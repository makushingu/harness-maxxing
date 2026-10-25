---
section: Using Harness Maxxing
---
# Team

Chat with the people you work with - a colleague, a partner, a client who also uses Harness Maxxing - right next
to your sessions: direct messages and groups, files, polls, and a summary by Claude when you want one.

Turn it on in **Settings -> Features -> Team**. The **Team** entry appears in the sidebar; the small icon next to it
(on hover) opens the chats in a panel on the right of any page, with the number of unread messages.

## Connecting with someone

Every Harness talks straight to the other one, server to server: no Harness Maxxing server in between, ours
included.

1. **Team -> Connections -> Create an invitation**: a link `https://ui.example.com#...`, valid 15 minutes, usable
   once. Send it to the person through a channel you trust (a message, a call...).
2. They paste it in **Connections -> Join** on their Harness and click **Send the request**.
3. You see their request with a fingerprint like `7F3A-91C2`; they see the same one. Check it with them (by
   phone or another app), then **Accept**.

> **Connect only with people you trust.** A contact can send you messages and files, and see your name and avatar.
> Nothing they write ever reaches Claude by itself, but read what you forward to a session.

Both servers need a **public address** (Harness installed with a domain, `https://`). Team does not work through
Tailscale nor on a local network: the other server could not reach yours. Connections shows why when it is not
ready. **Remove** a contact in Connections: their server is told and can no longer write to you.

## Chats and groups

- **New chat** (the **+** of the list): a direct message with a contact, or a group with several of them. A group
  has no host: each member's server sends straight to the others, so it keeps working when its creator is offline.
  Members of a group who are not your contacts can still talk in the group.
- **Files**: the paperclip, drag and drop or paste. Up to the upload limit of your server (2 GB by default). A file
  stays on the sender's server until the others download it.
- **Polls**: the poll button of the message box. Round options = one answer; tick **Several answers allowed** for square
  options. Click again to take your vote back.
- **Reactions** on hover of a message.
- A small clock on a message: not delivered yet to someone (their server is off); Harness retries for 7 days.

## Summarize

**Summarize** (top of a chat) lets you pick messages: click them (Shift = a range) or use **Last hour**, **Last 2
hours**, **Last 24 hours**, **Since the last summary** or **Everything**. Claude writes a short summary (decisions, to do,
open questions) in the language of the chat; it is posted in the chat for everyone. One call to Claude without any
tool, about a cent.

## To a session

On hover of any message or summary, **To a session** sends it to one of your sessions or starts a new session in
the topic you choose. The text is shown first and you can edit it; the message's files are attached. Nothing is
ever sent to a session without that click.
