---
section: Reference
---
# Command line reference

`maxxing` is installed in `/usr/local/bin`. Run `maxxing <command> --help` for every option.

## Server and setup

| Command | Purpose |
|---|---|
| `maxxing serve [--host IP] [--port N]` | run the web server (used by the `claude-maxxing` service) |
| `maxxing setup-link [--reset]` | print the one-time setup link; `--reset` forgets the password and starts the setup again |
| `maxxing password` | set a new UI password (interactive) |
| `maxxing 2fa status\|off\|forget-browsers` | two-step sign-in with Telegram: state, turn it off (the way back in when Telegram does not answer), make every browser ask again |
| `maxxing status [--json]` | version, URL, service, Claude auth, Telegram, backup, paths |
| `maxxing doctor [--json] [--live] [--offline] [--deps]` | check the installation; `--live` makes a real Claude call, `--offline` skips the update checks (GitHub, Claude Code release), `--deps` also looks up known vulnerabilities of the installed packages (osv.dev) |
| `maxxing harden [--undo] [--no-restart]` | apply (or remove) the systemd sandbox of the service, then restart it; restores the previous settings if the service does not come back (see [Security](security)) |

## maxxing init

Creates or refreshes the configuration, workspace, skills and default jobs. Safe to run again:
existing values and files are kept unless you pass a flag.
Workspace templates (default projects `general`, `system`, `tutorial`) are copied only when
missing, and a default project or topic you deleted is never re-created. Default jobs are created
once each (Memory compaction, Check for updates, Morning tasks and Renewal reminder disabled).

| Option | Effect |
|---|---|
| `--workspace PATH` | workspace folder (default `/root/maxxing`) |
| `--files-root PATH` | root of the Files page (default: home folder) |
| `--port N` | HTTP port (default 8787) |
| `--bind IP` | `127.0.0.1` or the Tailscale IP; public addresses are refused |
| `--public-url URL` | e.g. `https://ui.example.com`; `""` clears it |
| `--timezone TZ` | IANA name (default: the system zone). Keep it equal to the system zone (`timedatectl`), which cron uses - unless the server clock is kept |
| `--system-clock follow\|keep` | `follow`: changing the time zone in the UI also switches the system zone; `keep`: never touch it (shared server), jobs check their schedule in your zone |
| `--claude-dir PATH` | Claude Code folder for Harness Maxxing (default `~/.claude`; `""` = back to it). Another folder keeps it apart from a Claude Code already used on the server (passed to sessions as `CLAUDE_CONFIG_DIR`) |
| `--language en\|fr` | interface language |
| `--secret-from-stdin NAME` | store a secret read from stdin: `claude_oauth_token`, `anthropic_api_key`, `github_update_token` |
| `--no-crons` | do not create the default jobs |
| `--quiet`, `--json` | output control |

Example: `printf %s "$TOKEN" | maxxing init --quiet --secret-from-stdin claude_oauth_token`.

Restart the service after changing the port, bind address or public URL:
`systemctl restart claude-maxxing`.

## maxxing update

| Option | Effect |
|---|---|
| (none) | fetch the new version, replay your customizations on top, sync dependencies, refresh skills/templates, restart, check the service answers (else roll back), print the changelog. Exit codes: `0` done, `3` customizations conflict (nothing changed - adapt them, then `--resume`), `4` rolled back, `1` other error |
| `--resume` | finish an update after the customizations were adapted by hand (rebase completed) |
| `--rollback` | go back to the code that ran before the last update (refuses, changing nothing, while the code directory has unsaved changes) |
| `--branch B` | switch to and follow branch `B` |
| `--check` | only check: installed vs latest version and the changelog lines in between. Changes nothing; exit code 0 whether or not an update exists, 1 only when the check fails |
| `--check --notify` | also send a Telegram message (Crons thread) when an update is available; nothing happens when Telegram is not configured. Used by the weekly job "Check for updates" |
| `--check --json` | machine-readable result `{ok, current, latest, behind, available, changelog, ...}` |
| `--no-restart` | do not restart the service |
| `--preflight` | simulate the update on a throw-away copy: per customization *carries over* / *on code that changed* / *now included* / *conflicts*, plus unsaved edits, web UI edits, extensions the new version does not support, upgrade notes to apply, and a verdict (`simple` or `adapt`). Changes nothing; `--json` for machine-readable |
| `--verify` | check that every extension loads and every widget answers, and run each customization's check. Exit `0` everything works, `1` something to fix |
| `--smart` | used by the Update button: after the restart the server opens a `system/harness` session that applies the upgrade notes |

