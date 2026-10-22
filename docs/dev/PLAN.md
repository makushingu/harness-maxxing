# Harness Maxxing v2 — product & engineering plan

Status: living document. Owner: product (Romain). Implementation: this repository.

## 1. Product

**One sentence:** a self-hosted control room for Claude Code on your own server — many persistent
Claude conversations organised by project and topic, plus files, tasks, scheduled jobs, a Telegram
bridge and a memory backup, installed with one command and configured from a guided web onboarding.

**Target buyer:** a power user / freelancer / small team who runs Claude Code on a VPS and wants to
drive it from a browser and a phone, with structure (projects, topics, memory) instead of a single
terminal.

**Promise:**
1. `curl … | bash` on a fresh Ubuntu/Debian VPS → a working HTTPS UI in minutes.
2. Every setting is reachable from the UI (no file editing needed), every step is guided.
3. Nothing breaks visually: one design system, real components, no stale caches, no layout jumps.
4. Claude itself can set up, diagnose and extend the product (shipped Claude Code skills).

### 1.1 Feature scope (parity with v1 + improvements)

| Area | v1 | v2 |
|---|---|---|
| Sessions | project → topic → N persistent sessions, columns, model per session, stop/queue, archive, handoff/compact, search, Ctrl+K, notify | same, plus: streaming via SSE (no polling glitches), attachments (drag & drop, paste images), message queue (several messages), tool calls rendered as collapsible cards, diff viewer, real model + cost + context gauge, Telegram sessions are **the same sessions** (continuity web ↔ phone), keyboard-first |
| Workspace | folders + CLAUDE.md/memory.md created by API | same model, managed from the UI (create/rename/archive project & topic, edit memory inline) |
| Files | browser, viewer, markdown editor | browser with breadcrumbs, previews (image/video/audio/pdf/markdown/code), CodeMirror editor with conflict detection, upload by drag & drop, rename/move/delete (to trash), download |
| Tasks | read-only kanban + map from tasks.json | full CRUD kanban + list, projects/labels, due dates, link to topic; still a plain JSON file Claude can edit |
| Crons | crontab view + cron-wrap + cron-session | crons **managed from the UI**: shell command or Claude prompt in a topic, humanised schedule editor, run now, history, status, Telegram report |
| Dashboard | widgets (python + js) | built-in widgets (activity, tasks today, crons, server, backup, Telegram, Claude usage) + extension widgets declared as JSON cards (consistent design) or custom JS |
| Extensions | modules/ and widgets/ in the code repo | `workspace/extensions/<id>/` (outside the code: updates never erase them): widget cards, full pages, API routes; documented, with a Claude skill that writes them |
| Settings | hub | General (theme, accent, language EN/FR, time zone), Security (password, sessions), Claude (auth, default model, permission mode), Telegram (wizard), Backup (wizard), Keys (secret vault, optionally exposed to sessions as env vars), Extensions, System (services, logs, update), Docs |
| Telegram | separate third-party bot + UI notifications | built-in gateway: bot token wizard, chat linking with a one-time code, one thread per open session kept in sync (archive = thread deleted, deleted thread = archived, new session from the main chat with a topic picker), commands (/new /stop /model /sessions /status), photos/documents saved as attachments, cron reports thread, sign-in alerts |
| Memory backup | custom script + R2 + private GitHub repo | built-in: GitHub private repo (created for you if the token allows), whitelist, secret scanner, daily job, one-click restore (also offered by the installer on a new server) |
| Health | header pill | header pill + System page: disk, RAM, CPU, services, failed crons, failed sign-ins, Claude auth, backup age |
| Presentation mode | DOM masking | `<Sensitive>` component: data rendered masked at source, never in the DOM while active |
| Docs | markdown in repo | in-app docs (EN), searchable, including "write an extension" guides |
| Install | install.sh (v1.5) | one-liner + `maxxing` CLI (`doctor`, `update`, `backup`, `password`, `setup-link`…) + guided web onboarding + Claude skills |
| Tools & skills | - | installed with the product: zip, jq, ripgrep, ImageMagick, poppler, Node.js 22 + Remotion (shared, `maxxing video new`), HTML -> PDF (`maxxing pdf`); skills video-motion-design, pdf-document, image-edit, seo-audit |
| Import & trash | - | import from another agent (prompt -> zip -> preview -> merge without overwriting -> Claude finishes); trash with restore for files, topics, projects and sessions |

### 1.2 Non-goals for 2.0
Multi-user accounts and roles, Windows/macOS servers, Docker image (2.1 candidate), mobile native app.
(Voice messages were moved into 2.0: speech-to-text on the server - local Whisper, Groq or OpenAI.)

## 2. Distribution prerequisites
1. **License:** fair source (`LICENSE`, Harness Maxxing Fair Source License 1.0): free use, modification, forks and
   redistribution; one legal entity per organisation; selling, paid offers, paid hosting and the name / logo need
   the owners' written consent. Contributions under `CLA.md`.
