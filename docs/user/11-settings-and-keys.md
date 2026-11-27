---
section: Settings
---
# Settings and keys

Everything is configurable from **Settings**; no file editing is needed.

The sections are grouped in six blocks, in this order. On a phone, Settings opens on the list of every section,
grouped the same way (one tap each); inside a section the tabs at the top go to the others (a thin bar between two
blocks):

| Block | Section | What you find |
|---|---|---|
| **General** | **General** | language (English, French, Spanish, German, Simplified Chinese or Japanese - see [Language](#language)), time zone, **App** (install it on this computer or phone, below), the getting started guide and the tutorial |
| | **Appearance** | saved in this browser, in three cards. **Theme**: *Solid* (the default: plain colors) or *Glass* (the bars, menus and dialogs become see-through over a soft backdrop in your accent color; off when your system asks for less transparency), and the themes Harness installed for you next to them ([Themes](39-themes.md); **Ask Harness** for a new one), each shown as a small preview. **Options of the theme**: mode (dark, light or system), accent color (the logo takes it too), background (neutral or tinted with the accent), interface font (23, grouped by style: modern, with character, rounded, serif, easy to read, monospace) and code font (11; a font other than the default loads the first time you pick it) - the last mode, accent and background you pick also color the sign-in page and any browser that never chose one (new phone, private window). **Layout**: density, **layout** of this device (*Auto*: the touch layout on phones and tablets, the sidebar on computers; *Touch*; *Desktop* when the screen is wide enough), the first screen of the touch layout (*Last session* or *Dashboard*) |
| | **Profile** | your pseudo, a **photo** (kept on this server, shown instead of the color and emoji, also to your Team contacts), color and emoji (picked from a searchable list) for messages, notifications and Team, with a preview; **Stay in touch**: the optional e-mail, news and anonymous counter (see [License](license)) |
| | **Security** | **Protections** (what protects this server, and what is left to turn on), change the password, **Two-step sign-in** (Telegram, an authenticator app, recovery codes), **Privacy**: the presentation mode by default (new browsers start with your data masked), **Signed-in devices** (the browsers signed in, **Disconnect**, **Disconnect all the others**), sign out - see [Security](security#sign-in) |
| | **Features** | every page of the sidebar: the ones always there, the optional ones with their switch, the options of the sessions under Sessions (below) |
| | **Voice** | how voice messages and dictation are transcribed (on the server, Groq, OpenAI, or off), the microphone and call buttons, the voice mode |
| **Claude** | **Claude** | authentication (status, token or API key, live test), default model, automatic compaction threshold, compaction when you come back to an idle session, smart resume (a summary written for the message you come back with), short session titles (and whether Claude writes them), automatic Claude Code updates, permission mode |
| | **Memory** | second brain cleaner: line limit per `memory.md`, **Clean now**, size of every memory file - see [Memory](memory) |
| | **Skills** | the skills Claude sees on this server: **yours** (in `~/.claude/skills`, the workspace, a project or a topic, with where each one lives) and the ones **shipped with Harness** (refreshed by every update, read-only); **Open**, **Edit with Claude**, **Share with the community**, **New skill** - see [Skills](skills) |
| | **MCP** | the MCP servers of Claude Code (a service's tools for Claude): every session or one topic, state, **Connect** (sign-in), **Remove** - see [MCP servers](28-mcp.md) |
| | **Keys** | your secrets vault (below) |
| | **Usage** | **Daily budget**: a ceiling in dollars per day for the whole server (0 = none), counted at the price Claude Code reports for each turn (on a subscription: what the same turns would cost with an API key). A [notification](feed) at 80 %, an alert when it is reached; from then on the scheduled prompt jobs and the agents' triggers wait for the next day (skipped, with the reason), while your own messages, your messages to an agent and **Run now** still run. The card shows what today cost so far. **Alerts** (see [below](#usage-alerts)). **Start again after the usage limit** (on by default): a scheduled job or an agent run stopped by the usage limit of your Claude plan starts again by itself once the limit resets, plus a delay (60 seconds by default). Then Claude plan usage (5-hour window, week) and the plan name (Pro, Max, Ultra): the same figures as the bars at the bottom of the sidebar, read from the last Claude answer; a verified **Ultra** account has no 5-hour limit, so only the week is shown; **Show plan usage** (on for new installs) shows them here and adds the dashboard widget (experimental: it may also ask Anthropic directly when no answer came for 10 minutes); tokens and cost per project, topic, **agent** and session (**CSV** / **JSON** under the table download every row of the grouping shown, **Per day** the daily chart; `maxxing usage export`), tokens per day, how fast turns start (Claude Code ready / first answer, median of recent turns) |
| **Automate** | **Crons** | the scheduled jobs: list, run now, history, editor (see [Crons](crons)); old `/crons` links open it |
| | **Webhooks** | every URL that a service calls on this server (Stripe, Shopify, GitHub, a form, a phone Shortcut, n8n...): what each one does, its last calls, test, replay, new URL, secret; also the webhooks that post to the notifications feed and the ones of agents. Made by asking Harness - see [Webhooks](webhooks) |
| | **Events** | when something happens in Harness (a notification, an agent run that ends, a cron that fails), do one thing without AI - see [Events](events) |
| **Notifications** | **Alerts** | what this browser and your phone do: a notification (and an optional sound) when a Claude session finishes, Team messages, pulsing unread badges (saved per browser), **Mobile notifications** (push, even with the app closed) |
| | **Feed** | the [notifications feed](feed): its Telegram thread, **Server problems in the notifications**, the sources and what each one does in Telegram |
| | **Telegram** | bot wizard, linking, mode (simple chat, threads, web mirror), notification options, two-step sign-in (also in Security) – see [Telegram](telegram) |
| **Extensions** | **Widgets** | the widget extensions of `<workspace>/extensions`: switch on/off, **Rescan**, **Customize the dashboard** (opens the dashboard in edit mode) – see [Dashboard widgets](dashboard-widgets) |
| | **Pages** | the page extensions: every page pinned or not, switch on/off, **Open page**, **In the sidebar** (pin: the sidebar's Extensions folder), **Rescan** – see [Page extensions](page-extensions) |
| | **Agents views** | the extensions that bring a view of the Overview of the Agents page (a page or a widget that also brings one shows in both), switch on/off, **New view**, **Rescan** – see [Overview views](page-extensions#overview-views-of-the-agents-page) |
| | **Themes** | the themes installed in `<workspace>/themes`: their state (in use, advanced CSS on or off, values ignored), folders that are not usable, **New theme** (asks Harness), **Choose in Appearance** – see [Themes](themes) |
| | **Community** | the catalogue of the website in three tabs (Extensions, Themes, Skills): **Check and install** shows what a listing would do on this server, then installs it once you confirm – see [Community extensions](page-extensions#5-community-extensions) |
| **Workspace** | **Templates** | add a ready-made project (**starter pack**) for your kind of work; an existing project is never overwritten - see [Starter projects](starter-projects) |
| | **Import** | the memory of another agent (Hermes, OpenClaw, Claude Code, a zip) - see [Import](import); and the way to the other imports: a memory backup (**Backup**), an agent file (Agents page) |
| | **Backup** | repository, schedule, whitelist, history, restore – see [Backup](backup) |
| | **Trash** | deleted sessions, topics and files, restore them or empty the trash |
| **Server** | **System** | health, **disk space** (see [below](#disk-space)), **CPU priorities** (see [below](#cpu-priorities)), services (start/stop/restart), logs (see [below](#logs)), **metrics for a monitoring tool** (see [below](#metrics-for-a-monitoring-tool)), and the **address of the server**: public URL and files root (the folder the file viewer can show) |
| | **Updates** | the installed version, **Check** and **Update** (with the smart update preflight), **Automatic update**, **What's new** (also shown once after each update; the main new features have a **Show me** button that takes you to them and highlights them), then every version of Harness Maxxing, newest first, with a search |
| | **About** | the version and the useful links (docs, GitHub, community), the optional **Enterprise key** (only for companies that need one: record it, see it, remove it - see [License](license)), **Support**: Harness Maxxing is free, **Donate** opens the donation page of the website in a new tab (nothing is sent from the app); **Hide the Donate buttons** removes them from What's new and the Feedback window, in every browser - see [License](license#donations) |

The docs are not in Settings: open them with the book icon at the bottom of the sidebar (in the ⊞ menu on a phone).
The community catalogue (widgets, pages, Agents views, skills and themes shared by other users) is on the website,
[harness-maxxing.com/community](https://harness-maxxing.com/community), and in **Settings -> Community** (Extensions,
Themes, Skills): **Check and install** shows what a listing would do on your server, then installs it once you confirm -
see [Extensions](page-extensions#5-community-extensions).
Old links keep working: `/settings/stats` opens **Usage**, `/settings/license` and `/settings/support` open **About**, `/settings/packs` and `/settings/projects` open **Templates**, `/settings/extensions` opens
**Widgets**, `/settings/docs` opens the docs.

## Language

The interface exists in six languages: English, French, Spanish, German, Simplified Chinese and Japanese. Choose
yours in **Settings -> General -> Language** (the first step of the setup wizard asks it too): it is a setting of
the server, so every browser signed in follows it. The sign-in page opens in that language, and its language
button changes it for that page.

What the server writes follows the same setting: the Telegram bot's own messages and its command menu, mobile
notifications, the built-in texts of the dashboard. From a terminal: `maxxing init --language es` (`en`, `fr`, `es`,
`de`, `zh`, `ja`).

## Disk space

**Settings -> System -> Disk space** shows how full the disk is, with two buttons:

- **Free up space** measures what Harness can drop by itself and lists it with its size: old versions and
  leftovers (previous versions of the components, browsers no longer used, temporary files, oversized logs),
  download caches (uv, npm, pip, npx: downloaded again when needed; what a running tool such as an MCP server
  uses stays), the system journal (cut down to its last 200 MB), the system packages apt already installed, the
  video previews and thumbnails of the file viewer (made again when shown) and the Harness trash. Untick what you
  want to keep, then **Free**. The previews and the trash are never ticked by default: once emptied, nothing in
  the trash can be restored. While the components are being updated, old versions and caches are not cleaned
  (the part says so): run it again afterwards. Your projects, attachments and renders are never touched. From a
  terminal, `maxxing deps clean --caches` does the first two.
- **Clean up with Claude** opens a session in the Harness topic with a ready prompt: Claude measures the disk,
  goes through every project and topic (attachments, renders, `node_modules`, environments, builds, worktrees,
  other tools' caches), finds where each big folder comes from and whether it keeps growing, and gives you a
  table of what to delete, move or keep. It deletes nothing without your OK, and suggests fixing what keeps
  coming back (a size limit, a cleanup in the job that produces it).

## CPU priorities

When the processor is full (a video render, a big build, several sessions at once), Linux shares it equally by
default: a render at 99 % gets as much as the interface you are using. **Settings -> System -> CPU priorities** (on by
default) gives the processor in this order when it is full:

| Priority | What |
|---|---|
| **Live** | the Harness server - the interface you watch |
| **Normal** | the turns of your sessions and agents |
| **Background** | scheduled jobs and heavy work started with `maxxing heavy` (e.g. `maxxing heavy ffmpeg -i in.mov out.mp4`; `maxxing video render` does it for Remotion videos) |

These are priorities, never limits: while the processor has room, everything runs at full speed; when it is full,
background work slows down a little and never stops. The server takes its place at its next restart (an update
restarts it). Switch it off and every program gets the same share again.

**Who takes the processor**: click the CPU meter at the bottom of the sidebar. It lists the programs using the
processor most (Harness, a session, an agent, heavy work, a job, the browser, Docker…) with their priority and how
long programs wait for the processor. A high CPU figure alone is not a problem; when programs wait (more than 20 % of
the time) the meter turns amber and says **waiting**. If the processor stays full for 10 minutes, a health problem
(also in Settings -> Feed) names the program that takes the most; it clears itself.

## Usage alerts

**Settings -> Usage -> Alerts**: a [notification](feed) when the spend leaves its usual range, without a budget to
set first. Nothing is stopped by an alert (a budget does that); each one is said once.

- **An unusual day** (on, 3 times): what today cost so far is at least 3 times a usual day, the median of the last
  14 days that had usage. Looked at for the whole server and for each agent, so an agent without a budget that
  starts to run in a loop is noticed the same day. Silent below $5 for the server and $2 for an agent, and while
  the server has fewer than 3 days of history. Choose 2, 3, 5 or 10 times, or **Off**.
- **An expensive turn** (off): one turn costs at least the amount you enter. 0 = no alert.
- **A turn that keeps failing** (on): at least 8 tool calls of a turn failed, and at least half of them: Claude kept
  trying something that does not work. The notification opens the session; **Turn details** (the ⚙ under the
  answer) lists the calls.

## Logs

**Settings -> System -> Logs** shows the journal of a service of this server (Harness Maxxing by default). Three
filters narrow it down:

- **Search**: the lines that contain a text (no difference between capitals and small letters);
- **Level**: every line, warnings and errors, or errors only. A Python error keeps its whole trace;
- **Period**: the last 15 minutes up to 30 days.

Under the lines, a sentence says how many match and whether the journal held more than was read (a search reads the
20 000 most recent lines of the period). Passwords, tokens and keys are masked as everywhere else.

In a terminal: `maxxing logs --since 24h --level error`, `maxxing logs --grep telegram`,
`maxxing logs --session <id>` (the lines about one session), `--json` for a script.

## Metrics for a monitoring tool

For those who already run Prometheus, Grafana or another monitoring system. Off by default: nothing is exposed
until you turn it on, and most installations never need it (Settings -> Usage and the dashboard show the same
figures).

**Settings -> System -> Metrics for a monitoring tool -> Expose /metrics** (or `maxxing metrics on`) gives:

- an address, `https://<your address>/metrics`, in the Prometheus text format;
- a secret token, shown once: the monitoring tool sends it as `Authorization: Bearer <token>`. Without it the
  address answers 401; with the switch off, 404. **New token** replaces it (the old one stops working at once).

What it holds: tokens, cost and turns (in total, today, per project and per agent), the daily budget and whether it
is reached, the usage of your Claude plan, the scheduled jobs (last run, its result and duration), sessions running,
disk, memory, load, the health checks and the age of the last backup. No session title, message, file name or key
is in it.

```yaml
scrape_configs:
  - job_name: harness
    scheme: https
    authorization: { credentials: "hmx_..." }
    static_configs: [{ targets: ["harness.example.com"] }]
```

## Features

**Settings -> Features** lists every page of the sidebar, in its order, with what it is for. **Dashboard**,
**Sessions** and **Files** are always there (marked **Always on**); the optional pages have a switch and say what they
need. A page switched on gets its entry in the sidebar (and in the ⊞ menu, the palette and the `G` shortcuts); switched off, it
is hidden and nothing is deleted (each page's doc says what still runs meanwhile).

| Page | On a new install | Needs |
|---|---|---|
| **Agents** - lasting helpers of a topic (see [Agents](agents)) | on | nothing |
| **Tasks** - the task board (see [Tasks](tasks)) | off | nothing |
| **Team** - chats with other Harness users (see [Team](team)) | off | an https address on the internet (domain mode) |
| **E-mail** - your mailboxes (see [E-mail](mail)) | off | an IMAP/SMTP mailbox |
| **Infra** - sites, databases, buckets, domains, servers (see [Infra](infra)) | off | nothing for this server; a key for Cloudflare or Hostinger |
| **Git** - repositories and their graphs (see [Git](git)) | off | a `GITHUB_TOKEN` key for GitHub |

The first-run wizard asks the same question (**What will you use?**), and Settings -> Keys offers the Git page as
soon as a GitHub key is in the vault. An install made before 2.0.0a132 keeps the pages it had.

Under **Sessions**, indented: **Maxxing mode (beta)** and the **line under the answers** (cost, tokens, duration, model: tick what
it shows) for everyone, and, saved in this browser only (marked **This browser**): the **Tabs mode** (Alt+T; off = Zones). Below
the pages: **Badges**, one switch per page with a counter in the sidebar (Home: unread notifications, red when one is an
error; Sessions; Team; Agents), all on by default: turn one off and its page shows no number nor dot (the counts stay on
the page itself); then **Harness Browser** (see [Harness Browser](browser)) and **Devices**, off by default (Claude uses your own
computers and phones, see [Devices](devices)). Under **Team**, while Team is on: **Team bubbles** (the chat bubbles at the bottom right of every page,
saved in this browser). The notification when a session finishes is in **Settings -> Alerts**, the Claude plan usage
widget in **Settings -> Usage**, the presentation mode by default in **Settings -> Security**, the Telegram mode in
**Settings -> Telegram**.

Changing the **time zone** (Settings -> General) does not change the server clock: run
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

Phones and tablets get the **touch layout** (Settings -> Appearance -> Layout changes it per device): no sidebar, no
bar at the bottom, the conversation fills the screen. Two buttons sit at the top of every screen:
- **☰** (top left) opens the list of the page you are on, the one the second bar shows on a computer: your sessions
  on Sessions (its counter shows the unread answers - see [Sessions](04-sessions.md)), the agents, the chats, the
  task projects, the Infra sections, the folder, the mailboxes and folders, the notification sources. Pages without
  a list (Home, Git, Settings...) have no ☰.
- **⊞** (top right) opens everything else, laid out like the sidebar: a search field (the same as ⌘K), every page
  in your sidebar order (the unread notifications count on the Home tile, red when one is an error), the extension pages apart, Feedback and Settings, then the status
  card - server health (tap it for the issues), CPU / RAM / disk (opens Settings -> System), your Claude plan
  (opens Settings -> Usage), presentation mode, the theme, the docs and General settings. A dot on ⊞ means an
  update is waiting or the server needs attention.

On a computer the bottom of the sidebar holds the same status block, with the keyboard shortcuts next to the docs.
The pages with a list (Sessions, Agents, Team, Tasks, Infra, Files, E-mail, Notifications) show it in a second bar
next to the sidebar (see [Sessions](04-sessions.md#layout)); the touch layout opens the same list from ☰.
The getting started guide (also in Help, **?** at the bottom left) and the interactive tutorial are in **Settings -> General**; **Sign out** is in **Settings ->
Security**.

Also:
- **Share to Harness** (installed app, Android): in any app - Photos, Files, the browser, a note - tap **Share** and
  pick **Harness Maxxing**. A new session of the topic you were in opens with the photo, the file, the link or the
  text already in the message box (10 files at most); nothing is sent before you send the message, and you can
  move the session to another topic first. An iPhone does not offer installed web apps in its share sheet: attach
  the file from the message box instead.
- In the installed app, **swipe from the left edge** to open the page's list (the sessions on Sessions), from the
  right edge to open the menu;
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

## New Claude models

Once a day the server asks Anthropic which Claude models exist (with the Claude account it is signed in with) and
keeps the newest Opus, Sonnet, Haiku and Fable: the model lists (default model, topics, jobs, agents, Telegram
`/model`) show them as soon as Anthropic releases them, without an update of Harness Maxxing. If your default model
is the newest of its family (say Sonnet 5.5) and a newer one comes out (Sonnet 6), the default follows it. A model
you chose on a topic, a job or an agent is never changed. Short titles, the connection test and Team summaries
always use the newest Haiku or Sonnet.

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
| `sandbox` (**Sandbox (this topic only)**) | the default of a new installation. Claude works without asking inside the topic folder: its commands write there only and cannot read the server's keys, the SSH keys nor the rest of the home folder. What has to leave the topic (install a package, restart a service, another folder) asks you first, with a **Full access** button that gives the topic full access. The topics of the `system` project keep full access. See [Security](security#what-claude-may-do-on-the-server-permission-mode) |
| `bypass` (**Full access**) | Claude runs every tool without asking (`--dangerously-skip-permissions`). Needed for unattended work on the whole server; suitable for a server dedicated to Claude. A server installed before the sandbox became the default keeps this mode until you change it. |
| `acceptEdits` | file edits are allowed, other actions (commands) are refused unless pre-approved in Claude Code settings |
| `ask` (**Ask me**) | reading is free; every other tool that is not pre-allowed waits for your **Allow** / **Deny** (see below) |
| `default` (**Strict**) | Claude Code's standard permissions, nobody is asked: what needs an approval is refused |

A topic can have its own mode (session list -> topic menu -> **Permissions**), and so can a scheduled Claude job
(**Permission mode** in the job editor): use a stricter mode where Claude reads content from outside - web pages,
e-mails, forwarded messages - so instructions hidden in that content cannot make it do just anything. Order: the
job's mode, else the topic's, else this global one.

**Ask me** (`ask`): when Claude wants to run a command, edit a file, fetch a page or use an MCP tool that is not
allowed yet, the session shows a card above its message box with the exact request and **Deny** / **Allow** (a
message to Claude can go with Deny). The same request reaches the notifications and Telegram, so you can answer
from your phone. Without an answer it is denied after 30 minutes; a stopped turn drops its requests. **Always
allow** answers yes and adds a narrow rule to the topic - the exact command, the exact file, the site's domain, or
the MCP tool - so its sessions stop asking for it. The topic's **Permissions** dialog lists these rules; remove one
with ×. A job in an `ask` topic asks too (notifications, Telegram) and gets a denial if nobody answers in time.

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
- **Topics** (under the switch, in the dialog of a key or a file) limits an exposed key to the projects and
  topics you tick: only their sessions and their scheduled jobs get the variable. A ticked project covers all
  its topics, also the ones created later. Nothing ticked means every topic, as before. A limited key is not
  given to a session at the workspace root nor to a shell job without a topic, and the list shows "2 topics"
  next to it. From the terminal: `maxxing keys set NAME --topics projects/shop,projects/blog/topics/seo`
  (`--topics ""` for every topic again). Agents are not concerned: each one has its own list of keys. It decides
  what a session receives at its start; a session with full access can still run `maxxing keys get`, so combine
  it with the sandbox mode for the topics you do not trust;
- some names are reserved (system variables, variables that make shells, Node, Python or git load
  code or send credentials elsewhere - `NODE_OPTIONS`, `BASH_ENV`, `SHELLOPTS`, `CLAUDE_CONFIG_DIR`,
  `ANTHROPIC_BASE_URL`, `SSH_AUTH_SOCK`... -, anything starting with `MAXXING_`, `GIT_`, `LD_`, `DYLD_`,
  `PYTHON`, `NODE_`, `BASH_`, `XDG_` or `SSL_`, anything ending in `_PROXY`); an existing key with such a
  name is kept but no longer exposed.

From scripts and sessions: `maxxing keys list|get|set|delete` (the value of `set` is read from stdin) -
a script that renews a token writes the new value back this way. Scripts read keys from the
environment (`os.environ["NAME"]`), never from a file of their own.

Write only the key *name* in memory files ("Shop API: key `SHOP_TOKEN`"). Extensions read keys with
`ctx["secret"]("NAME")`.

Keys live in `/var/lib/claude-maxxing/secrets.json` (mode 600) and are not included in the backup.

**Encrypting that file (optional).** `maxxing keys encrypt`, as root, seals it with the machine's own key
(`systemd-creds`: the host key, and the TPM when there is one) into `secrets.json.cred`; `maxxing keys decrypt` goes
back. It makes a copy of the file (a backup of the state folder taken elsewhere) useless on another machine; it does
not stop someone who is already root on the server, since the key is on the machine so that the server restarts
alone - and without a TPM a copy of the whole disk holds the key too. Once sealed, a script that reads `secrets.json`
directly stops working (use `maxxing keys get NAME` or the environment), and the state folder cannot be moved to
another server as it is: run `maxxing keys decrypt` first. Details: [Security](15-security.md#secrets-sealed-on-disk-optional).

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