A git install (the default) fetches the new version from its git remote (a private fork or mirror: with the read
token stored as `github_update_token`); a server installed with a license key gets it from the license server
(signed archive, checked before use). After an update, the command
lists the **workspace upgrade notes** of the versions installed (`<code>/docs/upgrade/<version>.md`):
instructions for Claude to adapt your workspace. The easiest path is the topic `system/harness` (`system/update` on older servers):
say "update" and Claude checks, explains, updates after your yes, then applies these notes.

**Signed updates only (optional, git installs).** Set `"update_verify_signature": true` in
`/var/lib/claude-maxxing/config.json` and `maxxing update` installs a new version only if its commit, or a tag
pointing at it, carries a valid signature from a key git trusts on this server (`git verify-commit` /
`git verify-tag`: import the maintainer's GPG key with `gpg --import`, or point `gpg.ssh.allowedSignersFile` at
their SSH key). Otherwise the update stops before changing anything (exit code `1`, a warning in the
notifications feed and on Telegram) and the current version keeps running. `maxxing doctor` tells whether the
latest fetched version passes the check. Off by default; licensed servers always verify their signed archive
and skip this git check.

## maxxing license

| Command | Effect |
|---|---|
| `maxxing license status [--json]` | the optional Enterprise key of this server (type, email, end date) and where updates come from |
| `maxxing license activate [HM-…]` | record an Enterprise key, checked by the license server (asked hidden; `--key-from-stdin` reads it from stdin) |
| `maxxing license remove` | forget the key and free its place on the license |
| `maxxing license release` | free the key's place without forgetting it |
| `maxxing license check`, `ping` | servers still on signed archives (before 2.0.0a87) only |

See [License](license).

## maxxing video, maxxing pdf

| Command | Effect |
|---|---|
| `maxxing video new DIR` | create a Remotion project in DIR (node_modules linked to the shared install) |
| `maxxing video status` | Node.js, Remotion and the headless browser on this server (exit 1 if not ready) |
| `maxxing pdf IN.html OUT.pdf` | print an HTML file or an `https://` URL to PDF (A4, backgrounds) |
| `scrapling extract get\|fetch\|stealthy-fetch URL OUT.md` | fetch a page (HTTP / browser / stealthy browser) to Markdown, text or HTML |
| `scrapling-python SCRIPT.py` | run a scraping script with Scrapling and its browser |
| `bash /opt/claude-maxxing/install.sh --tools` | (re)install Node.js, Chromium, Remotion and Scrapling (= `maxxing deps update`) |

## maxxing import

| Command | Effect |
|---|---|
| `maxxing import --prompt [hermes\|claude-code\|openclaw\|other]` | print the prompt to give your old agent |
| `maxxing import ZIP --dry-run [--json]` | show what would be imported |
| `maxxing import ZIP [--json]` | import it (nothing overwritten; see [Import](import)) |

## maxxing custom

Changes made to the product code, recorded so updates carry them over (see [Customizing](customizing)).

| Command | Effect |
|---|---|
| `maxxing custom` / `status [--json]` | customizations, unsaved changes in the code directory, pending update |
| `maxxing custom save "TITLE" --why "REASON" [--files F…] [--check "CMD"]` | commit the uncommitted changes as one customization (refused under `web/`); `--check` = a command that succeeds while it works, run after every update |
| `maxxing custom check ID "CMD"` | set (or clear with `""`) the check of a customization |
| `maxxing custom drop ID` | remove one customization |
| `maxxing custom export` | rewrite `<workspace>/CUSTOMIZATIONS.md` and `customizations/*.patch` |
| `maxxing custom restore [--from DIR]` | re-apply the saved patches (new server) |

