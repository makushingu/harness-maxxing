---
name: maxxing-setup
description: Guide the setup of a Harness Maxxing installation from the terminal. Use when the user says "set up Harness Maxxing", just ran the installer, wants to finish/verify an install, change the access mode (domain, Tailscale, local), sign Claude in, or configure Telegram/backup for the first time.
---

# Set up Harness Maxxing

You are on the server where Harness Maxxing is installed (code `{{CODE_DIR}}`, state
`{{STATE_DIR}}`, workspace `{{WORKSPACE}}`, service `claude-maxxing`, CLI
`maxxing`). Work step by step, explain briefly what you do, ask before anything destructive.

## 1. Diagnose
Run `maxxing doctor --json` and read `checks[]` (`level`: ok | warn | fail | info, with `fix`).
Summarise for the user: what works, what fails, what is optional. Then fix in this order.

## 2. Service and access
- `service` / `http` fail -> follow the `maxxing-doctor` skill (logs: `journalctl -u claude-maxxing -n 80 --no-pager`).
- Access modes (the server never listens on 0.0.0.0):
  - **domain** (recommended): needs a DNS A/AAAA record pointing to this server and ports 80/443 open.
    Re-run the installer non-interactively:
    `ACCESS=domain DOMAIN=ui.example.com ASSUME_YES=1 bash {{CODE_DIR}}/install.sh`
    (it is idempotent: installs Caddy, writes `/etc/caddy/claude-maxxing.caddy`, sets `public_url`).
    Check DNS first: `getent ahosts ui.example.com` vs `hostname -I`.
  - **tailscale**: `tailscale status` must be up; re-run the installer with `ACCESS=tailscale`.
  - **local**: browse through an SSH tunnel: `ssh -N -L 8787:127.0.0.1:8787 root@<server>` then
    http://127.0.0.1:8787.
  If the installer script is not at hand: `bash {{CODE_DIR}}/install.sh` (same variables).
- `bind` fail (public address) -> `maxxing init --bind 127.0.0.1 && systemctl restart claude-maxxing`.

## 3. First sign-in
`setup` warn -> `maxxing setup-link` prints a one-time link `…/setup?token=…`; give it to the user
(it creates the UI password). Password lost: `maxxing password` (interactive, ask the user to run it)
or `maxxing setup-link --reset`.

## 4. Claude authentication (`claude_auth`)
Sessions need Claude credentials. Options, best first:
1. Long-lived token: the user runs `claude setup-token` on any machine with a browser, then pastes
   the token in **Settings -> Claude** (or onboarding step 2). From the terminal:
   `printf %s '<token>' | maxxing init --quiet --secret-from-stdin claude_oauth_token`
2. API key (pay-as-you-go): Settings -> Claude, or `--secret-from-stdin anthropic_api_key`.
3. Interactive CLI login: run `claude` once on the server and use `/login`.
Never echo a token back in the conversation or write it to a file other than through these commands.
Verify with `maxxing doctor --live` (makes one real one-line call).

## 5. Preferences
- Time zone (schedules, daily figures): the cron daemon uses the **system** zone, the UI the config
  zone - keep them equal (doctor check `timezone`). To change both:
  `timedatectl set-timezone Europe/Paris && systemctl restart cron` then
  `maxxing init --timezone Europe/Paris && systemctl restart claude-maxxing`. Language: `--language en|fr`.
- Workspace path is in `maxxing status`.

## 6. Telegram (optional)
Recommend the UI wizard: **Settings -> Telegram** (bot token from @BotFather -> link code ->
threads). Details and troubleshooting: `maxxing-telegram` skill. Check: `maxxing telegram status`.

## 7. Memory backup (strongly recommended)
UI wizard **Settings -> Backup** (private GitHub repo + fine-grained token; it can create the repo).
Details: `maxxing-backup` skill. Check: `maxxing backup status`.

## 8. Finish
Run `maxxing doctor` again and give a short summary:
- URL to open, sign-in done or link to use;
- Claude auth method;
- Telegram / backup: configured or "optional, Settings -> …";
- remaining warnings with their fix.
Suggest a first step: open Sessions, pick `tutorial / 1-first-steps` (interactive lessons) or
`general / inbox`, start a conversation. Product questions later: topic `system/help`.
Record durable facts about this server (access mode, domain) in the global memory (`memory` skill).
