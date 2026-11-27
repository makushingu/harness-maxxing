---
section: Reference
---
# Security

Harness Maxxing gives a browser (and a Telegram chat) control over Claude Code on your server.
Read this page once.

## What Claude may do on the server (permission mode)

**A new installation works in the sandbox by default.** A session works without asking inside
its topic folder; its commands cannot write elsewhere nor read the server's keys, the SSH keys or the rest of the
home folder; what has to leave the topic (installing a package, a service, another folder) arrives as an Allow /
Deny request, and **Full access** on that request gives the topic full rights for good. The topics of the `system`
project keep full access: that is where Harness repairs, updates and changes itself. When the sandbox cannot start
on a server (no bubblewrap, an AppArmor profile in the way), the installation keeps full access and `maxxing doctor`
says so.

**A server that was installed before this default keeps the mode it had** (full access, unless you changed it): nothing switches by
itself. `maxxing doctor` shows the mode in use; Settings → Claude → Permissions changes the default, a topic's
menu → Permissions changes one topic.

### Full access (bypass mode)

**Sessions, Claude jobs and shell jobs run as root, with full rights on the server.** By default `claude` runs
with `--dangerously-skip-permissions`: Claude can read and change any file (your secrets, SSH keys, other sites'
data), install software, change the firewall, start or stop services and run any command, without asking.
That is what makes unattended work, crons, server administration and phone conversations possible – and why
we recommend **a server dedicated to Harness Maxxing**, with no other critical service or data on it.

**The risks:** a malicious instruction hidden in content Claude reads (a web page, an e-mail, a document, a
forwarded message, a webhook) can make it act on the whole server; so can a mistake. Anyone who gets into the UI
or your Telegram chat gets the same power. Nothing on the server (deny rules, "Protect the secrets") stops
code that runs as root on purpose.

For work that reads outside text by itself (webhooks, e-mails, orders), prefer an [agent](agents#safety): outside
text is given as data, it sees only the keys you list, can ask for your OK, and new agents run in Claude Code's
sandbox. In an [agent group](agent-groups), only you write; what one member says is given to the others as data, and
the only extra place a member may write is the group's shared folder (turn off "Members trust each other" for groups
that read outside content: a hand-over then asks for your OK before risky actions).

**What limits it:**
- **Permission modes, per topic and per job** (the real limit): `bypass` (default, no questions), `sandbox`
  (free inside the topic folder, see below), `acceptEdits` (edits files, refuses commands), `ask` (asks you before anything but reading: **Allow** / **Deny** in the
  session, the notifications or Telegram), `default` (refuses edits and commands), `plan` (reads only, proposes a
  plan). Set them for the whole server (Settings -> Claude), a topic (topic menu -> **Permissions**) or a
  scheduled job. Put every topic and job that reads untrusted content in a stricter mode.
- Each session and job runs in its own systemd unit with a memory cap and a few protections that never get in
  the way of administering the server: it cannot set the system clock, change the process personality or use
  realtime scheduling (config `unit_hardening`, on for installations made from 2.0.0-alpha.70, off on older ones). These do not make root less than root.

A stricter mode costs refused actions in web sessions. See [Settings and keys](settings-and-keys).