## maxxing deps

The external components (`server/maxxing/deps.toml`: uv, Python, Node.js, Claude Code, Caddy, Scrapling, Chromium,
Remotion, the Whisper models, Garage). As root.

| Command | Effect |
|---|---|
| `maxxing deps list [--json]` | installed and expected version of each one (exit 1 when one is missing or outdated) |
| `maxxing deps verify [NAME...]` | checksums of the installed binaries, files not owned by root or writable by others |
| `maxxing deps update [NAME...] [--notify]` | install the pinned versions next to the old ones, switch once they work (every `maxxing update` does it) |
| `maxxing deps remove NAME [--force]` | delete what the manifest lists for it (`--force` for uv, Python, Claude Code) |
| `maxxing deps clean [--dry-run] [--caches]` | old versions, unused browsers, leftovers, oversized logs (weekly job); `--caches` also empties root's uv / npm / pip / npx caches, shared with the other tools of the server |
| `maxxing deps check [--notify]` | known vulnerabilities (osv.dev) in the lockfiles and components (weekly job, notification) |

## maxxing uninstall

| Option | Effect |
|---|---|
| (none) | remove the service, Caddy site, managed crontab block, product skills and `/usr/local/bin/maxxing`; keep code, state and workspace |
| `--purge` | also delete the code (`/opt/claude-maxxing`), the state (`/var/lib/claude-maxxing`) and the external components of `deps.toml` (uv, Node.js, the tools; Claude Code and Caddy when the installer installed them; its swap file) |
| `--purge-workspace` | also delete the workspace (irreversible) |
| `--yes` | do not ask for confirmation |

## Scheduled jobs

| Command | Purpose |
|---|---|
| `maxxing cron list` | jobs, schedules, last results |
| `maxxing cron run <id>` | run a job now in your terminal and wait for it; `--detach` starts it in its own systemd unit with the memory limits and returns (what the crontab calls); `--if-due` runs it only if its schedule matches now in your zone (server clock kept) |
| `maxxing cron sync` | rewrite the managed crontab block from the job list |

## Notifications feed

