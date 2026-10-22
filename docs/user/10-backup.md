---
section: Connectivity
---
# Memory backup

Your CLAUDE.md and memory.md files are the most valuable part of the installation: months of
decisions, preferences and context. The backup pushes them every day to a **private GitHub
repository**, with full history.

## What is saved

Only a **whitelist**, relative to the workspace:

- always: every `CLAUDE.md` and `memory.md`, plus `CUSTOMIZATIONS.md` and `customizations/*.patch`
  (your changes to the product code, see [Customizing](customizing));
- by default also: `**/NOTES.md`, `tasks.json`, `projects/*/topics/*/accounts.md` (the subscriptions inventory, kept in `general/inbox`), `extensions/**`, `.claude/skills/**`
  (editable in Settings -> Backup);
- plus non-secret settings (time zone, language, default model, dashboard layout...) and your
  scheduled jobs, in a `_maxxing/` folder.

Never saved, even if a pattern matches: `secrets.json`, keys, `.env` files, private keys,
credentials, logs, `attachments/`, `.git`, `node_modules`, virtual environments, and files over 5 MB.

## Safety checks

- **Secret scanner**: before every commit, each file is scanned for real secret *formats*
  (Anthropic and OpenAI-style keys, GitHub tokens, Slack tokens, AWS keys, Telegram bot tokens,
  Shopify tokens, Stripe keys and webhook secrets, Google API keys, npm, Hugging Face and SendGrid tokens, JSON web
  tokens, private keys (PGP too), a password in an address (`postgres://user:Pa55word@host`) and a password
  written next to its label such as `password: Hunter2xyz9` or `"password": "…"` - useful in `accounts.md`; UTF-16
  files are read too). If one is found the backup **stops before pushing** and tells you
  which file and which kind of secret (never the value). Remove it from the file – keep only the
  key name, store the value in Settings -> Keys – and run again.
- **Private only**: the repository must be private; this is checked when you configure it and
  again before every push. If it becomes public, backups stop.
- The GitHub token is stored in `secrets.json` (mode 600) and never written in a git config file.

## Setup (Settings -> Backup)

1. On GitHub, create a **fine-grained personal access token**:
   - Repository access: only the backup repository (or all repositories if you want Claude
     Maxxing to create it);
   - Permissions: **Contents: read and write**, **Metadata: read**; add **Administration: read and
     write** only if the repository must be created for you.
2. In Settings -> Backup enter `owner/name` and the token; tick "create the repository" if it does
   not exist yet.
3. Click **Back up now** and check the commit on GitHub.

A daily job **Memory backup** is created (default 04:40). Change the schedule and the whitelist in
Settings -> Backup.

## Restore

- **Settings -> Backup -> Restore** (or `maxxing backup restore`): restores the whitelisted files
  of the latest commit (or a chosen one). Files that would be overwritten are first moved to the
  trash (`/var/lib/claude-maxxing/trash/backup-restore-<date>/`).
- On a **new server** (no session started yet: the installer's restore, a move to another server) everything comes
  back as it was, jobs and extensions on. On a server **already in use**, code that runs on the server comes back
  **turned off**: scheduled jobs (shell or Claude) this server does not
  already have exactly the same, and extensions any of whose code files the restore writes (turned off before their
  files are written: their code never runs, even for a moment); Claude Code `hooks` and the other settings that run
  a command or redirect Claude (`statusLine`, `apiKeyHelper`, `env`, project MCP servers...) are
  removed from restored `.claude/settings.json` files (kept in `hooks-held.json` in the restore's trash folder); files
  the backup list of this server does not cover (a `.mcp.json`, a script...) are not written but kept aside in the
  `outside` folder of the restore's trash; local MCP servers (a command Claude Code starts at every turn) are
  not added back - they are saved in `mcp-held.json` in the restore's trash folder, add the ones you trust again in
  **Settings → MCP** (remote servers, an URL, are restored). Restored skills and customizations are listed to review
  before use. A notification lists all of it; check them, then turn them on in Crons and Extensions. Anyone able to push to the backup repository could otherwise
  get their code run here. The memory backup job itself stays on.
- One old version of one file: browse its history on GitHub and copy it back.

## Moving to a new server

```bash
curl -fsSL https://get.harness-maxxing.com | RESTORE_FROM=owner/name RESTORE_TOKEN=<token> bash
```

The installer restores your memory, settings and jobs. Then sign in, re-enter what is never backed
up (Claude token, Telegram bot token, Keys), and re-link Telegram – stop the old server first, a
bot can only be served by one server.

## Command line

```bash
maxxing backup status [--json]
maxxing backup run
maxxing backup restore [--ref <commit>]
maxxing backup restore --from owner/name      # token from $MAXXING_GITHUB_TOKEN or prompted
```
