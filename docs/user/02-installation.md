---
section: Getting started
---
# Installation

## Requirements

- A server running **Ubuntu 24.04** (tested: Ubuntu 22.04, 24.04 and 26.04, Debian 12; other apt-based systems
  usually work) with **systemd**, on **x86_64 or arm64**. **2 vCPU, 4 GB RAM and 40 GB disk**
  recommended (the tools for videos and scraping take ~1.5 GB). Under 4 GB of RAM without swap the installer adds a
  2 GB swap file; under 3 GB local voice transcription stays off unless you ask for it.
- Root access (`sudo -i`).
- A **Claude** subscription (Pro/Max) or an **Anthropic API key**.
- For HTTPS access: a domain name whose DNS A/AAAA record points to the server, and ports 80/443
  open. Alternatively Tailscale, or an SSH tunnel.

We recommend a server dedicated to Harness Maxxing: by default Claude runs with full permissions
(see [Security](security)). A server that already runs other things works too - see
[Installing on a server already in use](#installing-on-a-server-already-in-use).

## Install

As root on the server (`sudo -i` first if you are logged in as another user):

```bash
curl -fsSL https://get.harness-maxxing.com | bash
```

It asks three questions (access mode, domain, restore a backup), then clones the public git repository
(`github.com/makushingu/harness-maxxing`, branch `stable` = the published versions) - no key, no account. Updates then come from that branch
(`maxxing update`). Unattended install:
`curl -fsSL https://get.harness-maxxing.com | ACCESS=domain DOMAIN=ui.example.com ASSUME_YES=1 bash`.
Harness Maxxing is free under a fair source license: see [License](license).

No license key is asked. A company that needs an Enterprise key gives it after the install, in Settings → License
(or the onboarding step About you); see [License](license).

After the questions the installer runs unattended with a live progress display. Voice messages are enabled with the
local engine (on servers with at least 3 GB of RAM) and the time zone is chosen in the web onboarding:

1. checks the server (root, apt, systemd, architecture) and whether it is already in use (see below);
2. installs every system package it needs **in one pass** (git, curl, python3, gnupg, openssh-client, cron, ffmpeg,
   jq, ripgrep, ImageMagick, the browser libraries, unattended-upgrades, fail2ban...), turning Ubuntu's `universe`
   component on if the image shipped without it; on a small server without swap it adds a 2 GB swap file;
3. clones the code into `/opt/claude-maxxing`; your customizations sit on top of it, see
   [Customizing](customizing);
4. installs **uv** (Python toolchain) in `/usr/local/bin`, the Python of the server in
   `/var/lib/claude-maxxing/tools/python`, and the **Claude Code CLI**: each one a pinned version whose checksum is
   in the release's list of components, `deps.toml` - nothing downloaded is run before it is checked (see
   [Security](security), "Downloads");
5. creates the Python environment and the `maxxing` command, then runs `maxxing init`: configuration, workspace,
   skills, default jobs;
6. optionally restores your memory from a backup;
7. sets up access (Caddy for a domain, Tailscale, or local only);
8. **secures the server**: automatic security updates, SSH logins by key only (only when it is
   proven safe, see [Security](security)), fail2ban for SSH, and a firewall (ufw) that
   lets in only SSH, 80/443 (domain) or Tailscale - see [Security](security) (on a server already in
   use, the firewall is handled carefully: see below);
9. installs and starts the `claude-maxxing` service and checks it answers;
10. prints a **one-time setup link** (valid one hour);
11. meanwhile, in the background, installs the **tools** Claude uses every day: **Node.js 22**, **Remotion** (motion
    design videos), **Scrapling** (web scraping) and one **Chromium** they share with PDF printing, plus the speech
    model - see [Videos, PDFs and images](tools). `maxxing deps list` shows where they are.

About a minute until the setup link on a small server, a minute or two more for the tools. A re-run only redoes what
changed (about 10 seconds). Re-run one part alone on an existing server: `bash /opt/claude-maxxing/install.sh --tools`
(= `maxxing deps update`) or `--secure`. Technical names keep the original spelling: the service is
`claude-maxxing`, the code `/opt/claude-maxxing`, the state `/var/lib/claude-maxxing`.

### Install from a local copy

No download at all: unpack a Harness Maxxing archive (with its built `web/dist`) on the server and run its
installer, `bash /path/to/harness-maxxing/install.sh` (or `SOURCE_DIR=/path/to/harness-maxxing bash install.sh`).
The code is copied to `/opt/claude-maxxing`; such an install has no update source, so "Check for updates" is off
and `maxxing update` says "updates unavailable". To update it, unpack the newer copy and run its installer again.

### External components

