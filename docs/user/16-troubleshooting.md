---
section: Reference
---
# Troubleshooting


## The dot at the bottom of the sidebar

It turns orange or red when something needs you (disk, memory, a failed scheduled job, a stopped service, Claude
not connected, an old backup). Click it for the list. **Seen** on an issue stops it from counting in the dot (it
stays in the list, greyed): it comes back by itself when it changes - another job failing, for example - or after
24 hours if it is still there. The arrow next to a seen issue counts it again. Seen marks are kept on the server,
so they hold on every device.

## Start with the doctor

```bash
maxxing doctor            # human readable, exit code 1 if something fails
maxxing doctor --json     # for scripts and Claude
maxxing doctor --live     # also makes a real one-line Claude call
```

Or open a session and say "something is wrong, use the maxxing-doctor skill": Claude reads the
checks and the logs, explains, and fixes what is safe to fix.

| Check | Meaning |
|---|---|
| python, uv | runtime and toolchain |
| claude_cli, claude_auth | Claude Code installed and signed in |
| claude_version | Claude Code behind its latest release (info; releases carry security fixes). With Settings -> Claude -> Update Claude Code automatically (off by default) the server installs the stable release by itself when nothing has run for 10 min; the hint says why it did not - fix: `claude update` |
| skill_listing | how many skills Claude sees in every prompt and their size; past Claude Code's budget the least used ones lose their description (info) - see [Skills](skills) |
| deps | with `--deps`: installed packages (server, web, video tools) with a known vulnerability, from osv.dev |
| setup | first sign-in done |
| service, http | `claude-maxxing` running and answering |
| security | firewall (ufw), fail2ban and automatic security updates active - warning only; fix: `bash /opt/claude-maxxing/install.sh --secure` |
| state_files | a damaged `config.json` / `secrets.json` was found and replaced; its copy (`*.damaged-<date>`) is kept next to it - compare, restore what is missing (keys: Settings -> Keys), delete the copy |
| tools | Node.js, Remotion, Scrapling and the shared Chromium ready (videos, PDFs, scraping) - warning only; fix: `maxxing deps update` |
| deps_files | external components (`maxxing deps list`): ✘ when a binary changed since it was installed or a file is not owned by root (another user could replace it), ! when one is missing or not at the version of this release; fix: `maxxing deps update` |
| bind | not listening on a public address |
| public_url, caddy | your URL reachable, Caddy config valid |
| caddy_site | the Caddy site written by an older installer: `X-Frame-Options DENY` (PDF previews in Files stay blank) or a body limit below the 2 GB uploads - the fix command edits `/etc/caddy/claude-maxxing.caddy` and reloads Caddy |
| crontab | every enabled job present in the crontab |
| timezone | configured time zone = system time zone (cron uses the system one), or server clock kept (`system_clock = keep`) |
| telegram, backup | configured, linked, recent backup |
| disk, workspace | free space, workspace writable |
| memory | RAM and swap; a server under 4 GB without swap gets a warning (each running Claude turn uses 200-300 MB, local voice, browsers and renders more) and the commands to add a 2 GB swap file |
| skills, web | product skills and the web UI build present |
| git | local changes, updates available |

## Logs

```bash
journalctl -u claude-maxxing -n 100 --no-pager     # server
journalctl -u caddy -n 50 --no-pager               # HTTPS proxy
systemctl list-units 'maxxing-*'                   # running Claude turns
journalctl -u maxxing-<id8> --no-pager             # one turn
maxxing cron list                                  # jobs and their last result
```
Logs are also visible in Settings -> System.

## Common problems

**A command was "Killed" (exit code 137), or a heavy render stopped.**
It ran out of memory. Each session and scheduled job may use at most 75 % of the server's RAM: past it the
kernel stops the biggest process of that session only, and Claude tells you and continues. The UI and the
other sessions normally keep working (the cap is per session: several heavy sessions at once can still fill the
RAM). Ask Claude for a lighter way (a lower resolution, a render in parts, fewer
inputs at once). To change the cap, set `unit_memory_max` in `/var/lib/claude-maxxing/config.json`
(`"4G"`, `"90%"`, or `""` for none): it applies to the next turns and jobs. All the scheduled jobs running at once
also share `jobs_memory_max` (default 75 %, applied by `maxxing init`). `journalctl -k | grep -i oom`
shows what was killed. If the whole turn stopped, the session says "The turn was stopped: the server ran out
of memory".