| Command | Purpose |
|---|---|
| `maxxing feed post "Title" [--body] [--level info\|success\|warning\|error] [--source NAME] [--url] [--dedupe KEY] [--group KEY] [--quiet] [--json]` | add an event (dashboard, and Telegram per the source's rule); `--dedupe` ignores a repeat, `--group` folds repeats |
| `maxxing feed list [--unread] [--source] [--limit] [--json]` | latest events |
| `maxxing feed read-all` | mark everything read |
| `maxxing packs list [--json]` | starter projects and whether they are installed |
| `maxxing packs add ID [ID...] [--json]` | add starter projects (never overwrites: only missing files are added; jobs created disabled) |

## Keys

| Command | Purpose |
|---|---|
| `maxxing keys list [--json]` | names, notes and whether each key is exposed (never the values) |
| `maxxing keys get NAME` | print a value (exit code 1 when missing) |
| `printf %s "$VALUE" \| maxxing keys set NAME [--note TEXT] [--no-expose]` | create or update a key; the value comes from stdin, never from the command line. A new key is exposed (environment variable of every session and shell job) unless `--no-expose`; an update keeps its note and exposure |
| `maxxing keys delete NAME` | remove a key |
| `maxxing infra status` / `infra list [--kind K] [--json]` | the Infra inventory: sources, problems, every site / database / bucket / domain / server (last snapshot) |
| `maxxing infra refresh` | read everything now (this server, other servers over SSH, Cloudflare, Hostinger, URL checks) |
| `maxxing infra site add NAME (--dir D \| --port N) [--host H] [--dns] [--project P]` | put a site online: `https://<Harness address>/<NAME>/` (sandboxed) or its own host; `site remove`, `site list`, `reserved` |
| `maxxing infra db install` / `db create NAME` / `db sqlite PATH` / `db backup` | PostgreSQL on localhost, one database + user per app (URL in the vault as `DB_<NAME>_URL`), nightly backups |
| `maxxing infra bucket install` / `bucket create NAME [--public]` | S3 buckets on this server (Garage), keys in the vault as `S3_<NAME>_*` |
| `maxxing infra server add NAME HOST [--user U] [--key K]` | read another server over SSH (`server remove`, `server list`) |
| `maxxing infra annotate ID [--project P] [--note T] [--hide\|--show]` | attach a resource to a project, note it, hide it |

Scripts read keys from the environment (`os.environ["NAME"]`, `$NAME`); a script that renews a token
(a 24-hour shop token, a webhook secret it just created) writes it back with `maxxing keys set`.

## MCP servers

| Command | Purpose |
|---|---|
| `maxxing mcp list [--json] [--no-check]` | every MCP server of Claude Code, where it applies and its state (asks Claude Code first, a few seconds) |
| `maxxing mcp add NAME URL [--where projects/P/topics/T] [--header 'Name: value'] [--sse]` | add a server by address, for every session or one topic; secrets as `${KEY}` from the vault |
| `maxxing mcp add NAME --command 'npx -y pkg' [--env KEY=VALUE] [--where …]` | add a local program |
| `maxxing mcp remove NAME [--where …]` | remove it |

OAuth sign-ins (state "To connect") are done in Settings -> MCP -> **Connect**. See [MCP servers](28-mcp.md).

## Memory and sessions

| Command | Purpose |
|---|---|
| `maxxing memory [--json]` | every memory.md with its line count and the line limit (Settings -> Memory) |
| `maxxing sessions compact-logs [--dry-run]` | clip the tool outputs of existing session logs and drop the bulky Claude start-up lists and progress lines (frees disk space; `--dry-run` only reports what would be saved) |
| `maxxing sessions token-report [--days N] [--json]` | where the tokens of your sessions go, read from Claude Code's transcripts: context size per call, cache rewritten after an idle hour or a model switch, the tools whose outputs fill the context, and what automatic compaction at 400k / 300k / 250k / 200k would have saved on the same calls |

## Backup

| Command | Purpose |
|---|---|
| `maxxing backup status [--json]` | configuration and last run |
| `maxxing backup run` | back up now (exit code 2 if a secret was found) |
| `maxxing backup restore [--ref COMMIT]` | restore the whitelisted files |
| `maxxing backup restore --from OWNER/NAME [--token T]` | new server: configure an existing backup repository, then restore (token also from `$MAXXING_GITHUB_TOKEN`) |

## Telegram

| Command | Purpose |
|---|---|
| `maxxing telegram status [--json]` | bot, chat, threads, settings, last error |
| `maxxing telegram test` | send a test message |
| `maxxing voice status [--json]` | voice messages: engine, model, readiness |
| `maxxing voice set [--engine] [--model] [--language]` | change the voice settings |
| `maxxing voice download [model]` | download a local speech model |
| `maxxing voice transcribe <file>` | transcribe an audio file with the configured engine |

## Installer

```bash
curl -fsSL https://get.harness-maxxing.com | bash          # install / repair (from the public git repository, no key)
bash /opt/claude-maxxing/install.sh --update                # = maxxing update
bash /opt/claude-maxxing/install.sh --uninstall [--purge] [--purge-workspace]
bash /opt/claude-maxxing/install.sh --tools                 # (re)install Node.js, Chromium, Remotion, Scrapling (= maxxing deps update)
SOURCE_DIR=/path/to/copy bash /path/to/copy/install.sh      # install a local copy of the code (no download)
bash /opt/claude-maxxing/install.sh --secure                # security updates, fail2ban, firewall (FIREWALL=0: no firewall)
curl -fsSL https://get.harness-maxxing.com | bash -s -- --check   # look at the server first, change nothing
```
Variables: see [Installation](installation).

## Environment variables

| Variable | Use |
|---|---|
| `MAXXING_STATE` | state directory (default `/var/lib/claude-maxxing`); set by the service and the CLI wrapper |
| `MAXXING_GITHUB_TOKEN` | token for `maxxing backup restore --from` |
| `NO_COLOR` | plain output |
