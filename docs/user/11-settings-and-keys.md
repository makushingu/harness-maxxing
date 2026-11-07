---
section: Settings
---
# Settings and keys

Everything is configurable from **Settings**; no file editing is needed.

| Section | What you find |
|---|---|
| **General** | theme (dark/light), accent color (the logo takes it too), density, **layout** of this device (*Auto*: the touch layout on phones and tablets, the sidebar on computers; *Touch*; *Desktop* when the screen is wide enough), the first screen of the touch layout (*Last session* or *Dashboard*), background (neutral or tinted with the accent) - the last theme, accent and background you pick also color the sign-in page and any browser that never chose one (new phone, private window), interface font (23, grouped by style: modern, with character, rounded, serif, easy to read, monospace) and code font (11; a font other than the default loads the first time you pick it), language (English/French), time zone, files root, public URL, **App** (install it on this computer or phone, below) |
| **License** | optional **Enterprise key**, only for companies that need one (who does is explained there): record it, see it, remove it - see [License](license) |
| **Support** | Harness Maxxing is free: **Donate** opens the donation page of the website in a new tab (nothing is sent from the app); **Hide the Donate buttons** removes the Donate buttons from What's new, the Feedback window and Settings → License, in every browser - see [License](license#donations) |
| **Features** | every optional feature in one place: HUD mode and "notify me when a session finishes" (this browser), web conversations in Telegram, Claude plan usage widget, the **Tasks**, **Git & GitHub** and **Infra** pages and **Maxxing mode (beta)** of the Sessions page (off by default) and presentation mode by default (for everyone) |
| **Crons** | the scheduled jobs: list, run now, history, editor (see [Crons](crons)); old `/crons` links open it |
| **Notifications** | a notification (and an optional sound) when a Claude session finishes, pulsing unread badges - saved per browser; then the [notifications feed](feed): its Telegram thread, **Server problems in the notifications**, sources and webhooks |
| **Security** | change the password, two-step sign-in with Telegram (see [Telegram](telegram#two-step-sign-in)), sign out |
| **Claude** | authentication (status, token or API key, live test), default model, automatic compaction threshold, compaction when you come back to an idle session, smart resume (a summary written for the message you come back with), short session titles (and whether Claude writes them), automatic Claude Code updates, permission mode |
| **Stats** | Claude plan usage (5-hour window, week) and the plan name (Pro, Max, Ultra): the same figures as the bars at the bottom of the sidebar, read from the last Claude answer; a verified **Ultra** account has no 5-hour limit, so only the week is shown; **Show plan usage** shows them here and adds the dashboard widget (experimental: it may also ask Anthropic directly when no answer came for 10 minutes); tokens per project, topic and session, tokens per day, how fast turns start (Claude Code ready / first answer, median of recent turns) |
| **Memory** | second brain cleaner: line limit per `memory.md`, **Clean now**, size of every memory file - see [Memory](memory) |
| **Telegram** | bot wizard, linking, threads, notification options – see [Telegram](telegram) |
| **Backup** | repository, schedule, whitelist, history, restore – see [Backup](backup) |
| **Keys** | your secrets vault (below) |
| **MCP** | the MCP servers of Claude Code (a service's tools for Claude): every session or one topic, state, **Connect** (sign-in), **Remove** - see [MCP servers](28-mcp.md) |
| **Extensions** | installed widgets and pages, enable/disable, reload – see [Dashboard widgets](dashboard-widgets) |
| **System** | version and **Update** (with the smart update preflight), health, services (start/stop/restart), logs, **What's new** (also shown once after each update; the main new features have a **Show me** button that takes you to them and highlights them) |
| **Updates** | every version of Harness Maxxing, newest first, with a search - the full history of what changed |
| **Docs** | this documentation |

Changing the **time zone** here does not change the server clock: run
`timedatectl set-timezone <Zone> && systemctl restart cron` too, so scheduled jobs follow (see
[Crons](crons)).

## Install the app

Harness Maxxing installs like an app (its own window, an icon in the Dock, the taskbar or the home screen,
full screen on a phone). Two places: **Install app** in the ⊞ menu on a phone, and **Settings -> General -> App**.

- **Chrome, Edge (computer or Android)**: one click when the browser offers it; otherwise the button shows the
  steps (the install icon at the end of the address bar, or the browser menu).
- **Safari on a Mac** (macOS 14 or later): File -> **Add to Dock**.
- **iPhone / iPad**: Safari's Share button -> **Add to Home Screen**.
- **Firefox** cannot install web apps on a computer: use Chrome, Edge or Safari.
- The App card shows a **QR code** of the address: scan it with the phone, sign in, then add it to the home screen.
- Installing needs the **https** address (domain access). Through Tailscale (`http://100.x.y.z:8787`) browsers do
  not offer it.

### On a phone or a tablet

Phones and tablets get the **touch layout** (Settings -> General -> Layout changes it per device): no sidebar, no
bar at the bottom, the conversation fills the screen. Two buttons sit at the top of every screen:
- **☰** (top left) opens your sessions - see [Sessions](04-sessions.md). Its counter shows the unread answers.
- **⊞** (top right) opens everything else, laid out like the sidebar: a search field (the same as ⌘K), every page
  in your sidebar order (and Notifications), the extension pages apart, Feedback and Settings, then the status
  card - server health (tap it for the issues), CPU / RAM / disk (opens Settings -> System), your Claude plan
  (opens Settings -> Stats), presentation mode, the theme, the docs and General settings. A dot on ⊞ means an
  update is waiting or the server needs attention.

On a computer the bottom of the sidebar holds the same status block, with the keyboard shortcuts next to the docs.
The guided tour and the interactive tutorial are in **Settings -> General**; **Sign out** is in **Settings ->
Security**.

Also:
- In the installed app, **swipe from the left edge** to open the sessions, from the right edge to open the menu;
  swipe a drawer back towards its edge to close it.
- Panels that slide up from the bottom close with a **swipe down** (from their handle, their title, or their
  content when it is scrolled to the top), or a tap on the dimmed area above them.
- The microphone and send buttons are bigger; while you type, panels stay above the keyboard.
- The page does not zoom (no pinch, no double tap), like a native app; fields never make the iPhone zoom in.

## Claude authentication

Three ways, best first:
1. **Long-lived token**: run `claude setup-token` on any computer with a browser, paste the token.
2. **API key** from the Anthropic console (billed per use).
3. **CLI login** done on the server (`claude`, then `/login`): detected automatically.

**Test** makes a real one-line call and shows the model and the latency.

Turns start Claude without its update check, telemetry and feature-flag download (faster start, shorter prompt);
`"claude_quiet_start": false` in config.json turns that off.

Claude runs its helper agents in the foreground: you get their result in the same turn (several agents still run
side by side). Claude Code's own habit is to send them to the background, where the turn waits for them to report
back, which is slower; `"background_agents": true` in config.json goes back to it. You can always ask Claude for a
background agent in your message.

## Claude Code updates

**Update Claude Code automatically** (off by default): every 6 hours the server looks for a newer **stable** Claude
Code release (the one Anthropic marks stable: already used for some days, not the very latest). When there is one,
it installs that version itself - but only when nothing is running: no conversation turn, no message waiting in a
queue, no scheduled job, and the last turn ended more than 10 minutes ago. Otherwise it waits and tries again a few
minutes later, so an update never cuts a turn, and a turn that starts during the update waits for it (the
conversation says so; at most 7 minutes). Only the installed server does it: a second Harness Maxxing started on
the same machine for development or tests never updates the machine's Claude Code. It works for
the official installer and for a global npm install (another kind of install is left alone). If the new version
does not start, the previous one is put back.

Each update shows in the notifications ("Claude Code updated to 2.1.5"), and the switch shows the last one
(`2.1.4 -> 2.1.5` and its date). A failure is also notified, once per version, with the reason; the server tries
again 6 hours later. Leave the switch off to update by hand (`claude update` in a terminal); `maxxing doctor` then
lists Claude Code under `claude_version` when it is behind.

## Permission mode

| Mode | Behaviour |
|---|---|
| `bypass` (default) | Claude runs every tool without asking (`--dangerously-skip-permissions`). Needed for unattended work; suitable for a server dedicated to Claude. |
| `acceptEdits` | file edits are allowed, other actions (commands) are refused unless pre-approved in Claude Code settings |
| `default` | Claude Code's standard permissions; in a web session nobody can approve, so many actions are refused |

A topic can have its own mode (session list -> topic menu -> **Permissions**), and so can a scheduled Claude job
(**Permission mode** in the job editor): use a stricter mode where Claude reads content from outside - web pages,
e-mails, forwarded messages - so instructions hidden in that content cannot make it do just anything. Order: the
job's mode, else the topic's, else this global one.

**Protect the secrets** (on by default): in every mode, Claude's tools refuse to read or edit the server's secrets
(`secrets.json`) and the SSH keys (`~/.ssh`). It stops a hidden instruction from simply reading them; a script written
on purpose to open the file is not stopped, so it does not replace a stricter mode. More rules: `claude_deny` in
config.json (Claude Code rule syntax, for example `"Bash(rm -rf:*)"`).

See [Security](security).

## Keys (secrets vault)

Store API keys and tokens your projects need (for example `OPENAI_API_KEY`, `SHOP_TOKEN`):

- names are UPPER_CASE (`A-Z`, digits, `_`), values are hidden and shown only on **Reveal**;
- add a note (what it is for, where it comes from);
- **Add key** refuses a name already in the list (open that key with **Edit** to change it); a pasted
  multi-line value (a PEM or SSH private key) keeps its line breaks;
- **Expose** makes the secret available as an **environment variable** to every Claude session and
  every shell cron job – handy for scripts, and Claude never needs to see the value in a chat;
- some names are reserved (system variables, variables that make shells, Node, Python or git load
  code - `NODE_OPTIONS`, `BASH_ENV`, `GIT_SSH_COMMAND`... -, `ANTHROPIC_BASE_URL`, anything starting with
  `MAXXING_`); an existing key with such a name is kept but no longer exposed.

From scripts and sessions: `maxxing keys list|get|set|delete` (the value of `set` is read from stdin) -
a script that renews a token writes the new value back this way. Scripts read keys from the
environment (`os.environ["NAME"]`), never from a file of their own.

Write only the key *name* in memory files ("Shop API: key `SHOP_TOKEN`"). Extensions read keys with
`ctx["secret"]("NAME")`.

Keys live in `/var/lib/claude-maxxing/secrets.json` (mode 600) and are not included in the backup.

### Files

Some secrets are not a line of text: a keystore (`.p12`, `.jks`), a service-account JSON, a certificate. The **Files**
section of Settings → Keys stores them (1 byte to 1 MiB, binary is fine) under a name like a key
(`ANDROID_KEYSTORE`, `GCP_SERVICE_ACCOUNT`; same naming rules, and a name is either a key or a file). Only the list is
ever shown: name, original file name, size, a short SHA-256 fingerprint (its first 12 characters, enough to tell two
versions apart) and your note. The content is never sent to the
browser; to replace a file, upload it again under the same name (**Edit**, then choose the new file; leave the file empty to change only the note or the switch).

- **Expose** puts the file's **path** (not its content) in the environment variable of that name, for every Claude
  session and every shell cron job: `keytool -keystore "$ANDROID_KEYSTORE" ...`. Nothing to copy into a project folder
  and nothing to commit by mistake.
- From the terminal (the file comes from disk, or from stdin with `-`):
  `maxxing keys put-file NAME PATH [--note TEXT] [--no-expose]`, `maxxing keys get-file NAME [-o PATH]`
  (the bytes on stdout, or a new file of mode 600; `--force` to overwrite), `maxxing keys delete-file NAME`.
  On a terminal `get-file` prints only text: for a binary file use `-o FILE` or redirect the output (`> FILE`).
  `maxxing keys list` shows them with a `file` marker.
- Files live in `/var/lib/claude-maxxing/secret-files/` (folder mode 700, files mode 600), next to `secrets.json`:
  **never in the backup**, and covered by *Protect the secrets* like `secrets.json`.
- Agents never get a file (their *Keys it can use* list is about text keys), and their commands cannot read or
  change them with `maxxing keys`.

This is safe storage that avoids leaks **by mistake** (a commit, the backup, a memory file): sessions run as the
server's user, so it is not isolation from a session, which can read the path it is given - the same as for a key
exposed as a variable. A certificate expiry date in the list may come later.