Everything the installer adds besides the system packages is listed, with its version and checksum, in
`server/maxxing/deps.toml` and managed with `maxxing deps`:

```bash
maxxing deps list      # installed and expected versions
maxxing deps verify    # checksums, and files another user could replace
maxxing deps update    # move to the versions of this release (each update does it on its own)
maxxing deps clean     # old versions, leftovers, oversized logs (also every Sunday); --caches: root's uv/npm/pip caches too
maxxing deps check     # known vulnerabilities (osv.dev; also every Monday, with a notification)
```

On an installation made before 2.0.0-alpha.70, the two weekly jobs are created **turned off** (Crons page: turn them
on if you want them), and `maxxing update` keeps a working server Python and a `uv` it did not install where they are
(`maxxing deps update python` / `uv` moves them). Node.js is never linked into `/usr/local/bin` when the server
already has its own `node`: Harness Maxxing uses its copy, your programs keep theirs.

Each `maxxing update` moves them to the versions of the new release (installed next to the old ones, switched once
they work). Claude Code keeps updating itself (Settings -> Claude). System packages (Caddy, ffmpeg, git...) get their
security updates from `unattended-upgrades`.

Open the link: the [onboarding](onboarding) does the rest.

## Installing on a server already in use

Before changing anything, the installer looks at the server and prints a **Server check**: other
services reachable from outside, a web server on ports 80/443, an active firewall, Docker, other
scheduled jobs, an older Node.js, an existing Claude Code setup, other Telegram bridges. To only see
that report (nothing is changed):

```bash
curl -fsSL https://get.harness-maxxing.com | bash -s -- --check
```

When the server is already in use, the installer asks for confirmation and then:

| What it finds | What it does |
|---|---|
| other services reachable from outside, or Docker | does **not** turn the firewall on (it could cut them off). Force it with `FIREWALL=1 bash /opt/claude-maxxing/install.sh --secure` |
| an active ufw firewall | keeps your rules and only adds SSH (+ 80/443 for a domain, + Tailscale) |
| nginx, Apache or another web server on 80/443 | does not install Caddy; with a domain, saves the reverse-proxy block to add to your web server in `/var/lib/claude-maxxing/reverse-proxy.conf` |
| a Caddy you already use | adds its own site with one `import` line, your sites stay as they are |
| other scheduled jobs | **never changes the server clock**: your jobs keep their times, Harness Maxxing jobs run at the times you pick in your own zone |
| a Node.js of its own | keeps it; Harness Maxxing gets its Node.js 22 in `/var/lib/claude-maxxing/tools/nodejs`, used only by its sessions and tools |
| port 8787 taken | uses the next free port |
| Claude Code already signed in, with skills or a `~/.claude/CLAUDE.md` | keeps everything, and **asks**: give Harness Maxxing its own Claude Code folder (`~/.claude-harness`, the default - your `~/.claude` is not touched, you sign in again in the web setup and bring skills over when you need them) or share `~/.claude` (its global instructions and skills then also apply to Harness Maxxing sessions; a skill with the same name as a product skill is moved to the trash first). Without a terminal: own folder. Re-running the installer keeps the choice made the first time |
| another Telegram bridge or agent | warns you: give Harness Maxxing **a new bot** (one bot token can only be read by one program) |
| SSH password logins on | turned off only when the session running the installer is proven to use a key (asked first when you answer questions); otherwise left on, with a warning |
| your crontab, fail2ban SSH jail, automatic-update settings | kept (Harness Maxxing only edits its own crontab block) |

`maxxing uninstall` lists what the installer changed on the server (firewall turned on, SSH by key only, time zone)
and how to undo it.

## Access modes

| Mode | URL | How |
|---|---|---|
| `domain` (recommended) | `https://ui.example.com` | Caddy is installed from its official repository, gets a Let's Encrypt certificate on the first visit and forwards to `127.0.0.1:8787`. Site file: `/etc/caddy/claude-maxxing.caddy`. |
| `tailscale` | `http://100.x.y.z:8787` | The server listens on the Tailscale IP only: reachable from your Tailscale devices. |
| `local` | `http://127.0.0.1:8787` | Listens on localhost only. From your computer: `ssh -N -L 8787:127.0.0.1:8787 root@<server>` then open the URL. |

The server never listens on `0.0.0.0` or a public address.

## Unattended install

Answer every question with variables and add `ASSUME_YES=1`:

```bash
curl -fsSL https://get.harness-maxxing.com | ACCESS=domain DOMAIN=ui.example.com ASSUME_YES=1 bash
```