**Something you started on the server (a dev site, an API on port 3000…) is not reachable.**
The firewall only lets SSH, 80/443 and Tailscale in. Open the port on purpose (`ufw allow 3000/tcp`),
or better, serve it behind Caddy on your domain.

**The installer stops at "Claude Code".**
It prints the end of Anthropic's installer output and the likely cause above the error (full log:
`/tmp/maxxing-claude-install.log`). Usual causes: `downloads.claude.ai` unreachable from the server
(DNS, the provider's outgoing firewall, a temporary outage - it already retried once), a country
where Claude is not available (https://www.anthropic.com/supported-countries), a full disk, or an
architecture other than x86_64 / arm64. Fix it and re-run `curl -fsSL https://get.harness-maxxing.com | bash`:
finished steps are skipped. (Running it after `sudo -i` is fine: Claude Code is installed for root.)

**The installer says "could not record the Enterprise key".**
Only with `LICENSE=HM-…` (no key is needed: leave it out). The install itself is done; run
`maxxing license activate` to see why: unknown key (check it in your license email), key revoked, or **already
active on another server** (one key = one server): run `maxxing license release` on the one you no longer use.

**`maxxing update` says the server "still runs the code of a signed archive".**
A server installed with a key before 2.0.0a87 moves to the public git repository by itself; the message says what
holds it back (no network, edits of `web/` in the code folder, an update being finished). Fix it and run
`maxxing update` again.

**The page does not load.**
`systemctl status claude-maxxing`. If it is failing, read the journal. After a manual `git pull`,
run `maxxing update` instead (it syncs the dependencies). `systemctl restart claude-maxxing` is safe:
running Claude turns continue in their own units.

**Certificate error / domain unreachable.**
The domain's DNS record must point to the server (`getent ahosts ui.example.com`), and ports 80 and
443 must be open (`ufw status`, plus your hosting provider's firewall). Caddy obtains the
certificate on the first request: `journalctl -u caddy` shows why it failed. Validate the config:
`caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`.

**Lost password.** On the server: `maxxing password`. Or start over with a new setup link:
`maxxing setup-link --reset`.

**"Too many attempts".** Wait 15 minutes, or restart the service.

**Lost setup link.** `maxxing setup-link`.

**Every session fails at once.** Claude is not signed in or the token expired: Settings -> Claude ->
Test, or `maxxing doctor --live`. Renew with `claude setup-token`.

**A session stays "running".** Press Stop. If it persists: `systemctl list-units 'maxxing-*'` and
read that unit's journal.

**A note says the conversation could not be resumed.** The Claude transcript was missing; a fresh
context was started automatically. The history stays visible.

**A job did not run.** `maxxing cron list` (enabled? last result?), `crontab -l` (is its line in the
managed block?), `maxxing cron sync`, `systemctl status cron`. Run it by hand: `maxxing cron run <id>`.

**A job runs at the wrong hour.** The cron daemon uses the system time zone, the UI uses the one
from Settings -> General. `maxxing doctor` shows both. On a shared server, keep the server clock
and let jobs follow your zone: `maxxing init --system-clock keep`. Otherwise align them:
`timedatectl set-timezone <Zone> && systemctl restart cron`, and
`maxxing init --timezone <Zone> && systemctl restart claude-maxxing`.

**Telegram is silent.** `maxxing telegram status` shows the last error; `maxxing telegram test`.
See [Telegram](telegram).

**Backup failed.** `maxxing backup status`. Expired token, repository made public, or a secret found
in a file (the message names the file). See [Backup](backup).

**Disk full.** Check `~/.claude/projects` (transcripts), attachments in topics, and the journal
(`journalctl --vacuum-size=200M`). Delete with care: transcripts are needed to resume sessions.

**The UI looks outdated after an update.** Reload the page; the app's HTML is never cached, a
reload is enough.

**Tailscale URL stops working after a reboot.** If the Tailscale IP changed, re-run the installer
with `ACCESS=tailscale` (or `maxxing init --bind <ip> --public-url http://<ip>:8787` and restart).

## Still stuck?

Collect `maxxing doctor --json` and the last 200 lines of `journalctl -u claude-maxxing` (check that
they contain no secrets) and contact support.
