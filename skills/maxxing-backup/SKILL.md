---
name: maxxing-backup
description: Configure, run, check or restore the Harness Maxxing memory backup (private GitHub repository), explain what is saved and the secret scanner, and move an installation to a new server. Use when the user mentions backup, restore, losing the server, migration, or the backup check fails.
---

# Memory backup

The most valuable part of the installation is the knowledge in the workspace (CLAUDE.md, memory.md,
notes, tasks, extensions, skills). The backup copies a **whitelist** of those files into a git
working copy and pushes it to a **private** GitHub repository, daily (default 04:40, server time
zone) and on demand.

## What is saved
Whitelist (Settings -> Backup, `backup.include` in config.json), default:
`**/CLAUDE.md`, `**/memory.md`, `**/NOTES.md`, `tasks.json`, `extensions/**`, `.claude/skills/**`.
Never saved: secrets.json, keys, `.env`, credentials, session logs, attachments, project code.
Before each commit a **secret scanner** looks for real secret formats (Anthropic/OpenAI keys,
GitHub tokens, AWS keys, Slack tokens, private keys…); if one is found the backup **refuses to
push** and reports the file: remove the secret (store it in Settings -> Keys) and run again.
The push is also refused if the repository is (or became) public.

## Configure (UI wizard: Settings -> Backup)
1. On GitHub create a **fine-grained token**: Repository access = only the backup repo (or "All
   repositories" if the wizard must create it), permissions **Contents: Read and write**,
   **Metadata: Read** (+ **Administration: Read and write** only to let the wizard create the repo).
2. Settings -> Backup: repo `owner/name`, token, "create if missing" -> the server checks access and
   that the repo is private.
3. Run a first backup and check the commit on GitHub.

## Operate
```bash
maxxing backup status      # repo, private, schedule, last run (at, ok, commit, files, error)
maxxing backup run         # back up now
maxxing doctor             # "backup" check warns if the last success is older than 48 h
```
Schedule and whitelist: Settings -> Backup. History: Settings -> Backup -> history.

## Restore
- Same server, files damaged: Settings -> Backup -> Restore (or `maxxing backup restore`). Current
  files are moved to the trash first; only whitelisted files are written.
- A single older version of one file: the repo is plain git - browse it on GitHub (history of the
  file) and copy the content back.

## Move to a new server
On the new server run the installer with the restore variables:
```bash
curl -fsSL https://get.harness-maxxing.com | RESTORE_FROM=owner/name RESTORE_TOKEN=<token> bash   # no key needed (LICENSE=HM-… for signed releases)
```
(or answer "yes" to the restore question). It installs, initialises an empty workspace, then
restores the backup over it. Then: sign in with the new setup link, re-enter secrets that were not
backed up (Claude token, Telegram bot token, Keys), re-link Telegram (a bot can only be polled by
one server - stop the old one first), re-enable the backup.

## Troubleshooting
| Error | Fix |
|---|---|
| 401 / 403 from GitHub | token expired or lacks Contents: write on that repo -> new token in Settings -> Backup |
| repo is public | make it private on GitHub, then run again |
| secret detected in `<file>` | remove it from the file (keep only the key name), run again |
| non-fast-forward | the repo was edited elsewhere -> `maxxing backup run` again; ask before forcing anything |
