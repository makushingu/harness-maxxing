---
section: Getting started
---
# Installation

## Requirements

- A server running **Ubuntu 24.04** (tested: Ubuntu 22.04, 24.04 and 26.04, Debian 12 and 13, **Fedora 43** and
  **Arch Linux**; also [macOS](#macos) and [Windows through WSL 2](#windows-wsl-2); other systems with apt, dnf or pacman usually work - see [Fedora and Arch](#fedora-and-arch))
  with **systemd**, on **x86_64 or arm64**. **2 vCPU, 4 GB RAM and 40 GB disk**
  recommended (the tools for videos and scraping take ~1.5 GB). Under 4 GB of RAM without swap the installer adds a
  2 GB swap file; under 3 GB local voice transcription stays off unless you ask for it.
- Root access (`sudo -i`) - or none at all: see [Install without root](#install-without-root).
- A **Claude** subscription (Pro, Max or Ultra) or an **Anthropic API key**.
- For HTTPS access: a domain name whose DNS A/AAAA record points to the server, and ports 80/443
  open. Alternatively Tailscale, or an SSH tunnel.

We recommend a server dedicated to Harness Maxxing: on a new installation a session works in the sandbox of its
topic, but the `system` project, and every topic you give **Full access**, run with full permissions on the server
(see [Security](security)). A server that already runs other things works too - see
[Installing on a server already in use](#installing-on-a-server-already-in-use).

## Install

As root on the server (`sudo -i` first if you are logged in as another user):

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | bash
```

(`--proto '=https' --tlsv1.2`: curl only speaks HTTPS with TLS 1.2 or newer, even if a redirect points elsewhere.)

It asks a few questions (access mode, domain, restore a backup, the anonymous daily count), then clones the public git repository
(`github.com/makushingu/harness-maxxing`, branch `stable` = the published versions) - no key, no account. Updates then come from that branch
(`maxxing update`). Unattended install:
`curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | ACCESS=domain DOMAIN=ui.example.com ASSUME_YES=1 bash`.
Harness Maxxing is free under a fair source license: see [License](license).

No license key is asked. A company that needs an Enterprise key gives it after the install, in Settings → About
(or the onboarding step About you); see [License](license).

After the questions the installer runs unattended with a live progress display. Voice messages are enabled with the
local engine (on servers with at least 3 GB of RAM) and the time zone is chosen in the web onboarding:

1. checks the server (root, the package manager - apt, dnf or pacman -, systemd, architecture) and whether it is already in use (see below);
2. installs the system packages it needs: the base ones right away (git, curl, python3, gnupg, openssh-client,
   cron...), the others (ffmpeg, jq, ripgrep, ImageMagick, the browser libraries, unattended-upgrades, fail2ban...)
   **in one pass in the background** while the next steps run, turning Ubuntu's `universe` component on if the
   image shipped without it; on a small server without swap it adds a 2 GB swap file first;
3. clones the code into `/opt/claude-maxxing` (a partial clone: the files of older versions are fetched only if git
   ever needs them); your customizations sit on top of it, see [Customizing](customizing);
4. installs **uv** (Python toolchain) in `/usr/local/bin`, the Python of the server in
   `/var/lib/claude-maxxing/tools/python`, and the **Claude Code CLI**: each one a pinned version whose checksum is
   in the release's list of components, `deps.toml` - nothing downloaded is run before it is checked (see
   [Security](security), "Downloads");
5. creates the Python environment (in the background, while Claude Code installs) and the `maxxing` command, then
   runs `maxxing init`: configuration, workspace,
   skills, default jobs;
6. optionally restores your memory from a backup;
7. sets up access (Caddy for a domain, Tailscale, or local only);
8. **secures the server**: automatic security updates, SSH logins by key only (only when it is
   proven safe, see [Security](security)), fail2ban for SSH, and a firewall (ufw; firewalld on Fedora) that
   lets in only SSH, 80/443 (domain) or Tailscale - see [Security](security) (on a server already in
   use, the firewall is handled carefully: see below);
9. installs and starts the `claude-maxxing` service and checks it answers;
10. prints a **one-time setup link** (valid one hour);
11. meanwhile, in the background, installs the **tools** Claude uses every day: **Node.js 22**, **Remotion** (motion
    design videos), **Scrapling** (web scraping) and one **Chromium** they share with PDF printing, plus the speech
    model - see [Videos, PDFs and images](tools). `maxxing deps list` shows where they are.

About a minute until the setup link on a small server, a minute or two more for the tools. A re-run only redoes what
changed (about 10 seconds). If an install stops halfway (network cut, full disk), run the same command again: what
was already downloaded is kept in `/var/cache/harness-maxxing` (checked again before use, emptied once the install
succeeds) and is not downloaded again. Re-run one part alone on an existing server: `bash /opt/claude-maxxing/install.sh --tools`
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

On an installation made before 2.0.0-alpha.70, the two weekly jobs are created **turned off** (Settings -> Crons: turn them
on if you want them), and `maxxing update` keeps a working server Python and a `uv` it did not install where they are
(`maxxing deps update python` / `uv` moves them). Node.js is never linked into `/usr/local/bin` when the server
already has its own `node`: Harness Maxxing uses its copy, your programs keep theirs.

Each `maxxing update` moves them to the versions of the new release (installed next to the old ones, switched once
they work). Claude Code is updated apart: by hand (`claude update`), or by the server when **Update Claude Code automatically**
is on (Settings -> Claude, off by default). System packages (Caddy, ffmpeg, git...) get their
security updates from `unattended-upgrades`.

Open the link: the [onboarding](onboarding) does the rest.

## Fedora and Arch

The same command installs Harness Maxxing on Fedora (and systems of its family that use `dnf`) and on Arch Linux
(`pacman`), as root or [without root](#install-without-root). What differs from Ubuntu and Debian:

| | Ubuntu, Debian | Fedora | Arch |
|---|---|---|---|
| Packages | `apt` | `dnf` | `pacman` (a stale package list is refreshed with a full `pacman -Syu`, as Arch asks) |
| Scheduled jobs | `cron` | `cronie` (service `crond`) | `cronie` |
| Automatic security updates | `unattended-upgrades` | dnf's `automatic` plugin and its timer, security updates only | none: Arch has no such thing, keep the system up to date yourself |
| Firewall | `ufw` | `firewalld` (an active one is kept; 80/443 or the Tailscale interface are added to it) | `ufw` |
| fail2ban for SSH | yes | yes (bans through firewalld, or nftables when firewalld is not the firewall) | yes |
| Caddy (domain access) | Caddy's own signed repository | the distribution's package | the distribution's package |

On Fedora with SELinux enforcing, the installer allows Caddy to reach the server on `127.0.0.1`
(`httpd_can_network_connect`). `maxxing doctor` and the fixes it prints use the names of your system.

## macOS

On a Mac (macOS 13 or later, Apple Silicon or Intel), the same command as on Linux, in the Terminal, **without
`sudo`**:

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | bash
```

It installs everything in your home folder, like [Install without root](#install-without-root) on Linux, and
changes nothing of the system:

| | |
|---|---|
| Code, state | `~/.harness-maxxing/app`, `~/.harness-maxxing/state` |
| Workspace | `~/maxxing` |
| Commands | `~/.local/bin` (`maxxing`, `uv`, `claude`) |
| Service | a launchd agent of your account, `com.harness-maxxing.server`: starts when you sign in to the Mac, restarted if it stops; its output goes to `~/.harness-maxxing/state/logs/server.log` |
| Access | `http://127.0.0.1:8787`, on this Mac only |

What it needs: Apple's Command Line Tools (for git - the installer opens the window that installs them when they
are missing) and, for videos, PDFs and voice messages, [Homebrew](https://brew.sh): with it the installer adds
ffmpeg, jq, ripgrep, imagemagick and poppler; without it, it tells you the line to run later.

What a Mac does not have: the **sandbox mode** (it relies on bubblewrap, which is Linux only - sessions there run
with your own rights, in mode ask or bypass), domain access with automatic HTTPS, and the server hardening
(firewall, fail2ban). Attaching a file to a mail from a session is not available there yet. It runs while your
session on the Mac is open: for a server that is always on, use a Linux server.

`maxxing doctor`, `maxxing update` and `maxxing uninstall` work as on Linux; to restart the service by hand:
`launchctl kickstart -k gui/$(id -u)/com.harness-maxxing.server`.

## Windows (WSL 2)

On Windows 10 (version 2004 or later) and Windows 11, Harness Maxxing runs inside WSL 2, the Linux that ships with
Windows. In PowerShell:

```powershell
irm https://raw.githubusercontent.com/makushingu/harness-maxxing/main/install.ps1 | iex
```

The script does what is missing, and can be run again at any time:

1. turns WSL on - the first time only, from a PowerShell opened **as administrator**, followed by a restart of
   Windows; run the same command again after it;
2. installs an Ubuntu 24.04 distribution in WSL (or uses the one you name: `$env:HM_DISTRO = "Debian"` before the
   command) and turns systemd on in it;
3. runs the Linux installer inside it, as root: the same one as on a server, with **local** access;
4. adds a Windows task, "Harness Maxxing (WSL)", that starts the distribution when you sign in and keeps it
   running - Windows stops a WSL distribution nobody uses, and Harness Maxxing with it
   (`$env:HM_KEEPALIVE = "0"` skips the task).

Harness Maxxing then answers on `http://localhost:8787` in the browser of that PC. Your files are in the Linux
distribution (`\\wsl$\Ubuntu-24.04\root\maxxing` in the Explorer); the drives of Windows are under `/mnt/c`.
A terminal inside it: `wsl -d Ubuntu-24.04 -u root`; every `maxxing` command of this documentation runs there.

It runs while your Windows session is open: for a server that is always on, use a Linux server. To reach it from
your phone or another computer, install Tailscale **inside** the distribution and run the installer again with
`ACCESS=tailscale`. To remove it: `wsl -d Ubuntu-24.04 -u root -- maxxing uninstall`, then
`Unregister-ScheduledTask -TaskName "Harness Maxxing (WSL)"` (and `wsl --unregister Ubuntu-24.04` to delete the
distribution with everything in it).

## Install without root

Run the same command as a normal user, without `sudo`: on your own computer, or on a server where you have no
administrator rights.

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | bash
```

Everything then belongs to that user and nothing of the system is changed:

| | As root | Without root |
|---|---|---|
| Code and state | `/opt/claude-maxxing`, `/var/lib/claude-maxxing` | `~/.harness-maxxing/app`, `~/.harness-maxxing/state` |
| Workspace | `/root/maxxing` | `~/maxxing` |
| Commands (`maxxing`, `uv`, `claude`) | `/usr/local/bin` | `~/.local/bin` |
| Service | `systemctl status claude-maxxing` | `systemctl --user status claude-maxxing` |
| Access | domain, Tailscale or local | this machine only (`http://127.0.0.1:8787`), or Tailscale with `ACCESS=tailscale` |
| System packages, firewall, SSH, Caddy, swap, clock | set up by the installer | never touched |
| Sessions and jobs | one systemd unit each | plain processes of that user |

What to know:

- **System packages are not installed.** When a needed one is missing (git, curl, cron...) the installer stops and
  prints the one `sudo apt-get install ...` line to give an administrator. Optional ones (ffmpeg, the libraries
  of the browser, bubblewrap for the Sandbox mode) are listed the same way; without them the matching feature stays off.
- **It keeps running when you sign out** and starts with the machine when the system lets a user ask for it
  (`loginctl enable-linger`). When it does not, the installer says so and gives the line for an administrator.
- **A domain with HTTPS needs root** (ports 80 and 443). Put your own reverse proxy in front of `127.0.0.1:8787`, or
  install as root.
- A session can do what that user can do on the machine, no more.
- `maxxing update`, `maxxing doctor`, `maxxing deps update` and `maxxing uninstall` work the same, without `sudo`.
- It lives next to an installation made as root on the same machine without touching it (pick another `PORT`).

## Installing on a server already in use

Before changing anything, the installer looks at the server and prints a **Server check**: other
services reachable from outside, a web server on ports 80/443, an active firewall, Docker, other
scheduled jobs, an older Node.js, an existing Claude Code setup, other Telegram bridges. To only see
that report (nothing is changed):

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | bash -s -- --check
```

When the server is already in use, the installer asks for confirmation and then:

| What it finds | What it does |
|---|---|
| other services reachable from outside, or Docker | does **not** turn the firewall on (it could cut them off). Force it with `FIREWALL=1 bash /opt/claude-maxxing/install.sh --secure` |
| an active ufw firewall | keeps your rules and only adds SSH (+ 80/443 for a domain, + Tailscale) |
| nginx, Apache or another web server on 80/443 | does not install Caddy; with a domain, saves the reverse-proxy block to add to your web server in `/var/lib/claude-maxxing/reverse-proxy.conf` |
| a proxy in Docker on 80/443 (the Traefik of Dokploy or Coolify, or your own) | does not install Caddy; with a domain, opens a second private address for it (`maxxing proxy on`, see [Behind a proxy in Docker](#behind-a-proxy-in-docker)) and saves the Traefik block in `/var/lib/claude-maxxing/reverse-proxy.conf` |
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

### Behind a proxy in Docker

Dokploy, Coolify, Portainer and other tools run on a Harness Maxxing server like on any server: install them with
their own script, nothing to change in Harness Maxxing. Only the domain mode needs care, because these tools put
their own proxy (Traefik) on ports 80/443 and a proxy inside a container cannot reach `127.0.0.1` of the server.
Three ways:

- **Tailscale or local mode** for Harness Maxxing: nothing to set up.
- **The tool on another server**: Harness Maxxing reaches it through its API (key in the vault).
- **The same server, through their Traefik**: install the tool first, then Harness Maxxing with a domain. The
  installer sees Docker on 80/443 and runs `maxxing proxy on`: Harness Maxxing also listens on the address of Docker's
  bridge, port 8790 (`172.17.0.1:8790` by default: the server as seen from Docker; another private address: `maxxing proxy on 10.0.0.1:8790`) and writes the block to copy
  into Traefik's dynamic configuration folder to `/var/lib/claude-maxxing/reverse-proxy.conf`. On an existing
  install: `maxxing proxy on`, copy the block, `systemctl restart claude-maxxing`.

That second address refuses every request that does not carry the secret header of the block: another container
cannot reach the UI directly nor pass for another visitor. With an active ufw, `maxxing proxy on` lets the private
networks (where containers live) reach that port only; other machines of a private network can then reach it too, and
get the same refusal without the secret. A connection there must send its request within 10 s, and at most 512 are
open at once. If the block leaks, `maxxing proxy on --new-secret` makes it worthless (copy the new one). `maxxing proxy status` says when ufw blocks it, and when another program already held the port when the service started (the address is then not opened). Updates never touch Traefik: its configuration is yours. Docker's published ports
bypass ufw (true of every Docker server). `maxxing proxy off` closes the address.

## Unattended install

Answer every question with variables and add `ASSUME_YES=1`:

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | ACCESS=domain DOMAIN=ui.example.com ASSUME_YES=1 bash
```

| Variable | Default | Meaning |
|---|---|---|
| `REPO`, `BRANCH` | `makushingu/harness-maxxing`, `stable` | the git repository and branch the code and the updates come from (`stable` = published versions, `main` = work in progress) |
| `GH_TOKEN` | – | a read token, only for a private fork or mirror (`REPO=owner/name`) |
| `LICENSE` | – | optional: an Enterprise key, recorded at the end (same as Settings → About, see [License](license)) |
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
| `RESTORE_TRUST` | `0` | `1` = turn on what the restore brought back and kept off (scheduled jobs, extensions, Claude Code hooks, local MCP servers, customizations of the product) without asking |
| `CLAUDE_TOKEN` / `ANTHROPIC_API_KEY` | – | optional: Claude credentials stored right away |
| `FIREWALL` | `auto` | `auto` = ufw only on a server with nothing else exposed (an active ufw is kept, rules added), `1` = always, `0` = never (security updates and fail2ban are still set up) |
| `SSH_HARDEN` | `auto` | `auto` = turn SSH password logins off only when this session is proven to use a key, `1` = also when a key is installed but the session cannot be checked (console, web terminal), `0` = never touch SSH |
| `ANON_COUNT` | `ask` | the anonymous daily count of installations ([what is sent](license)): `ask` = a new installation asks in the terminal (not sent when there is no terminal), `1` = send it, `0` = never |
| `VOICE` | `local` (`off` under 3 GB of RAM) | voice messages: `local` (Whisper on the server, model downloaded in the background), `groq`, `openai` or `off` - see Voice messages. `VOICE=local` on a smaller server is asked, refused unattended |
| `TOOLS` | `background` | `background` = Node.js, Chromium, Remotion, Scrapling and the speech model are installed once the service runs, `foreground` = wait for them, `0` = skip (`maxxing deps update` later) |
| `SWAP` | `auto` | `auto` = a 2 GB `/swapfile` under 4 GB of RAM when there is no swap, on a fresh server only (not in containers, not on a server already in use or a re-run), `1` = the same on any server, `0` = never |
| `SOURCE_DIR` | – | install this local copy of the code (see "Install from a local copy") |
| `CACHE_DIR` | `/var/cache/harness-maxxing` | where downloads are kept until the install succeeds, so a re-run after a failure does not download them again |
| `ASSUME_YES` | `0` | `1` = never ask, use defaults |

## Restore on a new server

Moving to a new server? Install with your backup repository (with an Enterprise key, first free it on the old
server: Settings → About → Remove the key, see [License](license)):

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | RESTORE_FROM=owner/memory-backup RESTORE_TOKEN=<token> bash
```

The installer runs `maxxing backup restore --from owner/memory-backup --hold` after creating the
workspace: what would run code on the new server (scheduled jobs, extensions, Claude Code hooks, local MCP
servers, your customizations of the product) comes back turned off. The installer lists it and asks **Turn all
of this on now?** - say yes only if you trust everything in that repository (`RESTORE_TRUST=1` answers yes in
advance). Later: `maxxing backup release`, and `maxxing custom restore` for the customizations. See
[Backup](backup).

## Re-running, updating, uninstalling

- **Re-run** the installer at any time: every step keeps what exists (useful to change the access
  mode or repair an install).
- **Update**: `maxxing update` (or `... | bash -s -- --update`). It pulls the new version, replays
  your [customizations](customizing) on top, syncs dependencies, refreshes skills and templates
  (never your files), restarts the service, checks it answers (otherwise it rolls back) and prints
  what changed. Also available in Settings -> Updates and in the topic `system/harness` (`system/update` on older servers).
- **Uninstall**: `maxxing uninstall` (or `... | bash -s -- --uninstall`) removes the service,
  Caddy site, crontab block, product skills and the `maxxing` command. Add `--purge` to also
  delete the code, the state directory and every external component the installer added (`deps.toml`: uv, Node.js,
  the tools, Claude Code and Caddy when the installer installed them, the swap file it created),
  `--purge-workspace` to delete the workspace too (irreversible; a link, a system directory or a folder without `CLAUDE.md` nor `projects/` is kept).

## Check the installation

```bash
maxxing doctor
```
Every line is `✔` (fine), `!` (warning) or `✘` (problem), with a fix hint. See
[Troubleshooting](troubleshooting).
