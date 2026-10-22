---
section: Reference
---
# Security

Harness Maxxing gives a browser (and a Telegram chat) control over Claude Code on your server.
Read this page once.

## Claude runs with full permissions (bypass mode)

**Sessions, Claude jobs and shell jobs run as root, with full rights on the server.** By default `claude` runs
with `--dangerously-skip-permissions`: Claude can read and change any file (your secrets, SSH keys, other sites'
data), install software, change the firewall, start or stop services and run any command, without asking.
That is what makes unattended work, crons, server administration and phone conversations possible – and why
we recommend **a server dedicated to Harness Maxxing**, with no other critical service or data on it.

**The risks:** a malicious instruction hidden in content Claude reads (a web page, an e-mail, a document, a
forwarded message, a webhook) can make it act on the whole server; so can a mistake. Anyone who gets into the UI
or your Telegram chat gets the same power. Nothing on the server (deny rules, "Protect the secrets") stops
code that runs as root on purpose.

**What limits it:**
- **Permission modes, per topic and per job** (the real limit): `bypass` (default, no questions), `acceptEdits`
  (edits files, asks before commands), `default` (asks before edits and commands), `plan` (reads only, proposes a
  plan). Set them for the whole server (Settings -> Claude), a topic (topic menu -> **Permissions**) or a
  scheduled job. Put every topic and job that reads untrusted content in a stricter mode.
- Each session and job runs in its own systemd unit with a memory cap and a few protections that never get in
  the way of administering the server: it cannot set the system clock, change the process personality or use
  realtime scheduling (config `unit_hardening`, on for installations made from 2.0.0-alpha.70, off on older ones). These do not make root less than root.

A stricter mode costs refused actions in web sessions. See [Settings and keys](settings-and-keys).

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
  stop within 15 seconds. To sign out **every** browser, change the password (Settings, or `maxxing password`).
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
  most one password every 5 seconds for everyone: retry after a few seconds.
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
| `/var/lib/claude-maxxing/secrets.json` | password hash, cookie key, Claude token/API key, Telegram token, GitHub tokens, your Keys | mode 600; never returned by the API except on explicit Reveal |
| `/var/lib/claude-maxxing/sessions/` | session metadata and logs | mode 700 directory |
| `/root/maxxing/` | your workspace (memory, projects, tasks, extensions) | backed up (whitelist) |
| `~/.claude/` | Claude Code settings, CLI credentials, transcripts | Claude Code's own files |
| `/opt/claude-maxxing/` | the code (git clone) and its Python environment | replaced by updates |

Secrets never go to the backup: the backup copies a whitelist, refuses files like `.env` or keys,
scans for secret formats and refuses to push to a public repository.

## Files

The Files page and API only reach the *files root* (Settings -> General). Deleted files go to the
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
- **Import** never brings Claude Code settings or hooks (`.claude/settings.json`, `.mcp.json`) from
  the archive; skills and notes are imported.

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