2. **Distribution:** the default install clones the public git repository (no key, no token) and updates from it.
   Installs made with a license key before 2.0.0a87 got signed release tarballs; their old code still downloads
   the newest one, and once it runs this code they move to the public repository by themselves
   (`license.move_to_git`). The code to download, verify and import tarballs is gone since 2.0.0a93.
3. **Anthropic terms:** the buyer runs the official Claude Code CLI with *their own* account or API
   key on *their own* server; the product never ships, proxies or shares credentials. Verify the
   current Anthropic commercial / consumer terms for third-party tools built on Claude Code before
   launch. The product supports API-key authentication (`ANTHROPIC_API_KEY`) as well as OAuth tokens.
   The "Claude usage" widget relies on an undocumented endpoint → flagged *experimental*, off by default.
4. **Security posture:** sessions run Claude with full permissions on the server (bypass mode, root).
   It is a deliberate, documented choice ("this VPS is dedicated to Claude"), shown in onboarding;
   a stricter permission mode is selectable.
5. **Support & updates:** `maxxing update` (git pull + deps + restart), changelog, semantic versions.

## 3. Architecture

```
Browser (React SPA)  ──HTTPS──>  Caddy (optional)  ──>  maxxing server (FastAPI, 127.0.0.1:8787)
                                                          │  config/state: /var/lib/claude-maxxing
                                                          │  workspace:    /root/maxxing (CLAUDE.md, projects/…)
                                                          ├─ sessions: one transient systemd unit per turn
                                                          │     python -m maxxing.runner <sid>  →  claude -p --output-format stream-json
                                                          ├─ telegram gateway (asyncio task, long polling)
                                                          ├─ scheduler bridge: managed block in root crontab → `maxxing cron run <id>`
                                                          └─ backup: git working copy → private GitHub repo
```

### 3.1 Choices and why
- **Python 3.11+ / FastAPI / uvicorn**, installed in a venv by **uv** (single static binary, can fetch
  Python itself) → reliable install on any recent Ubuntu/Debian. Few dependencies: fastapi, uvicorn,
  httpx, python-multipart.
- **Turn runner in a transient systemd unit** (kept from v1, proven): a turn survives browser close
  and server restarts. The runner is stdlib-only and writes an NDJSON log; the server only reads it.
- **Real-time = SSE** (server tails the log file) instead of polling → no flicker, instant output.
  A global SSE bus pushes invalidations (sessions/tasks/crons/health) to the UI.
- **Frontend = React 19 + TypeScript + Vite + Tailwind v4**, Radix primitives, lucide icons,
  TanStack Query (cache, no double loads), Zustand for UI state, cmdk palette, CodeMirror 6,
  react-markdown. **Built `web/dist` is committed** → the server needs no Node. Hashed asset names are
  cached forever, `index.html` is `no-store` → no stale UI behind a CDN (v1 Cloudflare issue solved by design).
- **Normalised session events**: the server converts Claude's stream-json into a small, stable event
  vocabulary (see API.md); the UI never parses CLI internals. Normalisation runs at read time, so
  improvements apply to old sessions too.
- **Extensions live in the workspace**, never in the code directory → updates never touch them.
- **State files are JSON**, written atomically (tmp + rename). No database: easy backup, easy for
  Claude to read, no migration pain. (Sessions index is rebuilt from files.)

### 3.2 Paths (all configurable at install)
| What | Default |
|---|---|
| Code (git clone) + venv | `/opt/claude-maxxing` (+ `.venv`) |
| State | `/var/lib/claude-maxxing/` : `config.json`, `secrets.json` (600), `sessions/`, `crons/`, `telegram/`, `backup/`, `trash/`, `logs/` |
| Workspace | `/root/maxxing/` : `CLAUDE.md`, `memory.md`, `projects/<p>/topics/<t>/`, `tasks.json`, `extensions/` |
| CLI | `/usr/local/bin/maxxing` → venv entry point |
| Service | `claude-maxxing.service` ; turn units `maxxing-<sid8>` |
| Skills | `~/.claude/skills/maxxing-*` (user level → available in every session) |

### 3.3 Security
- First launch requires a **one-time setup token** printed by the installer (`/setup?token=…`):
  whoever reaches the URL first cannot claim the instance.
- Password hashed with scrypt; signed session cookie (HttpOnly, SameSite=Strict, Secure behind HTTPS);
  all mutating requests require the header `X-Maxxing: 1` (CSRF); login throttling with exponential delay.
- Server binds 127.0.0.1 (behind Caddy) or the Tailscale IP — never 0.0.0.0.
- `secrets.json` 600; secrets never returned in clear by the API except on explicit "reveal".
- Files API confined to `files_root`; Telegram accepts only the linked chat / user ids.
- Backup: refuses to push if the repo is public; secret scanner on content formats before commit.

