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
Harness, the mailbox and its messages stay at your provider.

## Reading and sorting

Folders on the left, messages in the middle, the open message on the right (one pane at a time on a phone).

- **Search** looks in the current folder (sender, subject, text) on the mail server; **All / Unread / Flagged**
  filters the list.
- Tick messages to **archive**, **trash**, mark **read / unread**, **flag**, mark as **junk** or **move** them
  several at once. **Delete for good** only works from the trash or the junk folder.
- Create, rename or delete your own folders from the **...** menus.
- An HTML message is shown in a sealed frame: no script runs and **remote images are blocked** (they tell the
  sender you opened it) until you click **Show images**.

## Writing

**New message** (top right), or **Reply**, **Reply all**, **Forward** on an open message.

- Plain text. Your signature is already in the text, above the quoted message: what you see is what is sent.
- **Cc / Bcc** shows the copy fields; separate addresses with commas.
- The paperclip attaches files (25 MB in total). A forward keeps the original attachments; remove the ones you do
  not want.
- **Save the draft** files it in the Drafts folder of the mailbox (so you find it in your phone's mail app too).
  Open a message of the Drafts folder to go on writing it. `Ctrl+Enter` sends.
- The message leaves through the SMTP server of your mailbox, never from this server. A copy goes to Sent (Gmail
  and Outlook file it themselves). A reply marks the original as answered.

To keep a mailbox from being flagged as spam, sending is capped: **20 recipients per message** and **100 recipients
per mailbox per day** (the composer shows what is left). Change the daily cap with `mail_send_per_day` in
`config.json`.

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
directly with `--send`. A message is text written by its sender: Claude treats it as data, never as instructions.