| Variable | Default | Meaning |
|---|---|---|
| `REPO`, `BRANCH` | `makushingu/harness-maxxing`, `stable` | the git repository and branch the code and the updates come from (`stable` = published versions, `main` = work in progress) |
| `GH_TOKEN` | – | a read token, only for a private fork or mirror (`REPO=owner/name`) |
| `LICENSE` | – | optional: an Enterprise key, recorded at the end (same as Settings → License, see [License](license)) |
| `LICENSE_API` | `https://api.harness-maxxing.com` | license server (checks an Enterprise key) |
| `INSTALL_DIR` | `/opt/claude-maxxing` | code + Python environment |
| `WORKSPACE` | `/root/maxxing` | your workspace |
| `STATE_DIR` | `/var/lib/claude-maxxing` | configuration and state |
| `PORT` | `8787` | HTTP port |
| `ACCESS` | asked (`local` when unattended) | `domain`, `tailscale` or `local` |
| `DOMAIN` | – | required for `domain` |
| `TIMEZONE` | system zone | IANA name, e.g. `Europe/Paris`. Usually chosen in the web onboarding instead. On a fresh server the system zone is switched (`timedatectl set-timezone`) so scheduled jobs fire at the times shown in the UI |
| `SYSTEM_CLOCK` | `auto` | `follow` = the system zone follows yours (default on a fresh server), `keep` = never touch it (default on a server already in use; jobs still run at your times) |
| `CLAUDE_DIR` | `~/.claude` (`~/.claude-harness` when Claude Code is already used and you keep the default answer) | Claude Code folder used by Harness Maxxing; set it to skip the question. Another folder (e.g. `/root/.claude-harness`) keeps it apart from a Claude Code you already use on this server: its own skills, global `CLAUDE.md`, conversations and sign-in; your `~/.claude` is not touched. Bring skills over one by one when you need them |
| `RESTORE_FROM`, `RESTORE_TOKEN` | – | restore an existing memory backup (see below) |
| `CLAUDE_TOKEN` / `ANTHROPIC_API_KEY` | – | optional: Claude credentials stored right away |
| `FIREWALL` | `auto` | `auto` = ufw only on a server with nothing else exposed (an active ufw is kept, rules added), `1` = always, `0` = never (security updates and fail2ban are still set up) |
| `SSH_HARDEN` | `auto` | `auto` = turn SSH password logins off only when this session is proven to use a key, `1` = also when a key is installed but the session cannot be checked (console, web terminal), `0` = never touch SSH |
| `VOICE` | `local` (`off` under 3 GB of RAM) | voice messages: `local` (Whisper on the server, model downloaded in the background), `groq`, `openai` or `off` - see Voice messages. `VOICE=local` on a smaller server is asked, refused unattended |
| `TOOLS` | `background` | `background` = Node.js, Chromium, Remotion, Scrapling and the speech model are installed once the service runs, `foreground` = wait for them, `0` = skip (`maxxing deps update` later) |
| `SWAP` | `auto` | `auto` = a 2 GB `/swapfile` under 4 GB of RAM when there is no swap, on a fresh server only (not in containers, not on a server already in use or a re-run), `1` = the same on any server, `0` = never |
| `SOURCE_DIR` | – | install this local copy of the code (see "Install from a local copy") |
| `ASSUME_YES` | `0` | `1` = never ask, use defaults |

## Restore on a new server

Moving to a new server? Install with your backup repository (with an Enterprise key, first free it on the old
server: Settings → License → Remove the key, see [License](license)):

```bash
curl -fsSL https://get.harness-maxxing.com | RESTORE_FROM=owner/memory-backup RESTORE_TOKEN=<token> bash
```

The installer runs `maxxing backup restore --from owner/memory-backup` after creating the
workspace. See [Backup](backup).

## Re-running, updating, uninstalling

- **Re-run** the installer at any time: every step keeps what exists (useful to change the access
  mode or repair an install).
- **Update**: `maxxing update` (or `... | bash -s -- --update`). It pulls the new version, replays
  your [customizations](customizing) on top, syncs dependencies, refreshes skills and templates
  (never your files), restarts the service, checks it answers (otherwise it rolls back) and prints
  what changed. Also available in Settings -> System and in the topic `system/harness` (`system/update` on older servers).
- **Uninstall**: `maxxing uninstall` (or `... | bash -s -- --uninstall`) removes the service,
  Caddy site, crontab block, product skills and the `maxxing` command. Add `--purge` to also
  delete the code, the state directory and every external component the installer added (`deps.toml`: uv, Node.js,
  the tools, Claude Code and Caddy when the installer installed them, the swap file it created),
  `--purge-workspace` to delete the workspace too (irreversible).

## Check the installation

```bash
maxxing doctor
```
Every line is `✔` (fine), `!` (warning) or `✘` (problem), with a fix hint. See
[Troubleshooting](troubleshooting).
