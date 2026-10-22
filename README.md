# Harness Maxxing

[![License: Fair Source](https://img.shields.io/badge/license-Fair%20Source-blue)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/makushingu/harness-maxxing?style=social)](https://github.com/makushingu/harness-maxxing/stargazers)
[![X (Twitter)](https://img.shields.io/badge/X-@HarnessMaxxing-black?logo=x)](https://x.com/HarnessMaxxing)

**A self-hosted control room for Claude Code.** Many persistent Claude conversations organised by
project and topic, plus files, tasks, scheduled jobs, a Telegram bridge and a memory backup -
installed on your own server with one command and configured from a guided web onboarding.

Free and [fair source](#fair-source) (source-available). Install: `curl -fsSL https://get.harness-maxxing.com | bash` as root - no key,
no account. Details in [Install](#install) below. News: [@HarnessMaxxing](https://x.com/HarnessMaxxing) on X.

## Screenshots

_Coming soon: dashboard, sessions (desktop and mobile), files, tasks, crons, onboarding._

## Features

- **Sessions** - project -> topic -> any number of persistent sessions. Columns side by side, live
  streaming, tool calls as cards, diffs, attachments (drag & drop, paste), message queue (steer, edit,
  side questions that do not interrupt), plan mode, HUD mode, stop, model per session (showing the model
  that really answered), cost and context gauge, compact and hand-off, archive, move to another topic,
  full-text search, command palette, keyboard shortcuts. Sessions list in three layouts with favorites,
  recent sessions and an emoji per project.
- **Memory that organises itself** - `CLAUDE.md` + `memory.md` at workspace, project and topic
  level, loaded automatically; shipped skills keep it up to date and compact.
- **Files** - browse, edit with conflict detection, upload, trash; one viewer for every file and folder
  (pictures, video with a quality choice, audio, PDF, markdown, CSV tables, HTML pages in a sandbox, archives, fonts, code) with
  ← / → through a conversation's or a folder's files.
- **Starter projects** - ready-made projects for your kind of work (online store, affiliate site, content
  creator, apps, second brain, freelance): topics that already know the job and ask you a few questions.
- **Notifications feed** - one place for what happens: cron runs, Stripe sales, Shopify orders, GitHub runs,
  any webhook or script (`maxxing feed post`); dashboard panel, optional Telegram thread posted by the bot,
  per-source rules, "Ask Harness" about an event.
- **Infra** (optional) - every site, database, bucket, domain and server: this server, your other servers (SSH,
  a Hostinger VPS connects in one click),
  Cloudflare, Hostinger; statuses, certificate and domain expiry, links domain -> server -> site -> app -> repository;
  standard recipes to put a site online, create a PostgreSQL database or an S3 bucket (`maxxing infra`).
- **Tasks** - kanban and list on a plain `tasks.json` that Claude can edit too.
- **Crons** - shell commands or Harness prompts on a schedule, run history, Telegram reports.
- **Telegram** - built-in gateway: one thread per open session, the same sessions as the web UI, photos
  and files, voice notes, sign-in alerts.
- **Voice messages** - mic button in every session and Telegram voice notes, transcribed on your
  server (Whisper, private and free) or by Groq / OpenAI.
- **Memory backup** - daily push to a private GitHub repository, whitelist, secret scanner,
  one-click restore, used by the installer to move to a new server.
- **Dashboard & extensions** - built-in widgets, your own widgets as JSON cards and full pages,
  stored in your workspace so updates never touch them.
- **Claude can run the product** - skills to set it up, diagnose it, configure Telegram and
  backups, create jobs, manage tasks and write extensions.
- **Claude Code stays current** - the server updates the CLI by itself, only while nothing runs.
- **Ready for real work** - Node.js + Remotion (motion design videos), HTML -> PDF, ImageMagick,
  Scrapling (web scraping, JavaScript pages included), and skills for videos, PDFs, images, SEO
  audits and scraping, installed with the product.
- **Import from another agent** - a prompt for Hermes, Claude Code or OpenClaw, a zip, a preview:
  projects, topics, memory and skills arrive without overwriting anything. A trash with restore.
- **A workspace that explains and maintains itself** - default `system` project (help from the
  installed docs, guided updates with workspace upgrade notes, server administration, tasks,
  subscriptions inventory, extensions), an interactive 4-lesson `tutorial`, and a weekly update check
  on Telegram.
- **Secure by default** - one-time setup link, scrypt password, strict cookies, CSRF header,
  login throttling, HTTPS via Caddy or Tailscale, never bound to a public interface; the server is
  hardened at install (firewall with only SSH / 80 / 443 open, fail2ban, automatic security updates).
- English and French interface, dark and light themes, mobile friendly.

## Requirements

- A VPS with **Ubuntu 24.04** (tested: Ubuntu 22.04, 24.04, 26.04 and Debian 12: apt + systemd), x86_64 or arm64,
  root access. **2 vCPU, 4 GB RAM, 40 GB disk** recommended.
- A Claude subscription (Pro or Max, connected with `claude setup-token`) or an Anthropic API key.
- For HTTPS: a subdomain pointing to the server, DNS only (or use Tailscale / an SSH tunnel).
- Optional: a Telegram bot (BotFather, Threaded Mode on), a Groq key for faster voice.
- A server dedicated to Claude is recommended: sessions run Claude Code with full permissions by
  default (configurable).

## Install

As root on the server (`sudo -i` first if you are logged in as another user):

```bash
curl -fsSL https://get.harness-maxxing.com | bash
```

It asks three questions (access mode, domain, restore a backup), clones this public repository (no key, no token),
then installs packages, uv, Claude Code, the code, HTTPS with Caddy,
the server security (firewall, fail2ban, security updates) and the service in about a minute; the tools (Node.js,
Remotion, Scrapling and their shared Chromium) finish in the background. Every third-party download is a pinned
version checked against its checksum (`server/maxxing/deps.toml`, managed with `maxxing deps`). It ends with a
**one-time setup link**: open it, choose your password and follow the onboarding (language, Claude
connection, import from another agent, first project, Telegram, backup).

Unattended: `curl -fsSL https://get.harness-maxxing.com | ACCESS=domain DOMAIN=ui.example.com ASSUME_YES=1 bash`.
Updates come from this repository (`maxxing update`, or the Update button in Settings).

Other ways to install:

```bash
curl -fsSL https://get.harness-maxxing.com | REPO=you/your-fork BRANCH=main bash   # from your fork (updates from it)
bash /path/to/harness-maxxing/install.sh       # from a local copy (a clone with web/dist): no download, updates = a newer copy
```

No key and no account. Companies that need an Enterprise license give their key afterwards in Settings → License
(optional): see [docs/user/23-license.md](docs/user/23-license.md). Servers installed with a key before 2.0.0a87
switch to the public git repository by themselves.

An anonymous counter (once a day: a random id, the version, the system and a few health codes; no name, no IP, no
content) is on by default; turn it off in Settings → Profile, or with `MAXXING_NO_TELEMETRY=1` (or `DO_NOT_TRACK=1`)
in the service environment - see [docs/user/23-license.md](docs/user/23-license.md#saying-hello-optional).

Day-to-day: `maxxing status`, `maxxing doctor`, `maxxing update`. Remove: `maxxing uninstall`.

## Documentation

User documentation is in [`docs/user/`](docs/user) and inside the app (Settings -> Docs):
[welcome](docs/user/01-welcome.md) · [installation](docs/user/02-installation.md) ·
[onboarding](docs/user/03-onboarding.md) · [sessions](docs/user/04-sessions.md) ·
[memory](docs/user/05-memory.md) · [crons](docs/user/08-crons.md) ·
[telegram](docs/user/09-telegram.md) · [backup](docs/user/10-backup.md) ·
[widgets](docs/user/12-dashboard-widgets.md) · [pages](docs/user/13-page-extensions.md) ·
[security](docs/user/15-security.md) · [troubleshooting](docs/user/16-troubleshooting.md) ·
[CLI](docs/user/17-cli-reference.md) · [files](docs/user/06-files.md) ·
[settings](docs/user/11-settings-and-keys.md) · [customizing](docs/user/20-customizing.md) ·
[import](docs/user/21-import.md) · [tools](docs/user/22-tools.md) · [license](docs/user/23-license.md) · [notifications](docs/user/24-feed.md) · [starter projects](docs/user/25-starter-projects.md).

Developers: [`docs/dev/PLAN.md`](docs/dev/PLAN.md) (architecture), [`docs/dev/API.md`](docs/dev/API.md)
(HTTP contract), [`docs/dev/INTERNALS.md`](docs/dev/INTERNALS.md).

```bash
cd server && uv sync && uv run pytest        # server
cd web && npm ci && npm run build            # web UI (web/dist is committed)
```

## Fair Source

Harness Maxxing is published under the [Harness Maxxing Fair Source License](LICENSE), a source-available license
(not an OSI open source license): the code is public and free, with a few limits that keep the project sustainable.

**Allowed, free of charge**
- use it, for any personal or professional purpose of your own;
- read, copy, modify and fork the code;
- redistribute it, changed or not, with the `LICENSE` and the copyright notice (and saying what you changed);
- an organisation may use it for the internal needs of **one legal entity**.

**Not allowed without the owners' prior written consent**
- selling, reselling, renting or licensing it, or a fork of it;
- including it in a paid product, offer or service (paid installation, setup or support built on it included);
- running it as a paid hosted or managed service;
- using the "Harness Maxxing" name or logo for a fork, a product or a service (saying truthfully that your work is
  based on Harness Maxxing is fine);
- using it for an organisation's affiliates, subsidiaries, clients or other third parties.

| | Harness Maxxing (Fair Source) | MIT ([Hermes Agent](https://github.com/NousResearch/hermes-agent), [OpenClaw](https://github.com/openclaw/openclaw)) |
|---|---|---|
| Free to use, source public | yes | yes |
| Modify, fork, redistribute | yes, with the license and notice | yes, with the notice |
| Organisations | one legal entity | unlimited |
| Sell it, paid offer, paid hosting | only with written consent | yes |
| Use the project's name and logo | only with written consent | not granted by MIT |
| Contributions | under the [CLA](CLA.md) | under MIT (inbound = outbound) |

## Contributing

Bug reports, ideas and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first (open an issue
before a feature, tests, changelog, `web/dist`), sign the [Contributor License Agreement](CLA.md) (one comment on
your first pull request) and follow the [Code of Conduct](CODE_OF_CONDUCT.md). Security issues: see
[SECURITY.md](SECURITY.md), never a public issue.

## Support the project

Harness Maxxing is free; donations fund its development: [harness-maxxing.com/donation](https://harness-maxxing.com/donation).

## Enterprise

Several entities, clients, a paid offer or hosting, the name or a custom deal: ask for a commercial license at
[harness-maxxing.com/#enterprise](https://harness-maxxing.com/#enterprise).

## License

[Harness Maxxing Fair Source License 1.0](LICENSE).
Copyright (c) 2026 Harness Maxxing - FEU and RomainPlus.

Third-party code and fonts shipped or installed with Harness Maxxing keep their own licenses (MIT, BSD, Apache,
ISC, SIL Open Font License...): see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Harness Maxxing runs the official Claude Code CLI with your own Anthropic account or API key; it
does not ship, proxy or share credentials. "Claude" is a trademark of Anthropic; this project is
not affiliated with Anthropic.