**The `sandbox` mode** keeps the comfort of full access for the work of one topic, without giving the server
away. Claude asks nothing while it stays in the topic: commands write in the topic folder only (and the separate
copy of a session), cannot read the server's keys, the SSH keys nor the rest of the home folder, and reach any
website. The files that decide what the topic may do (its permission mode, its MCP servers, its agents) cannot be
changed from inside. What has to leave the topic - install a package, restart a service, write in another
folder, most `maxxing` commands - is asked to you first (**Allow** / **Deny**, in the session, the notifications
or Telegram). **Full access** on that request allows it and switches the topic to `bypass` from its next
message: one click for the topics that administer the server. It uses the same sandbox as the agents (bubblewrap;
`maxxing agents sandbox-setup` installs what is missing). Limits to know: the keys of Settings -> Keys are still
given to the session as environment variables, so a script of the topic can use them - limit a key to the projects
or topics that need it (**Topics** in the key's dialog, see [Settings and keys](settings-and-keys)) and the others never
receive it; and a scheduled job in this
mode waits for an answer nobody may give, so choose it for jobs that stay inside their topic.

Treat anything you paste into a session (documents, web pages, emails) as instructions Claude may
follow: do not feed it untrusted content with the bypass mode on. Topics and jobs that read the web, e-mails or
forwarded messages are the ones to put in a stricter mode.

**Protect the secrets** (Settings -> Claude, on by default) makes Claude's tools refuse to read or edit
`secrets.json` and `~/.ssh` in every mode. It is a speed bump, not a wall: a script written on purpose to open the
file still can.

## Who can reach the UI

- The server listens only on `127.0.0.1` (behind Caddy) or on the Tailscale IP – **never** on
  `0.0.0.0` or a public address. `maxxing doctor` fails if it does.
- **Domain mode**: HTTPS only (Caddy, Let's Encrypt), with HSTS, `X-Frame-Options: SAMEORIGIN`,
  `nosniff` and a strict referrer policy (the server sends the same headers itself, whatever the mode).
- **Tailscale mode**: only devices of your tailnet can connect.
- **Local mode**: only through an SSH tunnel.

## The server itself

The installer hardens the server (step "Server security"; `bash /opt/claude-maxxing/install.sh
--secure` re-applies it on an existing server):

- **Firewall (ufw)**: everything incoming is refused except SSH (the ports sshd really listens on
  are detected first, so you are never locked out), 80/443 in domain mode and the `tailscale0`
  interface in Tailscale mode. This matters here: if Claude starts a dev server or a quick file
  server on `0.0.0.0`, it stays private. To publish something on purpose: `ufw allow 3000/tcp`.
  Skip the firewall with `FIREWALL=0` (e.g. your provider's firewall already does the job).
  On a server already in use the default (`FIREWALL=auto`) is careful: the firewall is not turned on
  when other services are reachable from outside or Docker runs, and an active ufw keeps its rules
  (only the needed ports are added). `FIREWALL=1` forces the strict setup.
- **SSH by key only**: password logins (and keyboard-interactive) are turned off with
  `/etc/ssh/sshd_config.d/01-harness-maxxing.conf`; `PermitRootLogin yes` becomes `prohibit-password` (a stricter
  value is kept). Built so you cannot be locked out: by default it is done only when the session running the
  installer is proven, from the SSH log, to be a key login (an interactive install asks first); the new
  configuration is checked with `sshd -t` and removed if it does not validate or does not take effect; open
  sessions stay connected. Otherwise password logins stay on and the installer says why
  (`SSH_HARDEN=1 bash /opt/claude-maxxing/install.sh --secure` once you log in with a key; `SSH_HARDEN=0` never
  touches SSH). To undo: `rm /etc/ssh/sshd_config.d/01-harness-maxxing.conf && systemctl reload ssh`.
- **fail2ban**: an IP is banned for 1 hour after 5 failed SSH logins in 10 minutes
  (`fail2ban-client status sshd`; settings in `/etc/fail2ban/jail.d/harness-maxxing.local`).
- **Automatic security updates** (`unattended-upgrades`, daily).
- **Signed versions** (optional for now): a published version can be signed by its publishers (one key each),
  and a server can refuse any version without that signature, checked with the keys of the version it already
  runs, before anything changes: someone who took over the GitHub repository cannot push code to it. How to turn
  it on: [CLI reference](cli-reference), *Signed versions*.
- **Downloads**: nothing fetched from a third party runs before it is checked, and no script from the internet is
  piped into a shell. Every external component (uv, Python, Node.js, Claude Code, Scrapling and each Python package
  it needs, Chromium, Remotion, the speech models, Garage) has a pinned version and sha256 in
  `server/maxxing/deps.toml`, shipped with each signed release; Caddy's repository key must have the expected
  fingerprint and its apt source is written by the installer. A download that does not match installs nothing.
  `maxxing deps verify` re-checks the installed binaries and that no file of them can be replaced by another user
  (the doctor does it too); `maxxing deps check` looks the versions up in the osv.dev vulnerability database, and a
  weekly job notifies you when one is affected. Temporary files never go to the shared `/tmp`.
- **Memory**: the web service has its own memory limit (60 % of the RAM), sessions and scheduled jobs run in their
  own capped units, and oversized requests are refused before they are read.

- **Service sandbox**: the `claude-maxxing` service runs with systemd protections that cannot get
  in the way of the product (no new privileges, read-only kernel settings, no kernel modules or kernel
  log, read-only cgroups, no set-uid files, a cap on processes). They live in
  `/etc/systemd/system/claude-maxxing.service.d/10-hardening.conf`. Installs older than 2.0.0a32 get
  it with `maxxing harden` (restarts the service; if it does not come back, the change is undone);
  `maxxing harden --undo` removes it. The service still runs as root: Claude sessions run in their own
  units and are not limited by it (they get the lighter protections described at the top of this page).

Recommended on top: SSH keys instead of passwords (`PasswordAuthentication no` once your key works).
`maxxing doctor` warns if any of the three is missing.

## Sign-in

- **Setup token**: the first visit requires the one-time link printed by the installer
  (`maxxing setup-link`), so whoever finds the URL first cannot claim your instance. It is deleted
  once the password is set.
- **Password**: at least 12 characters for a new password (an older, shorter one still signs in), stored as a
  scrypt hash. Change it in Settings -> Security or with `maxxing password` on the server; changing it signs every
  browser out. Wrong current passwords in that form are throttled like sign-ins.
- **Session cookie**: signed, `HttpOnly`, `SameSite=Strict`, `Secure` over HTTPS, valid 30 days.
  **Sign out** revokes that browser's cookie on the server too (a copied cookie stops working); your other
  browsers stay signed in. Live views already open in a signed-out browser (conversations, the dashboard's updates)
  stop within 15 seconds; its open terminals and its live views of the Harness Browser and of your devices are
  closed at once (within 5 seconds when the change comes from a `maxxing` command). To sign out **every** browser,
  change the password (Settings, or `maxxing password`): the browser you change it from stays signed in.
- **Signed-in devices** (Settings -> Security): the list of the browsers signed in - browser and system, the
  address the server saw, when it was last seen (refreshed about once a minute) - with **Disconnect** on each line
  and **Disconnect all the others**. A disconnected browser is back on the sign-in page at its next click. Browsers
  that signed in before this list existed share one line, *Browsers signed in before this version*: they stay
  signed in after the update, until *Disconnect all the others*, a password change, or the 30 days of their cookie.
- **Two-step sign-in** (optional, Settings -> Security): after the right password, a browser that is not trusted
  needs a second step. Two methods, each with its own switch, usable together (either one then signs you in):
  - **Telegram** (the default): a request in the *Alerts* thread with Allow / Deny buttons and a 6-digit code - see
    [Telegram](09-telegram.md).
  - **Authenticator app** (TOTP: Aegis, 2FAS, Google Authenticator, a password manager...): turn the switch on, type
    your current password, scan the QR code (or type the key shown), then enter the 6-digit code of the app - the
    app only becomes a sign-in step once that code is accepted, and the key is never shown again. A code works
    for its 30 seconds and the 30 before and after, and only once. It needs no Telegram: with both on, the sign-in
    page takes the Telegram code or the app code in the same field, and still works when Telegram is down.
  - **Recovery codes**: 10 one-time codes, shown once when the app is turned on (or with **New codes**, which asks
    for the password and ends the previous ones; available with Telegram alone too). Each replaces a second-step
    code once; only their hash is stored. Signing in with one is reported in Alerts with the number left.
  - Wrong codes are delayed and blocked like wrong passwords (8 in 15 minutes per address). Turning the app off
    asks for the current password **and** an app or recovery code.
  - Locked out (phone lost, no recovery code): on the server, `maxxing 2fa off` turns both methods off and drops
    the recovery codes - the password alone signs in again. `maxxing 2fa status` shows what is on.
- **CSRF**: every change request must carry the `X-Maxxing: 1` header, which another website cannot
  send.
- **Request size**: a request from a browser that is not signed in is refused before the server reads it
  (the sign-in form itself takes at most 64 kB), and signed-in requests are capped too (1 MB, more for the file
  editor, messages to Claude and uploads), so nobody can fill the server's memory with a huge request. Live
  views (open conversations, dashboard updates) are capped as well: 24 per browser, 96 in total; past that, a view
  retries a few seconds later.
- **Throttling**: after a wrong password the next attempts are delayed (1, 2, 4, 8 s); after 8 wrong
  passwords that address is blocked for 15 minutes - even the right password is refused until then.
  If many addresses fail at once (more than 30 wrong passwords in 15 minutes), the server checks at
  most one password every 5 seconds from addresses that already failed and one every 5 seconds from new ones:
  retry after a few seconds. A browser trusted by two-step sign-in, and an address that signed in during the
  last 30 days (since the server started), are never held back by this.
- **Alerts**: with Telegram linked, every sign-in and repeated wrong passwords are reported in the
  *Alerts* thread.

## Telegram

The gateway answers only the chat linked with the one-time code, and only the Telegram account that opened
the link. A chat linked without its owner (by hand, or by a very old version) answers nobody - `maxxing doctor`
warns, link it again from Settings -> Telegram. Anyone with access to that Telegram account can drive Claude:
protect it (2-step verification).

## What is stored where

| Path | Content | Protection |
|---|---|---|
| `/var/lib/claude-maxxing/config.json` | settings (no secrets) | directory mode 700 |
| `/var/lib/claude-maxxing/secrets.json` (`secrets.json.cred` once sealed, below) | password hash, cookie key, Claude token/API key, Telegram token, GitHub tokens, your Keys | mode 600; never returned by the API except on explicit Reveal; encrypted on disk if you run `maxxing keys encrypt` |
| `/var/lib/claude-maxxing/secret-files/` | your Keys that are files (keystores, service-account JSON, certificates) | directory mode 700, files mode 600; never returned by the API, never in the backup |
| `/var/lib/claude-maxxing/sessions/` | session metadata and logs | mode 700 directory |
| `/var/lib/claude-maxxing/signins.json` | the signed-in browsers (browser, address, last seen); the authenticator key and the recovery-code hashes are in `secrets.json` | mode 600 |
| `/root/maxxing/` | your workspace (memory, projects, tasks, extensions) | backed up (whitelist) |
| `~/.claude/` | Claude Code settings, CLI credentials, transcripts | Claude Code's own files |
| `/opt/claude-maxxing/` | the code (git clone) and its Python environment | replaced by updates |

Secrets never go to the backup: the backup copies a whitelist, refuses files like `.env` or keys,
scans for secret formats and refuses to push to a public repository.

### Secrets sealed on disk (optional)

By default `secrets.json` is a clear file that only root reads (mode 600). `maxxing keys encrypt` (as root) seals it:
the content goes to `secrets.json.cred`, encrypted by `systemd-creds` (systemd 250 or later) with a key that belongs
to this machine - the host key `/var/lib/systemd/credential.secret`, plus the TPM chip when the server has one and
systemd uses it. The sealed file is decrypted back and compared before the clear one is removed; if anything fails,
nothing changes. From then on the server decrypts it when it reads its secrets and seals it again at every change.
Nothing is on by default, new installations included.

What it protects:

- **a copy of the file alone** - a backup of the state folder taken elsewhere, a file sent by mistake, a snapshot of
  `/var/lib/claude-maxxing`: without this machine's key it cannot be opened;
- **a copy of the whole disk, only when a TPM is used**: the chip does not leave the machine. Without a TPM (most
  VPS), the host key is a file on the same disk, so a full disk image or a full-server backup holds both the sealed
  file and its key.

What it does not protect:

- **someone who is already root on the server** (or a session with full access): the key is on the machine so that
  the server restarts alone, and `maxxing keys get NAME` answers root. Permission modes and the sandbox are what
  limit a session, not this;
- the Keys that are files (`secret-files/`), the Claude CLI's own credentials (`~/.claude/`) and the values given
  to sessions and jobs as environment variables: unchanged.

What changes for you:

- a script or a tool that opens `secrets.json` itself stops working (the file is gone): read a key with
  `maxxing keys get NAME`, or from the environment of sessions and jobs;
- **moving the state folder to another server: run `maxxing keys decrypt` first.** A sealed file cannot be opened
  anywhere else; a reinstalled system (new host key) or a replaced TPM cannot open it either. Keep your own copy of
  what matters (the vault of a password manager) as for any secret;
- if the sealed file cannot be decrypted, the server refuses to read or write its secrets (sign-in fails, nothing is
  overwritten) and `maxxing doctor` shows it as a failure, rather than starting with an empty store;
- the sealed secrets are limited to 1 MiB (a limit of `systemd-creds`; a usual `secrets.json` is a few kilobytes).

Going back: `maxxing keys decrypt` writes the clear `secrets.json` (mode 600) again and removes the sealed file.
`maxxing doctor` says which form is in use (`secrets stored in clear (0600)` / `secrets sealed on disk`).

## Files

The Files page and API only reach the *files root* (Settings -> System). Deleted files go to the
trash.

- Files open in the browser can never run scripts with your session: anything other than images,
  audio, video and PDF is shown in a sandbox.
- An **HTML page preview** link (valid 2 hours, ended by signing out - of that browser or of all of them) reaches
  the page's folder - only pages and their static assets (styles, scripts, pictures, fonts, audio, video), never
  notes, data or documents (`.md`, `.json`, `.txt`, `.csv`, `.pdf`...), code or settings (`.py`, `.env`, `.yaml`...),
  hidden files or folders (`.ssh`, `.claude`...); from a topic's `attachments/`, only pictures and videos. A page saved
  directly in the files root, the home folder, the workspace root, `projects/`, a project or its `topics/` folder
  (or in a hidden folder) is shown alone: its images and styles next to it do not load - move it into its own
  folder.
- **Ask Harness** on a notification opens a session in **plan mode**: Claude reads and explains, it changes nothing
  until you approve a plan - a webhook's text cannot make it act.
- **Webhooks** refuse unknown links before reading anything, and any request over 1 MB.
- **Import** never brings Claude Code settings, hooks, sub-agents or commands (`.claude/settings.json`,
  `.mcp.json`, `.claude/agents/`, `.claude/commands/`) from the archive; skills and notes are imported.

## Extensions, skills and themes from other people

A community extension's `api.py` runs inside the Harness server with its rights, and a skill is a set of instructions
(and sometimes scripts) Claude follows: installing one is trusting its author. Before anything is copied,
`maxxing community check <folder or zip>` reads the package without running it and lists the code that would run on
the server, the hosts it contacts, the keys and secret files it reads, the processes and downloads it starts and the
paths outside its folder, with file and line. `maxxing community install` shows that report, asks (twice for
findings marked `danger`), installs only the content whose sha256 was shown, and keeps the hash, the source and the
date (`maxxing community list`, Settings). It is a reading aid, not a verdict: it never says a package is harmless,
and it does not replace reading the code or knowing who wrote it. Details:
[13-page-extensions.md](13-page-extensions.md#what-a-package-does-before-it-is-installed).

## Anthropic account

Harness Maxxing runs the official Claude Code CLI with **your** account or API key on **your**
server; it never shares or proxies credentials. Make sure your use complies with Anthropic's terms
for your plan.

## Checklist

- [ ] Dedicated server; SSH by key only, firewall, fail2ban and automatic security updates on (set by the installer).
- [ ] Domain (HTTPS) or Tailscale access; nothing reachable from the Internet but SSH, 80 and 443.
- [ ] SSH with a key (password login disabled).
- [ ] Strong UI password; Telegram account protected.
- [ ] Memory backup to a private repository.
- [ ] `maxxing doctor` all green.
