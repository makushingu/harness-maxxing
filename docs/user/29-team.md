---
section: Using Harness Maxxing
---
# Team

Chat with the people you work with - a colleague, a partner, a client who also uses Harness Maxxing - right next
to your sessions: direct messages and groups, files, polls, and a summary by Claude when you want one.

Turn it on in **Settings -> Features -> Team**. The **Team** entry appears in the sidebar; the small icon next to it
(on hover) opens the chats in a panel on the right of any page, with the number of unread messages. Drag the panel's
left edge to make it wider (double-click: normal width).

The list has two tabs: **Chats** and **Friends** (your contacts, who is online, pending requests, **Add a friend**).

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
ready. **Remove** a contact in Connections: their server is told and can no longer write to you. To connect
again with someone who is still a contact (a reinstalled server, for example), they remove you first, then use a
new invitation: an invitation never replaces an existing contact.

## Chats and groups

- **New chat** (the **+** of the list): pick one friend for a private chat, several for a group. A group
  has no host: each member's server sends straight to the others, so it keeps working when its creator is offline.
  Members of a group who are not your contacts can still talk in the group; their name shows **not a contact**:
  the group's creator vouches for who they are (it hands out the keys), so it could also write in their name.
- **Files**: the paperclip, drag and drop or paste. Up to the upload limit of your server (2 GB by default). A file
  stays on the sender's server until the others download it.
- **Polls**: the poll button of the message box. Round options = one answer; tick **Several answers allowed** for square
  options. Click again to take your vote back.
- **Reactions**, **Reply** on hover of a message. Your own messages can be **edited** or **deleted** for everyone
  (Up arrow in an empty message box edits your last one).
- **Seen** under your last message, **writing…** while someone types, and each friend's presence (online, or seen
  5 min ago): it shows while their Harness is open in a browser.
- **Notifications** for new messages of the chats you are not looking at: Settings -> Notifications -> Team
  messages. **Mute** a chat (its menu) to silence it.
- **Groups**: their creator renames them, adds friends and removes members; anyone can **leave** (final). The
  thread says who joined, was removed or left.
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

## From a session to a friend

Right click (a long press on a phone) on any message of a session, yours or Claude's: **Send to** lists your friends
and groups. The text is shown first and you can edit it; a private chat is created if you had none. Only the text
goes, not the message's attachments.