## 4. Repository layout
```
install.sh                 one-line installer (bootstrap)
server/                    Python package `maxxing` (pyproject, uv)
  maxxing/
    __main__.py  cli.py    `maxxing` CLI (serve, init, doctor, update, cron, backup, password, setup-link…)
    config.py              paths, config.json / secrets.json, atomic writes
    security.py            password hash, cookies, throttle, CSRF dependency
    app.py                 FastAPI factory, static SPA, router registry
    bus.py                 global SSE invalidation bus
    api/                   one router per domain: auth, onboarding, claude, workspace, sessions, files,
                           tasks, crons, telegram, backup, settings, secrets, system, docs, extensions, dashboard
    sessions/              store.py, normalize.py, runner.py (stdlib only), spawn.py
    telegram/              gateway.py, client.py, format.py
    crons.py backup.py health.py extensions.py
  tests/                   pytest (+ fake `claude` binary emitting stream-json)
web/                       React app (src/), committed build in web/dist
skills/                    Claude Code skills, installed to ~/.claude/skills/
templates/workspace/       CLAUDE.md, memory.md… copied on init
docs/user/                 in-app documentation (markdown)
docs/dev/                  PLAN.md (this file), API.md (contract), DESIGN.md (UI rules)
examples/extensions/       sample widget + sample page
```

## 5. UX blueprint
- **App shell:** left sidebar (collapsible; icons only in a narrow window; touch layout on phones and tablets: ☰ sessions / ⊞ app drawers): Dashboard,
  Sessions, Files, Tasks, Crons, Settings; search/⌘K button; health dot; presentation toggle; user menu.
- **Sessions:** left pane = project/topic tree with live badges (running, unread); main = 1..N columns
  (resizable, reorderable, detachable to a window); composer with attachments, model picker showing the
  model that actually answered, queue indicator, stop. Tool calls as compact cards (expand for input/output),
  file paths clickable (preview drawer), images inline, diffs rendered.
- **Onboarding wizard** (first login): 1 Password → 2 Claude connection (detects CLI auth; paste
  `claude setup-token` output or an API key; live test) → 3 First project & topic → 4 Telegram (optional) →
  5 GitHub memory backup (optional, can create the repo) → 6 Done (short tour). Resumable; every step also
  lives in Settings.
- **Design:** zinc neutrals, one accent colour (user-selectable), Inter, 4-px spacing scale, dark default,
  light theme, skeleton loaders (no layout jump), empty states with a call to action, toasts for results,
  confirmation dialogs for destructive actions, focus rings, keyboard shortcuts listed in a help dialog.
- **i18n:** English + French from day one (dictionary files), language picked in onboarding.

## 6. Delivery phases
| Phase | Content | Exit criteria |
|---|---|---|
| P0 Foundations | repo, PLAN/API/DESIGN, server skeleton (config, security, app, bus), web skeleton (design system, shell, API client, login/setup) | `maxxing serve` serves the SPA; login works |
| P1 Core | workspace, sessions (runner, normalise, SSE, queue, attachments, search), files | real Claude conversation from the UI, survives restart |
| P2 Organisation | tasks, crons (managed block + runner + history), dashboard + widgets, health, settings, secrets, docs, extensions | every v1 page has its v2 equivalent |
| P3 Connectivity | Telegram gateway + wizard, backup + restore, sign-in alerts | phone ↔ web continuity; backup round-trip |
| P4 Install & skills | install.sh, `maxxing doctor/update`, skills, workspace templates, docs | fresh Ubuntu 24.04 container → one-liner → onboarding → first conversation |
| P5 Quality | pytest, Playwright e2e on fake claude, visual pass desktop/mobile, a11y, perf budget | green tests, no console errors, Lighthouse ≥ 90 |

## 7. Testing strategy
- **Fake Claude** (`server/tests/fake_claude.py`): emits realistic stream-json (init, text, tool_use,
  tool_result, result) with configurable delays → sessions, Telegram replies and crons are testable
  without spending tokens.
- pytest: API contract per router, runner state machine (queue, stop, resume failure → new csid),
  crontab block sync, backup secret scanner, Telegram update handling (mocked HTTP).
- Playwright: onboarding, sessions (send, stream, stop, queue), files edit/save conflict, tasks CRUD,
  crons CRUD, mobile viewport.
- Install test: `systemd-nspawn` Ubuntu 24.04 container booted with systemd → run the one-liner.

## 8. Risks
| Risk | Mitigation |
|---|---|
| Claude CLI output format changes | normaliser isolated in one module + fake-claude fixtures from real logs |
| Telegram private-chat topics API changes | fallback to a forum supergroup (same code path: chat id + thread id) |
| Long turns killed by restarts | turns live in their own systemd units |
| Buyer exposes the port publicly | bind 127.0.0.1/Tailscale only; doctor warns if reachable |
| Secrets in backups | whitelist + format-based scanner + private-repo check |
