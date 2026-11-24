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
| `maxxing proxy on [HOST:PORT] [--domain D] [--new-secret]` / `proxy off` / `proxy status [--json]` | a second private listen address (default `172.17.0.1:8790`) for a reverse proxy in Docker, guarded by a secret header; writes the Traefik block to `<state>/reverse-proxy.conf` (`--new-secret`: a new header, copy the block again); `off` also forgets the secret and the block; restart the service after (see [Installation](installation#behind-a-proxy-in-docker)) |
| `maxxing harden [--undo] [--no-restart]` | apply (or remove) the systemd sandbox of the service, then restart it; restores the previous settings if the service does not come back (see [Security](security)) |

## maxxing init

Creates or refreshes the configuration, workspace, skills and default jobs. Safe to run again:
existing values and files are kept unless you pass a flag.
Workspace templates (default projects `general`, `system`, `tutorial`) are copied only when
missing, and a default project or topic you deleted is never re-created. Default jobs are created
once each (Memory compaction, Check for updates, and Morning tasks, which starts disabled).
As root on systemd it also writes the slices of the [CPU priorities](settings-and-keys#cpu-priorities)
(`maxxing-live.slice`, `maxxing-turns.slice`, `maxxing-jobs.slice`; the server joins its slice at its next restart).

| Option | Effect |
|---|---|
| `--workspace PATH` | workspace folder (default `/root/maxxing`) |
| `--files-root PATH` | root of the Files page (default: home folder) |
| `--port N` | HTTP port (default 8787) |
| `--bind IP` | `127.0.0.1` or the Tailscale IP; public addresses are refused |
| `--public-url URL` | e.g. `https://ui.example.com`; `""` clears it; a malformed URL is refused |
| `--timezone TZ` | IANA name (default: the system zone). Keep it equal to the system zone (`timedatectl`), which cron uses - unless the server clock is kept. An unknown zone is refused |
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
| `--auto` | used by the automatic update (Settings -> Updates): after the restart, a notification says which upgrade notes are left to apply |

Every install fetches the new version from its git remote (a private fork or mirror: with the read token stored as
`github_update_token`). A server installed with a key before 2.0.0a87 first moves to the public git repository by
itself (see [License](license)). After an update, the command
lists the **workspace upgrade notes** of the versions installed (`<code>/docs/upgrade/<version>.md`):
instructions for Claude to adapt your workspace. The easiest path is the topic `system/harness` (`system/update` on older servers):
say "update" and Claude checks, explains, updates after your yes, then applies these notes.

**Signed updates only (optional).** Set `"update_verify_signature": true` in
`/var/lib/claude-maxxing/config.json` and `maxxing update` installs a new version only if its commit, or a tag
pointing at it, carries a valid signature from a key git trusts on this server (`git verify-commit` /
`git verify-tag`: import the maintainer's GPG key with `gpg --import`, or point `gpg.ssh.allowedSignersFile` at
their SSH key). Otherwise the update stops before changing anything (exit code `1`, a warning in the
notifications feed and on Telegram) and the current version keeps running. `maxxing doctor` tells whether the
latest fetched version passes the check. Off by default.

## maxxing license

| Command | Effect |
|---|---|
| `maxxing license status [--json]` | the optional Enterprise key of this server (type, email, end date) and where updates come from |
| `maxxing license activate [HM-…]` | record an Enterprise key, checked by the license server (asked hidden; `--key-from-stdin` reads it from stdin) |
| `maxxing license remove` | forget the key and free its place on the license |
| `maxxing license release` | free the key's place without forgetting it |

See [License](license).

## maxxing video, maxxing pdf

| Command | Effect |
|---|---|
| `maxxing video new DIR` | create a Remotion project in DIR (node_modules linked to the shared install) |
| `maxxing video render [DIR] [--id Intro] [--out out/video.mp4]` | render a Remotion project with the background priority (through `maxxing heavy`) |
| `maxxing video status` | Node.js, Remotion and the headless browser on this server (exit 1 if not ready) |
| `maxxing pdf IN.html OUT.pdf` | print an HTML file or an `https://` URL to PDF (A4, backgrounds) |
| `scrapling extract get\|fetch\|stealthy-fetch URL OUT.md` | fetch a page (HTTP / browser / stealthy browser) to Markdown, text or HTML |
| `scrapling-python SCRIPT.py` | run a scraping script with Scrapling and its browser |
| `bash /opt/claude-maxxing/install.sh --tools` | (re)install Node.js, Chromium, Remotion and Scrapling (= `maxxing deps update`) |

## maxxing heavy

| Command | Effect |
|---|---|
| `maxxing heavy COMMAND [ARGS…]` | run a long, CPU-hungry command (render, encode, build, compression) with the background priority: when the processor is full it goes after the interface and the sessions, and is never slowed otherwise. Same terminal, same output, same exit code. Runs in a scope of `maxxing-jobs.slice` (named after the session or job that started it); without systemd or as a normal user, under `nice -n 10` and `ionice -c3` |

See [CPU priorities](settings-and-keys#cpu-priorities).

## maxxing import

| Command | Effect |
|---|---|
| `maxxing import --prompt [hermes\|claude-code\|openclaw\|other]` | print the prompt to give your old agent |
| `maxxing import ZIP --dry-run [--json]` | show what would be imported |
| `maxxing import ZIP [--json]` | import it (nothing overwritten; see [Import](import)), then print the message that lets a session finish (tasks, scheduled jobs, keys) |

## maxxing custom

Changes made to the product code, recorded so updates carry them over (see [Customizing](customizing)).

| Command | Effect |
|---|---|
| `maxxing custom` / `status [--json]` | customizations, unsaved changes in the code directory, the customized interface, pending update |
| `maxxing custom save "TITLE" --why "REASON" [--files F…] [--check "CMD"]` | commit the uncommitted changes as one customization (refused under `web/dist`, the shipped interface build); `--check` = a command that succeeds while it works, run after every update |
| `maxxing custom check ID "CMD"` | set (or clear with `""`) the check of a customization |
| `maxxing custom drop ID` | remove one customization |
| `maxxing custom export` | rewrite `<workspace>/CUSTOMIZATIONS.md` and `customizations/*.patch` |
| `maxxing custom restore [--from DIR]` | re-apply the saved patches (new server) |
| `maxxing custom build [--force] [--json]` | typecheck and build the customized interface into the state directory (shown at once; the first build installs the build tools) |

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
| `maxxing deps check [--notify] [--json]` | known vulnerabilities (osv.dev) in the lockfiles and components (weekly job, notification); exit code 1 when something is vulnerable, 0 with `--notify` (the notification reports it) |

## maxxing uninstall

| Option | Effect |
|---|---|
| (none) | remove the service, Caddy site, managed crontab block, product skills and `/usr/local/bin/maxxing`; keep code, state and workspace |
| `--purge` | also delete the code (`/opt/claude-maxxing`), the state (`/var/lib/claude-maxxing`) and the external components of `deps.toml` (uv, Node.js, the tools; Claude Code and Caddy when the installer installed them; its swap file); a code or state directory that is a link is kept |
| `--purge-workspace` | also delete the workspace (irreversible; kept if it is a link, a system directory or has no `CLAUDE.md` nor `projects/`) |
| `--yes` | do not ask for confirmation |

## Scheduled jobs

| Command | Purpose |
|---|---|
| `maxxing cron list` | jobs, schedules, last results |
| `maxxing cron run <id>` | run a job now in your terminal and wait for it; `--detach` starts it in its own systemd unit with the memory limits and returns (it runs it here if systemd refuses) (what the crontab calls); `--if-due` runs it only if its schedule matches now in your zone (server clock kept) |
| `maxxing cron sync` | rewrite the managed crontab block from the job list |

## Notifications feed

| Command | Purpose |
|---|---|
| `maxxing feed post "Title" [--body] [--level info\|success\|warning\|error] [--source NAME] [--url] [--dedupe KEY] [--group KEY] [--quiet] [--json]` | add an event (dashboard, and Telegram per the source's rule); `--dedupe` ignores a repeat, `--group` folds repeats |
| `maxxing feed list [--unread] [--source] [--limit] [--json]` | latest events |
| `maxxing feed read-all` | mark everything read |
| `maxxing packs list [--json]` | starter projects and whether they are installed |
| `maxxing packs add ID [ID...] [--json]` | add starter projects (never overwrites: only missing files are added; jobs created disabled) |

## Team

| Command | Purpose |
|---|---|
| `maxxing team send NAME MESSAGE... [--file PATH] [--json]` | send a message to a contact or a group, in your name (name: case and accents ignored, a unique beginning is enough, or a contact's address; `-` reads the message from stdin; `--file` repeatable). Team must be on |
| `maxxing team list [--json]` | the contacts and groups you can write to |

## Keys

| Command | Purpose |
|---|---|
| `maxxing keys list [--json]` | names, notes and whether each key is exposed, files marked `file` (never the values or contents) |
| `maxxing keys get NAME` | print a value (exit code 1 when missing) |
| `printf %s "$VALUE" \| maxxing keys set NAME [--note TEXT] [--no-expose]` | create or update a key; the value comes from stdin, never from the command line. A new key is exposed (environment variable of every session and shell job) unless `--no-expose`; an update keeps its note and exposure; a multi-line value (PEM, SSH key) keeps its final line break; a value that is not UTF-8 text is refused (use `put-file`) |
| `maxxing keys delete NAME` | remove a key |
| `maxxing keys put-file NAME PATH [--note TEXT] [--no-expose]` | store a secret **file** (keystore, service-account JSON, certificate; 1 byte to 1 MiB) read from `PATH`, or from stdin with `-`. A new file is exposed (the environment variable `NAME` holds its path in sessions and shell jobs) unless `--no-expose`; never in the backup |
| `maxxing keys get-file NAME [--output PATH] [--force]` | write the file to stdout, or to `PATH` (mode 600; refuses an existing path unless `--force`) |
| `maxxing keys delete-file NAME` | remove a secret file |
| `maxxing infra status` / `infra list [--kind K] [--json]` | the Infra inventory: sources, problems, every site / database / bucket / domain / server (last snapshot) |
| `maxxing infra refresh` | read everything now (this server, other servers over SSH, Cloudflare, Hostinger, URL checks) |
| `maxxing infra mail [--refresh] [--json]` | e-mail, view only: mailboxes of the E-mail page, Cloudflare Email Routing forwards, Hostinger e-mail, DNS health (MX, SPF, DKIM, DMARC) of the mail domains with what to fix |
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
| `maxxing mcp load NAME [--session ID]` | in a session (setting *Load MCP servers only when a session needs them*): load that server from the next turn on; Harness continues the turn by itself |

OAuth sign-ins (state "To connect") are done in Settings -> MCP -> **Connect**. See [MCP servers](28-mcp.md).

## Agents

| Command | Purpose |
|---|---|
| `maxxing agents list [--json]` | every agent: path, name, on/off, triggers, cost of the day |
| `maxxing agents run AGENT [TASK] [--data] [--json]` | start it now (a new session); `--data`: the text is outside data, not a task; exit 1 when a limit refused it |
| `maxxing agents send AGENT TEXT [--json]` | from an agent's session: hand work to another agent (the text is given as data; 3 hops at most) |
| `maxxing agents on AGENT` / `off AGENT` | switch it on / off |
| `maxxing agents silent AGENT` / `loud AGENT` | it works without notifying you (no Telegram, notifications already read, nothing unread) / back to normal |
| `maxxing agents templates [--lang L] [--json]` | the ready-made agents (id, name, trigger) |
| `maxxing agents create P/T/A --role TEXT\|--role-file F\|--template ID [--lang L] [--name N] [--model M] [--permission M] [--approvals] [--keys A,B] [--trust-outside] [--telegram] [--usd-per-day N] [--runs-per-hour N] [--domains H,H] [--writable D,D] [--mail ADDRESS] [--no-sandbox] [--off] [--json]` | create an agent in a topic (sandboxed unless `--no-sandbox`; `--template`: a ready-made agent, the other options override it; `--mail`: a mailbox for the agent - the one an e-mail template needs, or for a role-only agent read + drafts with the `maxxing mail` tool allowed) |
| `maxxing agents show AGENT` | its settings, role, triggers, schedule jobs and webhook URLs (JSON, no secret) |
| `maxxing agents cron AGENT --schedule CRON [--prompt T] [--name N] [--json]` | add a schedule (a Claude job in the agent folder) |
| `maxxing agents webhook AGENT [--kind generic\|stripe\|shopify\|github] [--prompt T] [--levels L] [--match W] [--json]` | add a webhook and print its URL |
| `maxxing agents watch AGENT --source S [--levels L] [--match W] [--prompt T] [--json]` | start it on new feed events of a source |
| `maxxing agents after AGENT OTHER [--on ok\|error\|any] [--match W] [--prompt T] [--json]` | start AGENT on the result of each automatic run of OTHER |
| `maxxing agents export AGENT [-o FILE]` | the agent as a Claude Code agent file (`.claude/agents/<name>.md`) |
| `maxxing agents import FILE --topic P/T [--name N]` | create an agent from a Claude Code agent file |
| `maxxing agents sandbox-setup` | install what the agents' sandbox needs (root): `bubblewrap`, `socat`, the AppArmor profile |
| `maxxing agents group list [--json]` | the agent groups: path, name, members |
| `maxxing agents group show P/G [--messages N]` | a group: members, goal, options, last messages (JSON) |
| `maxxing agents group create P/G --member AGENT[=ROLE] ... [--name N] [--emoji E] [--goal T] [--lead AGENT] [--no-shared-files] [--ask-on-handover] [--json]` | create a group of 2 to 6 agents of project P |
| `maxxing agents group update P/G [--name N] [--emoji E] [--goal T] [--lead AGENT] [--member AGENT[=ROLE] ...] [--shared-files on\|off] [--trust-members on\|off]` | change a group (`--member` replaces the members) |
| `maxxing agents group say P/G TEXT` | write to a group as yourself; its members answer in turn (refused in an agent's run) |

`AGENT` = `project/topic/agent` (or `projects/P/topics/T/agents/A`, or the agent's name when it is unique). See
[Agents](30-agents.md) and [Agent groups](31-agent-groups.md).

## Themes

Settings -> Appearance -> [Theme](39-themes.md): a theme is a `theme.json` of values (no code; at most one field of advanced CSS), made or
installed by Harness (skill `maxxing-theme`).

| Command | Purpose |
|---|---|
| `maxxing themes list [--json]` | installed themes, and folders that are not usable with the reason |
| `maxxing themes check FOLDER [--json]` | read a theme like the interface will: what it sets, what is dropped and why (nothing installed) |
| `maxxing themes install FOLDER [--force]` | check it, then copy it into `<workspace>/themes/<id>/` (`--force` replaces it); refused in an agent's run |
| `maxxing themes verify ID` | its advanced CSS was checked with this version of the interface: switch it back on (an update that changes the interface's CSS switches it off); refused in an agent's run |
| `maxxing themes remove ID` | delete an installed theme (browsers using it go back to its base); refused in an agent's run |
| `maxxing themes tokens [--json]` | the variables a theme may set and their kind |

## Webhooks and events

Settings -> Automate -> [Webhooks](37-webhooks.md) and [Events](38-events.md): automations without AI (one trigger,
one action). Harness creates them from a session; the definition is JSON (see the skill `maxxing-webhooks`).

| Command | Purpose |
|---|---|
| `maxxing webhooks list [--json]` | every webhook and event: id, on/off, sentence, last call (`[needs its signing secret]` when a Stripe / Shopify / GitHub one has none) |
| `maxxing webhooks show ID [--json] [--sign-secret]` | one of them, with its URL; `--sign-secret` prints the key that signs its calls (`X-Harness-Signature`) |
| `maxxing webhooks add [--spec JSON]` | create one from its JSON definition (`--spec`, or JSON on stdin); prints its id and URL |
| `maxxing webhooks edit ID [--spec JSON]` | change it: the top-level keys given (`name`, `description`, `trigger`, `action`, `queue`, `report`, `enabled`) are replaced |
| `maxxing webhooks describe ID "SENTENCE"` | the sentence shown on the page |
| `maxxing webhooks on ID` / `off ID` / `remove ID` | switch on / off, delete (its calls and data too) |
| `maxxing webhooks url ID` / `rotate ID` | print its URL / give it a new one (the old one stops at once) |
| `maxxing webhooks secret ID` | set its signing secret or phone key, read on stdin (`printf %s "$S" \| maxxing webhooks secret ID`); empty input removes it |
| `maxxing webhooks test ID` | run it now on a realistic sample of its service or event (filters skipped), here, and print the result |
| `maxxing webhooks calls ID [--limit N] [--json]` | its last calls (50 kept): time, status, summary, duration, error |
| `maxxing webhooks call ID CALL` | one call: what was received (headers without secrets, body up to 64 kB) and the result (JSON) |
| `maxxing webhooks replay ID CALL` | run a call again with the same request, here |
| `maxxing webhooks data ID [--last N] [--csv] [--json]` | the rows of a webhook that stores its data (`--csv`: every row, for a spreadsheet) |

`ID` = the id shown by `list` (`w_…`). Exit 1 on an error or a failed test / replay. In an agent's run, only `list`,
`show`, `url`, `calls`, `call` and `data` work.

## E-mail

| Command | Purpose |
|---|---|
| `maxxing mail accounts [--json]` | the mailboxes of the E-mail page |
| `maxxing mail folders [-a ACCOUNT]` | folders with unread / total counts |
| `maxxing mail list [-a A] [-f FOLDER] [--unread] [--flagged] [-s TEXT] [-n 20] [--page N]` | messages, newest first |
| `maxxing mail read UID [-a A] [-f FOLDER] [--keep-unread]` | one message (its body is framed as data, not instructions) |
| `maxxing mail archive\|trash\|junk\|inbox\|seen\|unseen\|flag\|unflag UID...` | sort messages |
| `maxxing mail move UID... --to FOLDER` / `mkdir NAME [--parent F]` | move / create a folder |
| `maxxing mail attachment UID INDEX OUT [--force]` | save an attachment: into a folder under its name (`name (2).pdf` when taken), or as the file OUT (replaced only with `--force`) |
| `maxxing mail write [--to A,B] [--cc ..] [--bcc ..] [-s SUBJECT] [--reply UID\|--reply-all UID\|--forward UID] [--attach FILE]... [--send] < body.txt` | write a message: saved as a **draft** for you to check and send, or sent with `--send` |
| `maxxing mail refresh [-a A]` | check the mailboxes now (new mail starts the agents watching them; from an agent's run: asks the server for a check) |
| `maxxing mail outbox [-a A]` | messages written by agents waiting for your OK (an agent sees its own) |
| `printf %s "$PW" \| maxxing mail add ADDRESS [--imap HOST[:PORT]] [--smtp HOST[:PORT]]` | add a mailbox (password on stdin) |

`ACCOUNT` = id or address (default: the first mailbox). See [E-mail](32-mail.md).

## Harness Browser

| Command | Purpose |
|---|---|
| `maxxing browser enable` / `disable` | switch the feature on or off (as Settings -> Features); `enable` installs what is missing first (root) |
| `maxxing browser setup [--exits]` | install what it needs on this server (root): `socat`, Chromium, its user, its AppArmor profile, the browser tools; `--exits`: also Tailscale and wireproxy (exits by a phone or a box) |
| `maxxing browser status [--json]` | feature on or off, what is missing, the settings, the profiles and their exit, the exits, requests waiting for you |
| `maxxing browser settings [--ask \| --no-ask] [--wait MIN] [--downloads \| --no-downloads] [--idle MIN] [--tab-sleep MIN] [--max-tabs N] [--max-profiles N]` | the settings shared by every profile: ask you when stuck, how long it waits for you, downloads, a profile / a tab sleeps after, tabs awake per profile, profiles running at once |
| `maxxing browser profile add NAME [--exit ID] [--fallback-vps]` | a new profile (its id is made from the name); `--exit`: an exit id or `direct`; `--fallback-vps`: when its exit is down, go out by the server's address instead of waiting |
| `maxxing browser profile set ID [--name N] [--exit ID] [--fallback-vps \| --wait-exit]` | change a profile |
| `maxxing browser profile rm ID` | delete a profile and its sign-ins (`main` cannot be deleted; an agent that had it has no browser any more) |
| `maxxing browser exit test ID\|direct` | what the sites see through an exit (`direct` = the server): address, country, operator, kind, delay, speed; exit code 1 when it fails |
| `maxxing browser set PATH on\|off\|inherit [--profile ID\|inherit]` | let a project (`acme`), a topic (`acme/blog`) or an agent (`acme/blog/writer`) use it, or not (`inherit` = its parent's switch, not for an agent); sessions use their project's profile (made the first time); `--profile` (an agent only): another profile, `inherit` = its project's again |
| `maxxing browser show PATH [--json]` | what it gets (on or off, its profile) and where each is inherited from |
| `maxxing browser forget ID` | erase a profile's sign-ins, tabs and journal |

`PATH` = `<project>`, `<project>/<topic>`, `<project>/<topic>/<agent>` or the full folder. `on`, `off`, `use`,
`profile`, `forget`, `setup` and `settings` are refused in an agent's runs. Exits are added in Settings -> Browser
(their passwords go to Settings -> Keys).

See [Harness Browser](33-browser.md).

## Devices

| Command | Purpose |
|---|---|
| `maxxing devices enable` / `disable` | switch the feature on or off (as Settings -> Features) |
| `maxxing devices list [--json]` | the devices (online or not, mode, who may use them), the codes not used yet, the devices waiting for your OK |
| `maxxing devices add [--os windows\|darwin\|linux\|android]` | a one-time code to connect a device (15 minutes), with the command to paste on it or the link for a phone |
| `maxxing devices confirm ID [--refuse]` | accept a device waiting for your OK, or refuse it (it is disconnected and forgets this server) |
| `maxxing devices remove ID` | remove a device: Claude can no longer use it, Harness Link there forgets this server |
| `maxxing devices rename ID NAME` | rename a device |
| `maxxing devices mode ID view\|control` | View only (Claude looks) or Control (Claude clicks and types) |
| `maxxing devices screen ID N\|main` | a computer with several screens: the one Claude sees and uses (and Watch shows); `list` shows their numbers, `*` = the one used |
| `maxxing devices access ID [--all] [--project NAME]... [--agent PATH]...` | who may use it: every project and agent, some projects, some agents (`projects/<p>/topics/<t>/agents/<a>`); none of them = nobody |

`ID` = the device's id (`dev_…`) or its name. An agent also needs the device in its own settings. See [Devices](34-devices.md).

## Memory and sessions

| Command | Purpose |
|---|---|
| `maxxing memory [--json]` | every memory.md with its line count and the line limit (Settings -> Memory) |
| `maxxing sessions send SESSION MESSAGE... [--file PATH] [--json]` | write to a session as if typed in it (SESSION: its id, its first 8 characters or its title - case and accents ignored, a unique beginning is enough; `--file` repeatable). Run by Claude from a session, the message says which session sent it; 3 sends in a row between sessions or agents at most. Refused in a sandboxed agent |
| `maxxing sessions new TOPIC [MESSAGE...] [--title T] [--model M] [--effort E] [--file PATH] [--fresh REASON] [--json]` | start a session in a topic (TOPIC: `<project>/<topic>` or `projects/<project>/topics/<topic>`) with a first message; no `--title`: made from the message. Run by Claude from a session or an agent, the message says which session started it, with the same limit of 3 sends in a row. From Jarvis's conversation it is refused (exit 3, with their list, closest to the subject first) while the topic has sessions that can take the work: `sessions send` to one of them, or `--fresh "<reason>"` for another subject (the reason shows on its work board card). An agent is started with `maxxing agents run` instead. Refused in a sandboxed agent |
| `maxxing sessions list [--json]` | the sessions that are not archived: id, state, topic, title |
| `maxxing sessions list --topic <project>/<topic> [--days N] [--json]` | a topic's sessions of the last 30 days (or N) with what Jarvis needs to continue one: start of the last answer, who started it, `reusable` or why not |
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
| `maxxing telegram status [--json]` | bot, chat, mode, threads, settings, last error |
| `maxxing telegram mode [simple\|threads\|mirror]` | show or change the mode (to `simple`: the session threads and Crons / Alerts / Notifications are deleted from Telegram) |
| `maxxing telegram test` | send a test message |
| `maxxing voice status [--json]` | voice messages: engine, model, readiness |
| `maxxing voice set [--engine] [--model] [--language]` | change the voice settings |
| `maxxing voice download [model]` | download a local speech model |
| `maxxing voice transcribe <file>` | transcribe an audio file with the configured engine |

## Installer

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | bash   # install / repair (from the public git repository, no key)
bash /opt/claude-maxxing/install.sh --update                # = maxxing update
bash /opt/claude-maxxing/install.sh --uninstall [--purge] [--purge-workspace]
bash /opt/claude-maxxing/install.sh --tools                 # (re)install Node.js, Chromium, Remotion, Scrapling (= maxxing deps update)
SOURCE_DIR=/path/to/copy bash /path/to/copy/install.sh      # install a local copy of the code (no download)
bash /opt/claude-maxxing/install.sh --secure                # security updates, fail2ban, firewall (FIREWALL=0: no firewall)
curl --proto '=https' --tlsv1.2 -fsSL https://get.harness-maxxing.com | bash -s -- --check   # look at the server first, change nothing
```
Variables: see [Installation](installation).

## Environment variables

| Variable | Use |
|---|---|
| `MAXXING_STATE` | state directory (default `/var/lib/claude-maxxing`); set by the service and the CLI wrapper |
| `MAXXING_GITHUB_TOKEN` | token for `maxxing backup restore --from` |
| `NO_COLOR` | plain output |
