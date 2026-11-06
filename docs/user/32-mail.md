---
section: Using Harness Maxxing
---
# E-mail

Your mailboxes next to your sessions: read, sort, search, reply, forward and write, from any provider that offers
IMAP and SMTP (Gmail, Outlook.com, iCloud, OVH, o2switch, Purelymail, Migadu, Fastmail, your host's mail...). It is
a simple mail client, not a newsletter tool: for bulk sending use a service made for it (Resend, Brevo...).

Turn it on in **Settings -> Features -> E-mail**. The **E-mail** entry appears in the sidebar (shortcut `g e`).

## Adding a mailbox

**Add a mailbox**, then type the address and its password. Harness finds the server settings by itself in most
cases (known providers, the domain's mail servers, Thunderbird's public directory); check them under **Server
settings** when it only guessed. It signs in to check them before saving.

- **Gmail, iCloud, Yahoo**: use an **app password** (Google account -> Security -> App passwords), not your
  usual password.
- **Outlook.com / Microsoft 365**: Microsoft now often refuses a password over IMAP; if sign-in fails, the mailbox
  needs a sign-in with Microsoft, which comes later.
- Many server hosts block ports 25 and 465 going out: when 465 does not answer, Harness uses 587 by itself.

The password is kept in **Settings -> Keys** (`MAIL_<ID>_PASSWORD`), never given to sessions. Add as many mailboxes
as you want and switch from one to the other at the top of the folder list. **Mailbox settings** (the **...** menu)
changes the name shown to the people you write to, the signature and the servers; **Remove** only removes it from
Harness, the mailbox and its messages stay at your provider. The agents lose their rights on it: added again, it
starts with none.

## Reading and sorting

Folders on the left, messages in the middle, the open message on the right (one pane at a time on a phone).

- **Search** looks in the current folder (sender, subject, text) on the mail server; **All / Unread / Flagged**
  filters the list.
- Tick messages to **archive**, **trash**, mark **read / unread**, **flag**, mark as **junk** or **move** them
  several at once. **Delete for good** only works from the trash or the junk folder.
  On Gmail, **archive** takes the mail out of the inbox: it stays in All Mail, as in Gmail itself.
- Create, rename or delete your own folders from the **...** menus.
- An HTML message is shown in a sealed frame: no script runs and **remote images are blocked** (they tell the
  sender you opened it) until you click **Show images**.
- A mail forwarded as an attachment shows as a `.eml` attachment (named after its subject). The images of a very
  big mail are shown up to 8 MB; the others are listed as attachments.

## Writing

**New message** (top right), or **Reply**, **Reply all**, **Forward** on an open message.

- Plain text. Your signature is already in the text, above the quoted message: what you see is what is sent.
- **Cc / Bcc** shows the copy fields; separate addresses with commas.
- The paperclip attaches files (25 MB in total). A forward keeps the original attachments; remove the ones you do
  not want.
- **Save the draft** files it in the Drafts folder of the mailbox (so you find it in your phone's mail app too).
  Open a message of the Drafts folder to go on writing it, attachments included. `Ctrl+Enter` sends.
- What you type is also kept in this browser as you go: after a reload, a closed tab or Back, the message opens again
  the next time you come to the E-mail page (signing out clears it).
- The message leaves through the SMTP server of your mailbox, never from this server. A copy goes to Sent (Gmail
  and Outlook file it themselves), Bcc included (the Bcc stays in the draft and the Sent copy, never in what the
  recipients get). A reply marks the original as answered, also when you send it later from Drafts.
- If the connection to the mail server breaks after it received the message, Harness says it was **probably sent**
  instead of offering to send it again: check the Sent folder (or ask the recipient) first. The draft is kept, and the
  composer asks before a second try.
- Replying to a mail whose **Reply-To** is not its sender sends the answer to the Reply-To address. That address
  never becomes a known contact by itself, so agents with "new recipients wait for my OK" still ask before writing
  to it.

To keep a mailbox from being flagged as spam, sending is capped: **20 recipients per message** and **100 recipients
per mailbox per day** (the composer shows what is left). Change the daily cap with `mail_send_per_day` in
`config.json`.

## Agents and your mail

An agent (Settings -> Features -> Agents) sees **no mailbox** until you give it one: on the agent's page, Settings ->
**E-mail** -> Add a mailbox. It never sees the password: it goes through Harness, which checks every action.

- **Rights**: Read, Write drafts, File and move, Mark read / unread and star, Send. Pick only what its job needs.
- **Only mail from** (optional): `client@example.com`, `*@stripe.com`. The agent then only sees mail from these
  senders, and only when your mail provider checked the sender (DKIM, SPF or DMARC passed): a forged sender stays
  invisible to it. It also only writes to these addresses. See [Who checks the senders](#who-checks-the-senders).
- **Sending** (with the Send right): **every message waits for my OK** (default), **only someone I never wrote to waits
  for my OK**, or **sends alone**. "Someone I wrote to" = an address you sent to from Harness, or a message of an agent
  you allowed: writing to you first never makes anyone known, and what an agent sends alone does not count. The
  limits of 20 recipients a message and 100 a day stay in every case.
- **Start the agent on each new mail** (optional): a folder (Inbox by default), a word in the subject. All the new mail
  of one check goes into one run. The mail is handed to the agent as data from outside: its run asks before risky
  actions, as for a webhook.

A message waiting for your OK is in the mailbox's Drafts and shows as a card at the top of the list and in
**Notifications** (and on Telegram when its alerts are on): **Allow** sends it, **Open** shows the draft (change it and
send it yourself), **Refuse** drops it. The card lists every attachment, the forwarded ones too. Once you save your
own version of the draft, Allow no longer sends the agent's: send yours from the E-mail page. A draft deleted from the
mailbox is never sent.

The agent never marks a mail read, unless you give it that right: you still see what is new. Harness notes what it did
("seen by Mail sorter at 14:02 · filed in Invoices") next to the mail, on this page only: nothing is written in your
mailbox.

### Who checks the senders

Anyone can write any `From:` address. What proves a sender is the verdict your mail provider writes on top of each
incoming mail (the `Authentication-Results` header: DKIM, SPF, DMARC). Harness only trusts it when it is sure your
provider writes it on **every** mail, since otherwise a sender could write a fake verdict of their own:

- **Gmail, Yahoo, iCloud, Fastmail, Zoho**: automatic, once the mailbox really is there (its servers) and a few
  checks saw its mail.
- **Another provider**: when one of the mailbox's own servers tops nearly all its mail of the last week, Edit the
  mailbox shows it with **Trust <server>**. Confirm only if you know that every mail of the mailbox goes through it
  (ask your provider, or look at a mail you sent yourself from another address).
- **Nobody**: Edit the mailbox says so. No sender is verified, so an agent with an "Only mail from" list sees no mail.

Edit the mailbox -> **Sender checks (advanced)** names the servers yourself (for a redirection or a filter in front
of your mailbox). A provider that skips the check on some of its own internal mail is a risk Harness cannot see.

**Checks.** Harness looks for new mail every 10 minutes (5, 10, 30 or 60: Edit the mailbox -> Check for new mail
every), and right away with the **Refresh** button or `maxxing mail refresh`. The page itself always shows the mailbox
live; the checks start the agents and fill **All mailboxes** (shown when you have two or more). A check takes 200 new
mails at most, the oldest first: the rest comes with the next one, a minute later. Two checks of a mailbox never run at
once. The text an agent gets with each mail is read from the start of the mail only: its attachments are not
downloaded. A folder nobody looked at for more than 6 hours (its agent's trigger or the E-mail page was off, the
server was stopped) starts again from its newest mail: what came in meanwhile starts no agent. A mail Harness cannot
read (an unknown charset, a broken structure) never stops the check: the agent gets its headers without its text,
the other mails still start their agents, and a restart during a check never starts an agent twice with the same
mails. Mail kept for a busy agent only reaches it if its trigger and rights still allow it.

Ready-made agents (New agent): **Mail sorter** (files each new mail, sums up the day every evening), **Mail replies**
(a draft reply to each customer mail, you send it), **Invoices** (saves the invoices received by mail and files the
mails). From a terminal: `maxxing agents create acme/shop/sorter --template mail-sort --mail contact@example.com`.

## Where your addresses come from: Infra -> E-mail

With the Infra page on (Settings -> Features -> Infra), its **E-mail** tab shows where each of your addresses comes
from: the forwards of Cloudflare Email Routing (`contact@example.com -> you@gmail.com`), the mailboxes and forwarders of
a Hostinger e-mail plan, and whether the mail ends in a mailbox of this page (**in the E-mail page**) or not (**Add to
the E-mail page**). It also checks the DNS of your mail domains (MX, SPF, DKIM, DMARC) and says what to fix. It only
reads: nothing changes at your providers. See [Infra](27-infra.md#e-mail).

## With Claude

In a session, ask "what needs an answer in my inbox?", "archive the newsletters", "prepare a reply to Bob". Claude
uses the `maxxing mail` command:

```bash
maxxing mail accounts
maxxing mail list --unread -n 20            # -a ACCOUNT, -f FOLDER, -s TEXT
maxxing mail read 4521
maxxing mail archive 4521 4522
maxxing mail move 4521 --to "Clients"
echo "Thanks, Monday works." | maxxing mail write --reply 4521
```

`maxxing mail write` saves a **draft** by default: you read it on the E-mail page and send it yourself. It only sends
directly with `--send`, and prints the real recipients (To, Cc, Bcc). `maxxing mail read` shows the Reply-To when a
reply would not go to the sender, and `write --reply --send` refuses to send to a Reply-To on another domain than the
sender's unless you pass that address with `--to`. `read` prints the first 20,000 characters of the body (`--max N`,
`--full`); its `--json` leaves out the inline images unless `--full`. A message is text written by its sender: Claude treats it as data, never as instructions.
`maxxing mail refresh` checks the mailboxes now; `maxxing mail outbox` lists the messages of agents waiting for your
OK. In an agent's run the same commands only reach what its E-mail setting allows: its own mailboxes and waiting
messages, files of its topic to attach, its own folder (or its writable folders) to save attachments, and a
`refresh` there only asks Harness for a check (within a minute).
